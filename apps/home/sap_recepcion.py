"""
SAP Recepcion.

Centraliza la logica SAP usada por el flujo de RECEPCION. Los endpoints
existentes siguen viviendo en views.py por compatibilidad de URLs, pero deben
delegar aqui para evitar mezclar Recepcion con Despacho.
"""

from apps.integrations.sap_b1.goods_receipt_draft_preview import (
    CAMPO_PESO_INFORMADO_GUIA,
    LOG_BORRADOR_SAP_ENVIADO,
    PASO_BORRADOR_SAP,
    build_goods_receipt_draft_preview,
    build_goods_receipt_draft_preview_from_peso_guia,
    get_goods_receipt_draft_guide_status,
    get_goods_receipt_draft_status,
    send_goods_receipt_draft_from_peso_guia_to_sap,
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
    consultar_proveedores_sap,
)


__all__ = [
    "CAMPO_PESO_INFORMADO_GUIA",
    "LOG_BORRADOR_SAP_ENVIADO",
    "PASO_BORRADOR_SAP",
    "SapDiApiError",
    "build_goods_receipt_draft_preview",
    "build_goods_receipt_draft_preview_from_peso_guia",
    "consultar_clientes_sap",
    "consultar_detalle_pedido_sap",
    "consultar_pedido_sap",
    "consultar_pedidos_por_producto_sap",
    "consultar_producto_sap",
    "consultar_productos_sap",
    "consultar_proveedores_sap",
    "get_goods_receipt_draft_guide_status",
    "get_goods_receipt_draft_status",
    "send_goods_receipt_draft_from_peso_guia_to_sap",
    "send_goods_receipt_draft_to_sap",
]
