import json
import logging

from apps.home.services.eli_config import NOT_AVAILABLE_TEXT, SECCIONES_POR_TIPO

logger = logging.getLogger(__name__)

LEGACY_EXPEDIENTE_KEYS = (
    "encabezado_eli", "etapas_eli", "documentos", "seguimiento", "tiempos",
    "datos_camion", "datos_planificacion", "resumen",
)

def fila_eli(codigo, etiqueta, valor, origen="", visible=True):
    return {"codigo": codigo, "etiqueta": etiqueta, "label": etiqueta, "valor": valor or "", "value": valor or "", "origen": origen, "visible": visible}

def normalizar_metadata_eli(valor):
    if not isinstance(valor, str):
        return valor
    texto = valor.strip()
    if not texto or texto[0:1] not in ("{", "["):
        return valor
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return valor

def normalizar_observacion_eli(valor):
    return "" if valor is None else str(valor)

def validar_contrato_expediente_eli(expediente):
    for key in LEGACY_EXPEDIENTE_KEYS:
        if key not in expediente:
            logger.debug("E.L.I. missing optional legacy key", extra={"key": key})
            expediente[key] = [] if key != "resumen" else {}
    return expediente

def componer_presentacion_eli(expediente, citacion, tipo):
    tipo = "DESPACHO" if tipo == "DESPACHO" else "RECEPCION"
    configuradas = SECCIONES_POR_TIPO[tipo]
    por_numero = {n + 1: config for n, config in enumerate(configuradas)}
    for etapa in expediente.get("etapas_eli", []):
        config = por_numero.get(etapa.get("numero"))
        if config:
            etapa.update({"codigo": config[0], "orden": config[1], "titulo": config[2]})
        etapa["filas"] = [
            fila_eli(str(index), row.get("label", ""), row.get("value", ""), visible=True)
            for index, row in enumerate(etapa.get("datos", []), start=1)
        ]
    expediente["etapas_eli"] = sorted(expediente.get("etapas_eli", []), key=lambda e: e.get("orden", e.get("numero", 0)))
    expediente["tipo_eli"] = tipo
    expediente["codigo_flujo"] = getattr(getattr(citacion, "SC_NID", None), "SE_CCODIGO", "") or ""
    expediente["empresa_id"] = citacion.EP_NID_id
    return validar_contrato_expediente_eli(expediente)
