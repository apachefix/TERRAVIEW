from datetime import datetime
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home.models import CITACION, CITACION_DESPACHO_DETALLE
from apps.home import views
from apps.home.views import build_datos_planificacion_terramar


class DespachoTerramarConductorPendienteTests(SimpleTestCase):
    def test_modelo_existente_admite_conductor_y_camion_vacios(self):
        for field_name in ('CON_NID', 'CA_NID'):
            field = CITACION._meta.get_field(field_name)
            self.assertTrue(field.null)
            self.assertTrue(field.blank)
        for field_name in (
            'CDD_CCONDUCTOR', 'CDD_CTELEFONO_CONDUCTOR',
            'CDD_CCODIGO_PAIS_TELEFONO', 'CDD_CPATENTE',
        ):
            field = CITACION_DESPACHO_DETALLE._meta.get_field(field_name)
            self.assertTrue(field.null)
            self.assertTrue(field.blank)

    def test_presentacion_cambia_pendiente_por_datos_reales_de_ingreso(self):
        citacion = SimpleNamespace(
            EP_NID_id=1,
            EP_NID=SimpleNamespace(EP_CRAZONSOCIAL='Terramar Chile SpA'),
            PL_NID_id=88,
            PL_NID=SimpleNamespace(
                PL_FFECHAINICIO=datetime(2026, 8, 15, 8, 0),
                PL_CTIPOCUPO='DESPACHO',
            ),
            CI_CTIPO='DESPACHO',
            CI_FFECHACITACION=datetime(2026, 8, 15, 10, 0),
            RUT_NID=None,
            TAR_NID=None,
            SN_NID=None,
            detalle_despacho=SimpleNamespace(
                CDD_CCONTENEDOR_CRT='CRT-1', CDD_CBODEGA='B-1',
                CDD_CTIPO_CAMION='Plano', CDD_BPALLET=True,
                CDD_BRELLENO=False, CDD_CTRANSPORTE_A_CARGO='Terramar',
            ),
        )
        detalle = {'empresa_transporte': 'Transportes Uno'}

        pendiente = build_datos_planificacion_terramar(
            citacion, detalle_despacho=detalle, valores_ingreso={}
        )
        self.assertEqual(pendiente['Conductor'], 'Pendiente de confirmar en ingreso')
        self.assertEqual(pendiente['Patente'], 'Pendiente de confirmar en ingreso')

        confirmado = build_datos_planificacion_terramar(
            citacion,
            detalle_despacho=detalle,
            valores_ingreso={'conductor': 'Ana Pérez', 'patente': 'ABCD12'},
        )
        self.assertEqual(confirmado['Conductor'], 'Ana Pérez')
        self.assertEqual(confirmado['Patente'], 'ABCD12')
        self.assertEqual(confirmado['Transportista'], 'Transportes Uno')

    def test_frontend_y_backend_contienen_guardas_del_flujo_pendiente(self):
        modal = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        patio = Path('apps/templates/home/CAMION_PATIO/registrar.html').read_text(encoding='utf-8')
        backend = Path('apps/home/views.py').read_text(encoding='utf-8')

        self.assertIn('despacho_terramar_conductor_pendiente', modal)
        self.assertIn("conductor_pendiente: conductorPendiente", modal)
        self.assertIn("'conductor_pendiente': conductor_pendiente", backend)
        self.assertIn("'patente': ''", backend)
        self.assertIn("(Q(CDD_CPATENTE__isnull=True) | Q(CDD_CPATENTE=''))", backend)
        self.assertIn("or (patente_planificada and patente_planificada !=", backend)
        self.assertIn("(datos_planificados or {}).get('empresa_transporte_nombre')", backend)
        self.assertIn("m.patente||$('#patio_patente_consulta').val()", patio)
        self.assertIn("if(m.conductor_pendiente)", patio)

