from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views


class DespachoTerramarPatioTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.ahora = timezone.now()
        self.citacion = SimpleNamespace(
            id=38738,
            EP_NID_id=1,
            EP_NID=SimpleNamespace(EP_CRAZONSOCIAL='TERRAMAR CHILE'),
            PL_NID_id=1295,
            PL_NID=SimpleNamespace(),
            SC_NID=SimpleNamespace(SE_CNOMBRE='Despacho Terramar', SE_CCODIGO='DESPACHO_TERRAMAR'),
            CI_FFECHACITACION=self.ahora + timedelta(hours=1),
            CI_CESTADO='Despacho Programado',
            CON_NID=None,
        )

    def test_busqueda_esta_aislada_a_empresa_1_y_despacho_terramar(self):
        with (
            patch.object(views, '_citaciones_por_patente_operacional', return_value=[self.citacion]),
            patch.object(views, 'es_citacion_despacho_terramar', return_value=True),
            patch.object(views, '_estado_citacion_no_vigente', return_value=False),
            patch.object(views, '_salida_confirmada_citacion', return_value=False),
            patch.object(views, '_citacion_tiene_proceso_operacional_iniciado', return_value=False),
            patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True),
        ):
            self.assertEqual(
                views.buscar_despachos_terramar_cercanos_sin_ingreso('GFDSS', views.ID_TERRAMAR),
                [self.citacion],
            )
            self.assertEqual(
                views.buscar_despachos_terramar_cercanos_sin_ingreso('GFDSS', views.ID_ACEITES_SBH),
                [],
            )

    def test_estado_camion_sbh_prioriza_su_planificacion_sin_consultar_terramar(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[SimpleNamespace(id=91)]),
            patch.object(views, '_payload_planificacion_estado_camion', return_value={'citacion_id': 91}),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views.EMPRESA.objects, 'filter', return_value=SimpleNamespace(first=lambda: SimpleNamespace(id=2))),
            patch.object(views.rs, 'pendientes_por_patente') as buscar_servicio,
            patch.object(views, 'buscar_despachos_terramar_cercanos_sin_ingreso') as buscar_terramar,
        ):
            response = views.estado_camion_ajax(request)
        import json
        self.assertEqual(json.loads(response.content)['tipo_resultado'], 'PLANIFICACION_ENCONTRADA')
        buscar_servicio.assert_not_called()
        buscar_terramar.assert_not_called()

    def test_estado_camion_sbh_sin_planificacion_no_invoca_terramar(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GBWG47'})
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[]),
            patch.object(views.rs, 'pendientes_por_patente', return_value=[]),
            patch.object(views, 'buscar_citacion_vigente_sin_ingreso_por_patente', return_value=[]),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views.EMPRESA.objects, 'filter', return_value=SimpleNamespace(first=lambda: SimpleNamespace(id=2))),
            patch.object(views, 'buscar_despachos_terramar_cercanos_sin_ingreso') as buscar_terramar,
        ):
            response = views.estado_camion_ajax(request)
        import json
        self.assertEqual(json.loads(response.content)['tipo_resultado'], 'SIN_CITACION_VIGENTE')
        buscar_terramar.assert_not_called()

    def test_estado_camion_expone_registro_especifico_para_terramar(self):
        request = self.factory.get('/estado-camion/', {'patente': 'GFDSS'})
        request.user = SimpleNamespace(is_superuser=False)
        empresa = SimpleNamespace(first=lambda: self.citacion.EP_NID)
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_TERRAMAR),
            patch.object(views, '_normalizar_patente_busqueda', return_value='GFDSS'),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_despachos_terramar_cercanos_sin_ingreso', return_value=[self.citacion]),
            patch.object(views, '_payload_planificacion_despacho_terramar', return_value={'citacion_id': self.citacion.id}),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(views, 'usuario_es_guardia', return_value=True),
            patch.object(views.rs, 'pendientes_por_patente', return_value=[]),
            patch.object(views, 'buscar_despachos_sbh_cercanos_sin_ingreso', return_value=[]),
            patch.object(views.EMPRESA.objects, 'filter', return_value=empresa),
        ):
            response = views.estado_camion_ajax(request)

        import json
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['tipo_resultado'], 'PLANIFICACION_ENCONTRADA')
        self.assertEqual(payload['data']['candidatos'][0]['citacion_id'], 38738)
        self.assertEqual(
            payload['data']['registro_url'],
            reverse('estado_camion_registrar_ingreso_despacho_terramar'),
        )
        self.assertTrue(payload['data']['puede_registrar_ingreso'])

    def test_ingreso_terramar_rechaza_empresa_distinta_y_usuario_no_guardia(self):
        request = self.factory.post(
            '/estado-camion/registrar-ingreso-despacho-terramar/',
            {'patente': 'GFDSS'},
        )
        request.user = SimpleNamespace(is_superuser=False)
        with patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH):
            response = views.estado_camion_registrar_ingreso_despacho_terramar(request)
        self.assertEqual(response.status_code, 403)

        with patch.object(views, 'Verificar_empresa', return_value=views.ID_TERRAMAR):
            with patch.object(views, 'usuario_es_guardia', return_value=False):
                response = views.estado_camion_registrar_ingreso_despacho_terramar(request)
        self.assertEqual(response.status_code, 403)

    def test_ingreso_terramar_registra_patente_y_trazabilidad_sin_asociar(self):
        request = self.factory.post(
            '/estado-camion/registrar-ingreso-despacho-terramar/',
            {'patente': 'GFDSS', 'citacion_id': str(self.citacion.id)},
        )
        request.user = SimpleNamespace(is_superuser=False)
        camion = SimpleNamespace(
            id=901,
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
        )
        traza = {}
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_TERRAMAR),
            patch.object(views, 'usuario_es_guardia', return_value=True),
            patch.object(views, '_normalizar_patente_busqueda', return_value='GFDSS'),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=None),
            patch.object(views, 'buscar_despachos_terramar_cercanos_sin_ingreso', return_value=[self.citacion]),
            patch.object(views, '_payload_planificacion_despacho_terramar', return_value={
                'patente': 'GFDSS',
                'conductor': 'GUILLERMO VARGAZ',
                'rut_conductor': '',
                'telefono': '',
                'codigo_pais': '+56',
                'empresa_transporte': 'TRANSPORTES SAEZ LIMITADA',
                'transporte_a_cargo': 'Terramar',
                'cliente': 'Ewos',
                'producto': 'HARINA DE PLUMA SS',
                'salida_documento': 'FE',
            }),
            patch.object(views.EMPRESA.objects, 'get', return_value=self.citacion.EP_NID),
            patch.object(views.CAMION_PATIO.objects, 'create', return_value=camion) as crear_camion,
            patch.object(views.CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects, 'create', side_effect=lambda **kwargs: traza.update(kwargs)),
            patch.object(views, 'registrar_log_camion_no_planificado'),
        ):
            response = views.estado_camion_registrar_ingreso_despacho_terramar(request)

        import json
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertIsNone(crear_camion.call_args.kwargs['CI_NID'])
        self.assertEqual(traza['CI_NID'], self.citacion)
        self.assertEqual(traza['CPTR_CPATENTE_LLEGADA'], 'GFDSS')

    def test_ingreso_terramar_es_idempotente_si_la_patente_ya_esta_activa(self):
        request = self.factory.post(
            '/estado-camion/registrar-ingreso-despacho-terramar/',
            {'patente': 'GFDSS'},
        )
        request.user = SimpleNamespace(is_superuser=False)
        activo = SimpleNamespace(id=902)
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_TERRAMAR),
            patch.object(views, 'usuario_es_guardia', return_value=True),
            patch.object(views, '_normalizar_patente_busqueda', return_value='GFDSS'),
            patch.object(views, '_camion_patio_activo_por_patente', return_value=activo),
        ):
            response = views.estado_camion_registrar_ingreso_despacho_terramar(request)
        self.assertEqual(response.status_code, 409)
        self.assertIn('ingreso activo', response.content.decode('utf-8'))

    def test_ingreso_terramar_no_asocia_citacion_automaticamente_en_la_creacion(self):
        source = Path(views.__file__).read_text(encoding='utf-8')
        start = source.index('def estado_camion_registrar_ingreso_despacho_terramar')
        end = source.index('RESULTADO_RECEPCION_SERVICIO_PROSESA', start)
        body = source[start:end]
        self.assertIn('EP_NID=empresa, CI_NID=None', body)
        self.assertIn('CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create', body)
        self.assertIn("CPTR_CRESULTADO_BUSQUEDA='GUARDIA_MATCH'", body)

    def test_asociacion_terramar_valida_tipo_despacho(self):
        source = Path(views.__file__).read_text(encoding='utf-8')
        start = source.index('def CAMION_PATIO_ASOCIAR')
        end = source.index('def _usuario_puede_consultar_transporte_despacho_sbh', start)
        body = source[start:end]
        self.assertIn('Empresa == ID_TERRAMAR', body)
        self.assertIn('es_citacion_despacho_terramar_principal(citacion)', body)
        self.assertIn('solo puede asociar citaciones de Despacho Terramar', body)

    def test_score_terramar_prioriza_patente_y_expone_desglose(self):
        camion = SimpleNamespace(
            CPA_CPATENTE='GFDSS',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES SAEZ LIMITADA',
            CPA_CINSUMO_DECLARADO_GUIA='HARINA DE PLUMA SS',
            CPA_CNOMBRE_CONDUCTOR='GUILLERMO VARGAZ',
            CPA_CRUT_CONDUCTOR='11684958-8',
            CPA_CCLIENTE_DECLARADO='EWOS',
            CPA_FFECHALLEGADA=self.ahora,
            CON_NID=SimpleNamespace(id=8610),
        )
        payload = {
            'patente': 'GFDSS',
            'empresa_transporte_nombre': 'TRANSPORTES SAEZ LIMITADA',
            'insumo': 'HARINA DE PLUMA SS',
            'conductor_nombre': 'GUILLERMO VARGAZ',
            'conductor_rut': '11684958-8',
            'conductor_id': 8610,
            'cliente': 'EWOS',
        }
        with (
            patch.object(views, 'es_citacion_despacho_terramar', return_value=True),
            patch.object(views, '_payload_citacion_terramar_patio', return_value=payload),
            patch.object(views, '_diferencia_horaria_patio', return_value=2),
        ):
            score, razones, info = views._score_citacion_camion_patio(camion, self.citacion)

        self.assertEqual(score, 197)
        self.assertEqual(info['desglose'][0]['criterio'], 'Patente')
        self.assertEqual(info['desglose'][0]['puntos'], 100)
        self.assertIn('Patente coincide: GFDSS', razones)
        self.assertEqual(
            {item['criterio'] for item in info['desglose']},
            {'Patente', 'Transportista', 'Producto', 'Conductor', 'RUT conductor', 'Cliente', 'Horario'},
        )

    def test_sugerencias_terramar_restringen_secuencia_de_despacho(self):
        source = Path(views.__file__).read_text(encoding='utf-8')
        start = source.index('def _citaciones_disponibles_para_patio')
        end = source.index('def _formatear_fecha_documental_camion_patio', start)
        body = source[start:end]
        self.assertIn("getattr(camion, 'EP_NID_id', None) == ID_TERRAMAR", body)
        self.assertIn('CI_CTIPO=CIT_DESPACHO', body)
        self.assertIn("DESPACHO_TERRAMAR", body)
        self.assertNotIn("DESPACHO_TERRAMAR_BODEGA_EXTERNA", body)

    def test_ui_habilita_asociacion_solo_para_asistente_terramar(self):
        template = (
            Path(__file__).resolve().parents[2]
            / 'templates/home/CAMION_PATIO/patio_modal_js.html'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'permisos.asociacion_directa_asistente_despacho && Number(PATIO_EMPRESA_ID) !== 1',
            template,
        )
