import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views
from apps.home.conductor_utils import RutChilenoInvalido, normalizar_rut_chileno


class RutChilenoTests(SimpleTestCase):
    def test_acepta_formatos_normalizables_y_calcula_dv(self):
        self.assertEqual(normalizar_rut_chileno('12.345.678-5'), '12345678-5')
        self.assertEqual(normalizar_rut_chileno('123456785'), '12345678-5')
        self.assertEqual(normalizar_rut_chileno('55.555.555-5'), '55555555-5')

    def test_rechaza_dv_incorrecto(self):
        with self.assertRaises(RutChilenoInvalido):
            normalizar_rut_chileno('12345678-4')

    def test_rechaza_rut_corto_sin_dv_y_texto(self):
        for rut in ('5', '12-3', '123-4', '12345678', 'texto arbitrario'):
            with self.subTest(rut=rut), self.assertRaises(RutChilenoInvalido):
                normalizar_rut_chileno(rut)


class EdicionConductorMaestroPatioTests(SimpleTestCase):
    def setUp(self):
        self.conductor = SimpleNamespace(
            id=10523, CON_CNOMBRE='HUMBERTO URRIZA', CON_CAPELLIDO='',
            CON_CRUT='55555555-5', CON_BHABILITADO=True,
        )
        self.camion = SimpleNamespace(
            CON_NID_id=10523, transporte_a_cargo='TERRAMAR',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES BRETTI LIMITADA',
            CPA_CNOMBRE_CONDUCTOR='HUMBERTO URRIZA', CPA_CRUT_CONDUCTOR='55555555-5',
            CPA_CTELEFONO_CONDUCTOR='', CPA_CCODIGO_PAIS_TELEFONO='',
            CPA_CPATENTE='SRXS8D', CPA_CPROVEEDOR_DECLARADO='', CPA_CCLIENTE_DECLARADO='',
            CPA_CNUMERO_GUIA='', CPA_CINSUMO_DECLARADO_GUIA='', CPA_COBSERVACION='',
            CPA_CBL='', CPA_CLOTE_CONTENEDOR='',
        )

    def post(self, **cambios):
        datos = {
            'conductor_id': '10523', 'transporte_a_cargo': 'TERRAMAR',
            'transportista': 'TRANSPORTES BRETTI LIMITADA', 'conductor': 'HUMBERTO URRIZA',
            'rut_conductor': '55555555-5', 'telefono_conductor': '923989118',
            'telefono_codigo_pais': '+56', 'patente': 'SRXS8D',
        }
        datos.update(cambios)
        return datos

    def normalizar(self, post):
        with (
            patch.object(views, '_es_camion_despacho_sbh_patio', return_value=True),
            patch.object(views, '_es_camion_recepcion_sbh_patio', return_value=False),
        ):
            return views._normalizar_datos_edicion_camion_patio(post, self.camion)

    def test_editar_solo_telefono_y_pais_conserva_fk(self):
        with patch.object(
            views, '_resolver_conductor_snapshot_camion_patio', return_value=self.conductor,
        ) as resolver:
            datos = self.normalizar(self.post())
        self.assertIs(datos['CON_NID'], self.conductor)
        self.assertEqual(datos['CPA_CTELEFONO_CONDUCTOR'], '923989118')
        self.assertEqual(datos['CPA_CCODIGO_PAIS_TELEFONO'], '+56')
        resolver.assert_called_once_with(self.camion)

    def test_cambiar_nombre_y_rut_vuelve_a_resolver_maestro(self):
        nuevo = SimpleNamespace(id=77)
        with (
            patch.object(
                views, '_resolver_conductor_snapshot_camion_patio',
                return_value=self.conductor,
            ),
            patch.object(
                views, '_resolver_conductor_maestro_por_identidad', return_value=nuevo,
            ) as resolver,
        ):
            datos = self.normalizar(self.post(
                conductor='ANA PEREZ', rut_conductor='12.345.678-5', conductor_id='77',
            ))
        self.assertIs(datos['CON_NID'], nuevo)
        resolver.assert_called_once_with('ANA PEREZ', '12345678-5', '77')

    def test_backend_rechaza_rut_invalido_sin_confiar_en_js(self):
        with self.assertRaisesMessage(ValueError, 'El RUT del conductor no es válido.'):
            self.normalizar(self.post(rut_conductor='12345678-4'))


