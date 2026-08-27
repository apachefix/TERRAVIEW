from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class TicketMopDespachoTerramarHelpersTests(SimpleTestCase):
    def test_condicion_estricta_exige_flujo_paso_y_tipo_ticket(self):
        def citacion(empresa=1, tipo='DESPACHO', secuencia='DESPACHO_TERRAMAR'):
            return SimpleNamespace(
                EP_NID_id=empresa,
                CI_CTIPO=tipo,
                SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
            )

        aplica = views.es_pesaje_salida_mop_despacho_terramar
        self.assertTrue(aplica(citacion(), 'Pesaje Salida', 'SAL'))
        self.assertFalse(aplica(citacion(), 'Pesaje Entrada', 'ENT'))
        self.assertFalse(aplica(citacion(), 'Pesaje Entrada', 'SAL'))
        self.assertFalse(aplica(citacion(), 'Pesaje Salida', 'ENT'))
        self.assertFalse(aplica(citacion(tipo='RECEPCION'), 'Pesaje Entrada', 'ENT'))
        self.assertFalse(aplica(citacion(empresa=2, tipo='RECEPCION'), 'Pesaje Entrada', 'ENT'))
        self.assertFalse(aplica(citacion(empresa=2), 'Pesaje Salida', 'SAL'))
        self.assertFalse(aplica(citacion(secuencia='DESPACHO_TERRAMAR_BODEGA_EXTERNA'), 'Pesaje Salida', 'SAL'))

    def test_payload_mop_no_renderiza_panel_fuera_del_flujo_estricto(self):
        casos = (
            SimpleNamespace(EP_NID_id=1, CI_CTIPO='RECEPCION', SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_TERRAMAR')),
            SimpleNamespace(EP_NID_id=2, CI_CTIPO='RECEPCION', SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_ESTANQUE_SBH')),
            SimpleNamespace(EP_NID_id=2, CI_CTIPO='DESPACHO', SC_NID=SimpleNamespace(SE_CCODIGO='EST_SBH_CLIENTE')),
            SimpleNamespace(EP_NID_id=1, CI_CTIPO='DESPACHO', SC_NID=SimpleNamespace(SE_CCODIGO='DESPACHO_TERRAMAR_BODEGA_EXTERNA')),
        )

        for citacion in casos:
            with self.subTest(empresa=citacion.EP_NID_id, tipo=citacion.CI_CTIPO, secuencia=citacion.SC_NID.SE_CCODIGO):
                self.assertFalse(views._payload_ticket_mop_guardado(citacion)['requerido'])
    def test_parser_ejes_normaliza_patente_y_timestamp(self):
        datos = views._extraer_timestamp_ticket_ejes('EJES_DP-BV30_26_07_30_20_03.pdf')
        self.assertEqual(datos['patente'], 'DPBV30')
        self.assertEqual(datos['timestamp'], datetime(2026, 7, 30, 20, 3))

    def test_nombres_simulados_asocian_con_diferencia_cero(self):
        salida = views._timestamp_base_ticket_salida('COM_SAL_DPBV30_26_07_30_20_03.pdf')
        ejes = views._extraer_timestamp_ticket_ejes('EJES_DPBV30_26_07_30_20_03.pdf')
        candidato, estado, _ = views._seleccionar_candidato_ticket_mop([
            {'nombre': 'EJES_DPBV30_26_07_30_20_03.pdf', 'timestamp': ejes['timestamp'], 'mtime': 1},
        ], salida)
        self.assertEqual(estado, 'MOP_ENCONTRADO')
        self.assertEqual(candidato['diferencia_segundos'], 0)

    def test_candidato_fuera_de_ventana_no_se_asocia(self):
        salida = datetime(2026, 7, 30, 20, 3)
        candidato, estado, _ = views._seleccionar_candidato_ticket_mop([
            {'nombre': 'EJES_DPBV30_26_07_30_18_00.pdf', 'timestamp': datetime(2026, 7, 30, 18, 0), 'mtime': 1},
        ], salida)
        self.assertIsNone(candidato)
        self.assertEqual(estado, 'MOP_NO_ENCONTRADO')

    def test_candidato_mas_cercano_es_inequivoco(self):
        salida = datetime(2026, 7, 30, 20, 3)
        candidatos = [
            {'nombre': 'EJES_DPBV30_26_07_30_20_01.pdf', 'timestamp': salida - timedelta(minutes=2), 'mtime': 1},
            {'nombre': 'EJES_DPBV30_26_07_30_20_07.pdf', 'timestamp': salida + timedelta(minutes=4), 'mtime': 2},
        ]
        candidato, estado, _ = views._seleccionar_candidato_ticket_mop(candidatos, salida)
        self.assertEqual(estado, 'MOP_ENCONTRADO')
        self.assertEqual(candidato['nombre'], 'EJES_DPBV30_26_07_30_20_01.pdf')

    def test_empate_temporal_entre_nombres_distintos_es_ambiguo(self):
        salida = datetime(2026, 7, 30, 20, 3)
        candidatos = [
            {'nombre': 'EJES_DPBV30_26_07_30_20_02.pdf', 'timestamp': salida - timedelta(minutes=1), 'mtime': 1},
            {'nombre': 'EJES_DPBV30_26_07_30_20_04.pdf', 'timestamp': salida + timedelta(minutes=1), 'mtime': 2},
        ]
        candidato, estado, _ = views._seleccionar_candidato_ticket_mop(candidatos, salida)
        self.assertIsNone(candidato)
        self.assertEqual(estado, 'MOP_AMBIGUO')
class TicketMopDespachoTerramarEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = SimpleNamespace(username='operador')

    @staticmethod
    def _citacion(empresa, tipo, secuencia, citacion_id=1):
        return SimpleNamespace(
            id=citacion_id,
            EP_NID_id=empresa,
            EP_NID=SimpleNamespace(id=empresa),
            CI_CTIPO=tipo,
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
            ETAPA_ACTUAL=None,
            CA_NID=None,
        )

    def test_pesaje_entrada_recepcion_y_despacho_terramar_solo_buscan_com_ent(self):
        casos = (
            self._citacion(1, 'RECEPCION', 'RECEPCION_TERRAMAR'),
            self._citacion(1, 'DESPACHO', 'DESPACHO_TERRAMAR', citacion_id=2),
        )
        for citacion in casos:
            with self.subTest(tipo=citacion.CI_CTIPO):
                request = self.factory.get('/ajax/operacion-planta/ticket/', {
                    'citacion_id': citacion.id,
                    'paso_nombre': 'Pesaje Entrada',
                })
                request.user = self.usuario
                with patch.object(views, '_validar_operacion_planta_ticket_request', return_value=(citacion, 'ENT', None)), patch.object(
                    views, 'obtener_valores_ingreso_camion', return_value={'patente': 'VV7002'}
                ), patch.object(views, '_dato_ticket_pesaje', return_value=None), patch.object(
                    views, '_payload_ticket_pesaje_guardado', return_value=None
                ), patch.object(views, '_buscar_ticket_pesaje_mas_reciente', return_value=None) as buscar_com, patch.object(
                    views, '_resolver_ticket_mop_despacho_terramar'
                ) as resolver_mop:
                    response = views.ajax_operacion_planta_obtener_ticket_pesaje(request)

                self.assertEqual(response.status_code, 404)
                buscar_com.assert_called_once_with('VV7002', 'ENT')
                resolver_mop.assert_not_called()
                self.assertNotIn('MOP', response.content.decode('utf-8'))

    def test_pesaje_salida_despacho_terramar_busca_com_sal_y_resuelve_ejes(self):
        citacion = self._citacion(1, 'DESPACHO', 'DESPACHO_TERRAMAR', citacion_id=38646)
        request = self.factory.get('/ajax/operacion-planta/ticket/', {
            'citacion_id': citacion.id,
            'paso_nombre': 'Pesaje Salida',
        })
        request.user = self.usuario
        dato = SimpleNamespace(id=10)
        metadata = {'nombre_archivo_pdf': 'COM_SAL_DRHZ32_26_07_30_16_34.pdf'}
        resultado_mop = {
            'estado': 'MOP_ENCONTRADO',
            'ok': True,
            'nombre': 'EJES_DRHZ32_26_07_30_16_34.pdf',
            'download_url': '/ticket-mop/',
            'mensaje': 'Ticket MOP obtenido correctamente.',
        }
        with patch.object(views, '_validar_operacion_planta_ticket_request', return_value=(citacion, 'SAL', None)), patch.object(
            views, 'obtener_valores_ingreso_camion', return_value={'patente': 'DRHZ32'}
        ), patch.object(views, '_dato_ticket_pesaje', return_value=None), patch.object(
            views, '_payload_ticket_pesaje_guardado', return_value={'download_url': '/ticket-salida/'}
        ), patch.object(
            views, '_buscar_ticket_pesaje_mas_reciente', return_value='C:\\tmp\\COM_SAL_DRHZ32_26_07_30_16_34.pdf'
        ) as buscar_com, patch.object(
            views, '_extraer_datos_ticket_pesaje', return_value={'peso_neto': 1000, 'folio': '77', 'observacion': ''}
        ), patch.object(
            views, '_copiar_ticket_local_si_necesario', return_value='C:\\tmp\\COM_SAL_DRHZ32_26_07_30_16_34.pdf'
        ), patch.object(views, '_ruta_ticket_permitida', return_value=True), patch.object(
            views, '_obtener_campo_ticket_pesaje', return_value=object()
        ), patch.object(views, '_metadata_ticket_pesaje', return_value=metadata), patch.object(
            views.DATO_OPERACION.objects, 'update_or_create', return_value=(dato, True)
        ), patch.object(views, 'registrar_log_camion_no_planificado'), patch.object(
            views, '_resolver_ticket_mop_despacho_terramar', return_value=resultado_mop
        ) as resolver_mop:
            response = views.ajax_operacion_planta_obtener_ticket_pesaje(request)

        self.assertEqual(response.status_code, 200)
        buscar_com.assert_called_once_with('DRHZ32', 'SAL')
        resolver_mop.assert_called_once()
        self.assertIn('"mop_requerido": true', response.content.decode('utf-8').lower())
