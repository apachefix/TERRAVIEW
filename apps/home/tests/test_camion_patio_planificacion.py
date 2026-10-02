import json
import re
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.home import views
from apps.home.models import CAMION_PATIO, CONDUCTOR, EMPRESA


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


    def test_patente_encuentra_conductor_y_precarga_rut(self):
        citacion = SimpleNamespace(id=38736)
        detalle = SimpleNamespace(CI_NID_id=38736, CI_NID=citacion)
        recepciones = MagicMock()
        recepciones.select_related.return_value = [detalle]
        despachos = MagicMock()
        despachos.select_related.return_value = []
        payload = {
            'citacion_id': 38736,
            'conductor_id': 10510,
            'conductor_nombre': 'Conductor Terramar',
            'conductor_rut': '11684951-8',
            'conductor_telefono': '912345678',
        }
        with (
            patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True),
            patch.object(views, 'usuario_puede_registrar_camion_patio_empresa', return_value=True),
            patch.object(views, 'Verificar_empresa', return_value=1),
            patch.object(
                views, '_queryset_patente_normalizada',
                side_effect=[recepciones, despachos],
            ),
            patch.object(
                views, '_citacion_terramar_disponible_para_llegada',
                return_value=True,
            ),
            patch.object(
                views, '_payload_citacion_terramar_patio',
                return_value=payload,
            ),
        ):
            response = views.consultar_citacion_patente_patio(self.request('RS-ZK-21'))
        self.assertEqual(response.status_code, 200)
        resultado = json.loads(response.content)
        self.assertEqual(resultado['status'], 'MATCH')
        self.assertEqual(resultado['matches'][0]['conductor_nombre'], 'Conductor Terramar')
        self.assertEqual(resultado['matches'][0]['conductor_rut'], '11684951-8')


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
        guardado = create_camion.call_args.kwargs
        self.assertIsNone(guardado['CI_NID'])
        self.assertEqual(
            guardado['CPA_CTRANSPORTISTA_DECLARADO'],
            'TRANSPORTES SAEZ LIMITADA',
        )
        self.assertEqual(guardado['CPA_CRUT_CONDUCTOR'], '26579766-0')
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


class RegistroRutRecepcionTerramarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='guardia_rut_terramar', password='test',
        )
        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR',
            EP_CRUT='11-1',
            EP_CBASEDATOS='TEST_TERRAMAR',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.conductor = CONDUCTOR.objects.create(
            EP_NID=cls.empresa,
            US_NID=cls.usuario,
            CON_CNOMBRE='CONDUCTOR',
            CON_CAPELLIDO='TERRAMAR',
            CON_CRUT='11684951-8',
            CON_CTELEFONO='912345678',
            CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_BHABILITADO=True,
        )

    def datos(self, **cambios):
        datos = {
            '_empresa_id': '1',
            'es_despacho': '0',
            'transporte_a_cargo': 'TERRAMAR',
            'transportista': 'TRANSPORTES SAEZ LIMITADA',
            'conductor_id': str(self.conductor.id),
            'conductor': 'CONDUCTOR TERRAMAR',
            'patente': 'RSZK21',
            'rut_conductor': '12.345.678-5',
            'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678',
            'proveedor': 'PROVEEDOR',
            'cliente': 'CLIENTE',
            'tipo_documento': 'GD',
            'numero_guia': '57950',
            'insumo_declarado_guia': 'INSUMO',
        }
        datos.update(cambios)
        return datos

    def registrar(self, datos, render_error=None):
        request = RequestFactory().post('/camiones-patio/registrar/', datos)
        request.user = self.usuario
        parches = [
            patch.object(views, 'Verificar_empresa', return_value=1),
            patch.object(
                views, 'usuario_puede_registrar_camion_patio_empresa',
                return_value=True,
            ),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views.messages, 'success'),
            patch.object(views.messages, 'error'),
        ]
        if render_error is not None:
            parches.append(
                patch.object(
                    views, '_render_camiones_patio_registrar',
                    return_value=render_error,
                )
            )
        iniciados = [parche.start() for parche in parches]
        try:
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        finally:
            for parche in reversed(parches):
                parche.stop()
        return response, iniciados

    def test_rut_post_editado_se_normaliza_persiste_y_se_recarga(self):
        response, _ = self.registrar(self.datos())
        self.assertEqual(response.status_code, 302)
        camion = CAMION_PATIO.objects.get(CPA_CPATENTE='RSZK21')
        self.assertEqual(camion.CON_NID_id, self.conductor.id)
        self.assertEqual(camion.CPA_CNOMBRE_CONDUCTOR, 'CONDUCTOR TERRAMAR')
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '12345678-5')
        self.assertEqual(camion.CPA_CTELEFONO_CONDUCTOR, '912345678')
        self.assertEqual(
            camion.CPA_CTRANSPORTISTA_DECLARADO,
            'TRANSPORTES SAEZ LIMITADA',
        )
        self.conductor.refresh_from_db()
        self.assertEqual(self.conductor.CON_CRUT, '11684951-8')
        recarga = views._datos_precarga_camion_patio(
            CAMION_PATIO.objects.get(pk=camion.pk)
        )
        self.assertEqual(recarga['rut_conductor'], '12345678-5')

    def test_despacho_terramar_conserva_rut_maestro(self):
        datos = self.datos(
            es_despacho='1',
            patente='DESP10',
            rut_conductor='12.345.678-5',
            tipo_documento='',
            numero_guia='',
            proveedor='',
            cliente='',
            insumo_declarado_guia='',
        )
        response, _ = self.registrar(datos)
        self.assertEqual(response.status_code, 302)
        camion = CAMION_PATIO.objects.get(CPA_CPATENTE='DESP10')
        self.assertEqual(camion.CON_NID_id, self.conductor.id)
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '11684951-8')

    def test_conductor_no_registrado_conserva_ingreso_manual(self):
        datos = self.datos(
            conductor_manual='1',
            conductor_id='',
            conductor='',
            conductor_nombre_manual='CHOFER MANUAL',
            patente='MANU10',
            rut_conductor='12.345.678-5',
            telefono_conductor='923456789',
        )
        response, _ = self.registrar(datos)
        self.assertEqual(response.status_code, 302)
        camion = CAMION_PATIO.objects.get(CPA_CPATENTE='MANU10')
        self.assertIsNone(camion.CON_NID_id)
        self.assertEqual(camion.CPA_CNOMBRE_CONDUCTOR, 'CHOFER MANUAL')
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '12345678-5')
        self.assertEqual(camion.CPA_CTELEFONO_CONDUCTOR, '923456789')

    def test_backend_rechaza_rut_invalido_y_no_crea_camion(self):
        respuesta_error = HttpResponse(status=400)
        response, parches = self.registrar(
            self.datos(rut_conductor='11684958-8'),
            render_error=respuesta_error,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CAMION_PATIO.objects.count(), 0)
        error_mock = parches[4]
        error_mock.assert_called_once()
        self.assertEqual(error_mock.call_args.args[1], 'El RUT del conductor no es válido.')


class CampoRutRecepcionTerramarUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='ui_rut_terramar', password='test',
        )
        cls.empresa_1 = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='11-1',
            EP_CBASEDATOS='TEST1', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.empresa_2 = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='22-2',
            EP_CBASEDATOS='TEST2', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )

    def render_registro(self, empresa_id, method='get'):
        self.client.force_login(self.usuario)
        with (
            patch.object(views, 'Verificar_empresa', return_value=empresa_id),
            patch.object(
                views, 'usuario_puede_registrar_camion_patio_empresa',
                return_value=True,
            ),
        ):
            if method == 'post':
                return self.client.post('/camiones-patio/registrar/', {
                    '_empresa_id': str(empresa_id),
                    'es_despacho': '1',
                    'transporte_a_cargo': 'TERRAMAR',
                })
            return self.client.get('/camiones-patio/registrar/', {
                '_empresa_id': str(empresa_id),
            })

    def campo_rut(self, response):
        coincidencias = re.findall(
            r'<input[^>]*id="patio_rut_conductor"[^>]*>',
            response.content.decode('utf-8'),
            flags=re.IGNORECASE,
        )
        self.assertEqual(len(coincidencias), 1)
        return coincidencias[0].lower()

    def campo_transportista(self, response):
        coincidencias = re.findall(
            r'<select[^>]*id="patio_transportista"[^>]*>',
            response.content.decode('utf-8'),
            flags=re.IGNORECASE,
        )
        self.assertEqual(len(coincidencias), 1)
        return coincidencias[0].lower()

    def test_html_recepcion_terramar_renderiza_rut_editable(self):
        response = self.render_registro(1)
        self.assertEqual(response.status_code, 200)
        campo = self.campo_rut(response)
        self.assertNotIn('disabled', campo)
        self.assertNotIn('readonly', campo)
        self.assertNotIn('disabled', self.campo_transportista(response))

    def test_html_despacho_y_empresa_dos_conservan_bloqueo(self):
        despacho = self.render_registro(1, method='post')
        empresa_dos = self.render_registro(2)
        self.assertEqual(despacho.status_code, 400)
        self.assertEqual(empresa_dos.status_code, 200)
        self.assertIn('disabled', self.campo_rut(despacho))
        self.assertIn('disabled', self.campo_rut(empresa_dos))

    def test_javascript_mantiene_rut_y_transportista_habilitados(self):
        contenido = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/CAMION_PATIO/registrar.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Number(PATIO_EMPRESA_ID) === 1', contenido)
        self.assertNotIn('PATIO_EMPRESA_ID === 1 &&', contenido)
        self.assertIn("const recepcionTerramar = esRecepcionTerramarPatio();", contenido)
        self.assertIn(".prop('disabled', terramar && !recepcionTerramar)", contenido)
        self.assertIn(".prop('readonly', false)", contenido)
        self.assertIn("$('#patio_rut_conductor').val(item.rut || '')", contenido)
        self.assertIn("$('#patio_rut_conductor').val(m.conductor_rut||'')", contenido)
        self.assertNotIn(
            "$('#patio_transportista').prop('disabled',String(m.transporte_a_cargo||'').toUpperCase()!=='CLIENTE');",
            contenido,
        )
        self.assertGreaterEqual(
            contenido.count('asegurarCamposRecepcionTerramarPatio();'),
            3,
        )
