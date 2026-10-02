import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.home import sap_recepcion_new_jersey as nj
from apps.home import views


def citation(sequence="RECEPCION_NEW_JERSEY_P1_CON_CALIDAD"):
    return SimpleNamespace(
        pk=38731, id=38731, EP_NID_id=2, CI_CTIPO="RECEPCION",
        SC_NID=SimpleNamespace(SE_CCODIGO=sequence),
    )


class DatosIngresoMercaderiaSbhTests(SimpleTestCase):
    def test_helper_compone_fuentes_y_normaliza_fechas(self):
        cit = citation()
        cit.CI_CTIPODOCUMENTO = "GD"
        cit.CI_CNUMERODOCUMENTO = "65688"
        detalle = SimpleNamespace(CDO_CBL_CONTENEDOR="CONT-1")
        documentos = {
            "bl": "CONT-1", "bl_documental": "BL-REAL",
            "cda": "", "di": "", "nave_naviera": "",
            "booking": "BOOK-1", "sui": "",
            "fecha_produccion": "15/05/2026",
            "fecha_vencimiento": "15052027",
        }
        transporte = {
            "nombre_transporte": "TRANSPORTES SAEZ LIMITADA",
            "rut_conductor": "13796965-3",
            "nombre_conductor": "DOMINGO DIAZ PEDREROS",
            "telefono_conductor": "+569239689118",
            "patente": "SDS45",
            "transporte_a_cargo": "TERRAMAR",
        }
        with patch.object(nj.technical, "resolver_datos_documentales_recepcion",
                          return_value=documentos) as documental, \
             patch.object(nj.technical, "resolver_datos_transporte_recepcion",
                          return_value=transporte) as transport:
            result = nj.technical.resolver_datos_ingreso_mercaderia_sbh(cit, detalle)
        documental.assert_called_once_with(cit, detalle)
        transport.assert_called_once_with(cit)
        self.assertEqual(result["transporte"]["nombre_transporte"],
                         "TRANSPORTES SAEZ LIMITADA")
        self.assertEqual(result["transporte"]["rut_conductor"], "13796965-3")
        self.assertEqual(result["transporte"]["nombre_conductor"],
                         "DOMINGO DIAZ PEDREROS")
        self.assertEqual(result["transporte"]["telefono_conductor"],
                         "+569239689118")
        self.assertEqual(result["transporte"]["patente"], "SDS45")
        self.assertEqual(result["documentos"]["bl"], "BL-REAL")
        self.assertEqual(result["documentos"]["booking"], "BOOK-1")
        self.assertEqual(result["recepcion"], {
            "tipo_documento": "GD", "numero_documento": "65688",
            "contenedor": "CONT-1",
        })
        self.assertEqual(result["fechas"], {
            "fecha_produccion": "2026-05-15T00:00:00",
            "fecha_vencimiento": "2027-05-15T00:00:00",
        })
        self.assertEqual(result["fechas_invalidas"], {})

    def test_marcador_transporte_a_cargo_no_es_nombre_transportista(self):
        with patch.object(nj.technical, "resolver_datos_documentales_recepcion",
                          return_value={}), \
             patch.object(nj.technical, "resolver_datos_transporte_recepcion",
                          return_value={"nombre_transporte": "TERRAMAR"}):
            result = nj.technical.resolver_datos_ingreso_mercaderia_sbh(
                citation(), SimpleNamespace(CDO_CBL_CONTENEDOR="CONT-1")
            )
        self.assertEqual(result["transporte"]["nombre_transporte"], "")
        self.assertEqual(result["documentos"]["bl"], "")
        self.assertEqual(result["recepcion"]["contenedor"], "CONT-1")

    def test_resolver_documental_separa_bl_de_contenedor_y_booking(self):
        detalle = SimpleNamespace(
            CDO_CBL_CONTENEDOR="CONT-1", CDO_CBL="BL-REAL",
            CDO_CBOOKING="BOOK-1",
        )
        queryset = MagicMock()
        queryset.order_by.return_value.first.return_value = None
        with patch.object(nj.technical.CAMION_PATIO.objects, "filter",
                          return_value=queryset), \
             patch.object(nj.technical, "_dato_valor", return_value=""):
            result = nj.technical.resolver_datos_documentales_recepcion(
                citation(), detalle
            )
        self.assertEqual(result["bl"], "CONT-1")
        self.assertEqual(result["bl_documental"], "BL-REAL")
        self.assertEqual(result["booking"], "BOOK-1")


