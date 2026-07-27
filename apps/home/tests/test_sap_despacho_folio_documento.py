from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db.models import NOT_PROVIDED
from django.test import SimpleTestCase

from apps.home import sap_despacho
from apps.home.models import CAMION_PATIO


class SapDespachoFolioDocumentoTestCase(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(id=38602, EP_NID_id=2, SN_NID=None)
        self.usuario = SimpleNamespace(id=7, username='qa.user')

    def _dato_valor(self, citacion, codigo):
        return {
            'ACD_CODIGO_SAP': '800034',
            'ACD_ESTANQUE_ORIGEN': 'TK-01',
            'ACD_INTERMES_ID': 'LOTE-01',
            'AR_INTERMES_ID': '',
            'ACD_PESO_INFORMADO': Decimal('26.59'),
        }.get(codigo, '')

    def _dependencias(self, tipo_documento, numero_documento):
        stack = ExitStack()
        camion = SimpleNamespace(
            CPA_CTIPO_DOCUMENTO=tipo_documento,
            CPA_CNUMERO_GUIA=numero_documento,
        )
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.first.return_value = camion
        stack.enter_context(patch.object(sap_despacho.CAMION_PATIO.objects, 'filter', return_value=queryset))
        stack.enter_context(patch.object(sap_despacho, '_detalle_despacho', return_value=None))
        stack.enter_context(patch.object(
            sap_despacho,
            'detalle_despacho_resumen_dict',
            return_value={
                'sap_cliente_codigo': 'C0001',
                'sap_abs_id': '3249',
                'sap_numero_acuerdo': '7001',
                'sap_codigo_producto': '800034',
            },
        ))
        stack.enter_context(patch.object(sap_despacho, '_dato_valor', side_effect=self._dato_valor))
        stack.enter_context(patch.object(sap_despacho, '_draft_series', return_value=102))
        stack.enter_context(patch.object(sap_despacho, '_draft_object_code', return_value='13'))
        stack.enter_context(patch.object(sap_despacho, 'get_sap_despacho_draft_status', return_value={'created': False}))
        stack.enter_context(patch.object(sap_despacho.timezone, 'localdate', return_value=date(2026, 7, 23)))
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

    def test_guia_genera_prefijo_gd_y_folio_entero(self):
        with self._dependencias('GD', '651'):
            preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['payload']['FolioPrefixString'], 'GD')
        self.assertEqual(preview['payload']['FolioNumber'], 651)
        self.assertNotIn('NumAtCard', preview['payload'])
        self.assertEqual(preview['payload']['DocumentLines'][0]['Quantity'], 26.59)

    def test_factura_genera_prefijo_fe_y_folio_entero(self):
        with self._dependencias('FE', '60011'):
            preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

        self.assertEqual(preview['errors'], [])
        self.assertEqual(preview['payload']['FolioPrefixString'], 'FE')
        self.assertEqual(preview['payload']['FolioNumber'], 60011)
        self.assertNotIn('NumAtCard', preview['payload'])

    def test_folio_no_numerico_no_llama_a_sap(self):
        with self._dependencias('GD', 'ABC-651'), patch.object(
            sap_despacho, 'load_config'
        ) as load_config, patch.object(
            sap_despacho, 'SapServiceLayerClient'
        ) as client_class:
            result = sap_despacho.crear_borrador_sap_despacho(self.citacion, self.usuario)

        self.assertFalse(result['success'])
        self.assertEqual(result['preview']['payload'], {})
        self.assertIn('debe ser numerico', ' '.join(result['preview']['errors']))
        load_config.assert_not_called()
        client_class.assert_not_called()

    def test_tipo_fuera_de_choices_no_genera_payload(self):
        with self._dependencias('XX', '651'):
            preview = sap_despacho.construir_payload_draft_despacho(self.citacion)

        self.assertEqual(preview['payload'], {})
        self.assertIn('tipo de documento valido', ' '.join(preview['errors']))
