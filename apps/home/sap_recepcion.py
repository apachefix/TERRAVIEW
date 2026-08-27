"""
SAP Recepcion.

Centraliza la logica SAP usada por el flujo de RECEPCION. Los endpoints
existentes siguen viviendo en views.py por compatibilidad de URLs, pero deben
delegar aqui para evitar mezclar Recepcion con Despacho.
"""

from apps.integrations.sap_b1.sap_recepcion import (
    CAMPO_LOTE_RECEPCION_SAP,
    CAMPO_PESO_INFORMADO_GUIA,
    LOG_BORRADOR_SAP_ENVIADO,
    LOG_BORRADOR_SAP_RECEPCION_ENVIO,
    LOG_UPDATE_SAP_RECEPCION_ERROR,
    LOG_UPDATE_SAP_RECEPCION_ENVIO,
    PASO_BORRADOR_SAP,
    build_goods_receipt_draft_preview,
    build_goods_receipt_draft_preview_from_peso_guia,
    build_goods_receipt_draft_update_with_salida_lote,
    generar_lote_recepcion_sap,
    get_goods_receipt_draft_guide_status,
    get_goods_receipt_draft_status,
    get_goods_receipt_draft_update_status,
    send_goods_receipt_draft_from_peso_guia_to_sap,
    send_goods_receipt_draft_update_to_sap,
    send_goods_receipt_draft_to_sap,
)

from .sap_di_api import (
    SapDiApiError,
    consultar_clientes_sap,
    consultar_detalle_pedido_sap,
    consultar_pedido_sap,
    consultar_pedidos_por_producto_sap,
    consultar_producto_sap,
    consultar_productos_sap,
    consultar_productos_recepcion_transferencia_sap,
    consultar_proveedores_sap,
)


__all__ = [
    "CAMPO_LOTE_RECEPCION_SAP",
    "CAMPO_PESO_INFORMADO_GUIA",
    "LOG_BORRADOR_SAP_ENVIADO",
    "LOG_BORRADOR_SAP_RECEPCION_ENVIO",
    "LOG_UPDATE_SAP_RECEPCION_ERROR",
    "LOG_UPDATE_SAP_RECEPCION_ENVIO",
    "PASO_BORRADOR_SAP",
    "SapDiApiError",
    "build_goods_receipt_draft_preview",
    "build_goods_receipt_draft_preview_from_peso_guia",
    "build_goods_receipt_draft_update_with_salida_lote",
    "consultar_clientes_sap",
    "consultar_detalle_pedido_sap",
    "consultar_pedido_sap",
    "consultar_pedidos_por_producto_sap",
    "consultar_producto_sap",
    "consultar_productos_sap",
    "consultar_productos_recepcion_transferencia_sap",
    "consultar_proveedores_sap",
    "generar_lote_recepcion_sap",
    "get_goods_receipt_draft_guide_status",
    "get_goods_receipt_draft_status",
    "get_goods_receipt_draft_update_status",
    "send_goods_receipt_draft_from_peso_guia_to_sap",
    "send_goods_receipt_draft_update_to_sap",
    "send_goods_receipt_draft_to_sap",
]
