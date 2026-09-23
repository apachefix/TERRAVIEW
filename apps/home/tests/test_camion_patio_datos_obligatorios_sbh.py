import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class DatosObligatoriosDespachoSbhTests(SimpleTestCase):
    def setUp(self):
        self.transportista = SimpleNamespace(
            id=31,
            EP_NID_id=views.ID_ACEITES_SBH,
            SN_BHABILITADO=True,
            SN_CTIPO='S',
            SN_CRAZONSOCIAL='TRANSPORTES PRUEBA LTDA',
            SN_CRUT='76.123.456-7',
        )
        self.conductor = SimpleNamespace(
            id=41,
            CON_CNOMBRE='JUAN',
            CON_CAPELLIDO='PEREZ',
            CON_CRUT='12.345.678-5',
            CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_CTELEFONO='912345678',
            SN_NID=self.transportista,
        )
        self.camion = SimpleNamespace(
            EP_NID_id=views.ID_ACEITES_SBH,
            CPA_CNOMBRE_CONDUCTOR='JUAN PEREZ',
            CPA_CRUT_CONDUCTOR='12.345.678-5',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTELEFONO_CONDUCTOR='912345678',
            CPA_CTRANSPORTISTA_DECLARADO='TRANSPORTES PRUEBA LTDA',
            transporte_a_cargo='CLIENTE',
        )

    def validar(self, camion=None, candidatos=None):
        consulta = MagicMock()
        consulta.filter.return_value.order_by.return_value.__getitem__.return_value = (
            [self.conductor] if candidatos is None else candidatos
        )
        transportistas = MagicMock()
        transportistas.filter.return_value.order_by.return_value.__iter__.return_value = iter(
            [self.transportista]
        )
        with (
            patch.object(views.CONDUCTOR.objects, 'select_related', return_value=consulta),
            patch.object(views.SOCIONEGOCIO.objects, 'filter', transportistas.filter),
        ):
            return views._validar_datos_asociacion_camion_despacho_sbh(
                camion or self.camion, aplicar=True,
            )

    def test_a_sin_conductor_bloquea(self):
        self.camion.CPA_CNOMBRE_CONDUCTOR = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('conductor', resultado['campos'])

    def test_b_sin_rut_conductor_bloquea(self):
        self.camion.CPA_CRUT_CONDUCTOR = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('rut_conductor', resultado['campos'])

    def test_c_sin_codigo_pais_bloquea(self):
        self.camion.CPA_CCODIGO_PAIS_TELEFONO = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('telefono_codigo_pais', resultado['campos'])

    def test_d_sin_telefono_bloquea(self):
        self.camion.CPA_CTELEFONO_CONDUCTOR = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('telefono_conductor', resultado['campos'])

    def test_e_sin_transportista_bloquea(self):
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('transportista', resultado['campos'])

    def test_f_transportista_sin_rut_bloquea(self):
        self.transportista.SN_CRUT = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('El transportista debe tener RUT registrado.', resultado['errores'])

    def test_g_transportista_de_otra_empresa_bloquea(self):
        self.transportista.EP_NID_id = views.ID_TERRAMAR
        resultado = self.validar()
        self.assertFalse(resultado['valido'])
        self.assertIn('transportista', resultado['campos'])

    def test_h_datos_completos_permiten_asociar(self):
        resultado = self.validar()
        self.assertTrue(resultado['valido'])
        self.assertIs(resultado['conductor'], self.conductor)
        self.assertIs(resultado['transportista'], self.transportista)

    def test_h_transportista_snapshot_no_se_sustituye_por_sn_conductor(self):
        self.conductor.SN_NID = SimpleNamespace(
            SN_CRAZONSOCIAL='TERRESTRE',
        )
        resultado = self.validar()
        self.assertTrue(resultado['valido'])
        self.assertIs(resultado['transportista'], self.transportista)

    def test_i_cliente_no_exige_ruta_ni_proforma(self):
        self.camion.transporte_a_cargo = 'CLIENTE'
        resultado = self.validar()
        self.assertTrue(resultado['valido'])

    def test_j_cliente_exige_conductor_y_transportista(self):
        self.camion.transporte_a_cargo = 'CLIENTE'
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = ''
        resultado = self.validar()
        self.assertFalse(resultado['valido'])

    def test_k_terramar_conserva_validacion_adicional_de_datos(self):
        self.camion.transporte_a_cargo = 'TERRAMAR'
        resultado = self.validar()
        self.assertTrue(resultado['valido'])
        self.camion.CPA_CTELEFONO_CONDUCTOR = ''
        self.assertFalse(self.validar()['valido'])

    def test_codigo_y_telefono_snapshot_validos_aunque_maestro_no_los_tenga(self):
        self.conductor.CON_CCODIGO_PAIS_TELEFONO = None
        self.conductor.CON_CTELEFONO = None
        resultado = self.validar()
        self.assertTrue(resultado['valido'])
        self.assertNotIn('telefono_codigo_pais', resultado['campos'])
        self.assertNotIn('telefono_conductor', resultado['campos'])

    def test_precarga_prioriza_los_cinco_snapshots(self):
        with patch.object(
            views, '_resolver_conductor_snapshot_camion_patio'
        ) as resolver:
            datos = views._datos_precarga_camion_patio(self.camion)
        self.assertEqual(datos, {
            'conductor': 'JUAN PEREZ',
            'rut_conductor': '12.345.678-5',
            'telefono_codigo_pais': '+56',
            'telefono_conductor': '912345678',
            'transportista': 'TRANSPORTES PRUEBA LTDA',
        })
        resolver.assert_not_called()

    def test_precarga_usa_maestro_solo_para_snapshots_vacios(self):
        camion = SimpleNamespace(
            CPA_CNOMBRE_CONDUCTOR='',
            CPA_CRUT_CONDUCTOR='12.345.678-5',
            CPA_CCODIGO_PAIS_TELEFONO='',
            CPA_CTELEFONO_CONDUCTOR='',
            CPA_CTRANSPORTISTA_DECLARADO='',
        )
        with patch.object(
            views,
            '_resolver_conductor_snapshot_camion_patio',
            return_value=self.conductor,
        ):
            datos = views._datos_precarga_camion_patio(camion)
        self.assertEqual(datos['conductor'], 'JUAN PEREZ')
        self.assertEqual(datos['rut_conductor'], '12.345.678-5')
        self.assertEqual(datos['telefono_codigo_pais'], '+56')
        self.assertEqual(datos['telefono_conductor'], '912345678')
        self.assertEqual(datos['transportista'], 'TRANSPORTES PRUEBA LTDA')

    def test_m_recepcion_no_aplica_esta_regla(self):
        with (
            patch.object(views, '_es_camion_despacho_sbh_patio', return_value=False),
            patch.object(views.CONDUCTOR.objects, 'select_related') as consulta,
        ):
            resultado = views._validar_datos_asociacion_camion_despacho_sbh(self.camion)
        self.assertFalse(resultado['aplica'])
        self.assertTrue(resultado['valido'])
        consulta.assert_not_called()

    def test_edicion_cliente_conserva_transportista_real(self):
        post = {
            'transporte_a_cargo': 'CLIENTE',
            'transportista': self.camion.CPA_CTRANSPORTISTA_DECLARADO,
            'conductor': self.camion.CPA_CNOMBRE_CONDUCTOR,
            'rut_conductor': self.camion.CPA_CRUT_CONDUCTOR,
            'telefono_codigo_pais': self.camion.CPA_CCODIGO_PAIS_TELEFONO,
            'telefono_conductor': self.camion.CPA_CTELEFONO_CONDUCTOR,
            'patente': 'ABCD12',
        }
        with (
            patch.object(views, '_es_camion_despacho_sbh_patio', return_value=True),
            patch.object(views, '_resolver_conductor_snapshot_camion_patio', return_value=self.conductor),
        ):
            datos = views._normalizar_datos_edicion_camion_patio(post, self.camion)
        self.assertEqual(
            datos['CPA_CTRANSPORTISTA_DECLARADO'],
            'TRANSPORTES PRUEBA LTDA',
        )
        self.assertEqual(datos['CPA_CNOMBRE_CONDUCTOR'], 'JUAN PEREZ')
        self.assertEqual(datos['CPA_CRUT_CONDUCTOR'], '12345678-5')
        self.assertEqual(datos['CPA_CCODIGO_PAIS_TELEFONO'], '+56')
        self.assertEqual(datos['CPA_CTELEFONO_CONDUCTOR'], '912345678')


class EndpointDatosObligatoriosDespachoSbhTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(username='asistente_despacho')
        solicitudes = MagicMock()
        solicitudes.filter.return_value.exists.return_value = False
        self.camion = SimpleNamespace(
            id=117,
            pk=117,
            EP_NID_id=views.ID_ACEITES_SBH,
            CI_NID_id=None,
            CPA_CESTADO=views.CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            solicitudes_no_planificado=solicitudes,
        )
        self.citacion = SimpleNamespace(
            id=38700,
            CI_CTIPO=views.CIT_DESPACHO,
            CON_NID_id=None,
        )

    def test_l_endpoint_directo_bloquea_datos_incompletos(self):
        request = self.factory.post(
            '/camiones-patio/117/asociar/',
            {'_empresa_id': '2', 'citacion_id': '38700'},
        )
        request.user = self.user
        camiones = MagicMock()
        camiones.select_related.return_value.prefetch_related.return_value.get.return_value = self.camion
        citaciones = MagicMock()
        citaciones.select_related.return_value.get.return_value = self.citacion
        duplicados = MagicMock()
        duplicados.exclude.return_value.exists.return_value = False
        validacion = {
            'aplica': True,
            'valido': False,
            'errores': ['Debe ingresar el conductor.'],
            'campos': ['conductor'],
            'conductor': None,
            'transportista': None,
        }
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views.transaction, 'atomic', return_value=nullcontext()),
            patch.object(views.CAMION_PATIO.objects, 'select_for_update', return_value=camiones),
            patch.object(views.CAMION_PATIO.objects, 'filter', return_value=duplicados),
            patch.object(views.CITACION.objects, 'select_for_update', return_value=citaciones),
            patch.object(views, 'usuario_puede_asociar_camion_patio', return_value=True),
            patch.object(views, '_es_camion_despacho_patio', return_value=True),
            patch.object(views, 'usuario_es_asistente_despacho_empresa', return_value=True),
            patch.object(views, 'citacion_disponible_para_asociar_camion_patio', return_value=True),
            patch.object(
                views,
                '_validar_datos_asociacion_camion_despacho_sbh',
                return_value=validacion,
            ),
            patch.object(views, '_asociar_camion_patio_a_citacion') as asociar,
        ):
            response = views.CAMION_PATIO_ASOCIAR(request, self.camion.id)
        contenido = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(contenido['campos'], ['conductor'])
        self.assertIn('conductor', contenido['message'])
        asociar.assert_not_called()

    def test_actualizar_persiste_los_cinco_snapshots(self):
        camion = SimpleNamespace(
            id=117,
            pk=117,
            EP_NID=SimpleNamespace(id=views.ID_ACEITES_SBH),
            EP_NID_id=views.ID_ACEITES_SBH,
            CPA_CPATENTE='KIW236',
            CPA_CNOMBRE_CONDUCTOR='ANTERIOR',
            CPA_CRUT_CONDUCTOR='1-9',
            CPA_CCODIGO_PAIS_TELEFONO='+1',
            CPA_CTELEFONO_CONDUCTOR='1111111',
            CPA_CTRANSPORTISTA_DECLARADO='ANTERIOR',
            save=MagicMock(),
        )
        datos = {
            'CPA_CNOMBRE_CONDUCTOR': 'ORLANDO PEITER',
            'CPA_CRUT_CONDUCTOR': '801915539-21',
            'CPA_CCODIGO_PAIS_TELEFONO': '+56',
            'CPA_CTELEFONO_CONDUCTOR': '9239689118',
            'CPA_CTRANSPORTISTA_DECLARADO': 'TRANSPORTES BRETTI LIMITADA',
        }
        request = self.factory.post(
            '/camiones-patio/117/actualizar/',
            {'_empresa_id': '2'},
        )
        request.user = self.user
        consulta = MagicMock()
        consulta.prefetch_related.return_value.get.return_value = camion
        with (
            patch.object(views, 'Verificar_empresa', return_value=views.ID_ACEITES_SBH),
            patch.object(views.CAMION_PATIO.objects, 'select_related', return_value=consulta),
            patch.object(views, 'usuario_puede_modificar_camion_patio_objeto', return_value=True),
            patch.object(views, '_camion_patio_bloqueado_para_edicion', return_value=False),
            patch.object(views, '_normalizar_datos_edicion_camion_patio', return_value=datos),
            patch.object(views, 'registrar_log_camion_no_planificado'),
            patch.object(
                views,
                '_detalle_camion_patio_response',
                return_value=views.JsonResponse({'success': True}),
            ),
        ):
            response = views.CAMION_PATIO_ACTUALIZAR(request, camion.id)
        self.assertEqual(response.status_code, 200)
        for campo, valor in datos.items():
            self.assertEqual(getattr(camion, campo), valor)
        camion.save.assert_called_once()


class ModalDatosObligatoriosDespachoSbhTests(SimpleTestCase):
    def test_modal_destaca_bloquea_y_mantiene_citacion_visible(self):
        from pathlib import Path

        ruta = Path(__file__).resolve().parents[3] / 'apps/templates/home/CAMION_PATIO/patio_modal_js.html'
        contenido = ruta.read_text(encoding='utf-8')
        self.assertIn('datosBloqueanAsociacion', contenido)
        self.assertIn("addClass('is-invalid')", contenido)
        self.assertIn('patioCitacionesList', contenido)
        self.assertIn("$('#btnEditarCamionPatio').toggle", contenido)
