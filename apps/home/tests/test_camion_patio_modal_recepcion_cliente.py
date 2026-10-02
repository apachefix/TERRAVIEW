import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    EMPRESA,
    PLANIFICACION,
    SECUENCIA,
    SYSLOGGER,
)


class CamionPatioModalRecepcionClienteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            'asistente_despacho_modal', password='test'
        )
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.otra_empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR',
            EP_CRUT='88-8',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Recepcion SBH',
            CA_NDIA=24,
            CA_NMES=9,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.plan_recepcion = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO=views.CIT_RECEPCION,
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.plan_despacho = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO=views.CIT_DESPACHO,
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia_recepcion = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO=views.CIT_RECEPCION,
            SE_CCODIGO='RECEPCION_BODEGA_EXTERNA_TEST',
            SE_CNOMBRE='Recepcion PROSESA',
            SE_BHABILITADO=True,
        )
        cls.secuencia_despacho = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO=views.CIT_DESPACHO,
            SE_CCODIGO='DESPACHO_TEST',
            SE_CNOMBRE='Despacho',
            SE_BHABILITADO=True,
        )
        cls.citacion_recepcion = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.plan_recepcion,
            SC_NID=cls.secuencia_recepcion,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=views.CIT_RECEPCION,
            CI_CESTADO='PENDIENTE',
        )
        cls.citacion_despacho = CITACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            PL_NID=cls.plan_despacho,
            SC_NID=cls.secuencia_despacho,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO=views.CIT_DESPACHO,
            CI_CESTADO='PENDIENTE',
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=cls.citacion_recepcion,
            EP_NID=cls.empresa,
            US_NID=cls.usuario,
            CDO_CALMACEN_DESTINO='PROSESA',
            CDO_CESTANQUE_DESTINO='PROSE_G2',
        )

        cls.camion_terramar = cls._crear_camion(
            cls.empresa,
            'TMTEST1',
            transporte='TERRAMAR',
            transportista='TRANSPORTISTA TERRAMAR',
        )
        cls.camion_cliente = cls._crear_camion(
            cls.empresa,
            'CLTEST1',
            transporte='CLIENTE',
            transportista='TRANSPORTES PRUEBA LTDA',
            conductor='Conductor manual',
        )
        cls.camion_asociado = cls._crear_camion(
            cls.empresa,
            'ASOCT1',
            transporte='CLIENTE',
            transportista='CLIENTE',
            estado=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            citacion=cls.citacion_despacho,
        )
        cls.camion_otra_empresa = cls._crear_camion(
            cls.otra_empresa,
            'OTRAT1',
            transporte='CLIENTE',
            transportista='CLIENTE',
        )
        cls.camion_despacho_con_traza = cls._crear_camion(
            cls.empresa,
            'DSPTR1',
            transporte='TERRAMAR',
            transportista='TRANSPORTISTA DESPACHO',
        )
        CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
            CPA_NID=cls.camion_despacho_con_traza,
            CI_NID=cls.citacion_despacho,
            PL_NID=cls.plan_despacho,
            EP_NID=cls.empresa,
            CPTR_CPATENTE_CONSULTADA='DSPTR1',
            CPTR_CRESULTADO_BUSQUEDA='GUARDIA_MATCH',
            CPTR_BCARGADO_DESDE_PLANIFICACION=True,
            CPTR_CPATENTE_PLANIFICADA='DSPTR1',
            CPTR_CPATENTE_LLEGADA='DSPTR1',
            US_NID=cls.usuario,
            CPTR_FFECHACONSULTA=timezone.now(),
        )

    @classmethod
    def _crear_camion(
        cls,
        empresa,
        patente,
        *,
        transporte,
        transportista,
        conductor='Conductor',
        estado=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
        citacion=None,
    ):
        return CAMION_PATIO.objects.create(
            EP_NID=empresa,
            CI_NID=citacion,
            CON_NID=None,
            transporte_a_cargo=transporte,
            CPA_CPATENTE=patente,
            CPA_CNOMBRE_CONDUCTOR=conductor,
            CPA_CRUT_CONDUCTOR='12345678-5',
            CPA_CTRANSPORTISTA_DECLARADO=transportista,
            CPA_CTIPO_RECEPCION='NACIONAL' if empresa.id == 2 else '',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CNUMERO_GUIA='GUIA-TEST',
            CPA_CESTADO=estado,
            US_GUARDIA_ID=cls.usuario,
        )

    def _request_modal(
        self, citacion, *, asistente_despacho=True, return_payload=False
    ):
        request = RequestFactory().get(
            f'/camiones-patio/pendientes-citacion/{citacion.id}/',
            {'_empresa_id': str(self.empresa.id)},
        )
        request.user = self.usuario
        request.session = {}
        resumen = {
            'id': citacion.id,
            'producto': '',
            'proveedor': '',
            'cliente': '',
            'cliente_nombre': '',
            'cliente_codigo': '',
            'pedido_sap': '',
            'contrato_sap': '',
            'almacen_destino': (
                'PROSESA' if citacion.CI_CTIPO == views.CIT_RECEPCION else ''
            ),
            'estanque_destino': (
                'PROSE_G2' if citacion.CI_CTIPO == views.CIT_RECEPCION else ''
            ),
            'es_despacho_sbh': citacion.CI_CTIPO == views.CIT_DESPACHO,
            'salida_documento': '',
            'salida_documento_label': '',
            'destino': '',
            'ventana_horaria': '',
        }

        with (
            patch.object(views, 'Verificar_empresa', return_value=self.empresa.id),
            patch.object(
                views,
                'usuario_puede_revisar_camion_patio',
                return_value=not asistente_despacho,
            ),
            patch.object(
                views,
                'usuario_es_asistente_despacho_empresa',
                return_value=asistente_despacho,
            ),
            patch.object(
                views,
                'citacion_disponible_para_asociar_camion_patio',
                return_value=True,
            ),
            patch.object(views, '_serializar_citacion_patio', return_value=resumen),
            patch.object(
                views,
                '_serializar_camion_patio',
                side_effect=lambda camion: {
                    'id': camion.id,
                    'patente': camion.CPA_CPATENTE,
                    'transporte_a_cargo': camion.transporte_a_cargo,
                },
            ),
        ):
            response = views.CAMIONES_PATIO_PENDIENTES_CITACION(
                request, citacion.id
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        return payload if return_payload else payload['camiones']

    def test_asistente_despacho_recepcion_no_aplica_filtro_de_trazabilidad(self):
        ids = {item['id'] for item in self._request_modal(self.citacion_recepcion)}
        self.assertIn(self.camion_cliente.id, ids)
        self.assertIn(self.camion_terramar.id, ids)

    def test_asistente_despacho_despacho_mantiene_filtro_de_trazabilidad(self):
        ids = {item['id'] for item in self._request_modal(self.citacion_despacho)}
        self.assertEqual(ids, {self.camion_despacho_con_traza.id})

    def test_asistente_recepcion_recepcion_mantiene_comportamiento(self):
        ids = {
            item['id']
            for item in self._request_modal(
                self.citacion_recepcion, asistente_despacho=False
            )
        }
        self.assertIn(self.camion_cliente.id, ids)
        self.assertIn(self.camion_terramar.id, ids)

    def test_cliente_sin_trazabilidad_aparece_en_recepcion(self):
        self.assertFalse(
            CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.filter(
                CPA_NID=self.camion_cliente
            ).exists()
        )
        ids = {item['id'] for item in self._request_modal(self.citacion_recepcion)}
        self.assertIn(self.camion_cliente.id, ids)

    def test_terramar_sin_trazabilidad_aparece_en_recepcion(self):
        self.assertFalse(
            CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.filter(
                CPA_NID=self.camion_terramar
            ).exists()
        )
        ids = {item['id'] for item in self._request_modal(self.citacion_recepcion)}
        self.assertIn(self.camion_terramar.id, ids)

    def test_camion_asociado_no_aparece(self):
        ids = {item['id'] for item in self._request_modal(self.citacion_recepcion)}
        self.assertNotIn(self.camion_asociado.id, ids)

    def test_camion_de_otra_empresa_no_aparece(self):
        ids = {item['id'] for item in self._request_modal(self.citacion_recepcion)}
        self.assertNotIn(self.camion_otra_empresa.id, ids)

    def test_recepcion_expone_y_presenta_destinos_planificados(self):
        citacion = CITACION.objects.select_related(
            'EP_NID', 'PL_NID', 'SC_NID', 'SN_NID', 'PRO_NID',
            'detalle_operacional',
        ).get(pk=self.citacion_recepcion.pk)
        serializada = views._serializar_citacion_patio(
            self.camion_cliente, citacion
        )
        self.assertEqual(serializada['almacen_destino'], 'PROSESA')
        self.assertEqual(serializada['estanque_destino'], 'PROSE_G2')

        respuesta = self._request_modal(
            self.citacion_recepcion, return_payload=True
        )
        self.assertEqual(
            respuesta['citacion_resumen']['almacen_destino'], 'PROSESA'
        )
        self.assertEqual(
            respuesta['citacion_resumen']['estanque_destino'], 'PROSE_G2'
        )

        template = (
            Path(__file__).resolve().parents[3]
            / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Almac\\u00e9n destino', template)
        self.assertIn('Estanque destino', template)
        self.assertIn('cit.almacen_destino', template)
        self.assertIn('cit.estanque_destino', template)
        self.assertIn('Sin informaci\\u00f3n', template)

    def test_asociacion_cliente_persiste_citacion_estado_y_cargo(self):
        SYSLOGGER.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            LOG_COPERACION='ING_CAMION',
            LOG_CADD1=str(self.citacion_recepcion.id),
        )
        SYSLOGGER.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            LOG_COPERACION='AVANZA_AR',
            LOG_CADD1=str(self.citacion_recepcion.id),
        )
        with (
            patch.object(
                views,
                'citacion_disponible_para_asociar_camion_patio',
                return_value=True,
            ),
            patch.object(
                views,
                '_copiar_datos_camion_patio_a_citacion',
                return_value=[object()],
            ),
            patch.object(
                views,
                '_copiar_adjuntos_camion_patio_a_citacion',
                return_value=[],
            ),
            patch.object(
                views,
                '_preparar_citacion_patio_para_revision_ar',
                return_value=None,
            ),
        ):
            views._asociar_camion_patio_a_citacion(
                camion=self.camion_cliente,
                citacion=self.citacion_recepcion,
                usuario=self.usuario,
                empresa=self.empresa,
                origen='ASOCIACION_MANUAL',
            )

        self.camion_cliente.refresh_from_db()
        self.assertEqual(
            self.camion_cliente.CI_NID_id, self.citacion_recepcion.id
        )
        self.assertEqual(
            self.camion_cliente.CPA_CESTADO,
            CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        )
        self.assertEqual(self.camion_cliente.US_ASOCIA_ID_id, self.usuario.id)
        self.assertEqual(self.camion_cliente.transporte_a_cargo, 'CLIENTE')
        self.assertEqual(
            self.camion_cliente.CPA_CTRANSPORTISTA_DECLARADO,
            'TRANSPORTES PRUEBA LTDA',
        )

    def test_asociacion_copia_empresa_real_al_snapshot_operacional(self):
        with patch.object(
            views,
            'guardar_dato_operacion_codigo',
            return_value=object(),
        ) as guardar:
            views._copiar_datos_camion_patio_a_citacion(
                self.camion_cliente,
                self.citacion_recepcion,
                self.usuario,
            )

        valores = {
            llamada.args[1]: llamada.args[2]
            for llamada in guardar.call_args_list
        }
        self.assertEqual(
            valores['ING_EMPRESA_TRANSPORTE'],
            'TRANSPORTES PRUEBA LTDA',
        )
        self.assertNotEqual(valores['ING_EMPRESA_TRANSPORTE'], 'CLIENTE')
