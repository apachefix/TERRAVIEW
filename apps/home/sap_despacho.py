"""
SAP Despacho.

Centraliza la logica SAP propia del flujo de DESPACHO. En la revision de
Asistente_Recepcion SAP debe seguir oculto; este modulo deja preparados los
datos para su uso posterior, principalmente en Pesaje Salida de Despacho.
"""

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from requests import HTTPError

from apps.integrations.sap_b1.service_layer_probe import (
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    load_config,
)

from .models import CAMION_PATIO, CITACION_DESPACHO_DETALLE, DATO_OPERACION, OPERACION_PLANTA_LOG
from .sap_di_api import HANA_IDENTIFIER_RE, SapDiApiError, _load_config, _rows, consultar_acuerdos_despacho_sap


SAP_DESPACHO_DRAFT_SERIES_DEFAULT = 102
SAP_DESPACHO_DRAFT_OBJECT_CODE_DEFAULT = "13"
LOG_BORRADOR_SAP_DESPACHO_ENVIO = "BORRADOR_SAP_DESPACHO_ENVIO"
LOG_UPDATE_SAP_DESPACHO_ENVIO = "UPDATE_SAP_DESPACHO_ENVIO"
LOG_UPDATE_SAP_DESPACHO_ERROR = "SAP_UPDATE_DRAFT_ERROR"
SAP_DESPACHO_DRAFT_ESTADO_CREADO = "CREADO"
SAP_DESPACHO_UPDATE_ESTADO_PENDIENTE = "PENDIENTE"
SAP_DESPACHO_UPDATE_ESTADO_ACTUALIZADO = "ACTUALIZADO"
SAP_DESPACHO_UPDATE_ESTADO_ERROR = "ERROR"

SAP_DESPACHO_CAMPOS = (
    "sap_abs_id",
    "sap_numero_acuerdo",
    "sap_linea_acuerdo",
    "sap_cliente_codigo",
    "sap_cliente_nombre",
    "sap_oc_cliente",
    "sap_codigo_producto",
    "sap_nombre_producto",
    "sap_cantidad_planificada",
    "sap_cantidad_consumida",
    "sap_saldo_contrato",
    "sap_unidad_medida",
    "cantidad_intentada_despachar",
    "peso_informado",
    "id_intermes",
)

SALIDA_DOCUMENTO_DESPACHO_OPCIONES = {
    "factura de cliente": "Factura de cliente",
    "guia de despacho": "Gu\u00eda de despacho",
    "factura anticipada": "Factura anticipada",
}


def texto_o_primero(*valores):
    for valor in valores:
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto:
            return texto
    return ""


def decimal_or_none(valor):
    if valor in [None, ""]:
        return None
    try:
        return Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def decimal_o_primero(*valores):
    for valor in valores:
        decimal = decimal_or_none(valor)
        if decimal is not None:
            return decimal
    return None


