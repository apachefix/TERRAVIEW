"""Estado del camion muestra unicamente procesos vigentes por patente."""

import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import CAMION_PATIO, CITACION, SECUENCIA


class EstadoCamionActivoPatenteTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .test_recepcion_prosesa import RecepcionProsesaTestCase
        RecepcionProsesaTestCase.setUpTestData.__func__(cls)

    def setUp(self):
        self.historico = CAMION_PATIO.objects.get(CI_NID=self.retiro)
        self.historico.CPA_CPATENTE = 'SDS45'
        self.historico.CPA_CESTADO = CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA
        self.historico.save(update_fields=['CPA_CPATENTE', 'CPA_CESTADO'])
        self.retiro.CI_CESTADO = views.CIT_TERMINADO
        self.retiro.save(update_fields=['CI_CESTADO'])

    def consultar(self):
        request = RequestFactory().get('/estado-camion/', {'patente': 'SDS45'})
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[],
        ), patch.object(
            views, 'buscar_citacion_vigente_sin_ingreso_por_patente', return_value=[],
        ), patch.object(views, 'registrar_log_camion_no_planificado'):
            response = views.estado_camion_ajax(request)
        return response, json.loads(response.content)

    def nuevo_jersey_activo(self):
        secuencia = SECUENCIA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO=views.SECUENCIA_RECEPCION_NEW_JERSEY_P1_CON_CALIDAD,
            SE_CNOMBRE='Sector New Jersey', SE_BHABILITADO=True,
        )
        self.legacy.SC_NID = secuencia
        self.legacy.CI_CESTADO = 'EN PROCESO'
        self.legacy.save(update_fields=['SC_NID', 'CI_CESTADO'])
        return CAMION_PATIO.objects.create(
            EP_NID=self.empresa, CI_NID=self.legacy,
            CPA_CPATENTE='SDS45', CPA_CNOMBRE_CONDUCTOR='Nuevo conductor',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.usuario,
        )

    def test_salida_confirmada_y_citacion_terminada_no_son_actividad_actual(self):
        response, data = self.consultar()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['tipo_resultado'], 'SIN_CITACION_VIGENTE')
        self.assertIn('No existe un proceso activo', data['message'])
        self.assertNotIn('38729', json.dumps(data))
        self.assertTrue(CAMION_PATIO.objects.filter(pk=self.historico.pk).exists())
        self.assertEqual(CITACION.objects.get(pk=38729).CI_CESTADO, views.CIT_TERMINADO)

    def test_citacion_terminada_no_se_reactiva_aunque_patio_diga_asociado(self):
        self.historico.CPA_CESTADO = CAMION_PATIO.ESTADO_ASOCIADO_CITACION
        self.historico.save(update_fields=['CPA_CESTADO'])
        _, data = self.consultar()
        self.assertEqual(data['tipo_resultado'], 'SIN_CITACION_VIGENTE')
        self.assertEqual(
            CAMION_PATIO.objects.get(pk=self.historico.pk).CPA_CESTADO,
            CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        )

    def test_patente_reutilizada_muestra_solo_new_jersey_activo(self):
        nuevo = self.nuevo_jersey_activo()
        with patch.object(views, '_estado_camion_payload', return_value={
            'citacion_id': self.legacy.id,
            'secuencia': 'Sector New Jersey',
        }):
            response, data = self.consultar()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['tipo_resultado'], 'PROCESO_ACTIVO')
        self.assertEqual(data['data']['camion_patio_id'], nuevo.id)
        self.assertEqual(data['data']['citacion_id'], self.legacy.id)
        self.assertNotEqual(data['data']['citacion_id'], 38729)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=self.historico.pk).exists())

    def test_dos_procesos_activos_devuelven_inconsistencia(self):
        for numero in (1, 2):
            CAMION_PATIO.objects.create(
                EP_NID=self.empresa, CPA_CPATENTE='SDS45',
                CPA_CNOMBRE_CONDUCTOR=f'Conductor {numero}',
                CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
                CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
                US_GUARDIA_ID=self.usuario,
            )
        with patch.object(views.logger, 'error') as log:
            response, data = self.consultar()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(data['tipo_resultado'], 'PROCESOS_ACTIVOS_AMBIGUOS')
        self.assertIn('multiples procesos activos', data['message'])
        log.assert_called_once()

    def test_estados_rechazado_y_cancelado_no_son_activos(self):
        for estado in (CAMION_PATIO.ESTADO_RECHAZADO, CAMION_PATIO.ESTADO_CANCELADO):
            self.historico.CPA_CESTADO = estado
            self.historico.save(update_fields=['CPA_CESTADO'])
            _, data = self.consultar()
            self.assertEqual(data['tipo_resultado'], 'SIN_CITACION_VIGENTE')