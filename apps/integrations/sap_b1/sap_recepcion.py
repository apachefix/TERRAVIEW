from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests import HTTPError

from apps.home.models import (
    CAMPO,
    CITACION,
    CITACION_DETALLE_OPERACIONAL,
    DATO_OPERACION,
    OPERACION_PLANTA_LOG,
)
from apps.home.sap_di_api import HANA_IDENTIFIER_RE, SapDiApiError, _first_row, _load_config as load_hana_config
from apps.integrations.sap_b1.sap_config import SAP_ENV_QA, normalize_sap_environment
from apps.integrations.sap_b1.service_layer_probe import (
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    load_config,
)


PASO_PESAJE_SALIDA = "Pesaje Salida"
PASO_BORRADOR_SAP = "Borrador SAP"
LOG_BORRADOR_SAP_ENVIADO = "BORRADOR_SAP_ENVIADO"
LOG_BORRADOR_SAP_RECEPCION_ENVIO = "BORRADOR_SAP_RECEPCION_ENVIO"
LOG_BORRADOR_SAP_GUIA_ENVIO = LOG_BORRADOR_SAP_RECEPCION_ENVIO
LOG_BORRADOR_SAP_GUIA_ENVIO_LEGACY = "BORRADOR_SAP_GUIA_ENVIO"
LOG_UPDATE_SAP_RECEPCION_ENVIO = "UPDATE_SAP_RECEPCION_ENVIO"
LOG_UPDATE_SAP_RECEPCION_ERROR = "UPDATE_SAP_RECEPCION_ERROR"
CAMPO_LOTE_RECEPCION_SAP = "SAP_RECEPCION_LOTE_GENERADO"
CAMPO_TICKET_PESAJE_SAL = "OP_TICKET_PESAJE_SAL"
CAMPO_PESO_INFORMADO_GUIA = "SAP_PESO_INFORMADO_GUIA"
ORIGEN_CANTIDAD_PESAJE_SALIDA = "pesaje_salida"
ORIGEN_CANTIDAD_PESO_GUIA = "peso_guia"
ORIGEN_CANTIDAD_DISPONIBLE = "cantidad_disponible"
DEFAULT_DRAFT_SERIES = 17
KILOGRAMOS_POR_TONELADA_METRICA = Decimal('1000')
UNIDAD_SAP_TONELADA_METRICA = 'MT'
MODO_LOTE_MANUAL_SAP = 'MANUAL_SAP'
MODO_LOTE_AUTOMATICO_TERRAVIEW = 'AUTOMATICO_TERRAVIEW'
DEFAULT_DRAFT_OBJECT_CODE = "oPurchaseDeliveryNotes"


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


def _enviar_lote_en_update_draft_recepcion() -> bool:
    return bool(getattr(settings, 'SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT', False))


def convertir_peso_salida_kg_a_cantidad_sap_mt(peso_salida_kg: Any) -> Optional[Decimal]:
    peso = _as_decimal(peso_salida_kg)
    if peso is None:
        return None
    return peso / KILOGRAMOS_POR_TONELADA_METRICA


def _latest_detail(citacion: CITACION) -> Optional[CITACION_DETALLE_OPERACIONAL]:
    return CITACION_DETALLE_OPERACIONAL.objects.filter(CI_NID=citacion).order_by("-id").first()


def get_plant_destination_from_citation(
    citacion: CITACION,
    detalle: Optional[CITACION_DETALLE_OPERACIONAL] = None,
) -> str:
    """Obtiene el estanque destino local usado por U_HCO_Plantadestino."""
    detalle = detalle if detalle is not None else _latest_detail(citacion)
    return _clean_text(detalle.CDO_CESTANQUE_DESTINO if detalle else "")

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


def get_folio_from_citation(citacion: CITACION) -> Tuple[str, Optional[int], List[str]]:
    """Valida los campos locales que SAP recibe como folio de documento."""
    errors: List[str] = []
    folio_prefix = _clean_text(getattr(citacion, "CI_CTIPODOCUMENTO", "")).upper()
    numero_documento = _clean_text(getattr(citacion, "CI_CNUMERODOCUMENTO", ""))
    if not folio_prefix:
        errors.append("La citación no tiene tipo de documento para FolioPrefixString.")
    elif folio_prefix not in {"GD", "FE"}:
        errors.append("El tipo de documento de la citación no es válido para FolioPrefixString.")
    if not numero_documento:
        errors.append("La citación no tiene número de documento para FolioNumber.")
    elif not numero_documento.isdigit():
        errors.append("El número de documento de la citación no es válido para FolioNumber.")
    return folio_prefix, (int(numero_documento) if numero_documento.isdigit() else None), errors


