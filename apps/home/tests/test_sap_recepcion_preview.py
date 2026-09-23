from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from inspect import getsource
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.home import views
from apps.integrations.sap_b1 import sap_recepcion


class RecepcionSbhPreviewEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_superuser=True,
        )
        self.citacion = SimpleNamespace(
            id=38714,
            pk=38714,
            EP_NID_id=2,
            CI_CTIPO='RECEPCION',
            PL_NID=SimpleNamespace(PL_CTIPOCUPO='RECEPCION'),
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_ESTANQUE_SBH'),
            save=MagicMock(),
        )
        self.preview = {
            'payload': {
                'CardCode': 'P76948423',
                'DocumentLines': [{
                    'ItemCode': '950128',
                    'Quantity': 6,
                    'BaseEntry': 5713,
                    'BaseLine': 0,
                    'WarehouseCode': 'TK14',
                    'LineTotal': 2000,
                }],
            },
            'source_data': {'origen_cantidad': 'peso_guia', 'quantity': 6},
            'validations': [],
            'warnings': [],
            'errors': [],
            'selected_line': {},
        }

    def _request(self):
        request = self.factory.post('/operacion-planta/38714/borrador-sap-preview/')
        request.user = self.user
        return request

    def _endpoint_dependencies(self, *, draft_status=None):
        stack = ExitStack()
        stack.enter_context(patch.object(views, 'usuario_es_operacion_planta', return_value=True))
        stack.enter_context(patch.object(
            views,
            '_obtener_citacion_operacion_planta_ajax',
            return_value=(self.citacion, None),
        ))
        stack.enter_context(patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True))
        stack.enter_context(patch.object(views, 'es_flujo_recepcion_estanque_sbh', return_value=True))
        stack.enter_context(patch.object(
            views,
            'get_goods_receipt_draft_guide_status',
            return_value=draft_status or {'sent': False, 'local_status': 'Pendiente de generar'},
        ))
        return stack

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False)
    def test_flag_desactivado_responde_404(self):
        with self._endpoint_dependencies(), patch.object(
            views, 'build_goods_receipt_draft_preview_from_peso_guia'
        ) as builder:
            response = views.ajax_operacion_planta_borrador_sap_preview(self._request(), 38714)

        self.assertEqual(response.status_code, 404)
        builder.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_preview_usa_peso_guia_sin_exigir_pesaje_salida(self):
        with self._endpoint_dependencies(), patch.object(
            views,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=dict(self.preview),
        ) as builder, patch.object(views, '_validar_borrador_sap_disponible') as validar_pesaje:
            response = views.ajax_operacion_planta_borrador_sap_preview(self._request(), 38714)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertTrue(payload['read_only'])
        self.assertEqual(payload['preview']['payload']['DocumentLines'][0]['Quantity'], 6)
        self.assertEqual(payload['preview']['source_data']['origen_cantidad'], 'peso_guia')
        builder.assert_called_once_with(self.citacion)
        validar_pesaje.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_preview_no_escribe_sap_bd_calidad_ni_citacion(self):
        with self._endpoint_dependencies(), patch.object(
            views,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=dict(self.preview),
        ), patch.object(
            views, 'send_goods_receipt_draft_to_sap'
        ) as send_legacy, patch.object(
            views, 'send_goods_receipt_draft_from_peso_guia_to_sap'
        ) as send_guia, patch.object(
            views.OPERACION_PLANTA_LOG.objects, 'create'
        ) as crear_log, patch.object(
            views, 'asegurar_calidad_iniciada'
        ) as cambiar_calidad:
            response = views.ajax_operacion_planta_borrador_sap_preview(self._request(), 38714)

        self.assertEqual(response.status_code, 200)
        send_legacy.assert_not_called()
        send_guia.assert_not_called()
        crear_log.assert_not_called()
        cambiar_calidad.assert_not_called()
        self.citacion.save.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_draft_existente_se_informa_y_no_se_reenvia(self):
        draft_status = {
            'sent': True,
            'local_status': 'Borrador enviado',
            'sap_status': 'Creado en SAP QA',
            'docentry': 8123,
            'docnum': 9123,
            'request_json': {'CardCode': 'P76948423'},
            'response_json': {'DocEntry': 8123, 'DocNum': 9123},
        }
        with self._endpoint_dependencies(draft_status=draft_status), patch.object(
            views,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=dict(self.preview),
        ), patch.object(views, 'send_goods_receipt_draft_from_peso_guia_to_sap') as enviar:
            response = views.ajax_operacion_planta_borrador_sap_preview(self._request(), 38714)

        payload = json.loads(response.content)['preview']['existing_draft']
        self.assertTrue(payload['sent'])
        self.assertEqual(payload['docentry'], 8123)
        self.assertEqual(payload['request_json']['CardCode'], 'P76948423')
        enviar.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_backend_rechaza_usuario_sin_permiso_operacion(self):
        with patch.object(views, 'usuario_es_operacion_planta', return_value=False):
            response = views.ajax_operacion_planta_borrador_sap_preview(self._request(), 38714)

        self.assertEqual(response.status_code, 403)

    def test_template_limita_boton_al_flag_de_recepcion(self):
        template_path = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'CITACION' / 'operacion_planta.html'
        )
        source = template_path.read_text(encoding='utf-8')
        self.assertIn('{% if sap_recepcion_preview_enabled %}', source)
        self.assertIn('btn-preview-sap-recepcion', source)

    def test_flags_recepcion_y_despacho_permanecen_independientes(self):
        source = getsource(views)
        self.assertIn("getattr(settings, 'SAP_RECEPCION_PREVIEW_ENABLED', False)", source)
        self.assertIn("getattr(settings, 'SAP_DESPACHO_PREVIEW_ENABLED', False)", source)


class RecepcionSbhPreviewBuilderTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(
            id=38714,
            EP_NID_id=2,
            CI_CTIPODOCUMENTO='GD',
            CI_CNUMERODOCUMENTO='565644',
        )
        self.detalle = SimpleNamespace(
            CDO_CESTANQUE_DESTINO='TK14',
            CDO_CPEDIDO_SAP='10000916',
            CDO_CCODIGO_SAP='950128',
            CDO_CINSUMO='ACEITE CAMELINA CARGILL',
            CDO_CPROVEEDOR_CODIGO='P76948423',
            CDO_CPRODUCTOR='CARGILL COSTANERA SPA',
            CDO_CBL_CONTENEDOR='',
            CDO_NCANTIDAD_DISPONIBLE=Decimal('2000'),
        )

    def test_builder_lee_purchase_order_y_nunca_invoca_write_sap(self):
        selected_line = {
            'LineNum': 0,
            'ItemCode': '950128',
            'ItemDescription': 'ACEITE CAMELINA CARGILL',
            'Quantity': 2000,
            'OpenQuantity': 2000,
            'LineStatus': 'bost_Open',
            'LineTotal': 2000,
        }
        client = MagicMock()
        client.get_json.return_value = {
            'CardCode': 'P76948423',
            'DocumentLines': [selected_line],
        }

        with patch.object(sap_recepcion, '_latest_detail', return_value=self.detalle), patch.object(
            sap_recepcion, '_resolve_doc_entry', return_value=5713
        ), patch.object(
            sap_recepcion,
            '_dato_valor',
            side_effect=lambda _citacion, codigo: (
                '6' if codigo == sap_recepcion.CAMPO_PESO_INFORMADO_GUIA else ''
            ),
        ), patch.object(
            sap_recepcion, 'get_batch_number_from_citation', return_value=''
        ), patch.object(
            sap_recepcion,
            'find_matching_purchase_order_line',
            return_value=(selected_line, 'Linea encontrada'),
        ), patch.object(
            sap_recepcion, '_draft_series', return_value=17
        ), patch.object(
            sap_recepcion, 'get_goods_receipt_draft_status', return_value={'sent': False}
        ), patch.object(
            sap_recepcion,
            'load_config',
            return_value=SimpleNamespace(company_db='TEST', username='test'),
        ), patch.object(
            sap_recepcion, 'SapServiceLayerClient', return_value=client
        ), patch.object(
            sap_recepcion.timezone, 'localdate', return_value=date(2026, 9, 21)
        ):
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(self.citacion)

        line = preview['payload']['DocumentLines'][0]
        self.assertEqual(preview['source_data']['origen_cantidad'], 'peso_guia')
        self.assertEqual(line['Quantity'], 6)
        self.assertEqual(line['BaseEntry'], 5713)
        self.assertEqual(line['BaseLine'], 0)
        client.get_json.assert_called_once_with('PurchaseOrders(5713)', 'PurchaseOrders(5713)')
        client.post_draft.assert_not_called()
        client.patch_draft.assert_not_called()
        client.login.assert_called_once()
        client.logout.assert_called_once()
