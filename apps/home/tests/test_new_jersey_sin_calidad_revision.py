import json
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class NewJerseySinCalidadRevisionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(id=19, username='asistente_real', is_superuser=False)

    def citacion(self, codigo='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD', *, empresa=2, tipo='RECEPCION'):
        empresa_obj = SimpleNamespace(id=empresa, EP_CRAZONSOCIAL='Aceites SBH')
        etapa = SimpleNamespace(ET_CCODIGO='NJ_P1_SC_PESAJE_ENTRADA')
        planificacion = SimpleNamespace(PL_CTIPOCUPO=tipo, PL_FFECHAINICIO=None)
        return SimpleNamespace(
            id=38748,
            EP_NID_id=empresa,
            EP_NID=empresa_obj,
            PL_NID_id=1299,
            PL_NID=planificacion,
            SC_NID=SimpleNamespace(SE_CCODIGO=codigo, SE_CNOMBRE=codigo),
            CI_CTIPO=tipo,
            CI_CESTADO='EN PROCESO',
            CI_CTIPODOCUMENTO='',
            CI_CNUMERODOCUMENTO='',
            CI_CCOMENTARIO='',
            CI_FFECHACITACION=None,
            ETAPA_ACTUAL=etapa,
            TAR_NID=None,
            TAR_NID_id=None,
            RUT_NID=None,
            RUT_NID_id=None,
            CI_NVALORTARIFA=None,
            SN_NID=None,
        )

    def test_excepcion_limitada_a_secuencia_empresa_y_tipo(self):
        self.assertTrue(views.es_flujo_recepcion_new_jersey_sin_calidad(self.citacion()))
        for codigo, empresa, tipo in (
            ('RECEPCION_NEW_JERSEY_P1_CON_CALIDAD', 2, 'RECEPCION'),
            ('RECEPCION_ESTANQUE_SBH', 2, 'RECEPCION'),
            ('RECEPCION_TRANSFERENCIA_SBH', 2, 'RECEPCION'),
            ('RECEPCION_SERVICIO', 2, 'RECEPCION'),
            ('RECEPCION_TRASVASIJE', 2, 'RECEPCION'),
            ('EST_SBH_CLIENTE', 2, 'DESPACHO'),
            ('RECEPCION_TERRAMAR', 1, 'RECEPCION'),
            ('DESPACHO_TERRAMAR', 1, 'DESPACHO'),
        ):
            with self.subTest(codigo=codigo):
                self.assertFalse(views.es_flujo_recepcion_new_jersey_sin_calidad(
                    self.citacion(codigo, empresa=empresa, tipo=tipo)
                ))
        self.assertFalse(views.es_flujo_recepcion_new_jersey_sin_calidad(
            self.citacion(empresa=1)
        ))
        self.assertFalse(views.es_flujo_recepcion_new_jersey_sin_calidad(
            self.citacion(tipo='DESPACHO')
        ))
        self.assertFalse(views.es_flujo_recepcion_new_jersey_sin_calidad(
            self.citacion('RECEPCION_ESTANQUE_SBH')
        ))

    def revision(self, codigo='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD'):
        citacion = self.citacion(codigo)
        camion = SimpleNamespace(
            CPA_CTRANSPORTISTA_DECLARADO='Transportes Saez',
            CPA_CNOMBRE_CONDUCTOR='',
            CPA_CPATENTE='',
            CPA_CNUMERO_GUIA='',
            CPA_CBL='',
            CPA_CLOTE_CONTENEDOR='',
            CPA_CTELEFONO_CONDUCTOR='',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CRUT_CONDUCTOR='',
            CPA_CTIPO_RECEPCION='NACIONAL',
            CPA_CCDA='',
            CPA_CDI='',
            CPA_CNAVE_NAVIERA='',
            CPA_CFECHAPRODUCCION=None,
            CPA_CFECHAVENCIMIENTOPRODUCTO=None,
            CPA_CSUI='',
        )
        contexto = {
            'camion': camion,
            'requiere_ruta_transportista': True,
            'transporte_a_cargo': 'TERRAMAR',
            'transporte_a_cargo_display': 'Terramar',
            'usuario_ingreso_nombre': 'guardia_real',
        }
        request = self.factory.get('/pla-citacion-revision-asistente/38748/')
        request.user = self.usuario
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, 'usuario_es_asistente_recepcion', return_value=True))
            stack.enter_context(patch.object(views, 'usuario_es_guardia', return_value=False))
            stack.enter_context(patch.object(views, 'usuario_es_guardia_porteria', return_value=False))
            stack.enter_context(patch.object(views, 'Verificar_empresa', return_value=2))
            stack.enter_context(patch.object(views, 'detalle_operacional_dict', return_value={}))
            stack.enter_context(patch.object(views, 'obtener_datos_operacion_citacion', return_value=({}, [])))
            stack.enter_context(patch.object(views, 'documentos_revision_camion', return_value=[]))
            stack.enter_context(patch.object(views, 'obtener_valores_ingreso_camion', return_value={'transportista': 'Transportes Saez'}))
            stack.enter_context(patch.object(views, 'obtener_bl_inicial_citacion', return_value=''))
            stack.enter_context(patch.object(views, '_contexto_ingreso_camion_patio', return_value=contexto))
            transportistas = stack.enter_context(patch.object(views.SOCIONEGOCIO.objects, 'filter'))
            transportistas.return_value.first.return_value = None
            stack.enter_context(patch.object(views, 'datos_snapshot_recepcion_sbh_presentacion', return_value={}))
            stack.enter_context(patch.object(views, 'obtener_dato_estanque_operacional', return_value=None))
            stack.enter_context(patch.object(views, 'es_flujo_preoperacional_terramar', return_value=False))
            stack.enter_context(patch.object(views, '_empresa_timbre_recepcion', return_value='SBH'))
            stack.enter_context(patch.object(views, 'obtener_etapa_actual_operacional_citacion', return_value='Pesaje Entrada'))
            stack.enter_context(patch.object(views, 'build_datos_planificacion_terramar', return_value=None))
            stack.enter_context(patch.object(views, '_campos_presentacion_planificacion_revision_camion', return_value={}))
            stack.enter_context(patch.object(views, 'country_options', return_value=[]))
            stack.enter_context(patch.object(views, 'registrar_log_camion_no_planificado'))
            stack.enter_context(patch.object(views, 'ruta_transportista_asistente_guardada', return_value=False))
            rutas = stack.enter_context(patch.object(views, 'obtener_rutas_tarifa_transportista', return_value={
                'rutas_texto': '', 'tarifa_texto': '', 'opciones': []
            }))
            citaciones = stack.enter_context(patch.object(views.CITACION.objects, 'select_related'))
            citaciones.return_value.get.return_value = citacion
            items = stack.enter_context(patch.object(views.CITACION_ITEM.objects, 'filter'))
            items.return_value.select_related.return_value.first.return_value = None
            detalles = stack.enter_context(patch.object(views.DETALLE_SECUENCIA.objects, 'filter'))
            detalles.return_value.first.return_value = SimpleNamespace(SE_NPASO=2)
            etapas = stack.enter_context(patch.object(views.ETAPA_LOG.objects, 'filter'))
            etapas.return_value.exists.return_value = True
            logs = stack.enter_context(patch.object(views.SYSLOGGER.objects, 'select_related'))
            logs.return_value.filter.return_value.order_by.return_value.first.return_value = None
            recepcion = stack.enter_context(patch.object(views.CITACION_RECEPCION_TERRAMAR_DETALLE.objects, 'select_related'))
            recepcion.return_value.filter.return_value.first.return_value = None
            response = views.PLANIFICACION_CITACION_REVISION_ASISTENTE(request, citacion.id)
            rutas_consultadas = rutas.called
        return response, rutas_consultadas

    def test_modal_sin_calidad_pide_peso_y_no_consulta_rutas(self):
        response, rutas_consultadas = self.revision()
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertTrue(data['requiere_peso_informado_guia'])
        self.assertFalse(data['requiere_ruta_transportista'])
        self.assertTrue(data['ruta_transportista_guardada'])
        self.assertEqual(data['rutas_transportista'], {'options': [], 'message': ''})
        self.assertFalse(rutas_consultadas)

    def test_con_calidad_conserva_requisito_de_ruta_y_peso_en_revision(self):
        response, rutas_consultadas = self.revision('RECEPCION_NEW_JERSEY_P1_CON_CALIDAD')
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertTrue(data['requiere_peso_informado_guia'])
        self.assertTrue(data['requiere_ruta_transportista'])
        self.assertFalse(data['ruta_transportista_guardada'])
        self.assertTrue(rutas_consultadas)

    def test_recepcion_estanque_sbh_conserva_peso_y_ruta(self):
        response, rutas_consultadas = self.revision('RECEPCION_ESTANQUE_SBH')
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertTrue(data['requiere_peso_informado_guia'])
        self.assertTrue(data['requiere_ruta_transportista'])
        self.assertTrue(rutas_consultadas)

    def aprobar(self, peso, codigo='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD'):
        citacion = self.citacion(codigo)
        request = self.factory.post('/pla-citacion-aprobar-asistente/38748/', {
            'peso_informado_guia': peso,
            'bl': 'BL-01',
            'lote_contenedor': 'CONT-01',
        })
        request.user = self.usuario
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, 'usuario_es_asistente_recepcion', return_value=True))
            stack.enter_context(patch.object(views, 'Verificar_empresa', return_value=2))
            stack.enter_context(patch.object(views.transaction, 'atomic', return_value=nullcontext()))
            stack.enter_context(patch.object(views, 'es_flujo_preoperacional_terramar', return_value=False))
            stack.enter_context(patch.object(views, 'es_citacion_despacho', return_value=False))
            stack.enter_context(patch.object(views, '_contexto_ingreso_camion_patio', return_value={'requiere_ruta_transportista': True}))
            stack.enter_context(patch.object(views, 'obtener_detalle_operacional_citacion', return_value=None))
            stack.enter_context(patch.object(views, 'obtener_datos_operacion_citacion', return_value=({}, [])))
            stack.enter_context(patch.object(views, 'obtener_almacen_planificacion', return_value='TK-06'))
            stack.enter_context(patch.object(views, 'obtener_usuarios_asistente_cd', return_value=[]))
            stack.enter_context(patch.object(views, 'registrar_log_camion_no_planificado'))
            guardar = stack.enter_context(patch.object(views, 'guardar_dato_operacion_codigo'))
            ruta_guardada = stack.enter_context(patch.object(views, 'ruta_transportista_asistente_guardada', return_value=False))
            avance = stack.enter_context(patch.object(views, 'avanzar_citacion_a_siguiente_etapa', return_value=(
                citacion.ETAPA_ACTUAL,
                SimpleNamespace(ET_CCODIGO='NJ_P1_SC_CICLO_DESCARGA'),
            )))
            citaciones = stack.enter_context(patch.object(views.CITACION.objects, 'select_for_update'))
            citaciones.return_value.select_related.return_value.get.return_value = citacion
            detalles = stack.enter_context(patch.object(views.DETALLE_SECUENCIA.objects, 'filter'))
            detalles.return_value.first.return_value = SimpleNamespace(SE_NPASO=2)
            etapas = stack.enter_context(patch.object(views.ETAPA_LOG.objects, 'filter'))
            etapas.return_value.exists.return_value = True
            response = views.APROBAR_CAMION_ASISTENTE(request, citacion.id)
            llamadas_guardar = list(guardar.call_args_list)
            llamadas_avance = list(avance.call_args_list)
            rutas_consultadas = ruta_guardada.called
        return response, llamadas_guardar, llamadas_avance, rutas_consultadas

    def test_sin_calidad_rechaza_peso_faltante_invalido_o_cero(self):
        for valor in ('', 'abc', '0', '-2'):
            with self.subTest(valor=valor):
                response, guardar, avance, rutas = self.aprobar(valor)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(guardar)
                self.assertFalse(avance)
                self.assertFalse(rutas)

    def test_sin_calidad_aprueba_sin_ruta_guarda_peso_y_actor_y_usa_avance_existente(self):
        response, guardar, avance, rutas = self.aprobar('28650,5')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(rutas)
        peso = [call for call in guardar if call.args[1] == views.CAMPO_PESO_INFORMADO_GUIA]
        self.assertEqual(len(peso), 1)
        self.assertEqual(peso[0].args[2], '28650.5')
        self.assertIs(peso[0].args[3], self.usuario)
        self.assertEqual(len(avance), 1)
        self.assertIs(avance[0].kwargs['usuario'], self.usuario)
        self.assertEqual(avance[0].kwargs['accion'], 'APRUEBA_ASISTENTE')

    def test_con_calidad_no_acepta_aprobacion_sin_ruta(self):
        response, guardar, avance, rutas = self.aprobar('28650', 'RECEPCION_NEW_JERSEY_P1_CON_CALIDAD')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Debe guardar la ruta', response.content)
        self.assertFalse(guardar)
        self.assertFalse(avance)
        self.assertTrue(rutas)
