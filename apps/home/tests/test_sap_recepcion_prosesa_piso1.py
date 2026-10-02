import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    PLANIFICACION,
    SECUENCIA,
)
from apps.integrations.sap_b1 import sap_recepcion
from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient


def citation(
    *,
    empresa=2,
    tipo="RECEPCION",
    secuencia="RECEPCION_PROSESA_PISO_1",
):
    planificacion = SimpleNamespace(PL_CTIPOCUPO=tipo)
    return SimpleNamespace(
        id=38724,
        pk=38724,
        EP_NID_id=empresa,
        EP_NID=SimpleNamespace(id=empresa),
        PL_NID=planificacion,
        CI_CTIPO=tipo,
        CI_CTIPODOCUMENTO="GD",
        CI_CNUMERODOCUMENTO="12345",
        SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
    )


class ProsesaContenedorPiso1HelperTests(SimpleTestCase):
    def test_identifica_empresa_2_recepcion_piso_1(self):
        self.assertTrue(
            sap_recepcion.es_recepcion_prosesa_contenedor_piso_1(citation())
        )

    def test_descarga_sobre_camion_permanece_aislada(self):
        citacion = citation(secuencia="RECEPCION_BODEGA_EXTERNA")
        detalle = SimpleNamespace(CDO_CALMACEN_DESTINO="PROSESA")
        self.assertFalse(
            sap_recepcion.es_recepcion_prosesa_contenedor_piso_1(citacion)
        )
        self.assertTrue(
            sap_recepcion.es_recepcion_prosesa_descarga_camion(citacion, detalle)
        )

    def test_piso_2_permanece_aislado(self):
        self.assertFalse(
            sap_recepcion.es_recepcion_prosesa_contenedor_piso_1(
                citation(secuencia="RECEPCION_PROSESA_PISO_2")
            )
        )

    def test_empresa_1_y_despacho_no_aplican(self):
        self.assertFalse(
            sap_recepcion.es_recepcion_prosesa_contenedor_piso_1(
                citation(empresa=1)
            )
        )
        self.assertFalse(
            sap_recepcion.es_recepcion_prosesa_contenedor_piso_1(
                citation(tipo="DESPACHO")
            )
        )


class ProsesaContenedorPiso1BatchGeneratorTests(SimpleTestCase):
    def _generar(self, item_code, row, numero_linea=1):
        with patch.object(
            sap_recepcion,
            "load_hana_config",
            return_value={"CompanyDB": "SBO_TST_SBH_USD"},
        ), patch.object(
            sap_recepcion,
            "_first_row",
            return_value=row,
        ) as first_row:
            result = (
                sap_recepcion
                .generar_lote_sap_recepcion_prosesa_piso_1(
                    item_code,
                    numero_linea=numero_linea,
                )
            )
        return result, first_row

    def test_line_num_sap_base_cero_se_convierte_a_posicion_humana(self):
        self.assertEqual(sap_recepcion.numero_linea_lote_desde_line_num(0), 1)
        self.assertEqual(sap_recepcion.numero_linea_lote_desde_line_num(1), 2)
        self.assertEqual(
            sap_recepcion.componer_lote_sap(
                "950105", 768, sap_recepcion.numero_linea_lote_desde_line_num(0)
            )["batch_number"], "LOTE-PT-950105-768-01",
        )
        self.assertEqual(
            sap_recepcion.componer_lote_sap(
                "950105", 768, sap_recepcion.numero_linea_lote_desde_line_num(1)
            )["batch_number"], "LOTE-PT-950105-768-02",
        )
        with self.assertRaises(sap_recepcion.GoodsReceiptDraftError):
            sap_recepcion.numero_linea_lote_desde_line_num(-1)

    def test_sufijo_depende_de_linea_y_no_de_item_code(self):
        self.assertEqual(
            sap_recepcion.componer_lote_sap("950105", 768, 1)["sufijo"],
            sap_recepcion.componer_lote_sap("950199", 768, 1)["sufijo"],
        )

    def test_prefijos_pd_ep_tt_generan_lote_mp(self):
        for item_code in ("PD1001", "EP1002", "TT1003"):
            with self.subTest(item_code=item_code):
                result, _ = self._generar(item_code, {"CORRELATIVO": 2})
                self.assertEqual(result["tipo_lote"], "MP")
                self.assertTrue(result["batch_number"].startswith("LOTE-MP-"))

    def test_item_950105_correlativo_766_primera_linea_genera_sufijo_01(self):
        result, first_row = self._generar(
            "950105",
            {"CORRELATIVO": 766},
            numero_linea=1,
        )
        self.assertEqual(result, {
            "item_code": "950105",
            "tipo_lote": "PT",
            "correlativo": 766,
            "sufijo": "01",
            "batch_number": "LOTE-PT-950105-766-01",
        })
        sql, params = first_row.call_args.args
        self.assertIn('"Add conteo de entradas para lote"', sql)
        self.assertIn('MAX(CAST(J0."CUENTA" AS INTEGER))', sql)
        self.assertEqual(params, ["950105"])
        self.assertNotIn("950105", sql)

    def test_item_950105_correlativo_766_segunda_linea_genera_sufijo_02(self):
        result, _ = self._generar(
            "950105",
            {"CORRELATIVO": 766},
            numero_linea=2,
        )
        self.assertEqual(result["correlativo"], 766)
        self.assertEqual(result["sufijo"], "02")
        self.assertEqual(
            result["batch_number"],
            "LOTE-PT-950105-766-02",
        )

    def test_mismo_correlativo_solo_cambia_sufijo_entre_lineas(self):
        linea_1, _ = self._generar(
            "950105",
            {"CORRELATIVO": 766},
            numero_linea=1,
        )
        linea_2, _ = self._generar(
            "950105",
            {"CORRELATIVO": 766},
            numero_linea=2,
        )
        self.assertEqual(linea_1["correlativo"], linea_2["correlativo"])
        self.assertEqual(
            [linea_1["batch_number"], linea_2["batch_number"]],
            [
                "LOTE-PT-950105-766-01",
                "LOTE-PT-950105-766-02",
            ],
        )

    def test_sin_registro_contador_hana_devuelve_correlativo_1(self):
        result, _ = self._generar("950105", {"CORRELATIVO": 1})
        self.assertEqual(result["correlativo"], 1)
        self.assertEqual(result["batch_number"], "LOTE-PT-950105-1-01")

    def test_falla_hana_se_reporta_sin_lote_ficticio(self):
        with patch.object(
            sap_recepcion,
            "load_hana_config",
            return_value={"CompanyDB": "SBO_TST_SBH_USD"},
        ), patch.object(
            sap_recepcion,
            "_first_row",
            side_effect=RuntimeError("HANA no disponible"),
        ):
            with self.assertRaisesRegex(
                sap_recepcion.GoodsReceiptDraftError,
                "HANA no disponible",
            ):
                sap_recepcion.generar_lote_sap_recepcion_prosesa_piso_1(
                    "950105"
                )


