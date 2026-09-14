from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.home.models import EMPRESA, PERFIL, PERFIL_USUARIO, USERS_EMPRESA


class AsistenteDespachoIngresoCamionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.terramar = cls._crear_empresa(1, 'TERRAMAR')
        cls.sbh = cls._crear_empresa(2, 'SBH')
        cls.no_asignada = cls._crear_empresa(3, 'NO ASIGNADA')
        cls.asistente = User.objects.create_user('asistente_despacho_prueba', password='test')
        cls.recepcion = User.objects.create_user('asistente_recepcion_prueba', password='test')
        cls.sin_permiso = User.objects.create_user('usuario_sin_ingreso', password='test')
        perfil_despacho = PERFIL.objects.create(
            US_NID=cls.asistente,
            PR_CCODIGO='ASISTENTE_DESPACHO',
            PR_CNOMBRE='Asistente Despacho',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=cls.asistente,
            PR_NID=perfil_despacho,
            PE_BHABILITADO=True,
        )
        perfil_recepcion = PERFIL.objects.create(
            US_NID=cls.recepcion,
            PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='Asistente Recepcion',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=cls.recepcion,
            PR_NID=perfil_recepcion,
            PE_BHABILITADO=True,
        )
        for empresa in (cls.terramar, cls.sbh):
            USERS_EMPRESA.objects.create(US_NID=cls.recepcion, EP_NID=empresa)
        for empresa in (cls.terramar, cls.sbh):
            USERS_EMPRESA.objects.create(US_NID=cls.asistente, EP_NID=empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.sin_permiso, EP_NID=cls.terramar)

    @staticmethod
    def _crear_empresa(pk, nombre):
        return EMPRESA.objects.create(
            id=pk,
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=f'7600000{pk}-{pk}',
            EP_CBASEDATOS=f'db{pk}',
            EP_CUSUARIOSBD='user',
            EP_CPORT='5432',
        )

    def _activar(self, usuario, empresa_id):
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = empresa_id
        session.save()

    def _render_menu(self, usuario, empresa_id):
        request = RequestFactory().get('/')
        request.user = usuario
        request.session = {'empresa_id': empresa_id}
        request.resolver_match = SimpleNamespace(url_name='home')
        return render_to_string('includes/component-navbar-inner.html', request=request)


    def _assert_subopciones_ingreso(self, html, empresa_id):
        self.assertEqual(html.count('Ingreso de cami&oacute;n'), 1)
        self.assertIn(f'{reverse("camiones_patio_control")}?_empresa_id={empresa_id}', html)
        self.assertIn(f'{reverse("camiones_patio_registrar")}?_empresa_id={empresa_id}', html)
        self.assertIn(f'{reverse("camiones_patio_list")}?_empresa_id={empresa_id}', html)
        self.assertIn(f'{reverse("pla_listall")}?tipo=RECEPCION&_empresa_id={empresa_id}', html)
        self.assertIn(f'{reverse("pla_listall")}?tipo=DESPACHO&_empresa_id={empresa_id}', html)
        self.assertNotIn('<span class="pcoded-mtext">Planificaciones</span>', html)
    def test_menu_muestra_un_solo_ingreso_camion_en_terramar(self):
        html = self._render_menu(self.asistente, 1)
        self._assert_subopciones_ingreso(html, 1)

    def test_menu_muestra_un_solo_ingreso_camion_en_sbh(self):
        html = self._render_menu(self.asistente, 2)
        self._assert_subopciones_ingreso(html, 2)

    def test_asistente_recepcion_conserva_la_misma_estructura(self):
        for empresa_id in (1, 2):
            with self.subTest(empresa_id=empresa_id):
                self._assert_subopciones_ingreso(self._render_menu(self.recepcion, empresa_id), empresa_id)

    def test_usuario_sin_perfil_no_ve_ingreso_camion(self):
        html = self._render_menu(self.sin_permiso, 1)
        self.assertNotIn('Ingreso de cami&oacute;n', html)

    def test_backend_respeta_recepcion_y_despacho_en_ambas_empresas(self):
        for empresa_id in (1, 2):
            for tipo in ('RECEPCION', 'DESPACHO'):
                with self.subTest(empresa_id=empresa_id, tipo=tipo):
                    self._activar(self.asistente, empresa_id)
                    response = self.client.get(
                        reverse('pla_listall'), {'tipo': tipo, '_empresa_id': empresa_id}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context['tipo_planificacion'], tipo)
                    self.assertTrue(response.context['modo_ingreso_camion'])

    def test_usuario_sin_permiso_conserva_denegacion_backend(self):
        self._activar(self.sin_permiso, 1)
        response = self.client.get(
            reverse('pla_listall'),
            {'tipo': 'DESPACHO', '_empresa_id': 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')



    def test_vistas_patio_responden_en_ambas_empresas(self):
        with patch('apps.home.views._render_camiones_patio_registrar', return_value=HttpResponse('ok')), \
             patch('apps.home.views._camiones_patio_queryset', return_value=[]), \
             patch('apps.home.views._serializar_camiones_control_patio', return_value=[]), \
             patch('apps.home.views._generar_base_control_patio', return_value=''):
            for empresa_id in (1, 2):
                self._activar(self.asistente, empresa_id)
                for nombre in ('camiones_patio_control', 'camiones_patio_registrar', 'camiones_patio_list'):
                    response = self.client.get(reverse(nombre), {'_empresa_id': empresa_id})
                    self.assertEqual(
                        response.status_code,
                        200,
                        (empresa_id, nombre, response.url if response.status_code == 302 else ''),
                    )
    def test_empresa_no_asignada_no_muestra_menu_y_bloquea_backend(self):
        html = self._render_menu(self.asistente, self.no_asignada.id)
        self.assertNotIn('Ingreso de cami&oacute;n', html)
        self._activar(self.asistente, self.no_asignada.id)
        response = self.client.get(
            reverse('camiones_patio_list'),
            {'_empresa_id': self.no_asignada.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_autorizacion_no_depende_del_username(self):
        self.asistente.username = 'nombre_totalmente_distinto'
        self.asistente.save(update_fields=['username'])
        html = self._render_menu(self.asistente, 1)
        self._assert_subopciones_ingreso(html, 1)
