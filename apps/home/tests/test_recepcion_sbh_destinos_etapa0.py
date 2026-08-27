from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.home.recepcion_sbh_destinos import (
    ALMACENES_DESTINO_RECEPCION_SBH,
    validar_destino_recepcion_sbh,
)
from apps.home.views import guardar_detalle_operacional_citacion


class DestinosRecepcionSbhEtapa0Tests(SimpleTestCase):
    def test_maestro_tiene_almacenes_y_cantidades_operacionales(self):
        self.assertEqual(
            {codigo: len(ubicaciones) for codigo, ubicaciones in ALMACENES_DESTINO_RECEPCION_SBH.items()},
            {
                'CANOPY': 6,
                'CISTERNA': 62,
                'PATIO DE CAMIONES': 1,
                'PATIO SBH': 12,
                'PROSESA': 9,
                'PUERTO': 2,
                'SBH': 16,
            },
        )

    def test_sbh_y_canopy_no_duplican_estanques(self):
        codigos_sbh = set(ALMACENES_DESTINO_RECEPCION_SBH['SBH'])
        codigos_canopy = set(ALMACENES_DESTINO_RECEPCION_SBH['CANOPY'])
        self.assertEqual(codigos_sbh & codigos_canopy, set())
        self.assertIn('TK12', codigos_sbh)
        self.assertNotIn('TK13', codigos_sbh)
        self.assertIn('TK13', codigos_canopy)
        self.assertIn('TK18', codigos_canopy)

    def test_codigos_especiales_se_conservan_exactamente(self):
        self.assertIn('PTO SBH', ALMACENES_DESTINO_RECEPCION_SBH['PUERTO'])
        self.assertIn('PROCESA', ALMACENES_DESTINO_RECEPCION_SBH['PROSESA'])
        self.assertIn('CISTER27', ALMACENES_DESTINO_RECEPCION_SBH['CISTERNA'])
        self.assertIn('CISTER_9', ALMACENES_DESTINO_RECEPCION_SBH['CISTERNA'])

    def test_maestro_no_incluye_terramar_ni_descripciones(self):
        self.assertNotIn('TERRAMAR', ALMACENES_DESTINO_RECEPCION_SBH)
        self.assertTrue(all(
            isinstance(ubicacion, str)
            for ubicaciones in ALMACENES_DESTINO_RECEPCION_SBH.values()
            for ubicacion in ubicaciones
        ))

    def test_valida_pertenencia_almacen_ubicacion(self):
        self.assertEqual(validar_destino_recepcion_sbh('CISTERNA', 'CISTER27'), (True, ''))
        valido, mensaje = validar_destino_recepcion_sbh('SBH', 'CISTER27')
        self.assertFalse(valido)
        self.assertEqual(mensaje, 'La ubicación seleccionada no pertenece al almacén destino.')

    def test_rechaza_almacen_ajeno_al_maestro(self):
        valido, mensaje = validar_destino_recepcion_sbh('TERRAMAR', 'T2-ARR')
        self.assertFalse(valido)
        self.assertEqual(mensaje, 'El almacén destino seleccionado no es válido.')

    @patch('apps.home.views.CITACION_DETALLE_OPERACIONAL.objects.update_or_create')
    def test_persistencia_guarda_codigos_como_snapshot(self, update_or_create):
        update_or_create.return_value = (object(), True)
        usuario = object()
        empresa = object()
        citacion = SimpleNamespace(
            EP_NID_id=2,
            EP_NID=empresa,
            CI_CTIPO='RECEPCION',
            US_NID=usuario,
        )

        guardar_detalle_operacional_citacion(
            citacion,
            {
                'almacen_destino': 'CISTERNA',
                'estanque_destino': 'CISTER27',
            },
            usuario=usuario,
        )

        defaults = update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDO_CALMACEN_DESTINO'], 'CISTERNA')
        self.assertEqual(defaults['CDO_CESTANQUE_DESTINO'], 'CISTER27')
