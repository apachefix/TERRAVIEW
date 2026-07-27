from contextlib import ExitStack
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.integrations.sap_b1 import sap_recepcion


class FakeSapServiceLayerClient:
    posted_payloads = []
    purchase_order = {
        "CardCode": "P0001",
        "DocDate": "2026-06-12",
        "DocDueDate": "2026-06-12",
        "TaxDate": "2026-06-12",
    }

    def __init__(self, config):
        self.config = config

    def login(self):
        return None

    def logout(self):
        return None

    def get_json(self, path, label):
        return deepcopy(self.purchase_order)

    def post_draft(self, payload):
        self.posted_payloads.append(deepcopy(payload))
        return {"status_code": 201, "data": {"DocEntry": 9001, "DocNum": 9001}}


@override_settings(SAP_DRAFT_QA_COMPANY_DB="SBO_TST_SBH_USD")
class GoodsReceiptDraftActionDatesTestCase(SimpleTestCase):
    def setUp(self):
        FakeSapServiceLayerClient.posted_payloads.clear()
        self.citacion = SimpleNamespace(id=38602, EP_NID_id=2, CI_CTIPODOCUMENTO="GD", CI_CNUMERODOCUMENTO="000212")
        self.detalle = SimpleNamespace(
            CDO_CESTANQUE_DESTINO="TK-01",
            CDO_CPEDIDO_SAP="4500123",
            CDO_CCODIGO_SAP="800034",
            CDO_CINSUMO="ACEITE",
            CDO_CPROVEEDOR_CODIGO="P0001",
            CDO_CPRODUCTOR="PROVEEDOR QA",
            CDO_CBL_CONTENEDOR="",
            CDO_NCANTIDAD_DISPONIBLE=Decimal("100"),
        )
        self.linea = {
            "LineNum": 0,
            "ItemCode": "800034",
            "OpenQuantity": 100,
            "LineStatus": "bost_Open",
        }
        self.usuario = SimpleNamespace(id=7, username="qa.user", is_superuser=True)

    def _dato_valor(self, citacion, codigo):
        if codigo == sap_recepcion.CAMPO_PESO_INFORMADO_GUIA:
            return Decimal("26.59")
        if codigo == "ETA3_ESTANQUE":
            return "TK-01"
        return ""

    def _dependencias(self, fechas):
        stack = ExitStack()
        stack.enter_context(patch.object(sap_recepcion, "_latest_detail", return_value=self.detalle))
        stack.enter_context(patch.object(sap_recepcion, "_resolve_doc_entry", return_value=3249))
        stack.enter_context(patch.object(sap_recepcion, "_dato_valor", side_effect=self._dato_valor))
        stack.enter_context(patch.object(sap_recepcion, "get_batch_number_from_citation", return_value=""))
        stack.enter_context(patch.object(sap_recepcion, "get_num_at_card_from_citation", return_value=("GUIA-38602", None)))
        stack.enter_context(patch.object(sap_recepcion, "find_matching_purchase_order_line", return_value=(self.linea, "Linea QA")))
        stack.enter_context(patch.object(sap_recepcion, "_draft_series", return_value=17))
        stack.enter_context(patch.object(sap_recepcion, "get_goods_receipt_draft_status", return_value={}))
        stack.enter_context(patch.object(sap_recepcion, "get_goods_receipt_draft_guide_status", return_value={}))
        stack.enter_context(patch.object(sap_recepcion, "_save_guide_send_log"))
        stack.enter_context(patch.object(
            sap_recepcion,
            "load_config",
            return_value=SimpleNamespace(company_db="SBO_TST_SBH_USD", username="qa_sap"),
        ))
        stack.enter_context(patch.object(sap_recepcion, "SapServiceLayerClient", FakeSapServiceLayerClient))
        if isinstance(fechas, list):
            stack.enter_context(patch.object(sap_recepcion.timezone, "localdate", side_effect=fechas))
        else:
            stack.enter_context(patch.object(sap_recepcion.timezone, "localdate", return_value=fechas))
        return stack

    def test_preview_usa_fecha_local_de_accion_en_los_tres_campos(self):
        fecha_accion = date(2026, 7, 23)
        with self._dependencias(fecha_accion):
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(
                self.citacion,
                Decimal("26.59"),
            )

        payload = preview["payload"]
        self.assertEqual(payload["DocDate"], "2026-07-23")
        self.assertEqual(payload["DocDate"], payload["DocDueDate"])
        self.assertEqual(payload["DocDate"], payload["TaxDate"])
        self.assertEqual(datetime.strptime(payload["DocDate"], "%Y-%m-%d").date(), fecha_accion)
        self.assertNotEqual(payload["DocDueDate"], FakeSapServiceLayerClient.purchase_order["DocDueDate"])
        self.assertNotEqual(payload["TaxDate"], FakeSapServiceLayerClient.purchase_order["TaxDate"])
        self.assertEqual(payload["DocumentLines"][0]["Quantity"], 26.59)
        self.assertEqual(payload["CardCode"], "P0001")
        self.assertEqual(payload["FolioPrefixString"], "GD")
        self.assertEqual(payload["FolioNumber"], 212)
        self.assertNotIn("NumAtCard", payload)
        self.assertEqual(payload["DocObjectCode"], 20)
        self.assertEqual(payload["DocumentLines"][0]["BaseEntry"], 3249)

    def test_envio_inicial_y_reintento_reconstruyen_fecha_local_sin_alterar_otros_campos(self):
        with self._dependencias([date(2026, 7, 23), date(2026, 7, 24)]):
            inicial = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                self.citacion,
                self.usuario,
            )
            reintento = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                self.citacion,
                self.usuario,
                allow_duplicate=True,
            )

        self.assertTrue(inicial["success"])
        self.assertTrue(reintento["success"])
        self.assertEqual(len(FakeSapServiceLayerClient.posted_payloads), 2)
        payload_inicial, payload_reintento = FakeSapServiceLayerClient.posted_payloads
        self.assertEqual(
            (payload_inicial["DocDate"], payload_inicial["DocDueDate"], payload_inicial["TaxDate"]),
            ("2026-07-23", "2026-07-23", "2026-07-23"),
        )
        self.assertEqual(
            (payload_reintento["DocDate"], payload_reintento["DocDueDate"], payload_reintento["TaxDate"]),
            ("2026-07-24", "2026-07-24", "2026-07-24"),
        )
        for payload in (payload_inicial, payload_reintento):
            self.assertEqual(payload["FolioPrefixString"], "GD")
            self.assertEqual(payload["FolioNumber"], 212)
            self.assertNotIn("NumAtCard", payload)
            payload.pop("DocDate")
            payload.pop("DocDueDate")
            payload.pop("TaxDate")
        self.assertEqual(payload_inicial, payload_reintento)