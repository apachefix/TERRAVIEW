"""Configuracion central de sociedades SAP y guardias para escrituras.

Los nombres activos de CompanyDB siempre se leen desde ``.env``. La matriz
incluida aqui no selecciona destinos: solo clasifica los destinos conocidos
para impedir que una escritura QA alcance accidentalmente una sociedad PROD.
"""

from decouple import config


SAP_EMPRESA_TERRAMAR = 1
SAP_EMPRESA_SBH = 2
SAP_ENV_QA = "QA"
SAP_ENV_PROD = "PROD"

# Excepcion de seguridad deliberada: estos nombres no configuran conexiones.
# Permiten validar el CompanyDB activo antes de cualquier operacion WRITE.
_WRITE_COMPANY_DB_GUARD = {
    SAP_EMPRESA_TERRAMAR: {
        SAP_ENV_QA: "TESTTERRACHILE",
        SAP_ENV_PROD: "SBOTERRACHILE",
    },
    SAP_EMPRESA_SBH: {
        SAP_ENV_QA: "SBO_TST_SBH_USD",
        SAP_ENV_PROD: "SBO_SBH_USD",
    },
}

_COMPANY_DB_VARIABLE = {
    SAP_EMPRESA_TERRAMAR: "SAP_TERRAMAR_COMPANY_DB",
    SAP_EMPRESA_SBH: "SAP_SBH_COMPANY_DB",
}

_PROFORMA_SERIES_VARIABLE = {
    SAP_EMPRESA_TERRAMAR: "SAP_TERRAMAR_PROFORMA_SERIES",
    SAP_EMPRESA_SBH: "SAP_SBH_PROFORMA_SERIES",
}


class SapConfigError(Exception):
    """Error controlado de configuracion central SAP."""


def _value(name, default=""):
    return str(config(name, default=default)).strip()


def normalize_sap_environment(value=None):
    environment = str(value if value is not None else _value("SAP_ENVIRONMENT")).strip().upper()
    if environment == "PRODUCTION":  # Compatibilidad con configuracion anterior.
        environment = SAP_ENV_PROD
    if environment not in {SAP_ENV_QA, SAP_ENV_PROD}:
        raise SapConfigError("SAP_ENVIRONMENT debe ser exactamente QA o PROD.")
    return environment


def get_sap_company_db(empresa_id, *, for_write=False):
    """Obtiene el CompanyDB central de la empresa y, si escribe, lo protege."""
    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError) as exc:
        raise SapConfigError(f"Empresa SAP no valida: {empresa_id}.") from exc

    variable = _COMPANY_DB_VARIABLE.get(empresa_id)
    if variable is None:
        raise SapConfigError(f"Empresa {empresa_id} no tiene configuracion SAP central.")

    company_db = _value(variable)
    if not company_db:
        raise SapConfigError(f"Falta variable SAP requerida: {variable}.")

    if for_write:
        environment = normalize_sap_environment()
        expected = _WRITE_COMPANY_DB_GUARD[empresa_id][environment]
        if company_db != expected:
            raise SapConfigError(
                f"Destino SAP bloqueado para empresa {empresa_id}: "
                f"SAP_ENVIRONMENT={environment} exige CompanyDB={expected}, "
                f"pero se configuro CompanyDB={company_db}."
            )

    return company_db


def get_sap_proforma_series(empresa_id):
    """Obtiene desde el entorno la serie OPOR de Proformas por empresa."""
    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError) as exc:
        raise SapConfigError(f"Empresa SAP no valida: {empresa_id}.") from exc

    variable = _PROFORMA_SERIES_VARIABLE.get(empresa_id)
    if variable is None:
        raise SapConfigError(f"Empresa {empresa_id} no tiene serie de Proforma SAP.")

    value = _value(variable)
    try:
        series = int(value)
    except (TypeError, ValueError) as exc:
        raise SapConfigError(f"{variable} debe ser un numero entero.") from exc
    if series <= 0:
        raise SapConfigError(f"{variable} debe ser mayor que cero.")
    return series
