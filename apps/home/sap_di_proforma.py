"""Conexion segura SAP Business One DI API para autorizacion de Proformas.

SAP_ENVIRONMENT define exclusivamente el ambiente permitido para escrituras
SAP controladas por este modulo. No selecciona ni redirige conexiones HANA de
solo lectura, cuya CompanyDB se configura de forma independiente.
"""

import logging
from dataclasses import dataclass

from decouple import config
from win32com.client import dynamic

from apps.integrations.sap_b1.sap_config import (
    SAP_EMPRESA_SBH,
    SAP_EMPRESA_TERRAMAR,
    SapConfigError,
    get_sap_company_db,
    get_sap_proforma_series,
    normalize_sap_environment,
)


logger = logging.getLogger(__name__)

OPOR = 22


class SapDiApiError(Exception):
    """Error controlado de configuracion o conexion SAP DI API."""


@dataclass(frozen=True)
class SapDiConfig:
    empresa_id: int
    environment: str
    server: str
    company_db: str
    db_server_type: int
    use_trusted: bool
    username: str
    password: str
    license_server: str


def _value(name, default=""):
    return str(config(name, default=default)).strip()


def _bool_value(name, default=False):
    try:
        return config(name, default=default, cast=bool)
    except (TypeError, ValueError) as exc:
        raise SapDiApiError(f"{name} debe ser True o False.") from exc


def _int_value(name):
    value = _value(name)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SapDiApiError(f"{name} debe ser un numero entero.") from exc


def _redact(message, sap_config):
    safe_message = str(message or "Error SAP sin detalle")
    if sap_config.password:
        safe_message = safe_message.replace(sap_config.password, "******")
    return safe_message


def get_sap_di_config(empresa_id):
    """Carga y valida la configuracion DI API de una empresa desde el entorno."""
    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError) as exc:
        raise SapDiApiError(f"Empresa SAP no valida: {empresa_id}.") from exc

    try:
        environment = normalize_sap_environment()
        company_db = get_sap_company_db(empresa_id, for_write=True)
    except SapConfigError as exc:
        raise SapDiApiError(str(exc)) from exc

    prefixes = {
        SAP_EMPRESA_TERRAMAR: "SAP_TERRAMAR",
        SAP_EMPRESA_SBH: "SAP_SBH",
    }
    prefix = prefixes.get(empresa_id)
    if prefix is None:
        raise SapDiApiError(f"Empresa {empresa_id} no tiene configuracion SAP DI API.")

    required_names = {
        "server": f"{prefix}_SERVER",
        "db_server_type": f"{prefix}_DB_SERVER_TYPE",
        "username": f"{prefix}_USER",
        "password": f"{prefix}_PASSWORD",
    }

    values = {key: _value(name) for key, name in required_names.items()}
    missing = [name for key, name in required_names.items() if not values[key]]
    if missing:
        raise SapDiApiError(
            "Faltan variables SAP DI API requeridas: " + ", ".join(missing)
        )

    # SLD / License Server SAP Business One
    license_server = _value(f"{prefix}_LICENSE_SERVER")

    sap_config = SapDiConfig(
        empresa_id=empresa_id,
        environment=environment,
        server=values["server"],
        company_db=company_db,
        db_server_type=_int_value(required_names["db_server_type"]),
        use_trusted=_bool_value(f"{prefix}_USE_TRUSTED", default=False),
        username=values["username"],
        password=values["password"],
        license_server=license_server,
    )

    return sap_config

def disconnect_sap_company(company):
    """Desconecta una instancia DI API solo si llego a conectarse."""
    if company is None:
        return
    try:
        if bool(getattr(company, "Connected", False)):
            company.Disconnect()
    except Exception:
        logger.error("No fue posible desconectar la sesion SAP DI API.")


def validate_sap_di_company(company, empresa_id):
    """Revalida el destino real conectado antes de crear un objeto SAP."""
    sap_config = get_sap_di_config(empresa_id)
    connected_company_db = str(getattr(company, "CompanyDB", "") or "").strip()
    if connected_company_db != sap_config.company_db:
        disconnect_sap_company(company)
        raise SapDiApiError(
            "Conexion SAP DI API rechazada: la CompanyDB conectada "
            f"({connected_company_db or '[vacia]'}) no coincide con la configurada "
            f"({sap_config.company_db})."
        )
    return sap_config


def sapConnect(empresa_id):
    """Crea una conexion DI API nueva y aislada para la empresa indicada."""
    sap_config = get_sap_di_config(empresa_id)

    logger.info(
        "SAP DI API autorizacion Proforma empresa_id=%s environment=%s "
        "server=%s company_db=%s",
        sap_config.empresa_id,
        sap_config.environment,
        sap_config.server,
        sap_config.company_db,
    )

    company = None

    try:
        company = dynamic.Dispatch("SAPbobsCOM.Company")

        company.Server = sap_config.server
        company.CompanyDB = sap_config.company_db
        company.DbServerType = sap_config.db_server_type
        company.UseTrusted = sap_config.use_trusted
        company.UserName = sap_config.username
        company.Password = sap_config.password

        # SLD / License Server SAP Business One
        if sap_config.license_server:
            company.LicenseServer = sap_config.license_server

        result = company.Connect()

        if result != 0:
            error_code, error_message = company.GetLastError()
            raise SapDiApiError(
                f"No fue posible conectar a SAP DI API. Codigo={error_code}. "
                f"Detalle={_redact(error_message, sap_config)}"
            )

        validate_sap_di_company(company, empresa_id)

        return company

    except SapDiApiError:
        disconnect_sap_company(company)
        raise

    except Exception as exc:
        disconnect_sap_company(company)
        raise SapDiApiError(
            f"Error inesperado al conectar a SAP DI API: {_redact(exc, sap_config)}"
        ) from exc