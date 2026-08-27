from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import signing
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    AJUSTE_TARIFA,
    AJUSTE_TARIFA_CITACION_DETALLE,
    AJUSTE_TARIFA_DETALLE,
    CALENDARIO,
    CITACION,
    CITACION_PROFORMA,
    COMUNA,
    CONCEPTO_VARIACION_TARIFA,
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PLANIFICACION,
    PROFORMA,
    PROVINCIA,
    REGION,
    RUTA,
    SECUENCIA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
    TARIFA_LOG,
    USERS_EMPRESA,
)
from apps.home.services.ajuste_tarifas import (
    AjusteTarifaError,
    ReversaTarifaError,
    actualizar_ajustes_vencidos,
    DatosPreviewCambiaron,
    aplicar_ajuste_tarifas,
    generar_preview_ajuste,
    reversar_ultimo_ajuste,
    generar_preview_impacto,
)

from apps.home.tarifa_ajuste_views import PREVIEW_SALT

class TarifasFase31Tests(TestCase):
    def setUp(self):
        self.terramar = self._empresa(1, 'TERRAMAR CHILE')
        self.sbh = self._empresa(2, 'ACEITES SBH')
        self.control = self._usuario('FLOTA31', 'CONTROL_FLOTA')
        self.planificador = self._usuario('PLAN31', 'PLANIFICADOR')
        for usuario in (self.control, self.planificador):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)
        self.transporte = self._transporte(self.terramar, '76111111-1')
        self.transporte_sbh = self._transporte(self.sbh, '76222222-2')
        self.ruta = self._ruta(self.terramar, 'RUTA-T')
        self.ruta_sbh = self._ruta(self.sbh, 'RUTA-S')
        self.tarifa = self._tarifa(self.terramar, self.transporte, self.ruta, 100000)
        self.tarifa_dos = self._tarifa(self.terramar, self.transporte, self.ruta, 200000)
        self.tarifa_sbh = self._tarifa(self.sbh, self.transporte_sbh, self.ruta_sbh, 300000)
        self.concepto = CONCEPTO_VARIACION_TARIFA.objects.create(
            EP_NID=self.terramar,
            US_NID=self.control,
            CVT_CNOMBRE='Alza combustible',
            CVT_NPORCENTAJEDEFAULT=Decimal('2'),
            CVT_FFECHAINICIODEFAULT=timezone.localdate(),
            CVT_FFECHAVENCIMIENTODEFAULT=timezone.localdate() + timedelta(days=30),
        )
        self.citacion = self._citacion_con_valor(self.tarifa, Decimal('100000'))
        self.proforma = PROFORMA.objects.create(
            EP_NID=self.terramar,
            US_NID=self.control,
            SN_NID=self.transporte,
            PRO_CESTADO='CREADO',
            PRO_NSUBTOTAL=100000,
            PRO_NIVA=19000,
            PRO_NTOTAL=119000,
            PRO_NINGRESO=0,
            PRO_NDESCUENTO=0,
            PRO_FFECHAEMISION=timezone.now(),
        )
        CITACION_PROFORMA.objects.create(
            EP_NID=self.terramar,
            CI_NID=self.citacion,
            PRO_NID=self.proforma,
            CIP_NSUBTOTAL=100000,
        )

    def _empresa(self, pk, nombre):
        return EMPRESA.objects.create(
            pk=pk, EP_CRAZONSOCIAL=nombre, EP_CRUT=f'7600000{pk}-{pk}',
            EP_CBASEDATOS=f'db{pk}', EP_CUSUARIOSBD='user', EP_CPORT='5432',
        )

    def _usuario(self, username, codigo):
        usuario = User.objects.create_user(username=username, password='test')
        perfil = PERFIL.objects.create(
            US_NID=usuario, PR_CCODIGO=codigo, PR_CNOMBRE=codigo,
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True,
        )
        return usuario

    def _transporte(self, empresa, rut):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL=f'Transporte {empresa.pk}',
            SN_CRUT=rut, SN_CTIPO='S', SN_BHABILITADO=True,
        )

    def _ruta(self, empresa, codigo):
        region = REGION.objects.create(RG_CNOMBRE=codigo, RG_CCODIGO=codigo)
        provincia = PROVINCIA.objects.create(RG_NID=region, PV_CNOMBRE=codigo, PV_CCODIGO=codigo)
        comuna = COMUNA.objects.create(PV_NID=provincia, COM_CNOMBRE=codigo, COM_CCODIGO=codigo)
        return RUTA.objects.create(
            EP_NID=empresa, RG_NID_INICIO=region, PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna, RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia, COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1, RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE=codigo, RUT_CCODIGO=codigo, RUT_BHABILITADO=True,
        )

    def _tarifa(self, empresa, transporte, ruta, valor):
        return TARIFA_GLOBAL.objects.create(
            EP_NID=empresa, RUT_NID=ruta, SN_NID=transporte, US_NID=self.control,
            TAR_NVALOR=valor, TAR_CNOMBRETARIFA=f'Tarifa {empresa.pk}-{valor}',
            TAR_CTIPOTARIFA='FLETE', TAR_CDIVISA='CLP', TAR_BHABILITADO=True,
        )

    def _citacion_con_valor(self, tarifa, valor, fecha=None):
        calendario = CALENDARIO.objects.create(
            US_NID=self.control, EP_NID=self.terramar, CA_NDIA=1, CA_NMES=1,
            CA_NANO=2026, CA_NCANTIDADCUPOS=10,
        )
        plan = PLANIFICACION.objects.create(
            US_NID=self.control, EP_NID=self.terramar, CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=2,
        )
        secuencia = SECUENCIA.objects.create(
            US_NID=self.control, EP_NID=self.terramar, SE_CTIPO='RECEPCION',
            SE_CCODIGO='TEST31', SE_CNOMBRE='Test', SE_BHABILITADO=True,
        )
        return CITACION.objects.create(
            US_NID=self.control, EP_NID=self.terramar, PL_NID=plan,
            SC_NID=secuencia, TAR_NID=tarifa, RUT_NID=tarifa.RUT_NID,
            CI_FFECHACITACION=fecha or timezone.now(), CI_CESTADO='CREADO', CI_NCUPO=1,
            CI_BHABILITADO=True, CI_NVALORTARIFA=valor,
        )

    def _aplicar(self, porcentaje=Decimal('2'), concepto=None, vencimiento=None):
        return aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk,
            tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
            porcentaje=porcentaje,
            fecha_inicio=timezone.localdate(),
            fecha_vencimiento=vencimiento or timezone.localdate() + timedelta(days=30),
            usuario=self.control,
            concepto=concepto or self.concepto,
            observacion='Prueba Fase 3.1',
        )

    def _login_empresa(self, usuario, empresa):
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion['empresa_id'] = empresa.pk
        sesion.save()

    def _ict_validado(self):
        variaciones = ('0.2', '-0.5', '2.3', '11.3', '1.5', '-3.5')
        return {
            'fuente': 'INE',
            'periodo': 'Febrero 2026 → Julio 2026',
            'periodo_inicio': '2026-02-01',
            'periodo_fin': '2026-07-01',
            'acumulado': '11.1872',
            'variacion': '11.1872',
            'fecha_publicacion': '2026-08-11',
            'url': 'https://calculadoraict.ine.cl/',
            'componentes': [
                {
                    'periodo_fecha': f'2026-{mes:02d}-01',
                    'periodo': f'Mes {mes} 2026',
                    'variacion': valor,
                }
                for mes, valor in enumerate(variaciones, start=2)
            ],
        }
    def _aplicar_ict_acumulado(self, ajuste_manual=None, snapshot_preview=None):
        ict = self._ict_validado()
        hay_manual = ajuste_manual is not None and str(ajuste_manual).strip() != ''
        porcentaje_aplicado = ajuste_manual if hay_manual else ict['acumulado']
        return aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk,
            tipo_ajuste=AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES,
            porcentaje=porcentaje_aplicado,
            fecha_inicio=timezone.localdate(),
            fecha_vencimiento=timezone.localdate() + timedelta(days=30),
            usuario=self.control,
            fuente='INE',
            url_fuente=ict['url'],
            periodo_ict=ict['periodo'],
            ict_calculado=ict['acumulado'],
            ajuste_manual=ajuste_manual if hay_manual else None,
            motivo_manual='Porcentaje acordado con Finanzas' if hay_manual else '',
            periodo_ict_inicio=datetime.fromisoformat(
                ict['periodo_inicio']
            ).date(),
            periodo_ict_fin=datetime.fromisoformat(ict['periodo_fin']).date(),
            componentes_ict=ict['componentes'],
            snapshot_preview=snapshot_preview,
        )
    def _crear_proforma_para(self, citacion, subtotal=None, estado='CREADO'):
        subtotal = Decimal(citacion.CI_NVALORTARIFA or 0) if subtotal is None else Decimal(subtotal)
        proforma = PROFORMA.objects.create(
            EP_NID=citacion.EP_NID, US_NID=self.control, SN_NID=self.transporte,
            PRO_CESTADO=estado, PRO_NSUBTOTAL=subtotal,
            PRO_NIVA=Decimal('0'), PRO_NTOTAL=subtotal,
            PRO_NINGRESO=Decimal('0'), PRO_NDESCUENTO=Decimal('0'),
            PRO_FFECHAEMISION=timezone.now(), PRO_BBORRADOR=estado != 'AUTORIZADO',
        )
        enlace = CITACION_PROFORMA.objects.create(
            EP_NID=citacion.EP_NID, CI_NID=citacion,
            PRO_NID=proforma, CIP_NSUBTOTAL=subtotal,
        )
        return proforma, enlace

    def test_aplicar_preview_auditoria_e_historicos_congelados(self):
        preview = generar_preview_ajuste(self.terramar.pk, Decimal('2'))
        self.assertEqual(preview[0].valor_nuevo, Decimal('102000'))
        ajuste = self._aplicar()
        self.tarifa.refresh_from_db()
        self.tarifa_sbh.refresh_from_db()
        self.citacion.refresh_from_db()
        self.proforma.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALORPREVIO, Decimal('100000'))
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('102000'))
        self.assertEqual(self.tarifa_sbh.TAR_NVALOR, Decimal('300000'))
        self.assertEqual(self.citacion.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(self.proforma.PRO_NTOTAL, Decimal('119000'))
        self.assertEqual(ajuste.detalles.count(), 2)
        self.assertEqual(TARIFA_LOG.objects.filter(TAR_NID=self.tarifa).count(), 1)

        nueva = self._citacion_con_valor(self.tarifa, self.tarifa.TAR_NVALOR)
        self.assertEqual(nueva.CI_NVALORTARIFA, Decimal('102000'))

    def test_reversa_restaura_maestro_y_no_historicos(self):
        ajuste = self._aplicar()
        reversado = reversar_ultimo_ajuste(
            empresa_id=self.terramar.pk, usuario=self.control, motivo='Fin de vigencia'
        )
        self.tarifa.refresh_from_db()
        self.citacion.refresh_from_db()
        self.proforma.refresh_from_db()
        self.assertEqual(reversado.pk, ajuste.pk)
        self.assertEqual(reversado.AJT_CESTADO, AJUSTE_TARIFA.ESTADO_REVERSADO)
        self.assertEqual(self.tarifa.TAR_NVALORPREVIO, Decimal('102000'))
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(self.citacion.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(self.proforma.PRO_NTOTAL, Decimal('119000'))
        nueva = self._citacion_con_valor(self.tarifa, self.tarifa.TAR_NVALOR)
        self.assertEqual(nueva.CI_NVALORTARIFA, Decimal('100000'))

    def test_vencimiento_solo_marca_estado_sin_reversa(self):
        ajuste = self._aplicar(
            vencimiento=timezone.localdate() + timedelta(days=1)
        )
        self.tarifa.refresh_from_db()
        valor_ajustado = self.tarifa.TAR_NVALOR
        actualizar_ajustes_vencidos(
            self.terramar.pk, hoy=timezone.localdate() + timedelta(days=2)
        )
        ajuste.refresh_from_db()
        self.tarifa.refresh_from_db()
        self.assertEqual(ajuste.AJT_CESTADO, AJUSTE_TARIFA.ESTADO_VENCIDO)
        self.assertEqual(self.tarifa.TAR_NVALOR, valor_ajustado)

    def test_concepto_reutilizable_y_ajuste_anterior_no_se_reversa(self):
        primero = self._aplicar()
        segundo = self._aplicar(porcentaje=Decimal('1'))
        self.assertNotEqual(primero.pk, segundo.pk)
        reversar_ultimo_ajuste(
            empresa_id=self.terramar.pk, usuario=self.control, motivo='Reversa segundo'
        )
        primero.refresh_from_db()
        self.assertEqual(primero.AJT_CESTADO, AJUSTE_TARIFA.ESTADO_APLICADO)
        with self.assertRaises(ReversaTarifaError):
            reversar_ultimo_ajuste(
                empresa_id=self.terramar.pk, usuario=self.control, motivo='Intento cascada'
            )

    def test_reversa_rechaza_modificacion_posterior(self):
        self._aplicar()
        self.tarifa.TAR_NVALOR = Decimal('126000')
        self.tarifa.save(update_fields=['TAR_NVALOR'])
        with self.assertRaisesMessage(ReversaTarifaError, 'modificadas posteriormente'):
            reversar_ultimo_ajuste(
                empresa_id=self.terramar.pk, usuario=self.control, motivo='Intento'
            )
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('126000'))
        self.assertEqual(AJUSTE_TARIFA.objects.get().AJT_CESTADO, AJUSTE_TARIFA.ESTADO_APLICADO)

    def test_rollback_total_ante_error_intermedio(self):
        original = AJUSTE_TARIFA_DETALLE.objects.create
        llamadas = {'n': 0}

        def fallar_segunda(*args, **kwargs):
            llamadas['n'] += 1
            if llamadas['n'] == 2:
                raise RuntimeError('falla simulada')
            return original(*args, **kwargs)

        with patch.object(AJUSTE_TARIFA_DETALLE.objects, 'create', side_effect=fallar_segunda):
            with self.assertRaises(RuntimeError):
                self._aplicar()
        self.tarifa.refresh_from_db()
        self.tarifa_dos.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(self.tarifa_dos.TAR_NVALOR, Decimal('200000'))
        self.assertEqual(AJUSTE_TARIFA.objects.count(), 0)
        self.assertEqual(AJUSTE_TARIFA_DETALLE.objects.count(), 0)
        self.assertEqual(TARIFA_LOG.objects.count(), 0)

    def test_panel_modal_preview_y_permisos_planificador(self):
        self._login_empresa(self.control, self.terramar)
        listado = self.client.get(reverse('tg_listall'))
        self.assertContains(listado, 'Variaciones de tarifa')
        self.assertContains(listado, 'Crear variación')
        self.assertContains(listado, 'Alza combustible')
        preview = self.client.get(reverse('tg_variacion_preview', args=[self.concepto.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, '$ 102.000')

        self._login_empresa(self.planificador, self.terramar)
        for nombre, args in (
            ('tg_variacion_crear', ()),
            ('tg_variacion_preview', (self.concepto.pk,)),
            ('tg_variacion_aplicar', (self.concepto.pk,)),
            ('tg_reversar_ajuste', ()),
        ):
            respuesta = self.client.post(reverse(nombre, args=args))
            self.assertRedirects(respuesta, '/')

    def test_ict_usa_mismo_motor_y_empresa_activa(self):
        ajuste = aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk,
            tipo_ajuste=AJUSTE_TARIFA.TIPO_ICT,
            porcentaje=Decimal('-2.9'),
            fecha_inicio=timezone.localdate(),
            fecha_vencimiento=timezone.localdate() + timedelta(days=30),
            usuario=self.control,
            fuente='INE',
            periodo_ict='Julio 2026',
            url_fuente='https://www.ine.gob.cl/ict',
        )
        self.assertEqual(ajuste.AJT_CTIPO, AJUSTE_TARIFA.TIPO_ICT)
        self.assertEqual(ajuste.CVT_NID, None)
        self.tarifa.refresh_from_db()
        self.tarifa_sbh.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('97100'))
        self.assertEqual(self.tarifa_sbh.TAR_NVALOR, Decimal('300000'))
        self.assertEqual(ajuste.detalles_citaciones.count(), 0)

    def test_crear_concepto_ignora_empresa_enviada_y_usa_empresa_activa(self):
        self._login_empresa(self.control, self.terramar)
        hoy = timezone.localdate()
        respuesta = self.client.post(reverse('tg_variacion_crear'), {
            'nombre': 'Peajes temporales',
            'descripcion': 'Creado desde modal',
            'porcentaje': '1.5',
            'fecha_inicio': hoy.isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=10)).isoformat(),
            'EP_NID': self.sbh.pk,
        })
        self.assertRedirects(respuesta, reverse('tg_listall'))
        concepto = CONCEPTO_VARIACION_TARIFA.objects.get(
            CVT_CNOMBRE='Peajes temporales'
        )
        self.assertEqual(concepto.EP_NID, self.terramar)
        self.assertEqual(concepto.US_NID, self.control)

    def test_aplicar_ict_editado_audita_calculado_y_aplicado(self):
        self._login_empresa(self.control, self.terramar)
        sesion = self.client.session
        sesion['ict_acumulado_6_meses_validado'] = self._ict_validado()
        sesion.save()
        preview = self.client.get(
            reverse('tg_ict_preview'), {
                'ajuste_manual': '10,50',
                'motivo_manual': 'Porcentaje acordado con Finanzas',
            }
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Confirma aplicar un ajuste manual de 10.5000%')
        self.assertContains(preview, 'ICT acumulado de referencia')
        self.assertContains(preview, 'Porcentaje acordado con Finanzas')
        preview_token = preview.context['preview_token']
        hoy = timezone.localdate()
        respuesta = self.client.post(reverse('tg_ict_aplicar'), {
            'porcentaje': '50',
            'fecha_inicio': hoy.isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=30)).isoformat(),
            'preview_token': preview_token,
            'observacion': 'ICT acumulado validado',
        })
        self.assertRedirects(respuesta, reverse('tg_listall'))
        ajuste = AJUSTE_TARIFA.objects.get(
            AJT_CTIPO=AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES
        )
        self.assertEqual(ajuste.AJT_NPORCENTAJECALCULADO, Decimal('11.1872'))
        self.assertEqual(ajuste.AJT_NPORCENTAJE, Decimal('10.5'))
        self.assertEqual(ajuste.AJT_NPORCENTAJEMANUAL, Decimal('10.5'))
        self.assertEqual(
            ajuste.AJT_CORIGENPORCENTAJE,
            AJUSTE_TARIFA.ORIGEN_PORCENTAJE_MANUAL,
        )
        self.assertEqual(
            ajuste.AJT_CMOTIVOMANUAL, 'Porcentaje acordado con Finanzas'
        )
        self.assertEqual(ajuste.AJT_FPERIODOICTINICIO.isoformat(), '2026-02-01')
        self.assertEqual(ajuste.AJT_FPERIODOICTFIN.isoformat(), '2026-07-01')
        self.assertEqual(len(__import__('json').loads(ajuste.AJT_CCOMPONENTESICT)), 6)
        self.tarifa.refresh_from_db()
        self.tarifa_sbh.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALORPREVIO, Decimal('100000'))
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('110500'))
        self.assertEqual(self.tarifa_sbh.TAR_NVALOR, Decimal('300000'))
        listado = self.client.get(reverse('tg_listall'))
        self.assertContains(listado, 'Aplicado / origen:')
        self.assertContains(listado, 'MANUAL')
        self.assertContains(listado, 'Porcentaje acordado con Finanzas')
        self.assertNotIn(
            'ict_acumulado_6_meses_validado', self.client.session
        )
    def test_preview_ict_sin_manual_confirma_ict_calculado(self):
        self._login_empresa(self.control, self.terramar)
        sesion = self.client.session
        sesion['ict_acumulado_6_meses_validado'] = self._ict_validado()
        sesion.save()
        preview = self.client.get(reverse('tg_ict_preview'))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context['parametros']['porcentaje'], '11.1872')
        self.assertEqual(
            preview.context['parametros']['origen_porcentaje'],
            AJUSTE_TARIFA.ORIGEN_PORCENTAJE_ICT,
        )
        self.assertContains(
            preview,
            'Confirma aplicar el reajuste ICT acumulado de 6 meses de 11.1872%'
        )
        self.assertContains(preview, 'No informado')
    def test_ict_sin_manual_aplica_calculado_y_audita_origen(self):
        ajuste = self._aplicar_ict_acumulado()
        self.tarifa.refresh_from_db()
        self.assertEqual(ajuste.AJT_NPORCENTAJECALCULADO, Decimal('11.1872'))
        self.assertIsNone(ajuste.AJT_NPORCENTAJEMANUAL)
        self.assertEqual(ajuste.AJT_NPORCENTAJE, Decimal('11.1872'))
        self.assertEqual(
            ajuste.AJT_CORIGENPORCENTAJE,
            AJUSTE_TARIFA.ORIGEN_PORCENTAJE_ICT,
        )
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('111187'))

    def test_ict_manual_cero_es_valido_y_deja_auditoria(self):
        ajuste = self._aplicar_ict_acumulado('0')
        self.tarifa.refresh_from_db()
        self.assertEqual(ajuste.AJT_NPORCENTAJECALCULADO, Decimal('11.1872'))
        self.assertEqual(ajuste.AJT_NPORCENTAJEMANUAL, Decimal('0'))
        self.assertEqual(ajuste.AJT_NPORCENTAJE, Decimal('0'))
        self.assertEqual(
            ajuste.AJT_CORIGENPORCENTAJE,
            AJUSTE_TARIFA.ORIGEN_PORCENTAJE_MANUAL,
        )
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(ajuste.detalles.count(), 2)

    def test_ict_manual_sin_motivo_es_rechazado_backend(self):
        ict = self._ict_validado()
        with self.assertRaisesMessage(
            AjusteTarifaError, 'motivo del ajuste manual'
        ):
            aplicar_ajuste_tarifas(
                empresa_id=self.terramar.pk,
                tipo_ajuste=AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES,
                porcentaje='8.5',
                fecha_inicio=timezone.localdate(),
                fecha_vencimiento=timezone.localdate() + timedelta(days=30),
                usuario=self.control,
                ict_calculado=ict['acumulado'],
                ajuste_manual='8.5',
                motivo_manual='',
                periodo_ict_inicio=datetime.fromisoformat(ict['periodo_inicio']).date(),
                periodo_ict_fin=datetime.fromisoformat(ict['periodo_fin']).date(),
                componentes_ict=ict['componentes'],
            )
        self.assertFalse(AJUSTE_TARIFA.objects.exists())

    def test_ict_regresion_previo_actual_y_reversa_compatible(self):
        self.tarifa.TAR_NVALORPREVIO = Decimal('90000')
        self.tarifa.save(update_fields=['TAR_NVALORPREVIO'])
        ajuste = self._aplicar_ict_acumulado('10')

        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALORPREVIO, Decimal('100000'))
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('110000'))
        detalle = AJUSTE_TARIFA_DETALLE.objects.get(
            AJT_NID=ajuste, TAR_NID=self.tarifa
        )
        self.assertEqual(detalle.AJTD_NVALORANTERIOR, Decimal('100000'))
        self.assertEqual(detalle.AJTD_NVALORNUEVO, Decimal('110000'))
        self.assertEqual(ajuste.AJT_NPORCENTAJECALCULADO, Decimal('11.1872'))
        self.assertEqual(ajuste.AJT_NPORCENTAJE, Decimal('10'))

        reversar_ultimo_ajuste(
            empresa_id=self.terramar.pk,
            usuario=self.control,
            motivo='Reversa ICT acumulado',
        )
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))

    def test_ict_acumulado_negativo_actualiza_previo_y_actual(self):
        self._aplicar_ict_acumulado('-2,9')
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALORPREVIO, Decimal('100000'))
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('97100'))

    def test_ict_acumulado_rollback_total_ante_falla_intermedia(self):
        original = AJUSTE_TARIFA_DETALLE.objects.create
        llamadas = {'n': 0}

        def fallar_segunda(*args, **kwargs):
            llamadas['n'] += 1
            if llamadas['n'] == 2:
                raise RuntimeError('falla ICT simulada')
            return original(*args, **kwargs)

        with patch.object(
            AJUSTE_TARIFA_DETALLE.objects,
            'create',
            side_effect=fallar_segunda,
        ):
            with self.assertRaises(RuntimeError):
                self._aplicar_ict_acumulado('10')
        self.tarifa.refresh_from_db()
        self.tarifa_dos.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(self.tarifa_dos.TAR_NVALOR, Decimal('200000'))
        self.assertFalse(AJUSTE_TARIFA.objects.exists())
        self.assertFalse(AJUSTE_TARIFA_DETALLE.objects.exists())

    def test_ict_acumulado_rechaza_preview_obsoleto(self):
        preview = generar_preview_impacto(
            self.terramar.pk,
            '10',
            timezone.localdate(),
            timezone.localdate() + timedelta(days=30),
        )
        self.tarifa.TAR_NVALOR = Decimal('101000')
        self.tarifa.save(update_fields=['TAR_NVALOR'])
        with self.assertRaisesMessage(
            DatosPreviewCambiaron,
            'tarifas cambiaron desde la vista previa',
        ):
            self._aplicar_ict_acumulado(
                '10', snapshot_preview=preview.snapshot()
            )
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('101000'))
        self.assertFalse(AJUSTE_TARIFA.objects.exists())
    def test_periodo_efectivo_revaloriza_solo_pendientes_sin_diferencias(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        elegible = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=4)
        )
        proformada = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=5)
        )
        proforma, enlace = self._crear_proforma_para(proformada, '100000', 'AUTORIZADO')
        anterior = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio - timedelta(days=1)
        )
        futura = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=31)
        )
        revision = self._citacion_con_valor(
            self.tarifa, Decimal('95000'), inicio + timedelta(days=6)
        )
        preview = generar_preview_impacto(
            self.terramar.pk, Decimal('2'), inicio.date(),
            (inicio + timedelta(days=30)).date(),
        )
        self.assertIn(elegible.pk, [x.citacion_id for x in preview.citaciones_elegibles])
        self.assertIn(proformada.pk, [x.citacion_id for x in preview.citaciones_proformadas])
        self.assertIn(revision.pk, [x.citacion_id for x in preview.citaciones_revision])

        with patch('apps.home.views.CREAR_OC') as crear_oc_sap:
            ajuste = aplicar_ajuste_tarifas(
                empresa_id=self.terramar.pk,
                tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
                porcentaje=Decimal('2'), fecha_inicio=inicio.date(),
                fecha_vencimiento=(inicio + timedelta(days=30)).date(),
                usuario=self.control, concepto=self.concepto,
                snapshot_preview=preview.snapshot(),
            )
        crear_oc_sap.assert_not_called()
        for objeto in (elegible, proformada, anterior, futura, revision, proforma, enlace):
            objeto.refresh_from_db()
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('102000'))
        self.assertEqual(elegible.CI_NVALORTARIFA, Decimal('102000'))
        self.assertEqual(proformada.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(enlace.CIP_NSUBTOTAL, Decimal('100000'))
        self.assertEqual(proforma.PRO_NTOTAL, Decimal('100000'))
        self.assertEqual(anterior.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(futura.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(revision.CI_NVALORTARIFA, Decimal('95000'))
        self.assertEqual(ajuste.detalles_citaciones.count(), 1)
        auditoria = AJUSTE_TARIFA_CITACION_DETALLE.objects.get(AJT_NID=ajuste)
        self.assertEqual(auditoria.CI_NID, elegible)
        self.assertEqual(auditoria.AJTC_NVALORANTERIOR, Decimal('100000'))
        self.assertEqual(auditoria.AJTC_NVALORNUEVO, Decimal('102000'))
        self.tarifa_sbh.refresh_from_db()
        self.assertEqual(self.tarifa_sbh.TAR_NVALOR, Decimal('300000'))

    def test_citacion_proformada_despues_del_preview_aborta_lote(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        citacion = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=4)
        )
        preview = generar_preview_impacto(
            self.terramar.pk, '2', inicio.date(), (inicio + timedelta(days=30)).date()
        )
        self._crear_proforma_para(citacion)
        with self.assertRaisesMessage(DatosPreviewCambiaron, 'datos cambiaron'):
            aplicar_ajuste_tarifas(
                empresa_id=self.terramar.pk,
                tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
                porcentaje='2', fecha_inicio=inicio.date(),
                fecha_vencimiento=(inicio + timedelta(days=30)).date(),
                usuario=self.control, concepto=self.concepto,
                snapshot_preview=preview.snapshot(),
            )
        self.tarifa.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(citacion.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(AJUSTE_TARIFA.objects.count(), 0)

    def test_rollback_citacion_revierte_tambien_tarifas_y_auditoria(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        citacion = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=4)
        )
        with patch.object(
            AJUSTE_TARIFA_CITACION_DETALLE.objects, 'create',
            side_effect=RuntimeError('falla auditoria citacion'),
        ):
            with self.assertRaises(RuntimeError):
                aplicar_ajuste_tarifas(
                    empresa_id=self.terramar.pk,
                    tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
                    porcentaje='2', fecha_inicio=inicio.date(),
                    fecha_vencimiento=(inicio + timedelta(days=30)).date(),
                    usuario=self.control, concepto=self.concepto,
                )
        self.tarifa.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(citacion.CI_NVALORTARIFA, Decimal('100000'))
        self.assertEqual(AJUSTE_TARIFA.objects.count(), 0)
        self.assertEqual(TARIFA_LOG.objects.count(), 0)

    def test_reversa_restaura_citacion_si_sigue_pendiente(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        citacion = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=4)
        )
        aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk,
            tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
            porcentaje='2', fecha_inicio=inicio.date(),
            fecha_vencimiento=(inicio + timedelta(days=30)).date(),
            usuario=self.control, concepto=self.concepto,
        )
        reversar_ultimo_ajuste(
            empresa_id=self.terramar.pk, usuario=self.control,
            motivo='Reversa periodo efectivo',
        )
        self.tarifa.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('100000'))
        self.assertEqual(citacion.CI_NVALORTARIFA, Decimal('100000'))

    def test_reversa_aborta_si_citacion_del_lote_ya_fue_proformada(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        citacion = self._citacion_con_valor(
            self.tarifa, Decimal('100000'), inicio + timedelta(days=4)
        )
        aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk,
            tipo_ajuste=AJUSTE_TARIFA.TIPO_VARIACION_MANUAL,
            porcentaje='2', fecha_inicio=inicio.date(),
            fecha_vencimiento=(inicio + timedelta(days=30)).date(),
            usuario=self.control, concepto=self.concepto,
        )
        self._crear_proforma_para(citacion, '102000')
        with self.assertRaisesMessage(ReversaTarifaError, 'ya fueron proformadas'):
            reversar_ultimo_ajuste(
                empresa_id=self.terramar.pk, usuario=self.control,
                motivo='Intento inseguro',
            )
        self.tarifa.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual(self.tarifa.TAR_NVALOR, Decimal('102000'))
        self.assertEqual(citacion.CI_NVALORTARIFA, Decimal('102000'))

    def test_preview_web_muestra_frontera_y_periodo_efectivo(self):
        self._login_empresa(self.control, self.terramar)
        respuesta = self.client.get(reverse('tg_variacion_preview', args=[self.concepto.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Inicio período efectivo')
        self.assertContains(respuesta, 'Citaciones a revalorizar')
        self.assertContains(respuesta, 'Proformadas excluidas')
        self.assertContains(respuesta, 'Requieren revisión')
        self.assertContains(respuesta, 'preview_token')
        cantidad = len(respuesta.context['impacto'].citaciones_elegibles)
        payload = signing.loads(
            respuesta.context['preview_token'], salt=PREVIEW_SALT
        )
        self.assertEqual(
            len(payload['snapshot']['citaciones']['elegibles']), cantidad
        )
        contenido = respuesta.content.decode()
        self.assertIn(
            f'id="citaciones-elegibles-card" data-count="{cantidad}"', contenido
        )
        self.assertIn(
            f'id="tab-citaciones" data-count="{cantidad}"', contenido
        )
        self.assertIn(
            f'id="citaciones-elegibles-tabla" data-count="{cantidad}"', contenido
        )
        self.assertIn(
            f'id="citaciones-elegibles-confirmacion" data-count="{cantidad}"',
            contenido,
        )

    def test_ict_aplica_exactamente_trece_citaciones_y_audita_todas(self):
        inicio = timezone.make_aware(datetime(2026, 8, 1, 0, 0))
        citaciones = [
            self._citacion_con_valor(
                self.tarifa, Decimal('100000'), inicio + timedelta(days=indice + 1)
            )
            for indice in range(13)
        ]
        preview = generar_preview_impacto(
            self.terramar.pk, '-2.9', inicio.date(),
            (inicio + timedelta(days=30)).date(),
        )
        ids = {citacion.pk for citacion in citaciones}
        self.assertEqual(
            {linea.citacion_id for linea in preview.citaciones_elegibles}, ids
        )
        ajuste = aplicar_ajuste_tarifas(
            empresa_id=self.terramar.pk, tipo_ajuste=AJUSTE_TARIFA.TIPO_ICT,
            porcentaje='-2.9', fecha_inicio=inicio.date(),
            fecha_vencimiento=(inicio + timedelta(days=30)).date(),
            usuario=self.control, fuente='INE', periodo_ict='Julio 2026',
            snapshot_preview=preview.snapshot(),
        )
        self.assertEqual(ajuste.detalles_citaciones.count(), 13)
        self.assertEqual(
            AJUSTE_TARIFA_CITACION_DETALLE.objects.filter(
                AJT_NID=ajuste, CI_NID_id__in=ids
            ).count(),
            13,
        )
        self.assertTrue(all(
            CITACION.objects.get(pk=citacion.pk).CI_NVALORTARIFA == Decimal('97100')
            for citacion in citaciones
        ))

    def test_error_tecnico_aplicar_ict_no_devuelve_500(self):
        self._login_empresa(self.control, self.terramar)
        sesion = self.client.session
        sesion['ict_acumulado_6_meses_validado'] = self._ict_validado()
        sesion.save()
        preview = self.client.get(reverse('tg_ict_preview'))
        with patch(
            'apps.home.tarifa_ajuste_views.aplicar_ajuste_tarifas',
            side_effect=RuntimeError('falla tecnica simulada'),
        ):
            respuesta = self.client.post(
                reverse('tg_ict_aplicar'),
                {'preview_token': preview.context['preview_token']},
                follow=True,
            )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta, 'No fue posible aplicar el ajuste. No se realizaron cambios.'
        )

    def test_estado_visual_de_variacion_despues_de_reversa(self):
        self._login_empresa(self.control, self.terramar)

        disponible = self.client.get(reverse('tg_listall'))
        self.assertContains(
            disponible,
            f'id="estado-concepto-{self.concepto.pk}" '
            'class="badge badge-info">DISPONIBLE / SIN APLICAR</span>',
        )

        ajuste = self._aplicar()
        activo = self.client.get(reverse('tg_listall'))
        self.assertContains(
            activo,
            f'id="estado-concepto-{self.concepto.pk}" '
            'class="badge badge-success">ACTIVO</span>',
        )

        reversado = reversar_ultimo_ajuste(
            empresa_id=self.terramar.pk,
            usuario=self.control,
            motivo='Reversa visual Fase 3.1',
        )
        self.concepto.refresh_from_db()
        listado = self.client.get(reverse('tg_listall'))
        historico = self.client.get(
            reverse('tg_variacion_historico', args=[self.concepto.pk])
        )

        self.assertEqual(reversado.pk, ajuste.pk)
        self.assertEqual(reversado.AJT_CESTADO, AJUSTE_TARIFA.ESTADO_REVERSADO)
        self.assertTrue(self.concepto.CVT_BHABILITADO)
        self.assertContains(
            listado,
            f'id="estado-concepto-{self.concepto.pk}" '
            'class="badge badge-secondary">REVERSADO</span>',
        )
        self.assertContains(
            listado, f'id="aplicar-concepto-{self.concepto.pk}"'
        )
        self.assertContains(historico, 'REVERSADO')
        self.assertContains(historico, 'Reversa visual Fase 3.1')