@override_settings(BODEGA_VIRTUAL="B_TRANSI", BODEGA_VIRTUAL_NEW_JERSEY="B_NJ_TEST")
class NewJerseyP1BuilderTests(SimpleTestCase):
    def setUp(self):
        self.citacion = citation()
        self.detail = SimpleNamespace(
            CDO_CDOCENTRY="6880", CDO_CCODIGO_SAP="950105",
            CDO_CESTANQUE_DESTINO="TK08",
        )
        self.operation = SimpleNamespace(
            ONJ_CBASE_ENTRY="6880", ONJ_CBASE_LINE="",
            ONJ_CITEM_CODE="950105",
        )
        self.order = {
            "DocEntry": 6880, "DocNum": 10001091, "CardCode": "P77424780",
            "DocumentLines": [
                {"LineNum": 1, "ItemCode": "950105", "UoMCode": "MT",
                 "LineStatus": "bost_Open", "RemainingOpenQuantity": 16388.348},
            ],
        }
        self.item = {"ManageBatchNumbers": "tYES"}
        self.client = MagicMock()
        self.client.get_json.side_effect = lambda path, *_: (
            self.order if path.startswith("PurchaseOrders(") else self.item
        )
        self.lote = {"batch_number": "LOTE-PT-950105-766-01", "item_code": "950105", "correlativo": 766, "tipo_lote": "PT", "sufijo": "01"}
        self.ingreso = {
            "transporte": {
                "nombre_transporte": "TRANSPORTES SAEZ LIMITADA",
                "rut_conductor": "13796965-3",
                "nombre_conductor": "DOMINGO DIAZ PEDREROS",
                "telefono_conductor": "+569239689118",
                "patente": "SDS45",
            },
            "documentos": {
                "bl": "MDFGD4533", "cda": "", "di": "",
                "nave_naviera": "", "booking": "", "sui": "",
            },
            "fechas": {
                "fecha_produccion": "2026-05-15T00:00:00",
                "fecha_vencimiento": "2027-05-15T00:00:00",
            },
            "fechas_invalidas": {},
            "recepcion": {
                "tipo_documento": "GD", "numero_documento": "65688",
                "contenedor": "MDFGD4533",
            },
        }

    def build(self):
        with patch.object(nj, "_operacion", return_value=self.operation), \
             patch.object(nj.technical, "_latest_detail", return_value=self.detail), \
             patch.object(nj.technical, "resolver_datos_ingreso_mercaderia_sbh",
                          return_value=self.ingreso), \
             patch.object(nj.technical, "_dato_valor", return_value="24000"), \
             patch.object(nj.technical, "get_folio_from_citation",
                          return_value=("GD", 65688, [])), \
             patch.object(nj, "load_config",
                          return_value=SimpleNamespace(company_db="TEST")), \
             patch.object(nj.technical, "obtener_fecha_sistema_sap",
                          return_value="2026-09-28"), \
             patch.object(nj, "SapServiceLayerClient", return_value=self.client), \
             patch.object(nj, "obtener_lote_sap_new_jersey_p1", return_value=self.lote), \
             patch.object(nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1") as lote:
            result = nj.build_purchase_delivery_note_new_jersey_p1(self.citacion)
        return result, lote

    def test_ambas_modalidades_usan_po_kg_mt_hana_y_bodega_new_jersey(self):
        for code in nj.SECUENCIAS_NEW_JERSEY_P1:
            self.citacion.SC_NID.SE_CCODIGO = code
            result, lote = self.build()
            self.assertTrue(result["ready_for_post"], result["errors"])
            payload = result["payload"]
            line = payload["DocumentLines"][0]
            self.assertEqual(payload["DocDate"], "2026-09-28")
            self.assertEqual((line["BaseType"], line["BaseEntry"], line["BaseLine"]),
                             (22, 6880, 1))
            self.assertEqual(line["ItemCode"], "950105")
            self.assertEqual(line["Quantity"], 24)
            self.assertEqual(line["WarehouseCode"], "B_NJ_TEST")
            self.assertNotEqual(line["WarehouseCode"], "B_TRANSI")
            self.assertNotEqual(line["WarehouseCode"], "TK08")
            self.assertEqual(result["source_data"]["destino_fisico"], "TK08")
            self.assertEqual(line["BatchNumbers"][0]["BatchNumber"],
                             "LOTE-PT-950105-766-01")
            self.assertEqual(line["BatchNumbers"][0]["Quantity"], line["Quantity"])
            lote.assert_not_called()
            self.client.post_purchase_delivery_note.assert_not_called()

    def test_payload_incluye_udf_confirmados_y_omite_vacios(self):
        result, _ = self.build()
        self.assertTrue(result["ready_for_post"], result["errors"])
        payload = result["payload"]
        line = payload["DocumentLines"][0]
        self.assertEqual(payload["U_NXNombreTransporte"], "TRANSPORTES SAEZ LIMITADA")
        self.assertEqual(payload["U_NXRutChofer"], "13796965-3")
        self.assertEqual(payload["U_NXNombreChofer"], "DOMINGO DIAZ PEDREROS")
        self.assertEqual(payload["U_NXTelefonoChofer"], "+569239689118")
        self.assertNotIn("U_NXPatente", payload)
        self.assertEqual(line["U_BL"], "MDFGD4533")
        self.assertEqual(line["U_HCO_FVEN"], "2026-05-15T00:00:00")
        self.assertEqual(line["U_NXFlote"], "2027-05-15T00:00:00")
        for campo in ("U_CDA", "U_DI", "U_HCO_NAVIERAS", "U_SUI", "U_HCO_BOOKING"):
            self.assertNotIn(campo, line)
        self.assertEqual(line["BatchNumbers"], [{
            "BatchNumber": "LOTE-PT-950105-766-01", "Quantity": 24,
        }])

    def test_udf_documentales_opcionales_aparecen_al_tener_valor(self):
        self.ingreso["documentos"].update({
            "cda": "CDA-1", "di": "DI-1", "nave_naviera": "NAVIERA-1",
            "sui": "SUI-1", "booking": "BOOK-1",
        })
        result, _ = self.build()
        line = result["payload"]["DocumentLines"][0]
        self.assertEqual(line["U_CDA"], "CDA-1")
        self.assertEqual(line["U_DI"], "DI-1")
        self.assertEqual(line["U_HCO_NAVIERAS"], "NAVIERA-1")
        self.assertEqual(line["U_SUI"], "SUI-1")
        self.assertEqual(line["U_HCO_BOOKING"], "BOOK-1")

    def test_fecha_documental_invalida_bloquea_preview(self):
        self.ingreso["fechas_invalidas"] = {"fecha_produccion": "31022026"}
        result, _ = self.build()
        self.assertFalse(result["ready_for_post"])
        self.assertIn("fecha_produccion invalida", " ".join(result["errors"]))
        self.client.login.assert_not_called()

    def test_preview_sin_lote_persistido_se_bloquea_sin_generar(self):
        self.lote = {}
        result, generador = self.build()
        self.assertFalse(result["ready_for_post"])
        self.assertEqual(result["errors"], [
            "Debe generar el lote SAP antes de previsualizar el ingreso."
        ])
        generador.assert_not_called()

    def test_item_sin_lote_no_genera_batch_numbers(self):
        self.item["ManageBatchNumbers"] = "tNO"
        result, lote = self.build()
        self.assertTrue(result["ready_for_post"])
        self.assertNotIn("BatchNumbers", result["payload"]["DocumentLines"][0])
        lote.assert_not_called()

    def test_base_line_ambiguo_bloquea_documento(self):
        self.order["DocumentLines"].append({
            "LineNum": 2, "ItemCode": "950105", "UoMCode": "MT",
            "LineStatus": "bost_Open",
        })
        result, _ = self.build()
        self.assertFalse(result["ready_for_post"])
        self.assertIn("linea SAP unica", " ".join(result["errors"]))

    def test_base_line_cero_se_respeta_aunque_haya_otro_item_igual(self):
        self.operation.ONJ_CBASE_LINE = "0"
        self.order["DocumentLines"][0]["LineNum"] = 0
        self.order["DocumentLines"].append({
            "LineNum": 1, "ItemCode": "950105", "UoMCode": "MT",
            "LineStatus": "bost_Open",
        })
        result, _ = self.build()
        self.assertTrue(result["ready_for_post"], result["errors"])
        self.assertEqual(result["payload"]["DocumentLines"][0]["BaseLine"], 0)

    def test_unidad_distinta_de_mt_bloquea_conversion(self):
        self.order["DocumentLines"][0]["UoMCode"] = "KG"
        result, _ = self.build()
        self.assertFalse(result["ready_for_post"])
        self.assertIn("UoMCode KG", " ".join(result["errors"]))

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY="")
    def test_configuracion_ausente_bloquea_sin_usar_bodega_prosesa(self):
        result, _ = self.build()
        self.assertFalse(result["ready_for_post"])
        self.assertIn("BODEGA_VIRTUAL_NEW_JERSEY", " ".join(result["errors"]))
        self.client.login.assert_not_called()

    def test_otras_secuencias_no_usan_builder(self):
        for code in ("RECEPCION_NEW_JERSEY_P2", "RECEPCION_PROSESA_PISO_1",
                     "RECEPCION_ESTANQUE_SBH"):
            self.citacion.SC_NID.SE_CCODIGO = code
            result, _ = self.build()
            self.assertFalse(result["ready_for_post"])
        self.client.login.assert_not_called()


