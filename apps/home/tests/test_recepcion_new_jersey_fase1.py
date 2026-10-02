import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CAMION_PATIO, CITACION, COMUNA, DETALLE_SECUENCIA, EMPRESA, ETAPA, ETAPA_LOG, ITEM, OPERACION_NEW_JERSEY,
    OPERACION_NEW_JERSEY_PROCESO, PLANIFICACION, PROVINCIA, REGION, RUTA, SECUENCIA, SOCIONEGOCIO, TARIFA_GLOBAL,
)


@override_settings(BODEGA_VIRTUAL='B_TRANSI', BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
class RecepcionNewJerseyFase1TestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('new_jersey_test', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='99-9',
            EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.empresa_1 = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='88-8',
            EP_CBASEDATOS='TEST1', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.cliente = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa, SN_CCODIGO_SAP='C-NJ',
            SN_CRAZONSOCIAL='Cliente New Jersey', SN_CRUT='11-1', SN_CTIPO='C',
        )
        cls.proveedor = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa, SN_CCODIGO_SAP='P-NJ',
            SN_CRAZONSOCIAL='Proveedor New Jersey', SN_CRUT='22-2', SN_CTIPO='S',
        )
        ITEM.objects.create(id=26, EP_NID=cls.empresa, IT_CCODIGO='ITEM-NJ', IT_CNOMBRE='Producto New Jersey')
        cls.legacy_con = SECUENCIA.objects.create(
            id=59, US_NID=cls.usuario, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_PATIO_LF_CON_CALIDAD',
            SE_CNOMBRE='Patio LF con Calidad historico', SE_BHABILITADO=True,
        )
        cls.legacy_sin = SECUENCIA.objects.create(
            id=60, US_NID=cls.usuario, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_PATIO_LF_SIN_CALIDAD',
            SE_CNOMBRE='Patio LF sin Calidad historico', SE_BHABILITADO=True,
        )
        cls.secuencias = views.asegurar_flujos_new_jersey(2, cls.usuario)
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, CA_CNOMBRE='New Jersey',
            CA_FHORA_APERTURA='00:00', CA_FHORA_CIERRE='23:59',
            CA_NDIA=25, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=20,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=6,
        )
        for indice, citacion_id in enumerate((38584, 38596, 38585, 38597, 38696, 38697)):
            CITACION.objects.create(
                id=citacion_id, US_NID=cls.usuario, EP_NID=cls.empresa,
                PL_NID=cls.planificacion,
                SC_NID=cls.legacy_con if indice % 2 == 0 else cls.legacy_sin,
                CI_FFECHAREGISTRO=timezone.now(), CI_FFECHACITACION=timezone.now(),
                CI_NCUPO=indice + 1, CI_CTIPO='RECEPCION', CI_CESTADO='EN PROCESO',
            )

    def item(self, codigo_secuencia):
        return {
            'fecha_llegada': '2026-09-26', 'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencias[codigo_secuencia].id),
            'cliente': str(self.cliente.id), 'cliente_codigo': self.cliente.SN_CCODIGO_SAP,
            'cliente_nombre': self.cliente.SN_CRAZONSOCIAL,
            'proveedor': str(self.proveedor.id), 'proveedor_codigo': self.proveedor.SN_CCODIGO_SAP,
            'codigo_proveedor_sap': self.proveedor.SN_CCODIGO_SAP,
            'proveedor_nombre': self.proveedor.SN_CRAZONSOCIAL,
            'proveedor_sap': self.proveedor.SN_CRAZONSOCIAL,
            'tipo_carga': 'CONTENEDOR', 'tipo_origen_recepcion': 'NACIONAL',
            'codigo': 'ITEM-NJ', 'codigo_sap': 'ITEM-NJ', 'insumo': 'Producto New Jersey',
            'pedido': '4500099', 'sap_opor_id': '7001', 'docentry': '7001',
            'base_line': '2', 'cantidad_disponible': '30',
            'almacen_destino': 'NEW_JERSEY', 'estanque_destino': 'TK-NJ-01',
        }

    def crear(self, codigo_secuencia):
        request = RequestFactory().post('/crear-planificacion-citacion/', {
            'flujo': 'INGRESO_MERCADERIA',
            'citaciones_json': json.dumps([self.item(codigo_secuencia)]),
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ), patch(
            'apps.home.views.validar_destino_recepcion_sbh', return_value=(True, ''),
        ), patch(
            'apps.home.views.normalizar_proveedor_ingreso_mercaderia_sbh',
            return_value=(self.proveedor.SN_CRAZONSOCIAL, ''),
        ), patch('apps.home.views.consultar_saldo_linea_pedido_sap', return_value={
            'DocStatus': 'O', 'LineNum': 2, 'OpenQty': '30',
        }):
            return views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)

    def test_ui_sector_modalidades_y_ocultamiento_tecnico(self):
        template = (
            Path(views.__file__).resolve().parents[1]
            / 'templates' / 'home' / 'PLANIFICACION' / 'pla_addone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Recepci\\u00f3n - Sector New Jersey', template)
        self.assertIn('Modalidad New Jersey', template)
        self.assertIn('Contenedor a Piso con Calidad', template)
        self.assertIn('Contenedor a Piso sin Calidad', template)
        self.assertNotIn('Recepcion - Patio LF con Calidad', template)
        self.assertNotIn(views.SECUENCIA_RECEPCION_NEW_JERSEY_P2, template)
        self.assertNotIn(views.SECUENCIA_RECEPCION_NEW_JERSEY_P3, template)

    def test_allowlist_etapa_0_incluye_p1_y_excluye_p2_p3_legacy(self):
        codigos = set(views.queryset_secuencias_recepcion_sbh_por_flujo(
            2, 'INGRESO_MERCADERIA'
        ).values_list('SE_CCODIGO', flat=True))
        self.assertTrue(views.SECUENCIAS_RECEPCION_NEW_JERSEY_P1 <= codigos)
        self.assertNotIn(views.SECUENCIA_RECEPCION_NEW_JERSEY_P2, codigos)
        self.assertNotIn(views.SECUENCIA_RECEPCION_NEW_JERSEY_P3, codigos)
        self.assertTrue(codigos.isdisjoint(views.SECUENCIAS_RECEPCION_LEGACY_NO_ETAPA_0))

    def test_etapas_empresa_2_y_sin_responsables_legacy(self):
        for secuencia in self.secuencias.values():
            detalles = secuencia.detalle_secuencia_set.select_related('ET_NID').all()
            self.assertTrue(detalles.exists())
            self.assertEqual({detalle.ET_NID.EP_NID_id for detalle in detalles}, {2})
            self.assertEqual({detalle.USERS_RESPONSABLE_ID for detalle in detalles}, {None})

    def test_legacy_y_seis_historicos_permanecen_intactos(self):
        views.asegurar_flujos_recepcion_etapa_0(2, self.usuario)
        self.legacy_con.refresh_from_db()
        self.legacy_sin.refresh_from_db()
        self.assertEqual(self.legacy_con.SE_CCODIGO, 'RECEPCION_PATIO_LF_CON_CALIDAD')
        self.assertEqual(self.legacy_sin.SE_CCODIGO, 'RECEPCION_PATIO_LF_SIN_CALIDAD')
        historicos = CITACION.objects.filter(
            id__in=(38584, 38596, 38585, 38597, 38696, 38697)
        )
        self.assertEqual(historicos.count(), 6)
        self.assertEqual(set(historicos.values_list('SC_NID_id', flat=True)), {59, 60})

    def test_creacion_con_calidad_genera_plan_citacion_operacion_y_solo_p1(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        self.assertEqual(len(payload['citaciones']), 1)
        self.assertEqual(len(payload['operaciones_new_jersey']), 1)
        operacion = OPERACION_NEW_JERSEY.objects.get(pk=payload['operaciones_new_jersey'][0])
        self.assertEqual(operacion.ONJ_CMODALIDAD, OPERACION_NEW_JERSEY.Modalidad.CON_CALIDAD)
        self.assertEqual(operacion.ONJ_CESTADO, OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_1)
        self.assertEqual(operacion.ONJ_CBODEGA_VIRTUAL, 'B_NJ_TEST')
        self.assertEqual((operacion.ONJ_CBASE_ENTRY, operacion.ONJ_CBASE_LINE), ('7001', '2'))
        self.assertEqual(list(operacion.procesos.values_list('ONJP_CTIPO', flat=True)), ['PROCESO_1'])

    def test_creacion_sin_calidad_genera_modalidad_y_solo_p1(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        citacion = CITACION.objects.get(pk=payload['citaciones'][0])
        operacion = OPERACION_NEW_JERSEY.objects.get(pk=payload['operaciones_new_jersey'][0])
        self.assertEqual(citacion.SC_NID.SE_CCODIGO, views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD)
        self.assertEqual(operacion.ONJ_CMODALIDAD, OPERACION_NEW_JERSEY.Modalidad.SIN_CALIDAD)
        self.assertFalse(operacion.procesos.filter(ONJP_CTIPO__in=['PROCESO_2', 'PROCESO_3']).exists())

    def test_helpers_y_operacion_planta_usan_codigo_estable(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD)
        citacion = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        self.assertTrue(views.es_recepcion_new_jersey(citacion))
        self.assertTrue(views.es_recepcion_new_jersey_p1(citacion))
        self.assertTrue(views.es_recepcion_new_jersey_p1_con_calidad(citacion))
        self.assertFalse(views.es_recepcion_new_jersey_p1_sin_calidad(citacion))
        nombre, pasos = views.obtener_pasos_operacion_citacion(citacion)
        self.assertEqual(nombre, 'RECEPCION SECTOR NEW JERSEY')
        self.assertEqual(
            [paso for paso, _ in pasos],
            ['Pesaje Entrada', views.PASO_NJ_DESCARGA_CONTENEDOR, 'Pesaje Salida',
             views.PASO_AUTORIZAR_SALIDA, views.PASO_CONFIRMAR_SALIDA],
        )
        citacion.CI_CTIPO = 'DESPACHO'
        self.assertFalse(views.es_recepcion_new_jersey(citacion))
        citacion.CI_CTIPO = 'RECEPCION'
        citacion.EP_NID_id = 1
        self.assertFalse(views.es_recepcion_new_jersey(citacion))

    def test_sin_calidad_omite_calidad_y_legacy_prosesa_no_califican(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD)
        citacion = CITACION.objects.get(pk=json.loads(response.content)['citaciones'][0])
        _, pasos = views.obtener_pasos_operacion_citacion(citacion)
        nombres = [paso for paso, _ in pasos]
        self.assertNotIn('Toma de muestra', nombres)
        self.assertNotIn('Analisis y calidad', nombres)
        legacy = CITACION(EP_NID=self.empresa, SC_NID=self.legacy_con, CI_CTIPO='RECEPCION')
        self.assertFalse(views.es_recepcion_new_jersey(legacy))
        prosesa = SECUENCIA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=views.SECUENCIA_RECEPCION_PROSESA_PISO_1,
            SE_CNOMBRE='Prosesa', SE_BHABILITADO=True,
        )
        self.assertFalse(views.es_recepcion_new_jersey(
            CITACION(EP_NID=self.empresa, SC_NID=prosesa, CI_CTIPO='RECEPCION')
        ))

    def test_constraints_relacion_y_codigos_peso_reservados(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD)
        proceso = OPERACION_NEW_JERSEY_PROCESO.objects.get(
            CI_NID_id=json.loads(response.content)['citaciones'][0]
        )
        duplicado = OPERACION_NEW_JERSEY_PROCESO(
            ONJ_NID=proceso.ONJ_NID, CI_NID=CITACION.objects.get(pk=38584),
            EP_NID=self.empresa, US_NID=self.usuario,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
        )
        with self.assertRaises(ValidationError):
            duplicado.full_clean()
        self.assertEqual(views.NJ_P1_PESO_INICIAL_KG, 'NJ_P1_PESO_INICIAL_KG')
        self.assertEqual(views.NJ_P3_PESO_TARA_CAMION_KG, 'NJ_P3_PESO_TARA_CAMION_KG')
        self.assertEqual(
            views.NJ_P3_PESO_CAMION_CONTENEDOR_VACIO_KG,
            'NJ_P3_PESO_CAMION_CONTENEDOR_VACIO_KG',
        )
        self.assertEqual(views.NJ_PESO_FINAL_PRODUCTO_KG, 'NJ_PESO_FINAL_PRODUCTO_KG')

    def test_relacion_rechaza_citacion_de_otra_empresa(self):
        response = self.crear(views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD)
        operacion = OPERACION_NEW_JERSEY.objects.get(
            pk=json.loads(response.content)['operaciones_new_jersey'][0]
        )
        relacion = OPERACION_NEW_JERSEY_PROCESO(
            ONJ_NID=operacion,
            CI_NID=CITACION(
                EP_NID=self.empresa_1,
                SC_NID=self.legacy_con,
                CI_CTIPO='RECEPCION',
            ),
            EP_NID=self.empresa,
            US_NID=self.usuario,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
        )
        with self.assertRaises(ValidationError):
            relacion.clean()


@override_settings(BODEGA_VIRTUAL='B_TRANSI', BODEGA_VIRTUAL_NEW_JERSEY='B_NJ_TEST')
class RecepcionNewJerseyRutaTransportistaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('nj_rutas', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='99-9',
            EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.empresa_maestra = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='88-8',
            EP_CBASEDATOS='TEST1', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.transportista = SOCIONEGOCIO.objects.create(
            id=1973, EP_NID=cls.empresa, SN_CCODIGO_SAP='SAEZ-2',
            SN_CRAZONSOCIAL='TRANSPORTES SAEZ LIMITADA',
            SN_CRUT='77061844-4', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.transportista_maestro = SOCIONEGOCIO.objects.create(
            id=1446, EP_NID=cls.empresa_maestra, SN_CCODIGO_SAP='SAEZ-1',
            SN_CRAZONSOCIAL=cls.transportista.SN_CRAZONSOCIAL,
            SN_CRUT=cls.transportista.SN_CRUT, SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.otro_transportista = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa_maestra, SN_CCODIGO_SAP='OTRO',
            SN_CRAZONSOCIAL='OTRO TRANSPORTISTA', SN_CRUT='12345678-9',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD,
            SE_CNOMBRE='NEW JERSEY', SE_BHABILITADO=True,
        )
        cls.secuencia_ajena = SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_OTRA', SE_CNOMBRE='OTRA', SE_BHABILITADO=True,
        )
        etapa = ETAPA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='ETAPA_NJ_RUTA', ET_CNOMBRE='Revision NJ rutas',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=etapa, SE_NPASO=1, SE_BOBLIGATORIO=True,
            SE_BHABILITADO=True,
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, CA_CNOMBRE='NJ rutas',
            CA_FHORA_APERTURA='00:00', CA_FHORA_CIERRE='23:59',
            CA_NDIA=27, CA_NMES=9, CA_NANO=2026, CA_NCANTIDADCUPOS=3,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=3,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, PL_NID=cls.planificacion,
            SC_NID=cls.secuencia, CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(), CI_NCUPO=1,
            CI_CTIPO='RECEPCION', CI_CESTADO='EN PROCESO',
        )
        ETAPA_LOG.objects.create(
            CI_NID=cls.citacion, EP_NID=cls.empresa,
            SC_NID=cls.secuencia, ET_NID=etapa,
            US_INICIO_ID=cls.usuario, EL_FFECHAINICIO=timezone.now(),
        )
        CAMION_PATIO.objects.create(
            EP_NID=cls.empresa, CI_NID=cls.citacion, CPA_CPATENTE='NJSAEZ',
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            CPA_CTRANSPORTISTA_DECLARADO=cls.transportista.SN_CRAZONSOCIAL,
            transporte_a_cargo='TERRAMAR', US_GUARDIA_ID=cls.usuario,
        )
        region = REGION.objects.create(RG_CNOMBRE='Biobio NJ', RG_CCODIGO='NJ')
        provincia = PROVINCIA.objects.create(
            RG_NID=region, PV_CNOMBRE='Concepcion NJ', PV_CCODIGO='NJ',
        )
        comuna = COMUNA.objects.create(
            PV_NID=provincia, COM_CNOMBRE='Coronel NJ', COM_CCODIGO='NJ',
        )
        cls.ruta = RUTA.objects.create(
            EP_NID=cls.empresa, RG_NID_INICIO=region, PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna, RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia, COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1, RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='CORONEL -> CORONEL (INTERNO)',
            RUT_CCODIGO='NJ-INTERNO', RUT_BHABILITADO=True,
        )
        cls.tarifa = TARIFA_GLOBAL.objects.create(
            EP_NID=cls.empresa, RUT_NID=cls.ruta,
            SN_NID=cls.transportista_maestro, US_NID=cls.usuario,
            TAR_NVALOR=106738, TAR_CNOMBRETARIFA='FLETE NJ',
            TAR_CTIPOTARIFA='FLETE', TAR_CDIVISA='CLP', TAR_BHABILITADO=True,
        )
        cls.tarifa_ajena = TARIFA_GLOBAL.objects.create(
            EP_NID=cls.empresa, RUT_NID=cls.ruta,
            SN_NID=cls.otro_transportista, US_NID=cls.usuario,
            TAR_NVALOR=999, TAR_CNOMBRETARIFA='FLETE AJENO',
            TAR_CTIPOTARIFA='FLETE', TAR_CDIVISA='CLP', TAR_BHABILITADO=True,
        )

    def test_new_jersey_resuelve_socio_maestro_y_muestra_solo_ruta(self):
        self.assertTrue(views.requiere_ruta_transportista_revision(self.citacion))
        resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
        self.assertEqual(resultado['message'], '')
        self.assertEqual(len(resultado['opciones']), 1)
        opcion = resultado['opciones'][0]
        self.assertEqual(opcion['text'], self.ruta.RUT_CNOMBRE)
        self.assertNotIn('CLP', opcion['text'])
        self.assertNotIn(str(self.tarifa.TAR_NVALOR), opcion['text'])
        self.assertEqual(opcion['tarifa_id'], str(self.tarifa.id))
        self.assertEqual(opcion['ruta_id'], str(self.ruta.id))
        self.assertEqual(opcion['costo'], '106738.00000')
        self.assertEqual(opcion['moneda'], 'CLP')

    def test_ajax_revision_usa_transportista_vigente_y_equivalencia(self):
        request = RequestFactory().get('/ajax-rutas-transportista-revision/', {
            'citacion_id': self.citacion.id,
            'transportista_id': self.transportista.id,
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ):
            response = views.AJAX_RUTAS_TRANSPORTISTA_REVISION(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['results'][0]['tarifa_id'], str(self.tarifa.id))

    def test_guardar_ruta_persiste_tarifa_ruta_y_valor(self):
        tarifa, error = views.validar_tarifa_transportista_revision(
            self.citacion, self.tarifa.id, self.ruta.id,
        )
        self.assertEqual(error, '')
        self.assertEqual(tarifa.id, self.tarifa.id)
        views.guardar_ruta_transportista_revision(self.citacion, tarifa, self.usuario)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.TAR_NID_id, self.tarifa.id)
        self.assertEqual(self.citacion.RUT_NID_id, self.ruta.id)
        self.assertEqual(self.citacion.CI_NVALORTARIFA, self.tarifa.TAR_NVALOR)
        self.assertTrue(views.ruta_transportista_asistente_guardada(self.citacion))

    def test_no_acepta_tarifa_ajena_ni_ruta_incorrecta(self):
        for tarifa_id, ruta_id in (
            (self.tarifa_ajena.id, self.ruta.id),
            (self.tarifa.id, self.ruta.id + 1000),
        ):
            tarifa, error = views.validar_tarifa_transportista_revision(
                self.citacion, tarifa_id, ruta_id,
            )
            self.assertIsNone(tarifa)
            self.assertTrue(error)

    def test_sin_tarifas_reales_informa_y_no_permite_guardar(self):
        self.tarifa.TAR_BHABILITADO = False
        self.tarifa.save(update_fields=['TAR_BHABILITADO'])
        resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
        self.assertEqual(resultado['opciones'], [])
        self.assertIn('TRANSPORTES SAEZ LIMITADA', resultado['message'])
        tarifa, error = views.validar_tarifa_transportista_revision(
            self.citacion, self.tarifa.id, self.ruta.id,
        )
        self.assertIsNone(tarifa)
        self.assertTrue(error)

    def test_cliente_no_requiere_flete_y_recepcion_usa_socio_equivalente(self):
        camion = CAMION_PATIO.objects.get(CI_NID=self.citacion)
        camion.transporte_a_cargo = 'CLIENTE'
        camion.save(update_fields=['transporte_a_cargo'])
        self.assertFalse(views.requiere_ruta_transportista_revision(self.citacion))
        otra = CITACION(
            EP_NID=self.empresa, SC_NID=self.secuencia_ajena,
            CI_CTIPO='RECEPCION',
        )
        self.assertCountEqual(
            views.obtener_ids_transportistas_tarifarios_revision(
                otra, self.transportista,
            ),
            [self.transportista_maestro.id, self.transportista.id],
        )
        despacho = CITACION(EP_NID=self.empresa, SC_NID=self.secuencia_ajena, CI_CTIPO='DESPACHO')
        self.assertEqual(
            views.obtener_ids_transportistas_tarifarios_revision(despacho, self.transportista),
            [self.transportista.id],
        )

    def test_aprobacion_rechaza_ruta_pendiente(self):
        request = RequestFactory().post('/pla-citacion-aprobar-asistente/', {'peso_informado_guia': '24000'})
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ):
            response = views.APROBAR_CAMION_ASISTENTE(request, self.citacion.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Debe guardar la ruta del transportista',
            json.loads(response.content)['message'],
        )

    def test_endpoint_guardar_ruta_valida_y_rechaza_tarifa_ajena(self):
        def guardar(tarifa):
            request = RequestFactory().post('/pla-citacion-guardar-ruta-asistente/', {
                'tarifa_id': tarifa.id,
                'ruta_id': self.ruta.id,
            })
            request.user = self.usuario
            with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
                'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
            ):
                return views.GUARDAR_RUTA_CAMION_ASISTENTE(request, self.citacion.id)

        rechazada = guardar(self.tarifa_ajena)
        self.assertEqual(rechazada.status_code, 400)
        self.citacion.refresh_from_db()
        self.assertIsNone(self.citacion.TAR_NID_id)

        aceptada = guardar(self.tarifa)
        self.assertEqual(aceptada.status_code, 200)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.TAR_NID_id, self.tarifa.id)
        self.assertEqual(self.citacion.RUT_NID_id, self.ruta.id)
    def _aprobar_con_peso_guia(self, valor):
        request = RequestFactory().post(
            '/pla-citacion-aprobar-asistente/',
            {'peso_informado_guia': valor},
        )
        request.user = self.usuario
        etapa = self.citacion.ETAPA_ACTUAL
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ), patch(
            'apps.home.views.avanzar_citacion_a_siguiente_etapa',
            return_value=(etapa, etapa),
        ), patch(
            'apps.home.views.obtener_usuarios_asistente_cd', return_value=[],
        ), patch('apps.home.views.registrar_log_camion_no_planificado'):
            return views.APROBAR_CAMION_ASISTENTE(request, self.citacion.id)

    def test_asistente_bloquea_peso_guia_vacio_o_invalido(self):
        camion = CAMION_PATIO.objects.get(CI_NID=self.citacion)
        camion.transporte_a_cargo = 'CLIENTE'
        camion.save(update_fields=['transporte_a_cargo'])
        for valor in ('', '0', '-1', 'abc', 'NaN'):
            with self.subTest(valor=valor):
                respuesta = self._aprobar_con_peso_guia(valor)
                self.assertEqual(respuesta.status_code, 400, respuesta.content)
                self.assertFalse(views.obtener_peso_informado_guia(self.citacion))

    def test_asistente_guarda_y_corrige_peso_guia_sin_duplicarlo(self):
        camion = CAMION_PATIO.objects.get(CI_NID=self.citacion)
        camion.transporte_a_cargo = 'CLIENTE'
        camion.save(update_fields=['transporte_a_cargo'])
        primera = self._aprobar_con_peso_guia('24000,5')
        self.assertEqual(primera.status_code, 200, primera.content)
        self.assertEqual(views.obtener_peso_informado_guia(self.citacion), '24000.5')
        corregida = self._aprobar_con_peso_guia('25000')
        self.assertEqual(corregida.status_code, 200, corregida.content)
        datos = views.DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views.CAMPO_PESO_INFORMADO_GUIA,
        )
        self.assertEqual(datos.count(), 1)
        self.assertEqual(datos.get().DO_CVALOR, '25000')
        self.assertEqual(datos.get().US_NID_id, self.usuario.id)
    def test_revision_muestra_peso_guia_kg(self):
        request = RequestFactory().get('/pla-citacion-revision-asistente/')
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ):
            response = views.PLANIFICACION_CITACION_REVISION_ASISTENTE(
                request, self.citacion.id,
            )
        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertTrue(payload['requiere_peso_informado_guia'])
        self.assertEqual(payload['peso_informado_guia_unidad'], 'kg')
    def _usar_secuencia_recepcion(self, codigo):
        secuencia = SECUENCIA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=codigo, SE_CNOMBRE=codigo, SE_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SC_NID=secuencia,
            ET_NID=DETALLE_SECUENCIA.objects.get(SC_NID=self.secuencia).ET_NID,
            SE_NPASO=1, SE_BOBLIGATORIO=True, SE_BHABILITADO=True,
        )
        self.citacion.SC_NID = secuencia
        self.citacion.save(update_fields=['SC_NID'])

    def test_estanque_sbh_terramar_usa_mismo_resolvedor_y_guarda_ruta(self):
        self._usar_secuencia_recepcion('RECEPCION_ESTANQUE_SBH')
        self.assertTrue(views.requiere_ruta_transportista_revision(self.citacion))
        self.assertCountEqual(
            views.obtener_ids_transportistas_tarifarios_revision(self.citacion, self.transportista),
            [self.transportista_maestro.id, self.transportista.id],
        )
        resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
        self.assertEqual([opcion['tarifa_id'] for opcion in resultado['opciones']], [str(self.tarifa.id)])
        request = RequestFactory().get('/ajax-rutas-transportista-revision/', {
            'citacion_id': self.citacion.id, 'transportista_id': self.transportista.id,
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ):
            response = views.AJAX_RUTAS_TRANSPORTISTA_REVISION(request)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(json.loads(response.content)['results'][0]['tarifa_id'], str(self.tarifa.id))
        tarifa, error = views.validar_tarifa_transportista_revision(
            self.citacion, self.tarifa.id, self.ruta.id,
        )
        self.assertEqual(error, '')
        views.guardar_ruta_transportista_revision(self.citacion, tarifa, self.usuario)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.RUT_NID_id, self.ruta.id)
        self.assertEqual(self.citacion.TAR_NID_id, self.tarifa.id)
        self.assertTrue(views.ruta_transportista_asistente_guardada(self.citacion))

    def test_prosesa_y_otras_recepciones_usan_equivalencia_tarifaria(self):
        for codigo in (
            views.SECUENCIA_RECEPCION_PROSESA_PISO_1,
            'RECEPCION_BODEGA_EXTERNA',
            'RECEPCION_TRASVASIJE',
        ):
            with self.subTest(codigo=codigo):
                self._usar_secuencia_recepcion(codigo)
                resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
                self.assertEqual([opcion['tarifa_id'] for opcion in resultado['opciones']], [str(self.tarifa.id)])
                validada, error = views.validar_tarifa_transportista_revision(
                    self.citacion, self.tarifa.id, self.ruta.id,
                )
                self.assertEqual(error, '')
                self.assertEqual(validada.id, self.tarifa.id)

    def test_recepcion_aisla_empresa_y_transportista_en_rutas(self):
        ruta_otra_empresa = RUTA.objects.create(
            EP_NID=self.empresa_maestra,
            RG_NID_INICIO=self.ruta.RG_NID_INICIO, PV_NID_INICIO=self.ruta.PV_NID_INICIO,
            COM_NID_INICIO=self.ruta.COM_NID_INICIO,
            RG_NID_TERMINO=self.ruta.RG_NID_TERMINO, PV_NID_TERMINO=self.ruta.PV_NID_TERMINO,
            COM_NID_TERMINO=self.ruta.COM_NID_TERMINO,
            RUT_NTIEMPOMAXIMOENTREGA=1, RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='RUTA EMPRESA 1', RUT_CCODIGO='E1', RUT_BHABILITADO=True,
        )
        tarifa_otra_empresa = TARIFA_GLOBAL.objects.create(
            EP_NID=self.empresa_maestra, RUT_NID=ruta_otra_empresa,
            SN_NID=self.transportista_maestro, US_NID=self.usuario,
            TAR_NVALOR=999, TAR_CNOMBRETARIFA='FLETE EMPRESA 1',
            TAR_CTIPOTARIFA='FLETE', TAR_CDIVISA='CLP', TAR_BHABILITADO=True,
        )
        self._usar_secuencia_recepcion('RECEPCION_ESTANQUE_SBH')
        resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
        self.assertEqual([opcion['tarifa_id'] for opcion in resultado['opciones']], [str(self.tarifa.id)])
        citacion_empresa_1 = CITACION(EP_NID=self.empresa_maestra, CI_CTIPO='RECEPCION')
        with patch('apps.home.views.transportista_vigente_camion_patio', return_value=self.transportista_maestro), patch(
            'apps.home.views.requiere_ruta_transportista_revision', return_value=True,
        ):
            resultado_empresa_1 = views.obtener_rutas_tarifa_transportista(citacion_empresa_1)
        self.assertEqual(
            [opcion['tarifa_id'] for opcion in resultado_empresa_1['opciones']],
            [str(tarifa_otra_empresa.id)],
        )
        for tarifa_id in (tarifa_otra_empresa.id, self.tarifa_ajena.id):
            tarifa, error = views.validar_tarifa_transportista_revision(
                self.citacion, tarifa_id, self.ruta.id,
            )
            self.assertIsNone(tarifa)
            self.assertTrue(error)

    def test_estanque_sin_rutas_y_cliente_no_obligan_guardar(self):
        self._usar_secuencia_recepcion('RECEPCION_ESTANQUE_SBH')
        self.tarifa.TAR_BHABILITADO = False
        self.tarifa.save(update_fields=['TAR_BHABILITADO'])
        resultado = views.obtener_rutas_tarifa_transportista(self.citacion)
        self.assertEqual(resultado['opciones'], [])
        self.assertIn('No existen rutas tarifadas vigentes', resultado['message'])
        self.assertIn('TRANSPORTES SAEZ LIMITADA', resultado['message'])
        camion = CAMION_PATIO.objects.get(CI_NID=self.citacion)
        camion.transporte_a_cargo = 'CLIENTE'
        camion.save(update_fields=['transporte_a_cargo'])
        self.assertFalse(views.requiere_ruta_transportista_revision(self.citacion))
        self.assertEqual(views.obtener_rutas_tarifa_transportista(self.citacion)['opciones'], [])
        request = RequestFactory().get('/ajax-rutas-transportista-revision/', {
            'citacion_id': self.citacion.id, 'transportista_id': self.transportista.id,
        })
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.usuario_es_asistente_recepcion', return_value=True,
        ):
            response = views.AJAX_RUTAS_TRANSPORTISTA_REVISION(request)
        self.assertEqual(json.loads(response.content)['results'], [])
