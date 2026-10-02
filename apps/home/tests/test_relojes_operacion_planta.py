from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase


class RelojesOperacionPlantaTestCase(SimpleTestCase):
    def test_toma_calidad_y_bodega_externa_reutilizan_el_mismo_componente(self):
        source = get_template('home/CITACION/operacion_planta.html').template.source
        include = "home/CITACION/_process_hourglass.html"

        self.assertIn(
            f"{{% include '{include}' with finalizada=paso.tiempo_toma_muestra.finalizada only %}}",
            source,
        )
        self.assertIn(
            f"{{% include '{include}' with finalizada=False only %}}",
            source,
        )
        self.assertIn(
            f"{{% include '{include}' with finalizada=True only %}}",
            source,
        )
        self.assertIn(
            f"{{% include '{include}' with finalizada=paso.ciclo_bodega_externa.finalizada only %}}",
            source,
        )

    def test_componente_compartido_anima_activo_y_deja_estatico_finalizado(self):
        activo = render_to_string(
            'home/CITACION/_process_hourglass.html',
            {'finalizada': False},
        )
        finalizado = render_to_string(
            'home/CITACION/_process_hourglass.html',
            {'finalizada': True},
        )

        self.assertIn('op-vapor-hourglass is-active', activo)
        self.assertIn('op-vapor-hourglass is-finished', finalizado)
        self.assertIn('op-vapor-sand-top', activo)
        self.assertIn('op-vapor-sand-bottom', activo)

    def test_css_compartido_respeta_reduccion_de_movimiento(self):
        source = get_template('home/CITACION/operacion_planta.html').template.source

        self.assertIn('@media (prefers-reduced-motion: reduce)', source)
        self.assertIn(
            '.op-vapor-hourglass.is-active .op-vapor-hourglass-turn',
            source,
        )
        self.assertIn('animation: none;', source)