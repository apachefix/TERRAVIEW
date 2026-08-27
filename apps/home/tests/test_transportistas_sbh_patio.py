import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.home import views
from apps.home.models import CONDUCTOR, EMPRESA, SOCIONEGOCIO


class TransportistasSbhPatioTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.terramar = self._empresa(1, 'Terramar')
        self.sbh = self._empresa(2, 'SBH')
        self.usuario = User.objects.create_superuser(
            username='transportistas_sbh', email='transportistas@sbh.test', password='test',
        )
        self.sbh_valido = self._transporte(self.sbh, 'Transportista SBH válido', '76111111-1')
        self.terramar_valido = self._transporte(self.terramar, 'Transportista Terramar', '76222222-2')
        self.sbh_inhabilitado = self._transporte(
            self.sbh, 'Transportista SBH inhabilitado', '76333333-3', habilitado=False,
        )
        self.sbh_cliente = self._transporte(
            self.sbh, 'Cliente SBH', '76444444-4', tipo='C',
        )
        self.puesto_ficticio = self._transporte(
            self.sbh, 'Puesto en planta', '55555555-5',
        )

    def _empresa(self, pk, nombre):
        empresa, _ = EMPRESA.objects.get_or_create(
            pk=pk,
            defaults={
                'EP_CRAZONSOCIAL': nombre,
                'EP_CRUT': f'7600000{pk}-{pk}',
                'EP_CBASEDATOS': f'db{pk}',
                'EP_CUSUARIOSBD': 'user',
                'EP_CPORT': '5432',
            },
        )
        return empresa

    def _transporte(self, empresa, nombre, rut, *, habilitado=True, tipo='S'):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa,
            SN_CRAZONSOCIAL=nombre,
            SN_CRUT=rut,
            SN_CTIPO=tipo,
            SN_BHABILITADO=habilitado,
        )

    def test_queryset_sbh_usa_solo_maestro_habilitado_de_sbh(self):
        ids = set(
            views.queryset_transportistas_validos_ingreso_camion(2)
            .filter(pk__in=[
                self.sbh_valido.pk, self.terramar_valido.pk,
                self.sbh_inhabilitado.pk, self.sbh_cliente.pk, self.puesto_ficticio.pk,
            ])
            .values_list('pk', flat=True)
        )
        self.assertIn(self.sbh_valido.pk, ids)
        self.assertNotIn(self.terramar_valido.pk, ids)
        self.assertNotIn(self.sbh_inhabilitado.pk, ids)
        self.assertNotIn(self.sbh_cliente.pk, ids)
        self.assertNotIn(self.puesto_ficticio.pk, ids)

    def test_ajax_sbh_no_expone_transportistas_ajenos(self):
        request = self.factory.get(
            '/ajax/transportistas-ingreso-camion/', {'empresa_id': '2'},
        )
        request.user = self.usuario
        request.session = {}
        payload = json.loads(views.AJAX_TRANSPORTISTAS_INGRESO_CAMION(request).content)
        ids = {item['socionegocio_id'] for item in payload['results']}
        self.assertIn(self.sbh_valido.pk, ids)
        self.assertNotIn(self.terramar_valido.pk, ids)
        self.assertNotIn(self.sbh_inhabilitado.pk, ids)
        self.assertNotIn(self.sbh_cliente.pk, ids)

    def test_post_sbh_manipulado_con_transportista_de_otra_empresa_se_rechaza(self):
        request = self.factory.post('/camiones-patio/registrar/', {
            'transporte_a_cargo': 'TERRAMAR',
            'transportista': self.terramar_valido.SN_CRAZONSOCIAL,
            'transportista_id': str(self.terramar_valido.pk),
        })
        request.user = self.usuario
        error = MagicMock()
        render = MagicMock(return_value=HttpResponse(status=400))
        with patch.object(views, 'usuario_puede_registrar_camion_patio', return_value=True), \
             patch.object(views, 'Verificar_empresa', return_value=2), \
             patch.object(views, '_validar_carga_planificada_patio', return_value=(None, None)), \
             patch.object(views, '_render_camiones_patio_registrar', render), \
             patch.object(views.messages, 'error', error), \
             patch.object(views.CAMION_PATIO.objects, 'create') as crear_camion:
            response = views.CAMIONES_PATIO_REGISTRAR(request)
        self.assertEqual(response.status_code, 400)
        crear_camion.assert_not_called()
        self.assertEqual(
            error.call_args.args[1],
            'El transportista seleccionado no pertenece al maestro habilitado de SBH.',
        )

    def test_sbh_conductores_son_globales_en_recepcion_y_despacho(self):
        otro_transportista = self._transporte(self.sbh, 'Otro transportista SBH', '76555555-5')
        conductor_ep1 = CONDUCTOR.objects.create(
            EP_NID=self.terramar,
            SN_NID=otro_transportista,
            US_NID=self.usuario,
            CON_CNOMBRE='Conductor global EP1',
            CON_CAPELLIDO='Prueba',
            CON_CRUT='16666666-6',
            CON_CEMAIL='ep1@sbh.test',
            CON_CTELEFONO='912345678',
            CON_BHABILITADO=True,
        )
        conductor_ep2 = CONDUCTOR.objects.create(
            EP_NID=self.sbh,
            SN_NID=otro_transportista,
            US_NID=self.usuario,
            CON_CNOMBRE='Conductor global EP2',
            CON_CAPELLIDO='Prueba',
            CON_CRUT='17777777-7',
            CON_CEMAIL='ep2@sbh.test',
            CON_CTELEFONO='912345679',
            CON_BHABILITADO=True,
        )
        conductor_inhabilitado = CONDUCTOR.objects.create(
            EP_NID=self.terramar,
            SN_NID=otro_transportista,
            US_NID=self.usuario,
            CON_CNOMBRE='Conductor inhabilitado',
            CON_CAPELLIDO='Prueba',
            CON_CRUT='18888888-8',
            CON_CEMAIL='off@sbh.test',
            CON_CTELEFONO='912345670',
            CON_BHABILITADO=False,
        )

        def consultar(transportista, es_despacho):
            request = self.factory.get('/ajax/conductores-ingreso-camion/', {
                'empresa_id': '2', 'es_despacho': es_despacho,
                'transportista_id': str(transportista.pk), 'q': 'global',
            })
            request.user = self.usuario
            request.session = {}
            payload = json.loads(views.AJAX_CONDUCTORES_INGRESO_CAMION(request).content)
            return {item['conductor_id'] for item in payload['results']}

        con_pascal = consultar(self.sbh_valido, '0')
        con_otro = consultar(otro_transportista, '0')
        con_despacho = consultar(self.sbh_valido, '1')
        self.assertEqual(con_pascal, con_otro)
        self.assertEqual(con_pascal, con_despacho)
        self.assertIn(conductor_ep1.pk, con_pascal)
        self.assertIn(conductor_ep2.pk, con_pascal)
        self.assertNotIn(conductor_inhabilitado.pk, con_pascal)
        conductor_ep1.refresh_from_db()
        self.assertEqual(conductor_ep1.EP_NID_id, self.terramar.pk)
        self.assertEqual(conductor_ep1.SN_NID_id, otro_transportista.pk)

    def test_terramar_conserva_el_query_historico_actual(self):
        CONDUCTOR.objects.create(
            EP_NID=self.terramar,
            SN_NID=self.sbh_valido,
            US_NID=self.usuario,
            CON_CNOMBRE='Histórico Terramar',
            CON_CAPELLIDO='Prueba',
            CON_CRUT='17777777-7',
            CON_CEMAIL='historico@terramar.test',
            CON_CTELEFONO='912345679',
            CON_BHABILITADO=True,
        )
        ids = set(
            views.queryset_transportistas_validos_ingreso_camion(1)
            .values_list('pk', flat=True)
        )
        self.assertIn(self.terramar_valido.pk, ids)
        self.assertIn(self.sbh_valido.pk, ids)
