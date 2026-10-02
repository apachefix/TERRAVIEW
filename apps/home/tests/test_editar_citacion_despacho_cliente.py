import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase

from apps.home import views
from apps.home.models import CITACION
from apps.home.sap_despacho import validar_asignaciones_sap_planificadas


class ClienteEdicionDespachoTests(SimpleTestCase):
    def asignacion(self, cliente='C001', nombre='Cliente Uno', abs_id='433'):
        return {
            'id': 7,
            'sap_abs_id': abs_id,
            'contrato_sap': f'AC-{abs_id}',
            'linea_acuerdo_sap': '1',
            'codigo_producto_sap': f'ITEM-{abs_id}',
            'nombre_producto_sap': 'Producto',
            'cliente_codigo': cliente,
            'cliente_nombre': nombre,
            'oc_cliente': 'OC-1',
            'cantidad_planificada_sap': '1000',
            'cantidad_consumida_sap': '200',
            'saldo_contrato_sap': '800',
            'unidad_medida': 'KG',
            'cantidad_intentada_despachar': '100',
            'estado': 'PLANIFICADA',
        }

    def post(self, asignaciones, **extra):
        data = {
            'fecha_despacho': '2026-09-10',
            'fecha_llegada_destino': '2026-09-11',
            'hora_llegada_planta': '08:30',
            'hora_llegada_destino': '13:45',
            'orden_carga': '2°',
            'tipo_carga': 'Cisterna',
            'destino': 'Destino actualizado',
            'id_secuencia': '5',
            'salida_documento': 'FE',
            'empresa_transporte': 'Transportes Dos',
            'conductor': 'Conductor Dos',
            'patente': 'bb cc 22',
            'asignaciones_sap': json.dumps(asignaciones),
        }
        data.update(extra)
        return data

    def test_precarga_prefiere_relacion_local(self):
        cliente = SimpleNamespace(id=3, SN_CCODIGO_SAP='C001', SN_CRAZONSOCIAL='Cliente Uno')
        resultado = views.cliente_edicion_citacion_despacho(
            SimpleNamespace(SN_NID=cliente), {}, [self.asignacion('C999')]
        )
        self.assertEqual(resultado, {'id': 3, 'codigo': 'C001', 'text': 'Cliente Uno'})

    def test_lock_limita_for_update_a_citacion_con_relaciones_opcionales(self):
        queryset = CITACION.objects.select_for_update(of=('self',)).select_related(
            'EP_NID', 'SN_NID', 'SC_NID'
        )
        self.assertEqual(queryset.query.select_for_update_of, ('self',))
        self.assertTrue(CITACION._meta.get_field('SN_NID').null)
    def test_precarga_recupera_snapshot_sap_si_sn_nid_es_nulo(self):
        resultado = views.cliente_edicion_citacion_despacho(
            SimpleNamespace(SN_NID=None),
            {'sap_cliente_codigo': 'C001', 'sap_cliente_nombre': 'Cliente detalle'},
            [self.asignacion()],
        )
        self.assertEqual(resultado, {'id': None, 'codigo': 'C001', 'text': 'Cliente Uno'})

    def test_contratos_de_clientes_distintos_se_rechazan(self):
        with self.assertRaisesRegex(ValueError, 'mismo cliente'):
            validar_asignaciones_sap_planificadas({
                'asignaciones_sap': [
                    self.asignacion('C001', abs_id='433'),
                    {**self.asignacion('C002', abs_id='434'), 'id': 8},
                ]
            })

    @patch('apps.home.views.serializar_asignaciones_sap_planificadas')
    @patch('apps.home.views.detalle_despacho_resumen_dict')
    @patch('apps.home.views.sincronizar_asignaciones_sap_planificadas')
    @patch('apps.home.views.CITACION_DESPACHO_DETALLE.objects.select_for_update')
    @patch('apps.home.views.SECUENCIA.objects.get')
    @patch('apps.home.views.resolver_socio_negocio_planificacion', return_value=None)
    @patch('apps.home.views.citacion_puede_editar_planificacion', return_value=True)
    @patch('apps.home.views.CITACION.objects.select_for_update')
    def test_edicion_sin_selector_conserva_cliente_sap_y_no_afecta_otra_citacion(
        self, bloquear, _editable, _resolver, secuencia_get, detalle_manager,
        sincronizar, detalle_resumen, serializar,
    ):
        empresa = SimpleNamespace()
        citacion = SimpleNamespace(
            id=99, EP_NID=empresa, EP_NID_id=2, SN_NID=None, SC_NID=None,
            CI_CTIPO='DESPACHO', CI_CTIPO_FLETE='', CI_CTIPODOCUMENTO='',
            CI_CNUMERODOCUMENTO='', CI_CCOMENTARIO='', save=Mock(),
        )
        consulta = bloquear.return_value.select_related.return_value
        consulta.get.return_value = citacion
        detalle_resumen.return_value = {
            'sap_cliente_codigo': 'C001', 'sap_cliente_nombre': 'Cliente Uno'
        }
        serializar.return_value = [self.asignacion()]
        secuencia_get.return_value = SimpleNamespace(SE_CCODIGO='D', SE_CNOMBRE='Despacho')
        detalle_manager.return_value.update_or_create.return_value = (
            SimpleNamespace(EP_NID=empresa, US_NID=None), False
        )

        response = views.actualizar_citacion_despacho_planificacion.__wrapped__(
            SimpleNamespace(user=SimpleNamespace(), POST=self.post([self.asignacion()])), 99
        )

        self.assertEqual(json.loads(response.content), {'valid': True})
        bloquear.assert_called_once_with(of=('self',))
        consulta.get.assert_called_once_with(id=99)
        self.assertIsNone(citacion.SN_NID)
        defaults = detalle_manager.return_value.update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDD_CSAP_CLIENTE_CODIGO'], 'C001')
        self.assertEqual(defaults['CDD_CSAP_CLIENTE_NOMBRE'], 'Cliente Uno')
        self.assertEqual(defaults['CDD_CEMPRESA_TRANSPORTE'], 'Transportes Dos')
        self.assertEqual(defaults['CDD_CCONDUCTOR'], 'Conductor Dos')
        self.assertEqual(defaults['CDD_CPATENTE'], 'BB CC 22')
        sincronizar.assert_called_once()
        self.assertEqual(sincronizar.call_args.args[1][0]['contrato_sap'], 'AC-433')

    @patch('apps.home.views.serializar_asignaciones_sap_planificadas', return_value=[])
    @patch('apps.home.views.detalle_despacho_resumen_dict', return_value={})
    @patch('apps.home.views.resolver_socio_negocio_planificacion', return_value=None)
    @patch('apps.home.views.citacion_puede_editar_planificacion', return_value=True)
    @patch('apps.home.views.CITACION.objects.select_for_update')
    def test_selector_incompatible_con_contratos_se_rechaza(
        self, bloquear, _editable, _resolver, _detalle, _serializar,
    ):
        bloquear.return_value.select_related.return_value.get.return_value = SimpleNamespace(
            EP_NID=SimpleNamespace(), EP_NID_id=2, SN_NID=None, SC_NID=None,
            CI_CTIPO='DESPACHO',
        )
        post = self.post(
            [self.asignacion()], id_cliente='C999',
            cliente_codigo='C999', cliente_nombre='Cliente Nueve'
        )
        with self.assertRaisesRegex(ValueError, 'coincidir con todos los contratos SAP'):
            views.actualizar_citacion_despacho_planificacion.__wrapped__(
                SimpleNamespace(user=SimpleNamespace(), POST=post), 99
            )

    def test_frontend_precarga_cardcode_y_sincroniza_reemplazo(self):
        template = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        self.assertIn("const inicial = new Option(nombreInicial, codigoInicial, true, true);", template)
        self.assertIn("data: { _empresa_id: empresaIdActiva() }", template)
        self.assertIn('function editDespachoSincronizarClienteDesdeContratos()', template)
        self.assertIn("$('#edit_cliente_codigo').val()", template)
        self.assertNotIn('clienteGlobal && cliente && clienteGlobal !== cliente', template)
class LockPostgresqlDespachoTests(TransactionTestCase):
    def test_for_update_con_fk_nullable_bloquea_solo_citacion(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La regresión corresponde específicamente a PostgreSQL.')
        with transaction.atomic():
            queryset = CITACION.objects.select_for_update(of=('self',)).select_related(
                'EP_NID', 'SN_NID', 'SC_NID'
            ).filter(pk=-1)
            # PostgreSQL analiza el LEFT OUTER JOIN de SN_NID aunque no haya filas.
            self.assertEqual(list(queryset), [])
