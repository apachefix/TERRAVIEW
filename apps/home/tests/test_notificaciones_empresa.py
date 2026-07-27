from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.home.models import EMPRESA, NOTIFICACION, USERS_EMPRESA
from apps.home.services.notification_service import (
    crear_notificacion_interna,
    marcar_notificacion_interna_leida,
)


class NotificacionesPorEmpresaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.harinas = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='1-9',
            EP_CBASEDATOS='harinas',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        cls.sbh = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='2-7',
            EP_CBASEDATOS='sbh',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        cls.emisor = User.objects.create_user('emisor_notificaciones')
        cls.solo_harinas = User.objects.create_user('solo_harinas')
        cls.solo_sbh = User.objects.create_user('solo_sbh')
        cls.multiempresa = User.objects.create_user('multiempresa')

        for user, empresa in (
            (cls.emisor, cls.harinas),
            (cls.emisor, cls.sbh),
            (cls.solo_harinas, cls.harinas),
            (cls.solo_sbh, cls.sbh),
            (cls.multiempresa, cls.harinas),
            (cls.multiempresa, cls.sbh),
        ):
            USERS_EMPRESA.objects.create(US_NID=user, EP_NID=empresa)

    def crear_pendiente(self, empresa, numero):
        return crear_notificacion_interna(
            USER_SENDER_ID=self.emisor,
            USER_RECEIVER_ID=self.multiempresa,
            EP_NID=empresa,
            NOT_CCONTENIDO=f'Notificacion {empresa.id}-{numero}',
            NOT_CURL=f'/notificacion/{empresa.id}/{numero}',
        )

    def consultar(self, user, empresa_id):
        self.client.force_login(user)
        return self.client.get(
            reverse('check_notifications'),
            {'_empresa_id': empresa_id},
        )

    def limpiar(self, user, empresa_id):
        self.client.force_login(user)
        return self.client.post(
            reverse('limpiar_notificaciones'),
            {'_empresa_id': empresa_id},
        )

    def test_creacion_exige_receptor_asociado_a_empresa_del_evento(self):
        sbh_multi = crear_notificacion_interna(
            USER_SENDER_ID=self.emisor,
            USER_RECEIVER_ID=self.multiempresa,
            EP_NID=self.sbh,
            NOT_CCONTENIDO='Evento SBH',
            NOT_CURL='/sbh',
        )
        sbh_para_harinas = crear_notificacion_interna(
            USER_SENDER_ID=self.emisor,
            USER_RECEIVER_ID=self.solo_harinas,
            EP_NID=self.sbh,
            NOT_CCONTENIDO='Evento SBH incorrecto',
            NOT_CURL='/sbh-incorrecto',
        )
        harinas_multi = crear_notificacion_interna(
            USER_SENDER_ID=self.emisor,
            USER_RECEIVER_ID=self.multiempresa,
            EP_NID=self.harinas,
            NOT_CCONTENIDO='Evento Harinas',
            NOT_CURL='/harinas',
        )
        harinas_para_sbh = crear_notificacion_interna(
            USER_SENDER_ID=self.emisor,
            USER_RECEIVER_ID=self.solo_sbh,
            EP_NID=self.harinas,
            NOT_CCONTENIDO='Evento Harinas incorrecto',
            NOT_CURL='/harinas-incorrecto',
        )

        self.assertIsNotNone(sbh_multi)
        self.assertIsNone(sbh_para_harinas)
        self.assertIsNotNone(harinas_multi)
        self.assertIsNone(harinas_para_sbh)
        self.assertEqual(NOTIFICACION.objects.count(), 2)

    def test_contador_y_listado_se_aislan_para_usuario_multiempresa(self):
        harinas_ids = [self.crear_pendiente(self.harinas, i).id for i in range(2)]
        sbh_ids = [self.crear_pendiente(self.sbh, i).id for i in range(4)]

        respuesta_harinas = self.consultar(self.multiempresa, self.harinas.id)
        respuesta_sbh = self.consultar(self.multiempresa, self.sbh.id)

        self.assertEqual(respuesta_harinas.status_code, 200)
        self.assertEqual(respuesta_sbh.status_code, 200)
        datos_harinas = respuesta_harinas.json()
        datos_sbh = respuesta_sbh.json()
        self.assertEqual(datos_harinas['empresa_id'], self.harinas.id)
        self.assertEqual(datos_sbh['empresa_id'], self.sbh.id)
        self.assertEqual(len(datos_harinas['notificaciones']), 2)
        self.assertEqual(len(datos_sbh['notificaciones']), 4)
        self.assertSetEqual({fila[0] for fila in datos_harinas['notificaciones']}, set(harinas_ids))
        self.assertSetEqual({fila[0] for fila in datos_sbh['notificaciones']}, set(sbh_ids))

    def test_limpieza_afecta_solo_empresa_activa(self):
        notificaciones_harinas = [self.crear_pendiente(self.harinas, i) for i in range(2)]
        notificaciones_sbh = [self.crear_pendiente(self.sbh, i) for i in range(4)]

        respuesta = self.limpiar(self.multiempresa, self.harinas.id)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['cantidad'], 2)
        self.assertFalse(NOTIFICACION.objects.filter(
            id__in=[n.id for n in notificaciones_harinas], NOT_BREAD=False
        ).exists())
        self.assertEqual(NOTIFICACION.objects.filter(
            id__in=[n.id for n in notificaciones_sbh], NOT_BREAD=False
        ).count(), 4)

        respuesta = self.limpiar(self.multiempresa, self.sbh.id)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['cantidad'], 4)
        self.assertFalse(NOTIFICACION.objects.filter(NOT_BREAD=False).exists())

    def test_usuario_exclusivo_no_puede_consultar_otra_empresa(self):
        self.crear_pendiente(self.sbh, 1)
        respuesta = self.consultar(self.solo_harinas, self.sbh.id)

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(respuesta.json()['notificaciones'], [])

    def test_marcar_leida_exige_empresa_correcta(self):
        notificacion = self.crear_pendiente(self.harinas, 1)

        marcada_en_sbh = marcar_notificacion_interna_leida(
            notificacion_id=notificacion.id,
            receptor=self.multiempresa,
            empresa_id=self.sbh.id,
        )
        notificacion.refresh_from_db()
        self.assertFalse(marcada_en_sbh)
        self.assertFalse(notificacion.NOT_BREAD)

        marcada_en_harinas = marcar_notificacion_interna_leida(
            notificacion_id=notificacion.id,
            receptor=self.multiempresa,
            empresa_id=self.harinas.id,
        )
        notificacion.refresh_from_db()
        self.assertTrue(marcada_en_harinas)
        self.assertTrue(notificacion.NOT_BREAD)
        self.assertIsNotNone(notificacion.NOT_FFECHALEIDO)

    def test_cambio_empresa_no_conserva_notificaciones_de_vista_anterior(self):
        harinas = self.crear_pendiente(self.harinas, 1)
        sbh = self.crear_pendiente(self.sbh, 1)

        respuesta_harinas = self.consultar(self.multiempresa, self.harinas.id)
        respuesta_sbh = self.consultar(self.multiempresa, self.sbh.id)
        respuesta_harinas_nuevamente = self.consultar(self.multiempresa, self.harinas.id)

        self.assertEqual([fila[0] for fila in respuesta_harinas.json()['notificaciones']], [harinas.id])
        self.assertEqual([fila[0] for fila in respuesta_sbh.json()['notificaciones']], [sbh.id])
        self.assertEqual(
            [fila[0] for fila in respuesta_harinas_nuevamente.json()['notificaciones']],
            [harinas.id],
        )
