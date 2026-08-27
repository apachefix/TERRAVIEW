from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_EXTRA,
    CITACION_PROFORMA,
    EMPRESA,
    EXTRA,
    EXTRA_PROFORMA,
    PERFIL,
    PERFIL_USUARIO,
    PERMISO,
    PROFORMA,
    SOCIONEGOCIO,
    USERS_EMPRESA,
    VISTA,
)
from apps.home.services.proforma_mensual import crear_o_ampliar_proforma_mensual
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


class ProformaMensualTerramarTests(IniciarProformaFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.crear_datos_base()
        self.assertEqual(self.empresa.pk, 1)
        self.perfil.PR_CCODIGO = 'CONTROL_FLOTA'
        self.perfil.save(update_fields=['PR_CCODIGO'])
        self.transporte_a = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL='TRANSPORTE A',
            SN_CRUT='11.111.111-1',
            SN_CTIPO='S',
        )
        self.transporte_b = SOCIONEGOCIO.objects.create(
            EP_NID=self.empresa,
            SN_CRAZONSOCIAL='TRANSPORTE B',
            SN_CRUT='22.222.222-2',
            SN_CTIPO='S',
        )
        self._preparar(self.citacion, datetime(2026, 8, 10, 12, 0))
        self.client.force_login(self.user)

    def _preparar(self, citacion, fecha, transporte=None, tipo='RECEPCION'):
        citacion.CI_FFECHACITACION = timezone.make_aware(fecha)
        citacion.CI_FFECHAREGISTRO = timezone.make_aware(datetime(2026, 7, 31, 12, 0))
        citacion.CI_FFECHAINICIO = citacion.CI_FFECHACITACION
        citacion.CI_FFECHATERMINO = citacion.CI_FFECHACITACION
        citacion.CI_CTIPO = tipo
        citacion.CI_CESTADO = 'TERMINADO'
        citacion.CI_BHABILITADO = True
        citacion.CI_BCONFORME = True
        citacion.PRO_NID = transporte or self.transporte_a
        citacion.CI_NVALORTARIFA = Decimal('127670')
        citacion.save()
        return citacion

    def _otra_citacion(self, fecha, transporte=None, tipo='RECEPCION'):
        original = self.citacion
        citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=original.PL_NID,
            SC_NID=original.SC_NID,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHAINICIO=timezone.now(),
            CI_FFECHATERMINO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=2,
            CI_CTIPO=tipo,
            CI_CESTADO='TERMINADO',
            CI_BHABILITADO=True,
            CI_BCONFORME=True,
        )
        self._preparar(citacion, fecha, transporte, tipo)
        self.crear_camion(citacion, 'TERRAMAR', patente=f'T{citacion.pk:05d}')
        return citacion

    def _crear(self, citaciones, **cambios):
        datos = {
            'user': self.user,
            'citacion_ids': [c.pk for c in citaciones],
            'empresa_id': 1,
            'transporte_id': self.transporte_a.pk,
            'tipo': 'RECEPCION',
            'periodo': '2026-08',
            'sin_extras': False,
        }
        datos.update(cambios)
        return crear_o_ampliar_proforma_mensual(**datos)

    def test_crea_grupo_mensual_y_snapshot_desde_fecha_citacion(self):
        resultado = self._crear([self.citacion])
        self.assertTrue(resultado['ok'])
        proforma = PROFORMA.objects.get(pk=resultado['proforma'])
        self.assertEqual(str(proforma.PRO_FPERIODO_INICIO), '2026-08-01')
        self.assertEqual(str(proforma.PRO_FPERIODO_FIN), '2026-08-31')
        self.assertEqual(proforma.SN_NID, self.transporte_a)
        self.assertEqual(proforma.PRO_CTIPO, 'RECEPCION')
        asociacion = CITACION_PROFORMA.objects.get(PRO_NID=proforma)
        self.assertEqual(asociacion.CIP_NSUBTOTAL, Decimal('127670'))
        self.assertTrue(asociacion.CIP_BREGLA_MENSUAL)

    def test_extras_respetan_grupo_y_modalidad_sin_extras(self):
        extra = EXTRA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            EXT_CNOMBRE='Espera',
            EXT_CTIPO_CITACION='RECEPCION',
            EXT_BINGRESO=True,
        )
        CITACION_EXTRA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            EXT_NID=extra,
            CI_NID=self.citacion,
            CIE_NVALOR=Decimal('1000'),
            CIE_BINGRESO=True,
        )
        creada = self._crear([self.citacion])
        proforma = PROFORMA.objects.get(pk=creada['proforma'])
        proforma_extras = PROFORMA.objects.get(pk=creada['proforma_extras'])
        self.assertFalse(EXTRA_PROFORMA.objects.filter(PRO_NID=proforma).exists())
        self.assertEqual(proforma.PRO_NSUBTOTAL, Decimal('127670'))
        self.assertEqual(proforma_extras.PRO_CTIPO, 'RECEPCION EXTRAS')
        self.assertEqual(EXTRA_PROFORMA.objects.filter(PRO_NID=proforma_extras).count(), 1)
        self.assertEqual(proforma_extras.PRO_NSUBTOTAL, Decimal('1000'))
        self.assertEqual(proforma_extras.PRO_NTOTAL, Decimal('1190'))

        otra = self._otra_citacion(datetime(2026, 9, 2, 12))
        sin_extras = self._crear([otra], periodo='2026-09', sin_extras=True)
        proforma_sin = PROFORMA.objects.get(pk=sin_extras['proforma'])
        self.assertTrue(proforma_sin.PRO_BSINEXTRAS)
        self.assertFalse(EXTRA_PROFORMA.objects.filter(PRO_NID=proforma_sin).exists())
    def test_rechaza_otro_tipo_transporte_periodo_y_empresa(self):
        despacho = self._otra_citacion(datetime(2026, 8, 11, 12), tipo='DESPACHO')
        otro_transporte = self._otra_citacion(
            datetime(2026, 8, 12, 12), self.transporte_b
        )
        julio = self._otra_citacion(datetime(2026, 7, 30, 12))
        self.assertFalse(self._crear([despacho])['ok'])
        self.assertFalse(self._crear([otro_transporte])['ok'])
        self.assertFalse(self._crear([julio])['ok'])
        self.assertEqual(
            self._crear([self.citacion], empresa_id=2)['codigo'],
            'EMPRESA_FUERA_ALCANCE',
        )
        self.assertEqual(PROFORMA.objects.count(), 0)

    def test_borrador_existente_exige_decision_explicita_y_admite_compatible(self):
        creada = self._crear([self.citacion])
        compatible = self._otra_citacion(datetime(2026, 8, 15, 12))
        conflicto = self._crear([compatible])
        self.assertEqual(conflicto['codigo'], 'PROFORMA_EXISTENTE')
        ampliada = self._crear(
            [compatible], proforma_id=creada['proforma']
        )
        self.assertTrue(ampliada['ok'])
        self.assertEqual(
            CITACION_PROFORMA.objects.filter(
                PRO_NID_id=creada['proforma']
            ).count(),
            2,
        )

    def test_solo_incorpora_ids_explicitos_y_deja_compatibles_disponibles(self):
        segunda = self._otra_citacion(datetime(2026, 8, 11, 12))
        tercera = self._otra_citacion(datetime(2026, 8, 12, 12))

        creada = self._crear([self.citacion])
        self.assertTrue(creada['ok'])
        proforma_id = creada['proforma']
        self.assertQuerySetEqual(
            CITACION_PROFORMA.objects.filter(PRO_NID_id=proforma_id)
            .values_list('CI_NID_id', flat=True),
            [self.citacion.pk],
            ordered=False,
        )
        self.assertFalse(CITACION_PROFORMA.objects.filter(
            CI_NID_id__in=[segunda.pk, tercera.pk]
        ).exists())

        ampliada = self._crear([segunda], proforma_id=proforma_id)
        self.assertTrue(ampliada['ok'])
        self.assertSetEqual(
            set(CITACION_PROFORMA.objects.filter(PRO_NID_id=proforma_id)
                .values_list('CI_NID_id', flat=True)),
            {self.citacion.pk, segunda.pk},
        )
        self.assertFalse(CITACION_PROFORMA.objects.filter(
            CI_NID_id=tercera.pk
        ).exists())

    def test_aprobada_no_admite_nuevas_citaciones(self):
        creada = self._crear([self.citacion])
        proforma = PROFORMA.objects.get(pk=creada['proforma'])
        proforma.PRO_CESTADO = 'APROBADO'
        proforma.save(update_fields=['PRO_CESTADO'])
        compatible = self._otra_citacion(datetime(2026, 8, 15, 12))

        resultado = self._crear([compatible], proforma_id=proforma.pk)
        self.assertEqual(resultado['codigo'], 'PROFORMA_APROBADA')
        self.assertFalse(CITACION_PROFORMA.objects.filter(
            PRO_NID=proforma, CI_NID=compatible
        ).exists())
    def test_add_citacion_rechaza_grupos_incompatibles(self):
        creada = self._crear([self.citacion])
        proforma_id = creada['proforma']
        casos = [
            self._otra_citacion(datetime(2026, 8, 12), tipo='DESPACHO'),
            self._otra_citacion(datetime(2026, 8, 13), self.transporte_b),
            self._otra_citacion(datetime(2026, 7, 31)),
        ]
        for citacion in casos:
            respuesta = self.client.post(
                reverse('proforma_add_citacion', args=[proforma_id]),
                {'CI_NID': citacion.pk},
            )
            self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(
            CITACION_PROFORMA.objects.filter(PRO_NID_id=proforma_id).count(),
            1,
        )

    def test_no_modifica_autorizada_ni_historica(self):
        autorizada = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            SN_NID=self.transporte_a,
            PRO_CESTADO='AUTORIZADO',
            PRO_NSUBTOTAL=0,
            PRO_NIVA=0,
            PRO_NTOTAL=0,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
            PRO_CTIPO='RECEPCION',
            PRO_BBORRADOR=False,
            PRO_FPERIODO_INICIO='2026-08-01',
            PRO_FPERIODO_FIN='2026-08-31',
        )
        resultado = self._crear([self.citacion])
        self.assertTrue(resultado['ok'])
        self.assertEqual(resultado['codigo'], 'PROFORMA_CREADA')
        self.assertNotEqual(resultado['proforma'], autorizada.pk)
        historica = PROFORMA.objects.create(
            EP_NID=self.empresa,
            US_NID=self.user,
            SN_NID=self.transporte_b,
            PRO_CESTADO='CREADO',
            PRO_NSUBTOTAL=10,
            PRO_NIVA=1.9,
            PRO_NTOTAL=11.9,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
            PRO_CTIPO='RECEPCION',
        )
        historica.refresh_from_db()
        self.assertIsNone(historica.PRO_FPERIODO_INICIO)
        self.assertIsNone(historica.PRO_FPERIODO_FIN)
        self.assertTrue(PROFORMA.objects.filter(pk=autorizada.pk).exists())

    def test_quitar_usa_snapshot_y_no_tarifa_actual(self):
        creada = self._crear([self.citacion])
        proforma = PROFORMA.objects.get(pk=creada['proforma'])
        self.citacion.CI_NVALORTARIFA = Decimal('999999')
        self.citacion.save(update_fields=['CI_NVALORTARIFA'])
        vista = VISTA.objects.create(
            US_NID=self.user,
            VI_CCODIGO='proforma_delete_citacion',
            VI_CNOMBRE='proforma_delete_citacion',
            VI_BHABILITADO=True,
        )
        PERMISO.objects.create(
            US_NID=self.user,
            PR_NID=self.perfil,
            VI_NID=vista,
            PE_BHABILITADO=True,
        )
        respuesta = self.client.get(
            reverse('proforma_delete_citacion', args=[self.citacion.pk])
        )
        self.assertEqual(respuesta.status_code, 302)
        proforma.refresh_from_db()
        self.assertEqual(proforma.PRO_NSUBTOTAL, Decimal('0'))
        self.assertEqual(proforma.PRO_NTOTAL, Decimal('0'))

    def test_lista_muestra_proforma_mensual_y_rechaza_sbh(self):
        limite_mes = self._otra_citacion(datetime(2026, 8, 31, 23, 30))
        resultado = self._crear([limite_mes])
        respuesta = self.client.get(
            reverse('prof_listall'),
            {'_empresa_id': 1},
        )

        self.assertTrue(resultado['ok'])
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Lista de Proformas')
        self.assertContains(respuesta, str(resultado['proforma']))
        self.assertContains(respuesta, 'TRANSPORTE A')
        self.assertContains(respuesta, 'type="month"')
        self.assertEqual(
            self.client.get(reverse('prof_listall'), {'_empresa_id': 2}).status_code,
            403,
        )

    def test_lista_filtra_tipo_y_estados_finales_pasan_a_historico(self):
        recepcion = self._crear([self.citacion])
        citacion_despacho = self._otra_citacion(
            datetime(2026, 8, 12, 12), tipo='DESPACHO'
        )
        despacho = self._crear(
            [citacion_despacho], tipo='DESPACHO'
        )
        self.assertTrue(recepcion['ok'])
        self.assertTrue(despacho['ok'])

        lista_recepcion = self.client.get(
            reverse('prof_listall'),
            {'_empresa_id': 1, 'tipo': 'RECEPCION'},
        )
        self.assertEqual(lista_recepcion.status_code, 200)
        ids_recepcion = {
            item.pk for item in lista_recepcion.context['object_list']
        }
        self.assertSetEqual(ids_recepcion, {recepcion['proforma']})

        lista_despacho = self.client.get(
            reverse('prof_listall'),
            {'_empresa_id': 1, 'tipo': 'DESPACHO'},
        )
        ids_despacho = {
            item.pk for item in lista_despacho.context['object_list']
        }
        self.assertSetEqual(ids_despacho, {despacho['proforma']})

        proforma_recepcion = PROFORMA.objects.get(pk=recepcion['proforma'])
        proforma_recepcion.PRO_CESTADO = 'APROBADO'
        proforma_recepcion.save(update_fields=['PRO_CESTADO'])
        proforma_despacho = PROFORMA.objects.get(pk=despacho['proforma'])
        proforma_despacho.PRO_CESTADO = 'AUTORIZADO'
        proforma_despacho.PRO_BBORRADOR = False
        proforma_despacho.PRO_DOC_NUM = '7001'
        proforma_despacho.PRO_DOC_ENTRY = 6001
        proforma_despacho.save(update_fields=[
            'PRO_CESTADO', 'PRO_BBORRADOR', 'PRO_DOC_NUM', 'PRO_DOC_ENTRY',
        ])

        lista = self.client.get(reverse('prof_listall'), {'_empresa_id': 1})
        self.assertSetEqual(
            {item.pk for item in lista.context['object_list']},
            {proforma_recepcion.pk},
        )

        detalle_historico = self.client.get(reverse(
            'proforma_terramar_detalle', args=[proforma_recepcion.pk]
        ))
        self.assertEqual(detalle_historico.status_code, 200)
        self.assertFalse(detalle_historico.context['editable'])
        self.assertNotContains(detalle_historico, 'Aprobar borrador')
        self.assertNotContains(detalle_historico, 'Agregar Extra')
        historico = self.client.get(
            reverse('proforma_historico'), {'_empresa_id': 1}
        )
        self.assertEqual(historico.status_code, 200)
        self.assertSetEqual(
            {item.pk for item in historico.context['object_list']},
            {proforma_despacho.pk},
        )
        historico_recepcion = self.client.get(
            reverse('proforma_historico'),
            {'_empresa_id': 1, 'tipo': 'RECEPCION'},
        )
        self.assertSetEqual(
            {item.pk for item in historico_recepcion.context['object_list']},
            set(),
        )
        historico_doc = self.client.get(
            reverse('proforma_historico'),
            {'_empresa_id': 1, 'doc_sap': '6001'},
        )
        self.assertSetEqual(
            {item.pk for item in historico_doc.context['object_list']},
            {proforma_despacho.pk},
        )
    def test_planificador_no_recibe_acceso_nuevo(self):
        User = get_user_model()
        planificador = User.objects.create_user('planificador_mensual')
        perfil = PERFIL.objects.create(
            US_NID=self.user,
            PR_CCODIGO='PLANIFICADOR',
            PR_CNOMBRE='Planificador',
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=planificador, PR_NID=perfil, PE_BHABILITADO=True
        )
        USERS_EMPRESA.objects.create(US_NID=planificador, EP_NID=self.empresa)
        resultado = crear_o_ampliar_proforma_mensual(
            user=planificador,
            citacion_ids=[self.citacion.pk],
            empresa_id=1,
            transporte_id=self.transporte_a.pk,
            tipo='RECEPCION',
            periodo='2026-08',
        )
        self.assertEqual(resultado['codigo'], 'SIN_PERMISO')
