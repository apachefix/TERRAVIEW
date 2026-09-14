import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class EnvioAsistenteCDDespachoSBHTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            id=7,
            username='Asistente_Despacho',
            is_superuser=False,
            is_staff=False,
        )
        self.ruta = SimpleNamespace(id=72, RUT_CNOMBRE='CORONEL -> CASTRO')
        self.tarifa = SimpleNamespace(
            id=813,
            RUT_NID=self.ruta,
            RUT_NID_id=self.ruta.id,
        )
        self.citacion = SimpleNamespace(
            id=38700,
            pk=38700,
            EP_NID_id=views.ID_ACEITES_SBH,
            EP_NID=SimpleNamespace(id=views.ID_ACEITES_SBH),
            CI_CTIPO=views.CIT_DESPACHO,
            CI_CESTADO=views.CIT_EN_PROCESO,
            PL_NID=SimpleNamespace(PL_CTIPOCUPO=views.CIT_DESPACHO),
            PL_NID_id=1266,
            SC_NID=SimpleNamespace(id=61),
            ETAPA_ACTUAL=SimpleNamespace(ET_CCODIGO='INGRESO_PLANTA'),
            TAR_NID=self.tarifa,
            TAR_NID_id=self.tarifa.id,
            RUT_NID=self.ruta,
            RUT_NID_id=self.ruta.id,
        )

    def _request(self, empresa_id=2, **overrides):
        data = {
            '_empresa_id': str(empresa_id),
            'tipo_despacho': '2',
            'tipo_traslado': '1',
        }
        data.update(overrides)
        request = self.factory.post(
            '/pla-citacion-aprobar-asistente/38700/',
            data,
        )
        request.user = self.user
        request.session = {'empresa_id': empresa_id}
        return request

    def _ejecutar(self, *, requiere_ruta, ruta_guardada, paso=2, post_data=None):
        consulta = MagicMock()
        consulta.select_related.return_value.get.return_value = self.citacion
        detalle = MagicMock()
        detalle.first.return_value = SimpleNamespace(SE_NPASO=paso)
        etapas = MagicMock()
        etapas.exists.return_value = True
        siguiente = SimpleNamespace(ET_CCODIGO='AUTORIZACION_INGRESO')
        destinatario = SimpleNamespace(id=31)

        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=consulta), \
             patch.object(views.DETALLE_SECUENCIA.objects, 'filter', return_value=detalle), \
             patch.object(views.ETAPA_LOG.objects, 'filter', return_value=etapas), \
             patch.object(views, 'es_flujo_preoperacional_terramar', return_value=False), \
             patch.object(views, 'es_flujo_recepcion_estanque_sbh', return_value=False), \
             patch.object(views, '_contexto_ingreso_camion_patio', return_value={
                 'requiere_ruta_transportista': requiere_ruta,
             }), \
             patch.object(views, 'ruta_transportista_asistente_guardada', return_value=ruta_guardada) as ruta_persistida, \
             patch.object(views, 'guardar_dato_operacion_codigo'), \
             patch.object(views, 'avanzar_citacion_a_siguiente_etapa', return_value=(
                 self.citacion.ETAPA_ACTUAL,
                 siguiente,
             )) as avanzar, \
             patch.object(views, 'obtener_datos_operacion_citacion', return_value=({}, [])), \
             patch.object(views, 'obtener_almacen_planificacion', return_value='BODEGA'), \
             patch.object(views, 'obtener_usuarios_asistente_cd', return_value=[destinatario]) as obtener_cd, \
             patch.object(views, 'crear_notificacion_interna') as notificar, \
             patch.object(views, 'registrar_log_camion_no_planificado') as registrar_log:
            response = views.APROBAR_CAMION_ASISTENTE(self._request(**(post_data or {})), self.citacion.id)

        return response, avanzar, ruta_persistida, obtener_cd, notificar, registrar_log

    def test_tipos_documento_obligatorios_y_validados_antes_de_enviar(self):
        casos = (
            ({'tipo_despacho': '', 'tipo_traslado': ''}, 'Tipo de despacho y Tipo de traslado'),
            ({'tipo_despacho': '', 'tipo_traslado': '1'}, 'Tipo de despacho'),
            ({'tipo_despacho': '2', 'tipo_traslado': ''}, 'Tipo de traslado'),
            ({'tipo_despacho': '4', 'tipo_traslado': '1'}, 'Tipo de despacho seleccionado no es válido'),
            ({'tipo_despacho': '2', 'tipo_traslado': '8'}, 'Tipo de traslado seleccionado no es válido'),
        )
        for post_data, mensaje in casos:
            with self.subTest(post_data=post_data):
                response, avanzar, _, obtener_cd, _, _ = self._ejecutar(
                    requiere_ruta=False, ruta_guardada=False, post_data=post_data,
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(mensaje, json.loads(response.content)['message'])
                avanzar.assert_not_called()
                obtener_cd.assert_not_called()
    def test_terramar_sin_ruta_no_envia_a_asistente_cd(self):
        response, avanzar, ruta_persistida, obtener_cd, notificar, registrar_log = self._ejecutar(
            requiere_ruta=True,
            ruta_guardada=False,
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('Debe guardar la ruta del transportista', json.loads(response.content)['message'])
        ruta_persistida.assert_called_once_with(self.citacion)
        avanzar.assert_not_called()
        obtener_cd.assert_not_called()
        notificar.assert_not_called()
        registrar_log.assert_not_called()

    def test_terramar_con_ruta_envia_una_etapa_y_notifica_asistente_cd(self):
        response, avanzar, ruta_persistida, obtener_cd, notificar, registrar_log = self._ejecutar(
            requiere_ruta=True,
            ruta_guardada=True,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(json.loads(response.content)['message'], 'Citacion enviada a Asistente_C_D correctamente.')
        ruta_persistida.assert_called_once_with(self.citacion)
        avanzar.assert_called_once_with(
            self.citacion,
            usuario=self.user,
            accion='ENVIA_CD_DESP_SBH',
        )
        obtener_cd.assert_called_once_with(views.ID_ACEITES_SBH)
        notificar.assert_called_once()
        self.assertIs(notificar.call_args.kwargs['USER_RECEIVER_ID'].id, 31)
        self.assertIn('pendiente de Asistente_C_D', notificar.call_args.kwargs['NOT_CCONTENIDO'])
        self.assertEqual(registrar_log.call_args.args[2], 'ENVIA_CD_DESP_SBH')
        self.assertIn('AUTORIZACION_INGRESO', registrar_log.call_args.args[3])
        self.assertNotIn('Guardia', registrar_log.call_args.args[3])

    def test_transporte_cliente_avanza_sin_exigir_ruta(self):
        self.citacion.TAR_NID = None
        self.citacion.TAR_NID_id = None
        self.citacion.RUT_NID = None
        self.citacion.RUT_NID_id = None

        response, avanzar, ruta_persistida, obtener_cd, _, registrar_log = self._ejecutar(
            requiere_ruta=False,
            ruta_guardada=False,
        )

        self.assertEqual(response.status_code, 200, response.content)
        ruta_persistida.assert_not_called()
        avanzar.assert_called_once()
        obtener_cd.assert_called_once()
        self.assertIn('Ruta transportista: No aplica (transporte a cargo del Cliente)', registrar_log.call_args.args[3])

    def test_no_permite_repetir_envio_si_la_secuencia_ya_avanzó(self):
        response, avanzar, _, obtener_cd, notificar, registrar_log = self._ejecutar(
            requiere_ruta=True,
            ruta_guardada=True,
            paso=3,
        )

        self.assertEqual(response.status_code, 409, response.content)
        avanzar.assert_not_called()
        obtener_cd.assert_not_called()
        notificar.assert_not_called()
        registrar_log.assert_not_called()

    def test_empresa_no_asignada_es_bloqueada_antes_de_consultar(self):
        with patch.object(views, 'Verificar_empresa', return_value=1), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=False), \
             patch.object(views.CITACION.objects, 'select_for_update') as consulta:
            response = views.APROBAR_CAMION_ASISTENTE(self._request(empresa_id=1), self.citacion.id)

        self.assertEqual(response.status_code, 403, response.content)
        consulta.assert_not_called()


class AccionesAsistenteDespachoTemplateTests(SimpleTestCase):
    def test_boton_envio_disponible_y_log_comparte_contenedor_horizontal(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')

        self.assertIn(
            '{% if request.user|es_asistente_recepcion or es_asistente_despacho_ingreso %}',
            template,
        )
        self.assertIn('id="btn_revision_aprobar"', template)
        self.assertIn('Enviar a Asistente_C_D', template)
        self.assertGreaterEqual(template.count('<div class="accion-log-asociacion">'), 4)
        self.assertIn('.accion-log-asociacion {', template)
        regla = template[template.index('.accion-log-asociacion {'):template.index('.acciones-enviada {')]
        self.assertIn('display: inline-flex;', regla)
        self.assertIn('flex-direction: row;', regla)
        self.assertIn('align-items: center;', regla)
        self.assertIn('gap: 12px;', regla)
        self.assertIn('flex-wrap: nowrap;', regla)
        self.assertIn('flex: 0 1 auto;', regla)
