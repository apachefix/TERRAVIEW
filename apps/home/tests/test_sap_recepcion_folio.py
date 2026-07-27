from decimal import Decimal

from apps.home.tests.test_sap_recepcion_plant_destination import SapRecepcionPlantDestinationTests
from apps.integrations.sap_b1 import sap_recepcion


class SapRecepcionFolioTests(SapRecepcionPlantDestinationTests):
    def test_gd_y_ceros_iniciales_generan_folio_entero_sin_numatcard(self):
        with self._preview_dependencies():
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion, Decimal("1"))

        payload = preview["payload"]
        self.assertEqual(payload["FolioPrefixString"], "GD")
        self.assertEqual(payload["FolioNumber"], 212)
        self.assertNotIn("NumAtCard", payload)
        self.assertEqual(self.citacion.CI_CNUMERODOCUMENTO, "000212")
        self.assertEqual(payload["DocumentLines"][0]["U_HCO_Plantadestino"], "PROSE_T3")
        self.assertNotIn("WarehouseCode", payload["DocumentLines"][0])

    def test_fe_generates_folio_prefix_fe(self):
        self.citacion.CI_CTIPODOCUMENTO = "FE"
        self.citacion.CI_CNUMERODOCUMENTO = "12345"
        with self._preview_dependencies():
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion, Decimal("1"))

        self.assertEqual(preview["payload"]["FolioPrefixString"], "FE")
        self.assertEqual(preview["payload"]["FolioNumber"], 12345)

    def test_folio_invalido_bloquea_preview(self):
        casos = [
            ("", "123", "La citación no tiene tipo de documento para FolioPrefixString."),
            ("OTRO", "123", "El tipo de documento de la citación no es válido para FolioPrefixString."),
            ("GD", "", "La citación no tiene número de documento para FolioNumber."),
            ("GD", "12A", "El número de documento de la citación no es válido para FolioNumber."),
        ]
        for tipo, numero, error in casos:
            with self.subTest(tipo=tipo, numero=numero):
                self.citacion.CI_CTIPODOCUMENTO = tipo
                self.citacion.CI_CNUMERODOCUMENTO = numero
                with self._preview_dependencies():
                    preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion, Decimal("1"))
                self.assertIn(error, preview["errors"])
                self.assertEqual(preview["payload"], {})