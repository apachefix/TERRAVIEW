from pathlib import Path
from types import SimpleNamespace

from django.http import QueryDict
from django.test import SimpleTestCase

from apps.home.views import _normalizar_datos_edicion_camion_patio


class RevisionCamionDocumentosRecepcionSbhTests(SimpleTestCase):
    def camion(self, empresa=2, tipo='EXTRANJERO'):
        return SimpleNamespace(
            EP_NID_id=empresa,
            CPA_CTIPO_RECEPCION=tipo,
            transporte_a_cargo='CLIENTE',
            CPA_CTRANSPORTISTA_DECLARADO='CLIENTE',
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
            CPA_CCDA='CDA-1',
            CPA_CDI='DI-1',
            CPA_CBL='MEDUPZ731605',
            CPA_CNAVE_NAVIERA='Naviera Uno',
            CPA_CLOTE_CONTENEDOR='MSNU2191837',
            CPA_CFECHAPRODUCCION='01082026',
            CPA_CFECHAVENCIMIENTOPRODUCTO='01082027',
            CPA_CSUI='SUI-1',
        )

    def test_post_parcial_conserva_tipo_y_documentos_extranjero(self):
        post = QueryDict('', mutable=True)
        post.update({'transportista': 'CLIENTE'})

        datos = _normalizar_datos_edicion_camion_patio(post, self.camion())

        self.assertEqual(datos['CPA_CTIPO_RECEPCION'], 'EXTRANJERO')
        self.assertEqual(datos['CPA_CBL'], 'MEDUPZ731605')
        self.assertEqual(datos['CPA_CLOTE_CONTENEDOR'], 'MSNU2191837')
        self.assertEqual(datos['CPA_CCDA'], 'CDA-1')
        self.assertEqual(datos['CPA_CDI'], 'DI-1')
        self.assertEqual(datos['CPA_CNAVE_NAVIERA'], 'Naviera Uno')
        self.assertEqual(datos['CPA_CFECHAPRODUCCION'], '01082026')
        self.assertEqual(datos['CPA_CFECHAVENCIMIENTOPRODUCTO'], '01082027')
        self.assertEqual(datos['CPA_CSUI'], 'SUI-1')

    def test_post_parcial_nacional_conserva_fechas(self):
        datos = _normalizar_datos_edicion_camion_patio(QueryDict(''), self.camion(tipo='NACIONAL'))
        self.assertEqual(datos['CPA_CTIPO_RECEPCION'], 'NACIONAL')
        self.assertEqual(datos['CPA_CFECHAPRODUCCION'], '01082026')
        self.assertEqual(datos['CPA_CFECHAVENCIMIENTOPRODUCTO'], '01082027')
        for campo in ('CPA_CCDA', 'CPA_CDI', 'CPA_CBL', 'CPA_CNAVE_NAVIERA', 'CPA_CLOTE_CONTENEDOR', 'CPA_CSUI'):
            self.assertEqual(datos[campo], '')

    def test_tipo_manipulado_sigue_siendo_rechazado(self):
        with self.assertRaisesRegex(ValueError, 'Tipo de recepción inválido'):
            _normalizar_datos_edicion_camion_patio(
                QueryDict('tipo_recepcion=OTRO'),
                self.camion(),
            )

    def test_recepcion_terramar_no_activa_documentos_sbh(self):
        datos = _normalizar_datos_edicion_camion_patio(QueryDict(''), self.camion(empresa=1))
        self.assertNotIn('CPA_CTIPO_RECEPCION', datos)
        self.assertNotIn('CPA_CCDA', datos)
        self.assertNotIn('CPA_CFECHAPRODUCCION', datos)

    def test_despacho_sbh_no_exige_tipo_recepcion(self):
        datos = _normalizar_datos_edicion_camion_patio(QueryDict(''), self.camion(tipo=''))
        self.assertNotIn('CPA_CTIPO_RECEPCION', datos)
        self.assertEqual(datos['CPA_CBL'], 'MEDUPZ731605')

    def test_template_precarga_y_envia_campos_documentales(self):
        template = Path(__file__).resolve().parents[3] / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        contenido = template.read_text(encoding='utf-8')
        self.assertIn('const esRecepcionSbh = !!valores.es_recepcion_sbh', contenido)
        self.assertIn("tipoRecepcion === 'EXTRANJERO' ? 'selected'", contenido)
        self.assertIn("tipoRecepcion === 'NACIONAL' ? 'selected'", contenido)
        for campo in (
            'revision_tipo_recepcion', 'revision_cda', 'revision_di',
            'revision_bl_edicion', 'revision_nave_naviera',
            'revision_lote_contenedor_edicion', 'revision_fecha_produccion',
            'revision_fecha_vencimiento', 'revision_sui',
        ):
            self.assertIn(campo, contenido)
        self.assertIn('Object.assign(datosEdicion', contenido)
        self.assertIn("$('.revision-recepcion-extranjero').toggle(esExtranjero)", contenido)

    def test_payload_backend_usa_campos_reales_y_condicion_sbh(self):
        views = Path(__file__).resolve().parents[1] / 'views.py'
        contenido = views.read_text(encoding='utf-8')
        self.assertIn("'tipo_recepcion': contexto_ingreso['camion'].CPA_CTIPO_RECEPCION", contenido)
        self.assertIn("'cda': contexto_ingreso['camion'].CPA_CCDA", contenido)
        self.assertIn("es_citacion_recepcion_sbh(citacion) else {}", contenido)
