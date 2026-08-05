def normalizar_expediente_para_comparacion(value):
    if isinstance(value, dict):
        return {str(k): normalizar_expediente_para_comparacion(v) for k, v in value.items() if str(k) not in {"tipo_eli", "codigo_flujo", "empresa_id", "filas", "codigo", "orden"}}
    if isinstance(value, (list, tuple)):
        return [normalizar_expediente_para_comparacion(item) for item in value]
    if hasattr(value, "pk"):
        return {"model": value.__class__.__name__, "pk": value.pk}
    return value

def comparar_expedientes_eli(legacy, nuevo):
    legacy = normalizar_expediente_para_comparacion(legacy)
    nuevo = normalizar_expediente_para_comparacion(nuevo)
    return [] if legacy == nuevo else ["La estructura normalizada difiere."]
