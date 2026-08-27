from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.home.views import (
    _campos_presentacion_planificacion_revision_camion,
    build_datos_planificacion_terramar,
)


class RevisionCamionPresentacionTerramarTests(SimpleTestCase):
    @staticmethod
    def citacion(empresa_id, fecha, secuencia='RECEPCION_TERRAMAR', tipo='RECEPCION'):
        planificacion = SimpleNamespace(
            PL_FFECHAINICIO=datetime(2026, 8, 14, 7, 30),
            PL_CTIPOCUPO=tipo,
        )
        return SimpleNamespace(
            EP_NID_id=empresa_id,
            EP_NID=SimpleNamespace(
                EP_CRAZONSOCIAL='Terramar Chile SpA' if empresa_id == 1 else 'Aceites SBH SpA'
            ),
            PL_NID_id=77,
            PL_NID=planificacion,
            CI_CTIPO=tipo,
            CI_FFECHACITACION=fecha,
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
            RUT_NID=SimpleNamespace(RUT_CNOMBRE='Ruta Norte'),
            TAR_NID=None,
            SN_NID=SimpleNamespace(SN_CRAZONSOCIAL='Cliente SAP'),
        )

    def test_recepcion_terramar_muestra_hora_y_bodega_persistidas(self):
        citacion = self.citacion(1, datetime(2026, 8, 14, 16, 0))
        detalle_terramar = SimpleNamespace(RTD_CBODEGA='T1')

        campos = _campos_presentacion_planificacion_revision_camion(
            citacion,
            {'estanque_destino': 'ESTANQUE_ANTIGUO'},
            detalle_terramar,
        )

        self.assertEqual(campos['Hora citación'], '16:00')
        self.assertEqual(campos['Bodega'], 'T1')
        self.assertNotIn('Estanque destino', campos)

    def test_recepcion_terramar_sin_hora_muestra_fallback(self):
        citacion = self.citacion(1, None)
        campos = _campos_presentacion_planificacion_revision_camion(
            citacion,
            {},
            SimpleNamespace(RTD_CBODEGA='BODEGA NORTE'),
        )
        self.assertEqual(campos['Hora citación'], 'No registrada')

    def test_condicion_visual_terramar_no_depende_de_la_secuencia(self):
        citacion = self.citacion(1, datetime(2026, 8, 14, 9, 5), 'RECEPCION_LEGACY')
        campos = _campos_presentacion_planificacion_revision_camion(
            citacion,
            {'estanque_destino': 'TK-LEGACY'},
            SimpleNamespace(RTD_CBODEGA='B-01'),
        )
        self.assertEqual(campos, {'Hora citación': '09:05', 'Bodega': 'B-01'})

    def test_recepcion_sbh_conserva_estanque_y_no_agrega_hora(self):
        citacion = self.citacion(2, datetime(2026, 8, 14, 16, 0), 'RECEPCION')
        campos = _campos_presentacion_planificacion_revision_camion(
            citacion,
            {'estanque_destino': 'TK-02'},
        )
        self.assertEqual(campos, {'Estanque destino': 'TK-02'})

    def test_builder_recepcion_entrega_minimos_y_datos_propios(self):
        citacion = self.citacion(1, datetime(2026, 8, 14, 16, 0))
        item = SimpleNamespace(IT_NID=SimpleNamespace(IT_CNOMBRE='Harina de pescado'))
        detalle = SimpleNamespace(
            RTD_CBODEGA='T1',
            RTD_CCONTENEDOR_CRT='CRT-900',
            RTD_CEMPRESA_TRANSPORTE='Transportes Uno',
            SN_NID_TRANSPORTISTA=None,
        )
        datos = build_datos_planificacion_terramar(
            citacion,
            detalle_operacional={'codigo': '100100', 'pedido': '4501'},
            valores_ingreso={},
            citacion_item=item,
            detalle_recepcion_terramar=detalle,
        )

        self.assertEqual(datos['Planificación'], '#77')
        self.assertEqual(datos['Fecha planificación'], '14/08/2026')
        self.assertEqual(datos['Hora citación'], '16:00')
        self.assertEqual(datos['Tipo planificación'], 'RECEPCION')
        self.assertEqual(datos['Transportista'], 'Transportes Uno')
        self.assertEqual(datos['Insumo'], 'Harina de pescado')
        self.assertEqual(datos['Bodega'], 'T1')
        self.assertNotIn('Estanque destino', datos)

    def test_builder_despacho_entrega_hora_y_campos_reales(self):
        citacion = self.citacion(
            1,
            datetime(2026, 8, 14, 18, 25),
            'DESPACHO_TERRAMAR',
            'DESPACHO',
        )
        citacion.detalle_despacho = SimpleNamespace(
            CDD_CCONTENEDOR_CRT='CRT-D-01',
            CDD_CBODEGA='BOD-DESP',
            CDD_CTIPO_CAMION='Cortina',
            CDD_BPALLET=True,
            CDD_BRELLENO=False,
            CDD_CTRANSPORTE_A_CARGO='Terramar',
        )
        datos = build_datos_planificacion_terramar(
            citacion,
            detalle_operacional={'codigo': 'PT-01'},
            valores_ingreso={'transportista': 'Transportes Dos'},
            detalle_despacho={
                'sap_cliente_nombre': 'Cliente Despacho',
                'sap_nombre_producto': 'Aceite terminado',
                'destino': 'Puerto Central',
                'sap_oc_cliente': 'OC-7788',
            },
        )

        self.assertEqual(datos['Hora citación'], '18:25')
        self.assertEqual(datos['Cliente'], 'Cliente Despacho')
        self.assertEqual(datos['Destino'], 'Puerto Central')
        self.assertEqual(datos['Contenedor / CRT'], 'CRT-D-01')
        self.assertEqual(datos['Bodega'], 'BOD-DESP')
        self.assertEqual(datos['Tipo camión'], 'Cortina')
        self.assertEqual(datos['Pallet'], 'Sí')
        self.assertEqual(datos['Relleno'], 'No')
        self.assertNotIn('Estanque destino', datos)

    def test_builder_no_interviene_sbh(self):
        citacion = self.citacion(2, datetime(2026, 8, 14, 16, 0))
        self.assertIsNone(build_datos_planificacion_terramar(citacion))

    def test_builder_esta_conectado_a_todas_las_superficies_identificadas(self):
        source = Path('apps/home/views.py').read_text(encoding='utf-8')
        resumen = source[source.index('def PLANIFICACION_CITACION_RESUMEN'):source.index('def PLANIFICACION_CITACION_REVISION_ASISTENTE')]
        revision = source[source.index('def PLANIFICACION_CITACION_REVISION_ASISTENTE'):source.index('def PLANIFICACION_CITACION_EDITAR_INGRESO_ASISTENTE')]
        ingreso = source[source.index('def PLANIFICACION_CITACION_ESTANQUE'):source.index('def AVANZAR_ESTANQUE_SIGUIENTE_ETAPA')]
        salida = source[source.index('def _payload_autorizar_salida_despacho_terramar'):source.index('def _validar_dependencias_autorizacion_despacho_terramar')]

        self.assertGreaterEqual(resumen.count('build_datos_planificacion_terramar('), 2)
        self.assertIn('build_datos_planificacion_terramar(', revision)
        self.assertIn('build_datos_planificacion_terramar(', ingreso)
        self.assertIn('build_datos_planificacion_terramar(', salida)

        template = Path('apps/templates/home/CITACION/operacion_planta.html').read_text(encoding='utf-8')
        self.assertIn('<h6>Datos planificación</h6>', template)
        self.assertIn('planificacion.datos.items', template)
