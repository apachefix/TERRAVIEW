from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.services.eli.base import normalizar_metadata_eli, validar_contrato_expediente_eli
from apps.home.services.eli.comparison import comparar_expedientes_eli
from apps.home.services.eli.selectors.base import logs_por_paso, primer_log, ultimo_log
from apps.home.services.eli_service import enriquecer_expediente_eli
from apps.home.views import eli_duracion


class EliServiceTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(EP_NID_id=2, SC_NID=SimpleNamespace(SE_CCODIGO="RECEPCION_ESTANQUE"))

    def test_recepcion_adds_identity_and_configured_order(self):
        expediente = {"etapas_eli": [{"numero": 2, "titulo": "x"}, {"numero": 1, "titulo": "x"}]}
        result = enriquecer_expediente_eli(expediente, self.citacion, "RECEPCION")
        self.assertEqual(result["tipo_eli"], "RECEPCION")
        self.assertEqual(result["codigo_flujo"], "RECEPCION_ESTANQUE")
        self.assertEqual(result["empresa_id"], 2)
        self.assertEqual([e["titulo"] for e in result["etapas_eli"]], ["Revision documental", "Ingreso a planta"])

    def test_despacho_uses_its_config(self):
        result = enriquecer_expediente_eli({"etapas_eli": [{"numero": 1, "titulo": "x"}]}, self.citacion, "DESPACHO")
        self.assertEqual(result["tipo_eli"], "DESPACHO")
        self.assertEqual(result["etapas_eli"][0]["titulo"], "Datos comerciales / SAP despacho")

    def test_negative_duration_is_zero(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        self.assertEqual(eli_duracion(now, now - timedelta(seconds=1)), "00:00:00")

    def test_metadata_is_safe_and_contract_preserves_legacy_keys(self):
        self.assertEqual(normalizar_metadata_eli('{"peso_neto": 10}')["peso_neto"], 10)
        self.assertEqual(normalizar_metadata_eli("{invalido"), "{invalido")
        result = validar_contrato_expediente_eli({})
        self.assertIn("encabezado_eli", result)
        self.assertIn("resumen", result)

    def test_unknown_section_does_not_fail(self):
        result = enriquecer_expediente_eli({"etapas_eli": [{"numero": 99, "titulo": "legacy", "datos": []}]}, self.citacion, "RECEPCION")
        self.assertEqual(result["etapas_eli"][0]["titulo"], "legacy")
        self.assertEqual(result["etapas_eli"][0]["filas"], [])

    def test_comparison_ignores_presentation_metadata(self):
        legacy = {"etapas_eli": [{"numero": 1, "titulo": "Revision documental"}]}
        nuevo = {"etapas_eli": [{"numero": 1, "titulo": "Revision documental", "codigo": "x", "orden": 10, "filas": []}], "tipo_eli": "RECEPCION"}
        self.assertEqual(comparar_expedientes_eli(legacy, nuevo), [])
