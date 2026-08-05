"""Central, presentation-only configuration for E.L.I. builders."""

PENDING_TEXT = "Pendiente"
NOT_AVAILABLE_TEXT = "No disponible"
NO_INFORMATION_TEXT = "Sin informacion"

ELI_RECEPCION_SECCIONES = (
    ("revision_documental", 10, "Revision documental"),
    ("ingreso_planta", 20, "Ingreso a planta"),
    ("inspeccion_transporte", 30, "Inspeccion transporte"),
    ("toma_muestra", 40, "Toma de muestra"),
    ("analisis_calidad", 50, "Analisis y calidad"),
    ("autorizacion_descarga", 60, "Autorizacion descarga"),
    ("descarga", 70, "Descarga"),
    ("cierre_operacional", 80, "Cierre operacional"),
)

ELI_DESPACHO_SECCIONES = (
    ("datos_comerciales_sap", 10, "Datos comerciales / SAP despacho"),
    ("datos_sap", 20, "Datos SAP despacho"),
    ("flujo_operacional", 30, "Flujo operacional despacho"),
    ("pesajes", 40, "Pesajes"),
    ("cierre_operacional", 50, "Cierre operacional despacho"),
)

SECCIONES_POR_TIPO = {
    "RECEPCION": ELI_RECEPCION_SECCIONES,
    "DESPACHO": ELI_DESPACHO_SECCIONES,
}

TEXTOS_AUDITORIA = {
    "pendiente": PENDING_TEXT,
    "no_disponible": NOT_AVAILABLE_TEXT,
    "sin_informacion": NO_INFORMATION_TEXT,
    "responsable": "Responsable",
    "observaciones": "Observaciones",
    "fecha_inicio": "Fecha inicio",
    "fecha_termino": "Fecha termino",
    "duracion": "Duracion",
}

ETIQUETAS_CAMPOS = {
    "numero_citacion": "Numero citacion", "fecha_citacion": "Fecha citacion",
    "empresa": "Empresa", "tipo_operacion": "Tipo operacion", "secuencia": "Flujo / secuencia",
    "estado": "Estado", "patente": "Patente", "transportista": "Transportista",
    "conductor": "Conductor", "rut_conductor": "RUT conductor", "telefono": "Telefono conductor",
    "remolque": "Remolque", "producto": "Producto", "codigo_sap": "Codigo SAP",
    "proveedor": "Proveedor", "cliente": "Cliente", "contrato": "Contrato SAP",
    "pedido": "Pedido SAP", "cantidad": "Cantidad", "estanque": "Estanque destino",
    "bl": "BL / contenedor", "guia": "Guia", "tipo_documento": "Tipo documento",
    "perfil": "Perfil", "fecha": "Fecha", "hora": "Hora", "inicio": "Inicio",
    "termino": "Termino", "tiempo_total": "Tiempo total del proceso",
}
