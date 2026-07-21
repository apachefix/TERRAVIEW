from datetime import time
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CAMION,
    CITACION,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    EVENTO_INTEGRACION_CALIDAD,
    ITEM,
    CITACION_ITEM,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    RESULTADO_CALIDAD_HISTORIAL,
    RESULTADO_CALIDAD_OPERACION,
    SECUENCIA,
)
from apps.home.services.calidad_integracion_service import intentar_notificacion_calidad_teams
from apps.home.services.calidad_service import asegurar_calidad_iniciada
from apps.home.services.teams_service import TeamsNotificationResult, enviar_resultado_calidad_teams


@override_settings(
    TERRAVIEW_CALIDAD_API_KEY='clave-integracion-pruebas',
    APP_PUBLIC_BASE_URL='https://terraview.example',
    CALIDAD_TEAMS_MAX_INTENTOS=3,
)
class CalidadIntegracionApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('calidad_integracion', password='test')
        cls.empresa = cls._empresa('Empresa Integracion', '31-1')
        cls.otra_empresa = cls._empresa('Otra Empresa Integracion', '32-2')
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE='Integracion calidad',
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18), CA_NDIA=1,
            CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=50,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA', SE_CNOMBRE='RECEPCION BODEGA EXTERNA',
            SE_BHABILITADO=True,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=50,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='ANALISIS_Y_CALIDAD', ET_CNOMBRE='Analisis y calidad',
            ET_NCANTIDADMAXIMA=50, ET_BHABILITADO=True,
        )

    @staticmethod
    def _empresa(nombre, rut):
        return EMPRESA.objects.create(
            EP_CRAZONSOCIAL=nombre, EP_CRUT=rut, EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test', EP_CPORT='0',
        )

    def setUp(self):
        self.teams_patcher = patch(
            'apps.home.services.calidad_integracion_service.enviar_resultado_calidad_teams',
            return_value=TeamsNotificationResult(True, 'TEAMS_WEBHOOK_OK', 'mock'),
        )
        self.teams_mock = self.teams_patcher.start()
        self.addCleanup(self.teams_patcher.stop)

    def crear_proceso(self, guia='00123456', con_camion=False, insumo='Aceite de prueba'):
        camion = None
        if con_camion:
            camion = CAMION.objects.create(
                US_NID=self.user, EP_NID=self.empresa,
                CAM_CPATENTE='ABCD12', CAM_CMODELO='Modelo', CAM_BHABILITADO=True,
            )
        citacion = CITACION.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            SC_NID=self.secuencia, CA_NID=camion, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE', CI_CNUMERODOCUMENTO=guia,
        )
        ETAPA_LOG.objects.create(
            CI_NID=citacion, EP_NID=self.empresa, SC_NID=self.secuencia,
            ET_NID=self.etapa, US_INICIO_ID=self.user, EL_FFECHAINICIO=timezone.now(),
        )
        if insumo:
            item = ITEM.objects.create(EP_NID=self.empresa, IT_CCODIGO=f'I-{citacion.id}', IT_CNOMBRE=insumo)
            CITACION_ITEM.objects.create(EP_NID=self.empresa, IT_NID=item, CI_NID=citacion)
        resultado, _ = asegurar_calidad_iniciada(citacion, self.user)
        return citacion, resultado

    def body(self, **cambios):
        data = {
            'empresa_id': self.empresa.id,
            'numero_guia': '00123456',
            'estado': 'APROBADO',
            'origen': 'EXCEL_CALIDAD',
            'observacion': 'Resultado columna P',
            'fecha_resultado': timezone.now().isoformat(),
            'id_evento': 'excel-00123456-aprobado-1',
        }
        data.update(cambios)
        return data

    def post(self, data=None, key='clave-integracion-pruebas', raw=None):
        return self.client.post(
            reverse('api_integracion_calidad_resultados'),
            data=raw if raw is not None else json.dumps(data or self.body()),
            content_type='application/json',
            **({'HTTP_X_TERRAVIEW_API_KEY': key} if key is not None else {}),
        )

    def test_01_sin_api_key_devuelve_401(self):
        self.assertEqual(self.post(self.body(), key=None).status_code, 401)

    def test_02_api_key_incorrecta_devuelve_403(self):
        self.assertEqual(self.post(self.body(), key='incorrecta').status_code, 403)

    def test_03_api_key_correcta_permite_procesar(self):
        self.crear_proceso()
        response = self.post(self.body())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['procesado'])

    @override_settings(TERRAVIEW_CALIDAD_API_KEY='')
    def test_04_variable_ausente_bloquea_seguro(self):
        self.assertEqual(self.post(self.body()).status_code, 503)

    def test_05_json_invalido_devuelve_400(self):
        self.assertEqual(self.post(raw='{invalido').status_code, 400)

    def test_06_falta_empresa_id(self):
        data = self.body(); data.pop('empresa_id')
        self.assertEqual(self.post(data).status_code, 400)

    def test_07_falta_numero_guia(self):
        data = self.body(); data.pop('numero_guia')
        self.assertEqual(self.post(data).status_code, 400)

    def test_08_falta_estado(self):
        data = self.body(); data.pop('estado')
        self.assertEqual(self.post(data).status_code, 400)

    def test_09_falta_origen(self):
        data = self.body(); data.pop('origen')
        self.assertEqual(self.post(data).status_code, 400)

    def test_10_falta_id_evento(self):
        data = self.body(); data.pop('id_evento')
        self.assertEqual(self.post(data).status_code, 400)

    def test_11_estado_minuscula_se_normaliza(self):
        self.crear_proceso()
        self.assertEqual(self.post(self.body(estado='aprobado')).json()['estado_actual'], 'APROBADO')

    def test_12_aprueba_cliente_con_espacio_se_normaliza(self):
        self.crear_proceso()
        response = self.post(self.body(estado='aprueba cliente', id_evento='evento-aprueba-cliente'))
        self.assertEqual(response.json()['estado_actual'], 'APRUEBA_CLIENTE')

    def test_13_estado_desconocido_devuelve_400(self):
        self.assertEqual(self.post(self.body(estado='OTRO')).status_code, 400)

    def test_14_origen_desconocido_devuelve_400(self):
        self.assertEqual(self.post(self.body(origen='MANUAL_PRUEBA')).status_code, 400)

    def test_15_guia_inexistente_devuelve_404(self):
        response = self.post(self.body(numero_guia='NO-EXISTE'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['codigo'], 'GUIA_NO_ENCONTRADA')

    def test_16_empresa_incorrecta_no_accede(self):
        self.crear_proceso()
        self.assertEqual(self.post(self.body(empresa_id=self.otra_empresa.id)).status_code, 404)

    def test_17_coincidencia_ambigua_devuelve_409(self):
        self.crear_proceso('GUIA-DUP')
        self.crear_proceso('GUIA-DUP')
        response = self.post(self.body(numero_guia='GUIA-DUP', id_evento='ambiguo-1'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['codigo'], 'COINCIDENCIA_AMBIGUA')

    def test_18_excel_aprobado_usa_servicio(self):
        self.crear_proceso()
        with patch('apps.home.services.calidad_integracion_service.procesar_resultado_calidad', wraps=__import__('apps.home.services.calidad_service', fromlist=['procesar_resultado_calidad']).procesar_resultado_calidad) as servicio:
            self.post(self.body())
        servicio.assert_called_once()

    def test_19_excel_rechazado_usa_servicio(self):
        self.crear_proceso()
        response = self.post(self.body(estado='RECHAZADO', id_evento='excel-rechazado'))
        self.assertEqual(response.json()['accion'], 'FLUJO_FINALIZADO_SALIDA_AUTORIZADA')

    def test_20_excel_aprueba_cliente_usa_servicio(self):
        self.crear_proceso()
        response = self.post(self.body(estado='APRUEBA_CLIENTE', id_evento='excel-cliente'))
        self.assertEqual(response.json()['accion'], 'ESPERA_APROBACION_CLIENTE')

    def test_21_correo_aprobado_resuelve_aprueba_cliente(self):
        self.crear_proceso()
        self.post(self.body(estado='APRUEBA_CLIENTE', id_evento='excel-espera'))
        response = self.post(self.body(origen='CORREO_CLIENTE', estado='APROBADO', id_evento='correo-aprueba'))
        self.assertEqual(response.json()['estado_actual'], 'APROBADO')

    def test_22_correo_rechazado_resuelve_aprueba_cliente(self):
        self.crear_proceso()
        self.post(self.body(estado='APRUEBA_CLIENTE', id_evento='excel-espera'))
        response = self.post(self.body(origen='CORREO_CLIENTE', estado='RECHAZADO', id_evento='correo-rechaza'))
        self.assertEqual(response.json()['estado_actual'], 'RECHAZADO')

    def test_23_correo_sobre_pendiente_devuelve_409(self):
        self.crear_proceso()
        self.assertEqual(self.post(self.body(origen='CORREO_CLIENTE', id_evento='correo-pendiente')).status_code, 409)

    def test_24_correo_aprueba_cliente_devuelve_409(self):
        self.crear_proceso()
        response = self.post(self.body(origen='CORREO_CLIENTE', estado='APRUEBA_CLIENTE', id_evento='correo-invalido'))
        self.assertEqual(response.status_code, 409)

    def test_25_mismo_id_evento_se_procesa_una_vez(self):
        citacion, _ = self.crear_proceso()
        self.post(self.body())
        self.post(self.body())
        self.assertEqual(EVENTO_INTEGRACION_CALIDAD.objects.count(), 1)
        self.assertEqual(RESULTADO_CALIDAD_HISTORIAL.objects.filter(CI_NID=citacion, RCH_CESTADO_NUEVO='APROBADO').count(), 1)

    def test_26_evento_duplicado_responde_200(self):
        self.crear_proceso()
        self.post(self.body())
        response = self.post(self.body())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['duplicado'])

    def test_27_eventos_distintos_mismo_resultado_no_cierran_dos_veces(self):
        citacion, _ = self.crear_proceso()
        self.post(self.body())
        self.post(self.body(id_evento='excel-mismo-resultado-2'))
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_CIERRE_AUTOMATICO').count(), 1)

    def test_28_eventos_distintos_mismo_resultado_no_avanzan_dos_veces(self):
        citacion, _ = self.crear_proceso()
        self.post(self.body())
        self.post(self.body(id_evento='excel-mismo-resultado-2'))
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_AVANCE_AUTOMATICO').count(), 1)

    def test_29_teams_se_envia_una_vez_aprobado(self):
        self.crear_proceso()
        self.post(self.body())
        self.assertEqual(self.teams_mock.call_count, 1)

    def test_30_teams_se_envia_una_vez_rechazado(self):
        self.crear_proceso()
        self.post(self.body(estado='RECHAZADO', id_evento='rechazado-teams'))
        self.assertEqual(self.teams_mock.call_count, 1)

    def test_31_teams_no_se_envia_aprueba_cliente(self):
        self.crear_proceso()
        self.post(self.body(estado='APRUEBA_CLIENTE', id_evento='sin-teams'))
        self.teams_mock.assert_not_called()

    def test_32_teams_no_se_envia_duplicado(self):
        self.crear_proceso()
        self.post(self.body())
        self.teams_mock.reset_mock()
        self.post(self.body())
        self.teams_mock.assert_not_called()

    def test_33_card_incluye_citacion_guia_patente_insumo(self):
        citacion, resultado = self.crear_proceso(con_camion=True)
        evento = EVENTO_INTEGRACION_CALIDAD.objects.create(
            EIC_CID_EVENTO='card-datos', EP_NID=self.empresa, EIC_CNUMERO_GUIA='00123456',
            EIC_CESTADO_SOLICITADO='APROBADO', EIC_CORIGEN='EXCEL_CALIDAD',
            RCO_NID=resultado, CI_NID=citacion,
        )
        resultado.RCO_CESTADO = 'APROBADO'
        with patch('apps.home.services.teams_service.enviar_alerta_camion_no_planificado_teams', return_value=TeamsNotificationResult(True, 'OK')) as generic:
            enviar_resultado_calidad_teams(resultado, evento)
        hechos = dict(generic.call_args.kwargs['hechos'])
        self.assertEqual(hechos['Citacion'], f'#{citacion.id}')
        self.assertEqual(hechos['Numero de guia'], '00123456')
        self.assertEqual(hechos['Patente'], 'ABCD12')
        self.assertEqual(hechos['Insumo'], 'Aceite de prueba')

    def test_34_error_teams_no_revierte_resultado(self):
        self.teams_mock.return_value = TeamsNotificationResult(False, 'TEAMS_ERROR', 'fallo mock')
        _, resultado = self.crear_proceso()
        self.post(self.body())
        resultado.refresh_from_db()
        self.assertEqual(resultado.RCO_CESTADO, 'APROBADO')

    def test_35_error_teams_queda_pendiente(self):
        self.teams_mock.return_value = TeamsNotificationResult(False, 'TEAMS_ERROR', 'fallo mock')
        self.crear_proceso()
        self.post(self.body())
        evento = EVENTO_INTEGRACION_CALIDAD.objects.get()
        self.assertTrue(evento.EIC_BTEAMS_PENDIENTE)
        self.assertEqual(evento.EIC_CESTADO_TEAMS, 'ERROR')

    def test_36_reintento_exitoso_marca_enviado(self):
        self.teams_mock.return_value = TeamsNotificationResult(False, 'TEAMS_ERROR', 'fallo mock')
        self.crear_proceso()
        self.post(self.body())
        evento = EVENTO_INTEGRACION_CALIDAD.objects.get()
        self.teams_mock.return_value = TeamsNotificationResult(True, 'TEAMS_WEBHOOK_OK', 'ok')
        evento, intentado = intentar_notificacion_calidad_teams(evento.id, es_reintento=True)
        self.assertTrue(intentado)
        self.assertTrue(evento.EIC_BTEAMS_ENVIADO)

    def test_37_reintento_no_ejecuta_servicio_calidad(self):
        self.teams_mock.return_value = TeamsNotificationResult(False, 'TEAMS_ERROR', 'fallo mock')
        self.crear_proceso()
        self.post(self.body())
        evento = EVENTO_INTEGRACION_CALIDAD.objects.get()
        self.teams_mock.return_value = TeamsNotificationResult(True, 'OK', 'ok')
        with patch('apps.home.services.calidad_integracion_service.procesar_resultado_calidad') as servicio:
            intentar_notificacion_calidad_teams(evento.id, es_reintento=True)
        servicio.assert_not_called()

    def test_38_api_key_no_aparece_en_logs(self):
        with self.assertLogs('apps.home.api_calidad', level='WARNING') as logs:
            self.post(self.body(), key='clave-que-no-debe-aparecer')
        self.assertNotIn('clave-que-no-debe-aparecer', '\n'.join(logs.output))

    def test_39_mantiene_sincronizacion_op_resultado_calidad(self):
        citacion, _ = self.crear_proceso()
        self.post(self.body())
        dato = DATO_OPERACION.objects.get(CI_NID=citacion, CAMP_NID__CA_CCODIGO='OP_RESULTADO_CALIDAD')
        self.assertEqual(json.loads(dato.DO_CVALOR)['resultado_calidad'], 'APROBADO')

    def test_40_comando_reintento_usa_pendientes(self):
        self.teams_mock.return_value = TeamsNotificationResult(False, 'TEAMS_ERROR', 'fallo mock')
        self.crear_proceso()
        self.post(self.body())
        self.teams_mock.return_value = TeamsNotificationResult(True, 'OK', 'ok')
        salida = StringIO()
        call_command('reenviar_notificaciones_calidad_teams', stdout=salida)
        self.assertIn('enviados: 1', salida.getvalue())

    def test_41_guia_sin_proceso_calidad_devuelve_409(self):
        CITACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE',
            CI_CNUMERODOCUMENTO='SIN-PROCESO-CALIDAD',
        )
        response = self.post(self.body(
            numero_guia='SIN-PROCESO-CALIDAD',
            id_evento='sin-proceso-calidad-1',
        ))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['codigo'], 'PROCESO_NO_PREPARADO')

    def test_42_observacion_externa_se_almacena_sanitizada(self):
        self.crear_proceso()
        self.post(self.body(
            observacion='token=secreto password:clave https://interna.example/ruta',
            id_evento='payload-sanitizado-1',
        ))
        evento = EVENTO_INTEGRACION_CALIDAD.objects.get(EIC_CID_EVENTO='payload-sanitizado-1')
        self.assertNotIn('secreto', evento.EIC_CPAYLOAD_SANITIZADO)
        self.assertNotIn('clave', evento.EIC_CPAYLOAD_SANITIZADO)
        self.assertNotIn('interna.example', evento.EIC_CPAYLOAD_SANITIZADO)
        self.assertIn('[DATO_REDACTADO]', evento.EIC_CPAYLOAD_SANITIZADO)
        self.assertIn('[URL_REDACTADA]', evento.EIC_CPAYLOAD_SANITIZADO)
