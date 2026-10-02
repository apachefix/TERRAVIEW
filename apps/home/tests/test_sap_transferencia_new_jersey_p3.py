"""Pruebas de StockTransfer New Jersey P3; ninguna contacta SAP real."""

import json
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CAMPO, CITACION, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION,
    OPERACION_NEW_JERSEY_PROCESO, OPERACION_PLANTA_LOG,
)
from apps.home.sap_recepcion_new_jersey import (
    CAMPO_LOTE_SAP_NEW_JERSEY_P1,
    LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1,
)
from apps.home.sap_solicitud_new_jersey_p2 import LOG_SOLICITUD
from apps.home.sap_transferencia_new_jersey_p3 import (
    CAMPO_PESO_REAL, CAMPO_TK_FINAL, FORMULA_PESO_REAL, LOG_TRANSFERENCIA,
    aplicar_overrides_qa_pesaje_new_jersey_p3,
    build_stock_transfer_new_jersey_p3,
    calcular_y_persistir_peso_real_new_jersey_p3,
    contexto_transferencia_new_jersey_p3,
    destino_vigente_p3,
    estado_transferencia_new_jersey_p3,
    guardar_destino_final_p3,
    guardar_overrides_qa_pesaje_new_jersey_p3,
    obtener_peso_real_new_jersey_p3_para_sap,
    resolver_pesajes_new_jersey_p3,
    send_stock_transfer_new_jersey_p3_to_sap,
)


