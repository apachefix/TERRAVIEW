import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.home import views
from apps.integrations.sap_b1 import sap_recepcion


def citation(*, empresa=2, tipo='RECEPCION', secuencia='RECEPCION_BODEGA_EXTERNA', flete='Contenedor'):
    return SimpleNamespace(
        id=38722,
        pk=38722,
        EP_NID_id=empresa,
        CI_CTIPO=tipo,
        CI_CTIPO_FLETE=flete,
        CI_CTIPODOCUMENTO='GD',
        CI_CNUMERODOCUMENTO='656555',
        PL_NID=SimpleNamespace(PL_CTIPOCUPO='RECEPCION'),
        SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
    )


def detail(**overrides):
    values = {
        'CDO_CALMACEN_DESTINO': 'PROSESA',
        'CDO_CESTANQUE_DESTINO': 'PROSE_G2',
        'CDO_CPEDIDO_SAP': '10000900',
        'CDO_CCODIGO_SAP': 'ITEM-1',
        'CDO_CINSUMO': 'INSUMO',
        'CDO_CPROVEEDOR_CODIGO': 'P123',
        'CDO_CPRODUCTOR': 'PROVEEDOR',
        'CDO_CBL_CONTENEDOR': '',
        'CDO_CBL': '',
        'CDO_CFECHA_PRODUCCION': '',
        'CDO_CFECHA_VENCIMIENTO': '',
        'CDO_CCDA': '',
        'CDO_CDI': '',
        'CDO_CSUI': '',
        'CDO_CNAVE_NAVIERA': '',
        'CDO_NCANTIDAD_DISPONIBLE': Decimal('1000'),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def patio(**overrides):
    values = {
        'id': 134,
        'CPA_CCDA': '',
        'CPA_CDI': '',
        'CPA_CBL': '',
        'CPA_CNAVE_NAVIERA': '',
        'CPA_CFECHAPRODUCCION': '',
        'CPA_CFECHAVENCIMIENTOPRODUCTO': '',
        'CPA_CSUI': '',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ProsesaDescargaCamionIsolationTests(SimpleTestCase):
    def test_caso_exacto_aplica(self):
        self.assertTrue(sap_recepcion.es_recepcion_prosesa_descarga_camion(citation(), detail()))

    def test_empresa_distinta_no_aplica(self):
        self.assertFalse(sap_recepcion.es_recepcion_prosesa_descarga_camion(citation(empresa=1), detail()))

    def test_despacho_no_aplica(self):
        self.assertFalse(sap_recepcion.es_recepcion_prosesa_descarga_camion(citation(tipo='DESPACHO'), detail()))

    def test_tipo_fallback_planificacion(self):
        caso = citation(tipo='')
        self.assertTrue(sap_recepcion.es_recepcion_prosesa_descarga_camion(caso, detail()))

    def test_secuencia_distinta_no_aplica(self):
        caso = citation(secuencia='RECEPCION_ESTANQUE_SBH')
        self.assertFalse(sap_recepcion.es_recepcion_prosesa_descarga_camion(caso, detail()))

    def test_almacen_sbh_no_aplica(self):
        self.assertFalse(
            sap_recepcion.es_recepcion_prosesa_descarga_camion(
                citation(), detail(CDO_CALMACEN_DESTINO='SBH')
            )
        )

    def test_alias_legacy_procesa_aplica(self):
        self.assertTrue(
            sap_recepcion.es_recepcion_prosesa_descarga_camion(
                citation(), detail(CDO_CALMACEN_DESTINO='PROCESA')
            )
        )

    def test_normaliza_mayusculas_y_espacios(self):
        self.assertTrue(
            sap_recepcion.es_recepcion_prosesa_descarga_camion(
                citation(), detail(CDO_CALMACEN_DESTINO='  prosesa  ')
            )
        )

    def test_sin_detalle_no_aplica(self):
        with patch.object(sap_recepcion, '_latest_detail', return_value=None):
            self.assertFalse(sap_recepcion.es_recepcion_prosesa_descarga_camion(citation()))

    def test_tipo_flete_no_define_modalidad(self):
        for flete in ('Contenedor', 'Cisterna', ''):
            with self.subTest(flete=flete):
                self.assertTrue(
                    sap_recepcion.es_recepcion_prosesa_descarga_camion(
                        citation(flete=flete), detail()
                    )
                )


class FechaDocumentalSapTests(SimpleTestCase):
    def test_vacia_se_omite(self):
        self.assertIsNone(sap_recepcion.normalizar_fecha_documental_sap(''))

    def test_ddmmaaaa(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('15052027'),
            '2027-05-15T00:00:00',
        )

    def test_formato_slash(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('15/05/2027'),
            '2027-05-15T00:00:00',
        )

    def test_formato_dash(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('15-05-2027'),
            '2027-05-15T00:00:00',
        )

    def test_formato_dot(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('15.05.2027'),
            '2027-05-15T00:00:00',
        )

    def test_iso_fecha(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('2027-05-15'),
            '2027-05-15T00:00:00',
        )

    def test_iso_datetime(self):
        self.assertEqual(
            sap_recepcion.normalizar_fecha_documental_sap('2027-05-15T18:30:00'),
            '2027-05-15T00:00:00',
        )

    def test_fecha_invalida(self):
        self.assertIsNone(sap_recepcion.normalizar_fecha_documental_sap('31022027'))


class ResolverDocumentalRecepcionTests(SimpleTestCase):
    def _resolve(self, detalle, camion, datos=None):
        queryset = MagicMock()
        queryset.order_by.return_value.first.return_value = camion
        with patch.object(
            sap_recepcion.CAMION_PATIO.objects,
            'filter',
            return_value=queryset,
        ), patch.object(
            sap_recepcion,
            '_dato_valor',
            side_effect=lambda _citacion, codigo: (datos or {}).get(codigo, ''),
        ):
            return sap_recepcion.resolver_datos_documentales_recepcion(
                citation(), detalle
            )

    def test_snapshot_prioriza_cda_sobre_patio(self):
        result = self._resolve(detail(CDO_CCDA='CDA-SNAPSHOT'), patio(CPA_CCDA='CDA-PATIO'))
        self.assertEqual(result['cda'], 'CDA-SNAPSHOT')
        self.assertEqual(result['fuentes']['cda'], 'CITACION_DETALLE_OPERACIONAL.CDO_CCDA')

    def test_patio_es_fallback_de_cda(self):
        result = self._resolve(detail(), patio(CPA_CCDA='CDA-PATIO'))
        self.assertEqual(result['cda'], 'CDA-PATIO')
        self.assertEqual(result['camion_patio_id'], 134)

    def test_bl_contenedor_tiene_primera_prioridad(self):
        result = self._resolve(
            detail(CDO_CBL_CONTENEDOR='CONT-1', CDO_CBL='BL-DET'),
            patio(CPA_CBL='BL-PATIO'),
            {'AR_BL_VALIDADO': 'BL-AR', 'ING_BL': 'BL-ING'},
        )
        self.assertEqual(result['bl'], 'CONT-1')

    def test_bl_detalle_precede_datos_operacion(self):
        result = self._resolve(
            detail(CDO_CBL='BL-DET'),
            patio(CPA_CBL='BL-PATIO'),
            {'AR_BL_VALIDADO': 'BL-AR', 'ING_BL': 'BL-ING'},
        )
        self.assertEqual(result['bl'], 'BL-DET')

    def test_bl_validado_precede_ingreso_y_patio(self):
        result = self._resolve(
            detail(),
            patio(CPA_CBL='BL-PATIO'),
            {'AR_BL_VALIDADO': 'BL-AR', 'ING_BL': 'BL-ING'},
        )
        self.assertEqual(result['bl'], 'BL-AR')

    def test_bl_ingreso_precede_patio(self):
        result = self._resolve(
            detail(),
            patio(CPA_CBL='BL-PATIO'),
            {'ING_BL': 'BL-ING'},
        )
        self.assertEqual(result['bl'], 'BL-ING')

    def test_snapshot_prioriza_fechas_y_sui(self):
        result = self._resolve(
            detail(
                CDO_CFECHA_PRODUCCION='01012027',
                CDO_CFECHA_VENCIMIENTO='01012028',
                CDO_CSUI='SUI-DET',
            ),
            patio(
                CPA_CFECHAPRODUCCION='02022027',
                CPA_CFECHAVENCIMIENTOPRODUCTO='02022028',
                CPA_CSUI='SUI-PATIO',
            ),
        )
        self.assertEqual(result['fecha_produccion'], '01012027')
        self.assertEqual(result['fecha_vencimiento'], '01012028')
        self.assertEqual(result['sui'], 'SUI-DET')


class ResolverTransporteRecepcionTests(SimpleTestCase):
    def _resolve(self, camion, datos=None):
        queryset = MagicMock()
        queryset.select_related.return_value.order_by.return_value.first.return_value = camion
        with patch.object(
            sap_recepcion.CAMION_PATIO.objects, 'filter', return_value=queryset
        ), patch.object(
            sap_recepcion,
            '_dato_valor',
            side_effect=lambda _citacion, codigo: (datos or {}).get(codigo, ''),
        ):
            return sap_recepcion.resolver_datos_transporte_recepcion(citation())

    def test_cliente_usa_datos_manuales_reales_del_camion(self):
        camion = SimpleNamespace(
            id=134,
            transporte_a_cargo='CLIENTE',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES PRUEBA LTDA',
            CPA_CNOMBRE_CONDUCTOR='JUAN PEREZ',
            CPA_CRUT_CONDUCTOR='12.345.678-9',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='912345678',
            CON_NID=None,
        )
        result = self._resolve(camion)
        self.assertEqual(
            result['nombre_transporte'],
            'TRANSPORTES PRUEBA LTDA',
        )
        self.assertEqual(result['nombre_conductor'], 'JUAN PEREZ')
        self.assertEqual(result['rut_conductor'], '12.345.678-9')
        self.assertEqual(result['telefono_conductor'], '+56912345678')
        self.assertEqual(
            result['fuentes']['nombre_conductor'],
            'CAMION_PATIO.CPA_CNOMBRE_CONDUCTOR',
        )

    def test_terramar_prioriza_transportista_y_conductor_seleccionados(self):
        maestro = SimpleNamespace(
            CON_CNOMBRE='Nombre',
            CON_CAPELLIDO='Maestro',
            CON_CRUT='11111111-1',
            CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_CTELEFONO='911111111',
            SN_NID=SimpleNamespace(SN_CRAZONSOCIAL='TRANSPORTISTA DEL MAESTRO'),
        )
        camion = SimpleNamespace(
            id=140, transporte_a_cargo='TERRAMAR',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTISTA SELECCIONADO',
            CPA_CNOMBRE_CONDUCTOR='Conductor Seleccionado',
            CPA_CRUT_CONDUCTOR='22222222-2',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='922222222',
            CON_NID=maestro,
        )
        result = self._resolve(camion)
        self.assertEqual(result['nombre_transporte'], 'TRANSPORTISTA SELECCIONADO')
        self.assertEqual(result['nombre_conductor'], 'Conductor Seleccionado')
        self.assertEqual(result['rut_conductor'], '22222222-2')
        self.assertEqual(result['telefono_conductor'], '+56922222222')

    def test_cliente_sin_transportista_declarado_no_usa_maestro_terramar(self):
        maestro = SimpleNamespace(
            CON_CNOMBRE='Conductor', CON_CAPELLIDO='Cliente',
            CON_CRUT='11111111-1', CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_CTELEFONO='911111111',
            SN_NID=SimpleNamespace(SN_CRAZONSOCIAL='NO USAR TERRAMAR'),
        )
        camion = SimpleNamespace(
            id=142, transporte_a_cargo='CLIENTE',
            CPA_CTRANSPORTISTA_DECLARADO='',
            CPA_CNOMBRE_CONDUCTOR='Conductor Cliente',
            CPA_CRUT_CONDUCTOR='11111111-1',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='911111111',
            CON_NID=maestro,
        )
        result = self._resolve(camion)
        self.assertEqual(result['nombre_transporte'], '')
        self.assertEqual(result['fuentes']['nombre_transporte'], '')

    def test_dato_operacion_es_respaldo_antes_del_maestro(self):
        camion = SimpleNamespace(
            id=141, transporte_a_cargo='CLIENTE',
            CPA_CTRANSPORTISTA_DECLARADO='', CPA_CNOMBRE_CONDUCTOR='',
            CPA_CRUT_CONDUCTOR='', CPA_CCODIGO_PAIS_TELEFONO='',
            CPA_CTELEFONO_CONDUCTOR='', CON_NID=None,
        )
        result = self._resolve(camion, {
            'ING_EMPRESA_TRANSPORTE': 'TRANSPORTES SNAPSHOT LTDA',
            'ING_NOMBRE_CONDUCTOR': 'Conductor Snapshot',
            'ING_RUT_CONDUCTOR': '33333333-3',
            'ING_CODIGO_PAIS_TELEFONO': '+56',
            'ING_TELEFONO_CONDUCTOR': '933333333',
        })
        self.assertEqual(result['nombre_conductor'], 'Conductor Snapshot')
        self.assertEqual(result['rut_conductor'], '33333333-3')
        self.assertEqual(result['telefono_conductor'], '+56933333333')
        self.assertEqual(
            result['nombre_transporte'],
            'TRANSPORTES SNAPSHOT LTDA',
        )
        self.assertEqual(
            result['fuentes']['nombre_transporte'],
            'DATO_OPERACION.ING_EMPRESA_TRANSPORTE',
        )
        self.assertEqual(
            result['fuentes']['nombre_conductor'],
            'DATO_OPERACION.ING_NOMBRE_CONDUCTOR',
        )

    def test_cliente_ignora_marcador_cliente_y_usa_snapshot_real(self):
        camion = SimpleNamespace(
            id=143,
            transporte_a_cargo='CLIENTE',
            CPA_CTRANSPORTISTA_DECLARADO='CLIENTE',
            CPA_CNOMBRE_CONDUCTOR='JUAN PEREZ',
            CPA_CRUT_CONDUCTOR='12345678-5',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='912345678',
            CON_NID=None,
        )

        result = self._resolve(camion, {
            'ING_EMPRESA_TRANSPORTE': 'TRANSPORTES PRUEBA LTDA',
        })

        self.assertEqual(
            result['nombre_transporte'],
            'TRANSPORTES PRUEBA LTDA',
        )
        self.assertEqual(
            result['fuentes']['nombre_transporte'],
            'DATO_OPERACION.ING_EMPRESA_TRANSPORTE',
        )


class ProsesaDocumentLineBuilderTests(SimpleTestCase):
    def _build(
        self,
        documentos,
        *,
        almacen='PROSESA',
        transporte=None,
        cantidad='27.920',
        remaining='30',
        unidad='MT',
    ):
        caso = citation()
        detalle = detail(CDO_CALMACEN_DESTINO=almacen)
        transporte = transporte or {
            'nombre_transporte': '', 'rut_conductor': '',
            'nombre_conductor': '', 'telefono_conductor': '',
            'fuentes': {}, 'camion_patio_id': None,
        }
        selected_line = {
            'LineNum': 0,
            'ItemCode': 'ITEM-1',
            'Quantity': 1000,
            'RemainingOpenQuantity': Decimal(remaining),
            'OpenQuantity': Decimal(remaining),
            'UoMCode': unidad,
            'MeasureUnit': 'Toneladas Metricas' if unidad == 'MT' else unidad,
            'LineStatus': 'bost_Open',
            'LineTotal': 1000,
        }
        client = MagicMock()
        client.get_json.return_value = {
            'CardCode': 'P123',
            'DocumentLines': [selected_line],
        }
        with patch.object(sap_recepcion, '_latest_detail', return_value=detalle), patch.object(
            sap_recepcion, '_resolve_doc_entry', return_value=5605
        ), patch.object(
            sap_recepcion,
            '_dato_valor',
            side_effect=lambda _citacion, codigo: (
                cantidad if codigo == sap_recepcion.CAMPO_PESO_INFORMADO_GUIA else ''
            ),
        ), patch.object(
            sap_recepcion, 'resolver_datos_documentales_recepcion', return_value=documentos
        ) as resolver, patch.object(
            sap_recepcion, 'resolver_datos_transporte_recepcion', return_value=transporte
        ) as resolver_transporte, patch.object(
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
            sap_recepcion.timezone, 'localdate', return_value=date(2026, 9, 24)
        ):
            preview = sap_recepcion.build_goods_receipt_draft_preview_from_peso_guia(caso)
            self.resolver_transporte = resolver_transporte
        return preview, resolver, client

    def test_cantidad_mt_se_usa_directamente_sin_conversion(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        with patch.object(
            sap_recepcion,
            'convertir_peso_salida_kg_a_cantidad_sap_mt',
        ) as convertir:
            preview, _, _ = self._build(documentos, cantidad='27.920', remaining='30')

        self.assertEqual(preview['payload']['DocumentLines'][0]['Quantity'], 27.92)
        self.assertEqual(preview['source_data']['quantity_unit'], 'MT')
        self.assertTrue(
            preview['source_data']['recepcion_prosesa_descarga_camion']
        )
        self.assertEqual(
            preview['source_data']['quantity_semantics'],
            'cantidad_informada_guia_mt',
        )
        self.assertFalse(preview['source_data']['quantity_exceeds_remaining'])
        convertir.assert_not_called()

    def test_cantidad_mt_supera_saldo_de_27_mt(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, _ = self._build(documentos, cantidad='27.920', remaining='27')
        source = preview['source_data']

        self.assertTrue(source['quantity_exceeds_remaining'])
        self.assertIn('27.920 MT', source['quantity_exceeds_message'])
        self.assertIn('27 MT', source['quantity_exceeds_message'])

    def test_caso_38723_conserva_warning_por_saldo_abierto_insuficiente(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, _ = self._build(documentos, cantidad='27.920', remaining='0.005')
        source = preview['source_data']

        self.assertEqual(preview['payload']['DocumentLines'][0]['Quantity'], 27.92)
        self.assertTrue(source['quantity_exceeds_remaining'])
        self.assertEqual(preview['errors'], [])
        self.assertEqual(
            source['quantity_exceeds_message'],
            'La cantidad informada (27.920 MT) supera la cantidad abierta '
            'disponible en SAP (0.005 MT). El borrador se creara para '
            'revision manual en SAP.',
        )
        self.assertIn(source['quantity_exceeds_message'], preview['warnings'])

    def test_envio_caso_38723_no_exige_confirmacion_y_llega_a_post_draft(self):
        caso = citation()
        mensaje = (
            'La cantidad informada (27.920 MT) supera la cantidad abierta '
            'disponible en SAP (0.005 MT). El borrador se creara para '
            'revision manual en SAP.'
        )
        preview = {
            'payload': {
                'DocObjectCode': 20,
                'DocumentLines': [{
                    'ItemCode': '600074', 'Quantity': 27.92,
                    'BaseType': 22, 'BaseEntry': 6726, 'BaseLine': 0,
                }],
            },
            'source_data': {
                'recepcion_prosesa_descarga_camion': True,
                'quantity_unit': 'MT',
                'remaining_open_quantity': 0.005,
                'quantity_exceeds_remaining': True,
                'quantity_exceeds_message': mensaje,
            },
            'errors': [],
        }
        client = MagicMock()
        client.post_draft.return_value = {
            'status_code': 201,
            'data': {'DocEntry': 9901, 'DocNum': 9901},
        }
        with patch.object(
            sap_recepcion,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': False},
        ), patch.object(
            sap_recepcion,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=preview,
        ), patch.object(
            sap_recepcion,
            'load_config',
            return_value=SimpleNamespace(company_db='TEST', username='test'),
        ), patch.object(
            sap_recepcion,
            'normalize_sap_environment',
            return_value='PROD',
        ), patch.object(
            sap_recepcion,
            'SapServiceLayerClient',
            return_value=client,
        ), patch.object(
            sap_recepcion,
            '_save_guide_send_log',
        ):
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                caso,
                SimpleNamespace(username='Asistente_Recepcion'),
            )

        self.assertTrue(result['success'])
        self.assertNotIn('confirmation_required', result)
        self.assertIn(mensaje, preview['source_data']['quantity_exceeds_message'])
        client.login.assert_called_once_with()
        client.post_draft.assert_called_once_with(preview['payload'])
        client.logout.assert_called_once_with()

    def test_envio_no_prosesa_sin_confirmacion_mantiene_bloqueo(self):
        caso = citation(empresa=1)
        preview = {
            'payload': {'DocumentLines': [{'Quantity': 31}]},
            'source_data': {
                'quantity_exceeds_remaining': True,
                'quantity_exceeds_message': 'Cantidad superior al saldo SAP.',
            },
            'errors': [],
        }
        with patch.object(
            sap_recepcion,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': False},
        ), patch.object(
            sap_recepcion,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=preview,
        ), patch.object(
            sap_recepcion,
            'SapServiceLayerClient',
        ) as sap_client:
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                caso,
                SimpleNamespace(username='Asistente_Recepcion'),
            )

        self.assertFalse(result['success'])
        self.assertTrue(result['confirmation_required'])
        self.assertEqual(result['message'], 'Cantidad superior al saldo SAP.')
        sap_client.assert_not_called()

    def test_envio_no_prosesa_con_confirmacion_conserva_comportamiento(self):
        caso = citation(empresa=1)
        preview = {
            'payload': {
                'DocObjectCode': 20,
                'DocumentLines': [{
                    'Quantity': 31, 'BaseType': 22,
                    'BaseEntry': 100, 'BaseLine': 0,
                }],
            },
            'source_data': {'quantity_exceeds_remaining': True},
            'errors': [],
        }
        client = MagicMock()
        client.post_draft.return_value = {
            'status_code': 201,
            'data': {'DocEntry': 9902, 'DocNum': 9902},
        }
        with patch.object(
            sap_recepcion,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': False},
        ), patch.object(
            sap_recepcion,
            'build_goods_receipt_draft_preview_from_peso_guia',
            return_value=preview,
        ), patch.object(
            sap_recepcion,
            'load_config',
            return_value=SimpleNamespace(company_db='TEST', username='test'),
        ), patch.object(
            sap_recepcion,
            'normalize_sap_environment',
            return_value='PROD',
        ), patch.object(
            sap_recepcion,
            'SapServiceLayerClient',
            return_value=client,
        ), patch.object(
            sap_recepcion,
            '_save_guide_send_log',
        ):
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                caso,
                SimpleNamespace(username='Asistente_Recepcion'),
                confirm_quantity_exceeds=True,
            )

        self.assertTrue(result['success'])
        client.post_draft.assert_called_once_with(preview['payload'])

    def test_fuera_de_scope_no_cambia_semantica_global_del_dato(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, _ = self._build(documentos, almacen='SBH', cantidad='27920')

        self.assertEqual(preview['payload']['DocumentLines'][0]['Quantity'], 27920)
        self.assertNotIn('quantity_unit', preview['source_data'])
        self.assertNotIn('quantity_semantics', preview['source_data'])
        self.assertNotIn('sap_quantity_unit', preview['source_data'])
        self.assertNotIn('quantity_exceeds_message', preview['source_data'])

    def test_agrega_todos_los_udf_en_document_line(self):
        documentos = {
            'cda': 'CDA-1',
            'di': 'DI-1',
            'bl': 'BL-1',
            'nave_naviera': 'NAVIERA-1',
            'fecha_produccion': '15052027',
            'fecha_vencimiento': '16052028',
            'sui': 'SUI-1',
            'fuentes': {},
            'camion_patio_id': 134,
        }
        preview, _, client = self._build(documentos)
        line = preview['payload']['DocumentLines'][0]
        self.assertEqual(line['U_CDA'], 'CDA-1')
        self.assertEqual(line['U_DI'], 'DI-1')
        self.assertEqual(line['U_BL'], 'BL-1')
        self.assertEqual(line['U_HCO_NAVIERAS'], 'NAVIERA-1')
        self.assertEqual(line['U_HCO_FVEN'], '2027-05-15T00:00:00')
        self.assertEqual(line['U_NXFlote'], '2028-05-16T00:00:00')
        self.assertEqual(line['U_SUI'], 'SUI-1')
        self.assertNotIn('U_HCO_BL', line)
        client.post_draft.assert_not_called()
        client.patch_draft.assert_not_called()

    def test_agrega_udf_transporte_solo_en_cabecera(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        transporte = {
            'nombre_transporte': 'TRANSPORTES PRUEBA LTDA',
            'rut_conductor': '12.345.678-9',
            'nombre_conductor': 'JUAN PEREZ',
            'telefono_conductor': '+56912345678',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, _ = self._build(documentos, transporte=transporte)
        payload = preview['payload']
        self.assertEqual(
            payload['U_NXNombreTransporte'],
            'TRANSPORTES PRUEBA LTDA',
        )
        self.assertEqual(payload['U_NXRutChofer'], '12.345.678-9')
        self.assertEqual(payload['U_NXNombreChofer'], 'JUAN PEREZ')
        self.assertEqual(payload['U_NXTelefonoChofer'], '+56912345678')
        line = payload['DocumentLines'][0]
        for field in ('U_NXNombreTransporte', 'U_NXRutChofer', 'U_NXNombreChofer', 'U_NXTelefonoChofer'):
            self.assertNotIn(field, line)

    def test_campos_vacios_no_se_envian(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, _ = self._build(documentos)
        line = preview['payload']['DocumentLines'][0]
        for field in ('U_CDA', 'U_DI', 'U_BL', 'U_HCO_NAVIERAS', 'U_HCO_FVEN', 'U_NXFlote', 'U_SUI'):
            self.assertNotIn(field, line)
        for field in ('U_NXNombreTransporte', 'U_NXRutChofer', 'U_NXNombreChofer', 'U_NXTelefonoChofer'):
            self.assertNotIn(field, preview['payload'])

    def test_fecha_invalida_bloquea_payload(self):
        documentos = {
            'cda': '', 'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '31022027', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, _, client = self._build(documentos)
        self.assertEqual(preview['payload'], {})
        self.assertTrue(any('Fecha de produccion invalida' in error for error in preview['errors']))
        client.post_draft.assert_not_called()

    def test_fuera_de_scope_no_resuelve_ni_agrega_udf(self):
        documentos = {
            'cda': 'NO-DEBE-APARECER',
            'di': '', 'bl': '', 'nave_naviera': '',
            'fecha_produccion': '', 'fecha_vencimiento': '', 'sui': '',
            'fuentes': {}, 'camion_patio_id': 134,
        }
        preview, resolver, _ = self._build(documentos, almacen='SBH')
        line = preview['payload']['DocumentLines'][0]
        resolver.assert_not_called()
        self.resolver_transporte.assert_not_called()
        self.assertNotIn('U_CDA', line)
        self.assertNotIn('U_NXNombreTransporte', preview['payload'])
        self.assertNotIn('U_NXNombreChofer', preview['payload'])

    def test_envio_real_reutiliza_sin_cambios_payload_del_preview(self):
        caso = citation()
        preview = {
            'payload': {
                'DocType': 'dDocument_Items',
                'U_NXNombreTransporte': 'TRANSPORTES PRUEBA LTDA',
                'U_NXRutChofer': '12.345.678-9',
                'U_NXNombreChofer': 'JUAN PEREZ',
                'U_NXTelefonoChofer': '+56912345678',
                'DocumentLines': [{'LineNum': 0, 'ItemCode': 'ITEM-1', 'Quantity': 1000}],
            },
            'source_data': {},
            'errors': [],
        }
        client = MagicMock()
        client.post_draft.return_value = {'status_code': 201, 'data': {'DocEntry': 999}}
        with patch.object(
            sap_recepcion, 'get_goods_receipt_draft_guide_status', return_value={'sent': False}
        ), patch.object(
            sap_recepcion, 'build_goods_receipt_draft_preview_from_peso_guia', return_value=preview
        ) as builder, patch.object(
            sap_recepcion, 'normalize_sap_environment', return_value='PROD'
        ), patch.object(
            sap_recepcion, 'load_config',
            return_value=SimpleNamespace(company_db='TEST', username='test'),
        ), patch.object(
            sap_recepcion, 'SapServiceLayerClient', return_value=client
        ), patch.object(
            sap_recepcion, '_save_guide_send_log'
        ):
            result = sap_recepcion.send_goods_receipt_draft_from_peso_guia_to_sap(
                caso, SimpleNamespace(username='Asistente_C_D')
            )
        self.assertTrue(result['success'])
        builder.assert_called_once_with(caso)
        client.post_draft.assert_called_once_with(preview['payload'])


class ProsesaPreviewModalContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_source = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_listone.html'
        ).read_text(encoding='utf-8')
        cls.views_source = Path(views.__file__).read_text(encoding='utf-8')

    def test_modal_contiene_boton_preview(self):
        self.assertIn('id="btn_preview_borrador_sap_recepcion"', self.template_source)

    def test_modal_declara_cantidad_de_guia_en_mt(self):
        self.assertIn('Cantidad informada en gu&iacute;a (MT)', self.template_source)
        self.assertIn("const placeholderCantidad = esProsesaCamion ? 'Ej: 27.920'", self.template_source)
        self.assertIn(
            'Ingrese la cantidad indicada en la gu&iacute;a expresada en toneladas m&eacute;tricas (MT).',
            self.template_source,
        )
        self.assertIn("'peso_unidad': peso_guia_unidad_revision or ('MT' if es_recepcion_prosesa_camion else 'kg')", self.views_source)

    def test_boton_depende_del_flag_y_helper_backend(self):
        self.assertIn(
            '!!response.sap_recepcion_preview_enabled && !!response.es_recepcion_prosesa_descarga_camion',
            self.template_source,
        )

    def test_preview_usa_endpoint_protegido_del_modal(self):
        self.assertIn(
            "url: '/pla-citacion-estanque/' + estanqueCamionCitacionId + '/'",
            self.template_source,
        )
        self.assertIn("data: {preview_sap: '1'}", self.template_source)

    def test_preview_no_construye_payload_sap_en_js(self):
        funcion = self.template_source.split(
            'function previsualizarBorradorSapRecepcion()', 1
        )[1].split('function crearBorradorSapRecepcion()', 1)[0]
        self.assertNotIn('DocumentLines:', funcion)
        self.assertNotIn('U_CDA:', funcion)

    def test_mensaje_cantidad_mt_guardada(self):
        mensaje = 'Debe guardar la cantidad informada en guia (MT) antes de previsualizar el Borrador SAP.'
        self.assertIn(mensaje, self.template_source)
        self.assertIn('Debe guardar la cantidad informada en guia (MT)', self.views_source)
        self.assertIn('antes de previsualizar el Borrador SAP.', self.views_source)

    def test_endpoint_modal_exige_helper_y_flag(self):
        self.assertIn('not es_recepcion_prosesa_camion', self.views_source)
        self.assertIn("getattr(settings, 'SAP_RECEPCION_PREVIEW_ENABLED', False)", self.views_source)

    def test_preview_declara_read_only(self):
        self.assertIn("'read_only': True", self.views_source)
        self.assertIn('PREVISUALIZACION - NO ENVIADO A SAP', self.template_source)

class ProsesaUpdatePreviewEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.citacion = citation()
        self.user = SimpleNamespace(
            username='Asistente_Recepcion',
            is_authenticated=True,
            is_superuser=False,
        )
        self.preview = {
            'payload': {
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800103',
                        'Quantity': 28.4,
                    }
                ]
            },
            'source_data': {
                'citacion': 38722,
                'empresa': 2,
                'draft_docentry': 3535,
                'draft_docnum': 13183,
                'item_code': '800103',
                'warehouse_code': 'PROSE_G2',
                'peso_salida_kg': 28400,
                'cantidad_sap': 28.4,
                'unidad_sap': 'MT',
                'endpoint': '/Drafts(3535)',
            },
            'validations': [],
            'warnings': [],
            'errors': [],
        }

    def _request(self):
        request = self.factory.post(
            '/operacion-planta/38722/sap-recepcion-preview-update/',
            {'_empresa_id': '2'},
        )
        request.user = self.user
        return request

    def _endpoint_patches(self):
        return (
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(
                views,
                '_obtener_citacion_operacion_planta_ajax',
                return_value=(self.citacion, None),
            ),
            patch.object(
                views,
                'es_recepcion_prosesa_descarga_camion',
                return_value=True,
            ),
            patch.object(
                views,
                'obtener_pasos_operacion_citacion',
                return_value=('RECEPCION BODEGA EXTERNA', []),
            ),
            patch.object(
                views,
                'obtener_paso_activo_operacion',
                return_value=(views.PASO_AUTORIZAR_SALIDA, ['ASISTENTE DE RECEPCION'], set()),
            ),
            patch.object(
                views,
                'usuario_puede_actualizar_borrador_sap_recepcion',
                return_value=True,
            ),
        )

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_preview_devuelve_payload_update_y_es_read_only_sin_writes(self):
        patches = self._endpoint_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch.object(
            views,
            'build_goods_receipt_draft_update_preview',
            return_value=self.preview,
        ) as builder, patch.object(
            views,
            'send_goods_receipt_draft_update_to_sap',
        ) as enviar, patch.object(
            views.OPERACION_PLANTA_LOG.objects,
            'create',
        ) as crear_log, patch.object(
            views.DATO_OPERACION.objects,
            'update_or_create',
        ) as escribir_dato, patch.object(
            sap_recepcion,
            'SapServiceLayerClient',
        ) as client_class:
            response = views.ajax_operacion_planta_preview_update_sap_recepcion(
                self._request(),
                38722,
            )

        body = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body['success'])
        self.assertTrue(body['read_only'])
        self.assertEqual(body['preview']['payload'], self.preview['payload'])
        builder.assert_called_once_with(self.citacion)
        enviar.assert_not_called()
        crear_log.assert_not_called()
        escribir_dato.assert_not_called()
        client_class.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False)
    def test_flag_false_rechaza_preview_sin_construir_payload(self):
        with patch.object(
            views,
            'build_goods_receipt_draft_update_preview',
        ) as builder:
            response = views.ajax_operacion_planta_preview_update_sap_recepcion(
                self._request(),
                38722,
            )

        self.assertEqual(response.status_code, 404)
        builder.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_otro_flujo_no_puede_usar_preview(self):
        with patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views,
            '_obtener_citacion_operacion_planta_ajax',
            return_value=(self.citacion, None),
        ), patch.object(
            views,
            'es_recepcion_prosesa_descarga_camion',
            return_value=False,
        ), patch.object(
            views,
            'build_goods_receipt_draft_update_preview',
        ) as builder:
            response = views.ajax_operacion_planta_preview_update_sap_recepcion(
                self._request(),
                38722,
            )

        self.assertEqual(response.status_code, 404)
        builder.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_otro_perfil_conserva_restriccion_del_update(self):
        patches = self._endpoint_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            views,
            'usuario_puede_actualizar_borrador_sap_recepcion',
            return_value=False,
        ), patch.object(
            views,
            'build_goods_receipt_draft_update_preview',
        ) as builder:
            response = views.ajax_operacion_planta_preview_update_sap_recepcion(
                self._request(),
                38722,
            )

        self.assertEqual(response.status_code, 403)
        builder.assert_not_called()


