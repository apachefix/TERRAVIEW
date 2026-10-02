"""Solicitud SAP de traslado para New Jersey P2; el movimiento de stock pertenece a P3."""

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from requests.exceptions import HTTPError

from apps.integrations.sap_b1.sap_recepcion import (
    CAMPO_PESO_INFORMADO_GUIA,
    _dato_valor,
    obtener_fecha_sistema_sap,
)
from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient, load_config

from . import new_jersey_p2 as nj_p2
from .models import (
    CAMPO, CITACION, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION, ETAPA, OPERACION_NEW_JERSEY_PROCESO,
    OPERACION_PLANTA_LOG,
)
from .sap_di_api import _rows
from .sap_recepcion_new_jersey import (
    get_new_jersey_virtual_warehouse,
    get_purchase_delivery_note_new_jersey_p1_status,
)

ENDPOINT_SOLICITUD = '/InventoryTransferRequests'
LOG_SOLICITUD = 'NJ_P2_INVENTORY_TRANSFER_REQUEST'
CAMPO_SOLICITUD = 'NJ_P2_SOLICITUD_TRASLADO_SAP'
REFERENCIA_TERRAVIEW = 'TERRAVIEW'
MENSAJE_SOLICITUD_REQUERIDA = (
    'Debe crear la solicitud de traslado SAP antes de iniciar la descarga.'
)
UNIDADES_MT = {'MT', 'TONELADAS METRICAS'}


def es_new_jersey_p2_sap(citacion):
    return bool(
        citacion and citacion.EP_NID_id == nj_p2.EMPRESA_NJ
        and citacion.CI_CTIPO == 'RECEPCION'
        and citacion.SC_NID
        and citacion.SC_NID.SE_CCODIGO == nj_p2.SECUENCIA_P2
    )


def estado_solicitud_traslado_new_jersey_p2(citacion):
    """El log de éxito confirmado es la evidencia local que habilita Descarga."""
    for log in OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD,
    ).order_by('-OPL_FFECHAREGISTRO', '-id'):
        try:
            audit = json.loads(log.OPL_COBSERVACION or '{}')
        except (TypeError, ValueError):
            audit = {}
        if not isinstance(audit, dict):
            audit = {}
        estado = audit.get('estado')
        response = audit.get('response') or {}
        if (
            estado == 'CREADO'
            and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
            and response.get('DocEntry')
        ):
            return {
                'created': True, 'blocked': True, 'estado': estado,
                'endpoint': audit.get('endpoint') or ENDPOINT_SOLICITUD,
                'docentry': response['DocEntry'], 'docnum': response.get('DocNum'),
                'origen': audit.get('origen'), 'destino': audit.get('destino'),
                'item_code': audit.get('item_code'),
                'quantity_mt': audit.get('quantity_mt'),
                'peso_guia_kg': audit.get('peso_guia_kg'),
                'usuario': audit.get('usuario'),
                'fecha': audit.get('fecha_resultado') or audit.get('fecha_intento'),
            }
        if estado in {'ENVIANDO', 'INCIERTO'}:
            return {'created': False, 'blocked': True, 'estado': estado}
        if estado != 'RECHAZADO':
            return {'created': False, 'blocked': True, 'estado': 'INCIERTO'}
        break
    return {'created': False, 'blocked': False, 'estado': 'NO_CREADA'}


def _schema_sap():
    config = load_config(nj_p2.EMPRESA_NJ, for_write=False)
    if not re.fullmatch(r'[A-Za-z0-9_]+', config.company_db or ''):
        raise ValueError('CompanyDB SAP invalida para la solicitud P2.')
    return config.company_db


def _articulo_y_bodegas(schema, item_code, origen, destino):
    rows = _rows(f'''
        SELECT I."InvntryUom" AS "unidad",
               I."ManBtchNum" AS "administra_lotes",
               O."Inactive" AS "origen_inactivo", O."Locked" AS "origen_bloqueado",
               D."Inactive" AS "destino_inactivo", D."Locked" AS "destino_bloqueado"
        FROM "{schema}"."OITM" I
        JOIN "{schema}"."OWHS" O ON O."WhsCode" = ?
        JOIN "{schema}"."OWHS" D ON D."WhsCode" = ?
        WHERE I."ItemCode" = ?
    ''', [origen, destino, item_code])
    if len(rows) != 1:
        raise ValueError('ItemCode, bodega virtual o TK destino no existen en SAP.')
    row = rows[0]
    unidad = unicodedata.normalize('NFKD', str(row.get('unidad') or '')).upper()
    unidad = ''.join(c for c in unidad if not unicodedata.combining(c)).strip()
    if unidad not in UNIDADES_MT:
        raise ValueError('La unidad de inventario SAP del ItemCode no es MT.')
    if any(row.get(c) != 'N' for c in (
        'origen_inactivo', 'origen_bloqueado',
        'destino_inactivo', 'destino_bloqueado',
    )):
        raise ValueError('La bodega origen o el TK destino estan bloqueados en SAP.')
    return row


