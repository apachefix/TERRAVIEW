from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from apps.home.models import EMPRESA, PERFIL_USUARIO, SYSLOGGER, USERS_EMPRESA
from apps.home.services.acceso_usuario_service import sincronizar_acceso_usuario
from apps.home.views import usuario_es_asistente_cd


class ClonarAccesoUsuarioTests(TestCase):
    def setUp(self):
        self.terramar, _ = EMPRESA.objects.get_or_create(
            id=1,
            defaults={
                'EP_CRAZONSOCIAL': 'TERRAMAR CHILE', 'EP_CRUT': '1-9',
                'EP_CBASEDATOS': 'test', 'EP_CUSUARIOSBD': 'test', 'EP_CPORT': '5432',
            },
        )
        self.terramar.EP_CRAZONSOCIAL = 'TERRAMAR CHILE'
        self.terramar.save(update_fields=['EP_CRAZONSOCIAL'])
        self.aceites = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-7', EP_CBASEDATOS='test2',
            EP_CUSUARIOSBD='test2', EP_CPORT='5432',
        )
        User = get_user_model()
        self.origen = User.objects.create_user('Asistente_C_D', password='origen')
        self.destino = User.objects.create_user('Asistente_bodega', password='destino')
        USERS_EMPRESA.objects.create(US_NID=self.origen, EP_NID=self.terramar)
        USERS_EMPRESA.objects.create(US_NID=self.origen, EP_NID=self.aceites)
        USERS_EMPRESA.objects.create(US_NID=self.destino, EP_NID=self.aceites)

    def test_dry_run_no_modifica(self):
        resumen = sincronizar_acceso_usuario('Asistente_C_D', 'Asistente_bodega', 1, dry_run=True)
        self.assertTrue(resumen.dry_run)
        self.assertFalse(USERS_EMPRESA.objects.filter(US_NID=self.destino, EP_NID=self.terramar).exists())
        self.assertFalse(PERFIL_USUARIO.objects.filter(US_NID=self.destino).exists())

    def test_menus_operativos_equivalentes_para_rol_normalizado(self):
        sincronizar_acceso_usuario('Asistente_C_D', 'Asistente_bodega', 1)
        factory = RequestFactory()

        def menu(usuario):
            request = factory.get('/')
            request.user = usuario
            request.session = {'empresa_id': 1}
            return render_to_string('includes/component-navbar-inner.html', {'request': request}, request=request)

        origen_html = menu(self.origen)
        destino_html = menu(self.destino)
        for etiqueta in (
            'Ingreso de cami&oacute;n',
            'Control de cami&oacute;n',
            'Operaci&oacute;n Planta',
            'Seguimiento Operacional',
            'Biblioteca de citaciones',
        ):
            self.assertIn(etiqueta, origen_html)
            self.assertIn(etiqueta, destino_html)
    def test_comando_es_idempotente_y_restringe_empresa(self):
        password_hash, email = self.destino.password, self.destino.email
        call_command('clonar_acceso_usuario', '--origen', 'Asistente_C_D', '--destino', 'Asistente_bodega', '--empresa-id', '1', '--confirm')
        call_command('clonar_acceso_usuario', '--origen', 'Asistente_C_D', '--destino', 'Asistente_bodega', '--empresa-id', '1', '--confirm')
        self.destino.refresh_from_db()
        self.assertFalse(self.destino.is_staff)
        self.assertFalse(self.destino.is_superuser)
        self.assertEqual(self.destino.password, password_hash)
        self.assertEqual(self.destino.email, email)
        self.assertEqual(list(USERS_EMPRESA.objects.filter(US_NID=self.destino).values_list('EP_NID_id', flat=True)), [1])
        self.assertTrue(usuario_es_asistente_cd(self.destino))
        self.assertEqual(PERFIL_USUARIO.objects.filter(US_NID=self.destino, PE_BHABILITADO=True).count(), 1)
        self.assertTrue(SYSLOGGER.objects.filter(LOG_COPERACION='CLONAR_ACCESO_USUARIO', LOG_CADD1=str(self.destino.id)).exists())