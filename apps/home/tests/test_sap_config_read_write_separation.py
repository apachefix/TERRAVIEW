import os
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import sap_di_api, sap_di_proforma


class SapReadWriteConfigurationSeparationTestCase(SimpleTestCase):
    def _environment(self):
        return {
            "SAP_ENVIRONMENT": "QA",
            "SAP_TERRAMAR_SERVER": "terramar-qa.example.local:30013",
            "SAP_TERRAMAR_COMPANY_DB": "TESTTERRACHILE",
            "SAP_TERRAMAR_DB_SERVER_TYPE": "9",
            "SAP_TERRAMAR_USE_TRUSTED": "False",
            "SAP_TERRAMAR_USER": "qa_writer",
            "SAP_TERRAMAR_PASSWORD": "qa_writer_password",
            "SAP_HANA_SERVER_ADDRESS": "hana-read.example.local",
            "SAP_HANA_SERVER_PORT": "30015",
            "SAP_HANA_COMPANY_DB": "SBOTERRACHILE",
            "SAP_HANA_DB_USERNAME": "read_only_user",
            "SAP_HANA_DB_PASSWORD": "read_only_password",
        }

    def test_qa_escritura_terramar_permite_solo_base_qa(self):
        with patch.dict(os.environ, self._environment(), clear=False):
            write_config = sap_di_proforma.get_sap_di_config(1)

        self.assertEqual(write_config.environment, "QA")
        self.assertEqual(write_config.company_db, "TESTTERRACHILE")

    def test_qa_escritura_terramar_rechaza_base_productiva(self):
        environment = self._environment()
        environment["SAP_TERRAMAR_COMPANY_DB"] = "SBOTERRACHILE"
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(
                sap_di_proforma.SapDiApiError, "TESTTERRACHILE"
            ):
                sap_di_proforma.get_sap_di_config(1)

    def test_hana_productivo_permanece_independiente_en_qa(self):
        with patch.dict(os.environ, self._environment(), clear=False):
            read_config = sap_di_api._load_config()
            write_config = sap_di_proforma.get_sap_di_config(1)

        self.assertEqual(write_config.environment, "QA")
        self.assertEqual(write_config.company_db, "TESTTERRACHILE")
        self.assertEqual(read_config["CompanyDB"], "SBOTERRACHILE")

    def test_cambiar_sap_environment_no_reescribe_company_db_hana(self):
        environment = self._environment()
        with patch.dict(os.environ, environment, clear=False):
            hana_qa = sap_di_api._load_config()["CompanyDB"]

        environment["SAP_ENVIRONMENT"] = "PRODUCTION"
        environment["SAP_TERRAMAR_COMPANY_DB"] = "SBOTERRACHILE"
        with patch.dict(os.environ, environment, clear=False):
            hana_production = sap_di_api._load_config()["CompanyDB"]

        self.assertEqual(hana_qa, "SBOTERRACHILE")
        self.assertEqual(hana_production, "SBOTERRACHILE")
