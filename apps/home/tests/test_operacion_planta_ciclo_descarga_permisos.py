from datetime import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CITACION, DETALLE_SECUENCIA, EMPRESA, ETAPA,
    OPERACION_PLANTA_LOG, PLANIFICACION, SECUENCIA,
)


class CicloDescargaPermisosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.sala = User.objects.create_user('Sala_Control', password='test')
        cls.asistente = User.objects.create_user('Asistente_C_D', password='test')
        cls.romana = User.objects.create_user('Operador_romana', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-7',
            EP_CBASEDATOS='sbh_test', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, CA_CNOMBRE='Recepcion SBH',
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
            CA_NDIA=5, CA_NMES=8, CA_NANO=2026, CA_NCANTIDADCUPOS=10,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_ESTANQUE_SBH',
            SE_CNOMBRE='RECEPCION ESTANQUE SBH', SE_BHABILITADO=True,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_SBH_OPERACION_PLANTA',
            ET_CNOMBRE='Operacion Planta SBH', ET_NCANTIDADMAXIMA=10,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa, SE_NPASO=1, SE_BHABILITADO=True,
            SE_BOBLIGATORIO=True,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.romana, EP_NID=cls.empresa, PL_NID=cls.planificacion,
            SC_NID=cls.secuencia, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1,
            CI_CTIPO='RECEPCION', CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-CICLO-1',
        )

    def setUp(self):
        for paso in ('Pesaje Entrada', 'Toma de muestra', 'Analisis y calidad', 'Resultado Calidad'):
            OPERACION_PLANTA_LOG.objects.create(
                US_NID=self.romana, EP_NID=self.empresa,
                PL_NID=self.planificacion, CI_NID=self.citacion,
                OPL_CPASO=paso, OPL_CPERFIL_RESPONSABLE='TEST',
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )

    def test_recepcion_compartida_y_otras_etapas_aisladas(self):
        for flujo in (
            'RECEPCION ESTANQUE SBH', 'RECEPCION TRASVASIJE',
            'RECEPCION PATIO LF CON CALIDAD', 'RECEPCION PATIO LF SIN CALIDAD',
            'RECEPCION CONTENEDOR A PISO',
            'RECEPCION CONTENEDOR DE PISO A ESTANQUE',
            'RECEPCION ESTANQUES SBH ALMACENAJE',
        ):
            responsables = dict(views.FLUJOS_OPERACION_PLANTA[flujo])['Ciclo Descarga']
            self.assertEqual(responsables, ['SALA CONTROL', 'ASISTENTE C D'])
            self.assertTrue(views.usuario_puede_paso_operacion(self.sala, responsables))
            self.assertTrue(views.usuario_puede_paso_operacion(self.asistente, responsables))
            self.assertFalse(views.usuario_puede_paso_operacion(self.romana, responsables))

        pasos = dict(views.PASOS_RECEPCION_CON_CALIDAD)
        self.assertFalse(views.usuario_puede_paso_operacion(self.asistente, pasos['Pesaje Entrada']))
        self.assertFalse(views.usuario_puede_paso_operacion(self.asistente, pasos['Pesaje Salida']))
        self.assertFalse(views.usuario_puede_paso_operacion(self.asistente, pasos['Analisis y calidad']))
        self.assertFalse(views.usuario_puede_paso_operacion(self.asistente, pasos['Autorizar Salida']))
        self.assertFalse(views.usuario_puede_paso_operacion(self.asistente, pasos['Confirmar Salida']))
        self.assertEqual(dict(views.PASOS_DESPACHO_CARGA)[views.PASO_CICLO_CARGA], ['SALA CONTROL'])

    def test_asistente_ve_controles_del_ciclo_sin_aviso_de_solo_lectura(self):
        self.client.force_login(self.asistente)
        url = reverse('operacion_planta_citacion', args=[self.citacion.id])
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:500])
        ciclo = next(paso for paso in respuesta.context['pasos'] if paso['nombre'] == 'Ciclo Descarga')
        self.assertTrue(ciclo['activo'])
        self.assertTrue(ciclo['puede_editar'])
        self.assertEqual(ciclo['solo_lectura_msg'], '')
        self.assertContains(respuesta, 'Responsable: SALA CONTROL / ASISTENTE C D')

    def test_sala_control_conserva_acceso_al_endpoint(self):
        self.client.force_login(self.sala)
        url = reverse('ajax_operacion_planta_iniciar_ciclo_descarga', args=[self.citacion.id])
        with patch('apps.home.views._obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)):
            respuesta = self.client.post(url, {'tipo_descarga': 'Descarga Estanque'})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        log = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO='INICIA_DESCARGA')
        self.assertEqual(log.OPL_CPERFIL_RESPONSABLE, 'SALA CONTROL')

    def test_endpoint_acepta_asistente_y_atribuye_log_al_perfil_real(self):
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Ciclo Descarga')
        self.client.force_login(self.asistente)
        url = reverse('ajax_operacion_planta_iniciar_ciclo_descarga', args=[self.citacion.id])
        with patch('apps.home.views._obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)):
            inicio = self.client.post(url, {'tipo_descarga': 'Descarga Estanque'})
        self.assertEqual(inicio.status_code, 200, inicio.content)
        self.assertTrue(inicio.json()['ciclo_descarga']['en_proceso'])
        inicio_log = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO='INICIA_DESCARGA')
        self.assertEqual(inicio_log.OPL_CPERFIL_RESPONSABLE, 'ASISTENTE C D')

        fin_url = reverse('ajax_operacion_planta_finalizar_ciclo_descarga', args=[self.citacion.id])
        with patch('apps.home.views._obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)):
            fin = self.client.post(fin_url, {'observacion': 'Ciclo terminado'})
        self.assertEqual(fin.status_code, 200, fin.content)
        fin_log = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO='Ciclo Descarga')
        self.assertEqual(fin_log.OPL_CPERFIL_RESPONSABLE, 'ASISTENTE C D')

    def test_endpoint_bloquea_perfil_ajeno(self):
        self.client.force_login(self.romana)
        url = reverse('ajax_operacion_planta_iniciar_ciclo_descarga', args=[self.citacion.id])
        with patch('apps.home.views._obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)):
            respuesta = self.client.post(url, {'tipo_descarga': 'Descarga Estanque'})
        self.assertEqual(respuesta.status_code, 403, respuesta.content)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=self.citacion, OPL_CPASO='INICIA_DESCARGA').exists())
