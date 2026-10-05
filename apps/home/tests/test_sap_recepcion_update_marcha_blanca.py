import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from requests import HTTPError

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
    @patch.object(views, 'usuario_puede_actualizar_borrador_sap_recepcion', return_value=True)
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


class SapRecepcionEstanqueSbhLoteEndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_superuser=False, username='Asistente_C_D')
        self.citacion = SimpleNamespace(
            pk=38779,
            id=38779,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_ESTANQUE_SBH'),
            ETAPA_ACTUAL=SimpleNamespace(id=8),
            CI_CTIPO='RECEPCION',
        )

    def ejecutar_endpoint(self, *, lote_existente=None, draft_status=None, update_status=None):
        request = self.factory.post(
            '/operacion-planta/38779/sap-recepcion-actualizar/',
            {'empresa_id': 2, '_empresa_id': 2, 'accion': 'generar_lote'},
        )
        request.user = self.user

        citation_qs = MagicMock()
        citation_qs.select_related.return_value.get.return_value = self.citacion
        dato_qs = MagicMock()
        dato_qs.order_by.return_value.first.return_value = lote_existente

        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), \
                patch.object(views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)), \
                patch.object(views, 'obtener_pasos_operacion_citacion', return_value=('ESTANQUE SBH', [])), \
                patch.object(views, 'obtener_paso_activo_operacion', return_value=('Autorizar Salida', [], set())), \
                patch.object(views, 'usuario_puede_actualizar_borrador_sap_recepcion', return_value=True), \
                patch.object(views.CITACION.objects, 'select_for_update', return_value=citation_qs), \
                patch.object(views.DATO_OPERACION.objects, 'filter', return_value=dato_qs), \
                patch.object(views, 'get_goods_receipt_draft_guide_status', return_value=draft_status or {}), \
                patch.object(views, 'get_goods_receipt_draft_update_status', return_value=update_status or {}), \
                patch.object(views, 'generar_lote_recepcion_sap', return_value='LOTE-MP-950105-7-001') as generar_mock, \
                patch.object(views, '_guardar_lote_recepcion') as guardar_mock, \
                patch.object(views, 'send_goods_receipt_draft_update_to_sap') as actualizar_mock:
            response = views.ajax_operacion_planta_actualizar_sap_recepcion(request, 38779)

        return response, generar_mock, guardar_mock, actualizar_mock

    def ejecutar_update_final(self, lote):
        request = self.factory.post(
            '/operacion-planta/38779/sap-recepcion-actualizar/',
            {'empresa_id': 2, '_empresa_id': 2},
        )
        request.user = self.user
        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), \
                patch.object(views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.citacion, None)), \
                patch.object(views, 'obtener_pasos_operacion_citacion', return_value=('ESTANQUE SBH', [])), \
                patch.object(views, 'obtener_paso_activo_operacion', return_value=('Autorizar Salida', [], set())), \
                patch.object(views, 'usuario_puede_actualizar_borrador_sap_recepcion', return_value=True), \
                patch.object(views, 'obtener_lote_recepcion_sap', return_value=lote), \
                patch.object(views, 'send_goods_receipt_draft_update_to_sap', return_value={'success': True}) as actualizar_mock:
            response = views.ajax_operacion_planta_actualizar_sap_recepcion(request, 38779)
        return response, actualizar_mock

    def test_actualizar_sin_lote_es_rechazado_por_backend(self):
        response, actualizar_mock = self.ejecutar_update_final('')

        self.assertEqual(response.status_code, 409)
        self.assertIn('Genere el Lote SAP', json.loads(response.content)['message'])
        actualizar_mock.assert_not_called()

    def test_actualizar_con_lote_utiliza_servicio_existente(self):
        response, actualizar_mock = self.ejecutar_update_final('LOTE-MP-950105-7-001')

        self.assertEqual(response.status_code, 200)
        actualizar_mock.assert_called_once_with(
            self.citacion,
            self.user,
            allow_retry=False,
        )

    def test_genera_y_persiste_lote_con_draft_y_pesaje_salida(self):
        response, generar_mock, guardar_mock, actualizar_mock = self.ejecutar_endpoint(
            draft_status={'sent': True, 'docentry': 3249, 'item_code': '950105'},
            update_status={
                'updated': False,
                'item_code': '950105',
                'peso_salida_kg': 25770,
            },
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['lote'], 'LOTE-MP-950105-7-001')
        self.assertFalse(payload['reused'])
        generar_mock.assert_called_once_with('950105')
        guardar_mock.assert_called_once_with(
            self.citacion,
            self.user,
            'LOTE-MP-950105-7-001',
        )
        actualizar_mock.assert_not_called()

    def test_segundo_click_reutiliza_lote_existente(self):
        existente = SimpleNamespace(DO_CVALOR='LOTE-MP-950105-7-001')
        response, generar_mock, guardar_mock, _ = self.ejecutar_endpoint(lote_existente=existente)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['reused'])
        self.assertEqual(payload['lote'], 'LOTE-MP-950105-7-001')
        generar_mock.assert_not_called()
        guardar_mock.assert_not_called()

    def test_sin_pesaje_salida_bloquea_generacion(self):
        response, generar_mock, guardar_mock, _ = self.ejecutar_endpoint(
            draft_status={'sent': True, 'docentry': 3249, 'item_code': '950105'},
            update_status={'updated': False, 'peso_salida_kg': None},
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 409)
        self.assertIn('Pesaje Salida', payload['message'])
        generar_mock.assert_not_called()
        guardar_mock.assert_not_called()

    def test_sin_draft_con_docentry_bloquea_generacion(self):
        response, generar_mock, guardar_mock, _ = self.ejecutar_endpoint(
            draft_status={'sent': False, 'docentry': ''},
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 409)
        self.assertIn('Draft SAP con DocEntry', payload['message'])
        generar_mock.assert_not_called()
        guardar_mock.assert_not_called()

    def test_otra_secuencia_no_puede_generar_lote(self):
        self.citacion.SC_NID = SimpleNamespace(SE_CCODIGO='RECEPCION_NEW_JERSEY')
        response, generar_mock, guardar_mock, _ = self.ejecutar_endpoint()
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertIn('solo aplica a Recepción Estanque SBH', payload['message'])
        generar_mock.assert_not_called()
        guardar_mock.assert_not_called()
    @patch.object(sap_recepcion.DATO_OPERACION.objects, 'update_or_create')
    @patch.object(sap_recepcion.CAMPO.objects, 'filter')
    def test_helper_canonico_persiste_en_dato_operacion(self, campo_filter_mock, update_mock):
        campo = SimpleNamespace(id=901)
        campo_filter_mock.return_value.first.return_value = campo

        sap_recepcion._guardar_lote_recepcion(
            self.citacion,
            self.user,
            'LOTE-MP-950105-7-001',
        )

        update_mock.assert_called_once()
        llamada = update_mock.call_args
        self.assertIs(llamada.kwargs['CI_NID'], self.citacion)
        self.assertIs(llamada.kwargs['SC_NID'], self.citacion.SC_NID)
        self.assertIs(llamada.kwargs['CAMP_NID'], campo)
        self.assertEqual(llamada.kwargs['defaults']['DO_CVALOR'], 'LOTE-MP-950105-7-001')

