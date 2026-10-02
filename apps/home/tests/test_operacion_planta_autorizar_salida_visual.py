import re
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.template import Context, Template
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from apps.home import views


class AutorizarSalidaVisualTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = get_template(
            'home/CITACION/operacion_planta.html'
        ).template.source
        match = re.search(
            r'({% if paso\.activo and paso\.puede_editar %}\s*'
            r'{% if not es_new_jersey_p1 and not paso\.es_new_jersey_p3 %}\s*'
            r"{% if not paso\.es_sbh_recepcion or citacion\.SC_NID\.SE_CCODIGO != 'RECEPCION_BODEGA_EXTERNA' %}.*?"
            r'<div class="op-authorize-final-actions".*?'
            r'</div>\s*{% endif %}\s*{% endif %}\s*{% endif %})',
            cls.source,
            flags=re.DOTALL,
        )
        if not match:
            raise AssertionError('No se encontro el bloque visual de autorizacion intermedia.')
        cls.green_button_template = Template(match.group(1))
        final = re.search(
            r'(<button type="button" class="btn btn-primary btn-autorizar-salida-terramar".*?</button>)',
            cls.source, flags=re.DOTALL,
        )
        if not final:
            raise AssertionError('No se encontro el boton final de autorizacion.')
        cls.final_button_template = Template(final.group(1))

    def render_green_button(
        self,
        *,
        es_sbh_recepcion,
        secuencia,
        es_new_jersey_p1=False,
        es_new_jersey_p3=False,
    ):
        return self.green_button_template.render(Context({
            'es_new_jersey_p1': es_new_jersey_p1,
            'citacion': SimpleNamespace(
                SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
            ),
            'paso': {
                'activo': True,
                'puede_editar': True,
                'es_sbh_recepcion': es_sbh_recepcion,
                'es_new_jersey_p3': es_new_jersey_p3,
                'autorizar_salida': {
                    'revision_conformidad': {'recepcion_conforme': 'SI'},
                },
                'drafts_sap_despacho_operacionales': {
                    'aplicable': False,
                    'documentacion_completa': True,
                    'todos_actualizados': True,
                    'completos': True,
                },
            },
        }))

    def test_sbh_recepcion_bodega_externa_oculta_boton_intermedio(self):
        html = self.render_green_button(
            es_sbh_recepcion=True,
            secuencia='RECEPCION_BODEGA_EXTERNA',
        )

        self.assertNotIn('btn-autorizar-salida-operacion', html)

    def test_new_jersey_p1_oculta_boton_intermedio_en_ambas_modalidades(self):
        for secuencia in views.SECUENCIAS_RECEPCION_NEW_JERSEY_P1:
            with self.subTest(secuencia=secuencia):
                html = self.render_green_button(
                    es_sbh_recepcion=True,
                    secuencia=secuencia,
                    es_new_jersey_p1=True,
                )
                self.assertNotIn('btn-autorizar-salida-operacion', html)
                final = self.final_button_template.render(Context({
                    'paso': {'documentacion_terramar': {'timbrado_completo': True}},
                }))
                self.assertIn('btn-autorizar-salida-terramar', final)
                self.assertEqual((html + final).count('btn-autorizar-salida-'), 1)

    def test_new_jersey_p3_oculta_boton_intermedio_y_conserva_boton_final(self):
        html = self.render_green_button(
            es_sbh_recepcion=True,
            secuencia=views.SECUENCIA_RECEPCION_NEW_JERSEY_P3,
            es_new_jersey_p3=True,
        )
        final = self.final_button_template.render(Context({
            'paso': {'documentacion_terramar': {'timbrado_completo': True}},
        }))

        self.assertNotIn('btn-autorizar-salida-operacion', html)
        self.assertIn('btn-autorizar-salida-terramar', final)
        self.assertEqual((html + final).count('btn-autorizar-salida-'), 1)

    def test_otros_flujos_conservan_boton_intermedio(self):
        casos = (
            (True, 'RECEPCION_TRASVASIJE'),
            (True, 'RECEPCION_ESTANQUE_SBH'),
            (True, 'RECEPCION_PROSESA_PISO_1'),
            (True, 'RECEPCION_PROSESA_PISO_2'),
            (False, 'RECEPCION_BODEGA_EXTERNA'),
            (False, 'DESPACHO_SBH'),
        )

        for es_sbh_recepcion, secuencia in casos:
            with self.subTest(
                es_sbh_recepcion=es_sbh_recepcion,
                secuencia=secuencia,
            ):
                html = self.render_green_button(
                    es_sbh_recepcion=es_sbh_recepcion,
                    secuencia=secuencia,
                )
                self.assertIn('btn-autorizar-salida-operacion', html)

    def test_controles_independientes_y_boton_final_permanecen(self):
        self.assertIn('autorizacion-observacion-descarga', self.source)
        self.assertIn('data-observacion-target="autorizar_salida"', self.source)
        self.assertIn('op-conforme-option op-conforme-si', self.source)
        self.assertIn('op-conforme-option op-conforme-no', self.source)
        self.assertIn('btn-autorizar-salida-terramar', self.source)
        self.assertIn('btn-timbrar-documentos-terramar', self.source)
        self.assertIn('btn-exportar-documentos-terramar', self.source)

    def test_handlers_y_endpoint_compartido_permanecen(self):
        self.assertIn(
            "$(document).on('click', '.btn-autorizar-salida-operacion'",
            self.source,
        )
        self.assertIn("accion: 'guardar_conformidad'", self.source)
        self.assertIn(
            "$(document).on('click', '.btn-autorizar-salida-terramar'",
            self.source,
        )
        self.assertGreaterEqual(
            self.source.count("{% url 'ajax_operacion_planta_autorizar_salida' citacion.id %}"),
            2,
        )


class AutorizarSalidaSbhBackendContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            username='Asistente_Recepcion',
            is_superuser=False,
        )
        self.citacion = SimpleNamespace(
            id=38722,
            CI_CTIPO='RECEPCION',
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2, EP_CRAZONSOCIAL='ACEITES SBH'),
            PL_NID=None,
        )

    def request(self, **data):
        request = self.factory.post(
            '/operacion-planta/38722/autorizar-salida/',
            data,
        )
        request.user = self.user
        return request

    def common_patches(self, *, documentos_completos=True, draft_actualizado=True):
        log_queryset = Mock()
        log_queryset.order_by.return_value.first.return_value = None
        log = SimpleNamespace(OPL_FFECHAREGISTRO=timezone.now())
        return (
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(
                views,
                '_obtener_citacion_operacion_planta_ajax',
                return_value=(self.citacion, None),
            ),
            patch.object(
                views,
                'es_citacion_recepcion_terramar',
                return_value=False,
            ),
            patch.object(
                views,
                '_empresa_timbre_recepcion',
                return_value='SBH',
            ),
            patch.object(
                views,
                'obtener_pasos_operacion_citacion',
                return_value=('RECEPCION BODEGA EXTERNA', []),
            ),
            patch.object(
                views,
                'obtener_paso_activo_operacion',
                return_value=(
                    views.PASO_AUTORIZAR_SALIDA,
                    ['ASISTENTE DE RECEPCION'],
                    set(),
                ),
            ),
            patch.object(
                views,
                'usuario_puede_paso_operacion',
                return_value=True,
            ),
            patch.object(
                views,
                'es_despacho_sbh_operacion',
                return_value=False,
            ),
            patch.object(
                views,
                'es_despacho_bodega_externa_operacion',
                return_value=False,
            ),
            patch.object(
                views,
                '_leer_revision_conformidad_sbh',
                return_value={
                    'recepcion_conforme': 'SI',
                    'observacion': 'Duracion descarga: 01:04:36',
                },
            ),
            patch.object(
                views,
                'aplica_timbraje_recepcion',
                return_value=True,
            ),
            patch.object(
                views,
                '_estado_timbrado_documentos_terramar',
                return_value={'completo': documentos_completos},
            ),
            patch.object(
                views,
                'get_goods_receipt_draft_update_status',
                return_value={
                    'updated': draft_actualizado,
                    'is_error': False,
                },
            ),
            patch.object(
                views.OPERACION_PLANTA_LOG.objects,
                'filter',
                return_value=log_queryset,
            ),
            patch.object(
                views.OPERACION_PLANTA_LOG.objects,
                'create',
                return_value=log,
            ),
            patch.object(views.transaction, 'atomic', return_value=nullcontext()),
        )

    def run_final(self, *, documentos_completos=True, draft_actualizado=True):
        patches = self.common_patches(
            documentos_completos=documentos_completos,
            draft_actualizado=draft_actualizado,
        )
        registrar = patch.object(
            views,
            '_registrar_autorizar_salida',
            return_value={
                'recepcion_conforme': 'SI',
                'observacion_descarga': 'Duracion descarga: 01:04:36',
            },
        )
        with ExitStack() as stack:
            for current_patch in patches:
                stack.enter_context(current_patch)
            registrar_mock = stack.enter_context(registrar)
            response = views.ajax_operacion_planta_autorizar_salida(
                self.request(),
                self.citacion.id,
            )
        return response, registrar_mock

    def test_conformidad_se_guarda_sin_autorizar_salida(self):
        metadata = {
            'recepcion_conforme': 'SI',
            'observacion': 'Duracion descarga: 01:04:36',
        }
        with patch.object(
            views,
            'usuario_es_operacion_planta',
            return_value=True,
        ), patch.object(
            views,
            '_obtener_citacion_operacion_planta_ajax',
            return_value=(self.citacion, None),
        ), patch.object(
            views,
            'es_citacion_recepcion_terramar',
            return_value=False,
        ), patch.object(
            views,
            '_empresa_timbre_recepcion',
            return_value='SBH',
        ), patch.object(
            views,
            'usuario_es_asistente_recepcion',
            return_value=True,
        ), patch.object(
            views,
            '_paso_activo_es',
            return_value=True,
        ), patch.object(
            views,
            '_leer_revision_conformidad_sbh',
            return_value={},
        ), patch.object(
            views,
            '_recargar_citacion_bloqueada_operacion',
            return_value=self.citacion,
        ), patch.object(
            views,
            '_guardar_revision_conformidad_sbh',
            return_value=metadata,
        ) as guardar, patch.object(
            views,
            '_registrar_autorizar_salida',
        ) as autorizar, patch.object(
            views.transaction,
            'atomic',
            return_value=nullcontext(),
        ):
            response = views.ajax_operacion_planta_autorizar_salida(
                self.request(
                    accion='guardar_conformidad',
                    recepcion_conforme='SI',
                    observacion_descarga='Duracion descarga: 01:04:36',
                ),
                self.citacion.id,
            )

        self.assertEqual(response.status_code, 200)
        guardar.assert_called_once()
        autorizar.assert_not_called()

    def test_documentacion_pendiente_bloquea_autorizacion(self):
        response, registrar = self.run_final(documentos_completos=False)

        self.assertEqual(response.status_code, 409)
        self.assertIn('timbrar todos los documentos', response.content.decode())
        registrar.assert_not_called()

    def test_draft_pendiente_bloquea_autorizacion(self):
        response, registrar = self.run_final(draft_actualizado=False)

        self.assertEqual(response.status_code, 400)
        self.assertIn('actualizar el Borrador SAP', response.content.decode())
        registrar.assert_not_called()

    def test_condiciones_completas_autorizan_y_avanzan(self):
        response, registrar = self.run_final()

        self.assertEqual(response.status_code, 200)
        self.assertIn('avanzo a Confirmar Salida', response.content.decode())
        registrar.assert_called_once_with(
            self.citacion,
            self.user,
            'SI',
            'Duracion descarga: 01:04:36',
        )
