import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import CITACION, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION, DETALLE_SECUENCIA, EMPRESA, ETAPA, ITEM, SECUENCIA, SOCIONEGOCIO


class RecepcionSbhEtapa0AjustesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sbh = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-9',
            EP_CBASEDATOS='test_sbh', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='1-9',
            EP_CBASEDATOS='test_terramar', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        for empresa in (cls.sbh, cls.terramar):
            for codigo in (
                'RECEPCION_PATIO_LF_CON_CALIDAD',
                'RECEPCION_PATIO_LF_SIN_CALIDAD',
                'RECEPCION_NEW_JERSEY_P1_CON_CALIDAD',
                'RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD',
                'RECEPCION_ESTANQUE_SBH',
                'RECEPCION_BODEGA_EXTERNA',
                'RECEPCION_TRASVASIJE',
                'RECEPCION_SERVICIO',
            ):
                SECUENCIA.objects.create(
                    EP_NID=empresa, SE_CTIPO='RECEPCION',
                    SE_CCODIGO=codigo, SE_CNOMBRE=codigo, SE_BHABILITADO=True,
                )
        SECUENCIA.objects.create(
            EP_NID=cls.sbh, SE_CTIPO='DESPACHO', SE_CCODIGO='EST_SBH_CLIENTE',
            SE_CNOMBRE='Despacho Estanque', SE_BHABILITADO=True,
        )
        cls.proveedor = SOCIONEGOCIO.objects.create(
            EP_NID=cls.sbh, SN_CTIPO='S', SN_CCODIGO_SAP='P002',
            SN_CRAZONSOCIAL='Proveedor B', SN_CRUT='22222222-2',
            SN_BHABILITADO=True,
        )
        cls.usuario = get_user_model().objects.create_user('planificador_sbh_test', password='test-pass')
        ITEM.objects.create(id=26, EP_NID=cls.sbh, IT_CCODIGO='ITEM-26', IT_CNOMBRE='Producto prueba')
        etapa = ETAPA.objects.create(
            EP_NID=cls.sbh, ET_CTIPO='OPERACION', ET_CCODIGO='PROGRAMADO_TEST',
            ET_CNOMBRE='Programado', ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.sbh,
            SC_NID=SECUENCIA.objects.get(EP_NID=cls.sbh, SE_CCODIGO='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD'),
            ET_NID=etapa, SE_NPASO=1, SE_BHABILITADO=True,
        )

    def test_sbh_oculta_patio_lf_y_conserva_flujos_vigentes(self):
        codigos = set(views.queryset_secuencias_recepcion_sbh_por_flujo(
            2, 'INGRESO_MERCADERIA'
        ).values_list('SE_CCODIGO', flat=True))
        self.assertFalse(codigos & views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH)
        self.assertTrue({
            'RECEPCION_NEW_JERSEY_P1_CON_CALIDAD',
            'RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD',
            'RECEPCION_ESTANQUE_SBH',
            'RECEPCION_BODEGA_EXTERNA',
            'RECEPCION_TRASVASIJE',
            'RECEPCION_SERVICIO',
        } <= codigos)
        self.assertEqual(SECUENCIA.objects.filter(
            EP_NID=self.sbh,
            SE_CCODIGO__in=views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH,
        ).count(), 2)

    def test_tk18_planificado_sigue_si_valido_en_catalogo_operacional_sbh(self):
        self.assertIn('TK18', views.ESTANQUES_POR_ALMACEN['SBH'])
        self.assertEqual(len(views.ESTANQUES_POR_ALMACEN['SBH']), len(set(views.ESTANQUES_POR_ALMACEN['SBH'])))

    def test_bootstrap_no_rehabilita_patio_lf_sbh(self):
        SECUENCIA.objects.filter(
            EP_NID=self.sbh,
            SE_CCODIGO__in=views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH,
        ).update(SE_BHABILITADO=False)
        flujos = tuple(
            flujo for flujo in views.FLUJOS_RECEPCION_ETAPA_0
            if flujo[0] in views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH
        )
        with patch.object(views, 'FLUJOS_RECEPCION_ETAPA_0', flujos):
            self.assertEqual(views.asegurar_flujos_recepcion_etapa_0(2, None), [])
        self.assertFalse(SECUENCIA.objects.filter(
            EP_NID=self.sbh,
            SE_CCODIGO__in=views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH,
            SE_BHABILITADO=True,
        ).exists())

    def test_empresa_1_y_despacho_no_heredan_exclusion(self):
        codigos_e1 = set(views.queryset_secuencias_recepcion_sbh_por_flujo(
            1, 'INGRESO_MERCADERIA'
        ).values_list('SE_CCODIGO', flat=True))
        self.assertTrue(views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH <= codigos_e1)
        self.assertTrue(SECUENCIA.objects.filter(
            EP_NID=self.sbh, SE_CTIPO='DESPACHO', SE_CCODIGO='EST_SBH_CLIENTE',
            SE_BHABILITADO=True,
        ).exists())

    def test_backend_rechaza_ambos_patio_lf_para_nuevas_citaciones(self):
        for codigo in views.SECUENCIAS_PATIO_LF_HISTORICAS_SBH:
            with self.subTest(codigo=codigo):
                secuencia = SECUENCIA.objects.get(EP_NID=self.sbh, SE_CCODIGO=codigo)
                request = RequestFactory().post('/crear-planificacion-citacion/', {
                    'flujo': 'INGRESO_MERCADERIA',
                    'citaciones_json': json.dumps([{
                        'fecha_llegada': '2026-10-04', 'tipo_operacion': 'RECEPCION',
                        'flujo': 'INGRESO_MERCADERIA', 'secuencia_id': secuencia.id,
                    }]),
                })
                request.user = SimpleNamespace()
                with patch.object(views, 'Verificar_empresa', return_value=2):
                    response = views.CREAR_PLANIFICACION_CITACION(request)
                self.assertEqual(response.status_code, 400)
                self.assertIn('secuencia', json.loads(response.content)['message'].lower())

    def test_creacion_multiple_persiste_proveedor_elegido_pedido_y_tk18(self):
        secuencia = SECUENCIA.objects.get(
            EP_NID=self.sbh, SE_CCODIGO='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD'
        )
        base = {
            'fecha_llegada': '2026-10-04', 'tipo_operacion': 'RECEPCION',
            'tipo_origen_recepcion': 'NACIONAL', 'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': secuencia.id, 'almacen_destino': 'SBH',
            'estanque_destino': 'TK18', 'codigo': 'ITEM-26', 'insumo': 'Producto prueba',
            'pedido': '12345',
        }
        citaciones = [
            {**base, 'proveedor': f'maestro:{self.proveedor.id}',
             'proveedor_nombre': 'Proveedor anterior', 'codigo_proveedor_sap': 'P001'},
            {**base, 'proveedor': 'manual:Proveedor ingresado',
             'proveedor_nombre': 'Proveedor anterior', 'codigo_proveedor_sap': 'P001'},
        ]
        request = RequestFactory().post('/crear-planificacion-citacion/', {
            'flujo': 'INGRESO_MERCADERIA', 'citaciones_json': json.dumps(citaciones),
        })
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'consultar_proveedores_sap') as consultar_proveedores, \
             patch.object(views, 'consultar_pedido_sap') as consultar_pedido:
            response = views.CREAR_PLANIFICACION_CITACION(request)
        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'], payload)
        self.assertEqual(len(payload['citaciones']), 2)
        primera, segunda = [CITACION.objects.get(pk=pk) for pk in payload['citaciones']]
        self.assertEqual(primera.PL_NID_id, segunda.PL_NID_id)
        self.assertEqual(primera.PRO_NID_id, self.proveedor.id)
        self.assertIsNone(segunda.PRO_NID_id)
        for citacion, nombre, codigo in (
            (primera, 'Proveedor B', 'P002'),
            (segunda, 'Proveedor ingresado', ''),
        ):
            detalle = CITACION_DETALLE_OPERACIONAL.objects.get(CI_NID=citacion)
            self.assertEqual(detalle.CDO_CPRODUCTOR, nombre)
            self.assertEqual(detalle.CDO_CPROVEEDOR_CODIGO, codigo)
            self.assertEqual(detalle.CDO_CPEDIDO_SAP, '12345')
            self.assertEqual(detalle.CDO_CESTANQUE_DESTINO, 'TK18')
            datos = dict(DATO_OPERACION.objects.filter(CI_NID=citacion).values_list(
                'CAMP_NID__CA_CCODIGO', 'DO_CVALOR'
            ))
            self.assertEqual(datos['PLAN_PROVEEDOR_SAP'], nombre)
            self.assertEqual(datos.get('PLAN_CODIGO_PROVEEDOR_SAP', ''), codigo)
        consultar_proveedores.assert_not_called()
        consultar_pedido.assert_not_called()

    def test_maestro_canoniza_codigo_y_nombre_ignorando_valores_sap_previos(self):
        item = {
            'proveedor': f'maestro:{self.proveedor.id}',
            'proveedor_nombre': 'Proveedor anterior',
            'proveedor_codigo': 'P001',
            'codigo_proveedor_sap': 'P001',
        }
        self.assertFalse(views.normalizar_proveedor_recepcion_sbh_etapa_0(item, 2))
        self.assertEqual(item['proveedor'], 'P002')
        self.assertEqual(item['proveedor_nombre'], 'Proveedor B')
        self.assertEqual(item['proveedor_sap'], 'Proveedor B')
        self.assertEqual(item['proveedor_codigo'], 'P002')
        self.assertEqual(item['codigo_proveedor_sap'], 'P002')
        socio = views.resolver_socio_negocio_planificacion(
            2, 'S', valor=item['proveedor'], codigo=item['codigo_proveedor_sap'],
            nombre=item['proveedor_nombre'],
        )
        self.assertEqual(socio, self.proveedor)

    def test_manual_guarda_nombre_sin_codigo_ni_socio(self):
        item = {
            'proveedor': 'manual:Proveedor ingresado',
            'proveedor_nombre': 'Proveedor anterior',
            'proveedor_codigo': 'P001',
            'codigo_proveedor_sap': 'P001',
        }
        self.assertTrue(views.normalizar_proveedor_recepcion_sbh_etapa_0(item, 2))
        self.assertEqual(item['proveedor'], '')
        self.assertEqual(item['proveedor_nombre'], 'Proveedor ingresado')
        self.assertEqual(item['codigo_proveedor_sap'], '')
        citacion = SimpleNamespace(EP_NID_id=2, EP_NID=self.sbh, CI_CTIPO='RECEPCION', US_NID=None)
        with patch.object(views.CITACION_DETALLE_OPERACIONAL.objects, 'update_or_create') as guardar_detalle, \
             patch.object(views, 'guardar_dato_operacion_codigo') as guardar_dato:
            guardar_detalle.return_value = (object(), True)
            views.guardar_detalle_operacional_citacion(citacion, item)
            views.guardar_datos_planificacion_operacional(citacion, item, None)
        defaults = guardar_detalle.call_args.kwargs['defaults']
        self.assertEqual(defaults['CDO_CPRODUCTOR'], 'Proveedor ingresado')
        self.assertEqual(defaults['CDO_CPROVEEDOR_CODIGO'], '')
        self.assertEqual([call.args[1] for call in guardar_dato.call_args_list], ['PLAN_PROVEEDOR_SAP'])

    def test_sugerencia_sap_precarga_codigo_y_nombre_coherentes(self):
        item = {'proveedor': 'sap:P999', 'proveedor_nombre': 'Proveedor SAP',
                'proveedor_codigo': 'P001', 'codigo_proveedor_sap': 'P001'}
        self.assertFalse(views.normalizar_proveedor_recepcion_sbh_etapa_0(item, 2))
        self.assertEqual((item['proveedor'], item['proveedor_nombre'], item['codigo_proveedor_sap']),
                         ('P999', 'Proveedor SAP', 'P999'))

    def test_cliente_legacy_no_conserva_codigo_oculto_de_otro_proveedor(self):
        item = {'proveedor': 'P999', 'proveedor_nombre': 'Proveedor SAP',
                'proveedor_codigo': 'P001', 'codigo_proveedor_sap': 'P001'}
        self.assertFalse(views.normalizar_proveedor_recepcion_sbh_etapa_0(item, 2))
        self.assertEqual(item['proveedor_codigo'], 'P999')
        self.assertEqual(item['codigo_proveedor_sap'], 'P999')

    def test_maestro_ajeno_no_se_puede_elegir(self):
        item = {'proveedor': f'maestro:{self.proveedor.id}'}
        with self.assertRaises(ValueError):
            views.normalizar_proveedor_recepcion_sbh_etapa_0(item, 1)

    def test_modal_sbh_habilita_proveedor_y_conserva_cantidad_a_crear(self):
        template = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_form.html').read_text(encoding='utf-8')
        script = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_scripts.html').read_text(encoding='utf-8')
        self.assertIn('id="proveedor" name="proveedor" required {% if not es_recepcion_sbh %}disabled{% endif %}', template)
        self.assertIn('value="maestro:{{ proveedor.id }}"', template)
        self.assertIn("id: 'manual:' + nombre", script)
        self.assertIn('for (let i = 0; i < cantidad; i++)', script)
