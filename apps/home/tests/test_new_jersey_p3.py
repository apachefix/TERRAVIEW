import json
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import new_jersey_p3 as p3, views
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    CITACION_ITEM,
    DATO_OPERACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    ETAPA_LOG,
    ITEM,
    NOTIFICACION,
    OPERACION_NEW_JERSEY,
    OPERACION_NEW_JERSEY_PROCESO,
    OPERACION_PLANTA_LOG,
    PLANIFICACION,
    SECUENCIA,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
)


class NewJerseyProceso3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            username='planificador_p3',
            email='p3@example.com',
            password='test',
        )
        cls.empresa_catalogo = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR',
            EP_CRUT='88-8',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='99-9',
            EP_CBASEDATOS='TEST',
            EP_CUSUARIOSBD='test',
            EP_CPORT='0',
        )
        cls.proveedor = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='P001',
            SN_CRAZONSOCIAL='PROVEEDOR NEW JERSEY',
            SN_CRUT='11-1',
            SN_CTIPO='S',
        )
        cls.transportista = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa,
            SN_CCODIGO_SAP='T001',
            SN_CRAZONSOCIAL='TRANSPORTE P3',
            SN_CRUT='22-2',
            SN_CTIPO='S',
        )
        cls.item_legacy = ITEM.objects.create(
            EP_NID=cls.empresa_catalogo,
            IT_CCODIGO='129',
            IT_CNOMBRE='ACEITES Y GRASAS',
        )
        cls.secuencia_p1 = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_NEW_JERSEY_P1_CON_CALIDAD',
            SE_CNOMBRE='New Jersey P1',
            SE_BHABILITADO=True,
        )
        cls.secuencia_p2 = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_NEW_JERSEY_P2_OPERACION_INTERNA',
            SE_CNOMBRE='New Jersey P2',
            SE_BHABILITADO=True,
        )
        cls.secuencia_p3 = SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO=p3.SECUENCIA_P3,
            SE_CNOMBRE='Sector New Jersey - Proceso 3 Retiro vacío',
            SE_BHABILITADO=True,
        )
        cls.etapa_p3 = ETAPA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='NJ_P3_INGRESO',
            ET_CNOMBRE='Ingreso camión P3',
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia_p3,
            ET_NID=cls.etapa_p3,
            SE_NPASO=1,
            SE_BHABILITADO=True,
            SE_BOBLIGATORIO=True,
        )
        cls.etapas_revision_p3 = [cls.etapa_p3]
        for paso, (codigo, nombre) in enumerate((
            ('NJ_P3_REVISION_ASISTENTE', 'Revisión Asistente Recepción'),
            ('NJ_P3_AUTORIZACION_GUARDIA', 'Autorización Guardia'),
            ('NJ_P3_INGRESO_PORTERIA', 'Ingreso físico Guardia Portería'),
            ('NJ_P3_OPERACION', 'Operación Planta P3'),
        ), start=2):
            etapa = ETAPA.objects.create(
                US_NID=cls.usuario,
                EP_NID=cls.empresa,
                ET_CTIPO='OPERACION',
                ET_CCODIGO=codigo,
                ET_CNOMBRE=nombre,
                ET_NCANTIDADMAXIMA=1,
                ET_BHABILITADO=True,
            )
            cls.etapas_revision_p3.append(etapa)
            DETALLE_SECUENCIA.objects.create(
                US_NID=cls.usuario,
                EP_NID=cls.empresa,
                SC_NID=cls.secuencia_p3,
                ET_NID=etapa,
                SE_NPASO=paso,
                SE_BHABILITADO=True,
                SE_BOBLIGATORIO=True,
            )
        fecha_base = timezone.localdate() - timedelta(days=1)
        cls.calendario_origen = CALENDARIO.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CA_CNOMBRE='New Jersey origen',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=fecha_base.day,
            CA_NMES=fecha_base.month,
            CA_NANO=fecha_base.year,
            CA_NCANTIDADCUPOS=5,
        )
        cls.planificacion_origen = PLANIFICACION.objects.create(
            US_NID=cls.usuario,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario_origen,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=timezone.now(),
            PL_FFECHAINICIO=timezone.now() - timedelta(days=1),
            PL_FFECHAFIN=timezone.now() - timedelta(hours=1),
            PL_NCANTIDADCUPOS=5,
        )

    def setUp(self):
        self.p1, self.p2, self.operacion = self._crear_operacion_lista_p3('65688', 'MDFGD4533')

    def _crear_operacion_lista_p3(self, guia, contenedor):
        p1 = CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion_origen,
            SC_NID=self.secuencia_p1,
            PRO_NID=self.proveedor,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now() - timedelta(days=1),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='TERMINADO',
            CI_CTIPODOCUMENTO='GD',
            CI_CNUMERODOCUMENTO=guia,
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=p1,
            EP_NID=self.empresa,
            US_NID=self.usuario,
            CDO_CORIGEN='new_jersey_p1',
            CDO_CGUIA=guia,
            CDO_CBL_CONTENEDOR=contenedor,
            CDO_CBL='BL-001',
            CDO_CCODIGO_SAP='950105',
            CDO_CINSUMO='ACIDOS GRASOS MARINOS EWOS',
            CDO_CPEDIDO_SAP='10001091',
            CDO_CDOCENTRY='6880',
            CDO_CSAP_OPOR_ID='6880',
            CDO_CTIPO_RECEPCION='NACIONAL',
            CDO_CCDA='CDA-1',
            CDO_CDI='DI-1',
            CDO_CBOOKING='BOOK-1',
            CDO_CNAVE_NAVIERA='NAVIERA',
            CDO_CFECHA_PRODUCCION='2026-09-01',
            CDO_CFECHA_VENCIMIENTO='2027-09-01',
            CDO_CESTANQUE_DESTINO='TK08',
        )
        CITACION_ITEM.objects.create(
            EP_NID=self.empresa,
            IT_NID=self.item_legacy,
            CI_NID=p1,
        )
        p2_citacion = CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            PL_NID=self.planificacion_origen,
            SC_NID=self.secuencia_p2,
            PRO_NID=self.proveedor,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now() - timedelta(days=1),
            CI_NCUPO=0,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='TERMINADO',
            CI_CTIPODOCUMENTO='GD',
            CI_CNUMERODOCUMENTO=guia,
            CI_NID_REF=p1.id,
        )
        CITACION_DETALLE_OPERACIONAL.objects.create(
            CI_NID=p2_citacion,
            EP_NID=self.empresa,
            US_NID=self.usuario,
            CDO_CORIGEN='new_jersey_p1',
            CDO_CGUIA=guia,
            CDO_CBL_CONTENEDOR=contenedor,
            CDO_CBL='BL-001',
            CDO_CCODIGO_SAP='950105',
            CDO_CINSUMO='ACIDOS GRASOS MARINOS EWOS',
            CDO_CPEDIDO_SAP='10001091',
            CDO_CDOCENTRY='6880',
            CDO_CSAP_OPOR_ID='6880',
            CDO_CTIPO_RECEPCION='NACIONAL',
            CDO_CCDA='CDA-1',
            CDO_CDI='DI-1',
            CDO_CBOOKING='BOOK-1',
            CDO_CNAVE_NAVIERA='NAVIERA',
            CDO_CFECHA_PRODUCCION='2026-09-01',
            CDO_CFECHA_VENCIMIENTO='2027-09-01',
            CDO_CESTANQUE_DESTINO='TK08',
        )
        operacion = OPERACION_NEW_JERSEY.objects.create(
            EP_NID=self.empresa,
            US_NID=self.usuario,
            PRO_NID=self.proveedor,
            ONJ_CMODALIDAD=OPERACION_NEW_JERSEY.Modalidad.CON_CALIDAD,
            ONJ_CESTADO=OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_3,
            ONJ_CITEM_CODE='950105',
            ONJ_CPRODUCTO='ACIDOS GRASOS MARINOS EWOS',
            ONJ_CPURCHASE_ORDER='10001091',
            ONJ_CBASE_ENTRY='6880',
            ONJ_CBASE_LINE='2',
            ONJ_CBODEGA_VIRTUAL='EPSBH',
            ONJ_CTK_DESTINO='TK08',
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=operacion,
            CI_NID=p1,
            EP_NID=self.empresa,
            US_NID=self.usuario,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.COMPLETADO,
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.create(
            ONJ_NID=operacion,
            CI_NID=p2_citacion,
            EP_NID=self.empresa,
            US_NID=self.usuario,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
            ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.COMPLETADO,
        )
        return p1, p2_citacion, operacion

    def _crear_plan_hoy(self, nombre='Recepción hoy', cupos=0, desplazamiento_minutos=0):
        ahora = timezone.now()
        fecha = timezone.localdate()
        calendario = CALENDARIO.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            CA_CNOMBRE=nombre,
            CA_FHORA_APERTURA=time(0),
            CA_FHORA_CIERRE=time(23, 59),
            CA_NDIA=fecha.day,
            CA_NMES=fecha.month,
            CA_NANO=fecha.year,
            CA_NCANTIDADCUPOS=cupos,
        )
        return PLANIFICACION.objects.create(
            US_NID=self.usuario,
            EP_NID=self.empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=ahora,
            PL_FFECHAINICIO=ahora - timedelta(hours=1) + timedelta(minutes=desplazamiento_minutos),
            PL_FFECHAFIN=ahora + timedelta(hours=1) + timedelta(minutes=desplazamiento_minutos),
            PL_NCANTIDADCUPOS=cupos,
            PL_NSOBRECUPO=True,
            PL_NCANTIDADSOBRECUPO=0,
        )

    def _iniciar(self, patente='sds 45'):
        return p3.iniciar_p3(
            self.operacion.id,
            self.usuario,
            self.transportista.id,
            patente,
        )

    def _confirmar_p3(self):
        citacion = self._iniciar()['citacion']
        camion, _ = p3.confirmar_camion_p3(
            citacion.id,
            'SDS45',
            self.usuario,
            transportista_id=self.transportista.id,
            empresa_transporte='TRANSPORTE P3',
            nombre_conductor='Conductor P3',
            rut_conductor='12.345.678-5',
            codigo_pais='+56',
            telefono_conductor='912345678',
        )
        return citacion, camion

    def _aprobar_p3(self, citacion, guardias=None):
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views,
            'obtener_guardias_relacionados_citacion',
            return_value=guardias if guardias is not None else [self.usuario],
        ):
            return self.client.post(
                reverse('pla_citacion_aprobar_asistente', args=[citacion.id]),
                {'bl': '', 'lote_contenedor': 'MDFGD4533'},
            )

    def test_p3_pendiente_aparece_y_p2_sigue_en_la_cola(self):
        request = RequestFactory().get(
            '/planificaciones/recepcion/new-jersey/p2/?estado=PENDIENTE&_empresa_id=2'
        )
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views,
            'queryset_transportistas_validos_ingreso_camion',
            return_value=SOCIONEGOCIO.objects.filter(pk=self.transportista.pk),
        ), patch.object(views, 'render', return_value=HttpResponse('ok')) as render_mock:
            response = views.PLANIFICACION_NEW_JERSEY_P2(request)
        self.assertEqual(response.status_code, 200)
        filas = render_mock.call_args.args[2]['filas']
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]['tipo_proceso'], 'P3')
        self.assertEqual(filas[0]['p1'].id, self.p1.id)
        self.assertEqual(filas[0]['p2'].id, self.p2.id)
        self.assertEqual(filas[0]['guia'], '65688')
        self.assertEqual(filas[0]['contenedor'], 'MDFGD4533')

        relacion_p2 = OPERACION_NEW_JERSEY_PROCESO.objects.get(
            ONJ_NID=self.operacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
        )
        relacion_p2.ONJP_CESTADO = relacion_p2.Estado.PENDIENTE
        relacion_p2.save(update_fields=['ONJP_CESTADO'])
        self.operacion.ONJ_CESTADO = self.operacion.Estado.PENDIENTE_PROCESO_2
        self.operacion.save(update_fields=['ONJ_CESTADO'])
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views,
            'queryset_transportistas_validos_ingreso_camion',
            return_value=SOCIONEGOCIO.objects.filter(pk=self.transportista.pk),
        ), patch.object(views, 'render', return_value=HttpResponse('ok')) as render_mock:
            views.PLANIFICACION_NEW_JERSEY_P2(request)
        filas = render_mock.call_args.args[2]['filas']
        self.assertEqual([fila['tipo_proceso'] for fila in filas], ['P2'])

    def test_menu_y_template_identifican_p2_y_p3(self):
        raiz = Path(__file__).resolve().parents[3]
        menu = (raiz / 'apps/templates/includes/component-navbar-inner.html').read_text(encoding='utf-8')
        self.assertIn('New Jersey Pendientes', menu)
        self.assertNotIn('New Jersey - P2 pendientes', menu)

        request = RequestFactory().get('/')
        request.user = self.usuario
        contexto = {
            'filas': [{
                'tipo_proceso': 'P3',
                'operacion': self.operacion,
                'p1': self.p1,
                'p2': self.p2,
                'p3': None,
                'guia': '65688',
                'contenedor': 'MDFGD4533',
                'item_code': '950105',
                'producto': 'ACIDOS GRASOS MARINOS EWOS',
                'proveedor': self.proveedor.SN_CRAZONSOCIAL,
                'pedido_sap': '10001091',
                'lote_sap': '',
                'tk_destino': 'TK08',
                'empresa_transporte': '',
                'patente_esperada': '',
                'estado_fila': 'PENDIENTE',
            }],
            'pagina': type('Pagina', (), {
                'has_previous': lambda self: False,
                'has_next': lambda self: False,
                'number': 1,
                'paginator': type('Paginador', (), {'num_pages': 1})(),
            })(),
            'estado': 'PENDIENTE',
            'empresa_activa_id': 2,
            'transportistas': [self.transportista],
        }
        html = get_template(
            'home/PLANIFICACION/new_jersey_p2_pendientes.html'
        ).render(contexto, request=request)
        self.assertIn('<th>Proceso</th>', html)
        self.assertIn('Iniciar P3', html)
        self.assertIn('name="transportista_id"', html)
        self.assertIn('name="patente"', html)

    def test_iniciar_exige_transportista_y_patente(self):
        with self.assertRaisesMessage(ValueError, 'empresa de transporte válida'):
            p3.iniciar_p3(self.operacion.id, self.usuario, '', 'SDS45')
        with self.assertRaisesMessage(ValueError, 'patente planificada'):
            p3.iniciar_p3(
                self.operacion.id,
                self.usuario,
                self.transportista.id,
                '',
            )
        self.assertFalse(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=self.operacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ).exists())

    def test_iniciar_crea_una_citacion_p3_sobrecupo_y_conserva_p1_p2(self):
        resultado = self._iniciar()
        repetido = self._iniciar('OTRA99')
        citacion = resultado['citacion']
        snapshot = p3.leer_snapshot_p3(citacion)

        self.assertTrue(resultado['created'])
        self.assertFalse(repetido['created'])
        self.assertEqual(repetido['citacion'].id, citacion.id)
        self.assertEqual(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=self.operacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ).count(), 1)
        self.assertEqual(citacion.SC_NID.SE_CCODIGO, p3.SECUENCIA_P3)
        self.assertEqual(citacion.CI_NID_REF, self.p2.id)
        self.assertEqual(citacion.CI_CNUMERODOCUMENTO, '65688')
        self.assertTrue(citacion.CI_BSOBRECUPO)
        self.assertEqual(citacion.PL_NID.CAL_NID.CA_NDIA, timezone.localdate().day)
        self.assertEqual(citacion.PL_NID.CAL_NID.CA_NMES, timezone.localdate().month)
        self.assertEqual(snapshot['patente_esperada'], 'SDS45')
        self.assertEqual(snapshot['transportista_id'], self.transportista.id)
        self.assertEqual(snapshot['empresa_transporte'], 'TRANSPORTE P3')
        self.assertEqual(snapshot['base_line'], '2')
        self.assertEqual(snapshot['tk_destino'], 'TK08')
        item_p3 = CITACION_ITEM.objects.get(CI_NID=citacion)
        self.assertEqual(item_p3.IT_NID_id, self.item_legacy.id)
        self.assertEqual(CITACION_ITEM.objects.filter(CI_NID=citacion).count(), 1)
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.p2.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.p2.CI_NID_REF, self.p1.id)
        self.assertEqual(CITACION_ITEM.objects.filter(CI_NID=self.p1).count(), 1)
        self.assertFalse(CITACION_ITEM.objects.filter(CI_NID=self.p2).exists())

    def test_repara_item_p3_existente_sin_duplicar_y_carga_la_carpeta(self):
        resultado = self._iniciar()
        citacion = resultado['citacion']
        CITACION_ITEM.objects.filter(CI_NID=citacion).delete()

        relacion, creada = p3.asegurar_citacion_item_p3(citacion)
        repetida, creada_repetida = p3.asegurar_citacion_item_p3(citacion)

        self.assertTrue(creada)
        self.assertFalse(creada_repetida)
        self.assertEqual(relacion.id, repetida.id)
        self.assertEqual(relacion.IT_NID_id, self.item_legacy.id)
        self.assertEqual(CITACION_ITEM.objects.filter(CI_NID=citacion).count(), 1)

        self.client.force_login(self.usuario)
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'obtener_clientes_aceite', return_value=[]
        ):
            listado = self.client.get(reverse('pla_listall'), {'_empresa_id': 2})
            carpeta = self.client.get(
                reverse('pla_listone', args=[citacion.PL_NID_id]),
                {'_empresa_id': 2},
            )
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(carpeta.status_code, 200)

    def test_usa_carpeta_activa_del_dia_e_informa_resultado(self):
        planificacion = self._crear_plan_hoy(cupos=4)
        self.client.force_login(self.usuario)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            response = self.client.post(
                reverse('planificacion_iniciar_new_jersey_p3', args=[self.operacion.id]),
                {
                    '_empresa_id': '2',
                    'transportista_id': str(self.transportista.id),
                    'patente': 'SDS 45',
                },
            )
        self.assertEqual(response.status_code, 302)
        relacion = OPERACION_NEW_JERSEY_PROCESO.objects.get(
            ONJ_NID=self.operacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        )
        self.assertEqual(relacion.CI_NID.PL_NID_id, planificacion.id)
        mensajes = [str(mensaje) for mensaje in get_messages(response.wsgi_request)]
        self.assertTrue(any('P3 iniciado correctamente' in mensaje for mensaje in mensajes))
        self.assertTrue(any(
            f'Carpeta de Recepción: #{planificacion.id}' in mensaje
            for mensaje in mensajes
        ))

    def test_multiples_carpetas_activas_bloquean_sin_elegir_por_id(self):
        self._crear_plan_hoy('Recepción A', cupos=1)
        self._crear_plan_hoy('Recepción B', cupos=1)
        with self.assertRaisesMessage(
            p3.CarpetaRecepcionP3Ambigua,
            'varias carpetas de Recepción activas',
        ):
            self._iniciar()
        self.assertFalse(OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=self.operacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ).exists())

    def test_consulta_patente_recupera_p3_vivo_sin_crear_camion(self):
        resultado = self._iniciar('sds 45')
        citacion = resultado['citacion']
        candidatos = p3.buscar_procesos_vivos_por_patente('SDS-45', 2)
        self.assertEqual(len(candidatos), 1)
        datos = candidatos[0]
        self.assertEqual(datos['citacion_id'], citacion.id)
        self.assertEqual(datos['operacion_id'], self.operacion.id)
        self.assertEqual(datos['guia'], '65688')
        self.assertEqual(datos['contenedor'], 'MDFGD4533')
        self.assertEqual(datos['producto'], 'ACIDOS GRASOS MARINOS EWOS')
        self.assertEqual(datos['pedido_sap'], '10001091')
        self.assertEqual(datos['docentry'], '6880')
        self.assertEqual(datos['base_line'], '2')
        self.assertEqual(datos['tk_destino'], 'TK08')
        self.assertEqual(datos['empresa_transporte'], 'TRANSPORTE P3')
        self.assertEqual(datos['patente_esperada'], 'SDS45')
        self.assertEqual(p3.buscar_procesos_vivos_por_patente('SDS45', 1), [])
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())


    def test_consulta_ignora_p3_historico(self):
        resultado = self._iniciar()
        citacion = resultado['citacion']
        proceso = resultado['proceso']
        citacion.CI_CESTADO = 'TERMINADO'
        citacion.save(update_fields=['CI_CESTADO'])
        self.assertEqual(p3.buscar_procesos_vivos_por_patente('SDS45', 2), [])
        citacion.CI_CESTADO = p3.ESTADO_CITACION_P3_PENDIENTE
        citacion.save(update_fields=['CI_CESTADO'])
        proceso.ONJP_CESTADO = proceso.Estado.COMPLETADO
        proceso.save(update_fields=['ONJP_CESTADO'])
        self.assertEqual(p3.buscar_procesos_vivos_por_patente('SDS45', 2), [])

    def test_consulta_bloquea_multiples_procesos_vivos(self):
        self._iniciar()
        _, _, otra_operacion = self._crear_operacion_lista_p3('65689', 'OTRO-CONT')
        p3.iniciar_p3(
            otra_operacion.id,
            self.usuario,
            self.transportista.id,
            'SDS45',
        )
        candidatos = p3.buscar_procesos_vivos_por_patente('SDS45', 2)
        self.assertEqual(len(candidatos), 2)
        with self.assertRaises(p3.ProcesosVivosPatenteAmbiguos):
            p3.consultar_proceso_vivo_por_patente('SDS45', 2)

    def test_confirmar_valida_patente_crea_trazabilidad_y_es_idempotente(self):
        resultado = self._iniciar('sds 45')
        citacion = resultado['citacion']
        with self.assertRaisesMessage(ValueError, 'no coincide'):
            p3.confirmar_camion_p3(citacion.id, 'OTRA99', self.usuario)
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())

        camion, creado = p3.confirmar_camion_p3(citacion.id, 'SDS-45', self.usuario)
        repetido, creado_repetido = p3.confirmar_camion_p3(
            citacion.id,
            'sds 45',
            self.usuario,
        )
        self.assertTrue(creado)
        self.assertFalse(creado_repetido)
        self.assertEqual(repetido.id, camion.id)
        self.assertEqual(CAMION_PATIO.objects.filter(CI_NID=citacion).count(), 1)
        self.assertEqual(camion.CPA_CPATENTE, 'SDS45')
        self.assertEqual(camion.CPA_CTRANSPORTISTA_DECLARADO, 'TRANSPORTE P3')
        self.assertEqual(camion.CPA_CNUMERO_GUIA, '65688')
        self.assertEqual(camion.CPA_CLOTE_CONTENEDOR, 'MDFGD4533')
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)
        trazabilidad = CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.get(
            CPA_NID=camion
        )
        self.assertEqual(trazabilidad.CI_NID_id, citacion.id)
        self.assertEqual(trazabilidad.CPTR_CPATENTE_CONSULTADA, 'SDS45')
        self.assertEqual(trazabilidad.CPTR_CPATENTE_PLANIFICADA, 'SDS45')
        citacion.refresh_from_db()
        self.assertEqual(
            citacion.CI_CESTADO,
            p3.ESTADO_CITACION_P3_CAMION_CONFIRMADO,
        )

    def test_recepcion_servicio_busca_p3_por_patente_y_guia(self):
        resultado = self._iniciar('sds 45')
        citacion = resultado['citacion']
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()

        for tipo, valor in (('patente', 'sds-45'), ('guia', '65688')):
            with patch.object(views, 'Verificar_empresa', return_value=2):
                response = self.client.get(
                    reverse('recepcion_servicio_registro'),
                    {'_empresa_id': 2, 'tipo_busqueda': tipo, 'busqueda': valor},
                )
            self.assertEqual(response.status_code, 200)
            datos = response.context['datos']
            self.assertEqual(datos['flujo_codigo'], 'NEW_JERSEY_P3')
            self.assertEqual(datos['citacion_id'], citacion.id)
            self.assertEqual(datos['p1_id'], self.p1.id)
            self.assertEqual(datos['p2_id'], self.p2.id)
            self.assertEqual(datos['operacion_id'], self.operacion.id)
            self.assertEqual(datos['guia'], '65688')
            self.assertEqual(datos['contenedor'], 'MDFGD4533')
            self.assertEqual(datos['item_code'], '950105')
            self.assertEqual(datos['producto'], 'ACIDOS GRASOS MARINOS EWOS')
            self.assertEqual(datos['tk_destino'], 'TK08')
            self.assertEqual(datos['empresa_transporte'], 'TRANSPORTE P3')
            self.assertEqual(datos['patente_planificada'], 'SDS45')
            html = response.content.decode('utf-8')
            self.assertIn('Flujo: NEW JERSEY P3', html)
            self.assertIn('Confirmar camión New Jersey P3', html)
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())

    def test_recepcion_servicio_confirma_p3_valida_e_idempotente(self):
        resultado = self._iniciar('sds 45')
        citacion = resultado['citacion']
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        datos = {
            '_empresa_id': 2,
            'tipo_busqueda': 'guia',
            'busqueda': '65688',
            'citacion_id': citacion.id,
            'empresa_transporte': 'TRANSPORTE P3',
            'transportista_id': str(self.transportista.id),
            'patente': 'SDS 45',
            'nombre_conductor': 'Conductor P3',
            'rut_conductor': '12.345.678-5',
            'codigo_pais': '+56',
            'telefono_conductor': '912345678',
        }

        with patch.object(views, 'Verificar_empresa', return_value=2):
            distinta = self.client.post(
                reverse('recepcion_servicio_registro'),
                {**datos, 'patente': 'OTRA99'},
            )
        self.assertEqual(distinta.status_code, 400)
        self.assertContains(distinta, 'no coincide', status_code=400)
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())

        with patch.object(views, 'Verificar_empresa', return_value=2):
            transporte_distinto = self.client.post(
                reverse('recepcion_servicio_registro'),
                {**datos, 'empresa_transporte': 'OTRO TRANSPORTE'},
            )
        self.assertEqual(transporte_distinto.status_code, 400)
        self.assertContains(transporte_distinto, 'empresa de transporte no coincide', status_code=400)
        self.assertFalse(CAMION_PATIO.objects.filter(CI_NID=citacion).exists())

        with patch.object(views, 'Verificar_empresa', return_value=2):
            response = self.client.post(reverse('recepcion_servicio_registro'), datos)
        self.assertEqual(response.status_code, 302)
        camion = CAMION_PATIO.objects.get(CI_NID=citacion)
        self.assertEqual(camion.CPA_CPATENTE, 'SDS45')
        self.assertEqual(camion.CPA_CTRANSPORTISTA_DECLARADO, 'TRANSPORTE P3')
        self.assertEqual(camion.CPA_CNOMBRE_CONDUCTOR, 'Conductor P3')
        self.assertEqual(camion.CPA_CRUT_CONDUCTOR, '12345678-5')
        self.assertEqual(camion.CPA_CTELEFONO_CONDUCTOR, '912345678')
        self.assertEqual(
            camion.trazabilidad_planificacion.CPTR_CRESULTADO_BUSQUEDA,
            views.RESULTADO_RECEPCION_SERVICIO_NEW_JERSEY_P3,
        )
        citacion.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, p3.ESTADO_CITACION_P3_CAMION_CONFIRMADO)

        with patch.object(views, 'Verificar_empresa', return_value=2):
            repetida = self.client.post(reverse('recepcion_servicio_registro'), datos)
        self.assertEqual(repetida.status_code, 302)
        self.assertEqual(CAMION_PATIO.objects.filter(CI_NID=citacion).count(), 1)
        self.assertFalse(views.OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO__icontains='SALIDA_TEMPORAL',
        ).exists())
        self.assertFalse(views.OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO__icontains='RETORNO',
        ).exists())

    def test_p3_ya_no_aparece_en_registro_camiones_y_ui_servicio_es_aislada(self):
        raiz = Path(__file__).resolve().parents[3]
        patio = (
            raiz / 'apps/templates/home/CAMION_PATIO/registrar.html'
        ).read_text(encoding='utf-8')
        servicio = (
            raiz / 'apps/templates/home/RECEPCION_SERVICIO/registro.html'
        ).read_text(encoding='utf-8')
        urls = (raiz / 'apps/home/urls.py').read_text(encoding='utf-8')
        self.assertNotIn('patio_p3_consultar', patio)
        self.assertNotIn('camiones_patio_consultar_proceso_vivo', patio)
        self.assertNotIn('camiones_patio_confirmar_new_jersey_p3', patio)
        self.assertNotIn('camiones-patio/consultar-proceso-vivo', urls)
        self.assertNotIn('camiones-patio/confirmar-new-jersey-p3', urls)
        self.assertIn('Registro de camión · Recepción Servicio', servicio)
        self.assertIn('servicio-search-row', servicio)
        self.assertIn('@media (max-width: 767.98px)', servicio)
        self.assertIn("datos.flujo_codigo == 'NEW_JERSEY_P3'", servicio)

    def test_confirmar_p3_deja_revision_asistente_pendiente_y_modal_editable(self):
        citacion, camion = self._confirmar_p3()

        logs = list(ETAPA_LOG.objects.filter(CI_NID=citacion).order_by('EL_FFECHAINICIO', 'id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].EL_CACCION, 'CAMION_P3_CONFIRMADO')
        self.assertIsNotNone(logs[0].EL_FFECHAFIN)
        self.assertEqual(logs[1].EL_CACCION, 'ENVIA_ASISTENTE')
        self.assertIsNone(logs[1].EL_FFECHAFIN)
        self.assertEqual(logs[1].ET_NID_id, self.etapas_revision_p3[1].id)
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)

        self.client.force_login(self.usuario)
        with patch.object(views, 'Verificar_empresa', return_value=2):
            response = self.client.get(
                reverse('pla_citacion_revision_asistente', args=[citacion.id])
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['es_new_jersey_p3'])
        self.assertFalse(payload['aprobado_asistente'])
        self.assertTrue(payload['puede_editar_revision_asistente'])
        self.assertEqual(payload['citacion']['Estado'], p3.ESTADO_CITACION_P3_CAMION_CONFIRMADO)
        self.assertEqual(payload['citacion']['Numero documento'], '65688')
        self.assertEqual(payload['datos_edicion_asistente']['patente'], 'SDS45')
        self.assertEqual(payload['datos_edicion_asistente']['lote_contenedor'], 'MDFGD4533')

    def test_aprobar_p3_avanza_a_guardia_notifica_y_reconfirmar_no_reabre_revision(self):
        citacion, _ = self._confirmar_p3()
        guardia = get_user_model().objects.create_user(
            username='guardia_p3', email='guardia-p3@example.com', password='test'
        )
        USERS_EMPRESA.objects.create(US_NID=guardia, EP_NID=self.empresa)
        response = self._aprobar_p3(citacion, guardias=[guardia])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['notificados_guardia'], 1)
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_CD_NEXT', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertEqual(
            views.operacion_envio_guardia_para_citacion(citacion),
            'APRUEBA_AR',
        )
        self.assertEqual(
            views.obtener_etapa_actual_operacional_citacion(citacion),
            views.NOMBRE_ETAPA_PENDIENTE_GUARDIA,
        )
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertTrue(NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=guardia,
            EP_NID=self.empresa,
            NOT_CCONTENIDO__icontains='debe ingresar a Planta',
            NOT_CURL__endswith=f'citacion={citacion.id}',
        ).exists())
        revision = ETAPA_LOG.objects.get(
            CI_NID=citacion, ET_NID=self.etapas_revision_p3[1]
        )
        self.assertIsNotNone(revision.EL_FFECHAFIN)
        self.assertEqual(revision.EL_CACCION, 'APRUEBA_ASISTENTE')
        etapa_guardia = ETAPA_LOG.objects.get(
            CI_NID=citacion, ET_NID=self.etapas_revision_p3[2], EL_FFECHAFIN=None
        )
        self.assertEqual(etapa_guardia.EL_CACCION, 'APRUEBA_ASISTENTE')

        p3.confirmar_camion_p3(citacion.id, 'SDS45', self.usuario)
        self.assertTrue(ETAPA_LOG.objects.filter(pk=etapa_guardia.pk, EL_FFECHAFIN=None).exists())
        self.assertFalse(ETAPA_LOG.objects.filter(
            CI_NID=citacion, ET_NID=self.etapas_revision_p3[1], EL_FFECHAFIN=None
        ).exists())

    def test_reparar_transicion_legacy_conserva_aprobacion_y_deja_guardia(self):
        citacion, camion = self._confirmar_p3()
        self.assertEqual(self._aprobar_p3(citacion).status_code, 200)
        planificacion_id = citacion.PL_NID_id
        camion_id = camion.id

        SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR',
            LOG_CADD1=str(citacion.id),
        ).update(LOG_COPERACION='ENVIA_CD_NEXT')
        ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            EL_CACCION='APRUEBA_ASISTENTE',
        ).update(EL_CACCION='ENVIA_CD_NEXT')

        resultado = p3.reparar_transicion_guardia_p3(citacion.id)

        citacion.refresh_from_db()
        camion.refresh_from_db()
        self.assertEqual(resultado['responsable_siguiente'], 'GUARDIA')
        self.assertTrue(resultado['aprobacion_conservada'])
        self.assertEqual(citacion.PL_NID_id, planificacion_id)
        self.assertEqual(camion.id, camion_id)
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_CD_NEXT',
            LOG_CADD1=str(citacion.id),
        ).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR',
            LOG_CADD1=str(citacion.id),
        ).exists())
        self.assertFalse(ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            EL_CACCION='ENVIA_CD_NEXT',
        ).exists())
        self.assertTrue(ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            ET_NID=self.etapas_revision_p3[2],
            EL_CACCION='APRUEBA_ASISTENTE',
            EL_FFECHAFIN=None,
        ).exists())

        with patch.object(views, 'Verificar_empresa', return_value=2):
            modal = self.client.get(
                reverse('pla_citacion_revision_asistente', args=[citacion.id])
            )
        self.assertTrue(modal.json()['aprobado_asistente'])
        self.assertFalse(modal.json()['puede_editar_revision_asistente'])

    def test_reparar_transicion_preserva_avance_valido_de_guardia(self):
        citacion, _ = self._confirmar_p3()
        self.assertEqual(self._aprobar_p3(citacion).status_code, 200)

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_guardia', return_value=True
        ), patch.object(
            views, 'usuario_es_guardia_porteria', return_value=False
        ), patch.object(
            views, 'obtener_usuarios_guardia_porteria', return_value=[]
        ):
            respuesta_guardia = self.client.post(
                reverse('pla_citacion_enviar_guardia_porteria', args=[citacion.id])
            )
        self.assertEqual(respuesta_guardia.status_code, 200)

        SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR',
            LOG_CADD1=str(citacion.id),
        ).update(LOG_COPERACION='ENVIA_CD_NEXT')
        ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            ET_NID=self.etapas_revision_p3[1],
            EL_CACCION='APRUEBA_ASISTENTE',
        ).update(EL_CACCION='ENVIA_CD_NEXT')

        resultado = p3.reparar_transicion_guardia_p3(citacion.id)

        self.assertEqual(resultado['responsable_siguiente'], 'GUARDIA_PORTERIA')
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA',
            LOG_CADD1=str(citacion.id),
        ).exists())
        self.assertTrue(ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            ET_NID=self.etapas_revision_p3[3],
            EL_FFECHAFIN=None,
        ).exists())
    def test_asistente_cd_no_puede_intervenir_en_p3(self):
        citacion, _ = self._confirmar_p3()
        self.assertEqual(self._aprobar_p3(citacion).status_code, 200)

        with patch.object(views, 'Verificar_empresa', return_value=2):
            detalle = self.client.get(
                reverse('pla_citacion_estanque', args=[citacion.id])
            )
            avanzar = self.client.post(
                reverse('pla_citacion_estanque_avanzar', args=[citacion.id])
            )

        self.assertEqual(detalle.status_code, 403)
        self.assertEqual(avanzar.status_code, 403)
        self.assertIn('directamente de Asistente Recepcion a Guardia', detalle.json()['message'])
        self.assertIn('directamente de Asistente Recepcion a Guardia', avanzar.json()['message'])

    def test_ui_p3_muestra_guardia_y_excluye_acciones_asistente_cd(self):
        raiz = Path(__file__).resolve().parents[3]
        template = (
            raiz / 'apps/templates/home/PLANIFICACION/pla_listone.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Aprobar y enviar a Guardia', template)
        self.assertIn(
            'request.user|es_asistente_cd and object.24 and not object.47.es_new_jersey_p3',
            template,
        )
        self.assertIn(
            'request.user|es_asistente_cd and not object.47.es_new_jersey_p3',
            template,
        )
    def test_guardia_y_guardia_porteria_habilitan_operacion_en_dos_acciones(self):
        citacion, _ = self._confirmar_p3()
        self.assertEqual(self._aprobar_p3(citacion).status_code, 200)

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_guardia', return_value=True
        ), patch.object(
            views, 'usuario_es_guardia_porteria', return_value=False
        ), patch.object(
            views, 'obtener_usuarios_guardia_porteria', return_value=[]
        ):
            response_guardia = self.client.post(
                reverse('pla_citacion_enviar_guardia_porteria', args=[citacion.id])
            )
        self.assertEqual(response_guardia.status_code, 200)
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_GUARDIA_PORTERIA', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertFalse(views.citacion_habilitada_operacion(citacion))

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_guardia', return_value=True
        ), patch.object(
            views, 'usuario_es_guardia_porteria', return_value=True
        ):
            response_porteria = self.client.post(
                reverse('pla_citacion_enviar_guardia_porteria', args=[citacion.id])
            )
        self.assertEqual(response_porteria.status_code, 200)
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(citacion.id)
        ).exists())
        self.assertTrue(views.citacion_habilitada_operacion(citacion))

    def test_operacion_p3_tiene_cinco_etapas_y_no_altera_p1_p2_prosesa(self):
        citacion = self._iniciar()['citacion']
        nombre, pasos = views.obtener_pasos_operacion_citacion(citacion)

        self.assertIn('NEW JERSEY', nombre.upper())
        self.assertEqual(pasos, [
            ('Pesaje Entrada', ['OPERADOR ROMANA']),
            ('Carga / Descarga', ['OPERADOR ROMANA']),
            ('Pesaje Salida', ['OPERADOR ROMANA']),
            ('Autorizar Salida', ['ASISTENTE DE RECEPCION']),
            ('Confirmar Salida', ['GUARDIA PORTERIA']),
        ])
        texto = ' '.join(paso for paso, _ in pasos).upper()
        for excluido in ('MUESTRA', 'CALIDAD', 'SALIDA TEMPORAL', 'RETORNO'):
            self.assertNotIn(excluido, texto)
        self.assertEqual(views.PASOS_RECEPCION_NEW_JERSEY_P1[1][0], 'Descarga Contenedor')
        self.assertEqual(views.PASOS_RECEPCION_PROSESA_PISO_2[1][0], views.PASO_PROSESA_INICIO_RETIRO)
        self.assertEqual(self.p1.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.p2.CI_CESTADO, 'TERMINADO')

    def test_ui_p3_muestra_un_solo_boton_ticket_salida_en_pesaje_salida(self):
        raiz = Path(__file__).resolve().parents[3]
        template = (
            raiz / 'apps/templates/home/CITACION/operacion_planta.html'
        ).read_text(encoding='utf-8')
        inicio_p3 = template.index('{% if paso.es_new_jersey_p3 %}')
        fin_p3 = template.index('{% elif paso.es_ciclo_carga_despacho %}', inicio_p3)
        bloque_carga_descarga_p3 = template[inicio_p3:fin_p3]

        self.assertNotIn('btn-obtener-ticket-pesaje', bloque_carga_descarga_p3)
        self.assertNotIn('OBTENER TICKET DE SALIDA', bloque_carga_descarga_p3)
        self.assertIn(
            'Esta etapa se completará automáticamente al obtener el ticket de salida.',
            bloque_carga_descarga_p3,
        )
        self.assertEqual(template.lower().count('obtener ticket de salida'), 1)
        self.assertIn('data-paso="{{ paso.nombre }}"', template)
        self.assertIn('data-tipo-ticket="{{ paso.tipo_ticket_pesaje }}"', template)
    def test_ui_habilita_ticket_salida_mientras_carga_descarga_esta_en_proceso(self):
        citacion, _ = self._confirmar_p3()
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, '_ticket_pesaje_obligatorio_guardado', return_value=True
        ):
            entrada = self.client.post(
                reverse('operacion_planta_guardar_paso', args=[citacion.id]),
                {'paso': 'Pesaje Entrada', 'observacion': 'COM_ENT registrado'},
            )
        self.assertEqual(entrada.status_code, 200)

        request = RequestFactory().get(f'/operacion-planta/{citacion.id}/')
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, 'render', return_value=HttpResponse('ok')
        ) as render_mock:
            response = views.OPERACION_PLANTA_CITACION(request, citacion.id)

        self.assertEqual(response.status_code, 200)
        pasos = render_mock.call_args.args[2]['pasos']
        carga = next(paso for paso in pasos if paso['nombre'] == 'Carga / Descarga')
        salida = next(paso for paso in pasos if paso['nombre'] == 'Pesaje Salida')
        self.assertTrue(carga['activo'])
        self.assertTrue(carga['ciclo_descarga']['en_proceso'])
        self.assertFalse(salida['activo'])
        self.assertTrue(salida['puede_obtener_ticket_salida_p3'])
        self.assertTrue(salida['puede_obtener_ticket_pesaje'])
    def test_pesajes_automatizan_carga_descarga_y_confirmar_salida_completa_p3(self):
        citacion, camion = self._confirmar_p3()
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = 2
        session.save()
        permisos = (
            patch.object(views, 'Verificar_empresa', return_value=2),
            patch.object(views, 'usuario_es_operacion_planta', return_value=True),
            patch.object(views, 'usuario_puede_paso_operacion', return_value=True),
            patch.object(views, 'citacion_habilitada_operacion', return_value=True),
            patch.object(views, '_ticket_pesaje_obligatorio_guardado', return_value=True),
        )
        with permisos[0], permisos[1], permisos[2], permisos[3], permisos[4]:
            entrada = self.client.post(
                reverse('operacion_planta_guardar_paso', args=[citacion.id]),
                {'paso': 'Pesaje Entrada', 'observacion': 'COM_ENT registrado'},
            )
        self.assertEqual(entrada.status_code, 200)
        ciclo = views._leer_metadata_ciclo_descarga(citacion)
        self.assertEqual(ciclo['estado'], 'EN_PROCESO')
        self.assertTrue(ciclo['inicio_automatico'])
        self.assertTrue(ciclo['inicio_descarga'])
        self.assertFalse(ciclo['fin_descarga'])
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO=views.PASO_NJ_P3_CARGA_DESCARGA,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
        ).exists())

        ruta_ticket = r'C:\tickets\COM_SAL_SDS45_26_09_29_12_00.pdf'
        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, '_buscar_ticket_pesaje_mas_reciente', return_value=ruta_ticket
        ), patch.object(
            views, '_extraer_datos_ticket_pesaje', return_value={
                'folio': 'SAL-38734', 'peso_neto': 12000, 'observacion': 'Ticket salida P3',
            }
        ), patch.object(
            views, '_copiar_ticket_local_si_necesario', return_value=ruta_ticket
        ), patch.object(
            views, '_ruta_ticket_permitida', return_value=True
        ), patch.object(
            views, '_payload_ticket_pesaje_guardado', return_value={}
        ):
            ticket = self.client.get(
                reverse('ajax_operacion_planta_obtener_ticket_pesaje'),
                {'citacion_id': citacion.id, 'paso_nombre': 'Pesaje Salida'},
            )
        self.assertEqual(ticket.status_code, 200)
        ticket_payload = ticket.json()
        self.assertTrue(ticket_payload['valid'])
        self.assertTrue(ticket_payload['carga_descarga_completada'])
        self.assertTrue(ticket_payload['recargar_operacion'])
        ciclo = views._leer_metadata_ciclo_descarga(citacion)
        self.assertEqual(ciclo['estado'], 'COMPLETADO')
        self.assertTrue(ciclo['fin_descarga'])
        self.assertIsNotNone(ciclo['duracion_segundos'])
        self.assertTrue(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO=views.PASO_NJ_P3_CARGA_DESCARGA,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).exists())
        ticket_salida = DATO_OPERACION.objects.get(
            CI_NID=citacion,
            CAMP_NID__CA_CCODIGO='OP_TICKET_PESAJE_SAL',
        )
        metadata_ticket_salida = json.loads(ticket_salida.DO_CVALOR)
        self.assertEqual(metadata_ticket_salida['tipo_ticket'], 'SAL')
        self.assertEqual(metadata_ticket_salida['paso_operacion'], 'Pesaje Salida')
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO='Pesaje Salida',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        ).exists())
        self.assertEqual(
            views.obtener_paso_activo_operacion(citacion)[0],
            'Pesaje Salida',
        )

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, '_ticket_pesaje_obligatorio_guardado', return_value=True
        ):
            salida = self.client.post(
                reverse('operacion_planta_guardar_paso', args=[citacion.id]),
                {'paso': 'Pesaje Salida', 'observacion': 'COM_SAL registrado'},
            )
        self.assertEqual(salida.status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(citacion)[0], 'Autorizar Salida')

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ), patch.object(
            views, '_empresa_timbre_recepcion', return_value=''
        ), patch.object(
            views, 'aplica_timbraje_recepcion', return_value=False
        ), patch.object(
            views, 'obtener_peso_real_new_jersey_p3_para_sap',
            return_value={'peso_real_kg': 20000},
        ), patch.object(
            views, 'estado_transferencia_new_jersey_p3',
            return_value={'creada': True, 'bloqueada': True, 'estado': 'CREADO'},
        ):
            autorizacion = self.client.post(
                reverse('ajax_operacion_planta_autorizar_salida', args=[citacion.id]),
                {'recepcion_conforme': 'SI', 'observacion_descarga': 'Conforme'},
            )
        self.assertEqual(autorizacion.status_code, 200)
        self.assertTrue(autorizacion.json()['success'])
        self.assertEqual(views.obtener_paso_activo_operacion(citacion)[0], 'Confirmar Salida')

        with patch.object(views, 'Verificar_empresa', return_value=2), patch.object(
            views, 'usuario_es_operacion_planta', return_value=True
        ), patch.object(
            views, 'usuario_puede_paso_operacion', return_value=True
        ), patch.object(
            views, 'citacion_habilitada_operacion', return_value=True
        ):
            confirmacion = self.client.post(
                reverse('operacion_planta_guardar_paso', args=[citacion.id]),
                {'paso': 'Confirmar Salida', 'observacion': 'Salida física confirmada'},
            )
        self.assertEqual(confirmacion.status_code, 200)
        citacion.refresh_from_db()
        camion.refresh_from_db()
        proceso = OPERACION_NEW_JERSEY_PROCESO.objects.get(
            CI_NID=citacion,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        )
        self.operacion.refresh_from_db()
        self.assertEqual(citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(proceso.ONJP_CESTADO, OPERACION_NEW_JERSEY_PROCESO.Estado.COMPLETADO)
        self.assertEqual(self.operacion.ONJ_CESTADO, OPERACION_NEW_JERSEY.Estado.COMPLETADA)
        self.assertNotEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_ASOCIADO_CITACION)