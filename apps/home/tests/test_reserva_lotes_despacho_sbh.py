import inspect
import json
from datetime import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from apps.home import despacho_carga, sap_despacho_documentos, views
from apps.home.models import (
    CALENDARIO,
    CITACION,
    CITACION_DESPACHO_ACUERDO_ESTANQUE,
    CITACION_DESPACHO_ACUERDO_LOTE,
    CITACION_DESPACHO_ACUERDO_OPERACIONAL,
    CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DRAFT_SAP,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
)


class DisponibilidadOperacionalTests(SimpleTestCase):
    def setUp(self):
        self.citacion = SimpleNamespace(id=200)
        self.stock = {
            '980057': [{
                'item_code': '980057',
                'warehouse_code': 'TKMX01',
                'batch_number': 'L1',
                'stock': '100',
                'fecha_vencimiento': '2099-01-01',
            }],
        }

    def calcular(self, cantidades=None, trazabilidad=None):
        with patch.object(
            despacho_carga,
            'reservas_activas',
            return_value={
                'cantidades': cantidades or {},
                'trazabilidad': trazabilidad or {},
            },
        ):
            return despacho_carga.aplicar_disponibilidad_operacional(
                self.citacion, self.stock,
            )['980057'][0]

    def test_a_sap_100_sin_reservas_disponible_100(self):
        fila = self.calcular()
        self.assertEqual(Decimal(fila['disponible']), Decimal('100'))
        self.assertEqual(fila['estado_operacional'], 'DISPONIBLE')

    def test_b_y_d_reserva_parcial_deja_72_5_disponible(self):
        clave = ('980057', 'TKMX01', 'L1')
        fila = self.calcular({clave: Decimal('27.5')})
        self.assertEqual(Decimal(fila['reservado']), Decimal('27.5'))
        self.assertEqual(Decimal(fila['disponible']), Decimal('72.5'))
        self.assertEqual(fila['estado_operacional'], 'DISPONIBLE')

    def test_c_y_e_reserva_total_sigue_visible_como_reservado(self):
        clave = ('980057', 'TKMX01', 'L1')
        traza = [{'citacion_id': 38709, 'acuerdo': '429', 'cantidad': '100'}]
        fila = self.calcular({clave: Decimal('100')}, {clave: traza})
        self.assertEqual(Decimal(fila['disponible']), Decimal('0'))
        self.assertEqual(fila['estado_operacional'], 'RESERVADO')
        self.assertEqual(fila['reservas'], traza)

    def test_o_no_mezcla_el_mismo_lote_entre_warehouses(self):
        clave_otra = ('980057', 'TK04', 'L1')
        fila = self.calcular({clave_otra: Decimal('100')})
        self.assertEqual(Decimal(fila['disponible']), Decimal('100'))

    def test_w_stock_sap_cero_no_se_muestra(self):
        self.stock['980057'][0]['stock'] = '0'
        with patch.object(
            despacho_carga,
            'reservas_activas',
            return_value={'cantidades': {}, 'trazabilidad': {}},
        ):
            resultado = despacho_carga.aplicar_disponibilidad_operacional(
                self.citacion, self.stock,
            )
        self.assertEqual(resultado['980057'], [])

    def test_f_fefo_salta_lote_totalmente_reservado(self):
        stock = [
            {'batch_number': 'A', 'stock': '0', 'fecha_vencimiento': '2099-01-01'},
            {'batch_number': 'B', 'stock': '30', 'fecha_vencimiento': '2099-02-01'},
        ]
        despacho_carga.validar_fefo(stock, {'B': Decimal('27.5')})

    def test_g_fefo_agota_saldo_parcial_antes_del_siguiente(self):
        stock = [
            {'batch_number': 'A', 'stock': '5', 'fecha_vencimiento': '2099-01-01'},
            {'batch_number': 'B', 'stock': '30', 'fecha_vencimiento': '2099-02-01'},
        ]
        despacho_carga.validar_fefo(
            stock, {'A': Decimal('5'), 'B': Decimal('22.5')},
        )

    def test_h_un_lote_menor_participa_en_despacho_mayor(self):
        stock = [
            {'batch_number': 'A', 'stock': '10', 'fecha_vencimiento': '2099-01-01'},
            {'batch_number': 'B', 'stock': '30', 'fecha_vencimiento': '2099-02-01'},
        ]
        despacho_carga.validar_fefo(
            stock, {'A': Decimal('10'), 'B': Decimal('17.5')},
        )

    def test_e_y_f_frontend_deshabilita_reservado_y_fefo_lo_excluye(self):
        ruta = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/PLANIFICACION/despacho_carga_js.html'
        )
        source = ruta.read_text(encoding='utf-8')
        self.assertIn("reserved ? 'RESERVADO' : 'DISPONIBLE'", source)
        self.assertIn('const blocked = reserved || !usable(row)', source)
        self.assertIn(
            'filter(row => operationallyAvailable(row) && usable(row)',
            source,
        )
        self.assertNotIn('No disponible actualmente', source)

    def test_boton_verificar_documento_respeta_estado_backend(self):
        ruta = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/CITACION/operacion_planta.html'
        )
        source = ruta.read_text(encoding='utf-8')
        self.assertIn('Verificar documento SAP', source)
        self.assertIn(
            'paso.drafts_sap_despacho_operacionales.'
            'verificacion_documentos_habilitada',
            source,
        )
        self.assertIn(
            'paso.drafts_sap_despacho_operacionales.todos_actualizados',
            source,
        )


class ReservaPersistidaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('reserva_lote_test')
        cls.empresa = EMPRESA.objects.create(
            pk=2,
            EP_CRAZONSOCIAL='SBH',
            EP_CRUT='22-2',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        calendario = CALENDARIO.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Reservas',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=20,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            SE_CTIPO='DESPACHO',
            SE_CCODIGO='RESERVA',
            SE_CNOMBRE='Reserva',
            SE_BHABILITADO=True,
        )
        cls.plan = PLANIFICACION.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='DESPACHO',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=20,
        )

    def crear_citacion(self, cupo, estado='PENDIENTE'):
        return CITACION.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            PL_NID=self.plan,
            SC_NID=self.secuencia,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=cupo,
            CI_CTIPO='DESPACHO',
            CI_CESTADO=estado,
        )

    def crear_acuerdo(
        self, citacion, orden, abs_id, numero, cantidad, batch='L1',
        warehouse='TKMX01', item='980057', respuesta=None, docentry=None,
    ):
        carga, _ = CITACION_DESPACHO_CARGA.objects.get_or_create(
            CI_NID=citacion,
            defaults={
                'US_NID': self.user,
                'cantidad_total': Decimal('100'),
                'zona_carga': 'Línea 1',
            },
        )
        acuerdo = CITACION_DESPACHO_ACUERDO_OPERACIONAL.objects.create(
            carga=carga,
            sap_abs_id=abs_id,
            numero_acuerdo=numero,
            cliente_codigo='C001',
            cliente_nombre='Cliente',
            cantidad=Decimal(str(cantidad)),
            orden=orden,
        )
        estanque = CITACION_DESPACHO_ACUERDO_ESTANQUE.objects.create(
            acuerdo=acuerdo,
            warehouse_code=warehouse,
            item_code=item,
            item_name='Producto',
            linea_acuerdo='1',
            unidad_medida='MT',
            cantidad=Decimal(str(cantidad)),
            orden=1,
        )
        lote = CITACION_DESPACHO_ACUERDO_LOTE.objects.create(
            estanque=estanque,
            batch_number=batch,
            stock_snapshot=Decimal('100'),
            cantidad=Decimal(str(cantidad)),
        )
        draft = CITACION_DESPACHO_DRAFT_SAP.objects.create(
            acuerdo=acuerdo,
            clave_idempotencia=f'RES-{citacion.pk}-{abs_id}',
            estado='CREADO' if docentry else 'PREPARADO',
            docentry=str(docentry or ''),
            payload={'DocObjectCode': '15'},
            respuesta=respuesta or {},
        )
        return acuerdo, lote, draft

    def test_i_reservas_propias_se_excluyen_y_k_multiacuerdo_se_suma(self):
        actual = self.crear_citacion(1)
        otra = self.crear_citacion(2)
        self.crear_acuerdo(actual, 1, 4000, 'ACTUAL', '50')
        self.crear_acuerdo(otra, 1, 4092, '429', '20')
        self.crear_acuerdo(otra, 2, 4093, '430', '7.5')
        reservas = despacho_carga.reservas_activas(actual.pk)
        clave = ('980057', 'TKMX01', 'L1')
        self.assertEqual(reservas['cantidades'][clave], Decimal('27.5'))
        self.assertEqual(len(reservas['trazabilidad'][clave]), 2)

    def test_l_edicion_libera_saldo_y_m_cambio_de_lote_libera_anterior(self):
        actual = self.crear_citacion(1)
        otra = self.crear_citacion(2)
        _, lote, _ = self.crear_acuerdo(otra, 1, 4092, '429', '27.5')
        clave_l1 = ('980057', 'TKMX01', 'L1')
        self.assertEqual(
            despacho_carga.reservas_activas(actual.pk)['cantidades'][clave_l1],
            Decimal('27.5'),
        )
        lote.cantidad = Decimal('20')
        lote.save(update_fields=['cantidad'])
        self.assertEqual(
            despacho_carga.reservas_activas(actual.pk)['cantidades'][clave_l1],
            Decimal('20'),
        )
        lote.batch_number = 'L2'
        lote.save(update_fields=['batch_number'])
        reservas = despacho_carga.reservas_activas(actual.pk)['cantidades']
        self.assertNotIn(clave_l1, reservas)
        self.assertEqual(reservas[('980057', 'TKMX01', 'L2')], Decimal('20'))

    def test_r_s_t_libera_solo_acuerdo_documentado_con_consumo_reflejado(self):
        actual = self.crear_citacion(1)
        otra = self.crear_citacion(2)
        confirmado = {
            'verificacion_sap': {
                'draft_docentry': 100,
                'cerrado': True,
                'resultado_count': 1,
                'consumo_reflejado': True,
            },
        }
        self.crear_acuerdo(
            otra, 1, 4092, '429', '20', respuesta=confirmado, docentry='100',
        )
        self.crear_acuerdo(otra, 2, 4093, '430', '7.5', docentry='101')
        reservas = despacho_carga.reservas_activas(actual.pk)
        clave = ('980057', 'TKMX01', 'L1')
        self.assertEqual(reservas['cantidades'][clave], Decimal('7.5'))
        self.assertEqual(reservas['trazabilidad'][clave][0]['acuerdo'], '430')

    def test_documento_sin_stock_reflejado_aun_conserva_reserva(self):
        actual = self.crear_citacion(1)
        otra = self.crear_citacion(2)
        confirmado_sin_consumo = {
            'verificacion_sap': {
                'draft_docentry': 100,
                'cerrado': True,
                'resultado_count': 1,
                'consumo_reflejado': False,
            },
        }
        self.crear_acuerdo(
            otra, 1, 4092, '429', '20',
            respuesta=confirmado_sin_consumo, docentry='100',
        )
        clave = ('980057', 'TKMX01', 'L1')
        self.assertEqual(
            despacho_carga.reservas_activas(actual.pk)['cantidades'][clave],
            Decimal('20'),
        )

    def test_estados_reales_terminal_rechazado_archivado_o_inhabilitado_liberan(self):
        actual = self.crear_citacion(1)
        for cupo, estado in ((2, 'TERMINADO'), (3, 'RECHAZADO')):
            citacion = self.crear_citacion(cupo, estado)
            self.crear_acuerdo(citacion, 1, 4000 + cupo, str(cupo), '10')
        archivada = self.crear_citacion(4)
        archivada.CI_BARCHIVADO = True
        archivada.save(update_fields=['CI_BARCHIVADO'])
        self.crear_acuerdo(archivada, 1, 4004, '4', '10')
        inhabilitada = self.crear_citacion(5)
        inhabilitada.CI_BHABILITADO = False
        inhabilitada.save(update_fields=['CI_BHABILITADO'])
        self.crear_acuerdo(inhabilitada, 1, 4005, '5', '10')
        self.assertEqual(
            despacho_carga.reservas_activas(actual.pk)['cantidades'], {},
        )

    def test_n_guardar_usa_transaccion_y_mutex_comun_de_empresa(self):
        source = inspect.getsource(despacho_carga.guardar_carga)
        self.assertIn('EMPRESA.objects.select_for_update().get(pk=2)', source)
        self.assertIn(
            '@transaction.atomic',
            Path(despacho_carga.__file__).read_text(encoding='utf-8'),
        )


class DocumentoDefinitivoSapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ReservaPersistidaTests.setUpTestData.__func__(cls)

    crear_citacion = ReservaPersistidaTests.crear_citacion
    crear_acuerdo = ReservaPersistidaTests.crear_acuerdo

    def setUp(self):
        self.citacion = self.crear_citacion(10)
        self.acuerdo_a, _, self.draft_a = self.crear_acuerdo(
            self.citacion, 1, 4092, '429', '20', docentry='100',
        )
        self.acuerdo_b, _, self.draft_b = self.crear_acuerdo(
            self.citacion, 2, 4093, '430', '7.5', docentry='101',
        )
        for draft in (self.draft_a, self.draft_b):
            draft.respuesta = {
                'creacion': {'DocEntry': int(draft.docentry)},
                'actualizacion_peso_real': {'success': True},
            }
            draft.save(update_fields=['respuesta'])

    def test_draft_sap_esta_cerrado_retorna_booleano(self):
        cerrado = MagicMock(return_value={'resultado_count': 1})
        abierto = MagicMock(return_value={'resultado_count': 0})
        self.assertTrue(
            sap_despacho_documentos.draft_sap_esta_cerrado(
                3530, row_loader=cerrado,
            )
        )
        self.assertFalse(
            sap_despacho_documentos.draft_sap_esta_cerrado(
                3530, row_loader=abierto,
            )
        )
        sql, params = cerrado.call_args.args
        self.assertIn('FROM ODRF', sql)
        self.assertEqual(params, [3530])

    def verificar(self, conteos, stock='72.5'):
        row_loader = MagicMock(
            side_effect=[
                {'resultado_count': conteo}
                for conteo in conteos
            ],
        )
        resultado = sap_despacho_documentos.verificar_documentos_definitivos(
            self.citacion,
            row_loader=row_loader,
            stock_loader=MagicMock(return_value=[{
                'item_code': '980057',
                'warehouse_code': 'TKMX01',
                'batch_number': 'L1',
                'stock': stock,
            }]),
        )
        return resultado, row_loader

    def test_q_r_s_t_documentos_independientes_y_liberacion_parcial(self):
        resultado, row_loader = self.verificar([1, 0])
        por_acuerdo = {
            item['numero_acuerdo']: item for item in resultado['documentos']
        }
        self.assertEqual(por_acuerdo['429']['estado'], 'CONFIRMADO')
        self.assertEqual(por_acuerdo['429']['resultado_count'], 1)
        self.assertEqual(por_acuerdo['430']['estado'], 'PENDIENTE')
        self.assertFalse(resultado['completo'])
        self.assertEqual(row_loader.call_count, 2)
        sql, params = row_loader.call_args_list[0].args
        self.assertIn('FROM ODRF', sql)
        self.assertIn('"DocStatus" = \'C\'', sql)
        self.assertIn('"DocEntry" = ?', sql)
        self.assertEqual(params, [100])

        actual = self.crear_citacion(11)
        reservas = despacho_carga.reservas_activas(actual.pk)
        self.assertEqual(
            reservas['cantidades'][('980057', 'TKMX01', 'L1')],
            Decimal('7.5'),
        )
        self.assertEqual(
            reservas['trazabilidad'][('980057', 'TKMX01', 'L1')][0]['acuerdo'],
            '430',
        )

    def test_q_y_v_todos_los_documentos_confirmados(self):
        resultado, _ = self.verificar([1, 1])
        self.assertTrue(resultado['completo'])
        self.assertEqual(
            [item['resultado_count'] for item in resultado['documentos']],
            [1, 1],
        )
        self.assertTrue(all(
            item['cerrado'] for item in resultado['documentos']
        ))

    def test_documento_confirmado_no_libera_si_stock_aun_no_bajo(self):
        resultado, _ = self.verificar([1, 0], stock='100')
        primero = resultado['documentos'][0]
        self.assertEqual(primero['estado'], 'CONFIRMADO')
        self.assertFalse(primero['consumo_reflejado'])
        self.draft_a.refresh_from_db()
        self.assertNotIn('documento_definitivo', self.draft_a.respuesta)
        actual = self.crear_citacion(12)
        reservas = despacho_carga.reservas_activas(actual.pk)
        self.assertEqual(
            reservas['cantidades'][('980057', 'TKMX01', 'L1')],
            Decimal('27.5'),
        )

    def test_factura_se_concilia_en_invoices_y_entrega_en_delivery_notes(self):
        source = inspect.getsource(
            sap_despacho_documentos.verificar_documentos_definitivos,
        )
        self.assertNotIn('DeliveryNotes', source)
        self.assertNotIn('DraftKey', source)
        self.assertNotIn('SapServiceLayerClient', source)

    def test_acuerdo_sin_draft_permanece_en_estado_global_incompleto(self):
        self.draft_b.delete()
        estado = sap_despacho_documentos.estado_documentos_definitivos(
            self.citacion,
        )
        self.assertEqual(len(estado['documentos']), 2)
        self.assertFalse(estado['completo'])
        self.assertEqual(estado['documentos'][1]['estado'], 'PENDIENTE')
        self.assertIn('no tiene Draft', estado['documentos'][1]['error'])

    def test_count_cero_se_persiste_y_no_habilita_salida(self):
        resultado, _ = self.verificar([0, 0])
        primero = resultado['documentos'][0]
        self.assertEqual(primero['estado'], 'PENDIENTE')
        self.assertFalse(primero['cerrado'])
        self.assertFalse(primero['valido'])
        self.assertFalse(resultado['completo'])
        self.draft_a.refresh_from_db()
        verificacion = self.draft_a.respuesta['verificacion_sap']
        self.assertEqual(verificacion['draft_docentry'], 100)
        self.assertEqual(verificacion['resultado_count'], 0)
        self.assertFalse(verificacion['cerrado'])

    def test_conteo_invalido_no_persiste_verificacion(self):
        respuesta_antes = json.loads(json.dumps(self.draft_a.respuesta))
        row_loader = MagicMock(return_value={'resultado_count': 'invalido'})
        with self.assertRaises(
            sap_despacho_documentos.VerificacionDocumentoSapError,
        ):
            sap_despacho_documentos.verificar_documentos_definitivos(
                self.citacion,
                row_loader=row_loader,
            )
        self.draft_a.refresh_from_db()
        self.assertEqual(self.draft_a.respuesta, respuesta_antes)

    def test_error_hana_no_cambia_estado_local(self):
        respuestas_antes = {
            draft.pk: json.loads(json.dumps(draft.respuesta))
            for draft in (self.draft_a, self.draft_b)
        }
        row_loader = MagicMock(side_effect=RuntimeError('HANA no disponible'))
        with self.assertRaises(
            sap_despacho_documentos.VerificacionDocumentoSapError,
        ):
            sap_despacho_documentos.verificar_documentos_definitivos(
                self.citacion,
                row_loader=row_loader,
            )
        for draft in (self.draft_a, self.draft_b):
            draft.refresh_from_db()
            self.assertEqual(draft.respuesta, respuestas_antes[draft.pk])

    def test_refresh_conserva_cierres_confirmados_desde_postgresql(self):
        resultado, row_loader = self.verificar([1, 1])
        self.assertTrue(resultado['completo'])
        self.draft_a.refresh_from_db()
        self.assertIn('creacion', self.draft_a.respuesta)
        self.assertIn('actualizacion_peso_real', self.draft_a.respuesta)
        self.assertTrue(self.draft_a.respuesta['verificacion_sap']['cerrado'])
        self.assertTrue(
            self.draft_a.respuesta['verificacion_sap']['consumo_reflejado']
        )
        row_loader.reset_mock()
        estado_local = sap_despacho_documentos.estado_documentos_definitivos(
            self.citacion,
        )
        self.assertTrue(estado_local['completo'])
        row_loader.assert_not_called()

    def test_caso_38710_no_descuenta_dos_veces_consumo_ya_reflejado(self):
        lote = self.acuerdo_a.estanques.get().lotes.get()
        lote.stock_snapshot = Decimal('80.25')
        lote.cantidad = Decimal('15.54')
        lote.save(update_fields=['stock_snapshot', 'cantidad'])
        lote_pendiente = self.acuerdo_b.estanques.get().lotes.get()
        lote_pendiente.batch_number = 'L2'
        lote_pendiente.save(update_fields=['batch_number'])
        self.draft_a.respuesta['actualizacion_peso_real']['request'] = {
            'DocumentLines': [{
                'ItemCode': '980057',
                'WarehouseCode': 'TKMX01',
                'BatchNumbers': [{
                    'BatchNumber': 'L1',
                    'Quantity': 15.74,
                }],
            }],
        }
        self.draft_a.save(update_fields=['respuesta'])
        self.verificar([1, 0], stock='64.51')

        nueva = self.crear_citacion(13)
        stocks = {'980057': [{
            'item_code': '980057',
            'warehouse_code': 'TKMX01',
            'batch_number': 'L1',
            'stock': '64.51',
        }]}
        fila = despacho_carga.aplicar_disponibilidad_operacional(
            nueva, stocks,
        )['980057'][0]
        self.assertEqual(Decimal(fila['reservado']), Decimal('0'))
        self.assertEqual(Decimal(fila['disponible']), Decimal('64.51'))
        self.assertFalse(any(
            item['acuerdo'] == '429' for item in fila['reservas']
        ))

    def test_verificacion_antigua_usa_stock_ya_cargado_sin_falso_cero(self):
        respuesta = dict(self.draft_a.respuesta)
        respuesta['verificacion_sap'] = {
            'draft_docentry': 100,
            'cerrado': True,
            'resultado_count': 1,
        }
        self.draft_a.respuesta = respuesta
        self.draft_a.save(update_fields=['respuesta'])
        self.assertFalse(sap_despacho_documentos.reserva_acuerdo_liberada(
            self.draft_a,
            stocks={'OTRO_ITEM': []},
        ))
        self.assertTrue(sap_despacho_documentos.reserva_acuerdo_liberada(
            self.draft_a,
            stocks={'980057': [{
                'item_code': '980057',
                'warehouse_code': 'TKMX01',
                'batch_number': 'L1',
                'stock': '80',
            }]},
        ))


    def test_bloque_historico_permanece_fuera_del_formulario_activo(self):
        template = Path(
            'apps/templates/home/CITACION/operacion_planta.html'
        ).read_text(encoding='utf-8')
        historico = template.index('Hist&oacute;rico documento SAP')
        formulario = template.index(
            '{% if not paso.autorizar_salida.registrada %}', historico,
        )
        self.assertLess(historico, formulario)
        self.assertIn('Informaci&oacute;n hist&oacute;rica de solo lectura', template)

    def test_acciones_sap_siguen_exigiendo_etapa_activa(self):
        template = Path(
            'apps/templates/home/CITACION/operacion_planta.html'
        ).read_text(encoding='utf-8')
        self.assertIn(
            '{% if paso.activo and paso.puede_editar and '
            'paso.drafts_sap_despacho_operacionales.'
            'verificacion_documentos_habilitada %}',
            template,
        )
        self.assertIn(
            '{% if paso.sap_despacho_preview_enabled and paso.activo and '
            'paso.puede_editar %}',
            template,
        )

    def test_draft_no_actualizado_bloquea_sin_abrir_sap(self):
        self.draft_b.respuesta = {'creacion': {'DocEntry': 101}}
        self.draft_b.save(update_fields=['respuesta'])
        row_loader = MagicMock()
        with self.assertRaises(
            sap_despacho_documentos.VerificacionDocumentoSapError,
        ):
            sap_despacho_documentos.verificar_documentos_definitivos(
                self.citacion,
                row_loader=row_loader,
            )
        row_loader.assert_not_called()

    def test_estado_ui_habilita_verificacion_solo_mientras_esta_pendiente(self):
        estado_pendiente = views._payload_drafts_sap_despacho_operacionales(
            self.citacion,
        )
        self.assertTrue(estado_pendiente['todos_actualizados'])
        self.assertTrue(estado_pendiente['verificacion_documentos_habilitada'])
        self.assertFalse(estado_pendiente['documentacion_completa'])

        for draft in (self.draft_a, self.draft_b):
            respuesta = dict(draft.respuesta)
            respuesta['verificacion_sap'] = {
                'draft_docentry': int(draft.docentry),
                'cerrado': True,
                'resultado_count': 1,
                'fecha_iso': timezone.now().isoformat(),
            }
            draft.respuesta = respuesta
            draft.save(update_fields=['respuesta'])
        estado_confirmado = views._payload_drafts_sap_despacho_operacionales(
            self.citacion,
        )
        self.assertTrue(estado_confirmado['documentacion_completa'])
        self.assertFalse(
            estado_confirmado['verificacion_documentos_habilitada']
        )


