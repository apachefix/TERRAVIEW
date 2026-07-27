from types import SimpleNamespace
from unittest.mock import patch

from django.http import QueryDict
from django.test import SimpleTestCase

from apps.home.views import _normalizar_datos_edicion_camion_patio, ruta_transportista_asistente_guardada


class RevisionCamionAsistenteTests(SimpleTestCase):
    def setUp(self):
        self.camion = SimpleNamespace(
            transporte_a_cargo='TERRAMAR',
            CPA_CTRANSPORTISTA_DECLARADO='Transportes Uno',
            CPA_CNOMBRE_CONDUCTOR='Conductor Uno',
            CPA_CRUT_CONDUCTOR='11111111-1',
            CPA_CTELEFONO_CONDUCTOR='+56912345678',
            CPA_CPATENTE='ABCD12',
            CPA_CPROVEEDOR_DECLARADO='Proveedor',
            CPA_CCLIENTE_DECLARADO='Cliente',
            CPA_CNUMERO_GUIA='000212',
            CPA_CINSUMO_DECLARADO_GUIA='Producto',
            CPA_CBL='BL-1',
            CPA_CCANTIDAD_EJES='6',
            CPA_CLOTE_CONTENEDOR='L-1',
            CPA_COBSERVACION='',
        )

    def test_normaliza_edicion_y_conserva_numero_guia(self):
        post = QueryDict('', mutable=True)
        post.update({
            'patente': 'zzzz99',
            'telefono_conductor': '912345678',
            'numero_guia': '000212',
            # Clientes antiguos pueden seguir enviandolo: se ignora sin error.
            'cantidad_ejes': '8',
        })
        datos = _normalizar_datos_edicion_camion_patio(post, self.camion)
        self.assertEqual(datos['CPA_CPATENTE'], 'ZZZZ99')
        self.assertEqual(datos['CPA_CNUMERO_GUIA'], '000212')
        self.assertEqual(datos['CPA_CTELEFONO_CONDUCTOR'], '912345678')
        self.assertEqual(datos['CPA_CCODIGO_PAIS_TELEFONO'], '+56')
        self.assertNotIn('CPA_CCANTIDAD_EJES', datos)

    def test_ruta_vacia_no_cuenta_como_guardada(self):
        dato_vacio = SimpleNamespace(DO_CVALOR='')
        citacion = SimpleNamespace(TAR_NID_id=1, RUT_NID_id=1, TAR_NID=SimpleNamespace(RUT_NID_id=1))
        with patch('apps.home.views.obtener_datos_operacion_citacion', return_value=({'AR_RUTA_TRANSPORTISTA': dato_vacio}, [])):
            self.assertFalse(ruta_transportista_asistente_guardada(citacion))