class SapSystemDateTests(SimpleTestCase):
    def test_obtiene_current_date_de_hana_configurada(self):
        with patch.object(
            sap_recepcion,
            "load_hana_config",
            return_value={"CompanyDB": "SBO_TST_SBH_USD"},
        ), patch.object(
            sap_recepcion,
            "_first_row",
            return_value={"CURRENT_DATE": "2026-09-24"},
        ) as first_row:
            fecha = sap_recepcion.obtener_fecha_sistema_sap(
                "SBO_TST_SBH_USD"
            )
        self.assertEqual(fecha, "2026-09-24")
        first_row.assert_called_once_with("SELECT CURRENT_DATE FROM DUMMY")

    def test_rechaza_company_db_hana_distinta_a_service_layer(self):
        with patch.object(
            sap_recepcion,
            "load_hana_config",
            return_value={"CompanyDB": "OTRA_COMPANY_DB"},
        ), patch.object(sap_recepcion, "_first_row") as first_row:
            with self.assertRaises(sap_recepcion.GoodsReceiptDraftError):
                sap_recepcion.obtener_fecha_sistema_sap(
                    "SBO_TST_SBH_USD"
                )
        first_row.assert_not_called()

    def test_rechaza_fecha_hana_invalida(self):
        with patch.object(
            sap_recepcion,
            "load_hana_config",
            return_value={"CompanyDB": "SBO_TST_SBH_USD"},
        ), patch.object(
            sap_recepcion,
            "_first_row",
            return_value={"CURRENT_DATE": "fecha-invalida"},
        ):
            with self.assertRaises(sap_recepcion.GoodsReceiptDraftError):
                sap_recepcion.obtener_fecha_sistema_sap(
                    "SBO_TST_SBH_USD"
                )


