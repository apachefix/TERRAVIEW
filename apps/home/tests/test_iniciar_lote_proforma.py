from django.template.loader import get_template
from django.test import Client, TestCase
from django.urls import reverse

from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_PROFORMA,
    EMPRESA,
    PROFORMA,
    SYSLOGGER,
    USERS_EMPRESA,
)
from apps.home.services.proforma_service import iniciar_lote_proforma
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


TRANSPORTISTA = 'TRANSPORTES SAEZ LIMITADA'


class IniciarLoteProformaTests(IniciarProformaFixtureMixin, TestCase):
    def setUp(self):
        self.crear_datos_base()
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = TRANSPORTISTA
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        self.client.force_login(self.user)

    def crear_citacion(
        self,
        transportista=TRANSPORTISTA,
        empresa=None,
        estado='TERMINADO',
        patente='LOTE02',
    ):
        empresa = empresa or self.empresa
        citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=empresa,
            PL_NID=self.citacion.PL_NID,
            SC_NID=self.citacion.SC_NID,
            CI_FFECHAREGISTRO=self.citacion.CI_FFECHAREGISTRO,
            CI_FFECHACITACION=self.citacion.CI_FFECHACITACION,
            CI_NCUPO=CITACION.objects.count() + 1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO=estado,
            CI_BHABILITADO=True,
            CI_BCONFORME=False,
            CI_CTIPO_FLETE='Flete Cliente',
        )
        camion = self.crear_camion(
            citacion,
            'TERRAMAR',
            empresa=empresa,
            patente=patente,
        )
        camion.CPA_CTRANSPORTISTA_DECLARADO = transportista
        camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        return citacion

    def iniciar(self, ids, empresa=None, transportista=TRANSPORTISTA):
        return iniciar_lote_proforma(
            citacion_ids=ids,
            user=self.user,
            empresa_id=(empresa or self.empresa).pk,
            transportista_esperado=transportista,
        )

    def test_lote_vacio_es_rechazado(self):
        resultado = self.iniciar([])

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'SIN_CITACIONES')

    def test_lote_correcto_es_atomico_idempotente_y_no_crea_proforma(self):
        segunda = self.crear_citacion(patente='LOTE03')

        primera_ejecucion = self.iniciar(
            [self.citacion.pk, segunda.pk, segunda.pk]
        )
        segunda_ejecucion = self.iniciar([segunda.pk, self.citacion.pk])

        self.assertTrue(primera_ejecucion['ok'])
        self.assertEqual(primera_ejecucion['codigo'], 'LOTE_INICIADO')
        self.assertTrue(segunda_ejecucion['ok'])
        self.assertEqual(segunda_ejecucion['codigo'], 'LOTE_YA_INICIADO')
        self.assertFalse(
            CITACION.objects.filter(
                pk__in=[self.citacion.pk, segunda.pk],
                CI_BCONFORME=False,
            ).exists()
        )
        self.assertEqual(
            SYSLOGGER.objects.filter(
                LOG_COPERACION='INICIAR_PROFORMA_LOTE'
            ).count(),
            2,
        )
        self.assertEqual(PROFORMA.objects.count(), 0)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 0)

    def test_transportistas_mixtos_rechazan_todo_el_lote(self):
        segunda = self.crear_citacion(
            transportista='LOGISTICA & TRANSPORTE PASCAL LTDA',
            patente='LOTE04',
        )

        resultado = self.iniciar([self.citacion.pk, segunda.pk])

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'TRANSPORTISTAS_MIXTOS')
        self.assertFalse(
            CITACION.objects.filter(
                pk__in=[self.citacion.pk, segunda.pk],
                CI_BCONFORME=True,
            ).exists()
        )
        self.assertFalse(
            SYSLOGGER.objects.filter(
                LOG_COPERACION='INICIAR_PROFORMA_LOTE'
            ).exists()
        )

    def test_empresas_mixtas_rechazan_todo_el_lote(self):
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Otra empresa lote',
            EP_CRUT=f'LOTE-{self.token}',
            EP_CBASEDATOS='db_lote',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )
        USERS_EMPRESA.objects.create(
            US_NID=self.user,
            EP_NID=otra_empresa,
        )
        segunda = self.crear_citacion(
            empresa=otra_empresa,
            patente='LOTE05',
        )

        resultado = self.iniciar([self.citacion.pk, segunda.pk])

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'EMPRESAS_MIXTAS')
        self.assertFalse(
            CITACION.objects.filter(
                pk__in=[self.citacion.pk, segunda.pk],
                CI_BCONFORME=True,
            ).exists()
        )

    def test_cliente_es_rechazado(self):
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = ' CLIENTE '
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])

        resultado = self.iniciar(
            [self.citacion.pk],
            transportista='CLIENTE',
        )

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'TRANSPORTISTA_INVALIDO')
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)

    def test_una_citacion_invalida_no_modifica_las_validas(self):
        segunda = self.crear_citacion(
            estado='EN PROCESO',
            patente='LOTE06',
        )

        resultado = self.iniciar([self.citacion.pk, segunda.pk])

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'ESTADO_INVALIDO')
        self.assertFalse(
            CITACION.objects.filter(
                pk__in=[self.citacion.pk, segunda.pk],
                CI_BCONFORME=True,
            ).exists()
        )

    def test_asociacion_con_proforma_rechaza_el_lote(self):
        proforma = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            PRO_CESTADO='BORRADOR',
            PRO_NSUBTOTAL=0,
            PRO_NIVA=0,
            PRO_NTOTAL=0,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
        )
        CITACION_PROFORMA.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            PRO_NID=proforma,
            CIP_NSUBTOTAL=0,
        )

        resultado = self.iniciar([self.citacion.pk])

        self.assertFalse(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'ASOCIACION_INCOMPATIBLE')
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)

    def test_endpoint_es_post_csrf_y_redirige_a_citaciones(self):
        url = reverse('proforma_citaciones_terminadas_iniciar_lote')

        cliente_csrf = Client(enforce_csrf_checks=True)
        cliente_csrf.force_login(self.user)
        sin_csrf = cliente_csrf.post(
            url,
            {
                'citacion_ids[]': [self.citacion.pk],
                'empresa_id': self.empresa.pk,
                'transportista_normalizado': TRANSPORTISTA,
            },
        )

        self.assertEqual(sin_csrf.status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)
        respuesta = self.client.post(
            url,
            {
                'citacion_ids[]': [self.citacion.pk],
                'empresa_id': self.empresa.pk,
                'transportista_normalizado': TRANSPORTISTA,
            },
        )

        self.assertRedirects(
            respuesta,
            reverse('prof_listall'),
            fetch_redirect_response=False,
        )
        self.citacion.refresh_from_db()
        self.assertTrue(self.citacion.CI_BCONFORME)
        self.assertEqual(PROFORMA.objects.count(), 0)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 0)

    def test_template_no_tiene_proveedor_y_prepara_seleccion_multiple(self):
        contenido = get_template(
            'home/PROFORMA/proforma_citaciones_terminadas.html'
        ).template.source

        self.assertNotIn('name="proveedor"', contenido)
        self.assertNotIn('selectedproveedor', contenido)
        self.assertIn('name="buscar_transportista"', contenido)
        self.assertIn('name="citacion_ids[]"', contenido)
        self.assertIn('id="seleccionar-todas-visibles"', contenido)
        self.assertIn('id="limpiar-seleccion"', contenido)
        self.assertIn('CONTINUAR CON BORRADOR', contenido)
        self.assertIn('mismoGrupo', contenido)
