"""
SAP Despacho.

Centraliza la logica SAP propia del flujo de DESPACHO. En la revision de
Asistente_Recepcion SAP debe seguir oculto; este modulo deja preparados los
datos para su uso posterior, principalmente en Pesaje Salida de Despacho.
"""

import json
import os
import re
import unicodedata
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests import HTTPError

from apps.integrations.sap_b1.service_layer_probe import (
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    load_config,
)

from .models import (
    CAMION_PATIO,
    CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DRAFT_SAP,
    CITACION_DESPACHO_ASIGNACION_SAP,
    CITACION_DESPACHO_DETALLE,
    CITACION_DESPACHO_ACUERDO_LOTE,
    DATO_OPERACION,
    OPERACION_PLANTA_LOG,
)
from .sap_di_api import HANA_IDENTIFIER_RE, SapDiApiError, _load_config, _rows, consultar_acuerdos_despacho_sap


SAP_DESPACHO_DRAFT_SERIES_DEFAULT = 116
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
    "factura reserva": "FE_RESERVA",
    "gd": "GD",
    "fe": "FE",
    "fe_reserva": "FE_RESERVA",
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


def fecha_iso(valor):
    if not valor:
        return ""
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor).strip()


def fecha_ddmmyyyy(valor):
    if not valor:
        return ""
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def hora_hhmm(valor):
    if not valor:
        return ""
    if hasattr(valor, "strftime"):
        return valor.strftime("%H:%M")
    texto = str(valor).strip()
    return texto[:5] if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", texto) else texto


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


def obtener_peso_entrada_sap_despacho(citacion):
    dato = _dato_operacion(citacion, "OP_TICKET_PESAJE_ENT")
    metadata = parse_json_text(dato.DO_CVALOR if dato else "")
    return decimal_o_primero(
        metadata.get("peso_neto"),
        getattr(dato, "DO_NPESO", None) if dato else None,
    )


def _datos_semanticos_ticket_despacho(citacion, tipo_ticket):
    codigo = f"OP_TICKET_PESAJE_{tipo_ticket}"
    dato = _dato_operacion(citacion, codigo)
    if not dato:
        return {}, f"No existe ticket de pesaje {tipo_ticket} persistido."
    metadata = parse_json_text(dato.DO_CVALOR)
    tiene_semantica = (
        tipo_ticket == "ENT" and metadata.get("peso_entrada_kg") not in [None, ""]
    ) or (
        tipo_ticket == "SAL"
        and metadata.get("peso_neto_producto_kg") not in [None, ""]
        and metadata.get("fuente_peso_neto")
    )
    if tiene_semantica:
        return metadata, ""

    ruta_pdf = texto_o_primero(metadata.get("ruta_real_pdf"))
    if not ruta_pdf or not os.path.isfile(ruta_pdf):
        return {}, (
            f"El ticket {tipo_ticket} es histórico y no se puede reconstruir "
            "semánticamente porque su PDF no está disponible."
        )
    try:
        from .views import _extraer_datos_ticket_pesaje

        reconstruido = _extraer_datos_ticket_pesaje(
            ruta_pdf,
            tipo_ticket,
            semantica_despacho_sbh=True,
        )
    except (OSError, ValueError) as exc:
        return {}, f"No se pudo interpretar semánticamente el ticket {tipo_ticket}: {exc}"
    reconstruido["ruta_real_pdf"] = ruta_pdf
    reconstruido["reconstruido_desde_pdf"] = True
    return reconstruido, ""


def obtener_pesaje_real_despacho(citacion):
    entrada_ticket, error_entrada = _datos_semanticos_ticket_despacho(citacion, "ENT")
    salida_ticket, error_salida = _datos_semanticos_ticket_despacho(citacion, "SAL")
    errores = [error for error in (error_entrada, error_salida) if error]
    warnings = []

    entrada_registrada = decimal_or_none(entrada_ticket.get("peso_entrada_kg"))
    entrada_en_salida = decimal_or_none(salida_ticket.get("peso_entrada_kg"))
    entrada = entrada_en_salida if entrada_en_salida is not None else entrada_registrada
    salida_bruta = decimal_or_none(salida_ticket.get("peso_salida_bruto_kg"))
    neto_producto = decimal_or_none(salida_ticket.get("peso_neto_producto_kg"))
    fuente = texto_o_primero(salida_ticket.get("fuente_peso_neto"))

    if entrada_registrada is not None and entrada_en_salida is not None and entrada_registrada != entrada_en_salida:
        warnings.append(
            "Advertencia: las pesadas de los tickets ENT/SAL no coinciden entre si, "
            "pero el peso neto despachado fue calculado correctamente."
        )
    if entrada is None:
        errores.append("No se pudo determinar el peso de entrada con evidencia del ticket.")
    if neto_producto is None:
        errores.append("No se pudo determinar el peso neto de producto con evidencia del ticket.")
    if not fuente:
        errores.append("No se pudo determinar la fuente semántica del peso neto de producto.")

    neto_calculado = None
    diferencia = None
    control_disponible = entrada is not None and salida_bruta is not None
    if control_disponible:
        neto_calculado = salida_bruta - entrada
        if neto_calculado < 0:
            errores.append("El peso bruto de salida es menor al peso de entrada.")
        if neto_producto is not None:
            diferencia = neto_calculado - neto_producto
            if diferencia != 0:
                errores.append(
                    "El Peso Neto explícito no coincide con peso salida bruto - peso entrada."
                )

    if neto_producto is not None and neto_producto <= 0:
        errores.append("El peso neto de producto debe ser mayor que cero.")

    etiquetas_fuente = {
        "ticket_explicito": "Ticket — Peso Neto explícito",
        "calculado_desde_pesadas": "Calculado desde pesadas del ticket",
    }
    return {
        'warnings': warnings,
        "peso_entrada_kg": entrada,
        "peso_entrada_ticket_ent_kg": entrada_registrada,
        "peso_entrada_ticket_sal_kg": entrada_en_salida,
        "peso_salida_bruto_kg": salida_bruta,
        "peso_neto_producto_kg": neto_producto,
        "peso_neto_calculado_kg": neto_calculado,
        "diferencia_control_kg": diferencia,
        "fuente_peso_neto": fuente,
        "fuente_peso_neto_label": etiquetas_fuente.get(fuente, fuente),
        "control_disponible": control_disponible,
        "control_pesaje_ok": control_disponible and diferencia == 0,
        "cantidad_real_mt": (
            neto_producto / Decimal("1000")
            if neto_producto is not None
            else None
        ),
        "errors": errores,
    }


def calcular_peso_real_despachado(citacion):
    """Retorna entrada, salida bruta, neto de producto y neto MT."""
    pesaje = obtener_pesaje_real_despacho(citacion)
    return (
        pesaje["peso_entrada_kg"],
        pesaje["peso_salida_bruto_kg"],
        pesaje["peso_neto_producto_kg"],
        pesaje["cantidad_real_mt"],
    )


def distribuir_cantidad_secuencial(cantidades_originales, cantidad_real):
    """Conserva los primeros valores y deja el remanente en el ultimo usado."""
    originales = [decimal_or_none(valor) for valor in cantidades_originales]
    total = decimal_or_none(cantidad_real)
    if total is None or total < 0 or not originales or any(valor is None or valor < 0 for valor in originales):
        raise ValueError("No se puede distribuir una cantidad real u original invalida.")
    resultado = []
    remanente = total
    for indice, original in enumerate(originales):
        asignado = remanente if indice == len(originales) - 1 else min(original, remanente)
        resultado.append(asignado)
        remanente -= asignado
    if any(valor < 0 for valor in resultado) or sum(resultado, Decimal("0")) != total:
        raise ValueError("La distribucion final de cantidades no es consistente.")
    return resultado