@override_settings(
    BODEGA_VIRTUAL="B_TRANSI",
    SAP_GOODS_RECEIPT_DRAFT_SERIES=17,
)
class ProsesaContenedorPiso1BuilderTests(SimpleTestCase):
    def setUp(self):
        self.citacion = citation()
        self.detalle = SimpleNamespace(
            CDO_CDOCENTRY="6880",
            CDO_CSAP_OPOR_ID="6880",
            CDO_CPEDIDO_SAP="10001091",
            CDO_CCODIGO_SAP="950105",
            CDO_CINSUMO="INSUMO PROSESA",
            CDO_CPROVEEDOR_CODIGO="P77424780",
            CDO_CPRODUCTOR="EWOS CHILE ALIMENTOS LTDA",
            CDO_CBL_CONTENEDOR="BL-PISO1",
            CDO_NCANTIDAD_DISPONIBLE=Decimal("16412.37"),
            CDO_CALMACEN_DESTINO="PROSESA",
            CDO_CESTANQUE_DESTINO="PROSE_T3",
        )
        self.documentos = {
            "cda": "CDA-1",
            "di": "DI-1",
            "bl": "BL-PISO1",
            "nave_naviera": "NAVIERA-1",
            "fecha_produccion": "15052026",
            "fecha_vencimiento": "15052027",
            "sui": "SUI-1",
            "fuentes": {},
            "camion_patio_id": 134,
        }
        self.purchase_order = {
            "DocEntry": 6880,
            "DocNum": 10001091,
            "CardCode": "P77424780",
            "CardName": "EWOS CHILE ALIMENTOS LTDA",
            "DocumentStatus": "bost_Open",
            "DocumentLines": [{
                "LineNum": 1,
                "ItemCode": "950105",
                "ItemDescription": "INSUMO PROSESA",
                "Quantity": 100,
                "RemainingOpenQuantity": 100,
                "UoMCode": "MT",
                "MeasureUnit": "MT",
                "LineStatus": "bost_Open",
                "U_NXContenedor": "BL-PISO1",
            }],
        }

    def _build(
        self,
        *,
        peso="24000",
        remaining=None,
        documentos=None,
        sap_date="2026-09-24",
        sap_date_error=None,
        lote_error=None,
    ):
        purchase_order = dict(self.purchase_order)
        purchase_order["DocumentLines"] = [
            dict(line)
            for line in self.purchase_order["DocumentLines"]
        ]
        if remaining is not None:
            purchase_order["DocumentLines"][0]["RemainingOpenQuantity"] = remaining
        client = MagicMock()
        client.get_json.return_value = purchase_order
        config = SimpleNamespace(company_db="TEST", username="tester")

        def dato_valor(_citacion, codigo):
            return peso if codigo == sap_recepcion.CAMPO_PESO_INFORMADO_GUIA else ""

        sap_date_patch = (
            patch.object(
                sap_recepcion,
                "obtener_fecha_sistema_sap",
                side_effect=sap_date_error,
            )
            if sap_date_error
            else patch.object(
                sap_recepcion,
                "obtener_fecha_sistema_sap",
                return_value=sap_date,
            )
        )
        def lote_generado(item_code, numero_linea=1):
            sufijo = f"{numero_linea:02d}"
            return {
                "item_code": item_code,
                "tipo_lote": "PT",
                "correlativo": 7,
                "sufijo": sufijo,
                "batch_number": f"LOTE-PT-{item_code}-7-{sufijo}",
            }

        lote_patch = (
            patch.object(
                sap_recepcion,
                "generar_lote_sap_recepcion_prosesa_piso_1",
                side_effect=lote_error,
            )
            if lote_error
            else patch.object(
                sap_recepcion,
                "generar_lote_sap_recepcion_prosesa_piso_1",
                side_effect=lote_generado,
            )
        )
        with patch.object(
            sap_recepcion, "_latest_detail", return_value=self.detalle
        ), patch.object(
            sap_recepcion,
            "resolver_datos_documentales_recepcion",
            return_value=self.documentos if documentos is None else documentos,
        ), patch.object(
            sap_recepcion, "_dato_valor", side_effect=dato_valor
        ), patch.object(
            sap_recepcion, "load_config", return_value=config
        ), patch.object(
            sap_recepcion, "SapServiceLayerClient", return_value=client
        ), sap_date_patch, lote_patch:
            preview = (
                sap_recepcion
                .build_purchase_delivery_note_prosesa_contenedor_piso_1(
                    self.citacion
                )
            )
        return preview, client

    def test_caso_38724_convierte_24000_kg_a_24_mt(self):
        preview, _ = self._build()
        line = preview["payload"]["DocumentLines"][0]
        self.assertEqual(line["Quantity"], 24)
        self.assertEqual(preview["source_data"]["peso_informado_guia_kg"], 24000)
        self.assertEqual(
            preview["source_data"]["quantity_source"],
            "DATO_OPERACION.SAP_PESO_INFORMADO_GUIA / 1000",
        )

    def test_payload_real_purchase_delivery_note_basado_en_purchase_order(self):
        preview, _ = self._build()
        payload = preview["payload"]
        line = payload["DocumentLines"][0]
        self.assertFalse(preview["errors"])
        self.assertEqual(preview["endpoint"], "/PurchaseDeliveryNotes")
        self.assertEqual(preview["document_type"], "PurchaseDeliveryNotes")
        self.assertNotIn("DocObjectCode", payload)
        self.assertEqual(line["BaseType"], 22)
        self.assertEqual(line["BaseEntry"], 6880)
        self.assertEqual(line["BaseLine"], 1)
        self.assertEqual(line["ItemCode"], "950105")
        self.assertEqual(line["BatchNumbers"], [{
            "BatchNumber": "LOTE-PT-950105-7-01",
            "Quantity": 24,
        }])

    def test_sufijo_usa_posicion_ordinal_y_conserva_baseline_sap(self):
        self.purchase_order["DocumentLines"].insert(0, {
            "LineNum": 0,
            "ItemCode": "OTRO",
            "RemainingOpenQuantity": 100,
            "UoMCode": "MT",
            "MeasureUnit": "MT",
            "LineStatus": "bost_Open",
            "U_NXContenedor": "OTRO-BL",
        })
        preview, _ = self._build()
        line = preview["payload"]["DocumentLines"][0]
        self.assertEqual(line["BaseLine"], 1)
        self.assertEqual(preview["source_data"]["numero_linea_lote"], 2)
        self.assertEqual(
            line["BatchNumbers"][0]["BatchNumber"],
            "LOTE-PT-950105-7-02",
        )

    def test_cruce_medianoche_usa_fecha_sap_y_no_fecha_local_futura(self):
        with patch.object(
            sap_recepcion.timezone,
            "localdate",
            return_value=date(2026, 9, 25),
        ):
            preview, _ = self._build(sap_date="2026-09-24")
        payload = preview["payload"]
        self.assertEqual(payload["DocDate"], "2026-09-24")
        self.assertEqual(payload["DocDueDate"], "2026-09-24")
        self.assertEqual(payload["TaxDate"], "2026-09-24")
        self.assertEqual(
            preview["source_data"]["posting_date_source"],
            "HANA CURRENT_DATE",
        )
        self.assertEqual(
            preview["source_data"]["sap_system_date"],
            "2026-09-24",
        )

    def test_falla_seguro_si_no_se_puede_obtener_fecha_sap(self):
        preview, client = self._build(
            sap_date_error=sap_recepcion.GoodsReceiptDraftError(
                "HANA no disponible"
            )
        )
        self.assertEqual(preview["payload"], {})
        self.assertTrue(
            any("fecha SAP" in item for item in preview["errors"])
        )
        client.post_purchase_delivery_note.assert_not_called()

    def test_bodega_virtual_es_destino_sap_y_prose_t3_sigue_fisico(self):
        preview, _ = self._build()
        line = preview["payload"]["DocumentLines"][0]
        self.assertEqual(line["WarehouseCode"], "B_TRANSI")
        self.assertNotEqual(line["WarehouseCode"], "PROSE_T3")
        self.assertEqual(
            preview["source_data"]["estanque_destino_planificado"],
            "PROSE_T3",
        )
        self.assertEqual(
            preview["source_data"]["destino_sap_inicial"],
            "B_TRANSI",
        )

    def test_no_usa_cantidad_planificada_como_quantity(self):
        preview, _ = self._build()
        self.assertEqual(
            preview["source_data"]["cantidad_disponible_planificada"],
            16412.37,
        )
        self.assertEqual(
            preview["payload"]["DocumentLines"][0]["Quantity"],
            24,
        )

    def test_solo_agrega_udf_confirmados_para_piso_1(self):
        preview, _ = self._build()
        line = preview["payload"]["DocumentLines"][0]
        self.assertEqual(line["U_HCO_FVEN"], "2026-05-15T00:00:00")
        self.assertEqual(line["U_NXFlote"], "2027-05-15T00:00:00")
        for field in (
            "U_CDA",
            "U_DI",
            "U_BL",
            "U_HCO_NAVIERAS",
            "U_SUI",
            "U_NXNombreTransporte",
            "U_NXRutChofer",
            "U_NXNombreChofer",
            "U_NXTelefonoChofer",
        ):
            self.assertNotIn(field, line)

    def test_udf_vacios_se_omiten(self):
        documentos = dict(self.documentos)
        documentos["fecha_produccion"] = ""
        documentos["fecha_vencimiento"] = ""
        preview, _ = self._build(documentos=documentos)
        line = preview["payload"]["DocumentLines"][0]
        self.assertNotIn("U_HCO_FVEN", line)
        self.assertNotIn("U_NXFlote", line)

    def test_saldo_abierto_inferior_es_warning_no_bloqueo(self):
        preview, _ = self._build(remaining=Decimal("20"))
        self.assertTrue(preview["payload"])
        self.assertFalse(preview["errors"])
        self.assertTrue(any("supera" in item for item in preview["warnings"]))

    def test_peso_faltante_bloquea_builder(self):
        preview, client = self._build(peso="")
        self.assertEqual(preview["payload"], {})
        self.assertTrue(any("peso informado" in item.lower() for item in preview["errors"]))
        client.post_purchase_delivery_note.assert_not_called()

    @override_settings(BODEGA_VIRTUAL="")
    def test_bodega_virtual_vacia_bloquea_sin_consultar_sap(self):
        client = MagicMock()
        with patch.object(
            sap_recepcion, "_latest_detail", return_value=self.detalle
        ), patch.object(
            sap_recepcion,
            "resolver_datos_documentales_recepcion",
            return_value=self.documentos,
        ), patch.object(
            sap_recepcion, "_dato_valor", return_value="24000"
        ), patch.object(
            sap_recepcion, "SapServiceLayerClient", return_value=client
        ) as client_class:
            preview = (
                sap_recepcion
                .build_purchase_delivery_note_prosesa_contenedor_piso_1(
                    self.citacion
                )
            )
        self.assertEqual(preview["payload"], {})
        self.assertTrue(any("bodega virtual" in item.lower() for item in preview["errors"]))
        client_class.assert_not_called()

    def test_preview_no_realiza_post(self):
        preview, client = self._build()
        self.assertTrue(preview["ready_for_post"])
        client.post_purchase_delivery_note.assert_not_called()
        client.post_draft.assert_not_called()
        client.logout.assert_called_once_with()

    def test_falla_generacion_lote_bloquea_payload_y_no_postea(self):
        preview, client = self._build(
            lote_error=sap_recepcion.GoodsReceiptDraftError(
                "HANA no disponible"
            )
        )
        self.assertEqual(preview["payload"], {})
        self.assertTrue(any("lote SAP" in item for item in preview["errors"]))
        client.post_purchase_delivery_note.assert_not_called()

    def test_batch_numbers_no_inventa_fechas_nativas(self):
        preview, _ = self._build()
        batch = preview["payload"]["DocumentLines"][0]["BatchNumbers"][0]
        self.assertNotIn("ManufacturingDate", batch)
        self.assertNotIn("ExpiryDate", batch)
        self.assertNotIn("AdmissionDate", batch)

    def test_builder_generico_delega_al_builder_semantico_piso_1(self):
        expected = {"payload": {"DocumentLines": []}, "errors": []}
        with patch.object(
            sap_recepcion,
            "build_purchase_delivery_note_prosesa_contenedor_piso_1",
            return_value=expected,
        ) as builder:
            result = sap_recepcion.build_goods_receipt_draft_preview(
                self.citacion
            )
        self.assertEqual(result, expected)
        builder.assert_called_once_with(self.citacion)


