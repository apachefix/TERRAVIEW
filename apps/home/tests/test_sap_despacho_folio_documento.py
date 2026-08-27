from contextlib import ExitStack
from datetime import date
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db.models import NOT_PROVIDED
from django.test import SimpleTestCase

from apps.home import sap_despacho
from apps.home.models import CAMION_PATIO


class SapDespachoFolioDocumentoTestCase(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(id=38682, EP_NID_id=2, CI_CTIPO='DESPACHO', SN_NID=None)
        self.detalle = SimpleNamespace(
            CDD_NCANTIDAD_INTENTADA_DESPACHAR=Decimal('1'),
            CDD_NPESO_INFORMADO=Decimal('26.59'),
            CDD_CJSON_DRAFT_REQUEST='',
        )

    def _dato_valor(self, citacion, codigo):
        return {
            'ACD_CODIGO_SAP': '800041',
            'ACD_ESTANQUE_ORIGEN': 'TK02',
            'ACD_INTERMES_ID': 'LOTE-MP-800041-347-01',
            'AR_INTERMES_ID': '',
            'ACD_PESO_INFORMADO': Decimal('26.59'),
        }.get(codigo, '')

    def _dependencias(self, tipo_documento, numero_documento='', draft_status=None):
        stack = ExitStack()
        camion = SimpleNamespace(
            CPA_CTIPO_DOCUMENTO=tipo_documento,
            CPA_CNUMERO_GUIA=numero_documento,
        )
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.first.return_value = camion
        stack.enter_context(patch.object(sap_despacho.CAMION_PATIO.objects, 'filter', return_value=queryset))
        stack.enter_context(patch.object(sap_despacho, '_detalle_despacho', return_value=self.detalle))
        stack.enter_context(patch.object(
            sap_despacho,
            'detalle_despacho_resumen_dict',
            return_value={
                'sap_cliente_codigo': 'C77424780',
                'sap_abs_id': '3409',
                'sap_numero_acuerdo': '7001',
                'sap_codigo_producto': '800041',
                'salida_documento': tipo_documento,
            },
        ))
        stack.enter_context(patch.object(sap_despacho, '_dato_valor', side_effect=self._dato_valor))
        stack.enter_context(patch.object(sap_despacho, '_draft_series', return_value=102))
        stack.enter_context(patch.object(sap_despacho, '_draft_object_code', return_value='13'))
        stack.enter_context(patch.object(
            sap_despacho,
            'get_sap_despacho_draft_status',
            return_value=draft_status or {'created': False},
        ))
        stack.enter_context(patch.object(sap_despacho, 'get_sap_despacho_update_status', return_value={'updated': False}))
        stack.enter_context(patch.object(sap_despacho.timezone, 'localdate', return_value=date(2026, 8, 10)))
        return stack

    def test_modelo_restringe_tipo_documento_a_gd_o_fe(self):
        field = CAMION_PATIO._meta.get_field('CPA_CTIPO_DOCUMENTO')
        self.assertEqual(field.max_length, 2)
        self.assertEqual(list(field.choices), [
            ('GD', 'Guía de despacho'),
            ('FE', 'Factura electrónica'),
        ])
        self.assertFalse(field.blank)
        self.assertFalse(field.null)
        self.assertIs(field.default, NOT_PROVIDED)

    def test_matriz_documental_sbh_no_emite_folios(self):
        casos = (
            ('GD', '15', None),
            ('FE', '13', 'tNO'),
            ('FE_RESERVA', '13', 'tYES'),
        )
        for tipo, object_code, reserve_invoice in casos:
            with self.subTest(tipo=tipo), self._dependencias(tipo, ''):
                preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

            self.assertEqual(preview['errors'], [])
            self.assertEqual(preview['payload']['DocObjectCode'], object_code)
            if reserve_invoice is None:
                self.assertNotIn('ReserveInvoice', preview['payload'])
            else:
                self.assertEqual(preview['payload']['ReserveInvoice'], reserve_invoice)
            self.assertNotIn('FolioPrefixString', preview['payload'])
            self.assertNotIn('FolioNumber', preview['payload'])
            self.assertNotIn('numero_documento', preview['source_data'])
            self.assertNotIn('folio_number', preview['source_data'])
            self.assertNotIn('folio_prefix', preview['source_data'])

    def test_quantity_inicial_usa_exclusivamente_cantidad_intentada(self):
        with self._dependencias('FE_RESERVA', 'ABC-IGNORADO'):
            preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

        linea = preview['payload']['DocumentLines'][0]
        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['source_data']['quantity'], 1.0)
        self.assertEqual(preview['source_data']['quantity_source'], 'CDD_NCANTIDAD_INTENTADA_DESPACHAR')
        self.assertEqual(linea['Quantity'], 1.0)
        self.assertEqual(linea['BatchNumbers'][0]['Quantity'], 1.0)

    def test_numero_guia_vacio_o_no_numerico_no_bloquea_sbh(self):
        for numero in ('', 'ABC-651'):
            with self.subTest(numero=numero), self._dependencias('GD', numero):
                preview = sap_despacho.construir_payload_draft_despacho(self.citacion)
            self.assertEqual(preview['errors'], [])
            self.assertNotIn('FolioPrefixString', preview['payload'])
            self.assertNotIn('FolioNumber', preview['payload'])

    def test_update_reemplaza_cantidades_y_elimina_folios_historicos(self):
        with self._dependencias('FE_RESERVA', ''):
            inicial = sap_despacho.construir_payload_draft_despacho(self.citacion)['payload']
        inicial['FolioPrefixString'] = 'FE'
        inicial['FolioNumber'] = 60012
        self.detalle.CDD_CJSON_DRAFT_REQUEST = json.dumps(inicial)

        with self._dependencias('FE_RESERVA', '', draft_status={'created': True, 'docentry': '123'}), patch.object(
            sap_despacho, 'obtener_peso_salida_sap_despacho', return_value=Decimal('0.984')
        ):
            preview = sap_despacho.construir_payload_update_draft_despacho(self.citacion)

        payload = preview['payload']
        linea = payload['DocumentLines'][0]
        self.assertEqual(preview['errors'], [])
        self.assertEqual(linea['Quantity'], 0.984)
        self.assertEqual(linea['BatchNumbers'][0]['Quantity'], 0.984)
        self.assertNotIn('FolioPrefixString', payload)
        self.assertNotIn('FolioNumber', payload)
        self.assertEqual(payload['DocObjectCode'], '13')
        self.assertEqual(payload['ReserveInvoice'], 'tYES')
        self.assertEqual(payload['CardCode'], 'C77424780')
        self.assertEqual(linea['AgreementNo'], 3409)
        self.assertEqual(linea['WarehouseCode'], 'TK02')
        self.assertEqual(linea['BatchNumbers'][0]['BatchNumber'], 'LOTE-MP-800041-347-01')

    def test_update_gd_elimina_reserve_invoice_historico(self):
        with self._dependencias('GD', ''):
            inicial = sap_despacho.construir_payload_draft_despacho(self.citacion)['payload']
        inicial['ReserveInvoice'] = 'tNO'
        self.detalle.CDD_CJSON_DRAFT_REQUEST = json.dumps(inicial)

        with self._dependencias('GD', '', draft_status={'created': True, 'docentry': '123'}), patch.object(
            sap_despacho, 'obtener_peso_salida_sap_despacho', return_value=Decimal('0.984')
        ):
            preview = sap_despacho.construir_payload_update_draft_despacho(self.citacion)

        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['payload']['DocObjectCode'], '15')
        self.assertNotIn('ReserveInvoice', preview['payload'])

    def test_update_fe_normaliza_reserve_invoice_a_tno(self):
        with self._dependencias('FE', ''):
            inicial = sap_despacho.construir_payload_draft_despacho(self.citacion)['payload']
        inicial['ReserveInvoice'] = 'tYES'
        self.detalle.CDD_CJSON_DRAFT_REQUEST = json.dumps(inicial)

        with self._dependencias('FE', '', draft_status={'created': True, 'docentry': '123'}), patch.object(
            sap_despacho, 'obtener_peso_salida_sap_despacho', return_value=Decimal('0.984')
        ):
            preview = sap_despacho.construir_payload_update_draft_despacho(self.citacion)

        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['payload']['DocObjectCode'], '13')
        self.assertEqual(preview['payload']['ReserveInvoice'], 'tNO')

    def test_fuera_de_sbh_conserva_payload_documental_y_quantity_existentes(self):
        citacion_otro_despacho = SimpleNamespace(
            id=38603, EP_NID_id=1, CI_CTIPO='DESPACHO', SN_NID=None
        )
        with self._dependencias('GD', '651'):
            preview = sap_despacho.construir_payload_draft_despacho(citacion_otro_despacho)

        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['payload']['DocObjectCode'], '13')
        self.assertEqual(preview['payload']['FolioPrefixString'], 'GD')
        self.assertEqual(preview['payload']['FolioNumber'], 651)
        self.assertNotIn('ReserveInvoice', preview['payload'])
        self.assertEqual(preview['payload']['DocumentLines'][0]['Quantity'], 26.59)

    def test_fuera_de_sbh_conserva_validacion_folio_numerico(self):
        citacion_otro_despacho = SimpleNamespace(
            id=38603, EP_NID_id=1, CI_CTIPO='DESPACHO', SN_NID=None
        )
        with self._dependencias('GD', 'ABC-651'):
            preview = sap_despacho.construir_payload_draft_despacho(citacion_otro_despacho)

        self.assertEqual(preview['payload'], {})
        self.assertIn('debe ser numerico', ' '.join(preview['errors']))

    def test_tipo_fuera_de_matriz_no_genera_payload(self):
        with self._dependencias('XX', ''):
            preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

        self.assertEqual(preview['payload'], {})
        self.assertIn('tipo de documento valido', ' '.join(preview['errors']))
