from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.models import CAMION_PATIO


class RegistroDocumentalRecepcionSbhTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(username='ASISTENTE_RECEPCION', is_superuser=False)

    def _datos(self, tipo='NACIONAL', es_despacho='0'):
        return {
            '_empresa_id': '2',
            'es_despacho': es_despacho,
            'tipo_recepcion': tipo,
            'transporte_a_cargo': 'TERRAMAR',
            'transportista': 'Transporte prueba',
            'transportista_id': '777',
            'conductor': 'Conductor prueba',
            'patente': 'ABCD12',
            'rut_conductor': '11111111-1',
            'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678',
            'proveedor': 'Proveedor prueba',
            'cliente': 'Cliente prueba',
            'tipo_documento': 'GD',
            'numero_guia': '1234',
            'insumo_declarado_guia': 'Aceite',
            'cda': 'CDA001',
            'di': 'DI001',
            'bl': 'BL001',
            'nave_naviera': 'MSC',
            'lote_contenedor': 'MSNU999999',
            'fecha_produccion': '01/08/2026',
            'fecha_vencimiento_producto': '01/08/2027',
            'sui': 'SUI001',
            'observacion': '',
        }

    def _ejecutar(self, datos):
        request = self.factory.post('/camiones-patio/registrar/', datos)
        request.user = self.usuario
        empresa = SimpleNamespace(id=2)
        camion = SimpleNamespace(id=91, CPA_CPATENTE=datos.get('patente', ''))
        create_mock = MagicMock(return_value=camion)
        render_mock = MagicMock(return_value=SimpleNamespace(status_code=400))
        error_mock = MagicMock()
        transportista_sbh = MagicMock(SN_CRAZONSOCIAL='Transporte prueba')
        maestro_transportistas = MagicMock()
        maestro_transportistas.filter.return_value.first.return_value = transportista_sbh
        parches = (
            patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True),
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=empresa))),
            patch.object(views, '_validar_carga_planificada_patio', return_value=(None, None)),
            patch.object(views, 'queryset_transportistas_validos_ingreso_camion', return_value=maestro_transportistas),
            patch.object(views, 'normalize_international_phone', return_value={'country_code': '+56', 'local_number': '912345678'}),
            patch.object(views.transaction, 'atomic', return_value=nullcontext()),
            patch.object(views.CAMION_PATIO.objects, 'create', create_mock),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views, 'notificar_camion_patio_nuevo', return_value=0),
            patch.object(views, '_render_camiones_patio_registrar', render_mock),
            patch.object(views.messages, 'success'),
            patch.object(views.messages, 'error', error_mock),
            patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)),
            patch.object(views, 'send_goods_receipt_draft_to_sap'),
        )
        with ExitStack() as stack:
            for parche in parches:
                stack.enter_context(parche)
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        return response, create_mock, error_mock

    def test_campos_nuevos_pertenecen_a_camion_patio(self):
        esperados = {
            'CPA_CTIPO_RECEPCION': 20,
            'CPA_CCDA': 128,
            'CPA_CDI': 128,
            'CPA_CNAVE_NAVIERA': 256,
            'CPA_CFECHAPRODUCCION': 8,
            'CPA_CSUI': 128,
        }
        for nombre, longitud in esperados.items():
            with self.subTest(nombre=nombre):
                campo = CAMION_PATIO._meta.get_field(nombre)
                self.assertEqual(campo.max_length, longitud)
                self.assertTrue(campo.blank)
                self.assertTrue(campo.null)

    def test_tipo_vacio_e_invalido_se_rechazan_con_mensaje_exacto(self):
        casos = (
            ('', 'Debe seleccionar si la recepción es Nacional o Extranjera.'),
            ('IMPORTADO', 'Tipo de recepción inválido.'),
        )
        for valor, mensaje in casos:
            with self.subTest(valor=valor):
                response, create_mock, error_mock = self._ejecutar(self._datos(tipo=valor))
                self.assertEqual(response.status_code, 400)
                create_mock.assert_not_called()
                self.assertEqual(error_mock.call_args.args[1], mensaje)

    def test_nacional_permite_fechas_vacias_y_limpia_campos_extranjeros(self):
        datos = self._datos(tipo='NACIONAL')
        datos['fecha_produccion'] = ''
        datos['fecha_vencimiento_producto'] = ''
        response, create_mock, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 302)
        guardado = create_mock.call_args.kwargs
        self.assertEqual(guardado['CPA_CTIPO_RECEPCION'], 'NACIONAL')
        for campo in ('CPA_CCDA', 'CPA_CDI', 'CPA_CNAVE_NAVIERA', 'CPA_CSUI', 'CPA_CBL', 'CPA_CLOTE_CONTENEDOR'):
            self.assertEqual(guardado[campo], '')
        self.assertEqual(guardado['CPA_CFECHAPRODUCCION'], '')
        self.assertEqual(guardado['CPA_CFECHAVENCIMIENTOPRODUCTO'], '')

    def test_extranjero_persiste_datos_parciales_y_fechas_normalizadas(self):
        datos = self._datos(tipo='extranjero')
        datos['cda'] = ''
        datos['sui'] = ''
        response, create_mock, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 302)
        guardado = create_mock.call_args.kwargs
        self.assertEqual(guardado['CPA_CTIPO_RECEPCION'], 'EXTRANJERO')
        self.assertEqual(guardado['CPA_CCDA'], '')
        self.assertEqual(guardado['CPA_CDI'], 'DI001')
        self.assertEqual(guardado['CPA_CBL'], 'BL001')
        self.assertEqual(guardado['CPA_CNAVE_NAVIERA'], 'MSC')
        self.assertEqual(guardado['CPA_CLOTE_CONTENEDOR'], 'MSNU999999')
        self.assertEqual(guardado['CPA_CFECHAPRODUCCION'], '01082026')
        self.assertEqual(guardado['CPA_CFECHAVENCIMIENTOPRODUCTO'], '01082027')
        self.assertEqual(guardado['CPA_CSUI'], '')

    def test_despacho_no_exige_tipo_y_conserva_bl_contenedor(self):
        datos = self._datos(tipo='', es_despacho='1')
        response, create_mock, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 302)
        guardado = create_mock.call_args.kwargs
        self.assertEqual(guardado['CPA_CTIPO_RECEPCION'], '')
        self.assertEqual(guardado['CPA_CBL'], 'BL001')
        self.assertEqual(guardado['CPA_CLOTE_CONTENEDOR'], 'MSNU999999')
        self.assertEqual(guardado['CPA_CFECHAPRODUCCION'], '')
        self.assertEqual(guardado['CPA_CFECHAVENCIMIENTOPRODUCTO'], '')

    def test_template_contiene_selector_y_limpieza_de_exclusivos(self):
        ruta = Path(views.__file__).parents[1] / 'templates' / 'home' / 'CAMION_PATIO' / 'registrar.html'
        contenido = ruta.read_text(encoding='utf-8')
        for identificador in (
            'patio_tipo_recepcion', 'patio_cda', 'patio_di', 'patio_bl',
            'patio_nave_naviera', 'patio_lote_contenedor', 'patio_fecha_produccion',
            'patio_fecha_vencimiento_producto', 'patio_sui',
        ):
            self.assertIn(f'id="{identificador}"', contenido)
        self.assertIn("camposExtranjeros.add(bl).add(contenedor).val('')", contenido)
        self.assertIn(".prop('required', false)", contenido)


