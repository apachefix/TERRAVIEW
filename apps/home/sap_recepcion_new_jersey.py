"""Ingreso SAP real de New Jersey Proceso 1, aislado de PROSESA."""
from __future__ import annotations

import json
import os
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests import HTTPError

from apps.home.models import CAMPO, CITACION, DATO_OPERACION, OPERACION_PLANTA_LOG
from apps.integrations.sap_b1 import sap_recepcion as technical
from apps.integrations.sap_b1.service_layer_probe import (
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    load_config,
)

LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1 = "PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1_ENVIO"
CAMPO_LOTE_SAP_NEW_JERSEY_P1 = "SAP_LOTE_INGRESO_NEW_JERSEY_P1"
SECUENCIAS_NEW_JERSEY_P1 = {
    "RECEPCION_NEW_JERSEY_P1_CON_CALIDAD",
    "RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD",
}


def generar_lote_sap_new_jersey_p1(
    item_code: str, numero_linea: int,
) -> dict[str, Any]:
    """Usa el contador HANA y el formato compartido con PROSESA."""
    lote = technical.generar_lote_sap_recepcion_prosesa_piso_1(
        item_code, numero_linea=numero_linea,
    )
    return {**lote, "numero_linea": numero_linea}


def obtener_lote_sap_new_jersey_p1(citacion: CITACION) -> dict[str, Any]:
    raw = technical._dato_valor(citacion, CAMPO_LOTE_SAP_NEW_JERSEY_P1)
    if not raw:
        return {}
    try:
        lote = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return lote if isinstance(lote, dict) else {}


def guardar_lote_sap_new_jersey_p1(
    citacion: CITACION, user: Any, lote: dict[str, Any],
) -> dict[str, Any]:
    if not es_recepcion_new_jersey_p1_sap(citacion):
        raise technical.GoodsReceiptDraftError("El lote SAP solo aplica a New Jersey P1.")
    item_code = str(lote.get("item_code") or "").strip()
    numero_linea = lote.get("numero_linea", 1)
    esperado = technical.componer_lote_sap(
        item_code, lote.get("correlativo"), numero_linea,
    )
    if (
        lote.get("batch_number") != esperado["batch_number"]
        or lote.get("sufijo") != esperado["sufijo"]
    ):
        raise technical.GoodsReceiptDraftError("El lote New Jersey no cumple la regla SAP.")
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID=citacion.EP_NID, CA_CCODIGO=CAMPO_LOTE_SAP_NEW_JERSEY_P1,
        defaults={
            "US_NID": user, "CA_CTIPO": "TEXTO",
            "CA_CETIQUETA": "Lote SAP ingreso New Jersey P1",
            "CA_CPLACEMARK": "Lote SAP ingreso New Jersey P1",
            "CA_BOBLIGATORIO": False, "CA_BHABILITADO": True,
            "CA_BASIGNARVALOR": False,
        },
    )
    ahora = timezone.now()
    auditado = {
        "citacion": citacion.pk, "item_code": item_code,
        "tipo_lote": esperado["tipo_lote"],
        "correlativo": esperado["correlativo"],
        "numero_linea": int(numero_linea),
        "sufijo": esperado["sufijo"],
        "batch_number": esperado["batch_number"],
        "usuario": getattr(user, "username", ""),
        "usuario_id": getattr(user, "pk", None),
        "fecha_hora": timezone.localtime(ahora).isoformat(),
    }
    if lote.get("lote_anterior"):
        auditado["lote_anterior"] = lote["lote_anterior"]
        auditado["fecha_hora_lote_anterior"] = lote.get("fecha_hora_lote_anterior")
    DATO_OPERACION.objects.update_or_create(
        CI_NID=citacion, SC_NID=citacion.SC_NID, CAMP_NID=campo,
        defaults={
            "EP_NID": citacion.EP_NID, "ET_NID": citacion.ETAPA_ACTUAL,
            "US_NID": user, "DO_CVALOR": json.dumps(auditado, ensure_ascii=False),
            "DO_FFECHAREGISTRO": ahora,
        },
    )
    return auditado