def _validar_payload_patch_completo(payload_original, payload_final, cantidad_real):
    """Valida cantidades e identidades de la colección final antes del PATCH."""
    total = decimal_or_none(cantidad_real)
    lineas_originales = (payload_original or {}).get("DocumentLines") or []
    lineas_finales = (payload_final or {}).get("DocumentLines") or []
    if total is None or total < 0 or not lineas_originales:
        raise ValueError("No se puede validar el payload PATCH sin cantidad y lineas originales.")

    cantidades_linea = distribuir_cantidad_secuencial(
        [linea.get("Quantity") for linea in lineas_originales],
        total,
    )
    esperadas = [
        (linea, cantidad_linea)
        for linea, cantidad_linea in zip(lineas_originales, cantidades_linea)
        if cantidad_linea > 0
    ]
    if len(lineas_finales) != len(esperadas):
        raise ValueError(
            "La colección DocumentLines del PATCH no representa todas las lineas finales."
        )

    resumen_lineas = []
    suma_lineas = Decimal("0")
    suma_lotes_documento = Decimal("0")
    for indice, ((linea_original, cantidad_linea), linea_final) in enumerate(
        zip(esperadas, lineas_finales),
        start=1,
    ):
        for campo in ("ItemCode", "AgreementNo", "WarehouseCode"):
            if linea_final.get(campo) != linea_original.get(campo):
                raise ValueError(
                    f"DocumentLine {indice}: el PATCH no conserva {campo}."
                )
        cantidad_final_linea = decimal_or_none(linea_final.get("Quantity"))
        if cantidad_final_linea != cantidad_linea:
            raise ValueError(
                f"DocumentLine {indice}: Quantity no coincide con la distribución calculada."
            )

        lotes_originales = linea_original.get("BatchNumbers") or []
        if not lotes_originales:
            raise ValueError(f"DocumentLine {indice}: faltan lotes originales.")
        cantidades_lote = distribuir_cantidad_secuencial(
            [lote.get("Quantity") for lote in lotes_originales],
            cantidad_linea,
        )
        lotes_esperados = [
            (lote, cantidad_lote)
            for lote, cantidad_lote in zip(lotes_originales, cantidades_lote)
            if cantidad_lote > 0
        ]
        lotes_finales = linea_final.get("BatchNumbers") or []
        if len(lotes_finales) != len(lotes_esperados):
            raise ValueError(
                f"DocumentLine {indice}: la colección BatchNumbers no contiene todos los lotes finales."
            )

        cantidades_vistas = Decimal("0")
        nombres_vistos = set()
        lotes_resumen = []
        for (lote_original, cantidad_lote), lote_final in zip(
            lotes_esperados,
            lotes_finales,
        ):
            batch_original = str(lote_original.get("BatchNumber") or "").strip()
            batch_final = str(lote_final.get("BatchNumber") or "").strip()
            if not batch_original or batch_final != batch_original:
                raise ValueError(
                    f"DocumentLine {indice}: el PATCH no conserva BatchNumber."
                )
            if batch_final in nombres_vistos:
                raise ValueError(
                    f"DocumentLine {indice}: BatchNumber duplicado en el PATCH."
                )
            nombres_vistos.add(batch_final)
            cantidad_final_lote = decimal_or_none(lote_final.get("Quantity"))
            if cantidad_final_lote != cantidad_lote or cantidad_final_lote <= 0:
                raise ValueError(
                    f"DocumentLine {indice}: Quantity de lote inválida."
                )
            cantidades_vistas += cantidad_final_lote
            lotes_resumen.append({
                "batch_number": batch_final,
                "quantity": json_safe(cantidad_final_lote),
            })

        if cantidades_vistas != cantidad_final_linea:
            raise ValueError(
                "SUM(BatchNumbers.Quantity) no coincide con DocumentLine.Quantity."
            )
        suma_lineas += cantidad_final_linea
        suma_lotes_documento += cantidades_vistas
        resumen_lineas.append({
            "document_line": indice,
            "quantity": json_safe(cantidad_final_linea),
            "suma_lotes": json_safe(cantidades_vistas),
            "lotes": lotes_resumen,
            "validacion": "OK",
        })

    if suma_lineas != total:
        raise ValueError(
            "SUM(DocumentLines.Quantity) no coincide con la cantidad final del acuerdo."
        )
    return {
        "cantidad_total_documento": json_safe(total),
        "suma_lineas": json_safe(suma_lineas),
        "suma_lotes": json_safe(suma_lotes_documento),
        "coleccion_final_completa": True,
        "validacion": "OK",
        "lineas": resumen_lineas,
    }


def _distribuir_payload_draft(payload_original, cantidad_real):
    payload = deepcopy(payload_original or {})
    lineas = payload.get("DocumentLines") or []
    if not lineas:
        raise ValueError("Falta informacion de lineas en el Draft SAP.")
    cantidades_linea = distribuir_cantidad_secuencial([linea.get("Quantity") for linea in lineas], cantidad_real)
    for linea, cantidad_linea in zip(lineas, cantidades_linea):
        lotes = linea.get("BatchNumbers") or []
        if not lotes:
            raise ValueError("Falta informacion de lotes en el Draft SAP.")
        cantidades_lote = distribuir_cantidad_secuencial([lote.get("Quantity") for lote in lotes], cantidad_linea)
        linea["Quantity"] = json_safe(cantidad_linea)
        for lote, cantidad_lote in zip(lotes, cantidades_lote):
            lote["Quantity"] = json_safe(cantidad_lote)
        linea["BatchNumbers"] = [lote for lote in lotes if decimal_or_none(lote["Quantity"]) > 0]
        if sum((decimal_or_none(lote["Quantity"]) for lote in linea["BatchNumbers"]), Decimal("0")) != cantidad_linea:
            raise ValueError("SUM(BatchNumbers.Quantity) no coincide con DocumentLine.Quantity.")
    payload["DocumentLines"] = [linea for linea in lineas if decimal_or_none(linea["Quantity"]) > 0]
    if sum((decimal_or_none(linea["Quantity"]) for linea in payload["DocumentLines"]), Decimal("0")) != cantidad_real:
        raise ValueError("SUM(DocumentLines.Quantity) no coincide con la cantidad real del acuerdo.")
    _validar_payload_patch_completo(payload_original, payload, cantidad_real)
    return payload


def _auditoria_update_operacional(draft):
    respuesta = draft.respuesta if isinstance(draft.respuesta, dict) else {}
    auditoria = respuesta.get("actualizacion_peso_real")
    return auditoria if isinstance(auditoria, dict) else {}


def _validar_disponibilidad_lotes_guardada(citacion, documentos):
    """Bloquea si la cantidad final supera el stock snapshot de los lotes elegidos."""
    lotes = list(
        CITACION_DESPACHO_ACUERDO_LOTE.objects
        .select_related("estanque__acuerdo")
        .filter(estanque__acuerdo__carga__CI_NID=citacion)
    )
    stock_por_clave = {}
    for lote in lotes:
        clave = (
            str(lote.estanque.item_code),
            str(lote.estanque.warehouse_code),
            str(lote.batch_number),
        )
        stock_por_clave[clave] = max(
            stock_por_clave.get(clave, Decimal("0")),
            decimal_or_none(lote.stock_snapshot) or Decimal("0"),
        )
    solicitadas = {}
    for documento in documentos or []:
        for linea in (documento.get('payload') or {}).get('DocumentLines') or []:
            for lote in linea.get('BatchNumbers') or []:
                clave = (
                    str(linea.get("ItemCode") or ""),
                    str(linea.get("WarehouseCode") or ""),
                    str(lote.get("BatchNumber") or ""),
                )
                solicitadas[clave] = solicitadas.get(clave, Decimal("0")) + (
                    decimal_or_none(lote.get("Quantity")) or Decimal("0")
                )
    for clave, cantidad in solicitadas.items():
        if cantidad > stock_por_clave.get(clave, Decimal("0")):
            raise ValueError(
                "No existe disponibilidad suficiente en los lotes SAP para cubrir la cantidad real despachada."
            )


def construir_preview_update_drafts_operacionales(citacion):
    pesaje = obtener_pesaje_real_despacho(citacion)
    warnings = list(pesaje.get('warnings') or [])
    errors = list(pesaje["errors"])
    entrada = pesaje["peso_entrada_kg"]
    salida = pesaje["peso_salida_bruto_kg"]
    neto_kg = pesaje["peso_neto_producto_kg"]
    neto_mt = pesaje["cantidad_real_mt"]

    carga = (
        CITACION_DESPACHO_CARGA.objects
        .prefetch_related("acuerdos__draft")
        .filter(CI_NID=citacion)
        .first()
    )
    acuerdos = list(carga.acuerdos.all()) if carga else []
    if not acuerdos:
        errors.append("No existe distribucion operacional de acuerdos para actualizar SAP.")

    drafts = []
    productos = set()
    for acuerdo in acuerdos:
        try:
            draft = acuerdo.draft
        except CITACION_DESPACHO_DRAFT_SAP.DoesNotExist:
            draft = None
        if not draft or not str(draft.docentry or "").strip() or draft.estado not in {"CREADO", "ACTUALIZADO"}:
            errors.append(f"No existe Draft SAP creado para el acuerdo {acuerdo.numero_acuerdo}.")
            continue
        if entero_o_none(draft.docentry) is None:
            errors.append(f"DocEntry invalido para el acuerdo {acuerdo.numero_acuerdo}.")
            continue
        lineas = (draft.payload or {}).get("DocumentLines") or []
        productos.update(str(linea.get("ItemCode") or "").strip() for linea in lineas if linea.get("ItemCode"))
        drafts.append((acuerdo, draft))
    if len(productos) > 1:
        errors.append("No existe regla de negocio para distribuir el pesaje entre productos distintos.")

    documentos = []
    if not errors and neto_mt is not None:
        cantidades_acuerdo = distribuir_cantidad_secuencial(
            [acuerdo.cantidad for acuerdo, _ in drafts], neto_mt
        )
        for (acuerdo, draft), cantidad_acuerdo in zip(drafts, cantidades_acuerdo):
            try:
                payload_final = _distribuir_payload_draft(draft.payload, cantidad_acuerdo)
                validacion_patch = _validar_payload_patch_completo(
                    draft.payload,
                    payload_final,
                    cantidad_acuerdo,
                )
            except ValueError as exc:
                errors.append(f"Acuerdo {acuerdo.numero_acuerdo}: {exc}")
                continue
            documentos.append({
                "acuerdo_id": acuerdo.id,
                "sap_abs_id": acuerdo.sap_abs_id,
                "numero_acuerdo": acuerdo.numero_acuerdo,
                "docentry": entero_o_none(draft.docentry),
                "docnum": draft.docnum,
                "cantidad_original": json_safe(acuerdo.cantidad),
                "cantidad_final": json_safe(cantidad_acuerdo),
                "payload_original": deepcopy(draft.payload),
                "payload": payload_final,
                "validacion_patch": validacion_patch,
                "actualizado": bool(_auditoria_update_operacional(draft).get("success")),
            })

    total_planificado = sum((acuerdo.cantidad for acuerdo in acuerdos), Decimal("0"))
    if documentos:
        total_final = sum((decimal_or_none(item["cantidad_final"]) for item in documentos), Decimal("0"))
        if total_final != neto_mt:
            errors.append("La suma final de documentos SAP no coincide con el peso real despachado.")
        else:
            try:
                _validar_disponibilidad_lotes_guardada(citacion, documentos)
            except ValueError as exc:
                errors.append(str(exc))
    return {
        "warnings": warnings,
        "aplicable": bool(carga),
        "errors": errors,
        "source_data": {
            "peso_entrada_kg": json_safe(entrada),
            "peso_salida_kg": json_safe(salida),
            "peso_salida_bruto_kg": json_safe(salida),
            "peso_real_kg": json_safe(neto_kg),
            "peso_neto_producto_kg": json_safe(neto_kg),
            "peso_neto_calculado_kg": json_safe(pesaje["peso_neto_calculado_kg"]),
            "diferencia_control_kg": json_safe(pesaje["diferencia_control_kg"]),
            "fuente_peso_neto": pesaje["fuente_peso_neto"],
            "fuente_peso_neto_label": pesaje["fuente_peso_neto_label"],
            "control_disponible": pesaje["control_disponible"],
            "control_pesaje_ok": pesaje["control_pesaje_ok"],
            "cantidad_real_mt": json_safe(neto_mt),
            "cantidad_planificada_mt": json_safe(total_planificado),
            "diferencia_mt": json_safe(neto_mt - total_planificado) if neto_mt is not None else None,
            "formula": "peso_neto_producto_kg",
        },
        "documentos": documentos,
    }