class ValidacionAsociacionRutPatioTests(SimpleTestCase):
    def test_rut_invalido_planificado_no_se_colapsa_en_error_conductor(self):
        camion = SimpleNamespace(
            EP_NID_id=views.ID_ACEITES_SBH,
            CPA_CNOMBRE_CONDUCTOR='HUMBERTO URRIZA', CPA_CRUT_CONDUCTOR='12345678-4',
            CPA_CCODIGO_PAIS_TELEFONO='+56', CPA_CTELEFONO_CONDUCTOR='923989118',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES BRETTI LIMITADA',
            trazabilidad_planificacion=SimpleNamespace(CPTR_BCARGADO_DESDE_PLANIFICACION=True),
        )
        transportista = SimpleNamespace(
            EP_NID_id=views.ID_ACEITES_SBH, SN_BHABILITADO=True, SN_CTIPO='S',
            SN_CRAZONSOCIAL='TRANSPORTES BRETTI LIMITADA', SN_CRUT='76123456-7',
        )
        with patch.object(
            views, '_resolver_transportista_snapshot_camion_patio', return_value=transportista,
        ):
            resultado = views._validar_datos_asociacion_camion_despacho_sbh(camion, aplicar=True)
        self.assertFalse(resultado['valido'])
        self.assertIn(
            'El RUT del conductor no es válido. Corrija los datos antes de asociar.',
            resultado['errores'],
        )
        self.assertNotIn('Debe seleccionar un conductor válido del maestro.', resultado['errores'])


class ModalRutPatioTests(SimpleTestCase):
    def test_modal_conserva_id_y_valida_rut_en_frontend(self):
        ruta = Path(__file__).resolve().parents[3] / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        contenido = ruta.read_text(encoding='utf-8')
        self.assertIn('name="conductor_id"', contenido)
        self.assertIn('function patioRutValido', contenido)
        self.assertIn('RUT inválido. Revise número y dígito verificador.', contenido)
        self.assertIn('!patioValidarRutEdicion()', contenido)
        self.assertIn("response.code === 'RUT_CONDUCTOR_INVALIDO'", contenido)
        self.assertIn("title: 'No asociado'", contenido)

class AsociacionRutBackendTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(username='asistente')

    def ejecutar(self, rut):
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        camion = SimpleNamespace(
            id=125, pk=125, EP_NID_id=views.ID_ACEITES_SBH,
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            CPA_CRUT_CONDUCTOR=rut,
            solicitudes_no_planificado=solicitudes,
        )
        request = self.factory.post(
            '/camiones-patio/125/asociar/',
            {'_empresa_id': '2', 'citacion_id': '38711'},
        )
        request.user = self.user
        consulta = MagicMock()
        consulta.select_related.return_value.prefetch_related.return_value.get.return_value = camion
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views.transaction, 'atomic', return_value=nullcontext()),
            patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=consulta),
            patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=True),
            patch.object(views, '_asociar_camion_patio_a_citacion') as asociar,
        ):
            response = views.CAMION_PATIO_ASOCIAR(request, camion.id)
        return response, json.loads(response.content), camion, asociar

    def test_post_directo_bloquea_ruts_invalidos_sin_mutar_estado(self):
        for rut in ('5', '1', '55', '123', '123-4', '12345678', '12345678-4', 'texto'):
            with self.subTest(rut=rut):
                response, contenido, camion, asociar = self.ejecutar(rut)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(contenido['code'], 'RUT_CONDUCTOR_INVALIDO')
                self.assertEqual(
                    contenido['message'],
                    'El RUT del conductor no es válido. Corrija los datos antes de asociar.',
                )
                self.assertIsNone(camion.CI_NID_id)
                self.assertEqual(camion.CPA_CESTADO, views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION)
                asociar.assert_not_called()

    def test_validador_transaccional_acepta_rut_valido(self):
        resultado = views._validar_rut_operacional_camion_patio(
            SimpleNamespace(CPA_CRUT_CONDUCTOR='12.345.678-5')
        )
        self.assertTrue(resultado['valido'])
        self.assertEqual(resultado['rut_normalizado'], '12345678-5')


