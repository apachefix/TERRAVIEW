from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
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
    SECUENCIA,
    SYSLOGGER,
)
from apps.home.views import (
    EVENTO_RECEPCION_BODEGA_EXTERNA_REGRESO,
    EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA,
    PASO_CICLO_DESCARGA,
    _finalizar_ciclo_recepcion_bodega_externa,
    _iniciar_ciclo_recepcion_bodega_externa,
    _payload_ciclo_recepcion_bodega_externa,
    es_recepcion_bodega_externa_operacion,
    obtener_paso_activo_operacion,
)


class CicloRecepcionBodegaExternaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.sala_control = User.objects.create_user('Sala_Control', password='test')
        cls.guardia = User.objects.create_user('Guardia_Porteria', password='test')
        cls.empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
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
            'Analisis y calidad',
            'Resultado Calidad',
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

    def test_inicio_y_cierre_ciclo_externo_son_idempotentes(self):
        self.assertTrue(es_recepcion_bodega_externa_operacion(self.citacion))
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], PASO_CICLO_DESCARGA)

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
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_SALIDA).count(), 1)
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
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=EVENTO_RECEPCION_BODEGA_EXTERNA_REGRESO).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO=PASO_CICLO_DESCARGA).count(), 1)
        self.assertEqual(obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='REC_BEXT_SALIDA').count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='REC_BEXT_REGRESO').count(), 1)

    def test_payload_vacio_no_muestra_contador(self):
        payload = _payload_ciclo_recepcion_bodega_externa(self.citacion)

        self.assertFalse(payload['iniciada'])
        self.assertEqual(payload['estado'], 'PENDIENTE DE AUTORIZACION')
        self.assertEqual(payload['duracion_legible'], '00:00:00')
