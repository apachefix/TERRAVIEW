from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class RecepcionSbhPesoWorkflowTests(SimpleTestCase):
    def _citacion(self, *, empresa=2, tipo='RECEPCION', secuencia='RECEPCION_ESTANQUE_SBH'):
        return SimpleNamespace(
            id=9001,
            EP_NID_id=empresa,
            EP_NID=SimpleNamespace(id=empresa),
            PL_NID_id=7001,
            PL_NID=SimpleNamespace(PL_CTIPOCUPO=tipo),
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
            CI_CTIPO=tipo,
        )

    def test_delimita_solo_recepcion_estanque_sbh(self):
        self.assertTrue(views.es_flujo_recepcion_estanque_sbh(self._citacion()))

    def test_no_aplica_a_recepcion_terramar(self):
        self.assertFalse(
            views.es_flujo_recepcion_estanque_sbh(
                self._citacion(empresa=1, secuencia='RECEPCION_TERRAMAR')
            )
        )

    def test_no_aplica_a_despacho_sbh(self):
        self.assertFalse(
            views.es_flujo_recepcion_estanque_sbh(
                self._citacion(tipo='DESPACHO', secuencia='EST_SBH_CLIENTE')
            )
        )

    def test_unidad_peso_guia_por_familia_de_recepcion(self):
        codigos_kg = (
            'RECEPCION_BODEGA_EXTERNA', 'RECEPCION_PROSESA_PISO_1',
            'RECEPCION_PROSESA_PISO_2', 'RECEPCION_ESTANQUE_SBH',
            'RECEPCION_TRASVASIJE',
            'RECEPCION_NEW_JERSEY_P1_CON_CALIDAD',
            'RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD',
            'RECEPCION_PATIO_LF_CON_CALIDAD',
        )
        with patch.object(views, 'es_recepcion_prosesa_descarga_camion', return_value=False):
            for codigo in codigos_kg:
                with self.subTest(codigo=codigo):
                    self.assertEqual(
                        views.unidad_peso_guia_revision_recepcion(
                            self._citacion(secuencia=codigo),
                        ), 'kg',
                    )
        with patch.object(views, 'es_recepcion_prosesa_descarga_camion', return_value=True):
            self.assertEqual(
                views.unidad_peso_guia_revision_recepcion(
                    self._citacion(secuencia='RECEPCION_BODEGA_EXTERNA'),
                ), 'MT',
            )

    def test_flujos_sin_peso_guia_no_se_obligan(self):
        for codigo in (
            'RECEPCION_TRANSFERENCIA_SBH',
            'RECEPCION_NEW_JERSEY_P2_OPERACION_INTERNA',
            'RECEPCION_NEW_JERSEY_P3_RETIRO_VACIO',
        ):
            with self.subTest(codigo=codigo):
                self.assertEqual(
                    views.unidad_peso_guia_revision_recepcion(
                        self._citacion(secuencia=codigo),
                    ), '',
                )
        self.assertEqual(
            views.unidad_peso_guia_revision_recepcion(
                self._citacion(empresa=1, secuencia='RECEPCION_TERRAMAR'),
            ), '',
        )
        self.assertEqual(
            views.unidad_peso_guia_revision_recepcion(
                self._citacion(tipo='DESPACHO', secuencia='RECEPCION_ESTANQUE_SBH'),
            ), '',
        )

    def test_peso_no_finito_se_rechaza(self):
        for valor in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(valor=valor):
                peso, error = views._validar_peso_informado_guia(valor)
                self.assertIsNone(peso)
                self.assertIn('mayor a 0', error)
    def test_peso_es_obligatorio(self):
        peso, error = views._validar_peso_informado_guia('')
        self.assertIsNone(peso)
        self.assertIn('Debe ingresar', error)

    def test_peso_debe_ser_mayor_a_cero(self):
        for valor in ('0', '-1'):
            peso, error = views._validar_peso_informado_guia(valor)
            self.assertIsNone(peso)
            self.assertIn('mayor a 0', error)

    def test_peso_valido_se_normaliza_sin_duplicar_concepto(self):
        peso, error = views._validar_peso_informado_guia('28650,5')
        self.assertEqual(peso, Decimal('28650.5'))
        self.assertEqual(error, '')

    @patch.object(views, 'send_goods_receipt_draft_from_peso_guia_to_sap')
    @patch.object(views, 'get_goods_receipt_draft_guide_status')
    def test_reintento_reutiliza_draft_existente(self, status_mock, enviar_mock):
        status_mock.return_value = {'sent': True, 'docentry': 123}
        resultado = views.crear_borrador_sap_recepcion_interno(
            self._citacion(), SimpleNamespace(username='acd')
        )
        self.assertTrue(resultado['success'])
        self.assertTrue(resultado['reused'])
        enviar_mock.assert_not_called()

    @patch.object(views, 'send_goods_receipt_draft_from_peso_guia_to_sap')
    @patch.object(views, 'get_goods_receipt_draft_guide_status')
    def test_sap_ok_usa_integracion_existente_una_vez(self, status_mock, enviar_mock):
        status_mock.side_effect = [
            {'sent': False},
            {'sent': True, 'docentry': 456},
        ]
        enviar_mock.return_value = {'success': True, 'status': {'sent': True, 'docentry': 456}}
        resultado = views.crear_borrador_sap_recepcion_interno(
            self._citacion(), SimpleNamespace(username='acd')
        )
        self.assertTrue(resultado['success'])
        enviar_mock.assert_called_once()

    @patch.object(views, 'send_goods_receipt_draft_from_peso_guia_to_sap')
    @patch.object(views, 'get_goods_receipt_draft_guide_status')
    def test_error_con_status_posterior_valido_no_es_falso_502(self, status_mock, enviar_mock):
        status_mock.side_effect = [
            {'sent': False},
            {'sent': True, 'docentry': 3269},
        ]
        enviar_mock.return_value = {
            'success': False,
            'message': 'Error Service Layer: Timeout durante login.',
        }
        resultado = views.crear_borrador_sap_recepcion_interno(
            self._citacion(), SimpleNamespace(username='acd')
        )
        self.assertTrue(resultado['success'])
        self.assertTrue(resultado['reused'])
        self.assertTrue(resultado['recovered_after_error'])
        self.assertEqual(resultado['status']['docentry'], 3269)

    @patch.object(views, 'registrar_log_camion_no_planificado')
    @patch.object(views, 'send_goods_receipt_draft_from_peso_guia_to_sap')
    @patch.object(views, 'get_goods_receipt_draft_guide_status')
    def test_sap_error_conserva_log_tecnico(self, status_mock, enviar_mock, log_mock):
        status_mock.return_value = {'sent': False}
        enviar_mock.return_value = {
            'success': False,
            'message': 'SAP rechazó el borrador',
            'status_code': 400,
            'sap_error': {'code': 'X'},
        }
        resultado = views.crear_borrador_sap_recepcion_interno(
            self._citacion(), SimpleNamespace(username='acd')
        )
        self.assertFalse(resultado['success'])
        log_mock.assert_called_once()
        self.assertEqual(log_mock.call_args.args[2], 'ERROR_BORRADOR_SAP')
        self.assertLessEqual(len(log_mock.call_args.args[2]), 24)

    def test_error_sap_prioriza_mensaje_real_service_layer(self):
        detalle = views.detalle_error_borrador_sap_recepcion({
            'message': 'SAP rechazo la creacion del borrador.',
            'sap_error_message': 'Enter a valid value in Whse field [DLN1.WhsCode]',
            'sap_error': {
                'data': {
                    'error': {
                        'message': {'value': 'Mensaje secundario'},
                    },
                },
            },
        })
        self.assertEqual(
            detalle,
            'Enter a valid value in Whse field [DLN1.WhsCode]',
        )

    def test_error_sap_extrae_mensaje_anidado_si_no_hay_resumen(self):
        detalle = views.detalle_error_borrador_sap_recepcion({
            'sap_error': {
                'data': {
                    'error': {
                        'message': {'value': 'Folio ya utilizado'},
                    },
                },
            },
        })
        self.assertEqual(detalle, 'Folio ya utilizado')

    def _aprobar_hasta_validaciones_sbh(self, peso, *, ruta_guardada=True):
        request = RequestFactory().post(
            '/pla-citacion-aprobar-asistente/9001/',
            {'peso_informado_guia': peso},
        )
        request.user = SimpleNamespace(is_superuser=False, username='asistente')
        citacion = self._citacion()
        citacion.CI_CESTADO = 'EN PROCESO'
        citacion.ETAPA_ACTUAL = SimpleNamespace(ET_CCODIGO='PESAJE CON ESTANQUE')
        manager = patch.object(views.CITACION.objects, 'select_for_update')
        with manager as select_for_update,              patch.object(views, 'usuario_es_asistente_recepcion', return_value=True),              patch.object(views, 'Verificar_empresa', return_value=2),              patch.object(views.transaction, 'atomic') as atomic_mock,              patch.object(views.DETALLE_SECUENCIA.objects, 'filter') as detalle_filter,              patch.object(views.ETAPA_LOG.objects, 'filter') as etapa_filter,              patch.object(views, '_contexto_ingreso_camion_patio', return_value={'requiere_ruta_transportista': True}),              patch.object(views, 'ruta_transportista_asistente_guardada', return_value=ruta_guardada):
            atomic_mock.return_value.__enter__.return_value = None
            atomic_mock.return_value.__exit__.return_value = False
            select_for_update.return_value.select_related.return_value.get.return_value = citacion
            detalle_filter.return_value.first.return_value = SimpleNamespace(SE_NPASO=2)
            etapa_filter.return_value.exists.return_value = True
            return views.APROBAR_CAMION_ASISTENTE(request, 9001)

    def test_asistente_recepcion_no_aprueba_sin_peso(self):
        response = self._aprobar_hasta_validaciones_sbh('')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Debe ingresar el peso informado', response.content)

    def test_asistente_recepcion_no_aprueba_con_peso_cero(self):
        response = self._aprobar_hasta_validaciones_sbh('0')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'mayor a 0', response.content)

    def test_asistente_recepcion_no_aprueba_sin_ruta_persistida(self):
        response = self._aprobar_hasta_validaciones_sbh('28650', ruta_guardada=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Debe guardar la ruta del transportista', response.content)
    def test_template_captura_peso_en_revision_y_lo_deja_readonly_en_acd(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('id="revision_peso_informado_guia"', template)
        self.assertIn("datos.peso_capturado_en_revision ? 'readonly'", template)
        self.assertIn("$('#btn_crear_borrador_sap_recepcion').hide()", template)

    def test_template_confirma_estanque_planificado_sin_exigir_edicion(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn("estanqueCamionEsRecepcionEstanqueSbh ? 'Confirmar estanque'", template)
        self.assertIn(
            'estanqueCamionEsRecepcionEstanqueSbh',
            template,
        )
        self.assertIn(
            '|| !selectorBloqueado',
            template,
        )
        self.assertNotIn(
            "$('#btn_editar_estanque_planificacion').show();\n"
            "                    $('#btn_guardar_estanque').prop('disabled', true);",
            template,
        )

    def test_template_evitar_doble_confirmacion_y_exige_checkbox(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('if (estanqueCamionGuardando)', template)
        self.assertIn("documentos_revisados: documentosRevisados ? '1' : ''", template)
        self.assertIn(
            'Debe confirmar que revisó los documentos antes de continuar.',
            template,
        )

    def test_error_frontend_distingue_guardado_local_de_fallo_sap(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('const estanqueGuardado =', template)
        self.assertIn('Borrador SAP no creado', template)
        self.assertIn('!!errorResponse.estanque_guardado', template)

    def test_estanque_tomado_sigue_disponible_y_no_bloquea_backend(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        inicio = source.index('def reservar_estanque_citacion')
        fin = source.index('def construir_opciones_estanque_reserva', inicio)
        reserva = source[inicio:fin]
        self.assertIn('return None, reserva_ocupada', reserva)

        inicio = source.index('def PLANIFICACION_CITACION_ESTANQUE')
        fin = source.index('def AVANZAR_ESTANQUE_SIGUIENTE_ETAPA', inicio)
        endpoint = source[inicio:fin]
        self.assertIn('if reserva_ocupada:', endpoint)
        self.assertIn('estanque_guardado', endpoint)
        self.assertNotIn('Estanque ocupado', endpoint)

        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Asignar igualmente', template)

    def test_checkbox_solo_actualiza_estado_sin_alerta_ni_request(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        inicio = template.index(".off('change.recepcion-docs'")
        fin = template.index('    $(document)', inicio + 10)
        handler = template[inicio:fin]
        self.assertIn('actualizarEstadoGuardarRecepcion();', handler)
        self.assertNotIn('Swal.fire', handler)
        self.assertNotIn('$.ajax', handler)
        self.assertNotIn('estanque_camion_bloqueo', handler)

    def test_exito_y_reapertura_bloquean_confirmacion_y_edicion(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('estanqueCamionConfirmado = estanqueCamionEsRecepcionEstanqueSbh', template)
        self.assertIn("${confirmada ? 'checked disabled' : disabled}", template)
        self.assertIn(
            "if (estanqueCamionEsRecepcionEstanqueSbh && response.estanque_confirmado)",
            template,
        )
        self.assertIn('if (!estanqueCamionPuedeEditar || estanqueCamionConfirmado)', template)
        self.assertIn(
            'estanqueCamionConfirmado || !estanqueCamionOriginalPlanificacion',
            template,
        )

    def test_backend_expone_confirmacion_y_bloquea_cambio_con_docentry(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn("estado_borrador_recepcion.get('docentry')", source)
        self.assertIn("'estanque_confirmado': estanque_confirmado", source)
        self.assertIn("'estanque_confirmado': es_flujo_recepcion_sbh", source)
        self.assertIn('if estanque_confirmado:', source)
        self.assertIn('El estanque ya fue confirmado y no puede modificarse.', source)

    def test_backend_acd_lee_peso_persistido_y_no_el_post_para_sbh(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn(
            "obtener_peso_informado_guia(citacion)\n"
            "                if peso_guia_unidad_revision",
            source,
        )
        self.assertIn('if not peso_guia_unidad_revision:', source)
        self.assertIn(
            'es_flujo_recepcion_sbh and requiere_ruta_transportista_revision(citacion) and not ruta_transportista_asistente_guardada(citacion)',
            source,
        )
        self.assertIn("'DO_FFECHAREGISTRO': timezone.now()", source)
        self.assertIn('CITACION.objects.select_for_update().get(pk=citacion.pk)', source)

    def test_aprobacion_persiste_el_campo_unico_de_peso(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn("request.POST.get('peso_informado_guia')", source)
        self.assertIn(
            "citacion, CAMPO_PESO_INFORMADO_GUIA, format(peso_informado_guia, 'f')",
            source,
        )
        self.assertEqual(views.CAMPO_PESO_INFORMADO_GUIA, 'SAP_PESO_INFORMADO_GUIA')
