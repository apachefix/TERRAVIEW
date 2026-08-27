from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase
from django.template.loader import render_to_string
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.home import views
from apps.home.models import (
    CAMION,
    COMUNA,
    CONDUCTOR,
    DOCUMENTO_CAMION,
    DOCUMENTO_CONDUCTOR,
    DOCUMENTO_SOCIONEGOCIO,
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    PROVINCIA,
    REGION,
    RUTA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
    USERS_EMPRESA,
    USERS_EXTENSION,
    VISTA,
)


class ControlFlotaIsolationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.terramar = self._empresa('Terramar', '1')
        self.sbh = self._empresa('Aceites SBH', '2')
        self.user = User.objects.create_user(
            username='MTAPIA', password='test', first_name='Matías', last_name='Tapia'
        )
        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=self.terramar)
        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=self.sbh)
        self.profile = PERFIL.objects.create(
            US_NID=self.user,
            PR_CCODIGO='CONTROL_FLOTA',
            PR_CNOMBRE='Control Flota',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.user, PR_NID=self.profile, PE_BHABILITADO=True
        )
        for codigo in (
            'PROVEEDOR', 'pro_listall', 'pro_listone',
            'CONDUCTOR', 'con_listall', 'con_listone', 'con_addone',
            'cam_listall', 'cam_listone', 'cam_addone',
            'TARIFAS', 'tg_listall', 'tg_addone',
            'RUTAS', 'rt_listall', 'rt_addone',
        ):
            vista = VISTA.objects.create(
                US_NID=self.user,
                VI_CCODIGO=codigo,
                VI_CNOMBRE=codigo,
                VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=self.user,
                PR_NID=self.profile,
                VI_NID=vista,
                PE_BHABILITADO=True,
            )

        self.transportes = {
            1: self._transporte(self.terramar, '76.000.001-1'),
            2: self._transporte(self.sbh, '76.000.002-2'),
        }
        self.camiones = {
            1: CAMION.objects.create(
                EP_NID=self.terramar, SN_NID=self.transportes[1], US_NID=self.user,
                CAM_CPATENTE='TT1111',
            ),
            2: CAMION.objects.create(
                EP_NID=self.sbh, SN_NID=self.transportes[2], US_NID=self.user,
                CAM_CPATENTE='SS2222',
            ),
        }
        self.conductores = {
            1: CONDUCTOR.objects.create(
                EP_NID=self.terramar, SN_NID=self.transportes[1], US_NID=self.user,
                CON_CNOMBRE='Terramar', CON_CAPELLIDO='Uno', CON_CRUT='11-1',
            ),
            2: CONDUCTOR.objects.create(
                EP_NID=self.sbh, SN_NID=self.transportes[2], US_NID=self.user,
                CON_CNOMBRE='SBH', CON_CAPELLIDO='Dos', CON_CRUT='22-2',
            ),
        }
        self.rutas = {1: self._ruta(self.terramar, 'RT-1'), 2: self._ruta(self.sbh, 'RS-2')}
        self.tarifas = {
            numero: TARIFA_GLOBAL.objects.create(
                EP_NID=empresa,
                RUT_NID=self.rutas[numero],
                SN_NID=self.transportes[numero],
                US_NID=self.user,
                TAR_NVALOR=1000,
                TAR_CNOMBRETARIFA=f'Tarifa {numero}',
                TAR_CTIPOTARIFA='NORMAL',
                TAR_CDIVISA='CLP',
            )
            for numero, empresa in ((1, self.terramar), (2, self.sbh))
        }
        self.documentos = {
            'camion': DOCUMENTO_CAMION.objects.create(
                EP_NID=self.sbh, CA_NID=self.camiones[2], US_NID=self.user,
                DCA_CTIPO='PADRON', DCA_CESTADO='OK', DCA_CRUTADOC='no-existe.pdf',
                DCA_FFECHAEMISION=date.today(), DCA_FFECHAVENCIMIENTO=date.today(),
            ),
            'conductor': DOCUMENTO_CONDUCTOR.objects.create(
                EP_NID=self.sbh, CON_NID=self.conductores[2], US_NID=self.user,
                DCON_CTIPO='LICENCIA', DCON_CESTADO='OK', DCON_CRUTADOC='no-existe.pdf',
                DCON_FFECHAEMISION=date.today(), DCON_FFECHAVENCIMIENTO=date.today(),
            ),
            'transporte': DOCUMENTO_SOCIONEGOCIO.objects.create(
                EP_NID=self.sbh, SN_NID=self.transportes[2], US_NID=self.user,
                DSN_CTIPO='RUT', DSN_CESTADO='OK', DSN_CRUTADOC='no-existe.pdf',
            ),
        }

    def _empresa(self, nombre, sufijo):
        return EMPRESA.objects.create(
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=f'76.000.00{sufijo}-{sufijo}',
            EP_CBASEDATOS=f'db{sufijo}',
            EP_CUSUARIOSBD='user',
            EP_CPORT='5432',
        )

    def _transporte(self, empresa, rut):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa,
            SN_CRAZONSOCIAL=f'Transporte {empresa.pk}',
            SN_CRUT=rut,
            SN_CTIPO='S',
        )

    def _ruta(self, empresa, codigo):
        region = REGION.objects.create(RG_CNOMBRE=codigo, RG_CCODIGO=codigo)
        provincia = PROVINCIA.objects.create(
            RG_NID=region, PV_CNOMBRE=codigo, PV_CCODIGO=codigo
        )
        comuna = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE=codigo, COM_CCODIGO=codigo
        )
        return RUTA.objects.create(
            EP_NID=empresa,
            RG_NID_INICIO=region,
            PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna,
            RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia,
            COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1,
            RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE=codigo,
            RUT_CCODIGO=codigo,
        )

    def _request(self, empresa_id, path='/'):
        request = self.factory.get(path)
        request.user = self.user
        SessionMiddleware(lambda req: HttpResponse()).process_request(request)
        request.session['empresa_id'] = empresa_id
        request.session.save()
        return request

    def test_menu_control_flota_usa_rotulos_nuevos_y_nombre_visible(self):
        request = self._request(self.terramar.pk)
        html = render_to_string(
            'includes/component-navbar-inner.html', {'request': request}, request=request
        )
        self.assertIn('Control Flota', html)
        self.assertIn('Transporte', html)
        request._messages = FallbackStorage(request)
        self.assertIn('Tripulaci&oacute;n y camiones', html)
        self.assertIn('Tarifas Globales', html)
        self.assertIn('Rutas', html)
        self.assertNotIn('pcoded-mtext">Proveedor', html)

    def test_listado_conductores_cambia_con_empresa_activa(self):
        for empresa_id, esperado, excluido in (
            (self.terramar.pk, self.conductores[1], self.conductores[2]),
            (self.sbh.pk, self.conductores[2], self.conductores[1]),
        ):
            request = self._request(empresa_id, '/con_listall/')
            with patch('apps.home.views.render', return_value=HttpResponse('ok')) as mocked:
                response = views.CONDUCTOR_LISTALL(request)
            self.assertEqual(response.status_code, 200)
            queryset = mocked.call_args.args[2]['object_list']
            self.assertIn(esperado, queryset)
            self.assertNotIn(excluido, queryset)

    def test_pk_cruzado_es_rechazado_en_todo_el_dominio(self):
        request = self._request(self.terramar.pk)
        casos = (
            (CAMION, self.camiones[2]),
            (CONDUCTOR, self.conductores[2]),
            (SOCIONEGOCIO, self.transportes[2]),
            (RUTA, self.rutas[2]),
            (TARIFA_GLOBAL, self.tarifas[2]),
            (DOCUMENTO_CAMION, self.documentos['camion']),
            (DOCUMENTO_CONDUCTOR, self.documentos['conductor']),
            (DOCUMENTO_SOCIONEGOCIO, self.documentos['transporte']),
        )
        for modelo, objeto in casos:
            with self.subTest(modelo=modelo.__name__):
                with self.assertRaises(Http404):
                    views._objeto_control_flota_o_404(request, modelo, id=objeto.pk)

        request.session['empresa_id'] = self.sbh.pk
        request.session.save()
        for modelo, objeto in casos:
            with self.subTest(modelo=modelo.__name__, empresa='SBH'):
                encontrado = views._objeto_control_flota_o_404(request, modelo, id=objeto.pk)
                self.assertEqual(encontrado.pk, objeto.pk)

    def test_deshabilitacion_cruzada_no_modifica_el_camion(self):
        superuser = User.objects.create_superuser('super-flota', 's@example.com', 'test')
        USERS_EXTENSION.objects.create(US_NID=superuser)
        USERS_EMPRESA.objects.create(US_NID=superuser, EP_NID=self.terramar)
        request = self.factory.get(f'/cam_delete/{self.camiones[2].pk}')
        request.user = superuser
        SessionMiddleware(lambda req: HttpResponse()).process_request(request)
        request.session['empresa_id'] = self.terramar.pk
        request.session.save()
        request._messages = FallbackStorage(request)
        response = views.CAMION_DELETE(request, self.camiones[2].pk)
        self.assertEqual(response.status_code, 302)
        self.camiones[2].refresh_from_db()
        self.assertTrue(self.camiones[2].CAM_BHABILITADO)

    def test_usuario_sin_control_flota_no_accede_a_alta_tarifa(self):
        outsider = User.objects.create_user('CARANEDA', password='test')
        USERS_EXTENSION.objects.create(US_NID=outsider, UX_IS_PROFORMA=True)
        USERS_EMPRESA.objects.create(US_NID=outsider, EP_NID=self.terramar)
        request = self.factory.get('/tg_addone/')
        request.user = outsider
        SessionMiddleware(lambda req: HttpResponse()).process_request(request)
        request.session['empresa_id'] = self.terramar.pk
        request.session.save()
        request._messages = FallbackStorage(request)
        response = views.TARIFA_GLOBAL_ADDONE(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')


    def test_flujo_mtapia_sin_users_extension_terramar_sbh_y_logout(self):
        self.assertFalse(USERS_EXTENSION.objects.filter(US_NID=self.user).exists())
        self.assertTrue(self.client.login(username='MTAPIA', password='test'))

        helpers_inicio = (
            patch('apps.home.views.get_camiones_planta_operacion', return_value=[0]),
            patch(
                'apps.home.views.get_camiones_dia_semana_mes',
                return_value=[(None, 0), (None, 0), (None, 0)],
            ),
            patch('apps.home.views.get_camiones_item', return_value=[]),
            patch('apps.home.views.get_cupos_por_proveedor', return_value=[]),
            patch(
                'apps.home.views.get_citacion_enproceso_terminado',
                return_value=[[0, 0]],
            ),
            patch(
                'apps.home.views.get_citacion_terminada_noproforma',
                return_value=[0],
            ),
            patch('apps.home.views.get_citacion_por_etapa', return_value=[]),
            patch('apps.home.views.get_citacion_por_secuencia', return_value=[]),
            patch(
                'apps.home.views.obtener_top_camiones_tiempo_planta',
                return_value=[],
            ),
        )

        for empresa, conductor, camion, tarifa, ruta in (
            (self.terramar, self.conductores[1], self.camiones[1], self.tarifas[1], self.rutas[1]),
            (self.sbh, self.conductores[2], self.camiones[2], self.tarifas[2], self.rutas[2]),
        ):
            session = self.client.session
            session['empresa_id'] = empresa.pk
            session.save()
            for helper in helpers_inicio:
                helper.start()
            try:
                self.assertEqual(self.client.get('/').status_code, 200)
            finally:
                for helper in reversed(helpers_inicio):
                    helper.stop()

            respuestas = {
                'transporte': self.client.get('/pro_listall/'),
                'conductores': self.client.get('/con_listall/'),
                'camiones': self.client.get('/cam_listall/'),
                'tarifas': self.client.get('/tg_listall/'),
                'rutas': self.client.get('/rut_listall/'),
            }
            self.assertTrue(all(r.status_code == 200 for r in respuestas.values()))
            self.assertContains(respuestas['transporte'], 'Lista de transportes')
            self.assertContains(respuestas['conductores'], conductor.CON_CRUT)
            self.assertContains(respuestas['camiones'], camion.CAM_CPATENTE)
            self.assertContains(respuestas['tarifas'], tarifa.TAR_CNOMBRETARIFA)
            self.assertContains(respuestas['rutas'], ruta.RUT_CNOMBRE)

        self.assertEqual(self.client.post('/logout/').status_code, 302)
        self.assertEqual(self.client.get('/').status_code, 302)





    def test_nombre_usuario_visible_mantiene_fallback_tecnico(self):
        from apps.home.templatetags.permission_filters import nombre_usuario_visible

        self.assertEqual(nombre_usuario_visible(self.user), 'Matías Tapia')
        self.user.first_name = ''
        self.user.last_name = ''
        self.assertEqual(nombre_usuario_visible(self.user), 'MTAPIA')
