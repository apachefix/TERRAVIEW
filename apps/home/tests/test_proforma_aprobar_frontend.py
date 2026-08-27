import re
from pathlib import Path

from django.test import SimpleTestCase


TEMPLATE = Path(
    'apps/templates/home/PROFORMA/proforma_terramar_detalle.html'
)


class AprobarProformaFrontendContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = TEMPLATE.read_text(encoding='utf-8')
        scripts = re.findall(r'<script>(.*?)</script>', cls.template, re.S)
        cls.script = next(
            script for script in scripts
            if 'iniciarAprobacionProforma' in script
        )

    def test_boton_formulario_y_modal_coinciden(self):
        self.assertIn('id="form-autorizar-sap"', self.template)
        self.assertIn(
            "action=\"{% url 'proforma_autorizar_ajax' proforma.pk %}\"",
            self.template,
        )
        self.assertIn('type="button" id="btn-autorizar-sap"', self.template)
        self.assertIn('aria-controls="modal-aprobar-proforma"', self.template)
        self.assertIn('id="modal-aprobar-proforma"', self.template)
        self.assertIn('Cancelar</button>', self.template)
        self.assertIn('Confirmar aprobación</button>', self.template)

    def test_listener_abre_modal_y_cancelar_no_hace_post(self):
        self.assertIn(
            "botonPrincipal.addEventListener('click', abrirModal)",
            self.script,
        )
        self.assertIn(
            "botonCancelar.addEventListener('click', cerrarModal)",
            self.script,
        )
        self.assertLess(
            self.script.index("botonConfirmar.addEventListener('click'"),
            self.script.index('fetch(form.action'),
        )
        self.assertNotIn("botonCancelar.addEventListener('click', async", self.script)

    def test_post_csrf_exito_error_y_doble_click(self):
        self.assertEqual(self.script.count('fetch(form.action'), 1)
        self.assertIn("method: 'POST'", self.script)
        self.assertIn("'X-CSRFToken': csrfInput.value", self.script)
        self.assertIn("credentials: 'same-origin'", self.script)
        self.assertIn('if (enviando) return;', self.script)
        self.assertIn("'APROBANDO...'", self.script)
        self.assertIn('if (!respuesta.ok || !datos.success)', self.script)
        self.assertIn('OC SAP N° ', self.script)
        self.assertIn('window.location.reload()', self.script)
        self.assertIn(
            'No fue posible generar la Orden de Compra SAP: ', self.script
        )
        self.assertIn('console.error', self.script)

    def test_confirmacion_usa_contexto_central_y_es_generica(self):
        self.assertIn('SAP {{ sap_environment', self.template)
        self.assertIn('{{ proforma.EP_NID.EP_CRAZONSOCIAL }}', self.template)
        self.assertIn('#{{ proforma.pk }}', self.template)
        self.assertIn('{{ categoria }}', self.template)
        self.assertIn('{{ sap_company_db', self.template)
        self.assertNotIn('TESTTERRACHILE', self.template)

    def test_script_tiene_delimitadores_balanceados(self):
        stack = []
        pairs = {')': '(', ']': '[', '}': '{'}
        quote = None
        escaped = False
        index = 0
        while index < len(self.script):
            char = self.script[index]
            following = self.script[index:index + 2]
            if quote:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if following == '//':
                newline = self.script.find('\n', index + 2)
                index = len(self.script) if newline == -1 else newline + 1
                continue
            if following == '/*':
                closing = self.script.find('*/', index + 2)
                self.assertNotEqual(closing, -1, 'Comentario JavaScript sin cerrar')
                index = closing + 2
                continue
            if char in {"'", '"', '`'}:
                quote = char
            elif char in '([{':
                stack.append(char)
            elif char in ')]}':
                self.assertTrue(stack, f'Cierre JavaScript inesperado: {char}')
                self.assertEqual(stack.pop(), pairs[char])
            index += 1
        self.assertIsNone(quote, 'Cadena JavaScript sin cerrar')
        self.assertEqual(stack, [], 'Delimitadores JavaScript sin cerrar')