class NewJerseyP1BatchRuleTests(SimpleTestCase):
    def test_item_950105_usa_ordinal_01_y_no_ultimos_digitos(self):
        base = nj.technical.componer_lote_sap("950105", 768, 1)
        with patch.object(
            nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1",
            return_value=base,
        ) as hana:
            lote = nj.generar_lote_sap_new_jersey_p1("950105", numero_linea=1)
        self.assertEqual(lote["sufijo"], "01")
        self.assertEqual(lote["batch_number"], "LOTE-PT-950105-768-01")
        self.assertEqual(lote["numero_linea"], 1)
        hana.assert_called_once_with("950105", numero_linea=1)

    def test_segunda_linea_usa_02_aunque_item_termine_en_05(self):
        base = nj.technical.componer_lote_sap("950105", 768, 2)
        with patch.object(
            nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1",
            return_value=base,
        ) as hana:
            lote = nj.generar_lote_sap_new_jersey_p1("950105", numero_linea=2)
        self.assertEqual(lote["batch_number"], "LOTE-PT-950105-768-02")
        hana.assert_called_once_with("950105", numero_linea=2)

    def test_lote_persistido_de_otro_item_o_formato_se_rechaza(self):
        lote = {
            "item_code": "950105", "correlativo": 768,
            "batch_number": "LOTE-PT-950105-768-1",
        }
        self.assertIn("formato", nj.validar_lote_sap_new_jersey_p1(lote, "950105"))
        lote.update(nj.technical.componer_lote_sap("950105", 768, 1))
        self.assertIn("otro ItemCode", nj.validar_lote_sap_new_jersey_p1(lote, "950106"))


