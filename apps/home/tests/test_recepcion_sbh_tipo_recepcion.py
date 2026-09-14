import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.models import CITACION_DETALLE_OPERACIONAL


class TipoRecepcionSbhTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(
            EP_NID_id=2,
            EP_NID=SimpleNamespace(),
            CI_CTIPO='RECEPCION',
            PL_NID=None,
            PRO_NID=None,
            US_NID=SimpleNamespace(),
        )

    def test_normaliza_solamente_valores_permitidos(self):
        self.assertEqual(views.validar_tipo_recepcion_sbh(' nacional '), ('NACIONAL', ''))
        self.assertEqual(views.validar_tipo_recepcion_sbh('EXTRANJERO'), ('EXTRANJERO', ''))
        self.assertEqual(
            views.validar_tipo_recepcion_sbh(''),
            ('', 'Debe seleccionar si la recepción es Nacional o Extranjera.'),
        )
        self.assertEqual(
            views.validar_tipo_recepcion_sbh('OTRO'),
            ('', 'Tipo de recepción inválido.'),
        )

    def _request_creacion(self, tipo_recepcion):
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {
                'citaciones_json': json.dumps([{
                    'fecha_llegada': '2026-08-21',
                    'tipo_operacion': 'RECEPCION',
                    'secuencia_id': '1',
                    'tipo_origen_recepcion': tipo_recepcion,
                    'almacen_destino': 'CISTERNA',
                    'estanque_destino': 'CISTER20',
                }]),
            },
        )
        request.user = SimpleNamespace()
        return request

    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_backend_rechaza_valor_vacio_antes_de_crear(self, _verificar):
        secuencias = Mock()
        secuencias.filter.return_value.exists.return_value = True
        with patch('apps.home.views.empresa_es_terramar_chile', return_value=False), patch(
            'apps.home.views.queryset_secuencias_recepcion_sbh_por_flujo',
            return_value=secuencias,
        ):
            response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(
                self._request_creacion('')
            )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload['success'])
        self.assertEqual(
            payload['message'],
            'Debe seleccionar si la recepción es Nacional o Extranjera.',
        )

    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_backend_rechaza_valor_manipulado(self, _verificar):
        secuencias = Mock()
        secuencias.filter.return_value.exists.return_value = True
        with patch('apps.home.views.empresa_es_terramar_chile', return_value=False), patch(
            'apps.home.views.queryset_secuencias_recepcion_sbh_por_flujo',
            return_value=secuencias,
        ):
            response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(
                self._request_creacion('OTRO')
            )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload['message'], 'Tipo de recepción inválido.')

    @patch('apps.home.views.CITACION_DETALLE_OPERACIONAL.objects.update_or_create')
    def test_cantidad_mayor_a_uno_persiste_snapshot_individual(self, update_or_create):
        detalles = [SimpleNamespace(save=Mock()) for _ in range(3)]
        update_or_create.side_effect = [(detalle, True) for detalle in detalles]

        for _ in range(3):
            views.guardar_detalle_operacional_citacion(
                self.citacion,
                {'tipo_origen_recepcion': 'NACIONAL'},
            )

        self.assertEqual(update_or_create.call_count, 3)
        for detalle in detalles:
            self.assertEqual(detalle.CDO_CTIPO_RECEPCION, 'NACIONAL')
            detalle.save.assert_called_once_with(update_fields=['CDO_CTIPO_RECEPCION'])

    def test_snapshot_posterior_muestra_etiqueta_amigable(self):
        snapshot = views.datos_snapshot_recepcion_sbh_presentacion(
            self.citacion,
            {'tipo_origen_recepcion': 'EXTRANJERO'},
        )

        self.assertEqual(snapshot['Tipo recepción'], 'Extranjero')

    def test_selector_es_exclusivo_y_cambiar_pedido_no_lo_limpia(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')
        bloque_reset_pedido = template.split(
            'function limpiarDatosPedido', 1
        )[1].split('function limpiarDatosProducto', 1)[0]

        self.assertIn('{% if es_recepcion_sbh %}', template)
        self.assertIn('id="tipo_origen_recepcion"', template)
        self.assertIn('name="tipo_origen_recepcion"', template)
        self.assertIn('<option value="NACIONAL">Nacional</option>', template)
        self.assertIn('<option value="EXTRANJERO">Extranjero</option>', template)
        self.assertIn(
            "tipo_origen_recepcion: ES_RECEPCION_SBH ? getValue('tipo_origen_recepcion') : ''",
            template,
        )
        self.assertNotIn('tipo_origen_recepcion', bloque_reset_pedido)

    def test_campo_fisico_corresponde_al_detalle_operacional(self):
        campo = CITACION_DETALLE_OPERACIONAL._meta.get_field('CDO_CTIPO_RECEPCION')

        self.assertEqual(campo.column, 'CDO_CTIPO_RECEPCION')
        self.assertEqual(campo.max_length, 20)


class ProveedorIngresoMercaderiaSbhTests(SimpleTestCase):
    def test_normaliza_proveedor_manual_sin_cambiar_mayusculas_ni_utf8(self):
        proveedor, mensaje = views.normalizar_proveedor_ingreso_mercaderia_sbh({
            'proveedor_nombre': '  Transportes Peña y Niño Ltda.  ',
        })

        self.assertEqual(proveedor, 'Transportes Peña y Niño Ltda.')
        self.assertEqual(mensaje, '')

    def test_rechaza_proveedor_vacio(self):
        proveedor, mensaje = views.normalizar_proveedor_ingreso_mercaderia_sbh({
            'proveedor_nombre': '   ',
        })

        self.assertEqual(proveedor, '')
        self.assertEqual(mensaje, 'Debe ingresar o seleccionar un proveedor.')

    def test_correccion_manual_prevalece_sobre_sugerencia_sap(self):
        proveedor, mensaje = views.normalizar_proveedor_ingreso_mercaderia_sbh({
            'proveedor_sap': 'PROVEEDOR ABC SPA',
            'proveedor_nombre': 'PROVEEDOR ABC CHILE SPA',
        })

        self.assertEqual(proveedor, 'PROVEEDOR ABC CHILE SPA')
        self.assertEqual(mensaje, '')

    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_backend_rechaza_proveedor_vacio_en_ingreso_mercaderia(self, _verificar):
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {
                'flujo': 'INGRESO_MERCADERIA',
                'citaciones_json': json.dumps([{
                    'fecha_llegada': '2026-08-21',
                    'tipo_operacion': 'RECEPCION',
                    'flujo': 'INGRESO_MERCADERIA',
                    'secuencia_id': '1',
                    'tipo_origen_recepcion': 'NACIONAL',
                    'almacen_destino': 'CISTERNA',
                    'estanque_destino': 'CISTER20',
                    'proveedor_nombre': '   ',
                }]),
            },
        )
        request.user = SimpleNamespace()
        secuencias = Mock()
        secuencias.filter.return_value.exists.return_value = True
        with patch('apps.home.views.empresa_es_terramar_chile', return_value=False), patch(
            'apps.home.views.queryset_secuencias_recepcion_sbh_por_flujo',
            return_value=secuencias,
        ):
            response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload['message'], 'Debe ingresar o seleccionar un proveedor.')

    @patch('apps.home.views.CITACION_DETALLE_OPERACIONAL.objects.update_or_create')
    def test_proveedor_manual_persiste_como_snapshot_sin_maestro(self, update_or_create):
        detalle = SimpleNamespace(save=Mock())
        update_or_create.return_value = (detalle, True)
        citacion = SimpleNamespace(
            EP_NID_id=2,
            EP_NID=SimpleNamespace(),
            CI_CTIPO='RECEPCION',
            PL_NID=None,
            PRO_NID=None,
            US_NID=SimpleNamespace(),
        )

        views.guardar_detalle_operacional_citacion(
            citacion,
            {'proveedor_sap': 'PROVEEDOR MANUAL SPA'},
        )

        defaults = update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDO_CPRODUCTOR'], 'PROVEEDOR MANUAL SPA')
        self.assertIsNone(citacion.PRO_NID)

    def test_control_editable_y_tags_quedan_aislados_al_flujo(self):
        template = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')

        self.assertIn('{% if not es_ingreso_mercaderia_sbh %} disabled{% endif %}', template)
        self.assertIn('const ES_INGRESO_MERCADERIA_SBH =', template)
        self.assertIn('if (ES_INGRESO_MERCADERIA_SBH) {', template)
        self.assertIn('proveedorSelect2Config.tags = true;', template)
        self.assertIn("setValue('codigo_proveedor_sap', codigoSap);", template)
        self.assertIn("setValue('codigo_proveedor_sap', '');", template)
