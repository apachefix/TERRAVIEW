import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.home import views


class ReintentoManualDraftSapRecepcionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            id=7,
            username="asistente_cd",
            is_authenticated=True,
            is_active=True,
            is_superuser=False,
        )
        self.citacion = SimpleNamespace(
            id=38782,
            pk=38782,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            PL_NID_id=1305,
            CI_CTIPO="RECEPCION",
            CI_BHABILITADO=True,
            SC_NID=SimpleNamespace(SE_CCODIGO="RECEPCION_ESTANQUE_SBH"),
            save=MagicMock(),
        )

    def _request(self):
        request = self.factory.post(
            "/operacion-planta/38782/borrador-sap-reintentar/",
            {"_empresa_id": "2", "empresa_id": "2"},
        )
        request.user = self.user
        return request

    def _endpoint_patches(self):
        return (
            patch.object(views, "usuario_es_operacion_planta", return_value=True),
            patch.object(
                views,
                "_obtener_citacion_operacion_planta_ajax",
                return_value=(self.citacion, None),
            ),
            patch.object(views, "es_flujo_recepcion_estanque_sbh", return_value=True),
            patch.object(views, "_usuario_tiene_acceso_empresa", return_value=True),
            patch.object(
                views,
                "usuario_puede_actualizar_borrador_sap_recepcion",
                return_value=True,
            ),
            patch.object(
                views,
                "calidad_aprobada_para_reintento_draft_sap",
                return_value=True,
            ),
            patch.object(
                views,
                "obtener_pasos_operacion_citacion",
                return_value=("Recepcion Estanque SBH", []),
            ),
            patch.object(
                views,
                "obtener_paso_activo_operacion",
                return_value=(views.PASO_RESULTADO_CALIDAD, [], set()),
            ),
        )

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=False)
    def test_flag_false_oculta_contexto_y_rechaza_endpoint(self):
        with patch.object(views, "es_flujo_recepcion_estanque_sbh") as flujo, patch.object(
            views, "crear_borrador_sap_recepcion_por_calidad_aprobada"
        ) as crear:
            contexto = views.contexto_reintento_manual_draft_sap_recepcion(
                self.citacion,
                self.user,
            )
            response = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(),
                self.citacion.id,
            )

        self.assertFalse(contexto["visible"])
        self.assertEqual(response.status_code, 404)
        flujo.assert_not_called()
        crear.assert_not_called()

        template = (
            Path(views.__file__).resolve().parents[1]
            / "templates" / "home" / "CITACION" / "operacion_planta.html"
        ).read_text(encoding="utf-8")
        self.assertIn("{% if sap_recepcion_reintento_manual.visible %}", template)
        self.assertIn("btn-reintentar-draft-sap-recepcion", template)

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_calidad_no_aprobada_rechaza_accion(self):
        patches = self._endpoint_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            views,
            "calidad_aprobada_para_reintento_draft_sap",
            return_value=False,
        ), patch.object(
            views, "crear_borrador_sap_recepcion_por_calidad_aprobada"
        ) as crear:
            response = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        self.assertEqual(response.status_code, 409)
        crear.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_calidad_aprobada_sin_draft_invoca_orquestador_y_devuelve_docentry(self):
        patches = self._endpoint_patches()
        resultado = {
            "success": True,
            "message": "Borrador creado.",
            "status_code": 201,
            "status": {
                "sent": True,
                "docentry": 9910,
                "docnum": 8810,
            },
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch.object(
            views, "get_goods_receipt_draft_guide_status", return_value={"sent": False}
        ), patch.object(
            views,
            "crear_borrador_sap_recepcion_por_calidad_aprobada",
            return_value=resultado,
        ) as crear, patch.object(
            views, "_registrar_log_reintento_manual_draft_sap"
        ) as registrar, patch.object(
            views.OPERACION_PLANTA_LOG.objects, "create"
        ) as crear_log_operacion:
            response = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["docentry"], 9910)
        self.assertEqual(payload["docnum"], 8810)
        crear.assert_called_once_with(38782, 7)
        registrar.assert_called_once()
        crear_log_operacion.assert_not_called()
        self.citacion.save.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_error_del_servicio_se_registra_y_no_avanza_etapa(self):
        patches = self._endpoint_patches()
        resultado = {
            "success": False,
            "message": "Saldo SAP insuficiente.",
            "confirmation_required": True,
            "preview": {
                "source_data": {"quantity_exceeds_remaining": True},
                "payload": {},
            },
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch.object(
            views, "get_goods_receipt_draft_guide_status", return_value={"sent": False}
        ), patch.object(
            views,
            "crear_borrador_sap_recepcion_por_calidad_aprobada",
            return_value=resultado,
        ), patch.object(
            views, "_registrar_log_reintento_manual_draft_sap"
        ) as registrar, patch.object(
            views.OPERACION_PLANTA_LOG.objects, "create"
        ) as crear_log_operacion:
            response = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        self.assertEqual(response.status_code, 400)
        registrar.assert_called_once_with(self.citacion, self.user, resultado)
        crear_log_operacion.assert_not_called()
        self.citacion.save.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_draft_existente_no_invoca_sap(self):
        patches = self._endpoint_patches()
        estado = {"sent": True, "docentry": 9910, "docnum": 8810}
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch.object(
            views, "get_goods_receipt_draft_guide_status", return_value=estado
        ), patch.object(
            views, "crear_borrador_sap_recepcion_por_calidad_aprobada"
        ) as crear, patch.object(
            views, "_registrar_log_reintento_manual_draft_sap"
        ):
            response = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["reused"])
        self.assertEqual(payload["message"], "El Draft SAP ya existe.")
        crear.assert_not_called()

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_doble_peticion_no_crea_un_segundo_draft(self):
        patches = self._endpoint_patches()
        estado_creado = {"sent": True, "docentry": 9910, "docnum": 8810}
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch.object(
            views,
            "get_goods_receipt_draft_guide_status",
            side_effect=[{"sent": False}, estado_creado],
        ), patch.object(
            views,
            "crear_borrador_sap_recepcion_por_calidad_aprobada",
            return_value={"success": True, "status": estado_creado},
        ) as crear, patch.object(
            views, "_registrar_log_reintento_manual_draft_sap"
        ):
            primera = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )
            segunda = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        crear.assert_called_once_with(38782, 7)

    @override_settings(SAP_RECEPCION_PREVIEW_ENABLED=True)
    def test_otra_secuencia_y_usuario_sin_permiso_son_rechazados(self):
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), patch.object(
            views,
            "_obtener_citacion_operacion_planta_ajax",
            return_value=(self.citacion, None),
        ), patch.object(
            views, "es_flujo_recepcion_estanque_sbh", return_value=False
        ), patch.object(
            views, "crear_borrador_sap_recepcion_por_calidad_aprobada"
        ) as crear:
            otra = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )

        self.assertEqual(otra.status_code, 404)
        crear.assert_not_called()

        patches = self._endpoint_patches()
        with patches[0], patches[1], patches[2], patches[3], patch.object(
            views,
            "usuario_puede_actualizar_borrador_sap_recepcion",
            return_value=False,
        ):
            sin_permiso = views.ajax_operacion_planta_reintentar_draft_sap_recepcion(
                self._request(), self.citacion.id
            )
        self.assertEqual(sin_permiso.status_code, 403)

    def test_log_manual_registra_datos_sap_sin_secretos(self):
        resultado = {
            "success": True,
            "status_code": 201,
            "message": "Borrador creado.",
            "response": {"DocEntry": 9910, "DocNum": 8810},
            "preview": {
                "source_data": {
                    "peso_informado_guia_kg": 16000,
                    "quantity_exceeds_remaining": False,
                },
                "payload": {
                    "DocumentLines": [{
                        "ItemCode": "600030",
                        "Quantity": 16,
                        "BaseEntry": 727,
                        "BaseLine": 0,
                        "WarehouseCode": "TK10",
                    }],
                },
            },
        }
        with patch.object(views.SYSLOGGER.objects, "create") as create_log:
            views._registrar_log_reintento_manual_draft_sap(
                self.citacion,
                self.user,
                resultado,
            )

        kwargs = create_log.call_args.kwargs
        data = json.loads(kwargs["LOG_CDESCRIPCION"])
        self.assertEqual(kwargs["LOG_COPERACION"], "REINTENTO_DRAFT_SAP_REC")
        self.assertEqual(data["citacion_id"], 38782)
        self.assertEqual(data["usuario"], "asistente_cd")
        self.assertEqual(data["item_code"], "600030")
        self.assertEqual(data["peso_informado_original"], 16000)
        self.assertEqual(data["quantity_sap"], 16)
        self.assertEqual(data["base_entry"], 727)
        self.assertEqual(data["base_line"], 0)
        self.assertEqual(data["warehouse_code"], "TK10")
        self.assertEqual(data["docentry"], 9910)
        self.assertEqual(data["docnum"], 8810)
        self.assertNotIn("password", kwargs["LOG_CDESCRIPCION"].lower())
        self.assertNotIn("cookie", kwargs["LOG_CDESCRIPCION"].lower())

    def test_log_manual_registra_fallo_y_validacion_de_cantidad(self):
        resultado = {
            "success": False,
            "message": "La cantidad informada supera la cantidad abierta en SAP.",
            "confirmation_required": True,
            "preview": {
                "source_data": {
                    "peso_informado_guia_kg": 90000,
                    "quantity": 90,
                    "quantity_exceeds_remaining": True,
                },
                "payload": {
                    "DocumentLines": [{
                        "ItemCode": "600030",
                        "Quantity": 90,
                        "BaseEntry": 727,
                        "BaseLine": 0,
                        "WarehouseCode": "TK10",
                    }],
                },
            },
        }
        with patch.object(views.SYSLOGGER.objects, "create") as create_log:
            views._registrar_log_reintento_manual_draft_sap(
                self.citacion,
                self.user,
                resultado,
            )

        data = json.loads(create_log.call_args.kwargs["LOG_CDESCRIPCION"])
        self.assertEqual(data["resultado"], "FALLIDO")
        self.assertTrue(data["confirmation_required"])
        self.assertTrue(data["quantity_exceeds_remaining"])