def _resumen_lineas_preview(payload):
    resumen = []
    for indice, linea in enumerate((payload or {}).get("DocumentLines") or [], start=1):
        cantidad_linea = decimal_or_none(linea.get("Quantity"))
        lotes = deepcopy(linea.get("BatchNumbers") or [])
        suma_lotes = sum(
            (decimal_or_none(lote.get("Quantity")) or Decimal("0") for lote in lotes),
            Decimal("0"),
        )
        resumen.append({
            "document_line": indice,
            "item_code": linea.get("ItemCode"),
            "warehouse_code": linea.get("WarehouseCode"),
            "agreement_no": linea.get("AgreementNo"),
            "quantity": json_safe(cantidad_linea),
            "batch_numbers": lotes,
            "suma_lotes": json_safe(suma_lotes),
            "suma_lotes_igual_linea": cantidad_linea is not None and suma_lotes == cantidad_linea,
        })
    return resumen


def _sanitizar_datos_preview(valor):
    claves_sensibles = {
        "authorization", "cookie", "cookies", "password", "routeid",
        "b1session", "sap_password", "sap_user", "sap_username", "sessionid",
        "set-cookie", "token", "username",
    }
    if isinstance(valor, dict):
        return {
            clave: "[OCULTO]" if str(clave).lower() in claves_sensibles else _sanitizar_datos_preview(item)
            for clave, item in valor.items()
        }
    if isinstance(valor, list):
        return [_sanitizar_datos_preview(item) for item in valor]
    return json_safe(valor)


def construir_diagnostico_preview_update_drafts_operacionales(citacion):
    """Construye el diagnostico del PATCH operacional sin abrir sesion ni escribir en SAP/DB."""
    preview_real = construir_preview_update_drafts_operacionales(citacion)
    warnings = list(preview_real.get("warnings") or [])
    source = preview_real.get("source_data") or {}
    carga = (
        CITACION_DESPACHO_CARGA.objects
        .prefetch_related("acuerdos__draft")
        .filter(CI_NID=citacion)
        .first()
    )
    acuerdos = list(carga.acuerdos.all()) if carga else []
    finales_por_acuerdo = {
        item["acuerdo_id"]: item for item in preview_real.get("documentos") or []
    }
    documentos = []
    productos = set()
    docentries = []

    for acuerdo in acuerdos:
        try:
            draft = acuerdo.draft
        except CITACION_DESPACHO_DRAFT_SAP.DoesNotExist:
            draft = None
        original = deepcopy(draft.payload) if draft and isinstance(draft.payload, dict) else {}
        for linea in original.get("DocumentLines") or []:
            if linea.get("ItemCode"):
                productos.add(str(linea["ItemCode"]).strip())
        final_real = finales_por_acuerdo.get(acuerdo.id)
        payload_patch = deepcopy(final_real["payload"]) if final_real else None
        distribucion_final = _resumen_lineas_preview(payload_patch) if payload_patch else []
        suma_lineas = sum(
            (decimal_or_none(linea.get("Quantity")) or Decimal("0") for linea in (payload_patch or {}).get("DocumentLines") or []),
            Decimal("0"),
        )
        cantidad_final = decimal_or_none(final_real.get("cantidad_final")) if final_real else None
        docentry = entero_o_none(draft.docentry) if draft else None
        if docentry is not None:
            docentries.append(docentry)
        lotes_validos = bool(distribucion_final) and all(
            linea["suma_lotes_igual_linea"] for linea in distribucion_final
        )
        lineas_validas = cantidad_final is not None and suma_lineas == cantidad_final
        suma_lotes = sum(
            (
                decimal_or_none(linea.get("suma_lotes")) or Decimal("0")
                for linea in distribucion_final
            ),
            Decimal("0"),
        )
        validacion_patch = deepcopy(
            (final_real or {}).get("validacion_patch") or {}
        )
        documentos.append({
            "acuerdo": {
                "id": acuerdo.id,
                "numero_visible": acuerdo.numero_acuerdo,
                "sap_abs_id": acuerdo.sap_abs_id,
            },
            "draft": {
                "encontrado": draft is not None,
                "docentry": docentry,
                "docnum": draft.docnum if draft else None,
                "estado": draft.estado if draft else None,
            },
            "pesajes": deepcopy(source),
            "cantidad_operacional": {
                "original_mt": json_safe(acuerdo.cantidad),
                "final_mt": json_safe(cantidad_final),
            },
            "endpoint": f"PATCH /Drafts({docentry})" if docentry is not None else None,
            "headers": {"B1S-ReplaceCollectionsOnPatch": "true"},
            "payload_original": original,
            "distribucion_original": _resumen_lineas_preview(original),
            "distribucion_final": distribucion_final,
            "payload_patch": payload_patch,
            "validacion": {
                "suma_lotes_igual_linea": lotes_validos,
                "suma_lotes": json_safe(suma_lotes),
                "suma_lineas": json_safe(suma_lineas),
                "suma_lineas_igual_acuerdo": lineas_validas,
                "coleccion_final_completa": bool(
                    validacion_patch.get("coleccion_final_completa")
                ),
                "resultado": (
                    "OK"
                    if lotes_validos
                    and lineas_validas
                    and validacion_patch.get("coleccion_final_completa")
                    else "INVÁLIDO"
                ),
            },
            "ultima_actualizacion_registrada": _sanitizar_datos_preview(
                _auditoria_update_operacional(draft) if draft else {}
            ),
        })

    validacion = {
        "draft_encontrado": bool(documentos) and all(item["draft"]["encontrado"] for item in documentos),
        "docentry_valido": bool(documentos) and all(item["draft"]["docentry"] is not None for item in documentos),
        "pesaje_entrada_disponible": source.get("peso_entrada_kg") is not None,
        "pesaje_salida_bruto_disponible": source.get("peso_salida_bruto_kg") is not None,
        "peso_neto_producto_disponible": source.get("peso_neto_producto_kg") is not None,
        "fuente_peso_neto_identificada": bool(source.get("fuente_peso_neto")),
        "control_pesaje_ok": (
            not source.get("control_disponible")
            or bool(source.get("control_pesaje_ok"))
        ),
        "peso_real_positivo": (decimal_or_none(source.get("peso_real_kg")) or Decimal("0")) > 0,
        "suma_lotes_igual_linea": bool(documentos) and all(item["validacion"]["suma_lotes_igual_linea"] for item in documentos),
        "suma_lineas_igual_acuerdo": bool(documentos) and all(item["validacion"]["suma_lineas_igual_acuerdo"] for item in documentos),
        "coleccion_final_completa": bool(documentos) and all(item["validacion"]["coleccion_final_completa"] for item in documentos),
        "acuerdos_separados_correctamente": bool(documentos) and len(docentries) == len(documentos) == len(set(docentries)),
        "productos_compatibles_multiacuerdo": len(productos) <= 1,
    }
    motivos = list(preview_real.get("errors") or [])
    for clave, correcto in validacion.items():
        if not correcto:
            motivos.append(f"Validacion fallida: {clave.replace('_', ' ')}.")
    return json_safe({
        "warnings": warnings,
        "success": not motivos,
        "resultado": (
            "PREVIEW V\u00c1LIDO CON ADVERTENCIAS"
            if not motivos and warnings
            else ("PREVIEW V\u00c1LIDO" if not motivos else "PREVIEW INV\u00c1LIDO")
        ),
        "citacion": citacion.pk,
        "documentos": documentos,
        "validacion_estructural": validacion,
        "motivos": motivos,
    })

