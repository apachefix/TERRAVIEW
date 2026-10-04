import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CAMION_PATIO_NO_PLANIFICADO, CITACION, CITACION_ITEM,
    DETALLE_SECUENCIA, EMPRESA, ETAPA, ITEM, PLANIFICACION, SECUENCIA,
)


class AgregarCitacionesMultiflujoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            username='planificador_multiflujo', password='test-pass', email='test@example.invalid',
        )
        cls.empresas = {}
        cls.planes = {}
        fecha = timezone.make_aware(datetime(2026, 10, 5, 9, 0))
        casos = (
            (2, 'RECEPCION', 'RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD', 'recepcion_sbh'),
            (2, 'RECEPCION', 'RECEPCION_TRANSFERENCIA_SBH', 'transferencia_sbh'),
            (2, 'DESPACHO', 'EST_SBH_CLIENTE', 'despacho_sbh'),
            (1, 'RECEPCION', 'RECEPCION_TERRAMAR', 'recepcion_terramar'),
            (1, 'DESPACHO', 'DESPACHO_TERRAMAR', 'despacho_terramar'),
        )
        for empresa_id, tipo, codigo, formulario in casos:
            empresa = cls.empresas.get(empresa_id)
            if empresa is None:
                empresa = EMPRESA.objects.create(
                    id=empresa_id, EP_CRAZONSOCIAL=(
                        'TERRAMAR CHILE' if empresa_id == 1 else 'ACEITES SBH'
                    ),
                    EP_CRUT=f'{empresa_id}-9', EP_CBASEDATOS='test',
                    EP_CUSUARIOSBD='test', EP_CPORT='5432',
                )
                cls.empresas[empresa_id] = empresa
            calendario = CALENDARIO.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, CA_NDIA=5, CA_NMES=10,
                CA_NANO=2026, CA_NCANTIDADCUPOS=16,
            )
            plan = PLANIFICACION.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, CAL_NID=calendario,
                PL_CTIPOCUPO=tipo, PL_FFECHAINICIO=fecha,
                PL_NCANTIDADCUPOS=16, PL_NCANTIDADSOBRECUPO=30,
            )
            secuencia = SECUENCIA.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, SE_CTIPO=tipo,
                SE_CCODIGO=codigo, SE_CNOMBRE=codigo, SE_BHABILITADO=True,
            )
            etapa = ETAPA.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, ET_CTIPO='OPERACION',
                ET_CCODIGO=f'ET_{codigo}', ET_CNOMBRE='Etapa 0',
                ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
            )
            DETALLE_SECUENCIA.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, SC_NID=secuencia,
                ET_NID=etapa, SE_NPASO=1, SE_BHABILITADO=True,
            )
            citacion = CITACION.objects.create(
                EP_NID=empresa, US_NID=cls.usuario, PL_NID=plan,
                SC_NID=secuencia, CI_FFECHACITACION=fecha,
                CI_NCUPO=1, CI_CTIPO=tipo, CI_CESTADO='PENDIENTE',
            )
            item = ITEM.objects.create(
                EP_NID=empresa, IT_CCODIGO=f'ITEM-{formulario}',
                IT_CNOMBRE=f'Producto {formulario}',
            )
            CITACION_ITEM.objects.create(EP_NID=empresa, CI_NID=citacion, IT_NID=item)
            cls.planes[formulario] = plan
        if not ITEM.objects.filter(pk=26).exists():
            ITEM.objects.create(
                id=26, EP_NID=cls.empresas[1], IT_CCODIGO='ITEM-26',
                IT_CNOMBRE='Producto base',
            )

    def setUp(self):
        self.factory = RequestFactory()

    def test_dispatcher_distingue_cinco_formularios_y_rechaza_mezcla(self):
        for formulario, plan in self.planes.items():
            with self.subTest(formulario=formulario):
                self.assertEqual(views.resolver_formulario_etapa0(plan), formulario)
        plan = self.planes['transferencia_sbh']
        otra = self.planes['recepcion_sbh']
        CITACION.objects.create(
            EP_NID=plan.EP_NID, US_NID=self.usuario, PL_NID=plan,
            SC_NID=CITACION.objects.get(PL_NID=otra).SC_NID,
            CI_FFECHACITACION=plan.PL_FFECHAINICIO,
            CI_NCUPO=2, CI_CTIPO='RECEPCION', CI_CESTADO='PENDIENTE',
        )
        self.assertEqual(views.resolver_formulario_etapa0(plan), '')

    def test_carpeta_renderiza_solo_su_modal_sin_legacy(self):
        modales = {
            'recepcion_sbh': 'ModalCrearCitacion',
            'transferencia_sbh': 'ModalCrearRecepcionTransferencia',
            'despacho_sbh': 'ModalCrearDespacho',
            'recepcion_terramar': 'ModalCrearRecepcionTerramar',
            'despacho_terramar': 'ModalCrearDespachoTerramar',
        }
        for formulario, plan in self.planes.items():
            with self.subTest(formulario=formulario):
                request = self.factory.get(f'/pla_listone/{plan.pk}', {'_empresa_id': plan.EP_NID_id})
                request.user = self.usuario
                with patch.object(views, 'Verificar_empresa', return_value=plan.EP_NID_id), \
                     patch.object(views, 'obtener_clientes_aceite', return_value=[]):
                    response = views.PLANIFICACION_LISTONE(request, plan.pk)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn('Agregar citaciones', html)
                self.assertIn(f'id="{modales[formulario]}"', html)
                self.assertNotIn('<iframe', html)
                for otro, modal_id in modales.items():
                    if otro != formulario:
                        self.assertNotIn(f'id="{modal_id}"', html)
                detalle = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
                for legacy in ('Importar citaciones', 'Asignar cupos masivo',
                               'Descargar reporte', 'ModalAgregarCitacionesVenta',
                               'ModalAgregarCitacionesCompra'):
                    self.assertFalse(legacy in detalle, legacy)
                if formulario == 'despacho_sbh':
                    self.assertIn('id="despacho_sap_busqueda"', html)
                    self.assertIn('id="despacho_transportado_por"', html)
                    self.assertEqual(html.count('id="ModalCrearDespacho"'), 1)

    def test_post_rechaza_empresa_tipo_flujo_y_modal_ajenos(self):
        plan = self.planes['transferencia_sbh']
        data = {
            'planificacion_existente_id': str(plan.pk),
            'flujo': 'INGRESO_MERCADERIA',
            'citaciones_json': json.dumps([{
                'fecha_llegada': '2026-10-05', 'tipo_operacion': 'RECEPCION',
                'secuencia_id': CITACION.objects.get(PL_NID=plan).SC_NID_id,
            }]),
        }
        request = self.factory.post('/crear-planificacion-citacion/', data)
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            self.assertEqual(views.CREAR_PLANIFICACION_CITACION(request).status_code, 400)
        data['flujo'] = 'TRANSFERENCIA'
        data['citaciones_json'] = json.dumps([{
            'fecha_llegada': '2026-10-05', 'tipo_operacion': 'DESPACHO',
        }])
        request = self.factory.post('/crear-planificacion-citacion/', data)
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            self.assertEqual(views.CREAR_PLANIFICACION_CITACION(request).status_code, 400)
        with patch.object(views, 'Verificar_empresa', return_value=1):
            self.assertEqual(views.CREAR_PLANIFICACION_CITACION(request).status_code, 404)
        self.assertEqual(CAMION_PATIO_NO_PLANIFICADO.objects.count(), 0)

    def test_no_permite_otra_secuencia_aunque_comparta_modal(self):
        plan = self.planes['despacho_sbh']
        otra = SECUENCIA.objects.create(
            EP_NID=plan.EP_NID, US_NID=self.usuario, SE_CTIPO='DESPACHO',
            SE_CCODIGO='BODEGA_EXTERNA_CLIENTE', SE_CNOMBRE='Bodega externa',
            SE_BHABILITADO=True,
        )
        response = self._agregar(plan, {
            'fecha_llegada': '2026-10-05', 'tipo_operacion': 'DESPACHO',
            'secuencia_id': otra.pk,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('secuencia', json.loads(response.content)['message'].lower())
        self.assertEqual(CITACION.objects.filter(PL_NID=plan).count(), 1)

    def test_producto_despacho_esta_despues_de_numero_y_no_colisiona_no_planificado(self):
        detalle = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        despacho = detalle.split('<table id="basic-btn"', 1)[1].split('</table>', 1)[0]
        cabecera = despacho.split('</thead>', 1)[0]
        self.assertLess(cabecera.index('<th>NUMERO CITACIÓN</th>'),
                        cabecera.index('<th>PRODUCTO</th>'))
        self.assertLess(cabecera.index('<th>PRODUCTO</th>'),
                        cabecera.index('<th>FECHA CITACION</th>'))
        fila = despacho.split('<td>{{ object.0 }}</td>', 1)[1]
        self.assertLess(fila.index('<td>{{ object.15 }}</td>'),
                        fila.index("<td>{{ object.1|date:'d/m/Y' }}</td>"))
        self.assertIn('id="ModalCrearDespachoNoPlanificado"', detalle)
        self.assertIn('id="np_form_crear_despacho"', detalle)
        self.assertNotIn('id="ModalCrearDespacho"', detalle)

    def _agregar(self, plan, item, extra=None):
        data = {
            'planificacion_existente_id': str(plan.pk),
            'citaciones_json': json.dumps([item]),
            'cantidad_sobrecupo': '999',
            **(extra or {}),
        }
        request = self.factory.post('/crear-planificacion-citacion/', data)
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=plan.EP_NID_id), \
             patch.object(views, 'guardar_detalle_operacional_citacion'), \
             patch.object(views, 'guardar_detalle_despacho_citacion'), \
             patch.object(views, 'guardar_detalle_despacho_terramar_citacion'), \
             patch.object(views, 'guardar_cliente_planificacion_despacho_terramar'), \
             patch.object(views, 'guardar_datos_planificacion_operacional'), \
             patch.object(views, 'obtener_snapshot_recepcion_transferencia_sap', return_value={
                 'codigo_sap': '950066', 'insumo': 'Aceite de alga',
                 'codigo_propietario': 'VITAPRO', 'propiedad_producto': 'VITAPRO',
                 'stock_disponible': 487.26, 'unidad': 'KG',
             }), \
             patch.object(views, 'consultar_clientes_sap', return_value={
                 'clientes': [{'cardcode': 'C001', 'cardname': 'Cliente prueba'}],
             }):
            response = views.CREAR_PLANIFICACION_CITACION(request)
        return response

    def test_agregar_transferencia_en_misma_carpeta(self):
        plan = self.planes['transferencia_sbh']
        secuencia = CITACION.objects.get(PL_NID=plan).SC_NID
        antes = (PLANIFICACION.objects.count(),
                 CAMION_PATIO_NO_PLANIFICADO.objects.count())
        item = {
            'flujo': 'TRANSFERENCIA', 'tipo_operacion': 'RECEPCION',
            'fecha_llegada': '2026-10-05', 'estanque_origen': 'PROSEG10',
            'codigo': '950066', 'codigo_sap': '950066',
            'insumo': 'Aceite de alga', 'cantidad_camion': 1,
            'almacen_destino': 'SBH', 'estanque_destino': 'TK18',
        }
        response = self._agregar(plan, item, {'flujo': 'TRANSFERENCIA'})
        self.assertEqual(response.status_code, 200, response.content)
        resultado = json.loads(response.content)
        self.assertTrue(resultado['success'], response.content)
        nueva = CITACION.objects.get(pk=resultado['citaciones'][0])
        self.assertEqual((nueva.PL_NID_id, nueva.EP_NID_id, nueva.SC_NID_id),
                         (plan.pk, 2, secuencia.pk))
        self.assertFalse(nueva.CI_BSOBRECUPO)
        self.assertEqual((PLANIFICACION.objects.count(),
                          CAMION_PATIO_NO_PLANIFICADO.objects.count()), antes)
        plan.refresh_from_db()
        self.assertEqual((plan.PL_NCANTIDADCUPOS, plan.PL_NCANTIDADSOBRECUPO), (16, 30))

    def test_agregar_despacho_sbh_en_misma_carpeta(self):
        plan = self.planes['despacho_sbh']
        secuencia = CITACION.objects.get(PL_NID=plan).SC_NID
        antes = (PLANIFICACION.objects.count(),
                 CITACION.objects.filter(PL_NID=plan).count(),
                 CAMION_PATIO_NO_PLANIFICADO.objects.count())
        item = {
            'tipo_operacion': 'DESPACHO', 'fecha_llegada': '2026-10-05',
            'secuencia_id': secuencia.pk, 'cliente': 'C001',
            'cliente_codigo': 'C001', 'cliente_nombre': 'Cliente prueba',
            'insumo': 'Aceite', 'codigo': '950066',
            'pedido': 'OC-1', 'condicion_entrega': 'Cliente',
            'empresa_transporte': 'Transportes cliente', 'conductor': 'Juan prueba',
            'patente': 'ABCD12', 'salida_documento': 'Guía de despacho',
            'tipo_carga': 'Cisterna',
        }
        response = self._agregar(plan, item)
        self.assertEqual(response.status_code, 200, response.content)
        resultado = json.loads(response.content)
        self.assertTrue(resultado['success'], response.content)
        nueva = CITACION.objects.get(pk=resultado['citaciones'][0])
        self.assertEqual((nueva.PL_NID_id, nueva.EP_NID_id, nueva.SC_NID_id),
                         (plan.pk, 2, secuencia.pk))
        self.assertFalse(nueva.CI_BSOBRECUPO)
        self.assertEqual((PLANIFICACION.objects.count(),
                          CITACION.objects.filter(PL_NID=plan).count(),
                          CAMION_PATIO_NO_PLANIFICADO.objects.count()),
                         (antes[0], antes[1] + 1, antes[2]))
        plan.refresh_from_db()
        self.assertEqual((plan.PL_NCANTIDADCUPOS, plan.PL_NCANTIDADSOBRECUPO), (16, 30))

    def test_agregar_despacho_terramar_en_misma_carpeta(self):
        plan = self.planes['despacho_terramar']
        secuencia = CITACION.objects.get(PL_NID=plan).SC_NID
        producto = ITEM.objects.filter(EP_NID_id=1).first()
        antes = (PLANIFICACION.objects.count(), CAMION_PATIO_NO_PLANIFICADO.objects.count())
        item = {
            'tipo_operacion': 'DESPACHO', 'despacho_terramar': True,
            'fecha_llegada': '2026-10-05', 'hora_citacion': '09:00',
            'secuencia_id': secuencia.pk, 'cliente': 'C001',
            'cliente_codigo': 'C001', 'cliente_nombre': 'Cliente prueba',
            'destino': 'Puerto', 'contenedor_crt': 'CRT-1',
            'item_id': producto.pk, 'insumo': producto.IT_CNOMBRE,
            'bodega': 'Bodega', 'tipo_camion': 'Plano', 'pallet': 'SI',
            'relleno': 'NO', 'transporte_a_cargo': 'Cliente',
            'condicion_entrega': 'Cliente', 'empresa_transporte': 'Transportes cliente',
            'conductor': 'Juan prueba', 'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678', 'patente': 'ABCD12',
            'salida_documento': 'Guía de despacho',
        }
        response = self._agregar(plan, item)
        self.assertEqual(response.status_code, 200, response.content)
        resultado = json.loads(response.content)
        self.assertTrue(resultado['success'], response.content)
        nueva = CITACION.objects.get(pk=resultado['citaciones'][0])
        self.assertEqual((nueva.PL_NID_id, nueva.EP_NID_id, nueva.SC_NID_id),
                         (plan.pk, 1, secuencia.pk))
        self.assertEqual((PLANIFICACION.objects.count(),
                          CAMION_PATIO_NO_PLANIFICADO.objects.count()), antes)
        plan.refresh_from_db()
        self.assertEqual((plan.PL_NCANTIDADCUPOS, plan.PL_NCANTIDADSOBRECUPO), (16, 30))
