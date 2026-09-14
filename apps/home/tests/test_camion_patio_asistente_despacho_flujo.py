import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class CamionPatioAsistenteDespachoAlcanceTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(is_superuser=False)
        self.citacion = SimpleNamespace(CI_CTIPO=views.CIT_DESPACHO)
        self.traza = SimpleNamespace(
            CI_NID_id=38700,
            CI_NID=self.citacion,
            CPTR_CRESULTADO_BUSQUEDA='GUARDIA_MATCH',
        )
        self.camion = SimpleNamespace(
            EP_NID_id=views.ID_ACEITES_SBH,
            CI_NID_id=None,
            CPA_CTIPO_RECEPCION='',
            trazabilidad_planificacion=self.traza,
        )

    def test_asistente_despacho_puede_asociar_despacho_terramar_derivado(self):
        self.camion.EP_NID_id = views.ID_TERRAMAR
        with patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True):
            self.assertTrue(views._es_camion_despacho_patio(self.camion))
            self.assertTrue(views.usuario_puede_asociar_camion_patio(self.user, self.camion))

    def test_asistente_despacho_puede_asociar_recepcion_terramar(self):
        self.camion.EP_NID_id = views.ID_TERRAMAR
        self.citacion.CI_CTIPO = views.CIT_RECEPCION
        with patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True):
            self.assertFalse(views._es_camion_despacho_patio(self.camion))
            self.assertTrue(views.usuario_puede_asociar_camion_patio(self.user, self.camion))

    def test_asistente_despacho_puede_asociar_sbh_derivado(self):
        with patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True):
            self.assertTrue(views.usuario_puede_asociar_camion_patio(self.user, self.camion))

    def test_otro_perfil_no_puede_asociar_despacho_sbh(self):
        with patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=False):
            self.assertFalse(views.usuario_puede_asociar_camion_patio(self.user, self.camion))

    def test_camion_sbh_sin_derivacion_de_guardia_no_se_trata_como_despacho(self):
        self.camion.trazabilidad_planificacion = SimpleNamespace(
            CI_NID_id=None,
            CI_NID=None,
            CPTR_CRESULTADO_BUSQUEDA='RECEPCION_MANUAL',
        )
        self.assertFalse(views._es_camion_despacho_sbh_patio(self.camion))


class CamionPatioAsistenteDespachoNotificacionTests(SimpleTestCase):
    def setUp(self):
        self.usuario = SimpleNamespace(id=7)
        self.empresa = SimpleNamespace(id=views.ID_ACEITES_SBH)
        self.camion = SimpleNamespace(
            id=117,
            EP_NID_id=views.ID_ACEITES_SBH,
            EP_NID=self.empresa,
            CPA_CPATENTE='GBWG47',
            CPA_CNOMBRE_CONDUCTOR='SERGIO BELLO',
            CPA_CTRANSPORTISTA_DECLARADO='COMERCIAL BENITO LTDA',
            CPA_FFECHALLEGADA=views.timezone.now(),
            trazabilidad_planificacion=SimpleNamespace(CI_NID_id=38700, PL_NID_id=1266),
        )

    def test_notificacion_explica_la_accion_y_conserva_el_modal(self):
        duplicados = MagicMock()
        duplicados.exists.return_value = False
        with patch.object(views, '_usuarios_asistente_despacho_empresa', return_value=[self.usuario]), \
             patch.object(views.NOTIFICACION.objects, 'filter', return_value=duplicados), \
             patch.object(views, 'crear_notificacion_interna') as crear:
            cantidad = views.notificar_camion_patio_asistente_despacho(
                self.camion, SimpleNamespace(id=1), origen='Guardia'
            )
        self.assertEqual(cantidad, 1)
        datos = crear.call_args.kwargs
        self.assertIn('Camión de despacho requiere atención', datos['NOT_CCONTENIDO'])
        self.assertIn('El camión patente GBWG47 se presentó en Patio de Camiones', datos['NOT_CCONTENIDO'])
        self.assertIn('Revise y asocie el camión a la citación de despacho correspondiente.', datos['NOT_CCONTENIDO'])
        self.assertIn('Citacion sugerida: #38700', datos['NOT_CCONTENIDO'])
        self.assertEqual(
            datos['NOT_CURL'],
            '/camiones-patio/?_empresa_id=2&camion_patio=117',
        )

    def test_asociacion_resuelve_notificaciones_pendientes_del_camion(self):
        queryset = MagicMock()
        queryset.update.return_value = 2
        with patch.object(views.NOTIFICACION.objects, 'filter', return_value=queryset) as filtrar:
            actualizadas = views.resolver_notificaciones_camion_patio_asistente_despacho(self.camion)
        self.assertEqual(actualizadas, 2)
        self.assertEqual(filtrar.call_args.kwargs['EP_NID_id'], 2)
        self.assertFalse(filtrar.call_args.kwargs['NOT_BREAD'])
        queryset.update.assert_called_once()
        self.assertTrue(queryset.update.call_args.kwargs['NOT_BREAD'])


class CamionPatioAsistenteDespachoConcurrenciaTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(username='asistente_despacho', is_superuser=False)
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        self.camion = SimpleNamespace(
            id=117,
            pk=117,
            EP_NID_id=2,
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            solicitudes_no_planificado=solicitudes,
        )

    def ejecutar(self, *, disponible=True, estado=None):
        if estado:
            self.camion.CPA_CESTADO = estado
        request = self.factory.post(
            '/camiones-patio/117/asociar/',
            {'_empresa_id': '2', 'citacion_id': '38700'},
        )
        request.user = self.user
        camiones = MagicMock()
        camiones.select_related.return_value.prefetch_related.return_value.get.return_value = self.camion
        citacion = SimpleNamespace(id=38700)
        citaciones = MagicMock()
        citaciones.select_related.return_value.get.return_value = citacion
        duplicados = MagicMock()
        duplicados.exclude.return_value.exists.return_value = False
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=camiones) as lock_camion, \
             patch.object(views.CAMION_PATIO.objects, 'filter', return_value=duplicados), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=citaciones) as lock_citacion, \
             patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=True), \
             patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=disponible), \
             patch.object(views, '_asociar_camion_patio_a_citacion') as asociar:
            response = views.CAMION_PATIO_ASOCIAR(request, 117)
        return response, lock_citacion, asociar
        lock_camion.assert_called_once_with(of=('self',))

    def test_citacion_no_disponible_devuelve_conflicto_y_no_asocia(self):
        response, lock_citacion, asociar = self.ejecutar(disponible=False)
        self.assertEqual(response.status_code, 409)
        self.assertIn('ya no esta disponible', json.loads(response.content)['message'])
        lock_citacion.assert_called_once_with(of=('self',))
        asociar.assert_not_called()

    def test_camion_ya_asociado_impide_segunda_asociacion(self):
        response, lock_citacion, asociar = self.ejecutar(
            estado=views.CAMION_PATIO.ESTADO_ASOCIADO_CITACION
        )
        self.assertEqual(response.status_code, 409)
        lock_citacion.assert_not_called()
        asociar.assert_not_called()
