import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.db import connections
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from apps.home import views
from apps.home.models import (
    CITACION, DATO_OPERACION, OPERACION_PLANTA_LOG, PERFIL, PERFIL_USUARIO, USERS_EMPRESA,
    CITACION_DESPACHO_CARGA, CITACION_DESPACHO_ACUERDO_OPERACIONAL,
    CITACION_DESPACHO_ACUERDO_ESTANQUE, CITACION_DESPACHO_ACUERDO_LOTE,
    CITACION_DESPACHO_DRAFT_SAP,
)
from apps.home.tests import test_inspeccion_inicio_carga_sbh as fixture


class CargaEstanqueFixture:
    def preparar_carga(self):
        fixture.InspeccionInicioCargaTests.setUpTestData.__func__(type(self))
        OPERACION_PLANTA_LOG.objects.create(CI_NID=self.citacion, EP_NID=self.empresa,
            PL_NID=self.planificacion, US_NID=self.usuario, OPL_CPASO=views.PASO_APROBAR_INICIO_CARGA,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D', OPL_CESTADO='COMPLETADO')
        self.carga = CITACION_DESPACHO_CARGA.objects.create(CI_NID=self.citacion,
            US_NID=self.usuario, cantidad_total=Decimal('27.5'), zona_carga='Línea 1')
        self.acuerdo = self.nuevo_acuerdo(4092, '429', '27.5')

    def nuevo_acuerdo(self, abs_id, numero, cantidad):
        return CITACION_DESPACHO_ACUERDO_OPERACIONAL.objects.create(carga=self.carga,
            sap_abs_id=abs_id, numero_acuerdo=numero, cantidad=Decimal(cantidad),
            cliente_codigo='C001', cliente_nombre='Cliente', orden=self.carga.acuerdos.count() + 1)

    def estanque(self, whs='TK04', lotes=(('A', '27.5'),), acuerdo=None, item='980057'):
        acuerdo = acuerdo or self.acuerdo
        estanque = CITACION_DESPACHO_ACUERDO_ESTANQUE.objects.create(acuerdo=acuerdo,
            warehouse_code=whs, item_code=item, item_name='Producto operacional',
            linea_acuerdo='1', unidad_medida='Toneladas', orden=acuerdo.estanques.count() + 1,
            cantidad=sum(Decimal(qty) for _, qty in lotes))
        for batch, qty in lotes:
            CITACION_DESPACHO_ACUERDO_LOTE.objects.create(estanque=estanque,
                batch_number=batch, cantidad=Decimal(qty), stock_snapshot=340)
        return estanque

    def dos_estanques(self):
        self.estanque(lotes=(('A', '12.5'), ('B', '7.5')))
        self.estanque('TKMX01', (('C', '7.5'),))

    def request(self, endpoint, user=None, **data):
        request = RequestFactory().post('/', data)
        request.user = user or self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2):
            return endpoint(request, self.citacion.id)

    def iniciar(self, whs='TK04', punto='L1', user=None):
        return self.request(views.ajax_operacion_planta_iniciar_ciclo_descarga, user,
            proceso='carga', warehouse_code=whs, punto_despacho=punto)

    def finalizar(self, whs='TK04'):
        return self.request(views.ajax_operacion_planta_finalizar_proceso_despacho,
            proceso='carga', warehouse_code=whs)

    def avanzar(self):
        return self.request(views.OPERACION_PLANTA_GUARDAR_PASO, paso=views.PASO_CICLO_DESCARGA)

    def payload(self):
        return views._payload_ciclo_carga_despacho(self.citacion)

    def metadata(self):
        return views._leer_metadata_ciclo_descarga(self.citacion)


