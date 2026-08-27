from concurrent.futures import ThreadPoolExecutor
from datetime import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.general_postgres import get_list_citaciones_proforma
from apps.home.models import (
    CALENDARIO,
    CAMION_PATIO,
    CITACION,
    CITACION_PROFORMA,
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    PLANIFICACION,
    PROFORMA,
    SECUENCIA,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
    VISTA,
)
from apps.home.services.proforma_service import (
    PERMISO_INICIAR_PROFORMA,
    PERMISO_PROFORMA_CITACIONES,
    evaluar_inicio_proforma,
    iniciar_proforma,
)


class IniciarProformaFixtureMixin:
    def crear_datos_base(self):
        User = get_user_model()
        self.token = uuid4().hex[:10]
        self.user = User.objects.create_user(
            username=f'pro_cit_{self.token}',
            password='secreto-prueba',
        )
        self.empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Empresa prueba',
            EP_CRUT=f'RUT-{self.token}',
            EP_CBASEDATOS='db_test',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )
        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=self.empresa)

        self.perfil = PERFIL.objects.create(
            US_NID=self.user,
            PR_CCODIGO='PRO_CIT',
            PR_CNOMBRE='Proforma Citaciones',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=self.user,
            PR_NID=self.perfil,
            PE_BHABILITADO=True,
        )
        for codigo in (PERMISO_INICIAR_PROFORMA, PERMISO_PROFORMA_CITACIONES):
            vista = VISTA.objects.create(
                US_NID=self.user,
                VI_CCODIGO=codigo,
                VI_CNOMBRE=codigo,
                VI_BHABILITADO=True,
            )
            PERMISO.objects.create(
                US_NID=self.user,
                PR_NID=self.perfil,
                VI_NID=vista,
                PE_BHABILITADO=True,
            )

        ahora = timezone.now()
        calendario = CALENDARIO.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CA_CNOMBRE='Calendario prueba',
            CA_FHORA_APERTURA=time(8, 0),
            CA_FHORA_CIERRE=time(18, 0),
            CA_NDIA=ahora.day,
            CA_NMES=ahora.month,
            CA_NANO=ahora.year,
            CA_NCANTIDADCUPOS=10,
        )
        planificacion = PLANIFICACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=ahora,
            PL_FFECHAINICIO=ahora,
            PL_NCANTIDADCUPOS=10,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO=f'SEQ-{self.token}',
            SE_CNOMBRE='Secuencia prueba',
            SE_BHABILITADO=True,
        )
        self.citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=planificacion,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=ahora,
            CI_FFECHACITACION=ahora,
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='TERMINADO',
            CI_BHABILITADO=True,
            CI_BCONFORME=False,
            # Este dato legacy no interviene en la elegibilidad.
            CI_CTIPO_FLETE='Flete Cliente',
        )
        self.camion = self.crear_camion(self.citacion, 'TERRAMAR')

    def crear_camion(self, citacion, transporte, empresa=None, estado=None, patente='TEST01'):
        return CAMION_PATIO.objects.create(
            EP_NID=empresa or citacion.EP_NID,
            CI_NID=citacion,
            transporte_a_cargo=transporte,
            CPA_CPATENTE=patente,
            CPA_CNOMBRE_CONDUCTOR='Conductor prueba',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=estado or CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.user,
            US_ASOCIA_ID=self.user,
        )