def validar_lote_sap_new_jersey_p1(lote: dict[str, Any], item_code: str) -> str:
    if not lote:
        return "Debe generar el lote SAP antes de previsualizar el ingreso."
    if str(lote.get("item_code") or "").strip() != item_code:
        return "El lote SAP guardado corresponde a otro ItemCode."
    try:
        esperado = technical.componer_lote_sap(
            item_code, lote.get("correlativo"), lote.get("numero_linea", 1),
        )
    except technical.GoodsReceiptDraftError:
        return "El lote SAP guardado no cumple el formato vigente de New Jersey."
    if (
        lote.get("batch_number") != esperado["batch_number"]
        or lote.get("sufijo") != esperado["sufijo"]
    ):
        return "El lote SAP guardado no cumple el formato vigente de New Jersey."
    return ""


def _es_candidato_legacy_itemcode(lote: dict[str, Any], item_code: str) -> bool:
    """Reconoce solo el candidato -XX creado por la interpretaci?n anterior."""
    try:
        esperado = technical.componer_lote_sap(
            item_code, lote.get("correlativo"), lote.get("numero_linea", 1),
        )
    except technical.GoodsReceiptDraftError:
        return False
    sufijo_anterior = ("000" + item_code)[-2:]
    anterior = (
        f"LOTE-{esperado['tipo_lote']}-{item_code}-"
        f"{esperado['correlativo']}-{sufijo_anterior}"
    )
    return bool(
        sufijo_anterior != esperado["sufijo"]
        and lote.get("item_code") == item_code
        and lote.get("sufijo") == sufijo_anterior
        and lote.get("batch_number") == anterior
    )


def _lote_existe_en_sap(item_code: str, batch_number: str) -> bool:
    """Consulta solo OBTN; ante error, el candidato no se modifica."""
    hana = technical.load_hana_config()
    schema = str(hana.get("CompanyDB") or "").strip()
    if not technical.HANA_IDENTIFIER_RE.match(schema):
        raise technical.GoodsReceiptDraftError("CompanyDB HANA invalida al revisar lote.")
    sql = (
        f'SELECT COUNT(*) AS "N" FROM "{schema}"."OBTN" '
        'WHERE "ItemCode" = ? AND "DistNumber" = ?'
    )
    row = technical._first_row(sql, [item_code, batch_number])
    return bool(technical._clean_int((row or {}).get("N")))


def get_new_jersey_virtual_warehouse() -> str:
    # core/settings.py es local/ignorado en este repositorio; el fallback conserva
    # la configuracion de .env en otros despliegues sin tomar BODEGA_VIRTUAL.
    configured = getattr(settings, "BODEGA_VIRTUAL_NEW_JERSEY", None)
    if configured is None:
        configured = os.getenv("BODEGA_VIRTUAL_NEW_JERSEY", "")
    return str(configured or "").strip()


def es_recepcion_new_jersey_p1_sap(citacion: CITACION) -> bool:
    return bool(
        citacion
        and citacion.EP_NID_id == 2
        and str(citacion.CI_CTIPO or "").strip().upper() == "RECEPCION"
        and str(getattr(citacion.SC_NID, "SE_CCODIGO", "") or "").strip().upper()
        in SECUENCIAS_NEW_JERSEY_P1
    )


def _operacion(citacion: CITACION):
    proceso = getattr(citacion, "proceso_new_jersey", None)
    if proceso and proceso.ONJP_CTIPO == "PROCESO_1":
        return proceso.ONJ_NID
    return None


def resolver_item_code_new_jersey_p1(citacion: CITACION) -> str:
    if not es_recepcion_new_jersey_p1_sap(citacion):
        raise technical.GoodsReceiptDraftError("La citacion no corresponde a New Jersey P1.")
    operacion = _operacion(citacion)
    detalle = technical._latest_detail(citacion)
    item_code = str(
        getattr(operacion, "ONJ_CITEM_CODE", "")
        or getattr(detalle, "CDO_CCODIGO_SAP", "")
        or ""
    ).strip()
    if not item_code:
        raise technical.GoodsReceiptDraftError("Falta ItemCode persistido para New Jersey P1.")
    return item_code