class PurchaseDeliveryNoteClientTests(SimpleTestCase):
    def test_wrapper_postea_purchase_delivery_notes(self):
        client = object.__new__(SapServiceLayerClient)
        client.post_json = MagicMock(return_value={"status_code": 201, "data": {}})
        payload = {"CardCode": "P77424780", "DocumentLines": []}
        result = client.post_purchase_delivery_note(payload)
        self.assertEqual(result["status_code"], 201)
        client.post_json.assert_called_once_with(
            "PurchaseDeliveryNotes",
            payload,
            diagnostic_context="POST PurchaseDeliveryNotes",
        )


class ProsesaContenedorPiso1SenderTests(SimpleTestCase):
    def setUp(self):
        self.citacion = citation()
        self.user = SimpleNamespace(username="tester")
        self.batch_data = {
            "item_code": "950105",
            "tipo_lote": "PT",
            "correlativo": 7,
            "sufijo": "01",
            "batch_number": "LOTE-PT-950105-7-01",
        }
        self.payload = {
            "CardCode": "P77424780",
            "DocumentLines": [{
                "BaseType": 22,
                "BaseEntry": 6880,
                "BaseLine": 1,
                "ItemCode": "950105",
                "Quantity": 24,
                "WarehouseCode": "B_TRANSI",
                "BatchNumbers": [{
                    "BatchNumber": "LOTE-PT-950105-7-01",
                    "Quantity": 24,
                }],
            }],
        }
        self.obtener_lote = patch.object(
            sap_recepcion,
            "obtener_lote_sap_prosesa_piso_1",
            return_value=dict(self.batch_data),
        ).start()
        self.guardar_lote = patch.object(
            sap_recepcion,
            "guardar_lote_sap_prosesa_piso_1",
            return_value=dict(self.batch_data),
        ).start()
        self.registrar_cambio = patch.object(
            sap_recepcion,
            "_registrar_cambio_lote_sap_prosesa_piso_1",
        ).start()
        self.addCleanup(patch.stopall)

    def test_sender_usa_purchase_delivery_notes_y_payload_del_preview(self):
        preview = {
            "payload": self.payload,
            "errors": [],
            "source_data": {"lote_sap": dict(self.batch_data)},
        }
        client = MagicMock()
        client.post_purchase_delivery_note.return_value = {
            "status_code": 201,
            "data": {"DocEntry": 9001, "DocNum": 8001},
        }
        config = SimpleNamespace(company_db="TEST", username="tester")
        with patch.object(
            sap_recepcion,
            "_purchase_delivery_note_piso_1_log",
            return_value=None,
        ), patch.object(
            sap_recepcion,
            "build_purchase_delivery_note_prosesa_contenedor_piso_1",
            return_value=preview,
        ), patch.object(
            sap_recepcion, "load_config", return_value=config
        ) as load_config, patch.object(
            sap_recepcion, "SapServiceLayerClient", return_value=client
        ), patch.object(
            sap_recepcion, "_save_purchase_delivery_note_piso_1_log"
        ) as save_log, patch.object(
            sap_recepcion,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": True, "docentry": 9001},
        ):
            result = (
                sap_recepcion
                .send_purchase_delivery_note_prosesa_contenedor_piso_1_to_sap(
                    self.citacion,
                    self.user,
                )
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["endpoint"], "/PurchaseDeliveryNotes")
        load_config.assert_called_once_with(2, for_write=True)
        client.post_purchase_delivery_note.assert_called_once_with(self.payload)
        client.post_draft.assert_not_called()
        self.guardar_lote.assert_called_once()
        save_log.assert_called_once()
        self.assertTrue(save_log.call_args.kwargs["success"])

    def test_sender_bloquea_duplicado(self):
        with patch.object(
            sap_recepcion,
            "_purchase_delivery_note_piso_1_log",
            return_value=MagicMock(),
        ), patch.object(
            sap_recepcion,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": True, "docentry": 9001},
        ), patch.object(
            sap_recepcion, "SapServiceLayerClient"
        ) as client_class:
            result = (
                sap_recepcion
                .send_purchase_delivery_note_prosesa_contenedor_piso_1_to_sap(
                    self.citacion,
                    self.user,
                )
            )
        self.assertFalse(result["success"])
        self.assertIn("Ya existe un Ingreso SAP", result["message"])
        client_class.assert_not_called()

    def test_sender_no_postea_preview_invalido(self):
        preview = {"payload": {}, "errors": ["Falta peso"]}
        with patch.object(
            sap_recepcion,
            "_purchase_delivery_note_piso_1_log",
            return_value=None,
        ), patch.object(
            sap_recepcion,
            "build_purchase_delivery_note_prosesa_contenedor_piso_1",
            return_value=preview,
        ), patch.object(
            sap_recepcion, "SapServiceLayerClient"
        ) as client_class:
            result = (
                sap_recepcion
                .send_purchase_delivery_note_prosesa_contenedor_piso_1_to_sap(
                    self.citacion,
                    self.user,
                )
            )
        self.assertFalse(result["success"])
        client_class.assert_not_called()

    def test_cambio_correlativo_antes_del_post_actualiza_y_registra(self):
        lote_previo = dict(self.batch_data)
        lote_previo.update({
            "correlativo": 6,
            "batch_number": "LOTE-PT-950105-6-01",
        })
        self.obtener_lote.return_value = lote_previo
        preview = {
            "payload": self.payload,
            "errors": [],
            "source_data": {"lote_sap": dict(self.batch_data)},
        }
        client = MagicMock()
        client.post_purchase_delivery_note.return_value = {
            "status_code": 201,
            "data": {"DocEntry": 9001, "DocNum": 8001},
        }
        with patch.object(
            sap_recepcion,
            "_purchase_delivery_note_piso_1_log",
            return_value=None,
        ), patch.object(
            sap_recepcion,
            "build_purchase_delivery_note_prosesa_contenedor_piso_1",
            return_value=preview,
        ), patch.object(
            sap_recepcion,
            "load_config",
            return_value=SimpleNamespace(company_db="TEST", username="tester"),
        ), patch.object(
            sap_recepcion,
            "SapServiceLayerClient",
            return_value=client,
        ), patch.object(
            sap_recepcion,
            "_save_purchase_delivery_note_piso_1_log",
        ), patch.object(
            sap_recepcion,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": True},
        ):
            result = (
                sap_recepcion
                .send_purchase_delivery_note_prosesa_contenedor_piso_1_to_sap(
                    self.citacion,
                    self.user,
                )
            )
        self.assertTrue(result["success"])
        self.registrar_cambio.assert_called_once()
        client.post_purchase_delivery_note.assert_called_once_with(self.payload)

    def test_estado_lee_log_exclusivo_purchase_delivery_note(self):
        log = SimpleNamespace(
            OPL_CESTADO=sap_recepcion.OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_FFECHAREGISTRO=timezone.make_aware(datetime(2026, 9, 25, 10, 0)),
            US_NID=SimpleNamespace(username="tester"),
            OPL_COBSERVACION="",
        )
        data = {
            "success": True,
            "endpoint": "/PurchaseDeliveryNotes",
            "status_code": 201,
            "payload": self.payload,
            "response": {"DocEntry": 9001, "DocNum": 8001},
        }
        with patch.object(
            sap_recepcion,
            "_purchase_delivery_note_piso_1_log",
            return_value=log,
        ), patch.object(
            sap_recepcion, "_parse_log_json", return_value=data
        ):
            status = (
                sap_recepcion.get_purchase_delivery_note_prosesa_piso_1_status(
                    self.citacion
                )
            )
        self.assertTrue(status["sent"])
        self.assertEqual(status["label"], "Ingreso SAP creado")
        self.assertEqual(status["endpoint"], "/PurchaseDeliveryNotes")
        self.assertEqual(status["docentry"], 9001)

    def test_log_registra_lote_cantidad_y_documento_sap(self):
        with patch.object(
            sap_recepcion.OPERACION_PLANTA_LOG.objects,
            "create",
            return_value=MagicMock(),
        ) as create_log:
            sap_recepcion._save_purchase_delivery_note_piso_1_log(
                self.citacion,
                self.user,
                success=True,
                payload=self.payload,
                status_code=201,
                response={"DocEntry": 9001, "DocNum": 8001},
                company_db="TEST",
                sap_username="tester",
            )
        data = json.loads(create_log.call_args.kwargs["OPL_COBSERVACION"])
        self.assertEqual(data["item_code"], "950105")
        self.assertEqual(data["batch_number"], "LOTE-PT-950105-7-01")
        self.assertEqual(data["correlativo"], 7)
        self.assertEqual(data["quantity"], 24)
        self.assertEqual(data["docentry"], 9001)
        self.assertEqual(data["docnum"], 8001)
        self.assertEqual(data["endpoint"], "/PurchaseDeliveryNotes")


