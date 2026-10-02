import json
from contextlib import nullcontext
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CAMION_PATIO, CAMION_PATIO_TRAZABILIDAD_PLANIFICACION, EMPRESA, NOTIFICACION,
    PERFIL, PERFIL_USUARIO, SYSLOGGER, USERS_EMPRESA,
)


class EstadoCamionCicloPatioActivoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('guardia_ciclo_activo')
        cls.empresa = EMPRESA.objects.create(
            id=812,
            EP_CRAZONSOCIAL='Empresa ciclo activo',
            EP_CRUT='81.200.000-1',
            EP_CBASEDATOS='ciclo_activo',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )

    def crear_camion(self, estado, patente='SRXS8D'):
        return CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CPA_CPATENTE=patente,
            CPA_CNOMBRE_CONDUCTOR='Humberto Urriza',
            CPA_CTRANSPORTISTA_DECLARADO='Transportes Bretti Limitada',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=estado,
            US_GUARDIA_ID=self.user,
        )

    def test_historico_y_nuevo_pendiente_selecciona_nuevo_ciclo(self):
        historico = self.crear_camion(CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        pendiente = self.crear_camion(CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION)
        encontrado = views._camion_patio_activo_por_patente(
            'SR-X S8D', self.empresa.id,
        )
        self.assertEqual(encontrado.id, pendiente.id)
        self.assertNotEqual(encontrado.id, historico.id)

    def test_varios_historicos_no_producen_ciclo_activo(self):
        self.crear_camion(CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        self.crear_camion(CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        self.assertIsNone(
            views._camion_patio_activo_por_patente('SRXS8D', self.empresa.id)
        )


class DerivacionIngresoCamionPatioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.guardia = User.objects.create_user('usuario_guardia_perfil')
        cls.usuario_solo_nombre = User.objects.create_user('Guardia')
        cls.usuario_sin_perfil = User.objects.create_user('usuario_sin_perfil_guardia')
        cls.asistente_despacho = User.objects.create_user('destino_despacho')
        cls.asistente_recepcion = User.objects.create_user('destino_recepcion')
        cls.empresa = EMPRESA.objects.create(
            id=813,
            EP_CRAZONSOCIAL='Empresa derivacion',
            EP_CRUT='81.300.000-2',
            EP_CBASEDATOS='derivacion',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        for usuario in (
            cls.guardia, cls.usuario_solo_nombre, cls.usuario_sin_perfil,
            cls.asistente_despacho, cls.asistente_recepcion,
        ):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=cls.empresa)
        perfiles = (
            (cls.guardia, 'GUARDIA', 'GUARDIA'),
            (cls.asistente_despacho, 'ASISTENTE_DESPACHO', 'ASISTENTE DESPACHO'),
            (cls.asistente_recepcion, 'ASISTENTE_RECEPCION', 'ASISTENTE RECEPCION'),
        )
        for usuario, codigo, nombre in perfiles:
            perfil = PERFIL.objects.create(
                US_NID=usuario,
                PR_CCODIGO=codigo,
                PR_CNOMBRE=nombre,
            )
            PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil)

    def crear_camion(self, patente):
        return CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CPA_CPATENTE=patente,
            CPA_CNOMBRE_CONDUCTOR='Conductor',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=self.guardia,
        )

    def derivar(self, camion, es_despacho, usuario=None):
        request = RequestFactory().post(f'/camiones-patio/{camion.id}/derivar/')
        request.user = usuario or self.guardia
        with (
            patch.object(views, 'Verificar_empresa', return_value=self.empresa.id),
            patch.object(views, '_es_camion_despacho_patio', return_value=es_despacho),
        ):
            return views.CAMION_PATIO_DERIVAR(request, camion.id)

    def test_despacho_deriva_por_perfil_a_asistente_despacho(self):
        camion = self.crear_camion('DESP01')
        response = self.derivar(camion, True)
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertEqual(data['responsable'], 'ASISTENTE_DESPACHO')
        self.assertEqual(data['notificados'], 1)
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION=views.CAMION_PATIO_LOG_DERIVACION,
            LOG_CADD1='ASISTENTE_DESPACHO',
            LOG_CADD2=str(camion.id),
        ).exists())
        notificacion = NOTIFICACION.objects.get(
            USER_RECEIVER_ID=self.asistente_despacho,
            EP_NID=self.empresa,
        )
        self.assertEqual(notificacion.USER_SENDER_ID, self.guardia)
        self.assertFalse(notificacion.NOT_BREAD)
        self.assertTrue(notificacion.NOT_BHABILITADO)
        self.assertIsNone(notificacion.NOT_FFECHALEIDO)
        self.assertEqual(
            notificacion.NOT_CURL,
            f'/camiones-patio/?_empresa_id={self.empresa.id}&camion_patio={camion.id}',
        )
        self.assertIn(f'Camion patio: #{camion.id}', notificacion.NOT_CCONTENIDO)

        repetido = self.derivar(camion, True)
        self.assertEqual(repetido.status_code, 409)
        self.assertEqual(NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=self.asistente_despacho,
            EP_NID=self.empresa,
            NOT_CURL=notificacion.NOT_CURL,
        ).count(), 1)

        camion.refresh_from_db()
        self.assertEqual(
            camion.CPA_CESTADO,
            CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
        )
        self.assertIsNone(camion.CI_NID_id)

    def test_recepcion_deriva_por_perfil_a_asistente_recepcion(self):
        camion = self.crear_camion('RECP01')
        response = self.derivar(camion, False)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            json.loads(response.content)['responsable'],
            'ASISTENTE_RECEPCION',
        )
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION=views.CAMION_PATIO_LOG_DERIVACION,
            LOG_CADD1='ASISTENTE_RECEPCION',
            LOG_CADD2=str(camion.id),
        ).exists())
        notificacion = NOTIFICACION.objects.get(
            USER_RECEIVER_ID=self.asistente_recepcion,
            EP_NID=self.empresa,
        )
        self.assertEqual(notificacion.USER_SENDER_ID, self.guardia)
        self.assertFalse(notificacion.NOT_BREAD)
        self.assertIn(f'camion_patio={camion.id}', notificacion.NOT_CURL)

    def test_guardia_legacy_reconocido_por_validador_existente_puede_derivar(self):
        camion = self.crear_camion('LEGACY')
        response = self.derivar(camion, True, usuario=self.usuario_solo_nombre)
        self.assertEqual(response.status_code, 200, response.content)
        notificacion = NOTIFICACION.objects.get(
            USER_RECEIVER_ID=self.asistente_despacho,
            EP_NID=self.empresa,
        )
        self.assertEqual(notificacion.USER_SENDER_ID, self.usuario_solo_nombre)

    def test_usuario_sin_perfil_ni_identidad_guardia_no_puede_derivar(self):
        camion = self.crear_camion('SINPER')
        response = self.derivar(camion, True, usuario=self.usuario_sin_perfil)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION=views.CAMION_PATIO_LOG_DERIVACION,
            LOG_CADD2=str(camion.id),
        ).exists())

