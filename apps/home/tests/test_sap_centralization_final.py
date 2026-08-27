import os
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import sap_di_api, sap_di_proforma
from apps.integrations.sap_b1.sap_config import (
    SapConfigError,
    get_sap_company_db,
    get_sap_proforma_series,
)
from apps.integrations.sap_b1.service_layer_probe import load_config


class SapFinalCentralizationTestCase(SimpleTestCase):
    def _write_environment(self, environment, terramar_db):
        return {
            "SAP_ENVIRONMENT": environment,
            "SAP_TERRAMAR_COMPANY_DB": terramar_db,
            "SAP_SBH_COMPANY_DB": "SBO_TST_SBH_USD",
            "SAP_SL_BASE_URL": "https://sap.example.local/b1s/v1",
            "SAP_SL_USERNAME": "sap_user",
            "SAP_SL_PASSWORD": "sap_password",
            "SAP_SL_VERIFY_SSL": "true",
            "SAP_SL_TIMEOUT": "30",
        }

    def test_qa_terramar_selecciona_company_db_desde_env(self):
        environment = self._write_environment("QA", "TESTTERRACHILE")
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(get_sap_company_db(1, for_write=True), "TESTTERRACHILE")

    def test_prod_terramar_cambia_solo_environment_y_company_db(self):
        environment = self._write_environment("PROD", "SBOTERRACHILE")
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(get_sap_company_db(1, for_write=True), "SBOTERRACHILE")

    def test_prod_sbh_cambia_solo_environment_y_company_db(self):
        environment = self._write_environment("PROD", "SBOTERRACHILE")
        environment["SAP_SBH_COMPANY_DB"] = "SBO_SBH_USD"
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(get_sap_company_db(2, for_write=True), "SBO_SBH_USD")

    def test_qa_rechaza_company_db_productiva_antes_de_cliente_sap(self):
        environment = self._write_environment("QA", "SBOTERRACHILE")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(SapConfigError):
                get_sap_company_db(1, for_write=True)

    def test_qa_rechaza_company_db_productiva_sbh(self):
        environment = self._write_environment("QA", "TESTTERRACHILE")
        environment["SAP_SBH_COMPANY_DB"] = "SBO_SBH_USD"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(SapConfigError):
                get_sap_company_db(2, for_write=True)

    def test_series_proforma_se_resuelven_por_empresa_desde_env(self):
        environment = {
            "SAP_TERRAMAR_PROFORMA_SERIES": "79",
            "SAP_SBH_PROFORMA_SERIES": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(get_sap_proforma_series(1), 79)
            self.assertEqual(get_sap_proforma_series(2), 1)

    def test_service_layer_operacional_usa_company_db_central_por_empresa(self):
        environment = self._write_environment("QA", "TESTTERRACHILE")
        with patch.dict(os.environ, environment, clear=True):
            terramar = load_config(1, for_write=True)
            sbh = load_config(2, for_write=True)

        self.assertEqual(terramar.company_db, "TESTTERRACHILE")
        self.assertEqual(sbh.company_db, "SBO_TST_SBH_USD")
        self.assertEqual(terramar.username, sbh.username)

    def test_hana_clientes_usa_esquema_configurado_sin_conectar(self):
        with patch.dict(
            os.environ,
            {"SAP_ENVIRONMENT": "QA", "SAP_HANA_CLIENTES_COMPANY_DB": "LECTURA_CLIENTES"},
            clear=True,
        ), patch.object(sap_di_api, "_rows", return_value=[]) as rows_mock:
            sap_di_api.consultar_clientes_sap()

        sql = rows_mock.call_args.args[0]
        self.assertIn('FROM "LECTURA_CLIENTES"."OCRD"', sql)

    def test_hana_acuerdos_usa_esquema_configurado_sin_conectar(self):
        with patch.dict(
            os.environ,
            {"SAP_ENVIRONMENT": "QA", "SAP_HANA_ACUERDOS_COMPANY_DB": "LECTURA_ACUERDOS"},
            clear=True,
        ), patch.object(sap_di_api, "_rows", return_value=[]) as rows_mock:
            sap_di_api.consultar_acuerdos_despacho_sap("AC")

        sql = rows_mock.call_args.args[0]
        self.assertIn('FROM "LECTURA_ACUERDOS"."OOAT"', sql)
        self.assertIn('JOIN "LECTURA_ACUERDOS"."OAT1"', sql)

    def test_di_api_acepta_prod_sin_cambiar_codigo(self):
        environment = {
            **self._write_environment("PROD", "SBOTERRACHILE"),
            "SAP_TERRAMAR_SERVER": "terramar.example.local:30013",
            "SAP_TERRAMAR_DB_SERVER_TYPE": "9",
            "SAP_TERRAMAR_USE_TRUSTED": "false",
            "SAP_TERRAMAR_USER": "sap_user",
            "SAP_TERRAMAR_PASSWORD": "sap_password",
        }
        with patch.dict(os.environ, environment, clear=True):
            result = sap_di_proforma.get_sap_di_config(1)

        self.assertEqual(result.environment, "PROD")
        self.assertEqual(result.company_db, "SBOTERRACHILE")
