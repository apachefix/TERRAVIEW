from datetime import date, timedelta
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


class AltaConductorRealConAddoneTests(TestCase):
    def setUp(self):
        self.terramar = EMPRESA.objects.create(
            pk=1, EP_CRAZONSOCIAL='TERRAMAR CHILE', EP_CRUT='76000001-1',
            EP_CBASEDATOS='db1', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )
        self.sbh = EMPRESA.objects.create(
            pk=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='76000002-2',
            EP_CBASEDATOS='db2', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )
        self.planificador = self._usuario('JNOVOA_TEST', 'PLAN', 'PLANIFICADOR')
        self.control = self._usuario('FLOTA_ADD', 'CONTROL_FLOTA', 'CONTROL_FLOTA')
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.terramar, SN_CRAZONSOCIAL='Transporte TERRAMAR',
            SN_CRUT='76111111-1', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        self.transporte_sbh = SOCIONEGOCIO.objects.create(
            EP_NID=self.sbh, SN_CRAZONSOCIAL='Transporte SBH',
            SN_CRUT='76222222-2', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        LISTADO_DOCUMENTO.objects.create(
            EP_NID=self.terramar, US_NID=self.control,
            LIS_CNOMBREDOCUMENTO='LICENCIA DE CONDUCIR', LIS_CGRUPO='Conductor',
            LIS_CCODIGO='LIC', LIS_CFORMATO='PDF',
            LIS_BOBLIGATORIO=True, LIS_BHABILITADO=True,
        )

    def _usuario(self, username, codigo, nombre):
        usuario = User.objects.create_user(username=username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=usuario, PR_CCODIGO=codigo,
            PR_CNOMBRE=nombre, PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True)
        for nombre_vista in ('con_addone', 'con_listone'):
            vista = VISTA.objects.filter(VI_CNOMBRE=nombre_vista).first() or VISTA.objects.create(
                US_NID=usuario, VI_CCODIGO=nombre_vista,
                VI_CNOMBRE=nombre_vista, VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=usuario, PR_NID=perfil, VI_NID=vista, PE_BHABILITADO=True,
            )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
        return usuario

    def _activar(self, usuario):
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = self.terramar.pk
        session.save()

    def _datos(self, **cambios):
        datos = {
            'SN_NID': str(self.transporte.pk),
            'CON_CNOMBRE': 'Juan',
            'CON_CAPELLIDO': 'Prueba',
            'CON_CRUT': '247362584',
            'CON_CEMAIL': 'juan.prueba@example.com',
            'CON_CTELEFONO': '9239899118',
            'licencia_fecha_emision': (date.today() - timedelta(days=30)).isoformat(),
            'licencia_fecha_vencimiento': (date.today() + timedelta(days=365)).isoformat(),
            'licencia_archivo': SimpleUploadedFile('licencia_conducir.pdf', b'%PDF-1.4 prueba'),
            'patente_informada': 'abcd12',
        }
        datos.update(cambios)
        return datos

    def test_get_planificador_muestra_alta_completa_y_filtra_transporte(self):
        self._activar(self.planificador)
        response = self.client.get('/con_addone/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Licencia de conducir')
        self.assertContains(response, 'name="licencia_archivo"', html=False)
        self.assertContains(response, 'name="licencia_fecha_vencimiento"', html=False)
        self.assertContains(response, 'Patente con la que se presenta')
        self.assertContains(response, '247362584')
        self.assertContains(response, self.transporte.SN_CRAZONSOCIAL)
        self.assertNotContains(response, self.transporte_sbh.SN_CRAZONSOCIAL)
        self.assertNotContains(response, 'Período de extras')

    def test_post_planificador_normaliza_y_guarda_todo_en_una_transaccion(self):
        self._activar(self.planificador)
        cantidad_camiones = CAMION.objects.count()
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta,
        ):
            response = self.client.post('/con_addone/', self._datos())
        self.assertEqual(response.status_code, 302)
        conductor = CONDUCTOR.objects.get(CON_CNOMBRE='Juan')
        self.assertEqual(conductor.CON_CRUT, '24736258-4')
        self.assertEqual(conductor.CON_CTELEFONO, '9239899118')
        self.assertEqual(conductor.CON_CCODIGO_PAIS_TELEFONO, '+56')
        self.assertEqual(conductor.SN_NID, self.transporte)
        documento = DOCUMENTO_CONDUCTOR.objects.get(CON_NID=conductor)
        self.assertEqual(documento.DCON_CESTADO, 'VIGENTE')
        self.assertTrue(documento.DCON_BHABILITADO)
        detalle = self.client.get(f'/con_listone/{conductor.pk}')
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'LICENCIA DE CONDUCIR')
        log = SYSLOGGER.objects.get(LOG_CADD1=str(conductor.pk))
        self.assertEqual(log.LOG_COPERACION, 'REG_PATENTE_CONDUCTOR')
        self.assertEqual(log.LOG_CADD2, 'ABCD12')
        self.assertEqual(CAMION.objects.count(), cantidad_camiones)

    def test_control_flota_puede_guardar_licencia_vencida(self):
        self._activar(self.control)
        datos = self._datos(
            CON_CNOMBRE='Flota', CON_CRUT='', patente_informada='',
            licencia_fecha_vencimiento=(date.today() - timedelta(days=1)).isoformat(),
        )
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta,
        ):
            response = self.client.post('/con_addone/', datos)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            DOCUMENTO_CONDUCTOR.objects.get(CON_NID__CON_CNOMBRE='Flota').DCON_CESTADO,
            'VENCIDO',
        )

    def test_errores_especificos_sin_licencia_sin_vencimiento_y_rut_invalido(self):
        self._activar(self.planificador)
        sin_archivo = self._datos(CON_CNOMBRE='SinArchivo')
        sin_archivo.pop('licencia_archivo')
        response = self.client.post('/con_addone/', sin_archivo)
        self.assertContains(response, 'Debe adjuntar la licencia de conducir.')

        sin_vencimiento = self._datos(CON_CNOMBRE='SinVencimiento')
        sin_vencimiento.pop('licencia_fecha_vencimiento')
        response = self.client.post('/con_addone/', sin_vencimiento)
        self.assertContains(response, 'Debe ingresar la fecha de vencimiento de la licencia.')

        invalido = self._datos(CON_CNOMBRE='RutInvalido', CON_CRUT='247362585')
        response = self.client.post('/con_addone/', invalido)
        self.assertContains(response, 'RUT inválido. Revise el número ingresado.')
        self.assertFalse(CONDUCTOR.objects.exists())
