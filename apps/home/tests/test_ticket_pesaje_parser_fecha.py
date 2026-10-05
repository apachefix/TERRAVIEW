import json
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class TicketPesajeParserTests(SimpleTestCase):
    def test_fila_historica_extrae_15950(self):
        filas = views._filas_fecha_pesaje_ticket([
            '10-09-2026 03:44 15.950 PJE/AUTO CARLOS MORA',
        ])
        self.assertEqual([fila['peso'] for fila in filas], [15950])

    def test_fila_productiva_sin_espacios_extrae_42550(self):
        filas = views._filas_fecha_pesaje_ticket([
            '05-10-202611:18 42.550PJE/AUTOADMINISTRADOR',
        ])
        self.assertEqual([fila['peso'] for fila in filas], [42550])

    def test_ignora_fecha_vacia_y_no_captura_numeros_posteriores(self):
        filas = views._filas_fecha_pesaje_ticket([
            '01-01-1900',
            '05-10-202611:18 42.550PJE/AUTOADMINISTRADOR 999999',
        ])
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]['peso'], 42550)

    def test_extraer_datos_ticket_productivo_entrada(self):
        pagina = SimpleNamespace(
            extract_text=lambda: (
                'Folio Nro: 351273\n'
                'Patente SG1502\n'
                '05-10-202611:18 42.550PJE/AUTOADMINISTRADOR\n'
            )
        )
        lector = SimpleNamespace(pages=[pagina])
        with patch('apps.home.views.PdfReader', return_value=lector), patch('builtins.open'):
            datos = views._extraer_datos_ticket_pesaje('ticket.pdf', 'ENT')
        self.assertEqual(datos['folio'], '351273')
        self.assertEqual(datos['peso_neto'], 42550)


