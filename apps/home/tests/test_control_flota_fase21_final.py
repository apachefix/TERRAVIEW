from contextlib import ExitStack
from datetime import date, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.home.models import (
    CONDUCTOR,
    CONDUCTOR_EMPRESA,
    DOCUMENTO_CONDUCTOR,
    EMPRESA,
    LISTADO_DOCUMENTO,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    SOCIONEGOCIO,
    USERS_EMPRESA,
    VISTA,
)


class AjusteFinalFase21Tests(TestCase):
    def setUp(self):
        self.terramar = self._empresa(1, 'TERRAMAR CHILE')
        self.sbh = self._empresa(2, 'ACEITES SBH')
        self.planificador = self._usuario('PLAN_FINAL', 'PLAN', 'PLANIFICADOR')
        self.control = self._usuario('FLOTA_FINAL', 'CONTROL_FLOTA', 'CONTROL_FLOTA')
        self.superuser = User.objects.create_superuser('ROOT_FINAL', 'root@example.com', 'test')
        for usuario in (self.planificador, self.control, self.superuser):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)
        self.transporte_a = self._transporte(self.terramar, 'Transporte A', '76111111-1')
        self.transporte_b = self._transporte(self.terramar, 'Transporte B', '76222222-2')
        self.transporte_sbh = self._transporte(self.sbh, 'Transporte SBH', '76333333-3')
        for empresa in (self.terramar, self.sbh):
            LISTADO_DOCUMENTO.objects.create(
                EP_NID=empresa, US_NID=self.control,
                LIS_CNOMBREDOCUMENTO='LICENCIA DE CONDUCIR', LIS_CGRUPO='Conductor',
                LIS_CCODIGO='LIC', LIS_CFORMATO='PDF',
                LIS_BOBLIGATORIO=True, LIS_BHABILITADO=True,
            )

    def _empresa(self, pk, nombre):
        return EMPRESA.objects.create(
            pk=pk, EP_CRAZONSOCIAL=nombre, EP_CRUT=f'7600000{pk}-{pk}',
            EP_CBASEDATOS=f'db{pk}', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )

    def _usuario(self, username, codigo, nombre):
        usuario = User.objects.create_user(username=username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=usuario, PR_CCODIGO=codigo, PR_CNOMBRE=nombre, PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True)
        for nombre_vista in ('con_addone', 'con_listall', 'con_listone'):
            vista = VISTA.objects.filter(VI_CNOMBRE=nombre_vista).first()
            if vista is None:
                vista = VISTA.objects.create(
                    US_NID=usuario, VI_CCODIGO=nombre_vista,
                    VI_CNOMBRE=nombre_vista, VI_BHABILITADO=True,
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

    def _activar(self, empresa, usuario=None):
        self.client.force_login(usuario or self.planificador)
        session = self.client.session
        session['empresa_id'] = empresa.pk
        session.save()

    def _historico(self, empresa, transporte, rut, habilitado=True, nombre='Historico'):
        return CONDUCTOR.objects.create(
            EP_NID=empresa, SN_NID=transporte, US_NID=self.control,
            CON_CNOMBRE=nombre, CON_CAPELLIDO='Prueba', CON_CRUT=rut,
            CON_CEMAIL='historico@example.com', CON_CTELEFONO='9239899118',
            CON_BHABILITADO=habilitado,
        )

    def _datos(self, transporte, rut='194551169', nombre='Nuevo'):
        return {
            'SN_NID': str(transporte.pk),
            'CON_CNOMBRE': nombre,
            'CON_CAPELLIDO': 'Prueba',
            'CON_CRUT': rut,
            'CON_CEMAIL': f'{nombre.lower()}@example.com',
            'CON_CTELEFONO': '9239899118',
            'licencia_fecha_emision': (date.today() - timedelta(days=30)).isoformat(),
            'licencia_fecha_vencimiento': (date.today() + timedelta(days=365)).isoformat(),
            'licencia_archivo': SimpleUploadedFile('licencia.pdf', b'%PDF-1.4 prueba'),
            'patente_informada': 'ABCD12',
        }

    def _post_alta(self, empresa, datos, usuario=None):
        self._activar(empresa, usuario)
        with TemporaryDirectory() as terramar_docs, TemporaryDirectory() as sbh_docs, ExitStack() as stack:
            stack.enter_context(patch('apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', terramar_docs))
            stack.enter_context(patch('apps.home.views.DOCUMENTOS_CONDUCTORE_ACEITESS_PATH', sbh_docs))
            return self.client.post(f'/con_addone/?_empresa_id={empresa.pk}', datos)

    def test_rechaza_mismo_rut_normalizado_en_misma_empresa_sin_importar_transporte(self):
        self._historico(self.terramar, self.transporte_a, '19.455.116-9')
        cantidad = CONDUCTOR.objects.count()
        response = self._post_alta(self.terramar, self._datos(self.transporte_b, '194551169'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RUT ya existe. No se puede crear nuevamente el conductor.')
        self.assertContains(response, 'puede utilizarse con otro Transporte en Planificación.')
        self.assertEqual(CONDUCTOR.objects.count(), cantidad)

    def test_reutiliza_conductor_terramar_al_registrarlo_en_sbh(self):
        terramar_original = self._historico(self.terramar, self.transporte_a, '19455116-9')
        response = self._post_alta(self.sbh, self._datos(self.transporte_sbh, '19.455.116-9', 'Sbh'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CONDUCTOR.objects.filter(CON_CRUT='19455116-9').count(), 1)
        self.assertEqual(terramar_original.SN_NID, self.transporte_a)
        self.assertTrue(CONDUCTOR_EMPRESA.objects.filter(
            CON_NID=terramar_original, EP_NID=self.sbh, CEM_BHABILITADO=True,
        ).exists())

    def test_alta_nueva_sbh_crea_membresia_operativa(self):
        response = self._post_alta(self.sbh, self._datos(self.transporte_sbh, '247362584', 'NuevoSbh'))
        self.assertEqual(response.status_code, 302)
        conductor = CONDUCTOR.objects.get(EP_NID=self.sbh, CON_CNOMBRE='NuevoSbh')
        self.assertTrue(CONDUCTOR_EMPRESA.objects.filter(
            CON_NID=conductor, EP_NID=self.sbh, CEM_BHABILITADO=True,
        ).exists())
        licencia = DOCUMENTO_CONDUCTOR.objects.get(CON_NID=conductor, EP_NID=self.sbh)
        self.assertEqual(licencia.DCON_CTIPO, 'LICENCIA DE CONDUCIR')
        self.assertEqual(licencia.DCON_FFECHAEMISION, date.today() - timedelta(days=30))
        self.assertEqual(licencia.DCON_FFECHAVENCIMIENTO, date.today() + timedelta(days=365))

    def test_sbh_sin_tipo_licencia_muestra_error_funcional_claro(self):
        LISTADO_DOCUMENTO.objects.filter(
            EP_NID=self.sbh,
            LIS_CGRUPO__iexact='Conductor',
            LIS_CNOMBREDOCUMENTO__iexact='LICENCIA DE CONDUCIR',
        ).delete()
        response = self._post_alta(self.sbh, self._datos(self.transporte_sbh, '120652842', 'SinTipo'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No existe un tipo documental habilitado para LICENCIA DE CONDUCIR.')
        self.assertFalse(CONDUCTOR.objects.filter(CON_CNOMBRE='SinTipo').exists())

    def test_fechas_licencia_invalidas_se_rechazan_en_sbh(self):
        datos = self._datos(self.transporte_sbh, '131587481', 'FechaInvalida')
        datos['licencia_fecha_emision'] = '2026/01/15'
        response = self._post_alta(self.sbh, datos)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La fecha de emisión de la licencia no es válida.')
        self.assertFalse(CONDUCTOR.objects.filter(CON_CNOMBRE='FechaInvalida').exists())

    def test_duplicados_historicos_no_producen_multiple_objects_ni_se_modifican(self):
        existentes = [
            self._historico(self.terramar, self.transporte_a, rut, nombre=f'Historico{i}')
            for i, rut in enumerate(('194551169', '19455116-9', '19.455.116-9'), start=1)
        ]
        estados_antes = list(CONDUCTOR.objects.filter(pk__in=[x.pk for x in existentes]).values_list('pk', 'SN_NID_id', 'CON_BHABILITADO'))
        response = self._post_alta(self.terramar, self._datos(self.transporte_b))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Existen registros históricos duplicados')
        self.assertEqual(CONDUCTOR.objects.filter(EP_NID=self.terramar).count(), 3)
        self.assertEqual(
            list(CONDUCTOR.objects.filter(pk__in=[x.pk for x in existentes]).values_list('pk', 'SN_NID_id', 'CON_BHABILITADO')),
            estados_antes,
        )

    def test_inhabilitado_bloquea_registro_en_cualquier_empresa(self):
        self._historico(self.terramar, self.transporte_a, '19455116-9', habilitado=False)
        response = self._post_alta(self.terramar, self._datos(self.transporte_b))
        self.assertContains(response, 'se encuentra inhabilitado')
        self.assertEqual(CONDUCTOR.objects.filter(EP_NID=self.terramar).count(), 1)

        response = self._post_alta(self.sbh, self._datos(self.transporte_sbh, nombre='SbhInactivoOtraEmpresa'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'inhabilitado o genérico')
        self.assertFalse(CONDUCTOR.objects.filter(EP_NID=self.sbh, CON_CRUT='19455116-9').exists())

    def test_rut_diferente_y_vacio_crean_normalmente(self):
        self._historico(self.terramar, self.transporte_a, '19455116-9')
        response = self._post_alta(self.terramar, self._datos(self.transporte_b, '247362584', 'Distinto'))
        self.assertEqual(response.status_code, 302)
        response = self._post_alta(self.terramar, self._datos(self.transporte_b, '', 'SinRut'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CONDUCTOR.objects.filter(CON_CNOMBRE='Distinto', CON_CRUT='24736258-4').exists())
        self.assertTrue(CONDUCTOR.objects.filter(CON_CNOMBRE='SinRut', CON_CRUT='').exists())

    def test_ajax_respeta_empresa_activa_y_reporta_duplicados_historicos(self):
        for rut in ('194551169', '19.455.116-9'):
            self._historico(self.terramar, self.transporte_a, rut)
        self._activar(self.terramar)
        response = self.client.get('/api/conductor/validar-rut/?rut=19455116-9&_empresa_id=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cantidad'], 2)
        self.assertTrue(response.json()['duplicados_historicos'])
        response = self.client.get('/api/conductor/validar-rut/?rut=19455116-9&_empresa_id=2')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['existe'])

    def test_control_masivo_solo_se_renderiza_completo_para_permiso_existente(self):
        self._historico(self.terramar, self.transporte_a, '19455116-9')
        self._activar(self.terramar, self.planificador)
        response = self.client.get('/con_listall/?_empresa_id=1')
        self.assertNotContains(response, 'id="deleteSelected"', html=False)
        self.assertContains(response, 'class="form-check-input conductor-checkbox"', html=False)

        self._activar(self.terramar, self.control)
        response = self.client.get('/con_listall/?_empresa_id=1')
        self.assertContains(response, 'id="deleteSelected"', html=False)

        self._activar(self.terramar, self.superuser)
        response = self.client.get('/con_listall/?_empresa_id=1')
        self.assertContains(response, 'id="deleteSelected"', html=False)
        self.assertContains(response, 'Eliminar Seleccionados')
        self.assertContains(response, "$('#deleteSelected').toggle(selectedCount > 0);", html=False)

    def test_planificador_no_adquiere_permiso_destructivo(self):
        conductor = self._historico(self.terramar, self.transporte_a, '19455116-9')
        self._activar(self.terramar, self.planificador)
        response = self.client.post('/con_delete_selected/?_empresa_id=1', {'selectedIds': [conductor.pk]})
        self.assertEqual(response.status_code, 302)
        conductor.refresh_from_db()
        self.assertTrue(conductor.CON_BHABILITADO)
