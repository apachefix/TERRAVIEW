from datetime import date, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.home.models import (
    CONDUCTOR,
    DOCUMENTO_CONDUCTOR,
    EMPRESA,
    SOCIONEGOCIO,
    USERS_EMPRESA,
)


class ReemplazoLicenciaFase2Tests(TestCase):
    def test_reemplazo_inhabilita_anterior_y_conserva_historico(self):
        empresa = EMPRESA.objects.create(
            pk=1, EP_CRAZONSOCIAL='TERRAMAR CHILE', EP_CRUT='76000001-1',
            EP_CBASEDATOS='db', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )
        usuario = User.objects.create_superuser('SUPER_FLOTA_2', 'f@example.com', 'test')
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=empresa)
        transporte = SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL='Transporte', SN_CRUT='76111111-1',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        conductor = CONDUCTOR.objects.create(
            EP_NID=empresa, SN_NID=transporte, US_NID=usuario,
            CON_CNOMBRE='Ana', CON_CAPELLIDO='Prueba', CON_CRUT='12345678-9',
        )
        anterior = DOCUMENTO_CONDUCTOR.objects.create(
            EP_NID=empresa, CON_NID=conductor, US_NID=usuario,
            DCON_CTIPO='LICENCIA DE CONDUCIR', DCON_CESTADO='VIGENTE',
            DCON_CRUTADOC='anterior.pdf', DCON_FFECHAEMISION=date.today(),
            DCON_FFECHAVENCIMIENTO=date.today() + timedelta(days=60),
            DCON_BHABILITADO=True,
        )
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = empresa.pk
        session.save()
        with TemporaryDirectory() as carpeta, patch(
            'apps.home.views.DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH', carpeta
        ):
            response = self.client.post(f'/con_doc_addone/{conductor.pk}', {
                'DCON_CTIPO': 'LICENCIA DE CONDUCIR',
                'DCON_FFECHAEMISION': date.today().isoformat(),
                'DCON_FFECHAVENCIMIENTO': (date.today() + timedelta(days=15)).isoformat(),
                'DCON_CRUTADOC': SimpleUploadedFile('nueva.pdf', b'%PDF-1.4 nueva'),
            })
        self.assertEqual(response.status_code, 302)
        anterior.refresh_from_db()
        self.assertFalse(anterior.DCON_BHABILITADO)
        activos = DOCUMENTO_CONDUCTOR.objects.filter(
            CON_NID=conductor, DCON_CTIPO='LICENCIA DE CONDUCIR', DCON_BHABILITADO=True,
        )
        self.assertEqual(activos.count(), 1)
        self.assertEqual(activos.get().DCON_CESTADO, 'POR VENCER')
        self.assertEqual(DOCUMENTO_CONDUCTOR.objects.filter(CON_NID=conductor).count(), 2)
