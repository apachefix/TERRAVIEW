from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.home.views import APROBAR_CAMION_ASISTENTE, documentos_revision_camion, es_flujo_revision_recepcion_terramar


class RevisionCamionTerramarTests(TestCase):
    def test_identifica_terramar_por_empresa_real_de_citacion(self):
        citacion = SimpleNamespace(
            EP_NID_id=1,
            EP_NID=SimpleNamespace(EP_CRAZONSOCIAL='TERRAMAR CHILE'),
        )
        self.assertTrue(es_flujo_revision_recepcion_terramar(citacion))

        otra_empresa = SimpleNamespace(
            EP_NID_id=2,
            EP_NID=SimpleNamespace(EP_CRAZONSOCIAL='TERRAMAR CHILE'),
        )
        self.assertFalse(es_flujo_revision_recepcion_terramar(otra_empresa))

    def test_terramar_rechaza_aprobacion_sin_confirmacion(self):
        request = RequestFactory().post('/pla-citacion-aprobar-asistente/99/', {})
        request.user = SimpleNamespace(is_superuser=False, username='asistente')
        citacion = SimpleNamespace(
            EP_NID_id=1,
            EP_NID=SimpleNamespace(EP_CRAZONSOCIAL='TERRAMAR CHILE'),
            CI_CTIPO='RECEPCION',
            PL_NID=SimpleNamespace(PL_CTIPOCUPO='RECEPCION'),
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_TERRAMAR'),
        )
        manager = patch('apps.home.views.CITACION.objects.select_for_update')
        with manager as select_for_update, \
             patch('apps.home.views.usuario_es_asistente_recepcion', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=1):
            select_for_update.return_value.select_related.return_value.get.return_value = citacion
            response = APROBAR_CAMION_ASISTENTE(request, 99)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Debes confirmar que validaste los datos', response.content)

    def test_documentos_vacios_no_inventan_documentos(self):
        citacion = SimpleNamespace(EP_NID=SimpleNamespace(id=1))
        with patch('apps.home.views.CITACION_DOCUMENTO.objects.select_related') as documentos, \
             patch('apps.home.views.CAMION_PATIO_ADJUNTO.objects.select_related') as adjuntos:
            documentos.return_value.filter.return_value.order_by.return_value = []
            adjuntos.return_value.filter.return_value.order_by.return_value = []
            self.assertEqual(documentos_revision_camion(citacion, []), [])

    def test_documentos_se_filtran_por_citacion_y_empresa(self):
        citacion = SimpleNamespace(EP_NID=SimpleNamespace(id=1))
        with patch('apps.home.views.CITACION_DOCUMENTO.objects.select_related') as documentos, \
             patch('apps.home.views.CAMION_PATIO_ADJUNTO.objects.select_related') as adjuntos:
            documentos.return_value.filter.return_value.order_by.return_value = []
            adjuntos.return_value.filter.return_value.order_by.return_value = []
            documentos_revision_camion(citacion, [])
            self.assertEqual(documentos.return_value.filter.call_args.kwargs['CI_NID'], citacion)
            self.assertEqual(documentos.return_value.filter.call_args.kwargs['EP_NID'], citacion.EP_NID)
            self.assertEqual(adjuntos.return_value.filter.call_args.kwargs['CPA_NID__CI_NID'], citacion)
            self.assertEqual(adjuntos.return_value.filter.call_args.kwargs['CPA_NID__EP_NID'], citacion.EP_NID)
    def test_template_tiene_checkbox_y_bifurcacion_servida_por_backend(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn('name="datos_validados"', template)
        self.assertIn('id="revisionDatosValidados"', template)
        self.assertIn('response.mostrar_validacion_asistente_recepcion', template)
        self.assertIn('response.requiere_confirmacion_datos', template)
        self.assertIn('renderRevisionDocuments(response.documentos, !!response.es_flujo_terramar)', template)