def _get_sap_despacho_update_status_operacional(citacion):
    preview = construir_preview_update_drafts_operacionales(citacion)
    drafts = list(
        CITACION_DESPACHO_DRAFT_SAP.objects
        .filter(acuerdo__carga__CI_NID=citacion)
        .select_related("acuerdo")
        .order_by("acuerdo__orden", "acuerdo_id")
    )
    auditorias = [_auditoria_update_operacional(draft) for draft in drafts]
    updated = bool(drafts) and all(auditoria.get("success") for auditoria in auditorias)
    is_error = any(auditoria and not auditoria.get("success") for auditoria in auditorias)
    estado = SAP_DESPACHO_UPDATE_ESTADO_ACTUALIZADO if updated else (
        SAP_DESPACHO_UPDATE_ESTADO_ERROR if is_error else SAP_DESPACHO_UPDATE_ESTADO_PENDIENTE
    )
    source = preview.get("source_data") or {}
    request_json = {"Drafts": [item["payload"] for item in preview.get("documentos") or []]}
    response_json = {"Drafts": [auditoria.get("response") or {} for auditoria in auditorias if auditoria]}
    ultimo = drafts[-1] if drafts else None
    usuario = next((str(a.get("usuario") or "") for a in reversed(auditorias) if a.get("usuario")), "")
    return {
        "updated": updated,
        "is_error": is_error,
        "estado": estado,
        "label": "Documentos SAP actualizados" if updated else ("Error al actualizar SAP" if is_error else "Pendiente de actualizar SAP"),
        "result_label": "OK" if updated else ("ERROR" if is_error else "PENDIENTE"),
        "css_estado": "ok" if updated else ("error" if is_error else "pending"),
        "resumen_mensaje": (
            "Drafts SAP actualizados con la cantidad fisicamente despachada."
            if updated else "Debe actualizar los documentos SAP con el peso real antes de autorizar la salida."
        ),
        "error_message": next((draft.error for draft in drafts if draft.error), ""),
        "docentry": drafts[0].docentry if len(drafts) == 1 else "",
        "docnum": drafts[0].docnum if len(drafts) == 1 else "",
        "peso_entrada": source.get("peso_entrada_kg"),
        "peso_salida": source.get("peso_salida_kg"),
        "peso_real_kg": source.get("peso_real_kg"),
        "cantidad_real_mt": source.get("cantidad_real_mt"),
        "cantidad_planificada_mt": source.get("cantidad_planificada_mt"),
        "diferencia_mt": source.get("diferencia_mt"),
        "distribucion": preview.get("documentos") or [],
        "preview_errors": preview.get("errors") or [],
        "request_json": request_json,
        "response_json": response_json,
        "request_json_pretty": json_pretty(request_json),
        "response_json_pretty": json_pretty(response_json),
        "fecha_hora": timezone.localtime(ultimo.actualizado).strftime("%d/%m/%Y %H:%M") if ultimo else "",
        "usuario": usuario,
    }


def actualizar_borradores_sap_despacho_operacionales(
    citacion,
    usuario,
    allow_retry=False,
    client_factory=SapServiceLayerClient,
    revalidar_disponibilidad=False,
):
    preview = construir_preview_update_drafts_operacionales(citacion)
    if preview.get("errors") or not preview.get("documentos"):
        return {
            "success": False,
            "message": (preview.get("errors") or ["Faltan datos para actualizar SAP."])[0],
            "preview": preview,
            "status": _get_sap_despacho_update_status_operacional(citacion),
        }
    if all(item.get("actualizado") for item in preview["documentos"]) and not allow_retry:
        return {"success": True, "message": "Documentos SAP ya actualizados.", "preview": preview,
                "status": _get_sap_despacho_update_status_operacional(citacion)}

    try:
        for item in preview["documentos"]:
            _validar_payload_patch_completo(
                item["payload_original"],
                item["payload"],
                decimal_or_none(item["cantidad_final"]),
            )
    except ValueError as exc:
        return {
            "success": False,
            "message": f"PATCH SAP bloqueado por validación estructural: {exc}",
            "preview": preview,
            "status": _get_sap_despacho_update_status_operacional(citacion),
        }
    if revalidar_disponibilidad:
        from .despacho_carga import CargaInvalida
        from .sap_despacho_envio import validar_disponibilidad_final_despacho

        carga = CITACION_DESPACHO_CARGA.objects.filter(CI_NID=citacion).first()
        try:
            preview["disponibilidad_lotes"] = validar_disponibilidad_final_despacho(
                citacion,
                carga,
                preview["documentos"],
            )
        except CargaInvalida as exc:
            preview["errors"].append(str(exc))
            return {
                "success": False,
                "message": str(exc),
                "preview": preview,
                "status": _get_sap_despacho_update_status_operacional(citacion),
            }

    client = client_factory(load_config(citacion.EP_NID_id, for_write=True))
    resultados = []
    try:
        client.login()
        for item in preview["documentos"]:
            draft = CITACION_DESPACHO_DRAFT_SAP.objects.get(acuerdo_id=item["acuerdo_id"])
            if item.get("actualizado") and not allow_retry:
                resultados.append({"docentry": draft.docentry, "reutilizado": True})
                continue
            try:
                response = client.patch_draft(item["docentry"], item["payload"], replace_collections=True)
                data = response.get("data") or {"status_code": response.get("status_code")}
                respuesta = deepcopy(draft.respuesta) if isinstance(draft.respuesta, dict) else {}
                if respuesta and "creacion" not in respuesta and "actualizacion_peso_real" not in respuesta:
                    respuesta = {"creacion": respuesta}
                respuesta["actualizacion_peso_real"] = {
                    "success": True, "request": item["payload"], "response": data,
                    "peso_entrada_kg": preview["source_data"]["peso_entrada_kg"],
                    "peso_salida_kg": preview["source_data"]["peso_salida_kg"],
                    "peso_real_kg": preview["source_data"]["peso_real_kg"],
                    "cantidad_final_mt": item["cantidad_final"],
                    "usuario": getattr(usuario, "username", ""), "fecha_iso": timezone.now().isoformat(),
                }
                draft.respuesta = respuesta
                draft.error = ""
                draft.save(update_fields=["respuesta", "error", "actualizado"])
                resultados.append({"docentry": draft.docentry, "reutilizado": False})
            except Exception as exc:
                respuesta = deepcopy(draft.respuesta) if isinstance(draft.respuesta, dict) else {}
                if respuesta and "creacion" not in respuesta and "actualizacion_peso_real" not in respuesta:
                    respuesta = {"creacion": respuesta}
                respuesta["actualizacion_peso_real"] = {
                    "success": False, "request": item["payload"], "response": _extract_sap_error(exc),
                    "usuario": getattr(usuario, "username", ""), "fecha_iso": timezone.now().isoformat(),
                }
                draft.respuesta = respuesta
                draft.error = _sap_error_short_message(respuesta["actualizacion_peso_real"]["response"]) or str(exc)
                draft.save(update_fields=["respuesta", "error", "actualizado"])
                return {"success": False, "message": f"No fue posible actualizar el Draft SAP {draft.docentry}.",
                        "preview": preview, "resultados": resultados,
                        "status": _get_sap_despacho_update_status_operacional(citacion)}
    finally:
        client.logout()
    mensaje = "Documentos SAP actualizados con el peso real despachado."
    if preview.get("warnings"):
        mensaje = f"{mensaje} {' '.join(preview['warnings'])}"
    return {"success": True, "message": mensaje, "warnings": preview.get("warnings") or [],
            "preview": preview, "resultados": resultados,
            "status": _get_sap_despacho_update_status_operacional(citacion)}