def generar_y_guardar_lote_sap_new_jersey_p1(
    citacion: CITACION, user: Any,
) -> dict[str, Any]:
    if not es_recepcion_new_jersey_p1_sap(citacion):
        raise technical.GoodsReceiptDraftError("La citacion no corresponde a New Jersey P1.")
    with transaction.atomic():
        CITACION.objects.select_for_update().get(pk=citacion.pk)
        status = get_purchase_delivery_note_new_jersey_p1_status(citacion)
        if status["sent"] or status.get("outcome_unknown"):
            raise technical.GoodsReceiptDraftError(
                "El Ingreso SAP ya fue creado o tiene resultado incierto; no se generara otro lote."
            )
        item_code = resolver_item_code_new_jersey_p1(citacion)
        vigente = obtener_lote_sap_new_jersey_p1(citacion)
        if vigente:
            error = validar_lote_sap_new_jersey_p1(vigente, item_code)
            if not error:
                return vigente
            if not _es_candidato_legacy_itemcode(vigente, item_code):
                raise technical.GoodsReceiptDraftError(error)
            if _lote_existe_en_sap(item_code, vigente["batch_number"]):
                raise technical.GoodsReceiptDraftError(
                    "El lote anterior ya existe en SAP; no se modifico el candidato local."
                )
            numero_linea = vigente.get("numero_linea", 1)
            corregido = technical.componer_lote_sap(
                item_code, vigente["correlativo"], numero_linea,
            )
            return guardar_lote_sap_new_jersey_p1(citacion, user, {
                **corregido, "numero_linea": numero_linea,
                "lote_anterior": vigente["batch_number"],
                "fecha_hora_lote_anterior": vigente.get("fecha_hora"),
            })

        config = load_config(citacion.EP_NID_id)
        client = SapServiceLayerClient(config)
        try:
            client.login()
            item = client.get_json(
                "Items('" + item_code.replace("'", "''") + "')",
                "Item New Jersey P1 para lote",
            )
        finally:
            client.logout()
        if str(item.get("ManageBatchNumbers") or "").strip().lower() != "tyes":
            raise technical.GoodsReceiptDraftError(
                "El ItemCode SAP no esta administrado por lote; no corresponde generar uno."
            )
        numero_linea = technical.numero_linea_lote_desde_line_num(0)
        lote = generar_lote_sap_new_jersey_p1(item_code, numero_linea)
        return guardar_lote_sap_new_jersey_p1(citacion, user, lote)


def get_purchase_delivery_note_new_jersey_p1_status(citacion: CITACION) -> dict[str, Any]:
    log = (
        OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion, OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1
        )
        .select_related("US_NID")
        .order_by("-OPL_FFECHAREGISTRO", "-id")
        .first()
    )
    if not log:
        return {
            "sent": False, "created": False, "local_status": "Pendiente de crear",
            "sap_status": "No enviado", "endpoint": "/PurchaseDeliveryNotes",
        }
    data = technical._parse_log_json(log)
    response = data.get("response") or {}
    sent = bool(data.get("success")) and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO
    return {
        "sent": sent,
        "created": sent,
        "outcome_unknown": bool(data.get("outcome_unknown")),
        "local_status": "Ingreso SAP creado" if sent else "Ingreso SAP no confirmado",
        "sap_status": "Creado en SAP" if sent else "No confirmado en SAP",
        "endpoint": "/PurchaseDeliveryNotes",
        "status_code": data.get("status_code"),
        "docentry": response.get("DocEntry") or response.get("docentry"),
        "docnum": response.get("DocNum") or response.get("docnum"),
        "request_json": data.get("payload") or {},
        "response_json": response or data.get("sap_error") or {},
        "sap_error": data.get("sap_error"),
        "usuario": log.US_NID.username if log.US_NID else "",
        "fecha_hora": timezone.localtime(log.OPL_FFECHAREGISTRO).strftime("%d/%m/%Y %H:%M"),
    }


