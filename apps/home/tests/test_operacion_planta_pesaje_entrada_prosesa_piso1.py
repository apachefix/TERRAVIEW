import json
from datetime import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMPO,
    CAMION_PATIO,
    CITACION,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    SECUENCIA,
)


class PesajeEntradaProsesaPiso1Tests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="operador_pesaje_piso1",
            email="operador@example.com",
            password="test-password",
        )
        self.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL="Empresa 2",
            EP_CRUT="2-7",
            EP_CBASEDATOS="TEST",
            EP_CUSUARIOSBD="test",
            EP_CPORT="0",
        )
        self.calendario = CALENDARIO.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CA_CNOMBRE="Calendario pesaje Piso 1",
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=1,
        )
        self.planificacion = PLANIFICACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CAL_NID=self.calendario,
            PL_CTIPOCUPO="RECEPCION",
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=1,
        )
        self.secuencia = SECUENCIA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            SE_CTIPO="RECEPCION",
            SE_CCODIGO="RECEPCION_PROSESA_PISO_1",
            SE_CNOMBRE="Recepcion Prosesa Piso 1",
            SE_BHABILITADO=True,
        )
        self.etapa = ETAPA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            ET_CTIPO="OPERACION",
            ET_CCODIGO="PESAJE_ENTRADA",
            ET_CNOMBRE="Pesaje Entrada",
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        self.citacion = CITACION.objects.create(
            id=38724,
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO="RECEPCION",
            CI_CESTADO="EN PROCESO",
            CI_CNUMERODOCUMENTO="57950",
        )
        ETAPA_LOG.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            US_INICIO_ID=self.user,
            EL_FFECHAINICIO=timezone.now(),
        )

    def _crear_patentes_historica_y_vigente(self):
        campo = CAMPO.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CA_CTIPO="TEXTO",
            CA_CCODIGO="ING_PATENTE",
            CA_CETIQUETA="Patente ingreso",
            CA_BHABILITADO=True,
        )
        DATO_OPERACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            CAMP_NID=campo,
            CI_NID=self.citacion,
            DO_CVALOR="RPJX22",
            DO_FFECHAREGISTRO=timezone.now(),
        )
        return CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            CPA_CPATENTE="WR7934",
            CPA_CNOMBRE_CONDUCTOR="Conductor vigente",
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CNUMERO_GUIA="57950",
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.user,
            US_ASOCIA_ID=self.user,
            CPA_FFECHAASOCIACION=timezone.now(),
        )

    def _obtener_ticket(self, tipo_ticket, peso, folio):
        paso = "Pesaje Entrada" if tipo_ticket == "ENT" else "Pesaje Salida"
        ruta = (
            f"C:/tickets/COM_{tipo_ticket}_RPJX22_26_09_25_10_00.pdf"
        )
        request = RequestFactory().get(
            "/ajax/operacion-planta/ticket-pesaje/",
            {
                "citacion_id": str(self.citacion.pk),
                "paso_nombre": paso,
            },
        )
        request.user = self.user
        with patch.object(
            views,
            "_validar_operacion_planta_ticket_request",
            return_value=(self.citacion, tipo_ticket, None),
        ), patch.object(
            views,
            "obtener_valores_ingreso_camion",
            return_value={"patente": "RPJX22"},
        ), patch.object(
            views,
            "_buscar_ticket_pesaje_mas_reciente",
            return_value=ruta,
        ) as buscar, patch.object(
            views,
            "_extraer_datos_ticket_pesaje",
            return_value={
                "folio": folio,
                "peso_neto": peso,
                "observacion": "",
            },
        ), patch.object(
            views,
            "_copiar_ticket_local_si_necesario",
            return_value=ruta,
        ), patch.object(
            views,
            "_ruta_ticket_permitida",
            return_value=True,
        ), patch.object(
            views,
            "_ticket_pesaje_obligatorio_guardado",
            return_value=True,
        ), patch.object(
            views,
            "registrar_log_camion_no_planificado",
        ):
            response = views.ajax_operacion_planta_obtener_ticket_pesaje(request)
        return response, buscar

    def _dato_ticket(self, tipo_ticket):
        return DATO_OPERACION.objects.get(
            CI_NID_id=self.citacion.pk,
            CAMP_NID__CA_CCODIGO=f"OP_TICKET_PESAJE_{tipo_ticket}",
        )

    def test_finalizar_pesaje_persiste_peso_folio_patente_y_citacion(self):
        response, _ = self._obtener_ticket("ENT", 16850, "349362")
        self.assertEqual(response.status_code, 200)

        request = RequestFactory().post(
            f"/operacion-planta/{self.citacion.pk}/guardar-paso/",
            {"paso": "Pesaje Entrada", "observacion": ""},
        )
        request.user = self.user
        with patch.object(
            views, "usuario_es_operacion_planta", return_value=True
        ), patch.object(
            views, "Verificar_empresa", return_value=self.empresa.pk
        ), patch.object(
            views, "citacion_habilitada_operacion", return_value=True
        ), patch.object(
            views, "operacion_planta_esta_terminada", return_value=False
        ), patch.object(
            views,
            "obtener_pasos_operacion_citacion",
            return_value=(
                "RECEPCION PROSESA PISO 1",
                [("Pesaje Entrada", ["OPERACION PLANTA"])],
            ),
        ), patch.object(
            views,
            "resolver_estado_operacional_visible",
            return_value="Pesaje Entrada",
        ), patch.object(
            views, "usuario_puede_paso_operacion", return_value=True
        ), patch.object(
            views, "_ticket_pesaje_obligatorio_guardado", return_value=True
        ):
            finalizar = views.OPERACION_PLANTA_GUARDAR_PASO(
                request,
                self.citacion.pk,
            )

        self.assertEqual(finalizar.status_code, 200)
        dato = self._dato_ticket("ENT")
        metadata = json.loads(dato.DO_CVALOR)
        self.assertGreater(dato.DO_NPESO, 0)
        self.assertEqual(dato.DO_NPESO, 16850)
        self.assertEqual(dato.CI_NID_id, 38724)
        self.assertEqual(metadata["folio"], "349362")
        self.assertEqual(metadata["patente"], "RPJX22")
        self.assertEqual(metadata["tipo_ticket"], "ENT")
        self.assertEqual(metadata["citacion_id"], 38724)
        self.assertTrue(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID_id=38724,
                OPL_CPASO="Pesaje Entrada",
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            ).exists()
        )

    def test_peso_entrada_se_recupera_desde_una_nueva_consulta_orm(self):
        self._obtener_ticket("ENT", 16850, "349362")
        peso_guardado = (
            DATO_OPERACION.objects.filter(
                CI_NID_id=38724,
                CAMP_NID__CA_CCODIGO="OP_TICKET_PESAJE_ENT",
            )
            .values_list("DO_NPESO", flat=True)
            .get()
        )
        self.assertEqual(peso_guardado, 16850)

    def test_pesaje_salida_no_sobrescribe_pesaje_entrada(self):
        self._obtener_ticket("ENT", 16850, "349362")
        self._obtener_ticket("SAL", 27950, "349308")

        entrada = self._dato_ticket("ENT")
        salida = self._dato_ticket("SAL")
        self.assertNotEqual(entrada.pk, salida.pk)
        self.assertEqual(entrada.DO_NPESO, 16850)
        self.assertEqual(salida.DO_NPESO, 27950)
        self.assertEqual(json.loads(entrada.DO_CVALOR)["folio"], "349362")
        self.assertEqual(json.loads(salida.DO_CVALOR)["folio"], "349308")

    def test_repetir_obtencion_devuelve_ticket_congelado_sin_sobrescribir(self):
        primera, primera_busqueda = self._obtener_ticket(
            "ENT",
            16850,
            "349362",
        )
        segunda, segunda_busqueda = self._obtener_ticket(
            "ENT",
            99999,
            "999999",
        )

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        primera_busqueda.assert_called_once()
        segunda_busqueda.assert_not_called()
        dato = self._dato_ticket("ENT")
        metadata = json.loads(dato.DO_CVALOR)
        self.assertEqual(dato.DO_NPESO, 16850)
        self.assertEqual(metadata["folio"], "349362")
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID_id=38724,
                CAMP_NID__CA_CCODIGO="OP_TICKET_PESAJE_ENT",
            ).count(),
            1,
        )

    def test_operacion_planta_muestra_patente_vigente_de_camion_patio(self):
        self._crear_patentes_historica_y_vigente()
        self.assertEqual(
            views.obtener_valores_ingreso_camion(self.citacion)["patente"],
            "RPJX22",
        )
        request = RequestFactory().get(
            f"/operacion-planta/{self.citacion.pk}/"
        )
        request.user = self.user
        with patch.object(
            views, "usuario_es_operacion_planta", return_value=True
        ), patch.object(
            views, "Verificar_empresa", return_value=self.empresa.pk
        ), patch.object(
            views, "citacion_habilitada_operacion", return_value=True
        ), patch.object(
            views, "operacion_planta_esta_terminada", return_value=False
        ), patch.object(
            views,
            "obtener_pasos_operacion_citacion",
            return_value=(
                "RECEPCION PROSESA PISO 1",
                [("Pesaje Entrada", ["OPERADOR ROMANA"])],
            ),
        ), patch.object(
            views,
            "obtener_paso_activo_operacion",
            return_value=("Pesaje Entrada", ["OPERADOR ROMANA"], set()),
        ), patch.object(
            views, "usuario_puede_paso_operacion", return_value=True
        ), patch.object(views, "render") as render_mock:
            views.OPERACION_PLANTA_CITACION(request, self.citacion.pk)

        contexto = render_mock.call_args.args[2]
        self.assertEqual(contexto["patente"], "WR7934")
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO="ING_PATENTE",
            ).DO_CVALOR,
            "RPJX22",
        )

    def test_endpoint_romana_busca_patente_vigente_de_camion_patio(self):
        self._crear_patentes_historica_y_vigente()
        request = RequestFactory().get(
            "/ajax/operacion-planta/ticket-pesaje/",
            {
                "citacion_id": str(self.citacion.pk),
                "paso_nombre": "Pesaje Entrada",
            },
        )
        request.user = self.user
        with patch.object(
            views,
            "_validar_operacion_planta_ticket_request",
            return_value=(self.citacion, "ENT", None),
        ), patch.object(
            views,
            "_buscar_ticket_pesaje_mas_reciente",
            return_value=None,
        ) as buscar:
            response = views.ajax_operacion_planta_obtener_ticket_pesaje(
                request
            )

        self.assertEqual(response.status_code, 404)
        buscar.assert_called_once_with("WR7934", "ENT")
