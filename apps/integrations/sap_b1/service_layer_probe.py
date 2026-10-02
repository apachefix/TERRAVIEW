"""
Archivo de diagnóstico inicial para SAP Business One Service Layer.
No crea documentos, no inserta datos y no modifica SAP.
Solo prueba login, request autenticado y logout.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests import Response
from requests.exceptions import ConnectionError, HTTPError, SSLError, Timeout
from urllib3.exceptions import InsecureRequestWarning

from apps.integrations.sap_b1.sap_config import SapConfigError, get_sap_company_db

try:
    from decouple import config as decouple_config
except ImportError:  # pragma: no cover - fallback for minimal diagnostic envs.
    decouple_config = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for minimal diagnostic envs.
    load_dotenv = None


LOGGER = logging.getLogger("sap_b1.service_layer_probe")


class SapServiceLayerProbeError(Exception):
    """Error controlado del diagnóstico Service Layer."""


@dataclass(frozen=True)
class SapServiceLayerConfig:
    base_url: str
    company_db: str
    username: str
    password: str
    verify_ssl: bool
    timeout: int


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_env_files() -> None:
    if not load_dotenv:
        return

    project_root = Path(__file__).resolve().parents[3]
    for env_path in (project_root / ".env", project_root / "core" / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def get_config_value(name: str, default: str = "") -> str:
    if decouple_config:
        return str(decouple_config(name, default=default)).strip()
    return str(os.getenv(name, default)).strip()


def parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(empresa_id=None, *, for_write=False) -> SapServiceLayerConfig:
    LOGGER.info("Cargando configuracion SAP Service Layer desde variables de entorno.")
    load_env_files()

    base_url = get_config_value("SAP_SL_BASE_URL").rstrip("/")
    try:
        company_db = (
            get_sap_company_db(empresa_id, for_write=for_write)
            if empresa_id is not None
            else get_config_value("SAP_SL_COMPANY_DB")
        )
    except SapConfigError as exc:
        raise SapServiceLayerProbeError(str(exc)) from exc
    username = get_config_value("SAP_SL_USERNAME")
    password = get_config_value("SAP_SL_PASSWORD", "")
    verify_ssl = parse_bool(get_config_value("SAP_SL_VERIFY_SSL", "false"))

    try:
        timeout = int(get_config_value("SAP_SL_TIMEOUT", "30"))
    except ValueError as exc:
        raise SapServiceLayerProbeError("SAP_SL_TIMEOUT debe ser un numero entero de segundos.") from exc

    missing = [
        name
        for name, value in {
            "SAP_SL_BASE_URL": base_url,
            (
                "SAP_TERRAMAR_COMPANY_DB/SAP_SBH_COMPANY_DB"
                if empresa_id is not None
                else "SAP_SL_COMPANY_DB"
            ): company_db,
            "SAP_SL_USERNAME": username,
            "SAP_SL_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise SapServiceLayerProbeError(
            "Faltan variables requeridas: " + ", ".join(missing)
        )

    if not verify_ssl:
        LOGGER.warning("SAP_SL_VERIFY_SSL=false: verificacion SSL desactivada solo para esta prueba.")
        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

    return SapServiceLayerConfig(
        base_url=base_url,
        company_db=company_db,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        timeout=timeout,
    )


class SapServiceLayerClient:
    def __init__(self, config: SapServiceLayerConfig):
        self.config = config
        self.session = requests.Session()
        self.logged_in = False

    def endpoint(self, path: str) -> str:
        return f"{self.config.base_url}/{path.lstrip('/')}"

    def login(self) -> Dict[str, Any]:
        LOGGER.info("Intentando login Service Layer en CompanyDB=%s.", self.config.company_db)
        payload = {
            "CompanyDB": self.config.company_db,
            "UserName": self.config.username,
            "Password": self.config.password,
        }

        response = self._request("POST", "Login", json=payload, diagnostic_context="login")
        LOGGER.info("Login HTTP status: %s.", response.status_code)

        data = self._json_or_error(response, "login")
        response.raise_for_status()
        self.logged_in = True

        has_b1session = bool(self.session.cookies.get("B1SESSION"))
        has_routeid = bool(self.session.cookies.get("ROUTEID"))
        LOGGER.info("Cookie B1SESSION: %s.", "presente" if has_b1session else "ausente")
        LOGGER.info("Cookie ROUTEID: %s.", "presente" if has_routeid else "ausente")
        LOGGER.info("Login exitoso. SessionId recibido: %s.", "presente" if data.get("SessionId") else "ausente")
        return data

    def test_authenticated_request(self) -> Dict[str, Any]:
        LOGGER.info("Ejecutando prueba autenticada liviana: BusinessPartners top 1.")
        response = self._request(
            "GET",
            "BusinessPartners?$select=CardCode,CardName&$top=1",
            diagnostic_context="prueba autenticada",
        )
        LOGGER.info("Prueba autenticada HTTP status: %s.", response.status_code)

        data = self._json_or_error(response, "prueba autenticada")
        response.raise_for_status()

        values = data.get("value", [])
        LOGGER.info("Consulta autenticada respondio OK. Registros recibidos: %s.", len(values) if isinstance(values, list) else "desconocido")
        if isinstance(values, list) and values:
            first = values[0]
            LOGGER.info(
                "Primer BusinessPartner recibido: CardCode=%s | CardName=%s.",
                first.get("CardCode", ""),
                first.get("CardName", ""),
            )
        return data

    def get_json(self, path: str, diagnostic_context: str = "GET autenticado") -> Dict[str, Any]:
        response = self._request("GET", path, diagnostic_context=diagnostic_context)
        data = self._json_or_error(response, diagnostic_context)
        response.raise_for_status()
        return data

    def post_json(self, path: str, payload: Dict[str, Any], diagnostic_context: str = "POST autenticado") -> Dict[str, Any]:
        response = self._request("POST", path, json=payload, diagnostic_context=diagnostic_context)
        data = self._json_or_error(response, diagnostic_context)
        response.raise_for_status()
        return {
            "status_code": response.status_code,
            "data": data,
        }

    def post_draft(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post_json("Drafts", payload, diagnostic_context="POST Drafts")

    def post_purchase_delivery_note(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post_json(
            "PurchaseDeliveryNotes",
            payload,
            diagnostic_context="POST PurchaseDeliveryNotes",
        )

    def post_stock_transfer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post_json(
            "StockTransfers",
            payload,
            diagnostic_context="POST StockTransfers",
        )

    def post_inventory_transfer_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post_json(
            "InventoryTransferRequests",
            payload,
            diagnostic_context="POST InventoryTransferRequests",
        )

    def patch_json(self, path: str, payload: Dict[str, Any], diagnostic_context: str = "PATCH autenticado", headers=None) -> Dict[str, Any]:
        response = self._request("PATCH", path, json=payload, headers=headers, diagnostic_context=diagnostic_context)
        if response.status_code >= 400:
            self._json_or_error(response, diagnostic_context)
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {"raw": response.text}
        response.raise_for_status()
        return {
            "status_code": response.status_code,
            "data": data,
        }

    def patch_draft(self, docentry: int, payload: Dict[str, Any], *, replace_collections: bool = False) -> Dict[str, Any]:
        headers = {"B1S-ReplaceCollectionsOnPatch": "true"} if replace_collections else None
        return self.patch_json(
            f"Drafts({int(docentry)})", payload,
            diagnostic_context=f"PATCH Drafts({int(docentry)})", headers=headers,
        )

    def logout(self) -> None:
        if not self.logged_in:
            LOGGER.info("Logout omitido: no hubo login exitoso.")
            return

        LOGGER.info("Ejecutando logout Service Layer.")
        try:
            response = self._request("POST", "Logout", diagnostic_context="logout")
            LOGGER.info("Logout HTTP status: %s.", response.status_code)
            response.raise_for_status()
            LOGGER.info("Logout ejecutado correctamente.")
        except Exception as exc:  # Logout must not hide the probe result.
            LOGGER.warning("No fue posible completar logout: %s.", exc)
        finally:
            self.logged_in = False

    def _request(self, method: str, path: str, diagnostic_context: str, **kwargs: Any) -> Response:
        try:
            return self.session.request(
                method,
                self.endpoint(path),
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
                **kwargs,
            )
        except SSLError as exc:
            raise SapServiceLayerProbeError(
                f"Error SSL durante {diagnostic_context}. Revise certificado o SAP_SL_VERIFY_SSL."
            ) from exc
        except Timeout as exc:
            raise SapServiceLayerProbeError(
                f"Timeout durante {diagnostic_context}. Revise red, puerto o SAP_SL_TIMEOUT."
            ) from exc
        except ConnectionError as exc:
            raise SapServiceLayerProbeError(
                f"Error de red durante {diagnostic_context}. Revise URL, DNS, Service Layer detenido o puerto bloqueado."
            ) from exc

    @staticmethod
    def _json_or_error(response: Response, diagnostic_context: str) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise SapServiceLayerProbeError(
                f"Respuesta JSON invalida en {diagnostic_context}. Status={response.status_code}."
            ) from exc

        if response.status_code >= 400:
            message = SapServiceLayerClient._service_layer_error_message(data)
            raise HTTPError(
                f"Error HTTP Service Layer en {diagnostic_context}. Status={response.status_code}. Detalle={message}",
                response=response,
            )
        return data

    @staticmethod
    def _service_layer_error_message(data: Dict[str, Any]) -> str:
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, dict):
                return str(message.get("value") or message)
            if message:
                return str(message)
            return str(error)
        return str(data)


def run_probe() -> bool:
    configure_logging()
    client: Optional[SapServiceLayerClient] = None

    try:
        config = load_config()
        client = SapServiceLayerClient(config)
        client.login()
        client.test_authenticated_request()
        LOGGER.info("Resultado final: prueba Service Layer exitosa.")
        return True
    except HTTPError as exc:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else "desconocido"
        if status in {401, 403}:
            LOGGER.error("Error de login/permisos Service Layer: %s", exc)
        else:
            LOGGER.error("Error HTTP Service Layer: %s", exc)
        LOGGER.error("Posibles causas: credenciales, CompanyDB, permisos, URL o servicio SAP.")
        return False
    except SapServiceLayerProbeError as exc:
        LOGGER.error("Diagnostico controlado: %s", exc)
        LOGGER.error("Posibles causas: URL incorrecta, Service Layer detenido, puerto bloqueado, SSL, red o variables incompletas.")
        return False
    except Exception as exc:
        LOGGER.exception("Error inesperado durante prueba Service Layer: %s", exc)
        return False
    finally:
        if client:
            client.logout()


if __name__ == "__main__":
    sys.exit(0 if run_probe() else 1)
