import json
import os
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.core import signing
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CAMION_PATIO,
    CAMION_PATIO_ADJUNTO,
    CITACION,
    CITACION_DOCUMENTO,
    CITACION_EXTRA,
    CITACION_ITEM,
    CITACION_PROFORMA,
    DATO_OPERACION,
    DOCUMENTO_PROFORMA,
    EXTRA,
    EXTRA_PROFORMA,
    LINEA_PROFORMA,
    OPERACION_PLANTA_LOG,
    PERFIL_USUARIO,
    PROFORMA,
    SYSLOGGER,
)
from apps.home.services.proforma_mensual import (
    categoria_proforma, obtener_o_crear_borrador_extras, periodo_citacion,
    recalcular_totales, tipo_operacion_proforma,
)
from apps.home.services.proforma_service import (
    PERMISO_BORRAR_PROFORMA,
    PERMISO_PROFORMA_CITACIONES,
    usuario_tiene_empresa,
    usuario_tiene_permiso_pro_cit,
)


EMPRESA_TERRAMAR = 1
ESTADO_BORRADOR = 'CREADO'
ESTADO_APROBADO = 'APROBADO'
ESTADO_AUTORIZADO = 'AUTORIZADO'
CODIGO_TICKET_ENTRADA = 'OP_TICKET_PESAJE_ENT'
CODIGO_TICKET_SALIDA = 'OP_TICKET_PESAJE_SAL'
CODIGO_TICKET_MOP = 'OP_TICKET_MOP_SAL_DESP_TERRAMAR'
CODIGO_TIMBRADO = 'OP_TIMBRADO_TERRAMAR'
CUANTIZACION_MONEDA = Decimal('0.00001')
SALT_BORRAR_CARPETA = 'terramar.proforma.borrar-carpeta.v1'


class ProformaTerramarError(ValueError):
    pass


def usuario_puede_proforma_terramar(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or (
                usuario_tiene_permiso_pro_cit(user, PERMISO_PROFORMA_CITACIONES)
                and usuario_tiene_empresa(user, EMPRESA_TERRAMAR)
            )
        )
    )


def usuario_puede_aprobar_borrador(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or PERFIL_USUARIO.objects.filter(
                US_NID=user,
                PE_BHABILITADO=True,
                PR_NID__PR_BHABILITADO=True,
                PR_NID__PR_CCODIGO__iexact='CONTROL_FLOTA',
            ).exists()
        )
    )

def usuario_puede_borrar_carpeta(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or usuario_tiene_permiso_pro_cit(user, PERMISO_BORRAR_PROFORMA)
        )
    )


def firma_borrado_carpeta(proforma):
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    payload = {
        'proforma': proforma.pk,
        'categoria': categoria,
        'estado': proforma.PRO_CESTADO,
        'borrador': bool(proforma.PRO_BBORRADOR),
        'doc_entry': proforma.PRO_DOC_ENTRY,
        'doc_num': str(proforma.PRO_DOC_NUM or ''),
        'citaciones': list(CITACION_PROFORMA.objects.filter(
            PRO_NID=proforma
        ).order_by('pk').values_list('pk', flat=True)),
        'extras': list(EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma
        ).order_by('pk').values_list('pk', flat=True)),
    }
    return signing.dumps(payload, salt=SALT_BORRAR_CARPETA, compress=True)


def _validar_firma_borrado(proforma, firma, categoria, citacion_proforma_ids, extra_proforma_ids):
    try:
        payload = signing.loads(
            str(firma or ''), salt=SALT_BORRAR_CARPETA, max_age=7200
        )
    except signing.BadSignature as exc:
        raise ProformaTerramarError(
            'La confirmación expiró o no es válida. Recargue el borrador.'
        ) from exc
    actual = {
        'proforma': proforma.pk,
        'categoria': categoria,
        'estado': proforma.PRO_CESTADO,
        'borrador': bool(proforma.PRO_BBORRADOR),
        'doc_entry': proforma.PRO_DOC_ENTRY,
        'doc_num': str(proforma.PRO_DOC_NUM or ''),
        'citaciones': citacion_proforma_ids,
        'extras': extra_proforma_ids,
    }
    if payload != actual:
        raise ProformaTerramarError(
            'El borrador cambió desde que abrió la pantalla. Recargue antes de borrar.'
        )


