"""Safe presentation-only summaries for SAP audit events in E.L.I."""
import json
import logging
import re

logger = logging.getLogger(__name__)

SAP_EVENT_TITLES = {
    "BORRADOR_SAP_RECEPCION_ENVIO": "Envio de borrador SAP de recepcion",
    "UPDATE_SAP_RECEPCION_ENVIO": "Actualizacion de borrador SAP de recepcion",
    "BORRADOR_SAP_DESPACHO_ENVIO": "Envio de borrador SAP de despacho",
    "UPDATE_SAP_DESPACHO_ENVIO": "Actualizacion de borrador SAP de despacho",
}


def es_evento_sap_eli(paso):
    return str(paso or "").upper() in SAP_EVENT_TITLES or "SAP_" in str(paso or "").upper()


def parsear_observacion_json_eli(valor, *, citacion_id=None, empresa_id=None, log_id=None, paso=None):
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        parsed = json.loads(valor)
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning(
            "E.L.I. SAP audit JSON unavailable citacion_id=%s empresa_id=%s log_id=%s paso=%s error=parse",
            citacion_id, empresa_id, log_id, paso,
        )
        return None
    return parsed if isinstance(parsed, dict) else None


def _presente(valor):
    return valor is not None and (not isinstance(valor, str) or bool(valor.strip()))


def primer_valor_no_vacio(*valores):
    return next((valor for valor in valores if _presente(valor)), "")


def obtener_primera_linea_documento(contenedor):
    """Safely return the first DocumentLines mapping without changing its source."""
    if not isinstance(contenedor, dict):
        return {}
    lineas = contenedor.get("DocumentLines")
    if not isinstance(lineas, list) or not lineas or not isinstance(lineas[0], dict):
        return {}
    return lineas[0]


def _dict(datos, clave):
    valor = datos.get(clave)
    return valor if isinstance(valor, dict) else {}


def _raiz(datos, *claves):
    return primer_valor_no_vacio(*(datos.get(clave) for clave in claves))


def _lineas(lineas, clave):
    return primer_valor_no_vacio(*(linea.get(clave) for linea in lineas))


def _guia(contenedor):
    if not isinstance(contenedor, dict):
        return ""
    valores = (contenedor.get("FolioPrefixString"), contenedor.get("FolioNumber"))
    return " ".join(str(valor) for valor in valores if _presente(valor))


def _resultado(datos, estado):
    if datos.get("success") is not None:
        return "Exitoso" if datos.get("success") is True else "Error"
    status_code = datos.get("status_code")
    if _presente(status_code):
        return "Exitoso" if str(status_code).startswith("2") else "Error"
    return "Exitoso" if str(estado or "").upper() in {"COMPLETADO", "EXITOSO", "OK"} else "Error"


def _fecha_documento(response, payload, request):
    fecha = primer_valor_no_vacio(response.get("DocDate"))
    if fecha:
        return " ".join(str(v) for v in (fecha, response.get("DocTime")) if _presente(v))
    return primer_valor_no_vacio(payload.get("DocDate"), request.get("DocDate"))


def _error(datos):
    valor = primer_valor_no_vacio(datos.get("sap_error_message"), datos.get("mensaje_corto"))
    if not valor and isinstance(datos.get("sap_error"), dict):
        error = datos["sap_error"]
        valor = primer_valor_no_vacio(error.get("message"), error.get("Message"), error.get("error"))
    return re.sub(r"https?://\S+", "", str(valor or "")).strip()[:300]