class ProsesaContenedorPiso1EndpointOrmTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="tester_orm",
            email="tester@example.com",
            password="test-password",
        )
        self.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL="Empresa 2",
            EP_CRUT="2-7",
            EP_CBASEDATOS="TEST",
            EP_CUSUARIOSBD="test",
            EP_CPORT="0",
        )
        self.calendario = CALENDARIO.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CA_CNOMBRE="Calendario prueba lote",
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=1,
        )
        self.planificacion = PLANIFICACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CAL_NID=self.calendario,
            PL_CTIPOCUPO="RECEPCION",
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=1,
        )
        self.secuencia = SECUENCIA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            SE_CTIPO="RECEPCION",
            SE_CCODIGO="RECEPCION_PROSESA_PISO_1",
            SE_CNOMBRE="Recepcion Prosesa Piso 1",
            SE_BHABILITADO=True,
        )
        self.etapa = ETAPA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            ET_CTIPO="OPERACION",
            ET_CCODIGO="EN_DESCARGA",
            ET_CNOMBRE="En descarga",
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        self.citacion = CITACION.objects.create(
            id=38724,
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO="RECEPCION",
            CI_CESTADO="PENDIENTE",
        )
        ETAPA_LOG.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            US_INICIO_ID=self.user,
            EL_FFECHAINICIO=timezone.now(),
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            US_NID=self.user,
            CDO_CCODIGO_SAP="950105",
        )

    def test_endpoint_carga_citacion_con_queryset_real_y_alcanza_generador(self):
        citacion_cargada = CITACION.objects.select_related(
            "EP_NID", "PL_NID", "SC_NID"
        ).get(pk=self.citacion.pk)
        self.assertEqual(citacion_cargada.pk, 38724)
        self.assertEqual(citacion_cargada.ETAPA_ACTUAL, self.etapa)

        request = RequestFactory().post(
            "/pla-citacion/38724/generar-lote-sap/"
        )
        request.user = self.user
        lote = {
            "item_code": "950105",
            "tipo_lote": "PT",
            "correlativo": 766,
            "sufijo": "01",
            "batch_number": "LOTE-PT-950105-766-01",
        }
        with patch.object(
            views, "Verificar_empresa", return_value=self.empresa.pk
        ), patch.object(
            views,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": False},
        ), patch.object(
            views,
            "generar_lote_sap_recepcion_prosesa_piso_1",
            return_value=lote,
        ) as generar, patch.object(
            views,
            "guardar_lote_sap_prosesa_piso_1",
            return_value={**lote, "usuario": self.user.username},
        ):
            response = views.PLANIFICACION_PROSESA_PISO1_GENERAR_LOTE_SAP(
                request,
                self.citacion.pk,
            )

        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["item_code"], "950105")
        self.assertEqual(data["batch_number"], "LOTE-PT-950105-766-01")
        generar.assert_called_once_with("950105")


