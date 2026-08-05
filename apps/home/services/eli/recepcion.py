from .base import componer_presentacion_eli

def construir_presentacion_recepcion(citacion, datos_legacy):
    return componer_presentacion_eli(datos_legacy, citacion, "RECEPCION")
