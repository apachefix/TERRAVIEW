import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CAMION_PATIO_ADJUNTO,
    CAMION_PATIO_NO_PLANIFICADO,
    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION,
    CITACION,
    EMPRESA,
    OPERACION_PLANTA_LOG,
    PERFIL,
    PERFIL_USUARIO,
    PLANIFICACION,
    SECUENCIA,
    SYSLOGGER,
    USERS_EMPRESA,
)


class CamionPatioEliminarTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = User.objects.create_user(
            username='asistente_recepcion_elimina',
            password='test',
        )
        self.sin_permiso = User.objects.create_user(
            username='usuario_sin_permiso_elimina',
            password='test',
        )
        self.empresas = [self._crear_empresa(1), self._crear_empresa(2)]
        for empresa in self.empresas:
            USERS_EMPRESA.objects.get_or_create(US_NID=self.usuario, EP_NID=empresa)

        perfil = PERFIL.objects.create(
            US_NID=self.usuario,
            PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='ASISTENTE RECEPCION',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.usuario,
            PR_NID=perfil,
            PE_BHABILITADO=True,
        )

    def _crear_empresa(self, empresa_id):
        empresa, _ = EMPRESA.objects.update_or_create(
            pk=empresa_id,
            defaults={
                'EP_CRAZONSOCIAL': f'Empresa {empresa_id}',
                'EP_CRUT': f'7600000{empresa_id}-0',
                'EP_CBASEDATOS': f'empresa_{empresa_id}',
                'EP_CUSUARIOSBD': 'test',
                'EP_CPORT': '1433',
            },
        )
        return empresa

    def _crear_camion(self, empresa=None, **cambios):
        datos = {
            'EP_NID': empresa or self.empresas[0],
            'CPA_CPATENTE': 'ABCD12',
            'CPA_CNOMBRE_CONDUCTOR': 'Conductor Prueba',
            'CPA_CTIPO_DOCUMENTO': CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            'CPA_CESTADO': CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            'US_GUARDIA_ID': self.usuario,
        }
        datos.update(cambios)
        return CAMION_PATIO.objects.create(**datos)

    def _crear_citacion(self, empresa=None):
        empresa = empresa or self.empresas[0]
        calendario = CALENDARIO.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa,
            CA_NDIA=5,
            CA_NMES=10,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=2,
        )
        planificacion = PLANIFICACION.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_NCANTIDADCUPOS=2,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='TEST_ELIMINAR_PATIO',
            SE_CNOMBRE='Prueba eliminar patio',
            SE_BHABILITADO=True,
        )
        citacion = CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa,
            PL_NID=planificacion,
            SC_NID=secuencia,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE',
        )
        return planificacion, citacion

    def _crear_traza(self, camion, citacion=None, planificacion=None):
        return CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
            CPA_NID=camion,
            CI_NID=citacion,
            PL_NID=planificacion,
            EP_NID=camion.EP_NID,
            CPTR_CPATENTE_CONSULTADA=camion.CPA_CPATENTE,
            CPTR_CRESULTADO_BUSQUEDA='MATCH' if citacion else 'SIN_MATCH',
            CPTR_BCARGADO_DESDE_PLANIFICACION=bool(citacion),
            US_NID=self.usuario,
        )

    def _post_eliminar(self, camion, usuario=None, empresa_id=None):
        empresa_id = empresa_id if empresa_id is not None else camion.EP_NID_id
        request = self.factory.post(
            f'/camiones-patio/{camion.pk}/eliminar/',
            {'_empresa_id': empresa_id},
        )
        request.user = usuario or self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=empresa_id):
            return views.CAMION_PATIO_ELIMINAR(request, camion.pk)

    def test_elimina_registro_inicial_en_empresas_1_y_2(self):
        for empresa in self.empresas:
            with self.subTest(empresa=empresa.pk):
                camion = self._crear_camion(
                    empresa=empresa,
                    CPA_CPATENTE=f'EMP{empresa.pk}01',
                )
                traza = self._crear_traza(camion)
                adjunto = CAMION_PATIO_ADJUNTO.objects.create(
                    CPA_NID=camion,
                    CPA_FARCHIVO=f'camiones_patio/{camion.pk}/guia.pdf',
                    CPA_CTIPO_DOCUMENTO=CAMION_PATIO_ADJUNTO.TIPO_GUIA,
                    US_CARGA_ID=self.usuario,
                )

                response = self._post_eliminar(camion)
                payload = json.loads(response.content)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(payload['success'])
                self.assertFalse(CAMION_PATIO.objects.filter(pk=camion.pk).exists())
                self.assertFalse(
                    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.filter(pk=traza.pk).exists()
                )
                self.assertFalse(CAMION_PATIO_ADJUNTO.objects.filter(pk=adjunto.pk).exists())

    def test_bloquea_camion_con_estado_asociado(self):
        camion = self._crear_camion(
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        )

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)['message'],
            views.CAMION_PATIO_MENSAJE_ELIMINACION_BLOQUEADA,
        )
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_bloquea_citacion_asociada_y_no_elimina_planificacion(self):
        planificacion, citacion = self._crear_citacion()
        camion = self._crear_camion(CI_NID=citacion)

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())
        self.assertTrue(CITACION.objects.filter(pk=citacion.pk).exists())
        self.assertTrue(PLANIFICACION.objects.filter(pk=planificacion.pk).exists())

    def test_bloquea_traza_con_avance_operacional(self):
        planificacion, citacion = self._crear_citacion()
        camion = self._crear_camion()
        self._crear_traza(camion, citacion=citacion, planificacion=planificacion)
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario,
            EP_NID=camion.EP_NID,
            PL_NID=planificacion,
            CI_NID=citacion,
            OPL_CPASO='PESAJE_ENTRADA',
            OPL_CPERFIL_RESPONSABLE='ROMANA',
        )

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_traza_inicial_se_elimina_sin_eliminar_citacion_ni_planificacion(self):
        planificacion, citacion = self._crear_citacion()
        camion = self._crear_camion()
        traza = self._crear_traza(camion, citacion=citacion, planificacion=planificacion)

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CAMION_PATIO.objects.filter(pk=camion.pk).exists())
        self.assertFalse(
            CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.filter(pk=traza.pk).exists()
        )
        self.assertTrue(CITACION.objects.filter(pk=citacion.pk).exists())
        self.assertTrue(PLANIFICACION.objects.filter(pk=planificacion.pk).exists())

    def test_bloquea_solicitud_no_planificada(self):
        camion = self._crear_camion()
        solicitud = CAMION_PATIO_NO_PLANIFICADO.objects.create(
            CPA_NID=camion,
            EP_NID=camion.EP_NID,
            US_SOLICITA_ID=self.usuario,
        )

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())
        self.assertTrue(
            CAMION_PATIO_NO_PLANIFICADO.objects.filter(pk=solicitud.pk).exists()
        )

    def test_bloquea_traza_de_asociacion_en_syslogger(self):
        camion = self._crear_camion()
        SYSLOGGER.objects.create(
            US_NID=self.usuario,
            EP_NID=camion.EP_NID,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='PLANIFICACION',
            LOG_COPERACION=views.CAMION_PATIO_LOG_ASOCIACION,
            LOG_CDESCRIPCION='Asociación previa',
            LOG_CADD2=str(camion.pk),
        )

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_usuario_sin_permiso_no_puede_eliminar(self):
        camion = self._crear_camion()

        response = self._post_eliminar(camion, usuario=self.sin_permiso)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_empresa_activa_distinta_no_puede_eliminar(self):
        camion = self._crear_camion(empresa=self.empresas[0])

        response = self._post_eliminar(camion, empresa_id=self.empresas[1].pk)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_get_no_elimina(self):
        camion = self._crear_camion()
        request = self.factory.get(f'/camiones-patio/{camion.pk}/eliminar/')
        request.user = self.usuario

        response = views.CAMION_PATIO_ELIMINAR(request, camion.pk)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=camion.pk).exists())

    def test_auditoria_sobrevive_a_eliminacion(self):
        camion = self._crear_camion(CPA_CPATENTE='AUDI01')
        camion_id = camion.pk

        response = self._post_eliminar(camion)

        self.assertEqual(response.status_code, 200)
        log = SYSLOGGER.objects.get(
            LOG_COPERACION=views.CAMION_PATIO_LOG_ELIMINACION,
            EP_NID=self.empresas[0],
            LOG_CADD1=str(camion_id),
        )
        self.assertEqual(log.LOG_CADD2, 'AUDI01')
        self.assertIn(f'Camión patio #{camion_id}', log.LOG_CDESCRIPCION)
        self.assertIn('estado previo PENDIENTE_ASOCIACION', log.LOG_CDESCRIPCION)
        self.assertFalse(CAMION_PATIO.objects.filter(pk=camion_id).exists())

    def test_frontend_confirma_post_y_retiro_de_tarjeta(self):
        base = Path(__file__).resolve().parents[3]
        listado = (base / 'apps/templates/home/CAMION_PATIO/list.html').read_text(encoding='utf-8')
        javascript = (
            base / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        ).read_text(encoding='utf-8')

        self.assertIn('btn-eliminar-camion-patio', listado)
        self.assertIn('{% if puede_eliminar_camion_patio %}', listado)
        self.assertIn("camion.CPA_CESTADO == 'PENDIENTE_ASOCIACION'", listado)
        self.assertIn('disabled', listado)
        self.assertIn('aria-disabled="true"', listado)
        self.assertIn(
            'No se puede eliminar: camión asociado a una citación o con avance operacional.',
            listado,
        )
        self.assertIn('¿Desea eliminar el camión', javascript)
        self.assertIn("type: 'POST'", javascript)
        self.assertIn("'/camiones-patio/' + id + '/eliminar/'", javascript)
        self.assertIn(".patio-card[data-camion-id=\"' + id + '\"]').remove()", javascript)
