from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase

from apps.home import sap_di_api, views
from apps.home.models import CITACION, CITACION_DETALLE_OPERACIONAL, CITACION_TRANSFERENCIA_DETALLE, EMPRESA


class RecepcionTransferenciaSbhTests(SimpleTestCase):
    productos_sap = [
        {
            'codigo_sap': '950066',
            'insumo': 'ACEITE DE ALGA PRIME VITAPRO',
            'codigo_propietario': 'C96677260',
            'propiedad_producto': 'VITAPRO CHILE SA',
            'stock_disponible': 487.26,
            'unidad': 'Toneladas Metricas',
        },
        {
            'codigo_sap': '800042',
            'insumo': 'ALGA PRIME DHA',
            'codigo_propietario': None,
            'propiedad_producto': None,
            'stock_disponible': 257.73,
            'unidad': 'Toneladas Metricas',
        },
    ]

    def test_identificacion_es_persistente_por_secuencia(self):
        citacion = SimpleNamespace(EP_NID_id=2, CI_CTIPO='RECEPCION', PL_NID=None, SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_TRANSFERENCIA_SBH'))
        self.assertTrue(views.es_flujo_recepcion_transferencia_sbh(citacion))
        citacion.SC_NID.SE_CCODIGO = 'RECEPCION_ESTANQUE_SBH'
        self.assertFalse(views.es_flujo_recepcion_transferencia_sbh(citacion))

    def test_modal_y_campos_exclusivos_existen(self):
        template = Path('apps/templates/home/PLANIFICACION/_etapa0_transferencia_form.html').read_text(encoding='utf-8')
        script = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_scripts.html').read_text(encoding='utf-8')
        self.assertIn('ModalCrearRecepcionTransferencia', template)
        self.assertIn('transferencia_movimientos', template)
        self.assertIn('agregarMovimientoTransferencia', script)
        self.assertIn('transferencia-codigo-sap', script)
        self.assertIn('transferencia-cantidad', script)
        self.assertIn('eliminarMovimientoTransferencia', script)
        self.assertIn('transferencia_total', template)
        self.assertIn('Cantidad de camiones', template)
        self.assertIn('transferencia_almacen_destino', template)
        self.assertIn('transferencia_estanque_destino', template)
        bloque_transferencia = template.split(
            '<form id="form_recepcion_transferencia">', 1
        )[1].split('</form>', 1)[0]
        self.assertNotIn('Flujo operacional', bloque_transferencia)
        self.assertNotIn('Seleccione secuencia', bloque_transferencia)
        self.assertNotIn('transferencia_secuencia_id', template)

    def test_backend_asigna_secuencia_transferencia_sin_valor_del_navegador(self):
        source = Path(views.__file__).read_text(encoding='utf-8')
        self.assertIn("if flujo_recepcion_sbh == 'TRANSFERENCIA':", source)
        self.assertIn('SE_CCODIGO=SECUENCIA_RECEPCION_TRANSFERENCIA_SBH', source)
        self.assertIn("item['secuencia_id'] = secuencia_transferencia.pk", source)
        self.assertIn('if secuencia_transferencia:', source)
        self.assertIn("secuencia_enviada != str(secuencia_transferencia.pk)", source)

    def test_transferencia_expande_un_borrador_por_camion_y_usa_tabla_exclusiva(self):
        script = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_scripts.html').read_text(encoding='utf-8')
        template = Path('apps/templates/home/PLANIFICACION/_etapa0_resumen_cabecera.html').read_text(encoding='utf-8')
        self.assertIn('for (let numeroCamion = 1; numeroCamion <= cantidadCamiones; numeroCamion += 1)', script)
        self.assertIn('cantidad_camion: 1', script)
        self.assertIn('movimientos: recopilado.movimientos', script)
        self.assertIn('function renderizarFilaRecepcionTransferencia(item, index)', script)
        self.assertIn('<th>N° camión</th>', template)
        self.assertIn('<th>Movimientos</th>', template)
        self.assertIn('<th>Total a mover</th>', template)
        self.assertIn('<th>Almacén destino</th>', template)
        self.assertIn('ES_RECEPCION_TRANSFERENCIA_SBH ? 7', script)

    @patch('apps.home.views.obtener_snapshot_recepcion_transferencia_sap')
    def test_dos_estanques_generan_dos_movimientos_validados(self, snapshot_mock):
        snapshot_mock.side_effect = [self.productos_sap[0], self.productos_sap[1]]

        movimientos = views.validar_movimientos_recepcion_transferencia_sbh([
            {'estanque_origen': 'PROSE_T5', 'codigo_sap': '950066', 'cantidad_a_mover': '10'},
            {'estanque_origen': 'PROSEG10', 'codigo_sap': '800042', 'cantidad_a_mover': '8'},
        ])

        self.assertEqual(len(movimientos), 2)
        self.assertEqual(snapshot_mock.call_count, 2)
        self.assertEqual(movimientos[0]['cantidad_a_mover'], 10)

    @patch('apps.home.views.obtener_snapshot_recepcion_transferencia_sap')
    def test_mismo_estanque_con_productos_distintos_es_valido(self, snapshot_mock):
        snapshot_mock.side_effect = [self.productos_sap[0], self.productos_sap[1]]

        movimientos = views.validar_movimientos_recepcion_transferencia_sbh([
            {'estanque_origen': 'PROSEG10', 'codigo_sap': '950066', 'cantidad_a_mover': '8'},
            {'estanque_origen': 'PROSEG10', 'codigo_sap': '800042', 'cantidad_a_mover': '4'},
        ])

        self.assertEqual(len(movimientos), 2)

    def test_rechaza_duplicado_exacto_antes_de_persistir(self):
        with patch('apps.home.views.obtener_snapshot_recepcion_transferencia_sap', return_value=self.productos_sap[0]):
            with self.assertRaisesRegex(ValueError, 'ya fue agregado'):
                views.validar_movimientos_recepcion_transferencia_sbh([
                    {'estanque_origen': 'PROSEG10', 'codigo_sap': '950066', 'cantidad_a_mover': '8'},
                    {'estanque_origen': 'PROSEG10', 'codigo_sap': '950066', 'cantidad_a_mover': '4'},
                ])

    @patch('apps.home.views.obtener_snapshot_recepcion_transferencia_sap')
    def test_rechaza_cantidad_superior_al_stock(self, snapshot_mock):
        snapshot_mock.return_value = self.productos_sap[0]
        with self.assertRaisesRegex(ValueError, 'supera el stock'):
            views.validar_movimientos_recepcion_transferencia_sbh([
                {'estanque_origen': 'PROSEG10', 'codigo_sap': '950066', 'cantidad_a_mover': '500'},
            ])

    def test_modelo_detalle_tiene_relacion_y_restricciones(self):
        self.assertEqual(
            CITACION_TRANSFERENCIA_DETALLE._meta.get_field('CI_NID').remote_field.related_name,
            'detalles_transferencia',
        )
        nombres = {constraint.name for constraint in CITACION_TRANSFERENCIA_DETALLE._meta.constraints}
        self.assertIn('CIT_TRANSF_UNQ_ESTANQUE_ITEM', nombres)
        self.assertIn('CIT_TRANSF_UNQ_ORDEN', nombres)

    @patch('apps.home.views.CITACION_TRANSFERENCIA_DETALLE.objects.bulk_create')
    @patch('apps.home.views.CITACION_TRANSFERENCIA_DETALLE.objects.filter')
    def test_persistencia_crea_un_detalle_por_movimiento(self, filter_mock, bulk_create):
        filter_mock.return_value.delete.return_value = (0, {})
        citacion = CITACION(EP_NID=EMPRESA(), US_NID=get_user_model()())
        movimientos = [
            {
                'estanque_origen': 'PROSE_T5', 'codigo_sap': '980047',
                'insumo': 'BLEND VEGETAL', 'stock_disponible_snapshot': 163.41,
                'unidad_inventario_snapshot': 'Toneladas Metricas',
                'cantidad_a_mover': 10, 'orden': 1,
            },
            {
                'estanque_origen': 'PROSEG10', 'codigo_sap': '950066',
                'insumo': 'ACEITE DE ALGA', 'stock_disponible_snapshot': 487.26,
                'unidad_inventario_snapshot': 'Toneladas Metricas',
                'cantidad_a_mover': 8, 'orden': 2,
            },
        ]

        views.guardar_detalles_transferencia_citacion(citacion, movimientos)

        detalles = bulk_create.call_args.args[0]
        self.assertEqual(len(detalles), 2)
        self.assertEqual(detalles[0].CTD_CESTANQUE_ORIGEN, 'PROSE_T5')
        self.assertEqual(detalles[1].CTD_NCANTIDAD_A_MOVER, 8)

    def test_validacion_sucede_antes_de_crear_planificacion(self):
        source = Path(views.__file__).read_text(encoding='utf-8')
        self.assertLess(
            source.index('movimientos_validados = validar_movimientos_recepcion_transferencia_sbh'),
            source.index('planificacion = PLANIFICACION()'),
        )
        self.assertIn('@transaction.atomic\ndef CREAR_PLANIFICACION_CITACION', source)

    def test_cantidad_camiones_exige_entero_positivo(self):
        for valor in ('', '0', '-1', '1.5', 'texto'):
            cantidad, mensaje = views.validar_cantidad_camiones_transferencia(valor)
            self.assertIsNone(cantidad)
            self.assertTrue(mensaje)
        for valor in ('1', '3', '5'):
            self.assertEqual(
                views.validar_cantidad_camiones_transferencia(valor),
                (int(valor), ''),
            )

    def test_destino_debe_pertenecer_al_almacen_sbh(self):
        valido, mensaje = views.validar_destino_recepcion_sbh('SBH', 'TK01')
        self.assertTrue(valido)
        self.assertEqual(mensaje, '')

        valido, mensaje = views.validar_destino_recepcion_sbh('SBH', 'PROSE_T5')
        self.assertFalse(valido)
        self.assertIn('no pertenece', mensaje)

    @patch('apps.home.views.consultar_productos_recepcion_transferencia_sap')
    def test_snapshot_reconsulta_sap_y_rechaza_codigo_manipulado(self, consulta_mock):
        consulta_mock.return_value = {
            'estanque': 'PROSEG10',
            'productos': self.productos_sap,
        }

        snapshot = views.obtener_snapshot_recepcion_transferencia_sap('PROSEG10', '950066')

        self.assertEqual(snapshot['propiedad_producto'], 'VITAPRO CHILE SA')
        self.assertEqual(snapshot['stock_disponible'], 487.26)
        with self.assertRaisesRegex(ValueError, 'no está disponible'):
            views.obtener_snapshot_recepcion_transferencia_sap('PROSEG10', 'ITEM-FALSO')

    @patch('apps.home.views.consultar_productos_recepcion_transferencia_sap')
    def test_endpoint_acepta_estanque_permitido_y_conserva_propiedad_null(self, consulta_mock):
        consulta_mock.return_value = {
            'estanque': 'PROSEG10',
            'productos': self.productos_sap,
        }
        request = RequestFactory().get(
            '/api/sap/recepcion-transferencia/estanque/', {'estanque': 'PROSEG10'}
        )

        response = views.API_SAP_RECEPCION_TRANSFERENCIA_ESTANQUE(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {
            'success': True,
            'estanque': 'PROSEG10',
            'productos': self.productos_sap,
        })

    def test_endpoint_rechaza_estanque_fuera_de_la_lista_permitida(self):
        request = RequestFactory().get(
            '/api/sap/recepcion-transferencia/estanque/', {'estanque': 'BODEGA_AJENA'}
        )

        response = views.API_SAP_RECEPCION_TRANSFERENCIA_ESTANQUE(request)

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {
            'success': False,
            'message': 'Estanque origen inválido.',
        })

    @patch('apps.home.sap_di_api._rows')
    @patch('apps.home.sap_di_api._load_config')
    def test_query_hana_usa_whscode_parametrizado(self, config_mock, rows_mock):
        config_mock.return_value = {'CompanyDB': 'SBO_TST_SBH_USD'}
        rows_mock.return_value = [{
            'CodigoSAP': '980047', 'Insumo': 'BLEND VEGETAL',
            'CodigoPropietario': 'C77424780',
            'PropiedadProducto': 'EWOS CHILE ALIMENTOS LTDA',
            'StockDisponible': 163.41, 'UnidadInventario': 'Toneladas Metricas',
        }]

        respuesta = sap_di_api.consultar_productos_recepcion_transferencia_sap('PROSE_T5')

        sql, params = rows_mock.call_args.args
        self.assertIn('INNER JOIN "SBO_TST_SBH_USD"."OITW" T1', sql)
        self.assertIn('T1."WhsCode" = ?', sql)
        self.assertEqual(params, ['PROSE_T5'])
        self.assertEqual(respuesta['productos'][0]['codigo_sap'], '980047')
