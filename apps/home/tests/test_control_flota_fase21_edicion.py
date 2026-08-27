from datetime import date, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.home.models import CONDUCTOR, DOCUMENTO_CONDUCTOR, SYSLOGGER
from apps.home.tests.test_control_flota_fase21_final import AjusteFinalFase21Tests


class EdicionModernaConductorFase21Tests(AjusteFinalFase21Tests):
    def _licencia(self, conductor, *, vencimiento=None, habilitada=True, nombre='licencia-vieja.pdf'):
        return DOCUMENTO_CONDUCTOR.objects.create(
            EP_NID=conductor.EP_NID, CON_NID=conductor, US_NID=self.control,
            DCON_CTIPO='LICENCIA DE CONDUCIR', DCON_CESTADO='VIGENTE',
            DCON_CRUTADOC=nombre,
            DCON_FFECHAEMISION=date.today() - timedelta(days=30),
            DCON_FFECHAVENCIMIENTO=vencimiento or date.today() + timedelta(days=365),
            DCON_BHABILITADO=habilitada,
        )

    def _datos_edicion(self, conductor, **cambios):
        datos = {
            'SN_NID': str(conductor.SN_NID_id),
            'CON_CNOMBRE': conductor.CON_CNOMBRE,
            'CON_CAPELLIDO': conductor.CON_CAPELLIDO,
            'CON_CRUT': conductor.CON_CRUT,
            'CON_CEMAIL': conductor.CON_CEMAIL,
            'CON_CTELEFONO': conductor.CON_CTELEFONO,
            'CON_CDIRECCION': conductor.CON_CDIRECCION or '',
            'licencia_fecha_emision': (date.today() - timedelta(days=20)).isoformat(),
            'licencia_fecha_vencimiento': (date.today() + timedelta(days=180)).isoformat(),
        }
        datos.update(cambios)
        return datos

    def test_listado_solo_ver_y_boton_masivo_segun_perfil(self):
        self._historico(self.terramar, self.transporte_a, '19455116-9')
        for usuario, debe_eliminar in (
            (self.planificador, False), (self.control, True), (self.superuser, True),
        ):
            self._activar(self.terramar, usuario)
            response = self.client.get('/con_listall/?_empresa_id=1')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '/con_listone/')
            self.assertNotContains(response, '/con_update/')
            self.assertNotContains(response, 'class="btn btn-danger delete_conductor"', html=False)
            if debe_eliminar:
                self.assertContains(response, 'Eliminar Seleccionados')
            else:
                self.assertNotContains(response, 'id="deleteSelected"', html=False)

    def test_control_flota_deshabilita_conductor_y_planificador_no(self):
        conductor_plan = self._historico(
            self.terramar, self.transporte_a, '19455116-9', nombre='PlanNoElimina',
        )
        self._activar(self.terramar, self.planificador)
        self.client.get(f'/con_delete/{conductor_plan.pk}?_empresa_id=1')
        conductor_plan.refresh_from_db()
        self.assertTrue(conductor_plan.CON_BHABILITADO)

        conductor_control = self._historico(
            self.terramar, self.transporte_a, '24736258-4', nombre='ControlElimina',
        )
        self._activar(self.terramar, self.control)
        self.client.get(f'/con_delete/{conductor_control.pk}?_empresa_id=1')
        conductor_control.refresh_from_db()
        self.assertFalse(conductor_control.CON_BHABILITADO)

        conductor_masivo = self._historico(
            self.terramar, self.transporte_a, '18104277-3', nombre='ControlMasivo',
        )
        self.client.post(
            '/con_delete_selected/?_empresa_id=1', {'selectedIds': [conductor_masivo.pk]},
        )
        conductor_masivo.refresh_from_db()
        self.assertFalse(conductor_masivo.CON_BHABILITADO)

    def test_edicion_moderna_planificador_modifica_datos_fechas_y_mismo_rut(self):
        conductor = self._historico(self.terramar, self.transporte_a, '19.455.116-9')
        licencia = self._licencia(conductor)
        self._activar(self.terramar, self.planificador)
        response = self.client.get(f'/con_update/{conductor.pk}?_empresa_id=1')
        self.assertContains(response, 'Editar datos y licencia')
        self.assertContains(response, 'Descargar licencia')
        self.assertNotContains(response, 'patente_informada')
        self.assertNotContains(response, 'Quitar licencia activa')

        response = self.client.post(
            f'/con_update/{conductor.pk}?_empresa_id=1',
            self._datos_edicion(
                conductor, CON_CRUT='194551169',
                CON_CEMAIL='editado@example.com', CON_CTELEFONO='987654321',
                licencia_fecha_vencimiento=(date.today() + timedelta(days=10)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 302)
        conductor.refresh_from_db()
        licencia.refresh_from_db()
        self.assertEqual(conductor.CON_CRUT, '19455116-9')
        self.assertEqual(conductor.CON_CEMAIL, 'editado@example.com')
        self.assertEqual(conductor.CON_CTELEFONO, '987654321')
        self.assertEqual(licencia.DCON_CESTADO, 'POR VENCER')
        self.assertEqual(licencia.DCON_FFECHAVENCIMIENTO, date.today() + timedelta(days=10))

    def test_edicion_rechaza_rut_de_otro_conductor_misma_empresa(self):
        primero = self._historico(self.terramar, self.transporte_a, '19455116-9')
        segundo = self._historico(self.terramar, self.transporte_b, '24736258-4', nombre='Segundo')
        self._licencia(segundo)
        self._activar(self.terramar, self.planificador)
        response = self.client.post(
            f'/con_update/{segundo.pk}?_empresa_id=1',
            self._datos_edicion(segundo, CON_CRUT='19.455.116-9'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RUT ya existe. No se puede asignar a este conductor.')
        segundo.refresh_from_db()
        self.assertEqual(segundo.CON_CRUT, '24736258-4')
        self.assertTrue(CONDUCTOR.objects.filter(pk=primero.pk).exists())

    def test_planificador_reemplaza_licencia_y_conserva_historico(self):
        conductor = self._historico(self.terramar, self.transporte_a, '19455116-9')
        anterior = self._licencia(conductor)
        datos = self._datos_edicion(conductor)
        datos['licencia_archivo'] = SimpleUploadedFile('licencia-nueva.pdf', b'%PDF nueva')
        self._activar(self.terramar, self.planificador)
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta,
        ):
            response = self.client.post(f'/con_update/{conductor.pk}?_empresa_id=1', datos)
        self.assertEqual(response.status_code, 302)
        anterior.refresh_from_db()
        self.assertFalse(anterior.DCON_BHABILITADO)
        activas = DOCUMENTO_CONDUCTOR.objects.filter(
            CON_NID=conductor, DCON_CTIPO='LICENCIA DE CONDUCIR', DCON_BHABILITADO=True,
        )
        self.assertEqual(activas.count(), 1)
        self.assertNotEqual(activas.get().pk, anterior.pk)
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='REEMPLAZA_LIC_CONDUCTOR', LOG_CADD1=str(conductor.pk),
        ).exists())

    def test_quitar_licencia_solo_control_flota_es_logico_y_deja_faltante(self):
        conductor = self._historico(self.terramar, self.transporte_a, '19455116-9')
        licencia = self._licencia(conductor)
        self._activar(self.terramar, self.planificador)
        self.client.post(
            f'/conductor/{conductor.pk}/licencia/deshabilitar/?_empresa_id=1',
        )
        licencia.refresh_from_db()
        self.assertTrue(licencia.DCON_BHABILITADO)

        self._activar(self.terramar, self.control)
        response = self.client.post(
            f'/conductor/{conductor.pk}/licencia/deshabilitar/?_empresa_id=1',
        )
        self.assertEqual(response.status_code, 302)
        licencia.refresh_from_db()
        self.assertFalse(licencia.DCON_BHABILITADO)
        self.assertTrue(DOCUMENTO_CONDUCTOR.objects.filter(pk=licencia.pk).exists())
        detalle = self.client.get(f'/con_listone/{conductor.pk}?_empresa_id=1')
        self.assertContains(detalle, 'Estado documental: <strong>FALTANTE</strong>', html=True)
        listado = self.client.get('/con_listall/?_empresa_id=1')
        self.assertContains(listado, 'Faltan documentos')
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='DESHABILITA_LIC_COND', LOG_CADD1=str(conductor.pk),
        ).exists())

