from datetime import time

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.context_processors import empresa_context
from apps.home.models import (
    CALENDARIO,
    EMPRESA,
    PLANIFICACION,
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
