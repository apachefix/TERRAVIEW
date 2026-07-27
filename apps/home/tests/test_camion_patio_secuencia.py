from datetime import time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.home.models import CALENDARIO, CITACION, EMPRESA, PLANIFICACION, SECUENCIA
from apps.home.views import _serializar_citacion_patio


class CamionPatioSecuenciaTestCase(SimpleTestCase):
    def _serializar(self, tipo, secuencia):
        citacion = SimpleNamespace(
            id=99, PL_NID_id=None, PL_NID=None, SC_NID=secuencia,
            CI_CTIPO=tipo, SN_NID=None, PRO_NID=None, CI_CESTADO='PENDIENTE',
        )
        camion = SimpleNamespace(id=11, EP_NID_id=7)
        with patch('apps.home.views._detalle_operacional_citacion', return_value=None), patch(
            'apps.home.views._score_citacion_camion_patio', return_value=(0, [], {})
        ):
            return _serializar_citacion_patio(camion, citacion)

    def test_recepcion_expone_la_secuencia_persistida(self):
        secuencia = SimpleNamespace(id=56, SE_CCODIGO='RECEPCION_ESTANQUE_SBH', SE_CNOMBRE='RECEPCION - Estanque SBH')
        self.assertEqual(self._serializar('RECEPCION', secuencia)['secuencia_operacional'], {
            'id': 56, 'codigo': 'RECEPCION_ESTANQUE_SBH', 'nombre': 'RECEPCION - Estanque SBH',
        })

    def test_despacho_expone_la_secuencia_persistida(self):
        secuencia = SimpleNamespace(id=57, SE_CCODIGO='DESPACHO_BODEGA', SE_CNOMBRE='Despacho desde Bodega Externa')
        resultado = self._serializar('DESPACHO', secuencia)
        self.assertEqual(resultado['secuencia_operacional']['nombre'], 'Despacho desde Bodega Externa')
        self.assertEqual(resultado['secuencia_operacional']['codigo'], 'DESPACHO_BODEGA')

    def test_planificacion_antigua_sin_secuencia_entrega_valor_nulo(self):
        self.assertIsNone(self._serializar('RECEPCION', None)['secuencia_operacional'])


class CamionPatioSecuenciaQueryTestCase(TestCase):
    def test_select_related_evita_n_mas_uno_al_leer_secuencias(self):
        user = get_user_model().objects.create_user('patio-secuencia')
        empresa = EMPRESA.objects.create(EP_CRAZONSOCIAL='Empresa patio', EP_CRUT='1-9', EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0')
        calendario = CALENDARIO.objects.create(
            US_NID=user, EP_NID=empresa, CA_CNOMBRE='Calendario', CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18), CA_NDIA=1, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=2,
        )
        planificacion = PLANIFICACION.objects.create(
            US_NID=user, EP_NID=empresa, CAL_NID=calendario, PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=2,
        )
        for numero in range(2):
            secuencia = SECUENCIA.objects.create(
                US_NID=user, EP_NID=empresa, SE_CTIPO='RECEPCION', SE_CCODIGO='REC_%s' % numero,
                SE_CNOMBRE='Recepcion %s' % numero, SE_BHABILITADO=True,
            )
            CITACION.objects.create(
                US_NID=user, EP_NID=empresa, PL_NID=planificacion, SC_NID=secuencia,
                CI_FFECHACITACION=timezone.now(), CI_NCUPO=numero + 1,
                CI_CTIPO='RECEPCION', CI_CESTADO='PENDIENTE',
            )

        citaciones = list(CITACION.objects.select_related('SC_NID').filter(EP_NID=empresa))
        with self.assertNumQueries(0):
            nombres = [citacion.SC_NID.SE_CNOMBRE for citacion in citaciones]

        self.assertEqual(nombres, ['Recepcion 0', 'Recepcion 1'])
