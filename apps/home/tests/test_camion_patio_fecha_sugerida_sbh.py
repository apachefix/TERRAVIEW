from datetime import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.home.views import _fecha_planificacion_sugerida_patio


@override_settings(TIME_ZONE='America/Santiago', USE_TZ=True)
class FechaCitacionSugeridaSbhTests(SimpleTestCase):
    def citacion(self, empresa, tipo, fecha=None):
        fecha = fecha or timezone.make_aware(datetime(2026, 8, 21, 15, 30))
        return SimpleNamespace(
            EP_NID_id=empresa,
            CI_CTIPO=tipo,
            PL_NID=SimpleNamespace(PL_FFECHAINICIO=fecha),
        )

    def test_recepcion_sbh_muestra_solo_fecha(self):
        citacion = self.citacion(2, 'RECEPCION')
        fecha_original = citacion.PL_NID.PL_FFECHAINICIO
        self.assertEqual(_fecha_planificacion_sugerida_patio(citacion), '21/08/2026')
        self.assertEqual(citacion.PL_NID.PL_FFECHAINICIO, fecha_original)

    def test_recepcion_terramar_conserva_fecha_y_hora(self):
        self.assertEqual(
            _fecha_planificacion_sugerida_patio(self.citacion(1, 'RECEPCION')),
            '21/08/2026 15:30',
        )

    def test_despacho_sbh_conserva_fecha_y_hora(self):
        self.assertEqual(
            _fecha_planificacion_sugerida_patio(self.citacion(2, 'DESPACHO')),
            '21/08/2026 15:30',
        )

    def test_despacho_terramar_conserva_fecha_y_hora(self):
        self.assertEqual(
            _fecha_planificacion_sugerida_patio(self.citacion(1, 'DESPACHO')),
            '21/08/2026 15:30',
        )

    def test_fecha_ausente_mantiene_valor_vacio(self):
        citacion = self.citacion(2, 'RECEPCION')
        citacion.PL_NID.PL_FFECHAINICIO = None
        self.assertEqual(_fecha_planificacion_sugerida_patio(citacion), '')