@transaction.atomic
def borrar_carpeta_borrador(*, user, proforma_id, firma, confirmacion):
    if str(confirmacion or '').strip().upper() != 'BORRAR':
        raise ProformaTerramarError('Debe escribir BORRAR para confirmar la operación.')
    if not usuario_puede_borrar_carpeta(user):
        raise PermissionError('No tiene permiso para borrar carpetas de Proforma.')
    proforma = obtener_proforma_terramar(proforma_id, user, bloquear=True)
    if not usuario_tiene_empresa(user, EMPRESA_TERRAMAR) and not user.is_superuser:
        raise PermissionError('No tiene acceso a Terramar.')
    if not (
        proforma.PRO_CESTADO == ESTADO_BORRADOR
        and proforma.PRO_BBORRADOR
        and proforma.PRO_DOC_ENTRY is None
        and not str(proforma.PRO_DOC_NUM or '').strip()
    ):
        raise ProformaTerramarError(
            'La Proforma ya no es un borrador eliminable. Recargue la pantalla.'
        )
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    asociaciones = list(
        CITACION_PROFORMA.objects.select_for_update()
        .filter(PRO_NID=proforma).order_by('pk')
    )
    snapshots_extras = list(
        EXTRA_PROFORMA.objects.select_for_update()
        .filter(PRO_NID=proforma).order_by('pk')
    )
    _validar_firma_borrado(
        proforma,
        firma,
        categoria,
        [item.pk for item in asociaciones],
        [item.pk for item in snapshots_extras],
    )
    if DOCUMENTO_PROFORMA.objects.select_for_update().filter(PRO_NID=proforma).exists():
        raise ProformaTerramarError(
            'El borrador tiene documentos de Proforma asociados y no puede borrarse.'
        )
    if LINEA_PROFORMA.objects.select_for_update().filter(PRO_NID=proforma).exists():
        raise ProformaTerramarError(
            'El borrador tiene líneas manuales asociadas y no puede borrarse.'
        )
    if categoria == 'FLETE':
        if snapshots_extras:
            raise ProformaTerramarError(
                'El borrador mezcla Fletes y Extras. Debe separarse antes de borrarlo.'
            )
        citacion_ids = sorted({item.CI_NID_id for item in asociaciones})
        list(CITACION.objects.select_for_update().filter(pk__in=citacion_ids))
        ids_afectados = citacion_ids
        cantidad_citaciones = len(citacion_ids)
        cantidad_extras = 0
    else:
        if asociaciones:
            raise ProformaTerramarError(
                'La Proforma de Extras contiene snapshots de Fletes y requiere revisión.'
            )
        citacion_extra_ids = sorted({item.CIE_NID_id for item in snapshots_extras})
        list(CITACION_EXTRA.objects.select_for_update().filter(pk__in=citacion_extra_ids))
        ids_afectados = citacion_extra_ids
        cantidad_citaciones = 0
        cantidad_extras = len(citacion_extra_ids)
    descripcion = (
        f'BORRAR_CARPETA_PROFORMA_{categoria}. Proforma: {proforma.pk}. '
        f'Transporte: {proforma.SN_NID_id}. Tipo: {proforma.PRO_CTIPO}. '
        f'Período: {proforma.PRO_FPERIODO_INICIO} a {proforma.PRO_FPERIODO_FIN}. '
        f'Categoría: {categoria}. Citaciones: {cantidad_citaciones}. '
        f'Extras: {cantidad_extras}. IDs liberados: {ids_afectados}.'
    )
    SYSLOGGER.objects.create(
        US_NID=user,
        EP_NID_id=EMPRESA_TERRAMAR,
        LOG_FFECHAREGISTRO=timezone.now(),
        LOG_CMODULO='PROFORMA',
        LOG_COPERACION=f'BORRAR_CARPETA_{categoria}',
        LOG_CADD1=f'Proforma: {proforma.pk}',
        LOG_CADD2=f'{categoria}: {len(ids_afectados)}',
        LOG_CDESCRIPCION=descripcion,
    )
    proforma_pk = proforma.pk
    if categoria == 'FLETE':
        CITACION_PROFORMA.objects.filter(pk__in=[item.pk for item in asociaciones]).delete()
        pendientes = [
            citacion_id for citacion_id in ids_afectados
            if not CITACION_PROFORMA.objects.filter(CI_NID_id=citacion_id).exists()
        ]
        CITACION.objects.filter(pk__in=pendientes).update(CI_BCONFORME=False)
    else:
        EXTRA_PROFORMA.objects.filter(pk__in=[item.pk for item in snapshots_extras]).delete()
    proforma.delete()
    return {
        'ok': True,
        'proforma': proforma_pk,
        'categoria': categoria,
        'cantidad_citaciones': cantidad_citaciones,
        'cantidad_extras': cantidad_extras,
        'ids_afectados': ids_afectados,
    }

def obtener_proforma_terramar(pk, user, bloquear=False):
    queryset = PROFORMA.objects.all()
    if bloquear:
        queryset = queryset.select_for_update()
    else:
        queryset = queryset.select_related('EP_NID', 'SN_NID', 'US_NID')
    try:
        proforma = queryset.get(pk=pk, EP_NID_id=EMPRESA_TERRAMAR)
    except PROFORMA.DoesNotExist as exc:
        raise ProformaTerramarError('La Proforma Terramar no existe.') from exc
    if not usuario_puede_proforma_terramar(user):
        raise PermissionError('No tiene permiso para acceder a esta Proforma Terramar.')
    if not proforma.PRO_FPERIODO_INICIO or not proforma.PRO_FPERIODO_FIN:
        raise ProformaTerramarError('La nueva vista solo está disponible para Proformas mensuales Terramar.')
    return proforma


def proforma_editable(proforma):
    return bool(
        proforma.EP_NID_id == EMPRESA_TERRAMAR
        and proforma.PRO_CESTADO == 'CREADO'
        and proforma.PRO_BBORRADOR
        and proforma.PRO_DOC_ENTRY is None
    )


def es_proforma_mensual_terramar(proforma):
    return bool(
        proforma.EP_NID_id == EMPRESA_TERRAMAR
        and proforma.PRO_FPERIODO_INICIO
        and proforma.PRO_FPERIODO_FIN
    )


def estado_permite_autorizar_sap(proforma):
    estado_requerido = (
        ESTADO_APROBADO
        if es_proforma_mensual_terramar(proforma)
        else ESTADO_BORRADOR
    )
    return bool(
        proforma.PRO_CESTADO == estado_requerido
        and proforma.PRO_BBORRADOR
        and proforma.PRO_DOC_ENTRY is None
        and not str(proforma.PRO_DOC_NUM or '').strip()
    )


def _exigir_editable(proforma):
    if not proforma_editable(proforma):
        raise ProformaTerramarError('La Proforma no permite modificar Extras en su estado actual.')


