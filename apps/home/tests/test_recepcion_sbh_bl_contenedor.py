import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import sap_di_api, views
from apps.home.models import CITACION_DETALLE_OPERACIONAL


class RecepcionSbhBlContenedorTests(SimpleTestCase):
    def setUp(self):
        self.sap_row = {
            'DocEntry': 123,
            'DocNum': 456,
            'CardCode': 'P001',
            'CardName': 'Proveedor',
            'ContratoSap': 789,
            'LineNum': 0,
            'ItemCode': 'ITEM01',
            'Dscription': 'Insumo',
            'OpenQty': 12,
            'Contenedor': 'CONT123',
            'BL': 'BL9988',
            'Guia': 'GUIA1',
            'FechaProduccion': '2026-08-01',
            'FechaVencimiento': '2027-08-01',
            'CDA': 'CDA1',
            'DI': 'DI1',
            'SUI': 'SUI1',
            'NaveNaviera': 'NAVIERA1',
            'Booking': 'BOOK1',
        }

    @patch('apps.home.sap_di_api._first_row')
    def test_consultar_pedido_separa_bl_y_contenedor(self, first_row):
        first_row.return_value = self.sap_row

        resultado = sap_di_api.consultar_pedido_sap('456', 'ITEM01', 'P001')

        self.assertTrue(resultado['ok'])
        self.assertEqual(resultado['contenedor'], 'CONT123')
        self.assertEqual(resultado['bl'], 'BL9988')
        self.assertEqual(resultado['bl_contenedor'], 'CONT123')
        sql, params = first_row.call_args.args
        self.assertIn('T1."U_NXContenedor" AS "Contenedor"', sql)
        self.assertIn('T1."U_BL" AS "BL"', sql)
        self.assertIn('AND T0."CardCode" = ?', sql)
        self.assertEqual(params, [456, 'ITEM01', 'P001'])

    def test_mapeo_linea_mantiene_campos_independientes_incluso_si_bl_es_nulo(self):
        row = {**self.sap_row, 'BL': None}

        resultado = sap_di_api._pedido_row_to_dict(row)

        self.assertEqual(resultado['contenedor'], 'CONT123')
        self.assertEqual(resultado['bl'], '')
        self.assertEqual(resultado['bl_contenedor'], 'CONT123')

    @patch('apps.home.views.CITACION_DETALLE_OPERACIONAL.objects.update_or_create')
    def test_snapshot_sbh_persiste_bl_manual_y_permite_bl_vacio(self, update_or_create):
        update_or_create.return_value = (SimpleNamespace(), True)
        citacion = SimpleNamespace(
            EP_NID_id=2,
            EP_NID=SimpleNamespace(),
            CI_CTIPO='RECEPCION',
            US_NID=SimpleNamespace(),
        )

        views.guardar_detalle_operacional_citacion(
            citacion,
            {'contenedor': 'CONT123', 'bl': 'MANUAL123'},
        )

        defaults = update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDO_CBL_CONTENEDOR'], 'CONT123')
        self.assertEqual(defaults['CDO_CBL'], 'MANUAL123')

        views.guardar_detalle_operacional_citacion(
            citacion,
            {'contenedor': 'CONT123', 'bl': ''},
        )
        defaults = update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDO_CBL'], '')

    @patch('apps.home.views.consultar_pedido_sap')
    def test_endpoint_buscar_opor_no_mezcla_bl_contenedor(self, consultar):
        consultar.return_value = {
            'ok': True,
            'docentry': 123,
            'docnum': 456,
            'itemcode': 'ITEM01',
            'descripcion': 'Insumo',
            'cantidad_disponible': 12,
            'cardcode': 'P001',
            'cardname': 'Proveedor',
            'contenedor': 'CONT123',
            'bl': 'BL9988',
        }
        request = RequestFactory().get(
            '/buscar-opor-pedido/',
            {'pedido': '456', 'codigo': 'ITEM01', 'proveedor': 'P001'},
        )

        response = views.BUSCAR_OPOR_POR_PEDIDO(request)
        data = json.loads(response.content)

        self.assertEqual(data['data'][0]['contenedor'], 'CONT123')
        self.assertEqual(data['data'][0]['bl'], 'BL9988')
        self.assertEqual(data['data'][0]['bl_contenedor'], 'CONT123')

    def test_modal_sbh_bl_es_readonly_solo_cuando_sap_trae_valor(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')

        for field_id in (
            'guia', 'cda', 'di', 'nave_naviera', 'booking',
            'contenedor', 'fecha_produccion', 'fecha_vencimiento', 'sui',
        ):
            self.assertIn(f'id="{field_id}" name="{field_id}" readonly', template)
        self.assertIn("setValue('contenedor', item.contenedor || '');", template)
        self.assertIn('id="bl" name="bl">', template)
        self.assertIn('actualizarBlRecepcionSbh(item.bl);', template)
        self.assertIn('if (!ES_RECEPCION_SBH) return;', template)
        self.assertIn("$('#bl').val(bl).prop('readonly', bl.length > 0);", template)
        self.assertGreaterEqual(template.count("actualizarBlRecepcionSbh('');"), 2)
        self.assertEqual(
            CITACION_DETALLE_OPERACIONAL._meta.get_field('CDO_CBL_CONTENEDOR').column,
            'CDO_CBL_CONTENEDOR',
        )
        self.assertEqual(
            CITACION_DETALLE_OPERACIONAL._meta.get_field('CDO_CBL').column,
            'CDO_CBL',
        )
