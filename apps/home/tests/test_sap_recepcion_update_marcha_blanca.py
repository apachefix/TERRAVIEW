import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

from apps.home import views
from apps.integrations.sap_b1 import sap_recepcion


class SapRecepcionUpdateMarchaBlancaTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.citacion = SimpleNamespace(
            pk=38595,
            id=38595,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            PL_NID=SimpleNamespace(id=1207),
            CI_CTIPO='RECEPCION',
        )
        self.usuario = SimpleNamespace(username='Asistente_C_D')
        self.draft_status = {
            'sent': True,
            'docentry': 3249,
            'docnum': 10961,
            'item_code': '800034',
            'request_json': {
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800034',
                    }
                ]
            },
        }
        self.estado_pendiente = {'updated': False}
        self.estado_actualizado = {
            'updated': True,
            'resumen_mensaje': (
                'Borrador SAP actualizado con el pesaje de salida. '
                'Lote pendiente de ingreso manual en SAP.'
            ),
        }

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status', return_value={})
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_payload_marcha_blanca_convierte_kg_a_mt_y_omite_lote(
        self,
        draft_status_mock,
        _status_mock,
    ):
        draft_status_mock.return_value = self.draft_status

        preview = sap_recepcion.build_goods_receipt_draft_update_with_salida_lote(
            self.citacion,
            Decimal('26590'),
        )

        self.assertEqual(
            preview['payload'],
            {
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800034',
                        'Quantity': 26.59,
                    }
                ]
            },
        )
        self.assertNotIn('BatchNumbers', preview['payload']['DocumentLines'][0])
        self.assertEqual(preview['source_data']['peso_salida_kg'], 26590)
        self.assertEqual(preview['source_data']['cantidad_sap'], 26.59)
        self.assertEqual(preview['source_data']['unidad_sap'], 'MT')
        self.assertFalse(preview['source_data']['lote_enviado'])
        self.assertEqual(preview['source_data']['modo_lote'], 'MANUAL_SAP')
        self.assertEqual(
            sap_recepcion.convertir_peso_salida_kg_a_cantidad_sap_mt(Decimal('26590')),
            Decimal('26.59'),
        )

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_registrar_log_update_sap_recepcion')
    @patch.object(sap_recepcion, 'SapServiceLayerClient')
    @patch.object(sap_recepcion, 'load_config')
    @patch.object(sap_recepcion, '_guardar_lote_recepcion')
    @patch.object(sap_recepcion, 'generar_lote_recepcion_sap')
    @patch.object(sap_recepcion, '_first_row')
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('26590'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status')
    def test_envio_marcha_blanca_no_consulta_hana_no_guarda_lote_y_acepta_204(
        self,
        status_mock,
        draft_status_mock,
        _peso_mock,
        hana_query_mock,
        generar_lote_mock,
        guardar_lote_mock,
        config_mock,
        client_class_mock,
        registrar_log_mock,
    ):
        status_mock.side_effect = [
            self.estado_pendiente,
            self.estado_pendiente,
            self.estado_actualizado,
        ]
        draft_status_mock.return_value = self.draft_status
        config_mock.return_value = SimpleNamespace(company_db='SBO_TST_SBH_USD')
        client = client_class_mock.return_value
        client.patch_draft.return_value = {'status_code': 204, 'data': {}}

        resultado = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
        )

        generar_lote_mock.assert_not_called()
        hana_query_mock.assert_not_called()
        guardar_lote_mock.assert_not_called()
        client.patch_draft.assert_called_once_with(
            3249,
            {
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800034',
                        'Quantity': 26.59,
                    }
                ]
            },
        )
        client.login.assert_called_once_with()
        client.logout.assert_called_once_with()
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['status_code'], 204)
        self.assertTrue(resultado['status']['updated'])
        self.assertIn('Lote pendiente de ingreso manual en SAP', resultado['message'])

        auditoria = registrar_log_mock.call_args.kwargs
        self.assertEqual(auditoria['peso_salida_kg'], 26590)
        self.assertEqual(auditoria['cantidad_sap'], 26.59)
        self.assertEqual(auditoria['unidad_sap'], 'MT')
        self.assertFalse(auditoria['lote_enviado'])
        self.assertEqual(auditoria['modo_lote'], 'MANUAL_SAP')
        self.assertNotIn('BatchNumbers', auditoria['payload']['DocumentLines'][0])

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=True)
    @patch.object(sap_recepcion, '_registrar_log_update_sap_recepcion')
    @patch.object(sap_recepcion, 'SapServiceLayerClient')
    @patch.object(sap_recepcion, 'load_config')
    @patch.object(sap_recepcion, '_guardar_lote_recepcion')
    @patch.object(sap_recepcion, 'generar_lote_recepcion_sap', return_value='LOTE-MP-800034-10-001')
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('26590'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status')
    def test_bandera_habilitada_conserva_lote_con_cantidad_en_mt(
        self,
        status_mock,
        draft_status_mock,
        _peso_mock,
        generar_lote_mock,
        guardar_lote_mock,
        config_mock,
        client_class_mock,
        registrar_log_mock,
    ):
        status_mock.side_effect = [
            self.estado_pendiente,
            self.estado_pendiente,
            {'updated': True},
        ]
        draft_status_mock.return_value = self.draft_status
        config_mock.return_value = SimpleNamespace(company_db='SBO_TST_SBH_USD')
        client = client_class_mock.return_value
        client.patch_draft.return_value = {'status_code': 204, 'data': {}}

        resultado = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
        )

        generar_lote_mock.assert_called_once_with('800034')
        guardar_lote_mock.assert_called_once_with(
            self.citacion,
            self.usuario,
            'LOTE-MP-800034-10-001',
        )
        linea = client.patch_draft.call_args.args[1]['DocumentLines'][0]
        self.assertEqual(linea['Quantity'], 26.59)
        self.assertEqual(
            linea['BatchNumbers'],
            [
                {
                    'BatchNumber': 'LOTE-MP-800034-10-001',
                    'Quantity': 26.59,
                    'BaseLineNumber': 0,
                    'ItemCode': '800034',
                }
            ],
        )
        self.assertTrue(resultado['success'])
        auditoria = registrar_log_mock.call_args.kwargs
        self.assertTrue(auditoria['lote_enviado'])
        self.assertEqual(auditoria['modo_lote'], 'AUTOMATICO_TERRAVIEW')

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, 'SapServiceLayerClient')
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status')
    def test_segundo_intento_despues_de_exito_no_ejecuta_patch(
        self,
        status_mock,
        client_class_mock,
    ):
        status_mock.return_value = self.estado_actualizado

        resultado = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
        )

        self.assertTrue(resultado['success'])
        client_class_mock.assert_not_called()

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_registrar_log_update_sap_recepcion')
    @patch.object(sap_recepcion, 'SapServiceLayerClient')
    @patch.object(sap_recepcion, 'load_config')
    @patch.object(sap_recepcion, '_guardar_lote_recepcion')
    @patch.object(sap_recepcion, 'generar_lote_recepcion_sap')
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('26590'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status')
    def test_allow_retry_reenvia_peso_pero_no_genera_lote_en_marcha_blanca(
        self,
        status_mock,
        draft_status_mock,
        _peso_mock,
        generar_lote_mock,
        guardar_lote_mock,
        config_mock,
        client_class_mock,
        _registrar_log_mock,
    ):
        status_mock.side_effect = [
            self.estado_actualizado,
            self.estado_pendiente,
            self.estado_actualizado,
        ]
        draft_status_mock.return_value = self.draft_status
        config_mock.return_value = SimpleNamespace(company_db='SBO_TST_SBH_USD')
        client = client_class_mock.return_value
        client.patch_draft.return_value = {'status_code': 204, 'data': {}}

        resultado = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
            allow_retry=True,
        )

        self.assertTrue(resultado['success'])
        client.patch_draft.assert_called_once()
        generar_lote_mock.assert_not_called()
        guardar_lote_mock.assert_not_called()

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_send_goods_receipt_draft_update_to_sap_locked')
    @patch.object(sap_recepcion.CITACION.objects, 'select_for_update')
    def test_wrapper_bloquea_la_citacion_antes_del_envio(
        self,
        select_for_update_mock,
        envio_locked_mock,
    ):
        select_for_update_mock.return_value.get.return_value = self.citacion
        envio_locked_mock.return_value = {'success': True}

        resultado = sap_recepcion.send_goods_receipt_draft_update_to_sap(
            self.citacion,
            self.usuario,
        )

        select_for_update_mock.assert_called_once_with()
        select_for_update_mock.return_value.get.assert_called_once_with(pk=38595)
        envio_locked_mock.assert_called_once_with(
            self.citacion,
            self.usuario,
            allow_retry=False,
        )
        self.assertTrue(resultado['success'])

    @patch.object(sap_recepcion.OPERACION_PLANTA_LOG.objects, 'create')
    def test_log_manual_registra_auditoria_sin_lote_ficticio(self, create_mock):
        create_mock.return_value = MagicMock()

        sap_recepcion._registrar_log_update_sap_recepcion(
            self.citacion,
            self.usuario,
            success=True,
            payload={
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800034',
                        'Quantity': 26.59,
                    }
                ]
            },
            response={},
            status_code=204,
            docentry=3249,
            docnum=10961,
            item_code='800034',
            peso_salida_kg=Decimal('26590'),
            cantidad_sap=Decimal('26.590'),
            unidad_sap='MT',
            lote_enviado=False,
            modo_lote='MANUAL_SAP',
        )

        observacion = json.loads(create_mock.call_args.kwargs['OPL_COBSERVACION'])
        self.assertEqual(observacion['peso_salida_kg'], 26590)
        self.assertEqual(observacion['cantidad_sap'], 26.59)
        self.assertEqual(observacion['unidad_sap'], 'MT')
        self.assertFalse(observacion['lote_enviado'])
        self.assertEqual(observacion['modo_lote'], 'MANUAL_SAP')
        self.assertNotIn('lote', observacion)
        self.assertNotIn('BatchNumbers', observacion['payload']['DocumentLines'][0])

    @patch.object(views, 'send_goods_receipt_draft_update_to_sap')
    @patch.object(views, 'usuario_puede_paso_operacion', return_value=True)
    @patch.object(views, 'obtener_paso_activo_operacion')
    @patch.object(views, 'obtener_pasos_operacion_citacion')
    @patch.object(views, '_obtener_citacion_operacion_planta_ajax')
    @patch.object(views, 'usuario_es_operacion_planta', return_value=True)
    def test_endpoint_usa_clasificacion_general_recepcion(
        self,
        _usuario_operacion_mock,
        obtener_citacion_mock,
        pasos_mock,
        paso_activo_mock,
        _permiso_paso_mock,
        enviar_mock,
    ):
        request = self.factory.post(
            '/operacion-planta/38595/sap-recepcion-actualizar/',
            {'empresa_id': 2, '_empresa_id': 2},
        )
        request.user = SimpleNamespace(is_superuser=False)
        obtener_citacion_mock.return_value = (self.citacion, None)
        pasos_mock.return_value = (
            'CUALQUIER FLUJO DE RECEPCION',
            [('Autorizar Salida', ['ASISTENTE DE RECEPCION'])],
        )
        paso_activo_mock.return_value = (
            'Autorizar Salida',
            ['ASISTENTE DE RECEPCION'],
            set(),
        )
        enviar_mock.return_value = {'success': True}

        response = views.ajax_operacion_planta_actualizar_sap_recepcion(request, 38595)

        self.assertEqual(response.status_code, 200)
        enviar_mock.assert_called_once_with(
            self.citacion,
            request.user,
            allow_retry=False,
        )