def _decimal_positivo(valor, etiqueta):
    try:
        numero = Decimal(str(valor or '').strip().replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ProformaTerramarError(f'{etiqueta} debe ser un número válido.')
    if numero <= 0:
        raise ProformaTerramarError(f'{etiqueta} debe ser mayor que cero.')
    return numero.quantize(CUANTIZACION_MONEDA)


def _cantidad(valor, permite_cantidad):
    if not permite_cantidad:
        return 1
    try:
        numero = int(str(valor or '').strip())
    except (TypeError, ValueError):
        raise ProformaTerramarError('Cantidad debe ser un entero mayor que cero.')
    if numero <= 0:
        raise ProformaTerramarError('Cantidad debe ser un entero mayor que cero.')
    return numero


def _valores_extra(extra, cantidad, valor_unitario, editar_valor=False):
    cantidad = _cantidad(cantidad, bool(extra.EXT_BPERMITECANTIDAD))
    if extra.EXT_BPERMITEEDITARVALOR and editar_valor:
        unitario = _decimal_positivo(valor_unitario, 'Valor unitario')
    else:
        unitario = _decimal_positivo(extra.EXT_NVALORBASE, 'Valor base')
    total = (Decimal(cantidad) * unitario).quantize(CUANTIZACION_MONEDA)
    return cantidad, unitario, total


def _misma_carpeta(proforma, otro):
    return bool(
        proforma.EP_NID_id == otro.EP_NID_id
        and proforma.SN_NID_id == otro.SN_NID_id
        and tipo_operacion_proforma(proforma.PRO_CTIPO) == tipo_operacion_proforma(otro.PRO_CTIPO)
        and proforma.PRO_FPERIODO_INICIO == otro.PRO_FPERIODO_INICIO
        and proforma.PRO_FPERIODO_FIN == otro.PRO_FPERIODO_FIN
    )


def _validar_citacion_carpeta(proforma, citacion):
    if (
        categoria_proforma(proforma.PRO_CTIPO) == 'FLETE'
        and CITACION_PROFORMA.objects.filter(
            PRO_NID=proforma, CI_NID=citacion, EP_NID_id=EMPRESA_TERRAMAR
        ).exists()
    ):
        return
    if (
        citacion.EP_NID_id != EMPRESA_TERRAMAR
        or str(citacion.CI_CTIPO or '').upper() != tipo_operacion_proforma(proforma.PRO_CTIPO)
        or periodo_citacion(citacion) != (
            proforma.PRO_FPERIODO_INICIO, proforma.PRO_FPERIODO_FIN
        )
        or citacion.PRO_NID_id not in {None, proforma.SN_NID_id}
    ):
        raise ProformaTerramarError('La citación no pertenece a la carpeta mensual de la Proforma.')


def _borrador_extras_para_citacion(*, user, proforma, citacion):
    if (
        categoria_proforma(proforma.PRO_CTIPO) == 'FLETE'
        and EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma, EPR_BHABILITADO=True
        ).exists()
    ):
        raise ProformaTerramarError(
            'El borrador mezcla Fletes y Extras. Debe separarse antes de continuar.'
        )
    _validar_citacion_carpeta(proforma, citacion)
    borrador, _ = obtener_o_crear_borrador_extras(
        user=user,
        empresa_id=EMPRESA_TERRAMAR,
        transporte_id=proforma.SN_NID_id,
        tipo=tipo_operacion_proforma(proforma.PRO_CTIPO),
        inicio=proforma.PRO_FPERIODO_INICIO,
        fin=proforma.PRO_FPERIODO_FIN,
        comentario=proforma.PRO_CCOMENTARIO,
    )
    return borrador

def _auditar_extra(user, proforma, citacion_id, operacion, extra, cantidad, unitario, anterior, nuevo):
    SYSLOGGER.objects.create(
        US_NID=user,
        EP_NID_id=EMPRESA_TERRAMAR,
        LOG_FFECHAREGISTRO=timezone.now(),
        LOG_CMODULO='PROFORMA',
        LOG_COPERACION=operacion,
        LOG_CADD1=f'Proforma: {proforma.pk}',
        LOG_CADD2=f'Citacion: {citacion_id}',
        LOG_CDESCRIPCION=(
            f'Concepto: {extra.EXT_CNOMBRE}. Cantidad: {cantidad}. '
            f'Valor unitario: {unitario}. Total: {nuevo}. '
            f'Valor anterior: {anterior}. Valor nuevo: {nuevo}.'
        ),
    )


@transaction.atomic
def agregar_extra(
    *, user, proforma_id, citacion_id, extra_id, cantidad, valor_unitario,
    comentario='', editar_valor=False,
):
    ancla = obtener_proforma_terramar(proforma_id, user, bloquear=True)
    citacion = CITACION.objects.select_for_update().filter(
        pk=citacion_id, EP_NID_id=EMPRESA_TERRAMAR
    ).first()
    if not citacion:
        raise ProformaTerramarError('La citación no existe.')
    proforma = _borrador_extras_para_citacion(
        user=user, proforma=ancla, citacion=citacion,
    )
    extra = EXTRA.objects.select_for_update().filter(
        pk=extra_id,
        EP_NID_id=EMPRESA_TERRAMAR,
        EXT_BHABILITADO=True,
        EXT_CTIPO_CITACION=citacion.CI_CTIPO,
        EXT_NVALORBASE__isnull=False,
    ).first()
    if not extra:
        raise ProformaTerramarError('El concepto de Extra no está configurado para esta operación.')
    cantidad, unitario, total = _valores_extra(
        extra, cantidad, valor_unitario, editar_valor=editar_valor,
    )
    citacion_extra = CITACION_EXTRA.objects.create(
        EP_NID_id=EMPRESA_TERRAMAR,
        US_NID=user,
        EXT_NID=extra,
        CI_NID=citacion,
        CIE_NVALOR=total,
        CIE_FFECHAREGISTRO=timezone.now(),
        CIE_BINGRESO=extra.EXT_BINGRESO,
        CIE_CCOMENTARIO=str(comentario or '').strip()[:128],
        CIE_NCANTIDAD=cantidad,
        CIE_NVALORUNITARIO=unitario,
    )
    extra_proforma = EXTRA_PROFORMA.objects.create(
        EP_NID_id=EMPRESA_TERRAMAR,
        CIE_NID=citacion_extra,
        PRO_NID=proforma,
        EPR_NVALOR=total,
        EPR_BINGRESO=extra.EXT_BINGRESO,
        EPR_BHABILITADO=True,
        EPR_NCANTIDAD=cantidad,
        EPR_NVALORUNITARIO=unitario,
    )
    recalcular_totales(proforma)
    _auditar_extra(user, proforma, citacion_id, 'EXTRA_AGREGADO', extra, cantidad, unitario, 0, total)
    return extra_proforma