def get_sap_despacho_update_status(citacion):
    if CITACION_DESPACHO_CARGA.objects.filter(CI_NID=citacion).exists():
        return _get_sap_despacho_update_status_operacional(citacion)
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
    tipo_documento_camion = texto_o_primero(
        getattr(camion_patio, 'CPA_CTIPO_DOCUMENTO', '') if camion_patio else ''
    ).upper()
    es_despacho_sbh = (
        citacion.EP_NID_id == 2
        and str(getattr(citacion, 'CI_CTIPO', '') or '').upper() == 'DESPACHO'
    )
    tipo_documento_planificado = texto_o_primero(
        detalle_resumen.get('salida_documento') if es_despacho_sbh else ''
    ).upper()
    tipo_documento = (
        tipo_documento_planificado
        if tipo_documento_planificado in {'GD', 'FE', 'FE_RESERVA'}
        else tipo_documento_camion
    )
    doc_object_code = _draft_object_code()
    reserve_invoice = None
    if es_despacho_sbh:
        if tipo_documento == 'GD':
            doc_object_code = '15'
        elif tipo_documento == 'FE':
            doc_object_code, reserve_invoice = '13', 'tNO'
        elif tipo_documento == 'FE_RESERVA':
            doc_object_code, reserve_invoice = '13', 'tYES'
    numero_documento = (
        ''
        if es_despacho_sbh
        else texto_o_primero(getattr(camion_patio, 'CPA_CNUMERO_GUIA', '') if camion_patio else '')
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
    quantity = (
        decimal_o_primero(getattr(detalle, "CDD_NCANTIDAD_INTENTADA_DESPACHAR", None) if detalle else None)
        if es_despacho_sbh
        else decimal_o_primero(
            _dato_valor(citacion, "ACD_PESO_INFORMADO"),
            getattr(detalle, "CDD_NPESO_INFORMADO", None) if detalle else None,
        )
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
        "doc_object_code": doc_object_code if es_despacho_sbh else _draft_object_code(),
        "card_code": card_code,
        "tipo_documento": tipo_documento,
        **({
            **({"reserve_invoice": reserve_invoice} if doc_object_code == '13' else {}),
            "quantity_source": "CDD_NCANTIDAD_INTENTADA_DESPACHAR",
        } if es_despacho_sbh else {
            "numero_documento": numero_documento,
            "folio_number": folio_number,
        }),
        "item_code": item_code,
        "agreement_no": agreement_no,
        "sap_abs_id": sap_abs_id,
        "sap_numero_acuerdo": sap_numero_acuerdo,
        "warehouse_code": warehouse_code,
        "quantity": json_safe(quantity),
        "batch_number": batch_number,
        "doc_date": doc_date,
    }

    tipos_documento_validos = {'GD', 'FE', 'FE_RESERVA'} if es_despacho_sbh else set(dict(CAMION_PATIO.TIPOS_DOCUMENTO))
    if tipo_documento not in tipos_documento_validos:
        errors.append('No se puede crear borrador SAP: falta un tipo de documento valido (GD, FE o FE_RESERVA).' if es_despacho_sbh else 'No se puede crear borrador SAP: falta un tipo de documento valido (GD o FE).')
    if not es_despacho_sbh:
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
            "DocObjectCode": doc_object_code if es_despacho_sbh else _draft_object_code(),
            "CardCode": card_code,
            **({} if es_despacho_sbh else {
                "FolioPrefixString": tipo_documento,
                "FolioNumber": folio_number,
            }),
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
        if es_despacho_sbh and doc_object_code == '13':
            payload["ReserveInvoice"] = reserve_invoice

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
    es_despacho_sbh = (
        citacion.EP_NID_id == 2
        and str(getattr(citacion, 'CI_CTIPO', '') or '').upper() == 'DESPACHO'
    )
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
        if es_despacho_sbh:
            payload.pop("FolioPrefixString", None)
            payload.pop("FolioNumber", None)
            doc_object_code = draft_preview.get("payload", {}).get("DocObjectCode")
            payload["DocObjectCode"] = doc_object_code
            if doc_object_code == "13":
                payload["ReserveInvoice"] = draft_preview["payload"]["ReserveInvoice"]
            else:
                payload.pop("ReserveInvoice", None)
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
    # Ningún endpoint antiguo puede enviar solo la primera asignación de la carga nueva.
    from .despacho_carga import usa_carga_operacional, MENSAJE_PREPARADO
    if usa_carga_operacional(citacion):
        return {'success': False, 'message': MENSAJE_PREPARADO, 'status': {}}
    existing_status = get_sap_despacho_draft_status(citacion)

    if existing_status.get("created") and not allow_duplicate:
        docentry = existing_status.get("docentry") or ""
        docnum = existing_status.get("docnum") or ""

        return {
            "success": False,
            "message": (
                f"La citacion ya tiene un borrador SAP creado. "
                f"DocEntry: {docentry} DocNum: {docnum}"
            ),
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

    config = load_config(citacion.EP_NID_id, for_write=True)
    client = SapServiceLayerClient(config)

    status_code = None
    response_payload = {}
    sap_phase = "LOGIN"

    try:
        print(
            f"\n[Borrador SAP][Despacho] "
            f"citacion={citacion.id} "
            f"empresa={citacion.EP_NID_id} "
            f"CompanyDB={config.company_db} "
            f"endpoint=/Drafts"
        )

        print(
            json.dumps(
                preview["payload"],
                indent=2,
                ensure_ascii=False
            )
        )

        client.login()

        sap_phase = "DRAFT"

        sap_response = client.post_draft(
            preview["payload"]
        )

        status_code = sap_response.get("status_code")
        response_payload = sap_response.get("data") or {}

    except HTTPError as exc:
        error_data = _extract_sap_error(exc)

        response = getattr(
            exc,
            "response",
            None
        )

        sap_data = error_data.get("data")

        sap_error = (
            sap_data.get("error")
            if isinstance(sap_data, dict)
            else None
        )

        sap_code = ""
        sap_message = ""

        # --------------------------------------------------
        # EXTRAER CÓDIGO Y MENSAJE SAP
        # --------------------------------------------------

        if isinstance(sap_error, dict):
            sap_code = sap_error.get(
                "code",
                ""
            )

            message = sap_error.get(
                "message"
            )

            if isinstance(message, dict):
                sap_message = texto_o_primero(
                    message.get("value"),
                    message.get("message"),
                    message.get("description"),
                )

                if not sap_message:
                    sap_message = json.dumps(
                        message,
                        ensure_ascii=False
                    )

            elif message is not None:
                sap_message = str(message)

        elif sap_error is not None:
            sap_message = str(
                sap_error
            )

        # --------------------------------------------------
        # FALLBACK PARA OTROS FORMATOS DE SAP
        # --------------------------------------------------

        if isinstance(sap_data, dict):
            sap_code = sap_code or texto_o_primero(
                sap_data.get("code"),
                sap_data.get("Code")
            )

            sap_message = sap_message or texto_o_primero(
                sap_data.get("message"),
                sap_data.get("Message"),
                sap_data.get("description"),
            )

        elif sap_data is not None:
            sap_message = str(
                sap_data
            )

        # --------------------------------------------------
        # RESPUESTA RAW SAP
        # --------------------------------------------------

        raw_response = (
            getattr(response, "text", "")
            if response is not None
            else ""
        )

        endpoint = (
            "/Drafts"
            if sap_phase == "DRAFT"
            else "/Login"
        )

        error_header = (
            "[SAP ERROR][DESPACHO]"
            if sap_phase == "DRAFT"
            else "[SAP ERROR][DESPACHO][LOGIN]"
        )

        # --------------------------------------------------
        # TRADUCCIONES SOLO PARA CONSOLA
        # --------------------------------------------------

        mensajes_sap_es = {
            "-4002": (
                "Para generar este documento, primero defina "
                "la serie de numeración en el módulo Administración."
            ),
        }

        mensaje_original = (
            sap_message
            or str(exc)
        )

        mensaje_sap_es = mensajes_sap_es.get(
            str(sap_code),
            mensaje_original
        )

        # --------------------------------------------------
        # LOG DIAGNÓSTICO CONSOLA
        # --------------------------------------------------

        print("\n" + "=" * 60)

        print(
            error_header
        )

        print(
            f"Citación: {citacion.id}"
        )

        print(
            f"Empresa: {citacion.EP_NID_id}"
        )

        print(
            f"CompanyDB: {config.company_db}"
        )

        print(
            f"Endpoint: {endpoint}"
        )

        print(
            f"HTTP SAP: {error_data.get('status_code')}"
        )

        print(
            f"Código SAP: {sap_code}"
        )

        print(
            f"Mensaje SAP original: {mensaje_original}"
        )

        print(
            f"Mensaje SAP ES: {mensaje_sap_es}"
        )

        print(
            f"Respuesta SAP Raw: {raw_response}"
        )

        print(
            "=" * 60
        )

        # --------------------------------------------------
        # REGISTRAR ERROR
        # --------------------------------------------------

        _registrar_log_borrador_sap_despacho(
            citacion,
            usuario,
            success=False,
            payload=preview["payload"],
            status_code=error_data.get(
                "status_code"
            ),
            sap_error=error_data,
        )

        # --------------------------------------------------
        # RESPUESTA ACTUAL
        # NO SE MODIFICA COMPORTAMIENTO FRONTEND
        # --------------------------------------------------

        return {
            "success": False,
            "message": (
                "SAP rechazo la creacion "
                "del borrador de despacho."
            ),
            "status_code": error_data.get(
                "status_code"
            ),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_draft_status(
                citacion
            ),
        }

    except SapServiceLayerProbeError as exc:
        error_data = {
            "error": str(exc)
        }

        root_exc = exc

        while getattr(
            root_exc,
            "__cause__",
            None
        ) is not None:
            root_exc = root_exc.__cause__

        root_type = type(
            root_exc
        ).__name__

        error_text = str(
            exc
        ).lower()

        if (
            "timeout" in error_text
            or "timeout" in root_type.lower()
        ):
            error_category = "TIMEOUT"

        elif (
            "ssl" in error_text
            or "ssl" in root_type.lower()
        ):
            error_category = "SSL"

        elif (
            "conex" in error_text
            or "connection" in root_type.lower()
        ):
            error_category = "CONNECTION"

        elif "json" in error_text:
            error_category = "NON_JSON"

        elif sap_phase == "LOGIN":
            error_category = "LOGIN"

        else:
            error_category = "SERVICE_LAYER"

        endpoint = (
            "/Drafts"
            if sap_phase == "DRAFT"
            else "/Login"
        )

        print("\n" + "=" * 60)

        print(
            f"[SAP ERROR][DESPACHO]"
            f"[{error_category}]"
        )

        print(
            f"Citación: {citacion.id}"
        )

        print(
            f"Empresa: {citacion.EP_NID_id}"
        )

        print(
            f"CompanyDB: {config.company_db}"
        )

        print(
            f"Endpoint: {endpoint}"
        )

        print(
            f"Tipo: {root_type}"
        )

        print(
            f"Detalle: {exc}"
        )

        print(
            "=" * 60
        )

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
            "status": get_sap_despacho_draft_status(
                citacion
            ),
        }

    finally:
        client.logout()

    # ------------------------------------------------------
    # BORRADOR CREADO CORRECTAMENTE
    # ------------------------------------------------------

    guardar_respuesta_borrador_sap_despacho(
        citacion,
        usuario,
        preview["payload"],
        response_payload
    )

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
        "status": get_sap_despacho_draft_status(
            citacion
        ),
    }

