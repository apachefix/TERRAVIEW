"""Transferencia SAP exclusiva de RECEPCION PROSESA CONTENEDOR A PISO 2."""

import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests.exceptions import HTTPError

from apps.integrations.sap_b1.sap_config import SapConfigError, get_sap_company_db
from apps.integrations.sap_b1.sap_recepcion import (
    LOG_PURCHASE_DELIVERY_NOTE_PROSESA_PISO_1,
    obtener_fecha_sistema_sap,
    obtener_lote_sap_prosesa_piso_1,
)
from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient, load_config

from .models import CITACION, CITACION_PROSESA_RELACION, OPERACION_PLANTA_LOG
from .sap_di_api import _rows


LOG_TRANSFERENCIA_PROSESA_PISO_2 = 'STOCK_TRANSFER_PROSESA_PISO_2'
REFERENCIA_ORIGEN = 'TERRAVIEW'
ENDPOINT_TRANSFERENCIA = '/StockTransfers'
UNIDADES_MT = {'MT', 'TONELADAS METRICAS', 'TONELADAS MÉTRICAS'}


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('SAP devolvio una cantidad no numerica.')


def _schema_sap():
    try:
        schema = get_sap_company_db(2, for_write=False)
    except SapConfigError as exc:
        raise ValueError(str(exc)) from exc
    if not re.fullmatch(r'[A-Za-z0-9_]+', schema or ''):
        raise ValueError('CompanyDB SAP invalida para consultar la transferencia.')
    return schema


def _log_ingreso_piso_1(citacion_piso_1):
    log = OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion_piso_1,
        OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_PROSESA_PISO_1,
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).order_by('-OPL_FFECHAREGISTRO', '-id').first()
    if not log:
        raise ValueError('Piso 1 no tiene un PurchaseDeliveryNotes real confirmado.')
    try:
        data = json.loads(log.OPL_COBSERVACION or '{}')
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict) or not data.get('success'):
        raise ValueError('El registro SAP de Piso 1 no confirma el ingreso real.')
    response = data.get('response') or {}
    docentry = response.get('DocEntry') or response.get('docentry')
    try:
        docentry = int(docentry)
    except (TypeError, ValueError):
        raise ValueError('El ingreso SAP de Piso 1 no tiene DocEntry valido.')
    lines = (data.get('payload') or {}).get('DocumentLines') or []
    if len(lines) != 1:
        raise ValueError('El ingreso SAP de Piso 1 no tiene una linea unica auditable.')
    line = lines[0]
    batches = line.get('BatchNumbers') or []
    if len(batches) > 1:
        raise ValueError('El ingreso SAP de Piso 1 usa multiples lotes; requiere revision.')
    batch_number = str((batches[0] if batches else {}).get('BatchNumber') or '').strip()
    if not batch_number:
        lote_local = obtener_lote_sap_prosesa_piso_1(citacion_piso_1)
        if str(lote_local.get('item_code') or '').strip() == str(line.get('ItemCode') or '').strip():
            batch_number = str(lote_local.get('batch_number') or '').strip()
    if not batch_number:
        raise ValueError('Piso 1 no conserva el lote utilizado en el ingreso SAP.')
    return {
        'docentry': docentry,
        'docnum': response.get('DocNum') or response.get('docnum'),
        'item_code': str(line.get('ItemCode') or '').strip(),
        'warehouse': str(line.get('WarehouseCode') or '').strip(),
        'batch_number': batch_number,
        'batch_quantity': (batches[0] if batches else {}).get('Quantity'),
    }