class IniciarProformaTests(IniciarProformaFixtureMixin, TransactionTestCase):
    reset_sequences = True
    def setUp(self):
        self.crear_datos_base()
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = 'TRANSPORTES SAEZ LIMITADA'
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL='TRANSPORTES SAEZ LIMITADA',
            SN_CRUT='77061844-4',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        self.citacion.PRO_NID = self.transporte
        self.citacion.save(update_fields=['PRO_NID'])
        self.client.force_login(self.user)

    def test_post_materializa_borrador_y_no_deja_estado_intermedio(self):
        url = reverse('citacion_iniciar_proforma', args=[self.citacion.pk])

        respuesta = self.client.post(url)

        proforma = PROFORMA.objects.get()
        self.assertRedirects(
            respuesta,
            reverse('proforma_listone', args=[proforma.pk]),
            fetch_redirect_response=False,
        )
        self.citacion.refresh_from_db()
        self.assertTrue(self.citacion.CI_BCONFORME)
        self.assertEqual(self.citacion.PRO_NID, self.transporte)
        self.assertEqual(CITACION_PROFORMA.objects.get(
            CI_NID=self.citacion
        ).PRO_NID, proforma)
        log = SYSLOGGER.objects.get(LOG_COPERACION='BORRADOR_MENSUAL')
        self.assertEqual(log.US_NID, self.user)
        self.assertEqual(log.EP_NID, self.empresa)

        segunda_respuesta = self.client.post(url)
        self.assertEqual(segunda_respuesta.status_code, 400)
        self.assertEqual(PROFORMA.objects.count(), 1)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 1)

    def test_nueva_ruta_rechaza_get_y_ruta_legacy_no_muta(self):
        nueva = reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        legacy = reverse('cit_entrega_conforme', args=[self.citacion.pk])

        self.assertEqual(self.client.get(nueva).status_code, 405)
        self.assertEqual(self.client.get(legacy).status_code, 410)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertFalse(
            SYSLOGGER.objects.filter(LOG_COPERACION='INICIAR_PROFORMA').exists()
        )

    def test_transporte_cliente_es_rechazado_aunque_flete_legacy_diga_otro(self):
        self.camion.transporte_a_cargo = 'CLIENTE'
        self.camion.save(update_fields=['transporte_a_cargo'])
        self.citacion.CI_CTIPO_FLETE = 'Flete Terramar'
        self.citacion.save(update_fields=['CI_CTIPO_FLETE'])

        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertFalse(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'TRANSPORTE_CLIENTE')

    def test_sin_camion_asociado_es_rechazado(self):
        self.camion.CPA_CESTADO = CAMION_PATIO.ESTADO_CANCELADO
        self.camion.save(update_fields=['CPA_CESTADO'])

        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertFalse(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'SIN_CAMION_PATIO')

    def test_multiples_camiones_asociados_son_rechazados(self):
        self.crear_camion(self.citacion, 'TERRAMAR', patente='TEST02')

        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertFalse(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'MULTIPLES_CAMIONES_PATIO')

    def test_camion_de_otra_empresa_es_rechazado(self):
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Otra empresa',
            EP_CRUT='77.000.000-0',
            EP_CBASEDATOS='db_test_2',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )
        self.camion.EP_NID = otra_empresa
        self.camion.save(update_fields=['EP_NID'])

        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertFalse(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'EMPRESA_INCONSISTENTE')

    def test_estado_habilitacion_perfil_y_empresa_se_validan(self):
        self.citacion.CI_CESTADO = 'EN PROCESO'
        self.citacion.save(update_fields=['CI_CESTADO'])
        self.assertEqual(
            evaluar_inicio_proforma(self.citacion, self.user)['codigo'],
            'ESTADO_INVALIDO',
        )

        self.citacion.CI_CESTADO = 'TERMINADO'
        self.citacion.CI_BHABILITADO = False
        self.citacion.save(update_fields=['CI_CESTADO', 'CI_BHABILITADO'])
        self.assertEqual(
            evaluar_inicio_proforma(self.citacion, self.user)['codigo'],
            'CITACION_INHABILITADA',
        )

        self.citacion.CI_BHABILITADO = True
        self.citacion.save(update_fields=['CI_BHABILITADO'])
        PERFIL_USUARIO.objects.filter(US_NID=self.user).update(PE_BHABILITADO=False)
        self.assertEqual(
            evaluar_inicio_proforma(self.citacion, self.user)['codigo'],
            'SIN_PERMISO',
        )

        PERFIL_USUARIO.objects.filter(US_NID=self.user).update(PE_BHABILITADO=True)
        USERS_EMPRESA.objects.filter(US_NID=self.user).delete()
        self.assertEqual(
            evaluar_inicio_proforma(self.citacion, self.user)['codigo'],
            'SIN_EMPRESA',
        )

    def test_elegible_expone_bandera_visual_antes_del_post(self):
        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertTrue(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'ELEGIBLE')

    def test_post_cliente_es_rechazado_y_no_modifica(self):
        self.camion.transporte_a_cargo = 'CLIENTE'
        self.camion.save(update_fields=['transporte_a_cargo'])

        respuesta = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        )

        self.assertEqual(respuesta.status_code, 400)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertFalse(
            SYSLOGGER.objects.filter(
                LOG_COPERACION='INICIAR_PROFORMA',
                LOG_CADD1=f'Citacion: {self.citacion.pk}',
            ).exists()
        )

    def test_post_en_proceso_es_rechazado_y_no_modifica(self):
        self.citacion.CI_CESTADO = 'EN PROCESO'
        self.citacion.save(update_fields=['CI_CESTADO'])

        respuesta = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        )

        self.assertEqual(respuesta.status_code, 400)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)

    def test_sin_pro_cit_backend_403_y_menu_oculto(self):
        PERFIL_USUARIO.objects.filter(US_NID=self.user).update(
            PE_BHABILITADO=False
        )

        respuesta = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        )
        request = RequestFactory().get('/')
        request.user = self.user
        html = render_to_string(
            'includes/component-navbar-inner.html',
            {'request': request},
            request=request,
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertNotIn('>Lista de Proformas</a>', html)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)

    def test_pro_cit_sin_empresa_backend_403_y_no_modifica(self):
        USERS_EMPRESA.objects.filter(US_NID=self.user).delete()

        respuesta = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        )

        self.assertEqual(respuesta.status_code, 403)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        request = RequestFactory().get('/')
        request.user = self.user
        html = render_to_string(
            'includes/component-navbar-inner.html',
            {'request': request},
            request=request,
        )
        self.assertNotIn('>Lista de Proformas</a>', html)


    def test_asociacion_existente_es_incompatible(self):
        proforma = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            PRO_CESTADO='BORRADOR',
            PRO_NSUBTOTAL=Decimal('0'),
            PRO_NIVA=Decimal('0'),
            PRO_NTOTAL=Decimal('0'),
            PRO_NINGRESO=Decimal('0'),
            PRO_NDESCUENTO=Decimal('0'),
            PRO_FFECHAREGISTRO=timezone.now(),
            PRO_FFECHAEMISION=timezone.now(),
        )
        CITACION_PROFORMA.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            PRO_NID=proforma,
            CIP_NSUBTOTAL=Decimal('0'),
        )

        evaluacion = evaluar_inicio_proforma(self.citacion, self.user)

        self.assertFalse(evaluacion['elegible'])
        self.assertEqual(evaluacion['codigo'], 'ASOCIACION_INCOMPATIBLE')

    def test_menu_pro_cit_expone_solo_citaciones(self):
        request = RequestFactory().get('/')
        request.user = self.user

        html = render_to_string(
            'includes/component-navbar-inner.html',
            {'request': request},
            request=request,
        )

        self.assertIn('>Lista de Proformas</a>', html)
        self.assertNotIn('>Extras</a>', html)
        self.assertNotIn('>Manual</a>', html)
        self.assertNotIn('>Borradores</a>', html)

    def test_template_detalle_usa_formulario_post_csrf_y_estado_iniciado(self):
        ruta = (
            Path(settings.BASE_DIR).parent
            / 'apps'
            / 'templates'
            / 'home'
            / 'CITACION'
            / 'cit_listone.html'
        )
        contenido = ruta.read_text(encoding='utf-8')

        self.assertIn('action="{% url \'citacion_iniciar_proforma\' citacion.pk %}"', contenido)
        self.assertIn('method="POST"', contenido)
        self.assertIn('{% csrf_token %}', contenido)
        self.assertIn('INICIAR PROFORMA', contenido)
        self.assertIn('PROFORMA INICIADA', contenido)
        self.assertNotIn("url 'cit_entrega_conforme'", contenido)


