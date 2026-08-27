from pathlib import Path

from django.test import SimpleTestCase


class PlanificacionesArchivadasAccionVisualTests(SimpleTestCase):
    def setUp(self):
        self.template = Path(
            'apps/templates/home/PLANIFICACION/pla_archived_list.html'
        ).read_text(encoding='utf-8')

    def test_accion_angosta_esta_inmediatamente_despues_de_tipo(self):
        encabezado = self.template.split('<thead>', 1)[1].split('</thead>', 1)[0]

        self.assertIn(
            '<th>Tipo</th>\n                                            <th class="action-cell">Ver</th>',
            encabezado,
        )
        self.assertIn('width: 56px;', self.template)
        self.assertIn('max-width: 56px;', self.template)

    def test_existe_un_solo_enlace_con_icono_y_url_historica(self):
        enlace = "{% url 'pla_archivada_resumen' row.planificacion.id %}?_empresa_id={{ empresa_id }}"

        self.assertEqual(self.template.count(enlace), 1)
        self.assertIn('class="fas fa-eye"', self.template)
        self.assertIn('title="Ver resumen hist&oacute;rico"', self.template)
        self.assertNotIn('sticky-actions', self.template)

    def test_columna_final_grande_fue_eliminada(self):
        encabezado = self.template.split('<thead>', 1)[1].split('</thead>', 1)[0]
        fila = self.template.split('{% for row in resumenes %}', 1)[1].split('</tr>', 1)[0]

        self.assertNotIn('>Acciones</th>', encabezado)
        self.assertTrue(fila.index('class="action-cell"') < fila.index('PL_FFECHAINICIO'))
        self.assertEqual(self.template.count('colspan="14"'), 1)