def actualizar_borrador_sap_despacho(
    citacion,
    usuario,
    allow_retry=False,
    revalidar_disponibilidad=False,
):
    if CITACION_DESPACHO_CARGA.objects.filter(CI_NID=citacion).exists():
        return actualizar_borradores_sap_despacho_operacionales(
            citacion,
            usuario,
            allow_retry=allow_retry,
            revalidar_disponibilidad=revalidar_disponibilidad,
        )
    existing_status = get_sap_despacho_update_status(citacion)

    if existing_status.get("updated") and not allow_retry:
        return {
            "success": True,
            "message": "Documento SAP actualizado.",
            "status": existing_status,
        }

    preview = construir_payload_update_draft_despacho(citacion)

    docentry = preview.get(
        "source_data",
        {}
    ).get("draft_docentry")

    peso_salida = decimal_or_none(
        preview.get(
            "source_data",
            {}
        ).get("peso_salida")
    )

    if preview.get("errors") or not preview.get("payload"):
        message = (
            preview["errors"][0]
            if preview.get("errors")
            else "Faltan datos obligatorios para actualizar SAP."
        )

        return {
            "success": False,
            "message": message,
            "preview": preview,
            "status": existing_status,
        }

    config = load_config(
        citacion.EP_NID_id,
        for_write=True
    )

    client = SapServiceLayerClient(config)

    status_code = None
    response_payload = {}
    sap_phase = "LOGIN"

    try:
        print(
            f"\n[Update SAP][Despacho] "
            f"citacion={citacion.id} "
            f"empresa={citacion.EP_NID_id} "
            f"CompanyDB={config.company_db} "
            f"endpoint=/Drafts({docentry})"
        )

        print(
            json.dumps(
                preview["payload"],
                indent=2,
                ensure_ascii=False
            )
        )

        client.login()

        sap_phase = "UPDATE_DRAFT"

        sap_response = client.patch_draft(
            docentry,
            preview["payload"]
        )

        status_code = sap_response.get(
            "status_code"
        )

        response_payload = (
            sap_response.get("data")
            or {
                "status_code": status_code,
                "message": (
                    "Service Layer respondio sin cuerpo."
                ),
            }
        )

    except HTTPError as exc:
        error_data = _extract_sap_error(exc)

        response = getattr(
            exc,
            "response",
            None
        )

        sap_data = error_data.get(
            "data"
        )

        sap_error = (
            sap_data.get("error")
            if isinstance(sap_data, dict)
            else None
        )

        sap_code = ""
        sap_message = ""

        # --------------------------------------------------
        # EXTRAER CÓDIGO Y MENSAJE SAP
        # --------------------------------------------------

        if isinstance(sap_error, dict):
            sap_code = sap_error.get(
                "code",
                ""
            )

            message = sap_error.get(
                "message"
            )

            if isinstance(message, dict):
                sap_message = texto_o_primero(
                    message.get("value"),
                    message.get("message"),
                    message.get("description"),
                )

                if not sap_message:
                    sap_message = json.dumps(
                        message,
                        ensure_ascii=False
                    )

            elif message is not None:
                sap_message = str(
                    message
                )

        elif sap_error is not None:
            sap_message = str(
                sap_error
            )

        # --------------------------------------------------
        # FALLBACK PARA OTROS FORMATOS SAP
        # --------------------------------------------------

        if isinstance(sap_data, dict):
            sap_code = (
                sap_code
                or texto_o_primero(
                    sap_data.get("code"),
                    sap_data.get("Code")
                )
            )

            sap_message = (
                sap_message
                or texto_o_primero(
                    sap_data.get("message"),
                    sap_data.get("Message"),
                    sap_data.get("description"),
                )
            )

        elif sap_data is not None:
            sap_message = str(
                sap_data
            )

        raw_response = (
            getattr(
                response,
                "text",
                ""
            )
            if response is not None
            else ""
        )

        endpoint = (
            f"/Drafts({docentry})"
            if sap_phase == "UPDATE_DRAFT"
            else "/Login"
        )

        error_header = (
            "[SAP ERROR][UPDATE DESPACHO]"
            if sap_phase == "UPDATE_DRAFT"
            else "[SAP ERROR][UPDATE DESPACHO][LOGIN]"
        )

        # --------------------------------------------------
        # TRADUCCIONES SOLO PARA CONSOLA
        # --------------------------------------------------

        mensajes_sap_es = {
            "-4002": (
                "Para generar este documento, primero defina "
                "la serie de numeración en el módulo Administración."
            ),
        }

        mensaje_original = (
            sap_message
            or str(exc)
        )

        mensaje_sap_es = mensajes_sap_es.get(
            str(sap_code),
            mensaje_original
        )

        # --------------------------------------------------
        # LOG DETALLADO EN CONSOLA
        # --------------------------------------------------

        print(
            "\n" + "=" * 60
        )

        print(
            error_header
        )

        print(
            f"Citación: {citacion.id}"
        )

        print(
            f"Empresa: {citacion.EP_NID_id}"
        )

        print(
            f"CompanyDB: {config.company_db}"
        )

        print(
            f"DocEntry: {docentry}"
        )

        print(
            f"Endpoint: {endpoint}"
        )

        print(
            f"HTTP SAP: {error_data.get('status_code')}"
        )

        print(
            f"Código SAP: {sap_code}"
        )

        print(
            f"Mensaje SAP original: {mensaje_original}"
        )

        print(
            f"Mensaje SAP ES: {mensaje_sap_es}"
        )

        print(
            f"Respuesta SAP Raw: {raw_response}"
        )

        print(
            "=" * 60
        )

        # --------------------------------------------------
        # GUARDAR ERROR EN TERRAVIEW
        # --------------------------------------------------

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
            status_code=error_data.get(
                "status_code"
            ),
            sap_error=error_data,
        )

        return {
            "success": False,
            "message": (
                "SAP rechazo la actualizacion "
                "del documento de despacho."
            ),
            "status_code": error_data.get(
                "status_code"
            ),
            "sap_error": error_data,
            "preview": preview,
            "status": get_sap_despacho_update_status(
                citacion
            ),
        }

    except SapServiceLayerProbeError as exc:
        error_data = {
            "error": str(exc)
        }

        root_exc = exc

        while getattr(
            root_exc,
            "__cause__",
            None
        ) is not None:
            root_exc = (
                root_exc.__cause__
            )

        root_type = type(
            root_exc
        ).__name__

        error_text = str(
            exc
        ).lower()

        if (
            "timeout" in error_text
            or "timeout" in root_type.lower()
        ):
            error_category = "TIMEOUT"

        elif (
            "ssl" in error_text
            or "ssl" in root_type.lower()
        ):
            error_category = "SSL"

        elif (
            "conex" in error_text
            or "connection" in root_type.lower()
        ):
            error_category = "CONNECTION"

        elif "json" in error_text:
            error_category = "NON_JSON"

        elif sap_phase == "LOGIN":
            error_category = "LOGIN"

        else:
            error_category = "SERVICE_LAYER"

        endpoint = (
            f"/Drafts({docentry})"
            if sap_phase == "UPDATE_DRAFT"
            else "/Login"
        )

        # --------------------------------------------------
        # LOG ERROR TÉCNICO EN CONSOLA
        # --------------------------------------------------

        print(
            "\n" + "=" * 60
        )

        print(
            f"[SAP ERROR][UPDATE DESPACHO]"
            f"[{error_category}]"
        )

        print(
            f"Citación: {citacion.id}"
        )

        print(
            f"Empresa: {citacion.EP_NID_id}"
        )

        print(
            f"CompanyDB: {config.company_db}"
        )

        print(
            f"DocEntry: {docentry}"
        )

        print(
            f"Endpoint: {endpoint}"
        )

        print(
            f"Tipo: {root_type}"
        )

        print(
            f"Detalle: {exc}"
        )

        print(
            "=" * 60
        )

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
            "status": get_sap_despacho_update_status(
                citacion
            ),
        }

    finally:
        client.logout()

    # ------------------------------------------------------
    # ACTUALIZACIÓN SAP CORRECTA
    # ------------------------------------------------------

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
        "status": get_sap_despacho_update_status(
            citacion
        ),
    }

