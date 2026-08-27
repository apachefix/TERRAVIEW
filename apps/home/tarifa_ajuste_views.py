"""Interfaz web de conceptos, previews, aplicaciones y reversas de tarifa."""

import logging

from decimal import Decimal

from django.contrib import messages
from django.core import signing
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .models import AJUSTE_TARIFA, CONCEPTO_VARIACION_TARIFA, EMPRESA
from .services.ajuste_tarifas import (
    AjusteTarifaError,
    ReversaTarifaError,
    actualizar_ajustes_vencidos,
    aplicar_ajuste_tarifas,
    generar_preview_ajuste,
    generar_preview_impacto,
    normalizar_porcentaje,
    normalizar_porcentaje_ict,
    obtener_ultimo_ajuste,
    resolver_porcentaje_ict,
    reversar_ultimo_ajuste,
)
from .services.tarifa_global_service import usuario_es_control_flota
from .views import _empresa_control_flota_o_404
logger = logging.getLogger(__name__)




PREVIEW_SALT = 'tarifa-ajuste-preview-v2'
PREVIEW_MAX_AGE = 4 * 60 * 60


def _exigir_control_flota(request):
    if usuario_es_control_flota(request.user):
        return None
    messages.error(request, 'Solo CONTROL_FLOTA puede administrar variaciones de tarifa.')
    return redirect('/')


def _porcentaje_valido(empresa_id, porcentaje):
    generar_preview_ajuste(empresa_id, porcentaje, tarifa_ids=[])


@require_POST
def crear_concepto(request):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    nombre = (request.POST.get('nombre') or '').strip()
    porcentaje = request.POST.get('porcentaje')
    fecha_inicio = parse_date(request.POST.get('fecha_inicio') or '')
    fecha_vencimiento = parse_date(request.POST.get('fecha_vencimiento') or '')
    try:
        _porcentaje_valido(empresa_id, porcentaje)
        if not nombre:
            raise AjusteTarifaError('Debe informar el nombre de la variacion.')
        if not fecha_inicio or not fecha_vencimiento or fecha_vencimiento < fecha_inicio:
            raise AjusteTarifaError('El periodo efectivo informado no es valido.')
        concepto = CONCEPTO_VARIACION_TARIFA.objects.create(
            EP_NID_id=empresa_id,
            US_NID=request.user,
            CVT_CNOMBRE=nombre,
            CVT_CDESCRIPCION=(request.POST.get('descripcion') or '').strip(),
            CVT_NPORCENTAJEDEFAULT=str(porcentaje).replace(',', '.'),
            CVT_FFECHAINICIODEFAULT=fecha_inicio,
            CVT_FFECHAVENCIMIENTODEFAULT=fecha_vencimiento,
        )
        messages.success(request, f'Concepto "{concepto.CVT_CNOMBRE}" creado correctamente.')
    except AjusteTarifaError as exc:
        messages.error(request, str(exc))
    return redirect('tg_listall')


@require_POST
def cambiar_estado_concepto(request, pk):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    concepto = get_object_or_404(CONCEPTO_VARIACION_TARIFA, pk=pk, EP_NID_id=empresa_id)
    concepto.CVT_BHABILITADO = not concepto.CVT_BHABILITADO
    concepto.save(update_fields=['CVT_BHABILITADO'])
    messages.success(request, 'Estado del concepto actualizado correctamente.')
    return redirect('tg_listall')


def _parametros_preview(request, concepto=None, ict=None):
    hoy = timezone.localdate()
    porcentaje_default = ict.get('acumulado') if ict else concepto.CVT_NPORCENTAJEDEFAULT
    inicio_default = concepto.CVT_FFECHAINICIODEFAULT if concepto else hoy
    vencimiento_default = concepto.CVT_FFECHAVENCIMIENTODEFAULT if concepto else hoy
    parametros = {
        'porcentaje': request.POST.get(
            'porcentaje',
            request.GET.get('porcentaje', str(porcentaje_default or '')),
        ),
        'fecha_inicio': request.POST.get(
            'fecha_inicio', inicio_default.isoformat() if inicio_default else ''
        ),
        'fecha_vencimiento': request.POST.get(
            'fecha_vencimiento', vencimiento_default.isoformat() if vencimiento_default else ''
        ),
        'observacion': request.POST.get('observacion', ''),
    }
    if ict:
        parametros['ajuste_manual'] = request.POST.get(
            'ajuste_manual', request.GET.get('ajuste_manual', '')
        )
        parametros['motivo_manual'] = request.POST.get(
            'motivo_manual', request.GET.get('motivo_manual', '')
        )
    return parametros


