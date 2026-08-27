import json
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CAMPO,
    CITACION_DOCUMENTO,
    CITACION_EXTRA,
    CITACION_PROFORMA,
    DATO_OPERACION,
    EMPRESA,
    ETAPA,
    EXTRA,
    EXTRA_PROFORMA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    PROFORMA,
    USERS_EMPRESA,
    VISTA,
    SOCIONEGOCIO,
    SYSLOGGER,
)
from apps.home.services.proforma_terramar import (
    ProformaTerramarError,
    agregar_extra,
    editar_extra,
    eliminar_extra,
    resumen_pesaje,
)
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin
from apps.home.templatetags.formats import clp


class ProformaTerramarFase3Tests(IniciarProformaFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.crear_datos_base()
        PERFIL.objects.filter(pk=self.perfil.pk).update(
            PR_CCODIGO='CONTROL_FLOTA', PR_CNOMBRE='Control Flota'
        )
        self.empresa.EP_CRAZONSOCIAL = 'TERRAMAR CHILE'
        self.empresa.save(update_fields=['EP_CRAZONSOCIAL'])
        self.assertEqual(self.empresa.pk, 1)
        self.transporte = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL='TRANSPORTES SAEZ LIMITADA',
            SN_CRUT='77061844-4',
            SN_CCODIGO_SAP='P77061844',
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        self.proforma = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            SN_NID=self.transporte,
            PRO_CESTADO='CREADO',
            PRO_BBORRADOR=True,
            PRO_CTIPO='RECEPCION',
            PRO_FPERIODO_INICIO=date(2026, 8, 1),
            PRO_FPERIODO_FIN=date(2026, 8, 31),
            PRO_NSUBTOTAL=Decimal('100000'),
            PRO_NIVA=Decimal('19000'),
            PRO_NTOTAL=Decimal('119000'),
            PRO_NINGRESO=Decimal('0'),
            PRO_NDESCUENTO=Decimal('0'),
        )
        CITACION_PROFORMA.objects.create(
            EP_NID=self.empresa,
            PRO_NID=self.proforma,
            CI_NID=self.citacion,
            CIP_NSUBTOTAL=Decimal('100000'),
            CIP_BREGLA_MENSUAL=True,
        )
        self.sobrestadia = EXTRA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            EXT_CNOMBRE='SOBRESTADIA',
            EXT_BHABILITADO=True,
            EXT_BINGRESO=True,
            EXT_CTIPO_CITACION='RECEPCION',
            EXT_NVALORBASE=Decimal('45000'),
            EXT_BPERMITECANTIDAD=True,
            EXT_BPERMITEEDITARVALOR=True,
        )
        self.noche = EXTRA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            EXT_CNOMBRE='NOCHE',
            EXT_BHABILITADO=True,
            EXT_BINGRESO=True,
            EXT_CTIPO_CITACION='RECEPCION',
            EXT_NVALORBASE=Decimal('15000'),
            EXT_BPERMITECANTIDAD=True,
            EXT_BPERMITEEDITARVALOR=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.pk
        session.save()

    def agregar(self, extra=None, cantidad='1', unitario='45000'):
        return agregar_extra(
            user=self.user,
            proforma_id=self.proforma.pk,
            citacion_id=self.citacion.pk,
            extra_id=(extra or self.sobrestadia).pk,
            cantidad=cantidad,
            valor_unitario=unitario,
            comentario='Prueba Fase 3',
        )

    def test_sobrestadia_cantidad_por_unitario_y_snapshot(self):
        extra = self.agregar(cantidad='2', unitario='45000.00000')
        extra.refresh_from_db(); extra.CIE_NID.refresh_from_db()
        extras = extra.PRO_NID; extras.refresh_from_db(); self.proforma.refresh_from_db()
        self.assertEqual(extra.EPR_NCANTIDAD, 2)
        self.assertEqual(extra.EPR_NVALORUNITARIO, Decimal('45000'))
        self.assertEqual(extra.EPR_NVALOR, Decimal('90000'))
        self.assertEqual(extra.CIE_NID.CIE_NCANTIDAD, 2)
        self.assertEqual(extra.CIE_NID.CIE_NVALOR, Decimal('90000'))
        self.assertEqual(self.proforma.PRO_NSUBTOTAL, Decimal('100000'))
        self.assertEqual(self.proforma.PRO_NTOTAL, Decimal('119000'))
        self.assertEqual(extras.PRO_NSUBTOTAL, Decimal('90000'))
        self.assertEqual(extras.PRO_NINGRESO, Decimal('90000'))
        self.assertEqual(extras.PRO_NTOTAL, Decimal('107100'))
        self.assertTrue(SYSLOGGER.objects.filter(LOG_COPERACION='EXTRA_AGREGADO').exists())
    def test_editar_tres_unidades_y_eliminar_recalcula(self):
        extra = self.agregar(cantidad='2')
        editar_extra(
            user=self.user, proforma_id=self.proforma.pk,
            citacion_id=self.citacion.pk, extra_proforma_id=extra.pk,
            cantidad='3', valor_unitario='45000',
            comentario='Corregido a tres', editar_valor=True,
        )
        extra.refresh_from_db(); extras = extra.PRO_NID; extras.refresh_from_db()
        self.proforma.refresh_from_db()
        self.assertEqual(extra.EPR_NVALOR, Decimal('135000'))
        self.assertEqual(extras.PRO_NTOTAL, Decimal('160650'))
        self.assertEqual(self.proforma.PRO_NTOTAL, Decimal('119000'))
        self.assertTrue(SYSLOGGER.objects.filter(LOG_COPERACION='EXTRA_EDITADO').exists())
        eliminar_extra(
            user=self.user, proforma_id=self.proforma.pk,
            citacion_id=self.citacion.pk, extra_proforma_id=extra.pk,
        )
        extra.refresh_from_db(); extras.refresh_from_db(); self.proforma.refresh_from_db()
        self.assertFalse(extra.EPR_BHABILITADO)
        self.assertEqual(extras.PRO_NSUBTOTAL, Decimal('0'))
        self.assertEqual(extras.PRO_NTOTAL, Decimal('0'))
        self.assertEqual(self.proforma.PRO_NTOTAL, Decimal('119000'))
        self.assertTrue(SYSLOGGER.objects.filter(LOG_COPERACION='EXTRA_ELIMINADO').exists())
    def test_cambio_valor_base_no_altera_snapshot_existente(self):
        anterior = self.agregar(extra=self.noche, unitario='15000')
        self.noche.EXT_NVALORBASE = Decimal('20000')
        self.noche.save(update_fields=['EXT_NVALORBASE'])
        nuevo = self.agregar(extra=self.noche, unitario='20000')

        anterior.refresh_from_db()
        nuevo.refresh_from_db()
        self.assertEqual(anterior.EPR_NVALOR, Decimal('15000'))
        self.assertEqual(anterior.EPR_NVALORUNITARIO, Decimal('15000'))
        self.assertEqual(nuevo.EPR_NVALOR, Decimal('20000'))
        self.assertEqual(nuevo.EPR_NVALORUNITARIO, Decimal('20000'))

    def test_autorizada_es_solo_lectura_y_extras_abren_documento_independiente(self):
        self.proforma.PRO_CESTADO = 'AUTORIZADO'
        self.proforma.PRO_BBORRADOR = False
        self.proforma.save(update_fields=['PRO_CESTADO', 'PRO_BBORRADOR'])
        snapshot = self.agregar(cantidad='2')
        self.assertEqual(snapshot.PRO_NID.PRO_CTIPO, 'RECEPCION EXTRAS')
        self.assertEqual(snapshot.PRO_NID.PRO_CESTADO, 'CREADO')
        respuesta = self.client.get(reverse('proforma_terramar_detalle', args=[self.proforma.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'AUTORIZADO')
        self.assertNotContains(respuesta, 'Agregar Extra')
    def test_control_flota_ve_detalle_y_documento_operacional(self):
        CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            CD_CTIPO='GUIA',
            CD_CRUTA_ARCHIVO='camiones_patio/1/TEST01/guia.pdf',
            CD_CNOMBRE_ARCHIVO='guia.pdf',
            US_SUBE_NID=self.user,
            CD_BACTIVO=True,
        )
        detalle = self.client.get(
            reverse('proforma_terramar_detalle', args=[self.proforma.pk])
        )
        operativo = self.client.get(reverse(
            'proforma_terramar_citacion_detalle',
            args=[self.proforma.pk, self.citacion.pk],
        ))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'Subtotal Fletes')
        self.assertNotContains(detalle, 'Agregar Extra')
        self.assertEqual(operativo.status_code, 200)
        self.assertContains(operativo, 'Datos de planificación')
        self.assertContains(operativo, 'guia.pdf')
        self.assertContains(operativo, 'Agregar Extra')

    def test_endpoint_agregar_extra_recalcula_y_redirige_al_detalle(self):
        respuesta = self.client.post(
            reverse('proforma_terramar_extra_agregar', args=[self.proforma.pk, self.citacion.pk]),
            {'extra_id': self.sobrestadia.pk, 'cantidad': '2',
             'valor_unitario': '45000.00000', 'comentario': 'Desde interfaz'},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, reverse('proforma_terramar_citacion_operacional', args=[self.citacion.pk]))
        snapshot = EXTRA_PROFORMA.objects.get(PRO_NID__PRO_CTIPO='RECEPCION EXTRAS')
        self.assertEqual(snapshot.EPR_NVALOR, Decimal('90000'))
        detalle = self.client.get(reverse('proforma_terramar_detalle', args=[snapshot.PRO_NID_id]))
        self.assertContains(detalle, 'Desde interfaz')
    def test_control_flota_aprueba_sin_sap_y_queda_solo_lectura(self):
        self.citacion.CI_FFECHACITACION = timezone.make_aware(
            timezone.datetime(2026, 8, 10, 12, 0)
        )
        self.citacion.save(update_fields=['CI_FFECHACITACION'])

        with patch('apps.home.views.CREAR_OC') as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_terramar_aprobar_borrador', args=[self.proforma.pk]
            ))
            self.assertEqual(respuesta.status_code, 302)
            crear_oc.assert_not_called()

            self.proforma.refresh_from_db()
            self.assertEqual(self.proforma.PRO_CESTADO, 'APROBADO')
            self.assertIsNone(self.proforma.PRO_DOC_ENTRY)
            self.assertTrue(SYSLOGGER.objects.filter(
                LOG_COPERACION='PROFORMA_FLETE_APROBADA',
                LOG_CADD1=f'Proforma: {self.proforma.pk}',
            ).exists())

            detalle = self.client.get(reverse(
                'proforma_terramar_citacion_detalle',
                args=[self.proforma.pk, self.citacion.pk],
            ))
            self.assertContains(detalle, 'Solo lectura')
            self.assertNotContains(detalle, 'Agregar Extra')

            sap = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
            self.assertEqual(sap.status_code, 403)
            crear_oc.assert_not_called()

            self.user.is_superuser = True
            self.user.save(update_fields=['is_superuser'])
            quitar = self.client.get(reverse(
                'proforma_delete_citacion', args=[self.citacion.pk]
            ))
            self.assertEqual(quitar.status_code, 409)
            self.assertTrue(CITACION_PROFORMA.objects.filter(
                PRO_NID=self.proforma, CI_NID=self.citacion
            ).exists())
            crear_oc.return_value = (True, {'doc_num': 9001, 'doc_entry': 8001})
            sap = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
            self.assertEqual(sap.status_code, 200)
            crear_oc.assert_called_once_with(self.proforma.pk)
            self.proforma.refresh_from_db()
            self.assertEqual(self.proforma.PRO_CESTADO, 'AUTORIZADO')
            self.assertEqual(self.proforma.PRO_DOC_ENTRY, 8001)

    def test_autorizacion_legacy_conserva_estado_creado_como_entrada(self):
        legacy = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            SN_NID=self.transporte,
            PRO_CESTADO='CREADO',
            PRO_BBORRADOR=True,
            PRO_CTIPO='RECEPCION',
            PRO_NSUBTOTAL=Decimal('10'),
            PRO_NIVA=Decimal('1.9'),
            PRO_NTOTAL=Decimal('11.9'),
            PRO_NINGRESO=Decimal('0'),
            PRO_NDESCUENTO=Decimal('0'),
        )
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        with patch(
            'apps.home.views.CREAR_OC',
            return_value=(True, {'doc_num': 7001, 'doc_entry': 6001}),
        ) as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[legacy.pk]
            ))
        self.assertEqual(respuesta.status_code, 200)
        crear_oc.assert_called_once_with(legacy.pk)
        legacy.refresh_from_db()
        self.assertEqual(legacy.PRO_CESTADO, 'AUTORIZADO')
        self.assertEqual(legacy.PRO_DOC_ENTRY, 6001)
    def _otorgar_permiso_final_control_flota(self):
        vista, _ = VISTA.objects.get_or_create(
            VI_CNOMBRE='proforma_autorizar',
            defaults={
                'US_NID': self.user,
                'VI_CCODIGO': 'proforma_autorizar',
                'VI_BHABILITADO': True,
            },
        )
        if not vista.VI_BHABILITADO:
            vista.VI_BHABILITADO = True
            vista.save(update_fields=['VI_BHABILITADO'])
        permiso, _ = PERMISO.objects.get_or_create(
            PR_NID=self.perfil,
            VI_NID=vista,
            defaults={'US_NID': self.user, 'PE_BHABILITADO': True},
        )
        if not permiso.PE_BHABILITADO:
            permiso.PE_BHABILITADO = True
            permiso.save(update_fields=['PE_BHABILITADO'])
        return permiso

    def test_control_flota_con_permiso_heredado_ve_boton_y_puede_post_mockeado(self):
        self._otorgar_permiso_final_control_flota()
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        self.assertTrue(PERFIL_USUARIO.objects.filter(
            US_NID=self.user,
            PR_NID=self.perfil,
            PE_BHABILITADO=True,
        ).exists())
        detalle = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertContains(detalle, 'APROBAR PROFORMA')
        with patch(
            'apps.home.views.CREAR_OC',
            return_value=(True, {'doc_num': '9001', 'doc_entry': 8001}),
        ) as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(respuesta.status_code, 200)
        crear_oc.assert_called_once_with(self.proforma.pk)

    def test_usuario_sin_permiso_no_ve_boton_y_post_es_403(self):
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        detalle = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertNotContains(detalle, 'APROBAR PROFORMA')
        with patch('apps.home.views.CREAR_OC') as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(respuesta.status_code, 403)
        crear_oc.assert_not_called()

    def test_permiso_final_exige_users_empresa_y_empresa_activa(self):
        self._otorgar_permiso_final_control_flota()
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        USERS_EMPRESA.objects.filter(
            US_NID=self.user, EP_NID=self.empresa
        ).delete()
        with patch('apps.home.views.CREAR_OC') as crear_oc:
            sin_empresa = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(sin_empresa.status_code, 403)
        crear_oc.assert_not_called()

        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=self.empresa)
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='EMPRESA FUERA DE CONTEXTO',
            EP_CRUT='OTRA-EMPRESA', EP_CBASEDATOS='otra',
            EP_CUSUARIOSBD='otra', EP_CPORT='5432',
        )
        USERS_EMPRESA.objects.create(US_NID=self.user, EP_NID=otra_empresa)
        session = self.client.session
        session['empresa_id'] = otra_empresa.pk
        session.save()
        with patch('apps.home.views.CREAR_OC') as crear_oc:
            empresa_inactiva = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(empresa_inactiva.status_code, 403)
        crear_oc.assert_not_called()

    def test_control_flota_no_autoriza_estado_o_documento_invalido(self):
        self._otorgar_permiso_final_control_flota()
        creado = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertNotContains(creado, 'APROBAR PROFORMA')

        self.proforma.PRO_CESTADO = 'AUTORIZADO'
        self.proforma.PRO_BBORRADOR = False
        self.proforma.PRO_DOC_ENTRY = 8001
        self.proforma.PRO_DOC_NUM = '9001'
        self.proforma.save(update_fields=[
            'PRO_CESTADO', 'PRO_BBORRADOR', 'PRO_DOC_ENTRY', 'PRO_DOC_NUM',
        ])
        autorizado = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertNotContains(autorizado, 'APROBAR PROFORMA')
        with patch('apps.home.views.CREAR_OC') as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(respuesta.status_code, 409)
        crear_oc.assert_not_called()
    def test_creado_mensual_no_muestra_boton_ni_ejecuta_sap_final(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        detalle = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertContains(detalle, 'EN PREPARACIÓN')
        self.assertNotContains(detalle, 'APROBAR PROFORMA')
        with patch('apps.home.views.CREAR_OC') as crear_oc:
            respuesta = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(
            respuesta.json()['error'],
            'El borrador debe ser revisado antes de aprobar definitivamente la Proforma.',
        )
        crear_oc.assert_not_called()

    def test_aprobado_muestra_aprobar_proforma_y_destino_central(self):
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        with patch(
            'apps.home.views.get_sap_company_db', return_value='TESTTERRACHILE'
        ), patch(
            'apps.home.views.normalize_sap_environment', return_value='QA'
        ):
            detalle = self.client.get(reverse(
                'proforma_terramar_detalle', args=[self.proforma.pk]
            ))
        self.assertContains(detalle, 'BORRADOR APROBADO')
        self.assertContains(detalle, 'APROBAR PROFORMA')
        self.assertContains(detalle, 'TESTTERRACHILE')
        self.assertContains(
            detalle, reverse('proforma_autorizar_ajax', args=[self.proforma.pk])
        )

    def test_errores_sap_mantienen_aprobado_vigente(self):
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        for error in ('No fue posible conectar a SAP QA', 'Error OPOR.Add(): -5002'):
            with self.subTest(error=error), patch(
                'apps.home.views.CREAR_OC', return_value=(False, error)
            ):
                respuesta = self.client.post(reverse(
                    'proforma_autorizar_ajax', args=[self.proforma.pk]
                ))
            self.assertEqual(respuesta.status_code, 502)
            self.assertIn(error, respuesta.json()['error'])
            self.proforma.refresh_from_db()
            self.assertEqual(self.proforma.PRO_CESTADO, 'APROBADO')
            self.assertTrue(self.proforma.PRO_BBORRADOR)
            lista = self.client.get(reverse('prof_listall'), {'_empresa_id': 1})
            self.assertIn(
                self.proforma.pk,
                {item.pk for item in lista.context['object_list']},
            )

    def test_exito_y_doble_post_crean_una_sola_oc_logica(self):
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        with patch(
            'apps.home.views.CREAR_OC',
            return_value=(True, {'doc_num': '9001', 'doc_entry': 8001}),
        ) as crear_oc:
            primera = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
            segunda = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(primera.status_code, 200)
        self.assertEqual(
            primera.json()['message'], 'Proforma aprobada correctamente.'
        )
        self.assertEqual(segunda.status_code, 409)
        self.assertEqual(
            segunda.json()['error'],
            'Esta Proforma ya tiene una Orden de Compra SAP asociada.',
        )
        crear_oc.assert_called_once_with(self.proforma.pk)
        self.proforma.refresh_from_db()
        self.assertEqual(self.proforma.PRO_CESTADO, 'AUTORIZADO')
        self.assertFalse(self.proforma.PRO_BBORRADOR)
        self.assertEqual(self.proforma.PRO_DOC_ENTRY, 8001)
        self.assertEqual(self.proforma.PRO_DOC_NUM, '9001')
        detalle = self.client.get(reverse(
            'proforma_terramar_detalle', args=[self.proforma.pk]
        ))
        self.assertContains(detalle, 'OC SAP N° 9001')
        self.assertNotContains(detalle, 'APROBAR PROFORMA')

    def test_docentry_sin_docnum_no_autoriza_y_bloquea_reintento(self):
        self.proforma.PRO_CESTADO = 'APROBADO'
        self.proforma.save(update_fields=['PRO_CESTADO'])
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        with patch(
            'apps.home.views.CREAR_OC',
            return_value=(True, {'doc_num': None, 'doc_entry': 8123}),
        ) as crear_oc:
            primera = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
            segunda = self.client.post(reverse(
                'proforma_autorizar_ajax', args=[self.proforma.pk]
            ))
        self.assertEqual(primera.status_code, 502)
        self.assertEqual(segunda.status_code, 409)
        crear_oc.assert_called_once_with(self.proforma.pk)
        self.proforma.refresh_from_db()
        self.assertEqual(self.proforma.PRO_CESTADO, 'APROBADO')
        self.assertTrue(self.proforma.PRO_BBORRADOR)
        self.assertEqual(self.proforma.PRO_DOC_ENTRY, 8123)
        self.assertIsNone(self.proforma.PRO_DOC_NUM)
    def test_pdf_muestra_solo_extras_del_documento_independiente(self):
        snapshot = self.agregar(cantidad='2', unitario='45000')
        with patch('apps.home.views.HTML') as html_pdf:
            respuesta = self.client.get(reverse(
                'proforma_terramar_borrador_pdf', args=[snapshot.PRO_NID_id]
            ))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        html = html_pdf.call_args.kwargs['string']
        self.assertIn(f'Citación #{self.citacion.pk}', html)
        self.assertIn('SOBRESTADIA', html)
        self.assertNotIn('Tarifa snapshot', html)
        html_numeros = html.replace(chr(160), '.')
        self.assertIn('45.000', html_numeros)
        self.assertIn('90.000', html_numeros)
    def _catalogo_exacto(self, tipo):
        EXTRA.objects.filter(
            EP_NID=self.empresa, EXT_CTIPO_CITACION=tipo
        ).delete()
        configuracion = [
            ('SOBRESTADIA', '45000', True),
            ('FERIADO', '30000', True),
            ('NOCHE', '15000', True),
            ('RETORNO VACIO', '250000', True),
            ('REDESTINACION', '250000', True),
            ('FLETE FALSO', '100000', True),
        ]
        return {
            nombre: EXTRA.objects.create(
                EP_NID=self.empresa,
                US_NID=self.user,
                EXT_CNOMBRE=nombre,
                EXT_BHABILITADO=True,
                EXT_BINGRESO=True,
                EXT_CTIPO_CITACION=tipo,
                EXT_NVALORBASE=Decimal(valor),
                EXT_BPERMITECANTIDAD=permite_cantidad,
                EXT_BPERMITEEDITARVALOR=True,
            )
            for nombre, valor, permite_cantidad in configuracion
        }

    def test_catalogo_completo_en_recepcion_y_despacho(self):
        esperados = {
            'SOBRESTADIA', 'FERIADO', 'NOCHE',
            'RETORNO VACIO', 'REDESTINACION', 'FLETE FALSO',
        }
        for tipo in ('RECEPCION', 'DESPACHO'):
            self._catalogo_exacto(tipo)
            self.citacion.CI_CTIPO = tipo
            self.citacion.save(update_fields=['CI_CTIPO'])
            self.proforma.PRO_CTIPO = tipo
            self.proforma.save(update_fields=['PRO_CTIPO'])
            respuesta = self.client.get(reverse(
                'proforma_terramar_citacion_operacional',
                args=[self.citacion.pk],
            ))
            self.assertEqual(respuesta.status_code, 200)
            nombres = list(respuesta.context['catalogo_extras'].values_list(
                'EXT_CNOMBRE', flat=True
            ))
            self.assertEqual(len(nombres), 6)
            self.assertSetEqual(set(nombres), esperados)

    def test_backend_rechaza_extra_de_otro_tipo(self):
        despacho = EXTRA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            EXT_CNOMBRE='FERIADO',
            EXT_BHABILITADO=True,
            EXT_BINGRESO=True,
            EXT_CTIPO_CITACION='DESPACHO',
            EXT_NVALORBASE=Decimal('30000'),
            EXT_BPERMITECANTIDAD=False,
            EXT_BPERMITEEDITARVALOR=True,
        )
        with self.assertRaisesMessage(
            ProformaTerramarError,
            'no está configurado para esta operación',
        ):
            agregar_extra(
                user=self.user,
                proforma_id=self.proforma.pk,
                citacion_id=self.citacion.pk,
                extra_id=despacho.pk,
                cantidad='1',
                valor_unitario='30000',
                editar_valor=True,
            )
    def test_noche_feriado_y_sobrestadia_multiplican_cantidad_por_unitario(self):
        catalogo = self._catalogo_exacto('RECEPCION')
        casos = (
            ('NOCHE', Decimal('15000'), Decimal('30000')),
            ('SOBRESTADIA', Decimal('45000'), Decimal('90000')),
            ('FERIADO', Decimal('30000'), Decimal('60000')),
        )
        for nombre, unitario, total in casos:
            snapshot = agregar_extra(
                user=self.user,
                proforma_id=self.proforma.pk,
                citacion_id=self.citacion.pk,
                extra_id=catalogo[nombre].pk,
                cantidad='2',
                valor_unitario=str(unitario),
                comentario=f'Dos unidades de {nombre}',
            )
            snapshot.refresh_from_db()
            snapshot.CIE_NID.refresh_from_db()
            self.assertEqual(snapshot.EPR_NCANTIDAD, 2)
            self.assertEqual(snapshot.EPR_NVALORUNITARIO, unitario)
            self.assertEqual(snapshot.EPR_NVALOR, total)
            self.assertEqual(snapshot.CIE_NID.CIE_NCANTIDAD, 2)
            self.assertEqual(snapshot.CIE_NID.CIE_NVALORUNITARIO, unitario)
            self.assertEqual(snapshot.CIE_NID.CIE_NVALOR, total)
    def test_retorno_vacio_editable_conserva_snapshot_real(self):
        catalogo = self._catalogo_exacto('RECEPCION')
        retorno = catalogo['RETORNO VACIO']
        snapshot = agregar_extra(
            user=self.user,
            proforma_id=self.proforma.pk,
            citacion_id=self.citacion.pk,
            extra_id=retorno.pk,
            cantidad='1',
            valor_unitario='280000',
            comentario='Valor operacional',
            editar_valor=True,
        )
        retorno.refresh_from_db()
        snapshot.refresh_from_db()
        snapshot.CIE_NID.refresh_from_db()
        self.assertEqual(retorno.EXT_NVALORBASE, Decimal('250000'))
        self.assertEqual(snapshot.EPR_NCANTIDAD, 1)
        self.assertEqual(snapshot.EPR_NVALORUNITARIO, Decimal('280000'))
        self.assertEqual(snapshot.EPR_NVALOR, Decimal('280000'))
        self.assertEqual(snapshot.CIE_NID.CIE_NVALORUNITARIO, Decimal('280000'))
        self.assertEqual(snapshot.CIE_NID.CIE_NVALOR, Decimal('280000'))
        auditoria = SYSLOGGER.objects.get(LOG_COPERACION='EXTRA_AGREGADO')
        self.assertIn('Valor unitario: 280000', auditoria.LOG_CDESCRIPCION)
        self.assertIn('Total: 280000', auditoria.LOG_CDESCRIPCION)

    def test_detalle_operacional_sin_proforma_no_crea_extras(self):
        CITACION_PROFORMA.objects.filter(
            PRO_NID=self.proforma, CI_NID=self.citacion
        ).delete()
        antes_cie = CITACION_EXTRA.objects.count()
        antes_epr = EXTRA_PROFORMA.objects.count()
        respuesta = self.client.get(reverse(
            'proforma_terramar_citacion_operacional',
            args=[self.citacion.pk],
        ))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'Los Extras se pueden administrar una vez que la citación sea incorporada a una Proforma borrador.',
        )
        self.assertNotContains(respuesta, 'Agregar Extra')
        self.assertEqual(CITACION_EXTRA.objects.count(), antes_cie)
        self.assertEqual(EXTRA_PROFORMA.objects.count(), antes_epr)

    def test_formato_clp_determinista(self):
        self.assertEqual(clp(Decimal('319381')), '319.381')
        self.assertEqual(clp(Decimal('60682.39')), '60.682,39')
        self.assertEqual(clp(Decimal('380063.39')), '380.063,39')
    def _crear_datos_pesaje(self, entrada, salida):
        etapa = ETAPA.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='PESAJE-TEST',
            ET_CNOMBRE='Pesaje',
            ET_NCANTIDADMAXIMA=1,
            ET_TTIEMPOMAXIMO=time(1, 0),
            ET_BHABILITADO=True,
        )
        for codigo, peso in (
            ('OP_TICKET_PESAJE_ENT', entrada),
            ('OP_TICKET_PESAJE_SAL', salida),
        ):
            campo = CAMPO.objects.create(
                US_NID=self.user,
                EP_NID=self.empresa,
                CA_CTIPO='ARCHIVO',
                CA_CCODIGO=codigo,
                CA_CETIQUETA=codigo,
                CA_BHABILITADO=True,
            )
            DATO_OPERACION.objects.create(
                US_NID=self.user,
                EP_NID=self.empresa,
                SC_NID=self.citacion.SC_NID,
                ET_NID=etapa,
                CAMP_NID=campo,
                CI_NID=self.citacion,
                DO_FFECHAREGISTRO=timezone.now(),
                DO_CVALOR=json.dumps({'peso_neto': peso, 'folio': codigo}),
                DO_NPESO=peso,
            )

    def test_formula_peso_neto_validada_para_recepcion_y_despacho(self):
        self._crear_datos_pesaje(42000, 22000)
        recepcion = resumen_pesaje(self.citacion)
        self.assertEqual(recepcion['neto'], Decimal('20000'))
        self.assertEqual(recepcion['formula'], 'Peso entrada - Peso salida')

        self.citacion.CI_CTIPO = 'DESPACHO'
        self.citacion.save(update_fields=['CI_CTIPO'])
        despacho = resumen_pesaje(self.citacion)
        self.assertEqual(despacho['neto'], Decimal('20000'))
        self.assertEqual(despacho['formula'], 'Peso entrada - Peso salida')

    def test_sbh_permanece_fuera_de_alcance(self):
        sbh = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='ACEITES SBH',
            EP_CRUT='SBH-TEST',
            EP_CBASEDATOS='sbh',
            EP_CUSUARIOSBD='sbh',
            EP_CPORT='5432',
        )
        proforma_sbh = PROFORMA.objects.create(
            EP_NID=sbh,
            US_NID=self.user,
            PRO_CESTADO='CREADO',
            PRO_BBORRADOR=True,
            PRO_CTIPO='RECEPCION',
            PRO_FPERIODO_INICIO=date(2026, 8, 1),
            PRO_FPERIODO_FIN=date(2026, 8, 31),
            PRO_NSUBTOTAL=0,
            PRO_NIVA=0,
            PRO_NTOTAL=0,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
        )
        respuesta = self.client.get(
            reverse('proforma_terramar_detalle', args=[proforma_sbh.pk])
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(EXTRA_PROFORMA.objects.filter(PRO_NID=proforma_sbh).exists())