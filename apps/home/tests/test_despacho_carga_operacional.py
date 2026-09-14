import copy
import json
from datetime import date, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.utils import timezone
from requests import Response
from requests.exceptions import HTTPError

from apps.home import despacho_carga as service
from apps.home import sap_despacho_envio as envio
from apps.home import sap_despacho_carga as sap_catalogo
from apps.home.models import (
    EMPRESA, CALENDARIO, SECUENCIA, PLANIFICACION, CITACION, ETAPA, ETAPA_LOG, DETALLE_SECUENCIA,
    CITACION_DESPACHO_DETALLE, CITACION_DESPACHO_ASIGNACION_SAP,
    CITACION_DESPACHO_CARGA, CITACION_DESPACHO_DRAFT_SAP,
)


class CargaOperacionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('carga_test')
        cls.empresa = EMPRESA.objects.create(pk=2, EP_CRAZONSOCIAL='SBH', EP_CRUT='22-2', EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0')
        calendario = CALENDARIO.objects.create(US_NID=cls.user, EP_NID=cls.empresa, CA_CNOMBRE='Carga',
            CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18), CA_NDIA=1, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=20)
        secuencia = SECUENCIA.objects.create(US_NID=cls.user, EP_NID=cls.empresa, SE_CTIPO='DESPACHO', SE_CCODIGO='CARGA', SE_CNOMBRE='Carga', SE_BHABILITADO=True)
        plan = PLANIFICACION.objects.create(US_NID=cls.user, EP_NID=cls.empresa, CAL_NID=calendario,
            PL_CTIPOCUPO='DESPACHO', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=20)
        cls.citacion = CITACION.objects.create(EP_NID=cls.empresa, US_NID=cls.user, PL_NID=plan, SC_NID=secuencia,
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO='DESPACHO', CI_CESTADO='PENDIENTE')
        cls.detalle = CITACION_DESPACHO_DETALLE.objects.create(CI_NID=cls.citacion, EP_NID=cls.empresa, US_NID=cls.user,
            CDD_NCANTIDAD_INTENTADA_DESPACHAR=100, CDD_CSALIDA_DOCUMENTO='GD',
            CDD_CSAP_ABS_ID='4092', CDD_CSAP_NUMERO_ACUERDO='429', CDD_CSAP_LINEA_ACUERDO='1',
            CDD_CSAP_CODIGO_PRODUCTO='980057', CDD_CSAP_CLIENTE_CODIGO='C001', CDD_CSAP_CLIENTE_NOMBRE='Cliente')
        for orden, abs_id, numero, item in [(1, '4092', '429', '980057'), (2, '3584', '381', '800040')]:
            CITACION_DESPACHO_ASIGNACION_SAP.objects.create(CDD_NID=cls.detalle, EP_NID=cls.empresa,
                CDAS_CSAP_ABS_ID=abs_id, CDAS_CSAP_NUMERO_ACUERDO=numero, CDAS_CSAP_LINEA_ACUERDO='1',
                CDAS_CSAP_CODIGO_PRODUCTO=item, CDAS_CSAP_CLIENTE_CODIGO='C001', CDAS_CSAP_CLIENTE_NOMBRE='Cliente',
                CDAS_NCANTIDAD_INTENTADA_DESPACHAR=100, CDAS_NORDEN=orden)

    def setUp(self):
        self.productos = {4092: [self.producto(4092, '980057'), self.producto(4092, 'P2', '2')],
                          3584: [self.producto(3584, '800040')]}
        self.p1 = patch.object(service, 'consultar_productos_acuerdo', side_effect=lambda key: copy.deepcopy(self.productos[key]))
        self.p2 = patch.object(service, 'consultar_stock_producto', side_effect=self.stock)
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)

    def producto(self, abs_id, item, linea='1'):
        return {'sap_abs_id': abs_id, 'numero_acuerdo': '429' if abs_id == 4092 else '381',
            'cliente_codigo': 'C001', 'cliente_nombre': 'Cliente', 'oc_cliente': 'OC1',
            'linea_acuerdo': linea, 'item_code': item, 'item_name': 'Producto ' + item, 'unidad_medida': 'Toneladas', 'saldo': 999}

    def stock(self, item):
        return [{'warehouse_code': whs, 'item_code': item, 'batch_number': batch, 'stock': qty, 'fecha_vencimiento': fecha}
            for whs in ['TK01', 'TK02']
            for batch, qty, fecha in [('A', '20', '2099-01-01'), ('B', '50', '2099-02-01'), ('C', '100', '2099-03-01'), ('D', '50', None), ('E', '50', None)]]

    def test_catalogo_stock_incluye_tk04_y_no_filtra_estado_del_lote(self):
        filas = [
            {'warehouse_code': 'TK04', 'item_code': '980057', 'batch_number': 'LOTE-PT-980057-6-01', 'stock': 70, 'fecha_vencimiento': None},
            {'warehouse_code': 'TK04', 'item_code': '980057', 'batch_number': 'LOTE-PT-980057-7-01', 'stock': 270, 'fecha_vencimiento': None},
            {'warehouse_code': 'TKMX01', 'item_code': '980057', 'batch_number': 'LOTE-PT-980057-4-01', 'stock': 80.25, 'fecha_vencimiento': None},
        ]
        with patch.object(sap_catalogo, '_schema', return_value='SBO_TEST'), patch.object(
            sap_catalogo, '_rows', return_value=filas
        ) as ejecutar:
            resultado = sap_catalogo.consultar_stock_producto('980057')
        sql, parametros = ejecutar.call_args.args
        self.assertNotIn('Status', sql)
        self.assertIn('Quantity', sql)
        self.assertIn('Inactive', sql)
        self.assertEqual(parametros, ['980057'])
        self.assertEqual(resultado, filas)
        self.assertEqual({fila['warehouse_code'] for fila in resultado}, {'TK04', 'TKMX01'})
        self.assertEqual(
            [fila['batch_number'] for fila in resultado if fila['warehouse_code'] == 'TK04'],
            ['LOTE-PT-980057-6-01', 'LOTE-PT-980057-7-01'],
        )

    def bloque(self, item='980057', whs='TK01', cantidad='60', lotes=None, linea='1'):
        lotes = lotes if lotes is not None else [('A', '20'), ('B', '40')]
        return {'warehouse_code': whs, 'item_code': item, 'linea_acuerdo': linea, 'cantidad': cantidad,
            'lotes': [{'batch_number': batch, 'cantidad': qty} for batch, qty in lotes]}

    def data(self):
        return {'version': 0, 'zona_carga': 'Línea 1', 'cantidad_total': '100', 'acuerdos': [
            {'sap_abs_id': 4092, 'cantidad': '60', 'estanques': [self.bloque()]},
            {'sap_abs_id': 3584, 'cantidad': '40', 'estanques': [self.bloque('800040', cantidad='40', lotes=[('A', '20'), ('B', '20')])]}]}

    def validar(self, data=None):
        return service.validar_configuracion(self.citacion, data or self.data())

    def test_dos_acuerdos_cantidad_operacional_no_suma_intenciones_duplicadas(self):
        state = service.estado_carga(self.citacion)
        self.assertEqual(state['cantidad_total'], '100.00000')
        self.assertEqual([a['cantidad'] for a in state['acuerdos']], ['', ''])
        self.assertEqual(self.validar()['cantidad_total'], Decimal(100))

    def test_un_acuerdo_un_lote(self):
        self.detalle.asignaciones_sap.filter(CDAS_CSAP_ABS_ID='3584').delete()
        data = self.data(); data['acuerdos'] = data['acuerdos'][:1]
        data['cantidad_total'] = data['acuerdos'][0]['cantidad'] = '10'
        data['acuerdos'][0]['estanques'] = [self.bloque(cantidad='10', lotes=[('A', '10')])]
        self.assertEqual(len(self.validar(data)['acuerdos']), 1)

    def test_dos_estanques_con_productos_distintos(self):
        data = self.data()
        data['acuerdos'][0]['estanques'] = [self.bloque(cantidad='20', lotes=[('A','20')]),
            self.bloque('P2', 'TK02', '40', [('A','20'),('B','20')], '2')]
        self.assertEqual(len(self.validar(data)['acuerdos'][0]['estanques']), 2)

    def test_mismo_producto_en_dos_estanques_permitido(self):
        data = self.data()
        data['acuerdos'][0]['estanques'] = [self.bloque(cantidad='20', lotes=[('A','20')]), self.bloque(whs='TK02', cantidad='40', lotes=[('A','20'),('B','20')])]
        self.validar(data)

    def test_mismo_estanque_producto_repetido_rechazado(self):
        data = self.data(); data['acuerdos'][0]['estanques'] *= 2
        with self.assertRaisesRegex(service.CargaInvalida, 'repita'):
            self.validar(data)

    def test_tres_lotes_fefo_secuencial(self):
        data = self.data(); data['cantidad_total'] = '140'
        data['acuerdos'][0]['cantidad'] = '100'
        data['acuerdos'][0]['estanques'] = [self.bloque(cantidad='100', lotes=[('A','20'),('B','50'),('C','30')])]
        self.assertEqual(len(self.validar(data)['acuerdos'][0]['estanques'][0]['lotes']), 3)

    def test_fefo_no_permite_saltar_lote_anterior(self):
        data = self.data(); data['acuerdos'][0]['estanques'][0]['lotes'] = [{'batch_number':'C','cantidad':'60'}]
        with self.assertRaisesRegex(service.CargaInvalida, 'FEFO'):
            self.validar(data)

    def test_sin_fecha_seleccion_manual(self):
        rows = [r for r in self.stock('P') if r['warehouse_code'] == 'TK01' and r['fecha_vencimiento'] is None]
        service.validar_fefo(rows, {'E': Decimal(30)})

    def test_mezcla_no_permite_sin_fecha_antes_de_agotar_fechados(self):
        rows = [r for r in self.stock('P') if r['warehouse_code'] == 'TK01']
        with self.assertRaisesRegex(service.CargaInvalida, 'FEFO'):
            service.validar_fefo(rows, {'D': Decimal(10)})
        service.validar_fefo(rows, {'A':Decimal(20),'B':Decimal(50),'C':Decimal(100),'D':Decimal(10)})

    def test_empate_fecha_no_impone_orden_artificial(self):
        rows = [{'batch_number': b, 'stock': '10', 'fecha_vencimiento': '2099-01-01'} for b in ['A','B']]
        service.validar_fefo(rows, {'B': Decimal(5)})

    def test_lote_vencido_rechazado(self):
        with self.assertRaisesRegex(service.CargaInvalida, 'vencido'):
            service.validar_fefo([{'batch_number':'A','stock':'10','fecha_vencimiento':'2020-01-01'}], {'A':Decimal(1)}, date(2026,1,1))

    def test_stock_excedido_rechazado(self):
        data = self.data(); data['acuerdos'][0]['estanques'][0]['lotes'] = [{'batch_number':'A','cantidad':'60'}]
        with self.assertRaisesRegex(service.CargaInvalida, 'stock'):
            self.validar(data)

    def test_producto_ajeno_rechazado(self):
        data = self.data(); data['acuerdos'][0]['estanques'][0]['item_code'] = 'NO-PERTENECE'
        with self.assertRaisesRegex(service.CargaInvalida, 'producto/línea'):
            self.validar(data)

    def test_warehouse_otra_empresa_rechazado(self):
        data = self.data(); data['acuerdos'][0]['estanques'][0]['warehouse_code'] = 'TERRAMAR'
        with self.assertRaisesRegex(service.CargaInvalida, 'Estanque'):
            self.validar(data)

    def test_acuerdo_ajeno_rechazado(self):
        data = self.data(); data['acuerdos'][0]['sap_abs_id'] = 111
        with self.assertRaisesRegex(service.CargaInvalida, 'ajeno'):
            self.validar(data)

    def test_cliente_cambiado_en_sap_rechazado(self):
        self.productos[4092][0]['cliente_codigo'] = 'OTRO'
        with self.assertRaisesRegex(service.CargaInvalida, 'cliente'):
            self.validar()

    def test_metadata_inyectada_ignorada(self):
        data = self.data(); lote = data['acuerdos'][0]['estanques'][0]['lotes'][0]
        lote.update(stock_snapshot=99999, fecha_vencimiento='2100-01-01')
        real = self.validar(data)['acuerdos'][0]['estanques'][0]['lotes'][0]
        self.assertEqual(real['stock_snapshot'], Decimal(20))
        self.assertEqual(real['fecha_vencimiento'], date(2099,1,1))

    def test_sumas_en_todos_los_niveles(self):
        for nivel in ['cantidad_total', 'acuerdo', 'estanque']:
            data = self.data()
            if nivel == 'cantidad_total': data[nivel] = '99'
            elif nivel == 'acuerdo': data['acuerdos'][0]['cantidad'] = '59'
            else: data['acuerdos'][0]['estanques'][0]['cantidad'] = '59'
            with self.subTest(nivel=nivel), self.assertRaises(service.CargaInvalida): self.validar(data)

    def test_cantidades_no_finitas_y_precision_rechazadas(self):
        for valor in ['NaN', 'Infinity', '-1', '0', '1.000001', None, [], '999999999999999']:
            with self.subTest(valor=valor), self.assertRaises(service.CargaInvalida): service.cantidad(valor)

    def test_payload_n_acuerdos_absid_y_reglas_documentales(self):
        config = self.validar()
        for tipo, codigo, reserva in [('GD','15',None),('FE','13','tNO'),('FE_RESERVA','13','tYES')]:
            self.detalle.CDD_CSALIDA_DOCUMENTO = tipo; self.detalle.save()
            payloads = service.preparar_payloads(self.citacion, config)
            self.assertEqual(set(payloads), {4092,3584})
            for abs_id, payload in payloads.items():
                self.assertEqual(payload['DocObjectCode'], codigo)
                if reserva is None: self.assertNotIn('ReserveInvoice', payload)
                else: self.assertEqual(payload['ReserveInvoice'], reserva)
                for linea in payload['DocumentLines']:
                    self.assertEqual(linea['AgreementNo'], abs_id)
                    self.assertEqual(sum(b['Quantity'] for b in linea['BatchNumbers']), linea['Quantity'])

    def test_guardar_persistencia_atomica_y_no_altera_planificacion(self):
        with patch('apps.home.sap_despacho.SapServiceLayerClient') as sap:
            estado = service.guardar_carga(self.citacion, self.data(), self.user)
        sap.assert_not_called()
        self.assertTrue(estado['guardado'])
        self.assertTrue(estado['puede_avanzar'])
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.count(), 2)
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR, Decimal(100))
        self.assertEqual(list(self.detalle.asignaciones_sap.values_list('CDAS_NCANTIDAD_INTENTADA_DESPACHAR', flat=True)), [Decimal(100),Decimal(100)])

    def test_guardado_invalido_no_deja_registros_parciales(self):
        data = self.data(); data['acuerdos'][1]['estanques'][0]['item_code'] = 'INVALIDO'
        with self.assertRaises(service.CargaInvalida): service.guardar_carga(self.citacion, data, self.user)
        self.assertFalse(CITACION_DESPACHO_CARGA.objects.exists())
        self.assertFalse(CITACION_DESPACHO_DRAFT_SAP.objects.exists())

    def test_version_y_clave_idempotencia(self):
        estado = service.guardar_carga(self.citacion, self.data(), self.user)
        claves = list(CITACION_DESPACHO_DRAFT_SAP.objects.values_list('clave_idempotencia', flat=True))
        with self.assertRaisesRegex(service.CargaInvalida, 'cambió'):
            service.guardar_carga(self.citacion, self.data(), self.user)
        data = self.data(); data['version'] = estado['version']
        service.guardar_carga(self.citacion, data, self.user)
        self.assertEqual(claves, list(CITACION_DESPACHO_DRAFT_SAP.objects.values_list('clave_idempotencia', flat=True)))

    def test_draft_creado_nunca_se_pierde_al_reintentar_guardar(self):
        service.guardar_carga(self.citacion, self.data(), self.user)
        draft = CITACION_DESPACHO_DRAFT_SAP.objects.first(); draft.estado = 'CREADO'; draft.docentry = 'QA-TEST'; draft.save()
        data = self.data(); data['version'] = 1
        with self.assertRaisesRegex(service.CargaInvalida, 'envíos SAP'):
            service.guardar_carga(self.citacion, data, self.user)
        draft.refresh_from_db(); self.assertEqual(draft.docentry, 'QA-TEST')

    def test_legacy_sin_hijas_abre_sin_crear_registros(self):
        self.detalle.asignaciones_sap.all().delete()
        estado = service.estado_carga(self.citacion)
        self.assertTrue(estado['legacy']); self.assertEqual(len(estado['acuerdos']), 1)
        self.assertFalse(CITACION_DESPACHO_CARGA.objects.exists())

    def test_legacy_con_draft_conserva_circuito(self):
        self.detalle.CDD_CSAP_DRAFT_DOCENTRY = '100'; self.detalle.save()
        self.assertFalse(service.usa_carga_operacional(self.citacion))

    def test_otras_empresas_y_recepcion_no_aplican(self):
        self.citacion.CI_CTIPO = 'RECEPCION'
        self.assertFalse(service.usa_carga_operacional(self.citacion))
        with self.assertRaises(service.CargaInvalida): service.validar_ambito(self.citacion)
        self.citacion.CI_CTIPO = 'DESPACHO'; self.citacion.EP_NID_id = 1
        self.assertFalse(service.usa_carga_operacional(self.citacion))

    def test_endpoint_antiguo_no_crea_draft_singular(self):
        from apps.home.sap_despacho import crear_borrador_sap_despacho
        with patch('apps.home.sap_despacho.SapServiceLayerClient') as sap:
            result = crear_borrador_sap_despacho(self.citacion, self.user, allow_duplicate=True)
        self.assertFalse(result['success']); sap.assert_not_called()

    def test_permiso_backend_modal(self):
        from apps.home import views
        request = RequestFactory().post('/pla-citacion-estanque/1/')
        request.user = self.user
        with patch.object(views, 'usuario_es_asistente_cd', return_value=False):
            response = views.PLANIFICACION_CITACION_ESTANQUE(request, self.citacion.pk)
        self.assertEqual(response.status_code, 403)

    def preparar_etapa(self):
        etapa = ETAPA.objects.create(US_NID=self.user, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='AUTORIZACION_INGRESO', ET_CNOMBRE='Carga', ET_NCANTIDADMAXIMA=20, ET_BHABILITADO=True)
        DETALLE_SECUENCIA.objects.create(US_NID=self.user, EP_NID=self.empresa, SC_NID=self.citacion.SC_NID, ET_NID=etapa,
            SE_NPASO=3, SE_BHABILITADO=True)
        ETAPA_LOG.objects.create(CI_NID=self.citacion, EP_NID=self.empresa, SC_NID=self.citacion.SC_NID,
            ET_NID=etapa, US_INICIO_ID=self.user, EL_FFECHAINICIO=timezone.now())
        return etapa

    def request_modal(self, metodo='get', data=None, empresa=2):
        from apps.home import views
        request = getattr(RequestFactory(), metodo)('/pla-citacion-estanque/1/', data or {})
        request.user = self.user
        request.session = {'empresa_id': empresa}
        with patch.object(views, 'Verificar_empresa', return_value=empresa), patch.object(views, 'usuario_es_asistente_cd', return_value=True):
            return views.PLANIFICACION_CITACION_ESTANQUE(request, self.citacion.pk)

    def test_endpoint_catalogo_validado_por_citacion(self):
        self.preparar_etapa()
        response = self.request_modal(data={'catalogo_acuerdo':'4092'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(json.loads(response.content)['productos']), 2)
        response = self.request_modal(data={'catalogo_acuerdo':'123'})
        self.assertEqual(response.status_code, 400, response.content)

    def test_endpoint_empresa_ajena_rechazada(self):
        response = self.request_modal(data={'catalogo_acuerdo':'4092'}, empresa=1)
        self.assertEqual(response.status_code, 404, response.content)

    def test_endpoint_post_persiste_y_no_invoca_sap(self):
        self.preparar_etapa()
        with patch('apps.home.sap_despacho.SapServiceLayerClient') as sap:
            response = self.request_modal('post', {'carga_operacional':json.dumps(self.data())})
        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        self.assertTrue(payload['datos_guardados'])
        self.assertTrue(payload['puede_avanzar'])
        self.assertTrue(payload['carga_operacional']['guardado'])
        self.assertTrue(payload['carga_operacional']['puede_avanzar'])
        self.assertEqual(len(payload['carga_operacional']['acuerdos']), 2)
        carga = CITACION_DESPACHO_CARGA.objects.get(CI_NID=self.citacion)
        self.assertEqual(carga.cantidad_total, Decimal('100'))
        self.assertEqual(sum((a.cantidad for a in carga.acuerdos.all()), Decimal('0')), Decimal('100'))
        self.assertEqual(carga.acuerdos.count(), 2)
        self.assertEqual(sum(a.estanques.count() for a in carga.acuerdos.all()), 2)
        self.assertEqual(sum(tk.lotes.count() for a in carga.acuerdos.all() for tk in a.estanques.all()), 4)
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.count(), 2)
        sap.assert_not_called()

    def test_endpoint_get_muestra_todos_los_acuerdos(self):
        self.preparar_etapa()
        response = self.request_modal()
        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(len(payload['carga_operacional']['acuerdos']), 2)
        self.assertFalse(payload['puede_avanzar'])

    def test_post_singular_no_puede_evitar_validaciones(self):
        self.preparar_etapa()
        response = self.request_modal('post', {'zona_carga':'Línea 1','codigo_sap':'980057','peso_informado':'100'})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CITACION_DESPACHO_CARGA.objects.exists())

    def test_stock_se_agrega_entre_acuerdos(self):
        self.productos[3584] = [self.producto(3584, '980057')]
        data = self.data()
        data['acuerdos'][1]['estanques'][0]['item_code'] = '980057'
        with self.assertRaisesRegex(service.CargaInvalida, 'stock'):
            self.validar(data)

    def test_fefo_agregado_permite_repartir_lote_temprano_entre_acuerdos(self):
        self.productos[3584] = [self.producto(3584, '980057')]
        data = self.data()
        data['acuerdos'][0]['estanques'][0]['lotes'] = [{'batch_number':'A','cantidad':'10'},{'batch_number':'B','cantidad':'50'}]
        data['acuerdos'][1]['estanques'][0]['item_code'] = '980057'
        data['acuerdos'][1]['estanques'][0]['lotes'] = [{'batch_number':'A','cantidad':'10'},{'batch_number':'C','cantidad':'30'}]
        self.validar(data)

    def test_hana_no_disponible_no_guarda(self):
        self.preparar_etapa()
        with patch.object(service, 'consultar_productos_acuerdo', side_effect=RuntimeError('SAP unavailable')):
            response = self.request_modal('post', {'carga_operacional':json.dumps(self.data())})
        self.assertEqual(response.status_code, 502, response.content)
        self.assertFalse(CITACION_DESPACHO_CARGA.objects.exists())

    def _guardar_para_envio(self, data=None):
        return service.guardar_carga(self.citacion, data or self.data(), self.user)

    def _payloads_envio(self, acuerdos=(4092, 3584)):
        return {abs_id: {'DocumentLines': [{'AgreementNo': abs_id}]} for abs_id in acuerdos}

    def _ejecutar_envio(self, client, payloads=None):
        factory = MagicMock(return_value=client)
        with patch.object(envio, 'load_config', return_value=object()), patch.object(
            envio, 'construir_payload_despacho', return_value=payloads or self._payloads_envio()
        ):
            resultado = envio.crear_borradores_sap_despacho(
                self.citacion, self.user, client_factory=factory
            )
        return resultado, factory

    def test_envio_dos_acuerdos_crea_y_persiste_dos_drafts(self):
        self._guardar_para_envio()
        client = MagicMock()
        client.post_draft.side_effect = [
            {'data': {'DocEntry': 701, 'DocNum': 801}},
            {'data': {'DocEntry': 702, 'DocNum': 802}},
        ]
        resultado, factory = self._ejecutar_envio(client)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(client.post_draft.call_count, 2)
        self.assertEqual(
            list(CITACION_DESPACHO_DRAFT_SAP.objects.order_by('acuerdo__orden').values_list('estado', 'docentry', 'docnum')),
            [('CREADO', '701', '801'), ('CREADO', '702', '802')],
        )
        factory.assert_called_once()
        client.login.assert_called_once()
        client.logout.assert_called_once()

    def test_envio_un_acuerdo_crea_un_draft(self):
        self.detalle.asignaciones_sap.filter(CDAS_CSAP_ABS_ID='3584').delete()
        data = self.data()
        data['acuerdos'] = data['acuerdos'][:1]
        data['cantidad_total'] = data['acuerdos'][0]['cantidad'] = '10'
        data['acuerdos'][0]['estanques'] = [self.bloque(cantidad='10', lotes=[('A', '10')])]
        self._guardar_para_envio(data)
        client = MagicMock()
        client.post_draft.return_value = {'data': {'DocEntry': 703, 'DocNum': 803}}
        self._ejecutar_envio(client, self._payloads_envio((4092,)))
        self.assertEqual(client.post_draft.call_count, 1)
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.get().docentry, '703')

    def test_draft_existente_no_se_duplica_en_reintento(self):
        self._guardar_para_envio()
        first = MagicMock()
        first.post_draft.side_effect = [
            {'data': {'DocEntry': 704, 'DocNum': 804}},
            {'data': {'DocEntry': 705, 'DocNum': 805}},
        ]
        self._ejecutar_envio(first)
        second = MagicMock()
        resultado, factory = self._ejecutar_envio(second)
        self.assertTrue(all(item['reutilizado'] for item in resultado))
        factory.assert_not_called()
        second.post_draft.assert_not_called()
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.count(), 2)

    def test_fallo_parcial_persiste_primero_y_reintenta_solo_segundo(self):
        self._guardar_para_envio()
        response = Response()
        response.status_code = 400
        response._content = b'{"error":{"message":{"value":"dato rechazado"}}}'
        first = MagicMock()
        first.post_draft.side_effect = [
            {'data': {'DocEntry': 706, 'DocNum': 806}},
            HTTPError(response=response),
        ]
        with self.assertRaisesRegex(envio.EnvioDraftSapError, '381'):
            self._ejecutar_envio(first)
        drafts = list(CITACION_DESPACHO_DRAFT_SAP.objects.order_by('acuerdo__orden'))
        self.assertEqual((drafts[0].estado, drafts[0].docentry), ('CREADO', '706'))
        self.assertEqual(drafts[1].estado, 'ERROR')
        self.assertFalse(envio.borradores_creados(self.citacion))

        retry = MagicMock()
        retry.post_draft.return_value = {'data': {'DocEntry': 707, 'DocNum': 807}}
        resultado, _ = self._ejecutar_envio(retry)
        self.assertEqual(retry.post_draft.call_count, 1)
        self.assertEqual([item['reutilizado'] for item in resultado], [True, False])
        self.assertTrue(envio.borradores_creados(self.citacion))

    def test_respuesta_incierta_bloquea_reenvio_automatico(self):
        self._guardar_para_envio()
        client = MagicMock()
        client.post_draft.side_effect = RuntimeError('timeout después del POST')
        with self.assertRaises(envio.EnvioDraftSapError):
            self._ejecutar_envio(client)
        draft = CITACION_DESPACHO_DRAFT_SAP.objects.order_by('acuerdo__orden').first()
        self.assertEqual(draft.estado, 'INCIERTO')
        retry = MagicMock()
        with self.assertRaisesRegex(envio.EnvioDraftSapError, 'conciliación'):
            self._ejecutar_envio(retry)
        retry.post_draft.assert_not_called()

    def test_configuracion_persistida_incompleta_no_llama_sap(self):
        self._guardar_para_envio()
        lote = CITACION_DESPACHO_CARGA.objects.get(CI_NID=self.citacion).acuerdos.first().estanques.first().lotes.first()
        lote.cantidad = Decimal('19')
        lote.save(update_fields=['cantidad'])
        factory = MagicMock()
        with self.assertRaises(service.CargaInvalida), patch.object(
            envio, 'construir_payload_despacho'
        ) as construir:
            envio.crear_borradores_sap_despacho(self.citacion, self.user, client_factory=factory)
        construir.assert_not_called()
        factory.assert_not_called()

    def test_error_sap_en_endpoint_no_avanza(self):
        from apps.home import views
        self._guardar_para_envio()
        self.preparar_etapa()
        request = RequestFactory().post('/pla-citacion-estanque-avanzar/1/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_asistente_cd', return_value=True
        ), patch.object(
            views, 'crear_borradores_sap_despacho',
            side_effect=envio.EnvioDraftSapError('No fue posible crear el borrador SAP del acuerdo 381.', acuerdo='381', estado='ERROR'),
        ), patch.object(views, 'avanzar_citacion_a_siguiente_etapa') as avanzar:
            response = views.AVANZAR_ESTANQUE_SIGUIENTE_ETAPA(request, self.citacion.pk)
        self.assertEqual(response.status_code, 502, response.content)
        avanzar.assert_not_called()
    def test_endpoint_exitoso_envia_sap_antes_de_avanzar(self):
        from apps.home import views
        self._guardar_para_envio()
        self.preparar_etapa()
        request = RequestFactory().post('/pla-citacion-estanque-avanzar/1/')
        request.user = self.user
        request.session = {'empresa_id': 2}
        origen = MagicMock(ET_CCODIGO='AUTORIZACION_INGRESO')
        destino = MagicMock(ET_CCODIGO='SIGUIENTE')
        eventos = []
        def crear_side_effect(*args, **kwargs):
            eventos.append('sap')
            return [{'sap_abs_id': 4092, 'docentry': '900'}]
        def avanzar_side_effect(*args, **kwargs):
            eventos.append('avance')
            return origen, destino
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_asistente_cd', return_value=True
        ), patch.object(
            views, 'crear_borradores_sap_despacho', side_effect=crear_side_effect
        ) as crear, patch.object(
            views, 'borradores_despacho_creados', return_value=True
        ), patch.object(
            views, 'avanzar_citacion_a_siguiente_etapa', side_effect=avanzar_side_effect
        ) as avanzar, patch.object(
            views, 'obtener_guardias_relacionados_citacion', return_value=[]
        ), patch.object(views, 'registrar_log_camion_no_planificado'):
            response = views.AVANZAR_ESTANQUE_SIGUIENTE_ETAPA(request, self.citacion.pk)
        self.assertEqual(response.status_code, 200, response.content)
        crear.assert_called_once()
        avanzar.assert_called_once()
        self.assertEqual(eventos, ['sap', 'avance'])
    @staticmethod
    def _salida_print(mock_print):
        return '\n'.join(' '.join(str(value) for value in call.args) for call in mock_print.call_args_list)

    def test_log_sap_exito_multiacuerdo_muestra_payload_y_respuesta(self):
        self._guardar_para_envio()
        client = MagicMock()
        client.post_draft.side_effect = [
            {'status_code': 201, 'data': {'DocEntry': 901, 'DocNum': 1001}},
            {'status_code': 201, 'data': {'DocEntry': 902, 'DocNum': 1002}},
        ]
        with patch('builtins.print') as mock_print:
            self._ejecutar_envio(client)
        salida = self._salida_print(mock_print)
        self.assertEqual(salida.count('[Borrador SAP][Despacho SBH][Enviar]'), 2)
        self.assertIn('"citacion": %s' % self.citacion.pk, salida)
        self.assertIn('"acuerdo_abs_id": 4092', salida)
        self.assertIn('"acuerdo_abs_id": 3584', salida)
        self.assertIn('"payload": {', salida)
        self.assertIn('"DocEntry": "901"', salida)
        self.assertIn('"DocNum": "1002"', salida)
        self.assertEqual(salida.count('[Borrador SAP][Despacho SBH][Respuesta SAP]'), 2)
        for secreto in ('password', 'sessionid', 'routeid', 'authorization', 'b1session'):
            self.assertNotIn(secreto, salida.casefold())

    def test_log_sap_error_incluye_contexto_payload_y_mensaje(self):
        self._guardar_para_envio()
        response = Response()
        response.status_code = 400
        response._content = b'{"error":{"code":"1470000315","message":{"value":"Cannot add document"}}}'
        client = MagicMock()
        client.post_draft.side_effect = HTTPError(response=response)
        with patch('builtins.print') as mock_print, self.assertRaises(envio.EnvioDraftSapError):
            self._ejecutar_envio(client)
        salida = self._salida_print(mock_print)
        self.assertIn('[Borrador SAP][Despacho SBH][Error SAP]', salida)
        self.assertIn('"citacion": %s' % self.citacion.pk, salida)
        self.assertIn('"acuerdo_abs_id": 4092', salida)
        self.assertIn('"endpoint": "/Drafts"', salida)
        self.assertIn('"status_http": 400', salida)
        self.assertIn('"payload": {', salida)
        self.assertIn('1470000315', salida)
        self.assertIn('Cannot add document', salida)

    def test_log_sap_draft_existente_indica_que_no_reenvia(self):
        self._guardar_para_envio()
        first = MagicMock()
        first.post_draft.side_effect = [
            {'status_code': 201, 'data': {'DocEntry': 903, 'DocNum': 1003}},
            {'status_code': 201, 'data': {'DocEntry': 904, 'DocNum': 1004}},
        ]
        with patch('builtins.print'):
            self._ejecutar_envio(first)
        retry = MagicMock()
        with patch('builtins.print') as mock_print:
            self._ejecutar_envio(retry)
        salida = self._salida_print(mock_print)
        self.assertEqual(salida.count('[Borrador SAP][Despacho SBH][Ya existente, no se reenvía]'), 2)
        self.assertIn('"DocEntry"'.casefold(), salida.casefold())
        self.assertNotIn('[Borrador SAP][Despacho SBH][Enviar]', salida)
        retry.post_draft.assert_not_called()
