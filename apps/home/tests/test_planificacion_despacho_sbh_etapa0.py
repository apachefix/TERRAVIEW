import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.planificacion_despacho_sbh import (
    capacidad_despacho_sbh,
    camiones_requeridos,
    distribuir_asignaciones,
    distribuir_tonelaje,
    formato_decimal_natural,
    validar_lote_borradores_sbh,
)
from apps.home.sap_despacho import validar_asignaciones_sap_planificadas


def asignacion(numero, cantidad, linea='0'):
    return {
        'sap_abs_id': numero,
        'contrato_sap': f'AC-{numero}',
        'linea_acuerdo_sap': linea,
        'codigo_producto_sap': 'ITEM-1',
        'nombre_producto_sap': 'Aceite',
        'cliente_codigo': 'C001',
        'cliente_nombre': 'Cliente Uno',
        'oc_cliente': 'OC-1',
        'cantidad_planificada_sap': '500.00000',
        'cantidad_consumida_sap': '0.00000',
        'saldo_contrato_sap': '500.00000',
        'unidad_medida': 'TON',
        'cantidad_intentada_despachar': cantidad,
        'estado': 'PLANIFICADA',
    }


def resolver_acuerdo(item):
    return {
        'nombre_insumo': item['nombre_producto_sap'],
        'cliente_nombre': item['cliente_nombre'],
        'oc_cliente': item['oc_cliente'],
        'cantidad_planificada': item['cantidad_planificada_sap'],
        'cantidad_consumida': item['cantidad_consumida_sap'],
        'saldo_contrato_sap': item['saldo_contrato_sap'],
        'unidad_medida': item['unidad_medida'],
    }


def lote_acuerdo_real(numero='423', abs_id='4031', oc_enviada='OC-FALSA'):
    original = {
        'sap_abs_id': abs_id,
        'contrato_sap': numero,
        'linea_acuerdo_sap': '1',
        'codigo_producto_sap': '900129',
        'nombre_producto_sap': 'ACIDO GRASO MARINO 12%',
        'cliente_codigo': 'C96701530',
        'cliente_nombre': 'COMERCIALIZADORA NUTRECO CHILE LIMITADA',
        'oc_cliente': oc_enviada,
        'cantidad_planificada_sap': '300.00000',
        'cantidad_consumida_sap': '0.00000',
        'saldo_contrato_sap': '300.00000',
        'unidad_medida': 'Toneladas Metricas',
        'cantidad_intentada_despachar': '27.50000',
        'estado': 'PLANIFICADA',
    }
    return [{
        'despacho_sbh_etapa0': True,
        'numero_borrador': 1,
        'distribucion_borradores': 'INICIAL_CAPACIDAD',
        'cliente': 'C96701530',
        'cliente_codigo': 'C96701530',
        'cliente_nombre': 'COMERCIALIZADORA NUTRECO CHILE LIMITADA',
        'fecha_llegada': '2026-09-22',
        'tipo_operacion': 'DESPACHO',
        'secuencia_id': '1',
        'tipo_carga': 'Cisterna',
        'total_planificado_despacho': '27.50000',
        'cantidad_estimada': '27.50000',
        'asignaciones_planificacion_sap': [dict(original)],
        'asignaciones_sap': [dict(original)],
    }]


def fila_sap_real(numero='423', abs_id='4031', oc_cliente=None):
    return {
        'sap_abs_id': int(abs_id),
        'sap_acuerdo_numero': int(numero),
        'linea_acuerdo': 1,
        'codigo_insumo': '900129',
        'nombre_insumo': 'ACIDO GRASO MARINO 12%',
        'cliente_codigo': 'C96701530',
        'cliente_nombre': 'COMERCIALIZADORA NUTRECO CHILE LIMITADA',
        'oc_cliente': oc_cliente,
        'cantidad_planificada': 300,
        'cantidad_consumida': 0,
        'saldo_contrato_sap': 300,
        'unidad_medida': 'Toneladas Metricas',
    }


