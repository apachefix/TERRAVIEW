import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.despacho_sbh_transporte import (
    obtener_alternativas_transporte_sbh,
    resolver_destino_despacho_sap,
    validar_alternativa_transporte_sbh,
)
from apps.home.models import (
    COMUNA,
    CONDUCTOR,
    EMPRESA,
    PROVINCIA,
    REGION,
    RUTA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
)


class TransporteInteligenteDespachoSbhTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sbh = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-9',
            EP_CBASEDATOS='sbh', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='1-9',
            EP_CBASEDATOS='terramar', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.usuario = get_user_model().objects.create_user('planificador_transporte_sbh')
        region = REGION.objects.create(RG_CNOMBRE='Biobío', RG_CCODIGO='VIII')
        provincia = PROVINCIA.objects.create(
            RG_NID=region, PV_CNOMBRE='Prueba', PV_CCODIGO='PRUEBA'
        )
        cls.coronel = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Coronel', COM_CCODIGO='COR'
        )
        cls.osorno = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Osorno', COM_CCODIGO='OSO'
        )
        cls.calbuco = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Calbuco', COM_CCODIGO='CAL'
        )
        cls.llanquihue = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Llanquihue', COM_CCODIGO='LLA'
        )

        def ruta(pk, nombre, origen, destino, empresa=None, habilitada=True):
            return RUTA.objects.create(
                id=pk, EP_NID=empresa or cls.sbh,
                RG_NID_INICIO=region, PV_NID_INICIO=provincia, COM_NID_INICIO=origen,
                RG_NID_TERMINO=region, PV_NID_TERMINO=provincia, COM_NID_TERMINO=destino,
                RUT_NTIEMPOMAXIMOENTREGA=Decimal('1'),
                RUT_NTIEMPOESTADIAPLANTA=Decimal('1'),
                RUT_CNOMBRE=nombre, RUT_CCODIGO=f'R-{pk}',
                RUT_BHABILITADO=habilitada,
            )

        cls.ruta_69 = ruta(69, 'CORONEL -> OSORNO', cls.coronel, cls.osorno)
        cls.ruta_81 = ruta(81, 'CORONEL -> OSORNO (ACEITES)', cls.coronel, cls.osorno)
        cls.ruta_73 = ruta(73, 'LLANQUIHUE -> OSORNO', cls.llanquihue, cls.osorno)
        cls.ruta_71 = ruta(71, 'CORONEL -> CALBUCO (PARGUA)', cls.coronel, cls.calbuco)
        cls.ruta_99 = ruta(99, 'CORONEL -> PARGUA (ACEITES)', cls.coronel, cls.calbuco)
        cls.ruta_calbuco = ruta(100, 'CORONEL -> CALBUCO', cls.coronel, cls.calbuco)
        cls.ruta_coronel = ruta(101, 'CORONEL LOCAL', cls.coronel, cls.coronel)
        cls.ruta_deshabilitada = ruta(
            102, 'CORONEL -> OSORNO INACTIVA', cls.coronel, cls.osorno, habilitada=False
        )
        cls.ruta_empresa_1 = ruta(
            103, 'CORONEL -> OSORNO TERRAMAR', cls.coronel, cls.osorno,
            empresa=cls.terramar,
        )

        cls.transportista_1 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CRAZONSOCIAL='SPHAGNUM', SN_CRUT='76000001-1',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transportista_2 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CRAZONSOCIAL='POLO SUR', SN_CRUT='76000002-2',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transportista_inhabilitado = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CRAZONSOCIAL='INACTIVO', SN_CRUT='76000003-3',
            SN_CTIPO='S', SN_BHABILITADO=False,
        )
        cls.transportista_empresa_1 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.terramar, SN_CRAZONSOCIAL='TERRAMAR TRANS', SN_CRUT='76000004-4',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )

        def tarifa(pk, ruta_obj, transportista, valor, habilitada=True, empresa=None):
            return TARIFA_GLOBAL.objects.create(
                id=pk, EP_NID=empresa or cls.sbh, RUT_NID=ruta_obj,
                SN_NID=transportista, TAR_NVALOR=Decimal(str(valor)),
                TAR_CNOMBRETARIFA=f'Tarifa {pk}', TAR_CTIPOTARIFA='FLETE',
                TAR_CDIVISA='CLP', TAR_BHABILITADO=habilitada,
            )

        cls.tarifa_69 = tarifa(900, cls.ruta_69, cls.transportista_1, 546840)
        cls.tarifa_81 = tarifa(901, cls.ruta_81, cls.transportista_2, 579400)
        cls.tarifa_duplicada = tarifa(902, cls.ruta_69, cls.transportista_1, 600000)
        tarifa(903, cls.ruta_69, cls.transportista_2, 500000, habilitada=False)
        tarifa(904, cls.ruta_deshabilitada, cls.transportista_2, 400000)
        tarifa(905, cls.ruta_81, cls.transportista_inhabilitado, 300000)
        tarifa(906, cls.ruta_73, cls.transportista_2, 200000)
        tarifa(907, cls.ruta_71, cls.transportista_1, 689920)
        tarifa(908, cls.ruta_99, cls.transportista_2, 731450)
        tarifa(909, cls.ruta_calbuco, cls.transportista_1, 100000)
        tarifa(910, cls.ruta_coronel, cls.transportista_1, 150000)
        tarifa(911, cls.ruta_empresa_1, cls.transportista_empresa_1, 1, empresa=cls.terramar)
        tarifa(1080, cls.ruta_81, cls.transportista_1, 26880)
        tarifa(1112, cls.ruta_81, cls.transportista_1, 27015)
        tarifa(1134, cls.ruta_81, cls.transportista_1, 25000)

        cls.conductor_otro_transportista = CONDUCTOR.objects.create(
            EP_NID=cls.terramar, SN_NID=cls.transportista_empresa_1, US_NID=cls.usuario,
            CON_CNOMBRE='Conductor', CON_CAPELLIDO='Global', CON_CRUT='11111111-1',
            CON_BHABILITADO=True,
        )

    @staticmethod
    def direccion(codigo, ciudad=''):
        return {
            'cliente_codigo': 'C001', 'direccion_codigo': codigo,
            'tipo_direccion': 'S', 'calle': '', 'ciudad': ciudad,
        }

    def test_osorno_solo_considera_origen_coronel_y_ordena_sin_deduplicar(self):
        destino = resolver_destino_despacho_sap(self.direccion('OSORNO'))
        alternativas = obtener_alternativas_transporte_sbh(destino)
        self.assertEqual([item['tarifa_id'] for item in alternativas], [900, 901, 902])
        self.assertEqual({item['ruta_id'] for item in alternativas}, {69, 81})
        self.assertNotIn(73, {item['ruta_id'] for item in alternativas})

    def test_pargua_resuelve_calbuco_y_restringe_rutas_al_alias(self):
        destino = resolver_destino_despacho_sap(self.direccion('PARGUA'))
        self.assertEqual(destino['comuna_id'], self.calbuco.id)
        self.assertEqual(destino['alias_ruta'], 'PARGUA')
        alternativas = obtener_alternativas_transporte_sbh(destino)
        self.assertEqual({item['ruta_id'] for item in alternativas}, {71, 99})
        self.assertNotIn(100, {item['ruta_id'] for item in alternativas})

    def test_coronel_usa_inicio_y_termino_coronel(self):
        destino = resolver_destino_despacho_sap(self.direccion('CORONEL'))
        alternativas = obtener_alternativas_transporte_sbh(destino)
        self.assertEqual([item['ruta_id'] for item in alternativas], [101])

    def test_excluye_anomalias_inactivos_y_empresa_uno(self):
        destino = resolver_destino_despacho_sap(self.direccion('OSORNO'))
        ids = {item['tarifa_id'] for item in obtener_alternativas_transporte_sbh(destino)}
        self.assertTrue({1080, 1112, 1134, 903, 904, 905, 906, 911}.isdisjoint(ids))

    def test_revalidacion_rechaza_mezcla_tarifa_ruta_transportista(self):
        destino = resolver_destino_despacho_sap(self.direccion('OSORNO'))
        tarifa, error = validar_alternativa_transporte_sbh(
            destino_resuelto=destino,
            transportista_id=self.transportista_1.id,
            ruta_id=self.ruta_81.id,
            tarifa_id=self.tarifa_69.id,
        )
        self.assertIsNone(tarifa)
        self.assertIn('no corresponde', error)

    def test_conductor_habilitado_sigue_independiente_del_transportista(self):
        item = {
            'cliente_codigo': 'C001',
            'direccion_despacho_sap_codigo': 'OSORNO',
            'condicion_entrega': 'Terramar',
            'empresa_transporte_id': str(self.transportista_1.id),
            'ruta_id': str(self.ruta_69.id),
            'tarifa_id': str(self.tarifa_69.id),
            'conductor_id': str(self.conductor_otro_transportista.id),
            'salida_documento': 'FE',
        }
        resolver = lambda cliente, empresa_id=None: [self.direccion('OSORNO')]
        views.validar_transportes_borradores_despacho_sbh(
            [item], self.sbh.id, resolver_direcciones=resolver
        )
        self.assertEqual(item['conductor_id'], str(self.conductor_otro_transportista.id))
        self.assertEqual(item['empresa_transporte_id'], str(self.transportista_1.id))
        self.assertEqual(item['ruta_id'], str(self.ruta_69.id))
        self.assertEqual(item['tarifa_id'], str(self.tarifa_69.id))

    def test_endpoint_no_autoselecciona_y_devuelve_unidades_reales(self):
        request = RequestFactory().get('/api/despacho-sbh/alternativas-transporte/', {
            'cliente_codigo': 'C001', 'direccion_codigo': 'OSORNO',
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views._usuario_puede_consultar_transporte_despacho_sbh', return_value=True,
        ), patch(
            'apps.home.views.consultar_direcciones_despacho_sap',
            return_value=[self.direccion('OSORNO')],
        ):
            response = views.API_DESPACHO_SBH_ALTERNATIVAS_TRANSPORTE(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['tarifa_id'] for item in payload['alternativas']], [900, 901, 902])
        self.assertNotIn('selected', payload)
        self.assertEqual(
            set(payload['alternativas'][0]),
            {
                'transportista_id', 'transportista_nombre', 'transportista_rut',
                'ruta_id', 'ruta_nombre', 'origen', 'destino', 'tarifa_id',
                'tarifa_valor', 'tarifa_moneda',
            },
        )
