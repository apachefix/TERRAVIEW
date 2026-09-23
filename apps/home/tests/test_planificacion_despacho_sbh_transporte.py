from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.home.models import CONDUCTOR, EMPRESA, SOCIONEGOCIO
from apps.home.views import validar_transportes_borradores_despacho_sbh


class TransportePorBorradorSbhTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sbh = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-9',
            EP_CBASEDATOS='empresa_2', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='1-9',
            EP_CBASEDATOS='empresa_1', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.usuario = get_user_model().objects.create_user('transportes_borrador_sbh')
        cls.transportistas = [
            SOCIONEGOCIO.objects.create(
                EP_NID=cls.sbh, SN_CCODIGO_SAP=f'TR-{indice}',
                SN_CRAZONSOCIAL=nombre, SN_CRUT=f'7600000{indice}-{indice}',
                SN_CTIPO='S', SN_BHABILITADO=True,
            )
            for indice, nombre in enumerate(
                ('TRANSPORTES BRETTI', 'PASCAL', 'OCEAN TRUCK'), start=1
            )
        ]
        cls.transportista_ep1 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.terramar, SN_CCODIGO_SAP='TR-EP1',
            SN_CRAZONSOCIAL='TRANSPORTE EP1', SN_CRUT='76111111-1',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transportista_ficticio = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CCODIGO_SAP='FICTICIO',
            SN_CRAZONSOCIAL='TRANSPORTE FICTICIO', SN_CRUT='55555555-5',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.conductor = CONDUCTOR.objects.create(
            EP_NID=cls.terramar, SN_NID=cls.transportista_ep1, US_NID=cls.usuario,
            CON_CNOMBRE='Ana', CON_CAPELLIDO='Global', CON_CRUT='12345678-5',
            CON_BHABILITADO=True,
        )

    def setUp(self):
        direccion = {
            'cliente_codigo': 'C001', 'direccion_codigo': 'OSORNO',
            'tipo_direccion': 'S', 'ciudad': 'Osorno',
        }
        parches = (
            patch('apps.home.views.consultar_direcciones_despacho_sap', return_value=[direccion]),
            patch('apps.home.views.resolver_destino_despacho_sap', return_value={'comuna_id': 1}),
            patch('apps.home.views.validar_alternativa_transporte_sbh', side_effect=self._alternativa_valida),
        )
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def _alternativa_valida(self, **datos):
        transportista = SOCIONEGOCIO.objects.get(pk=datos['transportista_id'])
        return SimpleNamespace(
            SN_NID=transportista,
            RUT_NID_id=int(datos['ruta_id']),
            id=int(datos['tarifa_id']),
            TAR_NVALOR=Decimal('1000'),
        ), ''

    def item(self, condicion='Terramar', transportista=None, conductor=None, patente=''):
        return {
            'cliente_codigo': 'C001',
            'direccion_despacho_sap_codigo': 'OSORNO',
            'condicion_entrega': condicion,
            'transportado_por': condicion,
            'inf_24hrs': condicion,
            'empresa_transporte': transportista.SN_CRAZONSOCIAL if transportista else '',
            'empresa_transporte_id': str(transportista.id) if transportista else '',
            'conductor': f'{conductor.CON_CNOMBRE} {conductor.CON_CAPELLIDO}' if conductor else '',
            'conductor_id': str(conductor.id) if conductor else '',
            'patente': patente,
            'ruta_id': '1',
            'tarifa_id': '1',
            'salida_documento': 'FE',
        }

    def test_tres_transportistas_independientes_y_cliente_son_validos(self):
        borradores = [
            self.item(transportista=self.transportistas[0]),
            self.item(transportista=self.transportistas[1], conductor=self.conductor),
            self.item(transportista=self.transportistas[2], patente='abcd12'),
            self.item(condicion='Cliente'),
        ]
        validar_transportes_borradores_despacho_sbh(borradores, self.sbh.id)
        self.assertEqual(
            [item['empresa_transporte'] for item in borradores],
            ['TRANSPORTES BRETTI', 'PASCAL', 'OCEAN TRUCK', ''],
        )
        self.assertEqual(borradores[0]['conductor'], '')
        self.assertEqual(borradores[0]['patente'], '')
        self.assertEqual(borradores[1]['conductor'], 'Ana Global')
        self.assertEqual(borradores[1]['patente'], '')
        self.assertEqual(borradores[2]['conductor'], '')
        self.assertEqual(borradores[2]['patente'], 'ABCD12')

    def test_terramar_sin_empresa_es_invalido(self):
        with self.assertRaisesRegex(ValueError, 'Borrador 1.*Empresa Transporte'):
            validar_transportes_borradores_despacho_sbh([self.item()], self.sbh.id)

    def test_cliente_sin_datos_de_transporte_es_valido(self):
        item = self.item(condicion='Cliente')
        validar_transportes_borradores_despacho_sbh([item], self.sbh.id)
        self.assertEqual(item['empresa_transporte_id'], '')
        self.assertEqual(item['conductor_id'], '')
        self.assertTrue(item['ingreso_manual_transporte'])

    def test_transportista_ep1_no_es_valido_para_sbh(self):
        with self.assertRaisesRegex(ValueError, 'no pertenece a SBH'):
            validar_transportes_borradores_despacho_sbh(
                [self.item(transportista=self.transportista_ep1)], self.sbh.id
            )

    def test_transportista_ficticio_no_es_valido(self):
        with self.assertRaisesRegex(ValueError, 'no pertenece a SBH'):
            validar_transportes_borradores_despacho_sbh(
                [self.item(transportista=self.transportista_ficticio)], self.sbh.id
            )

    def test_conductor_global_no_reasigna_transportista_ni_maestro(self):
        sn_original = self.conductor.SN_NID_id
        item = self.item(transportista=self.transportistas[1], conductor=self.conductor)
        validar_transportes_borradores_despacho_sbh([item], self.sbh.id)
        self.conductor.refresh_from_db()
        self.assertEqual(item['empresa_transporte_id'], str(self.transportistas[1].id))
        self.assertEqual(item['conductor_id'], str(self.conductor.id))
        self.assertEqual(self.conductor.SN_NID_id, sn_original)

    def test_texto_de_conductor_sin_id_maestro_se_rechaza_para_terramar(self):
        item = self.item(transportista=self.transportistas[0])
        item['conductor'] = 'Inventado'
        with self.assertRaisesRegex(ValueError, 'maestro'):
            validar_transportes_borradores_despacho_sbh([item], self.sbh.id)

    def test_salida_documento_se_valida_por_cada_borrador(self):
        items = [self.item(condicion='Cliente'), self.item(condicion='Cliente')]
        items[1]['salida_documento'] = ''
        with self.assertRaisesRegex(ValueError, 'Borrador 2.*Salida de documento'):
            validar_transportes_borradores_despacho_sbh(items, self.sbh.id)


class InterfazTransportePorBorradorSbhTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fuente = Path(
            'apps/templates/home/PLANIFICACION/pla_addone.html'
        ).read_text(encoding='utf-8')

    def test_editor_expone_campos_y_acciones_por_borrador(self):
        for texto in (
            'ModalEditarTransporteBorradorSbh', 'borrador_sbh_condicion',
            'borrador_sbh_empresa_transporte', 'borrador_sbh_conductor',
            'borrador_sbh_patente', 'abrirEditorTransporteBorradorSbh',
        ):
            self.assertIn(texto, self.fuente)

    def test_redistribucion_preserva_configuraciones_individuales(self):
        self.assertIn(
            'const configuraciones = citacionesTemporales.map(configuracionTransporteBorradorSbh);',
            self.fuente,
        )
        self.assertIn(
            'Object.assign(borrador, configuraciones[index] || configuraciones[0]);',
            self.fuente,
        )

    def test_selector_global_de_conductores_no_envia_transportista(self):
        inicio = self.fuente.index("$('#borrador_sbh_conductor').select2")
        fin = self.fuente.index("function abrirEditorTransporteBorradorSbh", inicio)
        bloque = self.fuente[inicio:fin]
        self.assertNotIn('transportista_id', bloque)
        self.assertNotIn('transportista:', bloque)

    def test_validacion_frontend_solo_exige_empresa_para_terramar(self):
        inicio = self.fuente.index('function validarTransportesBorradoresSbhFrontend')
        fin = self.fuente.index('function guardarPlanificacionConCitaciones', inicio)
        bloque = self.fuente[inicio:fin]
        self.assertIn('empresa_transporte_id', bloque)
        self.assertNotIn('item.conductor', bloque)
        self.assertNotIn('item.patente', bloque)
    def test_bloques_multicamion_estan_en_el_modal_etapa_cero(self):
        inicio = self.fuente.index('id="ModalCrearDespacho"')
        fin = self.fuente.index('</form>', inicio)
        modal = self.fuente[inicio:fin]
        self.assertIn('despacho_camiones_planificados_seccion', modal)
        self.assertIn('despacho_camiones_planificados', modal)
        self.assertIn('agregarCamionPlanificadoSbh', modal)

    def test_recalculo_preserva_primeros_bloques_y_elimina_sobrantes(self):
        inicio = self.fuente.index('function sincronizarCamionesPlanificadosSbh')
        fin = self.fuente.index('function actualizarModoCamionPlanificadoSbh', inicio)
        bloque = self.fuente[inicio:fin]
        self.assertIn('camionesPlanificadosDespachoSbh.pop()', bloque)
        self.assertIn('camionesPlanificadosDespachoSbh.push(configuracionInicialCamionSbh())', bloque)
        self.assertNotIn('camionesPlanificadosDespachoSbh = []', bloque)

    def test_agregar_y_eliminar_no_modifican_total_planificado(self):
        inicio = self.fuente.index('function agregarCamionPlanificadoSbh')
        fin = self.fuente.index('function validarCamionesPlanificadosSbhModal', inicio)
        bloque = self.fuente[inicio:fin]
        self.assertIn('camionesPlanificadosDespachoSbh.push', bloque)
        self.assertIn('camionesPlanificadosDespachoSbh.splice', bloque)
        self.assertNotIn('total_planificado_despacho =', bloque)
        self.assertIn('capacidad estimada de los camiones', self.fuente)

    def test_ibc_es_fijo_y_no_existe_input_configurable(self):
        self.assertNotIn('id="despacho_ibc_por_camion"', self.fuente)
        self.assertIn("if (formato === 'IBC') return 18 * ESCALA_TONELADAS_SBH", self.fuente)
        self.assertIn('20 IBC por cami&oacute;n', self.fuente)
        self.assertIn("citacion.tipo_carga === 'IBC' ? 20 : null", self.fuente)

    def test_crear_aplica_configuracion_individual_a_cada_borrador(self):
        inicio = self.fuente.index('function confirmarBorradoresDespachoSbh')
        fin = self.fuente.index('function configuracionTransporteBorradorSbh', inicio)
        bloque = self.fuente[inicio:fin]
        self.assertIn('camionesPlanificadosDespachoSbh.length', bloque)
        self.assertIn('camionesPlanificadosDespachoSbh[index]', bloque)
        self.assertIn('Object.assign(borrador, configuracionTransporteBorradorSbh', bloque)

    def test_selector_de_conductor_del_modal_usa_universo_global(self):
        inicio = self.fuente.index('function renderizarCamionesPlanificadosSbh')
        fin = self.fuente.index('function agregarCamionPlanificadoSbh', inicio)
        bloque = self.fuente[inicio:fin]
        self.assertIn('ajax_conductores_ingreso_camion', bloque)
        self.assertNotIn('transportista_id', bloque)
        self.assertNotIn('transportista:', bloque)
    def test_implementacion_multicamion_no_duplica_declaraciones(self):
        for token in (
            'let camionesPlanificadosDespachoSbh = [];',
            'let firmaCalculoCamionesDespachoSbh =',
            'function configuracionInicialCamionSbh()',
            'function sincronizarCamionesPlanificadosSbh(',
            'function agregarCamionPlanificadoSbh()',
        ):
            self.assertEqual(self.fuente.count(token), 1, token)
