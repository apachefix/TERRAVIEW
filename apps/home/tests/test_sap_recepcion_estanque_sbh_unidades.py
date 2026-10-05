from contextlib import ExitStack
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integrations.sap_b1 import sap_recepcion


class FakeSapServiceLayerClient:
    purchase_order_line = {}
    posted_payloads = []

    def __init__(self, config):
        self.config = config

    def login(self):
        return None

    def logout(self):
        return None

    def get_json(self, path, label):
        return {
            "CardCode": "P77424780",
            "DocumentLines": [deepcopy(self.purchase_order_line)],
        }

    def post_draft(self, payload):
        self.posted_payloads.append(deepcopy(payload))
        return {
            "status_code": 201,
            "data": {"DocEntry": 9901, "DocNum": 9901},
        }


class RecepcionEstanqueSbhUnidadDraftTests(SimpleTestCase):
    def setUp(self):
        FakeSapServiceLayerClient.posted_payloads.clear()
        self.peso_guia = "16000"
        self.citacion = SimpleNamespace(
            id=38782,
            EP_NID_id=2,
            CI_CTIPO="RECEPCION",
            CI_CTIPODOCUMENTO="GD",
            CI_CNUMERODOCUMENTO="53232",
            PL_NID=SimpleNamespace(PL_CTIPOCUPO="RECEPCION"),
            SC_NID=SimpleNamespace(SE_CCODIGO="RECEPCION_ESTANQUE_SBH"),
        )
        self.detalle = SimpleNamespace(
            CDO_CESTANQUE_DESTINO="TK10",
            CDO_CPEDIDO_SAP="10000192",
            CDO_CCODIGO_SAP="600030",
            CDO_CINSUMO="ACEITE DE CANOLA VITAPRO",
            CDO_CPROVEEDOR_CODIGO="P77424780",
            CDO_CPRODUCTOR="EWOS CHILE ALIMENTOS LTDA",
            CDO_CBL_CONTENEDOR="",
            CDO_NCANTIDAD_DISPONIBLE=Decimal("87.31"),
        )
        self.linea = {
            "LineNum": 0,
            "ItemCode": "600030",
            "ItemDescription": "ACEITE DE CANOLA VITAPRO",
            "Quantity": Decimal("87.31"),
            "RemainingOpenQuantity": Decimal("87.31"),
            "LineStatus": "bost_Open",
            "UoMCode": "MT",
            "UoMEntry": 2,
            "MeasureUnit": "Toneladas Metricas",
            "UnitsOfMeasurment": 1,
            "LineTotal": Decimal("108177.09"),
        }

    def _dependencies(self):
        FakeSapServiceLayerClient.purchase_order_line = self.linea
        stack = ExitStack()
        stack.enter_context(patch.object(
            sap_recepcion, "_latest_detail", return_value=self.detalle,
        ))
        stack.enter_context(patch.object(
            sap_recepcion, "_resolve_doc_entry", return_value=727,
        ))
        stack.enter_context(patch.object(
            sap_recepcion,
            "_dato_valor",
            side_effect=lambda _citacion, codigo: (
                self.peso_guia
                if codigo == sap_recepcion.CAMPO_PESO_INFORMADO_GUIA
                else ""
            ),
        ))
        stack.enter_context(patch.object(
            sap_recepcion, "get_batch_number_from_citation", return_value="",
        ))
        stack.enter_context(patch.object(
            sap_recepcion,
            "find_matching_purchase_order_line",
            return_value=(self.linea, "Linea encontrada"),
        ))
        stack.enter_context(patch.object(
            sap_recepcion, "get_goods_receipt_draft_status", return_value={"sent": False},
        ))
        stack.enter_context(patch.object(
            sap_recepcion, "get_goods_receipt_draft_guide_status", return_value={"sent": False},
        ))
        stack.enter_context(patch.object(
            sap_recepcion,
            "load_config",
            return_value=SimpleNamespace(company_db="TEST", username="test"),
        ))
        stack.enter_context(patch.object(
            sap_recepcion, "SapServiceLayerClient", FakeSapServiceLayerClient,
        ))
        stack.enter_context(patch.object(
            sap_recepcion.timezone, "localdate", return_value=date(2026, 10, 4),
        ))
        stack.enter_context(patch.object(sap_recepcion, "_log_recepcion_folio"))
        return stack

    def _preview(self):
        with self._dependencies():
            return sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(
                self.citacion,
            )

    def test_16000_kg_se_convierten_a_16_mt_y_no_exceden_saldo(self):
        preview = self._preview()
        source = preview["source_data"]
        line = preview["payload"]["DocumentLines"][0]

        self.assertEqual(line["Quantity"], 16)
        self.assertFalse(source["quantity_exceeds_remaining"])
        self.assertEqual(source["peso_informado_guia_kg"], 16000)
        self.assertEqual(source["sap_quantity_unit"], "MT")
        self.assertEqual(source["quantity_conversion_factor"], 0.001)
        self.assertEqual(line["LineTotal"], 108177.09)

    def test_90000_kg_se_convierten_a_90_mt_y_exceden_saldo(self):
        self.peso_guia = "90000"

        preview = self._preview()
        source = preview["source_data"]

        self.assertEqual(preview["payload"]["DocumentLines"][0]["Quantity"], 90)
        self.assertTrue(source["quantity_exceeds_remaining"])
        self.assertIn("90000 kg = 90 MT", source["quantity_exceeds_message"])
        self.assertIn("87.31 MT", source["quantity_exceeds_message"])

    def test_repetir_preview_no_aplica_doble_conversion(self):
        primero = self._preview()
        segundo = self._preview()

        self.assertEqual(primero["payload"]["DocumentLines"][0]["Quantity"], 16)
        self.assertEqual(segundo["payload"]["DocumentLines"][0]["Quantity"], 16)
        self.assertEqual(segundo["source_data"]["peso_informado_guia"], 16000)

    def test_linea_sap_en_kg_mantiene_cantidad_sin_conversion(self):
        self.linea.update({
            "Quantity": Decimal("20000"),
            "RemainingOpenQuantity": Decimal("20000"),
            "UoMCode": "KG",
            "UoMEntry": 1,
            "MeasureUnit": "Kilogramos",
        })

        preview = self._preview()
        source = preview["source_data"]

        self.assertEqual(preview["payload"]["DocumentLines"][0]["Quantity"], 16000)
        self.assertEqual(source["quantity_conversion_factor"], 1)
        self.assertFalse(source["quantity_exceeds_remaining"])

    def test_otras_secuencias_conservan_quantity_sin_conversion(self):
        self.citacion.SC_NID.SE_CCODIGO = "RECEPCION_TERRAMAR"

        preview = self._preview()

        self.assertEqual(preview["payload"]["DocumentLines"][0]["Quantity"], 16000)
        self.assertNotIn("quantity_conversion_factor", preview["source_data"])

    def test_envio_corregido_llega_a_post_drafts_sin_confirmacion_forzada(self):
        with self._dependencies(), patch.object(
            sap_recepcion, "normalize_sap_environment", return_value="PROD",
        ), patch.object(sap_recepcion, "_save_guide_send_log"):
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                self.citacion,
                SimpleNamespace(id=7, username="asistente_cd"),
            )

        self.assertTrue(result["success"])
        self.assertNotIn("confirmation_required", result)
        self.assertEqual(len(FakeSapServiceLayerClient.posted_payloads), 1)
        line = FakeSapServiceLayerClient.posted_payloads[0]["DocumentLines"][0]
        self.assertEqual(line["Quantity"], 16)
        self.assertEqual(line["BaseEntry"], 727)
        self.assertEqual(line["BaseLine"], 0)
        self.assertEqual(line["WarehouseCode"], "TK10")
