import inspect
import json
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.home import sap_despacho, sap_despacho_envio, views
from apps.home.despacho_carga import CargaInvalida
from apps.home.models import (
    CALENDARIO,
    CAMPO,
    CITACION,
    CITACION_DESPACHO_ACUERDO_ESTANQUE,
    CITACION_DESPACHO_ACUERDO_LOTE,
    CITACION_DESPACHO_ACUERDO_OPERACIONAL,
    CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DRAFT_SAP,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    PLANIFICACION,
    SECUENCIA,
)


class DistribucionPesoRealTests(SimpleTestCase):
    def test_peso_neto_producto_no_vuelve_a_descontar_entrada(self):
        with patch.object(sap_despacho, "obtener_pesaje_real_despacho", return_value={
            "peso_entrada_kg": Decimal("16030"),
            "peso_salida_bruto_kg": Decimal("43730"),
            "peso_neto_producto_kg": Decimal("27700"),
            "cantidad_real_mt": Decimal("27.70"),
        }):
            entrada, salida, neto_kg, neto_mt = sap_despacho.calcular_peso_real_despachado(object())
        self.assertEqual((entrada, salida, neto_kg, neto_mt), (
            Decimal("16030"), Decimal("43730"), Decimal("27700"), Decimal("27.70")
        ))

    def test_formula_semantica_no_usa_abs(self):
        source = inspect.getsource(sap_despacho.obtener_pesaje_real_despacho)
        self.assertIn('peso_neto_producto_kg', source)
        self.assertNotIn("abs(", source)

    def test_ticket_salida_con_peso_neto_explicito(self):
        lineas = [
            "03-09-2026 08:17 16.030 PJE/AUTO",
            "03-09-2026 09:34 43.730 PJE/AUTO",
            "Peso Neto 27.700",
        ]
        pesos = views._extraer_pesos_semanticos_ticket(lineas, "SAL")
        self.assertEqual(pesos["peso_entrada_kg"], 16030)
        self.assertEqual(pesos["peso_salida_bruto_kg"], 43730)
        self.assertEqual(pesos["peso_neto_producto_kg"], 27700)
        self.assertEqual(pesos["fuente_peso_neto"], "ticket_explicito")
        self.assertEqual(pesos["peso_neto_calculado_kg"], 27700)
        self.assertEqual(pesos["diferencia_control_kg"], 0)
        self.assertTrue(pesos["control_pesaje_ok"])

    def test_ticket_salida_sin_peso_neto_calcula_desde_pesadas(self):
        lineas = [
            "03-09-2026 08:17 16.030 PJE/AUTO",
            "03-09-2026 09:34 43.730 PJE/AUTO",
        ]
        pesos = views._extraer_pesos_semanticos_ticket(lineas, "SAL")
        self.assertEqual(pesos["peso_neto_producto_kg"], 27700)
        self.assertEqual(pesos["fuente_peso_neto"], "calculado_desde_pesadas")
        self.assertTrue(pesos["control_pesaje_ok"])

    def test_fallback_mantiene_peso_neto_legacy_pero_expone_neto_producto(self):
        texto = "\n".join([
            "Folio Nro",
            "349281",
            "03-09-2026 08:17 16.030 PJE/AUTO",
            "03-09-2026 09:34 43.730 PJE/AUTO",
        ])
        pagina = SimpleNamespace(extract_text=lambda: texto)
        with patch("builtins.open", mock_open(read_data=b"%PDF")), patch.object(
            views, "PdfReader", return_value=SimpleNamespace(pages=[pagina])
        ):
            datos = views._extraer_datos_ticket_pesaje(
                "ticket.pdf",
                "SAL",
                semantica_despacho_sbh=True,
            )
        self.assertEqual(datos["peso_neto"], 43730)
        self.assertEqual(datos["peso_neto_producto_kg"], 27700)
        self.assertEqual(datos["fuente_peso_neto"], "calculado_desde_pesadas")

    def test_ticket_salida_explicito_inconsistente_queda_invalido(self):
        lineas = [
            "03-09-2026 08:17 16.030 PJE/AUTO",
            "03-09-2026 09:34 43.730 PJE/AUTO",
            "Peso Neto 26.000",
        ]
        pesos = views._extraer_pesos_semanticos_ticket(lineas, "SAL")
        self.assertEqual(pesos["peso_neto_calculado_kg"], 27700)
        self.assertEqual(pesos["diferencia_control_kg"], 1700)
        self.assertFalse(pesos["control_pesaje_ok"])

    def test_metadata_mantiene_peso_neto_historico_y_agrega_semantica(self):
        datos = {
            "folio": "349281",
            "peso_neto": 27700,
            "observacion": "",
            "peso_entrada_kg": 16030,
            "peso_salida_bruto_kg": 43730,
            "peso_neto_producto_kg": 27700,
            "fuente_peso_neto": "ticket_explicito",
            "peso_neto_calculado_kg": 27700,
            "diferencia_control_kg": 0,
            "control_pesaje_ok": True,
        }
        metadata = views._metadata_ticket_pesaje(
            SimpleNamespace(id=38709),
            "Pesaje Salida",
            "SAL",
            "SRXS8D",
            "COM_SAL_SRXS8D_26_09_03_09_34.pdf",
            datos,
            SimpleNamespace(id=1884),
        )
        self.assertEqual(metadata["peso_neto"], 27700)
        self.assertEqual(metadata["peso_neto_producto_kg"], 27700)
        self.assertEqual(metadata["peso_salida_bruto_kg"], 43730)
        self.assertEqual(metadata["fuente_peso_neto"], "ticket_explicito")

    def test_un_lote_recibe_el_total_real(self):
        payload = {"DocumentLines": [{"Quantity": 27.5, "BatchNumbers": [{"BatchNumber": "A", "Quantity": 27.5}]}]}
        final = sap_despacho._distribuir_payload_draft(payload, Decimal("27.22"))
        self.assertEqual(final["DocumentLines"][0]["Quantity"], 27.22)
        self.assertEqual(final["DocumentLines"][0]["BatchNumbers"][0]["Quantity"], 27.22)

    def test_dos_y_tres_lotes_conservan_primeros_y_asignan_remanente(self):
        self.assertEqual(
            sap_despacho.distribuir_cantidad_secuencial([20, 7.5], Decimal("27.22")),
            [Decimal("20"), Decimal("7.22")],
        )
        self.assertEqual(
            sap_despacho.distribuir_cantidad_secuencial([10, 10, 7.5], Decimal("26.8")),
            [Decimal("10"), Decimal("10"), Decimal("6.8")],
        )

    def test_caso_critico_27_50_conserva_lotes_11_96_y_15_54(self):
        payload = {"DocumentLines": [{
            "ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 27.5,
            "BatchNumbers": [
                {"BatchNumber": "LOTE-A", "Quantity": 11.96},
                {"BatchNumber": "LOTE-B", "Quantity": 15.54},
            ],
        }]}
        final = sap_despacho._distribuir_payload_draft(payload, Decimal("27.50"))
        linea = final["DocumentLines"][0]
        self.assertEqual(Decimal(str(linea["Quantity"])), Decimal("27.5"))
        self.assertEqual(
            [(lote["BatchNumber"], Decimal(str(lote["Quantity"]))) for lote in linea["BatchNumbers"]],
            [("LOTE-A", Decimal("11.96")), ("LOTE-B", Decimal("15.54"))],
        )

    def test_caso_critico_27_70_conserva_primero_y_ajusta_ultimo_lote(self):
        payload = {"DocumentLines": [{
            "ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 27.5,
            "BatchNumbers": [
                {"BatchNumber": "LOTE-A", "Quantity": 11.96},
                {"BatchNumber": "LOTE-B", "Quantity": 15.54},
            ],
        }]}
        final = sap_despacho._distribuir_payload_draft(payload, Decimal("27.70"))
        linea = final["DocumentLines"][0]
        cantidades = [Decimal(str(lote["Quantity"])) for lote in linea["BatchNumbers"]]
        self.assertEqual(cantidades, [Decimal("11.96"), Decimal("15.74")])
        self.assertEqual(sum(cantidades), Decimal(str(linea["Quantity"])))

    def test_caso_11_67_omite_solo_lote_cuya_cantidad_final_es_cero(self):
        payload = {"DocumentLines": [{
            "ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 27.5,
            "BatchNumbers": [
                {"BatchNumber": "LOTE-A", "Quantity": 11.96},
                {"BatchNumber": "LOTE-B", "Quantity": 15.54},
            ],
        }]}
        final = sap_despacho._distribuir_payload_draft(payload, Decimal("11.67"))
        linea = final["DocumentLines"][0]
        self.assertEqual(linea["BatchNumbers"], [{"BatchNumber": "LOTE-A", "Quantity": 11.67}])
        self.assertEqual(linea["Quantity"], 11.67)

    def test_peso_inferior_al_primer_lote_no_genera_negativos(self):
        self.assertEqual(
            sap_despacho.distribuir_cantidad_secuencial([20, 7.5], Decimal("18")),
            [Decimal("18"), Decimal("0")],
        )

    def test_sumas_de_batches_y_lineas_son_exactas(self):
        payload = {"DocumentLines": [
            {"Quantity": 20, "BatchNumbers": [{"BatchNumber": "A", "Quantity": 10}, {"BatchNumber": "B", "Quantity": 10}]},
            {"Quantity": 7.5, "BatchNumbers": [{"BatchNumber": "C", "Quantity": 5}, {"BatchNumber": "D", "Quantity": 2.5}]},
        ]}
        final = sap_despacho._distribuir_payload_draft(payload, Decimal("26.8"))
        for line in final["DocumentLines"]:
            self.assertEqual(sum(Decimal(str(batch["Quantity"])) for batch in line["BatchNumbers"]), Decimal(str(line["Quantity"])))
        self.assertEqual(sum(Decimal(str(line["Quantity"])) for line in final["DocumentLines"]), Decimal("26.8"))

    def test_disponibilidad_final_usa_stock_sap_menos_reservas_locales(self):
        documentos = [{
            "payload": {
                "DocumentLines": [{
                    "ItemCode": "980057",
                    "WarehouseCode": "TK04",
                    "BatchNumbers": [{"BatchNumber": "LOTE-A", "Quantity": 27.95}],
                }],
            },
        }]
        catalogos = {
            4092: {
                "stocks": {
                    "980057": [{
                        "item_code": "980057",
                        "warehouse_code": "TK04",
                        "batch_number": "LOTE-A",
                        "stock_sap": "30",
                        "reservado": "2.05",
                        "disponible": "27.95",
                    }],
                },
            },
        }
        citacion = SimpleNamespace(pk=38707)

        with patch.object(
            sap_despacho_envio,
            "_catalogos_y_stock_actual",
            return_value=(catalogos, {}),
        ), patch.object(sap_despacho_envio, "configuracion_persistida"):
            resultado = sap_despacho_envio.validar_disponibilidad_final_despacho(
                citacion,
                object(),
                documentos,
            )

        self.assertTrue(resultado["disponibilidad_lotes_suficiente"])
        self.assertEqual(resultado["lotes"][0]["disponibilidad_actual"], "27.95")

        catalogos[4092]["stocks"]["980057"][0]["disponible"] = "27.94"
        with patch.object(
            sap_despacho_envio,
            "_catalogos_y_stock_actual",
            return_value=(catalogos, {}),
        ), patch.object(sap_despacho_envio, "configuracion_persistida"), self.assertRaisesMessage(
            CargaInvalida,
            "No existe disponibilidad suficiente en los lotes SAP para cubrir la cantidad real despachada.",
        ):
            sap_despacho_envio.validar_disponibilidad_final_despacho(
                citacion,
                object(),
                documentos,
            )


class ActualizacionDraftPesoRealTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("peso_real_test")
        cls.empresa = EMPRESA.objects.create(pk=2, EP_CRAZONSOCIAL="SBH", EP_CRUT="22-2", EP_CBASEDATOS="TEST", EP_CUSUARIOSBD="test", EP_CPORT="0")
        calendario = CALENDARIO.objects.create(US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE="Peso real",
            CA_FHORA_APERTURA="08:00", CA_FHORA_CIERRE="18:00", CA_NDIA=1, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=2)
        cls.secuencia = SECUENCIA.objects.create(US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO="DESPACHO", SE_CCODIGO="PESO_REAL", SE_CNOMBRE="Peso real", SE_BHABILITADO=True)
        cls.etapa = ETAPA.objects.create(US_NID=cls.user, EP_NID=cls.empresa, ET_CTIPO="OPERACION", ET_CCODIGO="PESO", ET_CNOMBRE="Peso", ET_NCANTIDADMAXIMA=1)
        plan = PLANIFICACION.objects.create(US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=calendario,
            PL_CTIPOCUPO="DESPACHO", PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=2)
        cls.citacion = CITACION.objects.create(EP_NID=cls.empresa, US_NID=cls.user, PL_NID=plan, SC_NID=cls.secuencia,
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO="DESPACHO", CI_CESTADO="PENDIENTE")
        tickets = (
            ("OP_TICKET_PESAJE_ENT", 16030, {
                "peso_neto": 16030,
                "peso_entrada_kg": 16030,
            }),
            ("OP_TICKET_PESAJE_SAL", 27700, {
                "peso_neto": 27700,
                "peso_entrada_kg": 16030,
                "peso_salida_bruto_kg": 43730,
                "peso_neto_producto_kg": 27700,
                "fuente_peso_neto": "ticket_explicito",
                "peso_neto_calculado_kg": 27700,
                "diferencia_control_kg": 0,
                "control_pesaje_ok": True,
            }),
        )
        for codigo, peso, metadata in tickets:
            campo = CAMPO.objects.create(US_NID=cls.user, EP_NID=cls.empresa, CA_CTIPO="NUMERO", CA_CCODIGO=codigo, CA_CETIQUETA=codigo)
            DATO_OPERACION.objects.create(US_NID=cls.user, EP_NID=cls.empresa, SC_NID=cls.secuencia, ET_NID=cls.etapa,
                CAMP_NID=campo, CI_NID=cls.citacion, DO_CVALOR=json.dumps(metadata), DO_NPESO=peso)

    def setUp(self):
        self.carga = CITACION_DESPACHO_CARGA.objects.create(CI_NID=self.citacion, US_NID=self.user, cantidad_total=Decimal("27.5"), zona_carga="Linea 1")

    @staticmethod
    def pesaje_valido(neto="27.22", entrada="15500"):
        entrada = Decimal(entrada)
        neto = Decimal(neto)
        salida = entrada + neto * Decimal("1000")
        neto_kg = neto * Decimal("1000")
        return {
            "peso_entrada_kg": entrada,
            "peso_entrada_ticket_ent_kg": entrada,
            "peso_entrada_ticket_sal_kg": entrada,
            "peso_salida_bruto_kg": salida,
            "peso_neto_producto_kg": neto_kg,
            "peso_neto_calculado_kg": neto_kg,
            "diferencia_control_kg": Decimal("0"),
            "fuente_peso_neto": "ticket_explicito",
            "fuente_peso_neto_label": "Ticket — Peso Neto explícito",
            "control_disponible": True,
            "control_pesaje_ok": True,
            "cantidad_real_mt": neto,
            "errors": [],
            "warnings": [],
        }

    def crear_acuerdo(self, orden, abs_id, numero, cantidad, lotes, item="980057", docentry=None):
        acuerdo = CITACION_DESPACHO_ACUERDO_OPERACIONAL.objects.create(carga=self.carga, sap_abs_id=abs_id,
            numero_acuerdo=numero, cliente_codigo="C001", cliente_nombre="Cliente", cantidad=Decimal(str(cantidad)), orden=orden)
        estanque = CITACION_DESPACHO_ACUERDO_ESTANQUE.objects.create(acuerdo=acuerdo, warehouse_code="TK04", item_code=item,
            item_name="Producto", linea_acuerdo="1", unidad_medida="MT", cantidad=Decimal(str(cantidad)), orden=1)
        for batch, qty in lotes:
            CITACION_DESPACHO_ACUERDO_LOTE.objects.create(estanque=estanque, batch_number=batch,
                stock_snapshot=Decimal("100"), cantidad=Decimal(str(qty)))
        payload = {"DocumentLines": [{"ItemCode": item, "AgreementNo": abs_id, "WarehouseCode": "TK04",
            "Quantity": float(cantidad), "BatchNumbers": [{"BatchNumber": batch, "Quantity": float(qty)} for batch, qty in lotes]}]}
        return CITACION_DESPACHO_DRAFT_SAP.objects.create(acuerdo=acuerdo, clave_idempotencia=f"test-{self.citacion.pk}-{abs_id}",
            estado="CREADO", docentry=str(docentry or (3500 + orden)), docnum=str(16000 + orden), payload=payload, respuesta={"DocEntry": docentry})

    def configurar_pesajes(self, entrada_ent=44250, entrada_sal=16300, salida_bruta=44250, neto=27950):
        entrada = DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO="OP_TICKET_PESAJE_ENT",
        )
        entrada.DO_CVALOR = json.dumps({
            "peso_neto": entrada_ent,
            "peso_entrada_kg": entrada_ent,
        })
        entrada.DO_NPESO = entrada_ent
        entrada.save(update_fields=["DO_CVALOR", "DO_NPESO"])

        salida = DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO="OP_TICKET_PESAJE_SAL",
        )
        salida.DO_CVALOR = json.dumps({
            "peso_neto": neto,
            "peso_entrada_kg": entrada_sal,
            "peso_salida_bruto_kg": salida_bruta,
            "peso_neto_producto_kg": neto,
            "fuente_peso_neto": "ticket_explicito",
            "peso_neto_calculado_kg": salida_bruta - entrada_sal,
            "diferencia_control_kg": salida_bruta - entrada_sal - neto,
            "control_pesaje_ok": salida_bruta - entrada_sal == neto,
        })
        salida.DO_NPESO = neto
        salida.save(update_fields=["DO_CVALOR", "DO_NPESO"])

    def test_registros_historicos_reconstruyen_semantica_con_el_mismo_parser(self):
        for tipo in ("ENT", "SAL"):
            dato = DATO_OPERACION.objects.get(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=f"OP_TICKET_PESAJE_{tipo}",
            )
            dato.DO_CVALOR = json.dumps({
                "peso_neto": dato.DO_NPESO,
                "ruta_real_pdf": f"C:/tickets/legacy-{tipo}.pdf",
            })
            dato.save(update_fields=["DO_CVALOR"])

        def reconstruir(_ruta, tipo, **_kwargs):
            if tipo == "ENT":
                return {"peso_neto": 16030, "peso_entrada_kg": 16030}
            return {
                "peso_neto": 27700,
                "peso_entrada_kg": 16030,
                "peso_salida_bruto_kg": 43730,
                "peso_neto_producto_kg": 27700,
                "fuente_peso_neto": "ticket_explicito",
                "peso_neto_calculado_kg": 27700,
                "diferencia_control_kg": 0,
                "control_pesaje_ok": True,
            }

        with patch.object(sap_despacho.os.path, "isfile", return_value=True), patch.object(
            views, "_extraer_datos_ticket_pesaje", side_effect=reconstruir
        ) as parser:
            pesaje = sap_despacho.obtener_pesaje_real_despacho(self.citacion)
        self.assertEqual(parser.call_count, 2)
        self.assertEqual(pesaje["peso_salida_bruto_kg"], Decimal("43730"))
        self.assertEqual(pesaje["peso_neto_producto_kg"], Decimal("27700"))
        self.assertEqual(pesaje["cantidad_real_mt"], Decimal("27.7"))
        self.assertEqual(pesaje["errors"], [])

    def test_ent_distinto_de_primera_pesada_sal_permite_preview_con_warning(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3534)
        self.configurar_pesajes()

        pesaje = sap_despacho.obtener_pesaje_real_despacho(self.citacion)
        diagnostico = sap_despacho.construir_diagnostico_preview_update_drafts_operacionales(
            self.citacion
        )

        self.assertEqual(pesaje["peso_entrada_ticket_ent_kg"], Decimal("44250"))
        self.assertEqual(pesaje["peso_entrada_ticket_sal_kg"], Decimal("16300"))
        self.assertEqual(pesaje["cantidad_real_mt"], Decimal("27.95"))
        self.assertEqual(pesaje["errors"], [])
        self.assertIn("Advertencia:", pesaje["warnings"][0])
        self.assertTrue(diagnostico["success"])
        self.assertEqual(diagnostico["resultado"], "PREVIEW VÁLIDO CON ADVERTENCIAS")
        self.assertEqual(diagnostico["motivos"], [])
        self.assertEqual(diagnostico["warnings"], pesaje["warnings"])

    def test_ent_distinto_de_primera_pesada_sal_permite_update(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3534)
        self.configurar_pesajes()
        client = MagicMock()
        client.patch_draft.return_value = {"status_code": 204, "data": {}}

        with patch.object(sap_despacho, "load_config", return_value=object()):
            resultado = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
                self.citacion,
                self.user,
                client_factory=lambda _config: client,
            )

        self.assertTrue(resultado["success"])
        self.assertIn("Advertencia:", resultado["message"])
        payload = client.patch_draft.call_args.args[1]
        self.assertEqual(Decimal(str(payload["DocumentLines"][0]["Quantity"])), Decimal("27.95"))

    def test_lotes_insuficientes_bloquean_preview_y_update(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3534)
        CITACION_DESPACHO_ACUERDO_LOTE.objects.filter(batch_number="B").update(
            stock_snapshot=Decimal("7.5")
        )
        self.configurar_pesajes()

        preview = sap_despacho.construir_preview_update_drafts_operacionales(self.citacion)
        client_factory = MagicMock()
        resultado = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
            self.citacion,
            self.user,
            client_factory=client_factory,
        )

        mensaje = "No existe disponibilidad suficiente en los lotes SAP para cubrir la cantidad real despachada."
        self.assertIn(mensaje, preview["errors"])
        self.assertFalse(resultado["success"])
        self.assertEqual(resultado["message"], mensaje)
        client_factory.assert_not_called()

    def test_disponibilidad_sap_actual_insuficiente_bloquea_antes_del_patch(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3534)
        self.configurar_pesajes()
        client_factory = MagicMock()
        mensaje = "No existe disponibilidad suficiente en los lotes SAP para cubrir la cantidad real despachada."

        with patch(
            "apps.home.sap_despacho_envio.validar_disponibilidad_final_despacho",
            side_effect=CargaInvalida(mensaje),
        ):
            resultado = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
                self.citacion,
                self.user,
                client_factory=client_factory,
                revalidar_disponibilidad=True,
            )

        self.assertFalse(resultado["success"])
        self.assertEqual(resultado["message"], mensaje)
        client_factory.assert_not_called()

    def test_peso_neto_cero_sigue_bloqueando(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3534)
        self.configurar_pesajes(salida_bruta=16300, neto=0)
        client_factory = MagicMock()

        resultado = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
            self.citacion,
            self.user,
            client_factory=client_factory,
        )

        self.assertFalse(resultado["success"])
        self.assertIn("mayor que cero", resultado["message"])
        client_factory.assert_not_called()

    def test_salida_menor_o_igual_a_entrada_bloquea_sin_patch(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 20), ("B", 7.5)], docentry=3528)
        client_factory = MagicMock()
        pesaje_invalido = self.pesaje_valido()
        pesaje_invalido.update({
            "peso_salida_bruto_kg": Decimal("15000"),
            "peso_neto_producto_kg": None,
            "cantidad_real_mt": None,
            "control_pesaje_ok": False,
            "errors": ["El peso bruto de salida es menor al peso de entrada."],
        })
        with patch.object(sap_despacho, "obtener_pesaje_real_despacho", return_value=pesaje_invalido):
            result = sap_despacho.actualizar_borradores_sap_despacho_operacionales(self.citacion, self.user, client_factory=client_factory)
        self.assertFalse(result["success"])
        self.assertIn("salida es menor", result["message"])
        client_factory.assert_not_called()

    def test_un_acuerdo_dos_lotes_caso_estructural_38707(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [("LOTE-PT-980057-6-01", 20), ("LOTE-PT-980057-7-01", 7.5)], docentry=3528)
        preview = sap_despacho.construir_preview_update_drafts_operacionales(self.citacion)
        self.assertEqual(preview["errors"], [])
        documento = preview["documentos"][0]
        self.assertEqual(documento["docentry"], 3528)
        self.assertEqual(documento["cantidad_final"], 27.7)
        self.assertEqual(
            [b["Quantity"] for b in documento["payload"]["DocumentLines"][0]["BatchNumbers"]],
            [20, 7.7],
        )

    def test_dos_acuerdos_mismo_producto_y_ultimo_con_n_lotes(self):
        self.crear_acuerdo(1, 4092, "429", 20, [("A", 20)], docentry=3528)
        self.crear_acuerdo(2, 4093, "430", 7.5, [("B1", 5), ("B2", 2.5)], docentry=3529)
        with patch.object(sap_despacho, "obtener_pesaje_real_despacho", return_value=self.pesaje_valido()):
            preview = sap_despacho.construir_preview_update_drafts_operacionales(self.citacion)
        self.assertEqual([d["cantidad_final"] for d in preview["documentos"]], [20, 7.22])
        self.assertEqual([b["Quantity"] for b in preview["documentos"][1]["payload"]["DocumentLines"][0]["BatchNumbers"]], [5, 2.22])

    def test_productos_distintos_bloquean_sin_tolerancia_por_planificacion(self):
        self.crear_acuerdo(1, 4092, "429", 20, [("A", 20)], item="980057")
        self.crear_acuerdo(2, 4093, "430", 7.5, [("B", 7.5)], item="800040")
        preview = sap_despacho.construir_preview_update_drafts_operacionales(self.citacion)
        self.assertIn("productos distintos", " ".join(preview["errors"]))
        self.assertNotIn("tolerancia", " ".join(preview["errors"]).lower())

    def test_patch_mockeado_reutiliza_drafts_y_no_crea_ni_hace_post(self):
        self.crear_acuerdo(1, 4092, "429", 20, [("A", 20)], docentry=3528)
        self.crear_acuerdo(2, 4093, "430", 7.5, [("B", 7.5)], docentry=3529)
        client = MagicMock()
        client.patch_draft.return_value = {"status_code": 204, "data": {}}
        with patch.object(sap_despacho, "load_config", return_value=object()), patch.object(
            sap_despacho, "obtener_pesaje_real_despacho", return_value=self.pesaje_valido()
        ):
            result = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
                self.citacion, self.user, client_factory=lambda config: client
            )
        self.assertTrue(result["success"])
        self.assertEqual([call.args[0] for call in client.patch_draft.call_args_list], [3528, 3529])
        client.post_draft.assert_not_called()
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.count(), 2)
        self.assertTrue(all(d.respuesta["actualizacion_peso_real"]["success"] for d in CITACION_DESPACHO_DRAFT_SAP.objects.all()))

    def test_patch_critico_envia_coleccion_completa_y_replace_collections(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [
            ("LOTE-A", 11.96),
            ("LOTE-B", 15.54),
        ], docentry=3530)
        client = MagicMock()
        client.patch_draft.return_value = {"status_code": 204, "data": {}}
        with patch.object(sap_despacho, "load_config", return_value=object()), patch.object(
            sap_despacho,
            "obtener_pesaje_real_despacho",
            return_value=self.pesaje_valido("27.70", "16030"),
        ):
            result = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
                self.citacion, self.user, client_factory=lambda config: client
            )
        self.assertTrue(result["success"])
        client.patch_draft.assert_called_once()
        docentry, payload = client.patch_draft.call_args.args
        self.assertEqual(docentry, 3530)
        self.assertTrue(client.patch_draft.call_args.kwargs["replace_collections"])
        linea = payload["DocumentLines"][0]
        self.assertEqual(
            [(lote["BatchNumber"], Decimal(str(lote["Quantity"]))) for lote in linea["BatchNumbers"]],
            [("LOTE-A", Decimal("11.96")), ("LOTE-B", Decimal("15.74"))],
        )
        self.assertEqual(
            sum(Decimal(str(lote["Quantity"])) for lote in linea["BatchNumbers"]),
            Decimal(str(linea["Quantity"])),
        )

    def test_payload_incompleto_bloquea_antes_de_abrir_sesion_sap(self):
        payload_original = {"DocumentLines": [{
            "ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 27.5,
            "BatchNumbers": [
                {"BatchNumber": "LOTE-A", "Quantity": 11.96},
                {"BatchNumber": "LOTE-B", "Quantity": 15.54},
            ],
        }]}
        payload_incompleto = {"DocumentLines": [{
            "ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 27.5,
            "BatchNumbers": [{"BatchNumber": "LOTE-A", "Quantity": 27.5}],
        }]}
        preview = {
            "errors": [],
            "documentos": [{
                "acuerdo_id": 1, "actualizado": False, "cantidad_final": 27.5,
                "payload_original": payload_original, "payload": payload_incompleto,
            }],
        }
        client_factory = MagicMock()
        with patch.object(sap_despacho, "construir_preview_update_drafts_operacionales", return_value=preview), patch.object(
            sap_despacho, "_get_sap_despacho_update_status_operacional", return_value={}
        ):
            result = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
                self.citacion, self.user, client_factory=client_factory
            )
        self.assertFalse(result["success"])
        self.assertIn("bloqueado por validación estructural", result["message"])
        client_factory.assert_not_called()

    def test_pesaje_inconsistente_bloquea_antes_de_llamar_sap(self):
        self.crear_acuerdo(1, 4092, "429", 27.5, [
            ("LOTE-A", 11.96),
            ("LOTE-B", 15.54),
        ], docentry=3530)
        dato_salida = DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO="OP_TICKET_PESAJE_SAL",
        )
        metadata = json.loads(dato_salida.DO_CVALOR)
        metadata.update({
            "peso_entrada_kg": 16030,
            "peso_salida_bruto_kg": 43730,
            "peso_neto_producto_kg": 26000,
            "peso_neto_calculado_kg": 27700,
            "diferencia_control_kg": 1700,
            "fuente_peso_neto": "ticket_explicito",
            "control_pesaje_ok": False,
        })
        dato_salida.DO_CVALOR = json.dumps(metadata)
        dato_salida.DO_NPESO = 26000
        dato_salida.save(update_fields=["DO_CVALOR", "DO_NPESO"])

        client_factory = MagicMock()
        result = sap_despacho.actualizar_borradores_sap_despacho_operacionales(
            self.citacion,
            self.user,
            client_factory=client_factory,
        )
        self.assertFalse(result["success"])
        self.assertIn("no coincide", result["message"])
        client_factory.assert_not_called()

    def test_diagnostico_reutiliza_payload_real_y_no_persiste_ni_inicia_sap(self):
        draft = self.crear_acuerdo(1, 4092, "429", 27.5, [
            ("LOTE-PT-980057-6-01", 20),
            ("LOTE-PT-980057-7-01", 7.5),
        ], docentry=3528)
        draft.respuesta = {
            "actualizacion_peso_real": {
                "success": True,
                "usuario": "operador_local",
                "SessionId": "secreto-sap",
            }
        }
        draft.save(update_fields=["respuesta"])
        payload_antes = json.loads(json.dumps(draft.payload))
        respuesta_antes = json.loads(json.dumps(draft.respuesta))
        datos_antes = list(DATO_OPERACION.objects.filter(CI_NID=self.citacion).values_list("id", "DO_CVALOR", "DO_NPESO"))

        with patch.object(sap_despacho, "SapServiceLayerClient") as cliente_sap:
            resultado = sap_despacho.construir_diagnostico_preview_update_drafts_operacionales(self.citacion)

        cliente_sap.assert_not_called()
        self.assertTrue(resultado["success"])
        documento = resultado["documentos"][0]
        self.assertEqual(documento["draft"]["docentry"], 3528)
        self.assertEqual(documento["endpoint"], "PATCH /Drafts(3528)")
        self.assertEqual(documento["headers"], {"B1S-ReplaceCollectionsOnPatch": "true"})
        self.assertEqual(documento["payload_original"], payload_antes)
        self.assertEqual(
            documento["payload_patch"],
            sap_despacho._distribuir_payload_draft(payload_antes, Decimal("27.70")),
        )
        self.assertTrue(documento["validacion"]["suma_lotes_igual_linea"])
        self.assertTrue(documento["validacion"]["suma_lineas_igual_acuerdo"])
        self.assertEqual(documento["ultima_actualizacion_registrada"]["SessionId"], "[OCULTO]")
        self.assertNotIn("secreto-sap", json.dumps(resultado))
        self.assertEqual(documento["ultima_actualizacion_registrada"]["usuario"], "operador_local")

        draft.refresh_from_db()
        self.assertEqual(draft.payload, payload_antes)
        self.assertEqual(draft.respuesta, respuesta_antes)
        self.assertEqual(
            list(DATO_OPERACION.objects.filter(CI_NID=self.citacion).values_list("id", "DO_CVALOR", "DO_NPESO")),
            datos_antes,
        )

    def test_diagnostico_multiacuerdo_genera_documentos_independientes(self):
        self.crear_acuerdo(1, 4092, "429", 20, [("A", 20)], docentry=3528)
        self.crear_acuerdo(2, 4093, "430", 7.5, [("B1", 5), ("B2", 2.5)], docentry=3529)
        with patch.object(
            sap_despacho,
            "obtener_pesaje_real_despacho",
            return_value=self.pesaje_valido(),
        ):
            resultado = sap_despacho.construir_diagnostico_preview_update_drafts_operacionales(self.citacion)
        self.assertTrue(resultado["success"])
        self.assertEqual([item["endpoint"] for item in resultado["documentos"]], [
            "PATCH /Drafts(3528)", "PATCH /Drafts(3529)"
        ])
        self.assertEqual([item["cantidad_operacional"]["final_mt"] for item in resultado["documentos"]], [20, 7.22])
        self.assertEqual(
            [lote["Quantity"] for lote in resultado["documentos"][1]["payload_patch"]["DocumentLines"][0]["BatchNumbers"]],
            [5, 2.22],
        )
        self.assertTrue(resultado["validacion_estructural"]["acuerdos_separados_correctamente"])

    def test_diagnostico_multiwarehouse_conserva_lineas_y_valida_sumas(self):
        draft = self.crear_acuerdo(1, 4092, "429", 27.5, [("A", 27.5)], docentry=3528)
        estanque_principal = draft.acuerdo.estanques.get(warehouse_code="TK04")
        estanque_principal.cantidad = Decimal("15")
        estanque_principal.save(update_fields=["cantidad"])
        lote_principal = estanque_principal.lotes.get()
        lote_principal.batch_number = "TK04-A"
        lote_principal.cantidad = Decimal("15")
        lote_principal.save(update_fields=["batch_number", "cantidad"])
        estanque_secundario = CITACION_DESPACHO_ACUERDO_ESTANQUE.objects.create(
            acuerdo=draft.acuerdo,
            warehouse_code="TKMX01",
            item_code="980057",
            item_name="Producto",
            linea_acuerdo="1",
            unidad_medida="MT",
            cantidad=Decimal("12.5"),
            orden=2,
        )
        CITACION_DESPACHO_ACUERDO_LOTE.objects.create(
            estanque=estanque_secundario,
            batch_number="TKMX01-A",
            stock_snapshot=Decimal("100"),
            cantidad=Decimal("12.5"),
        )
        draft.payload = {"DocumentLines": [
            {"ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TK04", "Quantity": 15,
             "BatchNumbers": [{"BatchNumber": "TK04-A", "Quantity": 15}]},
            {"ItemCode": "980057", "AgreementNo": 4092, "WarehouseCode": "TKMX01", "Quantity": 12.5,
             "BatchNumbers": [{"BatchNumber": "TKMX01-A", "Quantity": 12.5}]},
        ]}
        draft.save(update_fields=["payload"])
        with patch.object(
            sap_despacho,
            "obtener_pesaje_real_despacho",
            return_value=self.pesaje_valido(),
        ):
            resultado = sap_despacho.construir_diagnostico_preview_update_drafts_operacionales(self.citacion)
        documento = resultado["documentos"][0]
        self.assertEqual(
            [(linea["WarehouseCode"], linea["Quantity"]) for linea in documento["payload_patch"]["DocumentLines"]],
            [("TK04", 15), ("TKMX01", 12.22)],
        )
        self.assertTrue(documento["validacion"]["suma_lotes_igual_linea"])
        self.assertTrue(documento["validacion"]["suma_lineas_igual_acuerdo"])

class PreviewSapDespachoViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, is_active=True, is_superuser=True)

    @override_settings(SAP_DESPACHO_PREVIEW_ENABLED=False)
    def test_backend_rechaza_preview_deshabilitado_sin_calcular(self):
        request = self.factory.post('/preview/')
        request.user = self.user
        with patch.object(views, 'construir_diagnostico_preview_update_drafts_operacionales') as construir:
            response = views.ajax_operacion_planta_preview_sap_despacho(request, 38707)
        self.assertEqual(response.status_code, 404)
        construir.assert_not_called()

    @override_settings(SAP_DESPACHO_PREVIEW_ENABLED=True)
    def test_backend_habilitado_devuelve_preview_sin_cliente_sap(self):
        request = self.factory.post('/preview/')
        request.user = self.user
        citacion = SimpleNamespace(pk=38707, EP_NID_id=2)
        preview = {
            'success': True,
            'resultado': 'PREVIEW VÁLIDO',
            'citacion': 38707,
            'documentos': [],
            'validacion_estructural': {},
            'motivos': [],
        }
        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), \
             patch.object(views, '_obtener_citacion_operacion_planta_ajax', return_value=(citacion, None)), \
             patch.object(views, 'es_despacho_sbh_operacion', return_value=True), \
             patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True), \
             patch.object(views, 'obtener_pasos_operacion_citacion', return_value=(None, [])), \
             patch.object(views, 'obtener_paso_activo_operacion', return_value=(views.PASO_AUTORIZAR_SALIDA, ['ASISTENTE C D'], None)), \
             patch.object(views, 'usuario_puede_paso_operacion', return_value=True), \
             patch.object(views, 'construir_diagnostico_preview_update_drafts_operacionales', return_value=preview) as construir, \
             patch.object(views, '_registrar_log_preview_sap_despacho') as registrar_log, \
             patch.object(sap_despacho, 'SapServiceLayerClient') as cliente_sap:
            response = views.ajax_operacion_planta_preview_sap_despacho(request, 38707)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), preview)
        construir.assert_called_once_with(citacion)
        registrar_log.assert_called_once_with(preview)
        cliente_sap.assert_not_called()

    @override_settings(SAP_DESPACHO_PREVIEW_ENABLED=True)
    def test_backend_mantiene_permiso_funcional(self):
        request = self.factory.post('/preview/')
        request.user = self.user
        with patch.object(views, 'usuario_es_operacion_planta', return_value=False):
            response = views.ajax_operacion_planta_preview_sap_despacho(request, 38707)
        self.assertEqual(response.status_code, 403)

    def test_boton_se_renderiza_solo_si_bandera_esta_habilitada(self):
        ruta = Path(__file__).resolve().parents[3] / 'apps' / 'templates' / 'home' / 'CITACION' / 'operacion_planta.html'
        source = ruta.read_text(encoding='utf-8')
        inicio = source.index('{% if paso.sap_despacho_preview_enabled and paso.activo and paso.puede_editar %}')
        fin = source.index('{% endif %}', inicio) + len('{% endif %}')
        fragmento = Template(source[inicio:fin])
        habilitado = fragmento.render(Context({'paso': {
            'sap_despacho_preview_enabled': True, 'activo': True, 'puede_editar': True,
        }}))
        deshabilitado = fragmento.render(Context({'paso': {
            'sap_despacho_preview_enabled': False, 'activo': True, 'puede_editar': True,
        }}))
        self.assertIn('Previsualizar actualización SAP', habilitado)
        self.assertIn('btn-preview-sap-despacho', habilitado)
        self.assertNotIn('Previsualizar actualización SAP', deshabilitado)
        self.assertNotIn('btn-preview-sap-despacho', deshabilitado)

        inicio_actualizar = source.index('{% if paso.activo and paso.puede_editar and not paso.sap_update_despacho.updated %}', fin)
        fin_actualizar = source.index('Actualizar documento SAP', inicio_actualizar) + len('Actualizar documento SAP')
        bloque_actualizar = source[inicio_actualizar:fin_actualizar]
        self.assertIn('btn-actualizar-sap-despacho', bloque_actualizar)
        self.assertNotIn('sap_despacho_preview_enabled', bloque_actualizar)

    def test_warning_ent_sal_tiene_render_separado_de_errores(self):
        ruta = Path(__file__).resolve().parents[3] / 'apps' / 'templates' / 'home' / 'CITACION' / 'operacion_planta.html'
        source = ruta.read_text(encoding='utf-8')
        self.assertIn('response.warnings || []', source)
        self.assertIn('Advertencias no bloqueantes:', source)

    def test_endpoint_recepcion_no_usa_validacion_de_lotes_de_despacho(self):
        source = inspect.getsource(views.ajax_operacion_planta_actualizar_sap_recepcion)
        self.assertNotIn('validar_disponibilidad_final_despacho', source)
        self.assertIn('send_goods_receipt_draft_update_to_sap', source)
