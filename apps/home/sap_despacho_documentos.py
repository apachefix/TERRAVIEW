"""Verificación de cierre de Drafts SAP de Despacho SBH mediante ODRF."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    CITACION_DESPACHO_ACUERDO_OPERACIONAL,
    CITACION_DESPACHO_DRAFT_SAP,
    EMPRESA,
)
from .sap_di_api import _first_row
from .sap_despacho_carga import consultar_stock_producto


ODRF_DRAFT_CERRADO_SQL = '''
    SELECT COUNT(*) AS "resultado_count"
    FROM ODRF
    WHERE "DocStatus" = 'C'
      AND "DocEntry" = ?
'''


class VerificacionDocumentoSapError(RuntimeError):
    pass


def documento_definitivo_persistido(draft):
    respuesta = draft.respuesta if isinstance(draft.respuesta, dict) else {}
    documento = respuesta.get('documento_definitivo')
    return documento if isinstance(documento, dict) else {}


def draft_actualizado_correctamente(draft):
    respuesta = draft.respuesta if isinstance(draft.respuesta, dict) else {}
    actualizacion = respuesta.get('actualizacion_peso_real')
    return bool(
        isinstance(actualizacion, dict)
        and actualizacion.get('success') is True
        and str(draft.docentry or '').strip()
    )


def verificacion_sap_persistida(draft):
    respuesta = draft.respuesta if isinstance(draft.respuesta, dict) else {}
    verificacion = respuesta.get('verificacion_sap')
    return verificacion if isinstance(verificacion, dict) else {}


def _verificacion_sap_valida(draft, verificacion):
    try:
        draft_docentry = int(str(draft.docentry).strip())
        verificado_docentry = int(str(verificacion.get('draft_docentry')).strip())
        resultado_count = int(verificacion.get('resultado_count'))
    except (TypeError, ValueError):
        return False
    return bool(
        verificacion.get('cerrado') is True
        and resultado_count == 1
        and verificado_docentry == draft_docentry
    )


def _resultado_cierre_draft_sap(docentry, *, row_loader=_first_row):
    try:
        draft_docentry = int(str(docentry).strip())
    except (TypeError, ValueError) as exc:
        raise VerificacionDocumentoSapError(
            'El Draft SAP no tiene un DocEntry válido.'
        ) from exc
    if draft_docentry <= 0:
        raise VerificacionDocumentoSapError(
            'El Draft SAP no tiene un DocEntry válido.'
        )
    try:
        fila = row_loader(ODRF_DRAFT_CERRADO_SQL, [draft_docentry])
    except Exception as exc:
        raise VerificacionDocumentoSapError(
            f'No fue posible verificar el Draft {draft_docentry} en SAP HANA: {exc}'
        ) from exc
    if not isinstance(fila, dict):
        raise VerificacionDocumentoSapError(
            f'SAP HANA no devolvió el conteo del Draft {draft_docentry}.'
        )
    valor = fila.get('resultado_count')
    if valor is None:
        valor = fila.get('RESULTADO_COUNT')
    try:
        resultado_count = int(valor)
    except (TypeError, ValueError) as exc:
        raise VerificacionDocumentoSapError(
            f'SAP HANA devolvió un conteo inválido para el Draft {draft_docentry}.'
        ) from exc
    return resultado_count


def draft_sap_esta_cerrado(docentry, *, row_loader=_first_row):
    return _resultado_cierre_draft_sap(
        docentry, row_loader=row_loader,
    ) == 1


def documento_definitivo_confirmado(draft):
    documento = documento_definitivo_persistido(draft)
    return bool(
        documento.get('estado') == 'CONFIRMADO'
        and documento.get('docentry')
        and not documento.get('cancelado')
    )


def _decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _cantidades_finales_por_lote(draft):
    respuesta = draft.respuesta if isinstance(draft.respuesta, dict) else {}
    actualizacion = respuesta.get('actualizacion_peso_real') or {}
    request = actualizacion.get('request') if isinstance(actualizacion, dict) else {}
    cantidades = {}
    for linea in (request or {}).get('DocumentLines') or []:
        item_code = str(linea.get('ItemCode') or '').strip()
        warehouse = str(linea.get('WarehouseCode') or '').strip()
        for lote in linea.get('BatchNumbers') or []:
            clave = (item_code, warehouse, str(lote.get('BatchNumber') or '').strip())
            cantidades[clave] = _decimal(lote.get('Quantity'))
    return cantidades


def evidencia_consumo_sap(draft, stocks):
    """Contrasta el stock SAP actual con el snapshot y el consumo final del Draft."""
    cantidades_finales = _cantidades_finales_por_lote(draft)
    stock_actual = {}
    items_consultados = {str(item_code).strip() for item_code in (stocks or {})}
    for item_code, filas in (stocks or {}).items():
        for fila in filas or []:
            clave = (
                str(fila.get('item_code') or item_code).strip(),
                str(fila.get('warehouse_code') or '').strip(),
                str(fila.get('batch_number') or '').strip(),
            )
            stock_actual[clave] = _decimal(fila.get('stock'))

    detalles = []
    for estanque in draft.acuerdo.estanques.all():
        for lote in estanque.lotes.all():
            clave = (
                str(estanque.item_code).strip(),
                str(estanque.warehouse_code).strip(),
                str(lote.batch_number).strip(),
            )
            cantidad_final = cantidades_finales.get(clave, _decimal(lote.cantidad))
            item_consultado = clave[0] in items_consultados
            actual = stock_actual.get(clave, Decimal('0'))
            esperado_maximo = max(
                Decimal('0'), _decimal(lote.stock_snapshot) - cantidad_final,
            )
            detalles.append({
                'item_code': clave[0],
                'warehouse_code': clave[1],
                'batch_number': clave[2],
                'stock_snapshot': str(_decimal(lote.stock_snapshot)),
                'cantidad_final': str(cantidad_final),
                'stock_actual': str(actual),
                'stock_esperado_maximo': str(esperado_maximo),
                'reflejado': item_consultado and actual <= esperado_maximo,
            })
    return {
        'reflejado': bool(detalles) and all(item['reflejado'] for item in detalles),
        'detalles': detalles,
    }


def reserva_acuerdo_liberada(draft, stocks=None):
    """Separa la asignacion historica de la reserva operacional activa."""
    verificacion = verificacion_sap_persistida(draft)
    if not _verificacion_sap_valida(draft, verificacion):
        return False
    if verificacion.get('consumo_reflejado') is True:
        return True
    # Compatibilidad con verificaciones previas: usa el stock que el modal ya
    # obtuvo, sin realizar otra consulta SAP ni modificar el historico.
    if stocks is not None:
        return evidencia_consumo_sap(draft, stocks)['reflejado']
    return False


def _serializar_estado(draft):
    verificacion = verificacion_sap_persistida(draft)
    valido = _verificacion_sap_valida(draft, verificacion)
    return {
        'acuerdo_id': draft.acuerdo_id,
        'sap_abs_id': draft.acuerdo.sap_abs_id,
        'numero_acuerdo': draft.acuerdo.numero_acuerdo,
        'draft_docentry': draft.docentry,
        'draft_docnum': draft.docnum,
        'estado': 'CONFIRMADO' if valido else 'PENDIENTE',
        'valido': valido,
        'cerrado': verificacion.get('cerrado') is True,
        'resultado_count': verificacion.get('resultado_count'),
        'consumo_reflejado': verificacion.get('consumo_reflejado') is True,
        'consumo_detalle': verificacion.get('consumo_detalle') or [],
        'draft_actualizado': draft_actualizado_correctamente(draft),
        'fecha_iso': verificacion.get('fecha_iso') or '',
        'verificado_en': verificacion.get('fecha_iso') or '',
        'error': '',
    }


def estado_documentos_definitivos(citacion):
    acuerdos = list(
        CITACION_DESPACHO_ACUERDO_OPERACIONAL.objects
        .select_related('draft')
        .filter(carga__CI_NID=citacion)
        .order_by('orden', 'id')
    )
    documentos = []
    for acuerdo in acuerdos:
        try:
            draft = acuerdo.draft
        except CITACION_DESPACHO_DRAFT_SAP.DoesNotExist:
            draft = None
        if draft:
            documentos.append(_serializar_estado(draft))
        else:
            documentos.append({
                'acuerdo_id': acuerdo.id,
                'sap_abs_id': acuerdo.sap_abs_id,
                'numero_acuerdo': acuerdo.numero_acuerdo,
                'draft_docentry': '',
                'draft_docnum': '',
                'estado': 'PENDIENTE',
                'valido': False,
                'cerrado': False,
                'resultado_count': None,
                'draft_actualizado': False,
                'fecha_iso': '',
                'verificado_en': '',
                'error': 'El acuerdo todavía no tiene Draft SAP.',
            })
    completos = bool(documentos) and all(
        documento['draft_actualizado'] and documento['valido']
        for documento in documentos
    )
    return {
        'aplicable': bool(acuerdos),
        'completo': completos,
        'estado': 'SAP CONFIRMADO' if completos else 'DRAFT SAP AÚN ABIERTO',
        'documentos': documentos,
    }


def verificar_documentos_definitivos(
    citacion, *, row_loader=_first_row, stock_loader=consultar_stock_producto,
):
    drafts = list(
        CITACION_DESPACHO_DRAFT_SAP.objects
        .select_related('acuerdo')
        .prefetch_related('acuerdo__estanques__lotes')
        .filter(acuerdo__carga__CI_NID=citacion)
        .order_by('acuerdo__orden', 'id')
    )
    if not drafts:
        return estado_documentos_definitivos(citacion)
    no_actualizados = [
        draft.acuerdo.numero_acuerdo
        for draft in drafts
        if not draft_actualizado_correctamente(draft)
    ]
    if no_actualizados:
        raise VerificacionDocumentoSapError(
            'No se puede verificar el documento definitivo: faltan Drafts '
            f'actualizados correctamente para los acuerdos {", ".join(no_actualizados)}.'
        )

    resultados = {}
    stocks_por_item = {}
    try:
        for draft in drafts:
            draft_docentry = int(str(draft.docentry).strip())
            resultado_count = _resultado_cierre_draft_sap(
                draft_docentry,
                row_loader=row_loader,
            )
            evidencia = {'reflejado': False, 'detalles': []}
            if resultado_count == 1:
                items = {
                    str(estanque.item_code).strip()
                    for estanque in draft.acuerdo.estanques.all()
                }
                for item_code in items:
                    if item_code not in stocks_por_item:
                        stocks_por_item[item_code] = stock_loader(item_code)
                evidencia = evidencia_consumo_sap(draft, stocks_por_item)
            resultados[draft.id] = {
                'draft_docentry': draft_docentry,
                'cerrado': resultado_count == 1,
                'resultado_count': resultado_count,
                'consumo_reflejado': evidencia['reflejado'],
                'consumo_detalle': evidencia['detalles'],
                'fecha_iso': timezone.now().isoformat(),
            }
    except Exception as exc:
        if isinstance(exc, VerificacionDocumentoSapError):
            raise
        raise VerificacionDocumentoSapError(
            f'No fue posible verificar los Drafts en SAP HANA: {exc}'
        ) from exc

    with transaction.atomic():
        EMPRESA.objects.select_for_update().get(pk=2)
        bloqueados = {
            draft.id: draft
            for draft in CITACION_DESPACHO_DRAFT_SAP.objects.select_for_update().filter(
                pk__in=resultados
            )
        }
        for draft_id, verificacion in resultados.items():
            draft = bloqueados[draft_id]
            respuesta = deepcopy(draft.respuesta) if isinstance(draft.respuesta, dict) else {}
            respuesta['verificacion_sap'] = verificacion
            draft.respuesta = respuesta
            draft.save(update_fields=['respuesta', 'actualizado'])
    return estado_documentos_definitivos(citacion)


__all__ = [
    'VerificacionDocumentoSapError',
    'draft_sap_esta_cerrado',
    'draft_actualizado_correctamente',
    'documento_definitivo_confirmado',
    'documento_definitivo_persistido',
    'estado_documentos_definitivos',
    'evidencia_consumo_sap',
    'reserva_acuerdo_liberada',
    'verificacion_sap_persistida',
    'verificar_documentos_definitivos',
]
