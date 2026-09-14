from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

from django.db import models
from django.test import SimpleTestCase

from apps.home.models import CITACION_DESPACHO_DETALLE
from apps.home.sap_despacho import detalle_despacho_resumen_dict
from apps.home.views import validar_programacion_despacho_sbh_item


class ProgramacionHorariaDespachoSbhTests(SimpleTestCase):
    def test_modelo_usa_campos_tipados_y_anulables(self):
        fecha = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FFECHA_DESPACHO')
        hora_planta = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FHORA_LLEGADA_PLANTA')
        hora_destino = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FHORA_LLEGADA_DESTINO')

        self.assertIsInstance(fecha, models.DateField)
        self.assertIsInstance(hora_planta, models.TimeField)
        self.assertIsInstance(hora_destino, models.TimeField)
        self.assertTrue(fecha.null and fecha.blank)
        self.assertTrue(hora_planta.null and hora_planta.blank)
        self.assertTrue(hora_destino.null and hora_destino.blank)

    def test_validador_normaliza_cada_despacho(self):
        item = {
            'fecha_despacho': '2026-09-08',
            'hora_llegada_planta': '14:30',
            'hora_llegada_destino': '18:30',
            'orden_carga': ' 2° ',
            'tipo_carga': 'Cisterna',
            'estanque_destino_texto': ' Planta Cliente X ',
        }

        resultado = validar_programacion_despacho_sbh_item(item)

        self.assertEqual(resultado['fecha_despacho'], '2026-09-08')
        self.assertEqual(resultado['hora_llegada_planta'], '14:30')
        self.assertEqual(resultado['hora_llegada_destino'], '18:30')
        self.assertEqual(resultado['orden_carga'], '2°')
        self.assertEqual(resultado['destino'], 'Planta Cliente X')
        self.assertEqual(resultado['ventana_horaria_despacho'], '14:30')

    def test_validador_rechaza_horas_invalidas_o_vacias(self):
        base = {
            'fecha_despacho': '2026-09-08',
            'hora_llegada_planta': '14:30',
            'hora_llegada_destino': '18:30',
            'orden_carga': '1°',
            'tipo_carga': 'Cisterna',
            'destino': 'Cliente',
        }
        invalido = dict(base, hora_llegada_destino='18hrs')
        vacio = dict(base, hora_llegada_planta='')

        with self.assertRaisesMessage(ValueError, 'Hora llegada a destino debe tener formato HH:MM.'):
            validar_programacion_despacho_sbh_item(invalido)
        with self.assertRaisesMessage(ValueError, 'hora llegada a planta'):
            validar_programacion_despacho_sbh_item(vacio)

    def test_resumen_recupera_nuevos_campos_y_fallback_legacy(self):
        detalle = SimpleNamespace(
            CDD_FFECHA_DESPACHO=date(2026, 9, 8),
            CDD_FHORA_LLEGADA_PLANTA=time(14, 30),
            CDD_FHORA_LLEGADA_DESTINO=time(18, 30),
            CDD_CVENTANA_HORARIA_DESPACHO='16hrs',
        )
        citacion = SimpleNamespace(
            detalle_despacho=detalle,
            CI_CCOMENTARIO='',
            SC_NID=None,
            SN_NID=None,
        )

        resumen = detalle_despacho_resumen_dict(citacion)

        self.assertEqual(resumen['fecha_despacho'], '2026-09-08')
        self.assertEqual(resumen['hora_llegada_planta'], '14:30')
        self.assertEqual(resumen['hora_llegada_destino'], '18:30')

        detalle.CDD_FHORA_LLEGADA_PLANTA = None
        self.assertEqual(
            detalle_despacho_resumen_dict(citacion)['hora_llegada_planta'],
            '16hrs',
        )

    def test_modal_envia_campos_independientes_en_el_json(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')

        self.assertIn('id="despacho_hora_llegada_planta"', template)
        self.assertIn('id="despacho_hora_llegada_destino"', template)
        self.assertIn("fecha_despacho: getValue('despacho_fecha')", template)
        self.assertIn("hora_llegada_planta: getValue('despacho_hora_llegada_planta')", template)
        self.assertIn("hora_llegada_destino: getValue('despacho_hora_llegada_destino')", template)
        self.assertIn("orden_carga: getValue('despacho_orden_carga')", template)