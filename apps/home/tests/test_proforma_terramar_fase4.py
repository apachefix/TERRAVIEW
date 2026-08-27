from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CITACION_DOCUMENTO, CITACION_EXTRA, CITACION_PROFORMA, EMPRESA, EXTRA,
    EXTRA_PROFORMA, PERFIL, PERMISO, PROFORMA, SOCIONEGOCIO, VISTA,
)
from apps.home.services.proforma_terramar import (
    ProformaTerramarError, agregar_extra, aprobar_borrador,
    borrar_carpeta_borrador, contexto_pdf_proforma, firma_borrado_carpeta,
)
from apps.home.services.proforma_service import (
    PERMISO_BORRAR_PROFORMA, evaluar_inicio_proforma,
)
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


class ProformaTerramarFase4Tests(IniciarProformaFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.crear_datos_base()
        self.assertEqual(self.empresa.pk, 1)
        PERFIL.objects.filter(pk=self.perfil.pk).update(
            PR_CCODIGO='CONTROL_FLOTA', PR_CNOMBRE='Control Flota'
        )
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa, SN_CRAZONSOCIAL='TRANSPORTE FASE 4',
            SN_CRUT='77.061.844-4', SN_CCODIGO_SAP='P77061844',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        self.citacion.CI_FFECHACITACION = timezone.make_aware(
            timezone.datetime(2026, 8, 10, 12, 0)
        )
        self.citacion.CI_CTIPO = 'RECEPCION'
        self.citacion.PRO_NID = self.transporte
        self.citacion.CI_NVALORTARIFA = Decimal('100000')
        self.citacion.save(update_fields=[
            'CI_FFECHACITACION', 'CI_CTIPO', 'PRO_NID', 'CI_NVALORTARIFA'
        ])
        self.flete = self._documento('RECEPCION')
        CITACION_PROFORMA.objects.create(
            EP_NID=self.empresa, PRO_NID=self.flete, CI_NID=self.citacion,
            CIP_NSUBTOTAL=Decimal('100000'), CIP_BREGLA_MENSUAL=True,
        )
        self.extra = EXTRA.objects.create(
            EP_NID=self.empresa, US_NID=self.user, EXT_CNOMBRE='REDESTINACION',
            EXT_BHABILITADO=True, EXT_BINGRESO=True,
            EXT_CTIPO_CITACION='RECEPCION', EXT_NVALORBASE=Decimal('250000'),
            EXT_BPERMITECANTIDAD=False, EXT_BPERMITEEDITARVALOR=True,
        )
        vista_borrar = VISTA.objects.create(
            US_NID=self.user, VI_CCODIGO=PERMISO_BORRAR_PROFORMA,
            VI_CNOMBRE='Borrar borrador', VI_BHABILITADO=True,
        )
        PERMISO.objects.create(
            US_NID=self.user, PR_NID=self.perfil,
            VI_NID=vista_borrar, PE_BHABILITADO=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.pk
        session.save()

    def _documento(self, tipo, estado='CREADO', borrador=True):
        return PROFORMA.objects.create(
            EP_NID=self.empresa, US_NID=self.user, SN_NID=self.transporte,
            PRO_CESTADO=estado, PRO_BBORRADOR=borrador, PRO_CTIPO=tipo,
            PRO_BSINEXTRAS=tipo in {'RECEPCION', 'DESPACHO'},
            PRO_BSOLOEXTRAS=tipo.endswith(' EXTRAS'),
            PRO_FPERIODO_INICIO=date(2026, 8, 1),
            PRO_FPERIODO_FIN=date(2026, 8, 31),
            PRO_NSUBTOTAL=Decimal('100000') if tipo == 'RECEPCION' else Decimal('0'),
            PRO_NIVA=Decimal('19000') if tipo == 'RECEPCION' else Decimal('0'),
            PRO_NTOTAL=Decimal('119000') if tipo == 'RECEPCION' else Decimal('0'),
            PRO_NINGRESO=Decimal('0'), PRO_NDESCUENTO=Decimal('0'),
        )

    def _agregar(self):
        return agregar_extra(
            user=self.user, proforma_id=self.flete.pk,
            citacion_id=self.citacion.pk, extra_id=self.extra.pk,
            cantidad='1', valor_unitario='250000', editar_valor=True,
        )

    def test_a_flete_y_extra_quedan_en_documentos_independientes(self):
        snapshot = self._agregar()
        self.flete.refresh_from_db()
        extras = snapshot.PRO_NID
        extras.refresh_from_db()
        self.assertEqual(self.flete.PRO_NSUBTOTAL, Decimal('100000'))
        self.assertFalse(EXTRA_PROFORMA.objects.filter(PRO_NID=self.flete).exists())
        self.assertEqual(extras.PRO_CTIPO, 'RECEPCION EXTRAS')
        self.assertEqual(extras.PRO_NSUBTOTAL, Decimal('250000'))
        self.assertEqual(extras.PRO_NTOTAL, Decimal('297500'))

    def test_b_proforma_extras_no_crea_snapshot_de_flete(self):
        documento = self._agregar().PRO_NID
        self.assertFalse(CITACION_PROFORMA.objects.filter(PRO_NID=documento).exists())
        self.assertEqual(EXTRA_PROFORMA.objects.filter(PRO_NID=documento).count(), 1)

    def test_c_aprobar_flete_no_cierra_extras(self):
        extras = self._agregar().PRO_NID
        aprobar_borrador(user=self.user, proforma_id=self.flete.pk)
        self.flete.refresh_from_db(); extras.refresh_from_db()
        self.assertEqual(self.flete.PRO_CESTADO, 'APROBADO')
        self.assertEqual(extras.PRO_CESTADO, 'CREADO')

    def test_d_aprobar_extras_no_cierra_flete(self):
        extras = self._agregar().PRO_NID
        aprobar_borrador(user=self.user, proforma_id=extras.pk)
        self.flete.refresh_from_db(); extras.refresh_from_db()
        self.assertEqual(extras.PRO_CESTADO, 'APROBADO')
        self.assertEqual(self.flete.PRO_CESTADO, 'CREADO')

    def test_e_historico_y_nuevo_borrador_de_misma_categoria_coexisten(self):
        self.flete.PRO_CESTADO = 'AUTORIZADO'; self.flete.PRO_BBORRADOR = False
        self.flete.save(update_fields=['PRO_CESTADO', 'PRO_BBORRADOR'])
        nuevo = self._documento('RECEPCION')
        self.assertNotEqual(nuevo.pk, self.flete.pk)
        self.assertEqual(PROFORMA.objects.filter(PRO_CTIPO='RECEPCION').count(), 2)

    def test_f_extra_nuevo_despues_de_autorizado_abre_otro_borrador(self):
        anterior = self._agregar().PRO_NID
        anterior.PRO_CESTADO = 'AUTORIZADO'; anterior.PRO_BBORRADOR = False
        anterior.save(update_fields=['PRO_CESTADO', 'PRO_BBORRADOR'])
        nuevo = self._agregar().PRO_NID
        self.assertNotEqual(nuevo.pk, anterior.pk)
        self.assertEqual(anterior.extra_proforma_set.count(), 1)
        self.assertEqual(nuevo.extra_proforma_set.count(), 1)

    def test_g_contextos_pdf_no_mezclan_categorias(self):
        extras = self._agregar().PRO_NID
        pdf_flete = contexto_pdf_proforma(self.flete)
        pdf_extras = contexto_pdf_proforma(extras)
        self.assertEqual(pdf_flete['extras'], [])
        self.assertEqual(pdf_flete['totales_pdf']['extras_ingreso'], 0)
        self.assertEqual(pdf_extras['subtotal_transporte'], 0)
        self.assertFalse(any(fila['asociacion'] for fila in pdf_extras['citaciones']))

    def test_h_lista_e_historico_filtran_categoria(self):
        extras = self._agregar().PRO_NID
        lista = self.client.get(reverse('prof_listall'), {'_empresa_id': 1, 'categoria': 'EXTRAS'})
        self.assertSetEqual({p.pk for p in lista.context['object_list']}, {extras.pk})
        extras.PRO_CESTADO = 'APROBADO'; extras.save(update_fields=['PRO_CESTADO'])
        lista = self.client.get(reverse('prof_listall'), {'_empresa_id': 1, 'categoria': 'EXTRAS'})
        self.assertSetEqual({p.pk for p in lista.context['object_list']}, {extras.pk})
        historico = self.client.get(reverse('proforma_historico'), {'_empresa_id': 1, 'categoria': 'EXTRAS'})
        self.assertSetEqual({p.pk for p in historico.context['object_list']}, set())
        extras.PRO_CESTADO = 'AUTORIZADO'
        extras.PRO_BBORRADOR = False
        extras.PRO_DOC_ENTRY = 9100
        extras.PRO_DOC_NUM = '9200'
        extras.save(update_fields=['PRO_CESTADO', 'PRO_BBORRADOR', 'PRO_DOC_ENTRY', 'PRO_DOC_NUM'])
        historico = self.client.get(reverse('proforma_historico'), {'_empresa_id': 1, 'categoria': 'EXTRAS'})
        self.assertSetEqual({p.pk for p in historico.context['object_list']}, {extras.pk})

    def test_i_un_activo_por_categoria_y_dos_categorias_coexisten(self):
        extras = self._documento('RECEPCION EXTRAS')
        self.assertTrue(extras.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._documento('RECEPCION')

    def test_borrador_mixto_legacy_queda_bloqueado_hasta_transicion(self):
        cie = CITACION_EXTRA.objects.create(
            EP_NID=self.empresa, US_NID=self.user, EXT_NID=self.extra,
            CI_NID=self.citacion, CIE_NVALOR=Decimal('250000'),
            CIE_BINGRESO=True, CIE_NCANTIDAD=1,
            CIE_NVALORUNITARIO=Decimal('250000'),
        )
        EXTRA_PROFORMA.objects.create(
            EP_NID=self.empresa, PRO_NID=self.flete, CIE_NID=cie,
            EPR_NVALOR=Decimal('250000'), EPR_BINGRESO=True,
            EPR_NCANTIDAD=1, EPR_NVALORUNITARIO=Decimal('250000'),
        )
        with self.assertRaisesMessage(ProformaTerramarError, 'mezcla Fletes y Extras'):
            aprobar_borrador(user=self.user, proforma_id=self.flete.pk)
        with self.assertRaisesMessage(ProformaTerramarError, 'mezcla Fletes y Extras'):
            contexto_pdf_proforma(self.flete)
    def test_borrar_flete_libera_citaciones_y_conserva_operacion(self):
        self.citacion.CI_BCONFORME = True
        self.citacion.save(update_fields=['CI_BCONFORME'])
        documento = CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion, EP_NID=self.empresa,
            CD_CTIPO='GUIA', CD_CRUTA_ARCHIVO='prueba/guia.pdf',
            CD_CNOMBRE_ARCHIVO='guia.pdf', US_SUBE_NID=self.user,
            CD_BACTIVO=True,
        )
        planificacion_id = self.citacion.PL_NID_id
        camion_ids = list(self.citacion.camion_patio_set.values_list('pk', flat=True)) if hasattr(self.citacion, 'camion_patio_set') else []
        resultado = borrar_carpeta_borrador(
            user=self.user, proforma_id=self.flete.pk,
            firma=firma_borrado_carpeta(self.flete), confirmacion='BORRAR',
        )
        self.citacion.refresh_from_db()
        self.assertEqual(resultado['cantidad_citaciones'], 1)
        self.assertFalse(PROFORMA.objects.filter(pk=self.flete.pk).exists())
        self.assertFalse(CITACION_PROFORMA.objects.filter(CI_NID=self.citacion).exists())
        self.assertFalse(self.citacion.CI_BCONFORME)
        self.assertEqual(self.citacion.CI_CESTADO, 'TERMINADO')
        self.assertEqual(self.citacion.PL_NID_id, planificacion_id)
        self.assertTrue(CITACION_DOCUMENTO.objects.filter(pk=documento.pk).exists())
        if camion_ids:
            from apps.home.models import CAMION_PATIO
            self.assertSetEqual(set(CAMION_PATIO.objects.filter(pk__in=camion_ids).values_list('pk', flat=True)), set(camion_ids))

    def test_borrar_extras_libera_snapshots_y_conserva_extra_operacional(self):
        snapshot = self._agregar()
        documento = snapshot.PRO_NID
        citacion_extra_id = snapshot.CIE_NID_id
        resultado = borrar_carpeta_borrador(
            user=self.user, proforma_id=documento.pk,
            firma=firma_borrado_carpeta(documento), confirmacion='BORRAR',
        )
        self.assertEqual(resultado['cantidad_extras'], 1)
        self.assertFalse(PROFORMA.objects.filter(pk=documento.pk).exists())
        self.assertFalse(EXTRA_PROFORMA.objects.filter(CIE_NID_id=citacion_extra_id).exists())
        self.assertTrue(CITACION_EXTRA.objects.filter(pk=citacion_extra_id).exists())
        self.assertTrue(CITACION_EXTRA.objects.filter(
            pk=citacion_extra_id, extra_proforma__isnull=True
        ).exists())

    def test_borrar_autorizada_por_post_manipulado_es_rechazado(self):
        firma = firma_borrado_carpeta(self.flete)
        self.flete.PRO_CESTADO = 'AUTORIZADO'
        self.flete.PRO_BBORRADOR = False
        self.flete.save(update_fields=['PRO_CESTADO', 'PRO_BBORRADOR'])
        respuesta = self.client.post(
            reverse('proforma_terramar_borrar_carpeta', args=[self.flete.pk]),
            {'firma_borrado': firma, 'confirmacion': 'BORRAR'},
        )
        self.assertEqual(respuesta.status_code, 409)
        self.assertTrue(PROFORMA.objects.filter(pk=self.flete.pk).exists())
        self.assertTrue(CITACION_PROFORMA.objects.filter(PRO_NID=self.flete).exists())

    def test_borrar_detecta_cambio_concurrente_y_hace_rollback(self):
        firma = firma_borrado_carpeta(self.flete)
        cie = CITACION_EXTRA.objects.create(
            EP_NID=self.empresa, US_NID=self.user, EXT_NID=self.extra,
            CI_NID=self.citacion, CIE_NVALOR=Decimal('250000'),
            CIE_BINGRESO=True,
        )
        snapshot = EXTRA_PROFORMA.objects.create(
            EP_NID=self.empresa, PRO_NID=self.flete, CIE_NID=cie,
            EPR_NVALOR=Decimal('250000'), EPR_BINGRESO=True,
        )
        with self.assertRaisesMessage(ProformaTerramarError, 'cambió'):
            borrar_carpeta_borrador(
                user=self.user, proforma_id=self.flete.pk,
                firma=firma, confirmacion='BORRAR',
            )
        self.assertTrue(PROFORMA.objects.filter(pk=self.flete.pk).exists())
        self.assertTrue(EXTRA_PROFORMA.objects.filter(pk=snapshot.pk).exists())

    def test_borrar_requiere_permiso_funcional_y_post(self):
        detalle = self.client.get(reverse('proforma_terramar_detalle', args=[self.flete.pk]))
        self.assertContains(detalle, 'Borrar carpeta')
        self.assertEqual(
            self.client.get(reverse('proforma_terramar_borrar_carpeta', args=[self.flete.pk])).status_code,
            405,
        )
        PERMISO.objects.filter(VI_NID__VI_CCODIGO=PERMISO_BORRAR_PROFORMA).update(PE_BHABILITADO=False)
        respuesta = self.client.post(
            reverse('proforma_terramar_borrar_carpeta', args=[self.flete.pk]),
            {'firma_borrado': firma_borrado_carpeta(self.flete), 'confirmacion': 'BORRAR'},
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(PROFORMA.objects.filter(pk=self.flete.pk).exists())
    def test_j_sbh_permanece_fuera_de_alcance(self):
        sbh = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='SBH-F4',
            EP_CBASEDATOS='sbh', EP_CUSUARIOSBD='sbh', EP_CPORT='5432',
        )
        documento = PROFORMA.objects.create(
            EP_NID=sbh, US_NID=self.user, PRO_CESTADO='CREADO',
            PRO_BBORRADOR=True, PRO_CTIPO='RECEPCION',
            PRO_FPERIODO_INICIO=date(2026, 8, 1), PRO_FPERIODO_FIN=date(2026, 8, 31),
            PRO_NSUBTOTAL=0, PRO_NIVA=0, PRO_NTOTAL=0,
            PRO_NINGRESO=0, PRO_NDESCUENTO=0,
        )
        with self.assertRaisesMessage(ProformaTerramarError, 'no existe'):
            from apps.home.services.proforma_terramar import obtener_proforma_terramar
            obtener_proforma_terramar(documento.pk, self.user)