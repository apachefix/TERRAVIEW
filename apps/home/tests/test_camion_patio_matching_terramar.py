from datetime import time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CITACION,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
)


class ScoreRecepcionTerramarTests(SimpleTestCase):
    def setUp(self):
        self.ahora = timezone.now()
        self.camion = SimpleNamespace(
            CPA_CPATENTE='RSZK21',
            CPA_CNUMERO_GUIA='434333',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES SAEZ LIMITADA',
            CPA_CINSUMO_DECLARADO_GUIA='HARINA DE VISCERA 60%',
            CPA_CNOMBRE_CONDUCTOR='CRISTIAN GARCIA',
            CPA_CRUT_CONDUCTOR='11684951-8',
            CPA_CLOTE_CONTENEDOR='5433333',
            CPA_CPROVEEDOR_DECLARADO='Ewos',
            CPA_FFECHALLEGADA=self.ahora,
            CON_NID=SimpleNamespace(id=10510),
        )
        self.citacion = SimpleNamespace(
            PL_NID=SimpleNamespace(PL_FFECHAINICIO=self.ahora + timedelta(hours=4)),
            CI_FFECHACITACION=self.ahora + timedelta(hours=4),
        )
        self.planificados = {
            'patente': 'RSZK21',
            'producto': 'HARINA DE VISCERA 60%',
            'transportista': 'TRANSPORTES SAEZ LIMITADA',
            'transportista_id': 1446,
            'conductor': 'CRISTIAN GARCIA',
            'conductor_id': 10510,
            'rut_conductor': '11684951-8',
            'guia': '434333',
            'contenedor': '5433333',
            'proveedor': '',
            'proveedor_id': None,
            'proveedor_codigo': '',
        }

    def _score(self, **cambios_planificados):
        datos = {**self.planificados, **cambios_planificados}
        with (
            patch.object(
                views,
                '_datos_planificados_recepcion_terramar_patio',
                return_value=datos,
            ),
            patch.object(
                views,
                '_resolver_transportista_snapshot_camion_patio',
                return_value=SimpleNamespace(id=1446),
            ),
        ):
            return views._score_recepcion_terramar_patio(
                self.camion,
                self.citacion,
            )

    def test_patente_exacta_tiene_peso_mayor_que_producto(self):
        self.camion.CPA_CNUMERO_GUIA = ''
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = ''
        self.camion.CPA_CINSUMO_DECLARADO_GUIA = ''
        self.camion.CPA_CNOMBRE_CONDUCTOR = ''
        self.camion.CPA_CRUT_CONDUCTOR = ''
        self.camion.CPA_CLOTE_CONTENEDOR = ''
        self.camion.CPA_CPROVEEDOR_DECLARADO = ''
        self.camion.CON_NID = None
        self.camion.CPA_FFECHALLEGADA = None

        score, _, info = self._score(transportista_id=None, transportista='')

        self.assertEqual(score, 30)
        self.assertEqual(info['desglose'][0]['criterio'], 'Patente')

    def test_patente_normalizada_coincide(self):
        self.camion.CPA_CPATENTE = 'rsz k-21'
        score, _, info = self._score()

        self.assertTrue(info['patente_coincide'])
        self.assertIn('Patente', {item['criterio'] for item in info['desglose']})
        self.assertGreaterEqual(score, 30)

    def test_producto_coincide_con_peso_medio(self):
        self.camion.CPA_CPATENTE = ''
        score, _, info = self._score(patente='')

        producto = next(item for item in info['desglose'] if item['criterio'] == 'Producto')
        self.assertEqual(producto['puntos'], 10)
        self.assertGreater(score, 0)

    def test_transportista_prioriza_id_canonico(self):
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = 'texto distinto'
        score, _, info = self._score()

        transportista = next(
            item for item in info['desglose']
            if item['criterio'] == 'Transportista'
        )
        self.assertEqual(transportista['puntos'], 15)
        self.assertGreater(score, 15)

    def test_conductor_y_rut_refuerzan_match(self):
        score, _, info = self._score()

        puntos = {
            item['criterio']: item['puntos']
            for item in info['desglose']
        }
        self.assertEqual(puntos['Conductor'], 7)
        self.assertEqual(puntos['RUT conductor'], 5)

    def test_guia_exacta_es_senal_fuerte(self):
        _, _, info = self._score()

        guia = next(item for item in info['desglose'] if item['criterio'] == 'Guia')
        self.assertEqual(guia['puntos'], 20)

    def test_guia_ausente_no_penaliza(self):
        self.camion.CPA_CNUMERO_GUIA = ''
        score, _, info = self._score(guia='')

        self.assertNotIn('Guia', {item['criterio'] for item in info['desglose']})
        self.assertEqual(score, sum(item['puntos'] for item in info['desglose']))

    def test_caso_38736_equivalente_sube_de_55_a_95(self):
        score, _, info = self._score()

        self.assertEqual(score, 95)
        self.assertGreater(score, 55)
        self.assertEqual(
            score,
            sum(item['puntos'] for item in info['desglose']),
        )
        self.assertNotIn('Proveedor', {
            item['criterio'] for item in info['desglose']
        })

    def test_orden_estable_usa_score_horario_fecha_e_id(self):
        base = {
            'es_citacion_aprobada': False,
            'fecha_planificacion_orden': '2026-10-01T15:00:00',
        }
        candidatos = [
            {**base, 'id': 3, 'score': 80, 'diferencia_horas': 2},
            {**base, 'id': 2, 'score': 95, 'diferencia_horas': 4},
            {**base, 'id': 1, 'score': 95, 'diferencia_horas': 1},
        ]

        candidatos.sort(key=views._clave_orden_sugerencia_patio)

        self.assertEqual([item['id'] for item in candidatos], [1, 2, 3])

    def test_terminal_y_archivada_no_estan_disponibles(self):
        base = {
            'CI_BHABILITADO': True,
            'CI_BARCHIVADO': False,
            'CI_CESTADO': 'SALIDA_CONFIRMADA',
            'CI_FFECHATERMINO': None,
        }
        self.assertFalse(
            views.citacion_disponible_para_asociar_camion_patio(
                SimpleNamespace(**base)
            )
        )
        base['CI_CESTADO'] = 'PENDIENTE'
        base['CI_BARCHIVADO'] = True
        self.assertFalse(
            views.citacion_disponible_para_asociar_camion_patio(
                SimpleNamespace(**base)
            )
        )

    def test_ui_expone_datos_desglose_y_asociacion_manual(self):
        template = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        ).read_text(encoding='utf-8')

        for texto in (
            'Patente',
            'Producto',
            'Transportista',
            'Conductor',
            'Proveedor',
            'Guia',
            'Contenedor / CRT',
            'Pedido SAP',
            'Planificacion',
            'Secuencia operacional',
            'item.puntos',
        ):
            self.assertIn(texto, template)
        self.assertIn(
            'patioPrepararFiltrosCitaciones(!!citaciones.length, camion.tipo_operacion_sugerida)',
            template,
        )
        self.assertIn('patioCitacionSeleccionada = null;', template)
        self.assertIn(
            "$('#btnAsociarCamionPatio').on('click'",
            template,
        )


    def test_asociacion_continua_siendo_manual(self):
        template = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        ).read_text(encoding='utf-8')

        self.assertIn('patioCitacionSeleccionada = null;', template)
        self.assertIn(
            "$('#btnAsociarCamionPatio').on('click'",
            template,
        )
        self.assertIn('if (!result.isConfirmed) return;', template)
        self.assertIn('citacion_id: patioCitacionSeleccionada', template)

class FiltrosSugerenciasPatioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        usuario = get_user_model().objects.create_user('matching-patio')
        cls.empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='TERRAMAR TEST',
            EP_CRUT='1-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='OTRA EMPRESA',
            EP_CRUT='2-7',
            EP_CBASEDATOS='TEST2',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        calendario = CALENDARIO.objects.create(
            US_NID=usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Patio',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=10,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=5,
        )
        calendario_otro = CALENDARIO.objects.create(
            US_NID=usuario,
            EP_NID=cls.otra_empresa,
            CA_CNOMBRE='Otro',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=10,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=5,
        )
        cls.plan = PLANIFICACION.objects.create(
            US_NID=usuario,
            EP_NID=cls.empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO=views.CIT_RECEPCION,
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=5,
        )
        plan_otro = PLANIFICACION.objects.create(
            US_NID=usuario,
            EP_NID=cls.otra_empresa,
            CAL_NID=calendario_otro,
            PL_CTIPOCUPO=views.CIT_RECEPCION,
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=5,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=usuario,
            EP_NID=cls.empresa,
            SE_CTIPO=views.CIT_RECEPCION,
            SE_CCODIGO='RECEPCION_TERRAMAR',
            SE_CNOMBRE='Recepcion Terramar',
            SE_BHABILITADO=True,
        )
        secuencia_otra = SECUENCIA.objects.create(
            US_NID=usuario,
            EP_NID=cls.otra_empresa,
            SE_CTIPO=views.CIT_RECEPCION,
            SE_CCODIGO='RECEPCION_TERRAMAR',
            SE_CNOMBRE='Recepcion otra',
            SE_BHABILITADO=True,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.plan,
            SC_NID=cls.secuencia,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=views.CIT_RECEPCION,
            CI_CESTADO='PENDIENTE',
        )
        cls.citacion_otra = CITACION.objects.create(
            US_NID=usuario,
            EP_NID=cls.otra_empresa,
            PL_NID=plan_otro,
            SC_NID=secuencia_otra,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=views.CIT_RECEPCION,
            CI_CESTADO='PENDIENTE',
        )
        cls.camion = CAMION_PATIO.objects.create(
            EP_NID=cls.empresa,
            CPA_CPATENTE='RSZK21',
            CPA_CNOMBRE_CONDUCTOR='CRISTIAN GARCIA',
            CPA_CRUT_CONDUCTOR='11684951-8',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES SAEZ LIMITADA',
            CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=usuario,
        )
        cls.usuario = usuario

    def _listar_con_serializacion(self):
        def serializar(_camion, citacion, citacion_aprobada_id=None):
            return {
                'id': citacion.id,
                'es_citacion_aprobada': False,
                'score': citacion.id % 100,
                'diferencia_horas': 0,
                'fecha_planificacion_orden': (
                    citacion.CI_FFECHACITACION.isoformat()
                ),
            }

        with (
            patch.object(
                views,
                '_solicitud_no_planificado_visible',
                return_value=None,
            ),
            patch.object(
                views,
                '_es_camion_despacho_sbh_patio',
                return_value=False,
            ),
            patch.object(
                views,
                'citacion_disponible_para_asociar_camion_patio',
                return_value=True,
            ),
            patch.object(
                views,
                '_serializar_citacion_patio',
                side_effect=serializar,
            ),
        ):
            return views._citaciones_disponibles_para_patio(self.camion)

    def test_empresa_distinta_queda_excluida(self):
        ids = {item['id'] for item in self._listar_con_serializacion()}

        self.assertIn(self.citacion.id, ids)
        self.assertNotIn(self.citacion_otra.id, ids)

    def test_citacion_asociada_a_otro_camion_activo_queda_excluida(self):
        CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            CPA_CPATENTE='OTRA11',
            CPA_CNOMBRE_CONDUCTOR='Otro',
            CPA_CRUT_CONDUCTOR='12345678-5',
            CPA_CTRANSPORTISTA_DECLARADO='Otro',
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.usuario,
        )

        ids = {item['id'] for item in self._listar_con_serializacion()}

        self.assertNotIn(self.citacion.id, ids)