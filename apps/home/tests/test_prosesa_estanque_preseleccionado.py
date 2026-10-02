import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMPO,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    PLANIFICACION,
    SECUENCIA,
)
from apps.integrations.sap_b1.sap_recepcion import es_recepcion_prosesa_descarga_camion


class ProsesaEstanquePreseleccionadoBackendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user('prosesa_estanque_test', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Prosesa estanque',
            CA_FHORA_APERTURA='08:00',
            CA_FHORA_CIERRE='18:00',
            CA_NDIA=24,
            CA_NMES=9,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA',
            SE_CNOMBRE='Descarga sobre camion',
            SE_BHABILITADO=True,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='ACD_PROSESA_TEST',
            ET_CNOMBRE='Asistente Carga y Descarga',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
        )
        cls.detalle = CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.citacion,
            EP_NID=cls.empresa,
            US_NID=cls.usuario,
            CDO_CORIGEN='planificacion',
            CDO_CALMACEN_DESTINO='PROSESA',
            CDO_CESTANQUE_DESTINO='PROSE_G2',
        )
        cls.campo_estanque = CAMPO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CTIPO='LISTA',
            CA_CCODIGO='ETA3_ESTANQUE',
            CA_CETIQUETA='Estanque',
            CA_BHABILITADO=True,
        )
        DATO_OPERACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=cls.etapa,
            CAMP_NID=cls.campo_estanque,
            CI_NID=cls.citacion,
            DO_CVALOR='PROSE_G2',
            DO_FFECHAREGISTRO=timezone.now(),
        )

        cls.campo_peso = CAMPO.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, CA_CTIPO='TEXTO',
            CA_CCODIGO=views.CAMPO_PESO_INFORMADO_GUIA,
            CA_CETIQUETA='Cantidad informada de guía (MT)',
            CA_BHABILITADO=True,
        )
        DATO_OPERACION.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa,
            SC_NID=cls.secuencia, ET_NID=cls.etapa,
            CAMP_NID=cls.campo_peso, CI_NID=cls.citacion,
            DO_CVALOR='2222', DO_FFECHAREGISTRO=timezone.now(),
        )

    def _establecer_peso_revision(self, valor):
        DATO_OPERACION.objects.filter(
            CI_NID=self.citacion, CAMP_NID=self.campo_peso,
        ).update(DO_CVALOR=valor)
    def _post(self, *, estanque='PROSE_G2', peso='9999', documentos='1'):
        request = RequestFactory().post(
            f'/pla-citacion-estanque/{self.citacion.id}/',
            {
                'almacen': 'PROSESA',
                'estanque': estanque,
                'peso_informado': peso,
                'documentos_revisados': documentos,
            },
        )
        request.user = self.usuario

        detalle_qs = MagicMock()
        detalle_qs.first.return_value = SimpleNamespace(SE_NPASO=3)
        syslogger_qs = MagicMock()
        syslogger_qs.exists.return_value = False

        with ExitStack() as stack:
            stack.enter_context(patch.object(views, 'usuario_es_asistente_cd', return_value=True))
            stack.enter_context(patch.object(views, 'Verificar_empresa', return_value=2))
            stack.enter_context(patch.object(
                views.DETALLE_SECUENCIA.objects,
                'filter',
                return_value=detalle_qs,
            ))
            stack.enter_context(patch.object(
                views.SYSLOGGER.objects,
                'filter',
                return_value=syslogger_qs,
            ))
            stack.enter_context(patch.object(
                CITACION,
                'ETAPA_ACTUAL',
                new_callable=PropertyMock,
                return_value=self.etapa,
            ))
            stack.enter_context(patch.object(views, 'es_flujo_preoperacional_terramar', return_value=False))
            stack.enter_context(patch.object(views, 'es_citacion_despacho', return_value=False))
            stack.enter_context(patch.object(views, 'es_citacion_despacho_sbh', return_value=False))
            stack.enter_context(patch.object(views, 'es_flujo_recepcion_estanque_sbh', return_value=False))
            stack.enter_context(patch.object(
                views,
                'obtener_detalle_operacional_citacion',
                return_value=self.detalle,
            ))
            stack.enter_context(patch.object(views, 'obtener_almacen_planificacion', return_value='PROSESA'))
            stack.enter_context(patch.object(views, 'obtener_valores_ingreso_camion', return_value={}))
            stack.enter_context(patch.object(
                views,
                'reservar_estanque_citacion',
                return_value=(None, None),
            ))
            stack.enter_context(patch.object(
                views,
                'obtener_campo_estanque_operacional',
                return_value=self.campo_estanque,
            ))
            stack.enter_context(patch.object(views.OPERACION_PLANTA_LOG.objects, 'create'))
            stack.enter_context(patch.object(views, 'registrar_log_camion_no_planificado'))
            stack.enter_context(patch.object(
                views,
                'get_goods_receipt_draft_guide_status',
                return_value={'sent': False},
            ))
            return views.PLANIFICACION_CITACION_ESTANQUE(request, self.citacion.id)

    def _peso_guardado(self):
        return DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_PESO_INFORMADO_GUIA,
        ).values_list('DO_CVALOR', flat=True).first()

    def test_post_acepta_estanque_preseleccionado_sin_cambiarlo(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['success'])

    def test_mismo_estanque_persistido_es_idempotente(self):
        response = self._post(estanque='PROSE_G2')
        self.detalle.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.detalle.CDO_CESTANQUE_DESTINO, 'PROSE_G2')

    def test_post_no_sobrescribe_peso_validado_en_revision(self):
        response = self._post(peso='9999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._peso_guardado(), '2222')

    def test_lee_cantidad_mt_persistida_y_conserva_escala(self):
        self._establecer_peso_revision('27.920')
        response = self._post(peso='9999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._peso_guardado(), '27.920')

    def test_ignora_post_si_revision_normalizo_coma_a_punto(self):
        self._establecer_peso_revision('27.920')
        response = self._post(peso='27,920')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._peso_guardado(), '27.920')

    def test_peso_vacio_se_rechaza(self):
        self._establecer_peso_revision('')
        response = self._post(peso='9999')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._peso_guardado(), '')

    def test_peso_cero_se_rechaza(self):
        self._establecer_peso_revision('0')
        response = self._post(peso='9999')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._peso_guardado(), '0')

    def test_check_falso_se_rechaza(self):
        response = self._post(documentos='')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._peso_guardado(), '2222')

    def test_cambio_real_de_estanque_sigue_funcionando(self):
        response = self._post(estanque='PROSE_T3')
        self.detalle.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.detalle.CDO_CESTANQUE_DESTINO, 'PROSE_T3')
        self.assertEqual(self._peso_guardado(), '2222')

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_despues_de_guardar_existen_condiciones_backend_para_preview(self):
        response = self._post()
        self.citacion.refresh_from_db()
        self.detalle.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._peso_guardado(), '2222')
        self.assertTrue(es_recepcion_prosesa_descarga_camion(self.citacion, self.detalle))


