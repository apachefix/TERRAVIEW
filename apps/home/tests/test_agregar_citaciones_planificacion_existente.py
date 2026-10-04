import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import (
    CALENDARIO, CAMION_PATIO_NO_PLANIFICADO, CITACION, CITACION_ITEM,
    DETALLE_SECUENCIA, EMPRESA, ETAPA, ITEM, PLANIFICACION, SECUENCIA,
)


class AgregarCitacionesPlanificacionExistenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-9',
            EP_CBASEDATOS='test_sbh', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.usuario = get_user_model().objects.create_superuser(
            username='planificador_agregar_test', password='test-pass', email='test@example.invalid',
        )
        cls.secuencia = SECUENCIA.objects.create(
            EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD',
            SE_CNOMBRE='New Jersey sin calidad', SE_BHABILITADO=True,
        )
        ITEM.objects.create(id=26, EP_NID=cls.empresa, IT_CCODIGO='ITEM-26', IT_CNOMBRE='Producto prueba')
        etapa = ETAPA.objects.create(
            EP_NID=cls.empresa, ET_CTIPO='OPERACION', ET_CCODIGO='PROGRAMADO_TEST',
            ET_CNOMBRE='Programado', ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=etapa, SE_NPASO=1, SE_BHABILITADO=True,
        )

    def setUp(self):
        self.factory = RequestFactory()
        self.datos = {
            'fecha_llegada': '2026-10-05', 'tipo_operacion': 'RECEPCION',
            'tipo_origen_recepcion': 'NACIONAL', 'flujo': 'INGRESO_MERCADERIA',
            'secuencia_id': self.secuencia.pk, 'almacen_destino': 'SBH',
            'estanque_destino': 'TK18', 'codigo': 'ITEM-26',
            'insumo': 'Producto prueba', 'pedido': '12345',
            'proveedor': 'manual:Proveedor prueba',
        }
        self.planificacion = self._guardar([self.datos], sobrecupos=30)['planificacion_id']

    def _guardar(self, citaciones, planificacion_id=None, sobrecupos=0, empresa=2, solicitud=None):
        data = {
            'flujo': 'INGRESO_MERCADERIA', 'citaciones_json': json.dumps(citaciones),
            'cantidad_sobrecupo': str(sobrecupos),
        }
        if planificacion_id is not None:
            data['planificacion_existente_id'] = str(planificacion_id)
        if solicitud is not None:
            data['solicitud_no_planificado_id'] = str(solicitud)
        request = self.factory.post('/crear-planificacion-citacion/', data)
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=empresa):
            response = views.CREAR_PLANIFICACION_CITACION(request)
        return {'status': response.status_code, **json.loads(response.content)}

    def test_cinco_citaciones_en_misma_carpeta_sin_consumir_sobrecupo(self):
        plan = PLANIFICACION.objects.get(pk=self.planificacion)
        antes = (
            PLANIFICACION.objects.count(), CALENDARIO.objects.count(),
            CITACION.objects.filter(PL_NID=plan).count(),
            CAMION_PATIO_NO_PLANIFICADO.objects.count(),
            plan.PL_NCANTIDADCUPOS, plan.PL_NSOBRECUPO, plan.PL_NCANTIDADSOBRECUPO,
        )
        resultado = self._guardar([self.datos] * 5, self.planificacion, sobrecupos=999)
        self.assertEqual(resultado['status'], 200, resultado)
        self.assertTrue(resultado['success'], resultado)
        self.assertEqual(len(resultado['citaciones']), 5)
        plan.refresh_from_db()
        self.assertEqual((
            PLANIFICACION.objects.count(), CALENDARIO.objects.count(),
            CITACION.objects.filter(PL_NID=plan).count(),
            CAMION_PATIO_NO_PLANIFICADO.objects.count(),
            plan.PL_NCANTIDADCUPOS, plan.PL_NSOBRECUPO, plan.PL_NCANTIDADSOBRECUPO,
        ), (antes[0], antes[1], antes[2] + 5, antes[3], antes[4], antes[5], antes[6]))
        self.assertEqual(plan.TOTAL_CITACIONES, 6)
        self.assertEqual(plan.TOTAL_CUPOS_DISPONIBLES, 0)
        self.assertEqual(plan.TOTAL_SOBRECUPOS_DISPONIBLES, 30)
        self.assertEqual(plan.TOTAL_SOBRECUPOS_USADOS, 0)
        nuevas = CITACION.objects.filter(pk__in=resultado['citaciones']).order_by('CI_NCUPO')
        self.assertEqual(list(nuevas.values_list('CI_NCUPO', flat=True)), [2, 3, 4, 5, 6])
        self.assertEqual(set(nuevas.values_list('PL_NID_id', flat=True)), {self.planificacion})
        self.assertEqual(set(nuevas.values_list('EP_NID_id', flat=True)), {2})
        self.assertEqual(set(nuevas.values_list('SC_NID_id', flat=True)), {self.secuencia.pk})
        self.assertEqual(set(nuevas.values_list('CI_BSOBRECUPO', flat=True)), {False})
        self.assertEqual(CITACION_ITEM.objects.filter(CI_NID__in=nuevas).count(), 5)
        request = self.factory.get(f'/pla_listone/{self.planificacion}', {'_empresa_id': '2'})
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'obtener_clientes_aceite', return_value=[]):
            html = views.PLANIFICACION_LISTONE(request, self.planificacion).content.decode()
        for citacion_id in resultado['citaciones']:
            self.assertIn(f'id="citacion-row-{citacion_id}"', html)

    def test_rechaza_carpeta_ajena_archivada_fecha_y_solicitud_patio(self):
        plan = PLANIFICACION.objects.get(pk=self.planificacion)
        inicial = CITACION.objects.count()
        self.assertEqual(self._guardar([self.datos], self.planificacion, empresa=1)['status'], 404)
        self.assertEqual(self._guardar([{**self.datos, 'fecha_llegada': '2026-10-06'}], self.planificacion)['status'], 400)
        self.assertEqual(self._guardar([self.datos], self.planificacion, solicitud=123)['status'], 400)
        plan.PL_BARCHIVADO = True
        plan.save(update_fields=['PL_BARCHIVADO'])
        self.assertEqual(self._guardar([self.datos], self.planificacion)['status'], 404)
        plan.PL_BARCHIVADO = False
        plan.PL_CTIPOCUPO = 'DESPACHO'
        plan.save(update_fields=['PL_BARCHIVADO', 'PL_CTIPOCUPO'])
        self.assertEqual(self._guardar([self.datos], self.planificacion)['status'], 404)
        self.assertEqual(CITACION.objects.count(), inicial)

    def test_modo_existente_exige_permiso_de_planificacion(self):
        sin_permiso = get_user_model().objects.create_user('consulta_sin_planificar', password='test-pass')
        request = self.factory.post('/crear-planificacion-citacion/', {
            'flujo': 'INGRESO_MERCADERIA',
            'planificacion_existente_id': str(self.planificacion),
            'citaciones_json': json.dumps([self.datos]),
        })
        request.user = sin_permiso
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'usuario_es_planificador', return_value=False), \
             patch.object(views, 'validar_perfiles_activos', return_value=False):
            response = views.CREAR_PLANIFICACION_CITACION(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CITACION.objects.filter(PL_NID_id=self.planificacion).count(), 1)

    def test_plantilla_comparte_modal_y_tabla_conserva_orden_exportable(self):
        addone = Path('apps/templates/home/PLANIFICACION/pla_addone.html').read_text(encoding='utf-8')
        detalle = Path('apps/templates/home/PLANIFICACION/pla_listone.html').read_text(encoding='utf-8')
        formulario = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_form.html').read_text(encoding='utf-8')
        scripts = Path('apps/templates/home/PLANIFICACION/_etapa0_recepcion_scripts.html').read_text(encoding='utf-8')
        self.assertIn('id="ModalCrearCitacion"', formulario)
        self.assertIn('planificacion_existente_id', addone)
        self.assertIn('_etapa0_recepcion_form.html', addone)
        self.assertIn('_etapa0_recepcion_form.html', detalle)
        self.assertIn('_etapa0_recepcion_scripts.html', addone)
        self.assertIn('_etapa0_recepcion_scripts.html', detalle)
        self.assertNotIn('<iframe', detalle)
        self.assertIn('planificacion_existente_id', scripts)
        encabezados = detalle.split('<table id="basic-btn1"', 1)[1].split('</thead>', 1)[0].split('{% else %}', 1)[1]
        self.assertLess(encabezados.index('<th>NUMERO CITACIÓN</th>'), encabezados.index('<th>PRODUCTO</th>'))
        self.assertLess(encabezados.index('<th>PRODUCTO</th>'), encabezados.index('<th>FECHA CITACION</th>'))
        fila = detalle.split('{% else %}\n                                                        <td>{{ object.0 }}</td>', 1)[1]
        self.assertLess(fila.index('{{ object.6 }}'), fila.index("{{ object.1|date:'d/m/Y' }}"))

    def test_detalle_y_etapa0_reutilizada_renderizan_planificacion_existente(self):
        request = self.factory.get(
            f'/pla_listone/{self.planificacion}',
            {'_empresa_id': '2', 'tipo': 'RECEPCION', 'flujo': 'INGRESO_MERCADERIA'},
        )
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'obtener_clientes_aceite', return_value=[]):
            response = views.PLANIFICACION_LISTONE(request, self.planificacion)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('Agregar citaciones', html)
        self.assertIn('id="ModalCrearCitacion"', html)
        self.assertNotIn('<iframe', html)
        self.assertNotIn('>Opciones<', html)

        request = self.factory.get('/pla_addone/', {
            '_empresa_id': '2', 'tipo': 'RECEPCION', 'flujo': 'INGRESO_MERCADERIA',
            'planificacion_existente_id': self.planificacion, 'modal': 'recepcion',
        })
        request.user = self.usuario
        with patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, 'obtener_clientes_aceite', return_value=[]), \
             patch.object(views, 'asegurar_flujos_recepcion_etapa_0', return_value=[self.secuencia]), \
             patch.object(views, 'asegurar_flujos_despacho_etapa_0'):
            response = views.PLANIFICACION_ADDONE(request)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'Agregar citaciones - Planificación #{self.planificacion}', html)
        self.assertIn('id="ModalCrearCitacion"', html)
        self.assertIn('value="2026-10-05"', html)
