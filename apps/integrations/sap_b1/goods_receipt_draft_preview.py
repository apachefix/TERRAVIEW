from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone
from requests import HTTPError

from apps.home.models import (
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    DATO_OPERACION,
    OPERACION_PLANTA_LOG,
)
from apps.integrations.sap_b1.service_layer_probe import (
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    load_config,
)


PASO_PESAJE_SALIDA = "Pesaje Salida"
PASO_BORRADOR_SAP = "Borrador SAP"
LOG_BORRADOR_SAP_ENVIADO = "BORRADOR_SAP_ENVIADO"
LOG_BORRADOR_SAP_GUIA_ENVIO = "BORRADOR_SAP_GUIA_ENVIO"
CAMPO_TICKET_PESAJE_SAL = "OP_TICKET_PESAJE_SAL"
CAMPO_PESO_INFORMADO_GUIA = "SAP_PESO_INFORMADO_GUIA"
ORIGEN_CANTIDAD_PESAJE_SALIDA = "pesaje_salida"
ORIGEN_CANTIDAD_PESO_GUIA = "peso_guia"
DEFAULT_DRAFT_SERIES = 17
DEFAULT_DRAFT_OBJECT_CODE = "oPurchaseDeliveryNotes"
DEFAULT_QA_NUM_AT_CARD = "1111"


class GoodsReceiptDraftError(Exception):
    pass