@transaction.atomic
def editar_extra(
    *, user, proforma_id, citacion_id, extra_proforma_id, cantidad,
    valor_unitario, comentario='', editar_valor=False,
):
    ancla = obtener_proforma_terramar(proforma_id, user, bloquear=True)
    extra_proforma = EXTRA_PROFORMA.objects.select_for_update().select_related(
        'PRO_NID', 'CIE_NID__EXT_NID', 'CIE_NID__CI_NID'
    ).filter(
        pk=extra_proforma_id,
        EP_NID_id=EMPRESA_TERRAMAR,
        CIE_NID__CI_NID_id=citacion_id,
        EPR_BHABILITADO=True,
    ).first()
    if not extra_proforma:
        raise ProformaTerramarError('El Extra no existe o ya fue eliminado.')
    proforma = obtener_proforma_terramar(extra_proforma.PRO_NID_id, user, bloquear=True)
    if categoria_proforma(proforma.PRO_CTIPO) != 'EXTRAS' or not _misma_carpeta(ancla, proforma):
        raise ProformaTerramarError('El Extra no pertenece a la carpeta mensual seleccionada.')
    _exigir_editable(proforma)
    extra = extra_proforma.CIE_NID.EXT_NID
    cantidad, unitario, total = _valores_extra(
        extra, cantidad, valor_unitario, editar_valor=editar_valor,
    )
    anterior = extra_proforma.EPR_NVALOR
    citacion_extra = extra_proforma.CIE_NID
    citacion_extra.CIE_NCANTIDAD = cantidad
    citacion_extra.CIE_NVALORUNITARIO = unitario
    citacion_extra.CIE_NVALOR = total
    citacion_extra.CIE_CCOMENTARIO = str(comentario or '').strip()[:128]
    citacion_extra.save(update_fields=[
        'CIE_NCANTIDAD', 'CIE_NVALORUNITARIO', 'CIE_NVALOR', 'CIE_CCOMENTARIO'
    ])
    extra_proforma.EPR_NCANTIDAD = cantidad
    extra_proforma.EPR_NVALORUNITARIO = unitario
    extra_proforma.EPR_NVALOR = total
    extra_proforma.save(update_fields=['EPR_NCANTIDAD', 'EPR_NVALORUNITARIO', 'EPR_NVALOR'])
    recalcular_totales(proforma)
    _auditar_extra(
        user, proforma, citacion_extra.CI_NID_id, 'EXTRA_EDITADO',
        extra, cantidad, unitario, anterior, total,
    )
    return extra_proforma
@transaction.atomic
def eliminar_extra(*, user, proforma_id, citacion_id, extra_proforma_id):
    ancla = obtener_proforma_terramar(proforma_id, user, bloquear=True)
    extra_proforma = EXTRA_PROFORMA.objects.select_for_update().select_related(
        'PRO_NID', 'CIE_NID__EXT_NID', 'CIE_NID__CI_NID'
    ).filter(
        pk=extra_proforma_id,
        EP_NID_id=EMPRESA_TERRAMAR,
        CIE_NID__CI_NID_id=citacion_id,
        EPR_BHABILITADO=True,
    ).first()
    if not extra_proforma:
        raise ProformaTerramarError('El Extra no existe o ya fue eliminado.')
    proforma = obtener_proforma_terramar(extra_proforma.PRO_NID_id, user, bloquear=True)
    if categoria_proforma(proforma.PRO_CTIPO) != 'EXTRAS' or not _misma_carpeta(ancla, proforma):
        raise ProformaTerramarError('El Extra no pertenece a la carpeta mensual seleccionada.')
    _exigir_editable(proforma)
    anterior = extra_proforma.EPR_NVALOR
    extra_proforma.EPR_BHABILITADO = False
    extra_proforma.save(update_fields=['EPR_BHABILITADO'])
    recalcular_totales(proforma)
    _auditar_extra(
        user, proforma, extra_proforma.CIE_NID.CI_NID_id, 'EXTRA_ELIMINADO',
        extra_proforma.CIE_NID.EXT_NID,
        extra_proforma.EPR_NCANTIDAD or 1,
        extra_proforma.EPR_NVALORUNITARIO or extra_proforma.EPR_NVALOR, anterior, 0,
    )
    return extra_proforma
