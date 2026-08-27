from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home import views


class RecepcionSbhSnapshotModalesTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(
            EP_NID_id=2,
            CI_CTIPO='RECEPCION',
            PL_NID=None,
            PRO_NID=SimpleNamespace(SN_CRAZONSOCIAL='Proveedor citación'),
        )
        self.detalle = {
            'origen': 'planificacion',
            'inf_24hrs': 'Sí',
            'codigo': 'ITEM01',
            'insumo': 'Aceite',
            'pedido': '450001',
            'proveedor_sap': 'Proveedor SAP',
            'proveedor_codigo': 'P001',
            'cantidad_disponible': '12500',
            'docentry': '77',
            'sap_opor_id': '88',
            'guia': 'GUIA-1',
            'cda': 'CDA-1',
            'di': 'DI-1',
            'bl': 'BL-1',
            'nave_naviera': 'NAVE-1',
            'booking': 'BOOK-1',
            'contenedor': 'CONT-1',
            'fecha_produccion': '2026-08-01',
            'fecha_vencimiento': '2027-09-02T00:00:00',
            'sui': 'SUI-1',
            'almacen_destino': 'CISTERNA',
            'estanque_destino': 'CISTER20',
            'observacion': 'Revisar sello',
        }
        self.datos_operacion = {
            'PLAN_CONTRATO_SAP': SimpleNamespace(DO_CVALOR='CON-99'),
            'PLAN_CODIGO_PROVEEDOR_SAP': SimpleNamespace(DO_CVALOR='P-SNAPSHOT'),
        }

    @patch('apps.home.views.obtener_contrato_sap_visible_por_pedido')
    def test_resumen_usa_solo_snapshot_y_mantiene_campos_separados(self, consultar_contrato):
        items = views.datos_operacionales_resumen_planificacion(
            self.citacion,
            self.detalle,
            self.datos_operacion,
        )
        datos = {item['label']: item['value'] for item in items}

        consultar_contrato.assert_not_called()
        self.assertEqual(datos['Contrato SAP'], 'CON-99')
        self.assertEqual(datos['Código proveedor SAP'], 'P001')
        self.assertEqual(datos['BL'], 'BL-1')
        self.assertEqual(datos['Contenedor'], 'CONT-1')
        self.assertEqual(datos['Almacén destino'], 'CISTERNA')
        self.assertEqual(datos['Estanque destino'], 'CISTER20')
        self.assertEqual(datos['Fecha producción'], '01/08/2026')
        self.assertEqual(datos['Fecha vencimiento'], '02/09/2027')

    def test_campos_vacios_muestran_sin_informacion(self):
        citacion_sin_proveedor = SimpleNamespace(
            **{**self.citacion.__dict__, 'PRO_NID': None}
        )
        snapshot = views.datos_snapshot_recepcion_sbh_presentacion(
            citacion_sin_proveedor,
            {},
            {},
        )

        self.assertTrue(snapshot)
        self.assertTrue(all(valor == 'Sin información' for valor in snapshot.values()))
        self.assertIn('Guía', snapshot)
        self.assertIn('CDA', snapshot)
        self.assertIn('DI', snapshot)
        self.assertIn('SUI', snapshot)

    def test_snapshot_esta_aislado_de_otras_empresas_y_despacho(self):
        terramar = SimpleNamespace(**{**self.citacion.__dict__, 'EP_NID_id': 1})
        despacho = SimpleNamespace(**{**self.citacion.__dict__, 'CI_CTIPO': 'DESPACHO'})

        self.assertIsNone(views.datos_snapshot_recepcion_sbh_presentacion(terramar, self.detalle))
        self.assertIsNone(views.datos_snapshot_recepcion_sbh_presentacion(despacho, self.detalle))

    def test_plantillas_muestran_snapshot_solo_en_recepcion_sbh(self):
        planificacion = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        operacion = Path(
            'apps/templates/home/CITACION/operacion_planta.html'
        ).read_text(encoding='utf-8')

        self.assertIn(
            "response.es_recepcion_sbh ? renderRevisionSection('Datos SAP / operacionales', response.datos_operacionales) : ''",
            planificacion,
        )
        self.assertIn('{% if snapshot_recepcion_sbh %}', operacion)
        self.assertIn('{% for etiqueta, valor in snapshot_recepcion_sbh.items %}', operacion)