class TicketPesajeSeleccionFechaTests(SimpleTestCase):
    fecha_actual = date(2026, 10, 5)

    def _buscar(self, shared, local, patente='SG1502', tipo='ENT'):
        with patch.object(views, 'TICKET_PESAJE_SHARED_PATH', str(shared)), patch.object(
            views, 'TICKET_PESAJE_LOCAL_PATH', str(local)
        ), patch.object(views.timezone, 'localdate', return_value=self.fecha_actual):
            return views._buscar_ticket_pesaje_mas_reciente(patente, tipo)

    @staticmethod
    def _crear(carpeta, *nombres):
        carpeta = Path(carpeta)
        carpeta.mkdir(parents=True, exist_ok=True)
        for nombre in nombres:
            (carpeta / nombre).write_bytes(b'%PDF-1.4')

    def test_selecciona_mas_reciente_entre_solo_candidatos_de_hoy(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'shared'
            local = Path(base) / 'local'
            self._crear(
                shared,
                'COM_ENT_SG1502_26_09_25_15_55.pdf',
                'COM_ENT_SG1502_26_10_05_11_18.pdf',
                'COM_ENT_SG1502_26_10_05_11_20.pdf',
            )
            seleccionado = self._buscar(shared, local)
        self.assertEqual(Path(seleccionado).name, 'COM_ENT_SG1502_26_10_05_11_20.pdf')

    def test_ag386ou_con_segundos_se_encuentra_y_elige_el_mas_reciente(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'shared'
            local = Path(base) / 'local'
            self._crear(
                shared,
                'COM_ENT_AG386OU_26_10_04_23_59_59.pdf',
                'COM_ENT_OTRA99_26_10_05_13_06_00.pdf',
                'COM_SAL_AG386OU_26_10_05_13_07_00.pdf',
                'COM_ENT_AG386OU_26_10_05_13_05_19.pdf',
                'COM_ENT_AG386OU_26_10_05_13_05_20.pdf',
            )
            seleccionado = self._buscar(shared, local, patente='AG386OU', tipo='ENT')
        self.assertEqual(
            Path(seleccionado).name,
            'COM_ENT_AG386OU_26_10_05_13_05_20.pdf',
        )

    def test_nombre_con_segundos_interpreta_2026_10_05_y_conserva_formatos_previos(self):
        self.assertEqual(
            views._fecha_ticket_desde_nombre(
                'COM_ENT_AG386OU_26_10_05_13_05_20.pdf'
            ),
            datetime(2026, 10, 5, 13, 5, 20),
        )
        self.assertEqual(
            views._fecha_ticket_desde_nombre(
                'COM_ENT_AG386OU_26_10_05_13_05.pdf'
            ),
            datetime(2026, 10, 5, 13, 5),
        )
        self.assertEqual(
            views._fecha_ticket_desde_nombre(
                'COM_ENT_AG386OU_26_10_05_13_05_20261005_130541.pdf'
            ),
            datetime(2026, 10, 5, 13, 5, 41),
        )

    def test_salida_con_segundos_conserva_timestamp_base_para_mop(self):
        self.assertEqual(
            views._timestamp_base_ticket_salida(
                'COM_SAL_AG386OU_26_10_05_13_05_20.pdf'
            ),
            datetime(2026, 10, 5, 13, 5, 20),
        )

    def test_solo_ticket_historico_no_retorna_candidato(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'shared'
            local = Path(base) / 'local'
            self._crear(shared, 'COM_ENT_SG1502_26_10_04_23_59.pdf')
            seleccionado = self._buscar(shared, local)
        self.assertIsNone(seleccionado)

    def test_no_mezcla_patente_ni_tipo(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'shared'
            local = Path(base) / 'local'
            self._crear(
                shared,
                'COM_ENT_OTRA99_26_10_05_11_20.pdf',
                'COM_SAL_SG1502_26_10_05_11_21.pdf',
            )
            seleccionado = self._buscar(shared, local)
        self.assertIsNone(seleccionado)

    def test_shared_no_disponible_usa_ticket_local_de_hoy(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'no-existe'
            local = Path(base) / 'local'
            self._crear(local, 'COM_ENT_SG1502_26_10_05_11_20.pdf')
            seleccionado = self._buscar(shared, local)
        self.assertEqual(Path(seleccionado).name, 'COM_ENT_SG1502_26_10_05_11_20.pdf')

    def test_shared_no_disponible_no_usa_ticket_local_historico(self):
        with TemporaryDirectory() as base:
            shared = Path(base) / 'no-existe'
            local = Path(base) / 'local'
            self._crear(local, 'COM_ENT_SG1502_26_10_04_11_20.pdf')
            seleccionado = self._buscar(shared, local)
        self.assertIsNone(seleccionado)


class TicketPesajeMensajeHoyTests(SimpleTestCase):
    def test_endpoint_informa_que_no_existe_ticket_de_hoy(self):
        request = RequestFactory().get('/ajax/operacion-planta/ticket-pesaje/', {
            'citacion_id': '38761',
            'paso_nombre': 'Pesaje Entrada',
        })
        request.user = SimpleNamespace(username='romana')
        citacion = SimpleNamespace(
            id=38761,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            CI_CTIPO='RECEPCION',
            SC_NID=SimpleNamespace(SE_CCODIGO='RECEPCION_ESTANQUE_SBH'),
            ETAPA_ACTUAL=None,
            CA_NID=None,
        )
        with patch.object(
            views, '_validar_operacion_planta_ticket_request', return_value=(citacion, 'ENT', None)
        ), patch.object(
            views, 'obtener_valores_ingreso_camion', return_value={'patente': 'SG1502'}
        ), patch.object(
            views, 'obtener_patente_operacional_vigente', return_value='SG1502'
        ), patch.object(
            views, '_dato_ticket_pesaje', return_value=None
        ), patch.object(
            views, '_payload_ticket_pesaje_guardado', return_value=None
        ), patch.object(
            views, '_buscar_ticket_pesaje_mas_reciente', return_value=None
        ):
            response = views.ajax_operacion_planta_obtener_ticket_pesaje(request)

        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        self.assertEqual(
            data['msg'],
            'No se encontró un ticket de pesaje de hoy para la patente SG1502.',
        )
        self.assertNotIn('ticket_pesaje', data['msg'])
