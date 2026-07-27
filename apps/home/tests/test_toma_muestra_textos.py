from django.test import SimpleTestCase

from apps.home.views import _config_accion_toma_muestra


class TomaMuestraTextosTestCase(SimpleTestCase):
    def test_recepcion_trasvasije_describe_la_toma_fisica_de_muestra(self):
        config = _config_accion_toma_muestra('RECEPCION TRASVASIJE')

        self.assertEqual(config['accion_label'], 'Toma de muestra')
        self.assertEqual(config['estado_label'], 'Muestra tomada')
        self.assertEqual(config['pendiente_label'], 'Pendiente de toma de muestra')
        self.assertEqual(config['mensaje_guardado'], 'Muestra tomada.')
        self.assertEqual(config['log_mensaje'], 'Muestra tomada en Toma de muestra')
        self.assertTrue(config['mide_tiempo_toma_muestra'])

    def test_recepcion_trasvasije_conserva_identificadores_internos(self):
        config = _config_accion_toma_muestra('RECEPCION TRASVASIJE')

        self.assertEqual(config['tipo'], 'analisis')
        self.assertEqual(config['log_operacion'], 'MUESTRA_TOMADA')
        self.assertLessEqual(len(config['log_operacion']), 24)

    def test_recepcion_bodega_externa_envia_a_analisis_con_reloj(self):
        config = _config_accion_toma_muestra('RECEPCION BODEGA EXTERNA')

        self.assertTrue(config['mide_tiempo_toma_muestra'])
        self.assertEqual(config['accion_label'], 'Enviar a analisis')
        self.assertEqual(config['estado_label'], 'Muestra enviada a analisis')
        self.assertEqual(config['log_operacion'], 'MUESTRA_A_ANALISIS')

    def test_flujo_generico_no_recibe_reloj_de_bodega_externa(self):
        config = _config_accion_toma_muestra('RECEPCION GENERICA')

        self.assertFalse(config['mide_tiempo_toma_muestra'])