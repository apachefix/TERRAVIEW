import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.home import views
from apps.home.models import (
    CITACION,
    CITACION_DESPACHO_DETALLE,
    COMUNA,
    CONDUCTOR,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    ITEM,
    PLANIFICACION,
    PROVINCIA,
    REGION,
    RUTA,
    SECUENCIA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
    USERS_EMPRESA,
    USERS_EXTENSION,
)


class CargaDespachoTerramarNormalizacionTests(SimpleTestCase):
    def datos(self, **cambios):
        datos = {
            'tipo_camion': 'Plano',
            'pallet': 'NO',
            'relleno': 'NO',
            'contenedor_crt': 'CRT-1',
            'peso_1': '12500,5',
            'maxis_1': '2',
            'patente_rampla': '  ra   1234  ',
            'contenedor_2_crt': 'VALOR-OBSOLETO',
            'peso_2': '999',
            'maxis_2': '9',
        }
        datos.update(cambios)
        return datos

    def test_sin_relleno_limpia_carga_secundaria(self):
        datos = views.normalizar_carga_despacho_terramar_etapa0(self.datos())

        self.assertEqual(datos['peso_1'], '12500.5')
        self.assertEqual(datos['maxis_1'], '2')
        self.assertEqual(datos['patente_rampla'], 'RA 1234')
        self.assertEqual(datos['contenedor_2_crt'], '')
        self.assertEqual(datos['peso_2'], '')
        self.assertEqual(datos['maxis_2'], '')

    def test_patente_rampla_vacia_es_valida(self):
        datos = views.normalizar_carga_despacho_terramar_etapa0(
            self.datos(patente_rampla=None)
        )

        self.assertEqual(datos['patente_rampla'], '')
    def test_con_relleno_exige_los_tres_campos_secundarios(self):
        with self.assertRaisesMessage(
            ValueError, 'Para carga con relleno debe completar: peso 2.'
        ):
            views.normalizar_carga_despacho_terramar_etapa0(
                self.datos(
                    relleno='SI',
                    contenedor_2_crt='CRT-2',
                    peso_2='',
                    maxis_2='3',
                )
            )

    def test_restringe_tipo_camion_al_catalogo_del_modal(self):
        with self.assertRaisesMessage(
            ValueError, 'Tipo de camión inválido para Despacho Terramar.'
        ):
            views.normalizar_carga_despacho_terramar_etapa0(
                self.datos(tipo_camion='Rampla')
            )


class ModalDespachoTerramarEtapa0TemplateTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = (
            Path(__file__).resolve().parents[3]
            / 'apps'
            / 'templates'
            / 'home'
            / 'PLANIFICACION'
            / 'pla_addone.html'
        ).read_text(encoding='utf-8')

    def test_campos_y_catalogos_estan_en_modal_exclusivo(self):
        modal_inicio = self.template.index('<div class="modal fade" id="ModalCrearDespachoTerramar"')
        inicio = self.template.rfind('{% if es_despacho_terramar %}', 0, modal_inicio)
        fin = self.template.index('{% endif %}', modal_inicio)
        modal = self.template[inicio:fin]

        for texto in (
            'Contenedor 1 / CRT',
            'despacho_terramar_peso_1',
            'despacho_terramar_maxis_1',
            'despacho_terramar_patente_rampla',
            'Secuencia Tarifa',
            'despacho_terramar_contenedor_2_crt',
            'despacho_terramar_peso_2',
            'despacho_terramar_maxis_2',
        ):
            self.assertIn(texto, modal)
        self.assertIn('<option value="Plano">Plano</option>', modal)
        self.assertIn('<option value="Cortina">Cortina</option>', modal)
        self.assertNotIn('<option value="Rampla">', modal)
        self.assertIn(
            '<label>Patente Rampla</label><input class="form-control text-uppercase" '
            'id="despacho_terramar_patente_rampla">',
            modal,
        )
        self.assertNotIn('required-label">Patente Rampla', modal)
        self.assertNotIn('id="despacho_terramar_patente_rampla" required', modal)
        self.assertIn(
            '{% if not es_despacho_terramar %}<div class="modal fade modal-despacho-etapa0"',
            self.template,
        )

    def test_relleno_controla_visibilidad_required_y_limpieza(self):
        self.assertIn(
            "const conRelleno = $('#despacho_terramar_relleno').val() === 'SI';",
            self.template,
        )
        self.assertIn("bloque.toggleClass('d-none', !conRelleno);", self.template)
        self.assertIn("campos.prop('required', conRelleno);", self.template)
        self.assertIn("if (!conRelleno) campos.val('');", self.template)