class DerivacionSbhSinTransaccionExternaTests(TransactionTestCase):
    def test_derivacion_real_envuelve_bloqueo_notificacion_y_log(self):
        from django.contrib.sessions.backends.db import SessionStore

        empresa, _ = EMPRESA.objects.get_or_create(
            id=2, defaults={
                'EP_CRAZONSOCIAL': 'ACEITES SBH', 'EP_CRUT': '82.000.000-2',
                'EP_CBASEDATOS': 'sbh_test', 'EP_CUSUARIOSBD': 'test', 'EP_CPORT': '5432',
            },
        )
        guardia = get_user_model().objects.create_user('guardia_derivacion_sbh_tx')
        asistente = get_user_model().objects.create_user('asistente_despacho_sbh_tx')
        for usuario, codigo in ((guardia, 'GUARDIA'), (asistente, 'ASISTENTE_DESPACHO')):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=empresa)
            perfil = PERFIL.objects.create(US_NID=usuario, PR_CCODIGO=codigo, PR_CNOMBRE=codigo)
            PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil)
        camion = CAMION_PATIO.objects.create(
            EP_NID=empresa, CPA_CPATENTE='RVTZ28', CPA_CNOMBRE_CONDUCTOR='Conductor',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION, US_GUARDIA_ID=guardia,
        )
        CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
            CPA_NID=camion, EP_NID=empresa, US_NID=guardia,
            CPTR_CPATENTE_CONSULTADA='RVTZ28', CPTR_CPATENTE_LLEGADA='RVTZ28',
            CPTR_CRESULTADO_BUSQUEDA='GUARDIA_MATCH',
        )
        request = RequestFactory().post(
            f'/camiones-patio/{camion.id}/derivar/', {'_empresa_id': 2},
        )
        request.user = guardia
        request.session = SessionStore()

        primera = views.CAMION_PATIO_DERIVAR(request, camion.id)
        self.assertEqual(primera.status_code, 200, primera.content)
        self.assertEqual(json.loads(primera.content)['responsable'], 'ASISTENTE_DESPACHO')
        self.assertEqual(NOTIFICACION.objects.filter(
            EP_NID=empresa, USER_RECEIVER_ID=asistente,
            NOT_CURL__contains=f'camion_patio={camion.id}',
        ).count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION=views.CAMION_PATIO_LOG_DERIVACION,
            LOG_CADD2=str(camion.id),
        ).count(), 1)
        segunda = views.CAMION_PATIO_DERIVAR(request, camion.id)
        self.assertEqual(segunda.status_code, 409)
        self.assertEqual(NOTIFICACION.objects.filter(
            EP_NID=empresa, NOT_CURL__contains=f'camion_patio={camion.id}',
        ).count(), 1)
        camion.refresh_from_db()
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION)
        self.assertIsNone(camion.CI_NID_id)


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

    def test_tarea_generica_futura_se_muestra_sin_ingreso(self):
        futura = self.citacion(horas=26, pk=38711)
        with (
            patch.object(views, '_citaciones_por_patente_operacional', return_value=[futura]),
            patch.object(views, '_salida_confirmada_citacion', return_value=False),
            patch.object(views, '_citacion_tiene_proceso_operacional_iniciado', return_value=False),
        ):
            resultado = views.buscar_citacion_vigente_sin_ingreso_por_patente(
                'SRXS8D', 2,
            )
        self.assertEqual(resultado, [futura])

    def test_encuentra_despacho_sbh_de_hoy_y_futuro(self):
        hoy = self.citacion(horas=2, pk=1)
        futuro = self.citacion(horas=26, pk=2)
        self.assertEqual(self.buscar([futuro, hoy]), [hoy, futuro])

    def test_planificacion_ayer_a_medianoche_sigue_disponible_hoy(self):
        citacion = self.citacion(pk=38745)
        ayer = timezone.localdate() - timedelta(days=1)
        citacion.CI_FFECHACITACION = timezone.make_aware(datetime.combine(ayer, time.min))
        self.assertEqual(self.buscar([citacion]), [citacion])

    def test_planificacion_anteayer_no_reaparece(self):
        citacion = self.citacion(pk=38705)
        anteayer = timezone.localdate() - timedelta(days=2)
        citacion.CI_FFECHACITACION = timezone.make_aware(datetime.combine(anteayer, time.min))
        self.assertEqual(self.buscar([citacion]), [])

    def test_no_devuelve_terminadas(self):
        self.assertEqual(self.buscar([self.citacion(horas=2, estado=views.CIT_TERMINADO)]), [])

    def test_busqueda_nueva_no_se_aplica_a_otras_empresas(self):
        self.assertEqual(views.buscar_despachos_sbh_cercanos_sin_ingreso('GBWG47', 1), [])

    def test_camion_patio_activo_tiene_prioridad_sobre_citacion_historica(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = self.user
        camion = SimpleNamespace(
            id=77,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            CI_NID_id=None,
        )
        with (
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=camion),
            patch.object(views, '_payload_camion_patio_activo_pendiente', return_value={
                'camion_patio_id': 77,
                'estado': views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
                'responsable': 'Guardia',
                'derivado': False,
            }),
            patch.object(views, 'usuario_tiene_perfil_guardia_derivacion', return_value=True),
            patch.object(views, 'buscar_proceso_operacional_activo_por_patente') as buscar_historico,
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso') as buscar_planificacion,
        ):
            response = views.estado_camion_ajax(request)
        data = json.loads(response.content)
        self.assertEqual(data['tipo_resultado'], 'INGRESO_PATIO_PENDIENTE')
        self.assertEqual(data['data']['camion_patio_id'], 77)
        self.assertEqual(data['data']['responsable'], 'Guardia')
        self.assertTrue(data['data']['puede_derivar'])
        buscar_historico.assert_not_called()
        buscar_planificacion.assert_not_called()

    def test_asociado_usa_solo_citacion_del_camion_patio_activo(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = self.user
        citacion_activa = SimpleNamespace(id=91)
        camion = SimpleNamespace(
            id=78,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            CI_NID_id=91,
            CI_NID=citacion_activa,
        )
        with (
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=camion),
            patch.object(views, '_estado_camion_payload', return_value={
                'citacion_id': 91,
                'url_operacion': '/operacion-planta/91/',
            }) as payload,
            patch.object(views, 'buscar_proceso_operacional_activo_por_patente') as buscar_historico,
        ):
            response = views.estado_camion_ajax(request)
        data = json.loads(response.content)
        self.assertEqual(data['tipo_resultado'], 'PROCESO_ACTIVO')
        self.assertEqual(data['data']['citacion_id'], 91)
        self.assertEqual(data['data']['camion_patio_id'], 78)
        self.assertEqual(data['data']['url_operacion'], '/operacion-planta/91/')
        payload.assert_called_once_with(citacion_activa)
        buscar_historico.assert_not_called()

    def test_historico_terminado_no_reaparece_y_muestra_nueva_tarea(self):
        request = self.factory.get('/estado-camion/', {'patente': 'SRXS8D'})
        request.user = self.user
        nueva_tarea = self.citacion(horas=2, pk=38711)
        with (
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_proceso_operacional_activo_por_patente') as buscar_historico,
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[nueva_tarea]),
            patch.object(views, '_payload_planificacion_estado_camion', return_value={
                'citacion_id': 38711,
                'tipo': 'DESPACHO',
            }),
            patch.object(views, 'usuario_es_guardia', return_value=True),
            patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(
                first=MagicMock(return_value=SimpleNamespace(id=2)),
            )),
            patch.object(views, 'registrar_log_camion_no_planificado'),
        ):
            response = views.estado_camion_ajax(request)

        data = json.loads(response.content)
        self.assertEqual(data['tipo_resultado'], 'PLANIFICACION_ENCONTRADA')
        self.assertEqual(data['data']['candidatos'][0]['citacion_id'], 38711)
        self.assertIn('No existe un proceso activo', data['data']['mensaje'])
        self.assertNotIn('url_operacion', data['data'])
        self.assertNotIn('puede_derivar', data['data'])
        buscar_historico.assert_not_called()
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
        self.assertEqual(
            json.loads(response.content)['message'],
            'No existe un proceso activo en planta para esta patente.',
        )


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
        camion = SimpleNamespace(
            id=10,
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
        )
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
        self.assertEqual(
            json.loads(response.content)['estado'],
            views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
        )
        iniciados[-2].assert_not_called()
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
        citacion = SimpleNamespace(
            id=90, CI_CTIPO=views.CIT_DESPACHO, PL_NID=None,
            CON_NID_id=None, save=MagicMock(),
        )
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
        validacion = {
            'aplica': True, 'valido': True, 'errores': [], 'campos': [],
            'conductor': SimpleNamespace(id=41), 'transportista': SimpleNamespace(id=31),
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
             patch.object(views, '_validar_datos_asociacion_camion_despacho_sbh', return_value=validacion), \
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
