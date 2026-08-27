from datetime import date, datetime, time, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CAMION,
    CITACION,
    CONDUCTOR,
    DOCUMENTO_CAMION,
    DOCUMENTO_CONDUCTOR,
    EMPRESA,
    LISTADO_DOCUMENTO,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    PLANIFICACION,
    SECUENCIA,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
    VISTA,
)
from apps.home.services.control_flota_documental import (
    ESTADO_FALTANTE,
    ESTADO_POR_VENCER,
    ESTADO_VENCIDO,
    ESTADO_VIGENTE,
    evaluar_documentos_camion,
    patentes_historicas_conductor,
)


class ControlFlotaFase2Tests(TestCase):
    def setUp(self):
        self.terramar = self._empresa('TERRAMAR CHILE', '1', pk=1)
        self.sbh = self._empresa('ACEITES SBH', '2', pk=2)
        self.control = self._usuario_con_perfil(
            'FLOTA2', 'CONTROL_FLOTA',
            ('PROVEEDOR', 'CONDUCTOR', 'pro_listall', 'pro_listone', 'con_listall', 'con_listone', 'con_addone'),
        )
        self.planificador = self._usuario_con_perfil(
            'PLAN2', 'PLANIFICADOR',
            ('PROVEEDOR', 'CONDUCTOR', 'pro_listall', 'pro_listone', 'con_listall', 'con_listone', 'con_addone', 'pla_addone', 'pla_listone'),
        )
        for usuario in (self.control, self.planificador):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)

        self.transporte_a = self._transporte(self.terramar, 'Transporte A', '76000001-1')
        self.transporte_b = self._transporte(self.terramar, 'Transporte B', '76000002-2')
        self.transporte_sbh = self._transporte(self.sbh, 'Transporte SBH', '76000003-3')
        self.conductor = CONDUCTOR.objects.create(
            EP_NID=self.terramar, SN_NID=self.transporte_b, US_NID=self.control,
            CON_CNOMBRE='Conductor', CON_CAPELLIDO='Cruzado', CON_CRUT='11111111-1',
            CON_CTELEFONO='999999999', CON_BHABILITADO=True,
        )
        self.conductor_sbh = CONDUCTOR.objects.create(
            EP_NID=self.sbh, SN_NID=self.transporte_sbh, US_NID=self.control,
            CON_CNOMBRE='Conductor', CON_CAPELLIDO='SBH', CON_CRUT='22222222-2',
            CON_BHABILITADO=True,
        )
        self.camion = CAMION.objects.create(
            EP_NID=self.terramar, SN_NID=self.transporte_a, US_NID=self.control,
            CAM_CPATENTE='VF9451', CAM_BHABILITADO=True,
        )
        self.camion_alternativo = CAMION.objects.create(
            EP_NID=self.terramar, SN_NID=self.transporte_b, US_NID=self.control,
            CAM_CPATENTE='ALT123', CAM_BHABILITADO=True,
        )
        self.camion_sbh = CAMION.objects.create(
            EP_NID=self.sbh, SN_NID=self.transporte_sbh, US_NID=self.control,
            CAM_CPATENTE='SBH999', CAM_BHABILITADO=True,
        )
        self._catalogos_documentales()

    def _empresa(self, nombre, sufijo, pk):
        return EMPRESA.objects.create(
            pk=pk,
            EP_CRAZONSOCIAL=nombre, EP_CRUT=f'7600000{sufijo}-{sufijo}',
            EP_CBASEDATOS=f'db{sufijo}', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )

    def _usuario_con_perfil(self, username, codigo, vistas):
        usuario = User.objects.create_user(username=username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=usuario, PR_CCODIGO=codigo, PR_CNOMBRE=codigo, PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True)
        for nombre in vistas:
            vista = VISTA.objects.filter(VI_CNOMBRE=nombre).first() or VISTA.objects.create(
                US_NID=usuario, VI_CCODIGO=nombre, VI_CNOMBRE=nombre, VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=usuario, PR_NID=perfil, VI_NID=vista, PE_BHABILITADO=True,
            )
        return usuario

    def _transporte(self, empresa, nombre, rut):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL=nombre, SN_CRUT=rut,
            SN_CTIPO='S', SN_BHABILITADO=True,
        )

    def _catalogos_documentales(self):
        for grupo, nombres in (
            ('Conductor', ('LICENCIA DE CONDUCIR',)),
            ('Camion', ('REVISION TECNICA', 'PERMISO CIRCULACION', 'POLIZA', 'ANOTACIONES')),
        ):
            for indice, nombre in enumerate(nombres):
                LISTADO_DOCUMENTO.objects.create(
                    EP_NID=self.terramar, US_NID=self.control,
                    LIS_CNOMBREDOCUMENTO=nombre, LIS_CGRUPO=grupo,
                    LIS_CCODIGO=f'{grupo[:3]}-{indice}', LIS_CFORMATO='PDF',
                    LIS_BOBLIGATORIO=True, LIS_BHABILITADO=True,
                )

    def _activar_cliente(self, usuario, empresa=None):
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = (empresa or self.terramar).pk
        session.save()

    def _documento_camion(self, tipo, vencimiento):
        return DOCUMENTO_CAMION.objects.create(
            EP_NID=self.terramar, CA_NID=self.camion, US_NID=self.control,
            DCA_CTIPO=tipo, DCA_CESTADO='OK', DCA_CRUTADOC=f'{tipo}.pdf',
            DCA_FFECHAEMISION=date.today() - timedelta(days=30),
            DCA_FFECHAVENCIMIENTO=vencimiento, DCA_BHABILITADO=True,
        )

    def test_estados_documentales_cuatro_casos_y_no_bloqueo(self):
        hoy = date.today()
        self._documento_camion('REVISION TECNICA', hoy)
        self._documento_camion('PERMISO CIRCULACION', hoy + timedelta(days=15))
        self._documento_camion('POLIZA', hoy + timedelta(days=60))
        estados = {d['documento']: d['estado'] for d in evaluar_documentos_camion(self.camion)}
        self.assertEqual(estados['REVISION TECNICA'], ESTADO_VENCIDO)
        self.assertEqual(estados['PERMISO CIRCULACION'], ESTADO_POR_VENCER)
        self.assertEqual(estados['POLIZA'], ESTADO_VIGENTE)
        self.assertEqual(estados['ANOTACIONES'], ESTADO_FALTANTE)
        self._activar_cliente(self.control)
        response = self.client.get(f'/control-flota/camiones/{self.camion.pk}/documentos/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    def test_alta_rapida_con_licencia_y_transporte_preseleccionado(self):
        self._activar_cliente(self.control)
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta
        ):
            response = self.client.post(
                f'/control-flota/transportes/{self.transporte_a.pk}/conductores/alta-rapida/',
                {
                    'CON_CNOMBRE': 'Nueva', 'CON_CAPELLIDO': 'Conductora',
                    'CON_CRUT': '247362584', 'CON_CTELEFONO': '987654321',
                    'CON_CEMAIL': 'nueva@example.com', 'CON_CDIRECCION': 'Planta',
                    'licencia_fecha_emision': '2026-01-01',
                    'licencia_fecha_vencimiento': '2027-01-01',
                    'licencia_archivo': SimpleUploadedFile('licencia.pdf', b'%PDF-1.4 prueba'),
                },
            )
        self.assertEqual(response.status_code, 302)
        conductor = CONDUCTOR.objects.get(CON_CRUT='24736258-4')
        self.assertEqual(conductor.SN_NID, self.transporte_a)
        self.assertEqual(conductor.EP_NID, self.terramar)
        self.assertEqual(conductor.US_NID, self.control)
        licencia = DOCUMENTO_CONDUCTOR.objects.get(CON_NID=conductor, DCON_BHABILITADO=True)
        self.assertEqual(licencia.DCON_CTIPO, 'LICENCIA DE CONDUCIR')
        self.assertEqual(licencia.US_NID, self.control)

    def test_patentes_historicas_agrupadas_y_alternativa_no_exige_transporte(self):
        calendario = CALENDARIO.objects.create(
            US_NID=self.control, EP_NID=self.terramar, CA_NDIA=1, CA_NMES=1,
            CA_NANO=2026, CA_NCANTIDADCUPOS=10,
        )
        plan = PLANIFICACION.objects.create(
            US_NID=self.control, EP_NID=self.terramar, CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=2,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=self.control, EP_NID=self.terramar, SE_CTIPO='RECEPCION',
            SE_CCODIGO='TEST', SE_CNOMBRE='Test', SE_BHABILITADO=True,
        )
        for dia in (1, 2):
            CITACION.objects.create(
                US_NID=self.control, EP_NID=self.terramar, PL_NID=plan,
                SC_NID=secuencia, CON_NID=self.conductor, CA_NID=self.camion,
                CI_FFECHACITACION=timezone.make_aware(datetime(2026, 1, dia, 8, 0)),
                CI_CESTADO='CREADO', CI_NCUPO=dia, CI_BHABILITADO=True,
            )
        historial = patentes_historicas_conductor(self.conductor)
        self.assertEqual(historial[0]['patente'], 'VF9451')
        self.assertEqual(historial[0]['cantidad_usos'], 2)
        self._activar_cliente(self.planificador)
        response = self.client.get('/control-flota/camiones/buscar/', {'q': 'ALT123'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['id'], self.camion_alternativo.pk)

    def test_planificador_ve_conductor_cruzado_sin_permisos_nuevos_tarifa_ruta(self):
        self._activar_cliente(self.planificador)
        response = self.client.get('/ajax/conductores-ingreso-camion/', {
            'empresa_id': self.terramar.pk,
            'transportista_id': self.transporte_a.pk,
            'estricto_empresa': '1',
        })
        self.assertEqual(response.status_code, 200)
        ids = [item['conductor_id'] for item in response.json()['results']]
        self.assertIn(self.conductor.pk, ids)
        perfil = PERFIL_USUARIO.objects.get(US_NID=self.planificador).PR_NID
        permisos = set(PERMISO.objects.filter(PR_NID=perfil).values_list('VI_NID__VI_CNOMBRE', flat=True))
        self.assertNotIn('tg_listall', permisos)
        self.assertNotIn('rt_listall', permisos)

    def test_menu_planificador_expone_tripulacion_sin_administracion_flota(self):
        self._activar_cliente(self.planificador)
        response = self.client.get('/pro_listall/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Control Flota')
        self.assertContains(response, 'Transporte')
        self.assertContains(response, 'Conductores')
        self.assertNotContains(response, 'Tarifas Globales')
        self.assertNotContains(response, 'Conductores eliminados')
        self.assertNotContains(response, 'Camiones eliminados')

    def test_aislamiento_empresa_y_log_sin_spam_por_refresco(self):
        self._activar_cliente(self.control)
        self.assertEqual(
            self.client.get(f'/control-flota/conductores/{self.conductor_sbh.pk}/patentes-documentos/').status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f'/control-flota/camiones/{self.camion_sbh.pk}/documentos/').status_code,
            404,
        )
        self.assertEqual(SYSLOGGER.objects.count(), 0)
        self.client.get(f'/control-flota/camiones/{self.camion.pk}/documentos/')
        self.assertEqual(SYSLOGGER.objects.count(), 0)
        datos = {'tipo': 'CAMION', 'entidad_id': self.camion.pk, 'modulo': 'PLANIFICACION'}
        primera = self.client.post('/control-flota/alertas-documentales/', datos)
        segunda = self.client.post('/control-flota/alertas-documentales/', datos)
        self.assertEqual(primera.status_code, 200)
        self.assertGreater(primera.json()['logs_creados'], 0)
        self.assertEqual(segunda.json()['logs_creados'], 0)
        self.assertTrue(segunda.json()['operacion_permitida'])

