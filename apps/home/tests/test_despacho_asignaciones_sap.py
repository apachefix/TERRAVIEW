from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.home.models import (
    CITACION_DESPACHO_ASIGNACION_SAP,
    CITACION_DESPACHO_DETALLE,
)
from apps.home.sap_despacho import (
    detalle_despacho_resumen_dict,
    guardar_detalle_despacho_citacion,
    validar_asignaciones_sap_planificadas,
)


class AsignacionesSapPlanificacionTests(SimpleTestCase):
    def asignacion(self, abs_id, linea, cantidad, cliente='C001', producto='ITEM-1'):
        return {
            'sap_abs_id': abs_id,
            'contrato_sap': f'AC-{abs_id}',
            'linea_acuerdo_sap': linea,
            'codigo_producto_sap': producto,
            'nombre_producto_sap': f'Producto {producto}',
            'cliente_codigo': cliente,
            'cliente_nombre': 'Cliente Uno',
            'oc_cliente': 'OC-100',
            'cantidad_planificada_sap': '10000',
            'cantidad_consumida_sap': '2000',
            'saldo_contrato_sap': '8000',
            'unidad_medida': 'KG',
            'cantidad_intentada_despachar': cantidad,
            'orden': 99,
            'estado': 'PLANIFICADA',
        }

    def data(self, total, asignaciones):
        return {
            'cliente': 'C001',
            'cliente_codigo': 'C001',
            'cantidad_intentada_despachar': total,
            'asignaciones_sap': asignaciones,
        }

    def test_crear_despacho_con_una_asignacion_normaliza_y_espeja_legacy(self):
        data = self.data('5000', [self.asignacion('407', '1', '5000')])

        resultado = validar_asignaciones_sap_planificadas(data)

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['cantidad_intentada_despachar'], Decimal('5000'))
        self.assertEqual(data['sap_abs_id'], '407')
        self.assertEqual(data['contrato_sap'], 'AC-407')
        self.assertEqual(data['linea_acuerdo_sap'], '1')
        self.assertEqual(data['codigo'], 'ITEM-1')
        self.assertEqual(data['cantidad_intentada_despachar'], Decimal('5000'))

    def test_crear_despacho_con_dos_asignaciones_y_productos_distintos(self):
        data = self.data('5000', [
            self.asignacion('407', '1', '3000', producto='ITEM-1'),
            self.asignacion('412', '3', '2000', producto='ITEM-2'),
        ])

        resultado = validar_asignaciones_sap_planificadas(data)

        self.assertEqual(len(resultado), 2)
        self.assertEqual([item['orden'] for item in resultado], [1, 2])
        self.assertEqual(resultado[1]['codigo_producto_sap'], 'ITEM-2')
        self.assertEqual(data['sap_abs_id'], '407')

    def test_no_exige_que_cantidad_por_contrato_coincida_con_total_global(self):
        data = self.data('999999', [self.asignacion('407', '1', '4999')])

        resultado = validar_asignaciones_sap_planificadas(data)

        self.assertEqual(resultado[0]['cantidad_intentada_despachar'], Decimal('4999'))
        self.assertEqual(data['cantidad_intentada_despachar'], Decimal('4999'))

    def test_no_requiere_cantidad_global(self):
        data = self.data('', [self.asignacion('407', '1', '5001')])

        resultado = validar_asignaciones_sap_planificadas(data)

        self.assertEqual(resultado[0]['cantidad_intentada_despachar'], Decimal('5001'))

    def test_rechaza_cantidad_cero_o_negativa(self):
        for cantidad in ('0', '-1'):
            with self.subTest(cantidad=cantidad), self.assertRaisesRegex(ValueError, 'mayor que cero'):
                validar_asignaciones_sap_planificadas(
                    self.data('5000', [self.asignacion('407', '1', cantidad)])
                )

    def test_rechaza_contrato_de_cliente_distinto(self):
        data = self.data('5000', [
            self.asignacion('407', '1', '3000'),
            self.asignacion('412', '3', '2000', cliente='C999'),
        ])

        with self.assertRaisesRegex(ValueError, 'mismo cliente'):
            validar_asignaciones_sap_planificadas(data)

    def test_rechaza_abs_id_y_linea_duplicados(self):
        data = self.data('5000', [
            self.asignacion('407', '1', '3000'),
            self.asignacion('407', '1', '2000'),
        ])

        with self.assertRaisesRegex(ValueError, 'misma linea'):
            validar_asignaciones_sap_planificadas(data)

    def test_rechaza_contrato_sin_producto(self):
        data = self.data('5000', [self.asignacion('407', '1', '5000', producto='')])

        with self.assertRaisesRegex(ValueError, 'producto'):
            validar_asignaciones_sap_planificadas(data)

    def test_rechaza_asignacion_sin_numero_de_acuerdo(self):
        asignacion = self.asignacion('407', '1', '5000')
        asignacion['contrato_sap'] = ''

        with self.assertRaisesRegex(ValueError, 'acuerdo'):
            validar_asignaciones_sap_planificadas(self.data('5000', [asignacion]))

    @patch('apps.home.sap_despacho.CITACION_DESPACHO_DETALLE.objects.update_or_create')
    def test_persiste_n_asignaciones_y_primera_en_campos_legacy(self, update_or_create):
        relacionados = Mock()
        detalle = SimpleNamespace(asignaciones_sap=relacionados)
        update_or_create.return_value = (detalle, True)
        empresa = SimpleNamespace()
        usuario = SimpleNamespace()
        citacion = SimpleNamespace(
            CI_CTIPO='DESPACHO', EP_NID=empresa, US_NID=usuario, SC_NID=None,
        )
        data = self.data('5000', [
            self.asignacion('407', '1', '3000'),
            self.asignacion('412', '3', '2000', producto='ITEM-2'),
        ])

        with patch('apps.home.sap_despacho.CITACION_DESPACHO_ASIGNACION_SAP') as modelo_asignacion:
            modelo_asignacion.ESTADO_PLANIFICADA = 'PLANIFICADA'
            modelo_asignacion.ESTADO_ANULADA = 'ANULADA'
            modelo_asignacion.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
            guardar_detalle_despacho_citacion.__wrapped__(citacion, data, usuario)
            creadas = modelo_asignacion.objects.bulk_create.call_args.args[0]

        defaults = update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDD_CSAP_ABS_ID'], '407')
        self.assertEqual(defaults['CDD_CSAP_NUMERO_ACUERDO'], 'AC-407')
        self.assertEqual(defaults['CDD_CSAP_LINEA_ACUERDO'], '1')
        self.assertEqual(defaults['CDD_NCANTIDAD_INTENTADA_DESPACHAR'], Decimal('3000'))
        self.assertEqual(len(creadas), 2)
        self.assertEqual(creadas[0].CDAS_NCANTIDAD_INTENTADA_DESPACHAR, Decimal('3000'))
        self.assertEqual(creadas[1].CDAS_CSAP_CODIGO_PRODUCTO, 'ITEM-2')
        self.assertEqual(creadas[0].CDAS_CSAP_OC_CLIENTE, 'OC-100')
        relacionados.all.return_value.delete.assert_called_once_with()

    def test_modelo_declara_integridad_por_linea_y_orden(self):
        restricciones = {constraint.name for constraint in CITACION_DESPACHO_ASIGNACION_SAP._meta.constraints}

        self.assertIn('CIT_DESP_SAP_UNQ_LINEA', restricciones)
        self.assertIn('CIT_DESP_SAP_UNQ_ORDEN', restricciones)
        self.assertIn('CIT_DESP_SAP_CANT_POSITIVA', restricciones)

    def test_historico_sin_asignaciones_nuevas_conserva_lectura_legacy(self):
        detalle = SimpleNamespace(
            CDD_CSAP_ABS_ID='407',
            CDD_CSAP_NUMERO_ACUERDO='AC-407',
            CDD_CSAP_LINEA_ACUERDO='1',
            CDD_CSAP_CODIGO_PRODUCTO='ITEM-1',
            CDD_CSAP_NOMBRE_PRODUCTO='Producto uno',
        )
        citacion = SimpleNamespace(
            detalle_despacho=detalle,
            CI_CCOMENTARIO='',
            SC_NID=None,
            SN_NID=None,
        )

        resumen = detalle_despacho_resumen_dict(citacion)

        self.assertEqual(resumen['sap_abs_id'], '407')
        self.assertEqual(resumen['sap_numero_acuerdo'], 'AC-407')
        self.assertEqual(resumen['sap_codigo_producto'], 'ITEM-1')

    def test_modal_envia_coleccion_y_usa_buscadores_reutilizables(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')

        self.assertIn('let asignacionesSapPlanificadas = [];', template)
        self.assertIn('function anexarContratoSapDespacho()', template)
        self.assertIn('function inicializarBuscadorAsignacionSap(select)', template)
        self.assertIn('function confirmarAsignacionSap(asignacionId)', template)
        self.assertIn('let vistasPreviasSapDespacho = {};', template)
        self.assertIn('Debe confirmar el contrato SAP seleccionado', template)
        self.assertIn('asignaciones_sap: asignacionesSap', template)
        self.assertIn('cantidad_intentada_despachar: asignacion.cantidad_intentada_despachar', template)
        self.assertNotIn('Total asignado contratos', template)
        self.assertNotIn('Producto SAP / Insumo principal', template)
        self.assertNotIn('OC Cliente principal', template)
        self.assertEqual(template.count('id="despacho_cliente"'), 1)

    def test_seleccionar_contrato_solo_crea_vista_previa(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        seleccion = template.split('function seleccionarAsignacionSap(asignacionId, item)', 1)[1]
        seleccion = seleccion.split('function actualizarDetalleVisualAsignacionSap', 1)[0]

        self.assertIn('vistasPreviasSapDespacho[asignacionId] = vistaPrevia', seleccion)
        self.assertNotIn('asignacionesSapPlanificadas.push', seleccion)

    def test_confirmar_contrato_lo_agrega_a_coleccion(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        confirmacion = template.split('function confirmarAsignacionSap(asignacionId)', 1)[1]
        confirmacion = confirmacion.split('function reiniciarBloqueAsignacionSap', 1)[0]

        self.assertIn('asignacionesSapPlanificadas.push(vistaPrevia)', confirmacion)
        self.assertIn('delete vistasPreviasSapDespacho[asignacionId]', confirmacion)


class AsignacionesSapModeloTests(SimpleTestCase):
    def test_snapshots_sap_permiten_null_y_cantidades_son_decimal(self):
        snapshot = CITACION_DESPACHO_ASIGNACION_SAP._meta.get_field('CDAS_NSAP_SALDO')
        intentada = CITACION_DESPACHO_ASIGNACION_SAP._meta.get_field('CDAS_NCANTIDAD_INTENTADA_DESPACHAR')
        relacion = CITACION_DESPACHO_ASIGNACION_SAP._meta.get_field('CDD_NID')

        self.assertTrue(snapshot.null and snapshot.blank)
        self.assertEqual(intentada.decimal_places, 5)
        self.assertEqual(relacion.remote_field.model, CITACION_DESPACHO_DETALLE)
        self.assertEqual(relacion.remote_field.related_name, 'asignaciones_sap')
