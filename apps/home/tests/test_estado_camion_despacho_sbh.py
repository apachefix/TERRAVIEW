import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from apps.home import views


class EstadoCamionDespachoSbhBusquedaTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(username='guardia', is_superuser=False)

    def citacion(self, horas=0, estado='PROGRAMADO', pk=100):
        return SimpleNamespace(
            id=pk, CI_FFECHACITACION=timezone.now() + timedelta(hours=horas),
            CI_CESTADO=estado, CI_CTIPO='DESPACHO', PL_NID=None,
            EP_NID_id=2,
        )

    def buscar(self, citaciones):
        with patch.object(views, '_citaciones_por_patente_operacional', return_value=citaciones), \
             patch.object(views, '_salida_confirmada_citacion', return_value=False), \
             patch.object(views, '_citacion_tiene_proceso_operacional_iniciado', return_value=False), \
             patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True):
            return views.buscar_despachos_sbh_cercanos_sin_ingreso('GB-WG 47', 2)

    def test_encuentra_despacho_sbh_de_hoy_y_futuro(self):
        hoy = self.citacion(horas=2, pk=1)
        futuro = self.citacion(horas=26, pk=2)
        self.assertEqual(self.buscar([futuro, hoy]), [hoy, futuro])

    def test_no_devuelve_terminadas(self):
        self.assertEqual(self.buscar([self.citacion(horas=2, estado=views.CIT_TERMINADO)]), [])

    def test_busqueda_nueva_no_se_aplica_a_otras_empresas(self):
        self.assertEqual(views.buscar_despachos_sbh_cercanos_sin_ingreso('GBWG47', 1), [])

    def test_proceso_activo_tiene_prioridad(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = self.user
        proceso = SimpleNamespace(id=55)
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=proceso), \
             patch.object(views, '_estado_camion_payload', return_value={'citacion_id': 55}), \
             patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso') as buscar:
            response = views.estado_camion_ajax(request)
        self.assertEqual(json.loads(response.content)['tipo_resultado'], 'PROCESO_ACTIVO')
        buscar.assert_not_called()

    def test_multiples_candidatos_no_seleccionan_automaticamente(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = self.user
        candidatos = [self.citacion(2, pk=1), self.citacion(3, pk=2)]
        empresa = SimpleNamespace(id=2)
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=None), \
             patch.object(views, '_camion_patio_activo_por_patente', return_value=None), \
             patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=candidatos), \
             patch.object(views, '_payload_planificacion_estado_camion', side_effect=lambda c: {'citacion_id': c.id}), \
             patch.object(views, 'usuario_es_guardia', return_value=True), \
             patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=empresa))), \
             patch.object(views, 'registrar_log_camion_no_planificado'):
            response = views.estado_camion_ajax(request)
        data = json.loads(response.content)
        self.assertEqual(data['tipo_resultado'], 'MULTIPLE_MATCHES')
        self.assertEqual([item['citacion_id'] for item in data['data']['candidatos']], [1, 2])

    def test_sin_planificacion_deriva_a_recepcion(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = self.user
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=None), \
             patch.object(views, '_camion_patio_activo_por_patente', return_value=None), \
             patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[]), \
             patch.object(views, 'buscar_citacion_vigente_sin_ingreso_por_patente', return_value=[]), \
             patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=SimpleNamespace(id=2)))), \
             patch.object(views, 'registrar_log_camion_no_planificado'):
            response = views.estado_camion_ajax(request)
        self.assertIn('Asistente de Recepcion', json.loads(response.content)['message'])


class EstadoCamionDespachoSbhRegistroTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(username='guardia', is_superuser=False)
        self.empresa = SimpleNamespace(id=2)
        self.planificacion = SimpleNamespace(id=80)
        self.citacion = SimpleNamespace(
            id=90, PL_NID=self.planificacion, PL_NID_id=80,
            CI_CTIPODOCUMENTO='',
        )

    def ejecutar(self, datos=None):
        request = self.factory.post('/estado-camion/registrar-ingreso-despacho-sbh/', datos or {'patente': 'GB-WG 47', 'citacion_id': '90'})
        request.user = self.user
        camion = SimpleNamespace(id=10, CI_NID_id=None)
        crear_camion = MagicMock(return_value=camion)
        vista = getattr(views.estado_camion_registrar_ingreso_despacho_sbh, '__wrapped__', views.estado_camion_registrar_ingreso_despacho_sbh)
        parches = (
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views, 'usuario_es_guardia', return_value=True),
            patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=None),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[self.citacion]),
            patch.object(views, '_datos_planificacion_despacho_sbh', return_value={
                'patente': 'GBWG47', 'conductor': 'Conductora Uno', 'rut_conductor': '11111111-1',
                'telefono': '912345678', 'codigo_pais': '+56', 'empresa_transporte': 'Transportes SBH',
                'transporte_a_cargo': 'TERRAMAR', 'cliente': 'Cliente SBH', 'producto': 'Aceite',
            }),
            patch.object(views.EMPRESA.objects, 'get', return_value=self.empresa),
            patch.object(views.CAMION_PATIO.objects, 'create', crear_camion),
            patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'create'),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views, 'notificar_camion_patio_asistente_despacho', return_value=2),
            patch.object(views, '_notificar_asistente_cd_despacho_sbh'),
        )
        iniciados = [item.start() for item in parches]
        try:
            response = vista(request)
        finally:
            for item in reversed(parches):
                item.stop()
        return response, crear_camion, iniciados

    def test_guardia_crea_camion_sin_asociar_y_reutiliza_datos(self):
        response, crear_camion, iniciados = self.ejecutar()
        self.assertEqual(response.status_code, 200, response.content)
        kwargs = crear_camion.call_args.kwargs
        self.assertIsNone(kwargs['CI_NID'])
        self.assertEqual(kwargs['CPA_CPATENTE'], 'GBWG47')
        self.assertEqual(kwargs['CPA_CNOMBRE_CONDUCTOR'], 'Conductora Uno')
        self.assertEqual(kwargs['CPA_CCLIENTE_DECLARADO'], 'Cliente SBH')
        self.assertEqual(json.loads(response.content)['notificados'], 2)
        iniciados[-2].assert_called_once()
        iniciados[-1].assert_not_called()

    def test_rechaza_ingreso_duplicado(self):
        request = self.factory.post('/estado-camion/registrar-ingreso-despacho-sbh/', {'patente': 'GBWG47'})
        request.user = self.user
        vista = getattr(views.estado_camion_registrar_ingreso_despacho_sbh, '__wrapped__', views.estado_camion_registrar_ingreso_despacho_sbh)
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_guardia', return_value=True), \
             patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=None), \
             patch.object(views, '_camion_patio_activo_por_patente', return_value=SimpleNamespace(id=77)), \
             patch.object(views.CAMION_PATIO.objects, 'create') as crear:
            response = vista(request)
        self.assertEqual(response.status_code, 409)
        crear.assert_not_called()

    def test_guardia_no_resuelve_multiples_candidatos(self):
        request = self.factory.post('/estado-camion/registrar-ingreso-despacho-sbh/', {'patente': 'GBWG47', 'citacion_id': '90'})
        request.user = self.user
        vista = getattr(views.estado_camion_registrar_ingreso_despacho_sbh, '__wrapped__', views.estado_camion_registrar_ingreso_despacho_sbh)
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_guardia', return_value=True), \
             patch.object(views, 'buscar_proceso_operacional_activo_por_patente', return_value=None), \
             patch.object(views, '_camion_patio_activo_por_patente', return_value=None), \
             patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[self.citacion, SimpleNamespace(id=91)]):
            response = vista(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no debe resolver', json.loads(response.content)['message'])


class AsistenteDespachoPermisosYAsociacionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id=7, username='asistente_despacho', is_superuser=False, is_authenticated=True, is_active=True)

    def test_perfil_global_se_resuelve_por_codigo_y_empresa(self):
        filtro = MagicMock()
        filtro.exists.return_value = True
        with patch.object(views.PERFIL_USUARIO.objects, 'filter', return_value=filtro) as perfiles, \
             patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True) as empresa:
            permitido = views.usuario_es_asistente_despacho_empresa(self.user, 2)
        self.assertTrue(permitido)
        self.assertEqual(perfiles.call_args.kwargs['PR_NID__PR_CCODIGO__iexact'], 'ASISTENTE_DESPACHO')
        empresa.assert_called_once_with(self.user, 2)

    def test_destinatarios_exigen_perfil_habilitado_y_empresa_dos(self):
        perfiles = MagicMock()
        perfiles.values_list.return_value = [7]
        usuarios = MagicMock()
        usuarios.distinct.return_value = [self.user]
        with patch.object(views.PERFIL_USUARIO.objects, 'filter', return_value=perfiles) as filtro_perfil, \
             patch.object(views.User.objects, 'filter', return_value=usuarios) as filtro_usuario:
            resultado = views._usuarios_asistente_despacho_empresa(2)
        self.assertEqual(resultado, [self.user])
        self.assertEqual(filtro_perfil.call_args.kwargs['PR_NID__PR_CCODIGO__iexact'], 'ASISTENTE_DESPACHO')
        self.assertTrue(filtro_perfil.call_args.kwargs['PE_BHABILITADO'])
        self.assertEqual(filtro_usuario.call_args.kwargs['empresas_asignadas__EP_NID_id'], 2)

    def camion(self):
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        return SimpleNamespace(
            id=10, pk=10, EP_NID_id=2, EP_NID=SimpleNamespace(id=2), CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            CPA_CPATENTE='GBWG47', solicitudes_no_planificado=solicitudes,
        )

    def request_asociacion(self):
        request = self.factory.post('/camiones-patio/10/asociar/', {'citacion_id': '90', '_empresa_id': '2'})
        request.user = self.user
        return request

    def test_guardia_no_puede_asociar(self):
        camion = self.camion()
        cadena = MagicMock()
        cadena.select_related.return_value.prefetch_related.return_value.get.return_value = camion
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=cadena), \
             patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=False), \
             patch.object(views, '_asociar_camion_patio_a_citacion') as asociar:
            response = views.CAMION_PATIO_ASOCIAR(self.request_asociacion(), 10)
        self.assertEqual(response.status_code, 403)
        asociar.assert_not_called()

    def test_asistente_despacho_asocia_sbh_sin_saltar_revision(self):
        camion = self.camion()
        citacion = SimpleNamespace(id=90, CI_CTIPO=views.CIT_DESPACHO, PL_NID=None)
        cadena = MagicMock()
        cadena.select_related.return_value.prefetch_related.return_value.get.return_value = camion
        citaciones = MagicMock()
        citaciones.select_related.return_value.get.return_value = citacion
        duplicados = MagicMock()
        duplicados.exclude.return_value.exists.return_value = False
        resultado = {
            'datos_guardados': [1], 'adjuntos_guardados': [],
            'log_asociacion': SimpleNamespace(id=5),
            'siguiente_etapa': SimpleNamespace(ET_CCODIGO='ASISTENTE_CD'),
        }
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=cadena), \
             patch.object(views.CAMION_PATIO.objects, 'filter', return_value=duplicados), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=citaciones), \
             patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=True), \
             patch.object(views, '_es_camion_despacho_patio', return_value=True), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True), \
             patch.object(views, 'resolver_notificaciones_camion_patio_asistente_despacho', return_value=1), \
             patch.object(views, '_asociar_camion_patio_a_citacion', return_value=resultado) as asociar:
            response = views.CAMION_PATIO_ASOCIAR(self.request_asociacion(), 10)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(asociar.call_args.kwargs['origen'], 'ASOCIACION_MANUAL')
        self.assertIn('pendiente validacion/envio a Asistente_C_D', json.loads(response.content)['message'])

    def test_asociacion_persiste_fk_y_avanza_a_asistente_cd(self):
        empresa = SimpleNamespace(id=2)
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        camion = SimpleNamespace(
            id=10, pk=10, EP_NID_id=2, EP_NID=empresa, CI_NID_id=None, CI_NID=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            CPA_CPATENTE='GBWG47', CPA_CNOMBRE_CONDUCTOR='Conductora Uno',
            CPA_CINSUMO_DECLARADO_GUIA='', solicitudes_no_planificado=solicitudes,
            save=MagicMock(),
        )
        citacion = SimpleNamespace(
            id=90, EP_NID_id=2, EP_NID=empresa, PL_NID=SimpleNamespace(id=80),
            PL_NID_id=80, CI_CTIPO='DESPACHO',
        )
        sin_duplicados = MagicMock()
        sin_duplicados.exclude.return_value.exists.return_value = False
        logs = MagicMock()
        logs.filter.return_value.exists.return_value = True
        with patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True), \
             patch.object(views, '_faltantes_camion_patio_despacho_sbh', return_value=[]), \
             patch.object(views.CAMION_PATIO.objects, 'filter', return_value=sin_duplicados), \
             patch.object(views.CAMION_PATIO.objects, 'get', return_value=SimpleNamespace(CPA_CESTADO=views.CAMION_PATIO.ESTADO_ASOCIADO_CITACION, CI_NID_id=90)), \
             patch.object(views, '_copiar_datos_camion_patio_a_citacion', return_value=[1]), \
             patch.object(views, '_copiar_adjuntos_camion_patio_a_citacion', return_value=[]), \
             patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'filter', return_value=MagicMock(only=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))), \
             patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'update_or_create'), \
             patch.object(views, '_patente_planificada_despacho_patio', return_value='GBWG47'), \
             patch.object(views, '_preparar_citacion_patio_para_revision_ar'), \
             patch.object(views, 'avanzar_citacion_a_siguiente_etapa', return_value=(SimpleNamespace(), SimpleNamespace(ET_CCODIGO='CD'))) as avanzar, \
             patch.object(views, '_notificar_asistente_cd_despacho_sbh', return_value=[SimpleNamespace(id=3)]) as notificar_cd, \
             patch.object(views, 'registrar_log_camion_no_planificado'), \
             patch.object(views.SYSLOGGER.objects, 'create', return_value=SimpleNamespace(id=8)), \
             patch.object(views.SYSLOGGER.objects, 'filter', logs.filter):
            views._asociar_camion_patio_a_citacion(
                camion=camion, citacion=citacion, usuario=self.user, empresa=empresa,
                origen='ASOCIACION_ASISTENTE_DESPACHO_SBH',
            )
        self.assertIs(camion.CI_NID, citacion)
        self.assertEqual(camion.CPA_CESTADO, views.CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
        self.assertEqual(avanzar.call_args.kwargs['accion'], 'ENVIA_CD_DESP_SBH')
        notificar_cd.assert_called_once_with(citacion, camion, self.user)
