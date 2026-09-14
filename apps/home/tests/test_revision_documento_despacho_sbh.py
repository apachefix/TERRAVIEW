import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class RevisionDocumentoDespachoSbhTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id=7, is_superuser=False)
        self.citacion = SimpleNamespace(
            id=38703,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            CI_CTIPO='DESPACHO',
            CI_CESTADO='EN PROCESO',
            CI_BHABILITADO=True,
            SC_NID=SimpleNamespace(id=61),
            ETAPA_ACTUAL=SimpleNamespace(id=218),
        )

    def request(self, tipo_despacho='2', tipo_traslado='1'):
        request = self.factory.post(
            '/pla-citacion-guardar-documento-despacho-sbh/38703/',
            {'tipo_despacho': tipo_despacho, 'tipo_traslado': tipo_traslado},
        )
        request.user = self.user
        return request

    def ejecutar_guardado(self, tipo_despacho='2', tipo_traslado='1'):
        consulta = MagicMock()
        consulta.select_related.return_value.get.return_value = self.citacion
        detalle = MagicMock()
        detalle.first.return_value = SimpleNamespace(SE_NPASO=2)
        etapas = MagicMock()
        etapas.exists.return_value = True
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=consulta), \
             patch.object(views.DETALLE_SECUENCIA.objects, 'filter', return_value=detalle), \
             patch.object(views.ETAPA_LOG.objects, 'filter', return_value=etapas), \
             patch.object(views, 'es_citacion_despacho', return_value=True), \
             patch.object(views, 'guardar_dato_operacion_codigo') as guardar:
            response = views.GUARDAR_DATOS_DOCUMENTO_DESPACHO_SBH(
                self.request(tipo_despacho, tipo_traslado), self.citacion.id
            )
        return response, guardar, consulta

    def test_guarda_ambos_valores_en_dato_operacion_de_la_citacion(self):
        response, guardar, consulta = self.ejecutar_guardado('2', '1')
        self.assertEqual(response.status_code, 200, response.content)
        consulta.select_related.return_value.get.assert_called_once_with(
            pk=38703, EP_NID_id=2, CI_BHABILITADO=True
        )
        self.assertEqual(guardar.call_count, 2)
        self.assertEqual(guardar.call_args_list[0].args[:3], (
            self.citacion, views.CAMPO_TIPO_DESPACHO_SBH, '2'
        ))
        self.assertEqual(guardar.call_args_list[1].args[:3], (
            self.citacion, views.CAMPO_TIPO_TRASLADO_SBH, '1'
        ))

    def test_permite_cambiar_valores_antes_del_envio(self):
        response, guardar, _consulta = self.ejecutar_guardado('3', '6')
        self.assertEqual(json.loads(response.content)['success'], True)
        self.assertEqual(guardar.call_args_list[0].args[2], '3')
        self.assertEqual(guardar.call_args_list[1].args[2], '6')

    def test_validador_rechaza_vacios_y_valores_manipulados(self):
        casos = (
            ('', '', 'Tipo de despacho y Tipo de traslado'),
            ('', '1', 'Tipo de despacho'),
            ('2', '', 'Tipo de traslado'),
            ('4', '1', 'Tipo de despacho seleccionado no es válido'),
            ('2', '8', 'Tipo de traslado seleccionado no es válido'),
        )
        for tipo_despacho, tipo_traslado, mensaje in casos:
            with self.subTest(tipo_despacho=tipo_despacho, tipo_traslado=tipo_traslado):
                with self.assertRaisesRegex(ValueError, mensaje):
                    views.validar_tipos_documento_despacho_sbh(tipo_despacho, tipo_traslado)

    def test_modal_muestra_precarga_y_aislamiento_sbh_despacho(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        fuente = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn('<h6>Datos documento de despacho</h6>', template)
        self.assertIn('id="revision_tipo_despacho"', template)
        self.assertIn('id="revision_tipo_traslado"', template)
        self.assertIn("revisionRequiereTiposDocumentoDespacho ? renderRevisionDatosDocumentoDespacho", template)
        self.assertIn("'requiere_tipos_documento_despacho': Empresa == ID_ACEITES_SBH and es_despacho", fuente)
        self.assertIn("'tipo_despacho': dato(CAMPO_TIPO_DESPACHO_SBH)", fuente)
        self.assertIn("'tipo_traslado': dato(CAMPO_TIPO_TRASLADO_SBH)", fuente)

    def test_no_modifica_transporte_patente_ni_asignaciones_sap(self):
        fuente = Path('apps/home/views.py').read_text(encoding='utf-8')
        inicio = fuente.index('def GUARDAR_DATOS_DOCUMENTO_DESPACHO_SBH')
        fin = fuente.index('def APROBAR_CAMION_ASISTENTE', inicio)
        bloque = fuente[inicio:fin]
        self.assertNotIn('CITACION_DESPACHO_ASIGNACION_SAP', bloque)
        self.assertNotIn('CAMION_PATIO.objects', bloque)
        self.assertNotIn('CDD_CPATENTE', bloque)
        self.assertNotIn('CDD_CCONDUCTOR', bloque)

