from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase

from apps.home import views


class AlertasDocumentalesPlanificacionTerramarTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_template('home/PLANIFICACION/pla_addone.html')
        ruta = (
            Path(views.__file__).parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        )
        cls.contenido = ruta.read_text(encoding='utf-8')

    def test_recepcion_terramar_tiene_contenedores_independientes(self):
        self.assertIn('id="rt_control_documental_conductor"', self.contenido)
        self.assertIn('id="rt_control_documental_camion"', self.contenido)
        self.assertNotIn('id="rt_control_documental"', self.contenido)

    def test_despacho_terramar_tiene_contenedores_independientes(self):
        self.assertIn(
            'id="despacho_terramar_control_documental_conductor"',
            self.contenido,
        )
        self.assertIn(
            'id="despacho_terramar_control_documental_camion"',
            self.contenido,
        )
        self.assertNotIn(
            'id="despacho_terramar_control_documental"',
            self.contenido,
        )

    def test_cada_evaluacion_apunta_solamente_a_su_contenedor(self):
        self.assertIn(
            "evaluarConductorPlanificacion(data.conductor_id, '#rt_control_documental_conductor')",
            self.contenido,
        )
        self.assertIn(
            "if (campoId === 'rt_patente') return '#rt_control_documental_camion'",
            self.contenido,
        )
        self.assertIn(
            "evaluarConductorPlanificacion(data.conductor_id, '#despacho_terramar_control_documental_conductor')",
            self.contenido,
        )
        self.assertIn(
            "return '#despacho_terramar_control_documental_camion'",
            self.contenido,
        )

    def test_limpieza_es_independiente_y_evitar_respuestas_obsoletas(self):
        self.assertIn('function limpiarControlDocumental(selector)', self.contenido)
        self.assertIn("select2:clear.control-documental", self.contenido)
        self.assertIn("data('documentalClave') !== clave", self.contenido)
        self.assertIn(
            "limpiarControlDocumental(selectorAlertaCamionPlanificacion(this.id))",
            self.contenido,
        )

    def test_cambio_de_conductor_sincroniza_sugerencia_sin_borrar_patente_al_limpiar(self):
        self.assertIn("patente_sugerida||'').toUpperCase()).trigger('blur')", self.contenido)
        self.assertIn("patente_sugerida || '').toUpperCase()).trigger('blur')", self.contenido)
        self.assertIn("$('#rt_conductor_id,#rt_telefono').val('')", self.contenido)
        self.assertIn(
            "$('#despacho_terramar_conductor_id,#despacho_terramar_celular').val('')",
            self.contenido,
        )

    def test_texto_no_bloqueante_es_el_solicitado(self):
        self.assertIn(
            'Esto es solo una advertencia; no impide que puedas planificar con estos datos.',
            self.contenido,
        )
        self.assertNotIn(
            'Advertencia no bloqueante: puede continuar.',
            self.contenido,
        )

    def test_modales_terramar_restauran_scroll_interno_en_el_cuerpo(self):
        self.assertIn(
            '#ModalCrearRecepcionTerramar .modal-content > form,',
            self.contenido,
        )
        self.assertIn(
            '#ModalCrearDespachoTerramar .modal-content > form {',
            self.contenido,
        )
        self.assertIn(
            '#ModalCrearRecepcionTerramar .modal-body,',
            self.contenido,
        )
        self.assertIn(
            '#ModalCrearDespachoTerramar .modal-body {',
            self.contenido,
        )
        regla_scroll = self.contenido[
            self.contenido.index('#ModalCrearRecepcionTerramar .modal-body,'):
            self.contenido.index('#ModalCrearRecepcionTerramar .modal-header,')
        ]
        self.assertIn('flex: 1 1 auto;', regla_scroll)
        self.assertIn('min-height: 0;', regla_scroll)
        self.assertIn('overflow-y: auto !important;', regla_scroll)

    def test_scroll_no_aplica_hack_global_ni_cambia_ancho(self):
        regla_terramar = self.contenido[
            self.contenido.index('/* MODALES TERRAMAR:'):
            self.contenido.index('/* MODAL CREAR DESPACHO */')
        ]
        self.assertNotIn('\n    body {', regla_terramar)
        self.assertNotIn('width:', regla_terramar)
        self.assertNotIn('max-width:', regla_terramar)

    def test_alertas_no_deshabilitan_acciones_de_planificacion(self):
        bloque = self.contenido[
            self.contenido.index('function mostrarControlDocumental'):
            self.contenido.index('function abrirModalRecepcionTerramar')
        ]
        self.assertNotIn("prop('disabled'", bloque)
        self.assertNotIn("attr('disabled'", bloque)
