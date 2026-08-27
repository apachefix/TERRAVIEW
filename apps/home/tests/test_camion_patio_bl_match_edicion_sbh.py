from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.http import QueryDict
from django.test import SimpleTestCase

from apps.home.views import (
    _normalizar_bl_match,
    _normalizar_datos_edicion_camion_patio,
    _score_citacion_camion_patio,
)


class CamionPatioBlMatchSbhTests(SimpleTestCase):
    def camion(self, bl='MEDUPZ731605', empresa=2, tipo='EXTRANJERO'):
        return SimpleNamespace(
            EP_NID_id=empresa,
            CPA_CTIPO_RECEPCION=tipo,
            CPA_CBL=bl,
            CPA_CPATENTE='LTGJ73',
            CPA_CINSUMO_DECLARADO_GUIA='',
            CPA_CPROVEEDOR_DECLARADO='',
            CPA_CCLIENTE_DECLARADO='',
            CPA_FFECHALLEGADA=None,
        )

    def citacion(self, bl='MEDUPZ731605', empresa=2, tipo='RECEPCION', pk=38670):
        detalle = SimpleNamespace(CDO_CBL=bl, CDO_CINSUMO='', CDO_CPRODUCTOR='')
        citacion = SimpleNamespace(
            id=pk,
            EP_NID_id=empresa,
            CI_CTIPO=tipo,
            PL_NID=None,
            PRO_NID=None,
            SN_NID=None,
            SC_NID=None,
        )
        return citacion, detalle

    def score(self, camion, citacion, detalle):
        with patch('apps.home.views._detalle_operacional_citacion', return_value=detalle), patch(
            'apps.home.views.obtener_valores_ingreso_camion', return_value={}
        ), patch(
            'apps.home.views.obtener_cliente_planificacion_citacion',
            return_value={'nombre': '', 'codigo': ''},
        ):
            return _score_citacion_camion_patio(camion, citacion)

    def test_a_normaliza_separadores_sin_confundir_letras_y_numeros(self):
        self.assertEqual(_normalizar_bl_match(' medu-pz. 731605 '), 'MEDUPZ731605')
        self.assertNotEqual(_normalizar_bl_match('MEDUPZ73I605'), 'MEDUPZ731605')

    def test_b_bl_exacto_normalizado_suma_puntaje_alto(self):
        citacion, detalle = self.citacion(' medu-pz.731605 ')
        score, razones, info = self.score(self.camion(), citacion, detalle)
        self.assertEqual(score, 40)
        self.assertIn('BL coincide', razones)
        self.assertEqual(info['bl_estado'], 'coincide')

    def test_c_un_caracter_de_diferencia_es_solo_similar(self):
        citacion, detalle = self.citacion('MEDUPZ731606')
        score, razones, info = self.score(self.camion(), citacion, detalle)
        self.assertEqual(score, 15)
        self.assertIn('BL similar — revisar dato', razones)
        self.assertEqual(info['bl_estado'], 'similar')

    def test_d_bl_distinto_no_suma(self):
        citacion, detalle = self.citacion('OTROBL999999')
        score, razones, info = self.score(self.camion(), citacion, detalle)
        self.assertEqual(score, 0)
        self.assertEqual(razones, [])
        self.assertEqual(info['bl_estado'], 'distinto')

    def test_e_bl_vacio_no_participa(self):
        citacion, detalle = self.citacion('')
        score, razones, info = self.score(self.camion(''), citacion, detalle)
        self.assertEqual((score, razones, info['bl_estado']), (0, [], ''))

    def test_f_criterio_aislado_de_despacho_y_otras_empresas(self):
        for camion, empresa, tipo in (
            (self.camion(tipo=''), 2, 'DESPACHO'),
            (self.camion(empresa=1), 1, 'RECEPCION'),
        ):
            citacion, detalle = self.citacion(empresa=empresa, tipo=tipo)
            score, razones, info = self.score(camion, citacion, detalle)
            self.assertEqual(score, 0)
            self.assertNotIn('BL coincide', razones)
            self.assertEqual(info['bl_estado'], '')

    def test_g_editar_bl_recalcula_el_match_sin_asociar(self):
        camion = self.camion('MEDUPZ731606')
        citacion, detalle = self.citacion('MEDUPZ731605')
        self.assertEqual(self.score(camion, citacion, detalle)[2]['bl_estado'], 'similar')
        camion.CPA_CBL = 'MEDU-PZ 731605'
        score, razones, info = self.score(camion, citacion, detalle)
        self.assertEqual((score, info['bl_estado']), (40, 'coincide'))
        self.assertIn('BL coincide', razones)
        self.assertFalse(hasattr(camion, 'CI_NID_id'))

    def test_j_caso_real_lgtj73_citacion_38670(self):
        citacion, detalle = self.citacion(pk=38670)
        score, razones, info = self.score(self.camion(), citacion, detalle)
        self.assertEqual(citacion.id, 38670)
        self.assertGreaterEqual(score, 40)
        self.assertEqual(info['bl_estado'], 'coincide')
        self.assertIn('BL coincide', razones)