def build_purchase_delivery_note_new_jersey_p1(citacion: CITACION) -> dict[str, Any]:
    """Consulta SAP, valida la orden y prepara exactamente el JSON que enviara el sender."""
    errors: list[str] = []
    validations: list[str] = []
    warnings: list[str] = []
    source: dict[str, Any] = {"citacion": citacion.pk, "peso_fuente": technical.CAMPO_PESO_INFORMADO_GUIA}
    result: dict[str, Any] = {
        "ready_for_post": False, "document_type": "PurchaseDeliveryNotes",
        "endpoint": "/PurchaseDeliveryNotes", "flow": "RECEPCION_NEW_JERSEY_P1",
        "payload": {}, "source_data": source, "purchase_order": {},
        "selected_line": {}, "validations": validations, "warnings": warnings,
        "errors": errors,
    }
    if not es_recepcion_new_jersey_p1_sap(citacion):
        errors.append("La citacion no corresponde a New Jersey Proceso 1 de Empresa 2 Recepcion.")
        return result

    detalle = technical._latest_detail(citacion)
    operacion = _operacion(citacion)
    datos_ingreso = technical.resolver_datos_ingreso_mercaderia_sbh(citacion, detalle)
    warehouse = get_new_jersey_virtual_warehouse()
    doc_entry = technical._clean_int(
        getattr(operacion, "ONJ_CBASE_ENTRY", "") or technical._resolve_doc_entry(citacion, detalle)
    )
    item_code = str(
        getattr(operacion, "ONJ_CITEM_CODE", "")
        or getattr(detalle, "CDO_CCODIGO_SAP", "")
        or ""
    ).strip()
    base_line_guardada = str(getattr(operacion, "ONJ_CBASE_LINE", "") or "").strip()
    peso_kg = technical._as_decimal(
        technical._dato_valor(citacion, technical.CAMPO_PESO_INFORMADO_GUIA)
    )
    quantity_mt = technical.convertir_peso_salida_kg_a_cantidad_sap_mt(peso_kg)
    folio_prefix, folio_number, folio_errors = technical.get_folio_from_citation(citacion)
    source.update({
        "base_entry": doc_entry, "item_code": item_code,
        "base_line_guardada": base_line_guardada,
        "warehouse_code": warehouse,
        "destino_fisico": str(getattr(detalle, "CDO_CESTANQUE_DESTINO", "") or "").strip(),
        "peso_informado_guia_kg": technical._json_safe(peso_kg),
        "quantity_mt": technical._json_safe(quantity_mt),
        "folio_prefix": folio_prefix, "folio_number": folio_number,
        "datos_ingreso_mercaderia": technical._json_safe(datos_ingreso),
    })
    for campo, valor in datos_ingreso["fechas_invalidas"].items():
        errors.append(f"{campo} invalida para SAP: {valor}.")
    if not warehouse:
        errors.append("Debe configurar BODEGA_VIRTUAL_NEW_JERSEY antes de crear el Ingreso SAP.")
    if not doc_entry:
        errors.append("Falta BaseEntry/DocEntry del Purchase Order SAP.")
    if not item_code:
        errors.append("Falta ItemCode de New Jersey Proceso 1.")
    if peso_kg is None or peso_kg <= 0:
        errors.append("Falta SAP_PESO_INFORMADO_GUIA valido y positivo, capturado por Asistente Recepcion.")
    errors.extend(folio_errors)
    if errors:
        return result

    client = None
    try:
        config = load_config(citacion.EP_NID_id)
        fecha_sap = technical.obtener_fecha_sistema_sap(config.company_db)
        source["sap_system_date"] = fecha_sap
        source["posting_date_source"] = "HANA CURRENT_DATE"
        client = SapServiceLayerClient(config)
        client.login()
        order = client.get_json(f"PurchaseOrders({doc_entry})", "Purchase Order New Jersey P1")
        lines = order.get("DocumentLines") or []
        if not isinstance(lines, list):
            errors.append("Purchase Order sin DocumentLines validas.")
            return result
        candidates = [
            line for line in lines
            if str(line.get("ItemCode") or "").strip() == item_code
        ]
        if base_line_guardada:
            base_line = technical._clean_int(base_line_guardada)
            candidates = [
                line for line in candidates
                if technical._line_num(line) == base_line
            ]
        if len(candidates) != 1:
            errors.append(
                "No fue posible resolver una linea SAP unica para ItemCode y BaseLine de New Jersey."
            )
            return result
        line = candidates[0]
        base_line = technical._line_num(line)
        if base_line is None:
            errors.append("La linea SAP no informa LineNum/BaseLine.")
            return result
        if str(line.get("LineStatus") or "") != "bost_Open":
            errors.append("La linea del Purchase Order SAP no esta abierta.")
        sap_uom = str(line.get("UoMCode") or "").strip()
        if sap_uom.upper() != technical.UNIDAD_SAP_TONELADA_METRICA:
            errors.append(
                f"La linea SAP usa UoMCode {sap_uom or 'sin informar'}; no se puede convertir kg a MT."
            )
        item = client.get_json(
            "Items('" + item_code.replace("'", "''") + "')", "Item New Jersey P1"
        )
        managed = str(item.get("ManageBatchNumbers") or "").strip().lower()
        if managed not in {"tyes", "tno"}:
            errors.append("SAP no confirma si el ItemCode requiere lote.")
        remaining = technical._line_open_quantity(line)
        if remaining is not None and quantity_mt is not None and quantity_mt > remaining:
            warnings.append("Quantity supera RemainingOpenQuantity; SAP validara el saldo al enviar.")
        result["purchase_order"] = {
            "DocEntry": order.get("DocEntry"), "DocNum": order.get("DocNum"),
            "CardCode": order.get("CardCode"),
        }
        result["selected_line"] = {
            "BaseType": 22, "BaseEntry": doc_entry, "BaseLine": base_line,
            "ItemCode": item_code, "UoMCode": sap_uom,
            "ManageBatchNumbers": item.get("ManageBatchNumbers"),
            "RemainingOpenQuantity": technical._json_safe(remaining),
        }
        source.update({
            "base_line": base_line, "sap_quantity_unit": sap_uom,
            "manage_batch_numbers": item.get("ManageBatchNumbers"),
        })
        if not order.get("CardCode"):
            errors.append("Purchase Order SAP no informa CardCode.")
        if errors:
            return result
        document_line = {
            "LineNum": 0, "ItemCode": item_code,
            "Quantity": technical._json_safe(quantity_mt),
            "BaseType": 22, "BaseEntry": doc_entry, "BaseLine": base_line,
            "WarehouseCode": warehouse,
        }
        documentos = datos_ingreso["documentos"]
        fechas = datos_ingreso["fechas"]
        udf_linea = {
            "U_CDA": documentos["cda"],
            "U_DI": documentos["di"],
            "U_BL": documentos["bl"],
            "U_HCO_NAVIERAS": documentos["nave_naviera"],
            "U_HCO_FVEN": fechas["fecha_produccion"],
            "U_NXFlote": fechas["fecha_vencimiento"],
            "U_SUI": documentos["sui"],
            "U_HCO_BOOKING": documentos["booking"],
        }
        document_line.update({
            campo: valor for campo, valor in udf_linea.items()
            if technical._clean_text(valor)
        })
        if managed == "tyes":
            lote = obtener_lote_sap_new_jersey_p1(citacion)
            error_lote = validar_lote_sap_new_jersey_p1(lote, item_code)
            if error_lote:
                errors.append(error_lote)
                return result
            document_line["BatchNumbers"] = [{
                "BatchNumber": lote["batch_number"],
                "Quantity": technical._json_safe(quantity_mt),
            }]
            source["lote_sap"] = lote
            validations.append("Lote New Jersey persistido y validado para este ItemCode.")
        else:
            validations.append("ItemCode sin gestion por lote; no se agrega BatchNumbers.")
        result["payload"] = {
            "DocType": "dDocument_Items",
            "DocDate": fecha_sap, "DocDueDate": fecha_sap, "TaxDate": fecha_sap,
            "CardCode": order["CardCode"],
            "FolioPrefixString": folio_prefix, "FolioNumber": folio_number,
            "Series": technical._draft_series(),
            "DocumentLines": [document_line],
        }
        transporte = datos_ingreso["transporte"]
        udf_cabecera = {
            "U_NXNombreTransporte": transporte["nombre_transporte"],
            "U_NXRutChofer": transporte["rut_conductor"],
            "U_NXNombreChofer": transporte["nombre_conductor"],
            "U_NXTelefonoChofer": transporte["telefono_conductor"],
        }
        result["payload"].update({
            campo: valor for campo, valor in udf_cabecera.items()
            if technical._clean_text(valor)
        })
        validations.extend([
            "Purchase Order consultada en SAP en modo lectura.",
            f"BaseType 22, BaseEntry {doc_entry}, BaseLine {base_line}, ItemCode {item_code}.",
            f"Quantity = {technical._decimal_text(peso_kg)} kg / 1000 = {technical._decimal_text(quantity_mt)} MT.",
            f"WarehouseCode New Jersey: {warehouse}.",
            f"Fecha SAP/HANA: {fecha_sap}.",
        ])
    except (HTTPError, SapServiceLayerProbeError, technical.GoodsReceiptDraftError, technical.SapDiApiError) as exc:
        errors.append(f"No fue posible preparar el Ingreso SAP de New Jersey: {exc}")
    finally:
        if client:
            client.logout()
    result["ready_for_post"] = bool(result["payload"]) and not errors
    return result


