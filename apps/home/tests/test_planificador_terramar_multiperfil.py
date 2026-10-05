import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.home.models import EMPRESA, PERFIL, PERFIL_USUARIO, USERS_EMPRESA
from apps.home.services.permisos_planificacion import (
    usuario_es_planificador_terramar,
    usuario_planifica_solo_despacho_sbh,
    usuario_prioriza_planificacion_empresa,
)
from apps.home.templatetags.permission_filters import (
    es_asistente_despacho_empresa,
    es_ingreso_camion,
    puede_gestionar_planificaciones,
    puede_gestionar_planificaciones_empresa,
)


class PlanificadorTerramarMultiperfilTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.terramar = cls._crear_empresa(1, 'TERRAMAR CHILE')
        cls.sbh = cls._crear_empresa(2, 'ACEITES SBH')
        cls.dual = User.objects.create_user('planificador_asistente', password='test')
        cls.despacho_dual = User.objects.create_user('planificador_asistente_despacho', password='test')
        cls.planificador = User.objects.create_user('planificador_terramar', password='test')
        cls.planificador_sbh = User.objects.create_user('planificador_sbh', password='test')
        cls.asistente = User.objects.create_user('asistente_recepcion', password='test')

        perfil_plan = PERFIL.objects.create(
            US_NID=cls.dual,
            PR_CCODIGO='PLAN',
            PR_CNOMBRE='Planificador',
            PR_BHABILITADO=True,
        )
        perfil_asistente = PERFIL.objects.create(
            US_NID=cls.dual,
            PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='Asistente de Recepción',
            PR_BHABILITADO=True,
        )
        perfil_asistente_despacho = PERFIL.objects.create(
            US_NID=cls.dual,
            PR_CCODIGO='ASISTENTE_DESPACHO',
            PR_CNOMBRE='Asistente Despacho',
            PR_BHABILITADO=True,
        )
        for usuario in (cls.dual, cls.despacho_dual, cls.planificador, cls.planificador_sbh):
            PERFIL_USUARIO.objects.create(
                US_NID=usuario,
                PR_NID=perfil_plan,
                PE_BHABILITADO=True,
            )
        for usuario in (cls.dual, cls.asistente):
            PERFIL_USUARIO.objects.create(
                US_NID=usuario,
                PR_NID=perfil_asistente,
                PE_BHABILITADO=True,
            )
        PERFIL_USUARIO.objects.create(
            US_NID=cls.despacho_dual,
            PR_NID=perfil_asistente_despacho,
            PE_BHABILITADO=True,
        )

        USERS_EMPRESA.objects.create(US_NID=cls.planificador, EP_NID=cls.terramar)
        USERS_EMPRESA.objects.create(US_NID=cls.planificador_sbh, EP_NID=cls.sbh)
        USERS_EMPRESA.objects.create(US_NID=cls.asistente, EP_NID=cls.terramar)
        for usuario in (cls.dual, cls.despacho_dual):
            for empresa in (cls.terramar, cls.sbh):
                USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=empresa)

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

    def test_doble_perfil_prioriza_planificacion_solo_en_terramar(self):
        self.assertTrue(es_ingreso_camion(self.dual))
        self.assertFalse(puede_gestionar_planificaciones(self.dual))
        self.assertTrue(usuario_es_planificador_terramar(self.dual, self.terramar.id))
        self.assertTrue(puede_gestionar_planificaciones_empresa(self.dual, self.terramar.id))
        self.assertFalse(usuario_es_planificador_terramar(self.dual, self.sbh.id))
        self.assertFalse(puede_gestionar_planificaciones_empresa(self.dual, self.sbh.id))

    def test_menu_terramar_muestra_planificaciones_y_conserva_acciones_recepcion(self):
        html = self._render_menu(self.dual, self.terramar.id)
        self.assertIn('<span class="pcoded-mtext">Planificaciones</span>', html)
        self.assertNotIn('<span class="pcoded-mtext">Ingreso de cami&oacute;n</span>', html)
        self.assertIn(reverse('camiones_patio_control'), html)
        self.assertIn(reverse('camiones_patio_registrar'), html)
        self.assertIn(reverse('camiones_patio_list'), html)
        self.assertIn(reverse('pla_filedlistall'), html)

    def test_menu_empresa_dos_conserva_modo_ingreso_camion(self):
        html = self._render_menu(self.dual, self.sbh.id)
        self.assertIn('<span class="pcoded-mtext">Ingreso de cami&oacute;n</span>', html)
        self.assertNotIn(reverse('pla_filedlistall'), html)

    def test_listado_cambia_modo_por_empresa_sin_perder_acceso(self):
        for empresa_id, modo_ingreso in ((self.terramar.id, False), (self.sbh.id, True)):
            with self.subTest(empresa_id=empresa_id):
                self._activar(self.dual, empresa_id)
                response = self.client.get(
                    reverse('pla_listall'),
                    {'tipo': 'RECEPCION', '_empresa_id': empresa_id},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['modo_ingreso_camion'], modo_ingreso)

    def test_crear_y_archivadas_se_habilitan_solo_en_terramar(self):
        with patch('apps.home.views.obtener_clientes_aceite', return_value=[]), patch(
            'apps.home.views.asegurar_flujos_recepcion_etapa_0', return_value=[]
        ), patch('apps.home.views.asegurar_flujos_despacho_etapa_0'), patch(
            'apps.home.views.render', return_value=HttpResponse('ok')
        ):
            self._activar(self.dual, self.terramar.id)
            response = self.client.get(
                reverse('pla_addone'),
                {'tipo': 'RECEPCION', '_empresa_id': self.terramar.id},
            )
            self.assertEqual(response.status_code, 200)

            response = self.client.get(
                reverse('pla_addone'),
                {'tipo': 'RECEPCION', '_empresa_id': self.sbh.id},
            )
            self.assertRedirects(response, '/pla_listall/', fetch_redirect_response=False)

        self._activar(self.dual, self.terramar.id)
        self.assertEqual(self.client.get(reverse('pla_filedlistall')).status_code, 200)
        self._activar(self.dual, self.sbh.id)
        response = self.client.get(reverse('pla_filedlistall'))
        self.assertRedirects(response, '/pla_listall/', fetch_redirect_response=False)

    def test_asistente_sin_plan_y_planificador_normal_conservan_comportamiento(self):
        self.assertFalse(usuario_es_planificador_terramar(self.asistente, self.terramar.id))
        self.assertTrue(es_ingreso_camion(self.asistente))
        self.assertTrue(usuario_es_planificador_terramar(self.planificador, self.terramar.id))
        self.assertFalse(es_ingreso_camion(self.planificador))

    def test_plan_mas_asistente_despacho_tiene_alcance_por_empresa(self):
        self.assertTrue(es_asistente_despacho_empresa(self.despacho_dual, self.terramar.id))
        self.assertTrue(usuario_prioriza_planificacion_empresa(self.despacho_dual, self.terramar.id))
        self.assertFalse(usuario_planifica_solo_despacho_sbh(self.despacho_dual, self.terramar.id))
        self.assertTrue(usuario_prioriza_planificacion_empresa(self.despacho_dual, self.sbh.id))
        self.assertTrue(usuario_planifica_solo_despacho_sbh(self.despacho_dual, self.sbh.id))
        self.assertTrue(puede_gestionar_planificaciones_empresa(self.despacho_dual, self.sbh.id))

    def test_menu_plan_asistente_despacho_es_completo_en_terramar_y_solo_despacho_en_sbh(self):
        html_terramar = self._render_menu(self.despacho_dual, self.terramar.id)
        self.assertIn('<span class="pcoded-mtext">Planificaciones</span>', html_terramar)
        self.assertIn('?tipo=RECEPCION&_empresa_id=1', html_terramar)
        self.assertIn('?tipo=DESPACHO&_empresa_id=1', html_terramar)
        self.assertIn(reverse('camiones_patio_registrar'), html_terramar)

        html_sbh = self._render_menu(self.despacho_dual, self.sbh.id)
        self.assertIn('<span class="pcoded-mtext">Planificaciones</span>', html_sbh)
        self.assertNotIn('<span class="pcoded-mtext">Ingreso de cami&oacute;n</span>', html_sbh)
        self.assertIn('?tipo=DESPACHO&_empresa_id=2', html_sbh)
        self.assertNotIn('?tipo=RECEPCION', html_sbh)
        self.assertNotIn(reverse('planificacion_new_jersey_p2'), html_sbh)
        self.assertNotIn(reverse('planificacion_recepcion_transferencia'), html_sbh)

    def test_backend_sbh_fuerza_despacho_y_bloquea_recepcion(self):
        self._activar(self.despacho_dual, self.sbh.id)
        response = self.client.get(
            reverse('pla_listall'),
            {'tipo': 'DESPACHO', '_empresa_id': self.sbh.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['modo_ingreso_camion'])
        self.assertEqual(response.context['tipo_planificacion'], 'DESPACHO')

        response = self.client.get(
            reverse('pla_listall'),
            {'tipo': 'RECEPCION', '_empresa_id': self.sbh.id},
        )
        self.assertRedirects(
            response,
            '/pla_listall/?tipo=DESPACHO&_empresa_id=2',
            fetch_redirect_response=False,
        )

        response = self.client.post(reverse('crear_planificacion_citacion'), {
            '_empresa_id': self.sbh.id,
            'citaciones_json': json.dumps([{
                'fecha_llegada': '2026-10-05',
                'tipo_operacion': 'RECEPCION',
            }]),
        })
        self.assertEqual(response.status_code, 403)

    def test_etapa_cero_sbh_admite_despacho_y_rechaza_recepcion(self):
        with patch('apps.home.views.obtener_clientes_aceite', return_value=[]), patch(
            'apps.home.views.asegurar_flujos_recepcion_etapa_0', return_value=[]
        ), patch('apps.home.views.asegurar_flujos_despacho_etapa_0'), patch(
            'apps.home.views.render', return_value=HttpResponse('ok')
        ):
            self._activar(self.despacho_dual, self.sbh.id)
            response = self.client.get(
                reverse('pla_addone'),
                {'tipo': 'DESPACHO', '_empresa_id': self.sbh.id},
            )
            self.assertEqual(response.status_code, 200)
            response = self.client.get(
                reverse('pla_addone'),
                {'tipo': 'RECEPCION', '_empresa_id': self.sbh.id},
            )
            self.assertEqual(response.status_code, 403)

    def test_rutas_recepcion_sbh_bloqueadas_y_planificador_sbh_normal_sin_cambios(self):
        self._activar(self.despacho_dual, self.sbh.id)
        response = self.client.get(
            reverse('planificacion_recepcion_transferencia'),
            {'_empresa_id': self.sbh.id},
        )
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        response = self.client.get(
            reverse('planificacion_new_jersey_p2'),
            {'_empresa_id': self.sbh.id},
        )
        self.assertEqual(response.status_code, 403)

        html_maesc_equivalente = self._render_menu(self.planificador_sbh, self.sbh.id)
        self.assertIn('?tipo=RECEPCION', html_maesc_equivalente)
        self.assertIn('?tipo=DESPACHO&_empresa_id=2', html_maesc_equivalente)

