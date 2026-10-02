import json
import re
from datetime import time
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.urls import resolve, reverse
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.home import new_jersey_p2 as p2, sap_solicitud_new_jersey_p2 as sap_p2, views
from apps.home.services.calidad_service import (
    ProcesoCalidadAmbiguo, asegurar_calidad_iniciada, buscar_resultado_calidad_por_guia,
)
from apps.home.sap_solicitud_new_jersey_p2 import LOG_SOLICITUD
from apps.home.sap_recepcion_new_jersey import LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1
from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient
from apps.home.models import (
    CALENDARIO, CAMION_PATIO, CAMPO, CITACION, CITACION_DETALLE_OPERACIONAL,
    DATO_OPERACION, DETALLE_SECUENCIA, EMPRESA, ETAPA, ETAPA_LOG, OPERACION_NEW_JERSEY,
    OPERACION_NEW_JERSEY_PROCESO, OPERACION_PLANTA_LOG, PERFIL, PERFIL_USUARIO,
    PERMISO, PLANIFICACION, RESULTADO_CALIDAD_OPERACION, USERS_EMPRESA, VISTA,
    SECUENCIA, EVENTO_INTEGRACION_CALIDAD, RESULTADO_CALIDAD_HISTORIAL,
)


class NewJerseyProceso2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username='nj_p2_user', email='nj_p2@example.com', password='test',
        )
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='99-9',
            EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE='NJ P2',
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
            CA_NDIA=28, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=2,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=2,
        )
        cls.secuencia_p1 = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_NEW_JERSEY_P1_CON_CALIDAD',
            SE_CNOMBRE='New Jersey P1', SE_BHABILITADO=True,
        )

    def crear_p1_cerrado(self, guia='65688', contenedor='MDFGD4533', base_line='2', citacion_id=None):
        p1 = CITACION.objects.create(
            id=citacion_id, US_NID=self.user, EP_NID=self.empresa,
            PL_NID=self.planificacion, SC_NID=self.secuencia_p1,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1, CI_CTIPO='RECEPCION', CI_CESTADO='TERMINADO',
            CI_CTIPODOCUMENTO='GD', CI_CNUMERODOCUMENTO=guia,
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=p1, EP_NID=self.empresa, US_NID=self.user,
            CDO_CGUIA=guia, CDO_CBL_CONTENEDOR=contenedor,
            CDO_CESTANQUE_DESTINO='TK08', CDO_CINSUMO='Producto NJ',
        )
        operacion = OPERACION_NEW_JERSEY.objects.create(
            EP_NID=self.empresa, US_NID=self.user,
            ONJ_CMODALIDAD=OPERACION_NEW_JERSEY.Modalidad.CON_CALIDAD,
            ONJ_CESTADO=OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_1,
            ONJ_CITEM_CODE='950105', ONJ_CPRODUCTO='Producto NJ',
            ONJ_CPURCHASE_ORDER='10001091', ONJ_CBASE_ENTRY='6880',
            ONJ_CBASE_LINE=base_line, ONJ_CBODEGA_VIRTUAL='B_NJ',
            ONJ_CTK_DESTINO='TK08',
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=operacion, CI_NID=p1, EP_NID=self.empresa,
            US_NID=self.user,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO,
        )
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user, EP_NID=self.empresa,
            PL_NID=self.planificacion, CI_NID=p1,
            OPL_CPASO='Confirmar Salida', OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        return p1, operacion

    def preparar(self, guia='65688', contenedor='MDFGD4533', base_line='2'):
        p1, operacion = self.crear_p1_cerrado(guia, contenedor, base_line)
        proceso, creado = p2.preparar_p2_desde_cierre_p1(p1, self.user, guia)
        self.assertTrue(creado)
        return p1, operacion, proceso

    def simular_solicitud_sap_creada(self, citacion):
        return OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD,
            OPL_CPERFIL_RESPONSABLE=p2.RESPONSABLE_P2,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'estado': 'CREADO', 'endpoint': '/InventoryTransferRequests',
                'response': {'DocEntry': 900, 'DocNum': 901},
                'origen': 'B_NJ_TEST', 'destino': 'TK08',
                'item_code': '950105', 'quantity_mt': 24,
            }),
        )

    def test_preparacion_unica_hereda_datos_y_no_crea_camion(self):
        p1, operacion, proceso = self.preparar()
        nuevamente, creado = p2.preparar_p2_desde_cierre_p1(p1, self.user, '65688')
        self.assertFalse(creado)
        self.assertEqual(nuevamente.id, proceso.id)
        self.assertEqual(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=operacion, ONJP_CTIPO=proceso.TipoProceso.PROCESO_2,
        ).count(), 1)
        citacion = proceso.CI_NID
        self.assertEqual(citacion.CI_NID_REF, p1.id)
        self.assertEqual(citacion.CI_CESTADO, p2.ESTADO_CITACION_PENDIENTE)
        self.assertEqual(citacion.CI_CNUMERODOCUMENTO, '65688')
        self.assertEqual(citacion.CI_NCUPO, 0)
        self.assertEqual(self.planificacion.TOTAL_CITACIONES, 1)
        self.assertEqual(citacion.SC_NID.SE_CCODIGO, p2.SECUENCIA_P2)
        self.assertEqual(citacion.detalle_operacional.CDO_CBL_CONTENEDOR, 'MDFGD4533')
        self.assertEqual(citacion.detalle_operacional.CDO_CCODIGO_SAP, '950105')
        self.assertEqual(citacion.detalle_operacional.CDO_CPEDIDO_SAP, '10001091')
        self.assertEqual(citacion.detalle_operacional.CDO_CSAP_OPOR_ID, '6880')
        dato = DATO_OPERACION.objects.get(CI_NID=citacion, CAMP_NID__CA_CCODIGO=p2.CAMPO_SNAPSHOT_P2)
        snapshot = json.loads(dato.DO_CVALOR)
        self.assertEqual(snapshot['base_line'], '2')
        self.assertEqual(snapshot['tk_destino'], 'TK08')
        self.assertEqual(snapshot['producto'], 'Producto NJ')
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())
        operacion.refresh_from_db()
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_2)
        self.assertFalse(views.citacion_habilitada_operacion(citacion))
        self.assertEqual(views.obtener_etapa_actual_operacional_citacion(citacion), 'Pendiente de activar P2')

    def test_baseline_ausente_no_se_inventa(self):
        _, _, proceso = self.preparar(base_line='')
        dato = DATO_OPERACION.objects.get(CI_NID=proceso.CI_NID, CAMP_NID__CA_CCODIGO=p2.CAMPO_SNAPSHOT_P2)
        self.assertEqual(json.loads(dato.DO_CVALOR)['base_line'], '')

    def test_listado_multiples_pendientes_y_activar_solo_uno(self):
        _, _, uno = self.preparar()
        _, _, dos = self.preparar('65689', 'OTRO-CNT', '3')
        request = RequestFactory().get('/planificaciones/recepcion/new-jersey/p2/?_empresa_id=2')
        request.user = self.user
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'render', return_value=HttpResponse('ok'),
        ) as render:
            views.PLANIFICACION_NEW_JERSEY_P2(request)
        filas = render.call_args.args[2]['filas']
        self.assertEqual(len(filas), 2)
        self.assertEqual({fila['guia'] for fila in filas}, {'65688', '65689'})
        self.assertEqual({fila['contenedor'] for fila in filas}, {'MDFGD4533', 'OTRO-CNT'})
        self.assertTrue(all(fila['estado_p2'] == 'PENDIENTE' for fila in filas))
        html = get_template('home/PLANIFICACION/new_jersey_p2_pendientes.html').render(render.call_args.args[2], request=request)
        self.assertIn('65688', html)
        self.assertIn('MDFGD4533', html)
        self.assertEqual(html.count('Activar Proceso 2'), 2)
        p2.activar_p2(uno.id, self.user)
        uno.refresh_from_db()
        dos.refresh_from_db()
        self.assertEqual(uno.ONJP_CESTADO, uno.Estado.EN_PROCESO)
        self.assertEqual(dos.ONJP_CESTADO, dos.Estado.PENDIENTE)
        self.assertTrue(views.citacion_habilitada_operacion(uno.CI_NID))
        self.assertFalse(views.citacion_habilitada_operacion(dos.CI_NID))
        self.assertEqual(views.obtener_etapa_actual_operacional_citacion(uno.CI_NID), p2.PASO_TOMA)

    def test_planificador_no_puede_reactivar_ni_activar_con_p1_abierto(self):
        p1, _, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        with self.assertRaisesMessage(ValueError, 'ya fue activado'):
            p2.activar_p2(proceso.id, self.user)
        p1.CI_CESTADO = 'EN PROCESO'
        p1.save(update_fields=['CI_CESTADO'])
        with self.assertRaisesMessage(ValueError, 'P1 debe estar terminado'):
            p2.activar_p2(proceso.id, self.user)

    def test_pasos_calidad_descarga_y_estado_final_sin_sap_ni_p3(self):
        _, operacion, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        citacion = proceso.CI_NID
        self.assertEqual(
            views.obtener_pasos_operacion_citacion(citacion)[1],
            [(paso, ['ASISTENTE C D']) for paso in p2.PASOS_P2],
        )
        with patch('requests.post', side_effect=AssertionError('SAP POST prohibido')):
            self.assertEqual(p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'iniciar')['siguiente'], p2.PASO_TOMA)
            self.assertEqual(p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'completar')['siguiente'], p2.PASO_DESCARGA)
            with self.assertRaisesMessage(ValueError, 'no es el activo'):
                p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_CALIDAD, 'aprobar')
            self.simular_solicitud_sap_creada(citacion)
            p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'iniciar')
            self.assertIsNone(p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'completar')['siguiente'])
        proceso.refresh_from_db()
        operacion.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual(proceso.ONJP_CESTADO, proceso.Estado.COMPLETADO)
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)
        self.assertFalse(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=operacion, ONJP_CTIPO=proceso.TipoProceso.PROCESO_3,
        ).exists())
        self.assertEqual(ETAPA_LOG.objects.filter(CI_NID=citacion, EL_FFECHAFIN__isnull=False).count(), 2)
        self.assertTrue(views.operacion_planta_esta_terminada(citacion))

    def test_no_avanza_sin_iniciar_ni_salta_pasos(self):
        _, _, proceso = self.preparar()
        citacion = proceso.CI_NID
        with self.assertRaisesMessage(ValueError, 'P2 no está activo'):
            p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'iniciar')
        p2.activar_p2(proceso.id, self.user)
        with self.assertRaisesMessage(ValueError, 'no es el activo'):
            p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'iniciar')
        with self.assertRaisesMessage(ValueError, 'Debe iniciar'):
            p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'completar')
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())

    def test_lista_operacion_p2_sin_autorizacion_guardia_ni_romana(self):
        _, _, proceso = self.preparar()
        citacion = proceso.CI_NID
        self.assertFalse(views.citacion_habilitada_operacion(citacion))
        p2.activar_p2(proceso.id, self.user)
        self.assertTrue(views.citacion_habilitada_operacion(citacion))
        self.assertEqual(views.obtener_etapa_actual_operacional_citacion(citacion), p2.PASO_TOMA)
        self.assertNotIn('Pesaje', [paso for paso, _ in views.obtener_pasos_operacion_citacion(citacion)[1]])
        request = RequestFactory().get('/operacion-planta/%s/?_empresa_id=2' % citacion.id)
        request.user = self.user
        with patch.object(views, 'obtener_datos_operacion_citacion', return_value=(None, [])), patch.object(
            views, 'documentos_revision_camion', return_value=[],
        ), patch.object(views, 'render', return_value=HttpResponse('ok')) as render:
            views._render_operacion_new_jersey_p2(request, citacion, 2)
        self.assertEqual(render.call_args.args[1], 'home/CITACION/operacion_planta.html')
        pasos = render.call_args.args[2]['pasos']
        self.assertEqual([paso['nombre'] for paso in pasos], list(p2.PASOS_P2))
        self.assertTrue(pasos[0]['activo'])
        self.assertTrue(render.call_args.args[2]['puede_editar'])
        html = get_template('home/CITACION/operacion_planta.html').render(render.call_args.args[2], request=request)
        self.assertIn('Datos SAP / operacionales', html)
        self.assertIn('Documentos adjuntos', html)
        self.assertIn('Historial P2', html)
        self.assertIn('MDFGD4533', html)
        self.assertIn('65688', html)
        tabs = html.split('id="operacion-tabs"', 1)[1].split('</ul>', 1)[0]
        self.assertEqual(re.findall(r'<span class="op-etapa-nombre">([^<]+)</span>', tabs),
                         ['Toma de muestra', 'Calidad', 'Ciclo Descarga'])
        self.assertTrue('operacion-toma-muestra-box' in html)
        self.assertTrue('operacion-calidad-box' in html)
        self.assertTrue('operacion-ciclo-descarga-box' in html)
        self.assertTrue('Finalizar toma de muestra' in html)
        self.assertFalse('nj-p2-reloj' in html)
        self.assertNotIn('<span>Patente</span>', html)
        self.assertNotIn('Guardar paso', html.split('<div class="tab-content">', 1)[1].split('Historial P2', 1)[0])
        self.assertNotIn('Autorizar salida', html.split('<div class="tab-content">', 1)[1].split('Historial P2', 1)[0])


    def test_ruta_p2_usa_componentes_estandar_y_timers_persistentes(self):
        _, operacion, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        citacion = proceso.CI_NID
        self.client.force_login(self.user)
        url = reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2'
        def post(nombre, datos):
            with patch.object(views, 'Verificar_empresa', return_value=2), patch(
                'requests.post', side_effect=AssertionError('SAP POST prohibido')
            ):
                respuesta = self.client.post(reverse(nombre, args=[citacion.id]),
                                             {'_empresa_id': '2', **datos})
            self.assertEqual(respuesta.status_code, 200, respuesta.content[:500])
            self.assertTrue(respuesta.json()['success'])
            return respuesta
        def get():
            with patch.object(views, 'Verificar_empresa', return_value=2):
                return self.client.get(url)

        respuesta = get()
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'home/CITACION/operacion_planta.html')
        self.assertEqual(ETAPA_LOG.objects.filter(CI_NID=citacion).count(), 0)
        self.assertFalse(RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=citacion).exists())
        self.assertTrue('operacion-toma-muestra-box' in respuesta.content.decode())
        post('ajax_operacion_planta_registrar_accion_toma_muestra', {'paso': p2.PASO_TOMA})
        self.assertTrue(DATO_OPERACION.objects.filter(
            CI_NID=citacion, CAMP_NID__CA_CCODIGO=views.CAMPO_TOMA_MUESTRA_ACCION,
        ).exists())
        respuesta = get()
        self.assertTrue('op-toma-muestra-live-time' in respuesta.content.decode())
        self.assertTrue('data-wait-start=' in respuesta.content.decode())
        self.assertFalse(RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=citacion).exists())
        post('operacion_planta_guardar_paso', {'paso': p2.PASO_TOMA, 'observacion': 'Muestra tomada'})
        respuesta = get()
        self.assertEqual(respuesta.context['paso_actual'], p2.PASO_DESCARGA)
        self.assertTrue('operacion-calidad-box' in respuesta.content.decode())
        self.assertEqual(ETAPA_LOG.objects.filter(CI_NID=citacion).count(), 2)
        calidad = RESULTADO_CALIDAD_OPERACION.objects.get(CI_NID=citacion)
        self.assertEqual(calidad.RCO_CNUMERO_GUIA, '65688')
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)
        self.assertTrue(calidad.temporizador_activo)
        pasos = {paso['nombre']: paso for paso in respuesta.context['pasos']}
        self.assertEqual(pasos[p2.PASO_TOMA]['estado'], 'COMPLETADO')
        self.assertEqual(pasos[p2.PASO_CALIDAD]['estado'], 'EN PROCESO')
        self.assertEqual(pasos[p2.PASO_DESCARGA]['estado'], 'ACTIVO')
        self.assertTrue(pasos[p2.PASO_CALIDAD]['calidad_paralela'])
        self.assertTrue('operacion-ciclo-descarga-box' in respuesta.content.decode())
        self.simular_solicitud_sap_creada(citacion)
        post('ajax_operacion_planta_iniciar_ciclo_descarga', {'tipo_descarga': 'Descarga Estanque'})
        respuesta = get()
        self.assertTrue('data-cycle-start=' in respuesta.content.decode())
        post('ajax_operacion_planta_finalizar_ciclo_descarga', {'observacion': 'Descarga completa'})
        respuesta = get()
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context['operacion_solo_lectura'])
        self.assertTrue('P2 completado' in respuesta.content.decode())
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)
        self.assertTrue(calidad.temporizador_activo)
        operacion.refresh_from_db()
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)
        self.assertFalse(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=operacion, ONJP_CTIPO=proceso.TipoProceso.PROCESO_3,
        ).exists())

    def test_citacion_activa_aparece_en_listado_operacion_planta(self):
        _, _, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        request = RequestFactory().get(
            '/cit_listall_recepciones/?contexto=operacion_planta&tipo=RECEPCION&_empresa_id=2'
        )
        request.user = self.user
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'render', return_value=HttpResponse('ok'),
        ) as render:
            response = views.CITACION_LISTALL_RECEPCIONES(request)
        self.assertEqual(response.status_code, 200)
        objetos = render.call_args.args[2]['object_list']
        self.assertIn(proceso.CI_NID_id, [citacion.id for citacion in objetos])
        self.assertEqual(
            next(citacion for citacion in objetos if citacion.id == proceso.CI_NID_id).operacion_estado_visible,
            p2.PASO_TOMA,
        )
    def test_reutiliza_secuencia_p2_existente_y_actualiza_placeholders(self):
        secuencia = SECUENCIA.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=p2.SECUENCIA_P2, SE_CNOMBRE='P2 existente',
            SE_BHABILITADO=True,
        )
        for numero, codigo in enumerate((
            'NJ_P2_PENDIENTE', 'NJ_P2_OPERACION_INTERNA',
            'NJ_P2_TRASLADO_PREPARADO', 'NJ_P2_TERMINADO',
        ), start=1):
            etapa = ETAPA.objects.create(
                US_NID=self.user, EP_NID=self.empresa, ET_CTIPO='OPERACION',
                ET_CCODIGO=codigo, ET_CNOMBRE=codigo,
                ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
            )
            DETALLE_SECUENCIA.objects.create(
                US_NID=self.user, EP_NID=self.empresa, SC_NID=secuencia,
                ET_NID=etapa, SE_NPASO=numero, SE_BHABILITADO=True,
                SE_BOBLIGATORIO=True,
            )
        _, _, proceso = self.preparar()
        self.assertEqual(proceso.CI_NID.SC_NID_id, secuencia.id)
        self.assertEqual(list(DETALLE_SECUENCIA.objects.filter(
            SC_NID=secuencia,
        ).order_by('SE_NPASO').values_list('ET_NID__ET_CNOMBRE', flat=True)), [
            'Pendiente Proceso 2', 'Toma de muestra', 'Calidad', 'Ciclo Descarga',
        ])
    def test_usuario_sin_rol_no_activa_ni_opera_p2(self):
        _, _, proceso = self.preparar()
        usuario = get_user_model().objects.create_user('nj_sin_rol', password='test')
        solicitud_plan = RequestFactory().post(
            '/planificaciones/recepcion/new-jersey/p2/%s/activar/' % proceso.id,
            {'_empresa_id': '2'},
        )
        solicitud_plan.user = usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            respuesta = views.PLANIFICACION_ACTIVAR_NEW_JERSEY_P2(solicitud_plan, proceso.id)
        self.assertEqual(respuesta.status_code, 403)
        p2.activar_p2(proceso.id, self.user)
        solicitud_operacion = RequestFactory().post(
            '/operacion-planta/%s/new-jersey-p2/accion/' % proceso.CI_NID_id,
            {'_empresa_id': '2', 'paso': p2.PASO_TOMA, 'accion': 'iniciar'},
        )
        solicitud_operacion.user = usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            respuesta = views.OPERACION_PLANTA_ACCION_NEW_JERSEY_P2(
                solicitud_operacion, proceso.CI_NID_id,
            )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(ETAPA_LOG.objects.filter(CI_NID=proceso.CI_NID).exists())
    def _p2_cerrado_con_calidad_pendiente(self):
        p1, operacion, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        citacion = proceso.CI_NID
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'iniciar')
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'completar')
        calidad, creado = asegurar_calidad_iniciada(citacion, self.user)
        self.assertTrue(creado)
        self.simular_solicitud_sap_creada(citacion)
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'iniciar')
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'completar')
        citacion.refresh_from_db()
        proceso.refresh_from_db()
        operacion.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(proceso.ONJP_CESTADO, proceso.Estado.COMPLETADO)
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)
        return citacion, proceso, operacion, calidad

    def _evento_bot(self, estado, id_evento):
        data = {
            'empresa_id': 2, 'numero_guia': '65688', 'estado': estado,
            'origen': 'EXCEL_CALIDAD', 'observacion': 'Resultado laboratorio',
            'id_evento': id_evento,
        }
        with override_settings(TERRAVIEW_CALIDAD_API_KEY='clave-test'), patch(
            'apps.home.services.calidad_integracion_service.enviar_resultado_calidad_teams'
        ):
            return self.client.post(
                reverse('api_integracion_calidad_resultados'),
                data=json.dumps(data), content_type='application/json',
                HTTP_X_TERRAVIEW_API_KEY='clave-test',
            )

    def test_bot_aprueba_calidad_despues_de_cerrar_p2_sin_sap(self):
        citacion, proceso, operacion, calidad = self._p2_cerrado_con_calidad_pendiente()
        # Reproduce el registro real #38732, creado con guia vacia antes del ajuste.
        calidad.RCO_CNUMERO_GUIA = ''
        calidad.save(update_fields=['RCO_CNUMERO_GUIA'])
        with self.captureOnCommitCallbacks(execute=False) as callbacks, patch(
            'requests.post', side_effect=AssertionError('SAP POST prohibido')
        ):
            respuesta = self._evento_bot('APROBADO', 'nj-p2-aprobado')
        self.assertEqual(callbacks, [])
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:300])
        self.assertEqual(respuesta.json()['citacion'], citacion.id)
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.APROBADO)
        self.assertEqual(calidad.RCO_CNUMERO_GUIA, '65688')
        self.assertFalse(calidad.temporizador_activo)
        self.assertIsNotNone(calidad.RCO_FDETENCION_TEMPORIZADOR)
        citacion.refresh_from_db()
        operacion.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)
        self.assertTrue(RESULTADO_CALIDAD_HISTORIAL.objects.filter(
            CI_NID=citacion, RCH_CEVENTO='CALIDAD_APROBADA',
        ).exists())

    def test_bot_rechaza_y_calidad_resuelve_manualmente_despues_de_p2(self):
        citacion, proceso, operacion, calidad = self._p2_cerrado_con_calidad_pendiente()
        respuesta = self._evento_bot('RECHAZADO', 'nj-p2-rechazado')
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:300])
        self.assertEqual(respuesta.json()['estado_actual'], 'RECHAZADO_PENDIENTE_REVISION')
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.RECHAZADO_PENDIENTE_REVISION)
        self.assertFalse(calidad.temporizador_activo)
        self.assertIsNotNone(calidad.RCO_FDETENCION_TEMPORIZADOR)
        self.assertTrue(EVENTO_INTEGRACION_CALIDAD.objects.filter(
            CI_NID=citacion, RCO_NID=calidad,
        ).exists())
        perfil = PERFIL.objects.create(
            US_NID=self.user, PR_CCODIGO='CALIDAD', PR_CNOMBRE='CALIDAD', PR_BHABILITADO=True,
        )
        calidad_user = get_user_model().objects.create_user('nj_calidad', password='test')
        PERFIL_USUARIO.objects.create(US_NID=calidad_user, PR_NID=perfil, PE_BHABILITADO=True)
        USERS_EMPRESA.objects.create(US_NID=calidad_user, EP_NID=self.empresa)
        self.client.force_login(calidad_user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertEqual(pagina.status_code, 200)
        html = pagina.content.decode()
        self.assertTrue('operacion-revision-calidad-manual' in html)
        self.assertTrue('Aprobar manualmente' in html)
        self.assertTrue('RECHAZADO_PENDIENTE_REVISION' in html)
        with patch.object(views, 'Verificar_empresa', return_value=2), patch(
            'requests.post', side_effect=AssertionError('SAP POST prohibido')
        ):
            revision = self.client.post(
                reverse('ajax_operacion_planta_resolver_revision_calidad', args=[citacion.id]),
                {'decision': 'APROBADO', 'comentario': 'Muestra conforme', '_empresa_id': '2'},
            )
        self.assertEqual(revision.status_code, 200, revision.content[:300])
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.APROBADO)
        self.assertEqual(calidad.RCO_CORIGEN, calidad.Origen.REVISION_MANUAL)
        citacion.refresh_from_db()
        operacion.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)

    def test_rechazo_definitivo_manual_no_reabre_p2_ni_autoriza_salida(self):
        citacion, proceso, operacion, calidad = self._p2_cerrado_con_calidad_pendiente()
        respuesta = self._evento_bot('RECHAZADO', 'nj-p2-rechazo-definitivo')
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:300])
        self.client.force_login(self.user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            revision = self.client.post(
                reverse('ajax_operacion_planta_resolver_revision_calidad', args=[citacion.id]),
                {'decision': 'RECHAZADO', 'comentario': 'Rechazo definitivo', '_empresa_id': '2'},
            )
        self.assertEqual(revision.status_code, 200, revision.content[:300])
        calidad.refresh_from_db()
        citacion.refresh_from_db()
        operacion.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.RECHAZADO)
        self.assertFalse(calidad.RCO_BAUTORIZA_SALIDA)
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)

    def test_guia_legacy_p2_sin_guardar_se_resuelve_sin_prioridad_ambigua(self):
        citacion, proceso, operacion, calidad = self._p2_cerrado_con_calidad_pendiente()
        calidad.RCO_CNUMERO_GUIA = ''
        calidad.save(update_fields=['RCO_CNUMERO_GUIA'])
        self.assertEqual(buscar_resultado_calidad_por_guia(2, '65688').id, calidad.id)
        asegurar_calidad_iniciada(citacion, self.user)
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CNUMERO_GUIA, '65688')
        calidad_p1 = RESULTADO_CALIDAD_OPERACION.objects.create(
            CI_NID_id=citacion.CI_NID_REF, EP_NID=self.empresa,
            PL_NID=self.planificacion, RCO_CNUMERO_GUIA='65688',
            RCO_FINICIO=timezone.now(), RCO_CESTADO='PENDIENTE',
        )
        with self.assertRaises(ProcesoCalidadAmbiguo):
            buscar_resultado_calidad_por_guia(2, '65688')
        calidad_p1.RCO_CESTADO = calidad_p1.Estado.APROBADO
        calidad_p1.save(update_fields=['RCO_CESTADO'])
        self.assertEqual(buscar_resultado_calidad_por_guia(2, '65688').id, calidad.id)

    def preparar_solicitud_sap_p2(self):
        p1, operacion, proceso = self.preparar()
        p2.activar_p2(proceso.id, self.user)
        citacion = proceso.CI_NID
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'iniciar')
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_TOMA, 'completar')
        campo = CAMPO.objects.create(
            US_NID=self.user, EP_NID=self.empresa, CA_CTIPO='DECIMAL',
            CA_CCODIGO='SAP_PESO_INFORMADO_GUIA',
            CA_CETIQUETA='Peso informado guia', CA_BHABILITADO=True,
        )
        etapa = ETAPA.objects.create(
            US_NID=self.user, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='NJ_P1_PESO_GUIA_TEST', ET_CNOMBRE='Peso guia P1',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DATO_OPERACION.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SC_NID=p1.SC_NID,
            ET_NID=etapa, CAMP_NID=campo, CI_NID=p1,
            DO_FFECHAREGISTRO=timezone.now(), DO_CVALOR='24000',
        )
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=p1, OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'success': True, 'response': {'DocEntry': 20355, 'DocNum': 13186},
                'payload': {'DocumentLines': [{
                    'ItemCode': '950105', 'Quantity': 24, 'WarehouseCode': 'B_NJ_TEST',
                }]},
            }),
        )
        return p1, operacion, citacion

    def _mock_fuentes_sap_p2(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(sap_p2, '_schema_sap', return_value='TEST'))
        stack.enter_context(patch.object(
            sap_p2, '_articulo_y_bodegas',
            return_value={'unidad': 'Toneladas Metricas', 'administra_lotes': 'Y'},
        ))
        stack.enter_context(patch.object(
            sap_p2, 'obtener_fecha_sistema_sap', return_value='2026-09-28',
        ))
        return stack

    def _ruta_guardar_tk_p2(self, citacion):
        return reverse('ajax_operacion_planta_guardar_tk_new_jersey_p2', args=[citacion.id])

    def test_tk_p2_heredado_visible_y_conservarlo_no_modifica_p1(self):
        p1, operacion, citacion = self.preparar_solicitud_sap_p2()
        self.assertEqual(p2.destino_vigente_p2(citacion), 'TK08')
        self.assertEqual(operacion.ONJ_CTK_DESTINO, 'TK08')
        self.client.force_login(self.user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
            respuesta = self.client.post(self._ruta_guardar_tk_p2(citacion), {
                '_empresa_id': '2', 'tk_destino': 'TK08',
            })
        self.assertEqual(pagina.status_code, 200)
        html = pagina.content.decode()
        self.assertIn('id="new-jersey-p2-tk-destino"', html)
        self.assertIn('value="TK08" selected', html)
        self.assertIn('Destino heredado desde P1.', html)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.json()['changed'])
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=p2.LOG_CAMBIO_TK_P2).exists())
        self.assertEqual(p1.detalle_operacional.CDO_CESTANQUE_DESTINO, 'TK08')

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST', SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_cambiar_tk_p2_persiste_y_preview_refleja_tk_nuevo_sin_post(self):
        p1, operacion, citacion = self.preparar_solicitud_sap_p2()
        self.client.force_login(self.user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            respuesta = self.client.post(self._ruta_guardar_tk_p2(citacion), {
                '_empresa_id': '2', 'tk_destino': 'TK05',
            })
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:400])
        self.assertTrue(respuesta.json()['changed'])
        citacion.detalle_operacional.refresh_from_db()
        operacion.refresh_from_db()
        p1.detalle_operacional.refresh_from_db()
        self.assertEqual(citacion.detalle_operacional.CDO_CESTANQUE_DESTINO, 'TK05')
        self.assertEqual(operacion.ONJ_CTK_DESTINO, 'TK08')
        self.assertEqual(p1.detalle_operacional.CDO_CESTANQUE_DESTINO, 'TK08')
        log = OPERACION_PLANTA_LOG.objects.get(CI_NID=citacion, OPL_CPASO=p2.LOG_CAMBIO_TK_P2)
        audit = json.loads(log.OPL_COBSERVACION)
        self.assertEqual((audit['tk_heredado_p1'], audit['tk_anterior_p2'], audit['tk_seleccionado_p2']),
                         ('TK08', 'TK08', 'TK05'))
        self.assertEqual(audit['usuario'], self.user.username)
        self.assertTrue(audit['fecha'])
        with self._mock_fuentes_sap_p2(), patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            sap_p2, 'SapServiceLayerClient', side_effect=AssertionError('Preview no envía SAP')
        ):
            preview = self.client.post(reverse('ajax_operacion_planta_preview_solicitud_sap_new_jersey_p2', args=[citacion.id]), {'_empresa_id': '2'})
        self.assertEqual(preview.status_code, 200, preview.content[:400])
        payload = preview.json()['preview']['payload']
        self.assertEqual(payload['ToWarehouse'], 'TK05')
        self.assertEqual(payload['StockTransferLines'][0]['WarehouseCode'], 'TK05')
        with patch.object(views, 'Verificar_empresa', return_value=2):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertIn('value="TK05" selected', pagina.content.decode())
        self.assertIn('TK heredado de P1: TK08', pagina.content.decode())

    def test_tk_p2_invalido_vacio_y_otros_flujos_no_se_modifican(self):
        p1, _, citacion = self.preparar_solicitud_sap_p2()
        self.client.force_login(self.user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            for tk in ('', 'PROSE_T3', 'NO_EXISTE', 'PATIO_LF'):
                respuesta = self.client.post(self._ruta_guardar_tk_p2(citacion), {
                    '_empresa_id': '2', 'tk_destino': tk,
                })
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(p2.MENSAJE_TK_INVALIDO_P2, respuesta.json()['message'])
            otro = self.client.post(self._ruta_guardar_tk_p2(p1), {
                '_empresa_id': '2', 'tk_destino': 'TK05',
            })
        self.assertEqual(otro.status_code, 404)
        self.assertEqual(p2.destino_vigente_p2(citacion), 'TK08')
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=p2.LOG_CAMBIO_TK_P2).exists())

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_solicitud_sap_usa_tk_cambiado_y_luego_bloquea_selector(self):
        p1, operacion, citacion = self.preparar_solicitud_sap_p2()
        self.client.force_login(self.user)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            self.assertEqual(self.client.post(self._ruta_guardar_tk_p2(citacion), {
                '_empresa_id': '2', 'tk_destino': 'TK05',
            }).status_code, 200)
        ruta = reverse('ajax_operacion_planta_crear_solicitud_sap_new_jersey_p2', args=[citacion.id])
        with self._mock_fuentes_sap_p2(), patch.object(sap_p2, 'load_config', return_value=SimpleNamespace(company_db='TEST')), patch.object(
            sap_p2, 'buscar_solicitud_sap_new_jersey_p2', return_value=None
        ), patch.object(sap_p2, 'SapServiceLayerClient') as client_class, patch.object(views, 'Verificar_empresa', return_value=2):
            client = client_class.return_value
            client.post_inventory_transfer_request.return_value = {
                'status_code': 201, 'data': {'DocEntry': 5050, 'DocNum': 5150},
            }
            respuesta = self.client.post(ruta, {'_empresa_id': '2'})
            self.assertEqual(respuesta.status_code, 200, respuesta.content[:400])
            payload = client.post_inventory_transfer_request.call_args.args[0]
            self.assertEqual(payload['ToWarehouse'], 'TK05')
            self.assertEqual(payload['StockTransferLines'][0]['WarehouseCode'], 'TK05')
            client.post_stock_transfer.assert_not_called()
        with patch.object(views, 'Verificar_empresa', return_value=2):
            bloqueada = self.client.post(self._ruta_guardar_tk_p2(citacion), {
                '_empresa_id': '2', 'tk_destino': 'TK08',
            })
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertEqual(bloqueada.status_code, 409)
        self.assertEqual(p2.destino_vigente_p2(citacion), 'TK05')
        html = pagina.content.decode()
        self.assertRegex(html, r'id="new-jersey-p2-tk-destino"[^>]*disabled')
        self.assertIn('DocEntry:', html)
        self.assertIn('5050', html)

    def test_tk_p2_enviando_bloquea_edicion(self):
        _, _, citacion = self.preparar_solicitud_sap_p2()
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD,
            OPL_CPERFIL_RESPONSABLE=p2.RESPONSABLE_P2,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
            OPL_COBSERVACION=json.dumps({'estado': 'ENVIANDO'}),
        )
        with self.assertRaisesMessage(ValueError, 'no puede cambiarse'):
            p2.guardar_destino_p2(citacion.id, self.user, 'TK05')
        self.assertEqual(p2.destino_vigente_p2(citacion), 'TK08')

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_builder_rechaza_tk_p2_ausente_sin_recurrir_a_p1(self):
        _, operacion, citacion = self.preparar_solicitud_sap_p2()
        detalle = citacion.detalle_operacional
        detalle.CDO_CESTANQUE_DESTINO = ''
        detalle.save(update_fields=['CDO_CESTANQUE_DESTINO'])
        with self._mock_fuentes_sap_p2():
            preview = sap_p2.build_inventory_transfer_request_new_jersey_p2(citacion)
        self.assertFalse(preview['ready_for_post'])
        self.assertIn(p2.MENSAJE_TK_INVALIDO_P2, preview['errors'])
        self.assertEqual(preview['source_data']['destino'], '')
        self.assertEqual(preview['payload'], {})
        self.assertEqual(operacion.ONJ_CTK_DESTINO, 'TK08')

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_envio_detecta_tk_cambiado_entre_preview_y_bloqueo(self):
        _, _, citacion = self.preparar_solicitud_sap_p2()
        with self._mock_fuentes_sap_p2():
            preview = sap_p2.build_inventory_transfer_request_new_jersey_p2(citacion)
        detalle = citacion.detalle_operacional
        detalle.CDO_CESTANQUE_DESTINO = 'TK05'
        detalle.save(update_fields=['CDO_CESTANQUE_DESTINO'])
        with patch.object(sap_p2, 'build_inventory_transfer_request_new_jersey_p2', return_value=preview), patch.object(
            sap_p2, 'load_config', return_value=SimpleNamespace(company_db='TEST')
        ), patch.object(sap_p2, '_schema_sap', return_value='TEST'), patch.object(
            sap_p2, 'buscar_solicitud_sap_new_jersey_p2', side_effect=AssertionError('No consultar SAP con payload obsoleto')
        ), patch.object(sap_p2, 'SapServiceLayerClient', side_effect=AssertionError('No enviar SAP')):
            resultado = sap_p2.send_inventory_transfer_request_new_jersey_p2_to_sap(citacion, self.user)
        self.assertFalse(resultado['success'])
        self.assertIn('cambió', resultado['message'])
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD).exists())

    def test_solo_asistente_autorizado_puede_guardar_tk_p2(self):
        _, _, citacion = self.preparar_solicitud_sap_p2()
        usuario = get_user_model().objects.create_user(username='sin_perfil_p2_tk', password='test')
        self.client.force_login(usuario)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            respuesta = self.client.post(self._ruta_guardar_tk_p2(citacion), {
                '_empresa_id': '2', 'tk_destino': 'TK05',
            })
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(p2.destino_vigente_p2(citacion), 'TK08')

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST', BODEGA_VIRTUAL='PROSESA')
    def test_builder_solicitud_sap_p2_usa_peso_guia_mt_y_sin_lote(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        with self._mock_fuentes_sap_p2(), patch.object(
            sap_p2, 'SapServiceLayerClient', side_effect=AssertionError('Preview no usa Service Layer POST')
        ):
            preview = sap_p2.build_inventory_transfer_request_new_jersey_p2(citacion)
        self.assertTrue(preview['ready_for_post'], preview['errors'])
        self.assertEqual(preview['endpoint'], '/InventoryTransferRequests')
        payload = preview['payload']
        self.assertEqual(payload['DocDate'], '2026-09-28')
        self.assertEqual((payload['FromWarehouse'], payload['ToWarehouse']), ('B_NJ_TEST', 'TK08'))
        self.assertEqual((payload['Reference1'], payload['Reference2']), ('TERRAVIEW', str(citacion.id)))
        self.assertEqual(len(payload['StockTransferLines']), 1)
        linea = payload['StockTransferLines'][0]
        self.assertEqual(linea, {
            'ItemCode': '950105', 'Quantity': 24.0,
            'FromWarehouseCode': 'B_NJ_TEST', 'WarehouseCode': 'TK08',
        })
        self.assertEqual(preview['source_data']['peso_guia_kg'], 24000)
        self.assertEqual(preview['source_data']['quantity_mt'], 24)
        self.assertNotIn('BatchNumbers', linea)
        self.assertNotIn('StockTransfers', json.dumps(payload))
        self.assertEqual(preview['status']['estado'], 'NO_CREADA')
        self.assertTrue(RESULTADO_CALIDAD_OPERACION.objects.filter(CI_NID=citacion).count() == 0)

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_cantidad_guia_debe_coincidir_con_ingreso_p1_confirmado(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        dato = DATO_OPERACION.objects.get(CI_NID=p1, CAMP_NID__CA_CCODIGO='SAP_PESO_INFORMADO_GUIA')
        dato.DO_CVALOR = '25000'
        dato.save(update_fields=['DO_CVALOR'])
        with self._mock_fuentes_sap_p2():
            preview = sap_p2.build_inventory_transfer_request_new_jersey_p2(citacion)
        self.assertFalse(preview['ready_for_post'])
        self.assertTrue(any('difiere' in error for error in preview['errors']))
        self.assertEqual(preview['payload'], {})

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_preview_solicitud_sap_p2_flag_sin_post_y_json(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        self.client.force_login(self.user)
        ruta = reverse('ajax_operacion_planta_preview_solicitud_sap_new_jersey_p2', args=[citacion.id])
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False), patch.object(
            views, 'Verificar_empresa', return_value=2
        ):
            self.assertEqual(self.client.post(ruta, {'_empresa_id': '2'}).status_code, 404)
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True), self._mock_fuentes_sap_p2(), patch.object(
            views, 'Verificar_empresa', return_value=2
        ), patch.object(
            sap_p2, 'SapServiceLayerClient', side_effect=AssertionError('Preview no debe enviar SAP')
        ):
            respuesta = self.client.post(ruta, {'_empresa_id': '2'})
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:400])
        data = respuesta.json()
        self.assertTrue(data['read_only'])
        self.assertEqual(data['preview']['payload']['StockTransferLines'][0]['Quantity'], 24)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD).count(), 0)
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True), patch.object(
            views, 'Verificar_empresa', return_value=2
        ):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertEqual(pagina.status_code, 200)
        self.assertTrue('PREVISUALIZAR SOLICITUD SAP' in pagina.content.decode())
        self.assertTrue('CREAR SOLICITUD DE TRASLADO SAP' in pagina.content.decode())
        with override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False), patch.object(
            views, 'Verificar_empresa', return_value=2
        ):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertFalse('PREVISUALIZAR SOLICITUD SAP' in pagina.content.decode())
        self.assertTrue('CREAR SOLICITUD DE TRASLADO SAP' in pagina.content.decode())

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_envio_solicitud_p2_persiste_y_bloquea_duplicado(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        calidad, _ = asegurar_calidad_iniciada(citacion, self.user)
        self.client.force_login(self.user)
        ruta = reverse('ajax_operacion_planta_crear_solicitud_sap_new_jersey_p2', args=[citacion.id])
        with self._mock_fuentes_sap_p2(), patch.object(
            sap_p2, 'load_config', return_value=SimpleNamespace(company_db='TEST')
        ), patch.object(
            sap_p2, 'buscar_solicitud_sap_new_jersey_p2', return_value=None
        ), patch.object(
            sap_p2, 'SapServiceLayerClient'
        ) as client_class, patch.object(views, 'Verificar_empresa', return_value=2):
            client = client_class.return_value
            client.post_inventory_transfer_request.return_value = {
                'status_code': 201, 'data': {'DocEntry': 5001, 'DocNum': 5100},
            }
            preview = sap_p2.build_inventory_transfer_request_new_jersey_p2(citacion)
            respuesta = self.client.post(ruta, {'_empresa_id': '2'})
            self.assertEqual(respuesta.status_code, 200, respuesta.content[:400])
            self.assertTrue(respuesta.json()['inventory_transfer_request_created'])
            self.assertEqual(client.post_inventory_transfer_request.call_count, 1)
            payload = client.post_inventory_transfer_request.call_args.args[0]
            self.assertEqual(payload, preview['payload'])
            self.assertEqual(payload['StockTransferLines'][0]['Quantity'], 24)
            client.post_stock_transfer.assert_not_called()
            self.assertEqual(self.client.post(ruta, {'_empresa_id': '2'}).status_code, 409)
            self.assertEqual(client.post_inventory_transfer_request.call_count, 1)
        estado = sap_p2.estado_solicitud_traslado_new_jersey_p2(citacion)
        self.assertTrue(estado['created'])
        self.assertEqual((estado['docentry'], estado['docnum']), (5001, 5100))
        dato = DATO_OPERACION.objects.get(CI_NID=citacion, CAMP_NID__CA_CCODIGO=sap_p2.CAMPO_SOLICITUD)
        audit = json.loads(dato.DO_CVALOR)
        self.assertEqual(audit['payload'], payload)
        self.assertEqual(audit['response']['DocEntry'], 5001)
        self.assertEqual(audit['endpoint'], '/InventoryTransferRequests')
        calidad.refresh_from_db()
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion, OPL_CPASO__icontains='STOCK_TRANSFER',
        ).exists())
        with patch.object(views, 'Verificar_empresa', return_value=2):
            pagina = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]) + '?_empresa_id=2')
        self.assertTrue('DocEntry:' in pagina.content.decode())
        self.assertTrue('5001' in pagina.content.decode())

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_descarga_requiere_solicitud_sap_y_calidad_pendiente_no_bloquea(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        calidad, _ = asegurar_calidad_iniciada(citacion, self.user)
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)
        with self.assertRaisesMessage(ValueError, sap_p2.MENSAJE_SOLICITUD_REQUERIDA):
            p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'iniciar')
        self.client.force_login(self.user)
        ruta = reverse('ajax_operacion_planta_iniciar_ciclo_descarga', args=[citacion.id])
        with patch.object(views, 'Verificar_empresa', return_value=2):
            bloqueada = self.client.post(ruta, {'_empresa_id': '2', 'tipo_descarga': 'Descarga Estanque'})
        self.assertEqual(bloqueada.status_code, 409)
        self.assertIn(sap_p2.MENSAJE_SOLICITUD_REQUERIDA, bloqueada.json()['message'])
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=p2.PASO_DESCARGA).exists())
        self.simular_solicitud_sap_creada(citacion)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            permitida = self.client.post(ruta, {'_empresa_id': '2', 'tipo_descarga': 'Descarga Estanque'})
        self.assertEqual(permitida.status_code, 200, permitida.content[:400])
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_solicitud_existente_en_owtq_no_se_duplica(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        with self._mock_fuentes_sap_p2(), patch.object(
            sap_p2, 'load_config', return_value=SimpleNamespace(company_db='TEST')
        ), patch.object(
            sap_p2, 'buscar_solicitud_sap_new_jersey_p2',
            return_value={'docentry': 5000, 'docnum': 5001, 'origen': 'B_NJ_TEST', 'destino': 'TK08'},
        ), patch.object(
            sap_p2, 'SapServiceLayerClient', side_effect=AssertionError('No debe hacer POST')
        ):
            resultado = sap_p2.send_inventory_transfer_request_new_jersey_p2_to_sap(citacion, self.user)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['status']['docentry'], 5000)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD).exists())

    @override_settings(BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
    def test_resultado_sap_incierto_bloquea_reintento(self):
        p1, op, citacion = self.preparar_solicitud_sap_p2()
        with self._mock_fuentes_sap_p2(), patch.object(
            sap_p2, 'load_config', return_value=SimpleNamespace(company_db='TEST')
        ), patch.object(
            sap_p2, 'buscar_solicitud_sap_new_jersey_p2', return_value=None
        ), patch.object(sap_p2, 'SapServiceLayerClient') as client_class:
            client = client_class.return_value
            client.post_inventory_transfer_request.side_effect = TimeoutError('red interrumpida')
            primero = sap_p2.send_inventory_transfer_request_new_jersey_p2_to_sap(citacion, self.user)
            segundo = sap_p2.send_inventory_transfer_request_new_jersey_p2_to_sap(citacion, self.user)
        self.assertFalse(primero['success'])
        self.assertEqual(primero['status']['estado'], 'INCIERTO')
        self.assertFalse(segundo['success'])
        self.assertEqual(client.post_inventory_transfer_request.call_count, 1)
        self.assertTrue(sap_p2.estado_solicitud_traslado_new_jersey_p2(citacion)['blocked'])

    def test_descarga_completa_con_calidad_pendiente_deja_p3_pendiente(self):
        p1, operacion, citacion = self.preparar_solicitud_sap_p2()
        calidad, _ = asegurar_calidad_iniciada(citacion, self.user)
        self.simular_solicitud_sap_creada(citacion)
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'iniciar')
        p2.registrar_accion_p2(citacion.id, self.user, p2.PASO_DESCARGA, 'completar')
        citacion.refresh_from_db()
        operacion.refresh_from_db()
        calidad.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_3)
        self.assertEqual(calidad.RCO_CESTADO, calidad.Estado.PENDIENTE)

    def test_wrapper_usa_coleccion_confirmada_v1(self):
        cliente = SapServiceLayerClient(SimpleNamespace(base_url='https://sap.test/b1s/v1'))
        with patch.object(cliente, 'post_json', return_value={'status_code': 201}) as post:
            cliente.post_inventory_transfer_request({'StockTransferLines': []})
        self.assertEqual(post.call_args.args[0], 'InventoryTransferRequests')
        self.assertEqual(cliente.endpoint('InventoryTransferRequests'),
                         'https://sap.test/b1s/v1/InventoryTransferRequests')

    def _usuario_menu(self, codigo, nombre):
        usuario = get_user_model().objects.create_user(
            username='nj_menu_' + codigo.lower(), password='test',
        )
        perfil = PERFIL.objects.create(
            US_NID=self.user, PR_CCODIGO=codigo,
            PR_CNOMBRE=nombre, PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True,
        )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.empresa)
        return usuario, perfil

    def _menu_para(self, usuario, empresa_id=2):
        ruta = reverse('planificacion_new_jersey_p2')
        request = RequestFactory().get(ruta)
        request.user = usuario
        request.session = {'empresa_id': empresa_id}
        request.resolver_match = resolve(ruta)
        return get_template('includes/component-navbar-inner.html').render(
            {}, request=request,
        )

    def test_menu_planificador_empresa_2_muestra_p2_debajo_de_ingreso(self):
        planificador, _ = self._usuario_menu('PLAN', 'Planificador')
        html = self._menu_para(planificador)
        self.assertTrue(views.usuario_es_planificador(planificador))
        self.assertIn('New Jersey Pendientes', html)
        self.assertIn(reverse('planificacion_new_jersey_p2') + '?_empresa_id=2', html)
        self.assertLess(html.index('Ingreso de mercader'), html.index('New Jersey Pendientes'))
        self.assertLess(html.index('New Jersey Pendientes'), html.index('Transferencia'))
        self.assertIn('Despacho', html)
        self.assertIn('Planificaciones archivadas', html)

    def test_menu_no_muestra_p2_a_otro_perfil_ni_empresa(self):
        usuario, perfil = self._usuario_menu('REC', 'Recepcionista')
        vista = VISTA.objects.create(
            US_NID=self.user, VI_CCODIGO='PLANIFICACIONES',
            VI_CNOMBRE='Planificaciones', VI_BHABILITADO=True,
        )
        PERMISO.objects.create(
            US_NID=self.user, PR_NID=perfil, VI_NID=vista,
            PE_BHABILITADO=True,
        )
        html = self._menu_para(usuario)
        self.assertIn('Planificaciones', html)
        self.assertNotIn('New Jersey - P2 pendientes', html)
        planificador, _ = self._usuario_menu('PLAN', 'Planificador')
        empresa_1 = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='88-8',
            EP_CBASEDATOS='TEST1', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        USERS_EMPRESA.objects.filter(US_NID=planificador).delete()
        USERS_EMPRESA.objects.create(US_NID=planificador, EP_NID=empresa_1)
        self.assertNotIn('New Jersey - P2 pendientes', self._menu_para(planificador, 1))

    def test_ruta_planificador_muestra_p2_38732_y_accion(self):
        p1, operacion = self.crear_p1_cerrado(citacion_id=38731)
        secuencia_p2 = SECUENCIA.objects.create(
            US_NID=self.user, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=p2.SECUENCIA_P2, SE_CNOMBRE='New Jersey P2',
            SE_BHABILITADO=True,
        )
        citacion_p2 = CITACION.objects.create(
            id=38732, US_NID=self.user, EP_NID=self.empresa,
            PL_NID=self.planificacion, SC_NID=secuencia_p2,
            CI_FFECHAREGISTRO=timezone.now(), CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=0, CI_CTIPO='RECEPCION',
            CI_CESTADO=p2.ESTADO_CITACION_PENDIENTE,
            CI_CNUMERODOCUMENTO='65688', CI_NID_REF=p1.id,
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=citacion_p2, EP_NID=self.empresa, US_NID=self.user,
            CDO_CGUIA='65688', CDO_CBL_CONTENEDOR='MDFGD4533',
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=operacion, CI_NID=citacion_p2, EP_NID=self.empresa,
            US_NID=self.user,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.PENDIENTE,
        )
        operacion.ONJ_CESTADO = operacion.Estado.PENDIENTE_PROCESO_2
        operacion.save(update_fields=['ONJ_CESTADO'])
        self.assertEqual(reverse('planificacion_new_jersey_p2'), '/planificaciones/recepcion/new-jersey/p2/')
        planificador, _ = self._usuario_menu('PLAN', 'Planificador')
        self.client.force_login(planificador)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        respuesta = self.client.get(reverse('planificacion_new_jersey_p2') + '?_empresa_id=2')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.content.decode('utf-8')
        for esperado in (
            '#38731', '#38732', '65688', 'MDFGD4533',
            'Producto NJ', '950105', 'TK08', 'CON_CALIDAD',
            'PENDIENTE_PROCESO_2', 'Activar Proceso 2',
        ):
            self.assertIn(esperado, html)
        self.assertEqual(operacion.ONJ_CESTADO, operacion.Estado.PENDIENTE_PROCESO_2)

    def test_secuencia_aislada_de_p1_p3_y_prosesa(self):
        self.preparar()
        secuencia = SECUENCIA.objects.get(EP_NID=self.empresa, SE_CCODIGO=p2.SECUENCIA_P2)
        self.assertEqual(list(secuencia.detalle_secuencia_set.order_by('SE_NPASO').values_list('ET_NID__ET_CNOMBRE', flat=True)), [
            'Pendiente Proceso 2', 'Toma de muestra', 'Calidad', 'Ciclo Descarga',
        ])
        self.assertFalse(SECUENCIA.objects.filter(EP_NID=self.empresa, SE_CCODIGO='RECEPCION_NEW_JERSEY_P3_RETIRO_CONTENEDOR').exists())
        self.assertTrue(SECUENCIA.objects.filter(pk=self.secuencia_p1.pk).exists())