class ProsesaUpdatePreviewParityTests(SimpleTestCase):
    @override_settings(SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT=False)
    def test_preview_y_patch_real_comparten_payload_caso_38722(self):
        caso = citation()
        draft_status = {
            'sent': True,
            'docentry': 3535,
            'docnum': 13183,
            'item_code': '800103',
            'request_json': {
                'DocumentLines': [
                    {
                        'LineNum': 0,
                        'ItemCode': '800103',
                        'WarehouseCode': 'PROSE_G2',
                    }
                ]
            },
        }
        client = MagicMock()
        client.patch_draft.return_value = {'status_code': 204, 'data': {}}

        with patch.object(
            sap_recepcion,
            'get_goods_receipt_draft_guide_status',
            return_value=draft_status,
        ), patch.object(
            sap_recepcion,
            'get_exit_weight_from_citation',
            return_value=Decimal('28400'),
        ), patch.object(
            sap_recepcion,
            'get_goods_receipt_draft_update_status',
            return_value={},
        ), patch.object(
            sap_recepcion,
            'load_config',
            return_value=SimpleNamespace(company_db='TEST'),
        ), patch.object(
            sap_recepcion,
            'SapServiceLayerClient',
            return_value=client,
        ), patch.object(
            sap_recepcion,
            '_registrar_log_update_sap_recepcion',
        ) as registrar_log:
            preview = sap_recepcion.build_goods_receipt_draft_update_preview(caso)
            resultado = sap_recepcion._send_goods_receipt_draft_update_to_sap_locked(
                caso,
                self.user if hasattr(self, 'user') else SimpleNamespace(username='Asistente_Recepcion'),
            )

        payload_patch = client.patch_draft.call_args.args[1]
        self.assertEqual(preview['payload'], payload_patch)
        self.assertEqual(preview['source_data']['draft_docentry'], 3535)
        self.assertEqual(preview['source_data']['draft_docnum'], 13183)
        self.assertEqual(preview['source_data']['peso_salida_kg'], 28400)
        self.assertEqual(preview['source_data']['cantidad_sap'], 28.4)
        self.assertEqual(preview['source_data']['warehouse_code'], 'PROSE_G2')
        self.assertEqual(
            preview['payload']['DocumentLines'][0]['ItemCode'],
            '800103',
        )
        self.assertTrue(resultado['success'])
        client.patch_draft.assert_called_once_with(3535, preview['payload'])
        client.post_draft.assert_not_called()
        registrar_log.assert_called_once()


class ProsesaUpdatePreviewTemplateContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_source = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'CITACION' / 'operacion_planta.html'
        ).read_text(encoding='utf-8')
        cls.views_source = Path(views.__file__).read_text(encoding='utf-8')

    def test_boton_esta_en_bloque_update_y_depende_del_flag_aislado(self):
        bloque = self.template_source.split(
            'class="btn btn-outline-info btn-sm btn-preview-update-sap-recepcion',
            1,
        )[0][-500:]
        self.assertIn('{% if sap_recepcion_update_preview_enabled %}', bloque)
        self.assertIn('Previsualizar JSON SAP', self.template_source)
        self.assertIn('btn-actualizar-sap-recepcion', self.template_source)
        self.assertIn(
            "and es_recepcion_prosesa_descarga_camion(citacion)",
            self.views_source,
        )

    def test_ui_declara_no_envio_y_no_construye_document_lines(self):
        funcion = self.template_source.split(
            'function htmlPreviewUpdateSapRecepcion(response)', 1
        )[1].split(
            "$(document).on('click', '.btn-actualizar-sap-recepcion'", 1
        )[0]
        self.assertIn('PREVISUALIZACI&Oacute;N - NO ENVIADO A SAP', funcion)
        self.assertIn('Esta acci&oacute;n no modifica el Borrador SAP.', funcion)
        self.assertNotIn('DocumentLines:', funcion)
        self.assertIn('JSON.stringify(payload, null, 2)', funcion)
