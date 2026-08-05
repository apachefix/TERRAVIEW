import json
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
    def test_post_persiste_fk_y_ejecuta_asociacion_automatica(self):
        request = RequestFactory().post('/camiones-patio/registrar/', {
            '_empresa_id': '1', 'carga_desde_planificacion': '1', 'citacion_planificada_id': '38629',
            'planificacion_planificada_id': '1221', 'transporte_a_cargo': 'TERRAMAR', 'patente': 'JWRS50',
            'rut_conductor': '26579766-0', 'telefono_conductor': '926483068', 'telefono_codigo_pais': '+56',
            'conductor': 'ALEXANDER YHONIZ', 'transportista': 'TRANSPORTES SAEZ LIMITADA', 'proveedor': 'Proveedor',
            'cliente': 'Cliente', 'tipo_documento': 'GD', 'numero_guia': '1201112', 'insumo_declarado_guia': 'HARINA DE VISCERA 60%'
        })
        request.user = SimpleNamespace(username='asistente', is_superuser=False)
        empresa = SimpleNamespace(id=1)
        citacion = SimpleNamespace(id=38629, pk=38629, PL_NID=SimpleNamespace(id=1221), PL_NID_id=1221)
        camion = SimpleNamespace(id=9, CPA_CPATENTE='JWRS50')
        create_camion = MagicMock(return_value=camion)
        asociar = MagicMock(return_value={})
        with patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True), \
             patch.object(views, 'Verificar_empresa', return_value=1), \
             patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=empresa))), \
             patch.object(views, '_validar_carga_planificada_patio', return_value=(citacion, {'guia_esperada': '1201112', 'guia_recibida': '1201112', 'resultado_guia': 'COINCIDE', 'acepta_diferencia': False, 'observacion': ''})), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=MagicMock(select_related=MagicMock(return_value=MagicMock(get=MagicMock(return_value=citacion))))), \
             patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True), \
             patch.object(views, '_citacion_terramar_disponible_para_llegada', return_value=True), \
             patch.object(views, 'es_citacion_recepcion_terramar', return_value=True), \
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
        self.assertIs(create_camion.call_args.kwargs['CI_NID'], citacion)
        self.assertEqual(asociar.call_args.kwargs['origen'], 'REGISTRO_AUTOMATICO_TERRAMAR')
        self.assertIs(asociar.call_args.kwargs['citacion'], citacion)
