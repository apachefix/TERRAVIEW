from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.home.models import (
    CAMION,
    CONDUCTOR,
    DOCUMENTO_CONDUCTOR,
    EMPRESA,
    LISTADO_DOCUMENTO,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
    VISTA,
)


class ControlFlotaFase21Tests(TestCase):
    def setUp(self):
        self.terramar = EMPRESA.objects.create(
            pk=1, EP_CRAZONSOCIAL='TERRAMAR CHILE', EP_CRUT='76000001-1',
            EP_CBASEDATOS='db1', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )
        self.sbh = EMPRESA.objects.create(
            pk=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='76000002-2',
            EP_CBASEDATOS='db2', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )
        self.control = self._usuario('FLOTA21', 'CONTROL_FLOTA')
        self.planificador = self._usuario('PLAN21', 'PLANIFICADOR')
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.terramar, SN_CRAZONSOCIAL='Transporte Uno',
            SN_CRUT='76111111-1', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        self.otro_transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.terramar, SN_CRAZONSOCIAL='Transporte Dos',
            SN_CRUT='76222222-2', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        LISTADO_DOCUMENTO.objects.create(
            EP_NID=self.terramar, US_NID=self.control,
            LIS_CNOMBREDOCUMENTO='LICENCIA DE CONDUCIR',
            LIS_CGRUPO='Conductor', LIS_CCODIGO='LIC', LIS_CFORMATO='PDF',
            LIS_BOBLIGATORIO=True, LIS_BHABILITADO=True,
        )

    def _usuario(self, username, codigo):
        usuario = User.objects.create_user(username=username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=usuario, PR_CCODIGO=codigo,
            PR_CNOMBRE=codigo, PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True)
        for nombre in ('PROVEEDOR', 'CONDUCTOR', 'pro_listall', 'pro_listone',
                       'con_listall', 'con_listone', 'con_addone'):
            vista = VISTA.objects.filter(VI_CNOMBRE=nombre).first() or VISTA.objects.create(
                US_NID=usuario, VI_CCODIGO=nombre,
                VI_CNOMBRE=nombre, VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=usuario, PR_NID=perfil, VI_NID=vista, PE_BHABILITADO=True,
            )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)
        return usuario

    def _activar(self, usuario, empresa=None):
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = (empresa or self.terramar).pk
        session.save()

    def _datos(self, nombre='Nueva', vencimiento=None, **extra):
        datos = {
            'CON_CNOMBRE': nombre,
            'CON_CAPELLIDO': 'Conductora',
            'CON_CTELEFONO': '987654321',
            'CON_CEMAIL': f'{nombre.lower()}@example.com',
            'licencia_fecha_emision': (date.today() - timedelta(days=30)).isoformat(),
            'licencia_fecha_vencimiento': (
                vencimiento or date.today() + timedelta(days=365)
            ).isoformat(),
            'licencia_archivo': SimpleUploadedFile('licencia.pdf', b'%PDF-1.4 prueba'),
        }
        datos.update(extra)
        return datos

    def _crear(self, usuario, datos, carpeta, empresa=None):
        self._activar(usuario, empresa)
        with patch('apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta):
            return self.client.post(
                f'/control-flota/transportes/{self.transporte.pk}/conductores/alta-rapida/',
                datos,
            )

    def test_control_flota_y_planificador_pueden_crear_conductor_con_licencia(self):
        with TemporaryDirectory() as carpeta:
            for usuario, nombre in ((self.control, 'Control'), (self.planificador, 'Planifica')):
                response = self._crear(usuario, self._datos(nombre), carpeta)
                self.assertEqual(response.status_code, 302)
                conductor = CONDUCTOR.objects.get(CON_CNOMBRE=nombre)
                self.assertEqual(conductor.SN_NID, self.transporte)
                self.assertEqual(conductor.EP_NID, self.terramar)
                self.assertEqual(conductor.US_NID, usuario)
                self.assertEqual(conductor.CON_NPERIODO_EXTRA, 10)
                self.assertTrue(DOCUMENTO_CONDUCTOR.objects.filter(
                    CON_NID=conductor, EP_NID=self.terramar, DCON_BHABILITADO=True,
                ).exists())

    def test_rechaza_sin_archivo_o_sin_vencimiento(self):
        with TemporaryDirectory() as carpeta:
            sin_archivo = self._datos('SinArchivo')
            sin_archivo.pop('licencia_archivo')
            self._crear(self.control, sin_archivo, carpeta)
            sin_vencimiento = self._datos('SinVence')
            sin_vencimiento.pop('licencia_fecha_vencimiento')
            self._crear(self.control, sin_vencimiento, carpeta)
        self.assertFalse(CONDUCTOR.objects.filter(CON_CNOMBRE__in=['SinArchivo', 'SinVence']).exists())

    def test_campos_operacionales_requeridos_y_rut_direccion_opcionales(self):
        with TemporaryDirectory() as carpeta:
            for campo in ('CON_CNOMBRE', 'CON_CAPELLIDO', 'CON_CTELEFONO', 'CON_CEMAIL'):
                datos = self._datos(f'Falta{campo[-3:]}')
                datos[campo] = ''
                self._crear(self.control, datos, carpeta)
            self._crear(self.control, self._datos('SinRutDireccion'), carpeta)
        self.assertEqual(CONDUCTOR.objects.count(), 1)
        conductor = CONDUCTOR.objects.get()
        self.assertEqual(conductor.CON_CRUT, '')
        self.assertIn(conductor.CON_CDIRECCION, (None, ''))

    def test_estados_vigente_por_vencer_y_vencido_no_bloquean(self):
        casos = (
            ('Vigente', date.today() + timedelta(days=60), 'VIGENTE'),
            ('PorVencer', date.today() + timedelta(days=15), 'POR VENCER'),
            ('Vencida', date.today() - timedelta(days=1), 'VENCIDO'),
        )
        with TemporaryDirectory() as carpeta:
            for nombre, vencimiento, esperado in casos:
                self._crear(self.control, self._datos(nombre, vencimiento), carpeta)
                documento = DOCUMENTO_CONDUCTOR.objects.get(CON_NID__CON_CNOMBRE=nombre)
                self.assertEqual(documento.DCON_CESTADO, esperado)
                self.assertTrue(documento.DCON_BHABILITADO)

    def test_patente_informada_solo_crea_log_y_se_muestra_separada(self):
        camion = CAMION.objects.create(
            EP_NID=self.terramar, SN_NID=self.otro_transporte, US_NID=self.control,
            CAM_CPATENTE='ABC123', CAM_BHABILITADO=True,
        )
        cantidad_camiones = CAMION.objects.count()
        with TemporaryDirectory() as carpeta:
            self._crear(
                self.planificador,
                self._datos('ConPatente', patente_informada='abc123'),
                carpeta,
            )
        conductor = CONDUCTOR.objects.get(CON_CNOMBRE='ConPatente')
        camion.refresh_from_db()
        self.assertEqual(CAMION.objects.count(), cantidad_camiones)
        self.assertEqual(camion.SN_NID, self.otro_transporte)
        log = SYSLOGGER.objects.get(LOG_CADD1=str(conductor.pk))
        self.assertEqual(log.LOG_COPERACION, 'REG_PATENTE_CONDUCTOR')
        self.assertEqual(log.LOG_CADD2, 'ABC123')
        self.assertEqual(
            log.LOG_CDESCRIPCION,
            'Patente informada al registrar conductor. '
            'No representa asociaci\u00f3n permanente conductor-cami\u00f3n.',
        )
        respuesta = self.client.get(
            f'/control-flota/conductores/{conductor.pk}/patentes-documentos/'
        ).json()
        self.assertEqual(respuesta['patente_informada']['patente'], 'ABC123')
        self.assertFalse(respuesta['patente_informada']['uso_operacional_registrado'])
        self.assertEqual(respuesta['patentes'], [])

    def test_falla_documental_revierte_bd_y_elimina_archivo(self):
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTO_CONDUCTOR.objects.create',
            side_effect=RuntimeError('fallo documental'),
        ):
            self._crear(self.control, self._datos('Rollback'), carpeta)
            self.assertFalse(any(Path(carpeta).rglob('*.*')))
        self.assertFalse(CONDUCTOR.objects.filter(CON_CNOMBRE='Rollback').exists())

    def test_formulario_visual_y_aislamiento_empresa(self):
        self._activar(self.planificador)
        response = self.client.get(f'/pro_listone/{self.transporte.pk}')
        self.assertContains(response, 'Transporte:')
        self.assertContains(response, 'Patente con la que se presenta')
        self.assertContains(response, 'name="licencia_archivo" required', html=False)
        self.assertContains(response, 'name="licencia_fecha_vencimiento" required', html=False)
        self.assertNotContains(response, 'Período de extras')

        with TemporaryDirectory() as carpeta:
            respuesta = self._crear(
                self.control, self._datos('EmpresaIncorrecta'), carpeta, self.sbh,
            )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(CONDUCTOR.objects.filter(CON_CNOMBRE='EmpresaIncorrecta').exists())