class PlanificacionDespachoTerramarEtapa0Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='planificador_despacho_terramar',
            password='test-pass',
        )
        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='1-9',
            EP_CBASEDATOS='terramar_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        USERS_EXTENSION.objects.create(
            US_NID=cls.usuario,
            UX_IS_PLANIFICADOR=True,
            UX_IS_TERRAMAR=True,
        )
        USERS_EMPRESA.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa)

        region = REGION.objects.create(RG_CNOMBRE='Biobio', RG_CCODIGO='08')
        provincia = PROVINCIA.objects.create(
            RG_NID=region,
            PV_CNOMBRE='Concepcion',
            PV_CCODIGO='081',
        )
        comuna_origen = COMUNA.objects.create(
            PV_NID=provincia,
            COM_CNOMBRE='Coronel',
            COM_CCODIGO='08101',
        )
        comuna_destino = COMUNA.objects.create(
            PV_NID=provincia,
            COM_CNOMBRE='Talcahuano',
            COM_CCODIGO='08110',
        )
        cls.ruta = RUTA.objects.create(
            EP_NID=cls.empresa,
            RG_NID_INICIO=region,
            PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna_origen,
            RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia,
            COM_NID_TERMINO=comuna_destino,
            RUT_NTIEMPOMAXIMOENTREGA=1,
            RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='Coronel -> Talcahuano',
            RUT_CCODIGO='R-DESP-TER',
            RUT_BHABILITADO=True,
        )
        cls.transportista = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='TRANS-TEST',
            SN_CRAZONSOCIAL='TRANSPORTISTA TEST',
            SN_CRUT='77-7',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        cls.cliente = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='CLI-TEST',
            SN_CRAZONSOCIAL='CLIENTE TEST',
            SN_CRUT='66-6',
            SN_CTIPO='C',
            SN_BHABILITADO=True,
        )
        cls.conductor = CONDUCTOR.objects.create(
            EP_NID=cls.empresa,
            SN_NID=cls.transportista,
            US_NID=cls.usuario,
            CON_CNOMBRE='Ana',
            CON_CAPELLIDO='Prueba',
            CON_CRUT='11-1',
            CON_CTELEFONO='912345678',
            CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_BHABILITADO=True,
        )
        cls.tarifa = TARIFA_GLOBAL.objects.create(
            EP_NID=cls.empresa,
            RUT_NID=cls.ruta,
            US_NID=cls.usuario,
            MODIFICADO_POR=cls.usuario,
            SN_NID=cls.transportista,
            TAR_NVALOR=123456,
            TAR_NVALORPREVIO=123456,
            TAR_CNOMBRETARIFA='Secuencia tarifa test',
            TAR_CTIPOTARIFA='FLETE',
            TAR_CDIVISA='CLP',
            TAR_BHABILITADO=True,
        )
        ITEM.objects.create(
            id=26,
            EP_NID=cls.empresa,
            IT_CCODIGO='ITEM-26',
            IT_CNOMBRE='Producto despacho',
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='DESPACHO',
            SE_CCODIGO='DESPACHO_TERRAMAR',
            SE_CNOMBRE='Despacho Terramar',
            SE_BHABILITADO=True,
        )
        etapa = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='DESP_TER_PLANIFICACION',
            ET_CNOMBRE='Planificacion',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=etapa,
            SE_NPASO=1,
            SE_BHABILITADO=True,
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def item(self, **cambios):
        datos = {
            'despacho_terramar': True,
            'tipo_operacion': 'DESPACHO',
            'fecha_llegada': '2026-10-15',
            'hora_citacion': '08:30',
            'cliente': self.cliente.SN_CCODIGO_SAP,
            'cliente_codigo': self.cliente.SN_CCODIGO_SAP,
            'cliente_nombre': self.cliente.SN_CRAZONSOCIAL,
            'destino': 'Puerto destino',
            'contenedor_crt': 'CRT-001',
            'peso_1': '12500.50000',
            'maxis_1': '2',
            'patente_rampla': 'ra 1234',
            'item_id': 26,
            'codigo': 'ITEM-26',
            'insumo': 'Producto despacho',
            'bodega': 'BOD-01',
            'tipo_camion': 'Plano',
            'tipo_carga': 'Plano',
            'pallet': 'NO',
            'relleno': 'NO',
            'contenedor_2_crt': '',
            'peso_2': '',
            'maxis_2': '',
            'transporte_a_cargo': 'Terramar',
            'condicion_entrega': 'Terramar',
            'inf_24hrs': 'Terramar',
            'empresa_transporte': self.transportista.SN_CRAZONSOCIAL,
            'empresa_transporte_id': str(self.transportista.id),
            'ruta_id': str(self.ruta.id),
            'tarifa_id': str(self.tarifa.id),
            'conductor': 'Ana Prueba',
            'conductor_id': str(self.conductor.id),
            'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678',
            'patente': 'AA1111',
            'secuencia_id': self.secuencia.id,
            'secuencia_nombre': self.secuencia.SE_CNOMBRE,
            'secuencia_codigo': self.secuencia.SE_CCODIGO,
            'salida_documento': 'Guía de despacho',
            'observacion': '',
        }
        datos.update(cambios)
        return datos

    def payload(self, item):
        return {
            'citaciones_json': json.dumps([item]),
            'es_sobrecupo': 'No',
            'cantidad_sobrecupo': '0',
        }

    def crear(self, item):
        with (
            patch.object(
                views,
                'consultar_clientes_sap',
                return_value={'clientes': [{
                    'cardcode': self.cliente.SN_CCODIGO_SAP,
                    'cardname': self.cliente.SN_CRAZONSOCIAL,
                }]},
            ),
            patch.object(views, 'guardar_detalle_operacional_citacion'),
            patch.object(views, 'guardar_cliente_planificacion_despacho_terramar'),
            patch.object(views, 'guardar_datos_planificacion_operacional'),
        ):
            return self.client.post(
                reverse('crear_planificacion_citacion'),
                self.payload(item),
            )

    def test_sin_relleno_persiste_primarios_limpia_secundarios_y_tarifa(self):
        response = self.crear(self.item(
            contenedor_2_crt='NO-DEBE-GUARDARSE',
            peso_2='500',
            maxis_2='8',
        ))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        citacion = CITACION.objects.get(pk=response.json()['citaciones'][0])
        detalle = CITACION_DESPACHO_DETALLE.objects.get(CI_NID=citacion)
        self.assertEqual(detalle.CDD_CCONTENEDOR_CRT, 'CRT-001')
        self.assertEqual(detalle.CDD_NPESO_1, Decimal('12500.50000'))
        self.assertEqual(detalle.CDD_NMAXIS_1, 2)
        self.assertEqual(detalle.CDD_CPATENTE_RAMPLA, 'RA 1234')
        self.assertFalse(detalle.CDD_BRELLENO)
        self.assertIsNone(detalle.CDD_CCONTENEDOR_2_CRT)
        self.assertIsNone(detalle.CDD_NPESO_2)
        self.assertIsNone(detalle.CDD_NMAXIS_2)
        self.assertEqual(citacion.RUT_NID_id, self.ruta.id)
        self.assertEqual(citacion.TAR_NID_id, self.tarifa.id)
        self.assertEqual(citacion.CI_NVALORTARIFA, self.tarifa.TAR_NVALOR)

    def test_patente_rampla_vacia_crea_y_persiste_null(self):
        response = self.crear(self.item(patente_rampla=''))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        detalle = CITACION_DESPACHO_DETALLE.objects.get(
            CI_NID_id=response.json()['citaciones'][0]
        )
        self.assertIsNone(detalle.CDD_CPATENTE_RAMPLA)
    def test_con_relleno_persiste_segunda_carga(self):
        response = self.crear(self.item(
            relleno='SI',
            contenedor_2_crt='CRT-002',
            peso_2='8000.25',
            maxis_2='3',
        ))

        self.assertEqual(response.status_code, 200, response.content)
        detalle = CITACION_DESPACHO_DETALLE.objects.get(
            CI_NID_id=response.json()['citaciones'][0]
        )
        self.assertTrue(detalle.CDD_BRELLENO)
        self.assertEqual(detalle.CDD_CCONTENEDOR_2_CRT, 'CRT-002')
        self.assertEqual(detalle.CDD_NPESO_2, Decimal('8000.25000'))
        self.assertEqual(detalle.CDD_NMAXIS_2, 3)

    def test_relleno_sin_datos_secundarios_rechaza_sin_crear_registros(self):
        response = self.crear(self.item(
            relleno='SI',
            contenedor_2_crt='CRT-002',
            peso_2='',
            maxis_2='3',
        ))

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('peso 2', response.json()['message'])
        self.assertFalse(PLANIFICACION.objects.exists())
        self.assertFalse(CITACION.objects.exists())

    def test_tipo_camion_fuera_del_catalogo_rechaza_sin_crear_registros(self):
        response = self.crear(self.item(tipo_camion='Rampla'))

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('Tipo de camión inválido', response.json()['message'])
        self.assertFalse(PLANIFICACION.objects.exists())
        self.assertFalse(CITACION.objects.exists())