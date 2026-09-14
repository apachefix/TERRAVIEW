import json
from pathlib import Path
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home.sap_di_api import SapDiApiError, consultar_stock_fisico_despacho_sap
from apps.home.views import API_SAP_DESPACHO_STOCK


class StockFisicoDespachoSbhTests(SimpleTestCase):
    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_un_warehouse_muestra_total_unidad_y_parametro_posicional(self, _db, rows):
        rows.return_value = [{
            'item_code': '900129', 'whs_code': 'TK01',
            'whs_name': 'Estanque Almacenamiento TK 01',
            'on_hand': 29.5863, 'committed': 0, 'on_order': 0,
            'net_available': 29.5863, 'unit': 'Toneladas Metricas',
        }]

        resultado = consultar_stock_fisico_despacho_sap('900129', empresa_id=2)

        sql, params = rows.call_args.args
        self.assertIn('FROM "SBO_TST_SBH_USD"."OITW" W', sql)
        self.assertIn('INNER JOIN "SBO_TST_SBH_USD"."OWHS" H', sql)
        self.assertIn('INNER JOIN "SBO_TST_SBH_USD"."OITM" I', sql)
        self.assertIn('WHERE W."ItemCode" = ?', sql)
        self.assertEqual(params, ['900129'])
        self.assertEqual(resultado['stock_total'], 29.5863)
        self.assertEqual(resultado['unit'], 'Toneladas Metricas')
        self.assertEqual(resultado['warehouses'][0]['whs_code'], 'TK01')

    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_varios_warehouses_suman_on_hand_sin_mezclar_productos(self, _db, rows):
        rows.return_value = [
            {'whs_code': 'TK01', 'on_hand': 20, 'unit': 'Toneladas Metricas'},
            {'whs_code': 'TK03', 'on_hand': 12.8, 'unit': 'Toneladas Metricas'},
            {'whs_code': 'TKMX01', 'on_hand': 10, 'unit': 'Toneladas Metricas'},
        ]
        resultado = consultar_stock_fisico_despacho_sap('900129', empresa_id=2)
        self.assertEqual(resultado['stock_total'], 42.8)
        self.assertEqual(len(resultado['warehouses']), 3)

    @patch('apps.home.sap_di_api._rows', return_value=[])
    @patch('apps.home.sap_di_api.get_sap_company_db', return_value='SBO_TST_SBH_USD')
    def test_sin_stock_devuelve_total_cero_y_lista_vacia(self, _db, _rows):
        resultado = consultar_stock_fisico_despacho_sap('900129', empresa_id=2)
        self.assertEqual(resultado['stock_total'], 0)
        self.assertEqual(resultado['warehouses'], [])

    def test_ep1_esta_aislado(self):
        with self.assertRaisesRegex(SapDiApiError, 'sólo está disponible para SBH'):
            consultar_stock_fisico_despacho_sap('900129', empresa_id=1)

    @patch('apps.home.views.consultar_stock_fisico_despacho_sap', side_effect=SapDiApiError('sin conexión'))
    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_error_sap_es_informativo_y_no_bloqueante(self, _empresa, _consultar):
        request = RequestFactory().get('/api/sap/despacho-stock/', {'item_code': '900129'})
        response = API_SAP_DESPACHO_STOCK(request)
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['available'])
        self.assertIn('no disponible temporalmente', data['message'])

    def test_frontend_renderiza_por_tarjeta_cachea_itemcode_y_no_valida_cantidad_con_stock(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        self.assertIn('Saldo disponible del contrato', template)
        self.assertIn('Existencia f&iacute;sica en planta', template)
        self.assertIn('Estanque(s) con stock', template)
        self.assertIn("url: '/api/sap/despacho-stock/'", template)
        self.assertIn('stockFisicoSapCache[itemCode]', template)
        self.assertIn('stockFisicoSapPorAsignacion[asignacionId]', template)
        self.assertIn('Sin existencia física disponible en SAP.', template)
        self.assertNotIn('cantidad > datos.stock_total', template)
        self.assertNotIn('cantidad > stock_total', template)

