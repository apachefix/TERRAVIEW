import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.db import connection, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.home import views
from apps.home.models import CAMION_PATIO, CAMION_PATIO_TRAZABILIDAD_PLANIFICACION, EMPRESA


class AsociacionDirectaAsistenteDespachoEmpresasTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            id=7,
            username='asistente_despacho',
            is_superuser=False,
            is_authenticated=True,
            is_active=True,
        )

    def _ejecutar(self, empresa_id, tipo_citacion=views.CIT_DESPACHO):
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        camion = SimpleNamespace(
            id=117,
            pk=117,
            EP_NID_id=empresa_id,
            EP_NID=SimpleNamespace(id=empresa_id),
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            CPA_CPATENTE='GBWG47',
            solicitudes_no_planificado=solicitudes,
        )
        citacion = SimpleNamespace(
            id=38700,
            CI_CTIPO=tipo_citacion,
            PL_NID=None,
        )
        camiones = MagicMock()
        camiones.select_related.return_value.prefetch_related.return_value.get.return_value = camion
        citaciones = MagicMock()
        citaciones.select_related.return_value.get.return_value = citacion
        duplicados = MagicMock()
        duplicados.exclude.return_value.exists.return_value = False
        resultado = {
            'datos_guardados': [1],
            'adjuntos_guardados': [],
            'log_asociacion': SimpleNamespace(id=55),
            'siguiente_etapa': SimpleNamespace(ET_CCODIGO='SIGUIENTE'),
        }
        request = self.factory.post(
            f'/camiones-patio/{camion.id}/asociar/',
            {'_empresa_id': str(empresa_id), 'citacion_id': str(citacion.id)},
        )
        request.user = self.user
        with patch.object(views, 'Verificar_empresa', return_value=empresa_id), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=camiones) as lock_camion, \
             patch.object(views.CAMION_PATIO.objects, 'filter', return_value=duplicados), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=citaciones) as lock_citacion, \
             patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=True), \
             patch.object(views, '_es_camion_despacho_patio', return_value=tipo_citacion == views.CIT_DESPACHO), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True), \
             patch.object(views, 'resolver_notificaciones_camion_patio_asistente_despacho', return_value=1) as resolver, \
             patch.object(views, '_asociar_camion_patio_a_citacion', return_value=resultado) as asociar:
            response = views.CAMION_PATIO_ASOCIAR(request, camion.id)
        lock_camion.assert_called_once_with(of=('self',))
        lock_citacion.assert_called_once_with(of=('self',))
        return response, asociar, resolver

    def test_post_directo_terramar_responde_200_sin_redirect_y_resuelve_notificacion(self):
        response, asociar, resolver = self._ejecutar(views.ID_TERRAMAR)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('Location', response.headers)
        self.assertEqual(asociar.call_args.kwargs['origen'], 'ASOCIACION_MANUAL')
        self.assertEqual(json.loads(response.content)['notificaciones_resueltas'], 1)
        resolver.assert_called_once()

    def test_post_directo_sbh_asocia_y_deja_pendiente_revision_operacional(self):
        response, asociar, resolver = self._ejecutar(views.ID_ACEITES_SBH)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('Location', response.headers)
        self.assertEqual(asociar.call_args.kwargs['origen'], 'ASOCIACION_MANUAL')
        self.assertIn('pendiente validacion/envio', json.loads(response.content)['message'])
        self.assertEqual(json.loads(response.content)['notificaciones_resueltas'], 1)
        resolver.assert_called_once()

    def test_asistente_puede_usar_el_post_directo_con_recepcion(self):
        response, asociar, resolver = self._ejecutar(
            views.ID_TERRAMAR,
            tipo_citacion=views.CIT_RECEPCION,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(asociar.call_args.kwargs['origen'], 'ASOCIACION_MANUAL')
        resolver.assert_not_called()

    def test_frontend_directo_publica_post_y_recarga_sin_redirigir(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        contenido = template.read_text(encoding='utf-8')
        inicio = contenido.index('function asociarDespachoSeleccionado()')
        fin = contenido.index('function abrirSelectorTipoCitacion', inicio)
        rama_directa = contenido[inicio:fin]
        self.assertIn("url: '/camiones-patio/' + patioCamionActual.id + '/asociar/'", rama_directa)
        self.assertIn('window.location.reload();', rama_directa)
        self.assertNotIn('window.location.href', rama_directa)
        self.assertNotIn('PATIO_PLANIFICACIONES_URL', rama_directa)

    def test_listone_muestra_acciones_operacionales_al_asistente_despacho(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        contenido = template.read_text(encoding='utf-8')
        bloque_despachos = contenido[contenido.index('{% for object in despachos %}'):contenido.index('{% for object in recepciones %}')]
        self.assertIn(
            '{% if request.user|es_asistente_recepcion and object.46 or es_asistente_despacho_ingreso and object.46 %}',
            bloque_despachos,
        )
        self.assertIn('onclick="openAsociarCamionPatioModal({{ object.0 }})"', bloque_despachos)
        self.assertIn(
            '{% elif request.user|es_asistente_recepcion and object.21 or es_asistente_despacho_ingreso and object.21 %}',
            bloque_despachos,
        )
        self.assertIn('onclick="openRevisionAsistenteModal({{ object.0 }})"', bloque_despachos)

        bloque_recepciones = contenido[contenido.index('{% for object in recepciones %}'):]
        self.assertIn(
            '{% if request.user|es_asistente_recepcion and object.40 or es_asistente_despacho_ingreso and object.40 %}',
            bloque_recepciones,
        )
        self.assertIn(
            '{% elif request.user|es_asistente_recepcion and object.15 or es_asistente_despacho_ingreso and object.15 %}',
            bloque_recepciones,
        )
    def test_modal_reutiliza_endpoints_operacionales_existentes(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        contenido = template.read_text(encoding='utf-8')
        for endpoint in (
            '/pla-citacion-revision-asistente/',
            '/pla-citacion-editar-ingreso-asistente/',
            '/pla-citacion-guardar-ruta-asistente/',
            '/pla-citacion-aprobar-asistente/',

        ):
            self.assertIn(endpoint, contenido)

class EndpointsIngresoOperativoAsistenteDespachoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            id=7,
            username='asistente_despacho',
            is_superuser=False,
            is_staff=False,
        )

    def test_consulta_rutas_permite_recepcion_en_empresa_activa(self):
        request = self.factory.get(
            '/ajax/rutas-transportista-revision/',
            {'citacion_id': '38700', '_empresa_id': '2'},
        )
        request.user = self.user
        request.session = {'empresa_id': 2}
        citacion = SimpleNamespace(CI_CTIPO=views.CIT_RECEPCION, PL_NID=None)
        consulta = MagicMock()
        consulta.get.return_value = citacion
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.CITACION.objects, 'select_related', return_value=consulta), \
             patch.object(views, 'requiere_ruta_transportista_revision', return_value=False):
            response = views.AJAX_RUTAS_TRANSPORTISTA_REVISION(request)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['success'])

    def test_edicion_recepcion_supera_permiso_y_llega_a_validacion_operacional(self):
        request = self.factory.post('/pla-citacion-editar-ingreso-asistente/38700/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        citacion = SimpleNamespace(
            CI_CTIPO=views.CIT_RECEPCION,
            PL_NID=None,
            SC_NID=SimpleNamespace(id=1),
            ETAPA_ACTUAL=SimpleNamespace(id=1),
            CI_CESTADO=views.CIT_TERMINADO,
        )
        consulta = MagicMock()
        consulta.select_related.return_value.get.return_value = citacion
        detalles = MagicMock()
        detalles.first.return_value = None
        etapas = MagicMock()
        etapas.exists.return_value = False
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_cd', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=consulta), \
             patch.object(views.DETALLE_SECUENCIA.objects, 'filter', return_value=detalles), \
             patch.object(views.ETAPA_LOG.objects, 'filter', return_value=etapas):
            response = views.PLANIFICACION_CITACION_EDITAR_INGRESO_ASISTENTE(request, 38700)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotIn('No tiene permisos', json.loads(response.content)['message'])

    def test_revision_recepcion_supera_permiso_y_llega_a_busqueda_operacional(self):
        request = self.factory.get('/pla-citacion-revision-asistente/38700/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        consulta = MagicMock()
        consulta.get.side_effect = views.CITACION.DoesNotExist
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_guardia', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.CITACION.objects, 'select_related', return_value=consulta):
            response = views.PLANIFICACION_CITACION_REVISION_ASISTENTE(request, 38700)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotIn('No tiene permisos', json.loads(response.content)['message'])

    def test_guardar_ruta_recepcion_supera_permiso_y_llega_a_busqueda_operacional(self):
        request = self.factory.post('/pla-citacion-guardar-ruta-asistente/38700/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        consulta = MagicMock()
        consulta.get.side_effect = views.CITACION.DoesNotExist
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.CITACION.objects, 'select_related', return_value=consulta):
            response = views.GUARDAR_RUTA_CAMION_ASISTENTE(request, 38700)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotIn('No tiene permisos', json.loads(response.content)['message'])

    def test_aprobacion_recepcion_supera_permiso_y_llega_a_validacion_operacional(self):
        request = self.factory.post('/pla-citacion-aprobar-asistente/38700/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        citacion = SimpleNamespace(
            CI_CTIPO=views.CIT_RECEPCION,
            PL_NID=SimpleNamespace(PL_CTIPOCUPO=views.CIT_RECEPCION),
            SC_NID=SimpleNamespace(id=1),
            ETAPA_ACTUAL=SimpleNamespace(id=1),
            CI_CESTADO=views.CIT_TERMINADO,
        )
        consulta = MagicMock()
        consulta.select_related.return_value.get.return_value = citacion
        detalles = MagicMock()
        detalles.first.return_value = None
        etapas = MagicMock()
        etapas.exists.return_value = False
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=consulta), \
             patch.object(views, 'es_flujo_preoperacional_terramar', return_value=False), \
             patch.object(views, 'es_flujo_recepcion_estanque_sbh', return_value=False), \
             patch.object(views.DETALLE_SECUENCIA.objects, 'filter', return_value=detalles), \
             patch.object(views.ETAPA_LOG.objects, 'filter', return_value=etapas):
            response = views.APROBAR_CAMION_ASISTENTE(request, 38700)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotIn('No tiene permisos', json.loads(response.content)['message'])


class AsociacionForUpdateOuterJoinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user('lock_camion_patio')
        cls.empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='EMPRESA LOCK',
            EP_CRUT='76000009-9',
            EP_CBASEDATOS='lock_db',
            EP_CUSUARIOSBD='lock_user',
            EP_CPORT='5432',
        )

    def _crear_camion(self, patente):
        return CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CPA_CPATENTE=patente,
            CPA_CNOMBRE_CONDUCTOR='Conductor Lock',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            US_GUARDIA_ID=self.usuario,
        )

    def _bloquear(self, camion_id):
        with CaptureQueriesContext(connection) as consultas:
            with transaction.atomic():
                camion = CAMION_PATIO.objects.select_for_update(of=('self',)).select_related(
                    'EP_NID', 'CI_NID', 'trazabilidad_planificacion__CI_NID',
                ).get(pk=camion_id)
        sql = next(
            item['sql'] for item in reversed(consultas.captured_queries)
            if 'FOR UPDATE' in item['sql'].upper()
        )
        return camion, sql

    def test_lock_funciona_con_relacion_opcional_ausente(self):
        esperado = self._crear_camion('NULL01')
        obtenido, sql = self._bloquear(esperado.id)
        self.assertEqual(obtenido.id, esperado.id)
        self.assertIn('FOR UPDATE OF', sql.upper())
        self.assertIn('CAMION_PATIO', sql.upper())

    def test_lock_funciona_con_trazabilidad_opcional_presente(self):
        esperado = self._crear_camion('PRESENTE01')
        CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
            CPA_NID=esperado,
            EP_NID=self.empresa,
            CPTR_CPATENTE_CONSULTADA=esperado.CPA_CPATENTE,
            CPTR_CRESULTADO_BUSQUEDA='SIN_CITACION',
            CPTR_CPATENTE_LLEGADA=esperado.CPA_CPATENTE,
            US_NID=self.usuario,
        )
        obtenido, sql = self._bloquear(esperado.id)
        self.assertEqual(obtenido.trazabilidad_planificacion.CPA_NID_id, esperado.id)
        self.assertIn('FOR UPDATE OF', sql.upper())
        self.assertIn('CAMION_PATIO', sql.upper())
