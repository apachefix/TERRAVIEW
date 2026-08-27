import os
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import sap_di_proforma
from apps.home.tests.test_sap_di_proforma import FakeCompany


class SapDiCentralConfigTestCase(SimpleTestCase):
    def _environment(self, environment, sbh_company_db):
        return {
            "SAP_ENVIRONMENT": environment,
            "SAP_TERRAMAR_SERVER": "terramar.example.local:30013",
            "SAP_TERRAMAR_COMPANY_DB": (
                "TESTTERRACHILE" if environment == "QA" else "SBOTERRACHILE"
            ),
            "SAP_TERRAMAR_DB_SERVER_TYPE": "9",
            "SAP_TERRAMAR_USE_TRUSTED": "False",
            "SAP_TERRAMAR_USER": "terramar_user",
            "SAP_TERRAMAR_PASSWORD": "terramar_password",
            "SAP_SBH_SERVER": "sbh.example.local:30013",
            "SAP_SBH_COMPANY_DB": sbh_company_db,
            "SAP_SBH_DB_SERVER_TYPE": "9",
            "SAP_SBH_USE_TRUSTED": "False",
            "SAP_SBH_USER": "sbh_user",
            "SAP_SBH_PASSWORD": "sbh_password",
        }

    def test_sbh_qa_permite_sbo_tst_sbh_usd(self):
        company = FakeCompany()
        environment = self._environment("QA", "SBO_TST_SBH_USD")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ):
            result = sap_di_proforma.sapConnect(2)

        self.assertIs(result, company)
        self.assertEqual(company.CompanyDB, "SBO_TST_SBH_USD")
        self.assertEqual(company.connect_calls, 1)

    def test_sbh_production_permite_sbo_sbh_usd(self):
        company = FakeCompany()
        environment = self._environment("PRODUCTION", "SBO_SBH_USD")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch", return_value=company
        ):
            result = sap_di_proforma.sapConnect(2)

        self.assertIs(result, company)
        self.assertEqual(company.CompanyDB, "SBO_SBH_USD")
        self.assertEqual(company.connect_calls, 1)

    def test_sbh_qa_rechaza_base_productiva_antes_de_dispatch(self):
        environment = self._environment("QA", "SBO_SBH_USD")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch"
        ) as dispatch:
            with self.assertRaisesRegex(
                sap_di_proforma.SapDiApiError, "SBO_TST_SBH_USD"
            ):
                sap_di_proforma.sapConnect(2)

        dispatch.assert_not_called()

    def test_sbh_production_rechaza_base_qa_antes_de_dispatch(self):
        environment = self._environment("PRODUCTION", "SBO_TST_SBH_USD")
        with patch.dict(os.environ, environment, clear=False), patch.object(
            sap_di_proforma.dynamic, "Dispatch"
        ) as dispatch:
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "SBO_SBH_USD"):
                sap_di_proforma.sapConnect(2)

        dispatch.assert_not_called()

    def test_variable_legacy_sap_di_environment_no_es_fuente_de_verdad(self):
        environment = self._environment("QA", "SBO_TST_SBH_USD")
        environment["SAP_ENVIRONMENT"] = ""
        environment["SAP_DI_ENVIRONMENT"] = "QA"
        with patch.dict(os.environ, environment, clear=True), patch.object(
            sap_di_proforma.dynamic, "Dispatch"
        ) as dispatch:
            with self.assertRaisesRegex(sap_di_proforma.SapDiApiError, "SAP_ENVIRONMENT"):
                sap_di_proforma.sapConnect(2)

        dispatch.assert_not_called()
