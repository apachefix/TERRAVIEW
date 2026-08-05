from .base import seleccionar_contexto_base

def seleccionar_datos_eli_recepcion(citacion):
    contexto = seleccionar_contexto_base(citacion)
    contexto["tipo_eli"] = "RECEPCION"
    return contexto