class SapRecepcionEstanqueSbhOrdenFinalTests(TestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(
            pk=38782,
            id=38782,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            PL_NID=SimpleNamespace(id=1299),
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_ESTANQUE_SBH'),
            ETAPA_ACTUAL=SimpleNamespace(id=8),
            CI_CTIPO='RECEPCION',
        )
        self.usuario = SimpleNamespace(username='Asistente_Recepcion')
        self.draft_status = {
            'sent': True,
            'docentry': 3540,
            'docnum': 13188,
            'item_code': '600030',
            'request_json': {
                'DocumentLines': [{
                    'LineNum': 0,
                    'ItemCode': '600030',
                    'WarehouseCode': 'TK10',
                }],
            },
        }

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status', return_value={})
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_payload_estanque_sbh_incluye_lote_y_cantidad_sap_normalizada(
        self,
        draft_status_mock,
        _status_mock,
    ):
        draft_status_mock.return_value = self.draft_status

        preview = sap_recepcion.build_goods_receipt_draft_update_with_salida_lote(
            self.citacion,
            Decimal('27300'),
            'LOTE-MP-600030-8-001',
        )

        self.assertFalse(preview['errors'])
        linea = preview['payload']['DocumentLines'][0]
        self.assertEqual(linea['Quantity'], 27.3)
        self.assertEqual(linea['WarehouseCode'], 'TK10')
        self.assertEqual(
            linea['BatchNumbers'],
            [{
                'BatchNumber': 'LOTE-MP-600030-8-001',
                'Quantity': 27.3,
                'BaseLineNumber': 0,
                'ItemCode': '600030',
            }],
        )
        self.assertTrue(preview['source_data']['lote_enviado'])
        self.assertEqual(preview['source_data']['modo_lote'], 'AUTOMATICO_TERRAVIEW')

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status', return_value={})
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_payload_estanque_sbh_rechaza_actualizacion_sin_lote(
        self,
        draft_status_mock,
        _status_mock,
    ):
        draft_status_mock.return_value = self.draft_status

        preview = sap_recepcion.build_goods_receipt_draft_update_with_salida_lote(
            self.citacion,
            Decimal('27300'),
            '',
        )

        self.assertFalse(preview['payload'])
        self.assertIn('No se pudo obtener lote SAP', preview['errors'][0])

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, 'generar_lote_recepcion_sap')
    @patch.object(sap_recepcion, 'obtener_lote_recepcion_sap', return_value='LOTE-MP-600030-8-001')
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('27300'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status', return_value={})
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_preview_reutiliza_lote_persistido_sin_generar_otro(
        self,
        draft_status_mock,
        _status_mock,
        _peso_mock,
        _lote_mock,
        generar_mock,
    ):
        draft_status_mock.return_value = self.draft_status

        preview = sap_recepcion.build_goods_receipt_draft_update_preview(self.citacion)

        generar_mock.assert_not_called()
        self.assertEqual(
            preview['payload']['DocumentLines'][0]['BatchNumbers'][0]['BatchNumber'],
            'LOTE-MP-600030-8-001',
        )

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_parse_log_json')
    @patch.object(sap_recepcion, '_latest_update_recepcion_log')
    @patch.object(sap_recepcion, 'obtener_lote_recepcion_sap', return_value='')
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('27300'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_update_antiguo_sin_lote_queda_incompleto_y_recuperable(
        self,
        draft_status_mock,
        _peso_mock,
        _lote_mock,
        latest_log_mock,
        parse_log_mock,
    ):
        draft_status_mock.return_value = self.draft_status
        latest_log_mock.return_value = SimpleNamespace(
            OPL_CPASO=sap_recepcion.LOG_UPDATE_SAP_RECEPCION_ENVIO,
            OPL_FFECHAREGISTRO=timezone.now(),
            US_NID=self.usuario,
        )
        parse_log_mock.return_value = {
            'success': True,
            'docentry': 3540,
            'docnum': 13188,
            'item_code': '600030',
            'peso_salida_kg': 27300,
            'cantidad_sap': 27.3,
            'lote_enviado': False,
            'modo_lote': 'MANUAL_SAP',
            'payload': {'DocumentLines': [{'Quantity': 27.3}]},
        }

        estado = sap_recepcion.get_goods_receipt_draft_update_status(self.citacion)

        self.assertFalse(estado['updated'])
        self.assertFalse(estado['is_error'])
        self.assertEqual(estado['estado'], 'PENDIENTE_LOTE')
        self.assertIn('mismo Borrador SAP', estado['resumen_mensaje'])

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_parse_log_json')
    @patch.object(sap_recepcion, '_latest_update_recepcion_log')
    @patch.object(
        sap_recepcion,
        'obtener_lote_recepcion_sap',
        return_value='LOTE-MP-600030-8-001',
    )
    @patch.object(sap_recepcion, 'get_exit_weight_from_citation', return_value=Decimal('27300'))
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_guide_status')
    def test_update_ok_con_lote_persistido_habilita_continuar(
        self,
        draft_status_mock,
        _peso_mock,
        _lote_mock,
        latest_log_mock,
        parse_log_mock,
    ):
        draft_status_mock.return_value = self.draft_status
        latest_log_mock.return_value = SimpleNamespace(
            OPL_CPASO=sap_recepcion.LOG_UPDATE_SAP_RECEPCION_ENVIO,
            OPL_FFECHAREGISTRO=timezone.now(),
            US_NID=self.usuario,
        )
        parse_log_mock.return_value = {
            'success': True,
            'docentry': 3540,
            'docnum': 13188,
            'item_code': '600030',
            'lote': 'LOTE-MP-600030-8-001',
            'lote_enviado': True,
            'modo_lote': 'AUTOMATICO_TERRAVIEW',
            'peso_salida_kg': 27300,
            'cantidad_sap': 27.3,
            'payload': {
                'DocumentLines': [{
                    'Quantity': 27.3,
                    'BatchNumbers': [{
                        'BatchNumber': 'LOTE-MP-600030-8-001',
                        'Quantity': 27.3,
                    }],
                }],
            },
        }

        estado = sap_recepcion.get_goods_receipt_draft_update_status(self.citacion)

        self.assertTrue(estado['updated'])
        self.assertFalse(estado['is_error'])
        self.assertEqual(estado['estado'], 'OK')
        self.assertTrue(estado['lote_enviado'])

    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    @patch.object(sap_recepcion, '_extract_sap_error', return_value={'status_code': 500, 'error': 'rechazo'})
    @patch.object(sap_recepcion, '_registrar_log_update_sap_recepcion')
    @patch.object(sap_recepcion, '_guardar_lote_recepcion')
    @patch.object(sap_recepcion, 'generar_lote_recepcion_sap')
    @patch.object(sap_recepcion, 'SapServiceLayerClient')
    @patch.object(sap_recepcion, 'load_config')
    @patch.object(sap_recepcion, 'build_goods_receipt_draft_update_preview')
    @patch.object(sap_recepcion, 'get_goods_receipt_draft_update_status')
    def test_falla_sap_conserva_lote_y_permita_reintentar_mismo_draft(
        self,
        status_mock,
        preview_mock,
        config_mock,
        client_class_mock,
        generar_mock,
        guardar_mock,
        _log_mock,
        _error_mock,
    ):
        status_mock.side_effect = [
            {'updated': False},
            {'updated': False, 'is_error': True},
            {'updated': False, 'is_error': True},
            {'updated': True},
        ]
        preview_mock.return_value = {
            'payload': {
                'DocumentLines': [{
                    'LineNum': 0,
                    'ItemCode': '600030',
                    'Quantity': 27.3,
                    'BatchNumbers': [{
                        'BatchNumber': 'LOTE-MP-600030-8-001',
                        'Quantity': 27.3,
                    }],
                }],
            },
            'errors': [],
            'source_data': {
                'draft_docentry': 3540,
                'draft_docnum': 13188,
                'item_code': '600030',
                'lote': 'LOTE-MP-600030-8-001',
                'peso_salida_kg': 27300,
                'cantidad_sap': 27.3,
                'unidad_sap': 'MT',
                'lote_enviado': True,
                'modo_lote': 'AUTOMATICO_TERRAVIEW',
            },
        }
        config_mock.return_value = SimpleNamespace(company_db='SBO_TST_SBH_USD')
        client = client_class_mock.return_value
        client.patch_draft.side_effect = [
            HTTPError('rechazo SAP'),
            {'status_code': 204, 'data': {}},
        ]

        primer_intento = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
        )
        segundo_intento = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
            self.citacion,
            self.usuario,
        )

        self.assertFalse(primer_intento['success'])
        self.assertTrue(segundo_intento['success'])
        self.assertEqual(client.patch_draft.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in client.patch_draft.call_args_list],
            [3540, 3540],
        )
        generar_mock.assert_not_called()
        self.assertEqual(guardar_mock.call_count, 2)
        for call in guardar_mock.call_args_list:
            self.assertEqual(call.args[2], 'LOTE-MP-600030-8-001')

    def test_template_muestra_lote_antes_de_actualizar_y_bloquea_sin_lote(self):
        template = Path(
            'apps/templates/home/CITACION/operacion_planta.html'
        ).read_text(encoding='utf-8')
        inicio = template.index(
            '<div class="op-sap-draft-panel mb-3 operacion-sap-recepcion-update-box"'
        )
        fin = template.index(
            '<div class="op-sap-draft-panel mb-3 operacion-sap-despacho-update-box"',
            inicio,
        )
        seccion = template[inicio:fin]

        self.assertLess(
            seccion.index('sap-info-section-title">Lote SAP'),
            seccion.index('btn-actualizar-sap-recepcion'),
        )
        self.assertIn(
            'Genere el Lote SAP antes de actualizar el borrador.',
            seccion,
        )
        self.assertIn(
            'and not paso.lote_sap_recepcion %}disabled aria-disabled="true"',
            seccion,
        )
