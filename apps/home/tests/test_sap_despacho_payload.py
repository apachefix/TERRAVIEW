from datetime import time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    CITACION_DESPACHO_ASIGNACION_SAP,
    CITACION_DESPACHO_DETALLE,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
)
from apps.home.sap_despacho_payload import construir_payload_despacho
from apps.home import despacho_carga


class PayloadDespachoSBHTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("payload_test")
        cls.empresa = EMPRESA.objects.create(
            pk=2, EP_CRAZONSOCIAL="SBH", EP_CRUT="22-2", EP_CBASEDATOS="TEST",
            EP_CUSUARIOSBD="test", EP_CPORT="0",
        )
        calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE="Carga",
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18), CA_NDIA=1,
            CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=20,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO="DESPACHO",
            SE_CCODIGO="CARGA", SE_CNOMBRE="Carga", SE_BHABILITADO=True,
        )
        plan = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=calendario,
            PL_CTIPOCUPO="DESPACHO", PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=20,
        )
        cls.citacion = CITACION.objects.create(
            EP_NID=cls.empresa, US_NID=cls.user, PL_NID=plan, SC_NID=secuencia,
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO="DESPACHO",
            CI_CESTADO="PENDIENTE",
        )
        cls.detalle = CITACION_DESPACHO_DETALLE.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa, US_NID=cls.user,
            CDD_CSALIDA_DOCUMENTO="GD",
        )
        for orden, abs_id, numero, item, oc in [
            (1, "4138", "433", "900129", "OC-433"),
            (2, "5000", "434", "800041", "OC-434"),
        ]:
            CITACION_DESPACHO_ASIGNACION_SAP.objects.create(
                CDD_NID=cls.detalle, EP_NID=cls.empresa,
                CDAS_CSAP_ABS_ID=abs_id, CDAS_CSAP_NUMERO_ACUERDO=numero,
                CDAS_CSAP_LINEA_ACUERDO="1", CDAS_CSAP_CODIGO_PRODUCTO=item,
                CDAS_CSAP_CLIENTE_CODIGO="C77424780", CDAS_CSAP_CLIENTE_NOMBRE="Cliente",
                CDAS_CSAP_OC_CLIENTE=oc, CDAS_NCANTIDAD_INTENTADA_DESPACHAR=1, CDAS_NORDEN=orden,
            )

    def config(self):
        return {
            "acuerdos": [
                {"sap_abs_id": 4138, "cliente_codigo": "C77424780", "oc_cliente": "OC-433",
                 "estanques": [{"item_code": "900129", "warehouse_code": "TK01", "cantidad": 15,
                                "lotes": [{"batch_number": "A", "cantidad": 10}, {"batch_number": "B", "cantidad": 5}]}]},
                {"sap_abs_id": 5000, "cliente_codigo": "C77424780", "oc_cliente": "OC-434",
                 "estanques": [{"item_code": "800041", "warehouse_code": "TK02", "cantidad": 1,
                                "lotes": [{"batch_number": "C", "cantidad": 1}]}]},
            ]
        }

    def base_payloads(self):
        return {
            4138: {"Series": 116, "DocObjectCode": "15", "CardCode": "C77424780",
                   "DocDate": "2026-08-26", "DocumentLines": [{"ItemCode": "900129", "AgreementNo": 4138,
                   "WarehouseCode": "TK01", "Quantity": 15, "BatchNumbers": [{"ItemCode": "900129", "BatchNumber": "A", "Quantity": 10},
                   {"ItemCode": "900129", "BatchNumber": "B", "Quantity": 5}]}]},
            5000: {"Series": 116, "DocObjectCode": "15", "CardCode": "C77424780",
                   "DocDate": "2026-08-26", "DocumentLines": [{"ItemCode": "800041", "AgreementNo": 5000,
                   "WarehouseCode": "TK02", "Quantity": 1, "BatchNumbers": [{"ItemCode": "800041", "BatchNumber": "C", "Quantity": 1}]}]},
        }

    @patch("apps.home.sap_despacho_payload._datos_operacion", return_value={"REV_TIPO_DESPACHO": "2", "REV_TIPO_TRASLADO": "2"})
    @patch("apps.home.sap_despacho_payload.preparar_payloads")
    def test_mapeo_completo_y_un_draft_por_absid(self, preparar, _datos):
        preparar.return_value = self.base_payloads()
        camion = SimpleNamespace(CPA_CTRANSPORTISTA_DECLARADO="Transportes X", CPA_CNOMBRE_CONDUCTOR="Ana Chofer",
                                 CPA_CRUT_CONDUCTOR="11-1", CPA_CTELEFONO_CONDUCTOR="+56911111111",
                                 CPA_CPATENTE="ABCD12", CPA_CPATENTE_RAMPLA="RAM123")
        payloads = construir_payload_despacho(self.citacion, self.config(), camion=camion, series=116)
        self.assertEqual(set(payloads), {4138, 5000})
        first = payloads[4138]
        self.assertEqual(first["U_NXTipoDesp"], "2")
        self.assertEqual(first["U_NXIndTras"], "2")
        self.assertEqual(first["AgreementNo"], 4138) if "AgreementNo" in first else None
        self.assertEqual(first["CardCode"], "C77424780")
        self.assertEqual(first["U_NXNombreTransporte"], "Transportes X")
        self.assertEqual(first["U_NXNombreChofer"], "Ana Chofer")
        self.assertEqual(first["U_NXPatente"], "ABCD12")
        self.assertEqual(first["U_NXSemi"], "RAM123")
        self.assertEqual(first["U_NXOC"], "OC-433")
        self.assertEqual(first["ReserveInvoice"], "tNO")
        self.assertEqual(first["Indicator"], "52")
        self.assertEqual(sum(b["Quantity"] for b in first["DocumentLines"][0]["BatchNumbers"]), 15)
        self.assertNotEqual(payloads[4138]["DocumentLines"][0]["AgreementNo"], payloads[5000]["DocumentLines"][0]["AgreementNo"])

    @patch("apps.home.sap_despacho_payload._datos_operacion", return_value={"REV_TIPO_DESPACHO": "2", "REV_TIPO_TRASLADO": "2"})
    @patch("apps.home.sap_despacho_payload.preparar_payloads")
    def test_suma_lotes_inconsistente_rechazada(self, preparar, _datos):
        payloads = self.base_payloads()
        payloads[4138]["DocumentLines"][0]["BatchNumbers"][0]["Quantity"] = 9
        preparar.return_value = payloads
        with self.assertRaisesRegex(despacho_carga.CargaInvalida, "BatchNumbers"):
            construir_payload_despacho(self.citacion, self.config(), series=116)

    @patch("apps.home.sap_despacho_payload._datos_operacion", return_value={"REV_TIPO_DESPACHO": "", "REV_TIPO_TRASLADO": ""})
    @patch("apps.home.sap_despacho_payload.preparar_payloads")
    def test_tipos_documento_obligatorios(self, preparar, _datos):
        preparar.return_value = self.base_payloads()
        with self.assertRaisesRegex(despacho_carga.CargaInvalida, "TIPO_DESPACHO"):
            construir_payload_despacho(self.citacion, self.config(), series=116)

