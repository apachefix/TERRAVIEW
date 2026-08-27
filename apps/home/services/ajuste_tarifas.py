"""Motor transaccional comun para ICT y variaciones manuales de tarifas."""

from dataclasses import dataclass
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.home.models import (
    AJUSTE_TARIFA,
    AJUSTE_TARIFA_CITACION_DETALLE,
    AJUSTE_TARIFA_DETALLE,
    CITACION,
    CITACION_PROFORMA,
    TARIFA_GLOBAL,
    TARIFA_LOG,
)


class AjusteTarifaError(RuntimeError):
    pass


class DatosPreviewCambiaron(AjusteTarifaError):
    pass


class ReversaTarifaError(AjusteTarifaError):
    pass


@dataclass(frozen=True)
class LineaPreviewAjuste:
    tarifa_id: int
    transporte: str
    ruta: str
    tipo_tarifa: str
    valor_actual: Decimal
    porcentaje: Decimal
    valor_nuevo: Decimal
    diferencia: Decimal


@dataclass(frozen=True)
class LineaPreviewCitacion:
    citacion_id: int
    fecha: object
    transporte: str
    ruta: str
    tarifa_id: int | None
    valor_actual: Decimal | None
    valor_tarifa_anterior: Decimal | None
    valor_nuevo: Decimal | None
    diferencia: Decimal | None
    motivo: str


@dataclass
class PreviewImpactoAjuste:
    tarifas: list
    citaciones_elegibles: list
    citaciones_proformadas: list
    citaciones_revision: list
    citaciones_excluidas: list

    def snapshot(self):
        return {
            'tarifas': [
                {'id': linea.tarifa_id, 'valor': str(linea.valor_actual)}
                for linea in self.tarifas
            ],
            'citaciones': {
                'elegibles': _snapshot_citaciones(self.citaciones_elegibles),
                'proformadas': _snapshot_citaciones(self.citaciones_proformadas),
                'revision': _snapshot_citaciones(self.citaciones_revision),
                'excluidas': _snapshot_citaciones(self.citaciones_excluidas),
            },
        }


def _snapshot_citaciones(lineas):
    return [
        {
            'id': linea.citacion_id,
            'tarifa_id': linea.tarifa_id,
            'valor': None if linea.valor_actual is None else str(linea.valor_actual),
            'motivo': linea.motivo,
        }
        for linea in lineas
    ]


def normalizar_porcentaje(valor):
    try:
        porcentaje = Decimal(str(valor).strip().replace(',', '.'))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise AjusteTarifaError('El porcentaje informado no es valido.') from exc
    if not porcentaje.is_finite() or porcentaje <= Decimal('-100'):
        raise AjusteTarifaError('El porcentaje debe ser mayor que -100 %.')
    if porcentaje > Decimal('9999.9999'):
        raise AjusteTarifaError('El porcentaje informado excede el maximo permitido.')
    return porcentaje.quantize(Decimal('0.0001'))


def normalizar_porcentaje_ict(valor):
    porcentaje = normalizar_porcentaje(valor)
    if porcentaje >= Decimal('100'):
        raise AjusteTarifaError('El reajuste ICT debe ser menor que 100 %.')
    return porcentaje

def resolver_porcentaje_ict(ict_calculado, ajuste_manual=None, motivo_manual=''):
    """Resuelve el porcentaje efectivo: el manual reemplaza al ICT."""
    calculado = normalizar_porcentaje_ict(ict_calculado)
    manual_vacio = ajuste_manual is None or (
        isinstance(ajuste_manual, str) and not ajuste_manual.strip()
    )
    if manual_vacio:
        return (
            calculado, None, calculado,
            AJUSTE_TARIFA.ORIGEN_PORCENTAJE_ICT, '',
        )

    manual = normalizar_porcentaje_ict(ajuste_manual)
    motivo = (motivo_manual or '').strip()
    if not motivo:
        raise AjusteTarifaError('Debe informar el motivo del ajuste manual.')
    return (
        calculado, manual, manual,
        AJUSTE_TARIFA.ORIGEN_PORCENTAJE_MANUAL, motivo,
    )


def validar_vigencia(fecha_inicio, fecha_vencimiento):
    if not fecha_inicio or not fecha_vencimiento:
        raise AjusteTarifaError('Debe informar fecha de inicio y termino efectivo.')
    if fecha_vencimiento < fecha_inicio:
        raise AjusteTarifaError('La fecha de termino efectivo no puede ser anterior al inicio.')