class AutorizacionDocumentalTests(TestCase):
    def ejecutar(self, documentacion):
        request = RequestFactory().post('/autorizar/')
        request.user = SimpleNamespace(
            username='asistente_despacho',
            is_authenticated=True,
            is_active=True,
            is_superuser=False,
        )
        citacion = SimpleNamespace(
            id=38709,
            pk=38709,
            CI_CTIPO='DESPACHO',
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            PL_NID=SimpleNamespace(id=1),
        )
        queryset = MagicMock()
        queryset.order_by.return_value.first.return_value = None
        queryset.exists.return_value = True
        log = SimpleNamespace(OPL_FFECHAREGISTRO=timezone.now())
        parches = [
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(
                views, '_obtener_citacion_operacion_planta_ajax',
                return_value=(citacion, None),
            ),
            patch.object(
                views, 'es_citacion_recepcion_terramar', return_value=False,
            ),
            patch.object(views, '_empresa_timbre_recepcion', return_value='SBH'),
            patch.object(
                views, 'obtener_pasos_operacion_citacion',
                return_value=(None, []),
            ),
            patch.object(
                views, 'obtener_paso_activo_operacion',
                return_value=(
                    views.PASO_AUTORIZAR_SALIDA,
                    ['ASISTENTE DESPACHO'],
                    None,
                ),
            ),
            patch.object(
                views, 'usuario_puede_paso_operacion', return_value=True,
            ),
            patch.object(views, 'es_despacho_sbh_operacion', return_value=True),
            patch.object(
                views, '_leer_ultimas_cargas_despacho',
                return_value={'carga_1': 'A', 'carga_2': 'B', 'carga_3': 'C'},
            ),
            patch.object(
                views, '_payload_drafts_sap_despacho_operacionales',
                return_value={'completos': True},
            ),
            patch.object(
                views, 'get_sap_despacho_update_status',
                return_value={'updated': True},
            ),
            patch.object(
                views, 'verificar_documentos_definitivos',
                return_value=documentacion,
            ),
            patch.object(
                views, 'es_despacho_bodega_externa_operacion',
                return_value=False,
            ),
            patch.object(
                views, '_leer_revision_conformidad_sbh',
                return_value={'recepcion_conforme': 'SI', 'observacion': ''},
            ),
            patch.object(views, 'aplica_timbraje_recepcion', return_value=False),
            patch.object(
                views, '_registrar_autorizar_salida',
                return_value={
                    'recepcion_conforme': 'SI',
                    'observacion_descarga': '',
                },
            ),
            patch.object(
                views.OPERACION_PLANTA_LOG.objects,
                'filter',
                return_value=queryset,
            ),
            patch.object(
                views.OPERACION_PLANTA_LOG.objects, 'create', return_value=log,
            ),
        ]
        started = [parche.start() for parche in parches]
        self.addCleanup(lambda: [parche.stop() for parche in reversed(parches)])
        return views.ajax_operacion_planta_autorizar_salida(request, citacion.pk)

    def test_u_un_acuerdo_pendiente_bloquea_autorizacion(self):
        response = self.ejecutar({'completo': False, 'documentos': []})
        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertEqual(
            payload['message'],
            'No es posible autorizar la salida. Existen acuerdos cuyo Draft SAP '
            'aún está abierto en ODRF.',
        )

    def test_v_todos_los_acuerdos_documentados_permiten_autorizacion(self):
        response = self.ejecutar({'completo': True, 'documentos': []})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['success'])

    def test_x_verificacion_unitaria_no_realiza_sap_real(self):
        request = RequestFactory().post('/verificar/')
        request.user = SimpleNamespace(is_authenticated=True, is_active=True)
        citacion = SimpleNamespace(id=38709, pk=38709, EP_NID_id=2)
        estado = {'completo': False, 'estado': 'DOCUMENTACIÓN SAP INCOMPLETA'}
        with patch.object(
            views, 'usuario_es_operacion_planta', return_value=True,
        ), patch.object(
            views, '_obtener_citacion_operacion_planta_ajax',
            return_value=(citacion, None),
        ), patch.object(
            views, 'es_despacho_sbh_operacion', return_value=True,
        ), patch.object(
            views, 'obtener_pasos_operacion_citacion', return_value=(None, []),
        ), patch.object(
            views, 'obtener_paso_activo_operacion',
            return_value=(
                views.PASO_AUTORIZAR_SALIDA,
                ['ASISTENTE DESPACHO'],
                None,
            ),
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True,
        ), patch.object(
            views, 'verificar_documentos_definitivos', return_value=estado,
        ) as verificar:
            response = views.ajax_operacion_planta_verificar_documentos_sap_despacho(
                request, citacion.pk,
            )
        self.assertEqual(response.status_code, 200)
        verificar.assert_called_once_with(citacion)
