from django.db import connection
from django.template.loader import get_template, render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.home.general_postgres import (
    get_list_citaciones_proforma,
    get_list_citaciones_terminadas_proforma,
)
from apps.home.models import (
    CAMION_PATIO,
    CITACION_PROFORMA,
    EMPRESA,
    PERFIL_USUARIO,
    PROFORMA,
    SYSLOGGER,
)
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


class CitacionesTerminadasProformaTests(IniciarProformaFixtureMixin, TestCase):
    def setUp(self):
        self.crear_datos_base()
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = 'TRANSPORTES SAEZ LIMITADA'
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        self.client.force_login(self.user)

    def _requiere_postgresql(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Los selectores usan SQL específico de PostgreSQL.')

    def _ids_pendientes(self, empresa=None):
        filas = get_list_citaciones_terminadas_proforma(
            fecha_desde=None,
            fecha_hasta=None,
            tipo_citacion=None,
            empresa=empresa or self.empresa.pk,
        )
        return [fila[0] for fila in filas or []]

    def _ids_iniciadas(self):
        filas = get_list_citaciones_proforma(
            proveedor=None,
            fecha_desde=None,
            fecha_hasta=None,
            tipo_citacion=None,
            empresa=self.empresa.pk,
        )
        return [fila[0] for fila in filas or []]

    def test_menu_pro_cit_muestra_dos_colas_antes_de_consultas(self):
        request = RequestFactory().get('/')
        request.user = self.user

        html = render_to_string(
            'includes/component-navbar-inner.html',
            {'request': request},
            request=request,
        )

        self.assertIn('Citaciones terminadas', html)
        self.assertIn('>Citaciones</a>', html)
        self.assertLess(html.index('>Proformas</span>'), html.index('<label>Consultas</label>'))
        self.assertNotIn('>Extras</a>', html)
        self.assertNotIn('>Manual</a>', html)
        self.assertNotIn('>Borradores</a>', html)

    def test_usuario_sin_pro_cit_no_ve_menu_ni_accede_por_url(self):
        PERFIL_USUARIO.objects.filter(US_NID=self.user).update(
            PE_BHABILITADO=False,
        )
        request = RequestFactory().get('/')
        request.user = self.user

        html = render_to_string(
            'includes/component-navbar-inner.html',
            {'request': request},
            request=request,
        )
        respuesta = self.client.get(reverse('proforma_citaciones_terminadas'))

        self.assertNotIn('Citaciones terminadas', html)
        self.assertEqual(respuesta.status_code, 403)

    def test_pendiente_terramar_aparece_y_luego_pasa_a_iniciadas(self):
        self._requiere_postgresql()

        respuesta_lista = self.client.get(
            reverse('proforma_citaciones_terminadas')
        )

        self.assertEqual(respuesta_lista.status_code, 200)
        self.assertContains(respuesta_lista, str(self.citacion.pk))
        self.assertContains(respuesta_lista, 'CONTINUAR CON BORRADOR')
        self.assertContains(respuesta_lista, 'citacion_ids[]')
        self.assertIn(self.citacion.pk, self._ids_pendientes())
        self.assertNotIn(self.citacion.pk, self._ids_iniciadas())

        respuesta_inicio = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk]),
            {'return_to': 'proforma_citaciones_terminadas'},
        )

        self.assertRedirects(
            respuesta_inicio,
            reverse('proforma_citaciones_terminadas'),
            fetch_redirect_response=False,
        )
        self.citacion.refresh_from_db()
        self.assertTrue(self.citacion.CI_BCONFORME)
        self.assertNotIn(self.citacion.pk, self._ids_pendientes())
        self.assertIn(self.citacion.pk, self._ids_iniciadas())
        self.assertEqual(PROFORMA.objects.count(), 0)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 0)

    def test_inicio_desde_lista_sigue_siendo_idempotente(self):
        url = reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        datos = {'return_to': 'proforma_citaciones_terminadas'}

        primera = self.client.post(url, datos)
        segunda = self.client.post(url, datos)

        self.assertEqual(primera.status_code, 302)
        self.assertEqual(segunda.status_code, 302)
        self.assertEqual(
            SYSLOGGER.objects.filter(
                LOG_COPERACION='INICIAR_PROFORMA',
            ).count(),
            1,
        )
        self.assertEqual(PROFORMA.objects.count(), 0)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 0)

    def test_transporte_cliente_y_estado_en_proceso_no_aparecen(self):
        self._requiere_postgresql()

        self.camion.transporte_a_cargo = 'CLIENTE'
        self.camion.save(update_fields=['transporte_a_cargo'])
        self.assertNotIn(self.citacion.pk, self._ids_pendientes())

        self.camion.transporte_a_cargo = 'TERRAMAR'
        self.camion.save(update_fields=['transporte_a_cargo'])
        self.citacion.CI_CESTADO = 'EN PROCESO'
        self.citacion.save(update_fields=['CI_CESTADO'])
        self.assertNotIn(self.citacion.pk, self._ids_pendientes())

    def test_empresa_no_asignada_es_rechazada_y_aislada(self):
        self._requiere_postgresql()
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Empresa no asignada',
            EP_CRUT=f'OTRA-{self.token}',
            EP_CBASEDATOS='db_otra',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )

        respuesta = self.client.post(
            reverse('proforma_citaciones_terminadas'),
            {'empresa': otra_empresa.pk},
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertNotIn(self.citacion.pk, self._ids_pendientes(otra_empresa.pk))

    def test_selector_no_usa_flete_legacy_y_exige_un_camion_asociado(self):
        self._requiere_postgresql()

        self.assertEqual(self.citacion.CI_CTIPO_FLETE, 'Flete Cliente')
        self.assertIn(self.citacion.pk, self._ids_pendientes())

        self.crear_camion(self.citacion, 'TERRAMAR', patente='TEST02')
        self.assertNotIn(self.citacion.pk, self._ids_pendientes())

        CAMION_PATIO.objects.filter(
            CI_NID=self.citacion,
            CPA_CPATENTE='TEST02',
        ).delete()
        self.assertIn(self.citacion.pk, self._ids_pendientes())

    def test_detalle_individual_conserva_iniciar_proforma(self):
        contenido = get_template('home/CITACION/cit_listone.html').template.source

        self.assertIn('INICIAR PROFORMA', contenido)
        self.assertIn("url 'citacion_iniciar_proforma'", contenido)