class SerializacionDocumentalRecepcionSbhTests(SimpleTestCase):
    def test_datos_documentales_se_reconstruyen_desde_camion_patio(self):
        camion = SimpleNamespace(
            id=91, CPA_CESTADO='PENDIENTE_ASOCIACION', CPA_CPATENTE='ABCD12',
            transporte_a_cargo='TERRAMAR', get_transporte_a_cargo_display=lambda: 'Terramar',
            CPA_CNOMBRE_CONDUCTOR='Conductor', CPA_CRUT_CONDUCTOR='11111111-1',
            CPA_CCODIGO_PAIS_TELEFONO='+56', CPA_CTELEFONO_CONDUCTOR='912345678',
            CPA_CTRANSPORTISTA_DECLARADO='Transporte', CPA_CPROVEEDOR_DECLARADO='Proveedor',
            CPA_CINSUMO_DECLARADO_GUIA='Aceite', CPA_CTIPO_RECEPCION='EXTRANJERO',
            CPA_CCDA='CDA001', CPA_CDI='DI001', CPA_CNAVE_NAVIERA='MSC',
            CPA_CFECHAPRODUCCION='01082026', CPA_CFECHAVENCIMIENTOPRODUCTO='01082027',
            CPA_CSUI='SUI001', CPA_CCLIENTE_DECLARADO='Cliente', CPA_CNUMERO_GUIA='1234',
            CPA_CBL='BL001', CPA_CLOTE_CONTENEDOR='MSNU999999', CPA_COBSERVACION='',
            US_GUARDIA_ID=SimpleNamespace(username='asistente'),
            CPA_FFECHALLEGADA=views.timezone.now(), CI_NID_id=None,
        )
        with patch.object(views, '_solicitud_no_planificado_visible', return_value=None), patch.object(
            views, '_camion_patio_bloqueado_para_edicion', return_value=False
        ):
            data = views._serializar_camion_patio(camion)
        self.assertEqual(data['tipo_recepcion'], 'EXTRANJERO')
        self.assertEqual(data['cda'], 'CDA001')
        self.assertEqual(data['di'], 'DI001')
        self.assertEqual(data['nave_naviera'], 'MSC')
        self.assertEqual(data['fecha_produccion'], '01082026')
        self.assertEqual(data['fecha_vencimiento'], '01082027')
        self.assertEqual(data['sui'], 'SUI001')
        self.assertEqual(data['bl'], 'BL001')
        self.assertEqual(data['lote_contenedor'], 'MSNU999999')