@override_settings(BODEGA_VIRTUAL_NEW_JERSEY="B_NJ_TEST")
class NewJerseyP1SenderTests(SimpleTestCase):
    def test_sender_usa_mismo_builder_y_bloquea_segundo_post(self):
        cit = citation()
        user = SimpleNamespace(username="test")
        payload = {"DocumentLines": [{"WarehouseCode": "B_NJ_TEST"}]}
        preview = {"ready_for_post": True, "payload": payload, "errors": []}
        client = MagicMock()
        client.post_purchase_delivery_note.return_value = {
            "status_code": 201, "data": {"DocEntry": 9001, "DocNum": 77},
        }
        status_pending = {"sent": False}
        status_created = {"sent": True, "docentry": 9001}
        with patch.object(nj.transaction, "atomic") as atomic, \
             patch.object(nj.CITACION.objects, "select_for_update") as locked, \
             patch.object(nj, "get_purchase_delivery_note_new_jersey_p1_status",
                          side_effect=[status_pending, status_created, status_created]), \
             patch.object(nj, "build_purchase_delivery_note_new_jersey_p1",
                          return_value=preview) as build, \
             patch.object(nj, "load_config", return_value=SimpleNamespace()), \
             patch.object(nj, "SapServiceLayerClient", return_value=client), \
             patch.object(nj, "_guardar_log") as save_log:
            atomic.return_value.__enter__.return_value = None
            first = nj.send_purchase_delivery_note_new_jersey_p1_to_sap(cit, user)
            second = nj.send_purchase_delivery_note_new_jersey_p1_to_sap(cit, user)
        self.assertTrue(first["success"])
        self.assertFalse(second["success"])
        build.assert_called_once_with(cit)
        client.post_purchase_delivery_note.assert_called_once_with(payload)
        self.assertEqual(save_log.call_count, 1)
        locked.return_value.get.assert_called_with(pk=38731)

    def test_sender_rechaza_preview_invalido_sin_post(self):
        cit = citation("RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD")
        with patch.object(nj.transaction, "atomic"), \
             patch.object(nj.CITACION.objects, "select_for_update"), \
             patch.object(nj, "get_purchase_delivery_note_new_jersey_p1_status",
                          return_value={"sent": False}), \
             patch.object(nj, "build_purchase_delivery_note_new_jersey_p1",
                          return_value={"ready_for_post": False, "errors": ["sin bodega"]}), \
             patch.object(nj, "SapServiceLayerClient") as client:
            result = nj.send_purchase_delivery_note_new_jersey_p1_to_sap(
                cit, SimpleNamespace(username="test")
            )
        self.assertFalse(result["success"])
        client.assert_not_called()