class CalculoDespachoSbhEtapa0Tests(SimpleTestCase):
    def test_capacidades_y_camiones_obligatorios(self):
        self.assertEqual(camiones_requeridos('100', capacidad_despacho_sbh('Cisterna')), 4)
        self.assertEqual(camiones_requeridos('50', capacidad_despacho_sbh('Cisterna')), 2)
        self.assertEqual(camiones_requeridos('100', capacidad_despacho_sbh('Contenedor')), 5)
        self.assertEqual(camiones_requeridos('100', capacidad_despacho_sbh('Isotank')), 5)
        self.assertEqual(capacidad_despacho_sbh('IBC'), Decimal('18.00000'))
        self.assertEqual(capacidad_despacho_sbh('IBC', 20), Decimal('18.00000'))
        self.assertEqual(capacidad_despacho_sbh('IBC', 99), Decimal('18.00000'))
        self.assertEqual(camiones_requeridos('100', capacidad_despacho_sbh('IBC')), 6)

    def test_distribucion_inicial_cisterna_no_inventa_tonelaje(self):
        self.assertEqual(
            distribuir_tonelaje('100', '27.5'),
            [Decimal('27.50000'), Decimal('27.50000'), Decimal('27.50000'), Decimal('17.50000')],
        )

    def test_redistribucion_manual_es_determinista(self):
        cantidades = distribuir_tonelaje('100', '27.5', 5)
        self.assertEqual(cantidades, [Decimal('20.00000')] * 5)
        insuficiente = distribuir_tonelaje('100', '21.6', 4)
        self.assertEqual(sum(insuficiente), Decimal('86.40000'))

    def test_formato_visual_natural(self):
        self.assertEqual(formato_decimal_natural(Decimal('100.00000')), '100')
        self.assertEqual(formato_decimal_natural(Decimal('73.18100')), '73.181')
        self.assertEqual(formato_decimal_natural(Decimal('27.50000')), '27.5')
        self.assertEqual(formato_decimal_natural(Decimal('0.00500')), '0.005')

    def test_distribucion_multiacuerdo_conserva_sumas(self):
        originales = [asignacion('10', '73.181'), asignacion('20', '26.819')]
        cantidades = distribuir_tonelaje('100', '27.5')
        matriz = distribuir_asignaciones(originales, cantidades)
        self.assertEqual(
            [sum(Decimal(item['cantidad_intentada_despachar']) for item in columna) for columna in matriz],
            cantidades,
        )
        acumulado = {}
        for columna in matriz:
            for item in columna:
                clave = item['sap_abs_id']
                acumulado[clave] = acumulado.get(clave, Decimal('0')) + Decimal(item['cantidad_intentada_despachar'])
        self.assertEqual(acumulado, {'10': Decimal('73.18100'), '20': Decimal('26.81900')})

    def test_backend_recalcula_y_rechaza_cantidad_manipulada(self):
        originales = [asignacion('10', '73.181'), asignacion('20', '26.819')]
        cantidades = distribuir_tonelaje('100', '27.5')
        por_borrador = distribuir_asignaciones(originales, cantidades)
        lote = []
        for indice, cantidad in enumerate(cantidades):
            lote.append({
                'despacho_sbh_etapa0': True,
                'numero_borrador': indice + 1,
                'distribucion_borradores': 'INICIAL_CAPACIDAD',
                'cliente': 'C001',
                'cliente_codigo': 'C001',
                'cliente_nombre': 'Cliente Uno',
                'fecha_llegada': '2026-09-10',
                'tipo_operacion': 'DESPACHO',
                'secuencia_id': '1',
                'tipo_carga': 'Cisterna',
                'total_planificado_despacho': '100.00000',
                'cantidad_estimada': str(cantidad),
                'asignaciones_planificacion_sap': originales,
                'asignaciones_sap': por_borrador[indice],
            })

        for item, transportista in zip(lote, ('BRETTI', 'PASCAL', 'OCEAN TRUCK', 'CLIENTE')):
            item.update({
                'condicion_entrega': 'Cliente' if transportista == 'CLIENTE' else 'Terramar',
                'empresa_transporte': transportista,
                'conductor': '' if transportista != 'PASCAL' else 'Conductor Dos',
                'patente': '' if transportista != 'OCEAN TRUCK' else 'ABCD12',
            })

        resultado = validar_lote_borradores_sbh(lote, resolver_acuerdo=resolver_acuerdo)
        self.assertEqual(resultado['cantidad_borradores'], 4)
        self.assertEqual(resultado['total'], Decimal('100.00000'))
        lote[0]['cantidad_estimada'] = '27.4'
        with self.assertRaisesMessage(ValueError, 'manipuladas'):
            validar_lote_borradores_sbh(lote, resolver_acuerdo=resolver_acuerdo)

    @patch('apps.home.views.sap_despacho_guardar_detalle_citacion')
    def test_persistencia_cabecera_usa_total_estimado_del_borrador(self, guardar_base):
        from apps.home.views import guardar_detalle_despacho_citacion

        detalle = SimpleNamespace(save=Mock())
        guardar_base.return_value = detalle
        citacion = SimpleNamespace(EP_NID_id=2, CI_CTIPO='DESPACHO')
        resultado = guardar_detalle_despacho_citacion(citacion, {
            'despacho_sbh_etapa0': True,
            'cantidad_estimada': '27.50000',
        })
        self.assertIs(resultado, detalle)
        self.assertEqual(detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR, Decimal('27.50000'))
        detalle.save.assert_called_once()

    def test_backend_rechaza_acuerdo_inventado(self):
        original = asignacion('999', '27.5')
        lote = [{
            'despacho_sbh_etapa0': True,
            'numero_borrador': 1,
            'distribucion_borradores': 'INICIAL_CAPACIDAD',
            'cliente': 'C001',
            'cliente_codigo': 'C001',
            'fecha_llegada': '2026-09-10',
            'tipo_operacion': 'DESPACHO',
            'secuencia_id': '1',
            'tipo_carga': 'Cisterna',
            'total_planificado_despacho': '27.50000',
            'cantidad_estimada': '27.50000',
            'asignaciones_planificacion_sap': [original],
            'asignaciones_sap': [original],
        }]
        with self.assertRaisesMessage(ValueError, 'no existe'):
            validar_lote_borradores_sbh(lote, resolver_acuerdo=lambda _: False)

    def test_backend_rechaza_fila_sap_sin_oc_e_ignora_oc_falsa_del_navegador(self):
        lote = lote_acuerdo_real(oc_enviada='OC-INVENTADA')

        with self.assertRaisesMessage(
            ValueError,
            'El acuerdo SAP 423 no posee una OC asociada y no puede utilizarse para planificar.',
        ):
            validar_lote_borradores_sbh(
                lote,
                resolver_acuerdo=lambda _: fila_sap_real(oc_cliente=None),
            )

    def test_backend_acepta_acuerdo_433_con_oc_autoritativa(self):
        lote = lote_acuerdo_real(
            numero='433',
            abs_id='4138',
            oc_enviada='OC-MANIPULADA',
        )

        resultado = validar_lote_borradores_sbh(
            lote,
            resolver_acuerdo=lambda _: fila_sap_real(
                numero='433',
                abs_id='4138',
                oc_cliente='4511573329',
            ),
        )

        self.assertEqual(resultado['cantidad_borradores'], 1)
        self.assertEqual(
            lote[0]['asignaciones_planificacion_sap'][0]['oc_cliente'],
            '4511573329',
        )

    @patch('apps.home.views.consultar_acuerdos_despacho')
    @patch('apps.home.views.empresa_es_terramar_chile', return_value=False)
    @patch('apps.home.views.Verificar_empresa', return_value=2)
    def test_post_manipulado_sin_oc_reconsulta_sap_y_responde_400(
        self,
        _empresa,
        _terramar,
        consultar,
    ):
        lote = lote_acuerdo_real(oc_enviada='OC-INVENTADA')
        consultar.return_value = {
            'ok': True,
            'resultados': [fila_sap_real(oc_cliente=None)],
        }
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {'citaciones_json': json.dumps(lote)},
        )
        request.user = SimpleNamespace(is_authenticated=True)

        response = views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            payload['message'],
            'El acuerdo SAP 423 no posee una OC asociada y no puede utilizarse para planificar.',
        )
        consultar.assert_called_once_with('423', 2)

    def test_validador_general_conserva_lectura_historica_sin_oc(self):
        asignacion_historica = asignacion('4031', '27.5', linea='1')
        asignacion_historica['contrato_sap'] = '423'
        asignacion_historica['oc_cliente'] = ''
        data = {
            'cliente': 'C001',
            'cliente_codigo': 'C001',
            'asignaciones_sap': [asignacion_historica],
        }

        resultado = validar_asignaciones_sap_planificadas(data)

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['oc_cliente'], '')
