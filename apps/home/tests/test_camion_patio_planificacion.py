import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class ConsultaPatenteTerramarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_superuser=False)

    def request(self, patente='JW-RS-50'):
        request = self.factory.get('/camiones-patio/consultar-citacion-patente/', {'patente': patente, '_empresa_id': '1'})
        request.user = self.user
        request.session = {}
        return request

    def test_patente_normalizada_equivale_a_formatos_visuales(self):
        self.assertEqual(views._normalizar_patente_busqueda('JW-RS 50.'), 'JWRS50')
        self.assertEqual(views._normalizar_patente_busqueda('jwrs50'), 'JWRS50')

    @patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=False)
    def test_usuario_sin_permiso_es_rechazado(self, _permiso):
        response = views.consultar_citacion_patente_patio(self.request())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)['status'], 'UNAUTHORIZED_COMPANY')

    @patch.object(views, 'Verificar_empresa', return_value=2)
    @patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True)
    def test_empresa_dos_es_rechazada(self, _permiso, _empresa):
        response = views.consultar_citacion_patente_patio(self.request())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)['status'], 'UNAUTHORIZED_COMPANY')

    @patch.object(views, 'Verificar_empresa', return_value=1)
    @patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True)
    def test_patente_invalida(self, _permiso, _empresa):
        response = views.consultar_citacion_patente_patio(self.request('---'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['status'], 'INVALID_PLATE')

    def test_guia_conserva_ceros_y_normaliza_formato(self):
        self.assertEqual(views._normalizar_guia_planificacion('GD-001201112'), 'GD001201112')
        self.assertEqual(views._normalizar_guia_planificacion('gd 001201112'), 'GD001201112')


class RegistroDesdePlanificacionTests(SimpleTestCase):
    def test_post_conserva_citacion_como_sugerencia_sin_asociar(self):
        request = RequestFactory().post('/camiones-patio/registrar/', {
            '_empresa_id': '1', 'carga_desde_planificacion': '1', 'citacion_planificada_id': '38629',
            'planificacion_planificada_id': '1221', 'transporte_a_cargo': 'TERRAMAR', 'patente': 'JWRS50',
            'conductor_id': '77',
            'rut_conductor': '26579766-0', 'telefono_conductor': '926483068', 'telefono_codigo_pais': '+56',
            'conductor': 'ALEXANDER YHONIZ', 'transportista': 'TRANSPORTES SAEZ LIMITADA', 'proveedor': 'Proveedor',
            'cliente': 'Cliente', 'tipo_documento': 'GD', 'numero_guia': '1201112', 'insumo_declarado_guia': 'HARINA DE VISCERA 60%'
        })
        request.user = SimpleNamespace(username='asistente', is_superuser=False)
        empresa = SimpleNamespace(id=1)
        citacion = SimpleNamespace(
            id=38629, pk=38629, EP_NID_id=1, CI_CTIPO='RECEPCION',
            PL_NID=SimpleNamespace(id=1221), PL_NID_id=1221,
        )
        camion = SimpleNamespace(id=9, CPA_CPATENTE='JWRS50')
        conductor = SimpleNamespace(
            id=77,
            CON_CNOMBRE='ALEXANDER',
            CON_CAPELLIDO='YHONIZ',
            CON_CRUT='26579766-0',
        )
        create_camion = MagicMock(return_value=camion)
        asociar = MagicMock(return_value={})
        with patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True), \
             patch.object(views, 'Verificar_empresa', return_value=1), \
             patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=empresa))), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views, '_validar_carga_planificada_patio', return_value=(citacion, {'guia_esperada': '1201112', 'guia_recibida': '1201112', 'resultado_guia': 'COINCIDE', 'acepta_diferencia': False, 'observacion': ''})), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=MagicMock(select_related=MagicMock(return_value=MagicMock(get=MagicMock(return_value=citacion))))), \
             patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True), \
             patch.object(views, '_citacion_terramar_disponible_para_llegada', return_value=True), \
             patch.object(views, 'es_citacion_recepcion_terramar', return_value=True), \
             patch.object(views.CONDUCTOR.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=conductor))), \
             patch.object(views.CITACION_RECEPCION_TERRAMAR_DETALLE.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=SimpleNamespace(RTD_CPATENTE='JWRS50')))), \
             patch.object(views.CAMION_PATIO.objects, 'create', create_camion), \
             patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'create'), \
             patch.object(views, '_asociar_camion_patio_a_citacion', asociar), \
             patch.object(views, 'registrar_log_camion_no_planificado'), \
             patch.object(views, 'notificar_camion_patio_nuevo', return_value=0), \
             patch.object(views.messages, 'success'), \
             patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)):
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(create_camion.call_args.kwargs['CI_NID'])
        asociar.assert_not_called()


class ClientePatioDespachoTests(SimpleTestCase):
    def test_despacho_prioriza_cliente_detalle_sin_socio_negocio(self):
        citacion = SimpleNamespace(
            CI_CTIPO='DESPACHO',
            PL_NID=SimpleNamespace(PL_CTIPOCUPO='DESPACHO'),
            SN_NID=None,
            detalle_despacho=SimpleNamespace(
                CDD_CSAP_CLIENTE_CODIGO='C77424780',
                CDD_CSAP_CLIENTE_NOMBRE='EWOS CHILE ALIMENTOS LTDA',
                CDD_CSAP_NUMERO_ACUERDO='371',
            ),
            _datos_cliente_planificacion=[],
        )

        self.assertEqual(
            views.obtener_cliente_planificacion_citacion(citacion),
            {
                'codigo': 'C77424780',
                'nombre': 'EWOS CHILE ALIMENTOS LTDA',
            },
        )
        self.assertEqual(views.obtener_contrato_planificacion_citacion(citacion), '371')

    def test_etiquetas_documentales_despacho_sbh(self):
        self.assertEqual(views._etiqueta_salida_documento_despacho('FE'), 'Factura de cliente')
        self.assertEqual(views._etiqueta_salida_documento_despacho('GD'), 'Guía de despacho')
        self.assertEqual(views._etiqueta_salida_documento_despacho('FE_RESERVA'), 'Factura reserva')
        self.assertEqual(views._etiqueta_salida_documento_despacho(''), '')
    def test_despacho_sin_detalle_despacho_mantiene_fallback_seguro(self):
        citacion = SimpleNamespace(
            CI_CTIPO='DESPACHO',
            PL_NID=SimpleNamespace(PL_CTIPOCUPO='DESPACHO'),
            SN_NID=None,
            _datos_cliente_planificacion=[],
        )

        self.assertEqual(
            views.obtener_cliente_planificacion_citacion(citacion),
            {'codigo': '', 'nombre': ''},
        )
        self.assertEqual(views.obtener_contrato_planificacion_citacion(citacion), '')
