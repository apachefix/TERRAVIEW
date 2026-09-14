from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home.sap_di_api import consultar_acuerdos_despacho_sap
from apps.home.views import API_SAP_DESPACHO_ACUERDOS


class ConsultaAcuerdosDespachoSbhTests(SimpleTestCase):
    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_sbh_usa_udf_real_de_oat1(self, _company_db, rows):
        rows.side_effect = [[{'COLUMN_NAME': 'U_Incoterms'}], []]
        consultar_acuerdos_despacho_sap('371', empresa_id=2)
        sql, params = rows.call_args.args
        self.assertIn('FROM "SBO_TST_SBH_USD"."OOAT"', sql)
        self.assertIn('L."U_Incoterms" AS "incoterms"', sql)
        self.assertNotIn('L."U_U_Incoterms"', sql)
        self.assertEqual(params, ['%371%', '%371%', '%371%', '%371%', '%371%'])

    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_udf_opcional_ausente_devuelve_null_sin_error(self, _company_db, rows):
        rows.side_effect = [[], []]
        resultado = consultar_acuerdos_despacho_sap('371', empresa_id=2)
        sql = rows.call_args.args[0]
        self.assertTrue(resultado['ok'])
        self.assertIn('CAST(NULL AS NVARCHAR(50)) AS "incoterms"', sql)

    @patch('apps.home.sap_di_api._rows', return_value=[])
    @patch('apps.home.sap_di_api._configured_hana_schema', return_value='TERRAMAR_SCHEMA')
    def test_ep1_conserva_udf_legacy(self, _schema, rows):
        consultar_acuerdos_despacho_sap('371', empresa_id=1)
        sql = rows.call_args.args[0]
        self.assertIn('FROM "TERRAMAR_SCHEMA"."OOAT"', sql)
        self.assertIn('L."U_U_Incoterms" AS "incoterms"', sql)

    @patch('apps.home.views.consultar_acuerdos_despacho')
    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_endpoint_sbh_responde_http_200(self, _empresa, consultar):
        consultar.return_value = {'ok': True, 'resultados': []}
        request = RequestFactory().get('/api/sap/despacho/acuerdos/', {'q': '371'})
        response = API_SAP_DESPACHO_ACUERDOS(request)
        self.assertEqual(response.status_code, 200)
        consultar.assert_called_once_with('371', 2)