def _totales_snapshot_bloqueados(proforma):
    asociaciones = list(
        CITACION_PROFORMA.objects.select_for_update()
        .filter(PRO_NID=proforma, EP_NID_id=EMPRESA_TERRAMAR)
        .select_related('CI_NID')
        .order_by('id')
    )
    extras = list(
        EXTRA_PROFORMA.objects.select_for_update()
        .filter(PRO_NID=proforma, EP_NID_id=EMPRESA_TERRAMAR, EPR_BHABILITADO=True)
        .select_related('CIE_NID__CI_NID')
        .order_by('id')
    )
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    tarifa = sum((Decimal(item.CIP_NSUBTOTAL or 0) for item in asociaciones), Decimal('0'))
    ingresos = sum((Decimal(item.EPR_NVALOR or 0) for item in extras if item.EPR_BINGRESO), Decimal('0'))
    descuentos = sum((Decimal(item.EPR_NVALOR or 0) for item in extras if not item.EPR_BINGRESO), Decimal('0'))
    subtotal = tarifa if categoria == 'FLETE' else ingresos - descuentos
    iva = subtotal * Decimal('0.19')
    return asociaciones, extras, {
        'subtotal_transporte': tarifa,
        'extras_ingreso': ingresos,
        'extras_descuento': descuentos,
        'subtotal': subtotal,
        'iva': iva,
        'total': subtotal + iva,
    }


@transaction.atomic
def aprobar_borrador(*, user, proforma_id):
    if not usuario_puede_aprobar_borrador(user):
        raise PermissionError('Solo CONTROL_FLOTA puede aprobar el borrador Terramar.')
    proforma = obtener_proforma_terramar(proforma_id, user, bloquear=True)
    if not es_proforma_mensual_terramar(proforma):
        raise ProformaTerramarError('Solo se pueden aprobar borradores mensuales Terramar.')
    _exigir_editable(proforma)
    asociaciones, extras, totales = _totales_snapshot_bloqueados(proforma)
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    if categoria == 'FLETE':
        if extras:
            raise ProformaTerramarError(
                'El borrador mezcla Fletes y Extras. Debe separarse antes de aprobar.'
            )
        if not asociaciones:
            raise ProformaTerramarError('La Proforma de Fletes debe contener al menos una citación.')
        citaciones = [item.CI_NID for item in asociaciones]
    else:
        if asociaciones:
            raise ProformaTerramarError(
                'La Proforma de Extras no puede contener snapshots de Fletes.'
            )
        if not extras:
            raise ProformaTerramarError('La Proforma de Extras debe contener al menos un Extra.')
        citaciones = [item.CIE_NID.CI_NID for item in extras]
    esperado_periodo = (proforma.PRO_FPERIODO_INICIO, proforma.PRO_FPERIODO_FIN)
    for citacion in citaciones:
        if (
            citacion.EP_NID_id != EMPRESA_TERRAMAR
            or str(citacion.CI_CTIPO or '').upper() != tipo_operacion_proforma(proforma.PRO_CTIPO)
            or periodo_citacion(citacion) != esperado_periodo
            or citacion.PRO_NID_id not in {None, proforma.SN_NID_id}
        ):
            raise ProformaTerramarError('Los registros no pertenecen al mismo grupo mensual de la Proforma.')
    actuales = (
        Decimal(proforma.PRO_NSUBTOTAL or 0), Decimal(proforma.PRO_NIVA or 0),
        Decimal(proforma.PRO_NTOTAL or 0), Decimal(proforma.PRO_NINGRESO or 0),
        Decimal(proforma.PRO_NDESCUENTO or 0),
    )
    esperados = (
        totales['subtotal'], totales['iva'], totales['total'],
        totales['extras_ingreso'] if categoria == 'EXTRAS' else Decimal('0'),
        totales['extras_descuento'] if categoria == 'EXTRAS' else Decimal('0'),
    )
    if actuales != esperados:
        raise ProformaTerramarError('Los totales cambiaron o no son consistentes. Recargue el borrador antes de aprobar.')
    proforma.PRO_CESTADO = ESTADO_APROBADO
    proforma.save(update_fields=['PRO_CESTADO'])
    SYSLOGGER.objects.create(
        US_NID=user, EP_NID_id=EMPRESA_TERRAMAR,
        LOG_FFECHAREGISTRO=timezone.now(), LOG_CMODULO='PROFORMA',
        LOG_COPERACION=f'PROFORMA_{categoria}_APROBADA',
        LOG_CADD1=f'Proforma: {proforma.pk}',
        LOG_CADD2=f'Registros: {len(citaciones)}',
        LOG_CDESCRIPCION=(
            f'Borrador mensual de {categoria.title()} validado con transportista. '
            'No se ejecutó SAP ni se generó DocEntry/DocNum.'
        ),
    )
    return proforma

def contexto_pdf_proforma(proforma):
    contexto = contexto_detalle_proforma(proforma)
    if contexto['es_mixta']:
        raise ProformaTerramarError(
            'El borrador mezcla Fletes y Extras. Debe separarse antes de generar su PDF.'
        )
    ingresos = sum((Decimal(item.EPR_NVALOR or 0) for item in contexto['extras'] if item.EPR_BINGRESO), Decimal('0'))
    descuentos = sum((Decimal(item.EPR_NVALOR or 0) for item in contexto['extras'] if not item.EPR_BINGRESO), Decimal('0'))
    contexto.update({
        'generado': timezone.localtime(timezone.now()),
        'totales_pdf': {
            'subtotal_transporte': contexto['subtotal_transporte'],
            'extras_ingreso': ingresos,
            'extras_descuento': descuentos,
            'subtotal': Decimal(proforma.PRO_NSUBTOTAL or 0),
            'iva': Decimal(proforma.PRO_NIVA or 0),
            'total': Decimal(proforma.PRO_NTOTAL or 0),
        },
    })
    return contexto


def _json_seguro(valor):
    try:
        data = json.loads(str(valor or ''))
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dato_codigo(citacion, codigo):
    return DATO_OPERACION.objects.select_related('CAMP_NID', 'US_NID').filter(
        CI_NID=citacion,
        CAMP_NID__CA_CCODIGO=codigo,
    ).order_by('-id').first()


