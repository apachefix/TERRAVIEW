"""
Diagnostico de lectura para Orden de Compra SAP Business One Service Layer.
No crea documentos, no inserta datos y no modifica SAP.
Solo prueba login, consulta GET de PurchaseOrders y logout.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from requests import HTTPError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.integrations.sap_b1.service_layer_probe import (  # noqa: E402
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    configure_logging,
    load_config,
)


LOGGER = logging.getLogger("sap_b1.purchase_order_probe")

HEADER_FIELDS = (
    "DocEntry",
    "DocNum",
    "CardCode",
    "CardName",
    "DocDate",
    "DocDueDate",
    "TaxDate",
    "DocumentStatus",
    "DocCurrency",
    "DocTotal",
    "Comments",
)

LINE_FIELDS = (
    "LineNum",
    "ItemCode",
    "ItemDescription",
    "Quantity",
    "RemainingOpenQuantity",
    "OpenQuantity",
    "WarehouseCode",
    "LineStatus",
    "UnitPrice",
    "LineTotal",
    "U_NXContenedor",
)

EXTRA_LINE_KEYWORDS = (
    "cisterna",
    "contenedor",
    "container",
    "bl",
    "lote",
    "batch",
    "productor",
    "producer",
)

LATEST_SELECT_FIELDS = "DocEntry,DocNum,CardCode,CardName,DocDate,DocDueDate,DocumentStatus,DocTotal"


def positive_int(value: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Debe indicar un numero entero.") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Debe indicar un numero entero positivo.")
    return parsed


def service_layer_get_json(client: SapServiceLayerClient, path: str, context: str) -> Dict[str, Any]:
    response = client._request("GET", path, diagnostic_context=context)
    LOGGER.info("%s HTTP status: %s.", context, response.status_code)
    data = client._json_or_error(response, context)
    response.raise_for_status()
    return data


def fetch_purchase_orders_by_doc_num(client: SapServiceLayerClient, doc_num: int) -> List[Dict[str, Any]]:
    filter_query = quote(f"DocNum eq {doc_num}", safe="")
    endpoint = f"PurchaseOrders?$filter={filter_query}"
    LOGGER.info("Buscando Orden de Compra SAP por DocNum: GET /PurchaseOrders?$filter=DocNum eq %s", doc_num)
    data = service_layer_get_json(client, endpoint, f"PurchaseOrders filter DocNum {doc_num}")
    values = data.get("value", [])
    if not isinstance(values, list) or not values:
        raise SapServiceLayerProbeError(
            f"No se encontro Purchase Order con DocNum={doc_num} en la compania SAP configurada."
        )
    LOGGER.info("Purchase Orders encontradas por DocNum=%s: %s", doc_num, len(values))
    if len(values) > 1:
        LOGGER.warning("Se encontro mas de una OC para DocNum=%s; se esperaba una sola.", doc_num)
    for index, purchase_order in enumerate(values, start=1):
        LOGGER.info(
            "Coincidencia %s | DocEntry=%s | DocNum=%s | CardCode=%s | CardName=%s | DocumentStatus=%s | DocTotal=%s",
            index,
            purchase_order.get("DocEntry", ""),
            purchase_order.get("DocNum", ""),
            purchase_order.get("CardCode", ""),
            purchase_order.get("CardName", ""),
            purchase_order.get("DocumentStatus", ""),
            purchase_order.get("DocTotal", ""),
        )
    return values


def resolve_doc_entry_by_doc_num(client: SapServiceLayerClient, doc_num: int) -> int:
    matches = fetch_purchase_orders_by_doc_num(client, doc_num)
    doc_entry = matches[0].get("DocEntry")
    if doc_entry in [None, ""]:
        raise SapServiceLayerProbeError(f"La OC encontrada por DocNum={doc_num} no incluye DocEntry.")
    try:
        resolved = int(doc_entry)
    except (TypeError, ValueError) as exc:
        raise SapServiceLayerProbeError(f"DocEntry recibido no es numerico para DocNum={doc_num}: {doc_entry}") from exc
    LOGGER.info("DocEntry real obtenido desde DocNum=%s: %s", doc_num, resolved)
    return resolved


def fetch_latest_purchase_orders(client: SapServiceLayerClient, top: int) -> List[Dict[str, Any]]:
    endpoint = (
        f"PurchaseOrders?$select={LATEST_SELECT_FIELDS}"
        f"&$orderby=DocEntry desc&$top={top}"
    )
    LOGGER.info(
        "Consultando ultimas PurchaseOrders visibles: GET /PurchaseOrders?$select=%s&$orderby=DocEntry desc&$top=%s",
        LATEST_SELECT_FIELDS,
        top,
    )
    try:
        data = service_layer_get_json(client, endpoint, f"PurchaseOrders latest top {top} orderby DocEntry desc")
    except HTTPError as exc:
        LOGGER.warning("Consulta latest con orderby fallo: %s", exc)
        endpoint = f"PurchaseOrders?$select={LATEST_SELECT_FIELDS}&$top={top}"
        LOGGER.info(
            "Probando fallback sin orderby: GET /PurchaseOrders?$select=%s&$top=%s",
            LATEST_SELECT_FIELDS,
            top,
        )
        data = service_layer_get_json(client, endpoint, f"PurchaseOrders latest top {top} sin orderby")

    values = data.get("value", [])
    if not isinstance(values, list):
        raise SapServiceLayerProbeError("Respuesta latest PurchaseOrders no contiene una lista value valida.")
    return values


def log_latest_purchase_orders(purchase_orders: List[Dict[str, Any]]) -> None:
    LOGGER.info("========== ULTIMAS PURCHASE ORDERS VISIBLES ==========")
    LOGGER.info("Registros recibidos: %s", len(purchase_orders))
    if not purchase_orders:
        LOGGER.warning("Service Layer respondio sin PurchaseOrders visibles para la consulta latest.")
        return
    for index, purchase_order in enumerate(purchase_orders, start=1):
        LOGGER.info(
            "%s | DocEntry=%s | DocNum=%s | CardCode=%s | CardName=%s | DocDate=%s | DocDueDate=%s | DocumentStatus=%s | DocTotal=%s",
            index,
            purchase_order.get("DocEntry", ""),
            purchase_order.get("DocNum", ""),
            purchase_order.get("CardCode", ""),
            purchase_order.get("CardName", ""),
            purchase_order.get("DocDate", ""),
            purchase_order.get("DocDueDate", ""),
            purchase_order.get("DocumentStatus", ""),
            purchase_order.get("DocTotal", ""),
        )


def fetch_purchase_order(client: SapServiceLayerClient, doc_entry: int) -> Dict[str, Any]:
    endpoint = f"PurchaseOrders({doc_entry})"
    LOGGER.info("Consultando Orden de Compra SAP por endpoint directo: GET /%s", endpoint)
    try:
        data = service_layer_get_json(client, endpoint, f"PurchaseOrders({doc_entry})")
        LOGGER.info("Orden de Compra encontrada por endpoint directo.")
        return data
    except HTTPError as exc:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else None
        LOGGER.warning(
            "Consulta directa PurchaseOrders(%s) fallo con status=%s. Se probara filtro por DocEntry.",
            doc_entry,
            status or "desconocido",
        )
        if status and status not in {400, 404}:
            LOGGER.warning("El error directo no fue 400/404, pero se intentara alternativa controlada igualmente.")

    filter_query = quote(f"DocEntry eq {doc_entry}", safe="")
    endpoint = f"PurchaseOrders?$filter={filter_query}"
    LOGGER.info("Consultando Orden de Compra SAP por filtro: GET /PurchaseOrders?$filter=DocEntry eq %s", doc_entry)
    data = service_layer_get_json(client, endpoint, f"PurchaseOrders filter DocEntry {doc_entry}")
    values = data.get("value", [])
    if not isinstance(values, list) or not values:
        raise SapServiceLayerProbeError(f"OC no encontrada en SAP para DocEntry={doc_entry}.")
    LOGGER.info("Orden de Compra encontrada por filtro. Registros recibidos: %s.", len(values))
    return values[0]


def iter_extra_line_fields(line: Dict[str, Any]) -> Iterable[str]:
    known = set(LINE_FIELDS)
    for key in sorted(line.keys()):
        key_normalized = key.lower()
        if key in known:
            continue
        if any(keyword in key_normalized for keyword in EXTRA_LINE_KEYWORDS):
            yield key


def log_purchase_order_header(purchase_order: Dict[str, Any]) -> None:
    LOGGER.info("========== CABECERA ORDEN DE COMPRA ==========")
    for field in HEADER_FIELDS:
        LOGGER.info("%s: %s", field, purchase_order.get(field, ""))


def log_purchase_order_lines(purchase_order: Dict[str, Any]) -> None:
    lines = purchase_order.get("DocumentLines", [])
    if not isinstance(lines, list):
        LOGGER.warning("DocumentLines no viene como lista. Tipo recibido: %s", type(lines).__name__)
        return

    LOGGER.info("========== LINEAS ORDEN DE COMPRA ==========")
    LOGGER.info("Lineas recibidas: %s", len(lines))
    for line in lines:
        if not isinstance(line, dict):
            LOGGER.warning("Linea con formato no esperado: %s", line)
            continue
        line_num = line.get("LineNum", "")
        LOGGER.info("----- Linea SAP LineNum=%s | posible BaseLine=%s -----", line_num, line_num)
        for field in LINE_FIELDS:
            LOGGER.info("%s: %s", field, line.get(field, ""))
        for field in iter_extra_line_fields(line):
            LOGGER.info("%s: %s", field, line.get(field, ""))


def log_purchase_order(purchase_order: Dict[str, Any]) -> None:
    log_purchase_order_header(purchase_order)
    log_purchase_order_lines(purchase_order)
    LOGGER.info("Nota BaseLine: para borradores futuros, BaseLine corresponde al LineNum de la linea SAP seleccionada.")


def run_purchase_order_probe(
    doc_entry: Optional[int] = None,
    doc_num: Optional[int] = None,
    latest: Optional[int] = None,
) -> bool:
    configure_logging()
    client: Optional[SapServiceLayerClient] = None
    try:
        config = load_config()
        client = SapServiceLayerClient(config)
        client.login()
        if latest is not None:
            purchase_orders = fetch_latest_purchase_orders(client, latest)
            log_latest_purchase_orders(purchase_orders)
            LOGGER.info("Resultado final: consulta latest PurchaseOrders top=%s ejecutada.", latest)
            return True
        resolved_doc_entry = doc_entry
        if doc_num is not None:
            LOGGER.info("Parametro recibido: DocNum=%s. Se resolvera DocEntry antes de consultar el detalle.", doc_num)
            resolved_doc_entry = resolve_doc_entry_by_doc_num(client, doc_num)
        if resolved_doc_entry is None:
            raise SapServiceLayerProbeError("Debe indicar DocEntry o DocNum para consultar PurchaseOrders.")
        purchase_order = fetch_purchase_order(client, resolved_doc_entry)
        log_purchase_order(purchase_order)
        LOGGER.info("Resultado final: consulta PurchaseOrders DocEntry=%s exitosa.", resolved_doc_entry)
        return True
    except HTTPError as exc:
        LOGGER.error("Error HTTP Service Layer al consultar Orden de Compra: %s", exc)
        LOGGER.error("Posibles causas: OC inexistente, permisos, CompanyDB incorrecta o endpoint no disponible.")
        return False
    except SapServiceLayerProbeError as exc:
        LOGGER.error("Diagnostico controlado: %s", exc)
        return False
    except Exception as exc:
        LOGGER.exception("Error inesperado durante consulta PurchaseOrders: %s", exc)
        return False
    finally:
        if client:
            client.logout()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta una Orden de Compra SAP por DocEntry o DocNum via Service Layer.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc-entry", type=positive_int, help="DocEntry SAP de OPOR/PurchaseOrders.")
    group.add_argument("--doc-num", type=positive_int, help="DocNum SAP visible del pedido.")
    group.add_argument("--latest", type=positive_int, help="Lista las ultimas N PurchaseOrders visibles por Service Layer.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    return 0 if run_purchase_order_probe(doc_entry=args.doc_entry, doc_num=args.doc_num, latest=args.latest) else 1


if __name__ == "__main__":
    sys.exit(main())
