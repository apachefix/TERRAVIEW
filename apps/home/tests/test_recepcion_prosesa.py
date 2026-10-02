import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMPO,
    CAMION_PATIO,
    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    CITACION_ITEM,
    CITACION_PROSESA_RELACION,
    DATO_OPERACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    ITEM,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    PERFIL,
    PERFIL_USUARIO,
    REGION,
    PROVINCIA,
    COMUNA,
    RUTA,
    SECUENCIA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
    USERS_EMPRESA,
)
from apps.home.views import (
    CIT_TERMINADO,
    CAMPO_PROSESA_BASE_LINE_SAP,
    CAMPO_PROSESA_PISO2_PATENTE_RETIRO,
    CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
    CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID,
    CAMPO_PROSESA_PESO_REAL_INSUMO,
    ESTADO_PROSESA_ESPERANDO_RETIRO,
    PASO_BORRADOR_SAP,
    PASOS_RECEPCION_BODEGA_EXTERNA,
    PASO_PROSESA_DEPOSITAR_PISO_1,
    PASO_PROSESA_RETIRAR_CONTENEDOR,
    PASO_PROSESA_TRASLADO_MANUAL,
    PASO_PROSESA_INICIO_RETIRO,
    PASOS_RECEPCION_PROSESA_PISO_2,
    SECUENCIA_RECEPCION_PROSESA_PISO_1,
    SECUENCIA_RECEPCION_PROSESA_PISO_2,
    _cerrar_operacion_prosesa,
    calcular_y_persistir_peso_real_prosesa,
    citaciones_prosesa_piso_2_pendientes_por_patente,
    validar_camion_retiro_planificado_prosesa_piso_2,
    asegurar_flujos_recepcion_etapa_0,
    es_recepcion_prosesa_piso_1,
    es_recepcion_prosesa_piso_2,
    obtener_pasos_operacion_citacion,
    preparar_item_prosesa_piso_2_desde_origen,
    resolver_base_line_prosesa_piso_1,
    resolver_contenedor_prosesa_piso_1,
    resolver_guia_prosesa_piso_1,
    resolver_pesajes_prosesa,
    validar_cierre_prosesa_piso_2,
)


class RecepcionProsesaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user('prosesa_test', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Prosesa',
            CA_FHORA_APERTURA='08:00',
            CA_FHORA_CIERRE='18:00',
            CA_NDIA=17,
            CA_NMES=9,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia_piso_1 = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO=SECUENCIA_RECEPCION_PROSESA_PISO_1,
            SE_CNOMBRE='RECEPCION PROSESA PISO 1',
            SE_BHABILITADO=True,
        )
        cls.secuencia_piso_2 = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO=SECUENCIA_RECEPCION_PROSESA_PISO_2,
            SE_CNOMBRE='RECEPCION PROSESA PISO 2',
            SE_BHABILITADO=True,
        )
        cls.secuencia_legacy = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA',
            SE_CNOMBRE='RECEPCION BODEGA EXTERNA',
            SE_BHABILITADO=True,
        )
        cls.etapa_inicial = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='ETAPA_0_PROSESA_TEST',
            ET_CNOMBRE='Etapa 0 Prosesa Test',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        for secuencia in (cls.secuencia_piso_1, cls.secuencia_piso_2, cls.secuencia_legacy):
            DETALLE_SECUENCIA.objects.create(
                US_NID=cls.usuario,
                EP_NID=cls.empresa,
                SC_NID=secuencia,
                ET_NID=cls.etapa_inicial,
                SE_NPASO=1,
                SE_BOBLIGATORIO=True,
                SE_BHABILITADO=True,
            )
        cls.cliente = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='C001',
            SN_CRAZONSOCIAL='Cliente Prosesa',
            SN_CRUT='11-1',
            SN_CTIPO='C',
        )
        cls.proveedor = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='P001',
            SN_CRAZONSOCIAL='Proveedor Prosesa',
            SN_CRUT='22-2',
            SN_CTIPO='S',
        )
        cls.transportista = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='T001',
            SN_CRAZONSOCIAL='Transporte Prosesa',
            SN_CRUT='33-3',
            SN_CTIPO='S',
        )
        cls.item_maestro = ITEM.objects.create(
            id=26,
            EP_NID=cls.empresa,
            IT_CCODIGO='ITEM-1',
            IT_CNOMBRE='Aceite',
        )
        ahora = timezone.now()
        cls.origen = CITACION.objects.create(
            id=38724,
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia_piso_1,
            SN_NID=cls.cliente,
            PRO_NID=cls.proveedor,
            CI_FFECHAREGISTRO=ahora,
            CI_FFECHACITACION=ahora,
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CTIPO_FLETE='CONTENEDOR',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-PROSESA-1',
        )
        cls.retiro = CITACION.objects.create(
            id=38729,
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia_piso_2,
            SN_NID=cls.cliente,
            PRO_NID=cls.proveedor,
            CI_FFECHAREGISTRO=ahora,
            CI_FFECHACITACION=ahora,
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CTIPO_FLETE='CONTENEDOR',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-PROSESA-1',
        )
        cls.legacy = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia_legacy,
            CI_FFECHAREGISTRO=ahora,
            CI_FFECHACITACION=ahora,
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.origen,
            EP_NID=cls.empresa,
            US_NID=cls.usuario,
            CDO_CORIGEN='manual',
            CDO_CCODIGO_SAP='ITEM-1',
            CDO_CINSUMO='Aceite',
            CDO_CPEDIDO_SAP='4500001',
            CDO_CPROVEEDOR_CODIGO='P001',
            CDO_CBL_CONTENEDOR='CONT-1',
            CDO_CGUIA='GUIA-PROSESA-1',
            CDO_CPRODUCTOR='Proveedor Prosesa',
            CDO_CTIPO_RECEPCION='NACIONAL',
            CDO_CALMACEN_DESTINO='PROSESA',
            CDO_CESTANQUE_DESTINO='PROSE_G2',
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.retiro,
            EP_NID=cls.empresa,
            US_NID=cls.usuario,
            CDO_CORIGEN='prosesa_piso_2',
            CDO_CCODIGO_SAP='ITEM-1',
            CDO_CINSUMO='Aceite',
            CDO_CPEDIDO_SAP='4500001',
            CDO_CPROVEEDOR_CODIGO='P001',
            CDO_CBL_CONTENEDOR='CONT-1',
            CDO_CGUIA='GUIA-PROSESA-1',
            CDO_CPRODUCTOR='Proveedor Prosesa',
            CDO_CTIPO_RECEPCION='NACIONAL',
            CDO_CALMACEN_DESTINO='PROSESA',
            CDO_CESTANQUE_DESTINO='PROSE_G2',
        )
        CITACION_ITEM.objects.create(
            CI_NID=cls.origen,
            EP_NID=cls.empresa,
            IT_NID=cls.item_maestro,
        )
        cls.relacion = CITACION_PROSESA_RELACION.objects.create(
            EP_NID=cls.empresa,
            CI_NID_ORIGEN=cls.origen,
            CI_NID_RETIRO=cls.retiro,
            US_NID=cls.usuario,
        )
        for citacion, patente in ((cls.origen, 'PISO1'), (cls.retiro, 'PISO2')):
            CAMION_PATIO.objects.create(
                EP_NID=cls.empresa,
                CI_NID=citacion,
                CPA_CPATENTE=patente,
                CPA_CNOMBRE_CONDUCTOR='Conductor ' + patente,
                CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
                CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
                US_GUARDIA_ID=cls.usuario,
            )

    def _crear_ticket_prosesa(self, citacion, tipo, peso_bruto, patente):
        campo = CAMPO.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            CA_CTIPO='NUMERO',
            CA_CCODIGO=f'OP_TICKET_PESAJE_{tipo}',
            CA_CETIQUETA=f'Ticket {tipo}',
            CA_BHABILITADO=True,
        )
        paso = 'Pesaje Entrada' if tipo == 'ENT' else 'Pesaje Salida'
        return DATO_OPERACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            SC_NID=citacion.SC_NID,
            ET_NID=self.etapa_inicial,
            CAMP_NID=campo,
            CI_NID=citacion,
            DO_NPESO=peso_bruto,
            DO_CVALOR=json.dumps({
                'folio': f'{citacion.id}-{tipo}',
                'peso_neto': peso_bruto,
                'peso_bruto_kg': peso_bruto,
                'patente': patente,
                'tipo_ticket': tipo,
                'citacion_id': citacion.id,
                'paso_operacion': paso,
            }),
            DO_FFECHAREGISTRO=timezone.now(),
        )

    def _crear_dato_texto(self, citacion, codigo, valor):
        campo = CAMPO.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            CA_CTIPO='TEXTO',
            CA_CCODIGO=codigo,
            CA_CETIQUETA=codigo,
            CA_BHABILITADO=True,
        )
        return DATO_OPERACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            SC_NID=citacion.SC_NID,
            ET_NID=self.etapa_inicial,
            CAMP_NID=campo,
            CI_NID=citacion,
            DO_CVALOR=valor,
            DO_FFECHAREGISTRO=timezone.now(),
        )

    def _crear_cuatro_pesajes_validos(self):
        return {
            'p1_ent': self._crear_ticket_prosesa(
                self.origen, 'ENT', 32000, 'PISO1'
            ),
            'p1_sal': self._crear_ticket_prosesa(
                self.origen, 'SAL', 12000, 'PISO1'
            ),
            'p2_ent': self._crear_ticket_prosesa(
                self.retiro, 'ENT', 11000, 'PISO2'
            ),
            'p2_sal': self._crear_ticket_prosesa(
                self.retiro, 'SAL', 14000, 'PISO2'
            ),
        }

    def _completar_retiro_temporal(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            PL_NID=self.planificacion, CI_NID=self.retiro,
            OPL_CPASO='Pesaje Entrada', OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        inicio, creado = views._iniciar_retiro_temporal_prosesa_piso_2(self.retiro, self.usuario)
        self.assertTrue(creado)
        self.assertTrue(inicio['iniciada'])
        salida, creado = views._validar_salida_temporal_prosesa_piso_2(self.retiro, self.usuario)
        self.assertTrue(creado)
        self.assertTrue(salida['salida_validada'])
        retorno, creado = views._finalizar_retiro_temporal_prosesa_piso_2(self.retiro, self.usuario)
        self.assertTrue(creado)
        self.assertTrue(retorno['finalizada'])
        for paso, perfil in (('Pesaje Salida', 'OPERADOR ROMANA'), ('Autorizar Salida', 'ASISTENTE RECEPCION')):
            OPERACION_PLANTA_LOG.objects.create(
                US_NID=self.usuario, EP_NID=self.empresa,
                PL_NID=self.planificacion, CI_NID=self.retiro,
                OPL_CPASO=paso, OPL_CPERFIL_RESPONSABLE=perfil,
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )
        return retorno

    def test_flujos_prosesa_son_independientes_y_no_incluyen_sap(self):
        self.assertTrue(es_recepcion_prosesa_piso_1(self.origen))
        self.assertTrue(es_recepcion_prosesa_piso_2(self.retiro))
        self.assertFalse(es_recepcion_prosesa_piso_1(self.legacy))
        nombre_1, pasos_1 = obtener_pasos_operacion_citacion(self.origen)
        nombre_2, pasos_2 = obtener_pasos_operacion_citacion(self.retiro)
        self.assertEqual(nombre_1, 'RECEPCION PROSESA PISO 1')
        self.assertEqual(nombre_2, 'RECEPCION PROSESA PISO 2')
        self.assertIn(PASO_PROSESA_DEPOSITAR_PISO_1, [paso for paso, _ in pasos_1])
        self.assertEqual(pasos_2, PASOS_RECEPCION_PROSESA_PISO_2)
        self.assertNotIn(PASO_PROSESA_RETIRAR_CONTENEDOR, [paso for paso, _ in pasos_2])
        self.assertNotIn(PASO_PROSESA_TRASLADO_MANUAL, [paso for paso, _ in pasos_2])
        self.assertNotIn('ASISTENTE C D', [perfil for _, perfiles in pasos_2 for perfil in perfiles])
        self.assertNotIn(PASO_BORRADOR_SAP, [paso for paso, _ in pasos_1 + pasos_2])

    def test_piso_2_hereda_snapshot_operacional_sin_datos_de_camion(self):
        item = preparar_item_prosesa_piso_2_desde_origen({}, self.origen)
        self.assertEqual(item['guia'], 'GUIA-PROSESA-1')
        self.assertEqual(item['codigo_sap'], 'ITEM-1')
        self.assertEqual(item['cliente'], str(self.cliente.id))
        self.assertEqual(item['proveedor'], str(self.proveedor.id))
        self.assertEqual(item['tipo_carga'], 'CONTENEDOR')
        self.assertNotIn('patente', item)
        self.assertNotIn('conductor', item)

    def test_cierre_piso_1_espera_retiro_y_cierra_solo_camion(self):
        fecha = timezone.now()
        self.assertTrue(_cerrar_operacion_prosesa(self.origen, fecha))
        self.origen.refresh_from_db()
        self.assertEqual(self.origen.CI_CESTADO, ESTADO_PROSESA_ESPERANDO_RETIRO)
        self.assertIsNone(self.origen.CI_FFECHATERMINO)
        camion = CAMION_PATIO.objects.get(CI_NID=self.origen)
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)

    def test_cierre_piso_2_finaliza_ambas_citaciones(self):
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        self._crear_cuatro_pesajes_validos()
        calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        self._completar_retiro_temporal()
        fecha = timezone.now()
        self.assertTrue(_cerrar_operacion_prosesa(self.retiro, fecha))
        self.origen.refresh_from_db()
        self.retiro.refresh_from_db()
        self.assertEqual(self.origen.CI_CESTADO, CIT_TERMINADO)
        self.assertEqual(self.retiro.CI_CESTADO, CIT_TERMINADO)
        self.assertEqual(self.origen.CI_FFECHATERMINO, fecha)
        self.assertEqual(self.retiro.CI_FFECHATERMINO, fecha)
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        porteria = self._usuario_operacional('porteria_cierre_piso2', 'GUARDIA_PORTERIA')
        self._iniciar_sesion_operacional(porteria)
        estado = self.client.get(reverse('estado_camion_ajax'), {
            'patente': 'PISO2', '_empresa_id': 2,
        }).json()
        self.assertEqual(estado['tipo_resultado'], 'SIN_CITACION_VIGENTE')
        self.assertNotIn('data', estado)

    def test_calculo_usa_cuatro_pesadas_y_persiste_17000_kg(self):
        fuentes = self._crear_cuatro_pesajes_validos()
        dato, actualizado = calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )

        self.assertTrue(actualizado)
        self.assertEqual(dato.DO_NPESO, 17000)
        metadata = json.loads(dato.DO_CVALOR)
        self.assertEqual(metadata['peso_contenedor_cargado'], 20000)
        self.assertEqual(metadata['peso_contenedor_vacio'], 3000)
        self.assertEqual(metadata['peso_real_insumo'], 17000)
        self.assertNotEqual(metadata['peso_real_insumo'], 32000 - 14000)
        self.assertEqual(metadata['patente_piso1'], 'PISO1')
        self.assertEqual(metadata['patente_piso2'], 'PISO2')
        self.assertEqual(metadata['p1_ent_dato_id'], fuentes['p1_ent'].id)
        self.assertEqual(metadata['p1_sal_dato_id'], fuentes['p1_sal'].id)
        self.assertEqual(metadata['p2_ent_dato_id'], fuentes['p2_ent'].id)
        self.assertEqual(metadata['p2_sal_dato_id'], fuentes['p2_sal'].id)
        recuperado = DATO_OPERACION.objects.get(
            CI_NID=self.retiro,
            CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PESO_REAL_INSUMO,
        )
        self.assertEqual(recuperado.DO_NPESO, 17000)

    def test_parser_prosesa_conserva_brutos_sin_cambiar_peso_neto_sal(self):
        pagina = type('Pagina', (), {})()
        pagina.extract_text = lambda: (
            'Folio Nro: 123456\n'
            '25-09-2026 10:00 32.000\n'
            '25-09-2026 11:00 12.000\n'
            'Peso Neto 20.000\n'
        )
        lector = type('Lector', (), {'pages': [pagina]})()
        with patch('apps.home.views.PdfReader', return_value=lector), patch(
            'builtins.open',
        ):
            datos = views._extraer_datos_ticket_pesaje(
                'ticket.pdf',
                'SAL',
                conservar_pesos_brutos=True,
            )
        self.assertEqual(datos['peso_neto'], 20000)
        self.assertEqual(datos['peso_entrada_kg'], 32000)
        self.assertEqual(datos['peso_salida_bruto_kg'], 12000)
        self.assertEqual(datos['peso_bruto_kg'], 12000)

    def test_finalizar_pesaje_salida_piso_2_deja_calculo_explicitamente_pendiente(self):
        self._crear_cuatro_pesajes_validos()
        request = RequestFactory().post(
            f'/operacion-planta/{self.retiro.id}/guardar-paso/',
            {'paso': 'Pesaje Salida', 'observacion': ''},
        )
        request.user = self.usuario
        with patch(
            'apps.home.views.usuario_es_operacion_planta',
            return_value=True,
        ), patch(
            'apps.home.views.Verificar_empresa',
            return_value=self.empresa.id,
        ), patch(
            'apps.home.views.citacion_habilitada_operacion',
            return_value=True,
        ), patch(
            'apps.home.views.operacion_planta_esta_terminada',
            return_value=False,
        ), patch(
            'apps.home.views.obtener_pasos_operacion_citacion',
            return_value=(
                'RECEPCION PROSESA PISO 2',
                [('Pesaje Salida', ['OPERADOR ROMANA'])],
            ),
        ), patch(
            'apps.home.views.resolver_estado_operacional_visible',
            return_value='Pesaje Salida',
        ), patch(
            'apps.home.views.usuario_puede_paso_operacion',
            return_value=True,
        ), patch(
            'apps.home.views._ticket_pesaje_obligatorio_guardado',
            return_value=True,
        ), patch(
            'apps.home.views.liberar_reservas_estanque_citacion',
        ):
            response = views.OPERACION_PLANTA_GUARDAR_PASO(
                request,
                self.retiro.id,
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DATO_OPERACION.objects.filter(
            CI_NID=self.retiro,
            CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PESO_REAL_INSUMO,
        ).exists())

    def test_calculo_es_idempotente_con_las_mismas_fuentes(self):
        self._crear_cuatro_pesajes_validos()
        primero, creado = calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        segundo, actualizado = calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        self.assertTrue(creado)
        self.assertFalse(actualizado)
        self.assertEqual(primero.id, segundo.id)
        self.assertEqual(
            DATO_OPERACION.objects.filter(
                CI_NID=self.retiro,
                CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PESO_REAL_INSUMO,
            ).count(),
            1,
        )

    def test_cambio_controlado_de_fuente_actualiza_y_deja_historial(self):
        fuentes = self._crear_cuatro_pesajes_validos()
        calculo, _ = calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        fuente_anterior = fuentes['p2_sal'].id
        fuentes['p2_sal'].delete()
        nueva_fuente = self._crear_ticket_prosesa(
            self.retiro, 'SAL', 15000, 'PISO2'
        )
        actualizado, cambio = calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        metadata = json.loads(actualizado.DO_CVALOR)
        self.assertTrue(cambio)
        self.assertEqual(actualizado.id, calculo.id)
        self.assertEqual(actualizado.DO_NPESO, 16000)
        self.assertEqual(metadata['p2_sal_dato_id'], nueva_fuente.id)
        self.assertEqual(
            metadata['historial_calculos'][0]['fuentes']['p2_sal_dato_id'],
            fuente_anterior,
        )

    def test_contenedor_distinto_bloquea_calculo(self):
        self._crear_cuatro_pesajes_validos()
        detalle = self.retiro.detalle_operacional
        detalle.CDO_CBL_CONTENEDOR = 'OTRO-CONTENEDOR'
        detalle.save(update_fields=['CDO_CBL_CONTENEDOR'])
        with self.assertRaisesMessage(ValueError, 'no coincide'):
            calcular_y_persistir_peso_real_prosesa(
                self.relacion,
                self.usuario,
            )

    def test_cada_ticket_faltante_bloquea_resolucion(self):
        configuracion = (
            ('p1_ent', self.origen, 'ENT', 32000, 'PISO1'),
            ('p1_sal', self.origen, 'SAL', 12000, 'PISO1'),
            ('p2_ent', self.retiro, 'ENT', 11000, 'PISO2'),
            ('p2_sal', self.retiro, 'SAL', 14000, 'PISO2'),
        )
        for faltante, *_ in configuracion:
            with self.subTest(faltante=faltante):
                DATO_OPERACION.objects.filter(
                    CAMP_NID__CA_CCODIGO__in={
                        'OP_TICKET_PESAJE_ENT',
                        'OP_TICKET_PESAJE_SAL',
                    },
                ).delete()
                for clave, citacion, tipo, peso, patente in configuracion:
                    if clave != faltante:
                        self._crear_ticket_prosesa(
                            citacion, tipo, peso, patente
                        )
                with self.assertRaisesMessage(ValueError, f'Falta {faltante.upper()}'):
                    resolver_pesajes_prosesa(self.relacion)

    def test_peso_contenedor_cargado_no_positivo_bloquea(self):
        self._crear_ticket_prosesa(self.origen, 'ENT', 12000, 'PISO1')
        self._crear_ticket_prosesa(self.origen, 'SAL', 12000, 'PISO1')
        self._crear_ticket_prosesa(self.retiro, 'ENT', 11000, 'PISO2')
        self._crear_ticket_prosesa(self.retiro, 'SAL', 14000, 'PISO2')
        with self.assertRaisesMessage(ValueError, 'contenedor cargado'):
            calcular_y_persistir_peso_real_prosesa(
                self.relacion,
                self.usuario,
            )

    def test_peso_contenedor_vacio_no_positivo_bloquea(self):
        self._crear_ticket_prosesa(self.origen, 'ENT', 32000, 'PISO1')
        self._crear_ticket_prosesa(self.origen, 'SAL', 12000, 'PISO1')
        self._crear_ticket_prosesa(self.retiro, 'ENT', 14000, 'PISO2')
        self._crear_ticket_prosesa(self.retiro, 'SAL', 14000, 'PISO2')
        with self.assertRaisesMessage(ValueError, 'contenedor vacio'):
            calcular_y_persistir_peso_real_prosesa(
                self.relacion,
                self.usuario,
            )

    def test_peso_real_no_positivo_bloquea(self):
        self._crear_ticket_prosesa(self.origen, 'ENT', 15000, 'PISO1')
        self._crear_ticket_prosesa(self.origen, 'SAL', 12000, 'PISO1')
        self._crear_ticket_prosesa(self.retiro, 'ENT', 11000, 'PISO2')
        self._crear_ticket_prosesa(self.retiro, 'SAL', 14000, 'PISO2')
        with self.assertRaisesMessage(ValueError, 'peso real del insumo'):
            calcular_y_persistir_peso_real_prosesa(
                self.relacion,
                self.usuario,
            )

    def test_cierre_piso_2_bloqueado_si_falta_calculo(self):
        self._crear_cuatro_pesajes_validos()
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        with self.assertRaisesMessage(ValueError, 'Debe calcular y validar'):
            _cerrar_operacion_prosesa(self.retiro, timezone.now())
        self.origen.refresh_from_db()
        self.retiro.refresh_from_db()
        self.assertEqual(
            self.origen.CI_CESTADO,
            ESTADO_PROSESA_ESPERANDO_RETIRO,
        )
        self.assertNotEqual(self.retiro.CI_CESTADO, CIT_TERMINADO)

    def test_cierre_piso_2_bloqueado_si_falta_retorno(self):
        self._crear_cuatro_pesajes_validos()
        calcular_y_persistir_peso_real_prosesa(
            self.relacion,
            self.usuario,
        )
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        with self.assertRaisesMessage(ValueError, 'salida temporal y el retorno'):
            _cerrar_operacion_prosesa(self.retiro, timezone.now())
        self.origen.refresh_from_db()
        self.retiro.refresh_from_db()
        self.assertEqual(
            self.origen.CI_CESTADO,
            ESTADO_PROSESA_ESPERANDO_RETIRO,
        )
        self.assertNotEqual(self.retiro.CI_CESTADO, CIT_TERMINADO)

    def test_relacion_impide_un_segundo_retiro_para_mismo_origen(self):
        otro_retiro = CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia_piso_2,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CITACION_PROSESA_RELACION.objects.create(
                EP_NID=self.empresa,
                CI_NID_ORIGEN=self.origen,
                CI_NID_RETIRO=otro_retiro,
                US_NID=self.usuario,
            )

    def test_cierre_legacy_no_es_interceptado_por_prosesa(self):
        estado_original = self.legacy.CI_CESTADO
        self.assertFalse(_cerrar_operacion_prosesa(self.legacy, timezone.now()))
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.CI_CESTADO, estado_original)


    def test_ep_1_no_crea_ni_expone_secuencias_prosesa(self):
        empresa_terramar = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='88-8',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        flujos = asegurar_flujos_recepcion_etapa_0(empresa_terramar.id, self.usuario)
        codigos = {flujo.SE_CCODIGO for flujo in flujos}
        self.assertNotIn(SECUENCIA_RECEPCION_PROSESA_PISO_1, codigos)
        self.assertNotIn(SECUENCIA_RECEPCION_PROSESA_PISO_2, codigos)
        self.assertFalse(SECUENCIA.objects.filter(
            EP_NID=empresa_terramar,
            SE_CCODIGO__in={
                SECUENCIA_RECEPCION_PROSESA_PISO_1,
                SECUENCIA_RECEPCION_PROSESA_PISO_2,
            },
        ).exists())

    def test_descarga_sobre_camion_conserva_configuracion_bodega_externa(self):
        nombre, pasos = obtener_pasos_operacion_citacion(self.legacy)
        esperados = [
            paso for paso in PASOS_RECEPCION_BODEGA_EXTERNA
            if paso[0] != PASO_BORRADOR_SAP
        ]
        self.assertEqual(nombre, 'RECEPCION BODEGA EXTERNA')
        self.assertEqual(pasos, esperados)

    def _item_creacion_piso_1(self, **extra):
        item = {
            'fecha_llegada': '2026-09-17',
            'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencia_piso_1.id),
            'cliente': str(self.cliente.id),
            'cliente_codigo': self.cliente.SN_CCODIGO_SAP,
            'cliente_nombre': self.cliente.SN_CRAZONSOCIAL,
            'proveedor': str(self.proveedor.id),
            'proveedor_codigo': self.proveedor.SN_CCODIGO_SAP,
            'codigo_proveedor_sap': self.proveedor.SN_CCODIGO_SAP,
            'proveedor_nombre': self.proveedor.SN_CRAZONSOCIAL,
            'proveedor_sap': self.proveedor.SN_CRAZONSOCIAL,
            'tipo_carga': 'CONTENEDOR',
            'tipo_origen_recepcion': 'NACIONAL',
            'codigo': 'ITEM-1',
            'codigo_sap': 'ITEM-1',
            'insumo': 'Aceite',
            'pedido': '4500001',
            'sap_opor_id': '6726',
            'docentry': '6726',
            'cantidad_disponible': '28',
            'almacen_destino': 'PROSESA',
            'estanque_destino': 'PROSE_G2',
        }
        item.update(extra)
        return item

    def _respuesta_creacion_items(self, items):
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {
                'flujo': 'INGRESO_MERCADERIA',
                'citaciones_json': json.dumps(items),
            },
        )
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ), patch('apps.home.views.consultar_saldo_linea_pedido_sap', return_value={
            'DocStatus': 'O', 'LineNum': 0, 'OpenQty': '28',
        }):
            return views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)

    def test_piso_1_sin_guia_permite_creacion(self):
        planificaciones_antes = PLANIFICACION.objects.count()
        response = self._respuesta_creacion_items([
            self._item_creacion_piso_1(patente='AA11BB')
        ])
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(len(payload['citaciones']), 1)
        self.assertEqual(
            PLANIFICACION.objects.count(),
            planificaciones_antes + 1,
        )
        citacion = CITACION.objects.get(pk=payload['citaciones'][0])
        self.assertEqual(citacion.SC_NID_id, self.secuencia_piso_1.id)
        self.assertEqual(citacion.detalle_operacional.CDO_CGUIA, '')

    def test_piso_1_sin_patente_permite_creacion(self):
        response = self._respuesta_creacion_items([
            self._item_creacion_piso_1(guia='GUIA-INFORMATIVA')
        ])
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])

    def test_piso_1_no_busca_duplicado_por_guia(self):
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        with CaptureQueriesContext(connection) as queries:
            response = self._respuesta_creacion_items([
                self._item_creacion_piso_1(guia='GUIA-PROSESA-1')
            ])
        self.assertTrue(json.loads(response.content)['success'])
        selects = [
            query['sql'].upper()
            for query in queries.captured_queries
            if query['sql'].lstrip().upper().startswith('SELECT')
        ]
        clausulas_where = [
            sql.partition(' WHERE ')[2]
            for sql in selects
            if ' WHERE ' in sql
        ]
        self.assertFalse(any('CDO_CGUIA' in where for where in clausulas_where))

    def test_piso_1_cantidad_cinco_crea_una_planificacion_y_cinco_citaciones(self):
        datos_replicados = {
            'bl': 'BL-PISO1',
            'contenedor': 'CONT-PISO1',
            'cda': 'CDA-PISO1',
            'di': 'DI-PISO1',
            'nave_naviera': 'NAVIERA PISO1',
            'booking': 'BOOKING-PISO1',
            'fecha_produccion': '01092026',
            'fecha_vencimiento': '01092027',
            'sui': 'SUI-PISO1',
            'observacion': 'Observacion replicada',
        }
        planificaciones_antes = PLANIFICACION.objects.count()
        response = self._respuesta_creacion_items([
            self._item_creacion_piso_1(**datos_replicados)
            for _ in range(5)
        ])
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(PLANIFICACION.objects.count(), planificaciones_antes + 1)
        self.assertEqual(len(payload['citaciones']), 5)
        self.assertEqual(len(set(payload['citaciones'])), 5)

        planificacion = PLANIFICACION.objects.get(pk=payload['planificacion_id'])
        self.assertEqual(planificacion.PL_NCANTIDADCUPOS, 5)
        citaciones = list(
            CITACION.objects.filter(pk__in=payload['citaciones'])
            .select_related('detalle_operacional')
            .order_by('CI_NCUPO')
        )
        self.assertEqual([citacion.CI_NCUPO for citacion in citaciones], [1, 2, 3, 4, 5])
        self.assertEqual(
            {citacion.PL_NID_id for citacion in citaciones},
            {planificacion.id},
        )
        self.assertEqual(
            {citacion.SC_NID_id for citacion in citaciones},
            {self.secuencia_piso_1.id},
        )
        self.assertEqual(
            {citacion.CI_CTIPO_FLETE for citacion in citaciones},
            {'CONTENEDOR'},
        )
        detalles = [citacion.detalle_operacional for citacion in citaciones]
        self.assertEqual(
            {
                (
                    detalle.CDO_CCODIGO_SAP,
                    detalle.CDO_CPEDIDO_SAP,
                    detalle.CDO_CBL,
                    detalle.CDO_CBL_CONTENEDOR,
                    detalle.CDO_CCDA,
                    detalle.CDO_CDI,
                    detalle.CDO_CNAVE_NAVIERA,
                    detalle.CDO_CBOOKING,
                    detalle.CDO_CFECHA_PRODUCCION,
                    detalle.CDO_CFECHA_VENCIMIENTO,
                    detalle.CDO_CSUI,
                    detalle.CDO_CALMACEN_DESTINO,
                    detalle.CDO_CESTANQUE_DESTINO,
                    detalle.CDO_CGUIA,
                )
                for detalle in detalles
            },
            {
                (
                    'ITEM-1',
                    '4500001',
                    'BL-PISO1',
                    'CONT-PISO1',
                    'CDA-PISO1',
                    'DI-PISO1',
                    'NAVIERA PISO1',
                    'BOOKING-PISO1',
                    '01092026',
                    '01092027',
                    'SUI-PISO1',
                    'PROSESA',
                    'PROSE_G2',
                    '',
                )
            },
        )
        self.assertEqual(
            set(
                CITACION_ITEM.objects.filter(
                    CI_NID_id__in=payload['citaciones'],
                ).values_list('IT_NID_id', flat=True)
            ),
            {self.item_maestro.id},
        )

    def test_frontend_piso_1_no_exige_guia_ni_patente(self):
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'No corresponde ingresar guía ni patente en esta etapa.',
            template,
        )
        self.assertIn(
            'Para Contenedor a Piso 2 se solicitará la guía de la Citación 1.',
            template,
        )
        self.assertNotIn(
            'Contenedor a Piso 1 requiere número de guía.',
            template,
        )
        self.assertIn(
            'if (codigoSecuencia === CODIGO_PROSESA_PISO_2)',
            template,
        )
        self.assertNotIn(
            'if ([CODIGO_PROSESA_PISO_1, CODIGO_PROSESA_PISO_2].includes(codigoSecuencia))',
            template,
        )
        self.assertIn('for (let i = 0; i < cantidad; i++)', template)

    def test_modal_recepcion_mantiene_footer_fuera_del_scroll_del_body(self):
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('#ModalCrearCitacion #form_crear_citacion {', template)
        self.assertIn('max-height: none;', template)
        self.assertIn('overflow-y: auto;', template)
        self.assertIn('padding-bottom: 40px;', template)
        self.assertIn('#ModalCrearCitacion .modal-footer {', template)
        self.assertIn('flex: 0 0 auto;', template)

    def _respuesta_creacion_piso_2(
        self, guia_marker, cantidad=1, patente='HGH43',
        empresa_transporte=None, transportista_id=None,
    ):
        item = {
            'fecha_llegada': '2026-09-17',
            'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencia_piso_2.id),
            'patente_retiro_prosesa': patente,
            'empresa_transporte_retiro_prosesa': (
                self.transportista.SN_CRAZONSOCIAL
                if empresa_transporte is None else empresa_transporte
            ),
            'empresa_transporte_retiro_prosesa_id': (
                str(self.transportista.id)
                if transportista_id is None else transportista_id
            ),
        }
        if guia_marker is not None:
            item['guia_origen_prosesa'] = guia_marker
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {
                'flujo': 'INGRESO_MERCADERIA',
                'citaciones_json': json.dumps([
                    dict(item) for _ in range(cantidad)
                ]),
            },
        )
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ):
            return views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)

    def _habilitar_origen_para_retiro(self):
        self.relacion.delete()
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])

    def test_piso_2_encuentra_guia_en_numero_documento_caso_38724(self):
        self._habilitar_origen_para_retiro()
        self.origen.CI_CNUMERODOCUMENTO = '57950'
        self.origen.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle = self.origen.detalle_operacional
        detalle.CDO_CGUIA = ''
        detalle.save(update_fields=['CDO_CGUIA'])
        camion = CAMION_PATIO.objects.get(CI_NID=self.origen)
        camion.CPA_CNUMERO_GUIA = '57950'
        camion.save(update_fields=['CPA_CNUMERO_GUIA'])

        self.assertEqual(
            resolver_guia_prosesa_piso_1(self.origen),
            ('57950', 'CITACION.CI_CNUMERODOCUMENTO'),
        )
        response = self._respuesta_creacion_piso_2('57950')
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(retiro.detalle_operacional.CDO_CGUIA, '57950')
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(CI_NID_ORIGEN=self.origen).CI_NID_RETIRO,
            retiro,
        )

    def test_piso_2_encuentra_guia_en_detalle_operacional(self):
        self._habilitar_origen_para_retiro()
        detalle = self.origen.detalle_operacional
        detalle.CDO_CGUIA = 'GUIA-DETALLE'
        detalle.save(update_fields=['CDO_CGUIA'])

        self.assertEqual(
            resolver_guia_prosesa_piso_1(self.origen, 'GUIA-DETALLE'),
            ('GUIA-DETALLE', 'CITACION_DETALLE_OPERACIONAL.CDO_CGUIA'),
        )
        response = self._respuesta_creacion_piso_2('GUIA-DETALLE')
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(retiro.detalle_operacional.CDO_CGUIA, 'GUIA-DETALLE')

    def test_piso_2_encuentra_guia_en_camion_patio(self):
        self._habilitar_origen_para_retiro()
        camion = CAMION_PATIO.objects.get(CI_NID=self.origen)
        camion.CPA_CNUMERO_GUIA = 'GUIA-PATIO'
        camion.save(update_fields=['CPA_CNUMERO_GUIA'])

        self.assertEqual(
            resolver_guia_prosesa_piso_1(self.origen, 'GUIA-PATIO'),
            ('GUIA-PATIO', 'CAMION_PATIO.CPA_CNUMERO_GUIA'),
        )
        response = self._respuesta_creacion_piso_2('GUIA-PATIO')
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(retiro.detalle_operacional.CDO_CGUIA, 'GUIA-PATIO')

    def test_piso_2_rechaza_guia_ambigua(self):
        self._habilitar_origen_para_retiro()
        CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia_piso_1,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=2,
            CI_CTIPO='RECEPCION',
            CI_CESTADO=ESTADO_PROSESA_ESPERANDO_RETIRO,
            CI_CNUMERODOCUMENTO='GUIA-PROSESA-1',
            CI_BHABILITADO=True,
        )
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'coincide con',
            json.loads(response.content)['message'].lower(),
        )

    def test_resolver_contenedor_desde_fuentes_operacionales(self):
        detalle = self.origen.detalle_operacional
        self.assertEqual(
            resolver_contenedor_prosesa_piso_1(self.origen),
            ('CONT-1', 'CITACION_DETALLE_OPERACIONAL.CDO_CBL_CONTENEDOR'),
        )
        detalle.CDO_CBL_CONTENEDOR = ''
        detalle.save(update_fields=['CDO_CBL_CONTENEDOR'])
        dato = self._crear_dato_texto(
            self.origen, 'AR_LOTE_CONTENEDOR', 'CONT-OPERACION'
        )
        self.assertEqual(
            resolver_contenedor_prosesa_piso_1(self.origen),
            ('CONT-OPERACION', 'DATO_OPERACION.AR_LOTE_CONTENEDOR'),
        )
        dato.delete()
        camion = CAMION_PATIO.objects.get(CI_NID=self.origen)
        camion.CPA_CLOTE_CONTENEDOR = 'CONT-PATIO'
        camion.save(update_fields=['CPA_CLOTE_CONTENEDOR'])
        self.assertEqual(
            resolver_contenedor_prosesa_piso_1(self.origen),
            ('CONT-PATIO', 'CAMION_PATIO.CPA_CLOTE_CONTENEDOR'),
        )
        camion.CPA_CLOTE_CONTENEDOR = ''
        camion.save(update_fields=['CPA_CLOTE_CONTENEDOR'])
        self._crear_dato_texto(
            self.origen,
            'OP_TICKET_PESAJE_ENT',
            json.dumps({'contenedor': 'CONT-TICKET'}),
        )
        self.assertEqual(
            resolver_contenedor_prosesa_piso_1(self.origen),
            ('CONT-TICKET', 'DATO_OPERACION.OP_TICKET_PESAJE_ENT.contenedor'),
        )

    def test_piso_2_rechaza_contenedor_ausente(self):
        self._habilitar_origen_para_retiro()
        detalle = self.origen.detalle_operacional
        detalle.CDO_CBL_CONTENEDOR = ''
        detalle.save(update_fields=['CDO_CBL_CONTENEDOR'])
        self.assertEqual(resolver_contenedor_prosesa_piso_1(self.origen), ('', ''))
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(response.status_code, 409)
        self.assertIn('identificador de contenedor', json.loads(response.content)['message'])
        self.assertFalse(
            CITACION_PROSESA_RELACION.objects.filter(CI_NID_ORIGEN=self.origen).exists()
        )

    def test_piso_2_hereda_base_line_sap_definido_en_piso_1(self):
        self._habilitar_origen_para_retiro()
        self._crear_dato_texto(
            self.origen, CAMPO_PROSESA_BASE_LINE_SAP, '1'
        )
        self.assertEqual(
            resolver_base_line_prosesa_piso_1(self.origen),
            ('1', 'DATO_OPERACION.PROSESA_BASE_LINE_SAP'),
        )
        self.assertEqual(
            preparar_item_prosesa_piso_2_desde_origen(
                {'base_line': '9'}, self.origen
            )['base_line'],
            '1',
        )
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro,
                CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_BASE_LINE_SAP,
            ).DO_CVALOR,
            '1',
        )
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(CI_NID_RETIRO=retiro).CI_NID_ORIGEN,
            self.origen,
        )

    def _preparar_caso_38724(self, incluir_ticket=True):
        self._habilitar_origen_para_retiro()
        self.origen.CI_CNUMERODOCUMENTO = '57950'
        self.origen.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle = self.origen.detalle_operacional
        detalle.CDO_CGUIA = ''
        detalle.CDO_CBL_CONTENEDOR = ''
        detalle.CDO_CDOCENTRY = '6880'
        detalle.CDO_CSAP_OPOR_ID = '6880'
        detalle.CDO_CALMACEN_DESTINO = 'PROCESA'
        detalle.CDO_CESTANQUE_DESTINO = 'PROSE_T3'
        detalle.CDO_CBL = 'BL-REAL'
        detalle.CDO_CBOOKING = 'BOOKING-REAL'
        detalle.CDO_CNAVE_NAVIERA = 'NAVIERA-REAL'
        detalle.CDO_CCDA = 'CDA-REAL'
        detalle.CDO_CDI = 'DI-REAL'
        detalle.CDO_CSUI = 'SUI-REAL'
        detalle.CDO_NCANTIDAD_DISPONIBLE = 16412.37
        detalle.save()
        camion = CAMION_PATIO.objects.get(CI_NID=self.origen)
        camion.CPA_CNUMERO_GUIA = '57950'
        camion.CPA_CLOTE_CONTENEDOR = ''
        camion.save(update_fields=['CPA_CNUMERO_GUIA', 'CPA_CLOTE_CONTENEDOR'])
        if incluir_ticket:
            self._crear_dato_texto(
                self.origen,
                'OP_TICKET_PESAJE_ENT',
                json.dumps({'observacion': 'TLLU3391353'}),
            )

    def _cargar_origen_por_endpoint(self, guia):
        self.client.force_login(self.usuario)
        with patch('apps.home.views.Verificar_empresa', return_value=2):
            return self.client.get(
                '/prosesa/piso-2/cargar-origen/', {'guia': guia}
            )

    def test_endpoint_57950_carga_citacion_38724_y_snapshot(self):
        self._preparar_caso_38724()
        self.client.force_login(self.usuario)
        with patch('apps.home.views.Verificar_empresa', return_value=2), CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                '/prosesa/piso-2/cargar-origen/', {'guia': '57950'}
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['citacion_piso_1'], 38724)
        self.assertIn('#38724', payload['message'])
        self.assertFalse(payload['base_line_disponible'])
        datos = payload['datos']
        self.assertEqual(datos['guia'], '57950')
        self.assertEqual(datos['codigo_sap'], 'ITEM-1')
        self.assertEqual(datos['insumo'], 'Aceite')
        self.assertEqual(datos['pedido'], '4500001')
        self.assertEqual(datos['docentry'], '6880')
        self.assertEqual(datos['contenedor'], 'TLLU3391353')
        self.assertEqual(datos['almacen_destino'], 'PROSESA')
        self.assertEqual(datos['estanque_destino'], 'PROSE_T3')
        self.assertEqual(datos['bl'], 'BL-REAL')
        self.assertEqual(datos['booking'], 'BOOKING-REAL')
        self.assertEqual(datos['nave_naviera'], 'NAVIERA-REAL')
        self.assertEqual(datos['cda'], 'CDA-REAL')
        self.assertEqual(datos['di'], 'DI-REAL')
        self.assertEqual(datos['sui'], 'SUI-REAL')
        self.assertEqual(datos['tipo_origen_recepcion'], 'NACIONAL')
        self.assertFalse(any(
            query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
            for query in queries
        ))

    def test_endpoint_informa_base_line_si_esta_definido(self):
        self._preparar_caso_38724()
        self._crear_dato_texto(
            self.origen, CAMPO_PROSESA_BASE_LINE_SAP, '1'
        )
        response = self._cargar_origen_por_endpoint('57950')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['base_line_disponible'])
        self.assertEqual(response.json()['datos']['base_line'], '1')

    def test_endpoint_bloquea_contenedor_ausente_antes_de_agregar(self):
        self._preparar_caso_38724(incluir_ticket=False)
        response = self._cargar_origen_por_endpoint('57950')
        self.assertEqual(response.status_code, 409)
        self.assertIn('identificador de contenedor', response.json()['message'])

    def test_endpoint_guia_inexistente_y_ambigua(self):
        self._preparar_caso_38724()
        response = self._cargar_origen_por_endpoint('GUIA-INEXISTENTE')
        self.assertEqual(response.status_code, 404)
        self.assertIn('No existe', response.json()['message'])
        CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia_piso_1,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=2,
            CI_CTIPO='RECEPCION',
            CI_CESTADO=ESTADO_PROSESA_ESPERANDO_RETIRO,
            CI_CNUMERODOCUMENTO='57950',
            CI_BHABILITADO=True,
        )
        response = self._cargar_origen_por_endpoint('57950')
        self.assertEqual(response.status_code, 409)
        self.assertIn('coincide con', response.json()['message'])

    def test_endpoint_bloquea_piso_1_ya_relacionado(self):
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.CI_CNUMERODOCUMENTO = '57950'
        self.origen.save(update_fields=['CI_CESTADO', 'CI_CNUMERODOCUMENTO'])
        response = self._cargar_origen_por_endpoint('57950')
        self.assertEqual(response.status_code, 409)
        self.assertIn('ya tiene una', response.json()['message'])

    def test_json_del_snapshot_crea_planificacion_piso_2_y_relacion(self):
        self._preparar_caso_38724()
        self._crear_dato_texto(
            self.origen, CAMPO_PROSESA_BASE_LINE_SAP, '1'
        )
        datos = self._cargar_origen_por_endpoint('57950').json()['datos']
        item = {
            'fecha_llegada': '2026-09-17',
            'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencia_piso_2.id),
            **datos,
            'guia_origen_prosesa': '57950',
            'patente_retiro_prosesa': 'HGH43',
            'empresa_transporte_retiro_prosesa': self.transportista.SN_CRAZONSOCIAL,
            'empresa_transporte_retiro_prosesa_id': str(self.transportista.id),
            '_prosesa_origen_id': 38724,
        }
        enviado = json.loads(json.dumps([item]))[0]
        for clave in (
            'guia_origen_prosesa', '_prosesa_origen_id', 'codigo_sap',
            'proveedor', 'docentry', 'base_line', 'contenedor',
            'almacen_destino', 'estanque_destino',
        ):
            self.assertIn(clave, enviado)
        self.assertEqual(enviado['base_line'], '1')
        self.assertEqual(enviado['almacen_destino'], 'PROSESA')
        response = self._respuesta_creacion_items([enviado])
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'], payload.get('message'))
        self.assertTrue(PLANIFICACION.objects.filter(pk=payload['planificacion_id']).exists())
        retiro = CITACION.objects.get(pk=payload['citaciones'][0])
        self.assertEqual(retiro.detalle_operacional.CDO_CBL_CONTENEDOR, 'TLLU3391353')
        self.assertEqual(retiro.detalle_operacional.CDO_CALMACEN_DESTINO, 'PROSESA')
        self.assertEqual(retiro.detalle_operacional.CDO_CESTANQUE_DESTINO, 'PROSE_T3')
        self.assertEqual(retiro.detalle_operacional.CDO_CDOCENTRY, '6880')
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro,
                CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_BASE_LINE_SAP,
            ).DO_CVALOR,
            '1',
        )
        relacion = CITACION_PROSESA_RELACION.objects.get(CI_NID_ORIGEN=self.origen)
        self.assertEqual(relacion.CI_NID_RETIRO, retiro)

    def test_creacion_piso_2_ignora_campos_arbitrarios_del_frontend(self):
        self._preparar_caso_38724()
        self._crear_dato_texto(
            self.origen, CAMPO_PROSESA_BASE_LINE_SAP, '1'
        )
        item = {
            'fecha_llegada': '2026-09-17',
            'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencia_piso_2.id),
            'guia_origen_prosesa': '57950',
            'patente_retiro_prosesa': 'HGH43',
            'empresa_transporte_retiro_prosesa': self.transportista.SN_CRAZONSOCIAL,
            'empresa_transporte_retiro_prosesa_id': str(self.transportista.id),
            '_prosesa_origen_id': 999999,
            'codigo_sap': 'FAKE',
            'codigo': 'FAKE',
            'insumo': 'FAKE',
            'pedido': '999',
            'docentry': '999',
            'base_line': '99',
            'proveedor_sap': 'FAKE',
            'contenedor': 'FAKE',
            'almacen_destino': 'SBH',
            'estanque_destino': 'SBH_FAKE',
        }
        response = self._respuesta_creacion_items([item])
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'], payload.get('message'))
        retiro = CITACION.objects.get(pk=payload['citaciones'][0])
        detalle = retiro.detalle_operacional
        self.assertEqual(detalle.CDO_CCODIGO_SAP, 'ITEM-1')
        self.assertEqual(detalle.CDO_CPEDIDO_SAP, '4500001')
        self.assertEqual(detalle.CDO_CDOCENTRY, '6880')
        self.assertEqual(detalle.CDO_CBL_CONTENEDOR, 'TLLU3391353')
        self.assertEqual(detalle.CDO_CALMACEN_DESTINO, 'PROSESA')
        self.assertEqual(detalle.CDO_CESTANQUE_DESTINO, 'PROSE_T3')
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro,
                CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_BASE_LINE_SAP,
            ).DO_CVALOR,
            '1',
        )
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(
                CI_NID_RETIRO=retiro
            ).CI_NID_ORIGEN,
            self.origen,
        )

    def test_frontend_piso_2_carga_snapshot_y_muestra_error_backend(self):
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Cargar datos desde Piso 1', template)
        self.assertIn('prosesa_piso_2_cargar_origen', template)
        self.assertIn('mostrarSnapshotProsesaPiso2', template)
        self.assertIn('origenProsesaPiso2Cargado.datos', template)
        self.assertIn('_prosesa_origen_id: origenProsesaPiso2Cargado.origen_id', template)
        self.assertIn('mensajeErrorPlanificacion(xhr,', template)
        self.assertNotIn('Ocurri\u00f3 un error al guardar la planificaci\u00f3n.', template)

    def test_frontend_piso_2_solicita_camion_planificado(self):
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('id="prosesa_piso2_patente_retiro"', template)
        self.assertIn('id="prosesa_piso2_empresa_transporte"', template)
        self.assertIn("url: '{% url \"ajax_transportistas_ingreso_camion\" %}'", template)
        self.assertIn('patente_retiro_prosesa: normalizarPatenteRetiroProsesa(', template)
        self.assertIn('empresa_transporte_retiro_prosesa_id: getValue(', template)
        self.assertNotIn('Debe ingresar la patente del camion de retiro de Piso 2.', template)
        self.assertNotIn('Debe ingresar la empresa de transporte del camion de retiro de Piso 2.', template)
        self.assertIn("$('#prosesa_piso2_patente_retiro').prop('required', false)", template)
        self.assertIn("$('#prosesa_piso2_empresa_transporte').prop('required', false)", template)

    def test_piso_2_se_crea_sin_patente(self):
        self._habilitar_origen_para_retiro()
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1', patente='')
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_PATENTE_RETIRO,
            ).DO_CVALOR, '',
        )
        self.assertFalse(citaciones_prosesa_piso_2_pendientes_por_patente('HGH43').exists())
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(CI_NID_RETIRO=retiro).CI_NID_ORIGEN,
            self.origen,
        )

    def test_piso_2_se_crea_sin_transportista(self):
        self._habilitar_origen_para_retiro()
        response = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1', empresa_transporte='', transportista_id='',
        )
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
            ).DO_CVALOR, '',
        )
        self.assertFalse(DATO_OPERACION.objects.filter(
            CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID,
        ).exists())

    def test_piso_2_persiste_camion_planificado_y_se_busca_por_patente(self):
        self._habilitar_origen_para_retiro()
        camiones_antes = CAMION_PATIO.objects.count()
        response = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1', patente='  hgh43  ',
        )
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        valores = dict(DATO_OPERACION.objects.filter(
            CI_NID=retiro,
            CAMP_NID__CA_CCODIGO__in=(
                CAMPO_PROSESA_PISO2_PATENTE_RETIRO,
                CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
                CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID,
            ),
        ).values_list('CAMP_NID__CA_CCODIGO', 'DO_CVALOR'))
        self.assertEqual(valores, {
            CAMPO_PROSESA_PISO2_PATENTE_RETIRO: 'HGH43',
            CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE: self.transportista.SN_CRAZONSOCIAL,
            CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID: str(self.transportista.pk),
        })
        self.assertEqual(CAMION_PATIO.objects.count(), camiones_antes)
        self.assertEqual(
            list(citaciones_prosesa_piso_2_pendientes_por_patente(' hgh43 ')),
            [retiro],
        )
        self.assertFalse(citaciones_prosesa_piso_2_pendientes_por_patente('otra').exists())
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(CI_NID_ORIGEN=self.origen).CI_NID_RETIRO,
            retiro,
        )

    def test_piso_2_acepta_empresa_de_transporte_manual(self):
        self._habilitar_origen_para_retiro()
        response = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1', patente='h g h 4 3',
            empresa_transporte='  Transporte   Manual  ', transportista_id='',
        )
        self.assertEqual(response.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_PATENTE_RETIRO,
            ).DO_CVALOR,
            'HGH43',
        )
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
            ).DO_CVALOR,
            'Transporte Manual',
        )
        self.assertFalse(DATO_OPERACION.objects.filter(
            CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID,
        ).exists())

    def test_piso_2_rechaza_transportista_maestro_ajeno(self):
        self._habilitar_origen_para_retiro()
        empresa_ajena, _ = EMPRESA.objects.get_or_create(
            id=1,
            defaults={
                'EP_CRAZONSOCIAL': 'Otra empresa',
                'EP_CRUT': '88-8',
                'EP_CBASEDATOS': 'TEST',
                'EP_CUSUARIOSBD': 'test',
                'EP_CPORT': '0',
            },
        )
        transportista_ajeno = SOCIONEGOCIO.objects.create(
            EP_NID=empresa_ajena,
            SN_CCODIGO_SAP='T-AJENO',
            SN_CRAZONSOCIAL='Transporte ajeno',
            SN_CRUT='44-4',
            SN_CTIPO='S',
        )
        response = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1', transportista_id=str(transportista_ajeno.pk),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('empresa de transporte', json.loads(response.content)['message'].lower())

    def _preparar_edicion_piso_2(self):
        self._habilitar_origen_para_retiro()
        respuesta = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1', patente='', empresa_transporte='', transportista_id='',
        )
        self.assertEqual(respuesta.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(respuesta.content)['citaciones'][0])
        USERS_EMPRESA.objects.create(US_NID=self.usuario, EP_NID=self.empresa)
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        return retiro

    def _solicitar_edicion_piso_2(self, retiro, datos=None):
        ruta = reverse('editar_citacion_prosesa_piso_2', args=[retiro.pk])
        with patch('apps.home.views.usuario_es_planificador', return_value=True):
            if datos is None:
                return self.client.get(ruta, {'_empresa_id': 2})
            return self.client.post(ruta, {'_empresa_id': 2, **datos})

    def test_editor_piso_2_muestra_snapshot_readonly_y_ruta_exclusiva(self):
        retiro = self._preparar_edicion_piso_2()
        response = self._solicitar_edicion_piso_2(retiro)
        self.assertEqual(response.status_code, 200)
        datos = response.json()['datos']
        self.assertEqual(datos['citacion_id'], retiro.pk)
        self.assertEqual(datos['origen_id'], self.origen.pk)
        self.assertEqual(datos['guia'], 'GUIA-PROSESA-1')
        self.assertEqual(datos['item_code'], 'ITEM-1')
        self.assertEqual(datos['contenedor'], 'CONT-1')
        self.assertEqual(datos['tipo_recepcion'], 'NACIONAL')
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('id="editProsesaPiso2Modal"', template)
        self.assertIn('success: data => abrirEdicionProsesaPiso2(citacionId, data)', template)
        self.assertIn('not_prosesa_piso2', template)
        self.assertIn('openEditModalLegacy(citacionId)', template)
        for campo in (
            'citacion_id', 'origen_id', 'guia', 'item_code', 'producto',
            'proveedor', 'pedido_sap', 'base_entry', 'base_line', 'bl',
            'contenedor', 'cantidad_disponible', 'almacen', 'estanque',
            'tipo_recepcion',
        ):
            self.assertIn('data-campo="' + campo + '"', template)
        modal = template.split('id="editProsesaPiso2Modal"', 1)[1].split('id="editCitationModal"', 1)[0]
        self.assertNotIn('<input name="guia"', modal)
        self.assertNotIn('<input name="base_line"', modal)
        self.assertIn('name="patente_retiro_prosesa"', modal)
        self.assertIn('name="empresa_transporte_retiro_prosesa"', modal)

    def test_editar_piso_2_completa_camion_y_servicio_lo_encuentra(self):
        retiro = self._preparar_edicion_piso_2()
        camiones_antes = CAMION_PATIO.objects.count()
        response = self._solicitar_edicion_piso_2(retiro, {
            'patente_retiro_prosesa': ' hgh43 ',
            'empresa_transporte_retiro_prosesa': self.transportista.SN_CRAZONSOCIAL,
            'empresa_transporte_retiro_prosesa_id': str(self.transportista.pk),
        })
        self.assertEqual(response.status_code, 200)
        valores = dict(DATO_OPERACION.objects.filter(
            CI_NID=retiro, CAMP_NID__CA_CCODIGO__in=(
                CAMPO_PROSESA_PISO2_PATENTE_RETIRO,
                CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
                CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID,
            ),
        ).values_list('CAMP_NID__CA_CCODIGO', 'DO_CVALOR'))
        self.assertEqual(valores, {
            CAMPO_PROSESA_PISO2_PATENTE_RETIRO: 'HGH43',
            CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE: self.transportista.SN_CRAZONSOCIAL,
            CAMPO_PROSESA_PISO2_TRANSPORTISTA_ID: str(self.transportista.pk),
        })
        self.assertEqual(CAMION_PATIO.objects.count(), camiones_antes)
        self.assertEqual(list(citaciones_prosesa_piso_2_pendientes_por_patente('hgh43')), [retiro])
        self.assertEqual(
            CITACION_PROSESA_RELACION.objects.get(CI_NID_RETIRO=retiro).CI_NID_ORIGEN_id,
            self.origen.id,
        )
        logs = views.SYSLOGGER.objects.filter(
            LOG_COPERACION='EDIT_PROSESA_PISO2', LOG_CADD1=str(retiro.pk),
        )
        self.assertEqual(logs.count(), 3)
        self.assertTrue(all(log.US_NID_id == self.usuario.pk and log.LOG_FFECHAREGISTRO for log in logs))
        self.assertTrue(any("'' -> 'HGH43'" in log.LOG_CDESCRIPCION for log in logs))
        perfil = PERFIL.objects.create(
            US_NID=self.usuario, PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='Asistente Recepcion', PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=self.usuario, PR_NID=perfil, PE_BHABILITADO=True)
        servicio = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 2, 'tipo_busqueda': 'patente', 'busqueda': 'hgh43',
        })
        self.assertEqual(servicio.status_code, 200)
        self.assertEqual(servicio.context['datos']['citacion_id'], retiro.pk)

    def test_editar_piso_2_bloquea_campos_heredados_y_editor_generico(self):
        retiro = self._preparar_edicion_piso_2()
        response = self._solicitar_edicion_piso_2(retiro, {
            'patente_retiro_prosesa': 'HGH43', 'base_line': '999',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(citaciones_prosesa_piso_2_pendientes_por_patente('HGH43').exists())
        with patch('apps.home.views.usuario_es_planificador', return_value=True):
            generico = self.client.post(reverse('update_citation', args=[retiro.pk]), {
                'numero_documento': 'OTRA-GUIA',
            })
        self.assertEqual(generico.status_code, 403)
        retiro.refresh_from_db()
        self.assertIsNone(retiro.CI_CNUMERODOCUMENTO)

    def test_editar_piso_2_admite_transporte_manual_y_limpiar_datos(self):
        retiro = self._preparar_edicion_piso_2()
        self.assertEqual(self._solicitar_edicion_piso_2(retiro, {
            'patente_retiro_prosesa': ' h g h 4 3 ',
            'empresa_transporte_retiro_prosesa': '  Transporte   Manual ',
            'empresa_transporte_retiro_prosesa_id': '',
        }).status_code, 200)
        self.assertEqual(
            DATO_OPERACION.objects.get(
                CI_NID=retiro, CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PISO2_EMPRESA_TRANSPORTE,
            ).DO_CVALOR, 'Transporte Manual',
        )
        self.assertEqual(self._solicitar_edicion_piso_2(retiro, {
            'patente_retiro_prosesa': '',
            'empresa_transporte_retiro_prosesa': '',
            'empresa_transporte_retiro_prosesa_id': '',
        }).status_code, 200)
        self.assertFalse(citaciones_prosesa_piso_2_pendientes_por_patente('HGH43').exists())

    def test_otro_tipo_sigue_en_editor_generico(self):
        self._preparar_edicion_piso_2()
        response = self._solicitar_edicion_piso_2(self.legacy)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.json()['not_prosesa_piso2'])

    def _preparar_servicio(self):
        self._habilitar_origen_para_retiro()
        respuesta = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(respuesta.status_code, 200)
        retiro = CITACION.objects.get(pk=json.loads(respuesta.content)['citaciones'][0])
        perfil = PERFIL.objects.create(
            US_NID=self.usuario, PR_CCODIGO='ASISTENTE_RECEPCION',
            PR_CNOMBRE='Asistente Recepcion', PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.usuario, PR_NID=perfil, PE_BHABILITADO=True,
        )
        USERS_EMPRESA.objects.create(US_NID=self.usuario, EP_NID=self.empresa)
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        return retiro

    def _post_servicio(self, retiro, **cambios):
        datos = {
            '_empresa_id': 2, 'tipo_busqueda': 'patente',
            'busqueda': 'HGH43', 'citacion_id': retiro.id,
            'empresa_transporte': self.transportista.SN_CRAZONSOCIAL,
            'transportista_id': str(self.transportista.id),
            'patente': ' hgh43 ', 'nombre_conductor': 'Conductor Prosesa',
            'rut_conductor': '12.345.678-5', 'codigo_pais': '+56',
            'telefono_conductor': '912345678',
        }
        datos.update(cambios)
        return self.client.post(reverse('recepcion_servicio_registro'), datos)

    def test_servicio_menu_acceso_ambas_empresas_y_sin_permiso(self):
        self._preparar_servicio()
        terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='Terramar', EP_CRUT='88-8',
            EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        USERS_EMPRESA.objects.create(US_NID=self.usuario, EP_NID=terramar)
        for empresa_id in (1, 2):
            request = RequestFactory().get('/')
            request.user = self.usuario
            request.session = {'empresa_id': empresa_id}
            request.resolver_match = SimpleNamespace(url_name='home')
            menu = render_to_string('includes/component-navbar-inner.html', request=request)
            self.assertIn('Recepci&oacute;n Servicio', menu)
            self.assertIn('Registro de cami&oacute;n', menu)
            self.assertIn('Planificaci&oacute;n', menu)
            response = self.client.get(reverse('recepcion_servicio_registro'), {'_empresa_id': empresa_id})
            self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 2, 'seccion': 'planificacion',
        })
        self.assertContains(response, 'Recepciones de servicio')
        sin_perfil = get_user_model().objects.create_user('sin_servicio', password='test')
        USERS_EMPRESA.objects.create(US_NID=sin_perfil, EP_NID=self.empresa)
        self.client.force_login(sin_perfil)
        response = self.client.get(reverse('recepcion_servicio_registro'), {'_empresa_id': 2})
        self.assertEqual(response.status_code, 403)

    def test_servicio_busca_patente_guia_y_muestra_herencia_readonly(self):
        retiro = self._preparar_servicio()
        for tipo, valor in (('patente', ' hgh43 '), ('guia', 'GUIA-PROSESA-1')):
            response = self.client.get(reverse('recepcion_servicio_registro'), {
                '_empresa_id': 2, 'tipo_busqueda': tipo, 'busqueda': valor,
            })
            self.assertEqual(response.status_code, 200)
            datos = response.context['datos']
            self.assertEqual(datos['citacion_id'], retiro.id)
            self.assertEqual(datos['origen_id'], self.origen.id)
            self.assertEqual(datos['patente_planificada'], 'HGH43')
            self.assertEqual(datos['empresa_transporte'], self.transportista.SN_CRAZONSOCIAL)
            self.assertEqual(datos['guia'], 'GUIA-PROSESA-1')
            html = response.content.decode('utf-8')
            for conocido in ('ITEM-1', '4500001', 'CONT-1', 'PROSESA', 'PROSE_G2'):
                self.assertIn(conocido, html)
            for nombre in ('pedido_sap', 'item_code', 'proveedor', 'contenedor', 'almacen'):
                self.assertNotIn(f'name="{nombre}"', html)
            self.assertIn('name="patente"', html)
            self.assertIn('value="HGH43"', html)

    def test_servicio_registra_camion_directo_sin_avanzar_operacion(self):
        retiro = self._preparar_servicio()
        anteriores = CAMION_PATIO.objects.count()
        response = self._post_servicio(retiro)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CAMION_PATIO.objects.count(), anteriores + 1)
        camion = CAMION_PATIO.objects.get(CI_NID=retiro)
        self.assertEqual(camion.CPA_CPATENTE, 'HGH43')
        self.assertEqual(camion.CPA_CNOMBRE_CONDUCTOR, 'Conductor Prosesa')
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '12345678-5')
        self.assertEqual(camion.CPA_CCODIGO_PAIS_TELEFONO, '+56')
        self.assertEqual(camion.CPA_CTELEFONO_CONDUCTOR, '912345678')
        self.assertEqual(camion.CPA_CTRANSPORTISTA_DECLARADO, self.transportista.SN_CRAZONSOCIAL)
        self.assertEqual(camion.CPA_CNUMERO_GUIA, 'GUIA-PROSESA-1')
        self.assertEqual(camion.CPA_CLOTE_CONTENEDOR, 'CONT-1')
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
        self.assertEqual(retiro.CI_CESTADO, 'Insumo Programado')
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=retiro).exists())
        self.assertEqual(
            camion.trazabilidad_planificacion.CPTR_CRESULTADO_BUSQUEDA,
            views.RESULTADO_RECEPCION_SERVICIO_PROSESA,
        )

    def test_servicio_permite_corregir_patente_y_transporte(self):
        retiro = self._preparar_servicio()
        response = self._post_servicio(
            retiro, patente=' jh 123 ', empresa_transporte='  Transporte Manual  ',
            transportista_id='',
        )
        self.assertEqual(response.status_code, 302)
        camion = CAMION_PATIO.objects.get(CI_NID=retiro)
        self.assertEqual(camion.CPA_CPATENTE, 'JH123')
        self.assertEqual(camion.CPA_CTRANSPORTISTA_DECLARADO, 'Transporte Manual')

    def test_servicio_bloquea_duplicado_y_planificacion_utilizada(self):
        retiro = self._preparar_servicio()
        self.assertEqual(self._post_servicio(retiro).status_code, 302)
        self.assertEqual(self._post_servicio(retiro).status_code, 409)
        self.assertEqual(CAMION_PATIO.objects.filter(CI_NID=retiro).count(), 1)
        response = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 2, 'tipo_busqueda': 'patente', 'busqueda': 'HGH43',
        })
        self.assertContains(response, 'ya fue utilizada', status_code=409)

    def test_servicio_guardia_encuentra_llegada_en_estado_camion(self):
        retiro = self._preparar_servicio()
        self.assertEqual(self._post_servicio(retiro).status_code, 302)
        guardia = get_user_model().objects.create_user('guardia_servicio', password='test')
        perfil = PERFIL.objects.create(
            US_NID=guardia, PR_CCODIGO='GUARDIA',
            PR_CNOMBRE='Guardia', PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=guardia, PR_NID=perfil, PE_BHABILITADO=True)
        USERS_EMPRESA.objects.create(US_NID=guardia, EP_NID=self.empresa)
        self.client.force_login(guardia)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        response = self.client.get(reverse('estado_camion_ajax'), {
            'patente': 'hgh43', '_empresa_id': 2,
        })
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload['tipo_resultado'], 'RECEPCION_SERVICIO_PROSESA')
        self.assertEqual(payload['data']['citacion_id'], retiro.id)
        self.assertEqual(payload['data']['origen_id'], self.origen.id)
        self.assertIn('pla_listone', payload['data']['url_guardia'])
        self.assertIn('Pendiente de validacion de Guardia', payload['data']['mensaje'])
        self.assertTrue(payload['data']['puede_validar_guardia'])
        etapa_revision = ETAPA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            ET_CTIPO='OPERACION', ET_CCODIGO='REVISION_AR_SERVICIO_TEST',
            ET_CNOMBRE='Revision Asistente Recepcion',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            SC_NID=self.secuencia_piso_2, ET_NID=etapa_revision,
            SE_NPASO=2, SE_BOBLIGATORIO=True, SE_BHABILITADO=True,
        )
        camion = CAMION_PATIO.objects.get(CI_NID=retiro)
        validacion = self.client.post(
            reverse('recepcion_servicio_guardia_validar', args=[camion.id]),
            {'_empresa_id': 2},
        )
        self.assertEqual(validacion.status_code, 200)
        retiro.refresh_from_db()
        self.assertEqual(retiro.CI_CESTADO, 'EN PROCESO')
        self.assertEqual(retiro.ETAPA_ACTUAL, etapa_revision)
        self.assertTrue(views.SYSLOGGER.objects.filter(
            LOG_COPERACION='ING_CAMION', LOG_CADD1=str(retiro.id),
        ).exists())
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(CI_NID=retiro).exists())
        self.assertEqual(self.client.post(
            reverse('recepcion_servicio_guardia_validar', args=[camion.id]),
            {'_empresa_id': 2},
        ).status_code, 409)
        posterior = self.client.get(reverse('estado_camion_ajax'), {
            'patente': 'HGH43', '_empresa_id': 2,
        })
        posterior_payload = json.loads(posterior.content)
        self.assertEqual(posterior_payload['tipo_resultado'], 'PROCESO_ACTIVO')
        self.assertEqual(posterior_payload['data']['estado_prosesa_piso_2'], 'Patio de camiones / pendiente Asistente Recepcion')
        self.client.force_login(self.usuario)
        utilizada = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 2, 'tipo_busqueda': 'patente', 'busqueda': 'HGH43',
        })
        self.assertContains(utilizada, 'ya fue utilizada', status_code=409)

    def test_servicio_exige_datos_de_llegada_y_no_crea_camion_incompleto(self):
        retiro = self._preparar_servicio()
        anteriores = CAMION_PATIO.objects.count()
        response = self._post_servicio(retiro, nombre_conductor='')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'nombre del conductor', status_code=400)
        self.assertEqual(CAMION_PATIO.objects.count(), anteriores)

    def test_servicio_solo_guardia_puede_validar_llegada(self):
        retiro = self._preparar_servicio()
        self.assertEqual(self._post_servicio(retiro).status_code, 302)
        camion = CAMION_PATIO.objects.get(CI_NID=retiro)
        response = self.client.post(
            reverse('recepcion_servicio_guardia_validar', args=[camion.id]),
            {'_empresa_id': 2},
        )
        self.assertEqual(response.status_code, 403)
        retiro.refresh_from_db()
        self.assertEqual(retiro.CI_CESTADO, 'Insumo Programado')

    def test_piso_2_exige_guia(self):
        response = self._respuesta_creacion_piso_2(None)
        self.assertEqual(response.status_code, 400)
        self.assertIn('piso 2', json.loads(response.content)['message'].lower())

    def test_piso_2_cantidad_cinco_sigue_bloqueada(self):
        response = self._respuesta_creacion_piso_2(
            'GUIA-PROSESA-1',
            cantidad=5,
        )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Piso 2', payload['message'])
        self.assertIn('exactamente una citación', payload['message'])

    def test_piso_2_rechaza_guia_inexistente(self):
        response = self._respuesta_creacion_piso_2('GUIA-INEXISTENTE')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(json.loads(response.content)['success'])

    def test_piso_2_con_guia_valida_mantiene_relacion(self):
        self.relacion.delete()
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        relacion = CITACION_PROSESA_RELACION.objects.get(
            CI_NID_ORIGEN=self.origen
        )
        self.assertEqual(relacion.CI_NID_RETIRO_id, payload['citaciones'][0])

    def test_piso_2_rechaza_piso_1_ya_relacionado(self):
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertIn('ya tiene una Citación 2 vinculada', payload['message'])

    def test_piso_2_rechaza_origen_que_no_esta_esperando_retiro(self):
        self.origen.CI_CESTADO = CIT_TERMINADO
        self.origen.save(update_fields=['CI_CESTADO'])
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(response.status_code, 404)


    def _usuario_operacional(self, username, codigo):
        user = get_user_model().objects.create_user(username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=self.usuario, PR_CCODIGO=codigo,
            PR_CNOMBRE=codigo.replace('_', ' '), PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(US_NID=user, PR_NID=perfil, PE_BHABILITADO=True)
        USERS_EMPRESA.objects.create(US_NID=user, EP_NID=self.empresa)
        return user

    def _iniciar_sesion_operacional(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_retiro_piso_2_por_roles_estado_y_retorno(self):
        ar = self._usuario_operacional('ar_retiro_piso2', 'ASISTENTE_RECEPCION')
        porteria = self._usuario_operacional('porteria_retiro_piso2', 'GUARDIA_PORTERIA')
        guardia = self._usuario_operacional('guardia_retiro_piso2', 'GUARDIA')
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=self.retiro, OPL_CPASO='Pesaje Entrada',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], PASO_PROSESA_INICIO_RETIRO)
        self._iniciar_sesion_operacional(guardia)
        ruta_inicio = reverse('ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa', args=[self.retiro.id])
        ruta_validar = reverse('ajax_operacion_planta_validar_salida_temporal_prosesa_piso_2', args=[self.retiro.id])
        ruta_retorno = reverse('ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa', args=[self.retiro.id])
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            self.assertEqual(self.client.post(ruta_inicio, {'_empresa_id': 2}).status_code, 403)
            self.assertEqual(self.client.post(ruta_validar, {'_empresa_id': 2}).status_code, 403)
            self.assertEqual(self.client.post(ruta_retorno, {'_empresa_id': 2}).status_code, 403)
            self._iniciar_sesion_operacional(ar)
            inicio = self.client.post(ruta_inicio, {'_empresa_id': 2})
            self.assertEqual(inicio.status_code, 200)
            ciclo = inicio.json()['ciclo_bodega_externa']
            self.assertTrue(ciclo['iniciada'])
            self.assertFalse(ciclo['salida_validada'])
            self.assertTrue(ciclo['inicio_ms'])
            self.assertEqual(ciclo['guia'], 'GUIA-PROSESA-1')
            self.assertEqual(ciclo['contenedor'], 'CONT-1')
            self.assertEqual(
                views._payload_salida_temporal_prosesa_piso_2(CITACION.objects.get(pk=self.retiro.id))['inicio_ms'],
                ciclo['inicio_ms'],
            )
            camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
            self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
            self._iniciar_sesion_operacional(porteria)
            estado = self.client.get(reverse('estado_camion_ajax'), {'patente': 'PISO2', '_empresa_id': 2}).json()['data']
            self.assertEqual(estado['estado_prosesa_piso_2'], 'Autorizado salida temporal por retiro')
            self.assertTrue(estado['puede_validar_salida_temporal'])
            self.assertEqual(estado['timer_inicio_ms'], ciclo['inicio_ms'])
            self.assertEqual(self.client.post(ruta_validar, {'_empresa_id': 2}).status_code, 200)
            camion.refresh_from_db()
            self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_FUERA_TEMPORAL)
            fuera = self.client.get(reverse('estado_camion_ajax'), {'patente': 'PISO2', '_empresa_id': 2}).json()
            self.assertEqual(fuera['tipo_resultado'], 'PROCESO_ACTIVO')
            self.assertEqual(fuera['data']['estado_prosesa_piso_2'], 'Fuera temporalmente')
            self.assertTrue(fuera['data']['puede_registrar_retorno'])
            self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], PASO_PROSESA_INICIO_RETIRO)
            retorno = self.client.post(ruta_retorno, {'_empresa_id': 2, 'observacion': 'Sin novedades'})
            self.assertEqual(retorno.status_code, 200)
            self.assertTrue(retorno.json()['ciclo_bodega_externa']['finalizada'])
        camion.refresh_from_db()
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], 'Pesaje Salida')
        retornado = self.client.get(reverse('estado_camion_ajax'), {'patente': 'PISO2', '_empresa_id': 2}).json()['data']
        self.assertEqual(retornado['estado_prosesa_piso_2'], 'Retornado')
        self.assertEqual(retornado['proxima_accion'], 'Registrar Pesaje Salida')
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro, OPL_CPASO=PASO_PROSESA_INICIO_RETIRO,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).exists())
        congelado = views._payload_salida_temporal_prosesa_piso_2(CITACION.objects.get(pk=self.retiro.id))
        self.assertFalse(congelado['en_proceso'])
        self.assertEqual(congelado['duracion_legible'], retorno.json()['ciclo_bodega_externa']['duracion_legible'])

    def test_retiro_piso_2_exige_validacion_de_salida_antes_de_retorno(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=self.retiro, OPL_CPASO='Pesaje Entrada',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        views._iniciar_retiro_temporal_prosesa_piso_2(self.retiro, self.usuario)
        with self.assertRaisesMessage(ValueError, 'validar la salida temporal'):
            views._finalizar_retiro_temporal_prosesa_piso_2(self.retiro, self.usuario)
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], PASO_PROSESA_INICIO_RETIRO)


    def test_asistente_recepcion_envia_piso_2_directo_a_porteria(self):
        retiro = self._preparar_servicio()
        self.assertEqual(self._post_servicio(retiro).status_code, 302)
        etapa_revision = ETAPA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='REVISION_AR_PISO2_TEST', ET_CNOMBRE='Revision AR Piso 2',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        etapa_porteria = ETAPA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='INGRESO_PORTERIA_PISO2_TEST', ET_CNOMBRE='Ingreso Porteria Piso 2',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        for orden, etapa in ((2, etapa_revision), (3, etapa_porteria)):
            DETALLE_SECUENCIA.objects.create(
                US_NID=self.usuario, EP_NID=self.empresa, SC_NID=self.secuencia_piso_2,
                ET_NID=etapa, SE_NPASO=orden, SE_BOBLIGATORIO=True, SE_BHABILITADO=True,
            )
        guardia = self._usuario_operacional('guardia_ingreso_piso2', 'GUARDIA')
        porteria = self._usuario_operacional('porteria_ingreso_piso2', 'GUARDIA_PORTERIA')
        camion = CAMION_PATIO.objects.get(CI_NID=retiro)
        self._iniciar_sesion_operacional(porteria)
        self.assertEqual(self.client.post(
            reverse('recepcion_servicio_guardia_validar', args=[camion.id]),
            {'_empresa_id': 2},
        ).status_code, 403)
        self._iniciar_sesion_operacional(guardia)
        self.assertEqual(self.client.post(
            reverse('recepcion_servicio_guardia_validar', args=[camion.id]),
            {'_empresa_id': 2},
        ).status_code, 200)
        self._iniciar_sesion_operacional(self.usuario)
        ruta_aprobar = reverse('pla_citacion_aprobar_asistente', args=[retiro.id])
        sin_ruta = self.client.post(ruta_aprobar, {'_empresa_id': 2, 'peso_informado_guia': '24000'})
        self.assertEqual(sin_ruta.status_code, 400)
        self.assertIn('ruta del transportista', sin_ruta.json()['message'])
        with patch('apps.home.views.requiere_ruta_transportista_revision', return_value=False):
            aprobado = self.client.post(ruta_aprobar, {'_empresa_id': 2, 'peso_informado_guia': '24000'})
        self.assertEqual(aprobado.status_code, 200, aprobado.content)
        self.assertEqual(aprobado.json()['notificados_cd'], 0)
        self.assertGreaterEqual(aprobado.json()['notificados_guardia_porteria'], 1)
        self.assertTrue(views.SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(retiro.id),
        ).exists())
        self.assertFalse(views.SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR', LOG_CADD1=str(retiro.id),
        ).exists())
        retiro.refresh_from_db()
        self.assertEqual(retiro.ETAPA_ACTUAL, etapa_porteria)
        self._iniciar_sesion_operacional(porteria)
        estado = self.client.get(reverse('estado_camion_ajax'), {
            'patente': 'HGH43', '_empresa_id': 2,
        }).json()['data']
        self.assertEqual(estado['estado_prosesa_piso_2'], 'Autorizado ingreso planta')
        self.assertTrue(estado['puede_autorizar_ingreso_planta'])
        ingreso = self.client.post(
            reverse('pla_citacion_enviar_guardia_porteria', args=[retiro.id]),
            {'_empresa_id': 2},
        )
        self.assertEqual(ingreso.status_code, 200, ingreso.content)
        self.assertTrue(views.SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(retiro.id),
        ).exists())
        self.assertEqual(views.obtener_paso_activo_operacion(retiro)[0], 'Pesaje Entrada')


    def test_confirmar_salida_piso_2_solo_guardia_porteria(self):
        self.origen.CI_CESTADO = ESTADO_PROSESA_ESPERANDO_RETIRO
        self.origen.save(update_fields=['CI_CESTADO'])
        self._crear_cuatro_pesajes_validos()
        calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self._completar_retiro_temporal()
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro, OPL_CPASO='Autorizar Salida',
        ).delete()
        ar = self._usuario_operacional('ar_confirmar_piso2', 'ASISTENTE_RECEPCION')
        self._iniciar_sesion_operacional(ar)
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            autorizado = self.client.post(
                reverse('ajax_operacion_planta_autorizar_salida', args=[self.retiro.id]),
                {'_empresa_id': 2},
            )
        self.assertEqual(autorizado.status_code, 200, autorizado.content)
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], 'Confirmar Salida')
        guardia = self._usuario_operacional('guardia_confirmar_piso2', 'GUARDIA')
        porteria = self._usuario_operacional('porteria_confirmar_piso2', 'GUARDIA_PORTERIA')
        ruta = reverse('operacion_planta_guardar_paso', args=[self.retiro.id])
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            self._iniciar_sesion_operacional(guardia)
            rechazado = self.client.post(ruta, {'_empresa_id': 2, 'paso': 'Confirmar Salida'})
            self.assertEqual(rechazado.status_code, 403)
            self._iniciar_sesion_operacional(porteria)
            autorizado = self.client.get(reverse('estado_camion_ajax'), {'patente': 'PISO2', '_empresa_id': 2}).json()['data']
            self.assertEqual(autorizado['estado_prosesa_piso_2'], 'Autorizado salida final')
            confirmado = self.client.post(ruta, {'_empresa_id': 2, 'paso': 'Confirmar Salida'})
            self.assertEqual(confirmado.status_code, 200, confirmado.content)
        self.retiro.refresh_from_db()
        self.origen.refresh_from_db()
        self.assertEqual(self.retiro.CI_CESTADO, CIT_TERMINADO)
        self.assertEqual(self.origen.CI_CESTADO, CIT_TERMINADO)
        self.assertEqual(
            CAMION_PATIO.objects.get(CI_NID=self.retiro).CPA_CESTADO,
            CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA,
        )


    def test_operacion_planta_piso_2_muestra_panel_y_pasos_nuevos(self):
        ar = self._usuario_operacional('ar_panel_piso2', 'ASISTENTE_RECEPCION')
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, PL_NID=self.planificacion,
            CI_NID=self.retiro, OPL_CPASO='Pesaje Entrada',
            OPL_CPERFIL_RESPONSABLE='OPERADOR ROMANA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        self._iniciar_sesion_operacional(ar)
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            response = self.client.get(
                reverse('operacion_planta_citacion', args=[self.retiro.id]),
                {'_empresa_id': 2},
            )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('INICIAR RETIRO DE CONTENEDOR', html)
        self.assertIn(PASO_PROSESA_INICIO_RETIRO, html)
        self.assertNotIn(PASO_PROSESA_RETIRAR_CONTENEDOR, html)
        self.assertNotIn(PASO_PROSESA_TRASLADO_MANUAL, html)


    def test_autorizar_salida_piso_2_avanza_sin_consultar_sap(self):
        self._crear_cuatro_pesajes_validos()
        calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self._completar_retiro_temporal()
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro, OPL_CPASO='Autorizar Salida',
        ).delete()
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], 'Autorizar Salida')
        ar = self._usuario_operacional('ar_autoriza_piso2', 'ASISTENTE_RECEPCION')
        porteria = self._usuario_operacional('porteria_no_autoriza_piso2', 'GUARDIA_PORTERIA')
        ruta = reverse('ajax_operacion_planta_autorizar_salida', args=[self.retiro.id])
        self._iniciar_sesion_operacional(porteria)
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            self.assertEqual(self.client.post(ruta, {'_empresa_id': 2}).status_code, 403)
            self._iniciar_sesion_operacional(ar)
            with patch('apps.home.views.get_goods_receipt_draft_update_status', side_effect=AssertionError('SAP no debe consultarse')):
                with patch('apps.home.views._ticket_pesaje_obligatorio_guardado', return_value=True):
                    panel = self.client.get(reverse('operacion_planta_citacion', args=[self.retiro.id]), {'_empresa_id': 2})
                self.assertEqual(panel.status_code, 200)
                self.assertIn('AUTORIZAR SALIDA FINAL', panel.content.decode('utf-8'))
                autorizado = self.client.post(ruta, {'_empresa_id': 2})
            self.assertEqual(autorizado.status_code, 200, autorizado.content)
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro, OPL_CPASO='Autorizar Salida',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).exists())
        self.assertEqual(views.obtener_paso_activo_operacion(self.retiro)[0], 'Confirmar Salida')


    def test_guardia_patio_deriva_recepcion_piso_2_a_asistente_recepcion(self):
        self._usuario_operacional('ar_derivacion_piso2', 'ASISTENTE_RECEPCION')
        guardia = self._usuario_operacional('guardia_derivacion_piso2', 'GUARDIA')
        porteria = self._usuario_operacional('porteria_derivacion_piso2', 'GUARDIA_PORTERIA')
        camion = CAMION_PATIO.objects.create(
            EP_NID=self.empresa, CI_NID=self.retiro,
            CPA_CPATENTE='DERP2', CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=guardia,
        )
        ruta = reverse('camion_patio_derivar', args=[camion.id])
        self._iniciar_sesion_operacional(porteria)
        self.assertEqual(self.client.post(ruta, {'_empresa_id': 2}).status_code, 403)
        self._iniciar_sesion_operacional(guardia)
        with patch('apps.home.views.notificar_camion_patio_nuevo', return_value=1):
            derivado = self.client.post(ruta, {'_empresa_id': 2})
        self.assertEqual(derivado.status_code, 200, derivado.content)
        self.assertEqual(derivado.json()['responsable'], 'ASISTENTE_RECEPCION')
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION)


    def test_porteria_no_deriva_candidato_piso_2_sin_asociacion(self):
        porteria = self._usuario_operacional('porteria_patio_candidato_piso2', 'GUARDIA_PORTERIA')
        camion = CAMION_PATIO.objects.create(
            EP_NID=self.empresa, CI_NID=None,
            CPA_CPATENTE='CANDP2', CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=porteria,
        )
        CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
            CPA_NID=camion, CI_NID=self.retiro, PL_NID=self.planificacion,
            EP_NID=self.empresa, CPTR_CPATENTE_CONSULTADA='CANDP2',
            CPTR_CRESULTADO_BUSQUEDA='GUARDIA_MATCH', US_NID=porteria,
        )
        self._iniciar_sesion_operacional(porteria)
        estado = self.client.get(reverse('estado_camion_ajax'), {
            'patente': 'CANDP2', '_empresa_id': 2,
        }).json()
        self.assertEqual(estado['tipo_resultado'], 'INGRESO_PATIO_PENDIENTE')
        self.assertFalse(estado['data']['puede_derivar'])
        self.assertEqual(self.client.post(
            reverse('camion_patio_derivar', args=[camion.id]), {'_empresa_id': 2},
        ).status_code, 403)


    def _configurar_tarifa_transportista_equivalente_piso_2(self):
        empresa_maestra, _ = EMPRESA.objects.get_or_create(
            id=1,
            defaults={
                'EP_CRAZONSOCIAL': 'Empresa maestra transporte',
                'EP_CRUT': '88-8',
                'EP_CBASEDATOS': 'TEST',
                'EP_CUSUARIOSBD': 'test',
                'EP_CPORT': '0',
            },
        )
        self.transportista.SN_CRAZONSOCIAL = 'Transportes Equivalentes Piso 2'
        self.transportista.SN_CRUT = '77.777.777-7'
        self.transportista.SN_CTIPO = 'S'
        self.transportista.SN_BHABILITADO = True
        self.transportista.save(update_fields=[
            'SN_CRAZONSOCIAL', 'SN_CRUT', 'SN_CTIPO', 'SN_BHABILITADO',
        ])
        transportista_maestro = SOCIONEGOCIO.objects.create(
            EP_NID=empresa_maestra,
            SN_CCODIGO_SAP='T-EQUIV-P2',
            SN_CRAZONSOCIAL=self.transportista.SN_CRAZONSOCIAL,
            SN_CRUT=self.transportista.SN_CRUT,
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        region = REGION.objects.create(
            RG_CNOMBRE='Coronel P2', RG_CCODIGO='COR-P2',
        )
        provincia = PROVINCIA.objects.create(
            RG_NID=region, PV_CNOMBRE='Concepción P2', PV_CCODIGO='CON-P2',
        )
        comuna = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Coronel P2', COM_CCODIGO='COR-P2',
        )
        ruta = RUTA.objects.create(
            EP_NID=self.empresa,
            RG_NID_INICIO=region,
            PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna,
            RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia,
            COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1,
            RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='CORONEL -> CORONEL ( TARIFA PISO 2 )',
            RUT_CCODIGO='COR-P2',
            RUT_BHABILITADO=True,
        )
        tarifa = TARIFA_GLOBAL.objects.create(
            EP_NID=self.empresa,
            RUT_NID=ruta,
            SN_NID=transportista_maestro,
            US_NID=self.usuario,
            TAR_NVALOR=127670,
            TAR_CNOMBRETARIFA='FLETE CONTENEDOR PISO 2',
            TAR_CTIPOTARIFA='FLETE',
            TAR_CDIVISA='CLP',
            TAR_BHABILITADO=True,
        )
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.CPA_CTRANSPORTISTA_DECLARADO = self.transportista.SN_CRAZONSOCIAL
        camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        return ruta, tarifa

    def test_piso_2_resuelve_tarifa_de_transportista_equivalente_y_la_persiste(self):
        ruta, tarifa = self._configurar_tarifa_transportista_equivalente_piso_2()
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.transporte_a_cargo = 'CLIENTE'
        camion.save(update_fields=['transporte_a_cargo'])

        self.assertTrue(views.requiere_ruta_transportista_revision(
            self.retiro, {'requiere_ruta_transportista': False},
        ))
        resultado = views.obtener_rutas_tarifa_transportista(self.retiro)
        self.assertEqual([opcion['tarifa_id'] for opcion in resultado['opciones']], [str(tarifa.id)])
        texto_visible = resultado['opciones'][0]['text']
        self.assertEqual(texto_visible, ruta.RUT_CNOMBRE)
        self.assertNotIn('CLP', texto_visible)
        self.assertNotIn(str(tarifa.TAR_NVALOR), texto_visible)

        validada, error = views.validar_tarifa_transportista_revision(
            self.retiro, tarifa.id, ruta.id,
        )
        self.assertEqual(error, '')
        self.assertEqual(validada.id, tarifa.id)
        views.guardar_ruta_transportista_revision(self.retiro, validada, self.usuario)
        self.retiro.refresh_from_db()
        self.assertEqual(self.retiro.RUT_NID_id, ruta.id)
        self.assertEqual(self.retiro.TAR_NID_id, tarifa.id)
        self.assertEqual(self.retiro.CI_NVALORTARIFA, tarifa.TAR_NVALOR)
        self.assertEqual(DATO_OPERACION.objects.filter(
            CI_NID=self.retiro,
            CAMP_NID__CA_CCODIGO__in={
                'AR_RUTA_TRANSPORTISTA', 'AR_RUTA_ID', 'AR_TARIFA_ID',
            },
        ).count(), 3)

    def test_ajax_piso_2_usa_transportista_del_camion_aun_si_recibe_otro_id(self):
        ruta, tarifa = self._configurar_tarifa_transportista_equivalente_piso_2()
        request = RequestFactory().get('/ajax-rutas-transportista-revision/', {
            'citacion_id': self.retiro.id,
            'transportista_id': self.transportista.id,
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.usuario_es_asistente_recepcion', return_value=True), \
             patch('apps.home.views.usuario_es_asistente_despacho_empresa', return_value=False):
            response = views.AJAX_RUTAS_TRANSPORTISTA_REVISION(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['results'][0]['tarifa_id'], str(tarifa.id))
        self.assertEqual(payload['results'][0]['ruta_id'], str(ruta.id))

    def test_piso_2_informa_transportista_resuelto_sin_tarifas(self):
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.CPA_CTRANSPORTISTA_DECLARADO = self.transportista.SN_CRAZONSOCIAL
        camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])

        resultado = views.obtener_rutas_tarifa_transportista(self.retiro)
        self.assertEqual(resultado['opciones'], [])
        self.assertIn(self.transportista.SN_CRAZONSOCIAL, resultado['message'])
        self.assertIn(f'ID {self.transportista.id}', resultado['message'])
        self.assertIn('Empresa 2', resultado['message'])
    def _fila_listado_recepciones_operacion(self, citacion):
        self.usuario.is_superuser = True
        self.usuario.save(update_fields=['is_superuser'])
        USERS_EMPRESA.objects.get_or_create(US_NID=self.usuario, EP_NID=self.empresa)
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=citacion,
            OPL_CPASO='Habilitar Operacion Planta',
            OPL_CPERFIL_RESPONSABLE='TEST',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        response = self.client.get(reverse('cit_listall_recepciones'), {
            'contexto': 'operacion_planta',
            'tipo': 'RECEPCION',
            'empresa_id': self.empresa.id,
            '_empresa_id': self.empresa.id,
        })
        self.assertEqual(response.status_code, 200, response.content)
        fila = next(item for item in response.context['object_list'] if item.id == citacion.id)
        return response, fila

    def test_listado_piso_2_muestra_guia_de_numero_documento(self):
        self.retiro.CI_CNUMERODOCUMENTO = '57950'
        self.retiro.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle = self.retiro.detalle_operacional
        detalle.CDO_CGUIA = ''
        detalle.save(update_fields=['CDO_CGUIA'])
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.CPA_CNUMERO_GUIA = ''
        camion.save(update_fields=['CPA_CNUMERO_GUIA'])

        response, fila = self._fila_listado_recepciones_operacion(self.retiro)
        self.assertEqual(fila.numero_documento_listado, '57950')
        self.assertContains(response, '57950')

    def test_listado_piso_2_caso_38729_muestra_guia_de_detalle_y_es_buscable(self):
        self.retiro.CI_CNUMERODOCUMENTO = ''
        self.retiro.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle = self.retiro.detalle_operacional
        detalle.CDO_CGUIA = '57950'
        detalle.save(update_fields=['CDO_CGUIA'])
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.CPA_CNUMERO_GUIA = ''
        camion.save(update_fields=['CPA_CNUMERO_GUIA'])

        response, fila = self._fila_listado_recepciones_operacion(self.retiro)
        html = response.content.decode('utf-8')
        self.assertEqual(self.retiro.id, 38729)
        self.assertEqual(fila.numero_documento_listado, '57950')
        self.assertIn('57950', html)
        self.assertNotIn('Sin numero de documento', html)
        self.assertIn("$('#basic-btn').DataTable", html)

    def test_listado_piso_2_muestra_guia_de_camion_patio(self):
        self.retiro.CI_CNUMERODOCUMENTO = ''
        self.retiro.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle = self.retiro.detalle_operacional
        detalle.CDO_CGUIA = ''
        detalle.save(update_fields=['CDO_CGUIA'])
        camion = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion.CPA_CNUMERO_GUIA = '57950'
        camion.save(update_fields=['CPA_CNUMERO_GUIA'])

        response, fila = self._fila_listado_recepciones_operacion(self.retiro)
        self.assertEqual(fila.numero_documento_listado, '57950')
        self.assertContains(response, '57950')

    def test_listado_piso_2_hereda_guia_del_origen_relacionado(self):
        self.retiro.CI_CNUMERODOCUMENTO = ''
        self.retiro.save(update_fields=['CI_CNUMERODOCUMENTO'])
        detalle_retiro = self.retiro.detalle_operacional
        detalle_retiro.CDO_CGUIA = ''
        detalle_retiro.save(update_fields=['CDO_CGUIA'])
        camion_retiro = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        camion_retiro.CPA_CNUMERO_GUIA = ''
        camion_retiro.save(update_fields=['CPA_CNUMERO_GUIA'])
        self.origen.CI_CNUMERODOCUMENTO = '57950'
        self.origen.save(update_fields=['CI_CNUMERODOCUMENTO'])

        _, fila = self._fila_listado_recepciones_operacion(self.retiro)
        self.assertEqual(fila.numero_documento_listado, '57950')

    def test_listado_conserva_numero_documento_de_otras_recepciones(self):
        self.legacy.CI_CNUMERODOCUMENTO = 'DOC-LEGACY'
        self.legacy.save(update_fields=['CI_CNUMERODOCUMENTO'])

        response, fila = self._fila_listado_recepciones_operacion(self.legacy)
        self.assertFalse(hasattr(fila, 'numero_documento_listado'))
        self.assertContains(response, 'DOC-LEGACY')
    def _preparar_etapa_calculo_peso_real(self, username='ar_calculo_peso_real'):
        self._crear_cuatro_pesajes_validos()
        self._completar_retiro_temporal()
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro,
            OPL_CPASO='Autorizar Salida',
        ).delete()
        views.SYSLOGGER.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.retiro.id),
        )
        asistente = self._usuario_operacional(username, 'ASISTENTE_RECEPCION')
        self._iniciar_sesion_operacional(asistente)
        return asistente, reverse(
            'ajax_operacion_planta_calcular_peso_real_prosesa',
            args=[self.retiro.id],
        )

    @override_settings(QA_PESAJE=False)
    def test_qa_pesaje_false_muestra_pesos_readonly(self):
        self._preparar_etapa_calculo_peso_real('ar_readonly_peso')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True), patch(
            'apps.home.views._ticket_pesaje_obligatorio_guardado', return_value=True,
        ):
            response = self.client.get(
                reverse('operacion_planta_citacion', args=[self.retiro.id]),
                {'_empresa_id': 2},
            )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('CALCULO PESO REAL PROSESA', html)
        self.assertNotIn('MODO QA:', html)
        self.assertNotIn('class="form-control form-control-sm peso-qa-prosesa"', html)
        for folio in ('38724-ENT', '38724-SAL', '38729-ENT', '38729-SAL'):
            self.assertIn(folio, html)

    @override_settings(QA_PESAJE=True)
    def test_qa_pesaje_true_muestra_cuatro_inputs_y_aviso(self):
        self._preparar_etapa_calculo_peso_real('ar_ui_qa_peso')
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True), patch(
            'apps.home.views._ticket_pesaje_obligatorio_guardado', return_value=True,
        ):
            response = self.client.get(
                reverse('operacion_planta_citacion', args=[self.retiro.id]),
                {'_empresa_id': 2},
            )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('MODO QA:', html)
        self.assertEqual(
            html.count('class="form-control form-control-sm peso-qa-prosesa"'),
            4,
        )
        self.assertIn('Los tickets originales no seran modificados.', html)
        self.assertIn('Peso QA', html)
        self.assertIn('Peso usado', html)
        self.assertNotIn('Motivo QA', html)
        self.assertNotIn('motivo_qa', html)
        self.assertIn('Formula aplicada: (', html)
        self.assertIn('formula-p2-tara-prosesa', html)
        self.assertIn('formula-peso-real-prosesa', html)
        self.assertIn("fila.find('.peso-usado-prosesa').text(peso + ' kg');", html)
        self.assertIn("box.find('.formula-p1-ent-prosesa').text(valores.p1_ent);", html)
        self.assertIn("box.find('.formula-p1-sal-prosesa').text(valores.p1_sal);", html)
        self.assertIn("box.find('.formula-p2-tara-prosesa').text(valores.p2_ent);", html)
        self.assertIn("box.find('.formula-p2-sal-prosesa').text(valores.p2_sal);", html)
        self.assertIn("box.find('.valor-peso-real-prosesa, .formula-peso-real-prosesa').text(real);", html)
        self.assertIn('CALCULAR Y VALIDAR PESO REAL', html)
    @override_settings(QA_PESAJE=False)
    def test_qa_pesaje_false_backend_rechaza_override(self):
        _, url = self._preparar_etapa_calculo_peso_real('ar_rechaza_override')
        response = self.client.post(url, {
            '_empresa_id': 2,
            'p1_ent': 33000,
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn('QA_PESAJE esta deshabilitado', response.json()['message'])
        self.assertFalse(DATO_OPERACION.objects.filter(
            CAMP_NID__CA_CCODIGO__startswith='QA_PROSESA_',
        ).exists())

    @override_settings(QA_PESAJE=True)
    def test_qa_true_sin_override_usa_tickets_y_backend_recalcula(self):
        _, url = self._preparar_etapa_calculo_peso_real('ar_calculo_ticket')
        response = self.client.post(url, {'_empresa_id': 2, 'peso_real_insumo': 999999})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['peso_real_insumo'], 17000)
        resultado = DATO_OPERACION.objects.get(
            CI_NID=self.retiro,
            CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PESO_REAL_INSUMO,
        )
        metadata = json.loads(resultado.DO_CVALOR)
        self.assertTrue(all(
            fuente['origen'] == 'TICKET'
            for fuente in metadata['fuentes_pesajes'].values()
        ))

    @override_settings(QA_PESAJE=True)
    def test_qa_pesaje_true_persiste_overrides_sin_modificar_tickets(self):
        fuentes = self._crear_cuatro_pesajes_validos()
        originales = {clave: dato.DO_NPESO for clave, dato in fuentes.items()}
        self._completar_retiro_temporal()
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.retiro, OPL_CPASO='Autorizar Salida',
        ).delete()
        views.SYSLOGGER.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.retiro.id),
        )
        asistente = self._usuario_operacional('ar_override_peso', 'ASISTENTE_RECEPCION')
        self._iniciar_sesion_operacional(asistente)
        url = reverse('ajax_operacion_planta_calcular_peso_real_prosesa', args=[self.retiro.id])
        response = self.client.post(url, {
            '_empresa_id': 2,
            'p1_ent': 34000,
            'p1_sal': 12000,
            'p2_ent': 11000,
            'p2_sal': 14000,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['peso_real_insumo'], 19000)
        for clave, dato in fuentes.items():
            dato.refresh_from_db()
            self.assertEqual(dato.DO_NPESO, originales[clave])
        overrides = DATO_OPERACION.objects.filter(
            CAMP_NID__CA_CCODIGO__startswith='QA_PROSESA_',
        )
        self.assertEqual(overrides.count(), 1)
        override = overrides.get()
        metadata_override = json.loads(override.DO_CVALOR)
        self.assertNotIn('motivo_qa', metadata_override)
        self.assertIn('ticket_dato_id', metadata_override)
        self.assertIn('ticket_folio', metadata_override)
        self.assertEqual(metadata_override['peso_override_kg'], 34000)
        resultado = DATO_OPERACION.objects.get(
            CI_NID=self.retiro,
            CAMP_NID__CA_CCODIGO=CAMPO_PROSESA_PESO_REAL_INSUMO,
        )
        metadata = json.loads(resultado.DO_CVALOR)
        self.assertEqual(metadata['fuentes_pesajes']['p1_ent']['origen'], 'QA_OVERRIDE')
        self.assertTrue(all(
            metadata['fuentes_pesajes'][clave]['origen'] == 'TICKET'
            for clave in ('p1_sal', 'p2_ent', 'p2_sal')
        ))

    @override_settings(QA_PESAJE=True)
    def test_cambio_override_recalcula_y_conserva_historial(self):
        self._crear_cuatro_pesajes_validos()
        views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion, {'p1_ent': 33000}, self.usuario,
        )
        primero, _ = calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self.assertEqual(primero.DO_NPESO, 18000)
        views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion, {'p1_ent': 34000}, self.usuario,
        )
        segundo, actualizado = calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self.assertTrue(actualizado)
        self.assertEqual(segundo.id, primero.id)
        self.assertEqual(segundo.DO_NPESO, 19000)
        metadata = json.loads(segundo.DO_CVALOR)
        self.assertEqual(metadata['historial_calculos'][-1]['peso_real_insumo'], 18000)
        self.assertEqual(DATO_OPERACION.objects.filter(
            CAMP_NID__CA_CCODIGO=views.CAMPO_QA_PROSESA_P1_PESO_ENTRADA,
        ).count(), 2)

    @override_settings(QA_PESAJE=False)
    def test_autorizar_salida_exige_peso_real_y_luego_lo_acepta(self):
        asistente, calcular_url = self._preparar_etapa_calculo_peso_real('ar_bloqueo_peso')
        autorizar_url = reverse('ajax_operacion_planta_autorizar_salida', args=[self.retiro.id])
        with patch('apps.home.views.citacion_habilitada_operacion', return_value=True):
            bloqueado = self.client.post(autorizar_url, {'_empresa_id': 2})
            self.assertEqual(bloqueado.status_code, 409)
            self.assertEqual(
                bloqueado.json()['message'],
                'Debe calcular y validar el peso real del insumo antes de autorizar la salida.',
            )
            calculado = self.client.post(calcular_url, {'_empresa_id': 2})
            self.assertEqual(calculado.status_code, 200, calculado.content)
            autorizado = self.client.post(autorizar_url, {'_empresa_id': 2})
        self.assertEqual(autorizado.status_code, 200, autorizado.content)
        self.assertEqual(autorizado.json()['paso'], 'Autorizar Salida')
        self.assertEqual(asistente.username, autorizado.json()['usuario'])

    @override_settings(QA_PESAJE=False)
    def test_helper_futuro_sap_retorna_solo_peso_persistido(self):
        self._crear_cuatro_pesajes_validos()
        with self.assertRaisesMessage(ValueError, 'Debe calcular y validar'):
            views.obtener_peso_real_prosesa_para_sap(self.retiro)
        calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self.assertEqual(
            views.obtener_peso_real_prosesa_para_sap(self.retiro),
            17000,
        )

    @override_settings(QA_PESAJE=True, BODEGA_VIRTUAL='B_TRANSI')
    def test_contexto_qa_expone_relacion_guia_contenedor_y_cuatro_pesos(self):
        self._crear_cuatro_pesajes_validos()
        self.retiro.CI_CNUMERODOCUMENTO = '57950'
        self.retiro.save(update_fields=['CI_CNUMERODOCUMENTO'])
        contexto = views.contexto_peso_real_prosesa(self.retiro)
        self.assertTrue(contexto['qa_habilitado'])
        self.assertEqual(contexto['citacion_piso1_id'], 38724)
        self.assertEqual(contexto['citacion_piso2_id'], 38729)
        self.assertEqual(contexto['guia'], '57950')
        self.assertEqual(contexto['contenedor'], 'CONT-1')
        self.assertEqual(len(contexto['pesajes']), 4)
        self.assertEqual(contexto['peso_real_insumo'], 17000)
        self.assertEqual(contexto['origen_sap'], 'B_TRANSI')
        self.assertIsNone(contexto['cantidad_sap'])

    @override_settings(QA_PESAJE=True)
    def test_otro_flujo_no_expone_edicion_qa(self):
        contexto = views.contexto_peso_real_prosesa(self.legacy)
        self.assertFalse(contexto['aplicable'])
        self.assertNotIn('pesajes', contexto)
    @override_settings(QA_PESAJE=False)
    def test_qa_false_ignora_override_existente_y_usa_ticket_original(self):
        self._crear_cuatro_pesajes_validos()
        with override_settings(QA_PESAJE=True):
            views.guardar_overrides_qa_pesaje_prosesa(
                self.relacion, {'p1_ent': 34000}, self.usuario,
            )
        pesajes = resolver_pesajes_prosesa(self.relacion)
        self.assertEqual(pesajes['p1_ent']['peso_original'], 32000)
        self.assertEqual(pesajes['p1_ent']['peso_efectivo'], 32000)
        self.assertEqual(pesajes['p1_ent']['origen_peso'], 'TICKET')

    @override_settings(QA_PESAJE=True)
    def test_qa_con_pesos_originales_no_crea_overrides(self):
        self._crear_cuatro_pesajes_validos()
        guardados = views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion,
            {'p1_ent': 32000, 'p1_sal': 12000, 'p2_ent': 11000, 'p2_sal': 14000},
            self.usuario,
        )
        self.assertEqual(guardados, [])
        self.assertFalse(DATO_OPERACION.objects.filter(
            CAMP_NID__CA_CCODIGO__startswith='QA_PROSESA_',
        ).exists())

    @override_settings(QA_PESAJE=True)
    def test_override_idempotente_no_duplica_dato_qa(self):
        self._crear_cuatro_pesajes_validos()
        primero = views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion, {'p1_ent': 34000}, self.usuario,
        )
        segundo = views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion, {'p1_ent': 34000}, self.usuario,
        )
        self.assertEqual(len(primero), 1)
        self.assertEqual(len(segundo), 1)
        self.assertEqual(primero[0].id, segundo[0].id)
        self.assertEqual(DATO_OPERACION.objects.filter(
            CAMP_NID__CA_CCODIGO=views.CAMPO_QA_PROSESA_P1_PESO_ENTRADA,
        ).count(), 1)

    @override_settings(QA_PESAJE=True)
    def test_formula_efectiva_en_contexto_coincide_con_backend(self):
        self._crear_cuatro_pesajes_validos()
        views.guardar_overrides_qa_pesaje_prosesa(
            self.relacion, {'p1_ent': 34000, 'p2_sal': 15000}, self.usuario,
        )
        contexto = views.contexto_peso_real_prosesa(self.retiro)
        dato, _ = calcular_y_persistir_peso_real_prosesa(self.relacion, self.usuario)
        self.assertEqual(contexto['pesajes_por_clave']['p1_ent']['peso_original'], 32000)
        self.assertEqual(contexto['pesajes_por_clave']['p1_ent']['peso_efectivo'], 34000)
        self.assertEqual(contexto['peso_contenedor_cargado'], 22000)
        self.assertEqual(contexto['peso_contenedor_vacio'], 4000)
        self.assertEqual(contexto['peso_real_insumo'], 18000)
        self.assertEqual(dato.DO_NPESO, contexto['peso_real_insumo'])