def _clean_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"\d+", text.replace(".", ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_decimal(value: Any) -> Optional[Decimal]:
    if value in [None, ""]:
        return None
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _latest_detail(citacion: CITACION) -> Optional[CITACION_DETALLE_OPERACIONAL]:
    return CITACION_DETALLE_OPERACIONAL.objects.filter(CI_NID=citacion).order_by("-id").first()


def _dato_operacion(citacion: CITACION, codigo: str) -> Optional[DATO_OPERACION]:
    return (
        DATO_OPERACION.objects.filter(CI_NID=citacion, CAMP_NID__CA_CCODIGO=codigo)
        .select_related("CAMP_NID")
        .order_by("-id")
        .first()
    )


def _dato_valor(citacion: CITACION, codigo: str) -> str:
    dato = _dato_operacion(citacion, codigo)
    return _clean_text(dato.DO_CVALOR if dato else "")


def _ticket_salida_metadata(citacion: CITACION) -> Tuple[Optional[Dict[str, Any]], Optional[DATO_OPERACION]]:
    dato = _dato_operacion(citacion, CAMPO_TICKET_PESAJE_SAL)
    if not dato:
        return None, None
    try:
        metadata = json.loads(dato.DO_CVALOR or "{}")
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    if dato.DO_NPESO and not metadata.get("peso_neto"):
        metadata["peso_neto"] = dato.DO_NPESO
    return metadata, dato


def get_exit_weight_from_citation(citacion: CITACION) -> Optional[Decimal]:
    metadata, dato = _ticket_salida_metadata(citacion)
    if metadata:
        peso = _as_decimal(metadata.get("peso_neto"))
        if peso and peso > 0:
            return peso
    if dato:
        peso = _as_decimal(dato.DO_NPESO)
        if peso and peso > 0:
            return peso
    return None


def get_num_at_card_from_citation(citacion: CITACION) -> Tuple[str, Optional[str]]:
    candidates = [
        _dato_valor(citacion, "CI_CNUMERODOCUMENTO"),
        _dato_valor(citacion, "ING_NUMERO_GUIA"),
        _dato_valor(citacion, "ING_GUIA"),
        _clean_text(getattr(citacion, "CI_CNUMERODOCUMENTO", "")),
    ]
    for candidate in candidates:
        if candidate:
            return candidate, None
    return DEFAULT_QA_NUM_AT_CARD, "NumAtCard no encontrado en BD, usando valor QA temporal 1111"


def get_batch_number_from_citation(citacion: CITACION) -> Optional[str]:
    for codigo in ("AR_LOTE_CONTENEDOR", "ING_LOTE_CONTENEDOR"):
        value = _dato_valor(citacion, codigo)
        if value:
            return value
    return None


def _resolve_doc_entry(citacion: CITACION, detalle: Optional[CITACION_DETALLE_OPERACIONAL]) -> Optional[int]:
    if detalle:
        for value in (detalle.CDO_CDOCENTRY, detalle.CDO_CSAP_OPOR_ID):
            candidate = _clean_int(value)
            if candidate:
                return candidate
    for codigo in ("CDO_CDOCENTRY", "CDO_CSAP_OPOR_ID", "SAP_OPOR_ID", "DOCENTRY"):
        candidate = _clean_int(_dato_valor(citacion, codigo))
        if candidate:
            return candidate
    return None


def _line_container(line: Dict[str, Any]) -> str:
    return _clean_text(line.get("U_NXContenedor"))


def _line_item_code(line: Dict[str, Any]) -> str:
    return _clean_text(line.get("ItemCode"))


def _line_open_quantity(line: Dict[str, Any]) -> Optional[Decimal]:
    return _as_decimal(line.get("RemainingOpenQuantity") or line.get("OpenQuantity") or line.get("OpenQty"))


def _line_num(line: Dict[str, Any]) -> Optional[int]:
    return _clean_int(line.get("LineNum"))


def find_matching_purchase_order_line(
    purchase_order: Dict[str, Any],
    citation_data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    lines = purchase_order.get("DocumentLines") or []
    if not isinstance(lines, list):
        return None, "PurchaseOrder sin DocumentLines validas"

    containers = [
        citation_data.get("detalle_bl"),
        citation_data.get("ar_bl_validado"),
        citation_data.get("ing_bl"),
    ]
    containers = [_clean_text(value).upper() for value in containers if _clean_text(value)]

    for container in containers:
        for index, line in enumerate(lines):
            if _line_container(line).upper() == container:
                line["_ResolvedBaseLine"] = _line_num(line) if _line_num(line) is not None else index
                return line, f"Linea SAP encontrada por contenedor {container}"

    item_code = _clean_text(citation_data.get("item_code"))
    if item_code:
        candidates = []
        for index, line in enumerate(lines):
            if _line_item_code(line) == item_code:
                line["_ResolvedBaseLine"] = _line_num(line) if _line_num(line) is not None else index
                candidates.append(line)
        target_quantity = _as_decimal(citation_data.get("cantidad_disponible"))
        if candidates and target_quantity is not None:
            candidates.sort(
                key=lambda line: abs((_line_open_quantity(line) or Decimal("0")) - target_quantity)
            )
        if candidates:
            return candidates[0], f"Linea SAP encontrada por ItemCode {item_code} y cantidad cercana"

    return None, "No se encontro linea SAP por contenedor ni ItemCode"


def _draft_series() -> int:
    return int(getattr(settings, "SAP_GOODS_RECEIPT_DRAFT_SERIES", DEFAULT_DRAFT_SERIES))


def _draft_object_code() -> str:
    return str(getattr(settings, "SAP_GOODS_RECEIPT_DRAFT_OBJECT_CODE", DEFAULT_DRAFT_OBJECT_CODE))


def _extract_sap_error(exc: Exception) -> Dict[str, Any]:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    data: Any = None
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


def _existing_draft_log(citacion: CITACION) -> Optional[OPERACION_PLANTA_LOG]:
    return (
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO=LOG_BORRADOR_SAP_ENVIADO,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )
        .select_related("US_NID")
        .order_by("-OPL_FFECHAREGISTRO")
        .first()
    )


def _parse_log_json(log: Optional[OPERACION_PLANTA_LOG]) -> Dict[str, Any]:
    if not log:
        return {}
    try:
        data = json.loads(log.OPL_COBSERVACION or "{}")
    except (TypeError, ValueError):
        return {"raw": log.OPL_COBSERVACION or ""}
    return data if isinstance(data, dict) else {"raw": log.OPL_COBSERVACION or ""}


def get_goods_receipt_draft_status(citacion: CITACION) -> Dict[str, Any]:
    log = _existing_draft_log(citacion)
    if not log:
        return {
            "sent": False,
            "label": "Pendiente de generar",
        }
    data = _parse_log_json(log)
    response = data.get("response") if isinstance(data.get("response"), dict) else {}
    return {
        "sent": True,
        "label": "Borrador SAP creado",
        "usuario": log.US_NID.username if log.US_NID else "",
        "fecha_hora": timezone.localtime(log.OPL_FFECHAREGISTRO).strftime("%d/%m/%Y %H:%M"),
        "status_code": data.get("status_code"),
        "docentry": response.get("DocEntry") or response.get("DocEntry".lower()),
        "docnum": response.get("DocNum") or response.get("DocNum".lower()),
        "response": response,
    }


def get_goods_receipt_draft_guide_status(citacion: CITACION) -> Dict[str, Any]:
    log = (
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO=LOG_BORRADOR_SAP_GUIA_ENVIO,
        )
        .select_related("US_NID")
        .order_by("-OPL_FFECHAREGISTRO", "-id")
        .first()
    )
    if not log:
        return {
            "sent": False,
            "local_status": "Pendiente de generar",
            "sap_status": "No enviado",
        }

    data = _parse_log_json(log)
    response = data.get("response") if isinstance(data.get("response"), dict) else {}
    success = bool(data.get("success")) and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
    return {
        "sent": success,
        "local_status": "Borrador enviado" if success else "Borrador generado para revision",
        "sap_status": "Creado en SAP QA" if success else "Error al crear en SAP QA",
        "status_code": data.get("status_code"),
        "docentry": response.get("DocEntry") or response.get("docentry"),
        "docnum": response.get("DocNum") or response.get("docnum"),
        "response": response,
        "sap_error": data.get("sap_error"),
        "company_db": data.get("company_db"),
        "sap_username": data.get("sap_username"),
        "usuario": log.US_NID.username if log.US_NID else "",
        "fecha_hora": timezone.localtime(log.OPL_FFECHAREGISTRO).strftime("%d/%m/%Y %H:%M"),
    }


