from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CITACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    OPERACION_PLANTA_LOG,
    PERFIL,
    PERFIL_USUARIO,
    PLANIFICACION,
    SECUENCIA,
    SYSLOGGER,
    USERS_EMPRESA,
)


class OperacionPlantaTerramarEtapa1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.operador = User.objects.create_user('Operador_romana1', password='test')
        cls.bodega = User.objects.create_user('Asistente_bodega', password='test')
        cls.recepcion = User.objects.create_user('Asistente_Recepción', password='test')
        cls.despacho = User.objects.create_user('Asistente_Despacho', password='test')
        cls.guardia = User.objects.create_user('Guardia_Porteria', password='test')
        cls.ajeno = User.objects.create_user('Operador_romana_ajeno', password='test')

        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='1-9',
            EP_CBASEDATOS='terramar_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        cls.otra_empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='OTRA EMPRESA',
            EP_CRUT='2-7',
            EP_CBASEDATOS='otra_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        for usuario in (cls.operador, cls.bodega, cls.recepcion, cls.despacho, cls.guardia):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.ajeno, EP_NID=cls.otra_empresa)

        perfil_bodega = PERFIL.objects.create(
            US_NID=cls.bodega,
            PR_CCODIGO='ASISTENTE_CD',
            PR_CNOMBRE='ASISTENTE CD',
        )
        PERFIL_USUARIO.objects.create(US_NID=cls.bodega, PR_NID=perfil_bodega)

        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Operacion Terramar',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=5,
            CA_NMES=8,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TERRAMAR',
            SE_CNOMBRE='Recepcion Terramar',
            SE_BHABILITADO=True,
        )
        cls.etapa_legacy = ETAPA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_OPERACION_PLANTA',
            ET_CNOMBRE='Operacion Planta Terramar',
            ET_NCANTIDADMAXIMA=10,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=cls.etapa_legacy,
            SE_NPASO=1,
            SE_BHABILITADO=True,
            SE_BOBLIGATORIO=True,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-TERRAMAR-1',
        )

    def setUp(self):
        SYSLOGGER.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='TEST',
            LOG_CDESCRIPCION='Ingreso autorizado',
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.citacion.id),
        )

    def url(self, nombre):
        return '{}?_empresa_id={}'.format(reverse(nombre, args=[self.citacion.id]), self.empresa.id)

    def guardar(self, usuario, paso):
        self.client.force_login(usuario)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views._ticket_pesaje_obligatorio_guardado', return_value=True):
            return self.client.post(
                self.url('operacion_planta_guardar_paso'),
                {'paso': paso, 'observacion': 'Prueba etapa Terramar'},
            )

    def completar(self, paso, usuario=None, perfil='TEST'):
        return OPERACION_PLANTA_LOG.objects.create(
            US_NID=usuario or self.operador,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO=paso,
            OPL_CPERFIL_RESPONSABLE=perfil,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

    def test_configuracion_exacta_para_ambas_secuencias(self):
        esperado = [
            ('Pesaje Entrada', ['OPERADOR ROMANA']),
            ('Ciclo Descarga', ['ASISTENTE CD']),
            ('Pesaje Salida', ['OPERADOR ROMANA']),
            ('Documentación', ['ASISTENTE RECEPCION']),
            ('Autorizar Salida', ['ASISTENTE DESPACHO']),
            ('Confirmar Salida', ['GUARDIA PORTERIA']),
        ]
        for codigo in ('RECEPCION_TERRAMAR', 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'):
            self.secuencia.SE_CCODIGO = codigo
            nombre, pasos = views.obtener_pasos_operacion_citacion(self.citacion)
            self.assertEqual(nombre, codigo)
            self.assertEqual(pasos, esperado)
            texto = ' '.join(nombre_paso for nombre_paso, _ in pasos).upper()
            for concepto_ajeno in ('ESTANQUE', 'MUESTRA', 'CALIDAD', 'SAP'):
                self.assertNotIn(concepto_ajeno, texto)

    def test_pesaje_entrada_respeta_orden_perfil_empresa_y_duplicado(self):
        denegado = self.guardar(self.bodega, 'Pesaje Entrada')
        self.assertEqual(denegado.status_code, 403, denegado.content)

        self.client.force_login(self.ajeno)
        with patch('apps.home.views.Verificar_empresa', return_value=None):
            ajeno = self.client.post(self.url('operacion_planta_guardar_paso'), {'paso': 'Pesaje Entrada'})
        self.assertEqual(ajeno.status_code, 403, ajeno.content)

        creado = self.guardar(self.operador, 'Pesaje Entrada')
        self.assertEqual(creado.status_code, 200, creado.content)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Ciclo Descarga')
        repetido = self.guardar(self.operador, 'Pesaje Entrada')
        self.assertEqual(repetido.status_code, 409, repetido.content)

    def test_espera_descarga_inicia_con_pesaje_reanuda_y_cierra_al_iniciar_descarga(self):
        inicio_espera = timezone.now() - timedelta(minutes=20)
        with patch('apps.home.views.timezone.now', return_value=inicio_espera):
            creado = self.guardar(self.operador, 'Pesaje Entrada')
        self.assertEqual(creado.status_code, 200, creado.content)

        ciclo = views._payload_ciclo_descarga(self.citacion)
        espera = ciclo['espera_descarga']
        self.assertTrue(espera['iniciada'])
        self.assertFalse(espera['finalizada'])
        self.assertGreaterEqual(espera['duracion_segundos'], 1199)
        inicio_original = espera['inicio']
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO=views.EVENTO_ESPERA_DESCARGA_INICIO,
        ).count(), 1)

        repetido = self.guardar(self.operador, 'Pesaje Entrada')
        self.assertEqual(repetido.status_code, 409, repetido.content)
        self.assertEqual(views._payload_ciclo_descarga(self.citacion)['espera_descarga']['inicio'], inicio_original)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO=views.EVENTO_ESPERA_DESCARGA_INICIO,
        ).count(), 1)

        self.client.force_login(self.bodega)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            pagina = self.client.get(self.url('operacion_planta_citacion'))
        self.assertContains(pagina, 'EN ESPERA DESCARGA')
        self.assertContains(pagina, 'Espera previa a descarga')
        self.assertContains(pagina, 'data-wait-start=')

        inicio_descarga = inicio_espera + timedelta(minutes=20)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=inicio_descarga):
            respuesta = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_descarga'),
                {'tipo_descarga': views.TIPO_DESCARGA_TERRAMAR},
            )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        ciclo = respuesta.json()['ciclo_descarga']
        self.assertTrue(ciclo['espera_descarga']['finalizada'])
        self.assertEqual(ciclo['espera_descarga']['duracion_segundos'], 1200)
        self.assertEqual(respuesta.json()['metadata']['duracion_espera_descarga'], 1200)
        self.assertEqual(ciclo['espera_descarga']['fin'], ciclo['inicio_descarga'])
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO=views.EVENTO_ESPERA_DESCARGA_FIN,
        ).count(), 1)

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            doble = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_descarga'),
                {'tipo_descarga': views.TIPO_DESCARGA_TERRAMAR},
            )
        self.assertEqual(doble.status_code, 409, doble.content)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO=views.EVENTO_ESPERA_DESCARGA_FIN,
        ).count(), 1)

    def test_espera_descarga_no_aplica_a_bodega_externa(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        self.assertFalse(views.es_recepcion_terramar_principal(self.citacion))
        self.assertIsNone(views._registrar_inicio_espera_descarga_terramar(
            self.citacion, self.operador, timezone.now(),
        ))
        self.assertFalse(views._payload_espera_descarga_terramar(self.citacion)['aplicable'])

        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR'
        self.citacion.CI_CTIPO = 'DESPACHO'
        self.assertFalse(views.es_recepcion_terramar_principal(self.citacion))
        self.citacion.CI_CTIPO = 'RECEPCION'
        self.citacion.EP_NID_id = 2
        self.assertFalse(views.es_recepcion_terramar_principal(self.citacion))

    def test_ciclo_descarga_persiste_inicio_fin_duracion_observacion_y_bloquea_dobles(self):
        self.completar('Pesaje Entrada')
        inicio = timezone.now() - timedelta(minutes=17)
        fin = inicio + timedelta(minutes=17)
        self.client.force_login(self.bodega)

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=inicio):
            respuesta_inicio = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_descarga'),
                {'tipo_descarga': views.TIPO_DESCARGA_TERRAMAR},
            )
        self.assertEqual(respuesta_inicio.status_code, 200, respuesta_inicio.content)
        self.assertTrue(respuesta_inicio.json()['ciclo_descarga']['en_proceso'])

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            inicio_repetido = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_descarga'),
                {'tipo_descarga': views.TIPO_DESCARGA_TERRAMAR},
            )
        self.assertEqual(inicio_repetido.status_code, 409, inicio_repetido.content)

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=fin):
            respuesta_fin = self.client.post(
                self.url('ajax_operacion_planta_finalizar_ciclo_descarga'),
                {'observacion': 'Descarga terminada sin novedades.'},
            )
        self.assertEqual(respuesta_fin.status_code, 200, respuesta_fin.content)
        payload = respuesta_fin.json()['ciclo_descarga']
        self.assertTrue(payload['finalizada'])
        self.assertEqual(payload['duracion_segundos'], 1020)
        self.assertEqual(respuesta_fin.json()['metadata']['observacion'], 'Descarga terminada sin novedades.')
        log = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO='Ciclo Descarga')
        self.assertEqual(log.OPL_CPERFIL_RESPONSABLE, 'ASISTENTE CD')
        self.assertIn('Descarga terminada sin novedades.', log.OPL_COBSERVACION)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            fin_repetido = self.client.post(self.url('ajax_operacion_planta_finalizar_ciclo_descarga'))
        self.assertEqual(fin_repetido.status_code, 409, fin_repetido.content)

    def test_ciclo_descarga_rechaza_perfil_incorrecto_y_fin_sin_inicio(self):
        self.completar('Pesaje Entrada')
        self.client.force_login(self.operador)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            inicio = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_descarga'),
                {'tipo_descarga': views.TIPO_DESCARGA_TERRAMAR},
            )
        self.assertEqual(inicio.status_code, 403, inicio.content)

        self.client.force_login(self.bodega)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            fin = self.client.post(self.url('ajax_operacion_planta_finalizar_ciclo_descarga'))
        self.assertEqual(fin.status_code, 400, fin.content)

    def test_pesaje_salida_y_etapas_diferidas_mantienen_el_orden(self):
        self.completar('Pesaje Entrada')
        self.completar('Ciclo Descarga', self.bodega, 'ASISTENTE CD')
        pesaje = self.guardar(self.operador, 'Pesaje Salida')
        self.assertEqual(pesaje.status_code, 200, pesaje.content)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Documentación')

        documentacion = self.guardar(self.recepcion, 'Documentación')
        self.assertEqual(documentacion.status_code, 409, documentacion.content)

        self.client.force_login(self.despacho)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            autorizacion = self.client.post(self.url('ajax_operacion_planta_autorizar_salida'))
        self.assertEqual(autorizacion.status_code, 409, autorizacion.content)

        confirmar_anticipado = self.guardar(self.guardia, 'Confirmar Salida')
        self.assertEqual(confirmar_anticipado.status_code, 409, confirmar_anticipado.content)

    def test_confirmar_salida_solo_guardia_y_despues_de_las_etapas_previas(self):
        for paso in ('Pesaje Entrada', 'Ciclo Descarga', 'Pesaje Salida', 'Documentación', 'Autorizar Salida'):
            self.completar(paso)

        incorrecto = self.guardar(self.operador, 'Confirmar Salida')
        self.assertEqual(incorrecto.status_code, 403, incorrecto.content)
        confirmado = self.guardar(self.guardia, 'Confirmar Salida')
        self.assertEqual(confirmado.status_code, 200, confirmado.content)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertIsNotNone(self.citacion.CI_FFECHATERMINO)
        repetido = self.guardar(self.guardia, 'Confirmar Salida')
        self.assertEqual(repetido.status_code, 409, repetido.content)

    def _preparar_terramar_bodega_externa(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        self.secuencia.SE_CNOMBRE = 'Recepcion Terramar Bodega Externa'
        self.secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])
        self.completar('Pesaje Entrada', self.operador, 'OPERADOR ROMANA')

    def test_bodega_externa_renderiza_carga_seca_y_ciclo_backend(self):
        self._preparar_terramar_bodega_externa()
        self.client.force_login(self.bodega)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            pagina = self.client.get(self.url('operacion_planta_citacion'))
        self.assertEqual(pagina.status_code, 200, pagina.content)
        self.assertContains(pagina, 'DESCARGA EN BODEGA EXTERNA')
        self.assertContains(pagina, 'INICIAR SALIDA A BODEGA EXTERNA')
        self.assertContains(pagina, 'fa-warehouse')
        self.assertNotContains(pagina, 'Descarga Estanque')

        inicio = timezone.now() - timedelta(minutes=2, seconds=5)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=inicio):
            respuesta = self.client.post(
                self.url('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa'),
                {'observacion': 'Salida controlada hacia bodega externa.'},
            )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        payload = respuesta.json()['ciclo_bodega_externa']
        self.assertTrue(payload['en_proceso'])
        self.assertEqual(payload['usuario_inicio'], self.bodega.username)
        self.assertEqual(payload['observacion_inicio'], 'Salida controlada hacia bodega externa.')

        with patch('apps.home.views.timezone.now', return_value=inicio + timedelta(seconds=125)):
            recargado = views._payload_ciclo_terramar_bodega_externa(self.citacion)
        self.assertGreaterEqual(recargado['duracion_segundos'] or 0, 125)
        self.assertEqual(recargado['estado'], 'CAMIÓN EN DESCARGA EXTERNA')

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            repetido = self.client.post(self.url('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(repetido.status_code, 409, repetido.content)

    def test_bodega_externa_solo_guardia_cierra_y_habilita_pesaje_salida(self):
        self._preparar_terramar_bodega_externa()
        inicio = timezone.now() - timedelta(minutes=3)
        self.client.force_login(self.bodega)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=inicio):
            iniciado = self.client.post(self.url('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(iniciado.status_code, 200, iniciado.content)
        self.assertTrue(views.NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=self.guardia,
            EP_NID=self.empresa,
            NOT_CCONTENIDO__icontains='Pendiente confirmar regreso',
            NOT_BREAD=False,
        ).exists())
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            pagina_bodega = self.client.get(self.url('operacion_planta_citacion'))
        self.assertNotContains(pagina_bodega, 'CONFIRMAR REGRESO DE BODEGA EXTERNA')

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            cierre_bodega = self.client.post(self.url('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(cierre_bodega.status_code, 403, cierre_bodega.content)

        self.client.force_login(self.guardia)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            pagina_guardia = self.client.get(self.url('operacion_planta_citacion'))
        self.assertContains(pagina_guardia, 'CONFIRMAR REGRESO DE BODEGA EXTERNA')
        fin = inicio + timedelta(minutes=3, seconds=17)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.timezone.now', return_value=fin):
            cerrado = self.client.post(
                self.url('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa'),
                {'observacion': 'Regreso confirmado en porteria.'},
            )
        self.assertEqual(cerrado.status_code, 200, cerrado.content)
        payload = cerrado.json()['ciclo_bodega_externa']
        self.assertTrue(payload['finalizada'])
        self.assertEqual(payload['usuario_fin'], self.guardia.username)
        self.assertEqual(payload['duracion_segundos'], 197)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')
        self.assertTrue(SYSLOGGER.objects.filter(LOG_CADD1=str(self.citacion.id), LOG_COPERACION='CIERRA_BOD_EXT_TER').exists())

        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            repetido = self.client.post(self.url('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(repetido.status_code, 409, repetido.content)

    def test_bodega_externa_rechaza_cierre_sin_inicio_y_no_cambia_flujo_normal(self):
        self._preparar_terramar_bodega_externa()
        self.client.force_login(self.guardia)
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id):
            sin_inicio = self.client.post(self.url('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(sin_inicio.status_code, 409, sin_inicio.content)

        self.client.force_login(self.ajeno)
        with patch('apps.home.views.Verificar_empresa', return_value=None):
            ajeno = self.client.post(self.url('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa'))
        self.assertEqual(ajeno.status_code, 403, ajeno.content)

        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        self.assertFalse(views.es_recepcion_terramar_bodega_externa_operacion(self.citacion))
        self.assertEqual(views.opciones_tipos_ciclo_descarga('RECEPCION_TERRAMAR')[0]['codigo'], views.TIPO_DESCARGA_TERRAMAR)