@override_settings(
    BODEGA_VIRTUAL_NEW_JERSEY='EPSBH',
    SAP_RECEPCION_PREVIEW_ENABLED=True,
    QA_PESAJE=True,
)
class StockTransferNewJerseyP3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .test_new_jersey_p3 import NewJerseyProceso3Tests
        NewJerseyProceso3Tests.setUpTestData.__func__(cls)

    def _crear_operacion_lista_p3(self, *args):
        from .test_new_jersey_p3 import NewJerseyProceso3Tests
        return NewJerseyProceso3Tests._crear_operacion_lista_p3(self, *args)

    def setUp(self):
        self.p1, self.p2, self.operacion = self._crear_operacion_lista_p3(
            '65688', 'MDFGD4533',
        )
        self.p3 = CITACION.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            PL_NID=self.planificacion_origen, SC_NID=self.secuencia_p3,
            PRO_NID=self.proveedor, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=2,
            CI_CTIPO='RECEPCION', CI_CESTADO='EN PROCESO',
            CI_CTIPODOCUMENTO='GD', CI_CNUMERODOCUMENTO='65688',
            CI_NID_REF=self.p2.id, CI_BHABILITADO=True,
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=self.p3, EP_NID=self.empresa, US_NID=self.usuario,
            CDO_CORIGEN='new_jersey_p3', CDO_CGUIA='65688',
            CDO_CBL_CONTENEDOR='MDFGD4533', CDO_CBL='MDFGD4533',
            CDO_CCODIGO_SAP='950105',
            CDO_CINSUMO='ACIDOS GRASOS MARINOS EWOS',
            CDO_CPEDIDO_SAP='10001091', CDO_CDOCENTRY='6880',
            CDO_CSAP_OPOR_ID='6880', CDO_CTIPO_RECEPCION='NACIONAL',
            CDO_CALMACEN_DESTINO='SBH', CDO_CESTANQUE_DESTINO='TK08',
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=self.operacion, CI_NID=self.p3, EP_NID=self.empresa,
            US_NID=self.usuario,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO,
        )
        self._crear_ticket(self.p1, 'ENT', 40000, 'P1-ENT', 'CAMION-P1')
        self._crear_ticket(self.p1, 'SAL', 15000, 'P1-SAL', 'CAMION-P1')
        self._crear_ticket(self.p3, 'ENT', 13000, 'P3-ENT', 'CAMION-P3')
        self._crear_ticket(self.p3, 'SAL', 18000, 'P3-SAL', 'CAMION-P3')
        for paso in ('Pesaje Entrada', 'Carga / Descarga', 'Pesaje Salida'):
            OPERACION_PLANTA_LOG.objects.create(
                US_NID=self.usuario, EP_NID=self.empresa,
                PL_NID=self.planificacion_origen, CI_NID=self.p3,
                OPL_CPASO=paso, OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )
        self._crear_lote_p1()
        self._crear_ingreso_p1()
        self._crear_solicitud_p2()

    def _campo(self, codigo, etiqueta):
        return CAMPO.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, CA_CCODIGO=codigo,
            CA_CTIPO='TEXTO', CA_CETIQUETA=etiqueta,
            CA_CPLACEMARK=etiqueta, CA_BHABILITADO=True,
        )

    def _crear_ticket(self, citacion, tipo, peso, folio, patente):
        campo = self._campo(f'OP_TICKET_PESAJE_{tipo}', f'Ticket {tipo} {citacion.id}')
        return DATO_OPERACION.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SC_NID=citacion.SC_NID,
            ET_NID=self.etapa_p3, CAMP_NID=campo, CI_NID=citacion,
            DO_NPESO=peso, DO_FFECHAREGISTRO=timezone.now(),
            DO_CVALOR=json.dumps({
                'folio': folio, 'peso_neto': peso, 'patente': patente,
                'tipo_ticket': tipo, 'fecha_hora_ticket': '2026-09-29T12:00:00',
            }),
        )

    def _crear_lote_p1(self):
        campo = self._campo(CAMPO_LOTE_SAP_NEW_JERSEY_P1, 'Lote P1')
        DATO_OPERACION.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SC_NID=self.p1.SC_NID,
            ET_NID=self.etapa_p3, CAMP_NID=campo, CI_NID=self.p1,
            DO_FFECHAREGISTRO=timezone.now(),
            DO_CVALOR=json.dumps({
                'citacion': self.p1.id, 'item_code': '950105',
                'batch_number': 'LOTE-PT-950105-768-01',
                'correlativo': 768, 'numero_linea': 1, 'sufijo': '01',
            }),
        )

    def _crear_ingreso_p1(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            PL_NID=self.planificacion_origen, CI_NID=self.p1,
            OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'success': True, 'outcome_unknown': False,
                'response': {'DocEntry': 20355, 'DocNum': 13186},
                'payload': {'DocumentLines': [{
                    'ItemCode': '950105', 'WarehouseCode': 'EPSBH',
                    'Quantity': 24,
                    'BatchNumbers': [{
                        'BatchNumber': 'LOTE-PT-950105-768-01', 'Quantity': 24,
                    }],
                }]},
            }),
        )

    def _crear_solicitud_p2(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            PL_NID=self.planificacion_origen, CI_NID=self.p2,
            OPL_CPASO=LOG_SOLICITUD,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'accion': LOG_SOLICITUD, 'estado': 'CREADO',
                'endpoint': '/InventoryTransferRequests',
                'origen': 'EPSBH', 'destino': 'TK08',
                'item_code': '950105', 'quantity_mt': 24,
                'response': {'DocEntry': 450, 'DocNum': 10},
            }),
        )

    def sap_mocks(self, duplicate=None, stock='24'):
        stack = ExitStack()
        prefix = 'apps.home.sap_transferencia_new_jersey_p3.'
        stack.enter_context(patch(prefix + 'nj_p2.estanques_validos_p2',
                                  return_value=('TK05', 'TK08')))
        stack.enter_context(patch(prefix + '_schema_sap', return_value='SAP_TEST'))
        stack.enter_context(patch(prefix + 'consultar_ingreso_virtual_new_jersey_p1',
                                  return_value={
                                      'docentry': 20355, 'docnum': 13186,
                                      'item_code': '950105', 'warehouse': 'EPSBH',
                                      'quantity': Decimal('24'),
                                  }))
        stack.enter_context(patch(prefix + 'consultar_articulo_y_bodegas_prosesa',
                                  return_value={
                                      'unit': 'Toneladas Metricas',
                                      'batch_managed': 'Y',
                                      'origin_stock_total': Decimal('24'),
                                  }))
        stack.enter_context(patch(prefix + 'consultar_stock_lote_prosesa',
                                  return_value={
                                      'stock': Decimal(stock), 'available': Decimal(stock),
                                      'committed': Decimal('0'),
                                  }))
        stack.enter_context(patch(prefix + 'obtener_fecha_sistema_sap',
                                  return_value=date(2026, 9, 29).isoformat()))
        stack.enter_context(patch(prefix + 'buscar_transferencia_sap_new_jersey_p3',
                                  return_value=duplicate))
        return stack

    def _calcular(self):
        return calcular_y_persistir_peso_real_new_jersey_p3(self.p3, self.usuario)

    def test_recupera_pesajes_p1_p3_y_calcula_formula_propia(self):
        pesajes = resolver_pesajes_new_jersey_p3(self.p3)
        self.assertEqual(pesajes['p1_ent']['peso_efectivo'], 40000)
        self.assertEqual(pesajes['p3_sal']['peso_efectivo'], 18000)
        dato, actualizado = self._calcular()
        self.assertTrue(actualizado)
        self.assertEqual(dato.DO_NPESO, 20000)
        metadata = json.loads(dato.DO_CVALOR)
        self.assertEqual(metadata['formula'], FORMULA_PESO_REAL)
        self.assertEqual(metadata['peso_real_mt'], 20.0)
        self.assertEqual(set(metadata['fuentes_pesajes']), {'p1_ent', 'p1_sal', 'p3_ent', 'p3_sal'})

    def test_qa_override_es_trazable_y_no_modifica_ticket(self):
        original = DATO_OPERACION.objects.get(
            CI_NID=self.p1, CAMP_NID__CA_CCODIGO='OP_TICKET_PESAJE_ENT',
        )
        guardar_overrides_qa_pesaje_new_jersey_p3(
            self.p3, {'p1_ent': '41000'}, self.usuario,
        )
        pesajes = resolver_pesajes_new_jersey_p3(self.p3)
        original.refresh_from_db()
        self.assertEqual(original.DO_NPESO, 40000)
        self.assertEqual(pesajes['p1_ent']['peso_efectivo'], 41000)
        self.assertEqual(pesajes['p1_ent']['origen_peso'], 'QA_OVERRIDE')
        dato, _ = self._calcular()
        self.assertEqual(dato.DO_NPESO, 21000)

    @override_settings(QA_PESAJE=False)
    def test_qa_deshabilitado_ignora_override_y_rechaza_guardado(self):
        with self.assertRaises(PermissionError):
            guardar_overrides_qa_pesaje_new_jersey_p3(
                self.p3, {'p1_ent': '41000'}, self.usuario,
            )
        self.assertEqual(resolver_pesajes_new_jersey_p3(self.p3)['p1_ent']['peso_efectivo'], 40000)

    def test_aplicar_qa_actualiza_peso_usado_fuente_y_permite_limpiar_override(self):
        original = DATO_OPERACION.objects.get(
            CI_NID=self.p1, CAMP_NID__CA_CCODIGO='OP_TICKET_PESAJE_ENT',
        )
        aplicado = aplicar_overrides_qa_pesaje_new_jersey_p3(
            self.p3, {'p1_ent': '41000'}, self.usuario,
        )
        fila = next(item for item in aplicado['pesajes'] if item['clave'] == 'p1_ent')
        original.refresh_from_db()
        self.assertEqual(original.DO_NPESO, 40000)
        self.assertEqual(fila['peso_original'], 40000)
        self.assertEqual(fila['peso_efectivo'], 41000)
        self.assertEqual(fila['fuente'], 'QA')
        self.assertEqual(aplicado['peso_conjunto_cargado_kg'], 26000)
        limpiado = aplicar_overrides_qa_pesaje_new_jersey_p3(
            self.p3, {'p1_ent': ''}, self.usuario,
        )
        fila_limpia = next(item for item in limpiado['pesajes'] if item['clave'] == 'p1_ent')
        self.assertEqual(fila_limpia['peso_efectivo'], 40000)
        self.assertEqual(fila_limpia['fuente'], 'TICKET')

    def test_qa_valida_decimal_finito_positivo_y_respeta_kg_entero(self):
        for valor in ('NaN', 'Infinity', '0', '-1', '41000.5'):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                guardar_overrides_qa_pesaje_new_jersey_p3(
                    self.p3, {'p1_ent': valor}, self.usuario,
                )
        guardar_overrides_qa_pesaje_new_jersey_p3(
            self.p3, {'p1_ent': '41000.0'}, self.usuario,
        )
        self.assertEqual(
            resolver_pesajes_new_jersey_p3(self.p3)['p1_ent']['peso_efectivo'],
            41000,
        )

    def test_cambiar_qa_invalida_peso_previo_y_bloquea_stocktransfer(self):
        dato, _ = self._calcular()
        aplicar_overrides_qa_pesaje_new_jersey_p3(
            self.p3, {'p1_ent': '41000'}, self.usuario,
        )
        dato.refresh_from_db()
        self.assertTrue(json.loads(dato.DO_CVALOR)['invalidado'])
        with self.assertRaisesMessage(ValueError, 'debe recalcular'):
            obtener_peso_real_new_jersey_p3_para_sap(self.p3)
        preview = build_stock_transfer_new_jersey_p3(self.p3)
        self.assertFalse(preview['ready_for_post'])
        self.assertIn('debe recalcular', ' '.join(preview['errors']))

    def test_endpoint_aplicar_qa_es_independiente_del_calculo_final(self):
        request = RequestFactory().post(reverse(
            'ajax_operacion_planta_aplicar_pesos_qa_new_jersey_p3',
            args=[self.p3.id],
        ), {'p1_ent': '41000', 'p1_sal': '', 'p3_ent': '', 'p3_sal': ''})
        request.user = self.usuario
        comunes = (
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(views, 'usuario_es_asistente_recepcion', return_value=True),
            patch.object(views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.p3, None)),
            patch.object(views, '_recargar_citacion_bloqueada_operacion', return_value=self.p3),
            patch.object(views, 'obtener_paso_activo_operacion', return_value=(views.PASO_AUTORIZAR_SALIDA, None)),
        )
        with ExitStack() as stack:
            for contexto in comunes:
                stack.enter_context(contexto)
            response = views.ajax_operacion_planta_aplicar_pesos_qa_new_jersey_p3(
                request, self.p3.id,
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['actualizado'])
        self.assertFalse(DATO_OPERACION.objects.filter(
            CI_NID=self.p3, CAMP_NID__CA_CCODIGO=CAMPO_PESO_REAL,
        ).exists())
        self.assertEqual(
            next(item for item in payload['pesajes'] if item['clave'] == 'p1_ent')['fuente'],
            'QA',
        )

    def test_calcular_rechaza_overrides_no_aplicados(self):
        request = RequestFactory().post(reverse(
            'ajax_operacion_planta_calcular_peso_real_new_jersey_p3',
            args=[self.p3.id],
        ), {'p1_ent': '41000'})
        request.user = self.usuario
        with patch.object(views, 'usuario_es_operacion_planta', return_value=True), patch.object(
            views, 'usuario_es_asistente_recepcion', return_value=True,
        ), patch.object(
            views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.p3, None),
        ), patch.object(
            views, 'obtener_paso_activo_operacion', return_value=(views.PASO_AUTORIZAR_SALIDA, None),
        ):
            response = views.ajax_operacion_planta_calcular_peso_real_new_jersey_p3(
                request, self.p3.id,
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Aplicar pesos QA', json.loads(response.content)['message'])

    def test_tk_heredado_y_cambio_p3_no_reescribe_p1_p2(self):
        self.assertEqual(destino_vigente_p3(self.p3), 'TK08')
        with patch('apps.home.sap_transferencia_new_jersey_p3.nj_p2.estanques_validos_p2',
                   return_value=('TK05', 'TK08')):
            resultado = guardar_destino_final_p3(self.p3, self.usuario, 'TK05')
        self.assertTrue(resultado['changed'])
        self.assertEqual(destino_vigente_p3(self.p3), 'TK05')
        self.p1.detalle_operacional.refresh_from_db()
        self.p2.detalle_operacional.refresh_from_db()
        self.assertEqual(self.p1.detalle_operacional.CDO_CESTANQUE_DESTINO, 'TK08')
        self.assertEqual(self.p2.detalle_operacional.CDO_CESTANQUE_DESTINO, 'TK08')
        metadata = json.loads(DATO_OPERACION.objects.get(
            CI_NID=self.p3, CAMP_NID__CA_CCODIGO=CAMPO_TK_FINAL,
        ).DO_CVALOR)
        self.assertEqual(metadata['tk_p1'], 'TK08')
        self.assertEqual(metadata['tk_p2_solicitado'], 'TK08')
        self.assertEqual(metadata['tk_p3_final'], 'TK05')

    def test_builder_usa_peso_real_tk_editado_lote_existente_y_stocktransfer(self):
        self._calcular()
        with patch('apps.home.sap_transferencia_new_jersey_p3.nj_p2.estanques_validos_p2',
                   return_value=('TK05', 'TK08')):
            guardar_destino_final_p3(self.p3, self.usuario, 'TK05')
        with self.sap_mocks():
            preview = build_stock_transfer_new_jersey_p3(self.p3)
        self.assertTrue(preview['ready_for_post'], preview['errors'])
        self.assertEqual(preview['endpoint'], '/StockTransfers')
        self.assertEqual(preview['source_data']['solicitud_p2_docentry'], 450)
        self.assertEqual(preview['source_data']['cantidad_provisional_p2_mt'], 24)
        payload = preview['payload']
        self.assertEqual(payload['FromWarehouse'], 'EPSBH')
        self.assertEqual(payload['ToWarehouse'], 'TK05')
        self.assertEqual(payload['Reference2'], str(self.p3.id))
        linea = payload['StockTransferLines'][0]
        self.assertEqual(linea['ItemCode'], '950105')
        self.assertEqual(linea['Quantity'], 20)
        self.assertEqual(linea['WarehouseCode'], 'TK05')
        self.assertEqual(linea['BatchNumbers'], [{
            'BatchNumber': 'LOTE-PT-950105-768-01', 'Quantity': 20,
        }])
        self.assertNotEqual(linea['Quantity'], 24)

    def test_falta_ticket_y_peso_inconsistente_bloquean_builder(self):
        DATO_OPERACION.objects.filter(
            CI_NID=self.p3, CAMP_NID__CA_CCODIGO='OP_TICKET_PESAJE_SAL',
        ).delete()
        with self.sap_mocks():
            preview = build_stock_transfer_new_jersey_p3(self.p3)
        self.assertFalse(preview['ready_for_post'])
        self.assertIn('Falta P3', ' '.join(preview['errors']))
        self._crear_ticket(self.p3, 'SAL', 12000, 'P3-SAL-2', 'CAMION-P3')
        with self.assertRaisesMessage(ValueError, 'Pesajes P3 inconsistentes'):
            self._calcular()

    def test_stock_insuficiente_y_duplicado_bloquean(self):
        self._calcular()
        with self.sap_mocks(stock='19'):
            bajo = build_stock_transfer_new_jersey_p3(self.p3)
        self.assertFalse(bajo['ready_for_post'])
        self.assertIn('Stock disponible', ' '.join(bajo['errors']))
        duplicate = {'docentry': 91, 'docnum': 92, 'origen': 'EPSBH', 'destino': 'TK08'}
        with self.sap_mocks(duplicate=duplicate):
            duplicado = build_stock_transfer_new_jersey_p3(self.p3)
        self.assertFalse(duplicado['ready_for_post'])
        self.assertTrue(duplicado['status']['creada'])

    def test_sender_persiste_docentry_bloquea_tk_y_no_duplica(self):
        self._calcular()
        prefix = 'apps.home.sap_transferencia_new_jersey_p3.'
        with self.sap_mocks(), patch(prefix + 'load_config',
            return_value=SimpleNamespace(company_db='SAP_TEST')), patch(
            prefix + 'SapServiceLayerClient') as client_type:
            client = client_type.return_value
            client.post_stock_transfer.return_value = {
                'data': {'DocEntry': 91, 'DocNum': 92}, 'status_code': 201,
            }
            resultado = send_stock_transfer_new_jersey_p3_to_sap(self.p3, self.usuario)
            segundo = send_stock_transfer_new_jersey_p3_to_sap(self.p3, self.usuario)
        self.assertTrue(resultado['success'])
        self.assertFalse(segundo['success'])
        self.assertEqual(client.post_stock_transfer.call_count, 1)
        self.assertEqual(estado_transferencia_new_jersey_p3(self.p3)['docentry'], 91)
        self.assertTrue(DATO_OPERACION.objects.filter(
            CI_NID=self.p3, CAMP_NID__CA_CCODIGO='NJ_P3_STOCK_TRANSFER_SAP',
        ).exists())
        with patch(prefix + 'nj_p2.estanques_validos_p2', return_value=('TK05', 'TK08')):
            with self.assertRaisesMessage(ValueError, 'no puede cambiarse'):
                guardar_destino_final_p3(self.p3, self.usuario, 'TK05')
        with self.assertRaisesMessage(ValueError, 'no pueden modificarse'):
            guardar_overrides_qa_pesaje_new_jersey_p3(
                self.p3, {'p1_ent': '41000'}, self.usuario,
            )

    def test_timeout_deja_estado_incierto_y_no_reintenta(self):
        self._calcular()
        prefix = 'apps.home.sap_transferencia_new_jersey_p3.'
        with self.sap_mocks(), patch(prefix + 'load_config',
            return_value=SimpleNamespace(company_db='SAP_TEST')), patch(
            prefix + 'SapServiceLayerClient') as client_type:
            client_type.return_value.post_stock_transfer.side_effect = TimeoutError('timeout')
            primero = send_stock_transfer_new_jersey_p3_to_sap(self.p3, self.usuario)
            segundo = send_stock_transfer_new_jersey_p3_to_sap(self.p3, self.usuario)
        self.assertEqual(primero['status']['estado'], 'INCIERTO')
        self.assertFalse(segundo['success'])
        self.assertEqual(client_type.return_value.post_stock_transfer.call_count, 1)

    def test_preview_es_solo_lectura_y_respeta_feature_flag(self):
        self._calcular()
        request = RequestFactory().post(reverse(
            'ajax_operacion_planta_preview_transferencia_sap_new_jersey_p3',
            args=[self.p3.id],
        ))
        request.user = self.usuario
        with self.sap_mocks(), patch.object(views, 'usuario_es_operacion_planta', return_value=True), patch.object(
            views, 'usuario_es_asistente_recepcion', return_value=True), patch.object(
            views, '_obtener_citacion_operacion_planta_ajax', return_value=(self.p3, None)), patch.object(
            views, 'obtener_paso_activo_operacion', return_value=(views.PASO_AUTORIZAR_SALIDA, None)), patch(
            'apps.home.sap_transferencia_new_jersey_p3.SapServiceLayerClient') as client:
            response = views.ajax_operacion_planta_preview_transferencia_sap_new_jersey_p3(
                request, self.p3.id,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['read_only'])
        client.assert_not_called()
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False):
            response = views.ajax_operacion_planta_preview_transferencia_sap_new_jersey_p3(
                request, self.p3.id,
            )
        self.assertEqual(response.status_code, 404)

    def test_autorizar_salida_exige_transferencia_y_luego_avanza(self):
        request = RequestFactory().post('/autorizar/', {
            'recepcion_conforme': 'SI', 'observacion_descarga': 'ok',
        })
        request.user = self.usuario
        comunes = (
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(views, 'usuario_es_asistente_recepcion', return_value=True),
            patch.object(views, '_obtener_citacion_operacion_planta_ajax',
                         return_value=(self.p3, None)),
            patch.object(views, 'obtener_peso_real_new_jersey_p3_para_sap',
                         return_value=20000),
        )
        with ExitStack() as stack:
            for contexto in comunes:
                stack.enter_context(contexto)
            stack.enter_context(patch.object(
                views, 'estado_transferencia_new_jersey_p3',
                return_value={'creada': False, 'bloqueada': False, 'estado': 'NO_CREADA'},
            ))
            bloqueada = views.ajax_operacion_planta_autorizar_salida(request, self.p3.id)
        self.assertEqual(bloqueada.status_code, 409)
        self.assertIn('transferencia SAP final', json.loads(bloqueada.content)['message'])

        with ExitStack() as stack:
            for contexto in comunes:
                stack.enter_context(contexto)
            stack.enter_context(patch.object(
                views, 'estado_transferencia_new_jersey_p3',
                return_value={'creada': True, 'bloqueada': True, 'estado': 'CREADO'},
            ))
            stack.enter_context(patch.object(
                views, 'obtener_paso_activo_operacion',
                return_value=(views.PASO_AUTORIZAR_SALIDA, ['ASISTENTE DE RECEPCION'], None),
            ))
            stack.enter_context(patch.object(views, 'usuario_puede_paso_operacion', return_value=True))
            stack.enter_context(patch.object(views, '_empresa_timbre_recepcion', return_value=''))
            stack.enter_context(patch.object(views, 'aplica_timbraje_recepcion', return_value=False))
            permitida = views.ajax_operacion_planta_autorizar_salida(request, self.p3.id)
        self.assertEqual(permitida.status_code, 200)
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.p3, OPL_CPASO=views.PASO_AUTORIZAR_SALIDA,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).exists())

    def test_otro_flujo_no_es_aplicable_y_ui_esta_aislada(self):
        preview = build_stock_transfer_new_jersey_p3(self.p1)
        self.assertFalse(preview['ready_for_post'])
        from pathlib import Path
        html = Path('apps/templates/home/CITACION/operacion_planta.html').read_text(encoding='utf-8')
        self.assertIn('operacion-transferencia-sap-new-jersey-p3-box', html)
        self.assertIn('{% if paso.es_new_jersey_p3 %}', html)
        self.assertIn('Previsualizar Transferencia SAP', html)
        self.assertIn('Crear StockTransfer SAP', html)
        self.assertIn('btn-aplicar-pesos-qa-new-jersey-p3', html)
        self.assertIn('PESO CONJUNTO CARGADO P1', html)
        self.assertIn('PESO CONTENEDOR VACIO P3', html)
        self.assertIn('PESO REAL DEL PRODUCTO', html)
        self.assertIn('(P1 Entrada - P1 Salida) - (P3 Salida - P3 Entrada)', html)
        self.assertIn('{{ pesaje.fuente }}', html)
        self.assertIn('{% if nj.qa_habilitado and not transferencia.status.bloqueada %}', html)
        self.assertNotIn('{% if nj.qa_habilitado and paso.activo and paso.puede_editar and not transferencia.status.bloqueada %}', html)
        self.assertIn('btn-aplicar-pesos-qa-new-jersey-p3" disabled aria-disabled="true"', html)
        self.assertIn(".btn-aplicar-pesos-qa-new-jersey-p3').prop('disabled', false)", html)

    def test_formula_invalida_mantiene_estado_qa_visible_y_desbloqueado(self):
        ticket_p1_entrada = DATO_OPERACION.objects.get(
            CI_NID=self.p1, CAMP_NID__CA_CCODIGO='OP_TICKET_PESAJE_ENT',
        )
        ticket_p1_entrada.DO_NPESO = 10000
        ticket_p1_entrada.save(update_fields=['DO_NPESO'])
        contexto = contexto_transferencia_new_jersey_p3(self.p3)
        self.assertTrue(contexto['qa_habilitado'])
        self.assertTrue(contexto['disponible'])
        self.assertFalse(contexto['calculo_valido'])
        self.assertFalse(contexto['transferencia_sap']['status']['bloqueada'])
        self.assertIn('Pesajes P1 inconsistentes', contexto['error'])

    def test_peso_persistido_usa_codigo_semantico_reservado(self):
        dato, _ = self._calcular()
        self.assertEqual(dato.CAMP_NID.CA_CCODIGO, CAMPO_PESO_REAL)
        self.assertEqual(CAMPO_PESO_REAL, views.NJ_PESO_FINAL_PRODUCTO_KG)
