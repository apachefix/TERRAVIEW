from pathlib import Path
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home.sap_di_api import consultar_acuerdos_despacho_sap
from apps.home.views import API_SAP_DESPACHO_ACUERDOS


class ConsultaAcuerdosDespachoSbhTests(SimpleTestCase):
    def fila_acuerdo(self, numero, oc_cliente):
        return {
            'sap_abs_id': 4000 + numero,
            'sap_acuerdo_numero': numero,
            'cliente_codigo': 'C001',
            'cliente_nombre': 'Cliente SAP',
            'oc_cliente': oc_cliente,
            'linea_acuerdo': 1,
            'codigo_insumo': '900129',
            'nombre_insumo': 'Producto SAP',
            'cantidad_planificada': 100,
            'cantidad_consumida': 10,
            'saldo_contrato_sap': 90,
        }

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

    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_busqueda_conserva_terminos_sql_filtros_orden_limite_y_saldo(self, _company_db, rows):
        for termino in ('nutr', '433', '4511573329'):
            with self.subTest(termino=termino):
                rows.reset_mock()
                rows.side_effect = [[], []]
                consultar_acuerdos_despacho_sap(termino, empresa_id=2)
                sql, params = rows.call_args.args
                self.assertEqual(params, [
                    f'%{termino}%',
                    f'%{termino}%',
                    f'%{termino.upper()}%',
                    f'%{termino.upper()}%',
                    f'%{termino}%',
                ])
                self.assertIn('TOP 50', sql)
                self.assertIn('CAST(A."Number" AS NVARCHAR) LIKE ?', sql)
                self.assertIn('A."NumAtCard" LIKE ?', sql)
                self.assertIn('UPPER(A."BpName") LIKE ?', sql)
                self.assertIn('A."BpType" = \'C\'', sql)
                self.assertIn('A."Status" = \'A\'', sql)
                self.assertIn('L."LineStatus" = \'O\'', sql)
                self.assertIn('COALESCE(L."PlanQty", 0) - COALESCE(L."CumQty", 0)', sql)
                self.assertIn('ORDER BY A."CreateDate" DESC, A."Number" DESC, L."AgrLineNum"', sql)

    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_metadata_oc_habilita_433_y_bloquea_423_408_y_espacios(self, _company_db, rows):
        filas = [
            self.fila_acuerdo(433, '4511573329'),
            self.fila_acuerdo(423, None),
            self.fila_acuerdo(408, ''),
            self.fila_acuerdo(407, '   '),
        ]
        rows.side_effect = [[], filas]

        resultado = consultar_acuerdos_despacho_sap('nutr', empresa_id=2)
        por_numero = {
            fila['sap_acuerdo_numero']: fila
            for fila in resultado['resultados']
        }

        self.assertEqual(por_numero[433]['oc_cliente'], '4511573329')
        self.assertTrue(por_numero[433]['has_oc'])
        self.assertTrue(por_numero[433]['selectable'])
        self.assertEqual(por_numero[433]['selection_block_reason'], '')
        for numero in (423, 408, 407):
            with self.subTest(numero=numero):
                self.assertIn(numero, por_numero)
                self.assertFalse(por_numero[numero]['has_oc'])
                self.assertFalse(por_numero[numero]['selectable'])
                self.assertEqual(
                    por_numero[numero]['selection_block_reason'],
                    'Este acuerdo no posee una OC asociada y no puede utilizarse para planificar.',
                )

    def test_select2_mantiene_sin_oc_visible_disabled_y_defensa_js(self):
        source = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')

        self.assertIn("item.oc_cliente || 'Sin OC'", source)
        self.assertIn(
            'disabled: ES_DESPACHO_SBH_ETAPA0 && item.selectable === false',
            source,
        )
        self.assertIn('templateResult: renderResultadoSapDespacho', source)
        seleccion = source.split(
            'function seleccionarAsignacionSap(asignacionId, item)', 1
        )[1].split('function textoCantidadStockSap', 1)[0]
        self.assertIn(
            'ES_DESPACHO_SBH_ETAPA0 && (item.selectable === false || !ocCliente)',
            seleccion,
        )
        self.assertIn('delete vistasPreviasSapDespacho[asignacionId]', seleccion)
        self.assertLess(
            seleccion.index(
                'ES_DESPACHO_SBH_ETAPA0 && (item.selectable === false || !ocCliente)'
            ),
            seleccion.index('vistasPreviasSapDespacho[asignacionId] = vistaPrevia'),
        )