def build_goods_receipt_draft_preview(
    citacion: CITACION,
    *,
    origen_cantidad: str = ORIGEN_CANTIDAD_PESAJE_SALIDA,
    cantidad_informada: Any = None,
) -> Dict[str, Any]:
    validations: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    client: Optional[SapServiceLayerClient] = None

    detalle = _latest_detail(citacion)
    doc_entry = _resolve_doc_entry(citacion, detalle)
    if origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA:
        quantity = _as_decimal(
            cantidad_informada
            if cantidad_informada not in [None, ""]
            else _dato_valor(citacion, CAMPO_PESO_INFORMADO_GUIA)
        )
    else:
        origen_cantidad = ORIGEN_CANTIDAD_PESAJE_SALIDA
        quantity = get_exit_weight_from_citation(citacion)
    batch_number = get_batch_number_from_citation(citacion)
    num_at_card, num_warning = get_num_at_card_from_citation(citacion)
    if num_warning:
        warnings.append(num_warning)

    source_data = {
        "citacion": citacion.id,
        "empresa": citacion.EP_NID_id,
        "doc_entry": doc_entry,
        "pedido_sap": _clean_text(detalle.CDO_CPEDIDO_SAP if detalle else ""),
        "item_code": _clean_text(detalle.CDO_CCODIGO_SAP if detalle else ""),
        "insumo": _clean_text(detalle.CDO_CINSUMO if detalle else ""),
        "card_code": _clean_text(detalle.CDO_CPROVEEDOR_CODIGO if detalle else ""),
        "card_name": _clean_text(detalle.CDO_CPRODUCTOR if detalle else ""),
        "detalle_bl": _clean_text(detalle.CDO_CBL_CONTENEDOR if detalle else ""),
        "cantidad_disponible": _json_safe(detalle.CDO_NCANTIDAD_DISPONIBLE if detalle else None),
        "ar_bl_validado": _dato_valor(citacion, "AR_BL_VALIDADO"),
        "ing_bl": _dato_valor(citacion, "ING_BL"),
        "batch_number": batch_number,
        "origen_cantidad": origen_cantidad,
        "quantity": _json_safe(quantity),
        "exit_weight": _json_safe(quantity) if origen_cantidad == ORIGEN_CANTIDAD_PESAJE_SALIDA else None,
        "peso_informado_guia": _json_safe(quantity) if origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA else None,
        "num_at_card": num_at_card,
        "series": _draft_series(),
        "doc_object_code": _draft_object_code(),
    }

    if doc_entry:
        validations.append(f"DocEntry encontrado: {doc_entry}")
    else:
        errors.append("DocEntry SAP no encontrado en CITACION_DETALLE_OPERACIONAL.")

    if quantity and origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA:
        validations.append(f"Peso informado en guia encontrado: {_json_safe(quantity)}")
    elif quantity:
        validations.append(f"Peso salida encontrado: {_json_safe(quantity)}")
    elif origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA:
        errors.append("Peso informado en guia no encontrado o no valido.")
    else:
        errors.append("Peso ticket de Pesaje Salida no encontrado.")

    if batch_number:
        validations.append(f"Lote encontrado: {batch_number}")
    else:
        errors.append("Lote no encontrado en AR_LOTE_CONTENEDOR ni ING_LOTE_CONTENEDOR.")

    if num_warning:
        validations.append(f"NumAtCard fallback aplicado: {num_at_card}")
    else:
        validations.append(f"Guia/NumAtCard encontrada: {num_at_card}")

    purchase_order: Dict[str, Any] = {}
    selected_line: Optional[Dict[str, Any]] = None
    if doc_entry:
        try:
            config = load_config()
            source_data["company_db"] = config.company_db
            source_data["sap_username"] = config.username
            client = SapServiceLayerClient(config)
            client.login()
            purchase_order = client.get_json(f"PurchaseOrders({doc_entry})", f"PurchaseOrders({doc_entry})")
            validations.append("PurchaseOrder encontrada en SAP.")
            selected_line, match_reason = find_matching_purchase_order_line(purchase_order, source_data)
            if selected_line:
                validations.append(match_reason)
            else:
                errors.append(match_reason)
        except HTTPError as exc:
            errors.append(f"Error HTTP Service Layer al consultar PurchaseOrder: {exc}")
            source_data["sap_error"] = _extract_sap_error(exc)
        except SapServiceLayerProbeError as exc:
            errors.append(f"Error Service Layer: {exc}")
        finally:
            if client:
                client.logout()

    payload: Dict[str, Any] = {}
    line_summary: Dict[str, Any] = {}
    if selected_line:
        base_line = _line_num(selected_line)
        if base_line is None:
            base_line = _clean_int(selected_line.get("_ResolvedBaseLine"))
        remaining = _line_open_quantity(selected_line)
        line_status = _clean_text(selected_line.get("LineStatus"))
        line_item_code = _line_item_code(selected_line) or source_data["item_code"]
        warehouse_code = _clean_text(selected_line.get("WarehouseCode")) or "Z_DESCAR"
        card_code = _clean_text(purchase_order.get("CardCode")) or source_data["card_code"]
        today = timezone.localdate().isoformat()

        line_summary = {
            "LineNum": base_line,
            "ItemCode": line_item_code,
            "ItemDescription": selected_line.get("ItemDescription") or selected_line.get("Dscription") or "",
            "Quantity": selected_line.get("Quantity"),
            "RemainingOpenQuantity": _json_safe(remaining),
            "WarehouseCode": warehouse_code,
            "LineStatus": line_status,
            "U_NXContenedor": selected_line.get("U_NXContenedor") or "",
        }

        if base_line is not None:
            validations.append(f"BaseLine resuelto: {base_line}")
        else:
            errors.append("No se pudo resolver BaseLine desde LineNum.")

        if line_status == "bost_Open" or not line_status:
            validations.append("Linea SAP esta abierta.")
        else:
            errors.append(f"Linea SAP no esta abierta: {line_status}")

        if quantity and remaining and quantity != remaining:
            quantity_label = (
                "peso informado en guia"
                if origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA
                else "peso ticket salida"
            )
            warnings.append(
                f"Quantity del borrador usa {quantity_label} {_json_safe(quantity)}; "
                f"la linea SAP tiene RemainingOpenQuantity {_json_safe(remaining)}. "
                "Confirmar unidad con SAP antes de enviar."
            )
        quantity_exceeds_remaining = bool(quantity and remaining and quantity > remaining)
        if quantity_exceeds_remaining:
            warnings.append(
                "La cantidad informada supera la cantidad abierta en SAP. Revisar unidad de medida."
            )
        source_data["remaining_open_quantity"] = _json_safe(remaining)
        source_data["quantity_exceeds_remaining"] = quantity_exceeds_remaining

        if not card_code:
            errors.append("CardCode no encontrado en PurchaseOrder ni detalle local.")
        if not line_item_code:
            errors.append("ItemCode no encontrado en linea SAP ni detalle local.")
        if not warehouse_code:
            errors.append("WarehouseCode no encontrado.")

        if not errors and quantity and batch_number and base_line is not None:
            payload = {
                "DocObjectCode": _draft_object_code(),
                "DocType": "dDocument_Items",
                "DocDate": today,
                "DocDueDate": today,
                "TaxDate": today,
                "CardCode": card_code,
                "NumAtCard": num_at_card,
                "Series": _draft_series(),
                "DocumentLines": [
                    {
                        "ItemCode": line_item_code,
                        "Quantity": _json_safe(quantity),
                        "BaseType": 22,
                        "BaseEntry": doc_entry,
                        "BaseLine": base_line,
                        "WarehouseCode": warehouse_code,
                        "BatchNumbers": [
                            {
                                "BatchNumber": batch_number,
                                "Quantity": _json_safe(quantity),
                                "BaseLineNumber": 0,
                                "ItemCode": line_item_code,
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
        "selected_line": line_summary,
        "status": get_goods_receipt_draft_status(citacion),
    }


def build_goods_receipt_draft_preview_from_peso_guia(
    citacion: CITACION,
    peso_guia: Any = None,
) -> Dict[str, Any]:
    return build_goods_receipt_draft_preview(
        citacion,
        origen_cantidad=ORIGEN_CANTIDAD_PESO_GUIA,
        cantidad_informada=peso_guia,
    )


def _save_guide_send_log(
    citacion: CITACION,
    user: Any,
    *,
    success: bool,
    company_db: str,
    sap_username: str,
    payload: Dict[str, Any],
    response: Optional[Dict[str, Any]] = None,
    status_code: Optional[int] = None,
    sap_error: Optional[Dict[str, Any]] = None,
) -> OPERACION_PLANTA_LOG:
    log_data = {
        "accion": LOG_BORRADOR_SAP_GUIA_ENVIO,
        "success": success,
        "company_db": company_db,
        "sap_username": sap_username,
        "citacion": citacion.id,
        "status_code": status_code,
        "payload": payload,
        "response": response or {},
        "sap_error": sap_error or {},
        "usuario": getattr(user, "username", ""),
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
    }
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=user,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO=LOG_BORRADOR_SAP_GUIA_ENVIO,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE C D",
        OPL_CESTADO=(
            OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
            if success
            else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
        ),
        OPL_COBSERVACION=json.dumps(log_data, ensure_ascii=False),
    )


def send_goods_receipt_draft_from_peso_guia_to_sap(
    citacion: CITACION,
    user: Any,
    *,
    confirm_quantity_exceeds: bool = False,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    existing_status = get_goods_receipt_draft_guide_status(citacion)
    if existing_status.get("sent") and not (allow_duplicate and getattr(user, "is_superuser", False)):
        docentry = existing_status.get("docentry") or "sin DocEntry informado"
        return {
            "success": False,
            "message": (
                "Ya existe un borrador SAP creado para esta citacion: "
                f"DocEntry {docentry}. El reenvio esta bloqueado por defecto."
            ),
            "status": existing_status,
        }

    preview = build_goods_receipt_draft_preview_from_peso_guia(citacion)
    if preview.get("errors") or not preview.get("payload"):
        return {
            "success": False,
            "message": "El borrador no es valido. No se envio a SAP.",
            "preview": preview,
            "status": existing_status,
        }

    source_data = preview.get("source_data") or {}
    if source_data.get("quantity_exceeds_remaining") and not confirm_quantity_exceeds:
        return {
            "success": False,
            "confirmation_required": True,
            "message": "La cantidad informada supera la cantidad abierta en SAP. Revisar unidad de medida.",
            "preview": preview,
            "status": existing_status,
        }

    config = load_config()
    expected_company_db = str(settings.SAP_DRAFT_QA_COMPANY_DB or "").strip()
    if config.company_db != expected_company_db:
        return {
            "success": False,
            "message": (
                f"Envio bloqueado: CompanyDB configurada {config.company_db} "
                f"no coincide con SAP QA esperado {expected_company_db}."
            ),
            "preview": preview,
            "status": existing_status,
        }

    client = SapServiceLayerClient(config)
    print(
        f"\n[Borrador SAP][Peso guia][Enviar QA] citacion={citacion.id} "
        f"empresa={citacion.EP_NID_id} origen_cantidad=peso_guia "
        f"CompanyDB={config.company_db} endpoint=/Drafts"
    )
    print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))

    try:
        client.login()
        sap_response = client.post_draft(preview["payload"])
        status_code = sap_response.get("status_code")
        response_payload = sap_response.get("data") or {}
        print("[Borrador SAP][Peso guia][Enviar QA] Respuesta SAP:")
        print(json.dumps(response_payload, indent=2, ensure_ascii=False))
    except HTTPError as exc:
        error_data = _extract_sap_error(exc)
        print("[Borrador SAP][Peso guia][Enviar QA] Error SAP:")
        print(json.dumps(error_data, indent=2, ensure_ascii=False))
        _save_guide_send_log(
            citacion,
            user,
            success=False,
            company_db=config.company_db,
            sap_username=config.username,
            payload=preview["payload"],
            status_code=error_data.get("status_code"),
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": "SAP rechazo la creacion del borrador.",
            "status_code": error_data.get("status_code"),
            "sap_error": error_data,
            "preview": preview,
            "status": get_goods_receipt_draft_guide_status(citacion),
        }
    except SapServiceLayerProbeError as exc:
        error_data = {"error": str(exc)}
        print(json.dumps(error_data, indent=2, ensure_ascii=False))
        _save_guide_send_log(
            citacion,
            user,
            success=False,
            company_db=config.company_db,
            sap_username=config.username,
            payload=preview["payload"],
            sap_error=error_data,
        )
        return {
            "success": False,
            "message": str(exc),
            "sap_error": error_data,
            "preview": preview,
            "status": get_goods_receipt_draft_guide_status(citacion),
        }
    finally:
        client.logout()

    _save_guide_send_log(
        citacion,
        user,
        success=True,
        company_db=config.company_db,
        sap_username=config.username,
        payload=preview["payload"],
        response=response_payload,
        status_code=status_code,
    )
    return {
        "success": True,
        "message": "Borrador creado en SAP QA.",
        "status_code": status_code,
        "response": response_payload,
        "preview": preview,
        "company_db": config.company_db,
        "sap_username": config.username,
        "status": get_goods_receipt_draft_guide_status(citacion),
    }


def send_goods_receipt_draft_to_sap(citacion: CITACION, user: Any, allow_duplicate: bool = False) -> Dict[str, Any]:
    existing = _existing_draft_log(citacion)
    if existing and not (allow_duplicate and getattr(user, "is_superuser", False)):
        return {
            "success": False,
            "message": "Ya existe un borrador SAP enviado para esta citacion.",
            "existing": get_goods_receipt_draft_status(citacion),
        }

    preview = build_goods_receipt_draft_preview(citacion)
    if preview.get("errors") or not preview.get("payload"):
        return {
            "success": False,
            "message": "Preview invalido. No se envio a SAP.",
            "preview": preview,
        }

    config = load_config()
    client = SapServiceLayerClient(config)
    response_payload: Dict[str, Any] = {}
    status_code: Optional[int] = None
    try:
        print(
            f"\n[Borrador SAP][Enviar][Citacion {citacion.id}] "
            f"Destino Service Layer: CompanyDB={config.company_db}, endpoint=Drafts"
        )
        print("[Borrador SAP][Enviar] JSON SAP reconstruido que se enviara:")
        print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))
        client.login()
        response = client.post_draft(preview["payload"])
        status_code = response.get("status_code")
        response_payload = response.get("data") or {}
    except HTTPError as exc:
        error_data = _extract_sap_error(exc)
        return {
            "success": False,
            "message": "SAP rechazo la creacion del borrador.",
            "status_code": error_data.get("status_code"),
            "sap_error": error_data,
            "preview": preview,
        }
    except SapServiceLayerProbeError as exc:
        return {
            "success": False,
            "message": str(exc),
            "preview": preview,
        }
    finally:
        client.logout()

    log_data = {
        "accion": LOG_BORRADOR_SAP_ENVIADO,
        "company_db": config.company_db,
        "sap_username": config.username,
        "citacion": citacion.id,
        "status_code": status_code,
        "payload": preview["payload"],
        "response": response_payload,
        "usuario": getattr(user, "username", ""),
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
    }
    OPERACION_PLANTA_LOG.objects.create(
        US_NID=user,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO=LOG_BORRADOR_SAP_ENVIADO,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE DE RECEPCION",
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        OPL_COBSERVACION=json.dumps(log_data, ensure_ascii=False),
    )
    OPERACION_PLANTA_LOG.objects.get_or_create(
        US_NID=user,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO=PASO_BORRADOR_SAP,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE DE RECEPCION",
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        defaults={
            "OPL_COBSERVACION": (
                f"Borrador SAP enviado. Draft DocEntry: {response_payload.get('DocEntry', '')} "
                f"DocNum: {response_payload.get('DocNum', '')}"
            )
        },
    )

    return {
        "success": True,
        "message": "Borrador SAP creado.",
        "status_code": status_code,
        "response": response_payload,
        "preview": preview,
        "company_db": config.company_db,
        "sap_username": config.username,
        "fecha_hora": log_data["fecha_hora"],
        "usuario": getattr(user, "username", ""),
    }