class ProsesaEstanquePreseleccionadoFrontendTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_listone.html'
        ).read_text(encoding='utf-8')

    def _guardar_body(self):
        return self.source.split(
            'function actualizarEstadoGuardarRecepcion()', 1
        )[1].split('function activarEdicionDatosRecepcion()', 1)[0]

    def test_prosesa_permite_selector_bloqueado(self):
        body = self._guardar_body()
        self.assertIn('|| estanqueCamionEsRecepcionProsesaCamion', body)
        self.assertIn('|| !selectorBloqueado', body)

    def test_habilitacion_exige_estanque_peso_positivo_y_check(self):
        body = self._guardar_body()
        self.assertIn('almacen && estanque && peso', body)
        self.assertIn('Number.isFinite(pesoNumero) && pesoNumero > 0', body)
        self.assertIn('&& documentosOk', body)

    def test_no_depende_de_dirty_flag(self):
        body = self._guardar_body()
        self.assertNotIn('dirty', body)
        self.assertNotIn('change', body)
        self.assertNotIn('editar_estanque', body)

    def test_boton_editar_estanque_se_conserva(self):
        self.assertIn('id="btn_editar_estanque_planificacion"', self.source)
        self.assertIn('function editarEstanquePlanificacionSbh()', self.source)

    def test_peso_y_checkbox_recalculan_habilitacion(self):
        self.assertIn('input.recepcion-peso', self.source)
        self.assertIn('change.recepcion-docs', self.source)
        self.assertIn('actualizarEstadoGuardarRecepcion();', self.source)

    def test_preview_se_habilita_con_peso_persistido(self):
        self.assertIn(
            'estanqueCamionPesoInformadoGuardado = true;',
            self.source,
        )
        self.assertIn(
            'estanqueCamionPreviewRecepcionHabilitado',
            self.source,
        )

    def test_crear_borrador_conserva_reglas_existentes(self):
        self.assertIn('function crearBorradorSapRecepcion()', self.source)
        self.assertIn(
            "actualizarEstadoSapRecepcionDraft(response.sap_recepcion_draft || {}, true, true, response);",
            self.source,
        )


class ProsesaEstanquePreseleccionadoIsolationTests(SimpleTestCase):
    def _caso(self, secuencia, almacen='PROSESA', empresa=2):
        citacion = SimpleNamespace(
            EP_NID_id=empresa,
            CI_CTIPO='RECEPCION',
            PL_NID=SimpleNamespace(PL_CTIPOCUPO='RECEPCION'),
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
        )
        detalle = SimpleNamespace(CDO_CALMACEN_DESTINO=almacen)
        return es_recepcion_prosesa_descarga_camion(citacion, detalle)

    def test_recepcion_estanque_sbh_no_aplica(self):
        self.assertFalse(self._caso('RECEPCION_ESTANQUE_SBH', almacen='SBH'))

    def test_prosesa_piso_1_no_aplica(self):
        self.assertFalse(self._caso('RECEPCION_PROSESA_PISO_1'))

    def test_prosesa_piso_2_no_aplica(self):
        self.assertFalse(self._caso('RECEPCION_PROSESA_PISO_2'))

    def test_trasvasije_no_aplica(self):
        self.assertFalse(self._caso('RECEPCION_TRASVASIJE', almacen='TRASVASIJE'))

    def test_empresa_1_no_aplica(self):
        self.assertFalse(self._caso('RECEPCION_BODEGA_EXTERNA', empresa=1))
