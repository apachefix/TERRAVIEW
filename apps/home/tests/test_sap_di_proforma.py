import os
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import sap_di_proforma


class FakeCompany:
    def __init__(self, *, connect_result=0, connected_company_db=None, error=None):
        self.Connected = False
        self.CompanyDB = ""
        self.connect_result = connect_result
        self.connected_company_db = connected_company_db
        self.error = error or (-100, "Error de conexion")
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.get_business_object_calls = 0

    def Connect(self):
        self.connect_calls += 1
        if self.connect_result == 0:
            self.Connected = True
            if self.connected_company_db is not None:
                self.CompanyDB = self.connected_company_db
        return self.connect_result

    def Disconnect(self):
        self.disconnect_calls += 1
        self.Connected = False

    def GetLastError(self):
        return self.error

    def GetBusinessObject(self, _object_type):
        self.get_business_object_calls += 1
        raise AssertionError("GetBusinessObject no debe ejecutarse en estos tests")


class SapDiProformaTestCase(SimpleTestCase):
    def _environment(self, environment="QA", terramar_db="TESTTERRACHILE"):
        return {
            "SAP_ENVIRONMENT": environment,
            "SAP_TERRAMAR_SERVER": "NDB@qa.example.local:30013",
            "SAP_TERRAMAR_COMPANY_DB": terramar_db,
            "SAP_TERRAMAR_DB_SERVER_TYPE": "9",
            "SAP_TERRAMAR_USE_TRUSTED": "False",
            "SAP_TERRAMAR_USER": "qa_terramar",
            "SAP_TERRAMAR_PASSWORD": "terramar-secret",
            "SAP_SBH_SERVER": "sb-hana.example.local:30013",
            "SAP_SBH_COMPANY_DB": "SBO_TST_SBH_USD",
            "SAP_SBH_DB_SERVER_TYPE": "9",
            "SAP_SBH_USE_TRUSTED": "False",
            "SAP_SBH_USER": "sap_sbh",
            "SAP_SBH_PASSWORD": "sbh-secret",
        }

    def test_terramar_qa_permite_testterrachile(self):
        company = FakeCompany()
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ) as dispatch:
            result = sap_di_proforma.sapConnect(1)

        self.assertIs(result, company)
        self.assertEqual(company.CompanyDB, "TESTTERRACHILE")
        self.assertEqual(company.Server, "NDB@qa.example.local:30013")
        self.assertEqual(company.DbServerType, 9)
        self.assertFalse(company.UseTrusted)
        self.assertEqual(company.connect_calls, 1)
        dispatch.assert_called_once_with("SAPbobsCOM.Company")

    def test_terramar_production_permite_sboterrachile(self):
        company = FakeCompany()
        environment = self._environment("PRODUCTION", "SBOTERRACHILE")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ):
            result = sap_di_proforma.sapConnect(1)

        self.assertIs(result, company)
        self.assertEqual(company.CompanyDB, "SBOTERRACHILE")
        self.assertEqual(company.connect_calls, 1)

    def test_qa_rechaza_sboterrachile_antes_de_connect(self):
        company = FakeCompany()
        environment = self._environment("QA", "SBOTERRACHILE")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ) as dispatch:
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "TESTTERRACHILE"):
                sap_di_proforma.sapConnect(1)

        dispatch.assert_not_called()
        self.assertEqual(company.connect_calls, 0)

    def test_production_rechaza_testterrachile_antes_de_connect(self):
        company = FakeCompany()
        environment = self._environment("PRODUCTION", "TESTTERRACHILE")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ) as dispatch:
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "SBOTERRACHILE"):
                sap_di_proforma.sapConnect(1)

        dispatch.assert_not_called()
        self.assertEqual(company.connect_calls, 0)

    def test_company_db_conectada_distinta_aborta_antes_de_get_business_object(self):
        company = FakeCompany(connected_company_db="OTRA_BASE")
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ):
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "no coincide"):
                sap_di_proforma.sapConnect(1)

        self.assertEqual(company.get_business_object_calls, 0)
        self.assertEqual(company.disconnect_calls, 1)

    def test_empresa_desconocida_lanza_error_explicito(self):
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch"
        ) as dispatch:
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "Empresa 99"):
                sap_di_proforma.sapConnect(99)

        dispatch.assert_not_called()

    def test_terramar_y_sbh_crean_instancias_independientes(self):
        terramar = FakeCompany()
        sbh = FakeCompany()
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", side_effect=[terramar, sbh]
        ) as dispatch:
            terramar_result = sap_di_proforma.sapConnect(1)
            sbh_result = sap_di_proforma.sapConnect(2)

        self.assertIsNot(terramar_result, sbh_result)
        self.assertEqual(terramar.CompanyDB, "TESTTERRACHILE")
        self.assertEqual(sbh.CompanyDB, "SBO_TST_SBH_USD")
        self.assertEqual(dispatch.call_count, 2)

    def test_connect_fallido_entrega_error_controlado(self):
        company = FakeCompany(connect_result=-1, error=(-111, "Licencia no disponible"))
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ):
            with self.assertRaisesRegex(
                sap_di_proforma.SapDiApiError, "Codigo=-111.*Licencia no disponible"
            ):
                sap_di_proforma.sapConnect(1)

        self.assertEqual(company.connect_calls, 1)
        self.assertEqual(company.get_business_object_calls, 0)

    def test_password_no_aparece_en_logs_ni_excepcion(self):
        password = "terramar-secret"
        company = FakeCompany(
            connect_result=-1,
            error=(-222, f"Credencial invalida: {password}"),
        )
        with patch.dict(os.environ, self._environment(), clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ), self.assertLogs(sap_di_proforma.logger, level="INFO") as captured:
            with self.assertRaises(sap_di_proforma.SapDiApiError) as error:
                sap_di_proforma.sapConnect(1)

        self.assertNotIn(password, str(error.exception))
        self.assertNotIn(password, "\n".join(captured.output))
        self.assertIn("******", str(error.exception))