def entero_o_none(valor):
    texto = texto_o_primero(valor)
    if not texto:
        return None
    try:
        return int(Decimal(texto.replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def json_safe(valor):
    if isinstance(valor, Decimal):
        if valor == valor.to_integral_value():
            return int(valor)
        return float(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {key: json_safe(item) for key, item in valor.items()}
    if isinstance(valor, list):
        return [json_safe(item) for item in valor]
    return valor


def parse_json_text(valor):
    try:
        data = json.loads(valor or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def json_pretty(valor):
    data = valor if isinstance(valor, dict) else parse_json_text(valor)
    if not data:
        return ""
    return json.dumps(json_safe(data), indent=2, ensure_ascii=False)


def parsear_json_despacho_legacy(*valores):
    for valor in valores:
        texto = str(valor or "").strip()
        if not texto:
            continue
        try:
            data = json.loads(texto)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _dato_operacion(citacion, codigo):
    return (
        DATO_OPERACION.objects.filter(CI_NID=citacion, CAMP_NID__CA_CCODIGO=codigo)
        .select_related("CAMP_NID")
        .order_by("-id")
        .first()
    )


def _dato_valor(citacion, codigo):
    dato = _dato_operacion(citacion, codigo)
    return texto_o_primero(dato.DO_CVALOR if dato else "")


def _detalle_despacho(citacion):
    try:
        return citacion.detalle_despacho
    except CITACION_DESPACHO_DETALLE.DoesNotExist:
        return None


def _draft_series():
    return int(getattr(settings, "SAP_DESPACHO_DRAFT_SERIES", SAP_DESPACHO_DRAFT_SERIES_DEFAULT))


def _draft_object_code():
    return str(getattr(settings, "SAP_DESPACHO_DRAFT_OBJECT_CODE", SAP_DESPACHO_DRAFT_OBJECT_CODE_DEFAULT))


def _extract_sap_error(exc):
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    data = None
    if response is not None:
        try:
            data = response.json()
        except ValueError:
            data = getattr(response, "text", "")
    return {
        "status_code": status_code,
        "error": str(exc),
        "data": data,
    }


def _sap_error_short_message(error_data):
    if not error_data:
        return ""
    if isinstance(error_data, str):
        return error_data[:500]
    if not isinstance(error_data, dict):
        return str(error_data)[:500]

    data = error_data.get("data")
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, dict):
                value = texto_o_primero(message.get("value"), message.get("lang"))
                if value:
                    return value[:500]
            value = texto_o_primero(message, error.get("code"))
            if value:
                return value[:500]
        value = texto_o_primero(data.get("message"), data.get("Message"))
        if value:
            return value[:500]
    elif data:
        return str(data)[:500]

    return texto_o_primero(error_data.get("error"), error_data.get("message"))[:500]


def get_sap_despacho_draft_status(citacion):
    detalle = _detalle_despacho(citacion)
    if not detalle or not texto_o_primero(detalle.CDD_CSAP_DRAFT_DOCENTRY):
        return {
            "created": False,
            "label": "Pendiente de crear",
        }
    return {
        "created": True,
        "label": "Borrador SAP creado",
        "docentry": detalle.CDD_CSAP_DRAFT_DOCENTRY,
        "docnum": detalle.CDD_CSAP_DRAFT_DOCNUM,
        "estado": detalle.CDD_CESTADO_DRAFT_SAP or SAP_DESPACHO_DRAFT_ESTADO_CREADO,
        "request_json": parse_json_text(detalle.CDD_CJSON_DRAFT_REQUEST),
        "response_json": parse_json_text(detalle.CDD_CJSON_DRAFT_RESPONSE),
        "fecha_hora": timezone.localtime(detalle.CDD_FFECHA_DRAFT_SAP).strftime("%d/%m/%Y %H:%M") if detalle.CDD_FFECHA_DRAFT_SAP else "",
        "usuario": detalle.CDD_USUARIO_DRAFT_SAP.username if detalle.CDD_USUARIO_DRAFT_SAP else "",
    }


def obtener_peso_salida_sap_despacho(citacion):
    dato = _dato_operacion(citacion, "OP_TICKET_PESAJE_SAL")
    metadata = parse_json_text(dato.DO_CVALOR if dato else "")
    return decimal_o_primero(
        metadata.get("peso_neto"),
        getattr(dato, "DO_NPESO", None) if dato else None,
    )


def get_sap_despacho_update_status(citacion):
    detalle = _detalle_despacho(citacion)
    peso_salida_actual = obtener_peso_salida_sap_despacho(citacion)
    if not detalle:
        return {
            "updated": False,
            "is_error": False,
            "estado": SAP_DESPACHO_UPDATE_ESTADO_PENDIENTE,
            "label": "Pendiente de actualizar SAP",
            "result_label": "PENDIENTE",
            "css_estado": "pending",
            "resumen_mensaje": "Debe actualizar el documento SAP antes de autorizar la salida.",
            "error_message": "",
            "peso_salida": json_safe(peso_salida_actual),
            "request_json": {},
            "response_json": {},
            "request_json_pretty": "",
            "response_json_pretty": "",
        }

    estado = detalle.CDD_CSAP_UPDATE_ESTADO or SAP_DESPACHO_UPDATE_ESTADO_PENDIENTE
    request_json = parse_json_text(detalle.CDD_CJSON_UPDATE_REQUEST)
    response_json = parse_json_text(detalle.CDD_CJSON_UPDATE_RESPONSE)
    error_message = _sap_error_short_message(response_json)
    label = "Pendiente de actualizar SAP"
    result_label = "PENDIENTE"
    css_estado = "pending"
    resumen_mensaje = "Debe actualizar el documento SAP antes de autorizar la salida."
    if estado == SAP_DESPACHO_UPDATE_ESTADO_ACTUALIZADO:
        label = "Documento SAP actualizado"
        result_label = "OK"
        css_estado = "ok"
        resumen_mensaje = "Borrador SAP actualizado correctamente con el peso de salida. La confirmacion final del documento queda a cargo del equipo SAP."
        error_message = ""
    elif estado == SAP_DESPACHO_UPDATE_ESTADO_ERROR:
        label = "Error al actualizar SAP"
        result_label = "ERROR"
        css_estado = "error"
        resumen_mensaje = "No se puede avanzar hasta resolver la actualizacion SAP."
    else:
        error_message = ""

    return {
        "updated": estado == SAP_DESPACHO_UPDATE_ESTADO_ACTUALIZADO,
        "is_error": estado == SAP_DESPACHO_UPDATE_ESTADO_ERROR,
        "estado": estado,
        "label": label,
        "result_label": result_label,
        "css_estado": css_estado,
        "resumen_mensaje": resumen_mensaje,
        "error_message": error_message,
        "docentry": detalle.CDD_CSAP_UPDATE_DOCENTRY or detalle.CDD_CSAP_DRAFT_DOCENTRY,
        "docnum": detalle.CDD_CSAP_DRAFT_DOCNUM,
        "peso_salida": json_safe(detalle.CDD_NSAP_PESO_SALIDA or peso_salida_actual),
        "request_json": request_json,
        "response_json": response_json,
        "request_json_pretty": json_pretty(request_json),
        "response_json_pretty": json_pretty(response_json),
        "fecha_hora": timezone.localtime(detalle.CDD_FFECHA_UPDATE_SAP).strftime("%d/%m/%Y %H:%M") if detalle.CDD_FFECHA_UPDATE_SAP else "",
        "usuario": detalle.CDD_USUARIO_UPDATE_SAP.username if detalle.CDD_USUARIO_UPDATE_SAP else "",
    }


def construir_payload_draft_despacho(citacion):
    errors = []
    validations = []
    warnings = []
    detalle = _detalle_despacho(citacion)
    detalle_resumen = detalle_despacho_resumen_dict(citacion)
    camion_patio = (
        CAMION_PATIO.objects
        .filter(CI_NID=citacion)
        .order_by('-CPA_FFECHAASOCIACION', '-id')
        .first()
    )
    tipo_documento = texto_o_primero(
        getattr(camion_patio, 'CPA_CTIPO_DOCUMENTO', '') if camion_patio else ''
    ).upper()
    numero_documento = texto_o_primero(
        getattr(camion_patio, 'CPA_CNUMERO_GUIA', '') if camion_patio else ''
    )
    folio_number = int(numero_documento) if numero_documento.isdigit() else None

    item_code = texto_o_primero(
        _dato_valor(citacion, "ACD_CODIGO_SAP"),
        detalle_resumen.get("sap_codigo_producto"),
    )
    warehouse_code = texto_o_primero(_dato_valor(citacion, "ACD_ESTANQUE_ORIGEN"))
    batch_number = texto_o_primero(
        _dato_valor(citacion, "ACD_INTERMES_ID"),
        _dato_valor(citacion, "AR_INTERMES_ID"),
    )
    quantity = decimal_o_primero(
        _dato_valor(citacion, "ACD_PESO_INFORMADO"),
        getattr(detalle, "CDD_NPESO_INFORMADO", None) if detalle else None,
    )
    card_code = texto_o_primero(
        detalle_resumen.get("sap_cliente_codigo"),
        citacion.SN_NID.SN_CCODIGO_SAP if citacion.SN_NID else "",
    )
    sap_abs_id = texto_o_primero(detalle_resumen.get("sap_abs_id"))
    sap_numero_acuerdo = texto_o_primero(detalle_resumen.get("sap_numero_acuerdo"))
    agreement_no = entero_o_none(sap_abs_id)
    doc_date = timezone.localdate().isoformat()
    comment = f"Draft despacho TERRAVIEW citacion {citacion.id}"

    source_data = {
        "citacion": citacion.id,
        "empresa": citacion.EP_NID_id,
        "series": _draft_series(),
        "doc_object_code": _draft_object_code(),
        "card_code": card_code,
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "folio_number": folio_number,
        "item_code": item_code,
        "agreement_no": agreement_no,
        "sap_abs_id": sap_abs_id,
        "sap_numero_acuerdo": sap_numero_acuerdo,
        "warehouse_code": warehouse_code,
        "quantity": json_safe(quantity),
        "batch_number": batch_number,
        "doc_date": doc_date,
    }

    if tipo_documento not in dict(CAMION_PATIO.TIPOS_DOCUMENTO):
        errors.append('No se puede crear borrador SAP: falta un tipo de documento valido (GD o FE).')
    if not numero_documento:
        errors.append('No se puede crear borrador SAP: falta numero de guia/documento.')
    elif folio_number is None:
        errors.append('No se puede crear borrador SAP: el numero de guia/documento debe ser numerico.')

    if not sap_abs_id:
        errors.append("No se puede crear borrador SAP: falta SAP AbsID del acuerdo global.")
    elif agreement_no:
        validations.append(f"SAP AbsID / DocEntry acuerdo: {agreement_no}")
    else:
        errors.append("No se puede crear borrador SAP: SAP AbsID del acuerdo global debe ser numerico.")

    for value, label in [
        (card_code, "Cliente SAP / CardCode"),
        (item_code, "Codigo SAP / ItemCode"),
        (warehouse_code, "Estanque Origen / WarehouseCode"),
        (quantity, "Peso informado / Quantity"),
        (batch_number, "Lote / BatchNumber"),
    ]:
        if value:
            validations.append(f"{label}: {json_safe(value)}")
        else:
            errors.append(f"Falta {label}.")

    if quantity is not None and quantity <= 0:
        errors.append("Peso informado / Quantity debe ser mayor a 0.")

    payload = {}
    if not errors:
        payload = {
            "Series": _draft_series(),
            "DocObjectCode": _draft_object_code(),
            "CardCode": card_code,
            "FolioPrefixString": tipo_documento,
            "FolioNumber": folio_number,
            "DocDate": doc_date,
            "Comments": comment,
            "JournalMemo": comment,
            "DocumentLines": [
                {
                    "ItemCode": item_code,
                    "AgreementNo": agreement_no,
                    "WarehouseCode": warehouse_code,
                    "Quantity": json_safe(quantity),
                    "BatchNumbers": [
                        {
                            "ItemCode": item_code,
                            "BatchNumber": batch_number,
                            "Quantity": json_safe(quantity),
                        }
                    ],
                }
            ],
        }

    return {
        "payload": payload,
        "source_data": source_data,
        "validations": validations,
        "warnings": warnings,
        "errors": errors,
        "status": get_sap_despacho_draft_status(citacion),
    }


def construir_payload_update_draft_despacho(citacion):
    errors = []
    validations = []
    warnings = []
    detalle = _detalle_despacho(citacion)
    draft_status = get_sap_despacho_draft_status(citacion)
    update_status = get_sap_despacho_update_status(citacion)
    docentry_texto = texto_o_primero(draft_status.get("docentry"))
    docentry = entero_o_none(docentry_texto)
    peso_salida = obtener_peso_salida_sap_despacho(citacion)
    stored_draft_payload = parse_json_text(detalle.CDD_CJSON_DRAFT_REQUEST if detalle else "")

    if not docentry_texto:
        errors.append("No se puede actualizar SAP: falta DocEntry del borrador SAP.")
    elif not docentry:
        errors.append("No se puede actualizar SAP: DocEntry del borrador SAP debe ser numerico.")
    else:
        validations.append(f"Draft DocEntry: {docentry}")

    if peso_salida is None or peso_salida <= 0:
        errors.append("No se puede actualizar SAP: falta pesaje de salida.")
    else:
        validations.append(f"Peso salida real: {json_safe(peso_salida)}")

    draft_preview = construir_payload_draft_despacho(citacion)
    if not stored_draft_payload and draft_preview.get("errors"):
        errors.extend(draft_preview.get("errors") or [])

    base_payload = stored_draft_payload or draft_preview.get("payload") or {}
    document_lines = base_payload.get("DocumentLines") or []
    if not document_lines:
        errors.append("No se puede actualizar SAP: falta linea del borrador SAP.")
    elif not (document_lines[0].get("BatchNumbers") or []):
        errors.append("No se puede actualizar SAP: falta lote del borrador SAP.")

    payload = {}
    if not errors and base_payload:
        payload = json_safe(base_payload)
        document_lines = payload.get("DocumentLines") or []
        if document_lines:
            document_lines[0]["Quantity"] = json_safe(peso_salida)
            batch_numbers = document_lines[0].get("BatchNumbers") or []
            if batch_numbers:
                batch_numbers[0]["Quantity"] = json_safe(peso_salida)
        payload["Comments"] = payload.get("Comments") or f"Draft despacho TERRAVIEW citacion {citacion.id}"
        payload["JournalMemo"] = payload.get("JournalMemo") or payload["Comments"]

    return {
        "payload": payload,
        "source_data": {
            **draft_preview.get("source_data", {}),
            "draft_docentry": docentry,
            "draft_docnum": draft_status.get("docnum") or "",
            "peso_salida": json_safe(peso_salida),
            "endpoint": f"/Drafts({docentry})" if docentry else "",
        },
        "validations": validations,
        "warnings": warnings,
        "errors": errors,
        "status": update_status,
        "draft_status": draft_status,
    }


def guardar_respuesta_borrador_sap_despacho(citacion, usuario, request_json, response_json):
    detalle, _ = CITACION_DESPACHO_DETALLE.objects.get_or_create(
        CI_NID=citacion,
        defaults={
            "EP_NID": citacion.EP_NID,
            "US_NID": usuario or citacion.US_NID,
        },
    )
    docentry = texto_o_primero(response_json.get("DocEntry"), response_json.get("docentry"))
    docnum = texto_o_primero(response_json.get("DocNum"), response_json.get("docnum"))
    detalle.CDD_CSAP_DRAFT_DOCENTRY = docentry
    detalle.CDD_CSAP_DRAFT_DOCNUM = docnum
    detalle.CDD_CJSON_DRAFT_REQUEST = json.dumps(json_safe(request_json), ensure_ascii=False)
    detalle.CDD_CJSON_DRAFT_RESPONSE = json.dumps(json_safe(response_json), ensure_ascii=False)
    detalle.CDD_FFECHA_DRAFT_SAP = timezone.now()
    detalle.CDD_USUARIO_DRAFT_SAP = usuario
    detalle.CDD_CESTADO_DRAFT_SAP = SAP_DESPACHO_DRAFT_ESTADO_CREADO
    detalle.save(update_fields=[
        "CDD_CSAP_DRAFT_DOCENTRY",
        "CDD_CSAP_DRAFT_DOCNUM",
        "CDD_CJSON_DRAFT_REQUEST",
        "CDD_CJSON_DRAFT_RESPONSE",
        "CDD_FFECHA_DRAFT_SAP",
        "CDD_USUARIO_DRAFT_SAP",
        "CDD_CESTADO_DRAFT_SAP",
        "CDD_FFECHAACTUALIZACION",
    ])
    return detalle


def guardar_respuesta_update_sap_despacho(citacion, usuario, docentry, peso_salida, request_json, response_json, estado):
    detalle, _ = CITACION_DESPACHO_DETALLE.objects.get_or_create(
        CI_NID=citacion,
        defaults={
            "EP_NID": citacion.EP_NID,
            "US_NID": usuario or citacion.US_NID,
        },
    )
    detalle.CDD_CSAP_UPDATE_ESTADO = estado
    detalle.CDD_CSAP_UPDATE_DOCENTRY = texto_o_primero(docentry)
    detalle.CDD_CJSON_UPDATE_REQUEST = json.dumps(json_safe(request_json), ensure_ascii=False)
    detalle.CDD_CJSON_UPDATE_RESPONSE = json.dumps(json_safe(response_json), ensure_ascii=False)
    detalle.CDD_FFECHA_UPDATE_SAP = timezone.now()
    detalle.CDD_USUARIO_UPDATE_SAP = usuario
    detalle.CDD_NSAP_PESO_SALIDA = peso_salida
    detalle.save(update_fields=[
        "CDD_CSAP_UPDATE_ESTADO",
        "CDD_CSAP_UPDATE_DOCENTRY",
        "CDD_CJSON_UPDATE_REQUEST",
        "CDD_CJSON_UPDATE_RESPONSE",
        "CDD_FFECHA_UPDATE_SAP",
        "CDD_USUARIO_UPDATE_SAP",
        "CDD_NSAP_PESO_SALIDA",
        "CDD_FFECHAACTUALIZACION",
    ])
    return detalle


def obtener_docentry_draft_sap_despacho(citacion):
    # Para actualizacion/finalizacion posterior SAP Despacho,
    # usar CDD_CSAP_DRAFT_DOCENTRY como referencia principal.
    detalle = _detalle_despacho(citacion)
    return texto_o_primero(detalle.CDD_CSAP_DRAFT_DOCENTRY if detalle else "")


def _registrar_log_borrador_sap_despacho(citacion, usuario, success, payload, response=None, status_code=None, sap_error=None):
    log_data = {
        "accion": LOG_BORRADOR_SAP_DESPACHO_ENVIO,
        "success": success,
        "citacion": citacion.id,
        "status_code": status_code,
        "payload": json_safe(payload),
        "response": json_safe(response or {}),
        "sap_error": sap_error or {},
        "usuario": getattr(usuario, "username", ""),
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
    }
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=usuario,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO=LOG_BORRADOR_SAP_DESPACHO_ENVIO,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE C D",
        OPL_CESTADO=(
            OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
            if success
            else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
        ),
        OPL_COBSERVACION=json.dumps(log_data, ensure_ascii=False),
    )


def _registrar_log_update_sap_despacho(citacion, usuario, success, payload, response=None, status_code=None, sap_error=None):
    accion = LOG_UPDATE_SAP_DESPACHO_ENVIO if success else LOG_UPDATE_SAP_DESPACHO_ERROR
    log_data = {
        "accion": accion,
        "success": success,
        "citacion": citacion.id,
        "tipo": citacion.CI_CTIPO,
        "secuencia": citacion.SC_NID.SE_CCODIGO if citacion.SC_NID else "",
        "status_code": status_code,
        "estado": "OK" if success else "ERROR",
        "mensaje_corto": _sap_error_short_message(sap_error or response or {}),
        "payload": json_safe(payload),
        "response": json_safe(response or {}),
        "sap_error": sap_error or {},
        "usuario": getattr(usuario, "username", ""),
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
    }
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=usuario,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO=accion,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE DE RECEPCION",
        OPL_CESTADO=(
            OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
            if success
            else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
        ),
        OPL_COBSERVACION=(
            "Documento SAP actualizado con peso de salida."
            if success
            else f"Error actualizacion SAP despacho: {log_data.get('mensaje_corto') or 'Revisar detalle tecnico persistido.'}"
        ),
    )


def crear_borrador_sap_despacho(citacion, usuario, allow_duplicate=False):
    existing_status = get_sap_despacho_draft_status(citacion)
    if existing_status.get("created") and not allow_duplicate:
        docentry = existing_status.get("docentry") or ""
        docnum = existing_status.get("docnum") or ""
        return {
            "success": False,
            "message": f"La citacion ya tiene un borrador SAP creado. DocEntry: {docentry} DocNum: {docnum}",
            "status": existing_status,
        }

    preview = construir_payload_draft_despacho(citacion)
    if preview.get("errors") or not preview.get("payload"):
        return {
            "success": False,
            "message": "Faltan datos obligatorios para crear el borrador SAP de despacho.",
            "preview": preview,
            "status": existing_status,
        }

    config = load_config()
    client = SapServiceLayerClient(config)
    status_code = None
    response_payload = {}
    try:
        print(
            f"\n[Borrador SAP][Despacho] citacion={citacion.id} empresa={citacion.EP_NID_id} "
            f"CompanyDB={config.company_db} endpoint=/Drafts"
        )
        print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))
        client.login()
        sap_response = client.post_draft(preview["payload"])
        status_code = sap_response.get("status_code")
        response_payload = sap_response.get("data") or {}
    except HTTPError as exc:
        error_data = _extract_sap_error(exc)
        _registrar_log_borrador_sap_despacho(
            citacion,
            usuario,
            success=False,
            payload=preview["payload"],
            status_code=error_data.get("status_code"),
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": "SAP rechazo la creacion del borrador de despacho.",
            "status_code": error_data.get("status_code"),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_draft_status(citacion),
        }
    except SapServiceLayerProbeError as exc:
        error_data = {"error": str(exc)}
        _registrar_log_borrador_sap_despacho(
            citacion,
            usuario,
            success=False,
            payload=preview["payload"],
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": str(exc),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_draft_status(citacion),
        }
    finally:
        client.logout()

    guardar_respuesta_borrador_sap_despacho(citacion, usuario, preview["payload"], response_payload)
    _registrar_log_borrador_sap_despacho(
        citacion,
        usuario,
        success=True,
        payload=preview["payload"],
        response=response_payload,
        status_code=status_code,
    )
    return {
        "success": True,
        "message": "Borrador SAP de despacho creado.",
        "status_code": status_code,
        "request_json": preview["payload"],
        "response": response_payload,
        "preview": preview,
        "status": get_sap_despacho_draft_status(citacion),
    }


