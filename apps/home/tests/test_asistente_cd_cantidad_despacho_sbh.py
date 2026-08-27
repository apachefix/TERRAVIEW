from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.home import views


class AsistenteCdCantidadDespachoSbhTests(SimpleTestCase):
    def _citacion(self, empresa_id=2, tipo='DESPACHO', cantidad=Decimal('1')):
        detalle = SimpleNamespace(
            CDD_NCANTIDAD_INTENTADA_DESPACHAR=cantidad,
            CDD_NPESO_INFORMADO=Decimal('99'),
            save=Mock(),
        )
        citacion = SimpleNamespace(
            EP_NID_id=empresa_id,
            EP_NID=SimpleNamespace(id=empresa_id),
            CI_CTIPO=tipo,
            PL_NID=None,
            ETAPA_ACTUAL=SimpleNamespace(id=3),
            detalle_despacho=detalle,
        )
        return citacion, detalle

    def test_payload_usa_cantidad_planificada_y_no_pesos_legacy(self):
        citacion, _ = self._citacion(cantidad=Decimal('1'))
        datos_operacion = {
            'ACD_PESO_INFORMADO': SimpleNamespace(DO_CVALOR='25000'),
        }

        datos = views.datos_asistente_cd_despacho(
            citacion,
            datos_operacion=datos_operacion,
            detalle_operacional={'codigo': 'ITEM-1'},
        )

        self.assertEqual(datos['cantidad_intentada_despachar'], '1')
        self.assertEqual(datos['peso_informado'], '25000')

    @patch('apps.home.views.obtener_detalle_operacional_citacion', return_value=None)
    @patch('apps.home.views.guardar_dato_operacion_codigo')
    def test_guardado_sbh_ignora_peso_inyectado_y_no_modifica_detalle(
        self, guardar_dato, _obtener_detalle
    ):
        citacion, detalle = self._citacion(cantidad=Decimal('1'))
        data = {
            'zona_carga': 'Linea 1',
            'estanque_origen': 'EST-1',
            'codigo_sap': 'ITEM-1',
            'numero_bach': 'BATCH-1',
            'intermes_id': 'LOTE-1',
            'peso_informado': '999',
            'lote_quantity': '10',
            'lote_status': '0',
        }

        ok, mensaje = views.guardar_datos_asistente_cd_despacho(
            citacion, data, SimpleNamespace(id=1)
        )

        self.assertTrue(ok, mensaje)
        codigos_guardados = [call.args[1] for call in guardar_dato.call_args_list]
        self.assertNotIn('ACD_PESO_INFORMADO', codigos_guardados)
        self.assertEqual(detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR, Decimal('1'))
        self.assertEqual(detalle.CDD_NPESO_INFORMADO, Decimal('99'))
        detalle.save.assert_not_called()

    def test_otros_despachos_conservan_requisito_de_peso(self):
        citacion, _ = self._citacion(empresa_id=1)
        datos = views.datos_asistente_cd_despacho(
            citacion,
            datos_operacion={},
            detalle_operacional={'codigo': 'ITEM-1'},
        )

        self.assertFalse(views.es_citacion_despacho_sbh(citacion))
        with patch('apps.home.views.detalle_operacional_dict', return_value={'codigo': 'ITEM-1'}):
            self.assertFalse(views.datos_asistente_cd_despacho_guardados(citacion, {}))
        self.assertEqual(datos['peso_informado'], '99')

    def test_template_aplica_readonly_solo_con_bandera_sbh(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')

        self.assertIn("response.es_despacho_sbh ? 'readonly' : disabled", template)
        self.assertIn('Cantidad intentada a despachar', template)
        self.assertIn('Cantidad definida previamente en la planificaci&oacute;n.', template)



class AsistenteCdGuardarDraftDespachoSbhTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(EP_NID_id=2, CI_CTIPO='DESPACHO')
        self.usuario = SimpleNamespace(id=1, username='asistente_cd')
        self.data = {'zona_carga': 'Linea 1'}

    @patch('apps.home.views.sap_despacho_crear_borrador', return_value={'success': True})
    @patch('apps.home.views.guardar_datos_asistente_cd_despacho', return_value=(True, 'OK'))
    @patch('apps.home.views.get_sap_despacho_draft_status')
    def test_guardar_crea_draft_automaticamente(
        self, estado_draft, guardar_datos, crear_draft
    ):
        estado_draft.side_effect = [
            {'created': False},
            {'created': True, 'docentry': '3273', 'docnum': '6527'},
        ]

        ok, resultado = views.guardar_datos_y_crear_draft_despacho_sbh(
            self.citacion, self.data, self.usuario
        )

        self.assertTrue(ok)
        self.assertTrue(resultado['datos_guardados'])
        self.assertTrue(resultado['draft_sap']['created'])
        self.assertTrue(resultado['puede_avanzar'])
        guardar_datos.assert_called_once_with(self.citacion, self.data, self.usuario)
        crear_draft.assert_called_once_with(self.citacion, self.usuario)

    @patch('apps.home.views.sap_despacho_crear_borrador')
    @patch('apps.home.views.guardar_datos_asistente_cd_despacho', return_value=(True, 'OK'))
    @patch('apps.home.views.get_sap_despacho_draft_status')
    def test_error_sap_conserva_guardado_local_y_permite_retry(
        self, estado_draft, guardar_datos, crear_draft
    ):
        estado_draft.side_effect = [
            {'created': False},
            {'created': False},
            {'created': False},
            {'created': True, 'docentry': '3273'},
        ]
        crear_draft.side_effect = [
            {
                'success': False,
                'message': 'SAP rechazo la creacion del borrador de despacho.',
                'sap_error': {
                    'data': {
                        'error': {
                            'message': {'value': "Update the exchange rate 'CLP'"}
                        }
                    }
                },
            },
            {'success': True},
        ]

        ok_error, resultado_error = views.guardar_datos_y_crear_draft_despacho_sbh(
            self.citacion, self.data, self.usuario
        )
        ok_retry, resultado_retry = views.guardar_datos_y_crear_draft_despacho_sbh(
            self.citacion, self.data, self.usuario
        )

        self.assertFalse(ok_error)
        self.assertTrue(resultado_error['datos_guardados'])
        self.assertFalse(resultado_error['puede_avanzar'])
        self.assertEqual(resultado_error['sap_message'], "Update the exchange rate 'CLP'")
        self.assertTrue(ok_retry)
        self.assertTrue(resultado_retry['puede_avanzar'])
        self.assertEqual(guardar_datos.call_count, 2)
        self.assertEqual(crear_draft.call_count, 2)

    @patch('apps.home.views.datos_asistente_cd_despacho_guardados', return_value=True)
    @patch('apps.home.views.obtener_datos_operacion_citacion', return_value=({}, []))
    @patch('apps.home.views.sap_despacho_crear_borrador')
    @patch('apps.home.views.guardar_datos_asistente_cd_despacho')
    @patch('apps.home.views.get_sap_despacho_draft_status', return_value={
        'created': True,
        'docentry': '3273',
    })
    def test_draft_existente_no_guarda_ni_crea_duplicado(
        self, _estado, guardar_datos, crear_draft, _datos, _datos_guardados
    ):
        ok, resultado = views.guardar_datos_y_crear_draft_despacho_sbh(
            self.citacion, self.data, self.usuario
        )

        self.assertTrue(ok)
        self.assertTrue(resultado['already_created'])
        self.assertTrue(resultado['puede_avanzar'])
        guardar_datos.assert_not_called()
        crear_draft.assert_not_called()

    @patch('apps.home.views.sap_despacho_crear_borrador')
    @patch('apps.home.views.guardar_datos_asistente_cd_despacho', return_value=(False, 'Falta lote'))
    @patch('apps.home.views.get_sap_despacho_draft_status', return_value={'created': False})
    def test_validacion_local_fallida_no_llama_sap(
        self, _estado, _guardar_datos, crear_draft
    ):
        ok, resultado = views.guardar_datos_y_crear_draft_despacho_sbh(
            self.citacion, self.data, self.usuario
        )

        self.assertFalse(ok)
        self.assertFalse(resultado['datos_guardados'])
        self.assertFalse(resultado['puede_avanzar'])
        crear_draft.assert_not_called()

    def test_template_oculta_accion_manual_y_panel_tecnico_solo_sbh(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')

        self.assertIn("if (estanqueCamionEsDespachoSbh)", template)
        self.assertIn("$('#btn_crear_borrador_sap_despacho').hide().prop('disabled', true);", template)
        self.assertIn("$('#sap_despacho_draft_panel').empty().hide();", template)
        self.assertIn("if (estanqueCamionGuardando)", template)
        self.assertNotIn("Guardando datos y creando Draft SAP...", template)
        self.assertIn(".text('Datos guardados correctamente.');", template)
        self.assertIn(
            ".text('No fue posible completar el guardado. Intente nuevamente o contacte a soporte.');",
            template,
        )

    def test_respuesta_operador_exitosa_omite_metadata_sap(self):
        respuesta = views.respuesta_guardado_despacho_sbh_operador(True, {
            'datos_guardados': True,
            'puede_avanzar': True,
            'draft_sap': {'created': True, 'docentry': '3273', 'docnum': '6527'},
            'sap_message': 'Detalle tecnico',
        })

        self.assertEqual(respuesta, {
            'success': True,
            'message': 'Datos guardados correctamente.',
            'datos_guardados': True,
            'puede_avanzar': True,
        })

    def test_respuesta_operador_error_interno_es_generica(self):
        respuesta = views.respuesta_guardado_despacho_sbh_operador(False, {
            'datos_guardados': True,
            'puede_avanzar': False,
            'draft_sap': {'created': False, 'docentry': '3273'},
            'sap_message': 'CompanyDB y endpoint /Drafts',
        })

        self.assertEqual(
            respuesta['message'],
            'No fue posible completar el guardado. Intente nuevamente o contacte a soporte.',
        )
        self.assertNotIn('draft_sap', respuesta)
        self.assertNotIn('sap_message', respuesta)
        self.assertFalse(respuesta['puede_avanzar'])

    def test_respuesta_operador_conserva_validacion_funcional(self):
        respuesta = views.respuesta_guardado_despacho_sbh_operador(False, {
            'datos_guardados': False,
            'puede_avanzar': False,
            'message': 'Debe seleccionar un lote valido.',
        })

        self.assertEqual(respuesta['message'], 'Debe seleccionar un lote valido.')
        self.assertFalse(respuesta['datos_guardados'])

    @patch('apps.home.views.OPERACION_PLANTA_LOG.objects')
    @patch('apps.home.views.get_sap_despacho_draft_status', return_value={'created': False})
    def test_reabrir_modal_recupera_error_sap_seguro(self, _estado, logs):
        logs.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            OPL_CESTADO=views.OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
            OPL_COBSERVACION='{"sap_error":{"data":{"error":{"message":{"value":"Update the exchange rate CLP"}}}}}',
        )

        estado = views.estado_draft_sap_despacho_modal(self.citacion)

        self.assertTrue(estado['is_error'])
        self.assertEqual(estado['label'], 'Error al crear Draft SAP')
        self.assertEqual(estado['error_message'], 'Update the exchange rate CLP')

    @patch('apps.home.views.sap_despacho_crear_borrador')
    @patch('apps.home.views.guardar_datos_asistente_cd_despacho')
    def test_orquestacion_automatica_rechaza_despacho_no_sbh(
        self, guardar_datos, crear_draft
    ):
        citacion_terramar = SimpleNamespace(EP_NID_id=1, CI_CTIPO='DESPACHO')

        ok, resultado = views.guardar_datos_y_crear_draft_despacho_sbh(
            citacion_terramar, self.data, self.usuario
        )

        self.assertFalse(ok)
        self.assertFalse(resultado['puede_avanzar'])
        guardar_datos.assert_not_called()
        crear_draft.assert_not_called()

    def test_backend_exige_datos_y_draft_antes_de_avanzar_sbh(self):
        views_source = Path('apps/home/views.py').read_text(encoding='utf-8')

        self.assertIn(
            'Debe guardar correctamente los datos antes de avanzar.',
            views_source,
        )