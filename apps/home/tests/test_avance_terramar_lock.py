from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    DATO_OPERACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    NOTIFICACION,
    PLANIFICACION,
    SECUENCIA,
    SYSLOGGER,
    USERS_EMPRESA,
)
from apps.home.views import asegurar_notificaciones_guardia_porteria_pendientes


class AvanceTerramarPostFunctionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='asistente_bodega_lock_test', password='test-pass'
        )
        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='1-9',
            EP_CBASEDATOS='terramar_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Calendario prueba lock',
            CA_NDIA=4,
            CA_NMES=8,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=1,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_NCANTIDADCUPOS=1,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TERRAMAR',
            SE_CNOMBRE='Recepcion Terramar',
            SE_BHABILITADO=True,
        )
        cls.etapa_bodega = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_VALIDACION_DOCUMENTOS',
            ET_CNOMBRE='Validacion documentos',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        cls.etapa_guardia = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_INGRESO_GUARDIA',
            ET_CNOMBRE='Ingreso Guardia',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        cls.etapa_guardia_porteria = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_GUARDIA_PORTERIA',
            ET_CNOMBRE='Guardia Porteria',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        for paso, etapa in ((3, cls.etapa_bodega), (4, cls.etapa_guardia), (5, cls.etapa_guardia_porteria)):
            DETALLE_SECUENCIA.objects.create(
                US_NID=cls.usuario,
                EP_NID=cls.empresa,
                SC_NID=cls.secuencia,
                ET_NID=etapa,
                SE_NPASO=paso,
                SE_BHABILITADO=True,
            )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            SN_NID=None,
            CON_NID=None,
            CA_NID=None,
            PRO_NID=None,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
        )
        ETAPA_LOG.objects.create(
            CI_NID=cls.citacion,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=cls.etapa_bodega,
            US_INICIO_ID=cls.usuario,
            EL_FFECHAINICIO=timezone.now(),
        )
        cls.guardia = get_user_model().objects.create_user(
            username='guardia_terramar_lock_test', password='test-pass'
        )
        cls.guardia_porteria = get_user_model().objects.create_user(
            username='guardia_porteria_terramar_lock_test', password='test-pass'
        )
        cls.guardia_porteria_ajeno = get_user_model().objects.create_user(
            username='guardia_porteria_sin_empresa_lock_test', password='test-pass'
        )
        USERS_EMPRESA.objects.create(US_NID=cls.guardia, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.guardia_porteria, EP_NID=cls.empresa)

    def post_avance(self):
        return self.client.post(
            reverse('pla_citacion_estanque_avanzar', args=[self.citacion.id]),
            {'solicitud_ingreso_descarga': '1'},
        )

    def test_post_con_relaciones_nullable_null_no_lanza_not_supported_error(self):
        self.client.force_login(self.usuario)
        with patch('apps.home.views.usuario_es_asistente_cd', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.obtener_guardias_relacionados_citacion', return_value=[]):
            response = self.post_avance()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn(b'FOR UPDATE', response.content)
        self.assertTrue(DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO='BOD_SOLICITUD_INGRESO_DESCARGA',
        ).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_BOD_GUARDIA',
            LOG_CADD1=str(self.citacion.id),
        ).exists())

        with patch('apps.home.views.usuario_es_asistente_cd', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            repetido = self.post_avance()
        self.assertEqual(repetido.status_code, 409, repetido.content)

    def test_guardia_procesa_terramar_notifica_porteria_y_segundo_envio_es_409(self):
        self.client.force_login(self.usuario)
        with patch('apps.home.views.usuario_es_asistente_cd', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.obtener_valores_ingreso_camion', return_value={'patente': 'ABCD12'}), \
             patch('apps.home.views.obtener_guardias_relacionados_citacion', return_value=[self.guardia]):
            avance = self.post_avance()
        self.assertEqual(avance.status_code, 200, avance.content)

        notificacion_guardia = NOTIFICACION.objects.get(USER_RECEIVER_ID=self.guardia)
        self.assertIn('debe ingresar a planta', notificacion_guardia.NOT_CCONTENIDO)
        self.assertIn('ABCD12', notificacion_guardia.NOT_CCONTENIDO)
        self.assertIn(f'Citación: {self.citacion.id}', notificacion_guardia.NOT_CCONTENIDO)
        self.assertTrue(notificacion_guardia.NOT_CURL.endswith(f'?citacion={self.citacion.id}'))
        self.assertEqual(notificacion_guardia.EP_NID_id, self.empresa.id)

        self.client.force_login(self.guardia)
        endpoint = reverse('pla_citacion_enviar_guardia_porteria', args=[self.citacion.id])
        parches = (
            patch('apps.home.views.usuario_es_guardia', return_value=True),
            patch('apps.home.views.usuario_es_guardia_porteria', return_value=False),
            patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id),
            patch('apps.home.views.obtener_valores_ingreso_camion', return_value={'patente': 'ABCD12'}),
            patch('apps.home.views.obtener_usuarios_guardia_porteria', return_value=[self.guardia_porteria, self.guardia_porteria_ajeno]),
        )
        with parches[0], parches[1], parches[2], parches[3], parches[4]:
            response = self.client.post(endpoint)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(self.citacion.id)
        ).count(), 1)
        notificacion_guardia.refresh_from_db()
        self.assertTrue(notificacion_guardia.NOT_BREAD)

        notificacion_porteria = NOTIFICACION.objects.get(USER_RECEIVER_ID=self.guardia_porteria)
        self.assertIn('debe ingresar a planta', notificacion_porteria.NOT_CCONTENIDO)
        self.assertIn('Autorizar ingreso físico', notificacion_porteria.NOT_CCONTENIDO)
        self.assertIn('ABCD12', notificacion_porteria.NOT_CCONTENIDO)
        self.assertIn(f'Citación: {self.citacion.id}', notificacion_porteria.NOT_CCONTENIDO)
        self.assertEqual(notificacion_porteria.EP_NID_id, self.empresa.id)
        self.assertFalse(NOTIFICACION.objects.filter(USER_RECEIVER_ID=self.guardia_porteria_ajeno).exists())
        with patch('apps.home.views.usuario_es_guardia_porteria', return_value=True):
            asegurar_notificaciones_guardia_porteria_pendientes(self.guardia_porteria, self.empresa.id)
            asegurar_notificaciones_guardia_porteria_pendientes(self.guardia_porteria, self.empresa.id)
        self.assertEqual(NOTIFICACION.objects.filter(USER_RECEIVER_ID=self.guardia_porteria).count(), 1)

        parches = (
            patch('apps.home.views.usuario_es_guardia', return_value=True),
            patch('apps.home.views.usuario_es_guardia_porteria', return_value=False),
            patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id),
            patch('apps.home.views.obtener_valores_ingreso_camion', return_value={'patente': 'ABCD12'}),
            patch('apps.home.views.obtener_usuarios_guardia_porteria', return_value=[self.guardia_porteria]),
        )
        with parches[0], parches[1], parches[2], parches[3], parches[4]:
            repetido = self.client.post(endpoint)
        self.assertEqual(repetido.status_code, 409, repetido.content)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(self.citacion.id)
        ).count(), 1)
        self.assertEqual(NOTIFICACION.objects.filter(USER_RECEIVER_ID=self.guardia_porteria).count(), 1)

    def test_terramar_no_acepta_envia_cd_next_como_operacion_previa(self):
        SYSLOGGER.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_COPERACION='ENVIA_CD_NEXT',
            LOG_CADD1=str(self.citacion.id),
        )
        self.client.force_login(self.guardia)
        endpoint = reverse('pla_citacion_enviar_guardia_porteria', args=[self.citacion.id])
        with patch('apps.home.views.usuario_es_guardia', return_value=True), \
             patch('apps.home.views.usuario_es_guardia_porteria', return_value=False), \
             patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.obtener_valores_ingreso_camion', return_value={'patente': 'ABCD12'}):
            response = self.client.post(endpoint)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(self.citacion.id)
        ).exists())
