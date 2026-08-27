from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integrations.sap_b1 import goods_receipt_draft_preview as legacy_module
from apps.integrations.sap_b1 import sap_recepcion


class FakeSapClient:
    purchase_order = {"CardCode": "P0001"}

    def __init__(self, config):
        self.config = config

    def login(self):
        return None

    def logout(self):
        return None

    def get_json(self, path, label):
        return self.purchase_order


class SapRecepcionPlantDestinationTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(id=99999, EP_NID_id=2, CI_CTIPODOCUMENTO="GD", CI_CNUMERODOCUMENTO="000212")
        self.detalle = SimpleNamespace(
            CDO_CESTANQUE_DESTINO="PROSE_T3",
            CDO_CPEDIDO_SAP="4500123",
            CDO_CCODIGO_SAP="800034",
            CDO_CINSUMO="ACEITE",
            CDO_CPROVEEDOR_CODIGO="P0001",
            CDO_CPRODUCTOR="PROVEEDOR",
            CDO_CBL_CONTENEDOR="",
            CDO_NCANTIDAD_DISPONIBLE=Decimal("1"),
        )

    def _preview_dependencies(self):
        stack = ExitStack()
        stack.enter_context(patch.object(sap_recepcion, "_latest_detail", return_value=self.detalle))
        stack.enter_context(patch.object(sap_recepcion, "_resolve_doc_entry", return_value=5737))
        stack.enter_context(patch.object(sap_recepcion, "_dato_valor", return_value=""))
        stack.enter_context(patch.object(sap_recepcion, "get_batch_number_from_citation", return_value=""))
        stack.enter_context(patch.object(sap_recepcion, "get_num_at_card_from_citation", return_value=("GUIA-1", None)))
        stack.enter_context(patch.object(sap_recepcion, "find_matching_purchase_order_line", return_value=({
            "LineNum": 1, "ItemCode": "800034", "OpenQuantity": 10,
        }, "Linea encontrada")))
        stack.enter_context(patch.object(sap_recepcion, "_draft_series", return_value=17))
        stack.enter_context(patch.object(sap_recepcion, "get_goods_receipt_draft_status", return_value={}))
        stack.enter_context(patch.object(sap_recepcion, "load_config", return_value=SimpleNamespace(company_db="TEST", username="test")))
        stack.enter_context(patch.object(sap_recepcion, "SapServiceLayerClient", FakeSapClient))
        stack.enter_context(patch.object(sap_recepcion.timezone, "localdate", return_value=date(2026, 7, 27)))
        return stack

    def test_preview_usa_estanque_del_detalle_como_warehouse(self):
        with self._preview_dependencies():
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion, Decimal("1"))

        line = preview["payload"]["DocumentLines"][0]
        self.assertEqual(line["WarehouseCode"], "PROSE_T3")
        self.assertNotIn("U_HCO_Plantadestino", line)
        self.assertEqual(preview["source_data"]["estanque_destino"], "PROSE_T3")

    def test_preview_bloquea_si_el_estanque_del_detalle_esta_vacio(self):
        self.detalle.CDO_CESTANQUE_DESTINO = ""
        with self._preview_dependencies(), patch.object(sap_recepcion, "_dato_valor", return_value="NO-USAR"):
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion, Decimal("1"))

        self.assertIn(
            "La citación no tiene bodega/almacén destino asignado para WarehouseCode.",
            preview["errors"],
        )
        self.assertEqual(preview["payload"], {})

    def test_docentry_existente_bloquea_reenvio_aun_con_allow_duplicate(self):
        status = {"sent": True, "docentry": 3256, "docnum": 10963}
        with patch.object(sap_recepcion, "get_goods_receipt_draft_guide_status", return_value=status), patch.object(
            sap_recepcion, "build_goods_receipt_draft_preview_from_peso_guia"
        ) as preview_mock, patch.object(sap_recepcion, "SapServiceLayerClient") as client_mock:
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                self.citacion, SimpleNamespace(is_superuser=True), allow_duplicate=True
            )

        self.assertFalse(result["success"])
        self.assertIn("DocEntry 3256", result["message"])
        preview_mock.assert_not_called()
        client_mock.assert_not_called()

    def test_wrapper_reexporta_la_implementacion_central(self):
        self.assertIs(
            legacy_module.build_goods_receipt_draft_preview,
            sap_recepcion.build_goods_receipt_draft_preview,
        )