def calcular_valor_ajustado(valor_actual, porcentaje, divisa='CLP'):
    actual = Decimal(valor_actual)
    pct = normalizar_porcentaje(porcentaje)
    resultado = actual * (Decimal('1') + pct / Decimal('100'))
    precision = Decimal('1') if str(divisa or '').upper() == 'CLP' else Decimal('0.00001')
    return resultado.quantize(precision, rounding=ROUND_HALF_UP)


def _query_tarifas(empresa_id, tarifa_ids=None, bloquear=False):
    tarifas = TARIFA_GLOBAL.objects.filter(
        EP_NID_id=empresa_id,
        TAR_BHABILITADO=True,
    ).select_related('SN_NID', 'RUT_NID').order_by('id')
    if tarifa_ids is not None:
        ids = [int(valor) for valor in tarifa_ids]
        tarifas = tarifas.filter(pk__in=ids)
    if bloquear:
        tarifas = tarifas.select_for_update()
    return tarifas


def _lineas_tarifas(tarifas, porcentaje):
    pct = normalizar_porcentaje(porcentaje)
    return [
        LineaPreviewAjuste(
            tarifa_id=tarifa.pk,
            transporte=str(tarifa.SN_NID),
            ruta=str(tarifa.RUT_NID),
            tipo_tarifa=tarifa.TAR_CTIPOTARIFA,
            valor_actual=tarifa.TAR_NVALOR,
            porcentaje=pct,
            valor_nuevo=calcular_valor_ajustado(
                tarifa.TAR_NVALOR, pct, tarifa.TAR_CDIVISA
            ),
            diferencia=(
                calcular_valor_ajustado(tarifa.TAR_NVALOR, pct, tarifa.TAR_CDIVISA)
                - tarifa.TAR_NVALOR
            ),
        )
        for tarifa in tarifas
    ]


def generar_preview_ajuste(empresa_id, porcentaje, tarifa_ids=None):
    return _lineas_tarifas(
        list(_query_tarifas(empresa_id, tarifa_ids=tarifa_ids)), porcentaje
    )


def _linea_citacion(citacion, tarifa_linea, motivo):
    tarifa = citacion.TAR_NID
    nuevo = tarifa_linea.valor_nuevo if tarifa_linea else None
    actual = citacion.CI_NVALORTARIFA
    return LineaPreviewCitacion(
        citacion_id=citacion.pk,
        fecha=citacion.CI_FFECHACITACION,
        transporte=str(tarifa.SN_NID) if tarifa else '-',
        ruta=str(tarifa.RUT_NID) if tarifa else '-',
        tarifa_id=citacion.TAR_NID_id,
        valor_actual=actual,
        valor_tarifa_anterior=tarifa_linea.valor_actual if tarifa_linea else None,
        valor_nuevo=nuevo,
        diferencia=(nuevo - actual) if nuevo is not None and actual is not None else None,
        motivo=motivo,
    )


def _clasificar_citaciones(
    empresa_id, fecha_inicio, fecha_vencimiento, lineas_tarifas, bloquear=False
):
    tarifa_por_id = {linea.tarifa_id: linea for linea in lineas_tarifas}
    citaciones = CITACION.objects.filter(
        EP_NID_id=empresa_id,
        CI_FFECHACITACION__date__range=(fecha_inicio, fecha_vencimiento),
    ).select_related('TAR_NID', 'TAR_NID__SN_NID', 'TAR_NID__RUT_NID').order_by('id')
    if bloquear:
        citaciones = citaciones.select_for_update(of=('self',))
    citaciones = list(citaciones)
    proformadas = set(CITACION_PROFORMA.objects.filter(
        CI_NID_id__in=[citacion.pk for citacion in citaciones]
    ).values_list('CI_NID_id', flat=True))

    elegibles, con_proforma, revision, excluidas = [], [], [], []
    for citacion in citaciones:
        linea_tarifa = tarifa_por_id.get(citacion.TAR_NID_id)
        if citacion.pk in proformadas:
            con_proforma.append(_linea_citacion(
                citacion, linea_tarifa, 'YA INCORPORADA A PROFORMA'
            ))
        elif not citacion.CI_BHABILITADO:
            excluidas.append(_linea_citacion(citacion, linea_tarifa, 'CITACION INHABILITADA'))
        elif not citacion.TAR_NID_id:
            excluidas.append(_linea_citacion(citacion, None, 'SIN TARIFA ASOCIADA'))
        elif not linea_tarifa:
            excluidas.append(_linea_citacion(
                citacion, None, 'TARIFA FUERA DEL LOTE REAJUSTADO'
            ))
        elif (
            citacion.CI_NVALORTARIFA is None
            or Decimal(citacion.CI_NVALORTARIFA) != Decimal(linea_tarifa.valor_actual)
        ):
            revision.append(_linea_citacion(
                citacion, linea_tarifa, 'VALOR DISTINTO AL MAESTRO PREVIO'
            ))
        else:
            elegibles.append(_linea_citacion(citacion, linea_tarifa, 'ELEGIBLE'))
    return elegibles, con_proforma, revision, excluidas


