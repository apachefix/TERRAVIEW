import json
from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.services.eli.sap_audit import (
    normalizar_auditoria_sap_eli,
    obtener_primera_linea_documento,
    resumir_evento_sap_eli,
)


class EliSapAuditTests(SimpleTestCase):
    def setUp(self):
        self.payload = {
            "accion": "BORRADOR_SAP_RECEPCION_ENVIO", "success": True, "status_code": 201,
            "company_db": "secret", "CompanyDB": "secret-2", "sap_username": "technical",
            "endpoint": "https://private/Drafts", "usuario": "Asistente_C_D",
            "fecha_hora": "27/07/2026 14:29:36",
            "payload": {
                "FolioPrefixString": "GD", "FolioNumber": 613, "TaxExtension": {"secret": "x"},
                "DocumentLines": [{"ItemCode": "800034", "Quantity": 1, "BaseEntry": 5737,
                                   "U_HCO_Plantadestino": "PROSE_T3"}],
            },
            "response": {
                "DocEntry": 3258, "DocNum": 10963, "CardCode": "PE0163",
                "CardName": "FUZHOU SINO-FISHOIL TRADE CO., LTD.",
                "odata.metadata": "https://metadata", "AddressExtension": {"secret": "x"},
                "DocumentLines": [{"ItemCode": "800034", "ItemDescription": "ACEITE DE PESCADO",
                                   "Quantity": 99, "UoMCode": "MT", "MeasureUnit": "Toneladas Metricas",
                                   "BaseEntry": 5737, "U_HCO_Plantadestino": "RESPONSE_TANK"}],
            },
        }

    def summary(self, data=None, paso="BORRADOR_SAP_RECEPCION_ENVIO", **kwargs):
        return resumir_evento_sap_eli(paso, json.dumps(self.payload if data is None else data), **kwargs)

    def values(self, data=None, paso="BORRADOR_SAP_RECEPCION_ENVIO", **kwargs):
        return {row["etiqueta"]: row["valor"] for row in self.summary(data, paso, **kwargs)["filas"]}

    def test_real_38610_equivalent_resolves_each_field_independently(self):
        values = self.values()
        expected = {
            "Producto": "ACEITE DE PESCADO", "Unidad": "MT", "Cantidad": "1",
            "DocEntry": "3258", "DocNum": "10963", "Proveedor": "FUZHOU SINO-FISHOIL TRADE CO., LTD.",
            "CardCode": "PE0163", "Codigo SAP": "800034", "Pedido base": "5737",
            "Guia": "GD 613", "Estanque destino": "PROSE_T3",
            "Fecha": "27/07/2026 14:29:36", "Usuario": "Asistente_C_D",
        }
        for key, value in expected.items():
            self.assertEqual(values[key], value)

    def test_request_line_is_used_when_payload_line_is_absent(self):
        data = {"success": True, "request": {"DocumentLines": [{
            "ItemCode": "REQ", "Quantity": 7, "BaseEntry": 44, "U_HCO_Plantadestino": "REQ_TANK",
        }]}, "response": {"DocumentLines": [{"ItemDescription": "Producto", "UoMCode": "KG"}]}}
        values = self.values(data)
        self.assertEqual(values["Codigo SAP"], "REQ")
        self.assertEqual(values["Cantidad"], "7")
        self.assertEqual(values["Pedido base"], "44")
        self.assertEqual(values["Estanque destino"], "REQ_TANK")

    def test_response_line_fallbacks_and_measure_unit(self):
        data = {"status_code": 204, "response": {"DocumentLines": [{
            "ItemCode": "RESP", "ItemDescription": "Producto", "Quantity": 0,
            "MeasureUnit": "Toneladas Metricas", "U_HCO_Plantadestino": "RESP_TANK",
        }]}}
        values = self.values(data)
        self.assertEqual(values["Estado HTTP"], "204")
        self.assertEqual(values["Resultado"], "Exitoso")
        self.assertEqual(values["Codigo SAP"], "RESP")
        self.assertEqual(values["Cantidad"], "0")
        self.assertEqual(values["Unidad"], "Toneladas Metricas")
        self.assertEqual(values["Estanque destino"], "RESP_TANK")

    def test_root_item_code_wins(self):
        data = deepcopy(self.payload)
        data["item_code"] = "ROOT"
        self.assertEqual(self.values(data)["Codigo SAP"], "ROOT")

    def test_guide_can_come_from_response(self):
        data = {"response": {"FolioPrefixString": "GD", "FolioNumber": 9}}
        self.assertEqual(self.values(data)["Guia"], "GD 9")

    def test_update_preserves_operational_priorities(self):
        data = {"success": True, "cantidad_sap": 26.68, "unidad_sap": "MT", "peso_salida": 26680,
                "modo_lote": "MANUAL_SAP", "lote_enviado": False,
                "payload": {"DocumentLines": [{"Quantity": 1}]}}
        values = self.values(data, "UPDATE_SAP_RECEPCION_ENVIO")
        self.assertEqual(values["Cantidad SAP"], "26.68")
        self.assertEqual(values["Unidad"], "MT")
        self.assertEqual(values["Peso salida"], "26680")
        self.assertEqual(values["Modo lote"], "MANUAL_SAP")
        self.assertEqual(values["Lote enviado"], "False")

    def test_document_lines_helper_handles_invalid_shapes(self):
        invalid = ({}, {"DocumentLines": None}, {"DocumentLines": {}}, {"DocumentLines": "texto"},
                   {"DocumentLines": []}, {"DocumentLines": [None]}, {"DocumentLines": ["texto"]})
        for container in invalid:
            with self.subTest(container=container):
                self.assertEqual(obtener_primera_linea_documento(container), {})
        self.assertEqual(obtener_primera_linea_documento({"DocumentLines": [{}]}), {})

    def test_empty_and_null_fields_are_omitted_but_false_and_zero_are_kept(self):
        values = self.values({"success": False, "status_code": 0, "docentry": "  ", "docnum": None})
        self.assertEqual(values["Estado HTTP"], "0")
        self.assertEqual(values["Resultado"], "Error")
        self.assertNotIn("DocEntry", values)
        self.assertNotIn("DocNum", values)

    def test_invalid_or_empty_sap_json_is_safe(self):
        for value in ("{bad", ""):
            self.assertIn("Detalle tecnico no disponible", resumir_evento_sap_eli(
                "BORRADOR_SAP_RECEPCION_ENVIO", value
            )["texto"])

    def test_non_sap_text_is_preserved(self):
        exp = {"seguimiento": [{"paso": "Confirmar Salida", "observacion": "Camion salio de planta."}]}
        result = normalizar_auditoria_sap_eli(exp, SimpleNamespace(id=1, EP_NID_id=2))
        self.assertEqual(result["seguimiento"][0]["observacion"], "Camion salio de planta.")

    def test_presentation_uses_log_date_and_user_without_changing_source_json(self):
        source = deepcopy(self.payload)
        source.pop("fecha_hora")
        source.pop("usuario")
        original = deepcopy(source)
        exp = {"seguimiento": [{"paso": "BORRADOR_SAP_RECEPCION_ENVIO", "estado": "COMPLETADO",
                                "fecha": "27/07/2026 14:29:36", "usuario": "Asistente_C_D",
                                "observacion": json.dumps(source)}]}
        result = normalizar_auditoria_sap_eli(exp, SimpleNamespace(id=38610, EP_NID_id=2))
        self.assertEqual(source, original)
        self.assertIn("Fecha: 27/07/2026 14:29:36", result["seguimiento"][0]["observacion"])
        self.assertIn("Usuario: Asistente_C_D", result["seguimiento"][0]["observacion"])

    def test_summary_is_allowlisted_and_does_not_mutate_input(self):
        original = deepcopy(self.payload)
        text = self.summary()["texto"]
        self.assertEqual(self.payload, original)
        for prohibited in ("payload", "response", "request", "DocumentLines", "odata.metadata", "odata.etag",
                           "company_db", "CompanyDB", "sap_username", "AddressExtension", "TaxExtension", "https://"):
            self.assertNotIn(prohibited, text)

    def test_dispatch_equivalent_uses_same_safe_resolution(self):
        values = self.values(self.payload, "BORRADOR_SAP_DESPACHO_ENVIO")
        self.assertEqual(values["Producto"], "ACEITE DE PESCADO")
        self.assertEqual(values["Cantidad"], "1")

    def test_error_is_compact_and_url_is_removed(self):
        data = {"success": False, "status_code": 500, "sap_error": {"message": "Error https://secret stack"}}
        text = self.summary(data, "UPDATE_SAP_RECEPCION_ENVIO")["texto"]
        self.assertIn("Resultado: Error", text)
        self.assertNotIn("https://", text)

