"""Read-only, company-scoped sources used by E.L.I. builders."""
import logging

from apps.home.models import (
    CITACION_DOCUMENTO, CITACION_ITEM, DATO_OPERACION, ETAPA_LOG,
    OPERACION_PLANTA_LOG,
)

logger = logging.getLogger(__name__)


def seleccionar_contexto_base(citacion):
    """Return evaluated E.L.I. sources scoped to a validated citation/company."""
    empresa_id = citacion.EP_NID_id
    return {
        "citacion": citacion,
        "empresa_id": empresa_id,
        "item": CITACION_ITEM.objects.select_related("IT_NID").filter(
            CI_NID_id=citacion.id).first(),
        "datos_operacion": list(
            DATO_OPERACION.objects.select_related("CAMP_NID", "US_NID", "ET_NID")
            .filter(CI_NID_id=citacion.id, EP_NID_id=empresa_id)
            .order_by("DO_FFECHAREGISTRO", "id")),
        "logs": list(
            OPERACION_PLANTA_LOG.objects.select_related("US_NID")
            .filter(CI_NID_id=citacion.id, EP_NID_id=empresa_id)
            .order_by("OPL_FFECHAREGISTRO", "id")),
        "documentos": list(
            CITACION_DOCUMENTO.objects.select_related("US_SUBE_NID")
            .filter(CI_NID_id=citacion.id, EP_NID_id=empresa_id, CD_BACTIVO=True)
            .order_by("CD_CTIPO", "-CD_FFECHASUBIDA")),
        "etapa_logs": list(
            ETAPA_LOG.objects.select_related("ET_NID", "US_INICIO_ID", "US_FIN_ID")
            .filter(CI_NID_id=citacion.id, EP_NID_id=empresa_id).order_by("EL_FFECHAINICIO", "id")),
    }


def primer_log(logs, paso):
    """First matching record in explicit chronological order."""
    return next((log for log in logs if log.OPL_CPASO == paso), None)


def ultimo_log(logs, paso):
    """Last matching record in explicit chronological order."""
    return next((log for log in reversed(logs) if log.OPL_CPASO == paso), None)


def logs_por_paso(logs):
    """Keep repeated operational steps in chronological order."""
    resultado = {}
    for log in logs:
        resultado.setdefault(log.OPL_CPASO, []).append(log)
    return resultado


def texto_prioritario(*valores):
    """Return the first visible non-empty value."""
    return next((valor for valor in valores if valor not in (None, "")), "")


def resolver_patente_eli(contexto):
    """Priority: operational, truck-in-yard snapshot, citation, empty."""
    return texto_prioritario(contexto.get("operacional", {}).get("patente"),
                             contexto.get("datos_camion", {}).get("patente"),
                             contexto.get("citacion_patente"))


def resolver_transportista_eli(contexto):
    """Priority: operational, truck-in-yard snapshot, planning, empty."""
    return texto_prioritario(contexto.get("operacional", {}).get("transportista"),
                             contexto.get("datos_camion", {}).get("transportista"),
                             contexto.get("planificacion", {}).get("transportista"))


def resolver_conductor_eli(contexto):
    """Priority: operational, truck-in-yard snapshot, planning, empty."""
    return texto_prioritario(contexto.get("operacional", {}).get("conductor"),
                             contexto.get("datos_camion", {}).get("conductor"),
                             contexto.get("planificacion", {}).get("conductor"))


def resolver_producto_eli(contexto):
    """Priority: SAP, planning detail, item, empty."""
    return texto_prioritario(contexto.get("sap", {}).get("producto"),
                             contexto.get("detalle", {}).get("insumo"),
                             contexto.get("item_nombre"))


def resolver_proveedor_eli(contexto):
    """Priority: planning detail, operational copy, citation provider, empty."""
    return texto_prioritario(contexto.get("detalle", {}).get("proveedor_sap"),
                             contexto.get("operacional", {}).get("proveedor_sap"),
                             contexto.get("proveedor_citacion"))


def resolver_cliente_eli(contexto):
    """Priority: SAP, planning detail, citation customer, empty."""
    return texto_prioritario(contexto.get("sap", {}).get("cliente"),
                             contexto.get("detalle", {}).get("cliente_nombre"),
                             contexto.get("cliente_citacion"))


def resolver_documento_eli(contexto):
    """Priority: operational copy, citation, empty."""
    return texto_prioritario(contexto.get("operacional", {}).get("numero_documento"),
                             contexto.get("citacion_documento"))


def resolver_pedido_sap_eli(contexto):
    """Priority: planning detail, SAP source, empty."""
    return texto_prioritario(contexto.get("detalle", {}).get("pedido"),
                             contexto.get("sap", {}).get("pedido"))


def resolver_contrato_eli(contexto):
    """Priority: operational copy, SAP source, planning detail, empty."""
    return texto_prioritario(contexto.get("operacional", {}).get("contrato_sap"),
                             contexto.get("sap", {}).get("contrato"),
                             contexto.get("detalle", {}).get("contrato"))


def resolver_estanque_eli(contexto):
    """Priority: planning detail, operational cycle, empty."""
    return texto_prioritario(contexto.get("detalle", {}).get("estanque_destino"),
                             contexto.get("operacional", {}).get("estanque_destino"))
