"""Etapa 0 RECEPCION: saldo de la línea Purchase Order en SAP."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import CITACION, DATO_OPERACION, PLANIFICACION
from apps.home.sap_di_api import consultar_saldo_linea_pedido_sap, consultar_pedidos_por_producto_sap, consultar_detalle_pedido_sap, consultar_pedido_sap


class PlanificacionRecepcionSaldoSapTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        RecepcionProsesaTestCase.setUpTestData.__func__(cls)

    def item(self, **extra):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        item = RecepcionProsesaTestCase._item_creacion_piso_1(self)
        item['line_num'] = '2'
        item.update(extra)
        return item

    def crear(self, item, saldo):
        request = RequestFactory().post('/crear-planificacion-citacion/', {
            'flujo': 'INGRESO_MERCADERIA',
            'citaciones_json': json.dumps([item]),
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ), patch('apps.home.views.consultar_saldo_linea_pedido_sap', return_value={
            'DocStatus': 'O', 'DocEntry': 6726, 'DocNum': 4500001, 'LineNum': 2,
            'ItemCode': 'ITEM-1', 'OpenQty': Decimal(saldo),
        }) as consultar:
            response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)
        consultar.assert_called_once_with('6726', 'ITEM-1', '2')
        return response

    def test_85_6_permite_planificar(self):
        response = self.crear(self.item(), '85.6')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['success'])
        self.assertEqual(CITACION.objects.filter(PL_NID__PL_CTIPOCUPO='RECEPCION').count(), 4)

    def test_residual_0_005_es_positivo_y_permite_planificar(self):
        response = self.crear(self.item(cantidad_disponible='0'), '0.005')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['success'])
        citacion_id = json.loads(response.content)['citaciones'][0]
        self.assertEqual(
            CITACION.objects.get(pk=citacion_id).detalle_operacional.CDO_NCANTIDAD_DISPONIBLE,
            Decimal('0.005'),
        )

    def test_cero_bloquea_sin_crear_planificacion_ni_citacion(self):
        antes = (PLANIFICACION.objects.count(), CITACION.objects.count())
        response = self.crear(self.item(cantidad_disponible='85.6'), '0')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['message'],
            'No se puede planificar: la línea SAP seleccionada no tiene cantidad disponible.')
        self.assertEqual((PLANIFICACION.objects.count(), CITACION.objects.count()), antes)

    def test_negativo_bloquea_sin_crear_registros(self):
        antes = (PLANIFICACION.objects.count(), CITACION.objects.count())
        response = self.crear(self.item(), '-0.001')
        self.assertEqual(response.status_code, 400)
        self.assertEqual((PLANIFICACION.objects.count(), CITACION.objects.count()), antes)

    def test_consulta_exacta_usa_por1_openqty_incluso_saldo_cero(self):
        with patch('apps.home.sap_di_api._rows', return_value=[{
            'DocEntry': 6726, 'DocStatus': 'O', 'LineNum': 2,
            'ItemCode': 'ITEM-1', 'OpenQty': Decimal('0'),
        }]) as rows:
            linea = consultar_saldo_linea_pedido_sap('6726', 'ITEM-1', '2')
        self.assertEqual(linea['OpenQty'], Decimal('0'))
        sql, params = rows.call_args.args
        self.assertIn('POR1', sql)
        self.assertIn('"OpenQty"', sql)
        self.assertIn('"LineNum" = ?', sql)
        self.assertNotIn('"OpenQty" > 0', sql)
        self.assertEqual(params, [6726, 'ITEM-1', 2])
        self.assertNotIn('DPO1', sql)
        self.assertNotIn('TargetType', sql)
        self.assertNotIn('TrgetEntry', sql)

    def datos_sap_citacion(self, response):
        citacion = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        return citacion, dict(DATO_OPERACION.objects.filter(CI_NID=citacion).values_list(
            'CAMP_NID__CA_CCODIGO', 'DO_CVALOR',
        ))

    def test_consultas_canonicas_conservan_pedido_proveedor_linea_y_openqty(self):
        row = {
            'DocEntry': 6726, 'DocNum': 4500001, 'DocStatus': 'O',
            'CardCode': 'V-1', 'CardName': 'Proveedor', 'LineNum': 2,
            'ItemCode': 'ITEM-1', 'Dscription': 'Aceite',
            'OpenQty': Decimal('28'),
        }
        with patch('apps.home.sap_di_api._rows', return_value=[row]) as rows:
            producto = consultar_pedidos_por_producto_sap('ITEM-1')
            sql_producto = rows.call_args.args[0]
            detalle = consultar_detalle_pedido_sap('4500001')
            sql_detalle = rows.call_args.args[0]
        with patch('apps.home.sap_di_api._first_row', return_value=row) as first_row:
            pedido = consultar_pedido_sap('4500001', 'ITEM-1')
            sql_pedido = first_row.call_args.args[0]

        for sql in (sql_producto, sql_detalle, sql_pedido):
            self.assertIn('OPOR', sql)
            self.assertIn('POR1', sql)
            self.assertNotIn('DPO1', sql)
            self.assertNotIn('TargetType', sql)
            self.assertNotIn('TrgetEntry', sql)
        for linea in (producto['pedidos'][0], detalle['lineas'][0], pedido):
            self.assertEqual(linea['docentry'], 6726)
            self.assertEqual(linea['line_num'], 2)
            self.assertEqual(linea['cardcode'], 'V-1')
            self.assertEqual(linea['openqty'], Decimal('28'))
            self.assertNotIn('target_type', linea)
            self.assertNotIn('target_entry', linea)

    def test_nacional_e_importacion_permiten_sin_validacion_dpo1(self):
        for tipo in ('NACIONAL', 'IMPORTACION'):
            with self.subTest(tipo=tipo):
                response = self.crear(self.item(tipo_origen_recepcion=tipo), '28')
                self.assertEqual(response.status_code, 200, response.content)
                citacion, datos = self.datos_sap_citacion(response)
                self.assertEqual(citacion.detalle_operacional.CDO_CTIPO_RECEPCION, tipo)
                self.assertEqual(citacion.detalle_operacional.CDO_CSAP_OPOR_ID, '6726')
                self.assertEqual(citacion.detalle_operacional.CDO_CPEDIDO_SAP, '4500001')
                self.assertNotIn('PLAN_SAP_PO_BASE_LINE', datos)
                self.assertNotIn('PLAN_SAP_TARGET_TYPE', datos)
                self.assertNotIn('PLAN_SAP_TARGET_ENTRY', datos)

    def test_campos_target_del_navegador_se_ignoran_y_no_generan_snapshots(self):
        response = self.crear(self.item(
            tipo_origen_recepcion='IMPORTACION',
            target_type='18', target_entry='99999', related_document_ambiguous=True,
        ), '28')
        self.assertEqual(response.status_code, 200, response.content)
        _, datos = self.datos_sap_citacion(response)
        self.assertFalse(any(codigo.startswith('PLAN_SAP_TARGET_') for codigo in datos))

    def test_modal_conserva_selector_linea_y_saldo_sin_ui_factura(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        self.assertIn('id="pedido"', template)
        self.assertIn('id="line_num"', template)
        self.assertIn("line_num: getValue('line_num')", template)
        self.assertIn('id="cantidad_disponible"', template)
        self.assertNotIn('id="documento_relacionado_sap"', template)
        self.assertNotIn('sap_target_type', template)
        self.assertNotIn('sap_target_entry', template)
        self.assertNotIn('sap_related_ambiguous', template)
        self.assertNotIn('facturaRelacionadaSapSeleccionada', template)

    def test_pedido_sin_docentry_no_puede_omitir_revalidacion(self):
        item = self.item(sap_opor_id='', docentry='', cantidad_disponible='85.6')
        request = RequestFactory().post('/crear-planificacion-citacion/', {
            'flujo': 'INGRESO_MERCADERIA',
            'citaciones_json': json.dumps([item]),
        })
        request.user = self.usuario
        antes = (PLANIFICACION.objects.count(), CITACION.objects.count())
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ), patch('apps.home.views.consultar_saldo_linea_pedido_sap') as consultar:
            response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((PLANIFICACION.objects.count(), CITACION.objects.count()), antes)
        consultar.assert_not_called()