def consultar_ingreso_virtual_prosesa_piso_1(schema, ingreso):
    """Confirma en OPDN/PDN1 la cantidad realmente contabilizada."""
    rows = _rows(f'''
        SELECT H."DocEntry" AS "docentry", H."DocNum" AS "docnum",
               L."ItemCode" AS "item_code", L."WhsCode" AS "warehouse",
               L."Quantity" AS "quantity", L."UomCode" AS "uom_code"
        FROM "{schema}"."OPDN" H
        JOIN "{schema}"."PDN1" L ON L."DocEntry" = H."DocEntry"
        WHERE H."DocEntry" = ? AND L."LineNum" = 0 AND H."CANCELED" = 'N'
    ''', [ingreso['docentry']])
    if len(rows) != 1:
        raise ValueError('No se encontro el ingreso SAP real de Piso 1 en OPDN/PDN1.')
    row = rows[0]
    if row['item_code'] != ingreso['item_code'] or row['warehouse'] != ingreso['warehouse']:
        raise ValueError('La linea del ingreso SAP no coincide con el registro de Piso 1.')
    if str(row.get('uom_code') or '').strip().upper() != 'MT':
        raise ValueError('La unidad del ingreso SAP de Piso 1 no es MT.')
    quantity = _decimal(row['quantity'])
    if quantity <= 0:
        raise ValueError('El ingreso SAP de Piso 1 no tiene cantidad positiva.')
    if ingreso['batch_quantity'] is not None and _decimal(ingreso['batch_quantity']) != quantity:
        raise ValueError('La cantidad del lote registrado no coincide con el ingreso SAP real.')
    return {'docentry': row['docentry'], 'docnum': row['docnum'], 'quantity': quantity}


def consultar_articulo_y_bodegas_prosesa(schema, item_code, origen, destino):
    rows = _rows(f'''
        SELECT I."InvntryUom" AS "unit", I."ManBtchNum" AS "batch_managed",
               O."Inactive" AS "origin_inactive", O."Locked" AS "origin_locked",
               D."Inactive" AS "destination_inactive", D."Locked" AS "destination_locked",
               W."OnHand" AS "origin_stock_total", W."IsCommited" AS "origin_committed"
        FROM "{schema}"."OITM" I
        JOIN "{schema}"."OWHS" O ON O."WhsCode" = ?
        JOIN "{schema}"."OWHS" D ON D."WhsCode" = ?
        LEFT JOIN "{schema}"."OITW" W ON W."ItemCode" = I."ItemCode" AND W."WhsCode" = ?
        WHERE I."ItemCode" = ?
    ''', [origen, destino, origen, item_code])
    if len(rows) != 1:
        raise ValueError('ItemCode o bodegas SAP no existen.')
    row = rows[0]
    if str(row['unit'] or '').strip().upper() not in UNIDADES_MT:
        raise ValueError('La unidad de inventario SAP no es tonelada metrica.')
    if row['batch_managed'] != 'Y':
        raise ValueError('SAP no confirma que el ItemCode sea administrado por lote.')
    if any(row[field] != 'N' for field in (
        'origin_inactive', 'origin_locked', 'destination_inactive', 'destination_locked'
    )):
        raise ValueError('La bodega origen o destino esta inactiva o bloqueada en SAP.')
    return row


def consultar_stock_lote_prosesa(schema, item_code, origen, batch_number):
    rows = _rows(f'''
        SELECT COALESCE(SUM(Q."Quantity"), 0) AS "stock",
               COALESCE(SUM(Q."CommitQty"), 0) AS "committed"
        FROM "{schema}"."OBTQ" Q
        JOIN "{schema}"."OBTN" B
          ON B."ItemCode" = Q."ItemCode" AND B."SysNumber" = Q."SysNumber"
        WHERE Q."ItemCode" = ? AND Q."WhsCode" = ? AND B."DistNumber" = ?
    ''', [item_code, origen, batch_number])
    row = rows[0] if rows else {}
    stock = _decimal(row.get('stock') or 0)
    committed = _decimal(row.get('committed') or 0)
    return {'stock': stock, 'committed': committed, 'available': stock - committed}


def buscar_transferencia_sap_prosesa_piso_2(schema, citacion_id):
    """Busca una transferencia no cancelada por referencias exactas de TerraView."""
    rows = _rows(f'''
        SELECT "DocEntry" AS "docentry", "DocNum" AS "docnum",
               "Filler" AS "origen", "ToWhsCode" AS "destino"
        FROM "{schema}"."OWTR"
        WHERE "Ref1" = ? AND "Ref2" = ? AND "CANCELED" = 'N'
        ORDER BY "DocEntry" DESC
    ''', [REFERENCIA_ORIGEN, str(citacion_id)])
    return rows[0] if rows else None