class ProsesaContenedorPiso1EndpointTests(SimpleTestCase):
    def test_generar_lote_resuelve_item_code_en_backend_y_persiste_auditoria(self):
        request = RequestFactory().post(
            "/pla-citacion/38724/generar-lote-sap/",
            {"item_code": "PD-MANIPULADO"},
        )
        request.user = SimpleNamespace(is_superuser=True, username="tester")
        queryset = MagicMock()
        queryset.get.return_value = citation()
        lote = {
            "item_code": "950105",
            "tipo_lote": "PT",
            "correlativo": 7,
            "sufijo": "01",
            "batch_number": "LOTE-PT-950105-7-01",
        }
        with patch.object(
            views, "Verificar_empresa", return_value=2
        ), patch.object(
            views.CITACION.objects, "select_related", return_value=queryset
        ), patch.object(
            views,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": False},
        ), patch.object(
            views,
            "resolver_item_code_lote_prosesa_piso_1",
            return_value="950105",
        ) as resolver, patch.object(
            views,
            "generar_lote_sap_recepcion_prosesa_piso_1",
            return_value=lote,
        ) as generar, patch.object(
            views,
            "guardar_lote_sap_prosesa_piso_1",
            return_value={**lote, "usuario": "tester"},
        ) as guardar:
            response = views.PLANIFICACION_PROSESA_PISO1_GENERAR_LOTE_SAP(
                request,
                38724,
            )
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["batch_number"], "LOTE-PT-950105-7-01")
        resolver.assert_called_once_with(queryset.get.return_value)
        generar.assert_called_once_with("950105")
        guardar.assert_called_once()

    def test_generar_lote_bloquea_si_ingreso_ya_existe(self):
        request = RequestFactory().post(
            "/pla-citacion/38724/generar-lote-sap/"
        )
        request.user = SimpleNamespace(is_superuser=True, username="tester")
        queryset = MagicMock()
        queryset.get.return_value = citation()
        with patch.object(
            views, "Verificar_empresa", return_value=2
        ), patch.object(
            views.CITACION.objects, "select_related", return_value=queryset
        ), patch.object(
            views,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": True, "docentry": 9001},
        ), patch.object(
            views, "generar_lote_sap_recepcion_prosesa_piso_1"
        ) as generar:
            response = views.PLANIFICACION_PROSESA_PISO1_GENERAR_LOTE_SAP(
                request,
                38724,
            )
        self.assertEqual(response.status_code, 409)
        generar.assert_not_called()

    def test_endpoint_existente_rutea_al_sender_purchase_delivery_note(self):
        request = RequestFactory().post(
            "/pla-citacion-borrador-sap-peso-guia/38724/enviar/"
        )
        request.user = SimpleNamespace(is_superuser=True)
        queryset = MagicMock()
        queryset.get.return_value = citation()
        sender_result = {"success": True, "response": {"DocEntry": 9001}}
        with patch.object(
            views, "Verificar_empresa", return_value=2
        ), patch.object(
            views.CITACION.objects, "select_related", return_value=queryset
        ), patch.object(
            views, "_validar_borrador_sap_peso_guia_disponible", return_value=None
        ), patch.object(
            views,
            "send_purchase_delivery_note_prosesa_contenedor_piso_1_to_sap",
            return_value=sender_result,
        ) as sender, patch.object(
            views,
            "get_purchase_delivery_note_prosesa_piso_1_status",
            return_value={"sent": True, "docentry": 9001},
        ):
            response = views.PLANIFICACION_BORRADOR_SAP_PESO_GUIA_ENVIAR(
                request,
                38724,
            )
        self.assertEqual(response.status_code, 200)
        sender.assert_called_once_with(queryset.get.return_value, request.user)