def generar_preview_impacto(
    empresa_id, porcentaje, fecha_inicio, fecha_vencimiento, tarifa_ids=None
):
    validar_vigencia(fecha_inicio, fecha_vencimiento)
    tarifas = list(_query_tarifas(empresa_id, tarifa_ids=tarifa_ids))
    lineas_tarifas = _lineas_tarifas(tarifas, porcentaje)
    elegibles, proformadas, revision, excluidas = _clasificar_citaciones(
        empresa_id, fecha_inicio, fecha_vencimiento, lineas_tarifas
    )
    return PreviewImpactoAjuste(
        tarifas=lineas_tarifas,
        citaciones_elegibles=elegibles,
        citaciones_proformadas=proformadas,
        citaciones_revision=revision,
        citaciones_excluidas=excluidas,
    )


@transaction.atomic
def aplicar_ajuste_tarifas(
    *, empresa_id, tipo_ajuste, porcentaje, fecha_inicio, fecha_vencimiento,
    usuario, concepto=None, tarifa_ids=None, fuente='', url_fuente='',
    periodo_ict='', observacion='', snapshot_preview=None,
    ict_calculado=None, periodo_ict_inicio=None, periodo_ict_fin=None,
    componentes_ict=None, ajuste_manual=None, motivo_manual='',
):
    es_ict_acumulado = (
        tipo_ajuste == AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES
    )
    pct = (
        normalizar_porcentaje_ict(porcentaje)
        if es_ict_acumulado
        else normalizar_porcentaje(porcentaje)
    )
    validar_vigencia(fecha_inicio, fecha_vencimiento)
    if tipo_ajuste not in {AJUSTE_TARIFA.TIPO_ICT, AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES, AJUSTE_TARIFA.TIPO_VARIACION_MANUAL}:
        raise AjusteTarifaError('Tipo de ajuste no permitido.')
    if tipo_ajuste == AJUSTE_TARIFA.TIPO_VARIACION_MANUAL:
        if not concepto or concepto.EP_NID_id != empresa_id or not concepto.CVT_BHABILITADO:
            raise AjusteTarifaError('El concepto no pertenece a la empresa activa o esta inhabilitado.')
    elif concepto is not None:
        raise AjusteTarifaError('Un ajuste ICT no debe asociarse a un concepto manual.')

    if es_ict_acumulado:
        calculado, manual, aplicado, origen, motivo = resolver_porcentaje_ict(
            ict_calculado, ajuste_manual, motivo_manual
        )
        if pct != aplicado:
            raise AjusteTarifaError(
                'El porcentaje a aplicar no coincide con el ICT o ajuste manual informado.'
            )
        pct = aplicado
        if (
            not periodo_ict_inicio
            or not periodo_ict_fin
            or periodo_ict_fin < periodo_ict_inicio
            or not isinstance(componentes_ict, (list, tuple))
            or len(componentes_ict) != 6
        ):
            raise AjusteTarifaError(
                'El acumulado ICT requiere exactamente 6 períodos oficiales válidos.'
            )
    else:
        calculado = None
        manual = None
        origen = None
        motivo = ''
    tarifas = list(_query_tarifas(
        empresa_id, tarifa_ids=tarifa_ids, bloquear=True
    ))
    if not tarifas:
        raise AjusteTarifaError('No existen tarifas habilitadas para aplicar el ajuste.')
    lineas_tarifas = _lineas_tarifas(tarifas, pct)
    elegibles, proformadas, revision, excluidas = _clasificar_citaciones(
        empresa_id, fecha_inicio, fecha_vencimiento, lineas_tarifas, bloquear=True
    )
    impacto = PreviewImpactoAjuste(
        tarifas=lineas_tarifas,
        citaciones_elegibles=elegibles,
        citaciones_proformadas=proformadas,
        citaciones_revision=revision,
        citaciones_excluidas=excluidas,
    )
    if snapshot_preview is not None and impacto.snapshot() != snapshot_preview:
        raise DatosPreviewCambiaron(
            'Una o más tarifas cambiaron desde la vista previa. Genere nuevamente el cálculo; los datos cambiaron.'
        )

    estado = (
        AJUSTE_TARIFA.ESTADO_VENCIDO
        if fecha_vencimiento < timezone.localdate()
        else AJUSTE_TARIFA.ESTADO_APLICADO
    )
    ajuste = AJUSTE_TARIFA.objects.create(
        EP_NID_id=empresa_id,
        CVT_NID=concepto,
        US_NID=usuario,
        AJT_CTIPO=tipo_ajuste,
        AJT_NPORCENTAJE=pct,
        AJT_NPORCENTAJECALCULADO=calculado,
        AJT_NPORCENTAJEMANUAL=manual,
        AJT_CORIGENPORCENTAJE=origen,
        AJT_CMOTIVOMANUAL=motivo,
        AJT_FPERIODOICTINICIO=periodo_ict_inicio,
        AJT_FPERIODOICTFIN=periodo_ict_fin,
        AJT_CCOMPONENTESICT=(
            json.dumps(componentes_ict, ensure_ascii=False, separators=(',', ':'))
            if componentes_ict else ''
        ),
        AJT_FFECHAINICIO=fecha_inicio,
        AJT_FFECHAVENCIMIENTO=fecha_vencimiento,
        AJT_CESTADO=estado,
        AJT_CFUENTE=fuente or '',
        AJT_CURLFUENTE=url_fuente or '',
        AJT_CPERIODOICT=periodo_ict or '',
        AJT_COBSERVACION=observacion or '',
    )
    ahora = timezone.now()
    tarifa_por_id = {tarifa.pk: tarifa for tarifa in tarifas}
    linea_por_id = {linea.tarifa_id: linea for linea in lineas_tarifas}
    for tarifa in tarifas:
        linea = linea_por_id[tarifa.pk]
        AJUSTE_TARIFA_DETALLE.objects.create(
            AJT_NID=ajuste,
            TAR_NID=tarifa,
            AJTD_NVALORANTERIOR=linea.valor_actual,
            AJTD_NVALORNUEVO=linea.valor_nuevo,
            AJTD_NPORCENTAJE=pct,
        )
        tarifa.TAR_NVALORPREVIO = linea.valor_actual
        tarifa.TAR_NVALOR = linea.valor_nuevo
        tarifa.MODIFICADO_POR = usuario
        tarifa.TAR_FFECHAULTIMAMODIFICACION = ahora
        tarifa.save(update_fields=[
            'TAR_NVALORPREVIO', 'TAR_NVALOR', 'MODIFICADO_POR',
            'TAR_FFECHAULTIMAMODIFICACION',
        ])
        TARIFA_LOG.objects.create(
            TAR_NID=tarifa,
            US_NID=usuario,
            TL_FFECHAREGISTRO=ahora,
            TL_NVALOR=linea.valor_nuevo,
        )

    citaciones_por_id = {
        citacion.pk: citacion
        for citacion in CITACION.objects.select_for_update().filter(
            pk__in=[linea.citacion_id for linea in elegibles],
            EP_NID_id=empresa_id,
        )
    }
    for linea in elegibles:
        citacion = citaciones_por_id[linea.citacion_id]
        nuevo = linea_por_id[citacion.TAR_NID_id].valor_nuevo
        anterior = citacion.CI_NVALORTARIFA
        citacion.CI_NVALORTARIFA = nuevo
        citacion.save(update_fields=['CI_NVALORTARIFA'])
        AJUSTE_TARIFA_CITACION_DETALLE.objects.create(
            AJT_NID=ajuste,
            CI_NID=citacion,
            TAR_NID=tarifa_por_id[citacion.TAR_NID_id],
            EP_NID_id=empresa_id,
            US_NID=usuario,
            AJTC_NVALORANTERIOR=anterior,
            AJTC_NVALORNUEVO=nuevo,
        )
    return ajuste


