from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.home.models import (
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    USERS_EMPRESA,
    VISTA,
)
from apps.home.services.proforma_service import (
    PERMISO_INICIAR_PROFORMA,
    PERMISO_PROFORMA_CITACIONES,
    usuario_tiene_permiso_pro_cit,
)


class ControlFlotaProformaFase1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.actor = User.objects.create_user('actor_fase1')
        cls.control = User.objects.create_user('control_fase1')
        cls.planificador = User.objects.create_user('planificador_fase1')
        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='Terramar Chile SpA', EP_CRUT='77.620.020-4',
            EP_CBASEDATOS='test', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.empresa_sin_acceso = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Aceites SBH', EP_CRUT='96.000.000-0',
            EP_CBASEDATOS='test', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.perfil_control = PERFIL.objects.create(
            US_NID=cls.actor, PR_CCODIGO='CONTROL_FLOTA',
            PR_CNOMBRE='Control Flota', PR_BHABILITADO=True,
        )
        cls.perfil_planificador = PERFIL.objects.create(
            US_NID=cls.actor, PR_CCODIGO='PLANIFICADOR',
            PR_CNOMBRE='Planificador', PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=cls.control, PR_NID=cls.perfil_control,
            PE_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=cls.planificador, PR_NID=cls.perfil_planificador,
            PE_BHABILITADO=True,
        )
        USERS_EMPRESA.objects.create(US_NID=cls.control, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(
            US_NID=cls.planificador, EP_NID=cls.empresa,
        )
        for codigo in (
            PERMISO_INICIAR_PROFORMA,
            PERMISO_PROFORMA_CITACIONES,
        ):
            VISTA.objects.create(
                US_NID=cls.actor, VI_CCODIGO=codigo, VI_CNOMBRE=codigo,
                VI_CDESCRIPCION=codigo, VI_BHABILITADO=True,
            )

    def setUp(self):
        call_command('configurar_acceso_control_flota_proforma')

    def test_control_flota_recibe_solo_permisos_minimos(self):
        self.assertTrue(usuario_tiene_permiso_pro_cit(
            self.control, PERMISO_INICIAR_PROFORMA
        ))
        self.assertTrue(usuario_tiene_permiso_pro_cit(
            self.control, PERMISO_PROFORMA_CITACIONES
        ))
        self.assertEqual(
            set(PERMISO.objects.filter(PR_NID=self.perfil_control).values_list(
                'VI_NID__VI_CCODIGO', flat=True
            )),
            {PERMISO_INICIAR_PROFORMA, PERMISO_PROFORMA_CITACIONES},
        )

    def test_planificador_no_recibe_permisos(self):
        self.assertFalse(usuario_tiene_permiso_pro_cit(
            self.planificador, PERMISO_PROFORMA_CITACIONES
        ))
        self.assertFalse(PERMISO.objects.filter(
            PR_NID=self.perfil_planificador
        ).exists())

    def test_menu_control_flota_muestra_solo_accesos_autorizados(self):
        request = RequestFactory().get('/')
        request.user = self.control
        request.session = {'empresa_id': self.empresa.pk}
        html = render_to_string(
            'includes/component-navbar-inner.html', {'request': request},
            request=request,
        )
        self.assertIn('>Proformas</span>', html)
        self.assertIn('>Citaciones terminadas</a>', html)
        self.assertIn('>Lista de Proformas</a>', html)
        self.assertNotIn('>Extras</a>', html)
        self.assertNotIn('>Manual</a>', html)
        self.assertNotIn('>Borradores</a>', html)

    def test_control_flota_accede_lista_proformas(self):
        self.client.force_login(self.control)
        response = self.client.get(
            reverse('prof_listall'), {'_empresa_id': self.empresa.pk}
        )
        self.assertEqual(response.status_code, 200)

    def test_control_flota_no_puede_consultar_empresa_no_asignada(self):
        self.client.force_login(self.control)
        response = self.client.get(
            reverse('prof_listall'),
            {'_empresa_id': self.empresa_sin_acceso.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_comando_es_idempotente_y_dry_run_no_persiste(self):
        PERMISO.objects.filter(PR_NID=self.perfil_control).delete()
        call_command(
            'configurar_acceso_control_flota_proforma',
            dry_run=True, stdout=StringIO(),
        )
        self.assertFalse(PERMISO.objects.filter(
            PR_NID=self.perfil_control
        ).exists())
        call_command('configurar_acceso_control_flota_proforma')
        call_command('configurar_acceso_control_flota_proforma')
        self.assertEqual(
            PERMISO.objects.filter(PR_NID=self.perfil_control).count(), 2
        )