def _ticket(citacion, codigo, etiqueta):
    dato = _dato_codigo(citacion, codigo)
    if not dato:
        return None
    metadata = _json_seguro(dato.DO_CVALOR)
    peso = metadata.get('peso_neto') if metadata.get('peso_neto') not in [None, ''] else dato.DO_NPESO
    return {
        'concepto': etiqueta,
        'peso': peso,
        'fecha': metadata.get('fecha_hora_ticket') or dato.DO_FFECHAREGISTRO,
        'folio': metadata.get('folio'),
        'archivo': metadata.get('nombre_archivo_pdf'),
        'dato': dato,
        'metadata': metadata,
    }


def resumen_pesaje(citacion):
    entrada = _ticket(citacion, CODIGO_TICKET_ENTRADA, 'Peso entrada')
    salida = _ticket(citacion, CODIGO_TICKET_SALIDA, 'Peso salida')
    neto = None
    formula = ''
    if entrada and salida and entrada['peso'] not in [None, ''] and salida['peso'] not in [None, '']:
        peso_entrada = Decimal(str(entrada['peso']))
        peso_salida = Decimal(str(salida['peso']))
        if str(citacion.CI_CTIPO or '').upper() == 'DESPACHO':
            # Validado contra el flujo ELI de despacho y pesajes Terramar reales:
            # el ticket de entrada contiene el bruto y el de salida la tara.
            neto = peso_entrada - peso_salida
            formula = 'Peso entrada - Peso salida'
        else:
            # Recepcion se valida de forma independiente aunque hoy comparte
            # la direccion de la resta con despacho.
            neto = peso_entrada - peso_salida
            formula = 'Peso entrada - Peso salida'
    return {
        'entrada': entrada,
        'salida': salida,
        'neto': neto,
        'formula': formula,
    }


def _url_ticket(dato):
    return f"{reverse('ajax_operacion_planta_descargar_ticket_pesaje')}?{urlencode({'dato_id': dato.pk})}"


def documentos_operacion(citacion):
    timbrado = _json_seguro(getattr(_dato_codigo(citacion, CODIGO_TIMBRADO), 'DO_CVALOR', ''))
    timbrados = {
        item.get('source_ref'): item
        for item in timbrado.get('documentos', [])
        if isinstance(item, dict) and item.get('source_ref')
    }
    documentos = []
    rutas_vistas = set()
    for documento in CITACION_DOCUMENTO.objects.select_related('US_SUBE_NID').filter(
        CI_NID=citacion, EP_NID_id=EMPRESA_TERRAMAR, CD_BACTIVO=True
    ).order_by('CD_CTIPO', '-CD_FFECHASUBIDA'):
        source = f'CITACION_DOCUMENTO:{documento.pk}'
        version = timbrados.get(source)
        url = reverse('expediente_citacion_documento_descargar', args=[documento.pk])
        estado = 'ACTIVO'
        if version:
            url = f"{reverse('ajax_operacion_planta_documento_terramar', args=[citacion.pk, version['key']])}?version=timbrado&accion=descargar"
            estado = 'TIMBRADO'
        ruta = str(documento.CD_CRUTA_ARCHIVO or '')
        rutas_vistas.add(os.path.normcase(ruta))
        documentos.append({
            'nombre': documento.CD_CNOMBRE_ARCHIVO,
            'tipo': documento.CD_CTIPO,
            'fecha': documento.CD_FFECHASUBIDA,
            'usuario': documento.US_SUBE_NID,
            'estado': estado,
            'url': url,
        })
    for codigo, tipo in ((CODIGO_TICKET_ENTRADA, 'TICKET PESAJE ENTRADA'), (CODIGO_TICKET_SALIDA, 'TICKET PESAJE SALIDA'), (CODIGO_TICKET_MOP, 'TICKET MOP / EJES')):
        dato = _dato_codigo(citacion, codigo)
        if not dato:
            continue
        metadata = _json_seguro(dato.DO_CVALOR)
        source = f'TICKET_PESAJE:{dato.pk}'
        version = timbrados.get(source)
        url = _url_ticket(dato)
        estado = 'CONGELADO'
        if version:
            url = f"{reverse('ajax_operacion_planta_documento_terramar', args=[citacion.pk, version['key']])}?version=timbrado&accion=descargar"
            estado = 'TIMBRADO'
        documentos.append({
            'nombre': metadata.get('nombre_archivo_pdf') or os.path.basename(str(dato.DO_CVALOR or '')),
            'tipo': tipo,
            'fecha': metadata.get('fecha_hora_ticket') or dato.DO_FFECHAREGISTRO,
            'usuario': dato.US_NID,
            'estado': estado,
            'url': url,
        })
    for adjunto in CAMION_PATIO_ADJUNTO.objects.select_related('US_CARGA_ID').filter(
        CPA_NID__CI_NID=citacion
    ).order_by('-CPA_FFECHACARGA'):
        ruta = str(adjunto.CPA_FARCHIVO.name or '')
        if os.path.normcase(ruta) in rutas_vistas:
            continue
        rutas_vistas.add(os.path.normcase(ruta))
        documentos.append({
            'nombre': os.path.basename(ruta),
            'tipo': f'INGRESO CAMIÓN - {adjunto.CPA_CTIPO_DOCUMENTO}',
            'fecha': adjunto.CPA_FFECHACARGA,
            'usuario': adjunto.US_CARGA_ID,
            'estado': 'REFERENCIA',
            'url': adjunto.CPA_FARCHIVO.url if adjunto.CPA_FARCHIVO else '',
        })
    return documentos