def actualizar_borrador_sap_despacho(citacion, usuario, allow_retry=False):
    existing_status = get_sap_despacho_update_status(citacion)
    if existing_status.get("updated") and not allow_retry:
        return {
            "success": True,
            "message": "Documento SAP actualizado.",
            "status": existing_status,
        }

    preview = construir_payload_update_draft_despacho(citacion)
    docentry = preview.get("source_data", {}).get("draft_docentry")
    peso_salida = decimal_or_none(preview.get("source_data", {}).get("peso_salida"))
    if preview.get("errors") or not preview.get("payload"):
        message = preview["errors"][0] if preview.get("errors") else "Faltan datos obligatorios para actualizar SAP."
        return {
            "success": False,
            "message": message,
            "preview": preview,
            "status": existing_status,
        }

    config = load_config()
    client = SapServiceLayerClient(config)
    status_code = None
    response_payload = {}
    try:
        print(
            f"\n[Update SAP][Despacho] citacion={citacion.id} empresa={citacion.EP_NID_id} "
            f"CompanyDB={config.company_db} endpoint=/Drafts({docentry})"
        )
        print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))
        client.login()
        sap_response = client.patch_draft(docentry, preview["payload"])
        status_code = sap_response.get("status_code")
        response_payload = sap_response.get("data") or {
            "status_code": status_code,
            "message": "Service Layer respondio sin cuerpo.",
        }
    except HTTPError as exc:
        error_data = _extract_sap_error(exc)
        guardar_respuesta_update_sap_despacho(
            citacion,
            usuario,
            docentry,
            peso_salida,
            preview["payload"],
            error_data,
            SAP_DESPACHO_UPDATE_ESTADO_ERROR,
        )
        _registrar_log_update_sap_despacho(
            citacion,
            usuario,
            success=False,
            payload=preview["payload"],
            status_code=error_data.get("status_code"),
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": "SAP rechazo la actualizacion del documento de despacho.",
            "status_code": error_data.get("status_code"),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_update_status(citacion),
        }
    except SapServiceLayerProbeError as exc:
        error_data = {"error": str(exc)}
        guardar_respuesta_update_sap_despacho(
            citacion,
            usuario,
            docentry,
            peso_salida,
            preview["payload"],
            error_data,
            SAP_DESPACHO_UPDATE_ESTADO_ERROR,
        )
        _registrar_log_update_sap_despacho(
            citacion,
            usuario,
            success=False,
            payload=preview["payload"],
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": str(exc),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_update_status(citacion),
        }
    finally:
        client.logout()

    guardar_respuesta_update_sap_despacho(
        citacion,
        usuario,
        docentry,
        peso_salida,
        preview["payload"],
        response_payload,
        SAP_DESPACHO_UPDATE_ESTADO_ACTUALIZADO,
    )
    _registrar_log_update_sap_despacho(
        citacion,
        usuario,
        success=True,
        payload=preview["payload"],
        response=response_payload,
        status_code=status_code,
    )
    return {
        "success": True,
        "message": "Documento SAP actualizado.",
        "status_code": status_code,
        "request_json": preview["payload"],
        "response": response_payload,
        "preview": preview,
        "status": get_sap_despacho_update_status(citacion),
    }