def _log_recepcion_folio(citacion: CITACION, folio_prefix: str, folio_number: Optional[int], estanque: str) -> None:
    print(
        f"[SAP Recepción] citacion={citacion.id} FolioPrefixString={folio_prefix or '-'} "
        f"FolioNumber={folio_number if folio_number is not None else '-'} estanque={estanque or '-'}"
    )

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
    return "", "NumAtCard no encontrado; se enviara null."


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
            OPL_CPASO__in=[LOG_BORRADOR_SAP_ENVIADO],
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
            OPL_CPASO__in=[LOG_BORRADOR_SAP_GUIA_ENVIO, LOG_BORRADOR_SAP_GUIA_ENVIO_LEGACY],
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
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    line = (payload.get("DocumentLines") or [{}])[0] if isinstance(payload.get("DocumentLines"), list) else {}
    batch = (line.get("BatchNumbers") or [{}])[0] if isinstance(line.get("BatchNumbers"), list) else {}
    success = bool(data.get("success")) and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
    return {
        "sent": success,
        "local_status": "Borrador enviado" if success else "Borrador generado para revision",
        "sap_status": "Creado en SAP QA" if success else "Error al crear en SAP QA",
        "status_code": data.get("status_code"),
        "endpoint": data.get("endpoint") or "/Drafts",
        "docentry": response.get("DocEntry") or response.get("docentry"),
        "docnum": response.get("DocNum") or response.get("docnum"),
        "response": response,
        "response_json": response or data.get("sap_error") or {},
        "request_json": payload,
        "sap_error": data.get("sap_error"),
        "sap_error_message": data.get("sap_error_message") or "",
        "company_db": data.get("company_db"),
        "sap_username": data.get("sap_username"),
        "usuario": log.US_NID.username if log.US_NID else "",
        "fecha_hora": timezone.localtime(log.OPL_FFECHAREGISTRO).strftime("%d/%m/%Y %H:%M"),
        "card_code": payload.get("CardCode") or "",
        "item_code": line.get("ItemCode") or "",
        "quantity": line.get("Quantity") or "",
        "batch_number": batch.get("BatchNumber") or "",
        "base_entry": line.get("BaseEntry") or "",
        "base_line": line.get("BaseLine") if line.get("BaseLine") is not None else "",
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
    folio_prefix, folio_number, folio_errors = get_folio_from_citation(citacion)
    estanque_destino = get_plant_destination_from_citation(citacion, detalle)

    _log_recepcion_folio(
        citacion,
        folio_prefix,
        folio_number,
        estanque_destino,
    )

    source_data = {
        "citacion": citacion.id,
        "empresa": citacion.EP_NID_id,
        "doc_entry": doc_entry,
        "pedido_sap": _clean_text(
            detalle.CDO_CPEDIDO_SAP if detalle else ""
        ),
        "item_code": _clean_text(
            detalle.CDO_CCODIGO_SAP if detalle else ""
        ),
        "insumo": _clean_text(
            detalle.CDO_CINSUMO if detalle else ""
        ),
        "card_code": _clean_text(
            detalle.CDO_CPROVEEDOR_CODIGO if detalle else ""
        ),
        "card_name": _clean_text(
            detalle.CDO_CPRODUCTOR if detalle else ""
        ),
        "detalle_bl": _clean_text(
            detalle.CDO_CBL_CONTENEDOR if detalle else ""
        ),
        "ar_bl_validado": _dato_valor(
            citacion,
            "AR_BL_VALIDADO",
        ),
        "ing_bl": _dato_valor(
            citacion,
            "ING_BL",
        ),
        "batch_number": batch_number,
        "estanque_destino": estanque_destino,
        "warehouse_code": estanque_destino,
        "origen_cantidad": origen_cantidad,
        "quantity": _json_safe(quantity),
        "exit_weight": (
            _json_safe(quantity)
            if origen_cantidad == ORIGEN_CANTIDAD_PESAJE_SALIDA
            else None
        ),
        "peso_informado_guia": (
            _json_safe(quantity)
            if origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA
            else None
        ),
        "cantidad_disponible": (
            _json_safe(quantity)
            if origen_cantidad == ORIGEN_CANTIDAD_DISPONIBLE
            else _json_safe(
                detalle.CDO_NCANTIDAD_DISPONIBLE
                if detalle
                else None
            )
        ),
        "folio_prefix": folio_prefix,
        "folio_number": folio_number,
        "series": _draft_series(),
        "doc_object_code": 20,
    }

    if folio_errors:
        errors.extend(folio_errors)
    else:
        validations.append(
            f"FolioPrefixString: {folio_prefix}"
        )
        validations.append(
            f"FolioNumber: {folio_number}"
        )

    if doc_entry:
        validations.append(
            f"DocEntry encontrado: {doc_entry}"
        )
    else:
        errors.append(
            "No se puede crear Borrador SAP: "
            "falta DocEntry del pedido SAP."
        )

    if source_data["card_code"]:
        validations.append(
            "CardCode proveedor encontrado: "
            f"{source_data['card_code']}"
        )
    else:
        errors.append(
            "No se puede crear Borrador SAP: "
            "falta codigo proveedor SAP."
        )

    if source_data["item_code"]:
        validations.append(
            "Codigo producto SAP encontrado: "
            f"{source_data['item_code']}"
        )
    else:
        errors.append(
            "No se puede crear Borrador SAP: "
            "falta codigo producto SAP."
        )

    if quantity and origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA:
        validations.append(
            "Peso informado en guia encontrado: "
            f"{_json_safe(quantity)}"
        )
    elif quantity and origen_cantidad == ORIGEN_CANTIDAD_DISPONIBLE:
        validations.append(
            "Cantidad disponible encontrada: "
            f"{_json_safe(quantity)}"
        )
    elif quantity:
        validations.append(
            "Peso salida encontrado: "
            f"{_json_safe(quantity)}"
        )
    elif origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA:
        errors.append(
            "No se puede crear Borrador SAP: "
            "falta peso informado."
        )
    else:
        errors.append(
            "No se puede crear Borrador SAP: "
            "falta cantidad/peso informado."
        )

    if batch_number:
        validations.append(
            f"Lote encontrado: {batch_number}"
        )
    else:
        warnings.append(
            "Lote no informado en esta etapa; "
            "se agregara posteriormente."
        )

    if estanque_destino:
        validations.append(
            f"WarehouseCode encontrado: {estanque_destino}"
        )
    else:
        errors.append(
            "La citación no tiene bodega/almacén destino "
            "asignado para WarehouseCode."
        )

    purchase_order: Dict[str, Any] = {}
    selected_line: Optional[Dict[str, Any]] = None

    if doc_entry:
        try:
            config = load_config(citacion.EP_NID_id)

            source_data["company_db"] = config.company_db
            source_data["sap_username"] = config.username

            client = SapServiceLayerClient(config)
            client.login()

            purchase_order = client.get_json(
                f"PurchaseOrders({doc_entry})",
                f"PurchaseOrders({doc_entry})",
            )

            validations.append(
                "PurchaseOrder encontrada en SAP."
            )

            selected_line, match_reason = (
                find_matching_purchase_order_line(
                    purchase_order,
                    source_data,
                )
            )

            if selected_line:
                validations.append(match_reason)
            else:
                errors.append(match_reason)

        except HTTPError as exc:
            errors.append(
                "Error HTTP Service Layer al consultar "
                f"PurchaseOrder: {exc}"
            )
            source_data["sap_error"] = _extract_sap_error(exc)

        except SapServiceLayerProbeError as exc:
            errors.append(
                f"Error Service Layer: {exc}"
            )

        finally:
            if client:
                client.logout()

    payload: Dict[str, Any] = {}
    line_summary: Dict[str, Any] = {}

    if selected_line:
        base_line = _line_num(selected_line)

        if base_line is None:
            base_line = _clean_int(
                selected_line.get("_ResolvedBaseLine")
            )

        remaining = _line_open_quantity(selected_line)
        line_status = _clean_text(
            selected_line.get("LineStatus")
        )
        line_item_code = (
            _line_item_code(selected_line)
            or source_data["item_code"]
        )
        card_code = (
            _clean_text(purchase_order.get("CardCode"))
            or source_data["card_code"]
        )
        fecha_accion = timezone.localdate().isoformat()
        line_total = selected_line.get("LineTotal")

        line_summary = {
            "LineNum": base_line,
            "ItemCode": line_item_code,
            "ItemDescription": (
                selected_line.get("ItemDescription")
                or selected_line.get("Dscription")
                or ""
            ),
            "Quantity": selected_line.get("Quantity"),
            "RemainingOpenQuantity": _json_safe(remaining),
            "LineStatus": line_status,
            "U_NXContenedor": (
                selected_line.get("U_NXContenedor")
                or ""
            ),
            "LineTotal": _json_safe(line_total),
        }

        if base_line is not None:
            validations.append(
                f"BaseLine resuelto: {base_line}"
            )
            source_data["base_line"] = base_line
        else:
            errors.append(
                "No se puede crear Borrador SAP: "
                "falta linea del pedido SAP."
            )

        if line_status == "bost_Open" or not line_status:
            validations.append(
                "Linea SAP esta abierta."
            )
        else:
            errors.append(
                f"Linea SAP no esta abierta: {line_status}"
            )

        if quantity and remaining and quantity != remaining:
            quantity_label = (
                "peso informado en guia"
                if origen_cantidad == ORIGEN_CANTIDAD_PESO_GUIA
                else (
                    "cantidad disponible"
                    if origen_cantidad == ORIGEN_CANTIDAD_DISPONIBLE
                    else "peso ticket salida"
                )
            )

            warnings.append(
                f"Quantity del borrador usa {quantity_label} "
                f"{_json_safe(quantity)}; "
                "la linea SAP tiene RemainingOpenQuantity "
                f"{_json_safe(remaining)}. "
                "Confirmar unidad con SAP antes de enviar."
            )

        quantity_exceeds_remaining = bool(
            quantity
            and remaining
            and quantity > remaining
        )

        if quantity_exceeds_remaining:
            warnings.append(
                "La cantidad informada supera la cantidad "
                "abierta en SAP. Revisar unidad de medida."
            )

        source_data["remaining_open_quantity"] = (
            _json_safe(remaining)
        )
        source_data["quantity_exceeds_remaining"] = (
            quantity_exceeds_remaining
        )

        if (
            not card_code
            and (
                "No se puede crear Borrador SAP: "
                "falta codigo proveedor SAP."
            )
            not in errors
        ):
            errors.append(
                "No se puede crear Borrador SAP: "
                "falta codigo proveedor SAP."
            )

        if (
            not line_item_code
            and (
                "No se puede crear Borrador SAP: "
                "falta codigo producto SAP."
            )
            not in errors
        ):
            errors.append(
                "No se puede crear Borrador SAP: "
                "falta codigo producto SAP."
            )

        if not errors and quantity and base_line is not None:
            document_line = {
                "LineNum": 0,
                "ItemCode": line_item_code,
                "Quantity": _json_safe(quantity),
                "BaseType": 22,
                "BaseEntry": doc_entry,
                "BaseLine": base_line,
                "WarehouseCode": estanque_destino,
            }

            if line_total not in [None, ""]:
                document_line["LineTotal"] = (
                    _json_safe(line_total)
                )

            payload = {
                "DocType": "dDocument_Items",
                "DocDate": fecha_accion,
                "DocDueDate": fecha_accion,
                "CardCode": card_code,
                "FolioPrefixString": folio_prefix,
                "FolioNumber": folio_number,
                "Series": _draft_series(),
                "DocObjectCode": 20,
                "TaxDate": fecha_accion,
                "DocumentLines": [
                    document_line
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
    sap_error_message = _sap_error_message(sap_error) if sap_error else ""
    log_data = {
        "accion": LOG_BORRADOR_SAP_GUIA_ENVIO,
        "success": success,
        "company_db": company_db,
        "sap_username": sap_username,
        "endpoint": "/Drafts",
        "citacion": citacion.id,
        "status_code": status_code,
        "payload": payload,
        "response": response or {},
        "sap_error": sap_error or {},
        "sap_error_message": sap_error_message,
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


def _sap_error_message(sap_error: Optional[Dict[str, Any]]) -> str:
    if not sap_error:
        return ""
    data = sap_error.get("data")
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, dict):
                return _clean_text(message.get("value") or message.get("lang"))
            if message:
                return _clean_text(message)
        if data.get("message"):
            return _clean_text(data.get("message"))
    if data:
        return _clean_text(data)
    return _clean_text(sap_error.get("error"))


def _draft_debug_response(
    *,
    preview: Dict[str, Any],
    user: Any,
    status_code: Optional[int] = None,
    response_payload: Any = None,
    sap_error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response_json = response_payload
    if response_json in [None, ""]:
        response_json = (sap_error or {}).get("data") if sap_error else {}
    if response_json in [None, ""]:
        response_json = sap_error or {}
    return {
        "request_json": preview.get("payload") or {},
        "response_json": response_json,
        "status_code": status_code,
        "sap_error_message": _sap_error_message(sap_error),
        "endpoint": "/Drafts",
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
        "usuario": getattr(user, "username", ""),
    }


def _json_pretty(value: Any) -> str:
    if value in [None, ""]:
        return ""
    try:
        return json.dumps(_json_safe(value), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _sap_error_short_message(data: Any) -> str:
    if not data:
        return ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, dict):
                return _clean_text(message.get("value") or message.get("lang"))
            if message:
                return _clean_text(message)
        for key in ("message", "error", "detail"):
            if data.get(key) and not isinstance(data.get(key), (dict, list)):
                return _clean_text(data.get(key))
        if data.get("data"):
            return _sap_error_short_message(data.get("data"))
    return _clean_text(data)


def _latest_update_recepcion_log(citacion: CITACION) -> Optional[OPERACION_PLANTA_LOG]:
    return (
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion,
            OPL_CPASO__in=[LOG_UPDATE_SAP_RECEPCION_ENVIO, LOG_UPDATE_SAP_RECEPCION_ERROR],
        )
        .select_related("US_NID")
        .order_by("-OPL_FFECHAREGISTRO", "-id")
        .first()
    )


def get_goods_receipt_draft_update_status(citacion: CITACION) -> Dict[str, Any]:
    draft_status = get_goods_receipt_draft_guide_status(citacion)
    peso_salida = get_exit_weight_from_citation(citacion)
    enviar_lote = _enviar_lote_en_update_draft_recepcion()
    modo_lote_configurado = (
        MODO_LOTE_AUTOMATICO_TERRAVIEW if enviar_lote else MODO_LOTE_MANUAL_SAP
    )
    log = _latest_update_recepcion_log(citacion)
    if not log:
        return {
            "updated": False,
            "is_error": False,
            "estado": "PENDIENTE",
            "label": "Pendiente de actualizar",
            "result_label": "PENDIENTE",
            "resumen_mensaje": "Debe actualizar el Borrador SAP de recepcion antes de autorizar la salida.",
            "docentry": draft_status.get("docentry") or "",
            "docnum": draft_status.get("docnum") or "",
            "item_code": draft_status.get("item_code") or "",
            "lote": "",
            "peso_salida": _json_safe(peso_salida),
            "peso_salida_kg": _json_safe(peso_salida),
            "cantidad_sap": _json_safe(convertir_peso_salida_kg_a_cantidad_sap_mt(peso_salida)),
            "unidad_sap": UNIDAD_SAP_TONELADA_METRICA,
            "lote_enviado": False,
            "modo_lote": modo_lote_configurado,
            "lote_manual": not enviar_lote,
            "request_json": {},
            "response_json": {},
            "request_json_pretty": "",
            "response_json_pretty": "",
            "status_code": "",
            "error_message": "",
            "endpoint": "",
            "usuario": "",
            "fecha_hora": "",
        }

    data = _parse_log_json(log)
    success = bool(data.get("success")) and log.OPL_CPASO == LOG_UPDATE_SAP_RECEPCION_ENVIO
    request_json = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    response_json = data.get("response") if isinstance(data.get("response"), dict) else {}
    sap_error = data.get("sap_error") if isinstance(data.get("sap_error"), dict) else {}
    if not response_json and sap_error:
        response_json = sap_error
    error_message = data.get("mensaje_corto") or _sap_error_short_message(sap_error or response_json)
    modo_lote = data.get("modo_lote") or (
        MODO_LOTE_AUTOMATICO_TERRAVIEW if data.get("lote") else modo_lote_configurado
    )
    lote_manual = modo_lote == MODO_LOTE_MANUAL_SAP
    return {
        "updated": success,
        "is_error": not success,
        "estado": "OK" if success else "ERROR",
        "label": "Borrador SAP actualizado" if success else "Error al actualizar SAP",
        "result_label": "OK" if success else "ERROR",
        "resumen_mensaje": (
            (
                "Borrador SAP actualizado con el pesaje de salida. "
                "Lote pendiente de ingreso manual en SAP."
                if lote_manual
                else "Borrador SAP actualizado correctamente con lote y peso de salida."
            )
            if success
            else "No se puede autorizar la salida porque la actualizacion SAP fallo."
        ),
        "docentry": data.get("docentry") or draft_status.get("docentry") or "",
        "docnum": data.get("docnum") or draft_status.get("docnum") or "",
        "item_code": data.get("item_code") or draft_status.get("item_code") or "",
        "lote": data.get("lote") or "",
        "peso_salida": data.get("peso_salida") or _json_safe(peso_salida),
        "peso_salida_kg": data.get("peso_salida_kg") or data.get("peso_salida") or _json_safe(peso_salida),
        "cantidad_sap": data.get("cantidad_sap") or _json_safe(
            convertir_peso_salida_kg_a_cantidad_sap_mt(peso_salida)
        ),
        "unidad_sap": data.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
        "lote_enviado": bool(data.get("lote_enviado")),
        "modo_lote": modo_lote,
        "lote_manual": lote_manual,
        "request_json": request_json,
        "response_json": response_json,
        "request_json_pretty": _json_pretty(request_json),
        "response_json_pretty": _json_pretty(response_json),
        "status_code": data.get("status_code") or "",
        "error_message": error_message,
        "endpoint": data.get("endpoint") or "",
        "usuario": log.US_NID.username if log.US_NID else data.get("usuario") or "",
        "fecha_hora": timezone.localtime(log.OPL_FFECHAREGISTRO).strftime("%d/%m/%Y %H:%M"),
    }


def generar_lote_recepcion_sap(item_code: str) -> str:
    item_code = _clean_text(item_code)
    if not item_code:
        raise GoodsReceiptDraftError("No se puede obtener lote SAP: falta codigo producto SAP.")
    hana_config = load_hana_config()
    company_db = _clean_text(hana_config.get("CompanyDB"))
    if not company_db or not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError("CompanyDB HANA tiene un formato no valido.")
    sql = f'''
        SELECT 'LOTE-MP-' || "ItemCode" || '-' || ("CUENTA") + 1 || '-001' AS "LOTE"
        FROM "{company_db}"."Add conteo de entradas para lote"
        WHERE "ItemCode" = ?
    '''
    row = _first_row(sql, [item_code])
    lote = _clean_text((row or {}).get("LOTE"))
    if not lote:
        raise GoodsReceiptDraftError("No se pudo obtener lote SAP para el producto.")
    return lote


def _guardar_lote_recepcion(citacion: CITACION, user: Any, lote: str) -> None:
    campo = CAMPO.objects.filter(
        EP_NID=citacion.EP_NID,
        CA_CCODIGO=CAMPO_LOTE_RECEPCION_SAP,
        CA_BHABILITADO=True,
    ).first()
    if not campo:
        campo = CAMPO.objects.create(
            EP_NID=citacion.EP_NID,
            US_NID=user,
            CA_CTIPO="TEXTO",
            CA_CCODIGO=CAMPO_LOTE_RECEPCION_SAP,
            CA_CETIQUETA="Lote SAP recepcion",
            CA_CPLACEMARK="Lote SAP recepcion",
            CA_BOBLIGATORIO=False,
            CA_BHABILITADO=True,
            CA_BASIGNARVALOR=False,
        )
    DATO_OPERACION.objects.update_or_create(
        CI_NID=citacion,
        SC_NID=citacion.SC_NID,
        CAMP_NID=campo,
        defaults={
            "EP_NID": citacion.EP_NID,
            "ET_NID": citacion.ETAPA_ACTUAL,
            "US_NID": user,
            "DO_CVALOR": lote,
            "DO_FFECHAREGISTRO": timezone.now(),
        },
    )


def build_goods_receipt_draft_update_with_salida_lote(
    citacion: CITACION,
    peso_salida: Any = None,
    lote: str = "",
    *,
    enviar_lote: Optional[bool] = None,
) -> Dict[str, Any]:
    errors: List[str] = []
    validations: List[str] = []
    warnings: List[str] = []
    draft_status = get_goods_receipt_draft_guide_status(citacion)
    docentry = _clean_int(draft_status.get("docentry"))
    docnum = draft_status.get("docnum") or ""
    request_json = draft_status.get("request_json") or {}
    line = (request_json.get("DocumentLines") or [{}])[0] if isinstance(request_json.get("DocumentLines"), list) else {}
    item_code = _clean_text(line.get("ItemCode") or draft_status.get("item_code"))
    peso_salida_kg = _as_decimal(
        peso_salida if peso_salida not in [None, ""] else get_exit_weight_from_citation(citacion)
    )
    cantidad_sap = convertir_peso_salida_kg_a_cantidad_sap_mt(peso_salida_kg)
    lote = _clean_text(lote)
    enviar_lote = _enviar_lote_en_update_draft_recepcion() if enviar_lote is None else bool(enviar_lote)
    lote_enviado = bool(enviar_lote and lote)
    modo_lote = MODO_LOTE_AUTOMATICO_TERRAVIEW if enviar_lote else MODO_LOTE_MANUAL_SAP

    if not draft_status.get("sent") or not docentry:
        errors.append("No se puede actualizar SAP: falta DocEntry del Borrador SAP de recepcion.")
    else:
        validations.append(f"Draft DocEntry recepcion: {docentry}")
    if not item_code:
        errors.append("No se puede obtener lote SAP: falta codigo producto SAP.")
    else:
        validations.append(f"ItemCode: {item_code}")
    if peso_salida_kg is None or peso_salida_kg <= 0:
        errors.append("No se puede actualizar SAP: falta pesaje de salida.")
    else:
        validations.append(f"Peso salida real: {_json_safe(peso_salida_kg)} kg")
        validations.append(f"Cantidad SAP: {_json_safe(cantidad_sap)} MT")
    if enviar_lote and not lote:
        errors.append("No se pudo obtener lote SAP para el producto.")
    elif enviar_lote:
        validations.append(f"Lote SAP generado: {lote}")
    else:
        validations.append("Lote manual en SAP: no se enviaran BatchNumbers.")

    payload: Dict[str, Any] = {}
    if not errors:
        document_line = {
            "LineNum": 0,
            "ItemCode": item_code,
            "Quantity": _json_safe(cantidad_sap),
        }
        if enviar_lote:
            document_line["BatchNumbers"] = [
                {
                    "BatchNumber": lote,
                    "Quantity": _json_safe(cantidad_sap),
                    "BaseLineNumber": 0,
                    "ItemCode": item_code,
                }
            ]
        payload = {"DocumentLines": [document_line]}
    return {
        "payload": payload,
        "source_data": {
            "citacion": citacion.id,
            "empresa": citacion.EP_NID_id,
            "draft_docentry": docentry,
            "draft_docnum": docnum,
            "item_code": item_code,
            "lote": lote,
            "peso_salida": _json_safe(peso_salida_kg),
            "peso_salida_kg": _json_safe(peso_salida_kg),
            "cantidad_sap": _json_safe(cantidad_sap),
            "unidad_sap": UNIDAD_SAP_TONELADA_METRICA,
            "lote_enviado": lote_enviado,
            "modo_lote": modo_lote,
            "endpoint": f"/Drafts({docentry})" if docentry else "",
        },
        "validations": validations,
        "warnings": warnings,
        "errors": errors,
        "status": get_goods_receipt_draft_update_status(citacion),
        "draft_status": draft_status,
    }


def _registrar_log_update_sap_recepcion(
    citacion: CITACION,
    user: Any,
    *,
    success: bool,
    payload: Dict[str, Any],
    response: Optional[Dict[str, Any]] = None,
    status_code: Optional[int] = None,
    sap_error: Optional[Dict[str, Any]] = None,
    docentry: Any = "",
    docnum: Any = "",
    item_code: str = "",
    lote: str = "",
    peso_salida_kg: Any = None,
    cantidad_sap: Any = None,
    unidad_sap: str = UNIDAD_SAP_TONELADA_METRICA,
    lote_enviado: bool = False,
    modo_lote: str = MODO_LOTE_MANUAL_SAP,
) -> OPERACION_PLANTA_LOG:
    accion = LOG_UPDATE_SAP_RECEPCION_ENVIO if success else LOG_UPDATE_SAP_RECEPCION_ERROR
    response_data = response or {}
    sap_error_data = sap_error or {}
    log_data = {
        "accion": accion,
        "success": success,
        "citacion": citacion.id,
        "tipo": citacion.CI_CTIPO,
        "endpoint": f"/Drafts({docentry})" if docentry else "",
        "status_code": status_code,
        "docentry": docentry,
        "docnum": docnum,
        "item_code": item_code,
        "peso_salida": _json_safe(peso_salida_kg),
        "peso_salida_kg": _json_safe(peso_salida_kg),
        "cantidad_sap": _json_safe(cantidad_sap),
        "unidad_sap": unidad_sap,
        "lote_enviado": bool(lote_enviado),
        "modo_lote": modo_lote,
        "payload": _json_safe(payload),
        "response": _json_safe(response_data),
        "sap_error": sap_error_data,
        "mensaje_corto": _sap_error_short_message(sap_error_data or response_data),
        "usuario": getattr(user, "username", ""),
        "fecha_hora": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S"),
    }
    if lote_enviado and lote:
        log_data["lote"] = lote
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=user,
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
        OPL_COBSERVACION=json.dumps(log_data, ensure_ascii=False),
    )


def send_goods_receipt_draft_update_to_sap(
    citacion: CITACION,
    user: Any,
    *,
    allow_retry: bool = False,
) -> Dict[str, Any]:
    with transaction.atomic():
        citacion_bloqueada = CITACION.objects.select_for_update().get(pk=citacion.pk)
        return _send_goods_receipt_draft_update_to_sap_locked(
            citacion_bloqueada,
            user,
            allow_retry=allow_retry,
        )


def _send_goods_receipt_draft_update_to_sap_locked(
    citacion: CITACION,
    user: Any,
    *,
    allow_retry: bool = False,
) -> Dict[str, Any]:
    existing = get_goods_receipt_draft_update_status(citacion)
    if existing.get("updated") and not allow_retry:
        return {
            "success": True,
            "message": existing.get("resumen_mensaje") or "Borrador SAP actualizado.",
            "status": existing,
        }

    draft_status = get_goods_receipt_draft_guide_status(citacion)
    item_code = draft_status.get("item_code") or ""
    peso_salida = get_exit_weight_from_citation(citacion)
    enviar_lote = _enviar_lote_en_update_draft_recepcion()
    lote = ""
    if enviar_lote:
        try:
            lote = generar_lote_recepcion_sap(item_code)
        except Exception as exc:
            preview = build_goods_receipt_draft_update_with_salida_lote(
                citacion,
                peso_salida,
                lote="",
                enviar_lote=True,
            )
            source = preview.get("source_data") or {}
            _registrar_log_update_sap_recepcion(
                citacion,
                user,
                success=False,
                payload=preview.get("payload") or {},
                sap_error={"error": str(exc)},
                docentry=source.get("draft_docentry") or draft_status.get("docentry") or "",
                docnum=source.get("draft_docnum") or draft_status.get("docnum") or "",
                item_code=item_code,
                lote="",
                peso_salida_kg=source.get("peso_salida_kg"),
                cantidad_sap=source.get("cantidad_sap"),
                unidad_sap=source.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
                lote_enviado=False,
                modo_lote=source.get("modo_lote") or MODO_LOTE_AUTOMATICO_TERRAVIEW,
            )
            return {
                "success": False,
                "message": str(exc),
                "preview": preview,
                "sap_error": {"error": str(exc)},
                "status": get_goods_receipt_draft_update_status(citacion),
            }
        _guardar_lote_recepcion(citacion, user, lote)

    preview = build_goods_receipt_draft_update_with_salida_lote(
        citacion,
        peso_salida,
        lote,
        enviar_lote=enviar_lote,
    )
    source = preview.get("source_data") or {}
    docentry = source.get("draft_docentry")
    if preview.get("errors") or not preview.get("payload"):
        message = preview["errors"][0] if preview.get("errors") else "Faltan datos obligatorios para actualizar SAP."
        _registrar_log_update_sap_recepcion(
            citacion,
            user,
            success=False,
            payload=preview.get("payload") or {},
            sap_error={"error": message},
            docentry=docentry or "",
            docnum=source.get("draft_docnum") or "",
            item_code=source.get("item_code") or item_code,
            lote=lote,
            peso_salida_kg=source.get("peso_salida_kg"),
            cantidad_sap=source.get("cantidad_sap"),
            unidad_sap=source.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
            lote_enviado=source.get("lote_enviado", False),
            modo_lote=source.get("modo_lote") or MODO_LOTE_MANUAL_SAP,
        )
        return {
            "success": False,
            "message": message,
            "preview": preview,
            "sap_error": {"error": message},
            "status": get_goods_receipt_draft_update_status(citacion),
        }

    config = load_config(citacion.EP_NID_id, for_write=True)
    client = SapServiceLayerClient(config)
    status_code: Optional[int] = None
    response_payload: Dict[str, Any] = {}
    try:
        print(
            f"\n[Update SAP][Recepcion] citacion={citacion.id} empresa={citacion.EP_NID_id} "
            f"CompanyDB={config.company_db} endpoint=/Drafts({docentry})"
        )
        print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))
        client.login()
        sap_response = client.patch_draft(docentry, preview["payload"])
        status_code = sap_response.get("status_code")
        response_payload = sap_response.get("data") or {}
    except HTTPError as exc:
        error_data = _extract_sap_error(exc)
        _registrar_log_update_sap_recepcion(
            citacion,
            user,
            success=False,
            payload=preview["payload"],
            status_code=error_data.get("status_code"),
            sap_error=error_data,
            docentry=docentry,
            docnum=source.get("draft_docnum") or "",
            item_code=source.get("item_code") or "",
            lote=lote,
            peso_salida_kg=source.get("peso_salida_kg"),
            cantidad_sap=source.get("cantidad_sap"),
            unidad_sap=source.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
            lote_enviado=source.get("lote_enviado", False),
            modo_lote=source.get("modo_lote") or MODO_LOTE_MANUAL_SAP,
        )
        return {
            "success": False,
            "message": "SAP rechazo la actualizacion del Borrador SAP de recepcion.",
            "status_code": error_data.get("status_code"),
            "sap_error": error_data,
            "preview": preview,
            "status": get_goods_receipt_draft_update_status(citacion),
        }
    except SapServiceLayerProbeError as exc:
        error_data = {"error": str(exc)}
        _registrar_log_update_sap_recepcion(
            citacion,
            user,
            success=False,
            payload=preview["payload"],
            sap_error=error_data,
            docentry=docentry,
            docnum=source.get("draft_docnum") or "",
            item_code=source.get("item_code") or "",
            lote=lote,
            peso_salida_kg=source.get("peso_salida_kg"),
            cantidad_sap=source.get("cantidad_sap"),
            unidad_sap=source.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
            lote_enviado=source.get("lote_enviado", False),
            modo_lote=source.get("modo_lote") or MODO_LOTE_MANUAL_SAP,
        )
        return {
            "success": False,
            "message": str(exc),
            "sap_error": error_data,
            "preview": preview,
            "status": get_goods_receipt_draft_update_status(citacion),
        }
    finally:
        client.logout()

    _registrar_log_update_sap_recepcion(
        citacion,
        user,
        success=True,
        payload=preview["payload"],
        response=response_payload,
        status_code=status_code,
        docentry=docentry,
        docnum=source.get("draft_docnum") or "",
        item_code=source.get("item_code") or "",
        lote=lote,
        peso_salida_kg=source.get("peso_salida_kg"),
        cantidad_sap=source.get("cantidad_sap"),
        unidad_sap=source.get("unidad_sap") or UNIDAD_SAP_TONELADA_METRICA,
        lote_enviado=source.get("lote_enviado", False),
        modo_lote=source.get("modo_lote") or MODO_LOTE_MANUAL_SAP,
    )
    return {
        "success": True,
        "message": (
            "Borrador SAP actualizado."
            if enviar_lote
            else "Borrador SAP actualizado con el pesaje de salida. "
                 "Lote pendiente de ingreso manual en SAP."
        ),
        "status_code": status_code,
        "request_json": preview["payload"],
        "response": response_payload,
        "preview": preview,
        "status": get_goods_receipt_draft_update_status(citacion),
    }