def _valor_dato(citacion, codigo):
    dato = _dato_codigo(citacion, codigo)
    return str(dato.DO_CVALOR or '').strip() if dato else ''


def _agregar(filas, etiqueta, valor):
    if valor not in [None, '']:
        filas.append({'etiqueta': etiqueta, 'valor': valor})


def detalle_operacional_citacion(citacion):
    patio = CAMION_PATIO.objects.filter(CI_NID=citacion).order_by('-id').first()
    recepcion = getattr(citacion, 'detalle_recepcion_terramar', None)
    despacho = getattr(citacion, 'detalle_despacho', None)
    detalle = getattr(citacion, 'detalle_operacional', None)
    item = CITACION_ITEM.objects.select_related('IT_NID').filter(CI_NID=citacion).first()
    ruta = citacion.RUT_NID
    filas = []
    _agregar(filas, 'N° planificación', citacion.PL_NID_id)
    _agregar(filas, 'N° citación', citacion.pk)
    _agregar(filas, 'Empresa', citacion.EP_NID.EP_CRAZONSOCIAL)
    _agregar(filas, 'Tipo operación', citacion.CI_CTIPO)
    _agregar(filas, 'Fecha planificación', getattr(citacion.PL_NID, 'PL_FFECHAINICIO', None))
    _agregar(filas, 'Fecha/hora citación', citacion.CI_FFECHACITACION)
    _agregar(filas, 'Cliente', getattr(citacion.SN_NID, 'SN_CRAZONSOCIAL', ''))
    transporte = (
        getattr(recepcion, 'RTD_CEMPRESA_TRANSPORTE', '')
        or getattr(despacho, 'CDD_CEMPRESA_TRANSPORTE', '')
        or getattr(patio, 'CPA_CTRANSPORTISTA_DECLARADO', '')
        or getattr(citacion.PRO_NID, 'SN_CRAZONSOCIAL', '')
    )
    _agregar(filas, 'Transporte', transporte)
    conductor = getattr(recepcion, 'RTD_CCONDUCTOR', '') or getattr(despacho, 'CDD_CCONDUCTOR', '') or getattr(patio, 'CPA_CNOMBRE_CONDUCTOR', '')
    _agregar(filas, 'Conductor', conductor)
    rut_conductor = getattr(getattr(recepcion, 'CON_NID', None), 'CON_CRUT', '') or getattr(patio, 'CPA_CRUT_CONDUCTOR', '') or _valor_dato(citacion, 'ING_RUT_CONDUCTOR')
    _agregar(filas, 'RUT conductor', rut_conductor)
    telefono = getattr(recepcion, 'RTD_CTELEFONO_CONDUCTOR', '') or getattr(despacho, 'CDD_CTELEFONO_CONDUCTOR', '') or getattr(patio, 'CPA_CTELEFONO_CONDUCTOR', '')
    _agregar(filas, 'Teléfono', telefono)
    patente = getattr(recepcion, 'RTD_CPATENTE', '') or getattr(despacho, 'CDD_CPATENTE', '') or getattr(patio, 'CPA_CPATENTE', '')
    _agregar(filas, 'Patente', patente)
    _agregar(filas, 'Ruta', getattr(ruta, 'RUT_CNOMBRE', ''))
    _agregar(filas, 'Origen', getattr(getattr(ruta, 'COM_NID_INICIO', None), 'COM_CNOMBRE', ''))
    destino = getattr(despacho, 'CDD_CDESTINO', '') or getattr(getattr(ruta, 'COM_NID_TERMINO', None), 'COM_CNOMBRE', '')
    _agregar(filas, 'Destino', destino)
    producto = getattr(detalle, 'CDO_CINSUMO', '') or getattr(getattr(item, 'IT_NID', None), 'IT_CNOMBRE', '') or _valor_dato(citacion, 'ING_INSUMO_DECLARADO_GUIA')
    _agregar(filas, 'Producto / insumo', producto)
    bodega = getattr(recepcion, 'RTD_CBODEGA', '') if recepcion else getattr(despacho, 'CDD_CBODEGA', '')
    _agregar(filas, 'Bodega', bodega)
    _agregar(filas, 'Tipo documento', citacion.CI_CTIPODOCUMENTO or getattr(patio, 'CPA_CTIPO_DOCUMENTO', ''))
    _agregar(filas, 'Guía / documento', citacion.CI_CNUMERODOCUMENTO or getattr(patio, 'CPA_CNUMERO_GUIA', '') or _valor_dato(citacion, 'CI_CNUMERODOCUMENTO'))
    _agregar(filas, 'Observación', citacion.CI_CCOMENTARIO or getattr(patio, 'CPA_COBSERVACION', '') or getattr(detalle, 'CDO_COBSERVACION', ''))
    if recepcion:
        _agregar(filas, 'Contenedor / CRT', recepcion.RTD_CCONTENEDOR_CRT)
    if despacho:
        for etiqueta, valor in (
            ('OC cliente', despacho.CDD_COC_CLIENTE),
            ('Orden de carga', despacho.CDD_CORDEN_CARGA),
            ('Condición de entrega', despacho.CDD_CCONDICION_ENTREGA),
            ('Producto SAP', despacho.CDD_CSAP_NOMBRE_PRODUCTO),
            ('Cantidad planificada', despacho.CDD_NSAP_CANTIDAD_PLANIFICADA),
            ('Contenedor / CRT', despacho.CDD_CCONTENEDOR_CRT),
            ('Tipo camión', despacho.CDD_CTIPO_CAMION),
        ):
            _agregar(filas, etiqueta, valor)
    logs = OPERACION_PLANTA_LOG.objects.select_related('US_NID').filter(
        CI_NID=citacion, EP_NID_id=EMPRESA_TERRAMAR
    ).order_by('OPL_FFECHAREGISTRO', 'id')
    return {
        'datos': filas,
        'pesaje': resumen_pesaje(citacion),
        'documentos': documentos_operacion(citacion),
        'operacion': logs,
    }


