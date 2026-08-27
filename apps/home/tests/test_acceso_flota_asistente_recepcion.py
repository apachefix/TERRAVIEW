import importlib
from pathlib import Path

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import (
    CONDUCTOR,
    CONDUCTOR_EMPRESA,
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    SOCIONEGOCIO,
    USERS_EMPRESA,
    USERS_EXTENSION,
    VISTA,
)


class AccesoFlotaAsistenteRecepcionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.terramar = self._empresa(1, 'Terramar Chile')
        self.sbh = self._empresa(2, 'Aceites SBH')
        self.asistente = User.objects.create_user('recepcion_operativa', password='test')
        self.sin_permiso = User.objects.create_user('usuario_sin_permiso', password='test')
        self.control = User.objects.create_user('MTAPIA', password='test')

        self.perfil_asistente = PERFIL.objects.create(
            US_NID=self.asistente,
            PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='Asistente de Recepción',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.asistente, PR_NID=self.perfil_asistente, PE_BHABILITADO=True,
        )
        self.perfil_recepcionista = PERFIL.objects.create(
            US_NID=self.asistente,
            PR_CCODIGO='REC',
            PR_CNOMBRE='Recepcionista',
            PR_BHABILITADO=True,
        )
        self.perfil_control = PERFIL.objects.create(
            US_NID=self.control,
            PR_CCODIGO='CONTROL_FLOTA',
            PR_CNOMBRE='Control Flota',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.control, PR_NID=self.perfil_control, PE_BHABILITADO=True,
        )

        for usuario in (self.asistente, self.control):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)
        USERS_EMPRESA.objects.create(US_NID=self.sin_permiso, EP_NID=self.terramar)

        for codigo in ('PROVEEDOR', 'CONDUCTOR', 'TARIFAS', 'RUTAS'):
            vista = VISTA.objects.create(
                US_NID=self.control, VI_CCODIGO=codigo,
                VI_CNOMBRE=codigo, VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=self.control, PR_NID=self.perfil_control,
                VI_NID=vista, PE_BHABILITADO=True,
            )

        self.transporte_terramar = self._transporte(self.terramar, 'Transporte Terramar')
        self.transporte_sbh = self._transporte(self.sbh, 'Transporte SBH')
        self.conductor_terramar = self._conductor(self.terramar, self.transporte_terramar)
        self.conductor_sbh = self._conductor(self.sbh, self.transporte_sbh)
        CONDUCTOR_EMPRESA.objects.create(
            CON_NID=self.conductor_sbh, EP_NID=self.sbh, US_NID=self.asistente,
        )

    def _empresa(self, pk, nombre):
        return EMPRESA.objects.create(
            id=pk, EP_CRAZONSOCIAL=nombre, EP_CRUT=f'7600000{pk}-{pk}',
            EP_CBASEDATOS=f'db{pk}', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )

    def _transporte(self, empresa, nombre):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL=nombre,
            SN_CRUT=f'7611111{empresa.pk}-{empresa.pk}',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )

    def _conductor(self, empresa, transporte):
        return CONDUCTOR.objects.create(
            EP_NID=empresa, SN_NID=transporte, US_NID=self.asistente,
            CON_CNOMBRE='Conductor', CON_CAPELLIDO=empresa.EP_CRAZONSOCIAL,
            CON_CRUT=f'1711111{empresa.pk}-{empresa.pk}', CON_BHABILITADO=True,
        )

    def _menu(self, usuario, empresa_id):
        request = self.factory.get('/', {'_empresa_id': empresa_id})
        request.user = usuario
        request.session = {'empresa_id': empresa_id}
        return render_to_string(
            'includes/component-navbar-inner.html', {'request': request}, request=request,
        )

    def test_menu_asistente_es_control_flota_limitado_en_ep1_y_ep2(self):
        for empresa_id in (1, 2):
            with self.subTest(empresa_id=empresa_id):
                menu = self._menu(self.asistente, empresa_id)
                self.assertIn('Control Flota', menu)
                self.assertIn('Transporte', menu)
                self.assertIn('Conductores', menu)
                self.assertNotIn('>Camiones<', menu)
                self.assertNotIn('Tarifas Globales', menu)
                self.assertNotIn('Tarifas inhabilitadas', menu)
                self.assertNotIn('>Rutas<', menu)
                self.assertIn(f'/pro_listall/?_empresa_id={empresa_id}', menu)
                self.assertIn(f'/con_listall/?_empresa_id={empresa_id}', menu)

    def test_backend_asistente_permite_solo_lectura_transporte_y_alta_conductor(self):
        self.client.force_login(self.asistente)
        for empresa_id, transporte, conductor in (
            (1, self.transporte_terramar, self.conductor_terramar),
            (2, self.transporte_sbh, self.conductor_sbh),
        ):
            with self.subTest(empresa_id=empresa_id):
                query = {'_empresa_id': empresa_id}
                self.assertEqual(self.client.get('/pro_listall/', query).status_code, 200)
                self.assertEqual(self.client.get(f'/pro_listone/{transporte.pk}', query).status_code, 200)
                self.assertEqual(self.client.get('/con_listall/', query).status_code, 200)
                self.assertEqual(self.client.get(f'/con_listone/{conductor.pk}', query).status_code, 200)
                alta = self.client.get('/con_addone/', query)
                self.assertEqual(alta.status_code, 200)
                self.assertContains(alta, 'Transporte')

        for ruta in ('/cam_listall/', '/tg_listall/', '/rut_listall/'):
            respuesta = self.client.get(ruta, {'_empresa_id': 1})
            self.assertEqual(respuesta.status_code, 302)
            self.assertEqual(respuesta.url, '/')

    def test_asistente_accede_a_control_camiones_patio_en_ep1_y_ep2(self):
        self.client.force_login(self.asistente)
        for empresa_id in (1, 2):
            with self.subTest(empresa_id=empresa_id):
                respuesta = self.client.get(
                    '/camiones-patio/control/', {'_empresa_id': empresa_id},
                )
                self.assertEqual(respuesta.status_code, 200)

    def test_home_asistente_carga_con_empresa_activa(self):
        self.client.force_login(self.asistente)
        respuesta = self.client.get('/', {'_empresa_id': 2})
        self.assertEqual(respuesta.status_code, 200)
        for clave in (
            'citacion_en_proceso', 'citacion_terminado',
            'camiones_en_operacion', 'camiones_item',
        ):
            self.assertIn(clave, respuesta.context)

    def test_empresa_no_asignada_y_usuario_sin_perfil_no_acceden_al_alta(self):
        self.client.force_login(self.asistente)
        USERS_EMPRESA.objects.filter(US_NID=self.asistente, EP_NID=self.sbh).delete()
        respuesta = self.client.get('/con_addone/', {'_empresa_id': 2})
        self.assertEqual(respuesta.status_code, 302)

        self.client.force_login(self.sin_permiso)
        respuesta = self.client.get('/con_addone/', {'_empresa_id': 1})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, '/')

    def test_control_flota_conserva_menu_completo(self):
        relacion_control_antes = list(
            PERFIL_USUARIO.objects.filter(US_NID=self.control).values_list(
                'id', 'PR_NID_id', 'PE_BHABILITADO',
            )
        )
        empresas_control_antes = list(
            USERS_EMPRESA.objects.filter(US_NID=self.control).values_list('EP_NID_id', flat=True)
        )
        menu = self._menu(self.control, 1)
        self.assertIn('Control Flota', menu)
        self.assertIn('>Camiones<', menu)
        self.assertIn('Tarifas Globales', menu)
        self.assertIn('Tarifas inhabilitadas', menu)
        self.assertIn('>Rutas<', menu)
        self.assertEqual(
            relacion_control_antes,
            list(PERFIL_USUARIO.objects.filter(US_NID=self.control).values_list(
                'id', 'PR_NID_id', 'PE_BHABILITADO',
            )),
        )
        self.assertEqual(
            empresas_control_antes,
            list(USERS_EMPRESA.objects.filter(US_NID=self.control).values_list('EP_NID_id', flat=True)),
        )

    def test_registro_camion_contiene_atajo_contextual_por_empresa(self):
        plantilla = Path(
            'apps/templates/home/CAMION_PATIO/registrar.html'
        ).read_text(encoding='utf-8')
        self.assertIn('id="patio_registrar_conductor"', plantilla)
        self.assertIn('?_empresa_id={{ empresa_activa_id }}', plantilla)
        self.assertIn("terramar && manual", plantilla)
        self.assertIn("toggleClass('d-none', !(terramar && manual))", plantilla)
        self.assertIn("const mostrarManual = !terramar", plantilla)
        self.assertIn(".prop('disabled', terramar)", plantilla)
        self.assertIn("id=\"patio_conductor_pendiente_aviso\"", plantilla)

    def test_0116_no_provisiona_rec_para_usuario_legacy_y_preserva_rec_existente(self):
        legacy = User.objects.create_user('legacy_recepcionista', password='test')
        USERS_EXTENSION.objects.create(US_NID=legacy, UX_IS_RECEPCIONISTA=True)
        USERS_EMPRESA.objects.create(US_NID=legacy, EP_NID=self.terramar)
        USERS_EMPRESA.objects.create(US_NID=legacy, EP_NID=self.sbh)
        otro_perfil = PERFIL.objects.create(
            US_NID=legacy, PR_CCODIGO='OTRO', PR_CNOMBRE='Otro perfil', PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=legacy, PR_NID=otro_perfil, PE_BHABILITADO=True)
        rec_preexistente = PERFIL_USUARIO.objects.create(
            US_NID=legacy, PR_NID=self.perfil_recepcionista, PE_BHABILITADO=True,
        )
        empresas_antes = list(
            USERS_EMPRESA.objects.filter(US_NID=legacy).values_list('EP_NID_id', flat=True)
        )
        migracion = importlib.import_module(
            'apps.home.migrations.0116_perfil_recepcionista_legacy'
        )

        migracion.neutralizar_provision_legacy(django_apps, None)
        migracion.neutralizar_provision_legacy(django_apps, None)

        relaciones_rec = PERFIL_USUARIO.objects.filter(
            US_NID=legacy, PR_NID=self.perfil_recepcionista,
        )
        self.assertEqual(relaciones_rec.count(), 1)
        self.assertEqual(relaciones_rec.get().id, rec_preexistente.id)
        self.assertTrue(PERFIL_USUARIO.objects.filter(US_NID=legacy, PR_NID=otro_perfil).exists())
        self.assertEqual(
            empresas_antes,
            list(USERS_EMPRESA.objects.filter(US_NID=legacy).values_list('EP_NID_id', flat=True)),
        )

    def test_0117_crea_perfil_funcional_idempotente_sin_asignar_usuarios_legacy(self):
        legacy = User.objects.create_user('legacy_sin_membresia', password='test')
        USERS_EXTENSION.objects.create(US_NID=legacy, UX_IS_RECEPCIONISTA=True)
        PERFIL_USUARIO.objects.filter(PR_NID=self.perfil_asistente).delete()
        self.perfil_asistente.delete()
        migracion = importlib.import_module('apps.home.migrations.0117_perfil_asistente_recepcion')

        migracion.crear_perfil_asistente_recepcion(django_apps, None)
        migracion.crear_perfil_asistente_recepcion(django_apps, None)

        perfiles = PERFIL.objects.filter(PR_CCODIGO='ASISTENTE_RECEPCION')
        self.assertEqual(perfiles.count(), 1)
        self.assertEqual(perfiles.get().PR_CNOMBRE, 'Asistente de Recepción')
        self.assertFalse(PERFIL_USUARIO.objects.filter(US_NID=legacy, PR_NID=perfiles.get()).exists())

    def test_terramar_conductor_no_registrado_se_rechaza_y_cliente_sigue_manual(self):
        self.client.force_login(self.asistente)
        respuesta_terramar = self.client.post('/camiones-patio/registrar/', {
            '_empresa_id': 2,
            'transporte_a_cargo': 'TERRAMAR',
            'conductor_manual': '1',
            'conductor_nombre_manual': 'No debe guardarse',
            'rut_conductor': '11111111-1',
            'telefono_conductor': '912345678',
        })
        self.assertEqual(respuesta_terramar.status_code, 400)
        self.assertContains(
            respuesta_terramar,
            'Debe registrar al conductor en el maestro antes de continuar con Transporte Terramar.',
            status_code=400,
        )

        plantilla = Path('apps/templates/home/CAMION_PATIO/registrar.html').read_text(encoding='utf-8')
        self.assertIn("const mostrarManual = !terramar", plantilla)
        self.assertIn("$('#bloque_conductor_cliente').toggleClass('d-none', !mostrarManual)", plantilla)
        self.assertIn("$('#bloque_rut_conductor, #bloque_telefono_codigo_pais, #bloque_telefono_conductor')", plantilla)
        self.assertIn(".toggleClass('d-none', manual)", plantilla)
        self.assertIn(".prop('disabled', terramar)", plantilla)
        self.assertIn("$('#patio_telefono_conductor, #patio_telefono_codigo_pais')", plantilla)
        self.assertIn(".prop('disabled', manual)", plantilla)
        self.assertIn("$('#patio_telefono_conductor').val(item.telefono || '')", plantilla)
        vista = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertNotIn("telefono_conductor = telefono_maestro['local_number']", vista)
        self.assertNotIn("telefono_codigo_pais = telefono_maestro['country_code']", vista)
        self.assertIn("Debe seleccionar un conductor registrado del maestro.", Path('apps/home/views.py').read_text(encoding='utf-8'))
