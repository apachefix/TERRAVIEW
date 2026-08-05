from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class PlaListoneEditReceptionModalScrollTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        template_path = Path(settings.BASE_DIR).parent / (
            "apps/templates/home/PLANIFICACION/pla_listone.html"
        )
        cls.template = template_path.read_text(encoding="utf-8")

    def test_edit_reception_modal_uses_scoped_scrollable_layout(self):
        self.assertIn('id="editReceptionTerramarModal"', self.template)
        self.assertIn(
            'class="modal-dialog modal-xl modal-dialog-scrollable"',
            self.template,
        )
        self.assertIn(
            "#editReceptionTerramarModal #editReceptionTerramarForm",
            self.template,
        )
        self.assertIn("#editReceptionTerramarModal .modal-body", self.template)
        self.assertIn("overflow-y: auto;", self.template)
        self.assertNotIn("\n    .modal-body {\n        overflow-y: auto;", self.template)

    def test_footer_is_outside_the_scrollable_body(self):
        modal_start = self.template.index('id="editReceptionTerramarModal"')
        modal_end = self.template.index("</form>", modal_start)
        modal_markup = self.template[modal_start:modal_end]

        body_start = modal_markup.index('<div class="modal-body">')
        footer_start = modal_markup.index('<div class="modal-footer">')
        body_end = modal_markup.rfind("</div>", body_start, footer_start)

        self.assertLess(body_start, body_end)
        self.assertLess(body_end, footer_start)
        self.assertIn("Guardar cambios", modal_markup[footer_start:])
    def test_terramar_badge_uses_real_flow_label(self):
        terramar_label = (
            '{% if es_recepcion_terramar %}Enviado a Asistente_bodega'
            '{% else %}Enviado a Asistente_C_D{% endif %}'
        )
        self.assertEqual(self.template.count(terramar_label), 2)
        primero_condicional = self.template.index(terramar_label)
        primero_cd = self.template.index('Enviado a Asistente_C_D</span>')
        self.assertGreater(primero_condicional, primero_cd)

    def test_non_terramar_badges_keep_asistente_cd_label(self):
        self.assertGreaterEqual(
            self.template.count('Enviado a Asistente_C_D</span>'),
            2,
        )