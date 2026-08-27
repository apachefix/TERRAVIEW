from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class CamionPatioRegistroDespachoSimplificadoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(username='asistente_recepcion', is_superuser=False)

    def _datos_minimos(self, empresa_id):
        return {
            '_empresa_id': str(empresa_id),
            'es_despacho': '1',
            'transporte_a_cargo': 'TERRAMAR',
            'transportista': 'Transportes de prueba',
            'conductor': 'Conductor de prueba',
            'patente': 'UZ7482',
            'rut_conductor': '11111111-1',
            'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678',
        }

    def _ejecutar(self, datos, empresa_id, render_status=400):
        request = self.factory.post('/camiones-patio/registrar/', datos)
        request.user = self.usuario
        empresa = SimpleNamespace(id=empresa_id)
        camion = SimpleNamespace(id=93, CPA_CPATENTE=datos.get('patente', ''))
        create_mock = MagicMock(return_value=camion)
        render_mock = MagicMock(return_value=SimpleNamespace(status_code=render_status))

        parches = (
            patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True),
            patch.object(views, 'Verificar_empresa', return_value=empresa_id),
            patch.object(
                views.EMPRESA.objects,
                'filter',
                return_value=MagicMock(first=MagicMock(return_value=empresa)),
            ),
            patch.object(views, '_validar_carga_planificada_patio', return_value=(None, None)),
            patch.object(
                views,
                'normalize_international_phone',
                return_value={'country_code': '+56', 'local_number': '912345678'},
            ),
            patch.object(views.transaction, 'atomic', return_value=nullcontext()),
            patch.object(views.CAMION_PATIO.objects, 'create', create_mock),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views, 'notificar_camion_patio_nuevo', return_value=0),
            patch.object(views, '_render_camiones_patio_registrar', render_mock),
            patch.object(views.messages, 'success'),
            patch.object(views.messages, 'error'),
            patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)),
        )
        with ExitStack() as stack:
            for parche in parches:
                stack.enter_context(parche)
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        return response, create_mock, render_mock

    def test_despacho_simplificado_empresa_1_acepta_documentales_vacios(self):
        response, create_mock, _ = self._ejecutar(self._datos_minimos(1), 1)

        self.assertEqual(response.status_code, 302)
        kwargs = create_mock.call_args.kwargs
        self.assertEqual(kwargs['CPA_CPROVEEDOR_DECLARADO'], '')
        self.assertEqual(kwargs['CPA_CCLIENTE_DECLARADO'], '')
        self.assertEqual(kwargs['CPA_CTIPO_DOCUMENTO'], '')
        self.assertEqual(kwargs['CPA_CNUMERO_GUIA'], '')
        self.assertEqual(kwargs['CPA_CINSUMO_DECLARADO_GUIA'], '')
        self.assertEqual(kwargs['CPA_CBL'], '')
        self.assertEqual(kwargs['CPA_CLOTE_CONTENEDOR'], '')

    def test_despacho_simplificado_empresa_2_acepta_documentales_vacios(self):
        response, create_mock, _ = self._ejecutar(self._datos_minimos(2), 2)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_mock.call_args.kwargs['EP_NID'].id, 2)

    def test_recepcion_sigue_exigiendo_campos_documentales(self):
        datos = self._datos_minimos(2)
        datos['es_despacho'] = '0'

        response, create_mock, render_mock = self._ejecutar(datos, 2)

        self.assertEqual(response.status_code, 400)
        create_mock.assert_not_called()
        render_mock.assert_called_once()

    def test_despacho_exige_sus_siete_datos_basicos(self):
        campos = (
            'transporte_a_cargo',
            'transportista',
            'conductor',
            'patente',
            'rut_conductor',
            'telefono_codigo_pais',
            'telefono_conductor',
        )
        for campo in campos:
            with self.subTest(campo=campo):
                datos = self._datos_minimos(2)
                datos.pop(campo)
                response, create_mock, _ = self._ejecutar(datos, 2)
                self.assertEqual(response.status_code, 400)
                create_mock.assert_not_called()

    def test_patente_despacho_sbh_conserva_matching_existente(self):
        camion = SimpleNamespace(CPA_CPATENTE='UZ-7482')
        citacion = SimpleNamespace(
            CI_CTIPO='DESPACHO',
            PL_NID=None,
            detalle_despacho=SimpleNamespace(CDD_CPATENTE='UZ7482'),
        )

        patente, normalizada, coincide, estado = views._estado_patente_despacho_patio(
            camion,
            citacion,
            valores_ingreso={},
        )

        self.assertEqual(patente, 'UZ7482')
        self.assertEqual(normalizada, 'UZ7482')
        self.assertTrue(coincide)
        self.assertEqual(estado, 'coincide')

    def test_template_declara_selector_y_alternancia_sin_ocultar_campos(self):
        get_template('home/CAMION_PATIO/registrar.html')
        ruta = Path(views.__file__).parents[1] / 'templates' / 'home' / 'CAMION_PATIO' / 'registrar.html'
        contenido = ruta.read_text(encoding='utf-8')

        self.assertIn('id="patio_es_despacho"', contenido)
        self.assertIn('value="0" {% if form_data.es_despacho != \'1\' %}selected', contenido)
        self.assertIn("camposDocumentales.prop('required', !esDespacho)", contenido)
        self.assertNotIn("camposDocumentales.toggleClass('d-none'", contenido)
        self.assertIn("m.tipo_citacion||''", contenido)