def preview_variacion(request, pk):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    concepto = get_object_or_404(
        CONCEPTO_VARIACION_TARIFA,
        pk=pk,
        EP_NID_id=empresa_id,
        CVT_BHABILITADO=True,
    )
    return _render_preview(
        request, empresa_id, _parametros_preview(request, concepto=concepto), concepto=concepto
    )


def preview_ict(request):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    ict = request.session.get('ict_acumulado_6_meses_validado')
    if not ict:
        messages.error(request, 'Primero debe consultar un ICT valido desde INE.')
        return redirect('tg_listall')
    return _render_preview(
        request, empresa_id, _parametros_preview(request, ict=ict), ict=ict
    )


def _render_preview(request, empresa_id, parametros, concepto=None, ict=None):
    impacto, error, preview_token = None, None, ''
    inicio = parse_date(parametros['fecha_inicio'])
    vencimiento = parse_date(parametros['fecha_vencimiento'])
    tipo = (
        AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES
        if ict else AJUSTE_TARIFA.TIPO_VARIACION_MANUAL
    )
    try:
        if ict:
            (
                ict_calculado,
                ajuste_manual,
                porcentaje_normalizado,
                origen_porcentaje,
                motivo_manual,
            ) = resolver_porcentaje_ict(
                ict.get('acumulado'),
                parametros.get('ajuste_manual'),
                parametros.get('motivo_manual'),
            )
            parametros['porcentaje'] = str(porcentaje_normalizado)
            parametros['ajuste_manual_normalizado'] = ajuste_manual
            parametros['origen_porcentaje'] = origen_porcentaje
            parametros['motivo_manual'] = motivo_manual
        else:
            porcentaje_normalizado = normalizar_porcentaje(parametros['porcentaje'])
        impacto = generar_preview_impacto(
            empresa_id, porcentaje_normalizado, inicio, vencimiento
        )
        payload = {
            'empresa_id': empresa_id,
            'tipo_ajuste': tipo,
            'concepto_id': concepto.pk if concepto else None,
            'porcentaje': str(porcentaje_normalizado),
            'fecha_inicio': inicio.isoformat(),
            'fecha_vencimiento': vencimiento.isoformat(),
            'observacion': parametros['observacion'],
            'periodo_ict': ict.get('periodo', '') if ict else '',
            'ict_calculado': ict.get('acumulado') if ict else None,
            'ajuste_manual': (
                None if not ict or ajuste_manual is None else str(ajuste_manual)
            ),
            'origen_porcentaje': origen_porcentaje if ict else None,
            'motivo_manual': motivo_manual if ict else '',
            'periodo_ict_inicio': ict.get('periodo_inicio') if ict else None,
            'periodo_ict_fin': ict.get('periodo_fin') if ict else None,
            'componentes_ict': ict.get('componentes', []) if ict else [],
            'snapshot': impacto.snapshot(),
        }
        preview_token = signing.dumps(payload, salt=PREVIEW_SALT, compress=True)
    except (AjusteTarifaError, AttributeError, ValueError) as exc:
        error = str(exc)

    duplicado_ict = False
    if ict:
        duplicado_ict = AJUSTE_TARIFA.objects.filter(
            EP_NID_id=empresa_id,
            AJT_CTIPO=AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES,
            AJT_FPERIODOICTINICIO=parse_date(ict.get('periodo_inicio', '')),
            AJT_FPERIODOICTFIN=parse_date(ict.get('periodo_fin', '')),
        ).exists()
    return render(request, 'home/TARIFA/tg_ajuste_preview.html', {
        'concepto': concepto,
        'ict': ict,
        'empresa_activa': EMPRESA.objects.filter(pk=empresa_id).first(),
        'tipo_ajuste': tipo,
        'parametros': parametros,
        'impacto': impacto,
        'lineas': impacto.tarifas if impacto else [],
        'preview_token': preview_token,
        'error': error,
        'duplicado_ict': duplicado_ict,
    })

@require_POST
def aplicar_variacion(request, pk):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    concepto = get_object_or_404(
        CONCEPTO_VARIACION_TARIFA,
        pk=pk,
        EP_NID_id=empresa_id,
        CVT_BHABILITADO=True,
    )
    return _aplicar_desde_post(request, empresa_id, concepto=concepto)


@require_POST
def aplicar_ict(request):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    ict = request.session.get('ict_acumulado_6_meses_validado')
    if not ict:
        messages.error(request, 'La consulta ICT ya no esta disponible; consulte nuevamente.')
        return redirect('tg_listall')
    return _aplicar_desde_post(request, empresa_id, ict=ict)


def _cargar_preview_firmado(request):
    token = request.POST.get('preview_token') or ''
    try:
        return signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired) as exc:
        raise AjusteTarifaError(
            'La vista previa no es válida. Recalcule el ajuste.'
        ) from exc


