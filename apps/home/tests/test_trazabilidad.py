from datetime import time
import json

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO,
    CITACION,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    SECUENCIA,
    USERS_EMPRESA,
)
from apps.home.services.trazabilidad_service import (
    buscar_citaciones,
    construir_resultados_trazabilidad,
    obtener_numero_guia,
    queryset_citaciones_trazabilidad,
)


class TrazabilidadTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('trace_user', password='test-pass')
        cls.empresa = cls.crear_empresa('Empresa Uno', '1-9')
        cls.otra_empresa = cls.crear_empresa('Empresa Dos', '2-7')
        USERS_EMPRESA.objects.create(US_NID=cls.user, EP_NID=cls.empresa)
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Calendario trazabilidad',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=1,
            CA_NMES=1,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='TRACE_REC',
            SE_CNOMBRE='Recepcion trazabilidad',
            SE_BHABILITADO=True,
            SE_FFECHAREGISTRO=timezone.now(),
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.user,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=timezone.now(),
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=4,
        )
        cls.citacion = cls.crear_citacion(cls.empresa, cls.planificacion, cls.secuencia, ' GUIA-TXT-01 ')
        cls.citacion_misma_guia = cls.crear_citacion(cls.empresa, cls.planificacion, cls.secuencia, 'GUIA-COMUN')
        cls.citacion_misma_guia_2 = cls.crear_citacion(cls.empresa, cls.planificacion, cls.secuencia, 'GUIA-COMUN')

        calendario_otra = CALENDARIO.objects.create(
            US_NID=cls.user, EP_NID=cls.otra_empresa, CA_NDIA=1, CA_NMES=1, CA_NANO=2026,
            CA_NCANTIDADCUPOS=2,
        )
        secuencia_otra = SECUENCIA.objects.create(
            US_NID=cls.user, EP_NID=cls.otra_empresa, SE_CTIPO='RECEPCION', SE_CCODIGO='OTRA',
            SE_CNOMBRE='Otra empresa', SE_BHABILITADO=True,
        )
        planificacion_otra = PLANIFICACION.objects.create(
            US_NID=cls.user, EP_NID=cls.otra_empresa, CAL_NID=calendario_otra,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=1,
        )
        cls.citacion_otra = cls.crear_citacion(
            cls.otra_empresa, planificacion_otra, secuencia_otra, 'GUIA-PRIVADA'
        )

    @staticmethod
    def crear_empresa(nombre, rut):
        return EMPRESA.objects.create(
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=rut,
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )

    @classmethod
    def crear_citacion(cls, empresa, planificacion, secuencia, guia):
        return CITACION.objects.create(
            US_NID=cls.user,
            EP_NID=empresa,
            PL_NID=planificacion,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='PENDIENTE',
            CI_CNUMERODOCUMENTO=guia,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_busqueda_prioriza_citacion_exacta(self):
        encontrados, tipo = buscar_citaciones(self.empresa.id, str(self.citacion.id))
        self.assertEqual(tipo, 'citacion')
        self.assertEqual([item.id for item in encontrados], [self.citacion.id])

    def test_busqueda_guia_texto_y_varias_citaciones(self):
        encontrados, tipo = buscar_citaciones(self.empresa.id, '  GUIA-COMUN  ')
        self.assertEqual(tipo, 'guia')
        self.assertEqual({item.id for item in encontrados}, {self.citacion_misma_guia.id, self.citacion_misma_guia_2.id})

    def test_busqueda_no_expone_otra_empresa(self):
        encontrados, _ = buscar_citaciones(self.empresa.id, 'GUIA-PRIVADA')
        self.assertEqual(encontrados, [])

    def test_vista_busqueda_vacia_y_sin_resultado(self):
        vacia = self.client.get(reverse('trazabilidad_buscar'), {'_empresa_id': self.empresa.id, 'q': '   '})
        self.assertEqual(vacia.status_code, 200)
        self.assertContains(vacia, 'Ingrese un numero de guia o citacion')
        sin_resultado = self.client.get(
            reverse('trazabilidad_buscar'), {'_empresa_id': self.empresa.id, 'q': 'NO-EXISTE'}
        )
        self.assertContains(sin_resultado, 'No se encontraron registros')

    def test_usuario_sin_empresa_no_puede_consultar(self):
        otro_usuario = get_user_model().objects.create_user('sin_empresa', password='test-pass')
        self.client.force_login(otro_usuario)
        response = self.client.get(
            reverse('trazabilidad_buscar'), {'_empresa_id': self.empresa.id, 'q': self.citacion.id}
        )
        self.assertEqual(response.status_code, 302)

    def test_trazabilidad_llega_a_ultima_etapa_y_tolera_relaciones_opcionales(self):
        etapa = ETAPA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='PESAJE_ENTRADA',
            ET_CNOMBRE='Pesaje Entrada',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        ETAPA_LOG.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=etapa,
            US_INICIO_ID=self.user,
            US_FIN_ID=self.user,
            EL_FFECHAINICIO=timezone.now(),
            EL_FFECHAFIN=timezone.now(),
        )
        citacion = queryset_citaciones_trazabilidad(self.empresa.id).get(pk=self.citacion.id)
        resultado = construir_resultados_trazabilidad([citacion])[0]
        self.assertEqual(resultado['cabecera']['ultima_etapa'], 'Pesaje Entrada')
        self.assertTrue(resultado['etapas'][-1]['actual'])

    def test_operacion_planta_muestra_guia_y_sin_registrar(self):
        request = RequestFactory().get('/')
        request.user = self.user
        request.session = {}
        contexto = {
            'citacion': self.citacion,
            'pasos': [],
            'patente': 'ABCD12',
            'nombre_flujo': 'Recepcion trazabilidad',
            'numero_guia_operacion': obtener_numero_guia(self.citacion),
        }
        con_guia = render_to_string('home/CITACION/operacion_planta.html', contexto, request=request)
        self.assertIn('GUIA-TXT-01', con_guia)
        contexto['numero_guia_operacion'] = ''
        sin_guia = render_to_string('home/CITACION/operacion_planta.html', contexto, request=request)
        self.assertIn('Sin registrar', sin_guia)

    def test_sidebar_contiene_una_instancia_de_cada_buscador_y_barra_limpia(self):
        request = RequestFactory().get('/')
        request.user = self.user
        request.session = {'empresa_id': self.empresa.id}
        contexto = {'empresa_activa': self.empresa}
        sidebar = render_to_string('includes/sidebar.html', contexto, request=request)
        navegacion = render_to_string('includes/navigation.html', contexto, request=request)

        self.assertEqual(sidebar.count('id="buscar-patente-input"'), 1)
        self.assertEqual(sidebar.count('id="btn-buscar-patente"'), 1)
        self.assertEqual(sidebar.count('id="buscar-guia-citacion-input"'), 1)
        self.assertEqual(sidebar.count('id="btn-buscar-guia-citacion"'), 1)
        self.assertIn('Consultas', sidebar)
        self.assertNotIn('&iquest;Planificaciones?', sidebar)
        self.assertNotIn('Planifica tus citaciones.', sidebar)
        self.assertNotIn('id="buscar-patente-input"', navegacion)
        self.assertNotIn('id="buscar-guia-citacion-input"', navegacion)

    def test_borrador_sap_se_resume_sin_exponer_json_tecnico(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO='BORRADOR_SAP_RECEPCION_ENVIO',
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO='COMPLETADO',
            OPL_COBSERVACION=json.dumps({
                'success': True,
                'company_db': 'BASE_INTERNA',
                'sap_username': 'USUARIO_TECNICO',
                'endpoint': '/Drafts',
                'token': 'TOKEN-SECRETO',
                'payload': {'CardCode': 'P0001', 'DocumentLines': [{'ItemCode': 'ITEM'}]},
                'response': {'DocEntry': 777, 'DocNum': 10961, 'odata.metadata': 'interno'},
            }),
        )

        citacion = queryset_citaciones_trazabilidad(self.empresa.id).get(pk=self.citacion.id)
        resultado = construir_resultados_trazabilidad([citacion])[0]
        evento = next(
            item for item in resultado['etapas'] if item['nombre'] == 'Borrador SAP recepción'
        )

        self.assertEqual(evento['estado'], 'COMPLETADO')
        self.assertEqual(evento['detalle_visible'], '')
        self.assertEqual(evento['datos'], [{'etiqueta': 'Documento SAP', 'valor': '10961'}])
        contenido = repr(resultado)
        for valor_tecnico in (
            'BASE_INTERNA', 'USUARIO_TECNICO', '/Drafts', 'TOKEN-SECRETO',
            'CardCode', 'DocumentLines', 'odata.metadata',
        ):
            self.assertNotIn(valor_tecnico, contenido)

    def test_borrador_sap_fallido_muestra_error_sin_respuesta_tecnica(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO='BORRADOR_SAP_DESPACHO',
            OPL_CPERFIL_RESPONSABLE='ASISTENTE C D',
            OPL_CESTADO='PENDIENTE',
            OPL_COBSERVACION=json.dumps({
                'success': False,
                'sap_error': {'message': 'Respuesta privada', 'password': 'NO-EXPONER'},
                'response': {'status': 500},
            }),
        )

        citacion = queryset_citaciones_trazabilidad(self.empresa.id).get(pk=self.citacion.id)
        resultado = construir_resultados_trazabilidad([citacion])[0]
        evento = next(item for item in resultado['etapas'] if item['nombre'] == 'Borrador SAP despacho')

        self.assertEqual(evento['estado'], 'ERROR')
        self.assertEqual(evento['detalle_visible'], '')
        self.assertNotIn('Respuesta privada', repr(resultado))
        self.assertNotIn('NO-EXPONER', repr(resultado))
