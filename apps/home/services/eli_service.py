"""Public composition facade for E.L.I. legacy builders."""
from apps.home.services.eli.despacho import construir_presentacion_despacho
from apps.home.services.eli.recepcion import construir_presentacion_recepcion
from apps.home.services.eli.sap_audit import normalizar_auditoria_sap_eli


def enriquecer_expediente_eli(expediente, citacion, tipo_eli):
    if tipo_eli == "DESPACHO":
        expediente = construir_presentacion_despacho(citacion, expediente)
    else:
        expediente = construir_presentacion_recepcion(citacion, expediente)
    return normalizar_auditoria_sap_eli(expediente, citacion)

