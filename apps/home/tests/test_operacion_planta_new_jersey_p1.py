import json
import re
from datetime import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CAMION_PATIO, CITACION, CITACION_DETALLE_OPERACIONAL,
    DATO_OPERACION, EMPRESA, ETAPA, ETAPA_LOG, OPERACION_NEW_JERSEY,
    OPERACION_NEW_JERSEY_PROCESO, OPERACION_PLANTA_LOG,
    PLANIFICACION, SECUENCIA,
)


class OperacionPlantaNewJerseyP1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="nj_p1_operacion", email="nj_p1@example.com", password="test"
        )
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL="SBH", EP_CRUT="99-9",
            EP_CBASEDATOS="TEST", EP_CUSUARIOSBD="test", EP_CPORT="0",
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE="NJ P1",
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
            CA_NDIA=28, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=1,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO="RECEPCION", PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=1,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO="RECEPCION",
            SE_CCODIGO=views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD,
            SE_CNOMBRE="New Jersey con calidad", SE_BHABILITADO=True,
        )
        cls.etapa_calidad = ETAPA.objects.create(
            US_NID=cls.user, EP_NID=cls.empresa, ET_CTIPO="OPERACION",
            ET_CCODIGO="NJ_P1_CC_RESULTADO_CALIDAD",
            ET_CNOMBRE="Resultado Calidad", ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        cls.citacion = CITACION.objects.create(
            id=38731, US_NID=cls.user, EP_NID=cls.empresa,
            PL_NID=cls.planificacion, SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(), CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1, CI_CTIPO="RECEPCION", CI_CESTADO="EN PROCESO",
            CI_CTIPODOCUMENTO="GD", CI_CNUMERODOCUMENTO="65688",
        )
        ETAPA_LOG.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa_calidad, US_INICIO_ID=cls.user,
            EL_FFECHAINICIO=timezone.now(),
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa, US_NID=cls.user,
            CDO_CORIGEN="planificacion", CDO_CBL_CONTENEDOR="CONT-1",
            CDO_CESTANQUE_DESTINO="TK08",
        )
        cls.operacion_nj = OPERACION_NEW_JERSEY.objects.create(
            EP_NID=cls.empresa, US_NID=cls.user,
            ONJ_CMODALIDAD=OPERACION_NEW_JERSEY.Modalidad.CON_CALIDAD,
            ONJ_CESTADO=OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_1,
            ONJ_CITEM_CODE="ITEM-NJ", ONJ_CPRODUCTO="Producto NJ",
            ONJ_CPURCHASE_ORDER="PO-NJ", ONJ_CBASE_ENTRY="7001",
            ONJ_CBASE_LINE="2", ONJ_CBODEGA_VIRTUAL="B_NJ",
            ONJ_CTK_DESTINO="TK08",
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=cls.operacion_nj, CI_NID=cls.citacion,
            EP_NID=cls.empresa, US_NID=cls.user,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO,
        )
        cls.camion = CAMION_PATIO.objects.create(
            EP_NID=cls.empresa, CI_NID=cls.citacion, CPA_CPATENTE="SDS45",
            CPA_CNOMBRE_CONDUCTOR="DOMINGO DIAZ PEDREROS",
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CNUMERO_GUIA="65688",
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=cls.user, US_ASOCIA_ID=cls.user,
        )

    def pasos(self):
        return [nombre for nombre, _ in views.obtener_pasos_operacion_citacion(self.citacion)[1]]

    def log(self, paso):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=self.citacion, OPL_CPASO=paso,
            OPL_CPERFIL_RESPONSABLE="TEST",
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

    def guardar(self, paso, accion=""):
        data = {"paso": paso, "citacion_id": str(self.citacion.pk)}
        if accion:
            data["accion"] = accion
        request = RequestFactory().post(
            f"/operacion-planta/{self.citacion.pk}/guardar-paso/", data
        )
        request.user = self.user
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
             patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "citacion_habilitada_operacion", return_value=True), \
             patch.object(views, "_ticket_pesaje_obligatorio_guardado", return_value=True):
            return views.OPERACION_PLANTA_GUARDAR_PASO(request, self.citacion.pk)

    def test_ambas_modalidades_comienzan_en_pesaje_y_sin_calidad_visible(self):
        esperados = [
            "Pesaje Entrada", views.PASO_NJ_DESCARGA_CONTENEDOR,
            "Pesaje Salida", views.PASO_AUTORIZAR_SALIDA,
            views.PASO_CONFIRMAR_SALIDA,
        ]
        for codigo in views.SECUENCIAS_RECEPCION_NEW_JERSEY_P1:
            with self.subTest(codigo=codigo):
                self.citacion.SC_NID.SE_CCODIGO = codigo
                self.assertEqual(self.pasos(), esperados)
                self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                                 "Pesaje Entrada")
                self.assertNotIn("Resultado Calidad", self.pasos())
                self.assertNotIn(views.PASO_PROSESA_DEPOSITAR_PISO_1, self.pasos())
                self.assertNotIn(views.PASO_PROSESA_INICIO_RETIRO, self.pasos())
        self.secuencia.refresh_from_db()

    def test_pagina_con_etapa_tecnica_calidad_muestra_barra_new_jersey(self):
        request = RequestFactory().get(f"/operacion-planta/{self.citacion.pk}/")
        request.user = self.user
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
             patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "citacion_habilitada_operacion", return_value=True), \
             patch.object(views, "render") as render:
            views.OPERACION_PLANTA_CITACION(request, self.citacion.pk)
        pasos = render.call_args.args[2]["pasos"]
        self.assertEqual([paso["nombre"] for paso in pasos], [
            "Pesaje Entrada", views.PASO_NJ_DESCARGA_CONTENEDOR,
            "Pesaje Salida", views.PASO_AUTORIZAR_SALIDA,
            views.PASO_CONFIRMAR_SALIDA,
        ])
        self.assertEqual([paso["nombre"] for paso in pasos if paso["activo"]],
                         ["Pesaje Entrada"])
        self.assertEqual(pasos[1]["responsable"], "ASISTENTE C D")
        self.assertTrue(pasos[1]["requiere_descarga_contenedor_new_jersey"])
        self.assertEqual(pasos[1]["descarga_contenedor_new_jersey"]["contenedor"],
                         "CONT-1")
        self.assertEqual(pasos[1]["descarga_contenedor_new_jersey"]["destino_fisico"],
                         "TK08")

    def test_ambas_modalidades_conservan_bloque_documental_y_condicion_visual(self):
        self.empresa.EP_CRAZONSOCIAL = "ACEITES SBH SpA"
        self.empresa.save(update_fields=["EP_CRAZONSOCIAL"])
        for paso in ("Pesaje Entrada", views.PASO_NJ_DESCARGA_CONTENEDOR,
                     "Pesaje Salida"):
            self.log(paso)
        for codigo in views.SECUENCIAS_RECEPCION_NEW_JERSEY_P1:
            with self.subTest(codigo=codigo):
                self.secuencia.SE_CCODIGO = codigo
                self.secuencia.save(update_fields=["SE_CCODIGO"])
                request = RequestFactory().get(f"/operacion-planta/{self.citacion.pk}/")
                request.user = self.user
                request.session = {}
                with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
                     patch.object(views, "Verificar_empresa", return_value=2), \
                     patch.object(views, "citacion_habilitada_operacion", return_value=True), \
                     patch.object(views, "render") as render:
                    views.OPERACION_PLANTA_CITACION(request, self.citacion.pk)
                contexto = render.call_args.args[2]
                autorizar = next(paso for paso in contexto["pasos"]
                                 if paso["nombre"] == views.PASO_AUTORIZAR_SALIDA)
                self.assertTrue(contexto["es_new_jersey_p1"])
                self.assertTrue(autorizar["requiere_autorizar_salida"])
                self.assertTrue(autorizar["requiere_autorizar_salida_terramar"])
                html = get_template(
                    "home/CITACION/operacion_planta.html"
                ).render(contexto, request=request)
                self.assertEqual(len(re.findall(
                    r'<button[^>]*class="[^"]*btn-autorizar-salida-operacion', html,
                )), 0)
                self.assertEqual(len(re.findall(
                    r'<button[^>]*class="[^"]*btn-autorizar-salida-terramar', html,
                )), 1)
                self.assertIn("btn-timbrar-documentos-terramar", html)
                self.assertIn("op-conforme-option op-conforme-si", html)
                self.assertIn("op-conforme-option op-conforme-no", html)

    def test_boton_final_exige_conformidad_y_timbraje_antes_de_avanzar(self):
        self.empresa.EP_CRAZONSOCIAL = "ACEITES SBH SpA"
        self.empresa.save(update_fields=["EP_CRAZONSOCIAL"])
        for paso in ("Pesaje Entrada", views.PASO_NJ_DESCARGA_CONTENEDOR,
                     "Pesaje Salida"):
            self.log(paso)

        def solicitar(**datos):
            request = RequestFactory().post(
                f"/operacion-planta/{self.citacion.pk}/autorizar-salida/", datos,
            )
            request.user = self.user
            with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
                 patch.object(views, "_obtener_citacion_operacion_planta_ajax",
                              return_value=(self.citacion, None)):
                return views.ajax_operacion_planta_autorizar_salida(
                    request, self.citacion.pk,
                )

        self.assertEqual(solicitar().status_code, 409)
        self.assertEqual(solicitar(
            accion="guardar_conformidad", recepcion_conforme="NO",
            observacion_descarga="Revisi?n registrada",
        ).status_code, 200)
        with patch.object(views, "_estado_timbrado_documentos_terramar",
                          return_value={"completo": False}):
            pendiente = solicitar()
        self.assertEqual(pendiente.status_code, 409)
        self.assertIn("timbrar", pendiente.content.decode().lower())
        with patch.object(views, "_estado_timbrado_documentos_terramar",
                          return_value={"completo": True}):
            autorizado = solicitar(recepcion_conforme="SI")
        self.assertEqual(autorizado.status_code, 200)
        self.assertEqual(
            views._payload_autorizar_salida(self.citacion)["recepcion_conforme"],
            "NO",
        )
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         views.PASO_CONFIRMAR_SALIDA)

    def test_pesaje_entrada_activa_descarga_y_reutiliza_ticket(self):
        request = RequestFactory().post(
            f"/operacion-planta/{self.citacion.pk}/guardar-paso/",
            {"paso": "Pesaje Entrada"},
        )
        request.user = self.user
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
             patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "citacion_habilitada_operacion", return_value=True):
            bloqueado = views.OPERACION_PLANTA_GUARDAR_PASO(
                request, self.citacion.pk
            )
        self.assertEqual(bloqueado.status_code, 400)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion, OPL_CPASO="Pesaje Entrada"
        ).exists())
        entrada = self.guardar("Pesaje Entrada")
        self.assertEqual(entrada.status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         views.PASO_NJ_DESCARGA_CONTENEDOR)
        self.assertEqual(views.PASOS_OPERACION_PLANTA_TICKET["Pesaje Entrada"], "ENT")
        self.assertEqual(views.PASOS_OPERACION_PLANTA_TICKET["Pesaje Salida"], "SAL")

    def test_validacion_ticket_existente_acepta_entrada_y_salida_new_jersey(self):
        request = RequestFactory().get("/operacion-planta/ticket-pesaje/")
        request.user = self.user
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
             patch.object(views, "Verificar_empresa", return_value=2):
            _, tipo_entrada, error_entrada = views._validar_operacion_planta_ticket_request(
                request, self.citacion.pk, "Pesaje Entrada"
            )
            self.assertIsNone(error_entrada)
            self.assertEqual(tipo_entrada, "ENT")
            self.log("Pesaje Entrada")
            self.log(views.PASO_NJ_DESCARGA_CONTENEDOR)
            _, tipo_salida, error_salida = views._validar_operacion_planta_ticket_request(
                request, self.citacion.pk, "Pesaje Salida"
            )
        self.assertIsNone(error_salida)
        self.assertEqual(tipo_salida, "SAL")

    def test_descarga_registra_inicio_fin_contenedor_destino_y_usuario(self):
        self.log("Pesaje Entrada")
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         views.PASO_NJ_DESCARGA_CONTENEDOR)
        confirmar_antes = self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "confirmar")
        self.assertEqual(confirmar_antes.status_code, 409)
        inicio = self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "iniciar")
        self.assertEqual(inicio.status_code, 200)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion, OPL_CPASO=views.PASO_NJ_DESCARGA_CONTENEDOR
        ).exists())
        metadata = json.loads(DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_NJ_DESCARGA_CONTENEDOR,
        ).DO_CVALOR)
        self.assertEqual(metadata["citacion_id"], self.citacion.pk)
        self.assertEqual(metadata["contenedor"], "CONT-1")
        self.assertEqual(metadata["destino_fisico"], "TK08")
        self.assertEqual(metadata["usuario_inicio"], self.user.username)
        self.assertTrue(metadata["inicio_iso"])
        fin = self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "confirmar")
        self.assertEqual(fin.status_code, 200)
        metadata = json.loads(DATO_OPERACION.objects.get(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_NJ_DESCARGA_CONTENEDOR,
        ).DO_CVALOR)
        self.assertTrue(metadata["fin_iso"])
        self.assertEqual(metadata["usuario_fin"], self.user.username)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion, OPL_CPASO=views.PASO_NJ_DESCARGA_CONTENEDOR,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).count(), 1)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         "Pesaje Salida")

    def test_descarga_no_acepta_contenedor_ausente_ni_perfil_ajeno(self):
        self.log("Pesaje Entrada")
        detalle = self.citacion.detalle_operacional
        detalle.CDO_CBL_CONTENEDOR = ""
        detalle.save(update_fields=["CDO_CBL_CONTENEDOR"])
        self.assertEqual(
            self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "iniciar").status_code,
            409,
        )
        self.assertFalse(DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_NJ_DESCARGA_CONTENEDOR,
        ).exists())
        detalle.CDO_CBL_CONTENEDOR = "CONT-1"
        detalle.save(update_fields=["CDO_CBL_CONTENEDOR"])
        request = RequestFactory().post(
            f"/operacion-planta/{self.citacion.pk}/guardar-paso/",
            {"paso": views.PASO_NJ_DESCARGA_CONTENEDOR, "accion": "iniciar"},
        )
        request.user = self.user
        with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
             patch.object(views, "Verificar_empresa", return_value=2), \
             patch.object(views, "citacion_habilitada_operacion", return_value=True), \
             patch.object(views, "usuario_puede_paso_operacion", return_value=False):
            response = views.OPERACION_PLANTA_GUARDAR_PASO(request, self.citacion.pk)
        self.assertEqual(response.status_code, 403)

    def test_pesaje_salida_autorizar_y_confirmar_cierran_ciclo(self):
        self.log("Pesaje Entrada")
        self.assertEqual(
            self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "iniciar").status_code,
            200,
        )
        self.assertEqual(
            self.guardar(views.PASO_NJ_DESCARGA_CONTENEDOR, "confirmar").status_code,
            200,
        )
        salida = self.guardar("Pesaje Salida")
        self.assertEqual(salida.status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         views.PASO_AUTORIZAR_SALIDA)
        self.assertTrue(views._payload_descarga_contenedor_new_jersey(
            self.citacion
        )["finalizada"])
        with patch.object(views, "get_goods_receipt_draft_update_status",
                          side_effect=AssertionError("New Jersey no usa Draft")):
            revisar = RequestFactory().post(
                f"/operacion-planta/{self.citacion.pk}/autorizar-salida/",
                {"accion": "guardar_conformidad", "recepcion_conforme": "SI"},
            )
            revisar.user = self.user
            autorizar = RequestFactory().post(
                f"/operacion-planta/{self.citacion.pk}/autorizar-salida/", {}
            )
            autorizar.user = self.user
            with patch.object(views, "usuario_es_operacion_planta", return_value=True), \
                 patch.object(views, "_obtener_citacion_operacion_planta_ajax",
                              return_value=(self.citacion, None)):
                self.assertEqual(views.ajax_operacion_planta_autorizar_salida(
                    revisar, self.citacion.pk
                ).status_code, 200)
                self.assertEqual(views.ajax_operacion_planta_autorizar_salida(
                    autorizar, self.citacion.pk
                ).status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0],
                         views.PASO_CONFIRMAR_SALIDA)
        cierre = self.guardar(views.PASO_CONFIRMAR_SALIDA)
        self.assertEqual(cierre.status_code, 200)
        self.citacion.refresh_from_db()
        self.camion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertEqual(self.camion.CPA_CESTADO,
                         CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        self.assertTrue(views.operacion_planta_esta_terminada(self.citacion))
        proceso_p2 = OPERACION_NEW_JERSEY_PROCESO.objects.get(
            ONJ_NID=self.operacion_nj,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
        )
        self.assertEqual(proceso_p2.ONJP_CESTADO, proceso_p2.Estado.PENDIENTE)
        self.assertEqual(proceso_p2.CI_NID.CI_CNUMERODOCUMENTO, "65688")
        self.operacion_nj.refresh_from_db()
        self.assertEqual(
            self.operacion_nj.ONJ_CESTADO,
            OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_2,
        )

    def test_p2_y_p3_no_usan_los_pasos_de_proceso_1(self):
        for codigo in (
            views.SECUENCIA_RECEPCION_NEW_JERSEY_P2,
            views.SECUENCIA_RECEPCION_NEW_JERSEY_P3,
        ):
            with self.subTest(codigo=codigo):
                self.citacion.SC_NID.SE_CCODIGO = codigo
                self.assertFalse(views.es_recepcion_new_jersey_p1(self.citacion))
                self.assertNotIn(views.PASO_NJ_DESCARGA_CONTENEDOR, self.pasos())

    def test_prosesa_estanque_y_empresa_1_no_reciben_flujo_new_jersey(self):
        self.citacion.SC_NID.SE_CCODIGO = views.SECUENCIA_RECEPCION_PROSESA_PISO_1
        self.assertIn(views.PASO_PROSESA_DEPOSITAR_PISO_1, self.pasos())
        self.citacion.SC_NID.SE_CCODIGO = views.SECUENCIA_RECEPCION_ESTANQUE_SBH
        self.assertNotEqual(self.pasos(), [
            "Pesaje Entrada", views.PASO_NJ_DESCARGA_CONTENEDOR,
            "Pesaje Salida", views.PASO_AUTORIZAR_SALIDA,
            views.PASO_CONFIRMAR_SALIDA,
        ])
        self.citacion.SC_NID.SE_CCODIGO = views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD
        self.citacion.EP_NID_id = 1
        self.assertFalse(views.es_recepcion_new_jersey_p1(self.citacion))

