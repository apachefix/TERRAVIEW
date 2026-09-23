from datetime import time
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    EVENTO_INTEGRACION_CALIDAD,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    RESULTADO_CALIDAD_OPERACION,
    SECUENCIA,
)
from apps.home.services import calidad_service
from apps.home.services.calidad_service import (
    asegurar_calidad_iniciada,
    procesar_resultado_calidad,
)
from apps.home.services.teams_service import TeamsNotificationResult


@override_settings(
    TERRAVIEW_CALIDAD_API_KEY='clave-revision-manual',
    APP_PUBLIC_BASE_URL='https://terraview.example',
)
class CalidadRevisionManualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.calidad = get_user_model().objects.create_user('CALIDAD', password='test')
        cls.otro_usuario = get_user_model().objects.create_user('ASISTENTE_C_D', password='test')
        cls.empresa_1 = cls._crear_empresa(1, 'Empresa Uno', '11-1')
        cls.empresa_2 = cls._crear_empresa(2, 'Aceites SBH', '22-2')

    @staticmethod
    def _crear_empresa(pk, nombre, rut):
        return EMPRESA.objects.create(
            pk=pk,
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=rut,
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )

    def setUp(self):
        self.teams_patcher = patch(
            'apps.home.services.calidad_integracion_service.enviar_resultado_calidad_teams',
            return_value=TeamsNotificationResult(True, 'MOCK', 'sin llamada externa'),
        )
        self.teams_mock = self.teams_patcher.start()
        self.addCleanup(self.teams_patcher.stop)

    def crear_proceso(
        self,
        empresa=None,
        tipo='RECEPCION',
        codigo='RECEPCION_ESTANQUE_SBH',
        guia=None,
    ):
        empresa = empresa or self.empresa_2
        guia = guia or f'GUIA-REV-{CITACION.objects.count() + 1}'
        calendario = CALENDARIO.objects.create(
            US_NID=self.calidad,
            EP_NID=empresa,
            CA_CNOMBRE=f'Calidad {empresa.pk} {tipo} {CITACION.objects.count()}',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=20,
        )
        planificacion = PLANIFICACION.objects.create(
            US_NID=self.calidad,
            EP_NID=empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO=tipo,
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=20,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=self.calidad,
            EP_NID=empresa,
            SE_CTIPO=tipo,
            SE_CCODIGO=codigo,
            SE_CNOMBRE=f'{tipo} {codigo}',
            SE_BHABILITADO=True,
        )
        etapa = ETAPA.objects.create(
            US_NID=self.calidad,
            EP_NID=empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO=f'ANALISIS_{citacion_codigo_seguro(codigo)}_{CITACION.objects.count()}',
            ET_CNOMBRE='Analisis y calidad',
            ET_NCANTIDADMAXIMA=20,
            ET_BHABILITADO=True,
        )
        citacion = CITACION.objects.create(
            US_NID=self.calidad,
            EP_NID=empresa,
            PL_NID=planificacion,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=tipo,
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO=guia,
        )
        ETAPA_LOG.objects.create(
            CI_NID=citacion,
            EP_NID=empresa,
            SC_NID=secuencia,
            ET_NID=etapa,
            US_INICIO_ID=self.calidad,
            EL_FFECHAINICIO=timezone.now(),
        )
        asegurar_calidad_iniciada(citacion, self.calidad)
        return citacion

    def payload_bot(self, citacion, estado, id_evento):
        return {
            'empresa_id': citacion.EP_NID_id,
            'numero_guia': citacion.CI_CNUMERODOCUMENTO,
            'estado': estado,
            'origen': 'EXCEL_CALIDAD',
            'observacion': 'Resultado informado por bot',
            'fecha_resultado': timezone.now().isoformat(),
            'id_evento': id_evento,
        }

    def post_bot(self, citacion, estado, id_evento):
        return self.client.post(
            reverse('api_integracion_calidad_resultados'),
            data=json.dumps(self.payload_bot(citacion, estado, id_evento)),
            content_type='application/json',
            HTTP_X_TERRAVIEW_API_KEY='clave-revision-manual',
        )

    def crear_rechazo_revisable(self, guia='GUIA-REV-MANUAL'):
        citacion = self.crear_proceso(guia=guia)
        response = self.post_bot(citacion, 'RECHAZADO', f'bot-{guia}')
        self.assertEqual(response.status_code, 200)
        return citacion

    def resolver_manual(self, citacion, usuario=None, decision='APROBADO', comentario='Revision conforme'):
        self.client.force_login(usuario or self.calidad)
        url = reverse('ajax_operacion_planta_resolver_revision_calidad', args=[citacion.pk])
        with patch('apps.home.views.Verificar_empresa', return_value=citacion.EP_NID_id):
            return self.client.post(
                url,
                {
                    'decision': decision,
                    'comentario': comentario,
                    '_empresa_id': citacion.EP_NID_id,
                    'empresa_id': citacion.EP_NID_id,
                },
            )

    def test_bot_aprobado_sbh_mantiene_flujo_y_callback_sap(self):
        citacion = self.crear_proceso(guia='GUIA-BOT-APROBADO')
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.post_bot(citacion, 'APROBADO', 'bot-aprobado-sbh')

        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.APROBADO)
        self.assertEqual(len(callbacks), 1)

    def test_bot_rechazado_sbh_queda_pendiente_revision_sin_efectos_terminales(self):
        citacion = self.crear_proceso(guia='GUIA-BOT-RECHAZADO')
        with patch.object(
            calidad_service,
            '_crear_borrador_sap_recepcion_interno_post_commit',
        ) as crear_draft:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.post_bot(citacion, 'RECHAZADO', 'bot-rechazado-sbh')

        citacion.refresh_from_db()
        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        evento = EVENTO_INTEGRACION_CALIDAD.objects.get(EIC_CID_EVENTO='bot-rechazado-sbh')
        historial = resultado.historial.order_by('-id').first()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['estado_actual'],
            resultado.Estado.RECHAZADO_PENDIENTE_REVISION,
        )
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.RECHAZADO_PENDIENTE_REVISION)
        self.assertEqual(resultado.RCO_CORIGEN, resultado.Origen.EXCEL_CALIDAD)
        self.assertEqual(resultado.RCO_CRESPONSABLE_SISTEMA, 'BOT_CALIDAD_EXCEL')
        self.assertFalse(resultado.RCO_BAUTORIZA_SALIDA)
        self.assertFalse(resultado.RCO_BCIERRE_AUTOMATICO)
        self.assertIsNone(resultado.RCO_FCIERRE)
        self.assertEqual(citacion.CI_CESTADO, 'EN PROCESO')
        self.assertIsNone(citacion.CI_FFECHATERMINO)
        self.assertEqual(evento.EIC_CESTADO_SOLICITADO, resultado.Estado.RECHAZADO)
        self.assertEqual(evento.EIC_CRESULTADO, 'PENDIENTE_REVISION_MANUAL')
        self.assertEqual(historial.RCH_CESTADO_ANTERIOR, resultado.Estado.PENDIENTE)
        self.assertEqual(
            historial.RCH_CESTADO_NUEVO,
            resultado.Estado.RECHAZADO_PENDIENTE_REVISION,
        )
        self.assertEqual(historial.RCH_CORIGEN, resultado.Origen.EXCEL_CALIDAD)
        self.assertEqual(historial.RCH_COBSERVACION, 'Resultado informado por bot')
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=citacion,
                OPL_CPASO='Analisis y calidad',
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            ).exists()
        )
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=citacion,
                OPL_CPASO='CALIDAD_SALIDA_AUTORIZADA',
            ).exists()
        )
        self.assertEqual(callbacks, [])
        crear_draft.assert_not_called()
        self.teams_mock.assert_not_called()

    def test_aprobacion_manual_exige_comentario(self):
        citacion = self.crear_rechazo_revisable('GUIA-SIN-COMENTARIO')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            response = self.resolver_manual(citacion, comentario='   ')

        self.assertEqual(response.status_code, 400)
        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.RECHAZADO_PENDIENTE_REVISION)

    def test_usuario_no_calidad_no_puede_resolver(self):
        citacion = self.crear_rechazo_revisable('GUIA-USUARIO-AJENO')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            response = self.resolver_manual(citacion, usuario=self.otro_usuario)

        self.assertEqual(response.status_code, 403)
        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.RECHAZADO_PENDIENTE_REVISION)

    def test_calidad_aprueba_manual_con_historial_y_callback_sap_post_commit(self):
        citacion = self.crear_rechazo_revisable('GUIA-APROBACION-MANUAL')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True), patch.object(
            calidad_service,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': False, 'docentry': None},
        ), patch.object(
            calidad_service,
            '_crear_borrador_sap_recepcion_interno_post_commit',
            return_value={'success': True},
        ) as crear_draft:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.resolver_manual(
                    citacion,
                    comentario='Aprobado luego de revision humana',
                )

        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        historial = resultado.historial.order_by('-id').first()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.APROBADO)
        self.assertEqual(resultado.RCO_CORIGEN, resultado.Origen.REVISION_MANUAL)
        self.assertEqual(resultado.RCO_COBSERVACION, 'Aprobado luego de revision humana')
        self.assertEqual(historial.RCH_CESTADO_ANTERIOR, resultado.Estado.RECHAZADO_PENDIENTE_REVISION)
        self.assertEqual(historial.RCH_CESTADO_NUEVO, resultado.Estado.APROBADO)
        self.assertEqual(historial.RCH_CORIGEN, resultado.Origen.REVISION_MANUAL)
        self.assertEqual(historial.RCH_COBSERVACION, 'Aprobado luego de revision humana')
        self.assertEqual(historial.US_NID, self.calidad)
        self.assertEqual(len(callbacks), 1)
        crear_draft.assert_called_once()

    def test_doble_aprobacion_manual_no_duplica_historial_ni_callback(self):
        citacion = self.crear_rechazo_revisable('GUIA-DOBLE-APROBACION')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            with self.captureOnCommitCallbacks(execute=False) as callbacks_primera:
                primera = self.resolver_manual(citacion, comentario='Primera decision')
            with self.captureOnCommitCallbacks(execute=False) as callbacks_segunda:
                segunda = self.resolver_manual(citacion, comentario='Segunda decision')

        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 409)
        self.assertEqual(len(callbacks_primera), 1)
        self.assertEqual(callbacks_segunda, [])
        self.assertEqual(
            resultado.historial.filter(
                RCH_CESTADO_ANTERIOR=resultado.Estado.RECHAZADO_PENDIENTE_REVISION,
                RCH_CESTADO_NUEVO=resultado.Estado.APROBADO,
            ).count(),
            1,
        )

    def test_calidad_confirma_rechazo_terminal_sin_sap(self):
        citacion = self.crear_rechazo_revisable('GUIA-RECHAZO-DEFINITIVO')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True), patch.object(
            calidad_service,
            '_crear_borrador_sap_recepcion_interno_post_commit',
        ) as crear_draft:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.resolver_manual(
                    citacion,
                    decision='RECHAZADO',
                    comentario='Se confirma fuera de especificacion',
                )

        citacion.refresh_from_db()
        resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        historial = resultado.historial.order_by('-id').first()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.RECHAZADO)
        self.assertTrue(resultado.RCO_BAUTORIZA_SALIDA)
        self.assertTrue(resultado.RCO_BCIERRE_AUTOMATICO)
        self.assertIsNotNone(resultado.RCO_FCIERRE)
        self.assertEqual(citacion.CI_CESTADO, 'RECHAZADO')
        self.assertIsNotNone(citacion.CI_FFECHATERMINO)
        self.assertEqual(historial.RCH_CEVENTO, 'CALIDAD_REVISION_MANUAL_RECHAZADA')
        self.assertTrue(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=citacion,
                OPL_CPASO='CALIDAD_SALIDA_AUTORIZADA',
            ).exists()
        )
        self.assertEqual(callbacks, [])
        crear_draft.assert_not_called()

    def test_rechazo_sin_evento_bot_conserva_comportamiento_terminal(self):
        citacion = self.crear_proceso(guia='GUIA-SIN-EVENTO-BOT')
        registro, cambiado = procesar_resultado_calidad(
            citacion,
            RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
            RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD,
            observacion='Rechazo sin evento persistido',
            usuario=self.calidad,
            responsable_sistema='BOT_CALIDAD_EXCEL',
        )

        citacion.refresh_from_db()
        self.assertTrue(cambiado)
        self.assertEqual(registro.RCO_CESTADO, registro.Estado.RECHAZADO)
        self.assertEqual(citacion.CI_CESTADO, 'RECHAZADO')

    def test_estado_intermedio_no_se_puede_forzar_sin_rechazo_bot(self):
        citacion = self.crear_proceso(guia='GUIA-INTERMEDIO-FORZADO')
        with self.assertRaisesMessage(ValueError, 'solo puede originarse'):
            procesar_resultado_calidad(
                citacion,
                RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION,
                RESULTADO_CALIDAD_OPERACION.Origen.REVISION_MANUAL,
                usuario=self.calidad,
            )

    def test_rechazo_bot_no_cambia_otras_recepciones_ni_despachos(self):
        casos = (
            (self.empresa_1, 'RECEPCION', 'RECEPCION_ESTANQUE_SBH', 'empresa-1-recepcion'),
            (self.empresa_2, 'RECEPCION', 'RECEPCION_TRASVASIJE', 'empresa-2-otra-recepcion'),
            (self.empresa_2, 'DESPACHO', 'EST_SBH_CLIENTE', 'empresa-2-despacho'),
            (self.empresa_1, 'DESPACHO', 'EST_SBH_CLIENTE', 'empresa-1-despacho'),
        )
        for empresa, tipo, codigo, sufijo in casos:
            with self.subTest(empresa=empresa.pk, tipo=tipo, codigo=codigo):
                citacion = self.crear_proceso(
                    empresa=empresa,
                    tipo=tipo,
                    codigo=codigo,
                    guia=f'GUIA-{sufijo}',
                )
                with patch.object(
                    calidad_service,
                    '_crear_borrador_sap_recepcion_interno_post_commit',
                ) as crear_draft:
                    with self.captureOnCommitCallbacks(execute=True) as callbacks:
                        response = self.post_bot(
                            citacion,
                            'RECHAZADO',
                            f'bot-{sufijo}',
                        )

                citacion.refresh_from_db()
                resultado = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(resultado.RCO_CESTADO, resultado.Estado.RECHAZADO)
                self.assertNotEqual(
                    resultado.RCO_CESTADO,
                    resultado.Estado.RECHAZADO_PENDIENTE_REVISION,
                )
                self.assertTrue(resultado.RCO_BAUTORIZA_SALIDA)
                self.assertEqual(citacion.CI_CESTADO, 'RECHAZADO')
                self.assertEqual(callbacks, [])
                crear_draft.assert_not_called()


def citacion_codigo_seguro(codigo):
    return ''.join(caracter for caracter in codigo if caracter.isalnum())[:30]
