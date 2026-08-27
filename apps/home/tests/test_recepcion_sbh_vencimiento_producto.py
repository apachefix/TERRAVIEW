from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.models import CAMION_PATIO, CITACION


class FechaVencimientoProductoSbhTests(SimpleTestCase):
    def test_formatos_validos_se_normalizan_a_ddmmaaaa(self):
        for entrada in ('14/08/2026', '14-08-2026', '14.08.2026', '14082026', '2026-08-14'):
            with self.subTest(entrada=entrada):
                self.assertEqual(
                    views._normalizar_fecha_vencimiento_producto_sbh(entrada),
                    '14082026',
                )
        self.assertEqual(
            views._normalizar_fecha_vencimiento_producto_sbh('29/02/2028'),
            '29022028',
        )

    def test_fecha_con_anio_corto_se_rechaza(self):
        with self.assertRaisesMessage(ValueError, 'Ingrese la fecha con año de cuatro dígitos.'):
            views._normalizar_fecha_vencimiento_producto_sbh('14/08/26')

    def test_fechas_no_reales_se_rechazan(self):
        for entrada in ('31/02/2026', '32/08/2026', '00/08/2026', '14/13/2026', '00000000', '99999999', 'abcdefgh'):
            with self.subTest(entrada=entrada):
                with self.assertRaisesMessage(ValueError, 'Fecha de vencimiento de producto inválida.'):
                    views._normalizar_fecha_vencimiento_producto_sbh(entrada)

    def test_campos_modelo_tienen_longitud_operacional(self):
        self.assertEqual(
            CITACION._meta.get_field('CI_CFECHAVENCIMIENTOPRODUCTO').max_length,
            8,
        )
        self.assertEqual(
            CAMION_PATIO._meta.get_field('CPA_CFECHAVENCIMIENTOPRODUCTO').max_length,
            8,
        )


class RegistroRecepcionSbhTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(username='ASISTENTE_RECEPCION', is_superuser=False)

    def _datos(self, empresa_id=2, es_despacho='0'):
        return {
            '_empresa_id': str(empresa_id),
            'es_despacho': es_despacho,
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
            'tipo_recepcion': 'NACIONAL',
            'fecha_vencimiento_producto': '14/08/2026',
            'observacion': '  Producto según guía proveedor.  ',
        }

    def _ejecutar(self, datos, empresa_id=2):
        request = self.factory.post('/camiones-patio/registrar/', datos)
        request.user = self.usuario
        empresa = SimpleNamespace(id=empresa_id)
        camion = SimpleNamespace(id=91, CPA_CPATENTE=datos.get('patente', ''))
        create_mock = MagicMock(return_value=camion)
        render_mock = MagicMock(return_value=SimpleNamespace(status_code=400))
        sap_mock = MagicMock()
        transportista_sbh = MagicMock(SN_CRAZONSOCIAL='Transporte prueba')
        maestro_transportistas = MagicMock()
        maestro_transportistas.filter.return_value.first.return_value = transportista_sbh
        parches = (
            patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True),
            patch.object(views, 'Verificar_empresa', return_value=empresa_id),
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
            patch.object(views.messages, 'error'),
            patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)),
            patch.object(views, 'send_goods_receipt_draft_to_sap', sap_mock),
        )
        with ExitStack() as stack:
            for parche in parches:
                stack.enter_context(parche)
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        return response, create_mock, render_mock, sap_mock

    def test_recepcion_sbh_normaliza_fecha_y_observacion_en_staging(self):
        response, create_mock, _, sap_mock = self._ejecutar(self._datos())
        self.assertEqual(response.status_code, 302)
        kwargs = create_mock.call_args.kwargs
        self.assertEqual(kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO'], '14082026')
        self.assertEqual(kwargs['CPA_COBSERVACION'], 'Producto según guía proveedor.')
        self.assertEqual(len(kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO']), 8)
        sap_mock.assert_not_called()

    def test_variantes_de_fecha_se_persisten_normalizadas(self):
        for entrada in ('14-08-2026', '14.08.2026', '14082026'):
            with self.subTest(entrada=entrada):
                datos = self._datos()
                datos['fecha_vencimiento_producto'] = entrada
                response, create_mock, _, _ = self._ejecutar(datos)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(create_mock.call_args.kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO'], '14082026')

    def test_recepcion_sbh_sin_fecha_se_permite(self):
        datos = self._datos()
        datos['fecha_vencimiento_producto'] = ''
        response, create_mock, _, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_mock.call_args.kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO'], '')

    def test_fecha_invalida_se_rechaza(self):
        datos = self._datos()
        datos['fecha_vencimiento_producto'] = '31/02/2026'
        response, create_mock, _, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 400)
        create_mock.assert_not_called()

    def test_observacion_vacia_y_de_250_caracteres_son_validas(self):
        for observacion in ('', 'x' * 250):
            with self.subTest(longitud=len(observacion)):
                datos = self._datos()
                datos['observacion'] = observacion
                response, create_mock, _, _ = self._ejecutar(datos)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(create_mock.call_args.kwargs['CPA_COBSERVACION'], observacion)

    def test_observacion_de_251_caracteres_se_rechaza(self):
        datos = self._datos()
        datos['observacion'] = 'x' * 251
        response, create_mock, _, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 400)
        create_mock.assert_not_called()

    def test_despacho_ignora_fecha_manipulada(self):
        datos = self._datos(es_despacho='1')
        datos['fecha_vencimiento_producto'] = '14/08/2026'
        response, create_mock, _, _ = self._ejecutar(datos)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_mock.call_args.kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO'], '')

    def test_terramar_recepcion_mantiene_comportamiento_sin_fecha(self):
        datos = self._datos(empresa_id=1)
        datos.pop('fecha_vencimiento_producto')
        response, create_mock, _, _ = self._ejecutar(datos, empresa_id=1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_mock.call_args.kwargs['CPA_CFECHAVENCIMIENTOPRODUCTO'], '')

    def test_template_limita_ui_a_sbh_y_observacion_a_250(self):
        ruta = Path(views.__file__).parents[1] / 'templates' / 'home' / 'CAMION_PATIO' / 'registrar.html'
        contenido = ruta.read_text(encoding='utf-8')
        self.assertIn('{% if empresa_activa_id == 2 %}', contenido)
        self.assertIn('id="bloque_fecha_vencimiento_producto"', contenido)
        self.assertIn('id="patio_tipo_recepcion"', contenido)
        self.assertIn("Number(PATIO_EMPRESA_ID) === 2 && !esDespacho", contenido)
        self.assertNotIn('Fecha Vencimiento producto *', contenido)
        self.assertIn('maxlength="250"', contenido)


class PersistenciaCitacionRecepcionSbhTests(SimpleTestCase):
    def _camion(self, fecha='14082026', observacion='Observación persistente'):
        return SimpleNamespace(
            CPA_CPATENTE='ABCD12', CPA_CNOMBRE_CONDUCTOR='Conductor',
            CPA_CRUT_CONDUCTOR='11111111-1', CPA_CTRANSPORTISTA_DECLARADO='Transporte',
            CPA_CPROVEEDOR_DECLARADO='Proveedor', CPA_CINSUMO_DECLARADO_GUIA='Aceite',
            CPA_CCLIENTE_DECLARADO='Cliente', CPA_CNUMERO_GUIA='1234',
            CPA_CBL='', CPA_CLOTE_CONTENEDOR='', CPA_COBSERVACION=observacion,
            CPA_CFECHAVENCIMIENTOPRODUCTO=fecha, CPA_CTELEFONO_CONDUCTOR='',
            CPA_CTIPO_DOCUMENTO='GD',
        )

    def test_fecha_y_observacion_se_guardan_en_la_misma_citacion_sbh(self):
        citacion = SimpleNamespace(
            id=7123, EP_NID_id=2, CI_CTIPO='RECEPCION',
            CI_CFECHAVENCIMIENTOPRODUCTO=None, CI_CCOMENTARIO=None,
            CI_CTIPODOCUMENTO=None, CI_CNUMERODOCUMENTO=None,
            save=MagicMock(),
        )
        with patch.object(views, 'guardar_dato_operacion_codigo', side_effect=lambda *args, **kwargs: object()):
            views._copiar_datos_camion_patio_a_citacion(
                self._camion(), citacion, SimpleNamespace(username='asistente')
            )
        self.assertEqual(citacion.CI_CFECHAVENCIMIENTOPRODUCTO, '14082026')
        self.assertEqual(citacion.CI_CCOMENTARIO, 'Observación persistente')
        citacion.save.assert_any_call(update_fields=[
            'CI_CFECHAVENCIMIENTOPRODUCTO', 'CI_CCOMENTARIO',
        ])

    def test_despacho_sbh_no_recibe_fecha_residual(self):
        citacion = SimpleNamespace(
            id=7124, EP_NID_id=2, CI_CTIPO='DESPACHO',
            CI_CFECHAVENCIMIENTOPRODUCTO=None, CI_CCOMENTARIO=None,
            CI_CTIPODOCUMENTO=None, CI_CNUMERODOCUMENTO=None,
            save=MagicMock(),
        )
        with patch.object(views, 'guardar_dato_operacion_codigo', side_effect=lambda *args, **kwargs: object()):
            views._copiar_datos_camion_patio_a_citacion(
                self._camion(), citacion, SimpleNamespace(username='asistente')
            )
        self.assertIsNone(citacion.CI_CFECHAVENCIMIENTOPRODUCTO)
        self.assertIsNone(citacion.CI_CCOMENTARIO)