def estado_local_transferencia_prosesa_piso_2(citacion):
    logs = OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion, OPL_CPASO=LOG_TRANSFERENCIA_PROSESA_PISO_2,
    ).order_by('-OPL_FFECHAREGISTRO', '-id')
    rechazado = None
    for log in logs:
        try:
            data = json.loads(log.OPL_COBSERVACION or '{}')
        except (TypeError, ValueError):
            data = {}
        estado = data.get('estado')
        if estado == 'CREADO' and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO:
            return {'creada': True, 'bloqueada': True, 'estado': estado,
                    'docentry': (data.get('response') or {}).get('DocEntry'),
                    'docnum': (data.get('response') or {}).get('DocNum')}
        if estado in {'ENVIANDO', 'INCIERTO'}:
            return {'creada': False, 'bloqueada': True, 'estado': estado}
        rechazado = estado
    return {'creada': False, 'bloqueada': False, 'estado': rechazado or 'PENDIENTE'}

def build_stock_transfer_prosesa_piso_2(citacion):
    """Builder compartido por preview y envío. Solo lee TerraView y SAP HANA."""
    from .views import es_recepcion_prosesa_piso_2, obtener_peso_real_prosesa_para_sap

    preview = {
        'document_type': 'StockTransfers',
        'endpoint': ENDPOINT_TRANSFERENCIA,
        'flow': 'RECEPCION_PROSESA_PISO_2',
        'ready_for_post': False,
        'payload': {},
        'source_data': {'citacion_piso_2': citacion.id},
        'errors': [],
        'validations': [],
        'status': estado_local_transferencia_prosesa_piso_2(citacion),
    }
    errors = preview['errors']
    source = preview['source_data']
    if not es_recepcion_prosesa_piso_2(citacion):
        errors.append('La citacion no corresponde a Empresa 2, RECEPCION PROSESA Piso 2.')
        return preview

    try:
        relacion = CITACION_PROSESA_RELACION.objects.select_related('CI_NID_ORIGEN').get(
            CI_NID_RETIRO=citacion, EP_NID_id=2,
        )
    except (CITACION_PROSESA_RELACION.DoesNotExist, CITACION_PROSESA_RELACION.MultipleObjectsReturned):
        errors.append('Falta una relacion unica entre Piso 1 y Piso 2.')
        return preview
    source['citacion_piso_1'] = relacion.CI_NID_ORIGEN_id
    detalle = getattr(citacion, 'detalle_operacional', None)
    item_code = str(getattr(detalle, 'CDO_CCODIGO_SAP', '') or '').strip()
    origen = str(getattr(settings, 'BODEGA_VIRTUAL', '') or '').strip()
    destino = str(getattr(detalle, 'CDO_CESTANQUE_DESTINO', '') or '').strip()
    source.update({'item_code': item_code, 'origen': origen, 'destino': destino})
    if not item_code:
        errors.append('Falta ItemCode SAP de Piso 2.')
    if not origen:
        errors.append('Falta settings.BODEGA_VIRTUAL.')
    if not destino:
        errors.append('Falta el TK/estanque destino PROSESA.')
    if origen and destino and origen == destino:
        errors.append('La bodega origen y el TK destino deben ser distintos.')

    ingreso = None
    try:
        ingreso = _log_ingreso_piso_1(relacion.CI_NID_ORIGEN)
        source.update({
            'ingreso_docentry': ingreso['docentry'],
            'ingreso_docnum': ingreso['docnum'],
            'batch_number': ingreso['batch_number'],
        })
        if ingreso['item_code'] != item_code or ingreso['warehouse'] != origen:
            errors.append('ItemCode o bodega del ingreso Piso 1 no coinciden con Piso 2.')
    except ValueError as exc:
        errors.append(str(exc))

    schema = None
    try:
        schema = _schema_sap()
        source['company_db'] = schema
    except ValueError as exc:
        errors.append(str(exc))

    if schema and ingreso:
        try:
            doc = consultar_ingreso_virtual_prosesa_piso_1(schema, ingreso)
            source['peso_ingresado_virtual_mt'] = float(doc['quantity'])
            source['peso_ingresado_virtual_kg'] = float(doc['quantity'] * 1000)
        except Exception as exc:
            errors.append(f'No fue posible confirmar el ingreso SAP real: {exc}')

    quantity = None
    try:
        peso_real_kg = _decimal(obtener_peso_real_prosesa_para_sap(citacion))
        if peso_real_kg <= 0:
            raise ValueError('El peso real validado debe ser positivo.')
        quantity = peso_real_kg / Decimal('1000')
        source['peso_real_kg'] = float(peso_real_kg)
        source['quantity_mt'] = float(quantity)
    except ValueError as exc:
        errors.append(str(exc))
    if quantity is not None and 'peso_ingresado_virtual_kg' in source:
        remanente = _decimal(source['peso_ingresado_virtual_kg']) - peso_real_kg
        source['remanente_estimado_kg'] = float(remanente)
        source['remanente_estimado_mt'] = float(remanente / 1000)
        if remanente < 0:
            errors.append('El peso real supera la cantidad ingresada a bodega virtual.')

    if schema and ingreso and item_code and origen and destino and origen != destino:
        try:
            articulo = consultar_articulo_y_bodegas_prosesa(schema, item_code, origen, destino)
            source['unidad_sap'] = articulo['unit']
            source['stock_total_origen_mt'] = float(_decimal(articulo['origin_stock_total'] or 0))
        except Exception as exc:
            errors.append(f'No fue posible validar articulo y bodegas SAP: {exc}')
    if schema and ingreso and item_code and origen:
        try:
            stock = consultar_stock_lote_prosesa(
                schema, item_code, origen, ingreso['batch_number'],
            )
            source['stock_lote_mt'] = float(stock['stock'])
            source['stock_lote_disponible_mt'] = float(stock['available'])
            if quantity is not None:
                source['remanente_lote_mt'] = float(stock['available'] - quantity)
                if stock['available'] < quantity:
                    errors.append('Stock disponible del lote en bodega virtual insuficiente.')
        except Exception as exc:
            errors.append(f'No fue posible consultar el stock del lote SAP: {exc}')

    if schema and ingreso:
        try:
            source['fecha_sap'] = obtener_fecha_sistema_sap(schema)
        except Exception as exc:
            errors.append(f'No fue posible obtener la fecha SAP/HANA: {exc}')

    if schema and ingreso:
        try:
            existente = buscar_transferencia_sap_prosesa_piso_2(schema, citacion.id)
            if existente:
                preview['status'] = {
                    'creada': True, 'bloqueada': True, 'estado': 'CREADO_EN_SAP',
                    'docentry': existente['docentry'], 'docnum': existente['docnum'],
                }
                if existente['origen'] != origen or existente['destino'] != destino:
                    errors.append('Existe una transferencia con la referencia de esta citacion y bodegas distintas.')
                else:
                    errors.append('La transferencia SAP de esta citacion ya existe.')
        except Exception as exc:
            errors.append(f'No fue posible verificar duplicados en SAP: {exc}')
    if preview['status']['bloqueada'] and not preview['status']['creada']:
        errors.append('Existe un envio pendiente o incierto; requiere conciliacion antes de reintentar.')
    if preview['status']['creada'] and not any('ya existe' in e for e in errors):
        errors.append('La transferencia SAP de esta citacion ya fue creada.')

    if not errors:
        payload = {
            'DocDate': source['fecha_sap'],
            'FromWarehouse': origen,
            'ToWarehouse': destino,
            'Reference1': REFERENCIA_ORIGEN,
            'Reference2': str(citacion.id),
            'StockTransferLines': [{
                'ItemCode': item_code,
                'Quantity': float(quantity),
                'FromWarehouseCode': origen,
                'WarehouseCode': destino,
                'BatchNumbers': [{
                    'BatchNumber': ingreso['batch_number'],
                    'Quantity': float(quantity),
                }],
            }],
        }
        preview['payload'] = payload
        preview['ready_for_post'] = True
        preview['validations'].append(
            'Stock del lote suficiente; Quantity coincide con BatchNumbers.Quantity.'
        )
    return preview