def normalizar_salida_documento_despacho(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    clave = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
    return SALIDA_DOCUMENTO_DESPACHO_OPCIONES.get(clave, "")


def validar_asignaciones_sap_planificadas(data):
    asignaciones_recibidas = data.get('asignaciones_sap')
    if asignaciones_recibidas in (None, ''):
        return []
    if not isinstance(asignaciones_recibidas, list):
        raise ValueError('Las asignaciones SAP deben enviarse como una lista.')
    if not asignaciones_recibidas:
        return []

    cliente_cabecera = texto_o_primero(data.get('cliente_codigo'), data.get('cliente'))
    cliente_principal = ''
    lineas_vistas = set()
    ids_locales_vistos = set()
    asignaciones = []

    for indice, asignacion in enumerate(asignaciones_recibidas, start=1):
        if not isinstance(asignacion, dict):
            raise ValueError(f'La asignacion SAP {indice} tiene un formato invalido.')

        asignacion_id = asignacion.get('id')
        if asignacion_id not in (None, ''):
            try:
                asignacion_id = int(asignacion_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'El identificador local de la asignacion SAP {indice} no es valido.') from exc
            if asignacion_id in ids_locales_vistos:
                raise ValueError('No puede enviar dos veces la misma asignacion SAP local.')
            ids_locales_vistos.add(asignacion_id)
        else:
            asignacion_id = None

        sap_abs_id = texto_o_primero(asignacion.get('sap_abs_id'), asignacion.get('sap_opor_id'))
        numero_acuerdo = texto_o_primero(asignacion.get('contrato_sap'), asignacion.get('sap_numero_acuerdo'))
        linea_acuerdo = texto_o_primero(asignacion.get('linea_acuerdo_sap'), asignacion.get('sap_linea_acuerdo'))
        codigo_producto = texto_o_primero(asignacion.get('codigo_producto_sap'), asignacion.get('sap_codigo_producto'))
        cliente_codigo = texto_o_primero(asignacion.get('cliente_codigo'), asignacion.get('sap_cliente_codigo'))
        cantidad_intentada = decimal_or_none(
            asignacion.get('cantidad_intentada_despachar', asignacion.get('cantidad_asignada'))
        )
        estado = texto_o_primero(
            asignacion.get('estado'),
            CITACION_DESPACHO_ASIGNACION_SAP.ESTADO_PLANIFICADA,
        ).upper()

        if not numero_acuerdo or not sap_abs_id or not linea_acuerdo:
            raise ValueError(f'La asignacion SAP {indice} debe indicar acuerdo, AbsID y linea.')
        if not codigo_producto:
            raise ValueError(f'La asignacion SAP {indice} debe indicar el producto.')
        if not cliente_codigo:
            raise ValueError(f'La asignacion SAP {indice} debe indicar el cliente SAP.')
        if cantidad_intentada is None or cantidad_intentada <= 0:
            raise ValueError(f'La cantidad intentada a despachar del contrato {indice} debe ser mayor que cero.')
        if estado not in {
            CITACION_DESPACHO_ASIGNACION_SAP.ESTADO_PLANIFICADA,
            CITACION_DESPACHO_ASIGNACION_SAP.ESTADO_ANULADA,
        }:
            raise ValueError(f'El estado de la asignacion SAP {indice} no es valido.')

        identidad = (sap_abs_id, linea_acuerdo)
        if identidad in lineas_vistas:
            raise ValueError('No puede asignar dos veces la misma linea de acuerdo SAP en un despacho.')
        lineas_vistas.add(identidad)

        if not cliente_principal:
            cliente_principal = cliente_codigo
        if cliente_codigo != cliente_principal:
            raise ValueError('Todos los contratos SAP del despacho deben pertenecer al mismo cliente.')
        if cliente_cabecera and cliente_codigo != cliente_cabecera:
            raise ValueError('El cliente del despacho debe coincidir con el cliente de los contratos SAP.')

        normalizada = {
            'id': asignacion_id,
            'sap_abs_id': sap_abs_id,
            'contrato_sap': numero_acuerdo,
            'linea_acuerdo_sap': linea_acuerdo,
            'codigo_producto_sap': codigo_producto,
            'nombre_producto_sap': texto_o_primero(asignacion.get('nombre_producto_sap'), asignacion.get('sap_nombre_producto')),
            'cliente_codigo': cliente_codigo,
            'cliente_nombre': texto_o_primero(asignacion.get('cliente_nombre'), asignacion.get('sap_cliente_nombre')),
            'oc_cliente': texto_o_primero(asignacion.get('oc_cliente'), asignacion.get('sap_oc_cliente')),
            'cantidad_planificada_sap': decimal_or_none(asignacion.get('cantidad_planificada_sap')),
            'cantidad_consumida_sap': decimal_or_none(asignacion.get('cantidad_consumida_sap')),
            'saldo_contrato_sap': decimal_or_none(asignacion.get('saldo_contrato_sap')),
            'unidad_medida': texto_o_primero(asignacion.get('unidad_medida'), asignacion.get('sap_unidad_medida')),
            'cantidad_intentada_despachar': cantidad_intentada,
            'orden': indice,
            'estado': estado,
        }
        asignaciones.append(normalizada)

    primera = next(
        (item for item in asignaciones if item['estado'] == CITACION_DESPACHO_ASIGNACION_SAP.ESTADO_PLANIFICADA),
        asignaciones[0],
    )
    data.update({
        'sap_abs_id': primera['sap_abs_id'],
        'sap_opor_id': primera['sap_abs_id'],
        'docentry': primera['sap_abs_id'],
        'sap_numero_acuerdo': primera['contrato_sap'],
        'contrato_sap': primera['contrato_sap'],
        'sap_linea_acuerdo': primera['linea_acuerdo_sap'],
        'linea_acuerdo_sap': primera['linea_acuerdo_sap'],
        'sap_cliente_codigo': primera['cliente_codigo'],
        'sap_cliente_nombre': primera['cliente_nombre'],
        'sap_oc_cliente': primera['oc_cliente'],
        'sap_codigo_producto': primera['codigo_producto_sap'],
        'sap_nombre_producto': primera['nombre_producto_sap'],
        'sap_cantidad_planificada': primera['cantidad_planificada_sap'],
        'sap_cantidad_consumida': primera['cantidad_consumida_sap'],
        'sap_saldo_contrato': primera['saldo_contrato_sap'],
        'sap_unidad_medida': primera['unidad_medida'],
        'codigo': primera['codigo_producto_sap'],
        'insumo': primera['nombre_producto_sap'],
        'pedido': primera['oc_cliente'],
        'cantidad_planificada_sap': primera['cantidad_planificada_sap'],
        'cantidad_consumida_sap': primera['cantidad_consumida_sap'],
        'saldo_contrato_sap': primera['saldo_contrato_sap'],
        'cantidad_disponible': primera['saldo_contrato_sap'],
        'cantidad_intentada_despachar': primera['cantidad_intentada_despachar'],
    })
    data['asignaciones_sap'] = asignaciones
    return asignaciones


def serializar_asignaciones_sap_planificadas(citacion, detalle_despacho=None):
    if detalle_despacho is None:
        try:
            detalle_despacho = citacion.detalle_despacho
        except CITACION_DESPACHO_DETALLE.DoesNotExist:
            return []

    filas = list(detalle_despacho.asignaciones_sap.all().order_by('CDAS_NORDEN', 'id'))
    if filas:
        return [
            {
                'id': fila.id,
                'sap_abs_id': fila.CDAS_CSAP_ABS_ID or '',
                'contrato_sap': fila.CDAS_CSAP_NUMERO_ACUERDO or '',
                'linea_acuerdo_sap': fila.CDAS_CSAP_LINEA_ACUERDO or '',
                'codigo_producto_sap': fila.CDAS_CSAP_CODIGO_PRODUCTO or '',
                'nombre_producto_sap': fila.CDAS_CSAP_NOMBRE_PRODUCTO or '',
                'cliente_codigo': fila.CDAS_CSAP_CLIENTE_CODIGO or '',
                'cliente_nombre': fila.CDAS_CSAP_CLIENTE_NOMBRE or '',
                'oc_cliente': fila.CDAS_CSAP_OC_CLIENTE or '',
                'cantidad_planificada_sap': fila.CDAS_NSAP_CANTIDAD_CONTRATO,
                'cantidad_consumida_sap': fila.CDAS_NSAP_CANTIDAD_CONSUMIDA,
                'saldo_contrato_sap': fila.CDAS_NSAP_SALDO,
                'unidad_medida': fila.CDAS_CSAP_UNIDAD_MEDIDA or '',
                'cantidad_intentada_despachar': fila.CDAS_NCANTIDAD_INTENTADA_DESPACHAR,
                'orden': fila.CDAS_NORDEN,
                'estado': fila.CDAS_CESTADO,
                'legacy': False,
            }
            for fila in filas
        ]

    # Compatibilidad para despachos creados antes de la tabla de asignaciones.
    if not (
        detalle_despacho.CDD_CSAP_ABS_ID
        and detalle_despacho.CDD_CSAP_NUMERO_ACUERDO
        and detalle_despacho.CDD_CSAP_LINEA_ACUERDO
        and detalle_despacho.CDD_CSAP_CODIGO_PRODUCTO
    ):
        return []
    cliente_codigo = detalle_despacho.CDD_CSAP_CLIENTE_CODIGO or (
        citacion.SN_NID.SN_CCODIGO_SAP if citacion.SN_NID else ''
    )
    cliente_nombre = detalle_despacho.CDD_CSAP_CLIENTE_NOMBRE or (
        citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else ''
    )
    return [{
        'id': None,
        'sap_abs_id': detalle_despacho.CDD_CSAP_ABS_ID or '',
        'contrato_sap': detalle_despacho.CDD_CSAP_NUMERO_ACUERDO or '',
        'linea_acuerdo_sap': detalle_despacho.CDD_CSAP_LINEA_ACUERDO or '',
        'codigo_producto_sap': detalle_despacho.CDD_CSAP_CODIGO_PRODUCTO or '',
        'nombre_producto_sap': detalle_despacho.CDD_CSAP_NOMBRE_PRODUCTO or '',
        'cliente_codigo': cliente_codigo,
        'cliente_nombre': cliente_nombre,
        'oc_cliente': detalle_despacho.CDD_CSAP_OC_CLIENTE or '',
        'cantidad_planificada_sap': detalle_despacho.CDD_NSAP_CANTIDAD_PLANIFICADA,
        'cantidad_consumida_sap': detalle_despacho.CDD_NSAP_CANTIDAD_CONSUMIDA,
        'saldo_contrato_sap': detalle_despacho.CDD_NSAP_SALDO_CONTRATO,
        'unidad_medida': detalle_despacho.CDD_CSAP_UNIDAD_MEDIDA or '',
        'cantidad_intentada_despachar': detalle_despacho.CDD_NCANTIDAD_INTENTADA_DESPACHAR,
        'orden': 1,
        'estado': CITACION_DESPACHO_ASIGNACION_SAP.ESTADO_PLANIFICADA,
        'legacy': True,
    }]


def sincronizar_asignaciones_sap_planificadas(detalle, asignaciones, usuario=None):
    existentes = {
        fila.id: fila
        for fila in detalle.asignaciones_sap.select_for_update().all()
    }
    ids_recibidos = {item['id'] for item in asignaciones if item.get('id') is not None}
    ids_desconocidos = ids_recibidos.difference(existentes)
    if ids_desconocidos:
        raise ValueError('Una asignacion SAP no pertenece al despacho que se intenta actualizar.')

    detalle.asignaciones_sap.exclude(id__in=ids_recibidos).delete()
    resultado = []
    for item in asignaciones:
        valores = {
            'EP_NID': detalle.EP_NID,
            'US_NID': usuario or detalle.US_NID,
            'CDAS_CSAP_ABS_ID': item['sap_abs_id'],
            'CDAS_CSAP_NUMERO_ACUERDO': item['contrato_sap'] or None,
            'CDAS_CSAP_LINEA_ACUERDO': item['linea_acuerdo_sap'],
            'CDAS_CSAP_CODIGO_PRODUCTO': item['codigo_producto_sap'] or None,
            'CDAS_CSAP_NOMBRE_PRODUCTO': item['nombre_producto_sap'] or None,
            'CDAS_CSAP_CLIENTE_CODIGO': item['cliente_codigo'],
            'CDAS_CSAP_CLIENTE_NOMBRE': item['cliente_nombre'] or None,
            'CDAS_CSAP_OC_CLIENTE': item['oc_cliente'] or None,
            'CDAS_NSAP_CANTIDAD_CONTRATO': item['cantidad_planificada_sap'],
            'CDAS_NSAP_CANTIDAD_CONSUMIDA': item['cantidad_consumida_sap'],
            'CDAS_NSAP_SALDO': item['saldo_contrato_sap'],
            'CDAS_CSAP_UNIDAD_MEDIDA': item['unidad_medida'] or None,
            'CDAS_NCANTIDAD_INTENTADA_DESPACHAR': item['cantidad_intentada_despachar'],
            'CDAS_NORDEN': item['orden'],
            'CDAS_CESTADO': item['estado'],
            'CDAS_FFECHA_SNAPSHOT': timezone.now(),
        }
        fila = existentes.get(item.get('id'))
        if fila is None:
            fila = CITACION_DESPACHO_ASIGNACION_SAP.objects.create(CDD_NID=detalle, **valores)
        else:
            for campo, valor in valores.items():
                setattr(fila, campo, valor)
            fila.save()
        resultado.append(fila)
    return resultado


@transaction.atomic
def guardar_detalle_despacho_citacion(citacion, data, usuario=None):
    asignaciones_sap = None
    if str(citacion.CI_CTIPO or '').upper() == 'DESPACHO' and 'asignaciones_sap' in data:
        asignaciones_sap = validar_asignaciones_sap_planificadas(data)

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
            "CDD_FFECHA_DESPACHO": data.get("fecha_despacho") or None,
            "CDD_FFECHA_LLEGADA_DESTINO": data.get("fecha_llegada_destino") or None,
            "CDD_FHORA_LLEGADA_PLANTA": data.get("hora_llegada_planta") or None,
            "CDD_FHORA_LLEGADA_DESTINO": data.get("hora_llegada_destino") or None,
            "CDD_CVENTANA_HORARIA_DESPACHO": texto_o_primero(data.get("ventana_horaria_despacho"), data.get("hora_llegada_planta"), observacion_legacy.get("ventana_horaria")),
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
    if asignaciones_sap is not None:
        detalle.asignaciones_sap.all().delete()
        CITACION_DESPACHO_ASIGNACION_SAP.objects.bulk_create([
            CITACION_DESPACHO_ASIGNACION_SAP(
                CDD_NID=detalle,
                EP_NID=citacion.EP_NID,
                US_NID=usuario or citacion.US_NID,
                CDAS_CSAP_ABS_ID=asignacion['sap_abs_id'],
                CDAS_CSAP_NUMERO_ACUERDO=asignacion['contrato_sap'] or None,
                CDAS_CSAP_LINEA_ACUERDO=asignacion['linea_acuerdo_sap'],
                CDAS_CSAP_CODIGO_PRODUCTO=asignacion['codigo_producto_sap'] or None,
                CDAS_CSAP_NOMBRE_PRODUCTO=asignacion['nombre_producto_sap'] or None,
                CDAS_CSAP_CLIENTE_CODIGO=asignacion['cliente_codigo'],
                CDAS_CSAP_CLIENTE_NOMBRE=asignacion['cliente_nombre'] or None,
                CDAS_CSAP_OC_CLIENTE=asignacion['oc_cliente'] or None,
                CDAS_NSAP_CANTIDAD_CONTRATO=asignacion['cantidad_planificada_sap'],
                CDAS_NSAP_CANTIDAD_CONSUMIDA=asignacion['cantidad_consumida_sap'],
                CDAS_NSAP_SALDO=asignacion['saldo_contrato_sap'],
                CDAS_CSAP_UNIDAD_MEDIDA=asignacion['unidad_medida'] or None,
                CDAS_NCANTIDAD_INTENTADA_DESPACHAR=asignacion['cantidad_intentada_despachar'],
                CDAS_NORDEN=asignacion['orden'],
                CDAS_CESTADO=asignacion['estado'],
            )
            for asignacion in asignaciones_sap
        ])
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
        "fecha_despacho": fecha_iso(getattr(detalle, "CDD_FFECHA_DESPACHO", None) if detalle else None),
        "fecha_llegada_destino": fecha_iso(getattr(detalle, "CDD_FFECHA_LLEGADA_DESTINO", None) if detalle else None),
        "fecha_llegada_destino_display": fecha_ddmmyyyy(getattr(detalle, "CDD_FFECHA_LLEGADA_DESTINO", None) if detalle else None),
        "hora_llegada_planta": hora_hhmm(getattr(detalle, "CDD_FHORA_LLEGADA_PLANTA", None) if detalle else None) or campo("CDD_CVENTANA_HORARIA_DESPACHO", legacy_key="ventana_horaria"),
        "hora_llegada_destino": hora_hhmm(getattr(detalle, "CDD_FHORA_LLEGADA_DESTINO", None) if detalle else None),
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


def consultar_acuerdos_despacho(termino, empresa_id=None):
    return consultar_acuerdos_despacho_sap(termino, empresa_id=empresa_id)


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
    "calcular_peso_real_despachado",
    "construir_preview_update_drafts_operacionales",
    "construir_diagnostico_preview_update_drafts_operacionales",
    "distribuir_cantidad_secuencial",
    "obtener_peso_entrada_sap_despacho",
    "guardar_detalle_despacho_citacion",
    "guardar_respuesta_borrador_sap_despacho",
    "guardar_respuesta_update_sap_despacho",
    "normalizar_salida_documento_despacho",
    "obtener_docentry_draft_sap_despacho",
    "obtener_peso_salida_sap_despacho",
    "parsear_json_despacho_legacy",
    "serializar_asignaciones_sap_planificadas",
    "sincronizar_asignaciones_sap_planificadas",
    "texto_o_primero",
    "validar_asignaciones_sap_planificadas",
]