class RegistroDespachoPendienteTests(SimpleTestCase):
    def test_ingreso_acepta_patente_real_y_conserva_transportista_planificado(self):
        request = RequestFactory().post('/camiones-patio/registrar/', {
            '_empresa_id': '1', 'es_despacho': '1',
            'carga_desde_planificacion': '1', 'citacion_planificada_id': '90',
            'planificacion_planificada_id': '12', 'patente_consultada': 'ABCD12',
            'transporte_a_cargo': 'CLIENTE', 'transportista': 'VALOR MANIPULADO',
            'conductor': 'Ana Pérez', 'conductor_id': '7', 'patente': 'ABCD12',
            'rut_conductor': '12.345.678-5', 'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678', 'tipo_documento': '',
        })
        request.user = SimpleNamespace(username='asistente', is_superuser=False)
        empresa = SimpleNamespace(id=1)
        citacion = SimpleNamespace(
            id=90, pk=90, EP_NID_id=1, CI_CTIPO='DESPACHO',
            PL_NID=SimpleNamespace(id=12), PL_NID_id=12,
        )
        detalle = SimpleNamespace(CDD_CPATENTE='')
        camion = SimpleNamespace(id=5, CPA_CPATENTE='ABCD12')
        crear_camion = MagicMock(return_value=camion)
        trazabilidad = {
            'guia_esperada': '', 'guia_recibida': '',
            'resultado_guia': 'SIN_GUIA_ESPERADA',
            'acepta_diferencia': False, 'observacion': '',
        }

        with patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True), \
             patch.object(views, 'Verificar_empresa', return_value=1), \
             patch.object(views.EMPRESA.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=empresa))), \
             patch.object(views.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(views, '_validar_carga_planificada_patio', return_value=(citacion, trazabilidad)), \
             patch.object(views, '_payload_citacion_terramar_patio', return_value={
                 'transporte_a_cargo': 'Terramar',
                 'empresa_transporte_nombre': 'TRANSPORTES PLANIFICADO',
             }), \
             patch.object(views.CITACION.objects, 'select_for_update', return_value=MagicMock(select_related=MagicMock(return_value=MagicMock(get=MagicMock(return_value=citacion))))), \
             patch.object(views, '_usuario_tiene_acceso_empresa', return_value=True), \
             patch.object(views, '_citacion_terramar_disponible_para_llegada', return_value=True), \
             patch.object(views, 'es_citacion_recepcion_terramar', return_value=False), \
             patch.object(views, 'es_citacion_despacho_terramar', return_value=True), \
             patch.object(views.CITACION_DESPACHO_DETALLE.objects, 'filter', return_value=MagicMock(first=MagicMock(return_value=detalle))), \
             patch.object(views.CAMION_PATIO.objects, 'create', crear_camion), \
             patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'create'), \
             patch.object(views, '_asociar_camion_patio_a_citacion', return_value={}), \
             patch.object(views, 'registrar_log_camion_no_planificado'), \
             patch.object(views, 'notificar_camion_patio_nuevo', return_value=0), \
             patch.object(views.messages, 'success'), \
             patch.object(views, 'redirect', return_value=SimpleNamespace(status_code=302)):
            response = views.CAMIONES_PATIO_REGISTRAR(request)

        self.assertEqual(response.status_code, 302)
        guardado = crear_camion.call_args.kwargs
        self.assertEqual(guardado['CPA_CTRANSPORTISTA_DECLARADO'], 'TRANSPORTES PLANIFICADO')
        self.assertEqual(guardado['CPA_CPATENTE'], 'ABCD12')
        self.assertEqual(guardado['CPA_CNOMBRE_CONDUCTOR'], 'Ana Pérez')

class EstadoConductorIngresoDespachoTests(SimpleTestCase):
    def test_fk_valido_define_conductor_registrado_aunque_falten_rut_o_telefono(self):
        conductor = SimpleNamespace(
            id=7457, EP_NID_id=1, CON_BHABILITADO=True,
            CON_CNOMBRE='ALEXIS', CON_CAPELLIDO='ARAVENA',
            CON_CRUT='', CON_CTELEFONO='', CON_CCODIGO_PAIS_TELEFONO='',
        )
        resultado = views._resolver_conductor_planificado_despacho_patio(
            SimpleNamespace(CON_NID=conductor),
            SimpleNamespace(CDD_CCONDUCTOR='ALEXIS ARAVENA'),
        )
        self.assertIs(resultado, conductor)

    def test_nombre_historico_solo_resuelve_si_es_unico_en_terramar(self):
        conductor = SimpleNamespace(
            id=7457, EP_NID_id=1, CON_BHABILITADO=True,
            CON_CNOMBRE='ALEXIS', CON_CAPELLIDO='ARAVENA', SN_NID_id=747,
        )
        queryset = MagicMock()
        queryset.order_by.return_value = [conductor]
        with patch.object(views.CONDUCTOR.objects, 'filter', return_value=queryset):
            resultado = views._resolver_conductor_planificado_despacho_patio(
                SimpleNamespace(CON_NID=None),
                SimpleNamespace(CDD_CCONDUCTOR='Alexis  Aravena'),
            )
        self.assertIs(resultado, conductor)

    def test_js_no_activa_modo_manual_para_despacho_terramar_sin_match(self):
        patio = Path('apps/templates/home/CAMION_PATIO/registrar.html').read_text(encoding='utf-8')
        self.assertIn('else if(esDespachoTerramar)', patio)
