from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    RESULTADO_CALIDAD_OPERACION,
    SECUENCIA,
)
from apps.home.services.calidad_service import (
    PASO_ANALISIS_CALIDAD,
    asegurar_calidad_iniciada,
    procesar_resultado_calidad,
    serializar_resultado_calidad,
)
from apps.home.services.trazabilidad_service import construir_resultados_trazabilidad, queryset_citaciones_trazabilidad


class CalidadServiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('calidad_test', password='test')
        cls.empresa = cls._empresa('Calidad Uno', '11-1')
        cls.otra_empresa = cls._empresa('Calidad Dos', '22-2')
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE='Calidad',
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
            CA_NDIA=1, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=20,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA', SE_CNOMBRE='RECEPCION BODEGA EXTERNA',
            SE_BHABILITADO=True,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=20,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='ANALISIS_Y_CALIDAD', ET_CNOMBRE='Analisis y calidad',
            ET_NCANTIDADMAXIMA=20, ET_BHABILITADO=True,
        )

    @staticmethod
    def _empresa(nombre, rut):
        return EMPRESA.objects.create(
            EP_CRAZONSOCIAL=nombre, EP_CRUT=rut, EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test', EP_CPORT='0',
        )

    def crear_citacion(self, guia='GUIA-CALIDAD'):
        citacion = CITACION.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            SC_NID=self.secuencia, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE', CI_CNUMERODOCUMENTO=guia,
        )
        ETAPA_LOG.objects.create(
            CI_NID=citacion, EP_NID=self.empresa, SC_NID=self.secuencia,
            ET_NID=self.etapa, US_INICIO_ID=self.user, EL_FFECHAINICIO=timezone.now(),
        )
        return citacion

    def test_inicio_pendiente_idempotente_y_temporizador_activo(self):
        citacion = self.crear_citacion()
        inicio = timezone.now() - timedelta(minutes=3)
        registro, creado = asegurar_calidad_iniciada(citacion, self.user, fecha_inicio=inicio)
        repetido, creado_repetido = asegurar_calidad_iniciada(citacion, self.user)

        self.assertTrue(creado)
        self.assertFalse(creado_repetido)
        self.assertEqual(registro.pk, repetido.pk)
        self.assertEqual(registro.RCO_CESTADO, RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE)
        self.assertTrue(registro.temporizador_activo)
        self.assertEqual(RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=citacion).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_INICIO').count(), 1)

    def test_aprobado_detiene_cierra_y_avanza_una_vez(self):
        citacion = self.crear_citacion()
        asegurar_calidad_iniciada(citacion, self.user, fecha_inicio=timezone.now() - timedelta(minutes=2))
        registro, cambiado = procesar_resultado_calidad(
            citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user,
        )
        repetido, cambio_repetido = procesar_resultado_calidad(
            citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user,
        )

        self.assertTrue(cambiado)
        self.assertFalse(cambio_repetido)
        self.assertIsNotNone(registro.RCO_FDETENCION_TEMPORIZADOR)
        self.assertIsNotNone(registro.RCO_FCIERRE)
        self.assertTrue(registro.RCO_BCIERRE_AUTOMATICO)
        self.assertGreaterEqual(registro.RCO_NDURACION_SEGUNDOS, 119)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=PASO_ANALISIS_CALIDAD).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_AVANCE_AUTOMATICO').count(), 1)
        self.assertEqual(registro.pk, repetido.pk)

    def test_rechazado_bodega_externa_no_cierra_operacion_y_autoriza_salida(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(
            citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user,
        )
        citacion.refresh_from_db()

        self.assertEqual(citacion.CI_CESTADO, 'PENDIENTE')
        self.assertTrue(registro.RCO_BAUTORIZA_SALIDA)
        self.assertIsNotNone(registro.RCO_FDETENCION_TEMPORIZADOR)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_AVANCE_AUTOMATICO').exists())
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_SALIDA_AUTORIZADA').exists())

    def test_rechazado_mantiene_regla_actual_en_recepcion_normal(self):
        secuencia_normal = SECUENCIA.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_ESTANQUE_SBH', SE_CNOMBRE='RECEPCION ESTANQUE SBH',
            SE_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SC_NID=secuencia_normal,
            ET_NID=self.etapa, SE_NPASO=1, SE_BHABILITADO=True, SE_BOBLIGATORIO=True,
        )
        citacion = self.crear_citacion('GUIA-RECEPCION-NORMAL')
        citacion.SC_NID = secuencia_normal
        citacion.save(update_fields=['SC_NID'])

        procesar_resultado_calidad(
            citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            usuario=self.user,
        )
        citacion.refresh_from_db()

        self.assertEqual(citacion.CI_CESTADO, 'RECHAZADO')

    def test_aprueba_cliente_detiene_y_mantiene_abierta_hasta_aprobacion(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(
            citacion, 'APRUEBA_CLIENTE', RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD, usuario=self.user,
        )
        self.assertIsNotNone(registro.RCO_FDETENCION_TEMPORIZADOR)
        self.assertIsNotNone(registro.RCO_FSOLICITUD_CLIENTE)
        self.assertIsNone(registro.RCO_FCIERRE)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=PASO_ANALISIS_CALIDAD).exists())

        registro, _ = procesar_resultado_calidad(
            citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE, usuario=self.user,
        )
        self.assertIsNotNone(registro.RCO_FRESOLUCION_FINAL)
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_RESPUESTA_CLIENTE_APROBADA').exists())
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_AVANCE_AUTOMATICO').exists())

    def test_aprueba_cliente_puede_terminar_rechazado(self):
        citacion = self.crear_citacion()
        procesar_resultado_calidad(citacion, 'APRUEBA_CLIENTE', RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD, usuario=self.user)
        registro, _ = procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE, usuario=self.user)
        self.assertTrue(registro.RCO_BAUTORIZA_SALIDA)
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_RESPUESTA_CLIENTE_RECHAZADA').exists())

    def test_transicion_invalida_no_modifica_resultado_definitivo(self):
        citacion = self.crear_citacion()
        procesar_resultado_calidad(citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        with self.assertRaisesMessage(ValueError, 'Transicion de calidad no permitida'):
            procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)

    def test_comando_controla_guia_inexistente_y_empresa(self):
        with self.assertRaises(CommandError):
            call_command(
                'actualizar_estado_calidad', guia='NO-EXISTE', estado='APROBADO',
                empresa_id=self.otra_empresa.id, usuario=self.user.username,
            )

    def test_trazabilidad_incluye_cambio_calidad_y_datos_requeridos(self):
        citacion = self.crear_citacion('GUIA-TRACE-CAL')
        procesar_resultado_calidad(
            citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
            observacion='Fuera de especificacion', usuario=self.user,
        )
        citacion_traza = queryset_citaciones_trazabilidad(self.empresa.id).get(pk=citacion.pk)
        resultado = construir_resultados_trazabilidad([citacion_traza])[0]
        eventos = [item for item in resultado['etapas'] if item['tipo_evento'] == 'calidad']
        self.assertEqual(eventos[-1]['estado'], 'RECHAZADO')
        self.assertIn('GUIA-TRACE-CAL', repr(eventos[-1]))
        self.assertIn('Fuera de especificacion', repr(eventos[-1]))

    def test_serializacion_expone_reloj_mensaje_e_historial(self):
        citacion = self.crear_citacion()
        registro, _ = asegurar_calidad_iniciada(citacion, self.user)
        payload = serializar_resultado_calidad(registro, ahora=registro.RCO_FINICIO + timedelta(seconds=65))
        self.assertEqual(payload['duracion_legible'], '00:01:05')
        self.assertTrue(payload['temporizador_activo'])
        self.assertEqual(payload['mensaje'], 'En espera de resultados de análisis')
        self.assertEqual(payload['historial'][0]['estado_nuevo'], 'PENDIENTE')

    def test_recarga_no_duplica_historial_de_inicio(self):
        citacion = self.crear_citacion()
        asegurar_calidad_iniciada(citacion, self.user)
        registro, _ = asegurar_calidad_iniciada(citacion, self.user)
        self.assertEqual(registro.historial.filter(RCH_CEVENTO='CALIDAD_INICIO').count(), 1)

    def test_aprobado_deja_temporizador_inactivo(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        self.assertFalse(registro.temporizador_activo)

    def test_aprobado_registra_cierre_automatico_una_vez(self):
        citacion = self.crear_citacion()
        procesar_resultado_calidad(citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO='CALIDAD_CIERRE_AUTOMATICO').count(), 1)

    def test_rechazado_deja_temporizador_inactivo(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        self.assertFalse(registro.temporizador_activo)

    def test_rechazo_es_visible_para_guardia(self):
        from apps.home.views import _mensaje_estado_camion

        citacion = self.crear_citacion()
        procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        self.assertEqual(
            _mensaje_estado_camion(citacion, PASO_ANALISIS_CALIDAD, False, False),
            'Camión autorizado para salir de planta por rechazo de calidad',
        )

    def test_aprueba_cliente_no_reinicia_reloj(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(citacion, 'APRUEBA_CLIENTE', RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD, usuario=self.user)
        detencion = registro.RCO_FDETENCION_TEMPORIZADOR
        registro, _ = procesar_resultado_calidad(citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE, usuario=self.user)
        self.assertEqual(registro.RCO_FDETENCION_TEMPORIZADOR, detencion)

    def test_ejecucion_duplicada_no_repite_historial_final(self):
        citacion = self.crear_citacion()
        procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        procesar_resultado_calidad(citacion, 'RECHAZADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        registro = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(registro.historial.filter(RCH_CESTADO_NUEVO='RECHAZADO').count(), 1)

    def test_resultado_respeta_empresa_de_la_citacion(self):
        citacion = self.crear_citacion()
        registro, _ = procesar_resultado_calidad(citacion, 'APROBADO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)
        self.assertEqual(registro.EP_NID_id, self.empresa.id)
        self.assertFalse(RESULTADO_CALIDAD_OPERACION.objects.filter(EP_NID=self.otra_empresa, CI_NID=citacion).exists())

    def test_estado_desconocido_es_rechazado(self):
        citacion = self.crear_citacion()
        with self.assertRaisesMessage(ValueError, 'Estado de calidad no valido'):
            procesar_resultado_calidad(citacion, 'DESCONOCIDO', RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA, usuario=self.user)

    def test_origen_desconocido_es_rechazado(self):
        citacion = self.crear_citacion()
        with self.assertRaisesMessage(ValueError, 'Origen de calidad no valido'):
            procesar_resultado_calidad(citacion, 'APROBADO', 'BOT_NO_REGISTRADO', usuario=self.user)

    def test_citacion_historica_sin_calidad_sigue_en_trazabilidad(self):
        citacion = self.crear_citacion('GUIA-HISTORICA')
        citacion_traza = queryset_citaciones_trazabilidad(self.empresa.id).get(pk=citacion.pk)
        resultado = construir_resultados_trazabilidad([citacion_traza])[0]
        self.assertEqual(resultado['cabecera']['numero_guia'], 'GUIA-HISTORICA')
        self.assertFalse(any(item['tipo_evento'] == 'calidad' for item in resultado['etapas']))
