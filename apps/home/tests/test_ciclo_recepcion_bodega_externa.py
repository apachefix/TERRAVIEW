from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    DATO_OPERACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    RESULTADO_CALIDAD_HISTORIAL,
    RESULTADO_CALIDAD_OPERACION,
    SECUENCIA,
    SYSLOGGER,
    USERS_EMPRESA,
)
from apps.home.services.calidad_service import asegurar_calidad_iniciada, procesar_resultado_calidad
from apps.home.views import (
    EVENTO_RECEPCION_BODEGA_EXTERNA_REGRESO,
    EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
    PASO_CICLO_DESCARGA,
    _calidad_inicia_al_finalizar_toma_muestra,
    _finalizar_ciclo_recepcion_bodega_externa,
    _finalizar_tiempo_toma_muestra,
    _iniciar_ciclo_recepcion_bodega_externa,
    _payload_ciclo_recepcion_bodega_externa,
    _registrar_toma_muestra_accion,
    es_recepcion_bodega_externa_operacion,
    obtener_paso_activo_operacion,
    obtener_pasos_operacion_citacion,
)


class CicloRecepcionBodegaExternaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.sala_control = User.objects.create_user('Sala_Control', password='test')
        cls.asistente_cd = User.objects.create_user('Asistente_C_D', password='test')
        cls.guardia = User.objects.create_user('Guardia_Porteria', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        USERS_EMPRESA.objects.create(US_NID=cls.sala_control, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.asistente_cd, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.guardia, EP_NID=cls.empresa)
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Ciclo bodega externa',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=22,
            CA_NMES=7,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA',
            SE_CNOMBRE='Bodega Externa',
            SE_BHABILITADO=True,
        )
        cls.etapa_ciclo = ETAPA.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='SECUENCIA TERMINADA RACV2',
            ET_CNOMBRE='SECUENCIA TERMINADA RACV2',
            ET_NCANTIDADMAXIMA=10,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=cls.etapa_ciclo,
            SE_NPASO=1,
            SE_BHABILITADO=True,
            SE_BOBLIGATORIO=True,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.sala_control,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-BEXT',
        )

    def setUp(self):
        for paso in [
            'Habilitar Operacion Planta',
            'Pesaje Entrada',
            'Toma de muestra',
        ]:
            OPERACION_PLANTA_LOG.objects.create(
                US_NID=self.sala_control,
                EP_NID=self.empresa,
                PL_NID=self.planificacion,
                CI_NID=self.citacion,
                OPL_CPASO=paso,
                OPL_CPERFIL_RESPONSABLE='TEST',
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )

    def habilitar_operacion_planta(self):
        return SYSLOGGER.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='TEST',
            LOG_CDESCRIPCION='Habilitada para Operacion Planta',
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.citacion.id),
        )

    def url_inicio_viaje(self):
        return '{}?_empresa_id={}'.format(
            reverse('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa', args=[self.citacion.id]),
            self.empresa.id,
        )

    def url_retorno_viaje(self):
        return '{}?_empresa_id={}'.format(
            reverse('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa', args=[self.citacion.id]),
            self.empresa.id,
        )

    def test_inicio_y_cierre_ciclo_externo_son_idempotentes(self):
        self.assertTrue(es_recepcion_bodega_externa_operacion(self.citacion))
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], PASO_CICLO_DESCARGA)
        log_heredado = OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.sala_control,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

        inicio = timezone.now() - timedelta(minutes=35)
        regreso = inicio + timedelta(minutes=35)
        with patch('apps.home.views.timezone.now', return_value=inicio):
            payload_inicio, creado_inicio = _iniciar_ciclo_recepcion_bodega_externa(
                self.citacion,
                self.sala_control,
            )
        payload_repetido, creado_repetido = _iniciar_ciclo_recepcion_bodega_externa(
            self.citacion,
            self.sala_control,
        )

        self.assertTrue(creado_inicio)
        self.assertFalse(creado_repetido)
        self.assertTrue(payload_inicio['en_proceso'])
        self.assertEqual(payload_inicio['inicio_iso'], payload_repetido['inicio_iso'])
        self.assertEqual(DATO_OPERACION.objects.filter(CI_NID=self.citacion, CAMP_NID__CA_CCODIGO='OP_CICLO_DESCARGA').count(), 1)
        log_viaje = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA)
        self.assertEqual(log_viaje.OPL_CESTADO, OPERACION_PLANTA_LOG.ESTADO_PENDIENTE)
        self.assertEqual(log_viaje.id, log_heredado.id)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=PASO_CICLO_DESCARGA).exists())
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], PASO_CICLO_DESCARGA)

        with patch('apps.home.views.timezone.now', return_value=regreso):
            payload_fin, creado_fin = _finalizar_ciclo_recepcion_bodega_externa(
                self.citacion,
                self.guardia,
                'Camion regreso sin novedades.',
            )
        payload_fin_repetido, creado_fin_repetido = _finalizar_ciclo_recepcion_bodega_externa(
            self.citacion,
            self.guardia,
        )

        self.assertTrue(creado_fin)
        self.assertFalse(creado_fin_repetido)
        self.assertTrue(payload_fin['finalizada'])
        self.assertEqual(payload_fin['fin_iso'], payload_fin_repetido['fin_iso'])
        self.assertEqual(payload_fin['duracion_segundos'], 2100)
        log_viaje.refresh_from_db()
        self.assertEqual(log_viaje.OPL_CESTADO, OPERACION_PLANTA_LOG.ESTADO_COMPLETADO)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_REGRESO).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=PASO_CICLO_DESCARGA).count(), 1)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='REC_BEXT_SALIDA').count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='REC_BEXT_REGRESO').count(), 1)

    def test_asistente_cd_autoriza_salida_y_queda_registrado(self):
        self.habilitar_operacion_planta()
        self.client.force_login(self.asistente_cd)

        response = self.client.post(self.url_inicio_viaje())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['creado'])
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO='OP_CICLO_DESCARGA',
            ).count(),
            1,
        )
        payload = _payload_ciclo_recepcion_bodega_externa(self.citacion)
        self.assertTrue(payload['en_proceso'])
        self.assertEqual(payload['usuario_inicio'], self.asistente_cd.username)
        log_salida = OPERACION_PLANTA_LOG.objects.get(
            CI_NID=self.citacion,
            OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
        )
        self.assertEqual(log_salida.US_NID, self.asistente_cd)
        self.assertEqual(log_salida.OPL_CPERFIL_RESPONSABLE, 'ASISTENTE C D')
        self.assertTrue(
            SYSLOGGER.objects.filter(
                LOG_CADD1=str(self.citacion.id),
                US_NID=self.asistente_cd,
                LOG_COPERACION='REC_BEXT_SALIDA',
            ).exists()
        )

    def test_sala_control_y_guardia_no_pueden_autorizar_salida(self):
        self.habilitar_operacion_planta()

        for usuario in (self.sala_control, self.guardia):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                response = self.client.post(self.url_inicio_viaje())
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json()['message'],
                    'Solo Asistente_C_D puede autorizar la salida a Bodega Externa.',
                )
                self.assertFalse(
                    DATO_OPERACION.objects.filter(
                        CI_NID=self.citacion,
                        CAMP_NID__CA_CCODIGO='OP_CICLO_DESCARGA',
                    ).exists()
                )
                self.assertFalse(
                    OPERACION_PLANTA_LOG.objects.filter(
                        CI_NID=self.citacion,
                        OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
                    ).exists()
                )
                self.assertFalse(
                    SYSLOGGER.objects.filter(
                        LOG_CADD1=str(self.citacion.id),
                        LOG_COPERACION='REC_BEXT_SALIDA',
                    ).exists()
                )

    def test_guardia_porteria_conserva_cierre_exclusivo(self):
        self.habilitar_operacion_planta()
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        self.client.force_login(self.guardia)

        response = self.client.post(
            self.url_retorno_viaje(),
            {'observacion': 'Retorno confirmado por Guardia Porteria.'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['creado'])
        payload = _payload_ciclo_recepcion_bodega_externa(self.citacion)
        self.assertTrue(payload['finalizada'])
        self.assertEqual(payload['usuario_fin'], self.guardia.username)
        log_salida = OPERACION_PLANTA_LOG.objects.get(
            CI_NID=self.citacion,
            OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
        )
        self.assertEqual(log_salida.OPL_CESTADO, OPERACION_PLANTA_LOG.ESTADO_COMPLETADO)
        log_retorno = OPERACION_PLANTA_LOG.objects.get(
            CI_NID=self.citacion,
            OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_REGRESO,
        )
        self.assertEqual(log_retorno.US_NID, self.guardia)
        self.assertEqual(log_retorno.OPL_CPERFIL_RESPONSABLE, 'GUARDIA PORTERIA')

    def test_payload_vacio_no_muestra_contador(self):
        payload = _payload_ciclo_recepcion_bodega_externa(self.citacion)

        self.assertFalse(payload['iniciada'])
        self.assertEqual(payload['estado'], 'PENDIENTE DE AUTORIZACION')
        self.assertEqual(payload['duracion_legible'], '00:00:00')

    def registrar_paso(self, paso):
        return OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.sala_control,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO=paso,
            OPL_CPERFIL_RESPONSABLE='TEST',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

    def completar_salida_definitiva(self):
        for paso in ['Pesaje Salida', 'Autorizar Salida', 'Confirmar Salida']:
            self.registrar_paso(paso)
        fecha_termino = timezone.now()
        self.citacion.CI_CESTADO = 'TERMINADO'
        self.citacion.CI_FFECHATERMINO = fecha_termino
        self.citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHATERMINO'])
        return fecha_termino

    def _preparar_toma_muestra_activa(self):
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Toma de muestra',
        ).delete()
        self.habilitar_operacion_planta()
        self.client.force_login(self.asistente_cd)

    def _url_accion_toma_muestra(self):
        return '{}?_empresa_id={}'.format(
            reverse(
                'ajax_operacion_planta_registrar_accion_toma_muestra',
                args=[self.citacion.id],
            ),
            self.empresa.id,
        )

    def _url_finalizar_toma_muestra(self):
        return '{}?_empresa_id={}'.format(
            reverse('operacion_planta_guardar_paso', args=[self.citacion.id]),
            self.empresa.id,
        )

    def test_muestra_enviada_no_inicia_calidad_antes_de_finalizar(self):
        self._preparar_toma_muestra_activa()

        response = self.client.post(self._url_accion_toma_muestra())
        response_repetido = self.client.post(self._url_accion_toma_muestra())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_repetido.status_code, 200)
        self.assertFalse(
            RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=self.citacion).exists()
        )
        self.assertFalse(
            RESULTADO_CALIDAD_HISTORIAL.objects.filter(
                CI_NID=self.citacion,
                RCH_CEVENTO='CALIDAD_INICIO',
            ).exists()
        )
        self.assertFalse(
            DATO_OPERACION.objects.filter(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO='OP_RESULTADO_CALIDAD',
            ).exists()
        )

        recarga = self.client.get(
            reverse('operacion_planta_citacion', args=[self.citacion.id]),
            {'_empresa_id': self.empresa.id},
        )
        self.assertEqual(recarga.status_code, 200)
        self.assertFalse(
            RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=self.citacion).exists()
        )
        self.assertFalse(
            RESULTADO_CALIDAD_HISTORIAL.objects.filter(
                CI_NID=self.citacion,
                RCH_CEVENTO='CALIDAD_INICIO',
            ).exists()
        )
        pasos = {paso['nombre']: paso for paso in recarga.context['pasos']}
        self.assertFalse(pasos['Toma de muestra']['calidad_paralela'])
        self.assertFalse(pasos['Toma de muestra']['requiere_resultado_calidad'])

    def test_finalizar_toma_inicia_calidad_con_mismo_timestamp_y_es_idempotente(self):
        self._preparar_toma_muestra_activa()
        inicio = timezone.now() - timedelta(minutes=3)
        fin = inicio + timedelta(minutes=3)

        with patch('apps.home.views.timezone.now', return_value=inicio):
            response_inicio = self.client.post(self._url_accion_toma_muestra())
        self.assertEqual(response_inicio.status_code, 200)
        self.assertFalse(
            RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=self.citacion).exists()
        )

        with patch('apps.home.views.timezone.now', return_value=fin):
            response_fin = self.client.post(
                self._url_finalizar_toma_muestra(),
                {'paso': 'Toma de muestra'},
            )

        self.assertEqual(response_fin.status_code, 200)
        calidad = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=self.citacion)
        self.assertEqual(
            calidad.RCO_CESTADO,
            RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE,
        )
        self.assertEqual(
            calidad.RCO_CORIGEN,
            RESULTADO_CALIDAD_OPERACION.Origen.OPERACION_PLANTA,
        )
        self.assertEqual(calidad.RCO_FINICIO, fin)
        self.assertEqual(calidad.US_NID, self.asistente_cd)
        self.assertEqual(
            calidad.RCO_COBSERVACION,
            'En espera de resultados de análisis',
        )
        historial_inicio = calidad.historial.get(RCH_CEVENTO='CALIDAD_INICIO')
        self.assertEqual(historial_inicio.RCH_FFECHAREGISTRO, fin)

        response_repetido = self.client.post(
            self._url_finalizar_toma_muestra(),
            {'paso': 'Toma de muestra'},
        )
        self.assertEqual(response_repetido.status_code, 409)
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_FINICIO, fin)
        self.assertEqual(
            RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=self.citacion).count(),
            1,
        )
        self.assertEqual(calidad.historial.filter(RCH_CEVENTO='CALIDAD_INICIO').count(), 1)

        recarga = self.client.get(
            reverse('operacion_planta_citacion', args=[self.citacion.id]),
            {'_empresa_id': self.empresa.id},
        )
        self.assertEqual(recarga.status_code, 200)
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_FINICIO, fin)
        self.assertEqual(calidad.historial.filter(RCH_CEVENTO='CALIDAD_INICIO').count(), 1)
        pasos = {paso['nombre']: paso for paso in recarga.context['pasos']}
        self.assertTrue(pasos['Toma de muestra']['calidad_paralela'])
        self.assertTrue(pasos['Toma de muestra']['requiere_resultado_calidad'])

    def test_diferimiento_calidad_esta_aislado_a_empresa_2_y_flujo_exacto(self):
        self.assertTrue(_calidad_inicia_al_finalizar_toma_muestra(self.citacion))

        for codigo, tipo in (
            ('RECEPCION_ESTANQUE_SBH', 'RECEPCION'),
            ('RECEPCION_PROSESA_PISO_1', 'RECEPCION'),
            ('RECEPCION_PROSESA_PISO_2', 'RECEPCION'),
            ('RECEPCION_TRASVASIJE', 'RECEPCION'),
            ('RECEPCION_BODEGA_EXTERNA', 'DESPACHO'),
        ):
            with self.subTest(codigo=codigo, tipo=tipo):
                self.citacion.SC_NID.SE_CCODIGO = codigo
                self.citacion.CI_CTIPO = tipo
                self.assertFalse(
                    _calidad_inicia_al_finalizar_toma_muestra(self.citacion)
                )

        self.citacion.SC_NID.SE_CCODIGO = 'RECEPCION_BODEGA_EXTERNA'
        self.citacion.CI_CTIPO = 'RECEPCION'
        self.citacion.EP_NID_id = 1
        self.assertFalse(_calidad_inicia_al_finalizar_toma_muestra(self.citacion))

    def test_a_calidad_aprobada_antes_del_retorno_no_bloquea(self):
        calidad, _ = asegurar_calidad_iniciada(self.citacion, self.sala_control)
        self.assertEqual(calidad.RCO_CESTADO, 'PENDIENTE')
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        calidad, _ = procesar_resultado_calidad(
            self.citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], PASO_CICLO_DESCARGA)
        self.assertEqual(calidad.RCO_CESTADO, 'APROBADO')
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, 'EN PROCESO')
        self.assertEqual(
            OPERACION_PLANTA_LOG.objects.get(
                CI_NID=self.citacion,
                OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
            ).OPL_CESTADO,
            OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
        )

        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')

    def test_b_calidad_aprobada_despues_del_retorno_no_retrocede(self):
        asegurar_calidad_iniciada(self.citacion, self.sala_control)
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')

        calidad, _ = procesar_resultado_calidad(
            self.citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.assertEqual(calidad.RCO_CESTADO, 'APROBADO')
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')

    def test_c_calidad_aprobada_despues_pesaje_salida_no_retrocede(self):
        asegurar_calidad_iniciada(self.citacion, self.sala_control)
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        self.registrar_paso('Pesaje Salida')
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Autorizar Salida')

        procesar_resultado_calidad(
            self.citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Autorizar Salida')
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, 'EN PROCESO')

    def test_d_calidad_aprobada_despues_confirmar_salida_conserva_cierre(self):
        asegurar_calidad_iniciada(self.citacion, self.sala_control)
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        fecha_termino = self.completar_salida_definitiva()

        calidad, _ = procesar_resultado_calidad(
            self.citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.citacion.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, 'APROBADO')
        self.assertEqual(self.citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.citacion.CI_FFECHATERMINO, fecha_termino)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')

    def test_e_calidad_rechazada_antes_del_retorno_no_bloquea(self):
        asegurar_calidad_iniciada(self.citacion, self.sala_control)
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)

        calidad, _ = procesar_resultado_calidad(
            self.citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.citacion.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, 'RECHAZADO')
        self.assertEqual(self.citacion.CI_CESTADO, 'EN PROCESO')
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], PASO_CICLO_DESCARGA)
        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')

    def test_f_calidad_rechazada_despues_cierre_conserva_operacion(self):
        asegurar_calidad_iniciada(self.citacion, self.sala_control)
        _iniciar_ciclo_recepcion_bodega_externa(self.citacion, self.asistente_cd)
        _finalizar_ciclo_recepcion_bodega_externa(self.citacion, self.guardia)
        fecha_termino = self.completar_salida_definitiva()

        calidad, _ = procesar_resultado_calidad(
            self.citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.sala_control,
        )

        self.citacion.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, 'RECHAZADO')
        self.assertEqual(self.citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.citacion.CI_FFECHATERMINO, fecha_termino)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')

    def test_i_recarga_con_viaje_abierto_conserva_temporizador(self):
        inicio = timezone.now() - timedelta(minutes=12)
        with patch('apps.home.views.timezone.now', return_value=inicio):
            payload_inicio, _ = _iniciar_ciclo_recepcion_bodega_externa(
                self.citacion, self.asistente_cd,
            )

        payload_recarga = _payload_ciclo_recepcion_bodega_externa(self.citacion)

        self.assertTrue(payload_recarga['en_proceso'])
        self.assertEqual(payload_recarga['inicio_iso'], payload_inicio['inicio_iso'])
        self.assertNotEqual(payload_recarga['duracion_legible'], '00:00:00')

    def test_j_otros_flujos_conservan_calidad_y_ciclo_descarga(self):
        casos = [
            ('RECEPCION_ESTANQUE_SBH', 'RECEPCION ESTANQUE SBH', 'RECEPCION'),
            ('RECEPCION_TRASVASIJE', 'RECEPCION TRASVASIJE', 'RECEPCION'),
            ('EST_SBH_CLIENTE', 'Despacho desde Estanque SBH', 'DESPACHO'),
        ]
        for indice, (codigo, nombre, tipo) in enumerate(casos, start=1):
            secuencia = SECUENCIA.objects.create(
                US_NID=self.sala_control,
                EP_NID=self.empresa,
                SE_CTIPO=tipo,
                SE_CCODIGO=codigo,
                SE_CNOMBRE=nombre,
                SE_BHABILITADO=True,
            )
            citacion = CITACION.objects.create(
                US_NID=self.sala_control,
                EP_NID=self.empresa,
                PL_NID=self.planificacion,
                SC_NID=secuencia,
                CI_FFECHAREGISTRO=timezone.now(),
                CI_FFECHACITACION=timezone.now(),
                CI_NCUPO=indice + 1,
                CI_CTIPO=tipo,
                CI_CESTADO='EN PROCESO',
            )
            nombres = [paso for paso, _ in obtener_pasos_operacion_citacion(citacion)[1]]
            self.assertIn(PASO_CICLO_DESCARGA, nombres)
            self.assertFalse(es_recepcion_bodega_externa_operacion(citacion))
            if tipo == 'RECEPCION':
                self.assertIn('Analisis y calidad', nombres)
                self.assertIn('Resultado Calidad', nombres)

        nombres_especiales = [
            paso for paso, _ in obtener_pasos_operacion_citacion(self.citacion)[1]
        ]
        self.assertNotIn('Analisis y calidad', nombres_especiales)
        self.assertNotIn('Resultado Calidad', nombres_especiales)
        self.assertIn(PASO_CICLO_DESCARGA, nombres_especiales)
    def test_panel_toma_muestra_muestra_calidad_paralela_y_relojes_compartidos(self):
        _registrar_toma_muestra_accion(
            self.citacion,
            self.sala_control,
            'RECEPCION BODEGA EXTERNA',
        )
        fin_toma = timezone.now()
        with patch('apps.home.views.timezone.now', return_value=fin_toma):
            _finalizar_tiempo_toma_muestra(
                self.citacion,
                self.sala_control,
                'RECEPCION BODEGA EXTERNA',
            )
        asegurar_calidad_iniciada(
            self.citacion,
            self.sala_control,
            fecha_inicio=fin_toma,
        )
        _iniciar_ciclo_recepcion_bodega_externa(
            self.citacion,
            self.asistente_cd,
        )
        SYSLOGGER.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='TEST',
            LOG_CDESCRIPCION='Habilitada para Operacion Planta',
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.citacion.id),
        )
        self.client.force_login(self.asistente_cd)

        response = self.client.get(
            reverse('operacion_planta_citacion', args=[self.citacion.id]),
            {'_empresa_id': self.empresa.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=self.citacion).exists()
        )
        pasos = {paso['nombre']: paso for paso in response.context['pasos']}
        self.assertTrue(pasos['Toma de muestra']['seleccionado'])
        self.assertTrue(pasos['Toma de muestra']['requiere_resultado_calidad'])
        self.assertTrue(pasos['Toma de muestra']['calidad_paralela'])
        self.assertTrue(pasos['Toma de muestra']['requiere_ciclo_bodega_externa'])
        self.assertTrue(pasos['Toma de muestra']['puede_operar_ciclo_bodega_externa'])
        self.assertTrue(pasos[PASO_CICLO_DESCARGA]['oculto_visual'])
        self.assertContains(response, 'SALIDA A BODEGA EXTERNA')
        self.assertContains(response, 'Proceso paralelo al avance operacional del camion')
        self.assertContains(
            response,
            'Responsable inicio: Asistente_C_D | Responsable cierre: Guardia Porteria',
        )
        self.assertContains(response, 'Camion en Bodega Externa')
        self.assertContains(response, '<svg class="op-vapor-hourglass', count=3)
        self.assertContains(response, 'op-vapor-hourglass is-finished', count=1)
        self.assertContains(response, 'op-vapor-hourglass is-active', count=2)
        self.assertTrue(pasos['Toma de muestra']['puede_iniciar_ciclo_bodega_externa'])

        self.client.force_login(self.sala_control)
        response_sala = self.client.get(
            reverse('operacion_planta_citacion', args=[self.citacion.id]),
            {'_empresa_id': self.empresa.id},
        )
        pasos_sala = {paso['nombre']: paso for paso in response_sala.context['pasos']}
        self.assertFalse(pasos_sala['Toma de muestra']['puede_iniciar_ciclo_bodega_externa'])
        self.assertNotContains(response_sala, 'AUTORIZAR SALIDA A BODEGA EXTERNA')