def resumir_evento_sap_eli(
    paso, observacion, *, estado="", fecha="", usuario="", citacion_id=None, empresa_id=None, log_id=None
):
    titulo = SAP_EVENT_TITLES.get(str(paso or "").upper(), "Evento SAP")
    datos = parsear_observacion_json_eli(
        observacion, citacion_id=citacion_id, empresa_id=empresa_id, log_id=log_id, paso=paso
    )
    if datos is None:
        return {"tipo": "SAP", "titulo": titulo, "estado": estado or "", "filas": [], "error": "",
                "texto": f"{titulo}. Detalle tecnico no disponible."}

    payload, request, response = (_dict(datos, key) for key in ("payload", "request", "response"))
    lp, lq, lr = (obtener_primera_linea_documento(source) for source in (payload, request, response))
    request_first, response_first = (lp, lq, lr), (lr, lp, lq)
    es_update = str(paso or "").upper().startswith("UPDATE_SAP_")
    cantidad_linea = _lineas(request_first, "Quantity")
    cantidad = (primer_valor_no_vacio(datos.get("cantidad_sap"), cantidad_linea) if es_update
                else primer_valor_no_vacio(cantidad_linea, datos.get("cantidad_sap"), datos.get("quantity")))
    unidad = primer_valor_no_vacio(
        datos.get("unidad_sap"), lr.get("UoMCode"), lr.get("MeasureUnit"),
        lp.get("UoMCode"), lp.get("MeasureUnit"), lq.get("UoMCode"), lq.get("MeasureUnit"),
    )
    fields = [
        ("Accion", titulo), ("Resultado", _resultado(datos, estado)), ("Estado HTTP", datos.get("status_code")),
        ("DocEntry", primer_valor_no_vacio(datos.get("docentry"), datos.get("DocEntry"), response.get("DocEntry"), payload.get("DocEntry"), request.get("DocEntry"))),
        ("DocNum", primer_valor_no_vacio(datos.get("docnum"), datos.get("DocNum"), response.get("DocNum"), payload.get("DocNum"), request.get("DocNum"))),
        ("Proveedor", primer_valor_no_vacio(response.get("CardName"), payload.get("CardName"), request.get("CardName"), _raiz(datos, "proveedor", "card_name"))),
        ("CardCode", primer_valor_no_vacio(response.get("CardCode"), payload.get("CardCode"), request.get("CardCode"), datos.get("card_code"))),
        ("Codigo SAP", primer_valor_no_vacio(_raiz(datos, "item_code", "codigo_sap"), _lineas(request_first, "ItemCode"))),
        ("Producto", _lineas(response_first, "ItemDescription")),
        ("Cantidad SAP" if es_update else "Cantidad", cantidad), ("Unidad", unidad),
        ("Pedido base", primer_valor_no_vacio(_lineas(request_first, "BaseEntry"), _raiz(datos, "base_entry", "pedido_base"))),
        ("Contrato", datos.get("contrato")),
        ("Guia", primer_valor_no_vacio(_guia(payload), _guia(request), _guia(response), _raiz(datos, "guia", "folio", "numero_guia"), _guia(datos))),
        ("Estanque destino", primer_valor_no_vacio(_lineas(request_first, "U_HCO_Plantadestino"), _raiz(datos, "estanque_destino", "plantadestino"))),
        ("Fecha", primer_valor_no_vacio(datos.get("fecha_hora"), fecha, _fecha_documento(response, payload, request))),
        ("Usuario", primer_valor_no_vacio(datos.get("usuario"), usuario)),
    ]
    if es_update:
        fields += [("Peso salida", _raiz(datos, "peso_salida", "peso_salida_kg")),
                   ("Modo lote", datos.get("modo_lote")), ("Lote enviado", datos.get("lote_enviado"))]
    error = _error(datos)
    if error:
        fields.append(("Error", error))
    filas = [{"etiqueta": label, "valor": str(value)} for label, value in fields if _presente(value)]
    texto = " | ".join(f"{fila['etiqueta']}: {fila['valor']}" for fila in filas)
    return {"tipo": "SAP", "titulo": titulo, "estado": estado or "", "filas": filas, "error": error, "texto": texto}


def normalizar_auditoria_sap_eli(expediente, citacion):
    """Replace only presentation text of recognized SAP rows; never mutate logs."""
    for row in expediente.get("seguimiento", []):
        paso = row.get("paso")
        if not es_evento_sap_eli(paso):
            continue
        resumen = resumir_evento_sap_eli(
            paso, row.get("observacion"), estado=row.get("estado", ""), fecha=row.get("fecha", ""),
            usuario=row.get("usuario", ""), citacion_id=getattr(citacion, "id", None),
            empresa_id=getattr(citacion, "EP_NID_id", None),
        )
        row["auditoria_sap"] = resumen
        row["observacion"] = resumen["texto"]
    return expediente