class PersistenciaRutCorregidoEndpointTests(SimpleTestCase):
    def test_editar_datos_persiste_rut_normalizado_y_fk(self):
        caso = EdicionConductorMaestroPatioTests(methodName='test_editar_solo_telefono_y_pais_conserva_fk')
        caso.setUp()
        camion = caso.camion
        camion.CON_NID = None
        camion.CON_NID_id = None
        camion.id = camion.pk = 125
        camion.EP_NID_id = views.ID_ACEITES_SBH
        camion.EP_NID = SimpleNamespace(id=views.ID_ACEITES_SBH)
        camion.save = MagicMock()
        request = RequestFactory().post(
            '/camiones-patio/125/actualizar/',
            caso.post(rut_conductor='12.345.678-5'),
        )
        request.user = SimpleNamespace(username='asistente')
        consulta = MagicMock()
        consulta.prefetch_related.return_value.get.return_value = camion
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views.CAMION_PATIO.objects, 'select_related', return_value=consulta),
            patch.object(views, 'usuario_puede_modificar_camion_patio_objeto', return_value=True),
            patch.object(views, '_camion_patio_bloqueado_para_edicion', return_value=False),
            patch.object(views, '_es_camion_despacho_sbh_patio', return_value=True),
            patch.object(views, '_es_camion_recepcion_sbh_patio', return_value=False),
            patch.object(views, '_resolver_conductor_snapshot_camion_patio', return_value=caso.conductor),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(
                views, '_detalle_camion_patio_response',
                return_value=views.JsonResponse({'success': True}),
            ),
        ):
            response = views.CAMION_PATIO_ACTUALIZAR(request, camion.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '12345678-5')
        self.assertIs(camion.CON_NID, caso.conductor)
        campos_guardados = camion.save.call_args.kwargs['update_fields']
        self.assertIn('CPA_CRUT_CONDUCTOR', campos_guardados)
        self.assertIn('CON_NID', campos_guardados)
        self.assertIn('CPA_FFECHAACTUALIZACION', campos_guardados)

class PrioridadSnapshotOperacionalTests(SimpleTestCase):
    def test_corregir_rut_conserva_fk_aunque_maestro_tenga_rut_antiguo(self):
        caso = EdicionConductorMaestroPatioTests(methodName='test_editar_solo_telefono_y_pais_conserva_fk')
        caso.setUp()
        caso.conductor.CON_CRUT = '123-4'
        with patch.object(
            views, '_resolver_conductor_snapshot_camion_patio', return_value=caso.conductor,
        ):
            datos = caso.normalizar(caso.post(rut_conductor='12.345.678-5'))
        self.assertEqual(datos['CPA_CRUT_CONDUCTOR'], '12345678-5')
        self.assertIs(datos['CON_NID'], caso.conductor)
        self.assertEqual(caso.conductor.CON_CRUT, '123-4')

    def test_precarga_no_sobrescribe_snapshot_corregido_con_planificacion(self):
        camion = SimpleNamespace(
            CPA_CNOMBRE_CONDUCTOR='HUMBERTO URRIZA',
            CPA_CRUT_CONDUCTOR='12345678-5',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='923989118',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES BRETTI LIMITADA',
        )
        with patch.object(views, '_resolver_conductor_snapshot_camion_patio') as resolver:
            datos = views._datos_precarga_camion_patio(camion)
        self.assertEqual(datos['rut_conductor'], '12345678-5')
        resolver.assert_not_called()