class CargaPorEstanqueTests(CargaEstanqueFixture, TestCase):
    def setUp(self):
        self.preparar_carga()

    def test_un_estanque_con_varios_lotes_es_un_proceso_y_avanza_al_finalizar(self):
        self.estanque(lotes=(('A', '20'), ('B', '7.5')))
        self.assertEqual(self.payload()['cantidad_estanques'], 1)
        self.assertEqual(len(self.payload()['cargas'][0]['lotes']), 2)
        self.assertEqual(self.iniciar().status_code, 200)
        self.assertEqual(self.payload()['cargas'][0]['estado'], 'EN_CARGA')
        self.assertEqual(self.finalizar().status_code, 200)
        self.assertTrue(views._ciclo_carga_despacho_completo(self.citacion))
        self.assertEqual(self.avanzar().status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Pesaje Salida')
        self.assertEqual(DATO_OPERACION.objects.filter(CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_CICLO_DESCARGA).count(), 1)

    def test_cierre_valido_guarda_datos_y_activa_autorizacion_salida_sin_sap(self):
        self.estanque()
        self.iniciar()
        self.finalizar()
        self.assertEqual(self.avanzar().status_code, 200)
        OPERACION_PLANTA_LOG.objects.create(
            CI_NID=self.citacion, EP_NID=self.empresa, PL_NID=self.planificacion,
            US_NID=self.usuario, OPL_CPASO='Pesaje Salida',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA', OPL_CESTADO='COMPLETADO',
        )
        self.assertEqual(
            views.obtener_paso_activo_operacion(self.citacion)[0],
            views.PASO_CIERRE_CARGA,
        )

        with patch.object(views, 'get_sap_despacho_update_status') as estado_sap, \
             patch.object(views, 'sap_despacho_actualizar_borrador') as actualizar_sap:
            response = self.request(
                views.OPERACION_PLANTA_GUARDAR_PASO,
                paso=views.PASO_CIERRE_CARGA,
                despacho_cierre_nro_sellos='12345, 12346',
                despacho_cierre_temperatura='24.5',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=views.DESPACHO_CIERRE_NRO_SELLOS,
            ).DO_CVALOR,
            '12345, 12346',
        )
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=views.DESPACHO_CIERRE_TEMPERATURA,
            ).DO_CVALOR,
            '24.5',
        )
        self.assertEqual(
            views.obtener_paso_activo_operacion(self.citacion)[0],
            'Autorizar Salida',
        )
        estado_sap.assert_not_called()
        actualizar_sap.assert_not_called()


    def setUp(self):
        self.preparar_carga()
        self.asistente_recepcion = get_user_model().objects.create_user(
            username='asistente_recepcion_sbh_prueba',
        )
        perfil = PERFIL.objects.create(
            US_NID=self.asistente_recepcion,
            PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='ASISTENTE DE RECEPCION',
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.asistente_recepcion,
            PR_NID=perfil,
        )
        USERS_EMPRESA.objects.create(
            US_NID=self.asistente_recepcion,
            EP_NID=self.empresa,
        )
        self.asistente_despacho = get_user_model().objects.create_user(
            username='asistente_despacho_sbh_prueba',
        )
        perfil_despacho = PERFIL.objects.create(
            US_NID=self.asistente_despacho,
            PR_CCODIGO='ASISTENTE_DESPACHO',
            PR_CNOMBRE='ASISTENTE DESPACHO',
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.asistente_despacho,
            PR_NID=perfil_despacho,
        )
        USERS_EMPRESA.objects.create(
            US_NID=self.asistente_despacho,
            EP_NID=self.empresa,
        )

    def preparar_autorizacion(self):
        for paso, responsable in (
            (views.PASO_CICLO_DESCARGA, 'ASISTENTE C D'),
            ('Pesaje Salida', 'OPERADOR ROMANA'),
        ):
            OPERACION_PLANTA_LOG.objects.create(
                CI_NID=self.citacion,
                EP_NID=self.empresa,
                PL_NID=self.planificacion,
                US_NID=self.usuario,
                OPL_CPASO=paso,
                OPL_CPERFIL_RESPONSABLE=responsable,
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )
        guardado, _ = views.guardar_cierre_carga_despacho(
            self.citacion,
            {
                'despacho_cierre_nro_sellos': 'S-100, S-101',
                'despacho_cierre_temperatura': '22.5',
            },
            self.usuario,
        )
        self.assertTrue(guardado)
        OPERACION_PLANTA_LOG.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            US_NID=self.usuario,
            OPL_CPASO=views.PASO_CIERRE_CARGA,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        self.assertEqual(
            views.obtener_paso_activo_operacion(self.citacion)[0],
            views.PASO_AUTORIZAR_SALIDA,
        )

    def guardar_ultimas(self, **cambios):
        datos = {
            'accion': 'guardar_ultimas_cargas',
            'carga_1': 'Carga 001',
            'carga_2': 'Carga 002',
            'carga_3': 'Carga 003',
        }
        datos.update(cambios)
        return self.request(
            views.ajax_operacion_planta_autorizar_salida,
            self.asistente_despacho,
            **datos,
        )

    def estados_sap(self, updated=False):
        return (
            patch.object(views, 'get_sap_despacho_draft_status', return_value={'created': True}),
            patch.object(
                views,
                'get_sap_despacho_update_status',
                return_value={'updated': updated, 'is_error': False},
            ),
        )

    def test_payload_final_conserva_acuerdos_estanques_lotes_y_datos_cierre(self):
        estanque_uno = self.estanque(lotes=(('LOTE-A', '20'), ('LOTE-B', '7.5')))
        otro_acuerdo = self.nuevo_acuerdo(3584, '426', '7.5')
        estanque_dos = self.estanque('TKMX01', (('LOTE-C', '7.5'),), acuerdo=otro_acuerdo)
        estanque_uno.lotes.filter(batch_number='LOTE-A').update(fecha_vencimiento=date(2027, 1, 15))
        estanque_dos.lotes.filter(batch_number='LOTE-C').update(fecha_vencimiento=date(2027, 2, 20))
        views.guardar_cierre_carga_despacho(
            self.citacion,
            {
                'despacho_cierre_nro_sellos': 'S-100, S-101',
                'despacho_cierre_temperatura': '22.5',
            },
            self.usuario,
        )

        payload = views._payload_datos_finales_despacho_sbh(
            self.citacion,
            views.obtener_datos_operacion_citacion(self.citacion)[0],
        )

        self.assertEqual(len(payload['registros']), 3)
        self.assertEqual(
            {(item['numero_acuerdo'], item['warehouse_code'], item['batch_number']) for item in payload['registros']},
            {('429', 'TK04', 'LOTE-A'), ('429', 'TK04', 'LOTE-B'), ('426', 'TKMX01', 'LOTE-C')},
        )
        self.assertEqual({item['item_code'] for item in payload['registros']}, {'980057'})
        self.assertIn('15/01/2027', {item['fecha_vencimiento'] for item in payload['registros']})
        self.assertTrue(all(item['fecha_elaboracion'] == '' for item in payload['registros']))
        self.assertEqual(payload['nro_sellos'], 'S-100, S-101')
        self.assertEqual(payload['temperatura'], '22.5')

    def test_tres_cargas_exigen_exactamente_tres_valores_y_persisten_en_dato_operacion(self):
        self.estanque()
        self.preparar_autorizacion()
        for campo in ('carga_1', 'carga_2', 'carga_3'):
            response = self.guardar_ultimas(**{campo: ''})
            self.assertEqual(response.status_code, 400)
        response = self.guardar_ultimas()
        self.assertEqual(response.status_code, 200, response.content)
        metadata = views._leer_ultimas_cargas_despacho(self.citacion)
        self.assertEqual(
            [metadata[f'carga_{indice}'] for indice in range(1, 4)],
            ['Carga 001', 'Carga 002', 'Carga 003'],
        )
        self.assertEqual(metadata['usuario_id'], self.asistente_despacho.id)
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID=self.citacion,
                CAMP_NID__CA_CCODIGO=views.DESPACHO_ULTIMAS_CARGAS,
            ).count(),
            1,
        )

    def crear_draft(self, acuerdo=None, docentry='3528', docnum='16300'):
        acuerdo = acuerdo or self.acuerdo
        return CITACION_DESPACHO_DRAFT_SAP.objects.create(
            acuerdo=acuerdo,
            clave_idempotencia=f'prueba-{self.citacion.id}-{acuerdo.sap_abs_id}',
            estado='CREADO',
            docentry=docentry,
            docnum=docnum,
            payload={'AgreementNo': acuerdo.sap_abs_id},
            respuesta={'DocEntry': docentry, 'DocNum': docnum},
            intentos=1,
        )

    def test_drafts_operacionales_uno_dos_ausente_y_sin_duplicar(self):
        self.estanque()
        self.crear_draft()
        payload = views._payload_drafts_sap_despacho_operacionales(self.citacion)
        self.assertTrue(payload['completos'])
        self.assertEqual(
            [(item['numero_acuerdo'], item['docentry'], item['docnum']) for item in payload['drafts']],
            [('429', '3528', '16300')],
        )

        otro = self.nuevo_acuerdo(3584, '426', '7.5')
        self.estanque('TKMX01', (('B', '7.5'),), acuerdo=otro)
        incompleto = views._payload_drafts_sap_despacho_operacionales(self.citacion)
        self.assertFalse(incompleto['completos'])
        self.assertEqual(len(incompleto['drafts']), 2)
        self.assertEqual(incompleto['drafts'][1]['estado'], 'PENDIENTE')

        self.crear_draft(otro, '3529', '16301')
        completo = views._payload_drafts_sap_despacho_operacionales(self.citacion)
        self.assertEqual(
            {(item['numero_acuerdo'], item['docentry'], item['docnum']) for item in completo['drafts']},
            {('429', '3528', '16300'), ('426', '3529', '16301')},
        )
        self.assertEqual(CITACION_DESPACHO_DRAFT_SAP.objects.count(), 2)

    def test_autorizacion_renderiza_docentry_y_docnum_por_acuerdo(self):
        self.estanque()
        otro = self.nuevo_acuerdo(3584, '426', '7.5')
        self.estanque('TKMX01', (('B', '7.5'),), acuerdo=otro)
        self.crear_draft()
        self.crear_draft(otro, '3529', '16301')
        self.preparar_autorizacion()
        self.client.force_login(self.asistente_despacho)

        response = self.client.get(
            f"{reverse('operacion_planta_citacion', args=[self.citacion.id])}?empresa_id=2&_empresa_id=2"
        )

        self.assertEqual(response.status_code, 200)
        for texto in ('Acuerdo 429', '3528', '16300', 'Acuerdo 426', '3529', '16301'):
            self.assertContains(response, texto)
        self.assertContains(response, 'sin tolerancia porcentual')

    def test_actualizacion_sap_operacional_invoca_actualizacion_por_acuerdo(self):
        self.estanque()
        self.crear_draft()
        self.preparar_autorizacion()
        self.assertEqual(self.guardar_ultimas().status_code, 200)

        with patch.object(
            views,
            'sap_despacho_actualizar_borrador',
            return_value={'success': True, 'status': {'updated': True}},
        ) as actualizar:
            response = self.request(
                views.ajax_operacion_planta_actualizar_sap_despacho,
                self.asistente_despacho,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['success'])
        actualizar.assert_called_once_with(
            self.citacion,
            self.asistente_despacho,
            allow_retry=False,
            revalidar_disponibilidad=True,
        )

        with patch.object(
            views,
            'get_sap_despacho_update_status',
            return_value={'updated': False, 'is_error': False},
        ):
            bloqueada = self.request(
                views.ajax_operacion_planta_autorizar_salida,
                self.asistente_despacho,
                recepcion_conforme='SI',
            )
        self.assertEqual(bloqueada.status_code, 400)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO=views.PASO_AUTORIZAR_SALIDA,
        ).exists())

    def test_conformidad_no_tambien_permite_autorizacion_final_sin_imagenes(self):
        self.estanque()
        self.crear_draft()
        self.preparar_autorizacion()
        self.guardar_ultimas()
        with patch.object(views, 'get_sap_despacho_draft_status', return_value={'created': True}), \
             patch.object(views, 'get_sap_despacho_update_status', return_value={'updated': True, 'is_error': False}), \
             patch.object(views, 'verificar_documentos_definitivos', return_value={'completo': True, 'documentos': []}):
            conformidad = self.request(
                views.ajax_operacion_planta_autorizar_salida,
                self.asistente_despacho,
                accion='guardar_conformidad',
                recepcion_conforme='NO',
                observacion_descarga='Carga observada.',
            )
            final = self.request(
                views.ajax_operacion_planta_autorizar_salida,
                self.asistente_despacho,
            )
        self.assertEqual(conformidad.status_code, 200, conformidad.content)
        self.assertEqual(final.status_code, 200, final.content)
        self.assertEqual(
            views._payload_autorizar_salida(self.citacion)['recepcion_conforme'],
            'NO',
        )

    def test_responsable_autorizacion_es_despacho_y_recepcion_queda_solo_lectura(self):
        self.estanque()
        self.preparar_autorizacion()
        responsables = dict(views.obtener_pasos_operacion_citacion(self.citacion)[1])
        self.assertEqual(responsables[views.PASO_AUTORIZAR_SALIDA], ['ASISTENTE DESPACHO'])
        self.assertTrue(views.usuario_puede_paso_operacion(
            self.asistente_despacho,
            responsables[views.PASO_AUTORIZAR_SALIDA],
        ))
        self.assertFalse(views.usuario_puede_paso_operacion(
            self.asistente_recepcion,
            responsables[views.PASO_AUTORIZAR_SALIDA],
        ))
        self.assertEqual(self.guardar_ultimas().status_code, 200)
        for usuario in (self.usuario, self.asistente_recepcion):
            response = self.request(
                views.ajax_operacion_planta_autorizar_salida,
                usuario,
                accion='guardar_conformidad',
                recepcion_conforme='SI',
            )
            self.assertEqual(response.status_code, 403)

    def test_dos_estanques_puntos_y_horarios_propios_avance_requiere_ambos(self):
        self.dos_estanques()
        self.assertEqual(self.payload()['estanques_finalizados'], 0)
        inicio1 = datetime(2026, 9, 14, 13, 5, tzinfo=dt_timezone.utc)
        fin1 = datetime(2026, 9, 14, 13, 42, tzinfo=dt_timezone.utc)
        inicio2 = datetime(2026, 9, 14, 13, 50, tzinfo=dt_timezone.utc)
        fin2 = datetime(2026, 9, 14, 14, 18, tzinfo=dt_timezone.utc)
        with patch.object(views.timezone, 'now', return_value=inicio1):
            self.assertEqual(self.iniciar().status_code, 200)
        with patch.object(views.timezone, 'now', return_value=fin1):
            self.assertEqual(self.finalizar().status_code, 200)
        self.assertEqual(self.payload()['estanques_finalizados'], 1)
        self.assertEqual(self.payload()['cargas'][1]['estado'], 'PENDIENTE')
        self.assertEqual(self.avanzar().status_code, 409)
        with patch.object(views.timezone, 'now', return_value=inicio2):
            self.assertEqual(self.iniciar('TKMX01', 'L4.5 - TKMIX').status_code, 200)
        with patch.object(views.timezone, 'now', return_value=fin2):
            self.assertEqual(self.finalizar('TKMX01').status_code, 200)
        cargas = self.metadata()['cargas_por_estanque']
        self.assertEqual(cargas['TK04']['punto_despacho'], 'L1')
        self.assertEqual(cargas['TKMX01']['punto_despacho'], 'L4.5 - TKMIX')
        self.assertEqual(cargas['TK04']['inicio'], inicio1.isoformat())
        self.assertEqual(cargas['TKMX01']['inicio'], inicio2.isoformat())
        self.assertEqual(cargas['TK04']['fin'], fin1.isoformat())
        self.assertEqual(cargas['TKMX01']['fin'], fin2.isoformat())
        self.assertEqual(cargas['TK04']['duracion_segundos'], 37 * 60)
        self.assertEqual(cargas['TKMX01']['duracion_segundos'], 28 * 60)
        self.assertEqual(self.payload()['estanques_finalizados'], 2)
        self.assertEqual(self.avanzar().status_code, 200)
        for whs in cargas:
            self.assertEqual(cargas[whs]['usuario_id'], self.usuario.id)
            self.assertEqual(cargas[whs]['usuario_fin_id'], self.usuario.id)

    def test_puede_haber_ambos_en_carga_sin_copiar_el_estado(self):
        self.dos_estanques()
        self.iniciar()
        self.iniciar('TKMX01', 'L2')
        self.assertEqual([c['estado'] for c in self.payload()['cargas']], ['EN_CARGA', 'EN_CARGA'])
        self.finalizar()
        self.assertEqual([c['estado'] for c in self.payload()['cargas']], ['FINALIZADO', 'EN_CARGA'])
        self.assertFalse(self.payload()['finalizada'])

    def test_warehouse_arbitrario_punto_invalido_y_falta_warehouse_rechazados(self):
        self.estanque()
        for whs, punto in (('AJENO', 'L1'), ('', 'L1'), ('TK04', 'BOMBA_INVENTADA')):
            self.assertEqual(self.iniciar(whs, punto).status_code, 400)
        self.assertEqual(self.finalizar('AJENO').status_code, 400)
        self.assertEqual(self.finalizar().status_code, 400)
        self.assertIsNone(self.metadata())

    def test_permisos_empresa_y_etapa_activa(self):
        self.estanque()
        self.assertEqual(self.iniciar(user=self.guardia).status_code, 403)
        self.assertEqual(self.iniciar(user=self.ajeno).status_code, 403)
        USERS_EMPRESA.objects.filter(US_NID=self.usuario).delete()
        self.assertEqual(self.iniciar().status_code, 403)
        USERS_EMPRESA.objects.create(US_NID=self.usuario, EP_NID=self.empresa)
        OPERACION_PLANTA_LOG.objects.filter(OPL_CPASO=views.PASO_APROBAR_INICIO_CARGA).delete()
        self.assertEqual(self.iniciar().status_code, 409)

    def test_agrupa_dos_acuerdos_compatibles_y_suma_lote_compartido(self):
        self.estanque(lotes=(('A', '20'),))
        otro = self.nuevo_acuerdo(3584, '426', '7.5')
        self.estanque(acuerdo=otro, lotes=(('A', '7.5'),))
        payload = self.payload()
        self.assertEqual(payload['cantidad_estanques'], 1)
        self.assertEqual(payload['cargas'][0]['cantidad'], Decimal('27.5'))
        self.assertEqual(payload['cargas'][0]['lotes'], [{'batch_number': 'A', 'cantidad': Decimal('27.5')}])
        self.assertEqual(payload['cargas'][0]['acuerdos'], ['429', '426'])

    def test_productos_incompatibles_bloquean_inicio_y_avance(self):
        self.estanque(lotes=(('A', '20'),))
        otro = self.nuevo_acuerdo(3584, '426', '7.5')
        self.estanque(acuerdo=otro, lotes=(('B', '7.5'),), item='OTRO_PRODUCTO')
        self.assertIn('incompatibles', self.payload()['error_carga'])
        self.assertEqual(self.iniciar().status_code, 400)
        self.assertEqual(self.avanzar().status_code, 409)
        self.assertIsNone(self.metadata())

    def test_sin_carga_no_inventa_estanques_ni_avanza(self):
        self.assertIn('no contiene estanques', self.payload()['error_carga'])
        self.assertEqual(self.iniciar().status_code, 400)
        self.assertEqual(self.avanzar().status_code, 409)

    def test_reintentos_no_sobrescriben_punto_tiempos_ni_duplican_logs(self):
        self.estanque()
        self.iniciar()
        inicial = self.metadata()['cargas_por_estanque']['TK04'].copy()
        self.assertEqual(self.iniciar().status_code, 200)
        self.assertEqual(self.iniciar(punto='L2').status_code, 400)
        self.assertEqual(self.metadata()['cargas_por_estanque']['TK04'], inicial)
        self.finalizar()
        final = self.metadata()['cargas_por_estanque']['TK04'].copy()
        self.assertEqual(self.finalizar().status_code, 200)
        self.assertEqual(self.iniciar().status_code, 400)
        self.assertEqual(self.metadata()['cargas_por_estanque']['TK04'], final)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(OPL_CPASO__startswith='CICLO_DESPACHO_CARGA_TK04').count(), 2)

    def test_trasvasije_y_patio_se_conservan_y_no_completan_carga_fisica(self):
        self.dos_estanques()
        self.iniciar()
        for proceso in ('trasvasije', 'patio_linea_ferrea'):
            self.assertEqual(self.request(views.ajax_operacion_planta_iniciar_ciclo_descarga, proceso=proceso).status_code, 200)
            self.assertEqual(self.request(views.ajax_operacion_planta_finalizar_proceso_despacho, proceso=proceso).status_code, 200)
        self.assertEqual(set(self.metadata()['procesos_despacho']), {'trasvasije', 'patio_linea_ferrea'})
        self.assertEqual(self.metadata()['cargas_por_estanque']['TK04']['estado'], 'EN_CARGA')
        self.assertFalse(self.payload()['finalizada'])
        self.assertEqual(self.avanzar().status_code, 409)

    def guardar_legacy(self):
        metadata = {'tipo_ciclo': 'CARGA_DESPACHO', 'marca_ajena': 'conservar',
            'procesos_despacho': {'carga': {'inicio': '2026-09-14T13:05:00+00:00',
                'fin': '2026-09-14T13:42:00+00:00', 'estado': 'FINALIZADO',
                'punto_despacho': 'L1', 'usuario': self.usuario.username, 'usuario_fin': self.usuario.username}}}
        views._guardar_metadata_ciclo_descarga(self.citacion, self.usuario, metadata)
        return metadata

    def test_legacy_un_estanque_se_lee_sin_reescribir(self):
        self.estanque()
        self.guardar_legacy()
        antes = DATO_OPERACION.objects.get(CAMP_NID__CA_CCODIGO=views.CAMPO_CICLO_DESCARGA).DO_CVALOR
        payload = self.payload()
        self.assertTrue(payload['finalizada'])
        self.assertTrue(payload['aviso_legacy'])
        self.assertEqual(DATO_OPERACION.objects.get(CAMP_NID__CA_CCODIGO=views.CAMPO_CICLO_DESCARGA).DO_CVALOR, antes)
        self.assertEqual(self.avanzar().status_code, 200)

    def test_legacy_multi_no_reparte_tiempos_ni_habilita_avance(self):
        self.dos_estanques()
        self.guardar_legacy()
        self.assertFalse(self.payload()['finalizada'])
        self.assertEqual(self.payload()['estanques_finalizados'], 0)
        self.assertTrue(self.payload()['aviso_legacy'])
        self.iniciar()
        self.assertEqual(self.metadata()['marca_ajena'], 'conservar')
        self.assertEqual(self.metadata()['procesos_despacho']['carga']['estado'], 'FINALIZADO')
        self.assertEqual(self.avanzar().status_code, 409)

    def test_legacy_sin_distribucion_conserva_lectura_del_historial(self):
        self.guardar_legacy()
        payload = self.payload()
        self.assertTrue(payload['error_carga'])
        self.assertTrue(payload['carga_legacy']['finalizado'])
        self.assertFalse(payload['finalizada'])
        html = render_to_string('home/CITACION/carga_por_estanque.html',
            {'ciclo': payload, 'paso': {'activo': False, 'puede_editar': False}})
        self.assertIn('Registro histórico global', html)
        self.assertIn('13:05', payload['carga_legacy']['inicio_iso'])
        self.assertNotIn('<button ', html)

    def test_endpoint_cierre_global_no_evade_los_estanques(self):
        self.dos_estanques()
        self.iniciar()
        self.finalizar()
        response = self.request(views.ajax_operacion_planta_finalizar_ciclo_descarga, warehouse_code='TK04')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(OPL_CPASO=views.PASO_CICLO_DESCARGA).exists())

    def test_no_se_modifica_distribucion_operacional(self):
        self.dos_estanques()
        antes = views._resumen_carga_operacional_despacho(self.citacion)
        self.iniciar()
        self.finalizar()
        self.assertEqual(views._resumen_carga_operacional_despacho(self.citacion), antes)

    def test_frontend_un_estanque_simple_varios_con_progreso_y_lectura(self):
        self.estanque()
        def render(puede=True):
            return render_to_string('home/CITACION/carga_por_estanque.html', {
                'ciclo': self.payload(), 'paso': {'nombre': views.PASO_CICLO_DESCARGA, 'activo': True, 'puede_editar': puede}})
        html = render()
        self.assertIn('CARGA DESDE TK04', html)
        self.assertNotIn('1 de 1', html)
        self.assertNotIn('<progress ', html)
        self.assertIn('data-warehouse="TK04"', html)
        self.estanque('TKMX01', (('C', '7.5'),))
        html = render()
        self.assertIn('0 de 2 estanques completados', html)
        self.assertIn('CARGA DESDE TKMX01', html)
        self.assertNotIn('<button ', render(False))
        self.iniciar()
        self.finalizar()
        self.assertIn('1 de 2 estanques completados', render())
        self.assertIn('Término:', render())

    def test_fuera_del_ambito_conserva_regla_legacy(self):
        for ep, tipo, codigo in ((2, 'DESPACHO', 'TRASVASIJE_CLIENTE'),
                                 (1, 'DESPACHO', 'DESPACHO_TERRAMAR'),
                                 (2, 'RECEPCION', 'RECEPCION_ESTANQUE_SBH')):
            self.citacion.EP_NID_id = ep
            self.citacion.CI_CTIPO = tipo
            self.citacion.SC_NID.SE_CCODIGO = codigo
            with patch.object(views, '_leer_metadata_ciclo_descarga', return_value={}), \
                 patch.object(views, '_resumen_carga_operacional_despacho') as resumen:
                self.assertNotIn('por_estanque', self.payload())
                resumen.assert_not_called()