def _guardar_log(citacion, user, payload, *, success, response=None, status_code=None,
                 sap_error=None, outcome_unknown=False):
    data = {
        "success": success, "outcome_unknown": outcome_unknown,
        "payload": payload, "response": response or {},
        "status_code": status_code, "sap_error": sap_error or {},
    }
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=user, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
        CI_NID=citacion, OPL_CPASO=LOG_PURCHASE_DELIVERY_NOTE_NEW_JERSEY_P1,
        OPL_CPERFIL_RESPONSABLE="ASISTENTE DE RECEPCION",
        OPL_CESTADO=(
            OPERACION_PLANTA_LOG.ESTADO_COMPLETADO if success
            else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
        ),
        OPL_COBSERVACION=json.dumps(data, ensure_ascii=False),
    )


def send_purchase_delivery_note_new_jersey_p1_to_sap(citacion: CITACION, user) -> dict[str, Any]:
    if not es_recepcion_new_jersey_p1_sap(citacion):
        return {"success": False, "message": "La citacion no corresponde a New Jersey Proceso 1."}
    # El bloqueo de la citacion serializa doble click y doble POST del mismo documento.
    with transaction.atomic():
        CITACION.objects.select_for_update().get(pk=citacion.pk)
        status = get_purchase_delivery_note_new_jersey_p1_status(citacion)
        if status["sent"] or status.get("outcome_unknown"):
            return {
                "success": False,
                "message": (
                    "Ya existe un Ingreso SAP para esta citacion; el reenvio esta bloqueado."
                    if status["sent"] else
                    "El resultado del intento anterior no se pudo confirmar; revisar SAP antes de reintentar."
                ),
                "existing": status,
            }
        preview = build_purchase_delivery_note_new_jersey_p1(citacion)
        if not preview["ready_for_post"]:
            return {
                "success": False, "message": (preview.get("errors") or ["Previsualizacion invalida. No se envio a SAP."])[0],
                "preview": preview,
            }
        payload = preview["payload"]
        try:
            config = load_config(citacion.EP_NID_id, for_write=True)
            client = SapServiceLayerClient(config)
            try:
                client.login()
                posted = client.post_purchase_delivery_note(payload)
            finally:
                client.logout()
        except HTTPError as exc:
            error = technical._extract_sap_error(exc)
            status_code = error.get("status_code")
            uncertain = status_code is None or int(status_code) >= 500
            _guardar_log(citacion, user, payload, success=False, sap_error=error,
                         status_code=status_code, outcome_unknown=uncertain)
            return {
                "success": False,
                "message": (
                    "SAP no confirmo el resultado; revisar antes de reintentar."
                    if uncertain else technical._sap_error_message(error) or str(exc)
                ),
                "sap_error": error, "preview": preview,
            }
        except Exception as exc:
            # Un timeout tras POST deja resultado incierto: bloquear reenvio automatico.
            _guardar_log(citacion, user, payload, success=False,
                         sap_error={"message": str(exc)}, outcome_unknown=True)
            return {
                "success": False,
                "message": "No se pudo confirmar el resultado SAP; revisar antes de reintentar.",
                "preview": preview,
            }
        response = posted.get("data") or {}
        if not (response.get("DocEntry") or response.get("docentry")):
            _guardar_log(citacion, user, payload, success=False,
                         response=response, status_code=posted.get("status_code"),
                         outcome_unknown=True)
            return {
                "success": False,
                "message": "SAP no confirmo DocEntry; revisar el documento antes de reintentar.",
                "preview": preview, "response": response,
            }
        _guardar_log(citacion, user, payload, success=True, response=response,
                     status_code=posted.get("status_code"))
        return {
            "success": True, "message": "Ingreso SAP creado.",
            "status_code": posted.get("status_code"), "response": response,
            "preview": preview, "endpoint": "/PurchaseDeliveryNotes",
            "status": get_purchase_delivery_note_new_jersey_p1_status(citacion),
        }