def normalizar_salida_documento_despacho(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    clave = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
    return SALIDA_DOCUMENTO_DESPACHO_OPCIONES.get(clave, "")


def guardar_detalle_despacho_citacion(citacion, data, usuario=None):
    if str(citacion.CI_CTIPO or "").upper() != "DESPACHO":
        return None

    observacion_legacy = parsear_json_despacho_legacy(data.get("observacion"))
    sap_legacy = observacion_legacy.get("sap") if isinstance(observacion_legacy.get("sap"), dict) else {}
    salida_documento = normalizar_salida_documento_despacho(
        texto_o_primero(data.get("salida_documento"), observacion_legacy.get("salida_documento"))
    )
    detalle, _ = CITACION_DESPACHO_DETALLE.objects.update_or_create(
        CI_NID=citacion,
        defaults={
            "EP_NID": citacion.EP_NID,
            "US_NID": usuario or citacion.US_NID,
            "CDD_CDESTINO": texto_o_primero(data.get("destino"), data.get("estanque_destino_texto"), observacion_legacy.get("destino")),
            "CDD_COC_CLIENTE": texto_o_primero(data.get("oc_cliente"), data.get("pedido"), observacion_legacy.get("oc")),
            "CDD_NCANTIDAD_INTENTADA_DESPACHAR": decimal_o_primero(data.get("cantidad_intentada_despachar"), observacion_legacy.get("cantidad_intentada_despachar")),
            "CDD_CCONDICION_ENTREGA": texto_o_primero(data.get("condicion_entrega"), data.get("inf_24hrs"), observacion_legacy.get("condicion_entrega"), observacion_legacy.get("transportado_por")),
            "CDD_CSALIDA_DOCUMENTO": salida_documento,
            "CDD_CEMPRESA_TRANSPORTE": texto_o_primero(data.get("empresa_transporte"), data.get("proveedor_nombre"), observacion_legacy.get("empresa_transporte")),
            "CDD_CCONDUCTOR": texto_o_primero(data.get("conductor"), observacion_legacy.get("conductor")),
            "CDD_CTELEFONO_CONDUCTOR": texto_o_primero(data.get("telefono_conductor"), observacion_legacy.get("telefono_conductor")),
            "CDD_CPATENTE": texto_o_primero(data.get("patente"), observacion_legacy.get("patente")),
            "CDD_CORDEN_CARGA": texto_o_primero(data.get("orden_carga"), observacion_legacy.get("orden_carga")),
            "CDD_CVENTANA_HORARIA_DESPACHO": texto_o_primero(data.get("ventana_horaria_despacho"), observacion_legacy.get("ventana_horaria")),
            "CDD_NPESO_INFORMADO": decimal_o_primero(data.get("peso_informado"), data.get("peso_informado_despacho"), observacion_legacy.get("peso_informado")),
            "CDD_CBODEGA": texto_o_primero(data.get("bodega"), data.get("estanque_destino"), observacion_legacy.get("bodega")),
            "CDD_CSECUENCIA_OPERACIONAL_CODIGO": texto_o_primero(data.get("secuencia_operacional_codigo"), data.get("secuencia_codigo")),
            "CDD_CSECUENCIA_OPERACIONAL_NOMBRE": texto_o_primero(data.get("secuencia_operacional_nombre"), data.get("secuencia_nombre"), citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else ""),
            "CDD_CSAP_ABS_ID": texto_o_primero(data.get("sap_abs_id"), data.get("sap_opor_id"), data.get("docentry"), sap_legacy.get("abs_id")),
            "CDD_CSAP_NUMERO_ACUERDO": texto_o_primero(data.get("sap_numero_acuerdo"), data.get("contrato_sap"), sap_legacy.get("numero_acuerdo")),
            "CDD_CSAP_LINEA_ACUERDO": texto_o_primero(data.get("sap_linea_acuerdo"), data.get("linea_acuerdo_sap"), sap_legacy.get("linea_acuerdo")),
            "CDD_CSAP_CLIENTE_CODIGO": texto_o_primero(data.get("sap_cliente_codigo"), data.get("cliente_codigo")),
            "CDD_CSAP_CLIENTE_NOMBRE": texto_o_primero(data.get("sap_cliente_nombre"), data.get("cliente_nombre"), data.get("cliente")),
            "CDD_CSAP_OC_CLIENTE": texto_o_primero(data.get("sap_oc_cliente"), data.get("pedido"), observacion_legacy.get("oc")),
            "CDD_CSAP_CODIGO_PRODUCTO": texto_o_primero(data.get("sap_codigo_producto"), data.get("codigo"), sap_legacy.get("codigo_producto")),
            "CDD_CSAP_NOMBRE_PRODUCTO": texto_o_primero(data.get("sap_nombre_producto"), data.get("insumo"), sap_legacy.get("nombre_producto")),
            "CDD_NSAP_CANTIDAD_PLANIFICADA": decimal_o_primero(data.get("sap_cantidad_planificada"), data.get("cantidad_planificada_sap"), sap_legacy.get("cantidad_planificada")),
            "CDD_NSAP_CANTIDAD_CONSUMIDA": decimal_o_primero(data.get("sap_cantidad_consumida"), data.get("cantidad_consumida_sap"), sap_legacy.get("cantidad_consumida")),
            "CDD_NSAP_SALDO_CONTRATO": decimal_o_primero(data.get("sap_saldo_contrato"), data.get("saldo_contrato_sap"), data.get("cantidad_disponible"), sap_legacy.get("saldo_contrato")),
            "CDD_CSAP_UNIDAD_MEDIDA": texto_o_primero(data.get("sap_unidad_medida"), data.get("tipo_carga")),
        },
    )
    return detalle


def detalle_despacho_resumen_dict(citacion, detalle_operacional=None):
    detalle_operacional = detalle_operacional or {}
    try:
        detalle = citacion.detalle_despacho
    except CITACION_DESPACHO_DETALLE.DoesNotExist:
        detalle = None

    observacion_legacy = parsear_json_despacho_legacy(
        detalle_operacional.get("observacion"),
        citacion.CI_CCOMENTARIO,
    )
    sap_legacy = observacion_legacy.get("sap") if isinstance(observacion_legacy.get("sap"), dict) else {}

    def campo(nombre, legacy_key=None, operacional_key=None, sap_key=None):
        valor_detalle = getattr(detalle, nombre, None) if detalle else None
        return texto_o_primero(
            valor_detalle,
            detalle_operacional.get(operacional_key) if operacional_key else None,
            sap_legacy.get(sap_key) if sap_key else None,
            observacion_legacy.get(legacy_key) if legacy_key else None,
        )

    def campo_decimal(nombre, legacy_key=None, operacional_key=None, sap_key=None):
        valor_detalle = getattr(detalle, nombre, None) if detalle else None
        return decimal_o_primero(
            valor_detalle,
            detalle_operacional.get(operacional_key) if operacional_key else None,
            sap_legacy.get(sap_key) if sap_key else None,
            observacion_legacy.get(legacy_key) if legacy_key else None,
        )

    return {
        "destino": campo("CDD_CDESTINO", legacy_key="destino", operacional_key="estanque_destino_texto"),
        "oc_cliente": campo("CDD_COC_CLIENTE", legacy_key="oc", operacional_key="pedido"),
        "cantidad_intentada_despachar": campo_decimal("CDD_NCANTIDAD_INTENTADA_DESPACHAR", legacy_key="cantidad_intentada_despachar"),
        "condicion_entrega": campo("CDD_CCONDICION_ENTREGA", legacy_key="condicion_entrega", operacional_key="inf_24hrs") or observacion_legacy.get("transportado_por", ""),
        "salida_documento": campo("CDD_CSALIDA_DOCUMENTO", legacy_key="salida_documento"),
        "empresa_transporte": campo("CDD_CEMPRESA_TRANSPORTE", legacy_key="empresa_transporte", operacional_key="proveedor_sap"),
        "conductor": campo("CDD_CCONDUCTOR", legacy_key="conductor"),
        "telefono_conductor": campo("CDD_CTELEFONO_CONDUCTOR", legacy_key="telefono_conductor"),
        "patente": campo("CDD_CPATENTE", legacy_key="patente", operacional_key="bl"),
        "orden_carga": campo("CDD_CORDEN_CARGA", legacy_key="orden_carga"),
        "ventana_horaria_despacho": campo("CDD_CVENTANA_HORARIA_DESPACHO", legacy_key="ventana_horaria"),
        "peso_informado": campo_decimal("CDD_NPESO_INFORMADO", legacy_key="peso_informado"),
        "bodega": campo("CDD_CBODEGA", legacy_key="bodega", operacional_key="estanque_destino"),
        "secuencia_operacional_codigo": campo("CDD_CSECUENCIA_OPERACIONAL_CODIGO"),
        "secuencia_operacional_nombre": campo("CDD_CSECUENCIA_OPERACIONAL_NOMBRE") or (citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else ""),
        "sap_abs_id": campo("CDD_CSAP_ABS_ID", operacional_key="sap_opor_id", sap_key="abs_id") or detalle_operacional.get("docentry", ""),
        "sap_numero_acuerdo": campo("CDD_CSAP_NUMERO_ACUERDO", operacional_key="contrato_sap", sap_key="numero_acuerdo"),
        "sap_linea_acuerdo": campo("CDD_CSAP_LINEA_ACUERDO", sap_key="linea_acuerdo"),
        "sap_cliente_codigo": campo("CDD_CSAP_CLIENTE_CODIGO"),
        "sap_cliente_nombre": campo("CDD_CSAP_CLIENTE_NOMBRE") or (citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else ""),
        "sap_oc_cliente": campo("CDD_CSAP_OC_CLIENTE", legacy_key="oc", operacional_key="pedido"),
        "sap_codigo_producto": campo("CDD_CSAP_CODIGO_PRODUCTO", operacional_key="codigo", sap_key="codigo_producto"),
        "sap_nombre_producto": campo("CDD_CSAP_NOMBRE_PRODUCTO", operacional_key="insumo", sap_key="nombre_producto"),
        "sap_cantidad_planificada": campo_decimal("CDD_NSAP_CANTIDAD_PLANIFICADA", sap_key="cantidad_planificada"),
        "sap_cantidad_consumida": campo_decimal("CDD_NSAP_CANTIDAD_CONSUMIDA", sap_key="cantidad_consumida"),
        "sap_cantidad_pendiente": texto_o_primero(detalle_operacional.get("cantidad_pendiente_sap"), sap_legacy.get("cantidad_pendiente")),
        "sap_saldo_contrato": campo_decimal("CDD_NSAP_SALDO_CONTRATO", operacional_key="cantidad_disponible", sap_key="saldo_contrato"),
        "sap_estado_saldo": texto_o_primero(detalle_operacional.get("estado_saldo_sap"), sap_legacy.get("estado_saldo")),
        "sap_unidad_medida": campo("CDD_CSAP_UNIDAD_MEDIDA"),
    }


def consultar_acuerdos_despacho(termino):
    return consultar_acuerdos_despacho_sap(termino)


def _sap_hana_company_db_despacho():
    company_db = (_load_config().get("CompanyDB") or "").strip()
    if not company_db or not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError("CompanyDB HANA tiene un formato no valido.")
    return company_db


def _normalizar_item_o_whs(valor):
    return str(valor or "").strip()


def consultar_estanques_oibt_despacho(item_code):
    item_code = _normalizar_item_o_whs(item_code)
    if not item_code:
        raise SapDiApiError("No se puede consultar SAP: falta Codigo SAP del producto.")
    company_db = _sap_hana_company_db_despacho()
    sql = f'''
        SELECT
            T0."WhsCode",
            SUM(T0."Quantity") AS "QuantityTotal",
            COUNT(*) AS "TotalLotes"
        FROM "{company_db}"."OIBT" T0
        WHERE T0."ItemCode" = ?
          AND T0."Quantity" > 0
          AND T0."Status" = 0
        GROUP BY T0."WhsCode"
        ORDER BY T0."WhsCode"
    '''
    rows = _rows(sql, [item_code])
    return {
        "ok": True,
        "company_db": company_db,
        "item_code": item_code,
        "resultados": rows,
    }


def consultar_lotes_oibt_despacho(item_code, whs_code):
    item_code = _normalizar_item_o_whs(item_code)
    whs_code = _normalizar_item_o_whs(whs_code)
    if not item_code:
        raise SapDiApiError("No se puede consultar SAP: falta Codigo SAP del producto.")
    if not whs_code:
        raise SapDiApiError("Debe seleccionar Estanque Origen.")
    company_db = _sap_hana_company_db_despacho()
    sql = f'''
        SELECT
            T0."ItemCode",
            T0."ItemName",
            T0."WhsCode",
            T0."Quantity",
            T0."BatchNum",
            T0."SuppSerial",
            TO_CHAR(T0."InDate", 'yyyy-mm-dd') AS "InDate",
            T0."Status"
        FROM "{company_db}"."OIBT" T0
        WHERE T0."ItemCode" = ?
          AND T0."WhsCode" = ?
          AND T0."Quantity" > 0
          AND T0."Status" = 0
        ORDER BY T0."InDate" ASC
    '''
    rows = _rows(sql, [item_code, whs_code])
    return {
        "ok": True,
        "company_db": company_db,
        "item_code": item_code,
        "whs_code": whs_code,
        "resultados": rows,
    }


__all__ = [
    "SALIDA_DOCUMENTO_DESPACHO_OPCIONES",
    "SAP_DESPACHO_CAMPOS",
    "SapDiApiError",
    "actualizar_borrador_sap_despacho",
    "consultar_acuerdos_despacho",
    "consultar_estanques_oibt_despacho",
    "consultar_lotes_oibt_despacho",
    "construir_payload_draft_despacho",
    "construir_payload_update_draft_despacho",
    "crear_borrador_sap_despacho",
    "decimal_o_primero",
    "detalle_despacho_resumen_dict",
    "get_sap_despacho_draft_status",
    "get_sap_despacho_update_status",
    "guardar_detalle_despacho_citacion",
    "guardar_respuesta_borrador_sap_despacho",
    "guardar_respuesta_update_sap_despacho",
    "normalizar_salida_documento_despacho",
    "obtener_docentry_draft_sap_despacho",
    "obtener_peso_salida_sap_despacho",
    "parsear_json_despacho_legacy",
    "texto_o_primero",
]
