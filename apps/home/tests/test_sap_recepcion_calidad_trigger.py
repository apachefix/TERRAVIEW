from datetime import time
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CITACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    PLANIFICACION,
    RESULTADO_CALIDAD_OPERACION,
    SECUENCIA,
)
from apps.home.services import calidad_service


class RecepcionSbhDraftScopeTests(SimpleTestCase):
    @staticmethod
    def _citacion(empresa_id, tipo, secuencia):
        return SimpleNamespace(
            EP_NID_id=empresa_id,
            CI_CTIPO=tipo,
            PL_NID=SimpleNamespace(PL_CTIPOCUPO=tipo),
            SC_NID=SimpleNamespace(SE_CCODIGO=secuencia),
        )

    def test_solo_recepcion_estanque_sbh_empresa_2_deja_de_exigir_draft_para_avanzar(self):
        citacion = self._citacion(2, 'RECEPCION', 'RECEPCION_ESTANQUE_SBH')

        self.assertFalse(views.requiere_borrador_sap_recepcion_para_avanzar(citacion))

    def test_resto_de_recepciones_y_empresas_conservan_exigencia_de_draft(self):
        casos = (
            self._citacion(2, 'RECEPCION', 'RECEPCION_BODEGA_EXTERNA'),
            self._citacion(1, 'RECEPCION', 'RECEPCION_ESTANQUE_SBH'),
            self._citacion(2, 'DESPACHO', 'RECEPCION_ESTANQUE_SBH'),
            self._citacion(1, 'DESPACHO', 'EST_SBH_CLIENTE'),
        )

        for citacion in casos:
            with self.subTest(empresa=citacion.EP_NID_id, tipo=citacion.CI_CTIPO):
                self.assertTrue(views.requiere_borrador_sap_recepcion_para_avanzar(citacion))

    def test_confirmar_estanque_no_invoca_creacion_de_borrador(self):
        self.assertNotIn(
            'crear_borrador_sap_recepcion_interno(',
            getsource(views.PLANIFICACION_CITACION_ESTANQUE),
        )

    def test_frontend_sbh_habilita_avance_sin_estado_creado(self):
        template = Path(views.__file__).resolve().parents[1] / 'templates' / 'home' / 'PLANIFICACION' / 'pla_listone.html'
        contenido = template.read_text(encoding='utf-8')
        funcion = contenido.split('function actualizarEstadoSapRecepcionDraft', 1)[1].split('function numeroSap', 1)[0]

        self.assertIn(
            "$('#btn_enviar_estanque').prop('disabled', !puedeEditar || !estanqueGuardado || !pesoGuardado);",
            funcion,
        )
        self.assertIn(
            "$('#btn_enviar_estanque').prop('disabled', !puedeEditar || !estanqueGuardado || !pesoGuardado || !creado);",
            funcion,
        )


class RecepcionSbhDraftPorCalidadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('sap_calidad_test', password='test')
        cls.empresa_1 = cls._crear_empresa(1, 'Empresa Uno', '11-1')
        cls.empresa_2 = cls._crear_empresa(2, 'Empresa Dos', '22-2')
        cls._contextos = {}
        for empresa in (cls.empresa_1, cls.empresa_2):
            for tipo in ('RECEPCION', 'DESPACHO'):
                calendario = CALENDARIO.objects.create(
                    US_NID=cls.user,
                    EP_NID=empresa,
                    CA_CNOMBRE=f'Calidad {empresa.pk} {tipo}',
                    CA_FHORA_APERTURA=time(8),
                    CA_FHORA_CIERRE=time(18),
                    CA_NDIA=1,
                    CA_NMES=1,
                    CA_NANO=2026,
                    CA_NCANTIDADCUPOS=20,
                )
                planificacion = PLANIFICACION.objects.create(
                    US_NID=cls.user,
                    EP_NID=empresa,
                    CAL_NID=calendario,
                    PL_CTIPOCUPO=tipo,
                    PL_FFECHAINICIO=timezone.now(),
                    PL_NCANTIDADCUPOS=20,
                )
                etapa = ETAPA.objects.create(
                    US_NID=cls.user,
                    EP_NID=empresa,
                    ET_CTIPO='OPERACION',
                    ET_CCODIGO=f'ANALISIS_Y_CALIDAD_{tipo}',
                    ET_CNOMBRE=f'Analisis y calidad {tipo}',
                    ET_NCANTIDADMAXIMA=20,
                    ET_BHABILITADO=True,
                )
                cls._contextos[(empresa.pk, tipo)] = (planificacion, etapa)

    @staticmethod
    def _crear_empresa(pk, nombre, rut):
        return EMPRESA.objects.create(
            pk=pk,
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=rut,
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )

    def _crear_citacion(self, empresa, tipo='RECEPCION', codigo='RECEPCION_ESTANQUE_SBH'):
        planificacion, etapa = self._contextos[(empresa.pk, tipo)]
        secuencia = SECUENCIA.objects.create(
            US_NID=self.user,
            EP_NID=empresa,
            SE_CTIPO=tipo,
            SE_CCODIGO=codigo,
            SE_CNOMBRE=f'{tipo} {codigo}',
            SE_BHABILITADO=True,
        )
        citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=empresa,
            PL_NID=planificacion,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=tipo,
            CI_CESTADO='PENDIENTE',
            CI_CNUMERODOCUMENTO=f'GUIA-SAP-CALIDAD-{CITACION.objects.count() + 1}',
        )
        ETAPA_LOG.objects.create(
            CI_NID=citacion,
            EP_NID=empresa,
            SC_NID=secuencia,
            ET_NID=etapa,
            US_INICIO_ID=self.user,
            EL_FFECHAINICIO=timezone.now(),
        )
        return citacion

    def test_aprobado_crea_draft_solo_despues_del_commit_para_todos_los_origenes(self):
        for origen in RESULTADO_CALIDAD_OPERACION.Origen.values:
            with self.subTest(origen=origen):
                citacion = self._crear_citacion(self.empresa_2)
                with patch.object(
                    calidad_service,
                    'get_goods_receipt_draft_guide_status',
                    return_value={'sent': False, 'docentry': None},
                ), patch.object(
                    calidad_service,
                    '_crear_borrador_sap_recepcion_interno_post_commit',
                    return_value={'success': True},
                ) as crear_draft:
                    with self.captureOnCommitCallbacks(execute=False) as callbacks:
                        registro, cambiado = calidad_service.procesar_resultado_calidad(
                            citacion,
                            RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
                            origen,
                            usuario=self.user,
                        )
                        crear_draft.assert_not_called()

                    self.assertTrue(cambiado)
                    self.assertEqual(registro.RCO_CESTADO, RESULTADO_CALIDAD_OPERACION.Estado.APROBADO)
                    self.assertEqual(len(callbacks), 1)
                    callbacks[0]()
                    crear_draft.assert_called_once()

    def test_estados_no_aprobados_no_crean_draft(self):
        casos = (
            RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE,
            RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
            RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE,
        )
        for estado in casos:
            with self.subTest(estado=estado):
                citacion = self._crear_citacion(self.empresa_2)
                with patch.object(
                    calidad_service,
                    '_crear_borrador_sap_recepcion_interno_post_commit',
                ) as crear_draft:
                    with self.captureOnCommitCallbacks(execute=True) as callbacks:
                        if estado == RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE:
                            registro, _ = calidad_service.asegurar_calidad_iniciada(citacion, self.user)
                        else:
                            registro, _ = calidad_service.procesar_resultado_calidad(
                                citacion,
                                estado,
                                RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                                usuario=self.user,
                            )

                    self.assertEqual(registro.RCO_CESTADO, estado)
                    self.assertEqual(callbacks, [])
                    crear_draft.assert_not_called()

    def test_otros_flujos_empresas_y_despachos_no_crean_draft(self):
        casos = (
            (self.empresa_2, 'RECEPCION', 'RECEPCION_BODEGA_EXTERNA'),
            (self.empresa_1, 'RECEPCION', 'RECEPCION_ESTANQUE_SBH'),
            (self.empresa_2, 'DESPACHO', 'EST_SBH_CLIENTE'),
            (self.empresa_1, 'DESPACHO', 'EST_SBH_CLIENTE'),
        )
        for empresa, tipo, codigo in casos:
            with self.subTest(empresa=empresa.pk, tipo=tipo, codigo=codigo):
                citacion = self._crear_citacion(empresa, tipo, codigo)
                with patch.object(
                    calidad_service,
                    '_crear_borrador_sap_recepcion_interno_post_commit',
                ) as crear_draft, patch.object(
                    views,
                    'send_goods_receipt_draft_from_peso_guia_to_sap',
                ) as enviar_sap_recepcion:
                    with self.captureOnCommitCallbacks(execute=True) as callbacks:
                        calidad_service.procesar_resultado_calidad(
                            citacion,
                            RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
                            RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                            usuario=self.user,
                        )

                    self.assertEqual(callbacks, [])
                    crear_draft.assert_not_called()
                    enviar_sap_recepcion.assert_not_called()

    def test_draft_existente_no_duplica_envio(self):
        citacion = self._crear_citacion(self.empresa_2)
        with patch.object(
            calidad_service,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': True, 'docentry': 9876},
        ), patch.object(
            calidad_service,
            '_crear_borrador_sap_recepcion_interno_post_commit',
        ) as crear_draft:
            with self.captureOnCommitCallbacks(execute=True):
                calidad_service.procesar_resultado_calidad(
                    citacion,
                    RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
                    RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                    usuario=self.user,
                )

        crear_draft.assert_not_called()

    def test_repetir_aprobado_permita_reintento_controlado_tras_fallo(self):
        citacion = self._crear_citacion(self.empresa_2)
        with patch.object(
            calidad_service,
            'get_goods_receipt_draft_guide_status',
            return_value={'sent': False, 'docentry': None},
        ), patch.object(
            calidad_service,
            '_crear_borrador_sap_recepcion_interno_post_commit',
            side_effect=({'success': False}, {'success': True}),
        ) as crear_draft:
            with self.captureOnCommitCallbacks(execute=True):
                _, primer_cambio = calidad_service.procesar_resultado_calidad(
                    citacion,
                    RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
                    RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                    usuario=self.user,
                )
            with self.captureOnCommitCallbacks(execute=True):
                _, segundo_cambio = calidad_service.procesar_resultado_calidad(
                    citacion,
                    RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
                    RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                    usuario=self.user,
                )

        self.assertTrue(primer_cambio)
        self.assertFalse(segundo_cambio)
        self.assertEqual(crear_draft.call_count, 2)
