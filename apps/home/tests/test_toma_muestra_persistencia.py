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
    TIPO_DESCARGA_INICIO_TRASVASIJE,
    _finalizar_tiempo_toma_muestra,
    _iniciar_ciclo_descarga,
    _leer_metadata_toma_muestra_accion,
    _payload_ciclo_descarga,
    _payload_tiempo_toma_muestra,
    _payload_toma_muestra_accion,
    _registrar_toma_muestra_accion,
    opciones_tipos_ciclo_descarga,
)


class TomaMuestraPersistenciaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('Asistente_C_D_test', password='test')
        cls.empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Empresa prueba toma muestra',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Toma muestra',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=22,
            CA_NMES=7,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TRASVASIJE',
            SE_CNOMBRE='RECEPCION TRASVASIJE',
            SE_BHABILITADO=True,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='TOMA_DE_MUESTRA',
            ET_CNOMBRE='Toma de muestra',
            ET_NCANTIDADMAXIMA=10,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa, SC_NID=cls.secuencia, ET_NID=cls.etapa, SE_NPASO=1, SE_BHABILITADO=True, SE_BOBLIGATORIO=True)
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE',
            CI_CNUMERODOCUMENTO='GUIA-TOMA-MUESTRA',
        )

    def test_inicio_persiste_y_es_idempotente(self):
        inicio = timezone.now() - timedelta(minutes=5)
        with patch('apps.home.views.timezone.now', return_value=inicio):
            primero = _registrar_toma_muestra_accion(
                self.citacion, self.usuario, 'RECEPCION TRASVASIJE'
            )
        segundo = _registrar_toma_muestra_accion(
            self.citacion, self.usuario, 'RECEPCION TRASVASIJE'
        )

        self.assertEqual(primero['fecha_iso'], segundo['fecha_iso'])
        self.assertEqual(DATO_OPERACION.objects.filter(CI_NID=self.citacion, CAMP_NID__CA_CCODIGO='OP_TOMA_MUESTRA_ACCION').count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='MUESTRA_TOMADA').count(), 1)
        citacion_recargada = CITACION.objects.get(pk=self.citacion.pk)
        with patch('apps.home.views.timezone.now', return_value=inicio + timedelta(minutes=5)):
            accion = _payload_toma_muestra_accion(citacion_recargada, 'RECEPCION TRASVASIJE')
            reloj = _payload_tiempo_toma_muestra(citacion_recargada, 'RECEPCION TRASVASIJE')
        self.assertTrue(accion['registrada'])
        self.assertTrue(reloj['en_proceso'])
        self.assertEqual(reloj['duracion_segundos'], 300)

    def test_finalizacion_guarda_fin_duracion_y_no_se_reinicia(self):
        inicio = timezone.now() - timedelta(minutes=5)
        fin = inicio + timedelta(minutes=5)
        with patch('apps.home.views.timezone.now', return_value=inicio):
            _registrar_toma_muestra_accion(self.citacion, self.usuario, 'RECEPCION TRASVASIJE')
        with patch('apps.home.views.timezone.now', return_value=fin):
            primero = _finalizar_tiempo_toma_muestra(self.citacion, self.usuario, 'RECEPCION TRASVASIJE')
        with patch('apps.home.views.timezone.now', return_value=fin + timedelta(minutes=2)):
            segundo = _finalizar_tiempo_toma_muestra(self.citacion, self.usuario, 'RECEPCION TRASVASIJE')

        metadata = _leer_metadata_toma_muestra_accion(self.citacion)
        self.assertTrue(primero['finalizada'])
        self.assertEqual(primero['fin_iso'], segundo['fin_iso'])
        self.assertEqual(primero['duracion_segundos'], 300)
        self.assertEqual(metadata['duracion_segundos'], 300)
        self.assertEqual(metadata['usuario_fin'], self.usuario.username)

    def test_bodega_externa_envio_analisis_persiste_reloj_y_finaliza(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_BODEGA_EXTERNA'
        self.secuencia.SE_CNOMBRE = 'RECEPCION BODEGA EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])

        inicio = timezone.now() - timedelta(minutes=7)
        fin = inicio + timedelta(minutes=7)
        with patch('apps.home.views.timezone.now', return_value=inicio):
            primero = _registrar_toma_muestra_accion(
                self.citacion, self.usuario, 'RECEPCION BODEGA EXTERNA'
            )
        segundo = _registrar_toma_muestra_accion(
            self.citacion, self.usuario, 'RECEPCION BODEGA EXTERNA'
        )

        self.assertEqual(primero['fecha_iso'], segundo['fecha_iso'])
        self.assertEqual(DATO_OPERACION.objects.filter(CI_NID=self.citacion, CAMP_NID__CA_CCODIGO='OP_TOMA_MUESTRA_ACCION').count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(EP_NID=self.empresa, LOG_COPERACION='MUESTRA_A_ANALISIS').count(), 1)
        with patch('apps.home.views.timezone.now', return_value=inicio + timedelta(minutes=3)):
            accion = _payload_toma_muestra_accion(self.citacion, 'RECEPCION BODEGA EXTERNA')
            reloj = _payload_tiempo_toma_muestra(self.citacion, 'RECEPCION BODEGA EXTERNA')

        self.assertTrue(accion['registrada'])
        self.assertEqual(accion['estado_label'], 'Muestra enviada a analisis')
        self.assertTrue(reloj['en_proceso'])
        self.assertEqual(reloj['duracion_segundos'], 180)

        with patch('apps.home.views.timezone.now', return_value=fin):
            finalizado = _finalizar_tiempo_toma_muestra(self.citacion, self.usuario, 'RECEPCION BODEGA EXTERNA')

        self.assertTrue(finalizado['finalizada'])
        self.assertEqual(finalizado['duracion_segundos'], 420)
        self.assertEqual(_leer_metadata_toma_muestra_accion(self.citacion)['usuario_fin'], self.usuario.username)

    def test_opciones_descarga_son_contextuales_al_flujo(self):
        opciones_trasvasije = opciones_tipos_ciclo_descarga('RECEPCION TRASVASIJE')
        opciones_bodega = opciones_tipos_ciclo_descarga('RECEPCION BODEGA EXTERNA')

        self.assertEqual(
            [opcion['etiqueta_tarjeta'] for opcion in opciones_trasvasije],
            ['Descarga Estanque', 'Trasvasije', 'Descarga en Cisterna', 'Descarga Patio LF'],
        )
        self.assertEqual(
            [opcion['etiqueta_tarjeta'] for opcion in opciones_bodega],
            ['Descarga Estanque', 'Trasvasije', 'Descarga en Cisterna', 'Descarga Patio LF'],
        )
        self.assertNotIn('Envio Bodega Externa', [opcion['etiqueta_tarjeta'] for opcion in opciones_trasvasije])
        self.assertIn('Envio Bodega Externa', [opcion['etiqueta'] for opcion in opciones_bodega])

    def test_inicio_trasvasije_persiste_codigo_etiqueta_e_historial(self):
        metadata = _iniciar_ciclo_descarga(
            self.citacion,
            self.usuario,
            TIPO_DESCARGA_INICIO_TRASVASIJE,
        )
        citacion_recargada = CITACION.objects.get(pk=self.citacion.pk)
        payload = _payload_ciclo_descarga(citacion_recargada)
        log = OPERACION_PLANTA_LOG.objects.get(
            CI_NID=self.citacion,
            OPL_CPASO='INICIA_DESCARGA',
        )

        self.assertEqual(metadata['tipo_descarga_codigo'], 'INICIO_TRASVASIJE')
        self.assertEqual(metadata['tipo_descarga'], 'Inicio Trasvasije')
        self.assertEqual(payload['tipo_descarga_codigo'], 'INICIO_TRASVASIJE')
        self.assertEqual(payload['tipo_descarga_label'], 'Inicio Trasvasije')
        self.assertTrue(payload['en_proceso'])
        self.assertEqual(log.OPL_COBSERVACION, 'Tipo descarga: Inicio Trasvasije')

    def test_bodega_externa_conserva_su_opcion_y_rechaza_codigo_trasvasije(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_BODEGA_EXTERNA'
        self.secuencia.SE_CNOMBRE = 'RECEPCION BODEGA EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])

        with self.assertRaisesMessage(ValueError, 'Debe seleccionar un tipo de descarga valido.'):
            _iniciar_ciclo_descarga(
                self.citacion,
                self.usuario,
                TIPO_DESCARGA_INICIO_TRASVASIJE,
            )

        metadata = _iniciar_ciclo_descarga(
            self.citacion,
            self.usuario,
            'Envio Bodega Externa',
        )
        self.assertEqual(metadata['tipo_descarga_codigo'], 'Envio Bodega Externa')
        self.assertEqual(metadata['tipo_descarga'], 'Envio Bodega Externa')