class ConsultaYConcurrenciaTests(IniciarProformaFixtureMixin, TransactionTestCase):

    def setUp(self):
        self.crear_datos_base()

    def test_citacion_iniciada_aparece_en_consulta_y_no_crea_borrador(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La consulta legacy usa SQL específico de PostgreSQL.')

        _, resultado = iniciar_proforma(self.citacion.pk, self.user)
        filas = get_list_citaciones_proforma(
            proveedor=None,
            fecha_desde=None,
            fecha_hasta=None,
            tipo_citacion='RECEPCION',
            empresa=self.empresa.pk,
        )

        self.assertEqual(resultado['codigo'], 'INICIADA')
        self.assertIn(self.citacion.pk, [fila[0] for fila in filas])
        self.assertEqual(PROFORMA.objects.count(), 0)
        self.assertEqual(CITACION_PROFORMA.objects.count(), 0)

        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Empresa sin acceso',
            EP_CRUT='78.000.000-0',
            EP_CBASEDATOS='db_test_3',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )
        filas_otra_empresa = get_list_citaciones_proforma(
            None, None, None, 'RECEPCION', otra_empresa.pk
        )
        self.assertNotIn(self.citacion.pk, [fila[0] for fila in filas_otra_empresa])

    def test_dos_intentos_concurrentes_generan_un_solo_evento(self):
        if connection.vendor != 'postgresql':
            self.skipTest('select_for_update se valida con PostgreSQL.')

        def ejecutar():
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=self.user.pk)
                _, resultado = iniciar_proforma(self.citacion.pk, usuario)
                return resultado['codigo']
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            codigos = list(executor.map(lambda _: ejecutar(), range(2)))

        self.assertCountEqual(codigos, ['INICIADA', 'YA_INICIADA'])
        self.citacion.refresh_from_db()
        self.assertTrue(self.citacion.CI_BCONFORME)
        self.assertEqual(
            SYSLOGGER.objects.filter(LOG_COPERACION='INICIAR_PROFORMA').count(),
            1,
        )
        self.assertEqual(PROFORMA.objects.count(), 0)


class ConfigurarPerfilProCitTests(TestCase):
    def test_comando_es_idempotente_y_no_crea_caraneda(self):
        actor = get_user_model().objects.create_user(
            username=f'actor_configuracion_{uuid4().hex[:10]}',
            password='secreto-prueba',
        )

        call_command('configurar_perfil_pro_cit', actor_username=actor.username)
        call_command('configurar_perfil_pro_cit', actor_username=actor.username)

        perfil = PERFIL.objects.get(PR_CCODIGO='PRO_CIT')
        self.assertTrue(perfil.PR_BHABILITADO)
        self.assertEqual(PERFIL.objects.filter(PR_CCODIGO='PRO_CIT').count(), 1)
        self.assertEqual(
            PERMISO.objects.filter(
                PR_NID=perfil,
                PE_BHABILITADO=True,
                VI_NID__VI_CCODIGO__in=[
                    PERMISO_INICIAR_PROFORMA,
                    PERMISO_PROFORMA_CITACIONES,
                ],
            ).count(),
            2,
        )
        self.assertFalse(
            get_user_model().objects.filter(username__iexact='CARANEDA').exists()
        )
