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
        fecha_destino = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FFECHA_LLEGADA_DESTINO')
        hora_planta = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FHORA_LLEGADA_PLANTA')
        hora_destino = CITACION_DESPACHO_DETALLE._meta.get_field('CDD_FHORA_LLEGADA_DESTINO')

        self.assertIsInstance(fecha, models.DateField)
        self.assertIsInstance(fecha_destino, models.DateField)
        self.assertIsInstance(hora_planta, models.TimeField)
        self.assertIsInstance(hora_destino, models.TimeField)
        self.assertTrue(fecha.null and fecha.blank)
        self.assertTrue(fecha_destino.null and fecha_destino.blank)
        self.assertTrue(hora_planta.null and hora_planta.blank)
        self.assertTrue(hora_destino.null and hora_destino.blank)

    def test_validador_normaliza_cada_despacho(self):
        item = {
            'fecha_despacho': '2026-09-08',
            'fecha_llegada_destino': '2026-09-09',
            'hora_llegada_planta': '14:30',
            'hora_llegada_destino': '18:30',
            'orden_carga': ' 2° ',
            'tipo_carga': 'Cisterna',
            'estanque_destino_texto': ' Planta Cliente X ',
        }

        resultado = validar_programacion_despacho_sbh_item(item)

        self.assertEqual(resultado['fecha_despacho'], '2026-09-08')
        self.assertEqual(resultado['fecha_llegada_destino'], '2026-09-09')
        self.assertEqual(resultado['hora_llegada_planta'], '14:30')
        self.assertEqual(resultado['hora_llegada_destino'], '18:30')
        self.assertEqual(resultado['orden_carga'], '2°')
        self.assertEqual(resultado['destino'], 'Planta Cliente X')
        self.assertEqual(resultado['ventana_horaria_despacho'], '14:30')

    def test_validador_rechaza_horas_invalidas_o_vacias(self):
        base = {
            'fecha_despacho': '2026-09-08',
            'fecha_llegada_destino': '2026-09-09',
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

    def test_fecha_llegada_destino_es_obligatoria_y_no_admite_fecha_anterior(self):
        base = {
            'fecha_despacho': '2026-09-08',
            'fecha_llegada_destino': '2026-09-08',
            'hora_llegada_planta': '14:30',
            'hora_llegada_destino': '18:30',
            'orden_carga': '1',
            'tipo_carga': 'Cisterna',
            'destino': 'Cliente',
        }

        with self.assertRaisesMessage(ValueError, 'fecha llegada a destino'):
            validar_programacion_despacho_sbh_item(
                dict(base, fecha_llegada_destino='')
            )
        with self.assertRaisesMessage(
            ValueError,
            'no puede ser anterior a la fecha de despacho',
        ):
            validar_programacion_despacho_sbh_item(
                dict(base, fecha_llegada_destino='2026-09-07')
            )

        self.assertEqual(
            validar_programacion_despacho_sbh_item(dict(base))['fecha_llegada_destino'],
            '2026-09-08',
        )
        self.assertEqual(
            validar_programacion_despacho_sbh_item(
                dict(base, fecha_llegada_destino='2026-09-10')
            )['fecha_llegada_destino'],
            '2026-09-10',
        )

    def test_fecha_no_se_exige_fuera_del_flujo_sbh(self):
        item = {
            'fecha_despacho': '2026-09-08',
            'hora_llegada_planta': '14:30',
            'hora_llegada_destino': '18:30',
            'orden_carga': '1',
            'tipo_carga': 'Cisterna',
            'destino': 'Cliente',
        }

        resultado = validar_programacion_despacho_sbh_item(
            item,
            requerir_fecha_llegada_destino=False,
        )

        self.assertNotIn('fecha_llegada_destino', resultado)

    def test_resumen_recupera_nuevos_campos_y_fallback_legacy(self):
        detalle = SimpleNamespace(
            CDD_FFECHA_DESPACHO=date(2026, 9, 8),
            CDD_FFECHA_LLEGADA_DESTINO=date(2026, 9, 9),
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
        self.assertEqual(resumen['fecha_llegada_destino'], '2026-09-09')
        self.assertEqual(resumen['fecha_llegada_destino_display'], '09/09/2026')
        self.assertEqual(resumen['hora_llegada_planta'], '14:30')
        self.assertEqual(resumen['hora_llegada_destino'], '18:30')

        detalle.CDD_FHORA_LLEGADA_PLANTA = None
        self.assertEqual(
            detalle_despacho_resumen_dict(citacion)['hora_llegada_planta'],
            '16hrs',
        )
        detalle.CDD_FFECHA_LLEGADA_DESTINO = None
        self.assertEqual(
            detalle_despacho_resumen_dict(citacion)['fecha_llegada_destino'],
            '',
        )

    def test_modal_envia_campos_independientes_en_el_json(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')

        self.assertIn('id="despacho_hora_llegada_planta"', template)
        self.assertIn('id="despacho_hora_llegada_destino"', template)
        self.assertIn('id="despacho_fecha_llegada_destino"', template)
        self.assertIn("fecha_despacho: getValue('despacho_fecha')", template)
        self.assertIn("fecha_llegada_destino: getValue('despacho_fecha_llegada_destino')", template)
        self.assertIn("hora_llegada_planta: getValue('despacho_hora_llegada_planta')", template)
        self.assertIn("hora_llegada_destino: getValue('despacho_hora_llegada_destino')", template)
        self.assertIn("orden_carga: getValue('despacho_orden_carga')", template)
        self.assertIn('no puede ser anterior a la fecha de despacho', template)

        validacion_recepcion = template[
            template.index('function validarFormularioCitacion()'):
            template.index('function validarFormularioDespacho()')
        ]
        validacion_despacho = template[
            template.index('function validarFormularioDespacho()'):
            template.index('function limpiarFormularioCitacion()')
        ]
        self.assertNotIn('fechaLlegadaDestino', validacion_recepcion)
        self.assertIn('fechaLlegadaDestino < fechaDespacho', validacion_despacho)

    def test_fecha_se_expone_en_revision_patio_detalle_y_operacion(self):
        views_source = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn(
            "{'label': 'Fecha llegada a destino', 'value': detalle_despacho.get('fecha_llegada_destino_display')}",
            views_source,
        )
        self.assertIn(
            "'Fecha llegada a destino': valor_revision(detalle_despacho.get('fecha_llegada_destino_display'))",
            views_source,
        )
        self.assertIn("'fecha_llegada_destino_candidata':", views_source)
        self.assertIn(
            "'fecha_llegada_destino': detalle_despacho.get('fecha_llegada_destino_display', '')",
            views_source,
        )

        patio = Path(
            'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        ).read_text(encoding='utf-8')
        navegacion = Path(
            'apps/templates/includes/navigation.html'
        ).read_text(encoding='utf-8')
        operacion = Path(
            'apps/templates/home/CITACION/seguimiento_operacional.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Llegada estimada al destino', patio)
        self.assertIn('Llegada estimada al destino', navegacion)
        self.assertIn('Llegada estimada al destino', operacion)
