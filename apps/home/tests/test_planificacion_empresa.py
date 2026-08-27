import json
from datetime import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.context_processors import empresa_context
from apps.home.models import (
    CALENDARIO,
    CITACION,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
    USERS_EMPRESA,
    USERS_EXTENSION,
)


class AccesoInicialPlanificacionEmpresaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa_harinas = cls.crear_empresa(1, 'TERRAMAR CHILE')
        cls.empresa_aceites = cls.crear_empresa(2, 'ACEITES SBH')
        cls.planificador_harinas = cls.crear_planificador(
            'Planificador_harinas_test', cls.empresa_harinas, terramar=True
        )
        cls.planificador_aceites = cls.crear_planificador(
            'Planificador_aceites_test', cls.empresa_aceites, aceites=True
        )
        cls.planificacion_harinas = cls.crear_planificacion(
            cls.planificador_harinas, cls.empresa_harinas, 'Harinas'
        )
        cls.planificacion_aceites = cls.crear_planificacion(
            cls.planificador_aceites, cls.empresa_aceites, 'Aceites'
        )
        cls.secuencia_transferencia = SECUENCIA.objects.create(
            US_NID=cls.planificador_aceites,
            EP_NID=cls.empresa_aceites,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TRANSFERENCIA_SBH',
            SE_CNOMBRE='Recepción de Transferencia SBH',
            SE_BHABILITADO=True,
        )
        cls.secuencia_ingreso = SECUENCIA.objects.create(
            US_NID=cls.planificador_aceites,
            EP_NID=cls.empresa_aceites,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_ESTANQUE_SBH',
            SE_CNOMBRE='Estanque SBH',
            SE_BHABILITADO=True,
        )
        CITACION.objects.create(
            US_NID=cls.planificador_aceites,
            EP_NID=cls.empresa_aceites,
            PL_NID=cls.planificacion_aceites,
            SC_NID=cls.secuencia_transferencia,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='Insumo Programado',
        )

    @staticmethod
    def crear_empresa(pk, nombre):
        return EMPRESA.objects.create(
            id=pk,
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=f'{pk}-9',
            EP_CBASEDATOS=f'empresa_{pk}',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )

    @staticmethod
    def crear_planificador(username, empresa, terramar=False, aceites=False):
        usuario = get_user_model().objects.create_user(username, password='test-pass')
        USERS_EXTENSION.objects.create(
            US_NID=usuario,
            UX_IS_PLANIFICADOR=True,
            UX_IS_TERRAMAR=terramar,
            UX_IS_ACEITES=aceites,
        )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=empresa)
        return usuario

    @staticmethod
    def crear_planificacion(usuario, empresa, nombre):
        calendario = CALENDARIO.objects.create(
            US_NID=usuario,
            EP_NID=empresa,
            CA_CNOMBRE=nombre,
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        return PLANIFICACION.objects.create(
            US_NID=usuario,
            EP_NID=empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=timezone.now(),
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=5,
        )

    def test_menu_repara_sesion_y_genera_empresa_harinas(self):
        request = RequestFactory().get('/')
        request.user = self.planificador_harinas
        request.session = self.client.session
        request.session['empresa_id'] = self.empresa_aceites.id

        contexto = empresa_context(request)
        menu = render_to_string(
            'includes/component-navbar-inner.html', contexto, request=request
        )

        self.assertEqual(contexto['empresa_activa'].id, self.empresa_harinas.id)
        self.assertEqual(request.session['empresa_id'], self.empresa_harinas.id)
        self.assertIn('_empresa_id=1', menu)
        self.assertNotIn('_empresa_id=2', menu)
        self.assertEqual(menu.count('>Recepci&oacute;n</a>'), 1)
        self.assertEqual(menu.count('>Despacho</a>'), 1)
        self.assertIn('<a href="#" class="nav-link">Planificaciones</a>', menu)
        self.assertIn('Control de cami&oacute;n', menu)
        self.assertIn('Planificaciones archivadas', menu)

    def test_login_resuelve_empresa_unica_antes_del_dashboard(self):
        session = self.client.session
        session['empresa_id'] = self.empresa_aceites.id
        session.save()
        response = self.client.post(
            reverse('login'),
            {'username': self.planificador_harinas.username, 'password': 'test-pass'},
        )

        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['empresa_id'], self.empresa_harinas.id)

    def test_selector_con_sesion_vacia_guarda_empresa_unica_sin_error(self):
        self.client.force_login(self.planificador_harinas)
        response = self.client.get(reverse('seleccionar_empresa'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [('/', 302)])
        self.assertEqual(self.client.session['empresa_id'], self.empresa_harinas.id)
        self.assertNotContains(response, 'No tiene acceso a la empresa seleccionada.')

    def test_selector_repara_sesion_residual_y_dashboard_no_muestra_error(self):
        self.client.force_login(self.planificador_harinas)
        session = self.client.session
        session['empresa_id'] = self.empresa_aceites.id
        session.save()
        response = self.client.get(reverse('seleccionar_empresa'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['empresa_id'], self.empresa_harinas.id)
        self.assertNotContains(response, 'No tiene acceso a la empresa seleccionada.')
        self.assertContains(response, '_empresa_id=1')

    def test_usuario_multiempresa_conserva_selector(self):
        usuario = self.crear_planificador(
            'Planificador_multiempresa_test', self.empresa_harinas, terramar=True
        )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.empresa_aceites)
        self.client.force_login(usuario)
        response = self.client.get(reverse('seleccionar_empresa'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TERRAMAR CHILE')
        self.assertContains(response, 'Aceites SBH')
        self.assertNotIn('empresa_id', self.client.session)

    def test_usuario_sin_empresas_conserva_rechazo(self):
        usuario = get_user_model().objects.create_user(
            'Planificador_sin_empresa_test', password='test-pass'
        )
        self.client.force_login(usuario)
        response = self.client.get(reverse('seleccionar_empresa'))

        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_harinas_accede_y_listado_no_mezcla_empresas(self):
        self.client.force_login(self.planificador_harinas)
        response = self.client.get(
            reverse('pla_listall'),
            {'tipo': 'RECEPCION', '_empresa_id': self.empresa_harinas.id},
        )

        self.assertEqual(response.status_code, 200)
        ids = list(response.context['object_list'].values_list('id', flat=True))
        self.assertEqual(ids, [self.planificacion_harinas.id])
        self.assertEqual(self.client.session['empresa_id'], self.empresa_harinas.id)

    def test_empresa_de_sesion_se_normaliza_como_entero(self):
        self.client.force_login(self.planificador_harinas)
        session = self.client.session
        session['empresa_id'] = '1'
        session.save()

        response = self.client.get(reverse('pla_listall'), {'tipo': 'RECEPCION'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['empresa_id'], 1)
        self.assertIsInstance(self.client.session['empresa_id'], int)

    def test_harinas_no_puede_consultar_aceites(self):
        self.client.force_login(self.planificador_harinas)
        session = self.client.session
        session['empresa_id'] = self.empresa_harinas.id
        session.save()
        response = self.client.get(
            reverse('pla_listall'), {'_empresa_id': self.empresa_aceites.id}
        )

        self.assertRedirects(
            response, reverse('seleccionar_empresa'), fetch_redirect_response=False
        )
        self.assertEqual(self.client.session['empresa_id'], self.empresa_harinas.id)
        mensajes = [str(mensaje) for mensaje in get_messages(response.wsgi_request)]
        self.assertIn('No tiene acceso a la empresa seleccionada.', mensajes)

    def test_aceites_conserva_acceso_y_filtro_propios(self):
        self.client.force_login(self.planificador_aceites)
        response = self.client.get(
            reverse('pla_listall'),
            {'tipo': 'RECEPCION', '_empresa_id': self.empresa_aceites.id},
        )

        self.assertEqual(response.status_code, 200)
        ids = list(response.context['object_list'].values_list('id', flat=True))
        self.assertEqual(ids, [self.planificacion_aceites.id])
        self.assertEqual(self.client.session['empresa_id'], self.empresa_aceites.id)

    def test_menu_planificador_sbh_anida_recepcion_y_reutiliza_ingreso_mercaderia(self):
        request = RequestFactory().get(
            reverse('pla_listall'),
            {
                'tipo': 'RECEPCION',
                'flujo': 'INGRESO_MERCADERIA',
                '_empresa_id': self.empresa_aceites.id,
            },
        )
        request.user = self.planificador_aceites
        request.session = self.client.session
        request.session['empresa_id'] = self.empresa_aceites.id
        request.resolver_match = SimpleNamespace(url_name='pla_listall')

        menu = render_to_string(
            'includes/component-navbar-inner.html',
            empresa_context(request),
            request=request,
        )

        self.assertIn('Ingreso de mercader&iacute;a', menu)
        self.assertIn('Transferencia', menu)
        self.assertIn(
            f'{reverse("pla_listall")}?tipo=RECEPCION&flujo=INGRESO_MERCADERIA&_empresa_id=2',
            menu,
        )
        self.assertIn('href="#!">Recepci&oacute;n</a>', menu)
        self.assertIn('pcoded-trigger', menu)

    def test_pcoded_conserva_handler_generico_y_excluye_tercer_nivel(self):
        base_dir = Path(__file__).resolve().parents[3]
        selector_tercer_nivel = (
            '$(".pcoded-inner-navbar .pcoded-submenu > li > .pcoded-submenu > li").on'
        )

        source = (
            base_dir / 'apps' / 'static' / 'assets' / 'js' / 'pcoded.js'
        ).read_text(encoding='utf-8')
        minified = (
            base_dir / 'apps' / 'static' / 'assets' / 'js' / 'pcoded.min.js'
        ).read_text(encoding='utf-8')
        self.assertIn('$(".pcoded-submenu > li").not(', source)
        self.assertIn(selector_tercer_nivel, source)
        self.assertIn(
            '$(".pcoded-submenu > li").not('
            '".pcoded-inner-navbar .pcoded-submenu > li > '
            '.pcoded-submenu > li").on',
            minified,
        )
        self.assertIn(selector_tercer_nivel, minified)

        scripts = render_to_string('includes/scripts.html')
        self.assertEqual(scripts.count('pcoded.min.js'), 1)
        self.assertIn(
            '/static/assets/js/pcoded.min.js?v=20260822.2',
            scripts,
        )
        self.assertNotIn('/static/assets/js/pcoded.js', scripts)

    def test_transferencia_sbh_reutiliza_listado_recepcion_con_contexto_propio(self):
        self.client.force_login(self.planificador_aceites)
        response = self.client.get(
            reverse('planificacion_recepcion_transferencia'),
            {'_empresa_id': self.empresa_aceites.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home/PLANIFICACION/pla_listall.html')
        self.assertEqual(response.context['tipo_planificacion'], 'RECEPCION')
        self.assertEqual(response.context['flujo_navegacion'], 'TRANSFERENCIA')
        self.assertEqual(
            list(response.context['object_list'].values_list('id', flat=True)),
            [self.planificacion_aceites.id],
        )
        self.assertContains(response, 'flujo=TRANSFERENCIA')
        self.assertNotContains(response, 'Proceso de Transferencia en desarrollo')

    def test_transferencia_conserva_contexto_en_formulario_de_creacion(self):
        self.client.force_login(self.planificador_aceites)
        with patch('apps.home.views.obtener_clientes_aceite', return_value=[]) as clientes_sap_mock, \
             patch('apps.home.views.asegurar_flujos_recepcion_etapa_0', return_value=[]), \
             patch('apps.home.views.asegurar_flujos_despacho_etapa_0'):
            response = self.client.get(
                reverse('pla_addone'),
                {
                    'tipo': 'RECEPCION',
                    'flujo': 'TRANSFERENCIA',
                    '_empresa_id': self.empresa_aceites.id,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tipo_planificacion'], 'RECEPCION')
        self.assertEqual(response.context['flujo_navegacion'], 'TRANSFERENCIA')
        self.assertContains(response, 'URL_LISTADO_PLANIFICACION')
        self.assertContains(response, 'flujo=TRANSFERENCIA')
        clientes_sap_mock.assert_not_called()

    def test_ingreso_mercaderia_no_lista_la_secuencia_de_transferencia(self):
        self.client.force_login(self.planificador_aceites)
        with patch('apps.home.views.obtener_clientes_aceite', return_value=[]), \
             patch('apps.home.views.asegurar_flujos_recepcion_etapa_0', return_value=[]), \
             patch('apps.home.views.asegurar_flujos_despacho_etapa_0'):
            response = self.client.get(
                reverse('pla_addone'),
                {
                    'tipo': 'RECEPCION',
                    'flujo': 'INGRESO_MERCADERIA',
                    '_empresa_id': self.empresa_aceites.id,
                },
            )

        codigos = [secuencia.SE_CCODIGO for secuencia in response.context['secuencias']]
        self.assertIn(self.secuencia_ingreso.SE_CCODIGO, codigos)
        self.assertNotIn(self.secuencia_transferencia.SE_CCODIGO, codigos)
        self.assertContains(response, 'flujo=INGRESO_MERCADERIA')

    def test_transferencia_lista_exclusivamente_su_secuencia_operacional(self):
        self.client.force_login(self.planificador_aceites)
        with patch('apps.home.views.asegurar_flujos_recepcion_etapa_0', return_value=[]), \
             patch('apps.home.views.asegurar_flujos_despacho_etapa_0'):
            response = self.client.get(
                reverse('pla_addone'),
                {
                    'tipo': 'RECEPCION',
                    'flujo': 'TRANSFERENCIA',
                    '_empresa_id': self.empresa_aceites.id,
                },
            )

        codigos = [secuencia.SE_CCODIGO for secuencia in response.context['secuencias']]
        self.assertEqual(codigos, [self.secuencia_transferencia.SE_CCODIGO])
        self.assertContains(response, 'transferencia_secuencia_id')

    def test_backend_rechaza_secuencia_transferencia_en_ingreso_mercaderia(self):
        request = RequestFactory().post(
            reverse('crear_planificacion_citacion'),
            {
                'flujo': 'INGRESO_MERCADERIA',
                'citaciones_json': json.dumps([{
                    'fecha_llegada': '2026-08-23',
                    'tipo_operacion': 'RECEPCION',
                    'flujo': 'INGRESO_MERCADERIA',
                    'secuencia_id': self.secuencia_transferencia.id,
                }]),
            },
        )
        request.user = self.planificador_aceites

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa_aceites.id):
            response = views.CREAR_PLANIFICACION_CITACION(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('Ingreso de mercadería', json.loads(response.content)['message'])

    def test_backend_rechaza_secuencia_ingreso_en_transferencia(self):
        request = RequestFactory().post(
            reverse('crear_planificacion_citacion'),
            {
                'flujo': 'TRANSFERENCIA',
                'citaciones_json': json.dumps([{
                    'fecha_llegada': '2026-08-23',
                    'tipo_operacion': 'RECEPCION',
                    'flujo': 'TRANSFERENCIA',
                    'secuencia_id': self.secuencia_ingreso.id,
                }]),
            },
        )
        request.user = self.planificador_aceites

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa_aceites.id):
            response = views.CREAR_PLANIFICACION_CITACION(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('Transferencia', json.loads(response.content)['message'])

    def test_formulario_conserva_flujo_al_guardar_y_volver_al_listado(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn("formData.append('flujo', FLUJO_NAVEGACION);", template)
        self.assertIn('&flujo={{ flujo_navegacion }}', template)

    def test_menu_transferencia_marca_solo_su_hijo_como_activo(self):
        request = RequestFactory().get(
            reverse('planificacion_recepcion_transferencia'),
            {
                'tipo': 'RECEPCION',
                'flujo': 'TRANSFERENCIA',
                '_empresa_id': self.empresa_aceites.id,
            },
        )
        request.user = self.planificador_aceites
        request.session = self.client.session
        request.session['empresa_id'] = self.empresa_aceites.id
        request.resolver_match = SimpleNamespace(
            url_name='planificacion_recepcion_transferencia'
        )

        menu = render_to_string(
            'includes/component-navbar-inner.html',
            empresa_context(request),
            request=request,
        )

        self.assertIn('flujo=INGRESO_MERCADERIA', menu)
        self.assertIn('planificaciones/recepcion/transferencia/', menu)
        self.assertEqual(menu.count('class="active"'), 1)

    def test_transferencia_no_esta_disponible_para_planificador_terramar(self):
        self.client.force_login(self.planificador_harinas)
        response = self.client.get(
            reverse('planificacion_recepcion_transferencia'),
            {'_empresa_id': self.empresa_harinas.id},
        )

        self.assertRedirects(response, '/', fetch_redirect_response=False)