def _actualizar_intento_transferencia(log, audit, estado, *, response=None, error='', status_code=None):
    audit.update({
        'estado': estado,
        'response': response or {},
        'error': error,
        'status_code': status_code,
        'fecha_resultado': timezone.now().isoformat(),
    })
    log.OPL_COBSERVACION = json.dumps(audit, ensure_ascii=False, default=str)
    log.OPL_CESTADO = (
        OPERACION_PLANTA_LOG.ESTADO_COMPLETADO if estado == 'CREADO'
        else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
    )
    log.save(update_fields=['OPL_COBSERVACION', 'OPL_CESTADO'])


def send_stock_transfer_prosesa_piso_2_to_sap(citacion, user):
    """Revalida y crea una sola transferencia; una respuesta ambigua bloquea reintentos."""
    from .views import es_recepcion_prosesa_piso_2

    if not es_recepcion_prosesa_piso_2(citacion):
        return {'success': False, 'message': 'Flujo SAP no aplicable.'}
    try:
        config = load_config(citacion.EP_NID_id, for_write=True)
    except Exception as exc:
        return {'success': False, 'message': f'Configuracion SAP invalida: {exc}'}

    preview = build_stock_transfer_prosesa_piso_2(citacion)
    if not preview['ready_for_post']:
        return {'success': False, 'message': 'Transferencia SAP no valida.', 'preview': preview}

    source = preview['source_data']
    payload = preview['payload']
    audit = {
        'accion': LOG_TRANSFERENCIA_PROSESA_PISO_2,
        'estado': 'ENVIANDO',
        'endpoint': ENDPOINT_TRANSFERENCIA,
        'company_db': config.company_db,
        'citacion': citacion.id,
        'citacion_piso_1': source['citacion_piso_1'],
        'ingreso_docentry': source['ingreso_docentry'],
        'item_code': source['item_code'],
        'batch_number': source['batch_number'],
        'quantity': source['quantity_mt'],
        'origen': source['origen'],
        'destino': source['destino'],
        'fecha_sap': source['fecha_sap'],
        'usuario': user.username,
        'payload': payload,
        'fecha_intento': timezone.now().isoformat(),
    }
    with transaction.atomic():
        CITACION.objects.select_for_update().get(
            pk=citacion.pk, EP_NID_id=2, CI_BHABILITADO=True,
        )
        estado = estado_local_transferencia_prosesa_piso_2(citacion)
        if estado['bloqueada']:
            return {'success': False, 'message': 'Transferencia creada o envio pendiente de conciliacion.', 'status': estado}
        try:
            existente = buscar_transferencia_sap_prosesa_piso_2(_schema_sap(), citacion.id)
        except Exception as exc:
            return {'success': False, 'message': f'No fue posible verificar duplicados SAP: {exc}'}
        if existente:
            return {'success': False, 'message': 'Transferencia SAP ya existente.', 'status': existente}
        try:
            stock_actual = consultar_stock_lote_prosesa(
                _schema_sap(), source['item_code'], source['origen'], source['batch_number'],
            )
        except Exception as exc:
            return {'success': False, 'message': f'No fue posible revalidar el stock del lote: {exc}'}
        if stock_actual['available'] < _decimal(source['quantity_mt']):
            return {'success': False, 'message': 'Stock disponible del lote insuficiente antes de enviar.'}
        log = OPERACION_PLANTA_LOG.objects.create(
            US_NID=user, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO=LOG_TRANSFERENCIA_PROSESA_PISO_2,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
            OPL_COBSERVACION=json.dumps(audit, ensure_ascii=False, default=str),
        )

    client = SapServiceLayerClient(config)
    try:
        client.login()
        result = client.post_stock_transfer(payload)
        response = result.get('data') or {}
        if not response.get('DocEntry'):
            raise ValueError('SAP respondio sin DocEntry; estado del envio incierto.')
    except Exception as exc:
        status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
        estado_error = 'RECHAZADO' if isinstance(exc, HTTPError) and status_code and 400 <= status_code < 500 else 'INCIERTO'
        _actualizar_intento_transferencia(
            log, audit, estado_error, error=str(exc), status_code=status_code,
        )
        return {
            'success': False,
            'message': (
                'SAP rechazo la transferencia.' if estado_error == 'RECHAZADO'
                else 'Resultado SAP incierto. No reintentar antes de conciliar la referencia.'
            ),
            'status': {'estado': estado_error},
        }
    finally:
        client.logout()

    _actualizar_intento_transferencia(
        log, audit, 'CREADO', response=response, status_code=result.get('status_code'),
    )
    return {
        'success': True, 'message': 'Transferencia SAP creada.',
        'docentry': response['DocEntry'], 'docnum': response.get('DocNum'),
        'origen': source['origen'], 'destino': source['destino'],
        'quantity_mt': source['quantity_mt'], 'batch_number': source['batch_number'],
        'transferencia_sap_creada': True,
    }