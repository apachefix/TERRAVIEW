import json
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CITACION,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    SECUENCIA,
)


class SalidaTemporalProsesaPiso1Tests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.asistente = User.objects.create_user('Asistente_C_D', password='test')
        self.guardia = User.objects.create_user('Guardia_Porteria', password='test')
        self.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='Empresa 2',
            EP_CRUT='2-7',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        self.calendario = CALENDARIO.objects.create(
            US_NID=self.asistente,
            EP_NID=self.empresa,
            CA_CNOMBRE='Prosesa Piso 1',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=1,
        )
        self.planificacion = PLANIFICACION.objects.create(
            US_NID=self.asistente,
            EP_NID=self.empresa,
            CAL_NID=self.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=1,
        )
        self.secuencia = SECUENCIA.objects.create(
            US_NID=self.asistente,
            EP_NID=self.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_PROSESA_PISO_1',
            SE_CNOMBRE='Recepcion Prosesa Piso 1',
            SE_BHABILITADO=True,
        )
        self.etapa = ETAPA.objects.create(
            US_NID=self.asistente,
            EP_NID=self.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='OPERACION_PROSESA_PISO_1',
            ET_CNOMBRE='Operacion Prosesa Piso 1',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        self.citacion = CITACION.objects.create(
            id=38724,
            US_NID=self.asistente,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='57950',
        )
        ETAPA_LOG.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            US_INICIO_ID=self.asistente,
            EL_FFECHAINICIO=timezone.now(),
        )
        self.camion = CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            CPA_CPATENTE='WR7934',
            CPA_CNOMBRE_CONDUCTOR='Conductor',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CNUMERO_GUIA='57950',
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.guardia,
            US_ASOCIA_ID=self.asistente,
            CPA_FFECHAASOCIACION=timezone.now(),
        )
        self.log_pesaje = OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.asistente,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO='Pesaje Entrada',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

    def iniciar(self, fecha=None):
        contexto = patch.object(views, '_registrar_syslog_operacion_planta')
        if fecha is None:
            with contexto:
                return views._iniciar_salida_temporal_prosesa_piso_1(
                    self.citacion, self.asistente
                )
        with patch.object(views.timezone, 'now', return_value=fecha), contexto:
            return views._iniciar_salida_temporal_prosesa_piso_1(
                self.citacion, self.asistente
            )

    def finalizar(self, fecha):
        with patch.object(views.timezone, 'now', return_value=fecha), patch.object(
            views, '_registrar_syslog_operacion_planta'
        ):
            return views._finalizar_salida_temporal_prosesa_piso_1(
                self.citacion, self.guardia, 'Retorno sin novedades'
            )

    def metadata(self):
        dato = DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_CICLO_DESCARGA,
        )
        return json.loads(dato.DO_CVALOR)

    def test_no_permite_iniciar_sin_pesaje_entrada_completado(self):
        self.log_pesaje.delete()
        with self.assertRaisesMessage(ValueError, 'Debe completar Pesaje Entrada'):
            self.iniciar()

    def test_inicio_persiste_timestamp_y_marca_camion_fuera_sin_avanzar(self):
        inicio = timezone.now().replace(microsecond=0)
        payload, creado = self.iniciar(inicio)

        self.assertTrue(creado)
        self.assertTrue(payload['en_proceso'])
        self.assertEqual(payload['patente'], 'WR7934')
        self.camion.refresh_from_db()
        self.assertEqual(self.camion.CPA_CESTADO, CAMION_PATIO.ESTADO_FUERA_TEMPORAL)
        self.assertEqual(self.camion.CI_NID_id, self.citacion.id)
        metadata = self.metadata()
        self.assertEqual(metadata['camion_patio_id'], self.camion.id)
        self.assertEqual(metadata['fecha_salida_iso'], inicio.isoformat())
        self.assertTrue(metadata['ciclo_externo_activo'])
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.PASO_PROSESA_DEPOSITAR_PISO_1,
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            ).exists()
        )
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.PASO_CONFIRMAR_SALIDA,
            ).exists()
        )

    def test_payload_recargado_reconstruye_timer_desde_backend(self):
        inicio = timezone.now().replace(microsecond=0)
        self.iniciar(inicio)
        with patch.object(views.timezone, 'now', return_value=inicio + timedelta(seconds=65)):
            payload = views._payload_salida_temporal_prosesa_piso_1(
                CITACION.objects.get(pk=self.citacion.pk)
            )

        self.assertTrue(payload['en_proceso'])
        self.assertEqual(payload['inicio_iso'], inicio.isoformat())
        self.assertEqual(payload['duracion_legible'], '00:01:05')

    def test_operacion_planta_expone_panel_reutilizado_en_paso_deposito(self):
        request = RequestFactory().get(f'/operacion-planta/{self.citacion.id}/')
        request.user = self.asistente
        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), patch.object(
            views, 'Verificar_empresa', return_value=self.empresa.id
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, 'operacion_planta_esta_terminada', return_value=False
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(views, 'render') as render_mock:
            views.OPERACION_PLANTA_CITACION(request, self.citacion.id)

        contexto = render_mock.call_args.args[2]
        paso = next(
            item for item in contexto['pasos']
            if item['nombre'] == views.PASO_PROSESA_DEPOSITAR_PISO_1
        )
        self.assertTrue(paso['activo'])
        self.assertTrue(paso['requiere_ciclo_bodega_externa'])
        self.assertTrue(paso['es_salida_temporal_prosesa_piso_1'])
        self.assertEqual(
            paso['ciclo_bodega_externa']['tipo_ciclo'],
            views.TIPO_CICLO_PROSESA_PISO_1_SALIDA_TEMPORAL,
        )
        self.assertNotIn(
            views.PASO_PROSESA_INGRESO_MANUAL,
            [item['nombre'] for item in contexto['pasos']],
        )

    def test_retorno_persiste_fin_duracion_y_habilita_siguiente_etapa(self):
        inicio = timezone.now().replace(microsecond=0)
        self.iniciar(inicio)
        payload, creado = self.finalizar(inicio + timedelta(seconds=125))

        self.assertTrue(creado)
        self.assertTrue(payload['finalizada'])
        self.assertEqual(payload['duracion_segundos'], 125)
        self.assertEqual(payload['duracion_legible'], '00:02:05')
        metadata = self.metadata()
        self.assertFalse(metadata['ciclo_externo_activo'])
        self.assertEqual(metadata['siguiente_etapa'], 'Pesaje Salida')
        self.camion.refresh_from_db()
        self.assertEqual(self.camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
        self.assertEqual(self.camion.CI_NID_id, self.citacion.id)
        self.assertTrue(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.PASO_PROSESA_DEPOSITAR_PISO_1,
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            ).exists()
        )
        paso_actual, _, _ = views.obtener_paso_activo_operacion(self.citacion)
        self.assertEqual(paso_actual, 'Pesaje Salida')
        paso_actual_recarga, _, _ = views.obtener_paso_activo_operacion(
            CITACION.objects.get(pk=self.citacion.pk)
        )
        self.assertEqual(paso_actual_recarga, 'Pesaje Salida')
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.PASO_PROSESA_INGRESO_MANUAL,
            ).exists()
        )
        self.assertFalse(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.PASO_CONFIRMAR_SALIDA,
            ).exists()
        )

    def test_inicio_y_retorno_son_idempotentes(self):
        inicio = timezone.now().replace(microsecond=0)
        _, creado = self.iniciar(inicio)
        _, repetido = self.iniciar(inicio + timedelta(seconds=10))
        self.assertTrue(creado)
        self.assertFalse(repetido)

        _, cerrado = self.finalizar(inicio + timedelta(seconds=30))
        _, cierre_repetido = self.finalizar(inicio + timedelta(seconds=40))
        self.assertTrue(cerrado)
        self.assertFalse(cierre_repetido)
        self.assertEqual(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO=views.EVENTO_PROSESA_PISO_1_RETORNO_PLANTA,
            ).count(),
            1,
        )

    def test_piso_2_permanece_fuera_de_esta_rama(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_PROSESA_PISO_2'
        self.secuencia.SE_CNOMBRE = 'Recepcion Prosesa Piso 2'
        self.secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])
        with self.assertRaisesMessage(ValueError, 'solo aplica'):
            self.iniciar()

    def test_guardar_paso_directo_no_permite_omitir_retorno(self):
        request = RequestFactory().post(
            f'/operacion-planta/{self.citacion.id}/guardar-paso/',
            {'paso': views.PASO_PROSESA_DEPOSITAR_PISO_1},
        )
        request.user = self.asistente
        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), patch.object(
            views, 'Verificar_empresa', return_value=self.empresa.id
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, 'operacion_planta_esta_terminada', return_value=False
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ):
            response = views.OPERACION_PLANTA_GUARDAR_PASO(request, self.citacion.id)

        self.assertEqual(response.status_code, 409)
        self.assertIn('registrar el retorno', json.loads(response.content)['message'])
