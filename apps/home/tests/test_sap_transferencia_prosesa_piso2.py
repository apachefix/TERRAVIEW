"""Pruebas focalizadas de StockTransfers PROSESA Piso 2; nunca contactan SAP."""

import json
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.home import views
from apps.home.models import OPERACION_PLANTA_LOG
from apps.home.sap_transferencia_prosesa import (
    LOG_TRANSFERENCIA_PROSESA_PISO_2,
    build_stock_transfer_prosesa_piso_2,
    send_stock_transfer_prosesa_piso_2_to_sap,
)
from apps.integrations.sap_b1.sap_recepcion import LOG_PURCHASE_DELIVERY_NOTE_PROSESA_PISO_1


@override_settings(BODEGA_VIRTUAL='B_TRANSI', SAP_RECEPCION_PREVIEW_ENABLED=True)
class TransferenciaSapProsesaPiso2TestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        RecepcionProsesaTestCase.setUpTestData.__func__(cls)

    def _crear_ticket_prosesa(self, *args):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        return RecepcionProsesaTestCase._crear_ticket_prosesa(self, *args)

    def _crear_cuatro_pesajes_validos(self):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        return RecepcionProsesaTestCase._crear_cuatro_pesajes_validos(self)

    def setUp(self):
        self._crear_cuatro_pesajes_validos()
        views.calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self.ingreso_log = OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=self.origen, OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_PROSESA_PISO_1,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'success': True, 'response': {'DocEntry': 20347, 'DocNum': 13183},
                'payload': {'DocumentLines': [{
                    'ItemCode': 'ITEM-1', 'WarehouseCode': 'B_TRANSI', 'Quantity': 24,
                    'BatchNumbers': [{'BatchNumber': 'LOTE-PROSESA-1', 'Quantity': 24}],
                }]},
            }),
        )

    def sap_read_mocks(self, *, stock=24, duplicate=None):
        stack = ExitStack()
        module = 'apps.home.sap_transferencia_prosesa.'
        stack.enter_context(patch(module + '_schema_sap', return_value='SAP_TEST'))
        stack.enter_context(patch(module + 'consultar_ingreso_virtual_prosesa_piso_1',
            return_value={'docentry': 20347, 'docnum': 13183, 'quantity': Decimal('24')}))
        stack.enter_context(patch(module + 'consultar_articulo_y_bodegas_prosesa',
            return_value={'unit': 'Toneladas Metricas', 'origin_stock_total': Decimal('24'),
                          'batch_managed': 'Y'}))
        stack.enter_context(patch(module + 'consultar_stock_lote_prosesa',
            return_value={'stock': Decimal(str(stock)), 'available': Decimal(str(stock)),
                          'committed': Decimal('0')}))
        stack.enter_context(patch(module + 'obtener_fecha_sistema_sap',
            return_value=date(2026, 9, 26).isoformat()))
        stack.enter_context(patch(module + 'buscar_transferencia_sap_prosesa_piso_2',
            return_value=duplicate))
        return stack

    def test_builder_usa_ingreso_real_peso_persistido_lote_y_remanente(self):
        with self.sap_read_mocks():
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
        self.assertTrue(preview['ready_for_post'], preview['errors'])
        self.assertEqual(preview['endpoint'], '/StockTransfers')
        self.assertEqual(preview['source_data']['ingreso_docentry'], 20347)
        self.assertEqual(preview['source_data']['peso_ingresado_virtual_kg'], 24000)
        self.assertEqual(preview['source_data']['peso_real_kg'], 17000)
        self.assertEqual(preview['source_data']['remanente_estimado_kg'], 7000)
        payload = preview['payload']
        self.assertEqual(payload['FromWarehouse'], 'B_TRANSI')
        self.assertEqual(payload['ToWarehouse'], 'PROSE_G2')
        self.assertEqual(payload['Reference1'], 'TERRAVIEW')
        self.assertEqual(payload['Reference2'], '38729')
        line = payload['StockTransferLines'][0]
        self.assertEqual(line['ItemCode'], 'ITEM-1')
        self.assertEqual(line['Quantity'], 17)
        self.assertEqual(line['BatchNumbers'], [{'BatchNumber': 'LOTE-PROSESA-1', 'Quantity': 17}])

    def test_sin_ingreso_real_no_inventa_cantidad_virtual_ni_envia(self):
        self.ingreso_log.delete()
        with self.sap_read_mocks(), patch('apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client:
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
            result = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
        self.assertFalse(preview['ready_for_post'])
        self.assertNotIn('peso_ingresado_virtual_kg', preview['source_data'])
        self.assertFalse(result['success'])
        client.assert_not_called()

    def test_stock_lote_insuficiente_bloquea_payload(self):
        with self.sap_read_mocks(stock=16):
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
        self.assertFalse(preview['ready_for_post'])
        self.assertIn('Stock disponible del lote', ' '.join(preview['errors']))

    def test_transferencia_ya_existente_en_sap_bloquea_segundo_envio(self):
        duplicate = {'docentry': 88, 'docnum': 99, 'origen': 'B_TRANSI', 'destino': 'PROSE_G2'}
        with self.sap_read_mocks(duplicate=duplicate), patch('apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client:
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
            result = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
        self.assertTrue(preview['status']['creada'])
        self.assertFalse(preview['ready_for_post'])
        self.assertFalse(result['success'])
        client.assert_not_called()

    def test_sender_usa_mismo_payload_guarda_docentry_y_no_duplica(self):
        with self.sap_read_mocks(), patch('apps.home.sap_transferencia_prosesa.load_config',
            return_value=SimpleNamespace(company_db='SAP_TEST')) as config, patch(
            'apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client_type:
            client = client_type.return_value
            client.post_stock_transfer.return_value = {
                'data': {'DocEntry': 88, 'DocNum': 99}, 'status_code': 201,
            }
            result = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
            again = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
        self.assertTrue(result['success'])
        self.assertEqual(result['docentry'], 88)
        self.assertFalse(again['success'])
        self.assertEqual(client.post_stock_transfer.call_count, 1)
        payload = client.post_stock_transfer.call_args.args[0]
        self.assertEqual(payload['StockTransferLines'][0]['Quantity'], 17)
        config.assert_called_with(2, for_write=True)
        log = OPERACION_PLANTA_LOG.objects.get(
            CI_NID=self.retiro, OPL_CPASO=LOG_TRANSFERENCIA_PROSESA_PISO_2,
        )
        self.assertEqual(log.OPL_CESTADO, OPERACION_PLANTA_LOG.ESTADO_COMPLETADO)
        audit = json.loads(log.OPL_COBSERVACION)
        self.assertEqual(audit['estado'], 'CREADO')
        self.assertEqual(audit['response']['DocEntry'], 88)
        self.assertEqual(audit['payload'], payload)

    def test_respuesta_incierta_bloquea_reintento(self):
        with self.sap_read_mocks(), patch('apps.home.sap_transferencia_prosesa.load_config',
            return_value=SimpleNamespace(company_db='SAP_TEST')), patch(
            'apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client_type:
            client = client_type.return_value
            client.post_stock_transfer.side_effect = TimeoutError('timeout')
            result = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
            again = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
        self.assertEqual(result['status']['estado'], 'INCIERTO')
        self.assertFalse(again['success'])
        self.assertEqual(client.post_stock_transfer.call_count, 1)

    def test_preview_endpoint_es_solo_lectura_y_flag_lo_oculta(self):
        request = RequestFactory().post(reverse(
            'ajax_operacion_planta_preview_transferencia_sap_prosesa', args=[self.retiro.id],
        ))
        request.user = self.usuario
        with self.sap_read_mocks(), patch.object(views, 'usuario_es_operacion_planta', return_value=True), patch.object(
            views, 'usuario_es_asistente_recepcion', return_value=True), patch.object(
            views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.retiro, None)), patch.object(
            views, 'obtener_paso_activo_operacion', return_value=(views.PASO_AUTORIZAR_SALIDA, None)), patch(
            'apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client:
            response = views.ajax_operacion_planta_preview_transferencia_sap_prosesa(request, self.retiro.id)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['read_only'])
        client.assert_not_called()
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False):
            response = views.ajax_operacion_planta_preview_transferencia_sap_prosesa(request, self.retiro.id)
        self.assertEqual(response.status_code, 404)

    def test_otro_flujo_no_tiene_transferencia(self):
        with patch('apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client:
            preview = build_stock_transfer_prosesa_piso_2(self.legacy)
        self.assertFalse(preview['ready_for_post'])
        client.assert_not_called()

    def test_caso_18510_kg_equivale_a_18_51_mt_y_remanente_5_49_mt(self):
        pesos = {
            (self.origen.id, 'ENT'): 37070,
            (self.origen.id, 'SAL'): 17780,
            (self.retiro.id, 'ENT'): 16610,
            (self.retiro.id, 'SAL'): 17390,
        }
        for dato in views.DATO_OPERACION.objects.filter(
            CI_NID__in=[self.origen, self.retiro],
            CAMP_NID__CA_CCODIGO__startswith='OP_TICKET_PESAJE_',
        ):
            tipo = dato.CAMP_NID.CA_CCODIGO.rsplit('_', 1)[-1]
            peso = pesos[(dato.CI_NID_id, tipo)]
            metadata = json.loads(dato.DO_CVALOR)
            metadata.update({'peso_neto': peso, 'peso_bruto_kg': peso})
            dato.DO_NPESO = peso
            dato.DO_CVALOR = json.dumps(metadata)
            dato.save(update_fields=['DO_NPESO', 'DO_CVALOR'])
        views.calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        with self.sap_read_mocks():
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
        self.assertTrue(preview['ready_for_post'], preview['errors'])
        source = preview['source_data']
        self.assertEqual(source['peso_real_kg'], 18510)
        self.assertEqual(source['quantity_mt'], 18.51)
        self.assertEqual(source['remanente_estimado_kg'], 5490)
        self.assertEqual(source['remanente_estimado_mt'], 5.49)
        self.assertEqual(source['remanente_lote_mt'], 5.49)
        line = preview['payload']['StockTransferLines'][0]
        self.assertEqual(line['Quantity'], 18.51)
        self.assertEqual(line['BatchNumbers'][0]['Quantity'], 18.51)
        self.assertEqual(preview['payload']['DocDate'], '2026-09-26')

    def test_stock_que_cae_antes_del_post_bloquea_envio(self):
        stock_ok = {'stock': Decimal('24'), 'available': Decimal('24'), 'committed': Decimal('0')}
        stock_bajo = {'stock': Decimal('16'), 'available': Decimal('16'), 'committed': Decimal('0')}
        with self.sap_read_mocks(), patch(
            'apps.home.sap_transferencia_prosesa.consultar_stock_lote_prosesa',
            side_effect=[stock_ok, stock_bajo],
        ), patch('apps.home.sap_transferencia_prosesa.load_config',
            return_value=SimpleNamespace(company_db='SAP_TEST')), patch(
            'apps.home.sap_transferencia_prosesa.SapServiceLayerClient') as client:
            result = send_stock_transfer_prosesa_piso_2_to_sap(self.retiro, self.usuario)
        self.assertFalse(result['success'])
        self.assertIn('Stock disponible', result['message'])
        client.assert_not_called()

    def test_boton_preview_se_oculta_con_flag_false(self):
        from pathlib import Path
        from django.template import Context, Template

        html = Path('apps/templates/home/CITACION/operacion_planta.html').read_text(encoding='utf-8')
        start = html.index('{% with transferencia=peso_real_prosesa.transferencia_sap %}')
        end = html.index('{% endwith %}', start) + len('{% endwith %}')
        fragment = Template(html[start:end])
        with self.sap_read_mocks():
            preview = build_stock_transfer_prosesa_piso_2(self.retiro)
        context = {
            'peso_real_prosesa': {'transferencia_sap': preview, 'resultado_valido': True},
            'paso': {'activo': True, 'puede_editar': True},
            'prosesa_transferencia_preview_enabled': False,
        }
        output = fragment.render(Context(context))
        self.assertNotIn('btn-preview-transferencia-sap-prosesa', output)
        self.assertIn('btn-crear-transferencia-sap-prosesa', output)
        context['prosesa_transferencia_preview_enabled'] = True
        output = fragment.render(Context(context))
        self.assertIn('btn-preview-transferencia-sap-prosesa', output)