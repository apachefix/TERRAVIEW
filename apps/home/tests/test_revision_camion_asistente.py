from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.views import (
    _normalizar_datos_edicion_camion_patio,
    requiere_ruta_transportista_revision,
    ruta_transportista_asistente_guardada,
)


class RevisionCamionAsistenteTests(SimpleTestCase):
    def setUp(self):
        self.camion = SimpleNamespace(
            transporte_a_cargo='TERRAMAR',
            CPA_CTRANSPORTISTA_DECLARADO='Transportes Uno',
            CPA_CNOMBRE_CONDUCTOR='Conductor Uno',
            CPA_CRUT_CONDUCTOR='11111111-1',
            CPA_CTELEFONO_CONDUCTOR='+56912345678',
            CPA_CPATENTE='ABCD12',
            CPA_CPROVEEDOR_DECLARADO='Proveedor',
            CPA_CCLIENTE_DECLARADO='Cliente',
            CPA_CNUMERO_GUIA='000212',
            CPA_CINSUMO_DECLARADO_GUIA='Producto',
            CPA_CBL='BL-1',
            CPA_CCANTIDAD_EJES='6',
            CPA_CLOTE_CONTENEDOR='L-1',
            CPA_COBSERVACION='',
        )

    def test_normaliza_edicion_y_conserva_numero_guia(self):
        post = QueryDict('', mutable=True)
        post.update({
            'patente': 'zzzz99',
            'telefono_conductor': '912345678',
            'numero_guia': '000212',
            # Clientes antiguos pueden seguir enviandolo: se ignora sin error.
            'cantidad_ejes': '8',
        })
        datos = _normalizar_datos_edicion_camion_patio(post, self.camion)
        self.assertEqual(datos['CPA_CPATENTE'], 'ZZZZ99')
        self.assertEqual(datos['CPA_CNUMERO_GUIA'], '000212')
        self.assertEqual(datos['CPA_CTELEFONO_CONDUCTOR'], '912345678')
        self.assertEqual(datos['CPA_CCODIGO_PAIS_TELEFONO'], '+56')
        self.assertNotIn('CPA_CCANTIDAD_EJES', datos)

    def test_ruta_vacia_no_cuenta_como_guardada(self):
        dato_vacio = SimpleNamespace(DO_CVALOR='')
        citacion = SimpleNamespace(TAR_NID_id=1, RUT_NID_id=1, TAR_NID=SimpleNamespace(RUT_NID_id=1))
        with patch('apps.home.views.obtener_datos_operacion_citacion', return_value=({'AR_RUTA_TRANSPORTISTA': dato_vacio}, [])):
            self.assertFalse(ruta_transportista_asistente_guardada(citacion))

    def test_recepcion_sbh_cliente_no_requiere_ruta(self):
        citacion = SimpleNamespace(CI_CTIPO='RECEPCION', EP_NID_id=2)
        contexto = {'requiere_ruta_transportista': False}
        self.assertFalse(requiere_ruta_transportista_revision(citacion, contexto))

    def test_recepcion_sbh_terramar_requiere_ruta(self):
        citacion = SimpleNamespace(CI_CTIPO='RECEPCION', EP_NID_id=2)
        contexto = {'requiere_ruta_transportista': True}
        self.assertTrue(requiere_ruta_transportista_revision(citacion, contexto))

    def test_despacho_sbh_cliente_no_requiere_ruta_aunque_camion_no_informe_modalidad(self):
        citacion = SimpleNamespace(CI_CTIPO='DESPACHO', EP_NID_id=2)
        contexto = {'requiere_ruta_transportista': True}
        with patch('apps.home.views.sap_despacho_detalle_resumen_dict', return_value={'condicion_entrega': 'Cliente'}):
            self.assertFalse(requiere_ruta_transportista_revision(citacion, contexto))

    def test_despacho_sbh_terramar_requiere_ruta_aunque_contexto_camion_diga_cliente(self):
        citacion = SimpleNamespace(CI_CTIPO='DESPACHO', EP_NID_id=2)
        contexto = {'requiere_ruta_transportista': False}
        with patch('apps.home.views.sap_despacho_detalle_resumen_dict', return_value={'condicion_entrega': 'Terramar'}):
            self.assertTrue(requiere_ruta_transportista_revision(citacion, contexto))

    def test_backend_no_acepta_guardar_ruta_para_condicion_cliente(self):
        request = RequestFactory().post('/pla-citacion-guardar-ruta-asistente/38708/', {
            'ruta_id': '', 'tarifa_id': '',
        })
        request.user = SimpleNamespace(is_superuser=False)
        request.session = {'empresa_id': 2}
        citacion = SimpleNamespace(CI_CTIPO='DESPACHO', EP_NID_id=2)
        consulta = MagicMock()
        consulta.get.return_value = citacion
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=False), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True), \
             patch.object(views.CITACION.objects, 'select_related', return_value=consulta), \
             patch.object(views, '_contexto_ingreso_camion_patio', return_value={'requiere_ruta_transportista': True}), \
             patch.object(views, 'sap_despacho_detalle_resumen_dict', return_value={'condicion_entrega': 'Cliente'}), \
             patch.object(views, 'validar_tarifa_transportista_revision') as validar_tarifa:
            response = views.GUARDAR_RUTA_CAMION_ASISTENTE(request, 38708)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('no corresponde', response.content.decode('utf-8'))
        validar_tarifa.assert_not_called()

    def test_backend_recepcion_cliente_no_acepta_guardar_ruta_ni_valida_tarifa(self):
        request = RequestFactory().post('/pla-citacion-guardar-ruta-asistente/38761/', {
            'ruta_id': '', 'tarifa_id': '',
        })
        request.user = SimpleNamespace(is_superuser=False)
        request.session = {'empresa_id': 2}
        citacion = SimpleNamespace(CI_CTIPO='RECEPCION', EP_NID_id=2)
        consulta = MagicMock()
        consulta.get.return_value = citacion
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_asistente_recepcion', return_value=True), \
             patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=False), \
             patch.object(views.CITACION.objects, 'select_related', return_value=consulta), \
             patch.object(views, '_contexto_ingreso_camion_patio', return_value={'requiere_ruta_transportista': False}), \
             patch.object(views, 'validar_tarifa_transportista_revision') as validar_tarifa:
            response = views.GUARDAR_RUTA_CAMION_ASISTENTE(request, 38761)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('no corresponde', response.content.decode('utf-8'))
        validar_tarifa.assert_not_called()

    def test_frontend_renderiza_y_consulta_ruta_solo_si_backend_la_requiere(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn(
            "${data.requiere_ruta_transportista ? renderRevisionRutaTransportistaCampo(rutas, rutaMensaje) : ''}",
            template,
        )
        self.assertIn(
            'if (puedeEditarRevision && revisionRequiereRutaTransportista)',
            template,
        )

    def test_modal_sbh_reconstruye_controles_en_ambos_sentidos(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn('function reconstruirCamposTransporteRevision(modalidad)', template)
        self.assertIn("modalActivo.find('.revision-transporte-campo').remove()", template)
        self.assertIn("reconstruirCamposTransporteRevision($(this).val() === 'CLIENTE' ? 'CLIENTE' : 'TERRAMAR')", template)
        self.assertIn("$('#bloqueRutaTransportista').remove()", template)
        self.assertIn('renderRevisionRutaTransportistaCampo([],', template)
        self.assertIn('const requiereRuta = esTerramar && revisionCondicionEntregaPermiteRuta;', template)
        self.assertIn("String(response.condicion_entrega || '').toUpperCase() !== 'CLIENTE'", template)

    def test_selector_formal_usa_transportista_sbh_estricto_y_conductor_independiente(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn("empresa_id: empresaId, estricto_empresa: '1'", template)
        bloque_conductor = template[template.index("$('#revision_conductor').off('.revisionIngreso')"):]
        bloque_conductor = bloque_conductor[:bloque_conductor.index("$(document).on('click', '#btn_revision_editar_datos'")]
        self.assertNotIn('transportista_id:', bloque_conductor)
        self.assertNotIn('transportista:', bloque_conductor)

    def test_conductor_formal_tiene_rut_readonly_y_telefono_editable(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn('id="revision_rut_conductor" value="${escapeHtml(valores.rut_conductor || \'\')}" readonly', template)
        self.assertIn('id="revision_telefono_conductor" value="${escapeHtml(valores.telefono_conductor || \'\')}" required', template)
        self.assertNotIn('id="revision_telefono_conductor" readonly', template)

    def test_backend_reconstruye_maestro_y_admite_transportista_manual_cliente_sbh(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        self.assertIn("datos['CPA_CRUT_CONDUCTOR'] = str(conductor.CON_CRUT or '').strip()", source)
        self.assertIn("elif Empresa == ID_ACEITES_SBH:\n                datos['CPA_CTRANSPORTISTA_DECLARADO']", source)
        self.assertIn("queryset_transportistas_validos_ingreso_camion(\n                Empresa, estrictamente_empresa=True", source)