class CamionPatioEdicionRecepcionSbhTests(SimpleTestCase):
    def camion(self, tipo='EXTRANJERO'):
        return SimpleNamespace(
            EP_NID_id=2,
            CPA_CTIPO_RECEPCION=tipo,
            transporte_a_cargo='TERRAMAR',
            CPA_CTRANSPORTISTA_DECLARADO='Transportes Uno',
            CPA_CNOMBRE_CONDUCTOR='Conductor Uno',
            CPA_CRUT_CONDUCTOR='11111111-1',
            CPA_CTELEFONO_CONDUCTOR='912345678',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CPATENTE='LTGJ73',
            CPA_CPROVEEDOR_DECLARADO='Proveedor',
            CPA_CCLIENTE_DECLARADO='Cliente',
            CPA_CNUMERO_GUIA='GUIA-1',
            CPA_CINSUMO_DECLARADO_GUIA='Producto',
            CPA_COBSERVACION='',
            CPA_CCDA='CDA-ANT',
            CPA_CDI='DI-ANT',
            CPA_CBL='BL-ANT',
            CPA_CNAVE_NAVIERA='Nave anterior',
            CPA_CLOTE_CONTENEDOR='CONT-ANT',
            CPA_CSUI='SUI-ANT',
            CPA_CFECHAPRODUCCION='',
            CPA_CFECHAVENCIMIENTOPRODUCTO='',
        )

    def post(self, tipo='EXTRANJERO'):
        post = QueryDict('', mutable=True)
        post.update({
            'tipo_recepcion': tipo,
            'cda': 'CDA-1',
            'di': 'DI-1',
            'bl': 'MEDUPZ731605',
            'nave_naviera': 'Naviera Uno',
            'lote_contenedor': 'CONT-1',
            'fecha_produccion': '01/08/2026',
            'fecha_vencimiento': '01/08/2027',
            'sui': 'SUI-1',
        })
        return post

    def test_h_extranjero_persiste_todos_los_campos_documentales(self):
        datos = _normalizar_datos_edicion_camion_patio(self.post(), self.camion())
        self.assertEqual(datos['CPA_CTIPO_RECEPCION'], 'EXTRANJERO')
        self.assertEqual(datos['CPA_CBL'], 'MEDUPZ731605')
        self.assertEqual(datos['CPA_CLOTE_CONTENEDOR'], 'CONT-1')
        self.assertEqual(datos['CPA_CFECHAPRODUCCION'], '01082026')
        self.assertEqual(datos['CPA_CFECHAVENCIMIENTOPRODUCTO'], '01082027')
        self.assertEqual(datos['CPA_CSUI'], 'SUI-1')

    def test_h_nacional_conserva_fechas_y_limpia_campos_extranjeros(self):
        datos = _normalizar_datos_edicion_camion_patio(self.post('NACIONAL'), self.camion())
        self.assertEqual(datos['CPA_CTIPO_RECEPCION'], 'NACIONAL')
        self.assertEqual(datos['CPA_CFECHAPRODUCCION'], '01082026')
        for campo in ('CPA_CCDA', 'CPA_CDI', 'CPA_CBL', 'CPA_CNAVE_NAVIERA', 'CPA_CLOTE_CONTENEDOR', 'CPA_CSUI'):
            self.assertEqual(datos[campo], '')

    def test_h_tipo_vacio_conserva_el_valor_persistido(self):
        datos = _normalizar_datos_edicion_camion_patio(self.post(''), self.camion())
        self.assertEqual(datos['CPA_CTIPO_RECEPCION'], 'EXTRANJERO')


    def test_i_despacho_no_acepta_campos_nuevos_de_recepcion(self):
        camion = self.camion(tipo='')
        datos = _normalizar_datos_edicion_camion_patio(self.post(), camion)
        self.assertNotIn('CPA_CTIPO_RECEPCION', datos)
        self.assertNotIn('CPA_CCDA', datos)
        self.assertNotIn('CPA_CFECHAPRODUCCION', datos)
        self.assertEqual(datos['CPA_CBL'], 'MEDUPZ731605')

    def test_h_i_modal_condiciona_campos_y_refresca_sugerencias(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        contenido = template.read_text(encoding='utf-8')
        self.assertIn("if (camion.es_recepcion_sbh)", contenido)
        self.assertIn("name=\"tipo_recepcion\" required", contenido)
        self.assertIn("patio-edit-extranjero", contenido)
        self.assertIn("renderPatioDetalle(response);", contenido)
        self.assertIn("BL similar &mdash; revisar dato", contenido)
