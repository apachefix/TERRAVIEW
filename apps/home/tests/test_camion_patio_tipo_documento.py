from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase

from apps.home import views


class CamionPatioTipoDocumentoTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(username='guardia')
        self.empresa = SimpleNamespace(id=2)

    def _post_registro(self, tipo, numero):
        request = self.factory.post('/camiones-patio/registrar/', {
            '_empresa_id': '2', 'es_despacho': '0', 'tipo_recepcion': 'NACIONAL',
            'transporte_a_cargo': 'TERRAMAR', 'patente': 'ABCD12',
            'rut_conductor': '11111111-1', 'telefono_conductor': '+56912345678',
            'conductor': 'Conductor', 'transportista': 'Transportes', 'proveedor': 'Proveedor',
            'cliente': 'Cliente', 'tipo_documento': tipo, 'numero_guia': numero,
            'insumo_declarado_guia': 'Insumo',
            'fecha_vencimiento_producto': '14/08/2026',
        })
        request.user = self.usuario
        return request

    def _mocks_registro(self, camion):
        create_mock = MagicMock(return_value=camion)
        return [
            patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True),
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=self.empresa))),
            patch.object(views, 'normalize_chilean_mobile', return_value='+56912345678'),
            patch.object(views.CAMION_PATIO.objects, 'create', create_mock),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views, 'notificar_camion_patio_nuevo', return_value=0),
            patch.object(views.messages, 'success'),
            patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)),
        ], create_mock

    def _registrar(self, tipo, numero, camion):
        mocks, create_mock = self._mocks_registro(camion)
        for mock in mocks:
            mock.start()
        try:
            response = views.CAMIONES_PATIO_REGISTRAR(self._post_registro(tipo, numero))
        finally:
            for mock in reversed(mocks):
                mock.stop()
        return response, create_mock.call_args.kwargs

    def test_registro_persiste_gd_y_numero_con_ceros(self):
        response, kwargs = self._registrar('GD', '000212', SimpleNamespace(id=1, CPA_CPATENTE='ABCD12'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(kwargs['CPA_CTIPO_DOCUMENTO'], 'GD')
        self.assertEqual(kwargs['CPA_CNUMERO_GUIA'], '000212')

    def test_registro_persiste_fe(self):
        _, kwargs = self._registrar('FE', '12345', SimpleNamespace(id=2, CPA_CPATENTE='EFGH34'))
        self.assertEqual(kwargs['CPA_CTIPO_DOCUMENTO'], 'FE')
        self.assertEqual(kwargs['CPA_CNUMERO_GUIA'], '12345')

    def test_registro_rechaza_tipo_fuera_de_gd_fe(self):
        request = self._post_registro('FACTURA', '12345')
        rendered = SimpleNamespace(status_code=400)
        with patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True), patch.object(
            views, 'Verificar_empresa', return_value=2
        ), patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=self.empresa))), patch.object(
            views, '_render_camiones_patio_registrar', return_value=rendered
        ), patch.object(views.messages, 'error') as error_mock:
            response = views.CAMIONES_PATIO_REGISTRAR(request)

        self.assertEqual(response.status_code, 400)
        error_mock.assert_called_once_with(request, 'Tipo de documento inválido.')

    def test_asociacion_copia_tipo_y_numero_a_citacion(self):
        camion = SimpleNamespace(
            CPA_CPATENTE='ABCD12', CPA_CNOMBRE_CONDUCTOR='Conductor', CPA_CRUT_CONDUCTOR='',
            CPA_CTELEFONO_CONDUCTOR='', CPA_CTRANSPORTISTA_DECLARADO='', CPA_CPROVEEDOR_DECLARADO='',
            CPA_CINSUMO_DECLARADO_GUIA='', CPA_CCLIENTE_DECLARADO='', CPA_CTIPO_DOCUMENTO='GD',
            CPA_CNUMERO_GUIA='000212', CPA_CBL='', CPA_CLOTE_CONTENEDOR='', CPA_COBSERVACION='',
            CPA_CFECHAVENCIMIENTOPRODUCTO='14082026',
        )
        citacion = SimpleNamespace(
            id=77, EP_NID_id=1, CI_CTIPO='RECEPCION', save=MagicMock(),
        )
        with patch.object(views, 'guardar_dato_operacion_codigo', return_value=object()):
            views._copiar_datos_camion_patio_a_citacion(camion, citacion, self.usuario)

        self.assertEqual(citacion.CI_CTIPODOCUMENTO, 'GD')
        self.assertEqual(citacion.CI_CNUMERODOCUMENTO, '000212')
        citacion.save.assert_called_once_with(update_fields=['CI_CTIPODOCUMENTO', 'CI_CNUMERODOCUMENTO'])