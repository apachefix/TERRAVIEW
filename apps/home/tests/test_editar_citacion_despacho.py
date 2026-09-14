import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.home import views
from apps.home.sap_despacho import (
    serializar_asignaciones_sap_planificadas,
    sincronizar_asignaciones_sap_planificadas,
    validar_asignaciones_sap_planificadas,
)


class EditarCitacionDespachoTests(SimpleTestCase):
    def asignacion(self, local_id=1, abs_id='433', linea='1', cantidad='100'):
        return {
            'id': local_id,
            'sap_abs_id': abs_id,
            'contrato_sap': f'AC-{abs_id}',
            'linea_acuerdo_sap': linea,
            'codigo_producto_sap': f'ITEM-{abs_id}',
            'nombre_producto_sap': f'Producto {abs_id}',
            'cliente_codigo': 'C001',
            'cliente_nombre': 'Cliente Uno',
            'oc_cliente': f'OC-{abs_id}',
            'cantidad_planificada_sap': '1000',
            'cantidad_consumida_sap': '200',
            'saldo_contrato_sap': '800',
            'unidad_medida': 'KG',
            'cantidad_intentada_despachar': cantidad,
            'estado': 'PLANIFICADA',
        }

    @patch('apps.home.views.citacion_tiene_avance_operativo_critico', return_value=False)
    def test_despacho_programado_es_editable(self, _avance):
        citacion = SimpleNamespace(CI_CESTADO='Despacho Programado')
        self.assertTrue(views.citacion_puede_editar_planificacion(citacion))

    @patch('apps.home.views.citacion_tiene_avance_operativo_critico', return_value=True)
    def test_despacho_con_avance_critico_sigue_bloqueado(self, _avance):
        citacion = SimpleNamespace(CI_CESTADO='Despacho Programado')
        self.assertFalse(views.citacion_puede_editar_planificacion(citacion))

    def test_validador_conserva_id_local_y_rechaza_duplicados(self):
        datos = {'cliente_codigo': 'C001', 'asignaciones_sap': [self.asignacion(17)]}
        resultado = validar_asignaciones_sap_planificadas(datos)
        self.assertEqual(resultado[0]['id'], 17)

        datos['asignaciones_sap'] = [
            self.asignacion(17, '433', '1'),
            self.asignacion(18, '433', '1'),
        ]
        with self.assertRaisesRegex(ValueError, 'misma linea'):
            validar_asignaciones_sap_planificadas(datos)

    def test_serializer_devuelve_n_asignaciones_ordenadas_y_snapshots(self):
        fila_1 = SimpleNamespace(
            id=9, CDAS_CSAP_ABS_ID='433', CDAS_CSAP_NUMERO_ACUERDO='AC-433',
            CDAS_CSAP_LINEA_ACUERDO='1', CDAS_CSAP_CODIGO_PRODUCTO='ITEM-A',
            CDAS_CSAP_NOMBRE_PRODUCTO='Producto A', CDAS_CSAP_CLIENTE_CODIGO='C001',
            CDAS_CSAP_CLIENTE_NOMBRE='Cliente Uno', CDAS_CSAP_OC_CLIENTE='OC-A',
            CDAS_NSAP_CANTIDAD_CONTRATO=Decimal('1000'),
            CDAS_NSAP_CANTIDAD_CONSUMIDA=Decimal('100'),
            CDAS_NSAP_SALDO=Decimal('900'), CDAS_CSAP_UNIDAD_MEDIDA='KG',
            CDAS_NCANTIDAD_INTENTADA_DESPACHAR=Decimal('100'),
            CDAS_NORDEN=1, CDAS_CESTADO='PLANIFICADA',
        )
        fila_2 = SimpleNamespace(**{
            **fila_1.__dict__, 'id': 10, 'CDAS_CSAP_ABS_ID': '426',
            'CDAS_CSAP_NUMERO_ACUERDO': 'AC-426', 'CDAS_NORDEN': 2,
        })
        relacionados = Mock()
        relacionados.all.return_value.order_by.return_value = [fila_1, fila_2]
        detalle = SimpleNamespace(asignaciones_sap=relacionados)

        resultado = serializar_asignaciones_sap_planificadas(SimpleNamespace(), detalle)

        self.assertEqual([item['id'] for item in resultado], [9, 10])
        self.assertEqual(resultado[0]['cantidad_intentada_despachar'], Decimal('100'))
        relacionados.all.return_value.order_by.assert_called_once_with('CDAS_NORDEN', 'id')

    def test_serializer_reconstruye_historico_desde_legacy(self):
        relacionados = Mock()
        relacionados.all.return_value.order_by.return_value = []
        detalle = SimpleNamespace(
            asignaciones_sap=relacionados,
            CDD_CSAP_ABS_ID='407', CDD_CSAP_NUMERO_ACUERDO='AC-407',
            CDD_CSAP_LINEA_ACUERDO='1', CDD_CSAP_CODIGO_PRODUCTO='ITEM-1',
            CDD_CSAP_NOMBRE_PRODUCTO='Producto uno', CDD_CSAP_CLIENTE_CODIGO='',
            CDD_CSAP_CLIENTE_NOMBRE='', CDD_CSAP_OC_CLIENTE='OC-1',
            CDD_NSAP_CANTIDAD_PLANIFICADA=Decimal('1000'),
            CDD_NSAP_CANTIDAD_CONSUMIDA=Decimal('100'),
            CDD_NSAP_SALDO_CONTRATO=Decimal('900'),
            CDD_CSAP_UNIDAD_MEDIDA='KG',
            CDD_NCANTIDAD_INTENTADA_DESPACHAR=Decimal('50'),
        )
        cliente = SimpleNamespace(SN_CCODIGO_SAP='C001', SN_CRAZONSOCIAL='Cliente Uno')

        resultado = serializar_asignaciones_sap_planificadas(
            SimpleNamespace(SN_NID=cliente), detalle
        )

        self.assertEqual(len(resultado), 1)
        self.assertTrue(resultado[0]['legacy'])
        self.assertEqual(resultado[0]['cliente_codigo'], 'C001')

    @patch('apps.home.sap_despacho.CITACION_DESPACHO_ASIGNACION_SAP.objects.create')
    def test_sincronizacion_actualiza_crea_y_elimina_filas(self, crear):
        existente = SimpleNamespace(id=7, save=Mock())
        eliminado = SimpleNamespace(id=8, save=Mock())
        relacionados = Mock()
        relacionados.select_for_update.return_value.all.return_value = [existente, eliminado]
        detalle = SimpleNamespace(
            asignaciones_sap=relacionados,
            EP_NID=SimpleNamespace(),
            US_NID=SimpleNamespace(),
        )
        nueva = self.asignacion(None, '426', '2', '19')
        normalizadas = validar_asignaciones_sap_planificadas({
            'cliente_codigo': 'C001',
            'asignaciones_sap': [self.asignacion(7), nueva],
        })
        crear.return_value = SimpleNamespace()

        sincronizar_asignaciones_sap_planificadas(detalle, normalizadas)

        relacionados.exclude.assert_called_once_with(id__in={7})
        relacionados.exclude.return_value.delete.assert_called_once_with()
        existente.save.assert_called_once_with()
        self.assertEqual(existente.CDAS_NCANTIDAD_INTENTADA_DESPACHAR, Decimal('100'))
        self.assertEqual(crear.call_args.kwargs['CDAS_NORDEN'], 2)

    @patch('apps.home.views.sincronizar_asignaciones_sap_planificadas')
    @patch('apps.home.views.CITACION_DESPACHO_DETALLE.objects.select_for_update')
    @patch('apps.home.views.SECUENCIA.objects.get')
    @patch('apps.home.views.resolver_socio_negocio_planificacion')
    @patch('apps.home.views.citacion_puede_editar_planificacion', return_value=True)
    @patch('apps.home.views.CITACION.objects.select_for_update')
    def test_update_persiste_fechas_horas_orden_cliente_y_espejo(
        self, bloquear, _editable, resolver_cliente, obtener_secuencia,
        bloquear_detalle, sincronizar,
    ):
        empresa = SimpleNamespace()
        citacion = SimpleNamespace(
            EP_NID=empresa, EP_NID_id=2, SN_NID=None, SC_NID=None,
            CI_CTIPO='DESPACHO', CI_CTIPO_FLETE='', CI_CTIPODOCUMENTO='',
            CI_CNUMERODOCUMENTO='', CI_CCOMENTARIO='', save=Mock(),
        )
        bloquear.return_value.select_related.return_value.get.return_value = citacion
        cliente = SimpleNamespace()
        resolver_cliente.return_value = cliente
        secuencia = SimpleNamespace(SE_CCODIGO='DESP', SE_CNOMBRE='Despacho')
        obtener_secuencia.return_value = secuencia
        detalle = SimpleNamespace(EP_NID=empresa, US_NID=None)
        bloquear_detalle.return_value.update_or_create.return_value = (detalle, False)
        asignaciones = [self.asignacion(7)]
        request = SimpleNamespace(
            user=SimpleNamespace(),
            POST={
                'fecha_despacho': '2026-09-10',
                'hora_llegada_planta': '08:30',
                'hora_llegada_destino': '13:45',
                'orden_carga': '2°',
                'tipo_carga': 'Cisterna',
                'destino': 'Cliente destino',
                'id_cliente': 'C001',
                'cliente_codigo': 'C001',
                'cliente_nombre': 'Cliente Uno',
                'id_secuencia': '5',
                'salida_documento': 'FE',
                'bodega': 'SBH',
                'condicion_entrega': 'Terramar',
                'empresa_transporte': 'Transportes Uno',
                'conductor': 'Conductor Uno',
                'patente': 'aa bb 11',
                'asignaciones_sap': json.dumps(asignaciones),
            },
        )

        response = views.actualizar_citacion_despacho_planificacion.__wrapped__(request, 99)

        self.assertEqual(json.loads(response.content), {'valid': True})
        self.assertIs(citacion.SN_NID, cliente)
        defaults = bloquear_detalle.return_value.update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDD_FFECHA_DESPACHO'], '2026-09-10')
        self.assertEqual(defaults['CDD_FHORA_LLEGADA_PLANTA'], '08:30')
        self.assertEqual(defaults['CDD_FHORA_LLEGADA_DESTINO'], '13:45')
        self.assertEqual(defaults['CDD_CORDEN_CARGA'], '2°')
        self.assertEqual(defaults['CDD_CPATENTE'], 'AA BB 11')
        self.assertEqual(defaults['CDD_CSAP_ABS_ID'], '433')
        self.assertEqual(defaults['CDD_NCANTIDAD_INTENTADA_DESPACHAR'], Decimal('100'))
        sincronizar.assert_called_once()

    @patch('apps.home.views.sincronizar_asignaciones_sap_planificadas', side_effect=ValueError('fallo fila'))
    @patch('apps.home.views.CITACION_DESPACHO_DETALLE.objects.select_for_update')
    @patch('apps.home.views.SECUENCIA.objects.get')
    @patch('apps.home.views.resolver_socio_negocio_planificacion')
    @patch('apps.home.views.citacion_puede_editar_planificacion', return_value=True)
    @patch('apps.home.views.CITACION.objects.select_for_update')
    def test_update_propaga_error_de_asignacion_para_rollback_atomico(
        self, bloquear, _editable, resolver_cliente, obtener_secuencia,
        bloquear_detalle, _sincronizar,
    ):
        citacion = SimpleNamespace(
            EP_NID=SimpleNamespace(), EP_NID_id=2, SN_NID=None, SC_NID=None,
            CI_CTIPO='DESPACHO', CI_CTIPO_FLETE='', CI_CTIPODOCUMENTO='',
            CI_CNUMERODOCUMENTO='', CI_CCOMENTARIO='', save=Mock(),
        )
        bloquear.return_value.select_related.return_value.get.return_value = citacion
        resolver_cliente.return_value = SimpleNamespace()
        obtener_secuencia.return_value = SimpleNamespace(SE_CCODIGO='D', SE_CNOMBRE='Despacho')
        bloquear_detalle.return_value.update_or_create.return_value = (
            SimpleNamespace(EP_NID=citacion.EP_NID, US_NID=None), False
        )
        post = {
            'fecha_despacho': '2026-09-10', 'hora_llegada_planta': '08:30',
            'hora_llegada_destino': '13:45', 'orden_carga': '1°',
            'tipo_carga': 'Cisterna', 'destino': 'Destino',
            'id_cliente': 'C001', 'cliente_codigo': 'C001',
            'id_secuencia': '5', 'salida_documento': 'FE',
            'asignaciones_sap': json.dumps([self.asignacion(7)]),
        }
        with self.assertRaisesRegex(ValueError, 'fallo fila'):
            views.actualizar_citacion_despacho_planificacion.__wrapped__(
                SimpleNamespace(user=SimpleNamespace(), POST=post), 99
            )

    def test_modal_despacho_declara_campos_tipados_json_y_oc_por_tarjeta(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn('id="edit_despacho_fecha" name="fecha_despacho"', template)
        self.assertIn('id="edit_despacho_hora_planta" name="hora_llegada_planta"', template)
        self.assertIn('id="edit_despacho_hora_destino" name="hora_llegada_destino"', template)
        self.assertIn('id="edit_despacho_orden_carga" name="orden_carga"', template)
        self.assertIn('id="edit_despacho_asignaciones_json" name="asignaciones_sap"', template)
        self.assertIn('OC Cliente</small><strong class="d-block js-edit-oc"', template)
        self.assertIn('Debe confirmar el contrato SAP seleccionado antes de actualizar', template)
        self.assertNotIn('Total asignado contratos', template)
        self.assertNotIn('Producto principal', template)
        self.assertEqual(template.count('id="id_cliente"'), 1)

    def test_modal_oculta_recepcion_y_update_conserva_rama_legacy(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn("configurarModalEdicionPorTipo(PLANIFICACION_ES_DESPACHO ? 'DESPACHO' : 'RECEPCION')", template)
        self.assertIn("$('#edit_recepcion_fields').toggleClass('d-none', despacho)", template)
        fuente = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn('if es_citacion_despacho(citacion):\n                return actualizar_citacion_despacho_planificacion', fuente)
        self.assertIn('# Update citation fields', fuente)
