from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.views import seleccionar_tarifas_por_ruta_revision


class RutasTransportistaRevisionTests(SimpleTestCase):
    def test_preserva_tarifa_guardada_para_la_misma_ruta(self):
        ruta = SimpleNamespace(id=67)
        tarifas = [
            SimpleNamespace(id=100, RUT_NID=ruta, RUT_NID_id=67),
            SimpleNamespace(id=101, RUT_NID=ruta, RUT_NID_id=67),
        ]

        resultado = seleccionar_tarifas_por_ruta_revision(tarifas, tarifa_seleccionada_id=101)

        self.assertEqual([tarifa.id for tarifa in resultado], [101])

    def test_conserva_una_opcion_por_ruta_sin_tarifa_guardada(self):
        ruta_uno = SimpleNamespace(id=67)
        ruta_dos = SimpleNamespace(id=68)
        tarifas = [
            SimpleNamespace(id=100, RUT_NID=ruta_uno, RUT_NID_id=67),
            SimpleNamespace(id=101, RUT_NID=ruta_uno, RUT_NID_id=67),
            SimpleNamespace(id=102, RUT_NID=ruta_dos, RUT_NID_id=68),
        ]

        resultado = seleccionar_tarifas_por_ruta_revision(tarifas)

        self.assertEqual([tarifa.id for tarifa in resultado], [100, 102])
