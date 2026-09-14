from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CAMION_PATIO,
    ETAPA_LOG,
    NOTIFICACION,
    OPERACION_PLANTA_LOG,
    SYSLOGGER,
)
from apps.home.tests import test_avance_terramar_lock as etapa1
from apps.home.views import (
    CAMIONES_PATIO_LIST,
    CAMIONES_PATIO_MAPA,
    SEGUIMIENTO_OPERACIONAL,
    _camiones_patio_en_control_queryset,
    asegurar_notificaciones_guardia_porteria_pendientes,
    obtener_pasos_operacion_citacion,
)


class FlujoIngresoTerramarGuardiasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        etapa1.AvanceTerramarPostFunctionalTests.setUpTestData.__func__(cls)
        cls.camion_patio = CAMION_PATIO.objects.create(
            EP_NID=cls.empresa,
            CI_NID=cls.citacion,
            CPA_CPATENTE='ABCD12',
            CPA_CNOMBRE_CONDUCTOR='Conductor Terramar',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CNUMERO_GUIA='GD-100',
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=cls.guardia,
            US_ASOCIA_ID=cls.usuario,
            CPA_FFECHAASOCIACION=timezone.now(),
        )

    def preparar_guardia_porteria(self):
        ETAPA_LOG.objects.filter(CI_NID=self.citacion).update(
            ET_NID=self.etapa_guardia_porteria,
            EL_FFECHAFIN=None,
        )
        SYSLOGGER.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA',
            LOG_CADD1=str(self.citacion.id),
        )
        return NOTIFICACION.objects.create(
            USER_SENDER_ID=self.guardia,
            USER_RECEIVER_ID=self.guardia_porteria,
            EP_NID=self.empresa,
            NOT_CCONTENIDO=(
                f'El camión patente ABCD12 debe ingresar a planta. '
                f'Autorizar ingreso físico. Citación: {self.citacion.id}.'
            ),
            NOT_CURL=f'/pla_listone/{self.planificacion.id}?citacion={self.citacion.id}',
        )

    def autorizar_ingreso(self):
        self.client.force_login(self.guardia_porteria)
        endpoint = reverse('pla_citacion_enviar_guardia_porteria', args=[self.citacion.id])
        with patch('apps.home.views.usuario_es_guardia', return_value=True), \
             patch('apps.home.views.usuario_es_guardia_porteria', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.obtener_valores_ingreso_camion', return_value={'patente': 'ABCD12'}):
            return self.client.post(f'{endpoint}?_empresa_id=999')

    def test_autorizacion_saca_logicamente_del_patio_y_habilita_seguimiento(self):
        notificacion = self.preparar_guardia_porteria()

        response = self.autorizar_ingreso()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(SYSLOGGER.objects.filter(
            EP_NID=self.empresa,
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.citacion.id),
        ).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            OPL_CPASO='Habilitar Operacion Planta',
            OPL_CPERFIL_RESPONSABLE='GUARDIA PORTERIA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).count(), 1)
        self.assertFalse(ETAPA_LOG.objects.filter(CI_NID=self.citacion, EL_FFECHAFIN=None).exists())
        notificacion.refresh_from_db()
        self.assertTrue(notificacion.NOT_BREAD)

        self.assertTrue(CAMION_PATIO.objects.filter(pk=self.camion_patio.id).exists())
        self.assertFalse(_camiones_patio_en_control_queryset(self.empresa.id).filter(pk=self.camion_patio.id).exists())

        request_factory = RequestFactory()
        for vista, ruta in (
            (CAMIONES_PATIO_LIST, '/camiones-patio/'),
            (CAMIONES_PATIO_MAPA, '/camiones-patio/mapa/'),
        ):
            request = request_factory.get(ruta)
            request.user = self.usuario
            with patch('apps.home.views.usuario_puede_revisar_camion_patio', return_value=True), \
                 patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
                 patch('apps.home.views.render') as render_mock:
                vista(request)
            contexto = render_mock.call_args.args[2]
            self.assertFalse(contexto['camiones'].filter(pk=self.camion_patio.id).exists())

        nombre_flujo, pasos = obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(nombre_flujo, 'RECEPCION_TERRAMAR')
        self.assertEqual([paso for paso, _ in pasos], [
            'Pesaje Entrada', 'Ciclo Descarga', 'Pesaje Salida',
            'Documentación', 'Autorizar Salida', 'Confirmar Salida'
        ])
        texto_pasos = ' '.join(paso for paso, _ in pasos).upper()
        for requisito_ajeno in ('ESTANQUE', 'MUESTRA', 'CALIDAD', 'SAP'):
            self.assertNotIn(requisito_ajeno, texto_pasos)

        seguimiento_request = request_factory.get('/seguimiento-operacional/')
        seguimiento_request.user = self.usuario
        with patch('apps.home.views.Verificar_empresa', return_value=self.empresa.id), \
             patch('apps.home.views.obtener_valores_ingreso_camion', return_value={
                 'patente': 'ABCD12', 'conductor': 'Conductor Terramar'
             }), \
             patch('apps.home.views.render') as render_mock:
            SEGUIMIENTO_OPERACIONAL(seguimiento_request)
        seguimiento = render_mock.call_args.args[2]['camiones']
        fila = next(item for item in seguimiento if item['citacion_id'] == self.citacion.id)
        self.assertEqual(fila['nombre_flujo'], 'RECEPCION_TERRAMAR')
        self.assertEqual(fila['estado_actual'], 'Pesaje Entrada')

        with patch('apps.home.views.usuario_es_guardia_porteria', return_value=True):
            asegurar_notificaciones_guardia_porteria_pendientes(self.guardia_porteria, self.empresa.id)
            asegurar_notificaciones_guardia_porteria_pendientes(self.guardia_porteria, self.empresa.id)
        self.assertEqual(NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=self.guardia_porteria,
            EP_NID=self.empresa,
            NOT_CURL__endswith=f'citacion={self.citacion.id}',
        ).count(), 1)

        repetido = self.autorizar_ingreso()
        self.assertEqual(repetido.status_code, 409, repetido.content)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(self.citacion.id)
        ).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion, OPL_CPASO='Habilitar Operacion Planta'
        ).count(), 1)

    def test_ambas_secuencias_terramar_comparten_flujo_sin_alterar_configuraciones_existentes(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        nombre_flujo, pasos = obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(nombre_flujo, 'RECEPCION_TERRAMAR_BODEGA_EXTERNA')
        self.assertEqual(pasos, [
            ('Pesaje Entrada', ['OPERADOR ROMANA']),
            ('Ciclo Descarga', ['ASISTENTE CD']),
            ('Pesaje Salida', ['OPERADOR ROMANA']),
            ('Documentación', ['ASISTENTE RECEPCION']),
            ('Autorizar Salida', ['ASISTENTE DESPACHO']),
            ('Confirmar Salida', ['GUARDIA PORTERIA']),
        ])
        self.assertIs(views.FLUJOS_OPERACION_PLANTA['RECEPCION ESTANQUE SBH'], views.PASOS_RECEPCION_CON_CALIDAD)
        self.assertIs(views.FLUJOS_OPERACION_PLANTA['RECEPCION BODEGA EXTERNA'], views.PASOS_RECEPCION_BODEGA_EXTERNA)
        self.assertIs(views.FLUJOS_OPERACION_PLANTA['RECEPCION TRASVASIJE'], views.PASOS_RECEPCION_CON_CALIDAD)
        self.assertIs(views.FLUJOS_OPERACION_PLANTA['RECEPCION PATIO LF CON CALIDAD'], views.PASOS_RECEPCION_CON_CALIDAD)
        self.assertIs(views.FLUJOS_OPERACION_PLANTA['RECEPCION PATIO LF SIN CALIDAD'], views.PASOS_RECEPCION_SIN_CALIDAD)

        self.citacion.CI_CTIPO = 'DESPACHO'
        self.secuencia.SE_CCODIGO = 'EST_SBH_CLIENTE'
        nombre_despacho, pasos_despacho = obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(nombre_despacho, self.secuencia.SE_CNOMBRE)
        # Esta citación sigue siendo EP1 aunque se pruebe un código de secuencia SBH.
        self.assertNotIn(views.PASO_APROBAR_INICIO_CARGA, [paso for paso, _ in pasos_despacho])
        self.assertEqual(pasos_despacho, [
            paso for paso in views.pasos_despacho_operacion_activos(views.PASOS_DESPACHO_CARGA_ESTANQUE)
            if paso[0] != views.PASO_APROBAR_INICIO_CARGA
        ])

    def test_rama_comun_guardia_porteria_sigue_autorizando_sbh(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_ESTANQUE_SBH'
        self.secuencia.SE_CNOMBRE = 'RECEPCION ESTANQUE SBH'
        self.secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])
        self.preparar_guardia_porteria()

        response = self.autorizar_ingreso()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(self.citacion.id)
        ).count(), 1)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion, OPL_CPASO='Habilitar Operacion Planta'
        ).count(), 1)
        nombre_flujo, pasos = obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(nombre_flujo, 'RECEPCION ESTANQUE SBH')
        pasos_sbh_esperados = [
            paso for paso in views.PASOS_RECEPCION_CON_CALIDAD
            if not (
                views.RECEPCION_BORRADOR_SAP_TEMPORALMENTE_DESACTIVADO
                and paso[0] == views.PASO_BORRADOR_SAP
            )
        ]
        self.assertEqual(pasos, pasos_sbh_esperados)
