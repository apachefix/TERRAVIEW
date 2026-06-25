"""
Diagnostico de lectura de Orden de Compra SAP desde una citacion local.
No crea documentos, no inserta datos y no modifica SAP ni la BD local.
Solo lee la citacion, obtiene DocEntry SAP, consulta PurchaseOrders y ejecuta logout.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from requests import HTTPError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402

django.setup()

from apps.home.models import CITACION, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION  # noqa: E402
from apps.integrations.sap_b1.purchase_order_probe import (  # noqa: E402
    fetch_purchase_order,
    log_purchase_order,
    positive_int,
)
from apps.integrations.sap_b1.service_layer_probe import (  # noqa: E402
    SapServiceLayerClient,
    SapServiceLayerProbeError,
    configure_logging,
    load_config,
)


LOGGER = logging.getLogger("sap_b1.citation_purchase_order_probe")


def clean_int_candidate(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d+", text.replace(".", ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def get_citation(citacion_id: int) -> CITACION:
    return CITACION.objects.select_related("EP_NID", "PL_NID", "SC_NID", "SN_NID", "PRO_NID").get(pk=citacion_id)


def latest_operational_detail(citacion: CITACION) -> Optional[CITACION_DETALLE_OPERACIONAL]:
    return CITACION_DETALLE_OPERACIONAL.objects.filter(CI_NID=citacion).order_by("-id").first()


def detail_candidates(detalle: Optional[CITACION_DETALLE_OPERACIONAL]) -> List[Tuple[str, Any]]:
    if not detalle:
        return []
    return [
        ("CITACION_DETALLE_OPERACIONAL.CDO_CDOCENTRY", detalle.CDO_CDOCENTRY),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CSAP_OPOR_ID", detalle.CDO_CSAP_OPOR_ID),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CPEDIDO_SAP", detalle.CDO_CPEDIDO_SAP),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CCODIGO_SAP", detalle.CDO_CCODIGO_SAP),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CINSUMO", detalle.CDO_CINSUMO),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CPROVEEDOR_CODIGO", detalle.CDO_CPROVEEDOR_CODIGO),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CPRODUCTOR", detalle.CDO_CPRODUCTOR),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CBL_CONTENEDOR", detalle.CDO_CBL_CONTENEDOR),
        ("CITACION_DETALLE_OPERACIONAL.CDO_NCANTIDAD_DISPONIBLE", detalle.CDO_NCANTIDAD_DISPONIBLE),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CALMACEN_DESTINO", detalle.CDO_CALMACEN_DESTINO),
        ("CITACION_DETALLE_OPERACIONAL.CDO_CESTANQUE_DESTINO", detalle.CDO_CESTANQUE_DESTINO),
    ]


def dato_operacion_candidates(citacion: CITACION) -> List[Tuple[str, Any]]:
    registros = DATO_OPERACION.objects.filter(CI_NID=citacion).select_related("CAMP_NID").order_by("-id")
    candidates: List[Tuple[str, Any]] = []
    keywords = ("DOCENTRY", "OPOR", "PEDIDO", "SAP", "BL", "LOTE", "CONTENEDOR", "CISTERNA", "ESTANQUE")
    for dato in registros[:200]:
        codigo = dato.CAMP_NID.CA_CCODIGO if dato.CAMP_NID else ""
        etiqueta = dato.CAMP_NID.CA_CETIQUETA if dato.CAMP_NID else ""
        value = str(dato.DO_CVALOR or "").strip()
        hay_match = any(keyword in str(codigo or "").upper() for keyword in keywords)
        hay_match = hay_match or any(keyword in str(etiqueta or "").upper() for keyword in keywords)
        if hay_match and value:
            candidates.append((f"DATO_OPERACION.{codigo or etiqueta or dato.id}", value))
    return candidates


def log_local_candidates(citacion: CITACION, detalle: Optional[CITACION_DETALLE_OPERACIONAL]) -> None:
    LOGGER.info("========== CITACION LOCAL ==========")
    LOGGER.info("Citacion: %s", citacion.id)
    LOGGER.info("Empresa: %s", citacion.EP_NID_id)
    LOGGER.info("Planificacion: %s", citacion.PL_NID_id)
    LOGGER.info("Secuencia: %s", citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else "")
    LOGGER.info("Cliente: %s", citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else "")
    LOGGER.info("Proveedor local: %s", citacion.PRO_NID.SN_CRAZONSOCIAL if citacion.PRO_NID else "")

    LOGGER.info("========== CANDIDATOS SAP EN DETALLE OPERACIONAL ==========")
    if not detalle:
        LOGGER.warning("No existe CITACION_DETALLE_OPERACIONAL para la citacion.")
    for label, value in detail_candidates(detalle):
        LOGGER.info("%s: %s", label, value if value not in [None, ""] else "")

    dato_candidates = dato_operacion_candidates(citacion)
    LOGGER.info("========== CANDIDATOS SAP EN DATO_OPERACION ==========")
    if not dato_candidates:
        LOGGER.info("Sin candidatos relevantes en DATO_OPERACION.")
    for label, value in dato_candidates:
        LOGGER.info("%s: %s", label, value)


def resolve_doc_entry(citacion: CITACION, detalle: Optional[CITACION_DETALLE_OPERACIONAL]) -> Optional[int]:
    for label, value in detail_candidates(detalle):
        if label.endswith("CDO_CDOCENTRY") or label.endswith("CDO_CSAP_OPOR_ID"):
            candidate = clean_int_candidate(value)
            if candidate:
                LOGGER.info("DocEntry candidato obtenido desde %s: %s", label, candidate)
                return candidate

    for label, value in dato_operacion_candidates(citacion):
        if "DOCENTRY" in label.upper() or "OPOR" in label.upper():
            candidate = clean_int_candidate(value)
            if candidate:
                LOGGER.info("DocEntry candidato obtenido desde %s: %s", label, candidate)
                return candidate
    return None


def expected_doc_entry_for(citacion_id: int, explicit_expected: Optional[int]) -> Optional[int]:
    if explicit_expected:
        return explicit_expected
    if citacion_id == 38555:
        return 6211
    return None


def run_citation_purchase_order_probe(citacion_id: int, expected_doc_entry: Optional[int] = None) -> bool:
    configure_logging()
    client: Optional[SapServiceLayerClient] = None
    try:
        citacion = get_citation(citacion_id)
        detalle = latest_operational_detail(citacion)
        log_local_candidates(citacion, detalle)

        doc_entry = resolve_doc_entry(citacion, detalle)
        expected = expected_doc_entry_for(citacion_id, expected_doc_entry)
        if not doc_entry:
            LOGGER.error("No se encontro DocEntry SAP para la citacion %s", citacion_id)
            return False
        if expected and doc_entry == expected:
            LOGGER.info("DocEntry SAP confirmado para citacion %s: %s", citacion_id, doc_entry)
        elif expected and doc_entry != expected:
            LOGGER.warning("DocEntry encontrado distinto al esperado: encontrado=%s, esperado=%s", doc_entry, expected)
        else:
            LOGGER.info("DocEntry SAP encontrado para citacion %s: %s", citacion_id, doc_entry)

        config = load_config()
        client = SapServiceLayerClient(config)
        client.login()
        purchase_order = fetch_purchase_order(client, doc_entry)
        log_purchase_order(purchase_order)
        LOGGER.info("Resultado final: citacion=%s DocEntry=%s consultado correctamente.", citacion_id, doc_entry)
        return True
    except CITACION.DoesNotExist:
        LOGGER.error("Citacion %s no encontrada en BD local.", citacion_id)
        return False
    except HTTPError as exc:
        LOGGER.error("Error HTTP Service Layer al consultar OC desde citacion: %s", exc)
        return False
    except SapServiceLayerProbeError as exc:
        LOGGER.error("Diagnostico controlado: %s", exc)
        return False
    except Exception as exc:
        LOGGER.exception("Error inesperado durante probe de citacion: %s", exc)
        return False
    finally:
        if client:
            client.logout()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta una Orden de Compra SAP desde el DocEntry asociado a una citacion local.")
    parser.add_argument("--citacion", required=True, type=positive_int, help="ID de citacion local.")
    parser.add_argument("--expected-doc-entry", type=positive_int, default=None, help="DocEntry esperado opcional para validacion.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    ok = run_citation_purchase_order_probe(args.citacion, args.expected_doc_entry)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