def buscar_solicitud_sap_new_jersey_p2(schema, citacion_id):
    """OWTQ/WTQ1 son exclusivos de la solicitud; OWTR queda para P3."""
    rows = _rows(f'''
        SELECT "DocEntry" AS "docentry", "DocNum" AS "docnum",
               "Filler" AS "origen", "ToWhsCode" AS "destino"
        FROM "{schema}"."OWTQ"
        WHERE "Ref1" = ? AND "Ref2" = ? AND "CANCELED" = 'N'
        ORDER BY "DocEntry" DESC
    ''', [REFERENCIA_TERRAVIEW, str(citacion_id)])
    return rows[0] if rows else None


def build_inventory_transfer_request_new_jersey_p2(citacion):
    """Builder único para preview y envío. No realiza POST/PATCH de negocio."""
    result = {
        'document_type': 'InventoryTransferRequests',
        'endpoint': ENDPOINT_SOLICITUD,
        'flow': nj_p2.SECUENCIA_P2,
        'ready_for_post': False,
        'payload': {},
        'errors': [], 'warnings': [],
        'source_data': {'citacion_p2': getattr(citacion, 'pk', None)},
        'status': estado_solicitud_traslado_new_jersey_p2(citacion),
    }
    errors = result['errors']
    source = result['source_data']
    if not es_new_jersey_p2_sap(citacion):
        errors.append('La citacion no corresponde a New Jersey P2 de Empresa 2.')
        return result
    try:
        proceso = OPERACION_NEW_JERSEY_PROCESO.objects.select_related(
            'ONJ_NID',
        ).get(
            CI_NID=citacion, EP_NID_id=nj_p2.EMPRESA_NJ,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
        )
        p1 = CITACION.objects.select_related('SC_NID').get(
            pk=citacion.CI_NID_REF, EP_NID_id=nj_p2.EMPRESA_NJ,
        )
        OPERACION_NEW_JERSEY_PROCESO.objects.get(
            CI_NID=p1, ONJ_NID=proceso.ONJ_NID,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
        )
    except (CITACION.DoesNotExist, OPERACION_NEW_JERSEY_PROCESO.DoesNotExist):
        errors.append('Falta relacion unica con P1 y la operacion New Jersey.')
        return result

    op = proceso.ONJ_NID
    detalle = getattr(citacion, 'detalle_operacional', None)
    origen = get_new_jersey_virtual_warehouse()
    destino = nj_p2.destino_vigente_p2(citacion)
    item_code = str(op.ONJ_CITEM_CODE or '').strip()
    guia = str(citacion.CI_CNUMERODOCUMENTO or p1.CI_CNUMERODOCUMENTO or '').strip()
    contenedor = str(getattr(detalle, 'CDO_CBL_CONTENEDOR', '') or '').strip()
    peso_raw = _dato_valor(p1, CAMPO_PESO_INFORMADO_GUIA)
    try:
        peso_kg = Decimal(str(peso_raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        peso_kg = None
    cantidad_mt = peso_kg / Decimal('1000') if peso_kg is not None else None
    source.update({
        'citacion_p1': p1.id, 'guia': guia, 'contenedor': contenedor,
        'item_code': item_code, 'producto': op.ONJ_CPRODUCTO or '',
        'purchase_order': op.ONJ_CPURCHASE_ORDER or '',
        'origen': origen, 'destino': destino,
        'peso_fuente': f'P1 DATO_OPERACION.{CAMPO_PESO_INFORMADO_GUIA}',
        'peso_guia_kg': float(peso_kg) if peso_kg is not None else None,
        'quantity_mt': float(cantidad_mt) if cantidad_mt is not None else None,
        'unidad_sap': 'MT',
    })
    if proceso.ONJP_CESTADO != proceso.Estado.EN_PROCESO:
        errors.append('P2 debe estar en proceso para crear la solicitud SAP.')
    if nj_p2.paso_actual_p2(citacion) != nj_p2.PASO_DESCARGA:
        errors.append('Debe finalizar Toma de muestra antes de solicitar el traslado SAP.')
    ingreso_p1 = get_purchase_delivery_note_new_jersey_p1_status(p1)
    source['ingreso_p1_docentry'] = ingreso_p1.get('docentry')
    source['ingreso_p1_docnum'] = ingreso_p1.get('docnum')
    if not ingreso_p1.get('sent'):
        errors.append('P1 no tiene ingreso real confirmado en bodega virtual SAP.')
    else:
        lineas_ingreso = (ingreso_p1.get('request_json') or {}).get('DocumentLines') or []
        if len(lineas_ingreso) != 1:
            errors.append('El ingreso SAP P1 no conserva una linea unica para el traslado.')
        else:
            linea_ingreso = lineas_ingreso[0]
            if (
                str(linea_ingreso.get('ItemCode') or '').strip() != item_code
                or str(linea_ingreso.get('WarehouseCode') or '').strip() != origen
            ):
                errors.append('ItemCode o bodega virtual no coinciden con el ingreso SAP P1.')
            try:
                cantidad_ingreso = Decimal(str(linea_ingreso.get('Quantity')))
            except (InvalidOperation, TypeError, ValueError):
                cantidad_ingreso = None
            if cantidad_mt is not None and cantidad_ingreso != cantidad_mt:
                errors.append('La cantidad provisional de guia difiere del ingreso SAP P1.')
    if not origen:
        errors.append('Debe configurar BODEGA_VIRTUAL_NEW_JERSEY.')
    if destino not in nj_p2.estanques_validos_p2():
        errors.append(nj_p2.MENSAJE_TK_INVALIDO_P2)
    if origen and destino and origen == destino:
        errors.append('Origen y destino SAP deben ser distintos.')
    if not item_code:
        errors.append('Falta ItemCode New Jersey.')
    if not guia:
        errors.append('Falta guia heredada de P1.')
    if not contenedor:
        errors.append('Falta contenedor heredado de P1.')
    if peso_kg is None or peso_kg <= 0:
        errors.append('Falta SAP_PESO_INFORMADO_GUIA positivo en P1.')
    if not ETAPA.objects.filter(
        EP_NID_id=nj_p2.EMPRESA_NJ, ET_CCODIGO='NJ_P2_DESCARGA',
        ET_BHABILITADO=True,
    ).exists():
        errors.append('Falta etapa Ciclo Descarga de New Jersey P2.')
    if result['status']['blocked']:
        errors.append('La solicitud SAP ya fue creada o tiene envio pendiente de conciliacion.')
    if errors:
        return result

    try:
        schema = _schema_sap()
        item = _articulo_y_bodegas(schema, item_code, origen, destino)
        source['unidad_sap_origen'] = item.get('unidad')
        source['articulo_por_lote'] = item.get('administra_lotes') == 'Y'
        source['fecha_sap'] = obtener_fecha_sistema_sap(schema)
    except Exception as exc:
        errors.append(f'No fue posible validar ItemCode, bodegas o fecha SAP: {exc}')
        return result
    if source['articulo_por_lote']:
        result['warnings'].append(
            'Solicitud sin BatchNumbers: la asignacion de lote se realizara en P3.'
        )
    comentario = (
        f'NJ P2 #{citacion.id}; P1 #{p1.id}; '
        f'Guia {guia}; Contenedor {contenedor}; PO {op.ONJ_CPURCHASE_ORDER or ""}'
    )[:254]
    result['payload'] = {
        'DocDate': source['fecha_sap'],
        'FromWarehouse': origen,
        'ToWarehouse': destino,
        'Reference1': REFERENCIA_TERRAVIEW,
        'Reference2': str(citacion.id),
        'Comments': comentario,
        'StockTransferLines': [{
            'ItemCode': item_code,
            'Quantity': float(cantidad_mt),
            'FromWarehouseCode': origen,
            'WarehouseCode': destino,
        }],
    }
    result['ready_for_post'] = True
    return result


def _guardar_intento(log, audit, estado, response=None, error='', status_code=None):
    audit.update({
        'estado': estado, 'response': response or {}, 'error': error,
        'status_code': status_code, 'fecha_resultado': timezone.now().isoformat(),
    })
    log.OPL_COBSERVACION = json.dumps(audit, ensure_ascii=False, default=str)
    log.OPL_CESTADO = (
        OPERACION_PLANTA_LOG.ESTADO_COMPLETADO if estado == 'CREADO'
        else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
    )
    log.save(update_fields=['OPL_COBSERVACION', 'OPL_CESTADO'])


def send_inventory_transfer_request_new_jersey_p2_to_sap(citacion, user):
    """Reserva el intento antes del POST y bloquea reenvíos ante resultado incierto."""
    preview = build_inventory_transfer_request_new_jersey_p2(citacion)
    if not preview['ready_for_post']:
        return {'success': False, 'message': 'Solicitud SAP P2 no valida.', 'preview': preview}
    try:
        config = load_config(nj_p2.EMPRESA_NJ, for_write=True)
        schema = _schema_sap()
    except Exception as exc:
        return {'success': False, 'message': f'Configuracion SAP invalida: {exc}'}
    if schema != config.company_db:
        return {'success': False, 'message': 'CompanyDB de lectura y escritura no coinciden.'}

    source = preview['source_data']
    payload = preview['payload']
    audit = {
        'accion': LOG_SOLICITUD, 'estado': 'ENVIANDO',
        'endpoint': ENDPOINT_SOLICITUD, 'company_db': config.company_db,
        'citacion_p1': source['citacion_p1'], 'citacion_p2': citacion.id,
        'guia': source['guia'], 'contenedor': source['contenedor'],
        'origen': source['origen'], 'destino': source['destino'],
        'item_code': source['item_code'], 'quantity_mt': source['quantity_mt'],
        'peso_guia_kg': source['peso_guia_kg'],
        'usuario': user.username, 'payload': payload,
        'fecha_intento': timezone.now().isoformat(),
    }
    with transaction.atomic():
        CITACION.objects.select_for_update().get(
            pk=citacion.pk, EP_NID_id=nj_p2.EMPRESA_NJ, CI_BHABILITADO=True,
        )
        if estado_solicitud_traslado_new_jersey_p2(citacion)['blocked']:
            return {'success': False, 'message': 'Solicitud SAP creada o pendiente de conciliacion.'}
        destino_actual = CITACION_DETALLE_OPERACIONAL.objects.filter(
            CI_NID=citacion, EP_NID_id=nj_p2.EMPRESA_NJ,
        ).values_list('CDO_CESTANQUE_DESTINO', flat=True).first()
        if str(destino_actual or '').strip() != payload['ToWarehouse']:
            return {'success': False, 'message': 'El estanque destino P2 cambió. Previsualice nuevamente la solicitud SAP.'}
        try:
            existente = buscar_solicitud_sap_new_jersey_p2(schema, citacion.id)
        except Exception as exc:
            return {'success': False, 'message': f'No fue posible verificar solicitudes SAP existentes: {exc}'}
        if existente:
            return {'success': False, 'message': 'La solicitud SAP de este P2 ya existe.', 'status': existente}
        log = OPERACION_PLANTA_LOG.objects.create(
            US_NID=user, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO=LOG_SOLICITUD,
            OPL_CPERFIL_RESPONSABLE=nj_p2.RESPONSABLE_P2,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
            OPL_COBSERVACION=json.dumps(audit, ensure_ascii=False, default=str),
        )

    client = SapServiceLayerClient(config)
    post_iniciado = False
    try:
        client.login()
        post_iniciado = True
        result = client.post_inventory_transfer_request(payload)
        response = result.get('data') or {}
        if not response.get('DocEntry'):
            raise ValueError('SAP respondio sin DocEntry; resultado incierto.')
    except Exception as exc:
        status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
        rechazado = (
            not post_iniciado
            or isinstance(exc, HTTPError) and status_code and 400 <= status_code < 500
        )
        estado = 'RECHAZADO' if rechazado else 'INCIERTO'
        _guardar_intento(log, audit, estado, error=str(exc), status_code=status_code)
        return {
            'success': False,
            'message': (
                'SAP rechazo la solicitud de traslado.'
                if rechazado else
                'Resultado SAP incierto. Conciliar Reference2 antes de reintentar.'
            ),
            'status': {'created': False, 'blocked': not rechazado, 'estado': estado},
        }
    finally:
        client.logout()

    with transaction.atomic():
        campo, _ = CAMPO.objects.get_or_create(
            EP_NID=citacion.EP_NID, CA_CCODIGO=CAMPO_SOLICITUD,
            defaults={
                'US_NID': user, 'CA_CTIPO': 'TEXTO',
                'CA_CETIQUETA': 'Solicitud traslado SAP New Jersey P2',
                'CA_BHABILITADO': True,
            },
        )
        _guardar_intento(
            log, audit, 'CREADO', response=response,
            status_code=result.get('status_code'),
        )
        DATO_OPERACION.objects.update_or_create(
            CI_NID=citacion, CAMP_NID=campo,
            defaults={
                'US_NID': user, 'EP_NID': citacion.EP_NID,
                'SC_NID': citacion.SC_NID,
                'ET_NID': ETAPA.objects.get(
                    EP_NID_id=nj_p2.EMPRESA_NJ, ET_CCODIGO='NJ_P2_DESCARGA',
                ),
                'DO_CVALOR': json.dumps(audit, ensure_ascii=False, default=str),
                'DO_FFECHAREGISTRO': timezone.now(),
            },
        )
    return {
        'success': True, 'message': 'Solicitud de traslado SAP creada.',
        'inventory_transfer_request_created': True,
        'docentry': response['DocEntry'], 'docnum': response.get('DocNum'),
        'origen': source['origen'], 'destino': source['destino'],
        'quantity_mt': source['quantity_mt'],
    }