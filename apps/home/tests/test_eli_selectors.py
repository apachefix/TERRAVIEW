from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.services.eli.selectors.base import (
    logs_por_paso,
    primer_log,
    resolver_cliente_eli,
    resolver_conductor_eli,
    resolver_documento_eli,
    resolver_estanque_eli,
    resolver_patente_eli,
    resolver_producto_eli,
    resolver_proveedor_eli,
    resolver_transportista_eli,
    ultimo_log,
)


class EliSelectorTests(SimpleTestCase):
    def setUp(self):
        self.logs = [
            SimpleNamespace(OPL_CPASO="Pesaje", id=4),
            SimpleNamespace(OPL_CPASO="Calidad", id=6),
            SimpleNamespace(OPL_CPASO="Pesaje", id=8),
        ]

    def test_log_helpers_preserve_repeated_steps_and_explicit_order(self):
        self.assertEqual(primer_log(self.logs, "Pesaje").id, 4)
        self.assertEqual(ultimo_log(self.logs, "Pesaje").id, 8)
        self.assertEqual([log.id for log in logs_por_paso(self.logs)["Pesaje"]], [4, 8])

    def test_operational_values_take_precedence_for_truck_data(self):
        contexto = {
            "operacional": {
                "patente": "AA1111",
                "transportista": "Operacional",
                "conductor": "Chofer operacional",
                "numero_documento": "000212",
            },
            "datos_camion": {
                "patente": "BB2222",
                "transportista": "Patio",
                "conductor": "Chofer patio",
            },
            "citacion_patente": "CC3333",
            "citacion_documento": "999",
            "planificacion": {"transportista": "Planificado", "conductor": "Planificado"},
        }
        self.assertEqual(resolver_patente_eli(contexto), "AA1111")
        self.assertEqual(resolver_transportista_eli(contexto), "Operacional")
        self.assertEqual(resolver_conductor_eli(contexto), "Chofer operacional")
        self.assertEqual(resolver_documento_eli(contexto), "000212")

    def test_commercial_priorities_and_empty_context_are_safe(self):
        contexto = {
            "sap": {"producto": "Producto SAP", "cliente": "Cliente SAP"},
            "detalle": {
                "insumo": "Producto detalle",
                "proveedor_sap": "Proveedor detalle",
                "cliente_nombre": "Cliente detalle",
                "estanque_destino": "TQ-01",
            },
            "item_nombre": "Item",
            "proveedor_citacion": "Proveedor citacion",
            "cliente_citacion": "Cliente citacion",
            "operacional": {"estanque_destino": "TQ-02"},
        }
        self.assertEqual(resolver_producto_eli(contexto), "Producto SAP")
        self.assertEqual(resolver_proveedor_eli(contexto), "Proveedor detalle")
        self.assertEqual(resolver_cliente_eli(contexto), "Cliente SAP")
        self.assertEqual(resolver_estanque_eli(contexto), "TQ-01")
        self.assertEqual(resolver_patente_eli({}), "")
