import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import CONDUCTOR, EMPRESA, SOCIONEGOCIO


class ConductoresIndependientesRecepcionSbhTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        datos_empresa = {
            'EP_CRUT': '76000000-0',
            'EP_CBASEDATOS': 'TEST',
            'EP_CUSUARIOSBD': 'TEST',
            'EP_CPORT': '5432',
        }
        cls.terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='Terramar', **datos_empresa
        )
        cls.sbh = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='Aceites SBH', **datos_empresa
        )
        cls.otra_empresa = EMPRESA.objects.create(
            id=3, EP_CRAZONSOCIAL='Otra empresa', **datos_empresa
        )
        cls.transporte_a = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CRAZONSOCIAL='Transporte A', SN_CRUT='76000001-9',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transporte_b = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CRAZONSOCIAL='Transporte B', SN_CRUT='76000002-7',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.juan = CONDUCTOR.objects.create(
            EP_NID=cls.sbh, SN_NID=cls.transporte_a, CON_CNOMBRE='Juan',
            CON_CAPELLIDO='Soto', CON_CRUT='11111111-1', CON_CTELEFONO='912345678',
            CON_CCODIGO_PAIS_TELEFONO='+56', CON_BHABILITADO=True,
        )
        cls.pedro = CONDUCTOR.objects.create(
            EP_NID=cls.sbh, SN_NID=cls.transporte_b, CON_CNOMBRE='Pedro',
            CON_CAPELLIDO='Tranamil', CON_CRUT='16513997-6', CON_CTELEFONO='61234567',
            CON_CCODIGO_PAIS_TELEFONO='+54', CON_BHABILITADO=True,
        )
        cls.deshabilitado = CONDUCTOR.objects.create(
            EP_NID=cls.sbh, SN_NID=cls.transporte_a, CON_CNOMBRE='Inactivo',
            CON_CAPELLIDO='SBH', CON_CRUT='33333333-3', CON_BHABILITADO=False,
        )
        transporte_otra = SOCIONEGOCIO.objects.create(
            EP_NID=cls.otra_empresa, SN_CRAZONSOCIAL='Transporte externo',
            SN_CRUT='76000003-5', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.fuera_empresa = CONDUCTOR.objects.create(
            EP_NID=cls.otra_empresa, SN_NID=transporte_otra, CON_CNOMBRE='Fuera',
            CON_CAPELLIDO='Empresa', CON_CRUT='44444444-4', CON_BHABILITADO=True,
        )
        cls.transporte_tm_a = SOCIONEGOCIO.objects.create(
            EP_NID=cls.terramar, SN_CRAZONSOCIAL='Transporte TM A',
            SN_CRUT='76000004-3', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transporte_tm_b = SOCIONEGOCIO.objects.create(
            EP_NID=cls.terramar, SN_CRAZONSOCIAL='Transporte TM B',
            SN_CRUT='76000005-1', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.conductor_tm_a = CONDUCTOR.objects.create(
            EP_NID=cls.terramar, SN_NID=cls.transporte_tm_a, CON_CNOMBRE='Ana',
            CON_CAPELLIDO='TM', CON_CRUT='55555555-5', CON_BHABILITADO=True,
        )
        cls.conductor_tm_b = CONDUCTOR.objects.create(
            EP_NID=cls.terramar, SN_NID=cls.transporte_tm_b, CON_CNOMBRE='Luis',
            CON_CAPELLIDO='TM', CON_CRUT='66666666-6', CON_BHABILITADO=True,
        )

    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(is_superuser=True, id=1, username='admin')

    def _consultar(self, empresa_id, transporte, es_despacho):
        request = self.factory.get('/ajax/conductores-ingreso-camion/', {
            'empresa_id': str(empresa_id),
            'transportista_id': str(transporte.id),
            'transportista': transporte.SN_CRAZONSOCIAL,
            'es_despacho': str(es_despacho),
        })
        request.user = self.usuario
        with patch.object(views, 'obtener_camiones_inequivocos_por_conductor', return_value={}), patch.object(
            views, 'obtener_camiones_transportista_ingreso', return_value=[]
        ):
            response = views.AJAX_CONDUCTORES_INGRESO_CAMION(request)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)['results']

    def test_recepcion_sbh_incluye_conductores_de_ambos_transportes(self):
        for transporte in (self.transporte_a, self.transporte_b):
            with self.subTest(transporte=transporte.SN_CRAZONSOCIAL):
                resultados = self._consultar(2, transporte, es_despacho=0)
                ids = {item['conductor_id'] for item in resultados}
                self.assertIn(self.juan.id, ids)
                self.assertIn(self.pedro.id, ids)

    def test_recepcion_sbh_excluye_solo_deshabilitados(self):
        resultados = self._consultar(2, self.transporte_a, es_despacho=0)
        ids = {item['conductor_id'] for item in resultados}
        self.assertNotIn(self.deshabilitado.id, ids)
        self.assertIn(self.fuera_empresa.id, ids)

    def test_autocompletado_conserva_datos_del_conductor_cruzado(self):
        resultados = self._consultar(2, self.transporte_a, es_despacho=0)
        pedro = next(item for item in resultados if item['conductor_id'] == self.pedro.id)
        self.assertEqual(pedro['rut'], '16513997-6')
        self.assertEqual(pedro['telefono'], '61234567')
        self.assertEqual(pedro['telefono_codigo_pais'], '+54')

    def test_consulta_no_modifica_asociacion_historica_del_conductor(self):
        sn_original = self.pedro.SN_NID_id
        self._consultar(2, self.transporte_a, es_despacho=0)
        self.pedro.refresh_from_db()
        self.assertEqual(self.pedro.SN_NID_id, sn_original)

    def test_despacho_sbh_tambien_usa_padron_global(self):
        resultados = self._consultar(2, self.transporte_a, es_despacho=1)
        ids = {item['conductor_id'] for item in resultados}
        self.assertIn(self.juan.id, ids)
        self.assertIn(self.pedro.id, ids)

    def test_recepcion_y_despacho_terramar_mantienen_catalogo_actual(self):
        for es_despacho in ('0', '1'):
            with self.subTest(es_despacho=es_despacho):
                resultados = self._consultar(1, self.transporte_tm_a, es_despacho)
                ids = {item['conductor_id'] for item in resultados}
                self.assertIn(self.conductor_tm_a.id, ids)
                self.assertIn(self.conductor_tm_b.id, ids)
                self.assertIn(self.fuera_empresa.id, ids)

    def test_selector_global_no_depende_de_transportista(self):
        for empresa_id in (1, 2):
            with self.subTest(empresa_id=empresa_id):
                request = self.factory.get('/ajax/conductores-ingreso-camion/', {
                    'empresa_id': str(empresa_id),
                    'q': 'Fuera',
                })
                request.user = self.usuario
                request.session = {}
                response = views.AJAX_CONDUCTORES_INGRESO_CAMION(request)
                resultados = json.loads(response.content)['results']
                ids = {item['conductor_id'] for item in resultados}
                self.assertIn(self.fuera_empresa.id, ids)

    def test_selector_busca_nombre_y_apellido_por_tokens(self):
        consultas = (
            'pedro', 'pedro t', 'pedro tr', 'pedro tran',
            'pedro tranamil', 'tranamil', '16513997', '16513997-6',
        )
        for empresa_id in (1, 2):
            for consulta in consultas:
                with self.subTest(empresa_id=empresa_id, consulta=consulta):
                    request = self.factory.get('/ajax/conductores-ingreso-camion/', {
                        'empresa_id': str(empresa_id),
                        'q': f'  {consulta}  ',
                    })
                    request.user = self.usuario
                    request.session = {}
                    response = views.AJAX_CONDUCTORES_INGRESO_CAMION(request)
                    resultados = json.loads(response.content)['results']
                    ids = {item['conductor_id'] for item in resultados}
                    self.assertIn(self.pedro.id, ids)

    def test_template_envia_flujo_y_no_limpia_conductor_en_recepcion_sbh(self):
        ruta = Path(views.__file__).parents[1] / 'templates' / 'home' / 'CAMION_PATIO' / 'registrar.html'
        contenido = ruta.read_text(encoding='utf-8')
        self.assertIn("es_despacho: esDespachoPatio() ? '1' : '0'", contenido)
        self.assertIn('if (!esSbhPatio()) {', contenido)
        self.assertIn("item.telefono_codigo_pais || '+56'", contenido)
