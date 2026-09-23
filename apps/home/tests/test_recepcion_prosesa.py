import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    CITACION_PROSESA_RELACION,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
    SOCIONEGOCIO,
)
from apps.home.views import (
    CIT_TERMINADO,
    ESTADO_PROSESA_ESPERANDO_RETIRO,
    PASO_BORRADOR_SAP,
    PASOS_RECEPCION_BODEGA_EXTERNA,
    PASO_PROSESA_DEPOSITAR_PISO_1,
    PASO_PROSESA_RETIRAR_CONTENEDOR,
    SECUENCIA_RECEPCION_PROSESA_PISO_1,
    SECUENCIA_RECEPCION_PROSESA_PISO_2,
    _cerrar_operacion_prosesa,
    asegurar_flujos_recepcion_etapa_0,
    es_recepcion_prosesa_piso_1,
    es_recepcion_prosesa_piso_2,
    obtener_pasos_operacion_citacion,
    preparar_item_prosesa_piso_2_desde_origen,
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
        ahora = timezone.now()
        cls.origen = CITACION.objects.create(
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
            CDO_CALMACEN_DESTINO='01',
            CDO_CESTANQUE_DESTINO='E-01',
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

    def test_flujos_prosesa_son_independientes_y_no_incluyen_sap(self):
        self.assertTrue(es_recepcion_prosesa_piso_1(self.origen))
        self.assertTrue(es_recepcion_prosesa_piso_2(self.retiro))
        self.assertFalse(es_recepcion_prosesa_piso_1(self.legacy))
        nombre_1, pasos_1 = obtener_pasos_operacion_citacion(self.origen)
        nombre_2, pasos_2 = obtener_pasos_operacion_citacion(self.retiro)
        self.assertEqual(nombre_1, 'RECEPCION PROSESA PISO 1')
        self.assertEqual(nombre_2, 'RECEPCION PROSESA PISO 2')
        self.assertIn(PASO_PROSESA_DEPOSITAR_PISO_1, [paso for paso, _ in pasos_1])
        self.assertIn(PASO_PROSESA_RETIRAR_CONTENEDOR, [paso for paso, _ in pasos_2])
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

    def _respuesta_creacion_piso_2(self, guia_marker):
        item = {
            'fecha_llegada': '2026-09-17',
            'tipo_operacion': 'RECEPCION',
            'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': str(self.secuencia_piso_2.id),
        }
        if guia_marker is not None:
            item['guia_origen_prosesa'] = guia_marker
        request = RequestFactory().post(
            '/crear-planificacion-citacion/',
            {
                'flujo': 'INGRESO_MERCADERIA',
                'citaciones_json': json.dumps([item]),
            },
        )
        request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=2), patch(
            'apps.home.views.empresa_es_terramar_chile', return_value=False,
        ):
            return views.CREAR_PLANIFICACION_CITACION.__wrapped__(request)

    def test_piso_2_exige_guia(self):
        response = self._respuesta_creacion_piso_2(None)
        self.assertEqual(response.status_code, 400)
        self.assertIn('piso 2', json.loads(response.content)['message'].lower())

    def test_piso_2_rechaza_guia_inexistente(self):
        response = self._respuesta_creacion_piso_2('GUIA-INEXISTENTE')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(json.loads(response.content)['success'])

    def test_piso_2_rechaza_origen_que_no_esta_esperando_retiro(self):
        self.origen.CI_CESTADO = CIT_TERMINADO
        self.origen.save(update_fields=['CI_CESTADO'])
        response = self._respuesta_creacion_piso_2('GUIA-PROSESA-1')
        self.assertEqual(response.status_code, 404)
