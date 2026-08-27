from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.views import _bl_planificacion_asociacion_recepcion_sbh


class BlCitacionModalRecepcionSbhTests(SimpleTestCase):
    def citacion(self, empresa=2, tipo='RECEPCION', bl='MEDUPZ731605', pk=38670):
        return SimpleNamespace(
            id=pk,
            EP_NID_id=empresa,
            CI_CTIPO=tipo,
            detalle_operacional=SimpleNamespace(CDO_CBL=bl),
        )

    def test_caso_38670_expone_bl_del_snapshot_operacional(self):
        citacion = self.citacion()
        self.assertEqual(citacion.id, 38670)
        self.assertEqual(
            _bl_planificacion_asociacion_recepcion_sbh(citacion),
            'MEDUPZ731605',
        )

    def test_bl_vacio_se_conserva_vacio_para_que_frontend_mueste_fallback(self):
        self.assertEqual(
            _bl_planificacion_asociacion_recepcion_sbh(self.citacion(bl=None)),
            '',
        )

    def test_recepcion_terramar_no_expone_bl_en_este_panel(self):
        self.assertEqual(
            _bl_planificacion_asociacion_recepcion_sbh(self.citacion(empresa=1)),
            '',
        )

    def test_despacho_sbh_no_expone_bl_en_este_panel(self):
        self.assertEqual(
            _bl_planificacion_asociacion_recepcion_sbh(self.citacion(tipo='DESPACHO')),
            '',
        )

    def test_template_renderiza_fila_solo_con_indicador_recepcion_sbh(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        contenido = template.read_text(encoding='utf-8')
        self.assertIn('const datosRecepcionSbh = cit.es_recepcion_sbh', contenido)
        self.assertIn('escapeHtml(cit.bl || \'Sin informaci\\u00f3n\')', contenido)
        self.assertIn('datosRecepcionSbh +', contenido)
