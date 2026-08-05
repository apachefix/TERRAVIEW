from inspect import getsource
from pathlib import Path
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase

from apps.home.views import (
    SYSLOGGER_OP_ENVIA_BODEGA_GUARDIA,
    avanzar_recepcion_terramar_a_guardia,
    operacion_envio_guardia_para_citacion,
    es_citacion_recepcion_terramar,
)


class IngresoCamionTerramarTests(SimpleTestCase):
    def test_identificacion_exige_empresa_tipo_y_secuencia_terramar(self):
        citacion = SimpleNamespace(
            EP_NID_id=1,
            CI_CTIPO='RECEPCION',
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_TERRAMAR'),
        )
        self.assertTrue(es_citacion_recepcion_terramar(citacion))

        citacion.SC_NID.SE_CCODIGO = 'RECEPCION'
        self.assertFalse(es_citacion_recepcion_terramar(citacion))

    def test_terramar_exige_checkbox_antes_de_avanzar(self):
        request = RequestFactory().post('/pla-citacion-estanque-avanzar/99/', {})
        response = avanzar_recepcion_terramar_a_guardia(request, SimpleNamespace(pk=99))

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'solicitud de ingreso a descarga', response.content)

    def test_operacion_terramar_es_corta_y_no_reutiliza_envia_cd_next(self):
        self.assertLessEqual(len(SYSLOGGER_OP_ENVIA_BODEGA_GUARDIA), 24)
        source = getsource(avanzar_recepcion_terramar_a_guardia)
        self.assertIn('ENVIA_BODEGA_GUARDIA', source)
        self.assertNotIn("accion='ENVIA_CD_NEXT'", source)

    def test_operacion_previa_es_estricta_por_flujo_y_no_depende_del_request(self):
        terramar = SimpleNamespace(
            EP_NID_id=1,
            CI_CTIPO='RECEPCION',
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_TERRAMAR'),
        )
        sbh = SimpleNamespace(
            EP_NID_id=2,
            CI_CTIPO='RECEPCION',
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_SBH'),
        )
        despacho = SimpleNamespace(
            EP_NID_id=1,
            CI_CTIPO='DESPACHO',
            SC_NID=SimpleNamespace(SE_CCODIGO='DESPACHO_TERRAMAR'),
        )

        self.assertEqual(operacion_envio_guardia_para_citacion(terramar), 'ENVIA_BOD_GUARDIA')
        self.assertEqual(operacion_envio_guardia_para_citacion(sbh), 'ENVIA_CD_NEXT')
        self.assertEqual(operacion_envio_guardia_para_citacion(despacho), 'ENVIA_CD_NEXT')

    def test_template_bifurca_terramar_y_oculta_componentes_sbh(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')

        self.assertIn('if (response.es_recepcion_terramar)', template)
        self.assertIn("text('Ingreso de cam", template)
        self.assertIn('Solicitud de ingreso a descarga', template)
        self.assertIn('Confirmar y enviar a Guardia', template)
        self.assertIn('#btn_guardar_estanque, #btn_crear_borrador_sap_recepcion', template)
        self.assertIn("data: { solicitud_ingreso_descarga: '1' }", template)

    def test_avance_generico_enruta_terramar_antes_de_validar_estanque(self):
        views_source = Path('apps/home/views.py').read_text(encoding='utf-8')
        inicio = views_source.index('def AVANZAR_ESTANQUE_SIGUIENTE_ETAPA')
        bloque = views_source[inicio:views_source.index('\n\n\n', inicio)]

        self.assertIn('es_citacion_recepcion_terramar(citacion)', bloque)
        self.assertIn('request, citacion_bloqueada', bloque)

