from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.home import views


class DocumentacionDespachoTerramarIsolationTests(SimpleTestCase):
    def _citacion(self, empresa=1, tipo='DESPACHO', secuencia='DESPACHO_TERRAMAR'):
        return SimpleNamespace(
            id=99,
            EP_NID_id=empresa,
            CI_CTIPO=tipo,
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
        )

    def test_aplica_solo_a_despacho_terramar_estricto(self):
        self.assertTrue(views.es_documentacion_despacho_terramar(self._citacion()))
        self.assertFalse(views.es_documentacion_despacho_terramar(
            self._citacion(secuencia='DESPACHO_TERRAMAR_BODEGA_EXTERNA')
        ))
        self.assertFalse(views.es_documentacion_despacho_terramar(
            self._citacion(tipo='RECEPCION')
        ))
        self.assertFalse(views.es_documentacion_despacho_terramar(
            self._citacion(empresa=2)
        ))

    def test_payload_de_reloj_finalizado_conserva_duracion_persistida(self):
        inicio = timezone.now() - timedelta(minutes=3)
        fin = inicio + timedelta(seconds=95)
        metadata = {
            'inicio_iso': inicio.isoformat(),
            'fin_iso': fin.isoformat(),
            'duracion_segundos': 95,
            'duracion_legible': '00:01:35',
            'usuario_inicio': 'recepcion',
            'usuario_fin': 'recepcion',
        }
        with patch.object(views, '_metadata_documentacion_despacho_terramar', return_value=(metadata, None)):
            payload = views._payload_temporizador_documentacion_despacho_terramar(self._citacion())

        self.assertTrue(payload['finalizado'])
        self.assertFalse(payload['en_proceso'])
        self.assertEqual(payload['duracion_segundos'], 95)
        self.assertEqual(payload['duracion_legible'], '00:01:35')

    def test_codigos_de_persistencia_son_exclusivos(self):
        self.assertEqual(views.CAMPO_DESP_TERR_DOC_TEMPORIZADOR, 'DESP_TERR_DOC_TEMPORIZADOR')
        self.assertEqual(views.CAMPO_DESP_TERR_ENCARPE_OK, 'DESP_TERR_ENCARPE_OK')
        self.assertEqual(views.CAMPO_DESP_TERR_GUIA_SALIDA, 'DESP_TERR_GUIA_SALIDA')