def send_goods_receipt_draft_from_peso_guia_to_sap(
    citacion: CITACION,
    user: Any,
    *,
    confirm_quantity_exceeds: bool = False,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    existing_status = get_goods_receipt_draft_guide_status(citacion)
    # allow_duplicate se conserva solo por compatibilidad de firma: nunca habilita reenvios.
    if existing_status.get("sent"):
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
        errors = preview.get("errors") or []
        return {
            "success": False,
            "message": errors[0] if errors else "El borrador no es valido. No se envio a SAP.",
            "preview": preview,
            "status": existing_status,
            **_draft_debug_response(preview=preview, user=user),
        }

    source_data = preview.get("source_data") or {}
    if source_data.get("quantity_exceeds_remaining") and not confirm_quantity_exceeds:
        return {
            "success": False,
            "confirmation_required": True,
            "message": "La cantidad informada supera la cantidad abierta en SAP. Revisar unidad de medida.",
            "preview": preview,
            "status": existing_status,
            **_draft_debug_response(preview=preview, user=user),
        }

    config = load_config(citacion.EP_NID_id, for_write=True)
    expected_company_db = str(settings.SAP_DRAFT_QA_COMPANY_DB or "").strip()
    if (
        normalize_sap_environment() == SAP_ENV_QA
        and config.company_db != expected_company_db
    ):
        return {
            "success": False,
            "message": (
                f"Envio bloqueado: CompanyDB configurada {config.company_db} "
                f"no coincide con SAP QA esperado {expected_company_db}."
            ),
            "preview": preview,
            "status": existing_status,
            **_draft_debug_response(
                preview=preview,
                user=user,
                sap_error={"error": "CompanyDB no coincide con SAP QA esperado."},
            ),
        }

    client = SapServiceLayerClient(config)
    print(
        f"\n[Borrador SAP][Peso guia][Enviar QA] citacion={citacion.id} "
        f"empresa={citacion.EP_NID_id} origen_cantidad=peso_guia "
        f"CompanyDB={config.company_db} endpoint=/Drafts"
    )
    print(json.dumps(preview["payload"], indent=2, ensure_ascii=False))
    folio_source = preview.get("source_data") or {}
    _log_recepcion_folio(
        citacion,
        str(folio_source.get("folio_prefix") or ""),
        folio_source.get("folio_number"),
        str(folio_source.get("estanque_destino") or ""),
    )

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
            **_draft_debug_response(
                preview=preview,
                user=user,
                status_code=error_data.get("status_code"),
                sap_error=error_data,
            ),
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
            **_draft_debug_response(
                preview=preview,
                user=user,
                sap_error=error_data,
            ),
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
        "docentry": response_payload.get("DocEntry") or response_payload.get("docentry"),
        "docnum": response_payload.get("DocNum") or response_payload.get("docnum"),
        **_draft_debug_response(
            preview=preview,
            user=user,
            status_code=status_code,
            response_payload=response_payload,
        ),
    }