class ProsesaContenedorPiso1FrontendContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_source = (
            Path(views.__file__).resolve().parents[1]
            / "templates"
            / "home"
            / "PLANIFICACION"
            / "pla_listone.html"
        ).read_text(encoding="utf-8")

    def test_ui_piso_1_muestra_destino_sap_inicial(self):
        self.assertIn("Destino SAP inicial", self.template_source)
        self.assertIn("datos.destino_sap_inicial", self.template_source)

    def test_ui_piso_1_usa_textos_ingreso_sap(self):
        branch = self.template_source.split(
            "if (estanqueCamionEsRecepcionProsesaPiso1) {", 1
        )[1].split("return;", 1)[0]
        self.assertIn("Crear Ingreso SAP", branch)
        self.assertIn("Ingreso SAP creado", branch)
        self.assertIn("Previsualizar Ingreso SAP", self.template_source)
        self.assertIn("POST /PurchaseDeliveryNotes", self.template_source)

    def test_ui_piso_1_muestra_generador_y_campo_readonly(self):
        self.assertIn("Generar lote SAP", self.template_source)
        self.assertIn('id="lote_sap_prosesa_piso1"', self.template_source)
        self.assertIn('placeholder="Genere el lote SAP" readonly', self.template_source)
        self.assertIn(
            "'/pla-citacion/' + estanqueCamionCitacionId + '/generar-lote-sap/'",
            self.template_source,
        )

    def test_boton_lote_inicia_oculto_y_solo_se_activa_en_piso_1(self):
        self.assertIn(
            'id="btn_generar_lote_sap_prosesa_piso1"',
            self.template_source,
        )
        self.assertIn(
            ".toggle(estanqueCamionEsRecepcionProsesaPiso1)",
            self.template_source,
        )