class ConcurrenciaCargaEstanqueTests(CargaEstanqueFixture, TransactionTestCase):
    def setUp(self):
        self.preparar_carga()
        self.dos_estanques()

    def ejecutar_concurrentes(self, operaciones):
        barrera = Barrier(2)
        bloquear = views._recargar_citacion_bloqueada_operacion
        def entrar(citacion):
            barrera.wait(timeout=15)
            return bloquear(citacion)
        def ejecutar(operacion):
            try:
                citacion = CITACION.objects.select_related('SC_NID', 'EP_NID').get(pk=self.citacion.pk)
                return views._registrar_proceso_ciclo_carga_despacho(citacion, self.usuario, *operacion)
            finally:
                connections.close_all()
        with patch.object(views, '_recargar_citacion_bloqueada_operacion', side_effect=entrar):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(ejecutar, operacion) for operacion in operaciones]
                for future in futures:
                    future.result(timeout=30)

    @skipUnlessDBFeature('has_select_for_update')
    def test_inicios_simultaneos_conservan_ambos_warehouses(self):
        self.ejecutar_concurrentes([('carga', 'L1', 'TK04'), ('carga', 'L2', 'TKMX01')])
        self.assertEqual(set(self.metadata()['cargas_por_estanque']), {'TK04', 'TKMX01'})

    @skipUnlessDBFeature('has_select_for_update')
    def test_carga_y_trasvasije_simultaneos_conservan_ambas_secciones(self):
        self.ejecutar_concurrentes([('carga', 'L1', 'TK04'), ('trasvasije', '', '')])
        self.assertIn('TK04', self.metadata()['cargas_por_estanque'])
        self.assertIn('trasvasije', self.metadata()['procesos_despacho'])
