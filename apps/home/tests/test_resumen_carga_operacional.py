from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path

from django.db import connection
from django.template.loader import render_to_string, get_template
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.home import views
from apps.home.despacho_carga import preparar_payloads
from apps.home.models import (
    CITACION_DESPACHO_CARGA, CITACION_DESPACHO_ACUERDO_OPERACIONAL,
    CITACION_DESPACHO_ACUERDO_ESTANQUE, CITACION_DESPACHO_ACUERDO_LOTE,
)
from apps.home.tests import test_despacho_carga_operacional as fixtures


class ResumenCargaOperacionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.CargaOperacionalTests.setUpTestData.__func__(cls)
        cls.citacion.SC_NID.SE_CCODIGO = 'EST_SBH_CLIENTE'
        cls.citacion.SC_NID.save(update_fields=['SE_CCODIGO'])

    def crear_acuerdo(self, abs_id=4092, numero='429', cantidad='27.5'):
        carga, _ = CITACION_DESPACHO_CARGA.objects.get_or_create(CI_NID=self.citacion,
            defaults={'US_NID': self.user, 'cantidad_total': Decimal(cantidad), 'zona_carga': 'Línea 1'})
        return CITACION_DESPACHO_ACUERDO_OPERACIONAL.objects.create(carga=carga,
            sap_abs_id=abs_id, numero_acuerdo=numero, cantidad=Decimal(cantidad),
            cliente_codigo='C001', cliente_nombre='Cliente', orden=carga.acuerdos.count() + 1)

    def crear_estanque(self, acuerdo, whs='TK04', lotes=(('Lote A', '27.5'),), item='980057'):
        estanque = CITACION_DESPACHO_ACUERDO_ESTANQUE.objects.create(acuerdo=acuerdo,
            warehouse_code=whs, item_code=item, item_name='BLEND MARINE Q3 V3 2026 EWOS',
            linea_acuerdo='1', unidad_medida='Toneladas', orden=acuerdo.estanques.count() + 1,
            cantidad=sum(Decimal(cantidad) for _, cantidad in lotes))
        for batch, cantidad in lotes:
            CITACION_DESPACHO_ACUERDO_LOTE.objects.create(estanque=estanque,
                batch_number=batch, cantidad=Decimal(cantidad), stock_snapshot=Decimal('340'))
        return estanque

    def resumen(self):
        return views._resumen_carga_operacional_despacho(self.citacion)

    def comprobar_totales(self, resumen):
        for acuerdo in resumen['acuerdos']:
            total = Decimal(0)
            for producto in acuerdo['productos']:
                for estanque in producto['estanques']:
                    self.assertEqual(estanque['cantidad'], sum(l['cantidad'] for l in estanque['lotes']))
                    total += estanque['cantidad']
            self.assertEqual(acuerdo['cantidad'], total)

    def test_un_acuerdo_estanque_lote_cantidad_final_no_planificacion_ni_stock(self):
        acuerdo = self.crear_acuerdo(cantidad='18.5')
        self.crear_estanque(acuerdo, lotes=(('Lote final', '18.5'),))
        resumen = self.resumen()
        self.assertEqual(resumen['acuerdos'][0]['cantidad'], Decimal('18.5'))
        self.assertEqual(self.detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR, 100)
        self.comprobar_totales(resumen)
        self.assertNotIn('stock_snapshot', str(resumen))
        self.assertNotIn('340', str(resumen))

    def test_varios_lotes_en_estanque(self):
        self.crear_estanque(self.crear_acuerdo(), lotes=(
            ('LOTE-PT-980057-6-01', '20'), ('LOTE-PT-980057-7-01', '7.5')))
        resumen = self.resumen()
        lotes = resumen['acuerdos'][0]['productos'][0]['estanques'][0]['lotes']
        self.assertEqual(len(lotes), 2)
        self.assertEqual([l['cantidad'] for l in lotes], [Decimal(20), Decimal('7.5')])
        self.comprobar_totales(resumen)

    def test_varios_estanques_mismo_producto_y_equivalencia_document_lines(self):
        acuerdo = self.crear_acuerdo()
        self.crear_estanque(acuerdo, lotes=(('A', '15'), ('B', '5')))
        self.crear_estanque(acuerdo, 'TKMX01', lotes=(('C', '7.5'),))
        resumen = self.resumen()
        producto = resumen['acuerdos'][0]['productos'][0]
        self.assertEqual([e['warehouse_code'] for e in producto['estanques']], ['TK04', 'TKMX01'])
        self.comprobar_totales(resumen)
        # Mismos campos normalizados que preparar_payloads lleva a DocumentLines/BatchNumbers.
        bloques = [{'item_code': producto['item_code'], **e} for e in producto['estanques']]
        payload = preparar_payloads(self.citacion, {'acuerdos': [
            {'sap_abs_id': acuerdo.sap_abs_id, 'cliente_codigo': acuerdo.cliente_codigo, 'estanques': bloques},
        ]})[acuerdo.sap_abs_id]
        self.assertEqual(len(payload['DocumentLines']), 2)
        for linea, estanque in zip(payload['DocumentLines'], producto['estanques']):
            self.assertEqual(linea['WarehouseCode'], estanque['warehouse_code'])
            self.assertEqual(Decimal(str(linea['Quantity'])), estanque['cantidad'])
            self.assertEqual([l['BatchNumber'] for l in linea['BatchNumbers']],
                [l['batch_number'] for l in estanque['lotes']])

    def test_varios_acuerdos_no_mezclan_productos_ni_lotes(self):
        for abs_id, numero, lote in ((4092, '433', 'Lote acuerdo 433'), (3584, '426', 'Lote acuerdo 426')):
            self.crear_estanque(self.crear_acuerdo(abs_id, numero), lotes=((lote, '27.5'),))
        resumen = self.resumen()
        self.assertEqual([a['numero_acuerdo'] for a in resumen['acuerdos']], ['433', '426'])
        for acuerdo in resumen['acuerdos']:
            self.assertEqual(acuerdo['productos'][0]['estanques'][0]['lotes'][0]['batch_number'],
                'Lote acuerdo ' + acuerdo['numero_acuerdo'])
        self.comprobar_totales(resumen)

    def test_varios_productos_separados_dentro_del_acuerdo(self):
        acuerdo = self.crear_acuerdo(cantidad='30')
        self.crear_estanque(acuerdo, lotes=(('A', '10'),))
        self.crear_estanque(acuerdo, lotes=(('B', '20'),), item='800040')
        resumen = self.resumen()
        self.assertEqual([p['item_code'] for p in resumen['acuerdos'][0]['productos']], ['980057', '800040'])
        self.comprobar_totales(resumen)

    def test_sin_carga_no_reconstruye_desde_planificacion(self):
        self.assertEqual(self.resumen(), {'guardado': False, 'acuerdos': []})
        html = render_to_string('home/CITACION/resumen_carga_operacional.html', {'resumen': self.resumen()})
        self.assertIn('No hay una distribución de carga operacional guardada', html)

    def test_fuera_del_ambito_no_consulta_datos(self):
        for empresa, tipo, codigo in ((1, 'DESPACHO', 'EST_SBH_CLIENTE'),
                (2, 'RECEPCION', 'EST_SBH_CLIENTE'), (2, 'DESPACHO', 'TRASVASIJE_CLIENTE')):
            citacion = SimpleNamespace(EP_NID_id=empresa, CI_CTIPO=tipo,
                SC_NID=SimpleNamespace(SE_CCODIGO=codigo))
            with self.assertNumQueries(0):
                self.assertIsNone(views._resumen_carga_operacional_despacho(citacion))

    def test_solo_lectura_consultas_acotadas_template_responsive_y_ubicacion(self):
        self.crear_estanque(self.crear_acuerdo())
        with CaptureQueriesContext(connection) as queries:
            resumen = self.resumen()
            html = render_to_string('home/CITACION/resumen_carga_operacional.html', {'resumen': resumen})
        self.assertEqual(len(queries), 4)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        for etiqueta in ('<input', '<button', '<select', '<form'):
            self.assertNotIn(etiqueta, html)
        self.assertIn('Acuerdo SAP 429', html)
        self.assertIn('BLEND MARINE Q3 V3 2026 EWOS', html)
        self.assertIn('Total TK04', html)
        self.assertIn('Lote A', html)
        self.assertIn('@media(max-width:600px)', html)
        principal = get_template('home/CITACION/operacion_planta.html')
        fuente = Path(principal.origin.name).read_text(encoding='utf-8')
        self.assertLess(fuente.index("include 'home/CITACION/resumen_carga_operacional.html'"),
            fuente.index('<div class="op-dispatch-cycle-grid"'))
