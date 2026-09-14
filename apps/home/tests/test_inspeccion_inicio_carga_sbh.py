from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string, get_template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CITACION, DATO_OPERACION, EMPRESA, ETAPA, ETAPA_LOG,
    OPERACION_PLANTA_LOG, PERFIL, PERFIL_USUARIO, PLANIFICACION, SECUENCIA,
    SYSLOGGER, USERS_EMPRESA,
)


class InspeccionInicioCargaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(username='inspector_prueba')
        cls.guardia = get_user_model().objects.create_user(username='porteria_prueba')
        cls.ajeno = get_user_model().objects.create_user(username='lector_prueba')
        cls.empresa = EMPRESA.objects.create(id=2, EP_CRAZONSOCIAL='SBH prueba', EP_CRUT='2-7')
        for usuario, codigo in ((cls.usuario, 'ASISTENTE_CD'), (cls.guardia, 'GUARDIA_PORTERIA')):
            perfil = PERFIL.objects.create(US_NID=usuario, PR_CCODIGO=codigo, PR_CNOMBRE=codigo)
            PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil)
        for usuario in (cls.usuario, cls.guardia, cls.ajeno):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=cls.empresa)
        calendario = CALENDARIO.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            CA_CNOMBRE='Prueba', CA_NDIA=14, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=1)
        cls.planificacion = PLANIFICACION.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            CAL_NID=calendario, PL_CTIPOCUPO='DESPACHO', PL_NCANTIDADCUPOS=1)
        cls.secuencia = SECUENCIA.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            SE_CTIPO='DESPACHO', SE_CCODIGO='EST_SBH_CLIENTE', SE_CNOMBRE='Despacho desde Estanque SBH')
        etapa = ETAPA.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            ET_CTIPO='OPERACION', ET_CCODIGO='INICIO_CARGA', ET_CNOMBRE='Inicio carga', ET_NCANTIDADMAXIMA=1)
        cls.citacion = CITACION.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            PL_NID=cls.planificacion, SC_NID=cls.secuencia, CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1, CI_CTIPO='DESPACHO', CI_CESTADO='EN PROCESO')
        ETAPA_LOG.objects.create(CI_NID=cls.citacion, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=etapa, US_INICIO_ID=cls.usuario, EL_FFECHAINICIO=timezone.now())
        SYSLOGGER.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa,
            LOG_FFECHAREGISTRO=timezone.now(), LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(cls.citacion.id))
        OPERACION_PLANTA_LOG.objects.create(CI_NID=cls.citacion, EP_NID=cls.empresa,
            PL_NID=cls.planificacion, US_NID=cls.usuario, OPL_CPASO='Pesaje Entrada',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA', OPL_CESTADO='COMPLETADO')

    def respuestas(self, *fallas):
        return {codigo: 'NO_CUMPLE' if codigo in fallas else 'CUMPLE'
                for codigo, _, _ in views.CRITERIOS_INICIO_CARGA}

    def post(self, usuario=None, paso=None, datos=None):
        request = RequestFactory().post('/', {
            'paso': paso or views.PASO_APROBAR_INICIO_CARGA,
            **(self.respuestas() if datos is None else datos),
        })
        request.user = usuario or self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            return views.OPERACION_PLANTA_GUARDAR_PASO(request, self.citacion.id)

    def test_aprobado_perfil_real_y_persistencia(self):
        self.assertTrue(views.usuario_puede_paso_operacion(self.usuario, ['ASISTENTE C D']))
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], views.PASO_APROBAR_INICIO_CARGA)
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        metadata = views.leer_inspeccion_inicio_carga(self.citacion)
        self.assertEqual(metadata['resultado'], 'APROBADO')
        self.assertEqual(metadata['checks'], self.respuestas())
        self.assertEqual(metadata['usuario_id'], self.usuario.id)
        self.assertTrue(metadata['fecha_iso'])
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Ciclo Descarga')
        self.assertEqual(DATO_OPERACION.objects.filter(CAMP_NID__CA_CCODIGO=views.CAMPO_APROBAR_INICIO_CARGA).count(), 1)
        self.assertEqual(self.post().status_code, 409)

    def test_perfil_y_empresa_obligatorios(self):
        self.assertEqual(self.post(self.ajeno).status_code, 403)
        self.assertEqual(self.post(self.guardia).status_code, 403)
        USERS_EMPRESA.objects.filter(US_NID=self.usuario).delete()
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(views.leer_inspeccion_inicio_carga(self.citacion))

    def test_respuestas_faltantes_invalidas_y_paso_inactivo(self):
        for codigo, _, _ in views.CRITERIOS_INICIO_CARGA:
            for valor in (None, '', 'SI'):
                datos = self.respuestas()
                if valor is None:
                    datos.pop(codigo)
                else:
                    datos[codigo] = valor
                self.assertEqual(self.post(datos=datos).status_code, 409)
        OPERACION_PLANTA_LOG.objects.filter(OPL_CPASO='Pesaje Entrada').delete()
        self.assertEqual(self.post().status_code, 409)
        self.assertFalse(views.leer_inspeccion_inicio_carga(self.citacion))

    def test_rechazo_un_motivo_no_termina_y_bloquea_intermedias(self):
        response = self.post(datos=self.respuestas('estado_seguridad'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(views.leer_inspeccion_inicio_carga(self.citacion)['resultado'], 'RECHAZADO')
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[:2], ('Confirmar Salida', ['GUARDIA PORTERIA']))
        self.assertEqual(views._observacion_etapa_visible(self.citacion, 'Confirmar Salida'),
            'Camión fue rechazado por: Estado de seguridad. Se autoriza la salida.')
        self.citacion.refresh_from_db()
        self.assertNotEqual(self.citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertIsNone(self.citacion.CI_FFECHATERMINO)
        for paso in ('Ciclo Descarga', 'Pesaje Salida', 'Cierre Proceso de Carga', 'Autorizar Salida'):
            self.assertEqual(self.post(paso=paso).status_code, 409)
            self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(OPL_CPASO=paso).exists())
        nombres = [nombre for nombre, _ in views.obtener_pasos_operacion_citacion(self.citacion)[1]]
        estados = views.construir_estado_pasos_operacion(nombres, 'Confirmar Salida',
            {'Pesaje Entrada', views.PASO_APROBAR_INICIO_CARGA}, views.pasos_no_ejecutados_inspeccion(self.citacion))
        self.assertEqual(next(p['estado'] for p in estados if p['nombre'] == 'Ciclo Descarga'), 'pending')

    def test_multiples_motivos_precarga_y_guardia_finaliza(self):
        self.assertEqual(self.post(datos=self.respuestas('limpieza_equipo', 'equipos_seguridad')).status_code, 200)
        comentario = 'Camión fue rechazado por: Limpieza del equipo y Equipos de seguridad. Se autoriza la salida.'
        self.assertEqual(views._observacion_etapa_visible(self.citacion, 'Confirmar Salida'), comentario)
        self.assertEqual(self.post(paso='Confirmar Salida').status_code, 403)
        response = self.post(self.guardia, 'Confirmar Salida', {'observacion': 'Texto alterado'})
        self.assertEqual(response.status_code, 200, response.content)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertIsNotNone(self.citacion.CI_FFECHATERMINO)
        log = OPERACION_PLANTA_LOG.objects.get(OPL_CPASO='Confirmar Salida')
        self.assertIn(comentario, log.OPL_COBSERVACION)
        self.assertNotIn('Texto alterado', log.OPL_COBSERVACION)
        self.assertTrue(views.operacion_planta_esta_terminada(self.citacion))

    def test_todos_los_motivos_se_conservan(self):
        self.post(datos=self.respuestas(*(codigo for codigo, _, _ in views.CRITERIOS_INICIO_CARGA)))
        metadata = views.leer_inspeccion_inicio_carga(self.citacion)
        self.assertEqual(len(metadata['motivos_rechazo']), 5)
        comentario = views._observacion_etapa_visible(self.citacion, 'Confirmar Salida')
        for _, _, motivo in views.CRITERIOS_INICIO_CARGA:
            self.assertIn(motivo, comentario)

    def test_endpoints_dedicados_no_permiten_carga_ni_autorizacion_rechazada(self):
        self.post(datos=self.respuestas('limpieza_equipo'))
        request = RequestFactory().post('/', {'proceso': 'carga', 'paso_nombre': 'Pesaje Salida'})
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            for endpoint in (views.ajax_operacion_planta_iniciar_ciclo_descarga,
                             views.ajax_operacion_planta_finalizar_ciclo_descarga,
                             views.ajax_operacion_planta_autorizar_salida):
                self.assertEqual(endpoint(request, self.citacion.id).status_code, 409)
            with patch.object(views, 'usuario_puede_paso_operacion', return_value=True):
                _, _, error = views._validar_operacion_planta_ticket_request(request, self.citacion.id, 'Pesaje Salida')
                self.assertEqual(error.status_code, 409)

    def test_comentario_en_contexto_de_pantalla_guardia(self):
        self.post(datos=self.respuestas('limpieza_equipo'))
        request = RequestFactory().get('/')
        request.user = self.guardia
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(views, 'render') as render:
            views.OPERACION_PLANTA_CITACION(request, self.citacion.id)
        contexto = render.call_args.args[2]
        salida = next(p for p in contexto['pasos'] if p['nombre'] == 'Confirmar Salida')
        self.assertTrue(salida['activo'])
        self.assertTrue(salida['puede_editar'])
        self.assertIn('Camión fue rechazado por: Limpieza del equipo.', salida['observacion'])
        self.assertFalse(salida['puede_guardar_observacion'])
        ciclo = next(p for p in contexto['pasos'] if p['nombre'] == 'Ciclo Descarga')
        self.assertTrue(ciclo['no_ejecutado_inspeccion'])

    def test_post_fuera_del_flujo_es_rechazado(self):
        self.citacion.CI_CTIPO = 'RECEPCION'
        self.citacion.save(update_fields=['CI_CTIPO'])
        self.assertEqual(self.post().status_code, 409)


class InspeccionFrontendYAlcanceTests(SimpleTestCase):
    def test_alcance_exclusivo(self):
        for empresa, tipo, codigo in (
            (1, 'DESPACHO', 'EST_SBH_CLIENTE'), (2, 'RECEPCION', 'EST_SBH_CLIENTE'),
            (2, 'DESPACHO', 'TRASVASIJE_CLIENTE'), (2, 'DESPACHO', 'BODEGA_PATIO_CLIENTE'),
            (1, 'DESPACHO', 'DESPACHO_TERRAMAR'),
        ):
            citacion = SimpleNamespace(EP_NID_id=empresa, CI_CTIPO=tipo,
                SC_NID=SimpleNamespace(SE_CCODIGO=codigo, SE_CNOMBRE=codigo),
                PL_NID=SimpleNamespace(PL_CTIPOCUPO=tipo))
            self.assertFalse(views.aplica_inspeccion_inicio_carga(citacion))
            self.assertEqual(views.leer_inspeccion_inicio_carga(citacion), {})
            self.assertNotIn(views.PASO_APROBAR_INICIO_CARGA,
                [nombre for nombre, _ in views.obtener_pasos_operacion_citacion(citacion)[1]])

    def render_inspeccion(self, puede=True, metadata=None):
        metadata = metadata or {}
        return render_to_string('home/CITACION/inspeccion_inicio_carga.html', {
            'citacion': {'id': 1}, 'paso': {
                'nombre': views.PASO_APROBAR_INICIO_CARGA, 'activo': True, 'puede_editar': puede,
                'inspeccion_inicio_carga': metadata,
                'criterios_inicio_carga': [{'codigo': c, 'titulo': t, 'valor': metadata.get('checks', {}).get(c, '')}
                    for c, t, _ in views.CRITERIOS_INICIO_CARGA],
            },
        })

    def test_cinco_criterios_radios_obligatorios_y_responsive(self):
        html = self.render_inspeccion()
        for codigo, titulo, _ in views.CRITERIOS_INICIO_CARGA:
            self.assertIn(titulo, html)
            self.assertEqual(html.count('name="' + codigo + '"'), 2)
        self.assertEqual(html.count('type="radio"'), 10)
        self.assertEqual(html.count(' required '), 10)
        self.assertIn('id="op-inspeccion-guardar" disabled', html)
        self.assertIn('checked.length !== 5', html)
        self.assertIn('@media(max-width:600px)', html)
        get_template('home/CITACION/operacion_planta.html')

    def test_lectura_y_resultado_con_motivos(self):
        html = self.render_inspeccion(False)
        self.assertEqual(html.count('disabled>'), 5)
        self.assertNotIn('type="submit"', html)
        for resultado in ('APROBADO', 'RECHAZADO'):
            html = self.render_inspeccion(metadata={'resultado': resultado,
                'motivos_rechazo': ['Limpieza del equipo', 'Equipos de seguridad']})
            self.assertIn(resultado, html)
            self.assertNotIn('type="submit"', html)
            if resultado == 'RECHAZADO':
                self.assertIn('<li>Limpieza del equipo</li>', html)
                self.assertIn('<li>Equipos de seguridad</li>', html)