def _aplicar_desde_post(request, empresa_id, concepto=None, ict=None):
    destino_error = 'tg_ict_preview' if ict else 'tg_variacion_preview'
    try:
        payload = _cargar_preview_firmado(request)
        tipo = (
            AJUSTE_TARIFA.TIPO_ICT_ACUMULADO_6_MESES
            if ict else AJUSTE_TARIFA.TIPO_VARIACION_MANUAL
        )
        if (
            payload.get('empresa_id') != empresa_id
            or payload.get('tipo_ajuste') != tipo
            or payload.get('concepto_id') != (concepto.pk if concepto else None)
        ):
            raise AjusteTarifaError(
                'La vista previa no corresponde a la empresa o ajuste activo.'
            )
        if ict and (
            Decimal(payload.get('ict_calculado')) != normalizar_porcentaje_ict(
                ict.get('acumulado')
            )
            or payload.get('periodo_ict') != ict.get('periodo', '')
            or payload.get('periodo_ict_inicio') != ict.get('periodo_inicio')
            or payload.get('periodo_ict_fin') != ict.get('periodo_fin')
            or payload.get('componentes_ict') != ict.get('componentes', [])
        ):
            raise AjusteTarifaError(
                'El ICT validado cambió. Consulte nuevamente la fuente.'
            )

        ajuste = aplicar_ajuste_tarifas(
            empresa_id=empresa_id,
            tipo_ajuste=tipo,
            porcentaje=payload['porcentaje'],
            fecha_inicio=parse_date(payload['fecha_inicio']),
            fecha_vencimiento=parse_date(payload['fecha_vencimiento']),
            usuario=request.user,
            concepto=concepto,
            fuente=ict.get('fuente', '') if ict else '',
            url_fuente=ict.get('url', '') if ict else '',
            periodo_ict=ict.get('periodo', '') if ict else '',
            observacion=(payload.get('observacion') or '').strip(),
            snapshot_preview=payload['snapshot'],
            ict_calculado=payload.get('ict_calculado'),
            periodo_ict_inicio=parse_date(
                payload.get('periodo_ict_inicio') or ''
            ),
            periodo_ict_fin=parse_date(payload.get('periodo_ict_fin') or ''),
            componentes_ict=payload.get('componentes_ict') or [],
            ajuste_manual=payload.get('ajuste_manual'),
            motivo_manual=payload.get('motivo_manual') or '',
        )
        messages.success(
            request,
            'Ajuste aplicado a %s tarifas y %s citaciones pendientes de Proforma.' % (
                ajuste.detalles.count(), ajuste.detalles_citaciones.count()
            ),
        )
        if ict:
            request.session.pop('ict_acumulado_6_meses_validado', None)
        return redirect('tg_listall')
    except AjusteTarifaError as exc:
        messages.error(request, str(exc))
        if concepto:
            return redirect(destino_error, pk=concepto.pk)
        return redirect(destino_error)
    except Exception:
        logger.exception(
            'Error aplicando ajuste ICT' if ict
            else 'Error aplicando variacion de tarifa'
        )
        messages.error(
            request, 'No fue posible aplicar el ajuste. No se realizaron cambios.'
        )
        return redirect(
            destino_error, **({'pk': concepto.pk} if concepto else {})
        )

def historico_concepto(request, pk):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    concepto = get_object_or_404(CONCEPTO_VARIACION_TARIFA, pk=pk, EP_NID_id=empresa_id)
    ajustes = AJUSTE_TARIFA.objects.filter(
        EP_NID_id=empresa_id, CVT_NID=concepto
    ).select_related('US_NID', 'REVERSADO_POR').prefetch_related(
        'detalles', 'detalles_citaciones'
    )
    return render(request, 'home/TARIFA/tg_variacion_historico.html', {
        'concepto': concepto,
        'ajustes': ajustes,
    })


def reversar_ajuste(request):
    rechazo = _exigir_control_flota(request)
    if rechazo:
        return rechazo
    empresa_id = _empresa_control_flota_o_404(request)
    actualizar_ajustes_vencidos(empresa_id)
    ultimo = obtener_ultimo_ajuste(empresa_id)
    if request.method == 'POST':
        try:
            reversar_ultimo_ajuste(
                empresa_id=empresa_id,
                usuario=request.user,
                motivo=(request.POST.get('motivo') or '').strip(),
            )
            messages.success(request, 'El ultimo ajuste fue reversado correctamente.')
            return redirect('tg_listall')
        except ReversaTarifaError as exc:
            messages.error(request, str(exc))
            return redirect('tg_reversar_ajuste')
    return render(request, 'home/TARIFA/tg_ajuste_reversar.html', {'ajuste': ultimo})