def contexto_detalle_proforma(proforma):
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    asociaciones = list(CITACION_PROFORMA.objects.filter(
        PRO_NID=proforma, EP_NID_id=EMPRESA_TERRAMAR
    ).select_related(
        'CI_NID__PL_NID', 'CI_NID__EP_NID', 'CI_NID__SN_NID',
        'CI_NID__PRO_NID', 'CI_NID__RUT_NID__COM_NID_INICIO',
        'CI_NID__RUT_NID__COM_NID_TERMINO',
    ).order_by('CI_NID__CI_FFECHACITACION', 'CI_NID_id'))
    extras = list(EXTRA_PROFORMA.objects.filter(
        PRO_NID=proforma, EP_NID_id=EMPRESA_TERRAMAR, EPR_BHABILITADO=True
    ).select_related(
        'CIE_NID__EXT_NID', 'CIE_NID__CI_NID__PL_NID',
        'CIE_NID__CI_NID__EP_NID', 'CIE_NID__CI_NID__SN_NID',
        'CIE_NID__CI_NID__PRO_NID',
        'CIE_NID__CI_NID__RUT_NID__COM_NID_INICIO',
        'CIE_NID__CI_NID__RUT_NID__COM_NID_TERMINO',
    ).order_by('CIE_NID__CI_NID_id', 'id'))
    if categoria == 'FLETE' and extras:
        # Un borrador histórico mixto se muestra, pero no se autoriza ni se
        # vuelve a calcular automáticamente hasta ejecutar su transición.
        extras_documento = extras
    else:
        extras_documento = extras if categoria == 'EXTRAS' else []
    extras_por_citacion = {}
    for extra in extras_documento:
        extras_por_citacion.setdefault(extra.CIE_NID.CI_NID_id, []).append(extra)
    asociaciones_por_citacion = {item.CI_NID_id: item for item in asociaciones}
    if categoria == 'FLETE':
        citaciones_documento = [item.CI_NID for item in asociaciones]
    else:
        citaciones_documento = []
        vistas = set()
        for extra in extras_documento:
            citacion = extra.CIE_NID.CI_NID
            if citacion.pk not in vistas:
                vistas.add(citacion.pk)
                citaciones_documento.append(citacion)
    filas = []
    for citacion in citaciones_documento:
        asociacion = asociaciones_por_citacion.get(citacion.pk)
        patio = CAMION_PATIO.objects.filter(CI_NID=citacion).order_by('-id').first()
        extras_citacion = extras_por_citacion.get(citacion.pk, [])
        total_extras = sum(
            ((e.EPR_NVALOR if e.EPR_BINGRESO else -e.EPR_NVALOR) for e in extras_citacion),
            Decimal('0'),
        )
        tarifa = Decimal(asociacion.CIP_NSUBTOTAL or 0) if asociacion else Decimal('0')
        filas.append({
            'asociacion': asociacion,
            'citacion': citacion,
            'patente': getattr(patio, 'CPA_CPATENTE', '') or getattr(citacion.CA_NID, 'CAM_CPATENTE', ''),
            'conductor': getattr(patio, 'CPA_CNOMBRE_CONDUCTOR', '') or (f'{citacion.CON_NID.CON_CNOMBRE} {citacion.CON_NID.CON_CAPELLIDO}' if citacion.CON_NID else ''),
            'ruta': getattr(citacion.RUT_NID, 'RUT_CNOMBRE', ''),
            'guia': citacion.CI_CNUMERODOCUMENTO or getattr(patio, 'CPA_CNUMERO_GUIA', ''),
            'extras': extras_citacion,
            'total_extras': total_extras,
            'total': tarifa if categoria == 'FLETE' else total_extras,
        })
    catalogo = EXTRA.objects.filter(
        EP_NID_id=EMPRESA_TERRAMAR,
        EXT_BHABILITADO=True,
        EXT_NVALORBASE__isnull=False,
    ).order_by('EXT_CTIPO_CITACION', 'EXT_CNOMBRE', 'id')
    subtotal_transporte = sum(
        (Decimal(a.CIP_NSUBTOTAL or 0) for a in asociaciones), Decimal('0')
    ) if categoria == 'FLETE' else Decimal('0')
    documentos_carpeta = list(PROFORMA.objects.filter(
        EP_NID_id=proforma.EP_NID_id,
        SN_NID_id=proforma.SN_NID_id,
        PRO_FPERIODO_INICIO=proforma.PRO_FPERIODO_INICIO,
        PRO_FPERIODO_FIN=proforma.PRO_FPERIODO_FIN,
        PRO_CTIPO__in={
            tipo_operacion_proforma(proforma.PRO_CTIPO),
            f'{tipo_operacion_proforma(proforma.PRO_CTIPO)} EXTRAS',
        },
    ).order_by('PRO_CTIPO', '-pk'))
    for documento in documentos_carpeta:
        documento.categoria_visual = categoria_proforma(documento.PRO_CTIPO)
    return {
        'proforma': proforma,
        'categoria': categoria,
        'es_flete': categoria == 'FLETE',
        'es_extras': categoria == 'EXTRAS',
        'es_mixta': bool(categoria == 'FLETE' and extras),
        'editable': proforma_editable(proforma),
        'citaciones': filas,
        'extras': extras_documento,
        'catalogo_extras': catalogo,
        'subtotal_transporte': subtotal_transporte,
        'cantidad_citaciones': len(citaciones_documento),
        'documentos_carpeta': documentos_carpeta,
    }