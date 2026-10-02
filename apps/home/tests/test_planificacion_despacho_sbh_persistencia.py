import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import (
    CAMION, CITACION, CITACION_DESPACHO_ASIGNACION_SAP, COMUNA,
    CONDUCTOR, EMPRESA, ITEM, PLANIFICACION, PROVINCIA, REGION, RUTA,
    SECUENCIA, SOCIONEGOCIO, TARIFA_GLOBAL,
)


class PersistenciaPlanificacionDespachoSbhTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='2-9',
            EP_CBASEDATOS='empresa_2',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        cls.usuario = get_user_model().objects.create_user('planificador_sbh_etapa0')
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='DESPACHO',
            SE_CCODIGO='DESPACHO_SBH_TEST',
            SE_CNOMBRE='Despacho SBH test',
            SE_BHABILITADO=True,
        )
        ITEM.objects.update_or_create(
            id=26,
            defaults={
                'EP_NID': cls.empresa,
                'IT_CCODIGO': 'ITEM-1',
                'IT_CNOMBRE': 'Aceite',
            },
        )
        cls.transportistas = [
            SOCIONEGOCIO.objects.create(
                EP_NID=cls.empresa, SN_CCODIGO_SAP=f'TR-{indice}',
                SN_CRAZONSOCIAL=nombre, SN_CRUT=f'7700000{indice}-{indice}',
                SN_CTIPO='S', SN_BHABILITADO=True,
            )
            for indice, nombre in enumerate(('BRETTI', 'PASCAL', 'OCEAN TRUCK'), start=1)
        ]
        region = REGION.objects.create(RG_CNOMBRE='Biobío', RG_CCODIGO='VIII')
        provincia = PROVINCIA.objects.create(
            RG_NID=region, PV_CNOMBRE='Prueba', PV_CCODIGO='PRUEBA'
        )
        coronel = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Coronel', COM_CCODIGO='COR'
        )
        osorno = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Osorno', COM_CCODIGO='OSO'
        )
        cls.ruta = RUTA.objects.create(
            EP_NID=cls.empresa,
            RG_NID_INICIO=region, PV_NID_INICIO=provincia, COM_NID_INICIO=coronel,
            RG_NID_TERMINO=region, PV_NID_TERMINO=provincia, COM_NID_TERMINO=osorno,
            RUT_NTIEMPOMAXIMOENTREGA=1, RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='CORONEL -> OSORNO', RUT_CCODIGO='COR-OSO',
            RUT_BHABILITADO=True,
        )
        cls.tarifas = [
            TARIFA_GLOBAL.objects.create(
                EP_NID=cls.empresa, RUT_NID=cls.ruta, SN_NID=transportista,
                TAR_NVALOR=100000 + indice,
                TAR_CNOMBRETARIFA=f'Tarifa {indice}', TAR_CTIPOTARIFA='FLETE',
                TAR_CDIVISA='CLP', TAR_BHABILITADO=True,
            )
            for indice, transportista in enumerate(cls.transportistas, start=1)
        ]
        cls.conductor = CONDUCTOR.objects.create(
            EP_NID=cls.empresa, US_NID=cls.usuario,
            CON_CNOMBRE='Conductor', CON_CAPELLIDO='Dos', CON_CRUT='11111111-1',
            CON_BHABILITADO=True,
        )

    def asignacion(self, cantidad='25.00000'):
        return {
            'sap_abs_id': '10',
            'contrato_sap': 'AC-10',
            'linea_acuerdo_sap': '0',
            'codigo_producto_sap': 'ITEM-1',
            'nombre_producto_sap': 'Aceite',
            'cliente_codigo': 'C001',
            'cliente_nombre': 'Cliente Uno',
            'oc_cliente': 'OC-1',
            'cantidad_planificada_sap': '100.00000',
            'cantidad_consumida_sap': '0.00000',
            'saldo_contrato_sap': '100.00000',
            'unidad_medida': 'TON',
            'cantidad_intentada_despachar': cantidad,
            'estado': 'PLANIFICADA',
        }

    def borradores(self, cantidad=4):
        resultado = []
        for indice in range(cantidad):
            resultado.append({
                'despacho_sbh_etapa0': True,
                'distribucion_borradores': 'EQUILIBRADA',
                'numero_borrador': indice + 1,
                'cliente': 'C001',
                'cliente_codigo': 'C001',
                'direccion_despacho_sap_codigo': 'OSORNO',
                'direccion_despacho_sap_texto': 'OSORNO',
                'cliente_nombre': 'Cliente Uno',
                'inf_24hrs': 'Cliente',
                'condicion_entrega': 'Cliente',
                'transportado_por': 'Cliente',
                'fecha_llegada': '2026-09-10',
                'fecha_despacho': '2026-09-10',
                'fecha_llegada_destino': '2026-09-11',
                'hora_llegada_planta': '10:00',
                'hora_llegada_destino': '12:00',
                'orden_carga': '1',
                'tipo_operacion': 'DESPACHO',
                'tipo_operacion_texto': 'Despacho',
                'secuencia_id': str(self.secuencia.id),
                'secuencia_nombre': self.secuencia.SE_CNOMBRE,
                'tipo_carga': 'Cisterna',
                'tipo_carga_texto': 'Cisterna',
                'destino': 'Planta destino',
                'estanque_destino': 'SBH',
                'estanque_destino_texto': 'Planta destino',
                'salida_documento': 'FE',
                'total_planificado_despacho': '100.00000',
                'capacidad_planificacion': '27.50000',
                'cantidad_estimada': '25.00000',
                'cantidad_intentada_despachar': '25.00000',
                'asignaciones_planificacion_sap': [self.asignacion('100.00000')],
                'asignaciones_sap': [self.asignacion()],
                'codigo': 'ITEM-1',
                'insumo': 'Aceite',
                'pedido': 'OC-1',
                'proveedor': '',
                'proveedor_nombre': '',
                'empresa_transporte': '',
                'conductor': '',
                'patente': '',
                'bodega': 'SBH',
            })
        return resultado

    def request(self, borradores):
        request = RequestFactory().post('/crear-planificacion-citacion/', {
            'citaciones_json': json.dumps(borradores),
            'cantidad_repetir': len(borradores),
            'es_sobrecupo': 'No',
            'cantidad_sobrecupo': '0',
        })
        request.user = self.usuario
        request.session = {}
        return request

    def parches_comunes(self):
        return (
            patch('apps.home.views.Verificar_empresa', return_value=2),
            patch('apps.home.views.validar_lote_borradores_sbh'),
            patch('apps.home.views.guardar_detalle_operacional_citacion'),
            patch('apps.home.views.guardar_datos_planificacion_operacional'),
            patch('apps.home.views.consultar_direcciones_despacho_sap', return_value=[{
                'cliente_codigo': 'C001', 'direccion_codigo': 'OSORNO',
                'tipo_direccion': 'S', 'ciudad': 'Osorno',
            }]),
        )

    def test_crea_exactamente_una_citacion_y_transporte_por_borrador(self):
        borradores = self.borradores()
        borradores[0].update({
            'condicion_entrega': 'Terramar', 'transportado_por': 'Terramar',
            'inf_24hrs': 'Terramar', 'empresa_transporte': 'BRETTI',
            'empresa_transporte_id': str(self.transportistas[0].id),
            'ruta_id': str(self.ruta.id), 'tarifa_id': str(self.tarifas[0].id),
        })
        borradores[1].update({
            'condicion_entrega': 'Terramar', 'transportado_por': 'Terramar',
            'inf_24hrs': 'Terramar', 'empresa_transporte': 'PASCAL',
            'empresa_transporte_id': str(self.transportistas[1].id),
            'ruta_id': str(self.ruta.id), 'tarifa_id': str(self.tarifas[1].id),
            'conductor': 'Conductor Dos', 'conductor_id': str(self.conductor.id),
        })
        borradores[2].update({
            'condicion_entrega': 'Terramar', 'transportado_por': 'Terramar',
            'inf_24hrs': 'Terramar', 'empresa_transporte': 'OCEAN TRUCK',
            'empresa_transporte_id': str(self.transportistas[2].id),
            'ruta_id': str(self.ruta.id), 'tarifa_id': str(self.tarifas[2].id),
            'patente': 'ABCD12',
        })
        camiones_antes = CAMION.objects.count()
        conductores_antes = CONDUCTOR.objects.count()
        parches = self.parches_comunes()
        with parches[0], parches[1], parches[2], parches[3], parches[4]:
            response = views.CREAR_PLANIFICACION_CITACION(self.request(borradores))

        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['citaciones']), 4)
        planificacion = PLANIFICACION.objects.get(pk=data['planificacion_id'])
        self.assertEqual(planificacion.EP_NID_id, 2)
        self.assertEqual(planificacion.PL_CTIPOCUPO, 'DESPACHO')
        citaciones = list(CITACION.objects.filter(PL_NID=planificacion).order_by('id'))
        self.assertEqual(len(citaciones), 4)
        self.assertEqual(
            [citacion.PRO_NID_id for citacion in citaciones],
            [self.transportistas[0].id, self.transportistas[1].id, self.transportistas[2].id, None],
        )
        self.assertEqual(
            [citacion.CON_NID_id for citacion in citaciones],
            [None, self.conductor.id, None, None],
        )
        self.assertEqual([citacion.RUT_NID_id for citacion in citaciones[:3]], [self.ruta.id] * 3)
        self.assertEqual(
            [citacion.TAR_NID_id for citacion in citaciones[:3]], [tarifa.id for tarifa in self.tarifas]
        )
        self.assertEqual(
            [citacion.CI_NVALORTARIFA for citacion in citaciones[:3]],
            [tarifa.TAR_NVALOR for tarifa in self.tarifas],
        )
        detalles = [citacion.detalle_despacho for citacion in citaciones]
        self.assertEqual(
            [detalle.CDD_CDESTINO for detalle in detalles],
            ['OSORNO', 'OSORNO', 'OSORNO', 'OSORNO'],
        )
        self.assertEqual(
            [detalle.CDD_CEMPRESA_TRANSPORTE for detalle in detalles],
            ['BRETTI', 'PASCAL', 'OCEAN TRUCK', ''],
        )
        self.assertEqual([detalle.CDD_CCONDICION_ENTREGA for detalle in detalles], ['Terramar', 'Terramar', 'Terramar', 'Cliente'])
        self.assertEqual(
            [detalle.CDD_FFECHA_LLEGADA_DESTINO.isoformat() for detalle in detalles],
            ['2026-09-11'] * 4,
        )
        self.assertEqual(
            [detalle.CDD_FHORA_LLEGADA_DESTINO.strftime('%H:%M') for detalle in detalles],
            ['12:00'] * 4,
        )
        self.assertEqual([detalle.CDD_CCONDUCTOR for detalle in detalles], ['', 'Conductor Dos', '', ''])
        self.assertEqual([detalle.CDD_CPATENTE for detalle in detalles], ['', '', 'ABCD12', ''])
        self.assertEqual(CITACION_DESPACHO_ASIGNACION_SAP.objects.filter(CDD_NID__CI_NID__PL_NID=planificacion).count(), 4)
        self.assertEqual(CONDUCTOR.objects.count(), conductores_antes)
        self.assertEqual(CAMION.objects.count(), camiones_antes)

    def test_nueva_planificacion_sin_fecha_llegada_destino_se_rechaza(self):
        borradores = self.borradores()
        for borrador in borradores:
            borrador.pop('fecha_llegada_destino')
        planes_antes = PLANIFICACION.objects.count()
        citaciones_antes = CITACION.objects.count()
        parches = self.parches_comunes()

        with parches[0], parches[1], parches[2], parches[3], parches[4]:
            response = views.CREAR_PLANIFICACION_CITACION(
                self.request(borradores)
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'fecha llegada a destino',
            json.loads(response.content)['message'],
        )
        self.assertEqual(PLANIFICACION.objects.count(), planes_antes)
        self.assertEqual(CITACION.objects.count(), citaciones_antes)

    def test_fallo_en_tercera_citacion_revierte_lote_completo(self):
        planes_antes = PLANIFICACION.objects.count()
        citaciones_antes = CITACION.objects.count()
        parches = self.parches_comunes()
        with parches[0], parches[1], parches[2], parches[3], parches[4], patch(
            'apps.home.views.guardar_detalle_despacho_citacion',
            side_effect=[None, None, RuntimeError('fallo controlado')],
        ):
            response = views.CREAR_PLANIFICACION_CITACION(self.request(self.borradores()))

        self.assertFalse(json.loads(response.content)['success'])
        self.assertEqual(PLANIFICACION.objects.count(), planes_antes)
        self.assertEqual(CITACION.objects.count(), citaciones_antes)