class NewJerseyP1ModalContractTests(SimpleTestCase):
    def test_modal_muestra_estanque_destino_y_peso_readonly(self):
        template = (
            Path(views.__file__).resolve().parents[1] / "templates" / "home"
            / "PLANIFICACION" / "pla_listone.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="estanque_operacional"', template)
        self.assertIn('id="destino_sap_inicial"', template)
        self.assertIn("esProsesaPiso1 || esNewJerseyP1", template)
        self.assertIn("data-capturado-revision=", template)
        self.assertIn("datos.peso_capturado_en_revision ? 'readonly'", template)
        self.assertIn("previewNewJerseyP1Habilitado", template)
        self.assertIn("estanqueCamionEsRecepcionNewJerseyP1", template)
        self.assertIn("Previsualizar Ingreso SAP", template)
        self.assertIn("Crear Ingreso SAP", template)
        self.assertIn('id="btn_generar_lote_sap_new_jersey_p1"', template)
        self.assertIn('id="lote_sap_new_jersey_p1"', template)
        self.assertIn("loteSapNewJersey.batch_number || ''", template)
        self.assertIn("generar-lote-sap-new-jersey/", template)
        self.assertIn("estanqueCamionEsRecepcionNewJerseyP1 ? !!response.estanque_guardado_operacional", template)

    def test_backend_no_acepta_peso_del_post_y_preview_respeta_flag(self):
        source = Path(views.__file__).read_text(encoding="utf-8")
        start = source.index("def PLANIFICACION_CITACION_ESTANQUE")
        end = source.index("def AVANZAR_ESTANQUE_SIGUIENTE_ETAPA")
        section = source[start:end]
        self.assertIn("obtener_peso_informado_guia(citacion)\n", section)
        self.assertIn("if peso_guia_unidad_revision", section)
        self.assertIn("if not peso_guia_unidad_revision:", section)
        self.assertIn("build_purchase_delivery_note_new_jersey_p1(citacion)", section)
        self.assertIn("SAP_RECEPCION_PREVIEW_ENABLED", section)

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home.models import (
    CALENDARIO, CAMPO, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION,
    DETALLE_SECUENCIA, EMPRESA, ETAPA, ETAPA_LOG, PLANIFICACION, SECUENCIA,
)


@override_settings(
    BODEGA_VIRTUAL="B_TRANSI",
    BODEGA_VIRTUAL_NEW_JERSEY="B_NJ_TEST",
)
class NewJerseyP1EndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="nj_modal", email="nj@example.com", password="test"
        )
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL="SBH", EP_CRUT="99-9",
            EP_CBASEDATOS="TEST", EP_CUSUARIOSBD="test", EP_CPORT="0",
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE="NJ modal",
            CA_FHORA_APERTURA="00:00", CA_FHORA_CIERRE="23:59",
            CA_NDIA=28, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=2,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO="RECEPCION", PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=2,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO="RECEPCION",
            SE_CCODIGO="RECEPCION_NEW_JERSEY_P1_CON_CALIDAD",
            SE_CNOMBRE="NJ P1", SE_BHABILITADO=True,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, ET_CTIPO="OPERACION",
            ET_CCODIGO="NJ_ACD", ET_CNOMBRE="Asistente CD",
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa, SE_NPASO=3, SE_BOBLIGATORIO=True,
            SE_BHABILITADO=True,
        )
        cls.citacion = views.CITACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, PL_NID=cls.planificacion,
            SC_NID=cls.secuencia, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1,
            CI_CTIPO="RECEPCION", CI_CESTADO="EN PROCESO",
            CI_CTIPODOCUMENTO="GD", CI_CNUMERODOCUMENTO="65688",
        )
        ETAPA_LOG.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa, US_INICIO_ID=cls.user,
            EL_FFECHAINICIO=timezone.now(),
        )
        cls.detalle = CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa, US_NID=cls.user,
            CDO_CORIGEN="planificacion", CDO_CALMACEN_DESTINO="SBH",
            CDO_CESTANQUE_DESTINO="TK08", CDO_CDOCENTRY="6880",
            CDO_CCODIGO_SAP="950105",
        )
        cls.campo_peso = CAMPO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CTIPO="TEXTO",
            CA_CCODIGO="SAP_PESO_INFORMADO_GUIA",
            CA_CETIQUETA="Peso guia kg", CA_BHABILITADO=True,
        )
        DATO_OPERACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa, CAMP_NID=cls.campo_peso,
            CI_NID=cls.citacion, DO_CVALOR="24000",
            DO_FFECHAREGISTRO=timezone.now(),
        )

    def request(self, method="post", data=None):
        factory = RequestFactory()
        path = f"/pla-citacion-estanque/{self.citacion.pk}/"
        req = (factory.post(path, data or {}) if method == "post"
               else factory.get(path))
        req.user = self.user
        return req

    def test_preview_flag_y_mismo_builder_sin_envio(self):
        preview = {
            "ready_for_post": True, "errors": [], "payload": {
                "DocumentLines": [{"WarehouseCode": "B_NJ_TEST", "Quantity": 24}]
            },
        }
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "build_purchase_delivery_note_new_jersey_p1",
                          return_value=preview) as builder, \
             patch.object(views, "send_purchase_delivery_note_new_jersey_p1_to_sap") as sender:
            with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True):
                response = views.PLANIFICACION_CITACION_ESTANQUE(
                    self.request(data={"preview_sap": "1"}), self.citacion.pk
                )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(json.loads(response.content)["read_only"])
            builder.assert_called_once()
            sender.assert_not_called()
            with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False):
                disabled = views.PLANIFICACION_CITACION_ESTANQUE(
                    self.request(data={"preview_sap": "1"}), self.citacion.pk
                )
            self.assertEqual(disabled.status_code, 404)

    def test_preview_sin_lote_devuelve_error_y_no_envia(self):
        mensaje = "Debe generar el lote SAP antes de previsualizar el ingreso."
        preview = {"ready_for_post": False, "errors": [mensaje], "payload": {}}
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "build_purchase_delivery_note_new_jersey_p1",
                          return_value=preview) as builder, \
             patch.object(views, "send_purchase_delivery_note_new_jersey_p1_to_sap") as sender:
            with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True):
                response = views.PLANIFICACION_CITACION_ESTANQUE(
                    self.request(data={"preview_sap": "1"}), self.citacion.pk
                )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["message"], mensaje)
        builder.assert_called_once()
        sender.assert_not_called()

    def test_get_muestra_destino_fisico_virtual_y_peso_readonly(self):
        with patch.object(views, "Verificar_empresa", return_value=2):
            response = views.PLANIFICACION_CITACION_ESTANQUE(
                self.request(method="get"), self.citacion.pk
            )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["es_recepcion_new_jersey_p1"])
        self.assertEqual(data["destino_sap_inicial"], "B_NJ_TEST")
        self.assertEqual(data["estanque_destino"], "TK08")
        self.assertEqual(data["peso_informado_guia"], "24000")
        self.assertEqual(data["peso_unidad"], "kg")
        self.assertTrue(data["peso_capturado_en_revision"])

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False)
    def test_get_oculta_preview_con_flag_desactivada(self):
        with patch.object(views, "Verificar_empresa", return_value=2):
            response = views.PLANIFICACION_CITACION_ESTANQUE(
                self.request(method="get"), self.citacion.pk
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)["sap_recepcion_preview_enabled"])

    def test_post_manipulado_no_reemplaza_peso_heredado(self):
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "reservar_estanque_citacion",
                          return_value=(None, None)), \
             patch.object(views, "registrar_log_camion_no_planificado"):
            response = views.PLANIFICACION_CITACION_ESTANQUE(
                self.request(data={
                    "estanque": "TK08", "peso_informado": "99999",
                    "documentos_revisados": "1",
                }), self.citacion.pk
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            DATO_OPERACION.objects.filter(CI_NID=self.citacion,
                CAMP_NID=self.campo_peso).order_by("-id")
            .values_list("DO_CVALOR", flat=True).first(), "24000"
        )

    def test_generar_lote_endpoint_persiste_y_no_acepta_item_code_del_browser(self):
        client = MagicMock()
        client.get_json.return_value = {"ManageBatchNumbers": "tYES"}
        base = {
            "item_code": "950105", "tipo_lote": "PT", "correlativo": 768,
            "sufijo": "01", "batch_number": "LOTE-PT-950105-768-01",
        }
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "obtener_dato_estanque_operacional",
                          return_value=SimpleNamespace(DO_CVALOR="TK08")), \
             patch.object(nj, "load_config",
                          return_value=SimpleNamespace(company_db="TEST")), \
             patch.object(nj, "SapServiceLayerClient", return_value=client), \
             patch.object(nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1",
                          return_value=base) as hana:
            first = views.PLANIFICACION_NEW_JERSEY_P1_GENERAR_LOTE_SAP(
                self.request(data={"item_code": "INVENTADO"}), self.citacion.pk
            )
            second = views.PLANIFICACION_NEW_JERSEY_P1_GENERAR_LOTE_SAP(
                self.request(data={"item_code": "INVENTADO"}), self.citacion.pk
            )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        first_lote = json.loads(first.content)["lote_sap"]
        self.assertEqual(first_lote["item_code"], "950105")
        self.assertEqual(first_lote["batch_number"], "LOTE-PT-950105-768-01")
        self.assertEqual(first_lote, json.loads(second.content)["lote_sap"])
        self.assertEqual(first_lote["usuario"], self.user.username)
        self.assertEqual(first_lote["citacion"], self.citacion.pk)
        with patch.object(views, "Verificar_empresa", return_value=2):
            modal = views.PLANIFICACION_CITACION_ESTANQUE(
                self.request(method="get"), self.citacion.pk
            )
        self.assertEqual(modal.status_code, 200)
        self.assertEqual(
            json.loads(modal.content)["lote_sap_new_jersey"]["batch_number"],
            first_lote["batch_number"],
        )
        self.assertTrue(first_lote["fecha_hora"])
        hana.assert_called_once_with("950105", numero_linea=1)
        client.get_json.assert_called_once()
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=nj.CAMPO_LOTE_SAP_NEW_JERSEY_P1,
            ).count(), 1
        )
        self.assertEqual(
            nj.obtener_lote_sap_new_jersey_p1(self.citacion)["batch_number"],
            "LOTE-PT-950105-768-01",
        )

    def _guardar_candidato_legacy(self):
        campo = CAMPO.objects.create(
            US_NID=self.user, EP_NID=self.empresa, CA_CTIPO="TEXTO",
            CA_CCODIGO=nj.CAMPO_LOTE_SAP_NEW_JERSEY_P1,
            CA_CETIQUETA="Lote SAP New Jersey", CA_BHABILITADO=True,
        )
        viejo = {
            "citacion": self.citacion.pk, "item_code": "950105",
            "tipo_lote": "PT", "correlativo": 768, "sufijo": "05",
            "batch_number": "LOTE-PT-950105-768-05",
            "fecha_hora": "2026-09-28T10:07:23-03:00",
        }
        DATO_OPERACION.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SC_NID=self.secuencia,
            ET_NID=self.etapa, CAMP_NID=campo, CI_NID=self.citacion,
            DO_CVALOR=json.dumps(viejo), DO_FFECHAREGISTRO=timezone.now(),
        )
        return viejo

    def test_candidato_legacy_se_corrige_sin_nuevo_correlativo(self):
        viejo = self._guardar_candidato_legacy()
        with patch.object(nj, "_lote_existe_en_sap", return_value=False) as sap, \
             patch.object(nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1") as contador, \
             patch.object(nj, "SapServiceLayerClient") as client:
            nuevo = nj.generar_y_guardar_lote_sap_new_jersey_p1(
                self.citacion, self.user
            )
        self.assertEqual(nuevo["batch_number"], "LOTE-PT-950105-768-01")
        self.assertEqual(nuevo["correlativo"], 768)
        self.assertEqual(nuevo["lote_anterior"], viejo["batch_number"])
        self.assertEqual(
            nuevo["fecha_hora_lote_anterior"], viejo["fecha_hora"]
        )
        self.assertEqual(
            nj.obtener_lote_sap_new_jersey_p1(self.citacion)["batch_number"],
            "LOTE-PT-950105-768-01",
        )
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=nj.CAMPO_LOTE_SAP_NEW_JERSEY_P1,
            ).count(), 1,
        )
        sap.assert_called_once_with("950105", viejo["batch_number"])
        contador.assert_not_called()
        client.assert_not_called()

    def test_candidato_legacy_en_sap_no_se_modifica(self):
        viejo = self._guardar_candidato_legacy()
        with patch.object(nj, "_lote_existe_en_sap", return_value=True), \
             patch.object(nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1") as contador:
            with self.assertRaisesRegex(
                nj.technical.GoodsReceiptDraftError, "ya existe en SAP"
            ):
                nj.generar_y_guardar_lote_sap_new_jersey_p1(
                    self.citacion, self.user
                )
        self.assertEqual(
            nj.obtener_lote_sap_new_jersey_p1(self.citacion)["batch_number"],
            viejo["batch_number"],
        )
        contador.assert_not_called()

    def test_ingreso_sap_ya_enviado_no_corrige_candidato_local(self):
        viejo = self._guardar_candidato_legacy()
        with patch.object(
            nj, "get_purchase_delivery_note_new_jersey_p1_status",
            return_value={"sent": True},
        ), patch.object(nj, "_lote_existe_en_sap") as sap:
            with self.assertRaisesRegex(
                nj.technical.GoodsReceiptDraftError, "ya fue creado"
            ):
                nj.generar_y_guardar_lote_sap_new_jersey_p1(
                    self.citacion, self.user
                )
        self.assertEqual(
            nj.obtener_lote_sap_new_jersey_p1(self.citacion)["batch_number"],
            viejo["batch_number"],
        )
        sap.assert_not_called()

    def test_generar_lote_exige_estanque_guardado(self):
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "obtener_dato_estanque_operacional",
                          return_value=None), \
             patch.object(nj, "generar_lote_sap_new_jersey_p1") as generar:
            response = views.PLANIFICACION_NEW_JERSEY_P1_GENERAR_LOTE_SAP(
                self.request(data={}), self.citacion.pk
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("guardar el estanque", json.loads(response.content)["message"])
        generar.assert_not_called()

    def test_preview_y_envio_usan_mismo_lote_persistido_sin_regenerar(self):
        client = MagicMock()
        order = {
            "DocEntry": 6880, "DocNum": 10001091, "CardCode": "P77424780",
            "DocumentLines": [{
                "LineNum": 1, "ItemCode": "950105", "UoMCode": "MT",
                "LineStatus": "bost_Open", "RemainingOpenQuantity": 100,
            }],
        }
        client.get_json.side_effect = lambda path, *_: (
            order if path.startswith("PurchaseOrders(")
            else {"ManageBatchNumbers": "tYES"}
        )
        client.post_purchase_delivery_note.return_value = {
            "status_code": 201, "data": {"DocEntry": 9901, "DocNum": 77},
        }
        base = {
            "item_code": "950105", "tipo_lote": "PT", "correlativo": 768,
            "sufijo": "01", "batch_number": "LOTE-PT-950105-768-01",
        }
        with patch.object(nj, "load_config",
                          return_value=SimpleNamespace(company_db="TEST")), \
             patch.object(nj, "SapServiceLayerClient", return_value=client), \
             patch.object(nj.technical, "obtener_fecha_sistema_sap",
                          return_value="2026-09-28"), \
             patch.object(nj.technical, "generar_lote_sap_recepcion_prosesa_piso_1",
                          return_value=base) as hana:
            lote = nj.generar_y_guardar_lote_sap_new_jersey_p1(
                self.citacion, self.user
            )
            preview = nj.build_purchase_delivery_note_new_jersey_p1(self.citacion)
            sent = nj.send_purchase_delivery_note_new_jersey_p1_to_sap(
                self.citacion, self.user
            )
            duplicate = nj.send_purchase_delivery_note_new_jersey_p1_to_sap(
                self.citacion, self.user
            )
        self.assertTrue(preview["ready_for_post"], preview["errors"])
        self.assertTrue(sent["success"], sent)
        self.assertFalse(duplicate["success"])
        preview_line = preview["payload"]["DocumentLines"][0]
        sent_line = sent["preview"]["payload"]["DocumentLines"][0]
        self.assertEqual(preview_line["BatchNumbers"][0]["BatchNumber"],
                         lote["batch_number"])
        self.assertEqual(sent_line["BatchNumbers"][0]["BatchNumber"],
                         lote["batch_number"])
        self.assertEqual(preview_line["BatchNumbers"][0]["Quantity"],
                         preview_line["Quantity"])
        self.assertEqual(preview_line["Quantity"], 24)
        self.assertEqual(preview_line["WarehouseCode"], "B_NJ_TEST")
        hana.assert_called_once_with("950105", numero_linea=1)
        client.post_purchase_delivery_note.assert_called_once_with(sent["preview"]["payload"])

    def test_avance_exige_ingreso_sap_real(self):
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "obtener_dato_estanque_operacional",
                          return_value=SimpleNamespace(DO_CVALOR="TK08")):
            response = views.AVANZAR_ESTANQUE_SIGUIENTE_ETAPA(
                self.request(data={}), self.citacion.pk
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Debe crear el Ingreso SAP", json.loads(response.content)["message"])

    def test_endpoint_crear_ingreso_usa_sender_new_jersey(self):
        request = self.request(data={})
        with patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "obtener_dato_estanque_operacional",
                          return_value=SimpleNamespace(DO_CVALOR="TK08")), \
             patch.object(views, "send_purchase_delivery_note_new_jersey_p1_to_sap",
                          return_value={"success": True, "status": {"sent": True}}) as sender:
            response = views.PLANIFICACION_BORRADOR_SAP_PESO_GUIA_ENVIAR(
                request, self.citacion.pk
            )
        self.assertEqual(response.status_code, 200)
        sender.assert_called_once()
