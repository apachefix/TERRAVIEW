"""Carga operacional SBH: acuerdos, estanques, productos y lotes."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    CAMION_PATIO, CITACION, CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DETALLE, DATO_OPERACION, EMPRESA,
    CITACION_DESPACHO_ACUERDO_OPERACIONAL as Acuerdo,
    CITACION_DESPACHO_ACUERDO_ESTANQUE as Estanque,
    CITACION_DESPACHO_ACUERDO_LOTE as Lote,
    CITACION_DESPACHO_DRAFT_SAP as Draft,
)
from .sap_despacho import serializar_asignaciones_sap_planificadas, _draft_series
from .sap_despacho_carga import consultar_productos_acuerdo, consultar_stock_producto
from .sap_despacho_documentos import reserva_acuerdo_liberada


MENSAJE_PREPARADO = 'Carga guardada y lista para enviar a SAP.'


class CargaInvalida(ValueError):
    pass


def decimal_stock(valor):
    try:
        numero = Decimal(str(valor).replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError):
        raise CargaInvalida('SAP informó una cantidad de stock inválida.')
    if not numero.is_finite() or numero < 0:
        raise CargaInvalida('SAP informó una cantidad de stock inválida.')
    return numero


def cantidad(valor):
    try:
        numero = Decimal(str(valor).replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError):
        raise CargaInvalida('Cantidad inválida.')
    if not numero.is_finite() or numero <= 0 or numero >= Decimal('10000000000000'):
        raise CargaInvalida('La cantidad debe ser finita y mayor que cero.')
    if numero != numero.quantize(Decimal('0.00001')):
        raise CargaInvalida('La cantidad admite como máximo cinco decimales.')
    return numero


def fecha_sap(valor):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


def validar_ambito(citacion):
    tipo = citacion.CI_CTIPO or (citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID_id else '')
    if citacion.EP_NID_id != 2 or str(tipo).upper() != 'DESPACHO':
        raise CargaInvalida('La carga operacional solo aplica a DESPACHO SBH.')


def acuerdos_planificados(citacion):
    validar_ambito(citacion)
    detalle = CITACION_DESPACHO_DETALLE.objects.filter(CI_NID=citacion, EP_NID_id=2).first()
    if not detalle:
        raise CargaInvalida('Falta el detalle de despacho.')
    if detalle.asignaciones_sap.exclude(EP_NID_id=2).exists():
        raise CargaInvalida('Una asignación planificada pertenece a otra empresa.')
    grupos = {}
    for fila in serializar_asignaciones_sap_planificadas(citacion, detalle):
        if fila['estado'] != 'PLANIFICADA':
            continue
        try:
            abs_id = int(fila['sap_abs_id'])
        except (ValueError, TypeError):
            raise CargaInvalida('La planificación contiene un AbsID inválido.')
        if abs_id <= 0:
            raise CargaInvalida('La planificación contiene un AbsID inválido.')
        grupos.setdefault(abs_id, []).append(fila)
    if not grupos:
        raise CargaInvalida('No existen acuerdos SAP planificados activos.')
    return detalle, grupos


def usa_carga_operacional(citacion):
    """Históricos con Draft singular conservan su circuito original."""
    tipo = citacion.CI_CTIPO or (citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID_id else '')
    if citacion.EP_NID_id != 2 or str(tipo).upper() != 'DESPACHO':
        return False
    detalle = CITACION_DESPACHO_DETALLE.objects.filter(CI_NID=citacion).first()
    return bool(detalle and not detalle.CDD_CSAP_DRAFT_DOCENTRY)


def catalogo_acuerdo(citacion, abs_id):
    _, grupos = acuerdos_planificados(citacion)
    try:
        abs_id = int(str(abs_id))
    except (TypeError, ValueError):
        raise CargaInvalida('AbsID inválido.')
    if abs_id not in grupos:
        raise CargaInvalida('El acuerdo no pertenece a esta citación.')
    productos = consultar_productos_acuerdo(abs_id)
    clientes = {f['cliente_codigo'] for f in grupos[abs_id]}
    if not productos or any(str(p['cliente_codigo']) not in clientes for p in productos):
        raise CargaInvalida('Acuerdo SAP no disponible o cliente incompatible.')
    stocks = {}
    for p in productos:
        item = str(p['item_code'])
        if item not in stocks:
            stocks[item] = consultar_stock_producto(item)
    return {
        'productos': productos,
        'stocks': aplicar_disponibilidad_operacional(citacion, stocks),
    }


def _citacion_mantiene_reserva(citacion):
    if (
        not citacion.CI_BHABILITADO
        or citacion.CI_BARCHIVADO
        or str(citacion.CI_CESTADO or '').strip().upper() in {'RECHAZADO', 'TERMINADO'}
    ):
        return False
    camiones = list(citacion.camiones_patio.all())
    return not camiones or any(
        camion.CPA_CESTADO not in {
            CAMION_PATIO.ESTADO_RECHAZADO,
            CAMION_PATIO.ESTADO_CANCELADO,
        }
        for camion in camiones
    )


def reservas_activas(excluir_citacion_id=None, stocks=None):
    """Agrega reservas vigentes por ItemCode, WarehouseCode y BatchNumber."""
    lotes = (
        Lote.objects
        .select_related('estanque__acuerdo__carga__CI_NID', 'estanque__acuerdo__draft')
        .prefetch_related('estanque__acuerdo__carga__CI_NID__camiones_patio')
        .filter(
            estanque__acuerdo__carga__CI_NID__EP_NID_id=2,
            estanque__acuerdo__carga__CI_NID__CI_CTIPO__iexact='DESPACHO',
        )
        .order_by('estanque__acuerdo__carga__CI_NID_id', 'estanque__acuerdo__orden', 'id')
    )
    if excluir_citacion_id is not None:
        lotes = lotes.exclude(
            estanque__acuerdo__carga__CI_NID_id=excluir_citacion_id,
        )
    cantidades = defaultdict(Decimal)
    trazabilidad = defaultdict(list)
    for lote in lotes:
        acuerdo = lote.estanque.acuerdo
        citacion = acuerdo.carga.CI_NID
        if not _citacion_mantiene_reserva(citacion):
            continue
        try:
            draft = acuerdo.draft
        except Draft.DoesNotExist:
            draft = None
        if draft and reserva_acuerdo_liberada(draft, stocks=stocks):
            continue
        clave = (
            str(lote.estanque.item_code),
            str(lote.estanque.warehouse_code),
            str(lote.batch_number),
        )
        cantidades[clave] += lote.cantidad
        trazabilidad[clave].append({
            'citacion_id': citacion.id,
            'acuerdo': acuerdo.numero_acuerdo,
            'sap_abs_id': acuerdo.sap_abs_id,
            'cantidad': str(lote.cantidad),
        })
    return {'cantidades': dict(cantidades), 'trazabilidad': dict(trazabilidad)}


def aplicar_disponibilidad_operacional(citacion, stocks):
    reservas = reservas_activas(
        excluir_citacion_id=citacion.id,
        stocks=stocks,
    )
    resultado = {}
    for item_code, filas in stocks.items():
        disponibles = []
        for original in filas:
            fila = dict(original)
            stock_sap = decimal_stock(fila.get('stock'))
            if stock_sap <= 0:
                continue
            clave = (
                str(fila.get('item_code') or item_code),
                str(fila.get('warehouse_code') or ''),
                str(fila.get('batch_number') or ''),
            )
            reservado = reservas['cantidades'].get(clave, Decimal('0'))
            disponible = max(Decimal('0'), stock_sap - reservado)
            fila.update({
                'stock_sap': str(stock_sap),
                'reservado': str(reservado),
                'disponible': str(disponible),
                'stock': str(disponible),
                'estado_operacional': 'DISPONIBLE' if disponible > 0 else 'RESERVADO',
                'reservas': reservas['trazabilidad'].get(clave, []),
            })
            disponibles.append(fila)
        resultado[str(item_code)] = disponibles
    return resultado


def validar_fefo(stock, seleccion, hoy=None):
    """Valida el consumo agregado del warehouse/item en toda la citación.

    Empates de vencimiento son intercambiables; fechas ausentes permiten
    selección manual después de agotar los lotes fechados utilizables.
    """
    hoy = hoy or timezone.localdate()
    disponibles = {}
    for row in stock:
        batch = str(row['batch_number'])
        if batch in disponibles:
            raise CargaInvalida('SAP devolvió una identidad de lote ambigua.')
        vence = fecha_sap(row.get('fecha_vencimiento'))
        if vence and vence < hoy:
            continue
        disponibles[batch] = (decimal_stock(row['stock']), vence)
    for batch, qty in seleccion.items():
        if batch not in disponibles or qty > disponibles[batch][0]:
            raise CargaInvalida('Lote no disponible, vencido o cantidad mayor que su stock.')
        vence = disponibles[batch][1]
        for anterior, (saldo, fecha) in disponibles.items():
            if fecha and (vence is None or fecha < vence):
                if seleccion.get(anterior, Decimal(0)) < saldo:
                    raise CargaInvalida('FEFO: debe agotar los lotes de vencimiento anterior antes de utilizar este lote.')
    return disponibles


def validar_configuracion(citacion, data, catalogos=None):
    """Ignora cliente, vencimiento, stock y nombres enviados por el navegador."""
    _, grupos = acuerdos_planificados(citacion)
    if not isinstance(data, dict):
        raise CargaInvalida('Estructura de carga inválida.')
    total = cantidad(data.get('cantidad_total'))
    zona = str(data.get('zona_carga') or '').strip()
    if zona not in ['Línea 1', 'Línea 2', 'Línea 3', 'Línea 4']:
        raise CargaInvalida('Seleccione una zona de carga válida.')
    acuerdos = data.get('acuerdos')
    if not isinstance(acuerdos, list) or not 1 <= len(acuerdos) <= 100:
        raise CargaInvalida('Debe configurar los acuerdos planificados.')
    resultado, vistos, unidades = [], set(), set()
    usados = defaultdict(lambda: defaultdict(Decimal))
    stock_global = {}
    for raw in acuerdos:
        if not isinstance(raw, dict):
            raise CargaInvalida('Acuerdo inválido.')
        try:
            abs_id = int(str(raw.get('sap_abs_id')))
        except (ValueError, TypeError):
            raise CargaInvalida('AbsID inválido.')
        if abs_id not in grupos or abs_id in vistos:
            raise CargaInvalida('Acuerdo ajeno a la citación o repetido.')
        vistos.add(abs_id)
        catalogo = catalogos[abs_id] if catalogos is not None else catalogo_acuerdo(citacion, abs_id)
        productos = {(str(p['linea_acuerdo']), str(p['item_code'])): p for p in catalogo['productos']}
        bloques = raw.get('estanques')
        if not isinstance(bloques, list) or not 1 <= len(bloques) <= 100:
            raise CargaInvalida('Cada acuerdo requiere al menos un estanque.')
        normalizados, repetidos = [], set()
        for bloque in bloques:
            if not isinstance(bloque, dict):
                raise CargaInvalida('Bloque de estanque inválido.')
            whs = str(bloque.get('warehouse_code') or '').strip()
            item = str(bloque.get('item_code') or '').strip()
            linea = str(bloque.get('linea_acuerdo') or '').strip()
            producto = productos.get((linea, item))
            if not producto:
                raise CargaInvalida('El producto/línea no pertenece al acuerdo SAP.')
            if (whs, item) in repetidos:
                raise CargaInvalida('No repita el mismo estanque y producto dentro del acuerdo.')
            repetidos.add((whs, item))
            unidad = str(producto.get('unidad_medida') or '').strip()
            if not unidad:
                raise CargaInvalida('SAP no informó unidad de medida del producto.')
            unidades.add(unidad.casefold())
            stock = [s for s in catalogo['stocks'].get(item, []) if str(s['warehouse_code']) == whs and str(s['item_code']) == item]
            if not whs or not stock:
                raise CargaInvalida('Estanque no compatible o sin stock SBH para este producto.')
            clave = (whs, item)
            stock_global[clave] = stock
            lotes = bloque.get('lotes')
            if not isinstance(lotes, list) or not 1 <= len(lotes) <= 1000:
                raise CargaInvalida('Cada estanque/producto requiere al menos un lote.')
            seleccionados, duplicados = [], set()
            por_batch = {str(s['batch_number']): s for s in stock}
            for lote in lotes:
                if not isinstance(lote, dict):
                    raise CargaInvalida('Lote inválido.')
                batch = str(lote.get('batch_number') or '').strip()
                if batch in duplicados or batch not in por_batch:
                    raise CargaInvalida('Lote repetido o ajeno al estanque/producto.')
                duplicados.add(batch)
                qty = cantidad(lote.get('cantidad'))
                usados[clave][batch] += qty
                sap = por_batch[batch]
                seleccionados.append({'batch_number': batch, 'cantidad': qty,
                    'stock_snapshot': decimal_stock(sap.get('stock_sap', sap['stock'])),
                    'fecha_vencimiento': fecha_sap(sap.get('fecha_vencimiento'))})
            qty = cantidad(bloque.get('cantidad'))
            if sum(l['cantidad'] for l in seleccionados) != qty:
                raise CargaInvalida('La suma de lotes debe coincidir con la cantidad del estanque/producto.')
            normalizados.append({'warehouse_code': whs, 'item_code': item,
                'item_name': str(producto['item_name']), 'linea_acuerdo': linea,
                'unidad_medida': unidad, 'cantidad': qty, 'lotes': seleccionados})
        qty = cantidad(raw.get('cantidad'))
        if sum(b['cantidad'] for b in normalizados) != qty:
            raise CargaInvalida('La suma de estanques debe coincidir con la cantidad operacional del acuerdo.')
        cabecera = catalogo['productos'][0]
        resultado.append({'sap_abs_id': abs_id, 'numero_acuerdo': str(cabecera['numero_acuerdo']),
            'cliente_codigo': str(cabecera['cliente_codigo']), 'cliente_nombre': str(cabecera['cliente_nombre']),
            'oc_cliente': str(cabecera.get('oc_cliente') or ''), 'cantidad': qty, 'estanques': normalizados})
    if vistos != set(grupos):
        raise CargaInvalida('Debe configurar todos los acuerdos planificados activos.')
    if len(unidades) != 1:
        raise CargaInvalida('No se pueden sumar unidades SAP distintas sin una conversión definida.')
    if sum(a['cantidad'] for a in resultado) != total:
        raise CargaInvalida('La suma de acuerdos debe coincidir con el total operacional del despacho.')
    if len({a['cliente_codigo'] for a in resultado}) != 1:
        raise CargaInvalida('Los acuerdos deben pertenecer al mismo cliente.')
    for clave, seleccion in usados.items():
        validar_fefo(stock_global[clave], seleccion)
    return {'cantidad_total': total, 'zona_carga': zona, 'acuerdos': resultado}


def preparar_payloads(citacion, configuracion):
    detalle = CITACION_DESPACHO_DETALLE.objects.get(CI_NID=citacion)
    tipo = str(detalle.CDD_CSALIDA_DOCUMENTO or '').upper()
    if tipo not in {'GD', 'FE', 'FE_RESERVA'}:
        raise CargaInvalida('Debe existir una salida de documento GD, FE o FE_RESERVA.')
    payloads = {}
    for acuerdo in configuracion['acuerdos']:
        comentario = f"Draft despacho TERRAVIEW citacion {citacion.pk} acuerdo {acuerdo['sap_abs_id']}"
        payload = {'Series': _draft_series(), 'DocObjectCode': '15' if tipo == 'GD' else '13',
            'CardCode': acuerdo['cliente_codigo'], 'DocDate': timezone.localdate().isoformat(),
            'Comments': comentario, 'JournalMemo': comentario, 'DocumentLines': []}
        if tipo != 'GD':
            payload['ReserveInvoice'] = 'tYES' if tipo == 'FE_RESERVA' else 'tNO'
        for bloque in acuerdo['estanques']:
            payload['DocumentLines'].append({'ItemCode': bloque['item_code'],
                'AgreementNo': int(acuerdo['sap_abs_id']), 'WarehouseCode': bloque['warehouse_code'],
                'Quantity': float(bloque['cantidad']), 'BatchNumbers': [
                    {'BatchNumber': lote['batch_number'], 'Quantity': float(lote['cantidad'])}
                    for lote in bloque['lotes']]})
        payloads[acuerdo['sap_abs_id']] = payload
    return payloads


@transaction.atomic
def guardar_carga(citacion, data, usuario):
    EMPRESA.objects.select_for_update().get(pk=2)
    # Bloqueo del padre: serializa incluso la primera creación.
    citacion = CITACION.objects.select_for_update().get(pk=citacion.pk)
    validar_ambito(citacion)
    if not usa_carga_operacional(citacion):
        raise CargaInvalida('Este despacho ya tiene un Draft histórico y no puede reconfigurarse.')
    carga = CITACION_DESPACHO_CARGA.objects.filter(CI_NID=citacion).first()
    if not isinstance(data, dict) or str(data.get('version', '')) != str(carga.version if carga else 0):
        raise CargaInvalida('La carga cambió. Cierre y vuelva a abrir el modal.')
    if carga and Draft.objects.filter(acuerdo__carga=carga).exclude(estado='PREPARADO').exists():
        raise CargaInvalida('Existen envíos SAP iniciados; la carga no se puede reemplazar.')
    config = validar_configuracion(citacion, data)
    payloads = preparar_payloads(citacion, config)
    if carga is None:
        carga = CITACION_DESPACHO_CARGA(CI_NID=citacion, version=0)
    carga.version += 1
    carga.US_NID = usuario
    carga.cantidad_total = config['cantidad_total']
    carga.zona_carga = config['zona_carga']
    carga.save()
    for orden, raw in enumerate(config['acuerdos'], 1):
        valores = {k: v for k, v in raw.items() if k not in ('sap_abs_id', 'estanques')}
        acuerdo, _ = Acuerdo.objects.update_or_create(carga=carga, sap_abs_id=raw['sap_abs_id'], defaults={**valores, 'orden': orden})
        acuerdo.estanques.all().delete()
        for orden_tk, bloque in enumerate(raw['estanques'], 1):
            estanque = Estanque.objects.create(acuerdo=acuerdo, orden=orden_tk, **{k: v for k, v in bloque.items() if k != 'lotes'})
            Lote.objects.bulk_create([Lote(estanque=estanque, **lote) for lote in bloque['lotes']])
        Draft.objects.update_or_create(acuerdo=acuerdo, defaults={
            'clave_idempotencia': f'SBH-CIT-{citacion.pk}-AGR-{acuerdo.sap_abs_id}',
            'payload': payloads[acuerdo.sap_abs_id], 'estado': 'PREPARADO'})
    obsoletos = carga.acuerdos.exclude(sap_abs_id__in=payloads)
    Draft.objects.filter(acuerdo__in=obsoletos, estado='PREPARADO').delete()
    obsoletos.delete()
    return estado_carga(citacion)


def estado_carga(citacion):
    detalle, grupos = acuerdos_planificados(citacion)
    carga = CITACION_DESPACHO_CARGA.objects.filter(CI_NID=citacion).first()
    acuerdos = []
    datos_legacy = {}
    if not carga:
        datos_legacy = dict(DATO_OPERACION.objects.filter(CI_NID=citacion,
            CAMP_NID__CA_CCODIGO__in=['ACD_ZONA_CARGA', 'ACD_ESTANQUE_ORIGEN', 'ACD_INTERMES_ID'])
            .order_by('id').values_list('CAMP_NID__CA_CCODIGO', 'DO_CVALOR'))
    if carga:
        for a in carga.acuerdos.prefetch_related('estanques__lotes').select_related('draft'):
            acuerdos.append({'sap_abs_id': a.sap_abs_id, 'numero_acuerdo': a.numero_acuerdo,
                'cliente_codigo': a.cliente_codigo, 'cliente_nombre': a.cliente_nombre,
                'oc_cliente': a.oc_cliente, 'cantidad': str(a.cantidad),
                'planificacion': grupos.get(a.sap_abs_id, []),
                'draft': {'estado': a.draft.estado, 'docentry': a.draft.docentry, 'docnum': a.draft.docnum},
                'estanques': [{**{k: str(getattr(tk, k)) for k in ('warehouse_code', 'item_code', 'item_name', 'linea_acuerdo', 'unidad_medida', 'cantidad')},
                    'lotes': [{'batch_number': l.batch_number, 'cantidad': str(l.cantidad),
                        'stock_snapshot': str(l.stock_snapshot), 'fecha_vencimiento': l.fecha_vencimiento.isoformat() if l.fecha_vencimiento else None}
                        for l in tk.lotes.all()]} for tk in a.estanques.all()]})
    else:
        for abs_id, filas in grupos.items():
            f = filas[0]
            acuerdos.append({'sap_abs_id': abs_id, 'numero_acuerdo': f['contrato_sap'],
                'cliente_codigo': f['cliente_codigo'], 'cliente_nombre': f['cliente_nombre'],
                'oc_cliente': f['oc_cliente'], 'cantidad': str(detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR or '') if len(grupos) == 1 else '', 'planificacion': filas,
                'estanques': [{'warehouse_code': '', 'item_code': p['codigo_producto_sap'],
                    'linea_acuerdo': p['linea_acuerdo_sap'], 'cantidad': '', 'lotes': []} for p in filas]})
        if len(grupos) == 1 and len(acuerdos[0]['estanques']) == 1:
            bloque = acuerdos[0]['estanques'][0]
            bloque['cantidad'] = acuerdos[0]['cantidad']
            bloque['warehouse_code'] = datos_legacy.get('ACD_ESTANQUE_ORIGEN') or ''
            if datos_legacy.get('ACD_INTERMES_ID') and bloque['cantidad']:
                bloque['lotes'] = [{'batch_number': datos_legacy['ACD_INTERMES_ID'], 'cantidad': bloque['cantidad']}]
    return {'version': carga.version if carga else 0, 'guardado': bool(carga), 'hoy': timezone.localdate().isoformat(),
        'legacy': all(f['legacy'] for filas in grupos.values() for f in filas),
        'cantidad_total': str(carga.cantidad_total if carga else detalle.CDD_NCANTIDAD_INTENTADA_DESPACHAR or ''),
        'zona_carga': carga.zona_carga if carga else datos_legacy.get('ACD_ZONA_CARGA', ''), 'acuerdos': acuerdos,
        'puede_avanzar': bool(carga) and not any((a.get('draft') or {}).get('estado') in {'ENVIANDO', 'INCIERTO'} for a in acuerdos), 'mensaje': MENSAJE_PREPARADO if carga else 'Distribuya la cantidad operacional entre acuerdos y lotes.'}