def send_goods_receipt_draft_to_sap(citacion: CITACION, user: Any, allow_duplicate: bool = False) -> Dict[str, Any]:
    existing = _existing_draft_log(citacion)
    legacy_status = get_goods_receipt_draft_status(citacion)
    guide_status = get_goods_receipt_draft_guide_status(citacion)
    # allow_duplicate se conserva solo por compatibilidad de firma: nunca habilita reenvios.
    if existing or guide_status.get("sent"):
        status = guide_status if guide_status.get("sent") else legacy_status
        return {
            "success": False,
            "message": "Ya existe un borrador SAP creado para esta citacion: DocEntry %s. El reenvio esta bloqueado." % (status.get("docentry") or "sin DocEntry informado"),
            "existing": status,
        }

    preview = build_goods_receipt_draft_preview(citacion)
    if preview.get("errors") or not preview.get("payload"):
        return {
            "success": False,
            "message": "Preview invalido. No se envio a SAP.",
            "preview": preview,
        }

    config = load_config(citacion.EP_NID_id, for_write=True)
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
        folio_source = preview.get("source_data") or {}
        _log_recepcion_folio(
            citacion,
            str(folio_source.get("folio_prefix") or ""),
            folio_source.get("folio_number"),
            str(folio_source.get("estanque_destino") or ""),
        )
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