def actualizar_ajustes_vencidos(empresa_id, hoy=None):
    hoy = hoy or timezone.localdate()
    return AJUSTE_TARIFA.objects.filter(
        EP_NID_id=empresa_id,
        AJT_CESTADO=AJUSTE_TARIFA.ESTADO_APLICADO,
        AJT_FFECHAVENCIMIENTO__lt=hoy,
    ).update(AJT_CESTADO=AJUSTE_TARIFA.ESTADO_VENCIDO)


def obtener_ultimo_ajuste(empresa_id):
    return AJUSTE_TARIFA.objects.filter(EP_NID_id=empresa_id).select_related(
        'CVT_NID', 'US_NID', 'REVERSADO_POR'
    ).prefetch_related('detalles', 'detalles_citaciones').order_by(
        '-AJT_FFECHAAPLICACION', '-id'
    ).first()


@transaction.atomic
def reversar_ultimo_ajuste(*, empresa_id, usuario, motivo):
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReversaTarifaError('Debe informar el motivo de la reversa.')
    ultimo = AJUSTE_TARIFA.objects.select_for_update().filter(
        EP_NID_id=empresa_id
    ).order_by('-AJT_FFECHAAPLICACION', '-id').first()
    if not ultimo or ultimo.AJT_CESTADO == AJUSTE_TARIFA.ESTADO_REVERSADO:
        raise ReversaTarifaError('No existe un ultimo ajuste vigente que pueda reversarse.')

    detalles = list(AJUSTE_TARIFA_DETALLE.objects.filter(
        AJT_NID=ultimo,
        TAR_NID__EP_NID_id=empresa_id,
    ).order_by('TAR_NID_id'))
    if not detalles:
        raise ReversaTarifaError('El ajuste no contiene detalle historico para reversar.')
    tarifas = {
        tarifa.pk: tarifa
        for tarifa in TARIFA_GLOBAL.objects.select_for_update().filter(
            pk__in=[detalle.TAR_NID_id for detalle in detalles],
            EP_NID_id=empresa_id,
        )
    }
    if len(tarifas) != len(detalles) or any(
        tarifas[detalle.TAR_NID_id].TAR_NVALOR != detalle.AJTD_NVALORNUEVO
        for detalle in detalles
    ):
        raise ReversaTarifaError(
            'No es posible reversar automaticamente porque una o mas tarifas '
            'fueron modificadas posteriormente.'
        )

    detalles_citaciones = list(AJUSTE_TARIFA_CITACION_DETALLE.objects.filter(
        AJT_NID=ultimo,
        EP_NID_id=empresa_id,
    ).order_by('CI_NID_id'))
    citaciones = {
        citacion.pk: citacion
        for citacion in CITACION.objects.select_for_update().filter(
            pk__in=[detalle.CI_NID_id for detalle in detalles_citaciones],
            EP_NID_id=empresa_id,
        )
    }
    proformadas = CITACION_PROFORMA.objects.filter(
        CI_NID_id__in=list(citaciones)
    ).exists()
    citaciones_invalidas = (
        len(citaciones) != len(detalles_citaciones)
        or proformadas
        or any(
            not citaciones[detalle.CI_NID_id].CI_BHABILITADO
            or citaciones[detalle.CI_NID_id].TAR_NID_id != detalle.TAR_NID_id
            or citaciones[detalle.CI_NID_id].CI_NVALORTARIFA != detalle.AJTC_NVALORNUEVO
            for detalle in detalles_citaciones
        )
    )
    if citaciones_invalidas:
        raise ReversaTarifaError(
            'No es posible reversar automaticamente este ajuste porque una o mas '
            'citaciones ya fueron proformadas o modificadas posteriormente.'
        )

    ahora = timezone.now()
    for detalle in detalles:
        tarifa = tarifas[detalle.TAR_NID_id]
        tarifa.TAR_NVALORPREVIO = tarifa.TAR_NVALOR
        tarifa.TAR_NVALOR = detalle.AJTD_NVALORANTERIOR
        tarifa.MODIFICADO_POR = usuario
        tarifa.TAR_FFECHAULTIMAMODIFICACION = ahora
        tarifa.save(update_fields=[
            'TAR_NVALORPREVIO', 'TAR_NVALOR', 'MODIFICADO_POR',
            'TAR_FFECHAULTIMAMODIFICACION',
        ])
        TARIFA_LOG.objects.create(
            TAR_NID=tarifa,
            US_NID=usuario,
            TL_FFECHAREGISTRO=ahora,
            TL_NVALOR=detalle.AJTD_NVALORANTERIOR,
        )
    for detalle in detalles_citaciones:
        citacion = citaciones[detalle.CI_NID_id]
        citacion.CI_NVALORTARIFA = detalle.AJTC_NVALORANTERIOR
        citacion.save(update_fields=['CI_NVALORTARIFA'])

    ultimo.AJT_CESTADO = AJUSTE_TARIFA.ESTADO_REVERSADO
    ultimo.REVERSADO_POR = usuario
    ultimo.AJT_FFECHAREVERSA = ahora
    ultimo.AJT_CMOTIVOREVERSA = motivo
    ultimo.save(update_fields=[
        'AJT_CESTADO', 'REVERSADO_POR', 'AJT_FFECHAREVERSA',
        'AJT_CMOTIVOREVERSA',
    ])
    return ultimo
