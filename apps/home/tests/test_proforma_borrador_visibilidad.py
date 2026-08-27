from datetime import datetime
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.general_postgres import get_list_citaciones_terminadas_proforma
from apps.home.models import (
    CITACION,
    CITACION_PROFORMA,
    EMPRESA,
    PERFIL,
    PROFORMA,
    REGION,
    PROVINCIA,
    COMUNA,
    RUTA,
    TARIFA_GLOBAL,
    SOCIONEGOCIO,
    USERS_EMPRESA,
)
from apps.home.services.proforma_mensual import periodo_citacion
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


TRANSPORTE = 'TRANSPORTES SAEZ LIMITADA'


class ProformaBorradorVisibilidadTests(
    IniciarProformaFixtureMixin, TransactionTestCase
):
    reset_sequences = True

    def setUp(self):
        self.crear_datos_base()
        PERFIL.objects.filter(pk=self.perfil.pk).update(
            PR_CCODIGO='CONTROL_FLOTA',
            PR_CNOMBRE='Control Flota',
        )
        self.empresa.EP_CRAZONSOCIAL = 'TERRAMAR CHILE'
        self.empresa.save(update_fields=['EP_CRAZONSOCIAL'])
        self.assertEqual(self.empresa.pk, 1)
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL=TRANSPORTE,
            SN_CRUT='77061844-4',
            SN_CCODIGO_SAP='P77061844',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        self.cliente_homonimo = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL=TRANSPORTE,
            SN_CRUT='77061844-4',
            SN_CCODIGO_SAP='C77061844',
            SN_CTIPO='C',
            SN_BHABILITADO=True,
        )
        self.citacion.CI_FFECHAREGISTRO = timezone.make_aware(
            datetime(2026, 8, 4, 16, 48)
        )
        self.citacion.save(update_fields=['CI_FFECHAREGISTRO'])
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = TRANSPORTE
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.pk
        session.save()

    def _post_continuar(self, citaciones, follow=False):
        return self.client.post(
            reverse('proforma_citaciones_terminadas_iniciar_lote'),
            {
                'citacion_ids[]': [citacion.pk for citacion in citaciones],
                'empresa_id': self.empresa.pk,
                'transportista_normalizado': TRANSPORTE,
            },
            follow=follow,
        )

    def _crear_citacion_compatible(self, patente):
        citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.citacion.PL_NID,
            SC_NID=self.citacion.SC_NID,
            CI_FFECHAREGISTRO=self.citacion.CI_FFECHAREGISTRO,
            CI_FFECHACITACION=self.citacion.CI_FFECHACITACION,
            CI_NCUPO=CITACION.objects.count() + 1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='TERMINADO',
            CI_BHABILITADO=True,
            CI_BCONFORME=False,
            CI_NVALORTARIFA=127670,
        )
        camion = self.crear_camion(citacion, 'TERRAMAR', patente=patente)
        camion.CPA_CTRANSPORTISTA_DECLARADO = TRANSPORTE
        camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        return citacion

    def _asignar_tarifa(self, citacion, transporte):
        region = REGION.objects.create(
            RG_CNOMBRE='Region prueba', RG_CCODIGO=f'RG-{self.token}'
        )
        provincia = PROVINCIA.objects.create(
            RG_NID=region,
            PV_CNOMBRE='Provincia prueba',
            PV_CCODIGO=f'PV-{self.token}',
        )
        comuna = COMUNA.objects.create(
            PV_NID=provincia,
            COM_CNOMBRE='Comuna prueba',
            COM_CCODIGO=f'CO-{self.token}',
        )
        ruta = RUTA.objects.create(
            EP_NID=self.empresa,
            RG_NID_INICIO=region,
            PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna,
            RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia,
            COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1,
            RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='Ruta prueba',
            RUT_CCODIGO=f'RUT-{self.token}',
        )
        tarifa = TARIFA_GLOBAL.objects.create(
            EP_NID=self.empresa,
            RUT_NID=ruta,
            US_NID=self.user,
            MODIFICADO_POR=self.user,
            SN_NID=transporte,
            TAR_NVALOR=127670,
            TAR_CNOMBRETARIFA='Tarifa prueba',
            TAR_CTIPOTARIFA='RECEPCION',
            TAR_CDIVISA='CLP',
            TAR_BHABILITADO=True,
        )
        citacion.RUT_NID = ruta
        citacion.TAR_NID = tarifa
        citacion.save(update_fields=['RUT_NID', 'TAR_NID'])
        return tarifa
    def _ids_pendientes(self):
        if connection.vendor != 'postgresql':
            self.skipTest('El selector de pendientes usa SQL PostgreSQL.')
        filas = get_list_citaciones_terminadas_proforma(
            None, None, None, self.empresa.pk
        ) or []
        return [fila[0] for fila in filas]

    def test_flujo_crea_asocia_oculta_lista_y_abre_detalle(self):
        self.citacion.CI_NVALORTARIFA = 127670
        self.citacion.save(update_fields=['CI_NVALORTARIFA'])
        self.assertIn(self.citacion.pk, self._ids_pendientes())

        respuesta = self._post_continuar([self.citacion])

        proforma = PROFORMA.objects.get()
        asociacion = CITACION_PROFORMA.objects.get(CI_NID=self.citacion)
        self.assertRedirects(
            respuesta,
            reverse('proforma_listone', args=[proforma.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(asociacion.PRO_NID, proforma)
        self.assertEqual(asociacion.CIP_NSUBTOTAL, 127670)
        self.citacion.refresh_from_db()
        self.assertTrue(self.citacion.CI_BCONFORME)
        self.assertIsNone(self.citacion.PRO_NID_id)
        self.assertEqual(proforma.SN_NID, self.transporte)
        self.assertNotIn(self.citacion.pk, self._ids_pendientes())

        listado = self.client.get(reverse('prof_listall'))
        detalle = self.client.get(reverse('proforma_listone', args=[proforma.pk]))
        self.assertEqual(listado.status_code, 200)
        self.assertContains(listado, 'Lista de Proformas')
        self.assertContains(listado, str(proforma.pk))
        self.assertContains(listado, TRANSPORTE)
        self.assertContains(listado, 'RECEPCION')
        self.assertEqual(detalle.status_code, 200)

    @patch(
        'apps.home.services.proforma_mensual.crear_o_ampliar_proforma_mensual',
        return_value={
            'ok': False,
            'codigo': 'FALLO_SIMULADO',
            'mensaje': 'Fallo simulado',
        },
    )
    def test_fallo_revierte_conformidad_transporte_y_asociacion(self, _crear):
        respuesta = self._post_continuar([self.citacion])

        self.assertEqual(respuesta.status_code, 302)
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertIsNone(self.citacion.PRO_NID_id)
        self.assertFalse(PROFORMA.objects.exists())
        self.assertFalse(CITACION_PROFORMA.objects.exists())
        self.assertIn(self.citacion.pk, self._ids_pendientes())

    def test_borrador_compatible_se_reutiliza(self):
        segunda = self._crear_citacion_compatible('VIS002')
        primera_respuesta = self._post_continuar([self.citacion])
        proforma = PROFORMA.objects.get()

        segunda_respuesta = self._post_continuar([segunda])

        self.assertEqual(primera_respuesta.status_code, 302)
        self.assertRedirects(
            segunda_respuesta,
            reverse('proforma_listone', args=[proforma.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(PROFORMA.objects.count(), 1)
        self.assertEqual(
            CITACION_PROFORMA.objects.filter(PRO_NID=proforma).count(), 2
        )

    def test_autorizada_no_se_modifica(self):
        inicio, fin = periodo_citacion(self.citacion)
        autorizada = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            SN_NID=self.transporte,
            PRO_CESTADO='AUTORIZADO',
            PRO_BBORRADOR=False,
            PRO_CTIPO='RECEPCION',
            PRO_FPERIODO_INICIO=inicio,
            PRO_FPERIODO_FIN=fin,
            PRO_NSUBTOTAL=0,
            PRO_NIVA=0,
            PRO_NTOTAL=0,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
        )

        respuesta = self._post_continuar([self.citacion])

        self.assertEqual(respuesta.status_code, 302)
        self.citacion.refresh_from_db()
        autorizada.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertIsNone(self.citacion.PRO_NID_id)
        self.assertFalse(CITACION_PROFORMA.objects.exists())
        self.assertEqual(autorizada.PRO_CESTADO, 'AUTORIZADO')

    def test_tres_historicas_crean_un_borrador_sin_reescribir_pro_nid(self):
        segunda = self._crear_citacion_compatible('VIS003')
        tercera = self._crear_citacion_compatible('VIS004')

        respuesta = self._post_continuar([self.citacion, segunda, tercera])

        self.assertEqual(respuesta.status_code, 302)
        proforma = PROFORMA.objects.get()
        self.assertEqual(proforma.SN_NID, self.transporte)
        self.assertEqual(
            CITACION_PROFORMA.objects.filter(PRO_NID=proforma).count(), 3
        )
        self.assertFalse(CITACION.objects.filter(
            pk__in=[self.citacion.pk, segunda.pk, tercera.pk],
            PRO_NID__isnull=False,
        ).exists())

    def test_referencia_tarifa_desambigua_dos_proveedores_homonimos(self):
        SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL=TRANSPORTE,
            SN_CRUT='99999999-9',
            SN_CCODIGO_SAP='P99999999',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        self._asignar_tarifa(self.citacion, self.transporte)

        respuesta = self._post_continuar([self.citacion])

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(PROFORMA.objects.get().SN_NID, self.transporte)
        self.citacion.refresh_from_db()
        self.assertIsNone(self.citacion.PRO_NID_id)
    def test_dos_proveedores_homonimos_bloquean_sin_mutar_y_muestran_error(self):
        SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL=TRANSPORTE,
            SN_CRUT='99999999-9',
            SN_CCODIGO_SAP='P99999999',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )

        respuesta = self._post_continuar([self.citacion], follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'No fue posible identificar de forma única el Transporte',
        )
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertIsNone(self.citacion.PRO_NID_id)
        self.assertFalse(PROFORMA.objects.exists())
        self.assertFalse(CITACION_PROFORMA.objects.exists())

    def test_citacion_nueva_sin_pro_nid_es_rechazada_sin_mutar(self):
        self.citacion.CI_FFECHAREGISTRO = timezone.now()
        self.citacion.save(update_fields=['CI_FFECHAREGISTRO'])

        respuesta = self._post_continuar([self.citacion], follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'requiere PRO_NID')
        self.citacion.refresh_from_db()
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertFalse(PROFORMA.objects.exists())

    def test_citacion_nueva_con_pro_nid_formal_usa_el_proveedor(self):
        self.citacion.CI_FFECHAREGISTRO = timezone.now()
        self.citacion.PRO_NID = self.transporte
        self.citacion.save(update_fields=['CI_FFECHAREGISTRO', 'PRO_NID'])

        respuesta = self._post_continuar([self.citacion])

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(PROFORMA.objects.get().SN_NID, self.transporte)
        self.citacion.refresh_from_db()
        self.assertEqual(self.citacion.PRO_NID, self.transporte)
    def test_huerfana_iniciada_vuelve_a_pendientes_y_es_recuperable(self):
        self.citacion.CI_BCONFORME = True
        self.citacion.save(update_fields=['CI_BCONFORME'])
        self.assertIn(self.citacion.pk, self._ids_pendientes())

        respuesta = self._post_continuar([self.citacion])

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(CITACION_PROFORMA.objects.filter(
            CI_NID=self.citacion
        ).exists())

    def test_inicio_individual_terramar_tambien_materializa_borrador(self):
        respuesta = self.client.post(
            reverse('citacion_iniciar_proforma', args=[self.citacion.pk])
        )

        proforma = PROFORMA.objects.get()
        self.assertRedirects(
            respuesta,
            reverse('proforma_listone', args=[proforma.pk]),
            fetch_redirect_response=False,
        )
        self.assertTrue(CITACION_PROFORMA.objects.filter(
            CI_NID=self.citacion,
            PRO_NID=proforma,
        ).exists())
    def test_sbh_no_es_visible_ni_aceptado(self):
        sbh = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='SBH-TEST',
            EP_CBASEDATOS='sbh',
            EP_CUSUARIOSBD='sbh',
            EP_CPORT='5432',
        )
        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=sbh)
        session = self.client.session
        session['empresa_id'] = sbh.pk
        session.save()

        listado = self.client.get(reverse('prof_listall'))
        respuesta = self.client.post(
            reverse('proforma_citaciones_terminadas_iniciar_lote'),
            {
                'citacion_ids[]': [self.citacion.pk],
                'empresa_id': sbh.pk,
                'transportista_normalizado': TRANSPORTE,
            },
        )

        self.assertEqual(listado.status_code, 403)
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(PROFORMA.objects.exists())
        self.assertFalse(CITACION_PROFORMA.objects.exists())
