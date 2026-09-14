"""Construcción y validación de Draft SAP para despacho SBH (sin envío)."""

from decimal import Decimal

from .models import (
    CAMION_PATIO,
    CITACION_DESPACHO_DETALLE,
    DATO_OPERACION,
)
from .despacho_carga import CargaInvalida, preparar_payloads, validar_ambito
from .sap_despacho import serializar_asignaciones_sap_planificadas


def _datos_operacion(citacion):
    registros = (
        DATO_OPERACION.objects.filter(CI_NID=citacion, SC_NID=citacion.SC_NID)
        .select_related("CAMP_NID")
        .order_by("-id")
    )
    datos = {}
    for dato in registros:
        codigo = getattr(dato.CAMP_NID, "CA_CCODIGO", "")
        if codigo and codigo not in datos:
            datos[codigo] = "" if dato.DO_CVALOR is None else str(dato.DO_CVALOR).strip()
    return datos


def construir_payload_despacho(
    citacion,
    configuracion,
    datos_documento=None,
    camion=None,
    series=None,
    indicator="52",
):
    """Retorna un payload por AbsID, validando invariantes sin tocar SAP.

    ``configuracion`` es la salida de ``validar_configuracion`` y contiene la
    distribución acuerdo → estanque → lotes. No se realiza login, POST, Add ni
    SaveDraft; el resultado es apto para tests y revisión antes del envío.
    """
    validar_ambito(citacion)
    datos_documento = dict(datos_documento or {})
    datos = _datos_operacion(citacion)
    tipo_despacho = str(
        datos_documento.get("REV_TIPO_DESPACHO") or datos.get("REV_TIPO_DESPACHO") or ""
    ).strip()
    tipo_traslado = str(
        datos_documento.get("REV_TIPO_TRASLADO") or datos.get("REV_TIPO_TRASLADO") or ""
    ).strip()
    if tipo_despacho not in {"1", "2", "3"}:
        raise CargaInvalida("REV_TIPO_DESPACHO debe ser 1, 2 o 3.")
    if tipo_traslado not in {str(i) for i in range(1, 8)}:
        raise CargaInvalida("REV_TIPO_TRASLADO debe ser un código entre 1 y 7.")

    camion = camion or CAMION_PATIO.objects.filter(CI_NID=citacion).order_by(
        "-CPA_FFECHAASOCIACION", "-id"
    ).first()
    if camion is not None:
        transportista = str(getattr(camion, "CPA_CTRANSPORTISTA_DECLARADO", "") or "").strip()
        conductor = str(getattr(camion, "CPA_CNOMBRE_CONDUCTOR", "") or "").strip()
        rut_conductor = str(getattr(camion, "CPA_CRUT_CONDUCTOR", "") or "").strip()
        telefono = str(getattr(camion, "CPA_CTELEFONO_CONDUCTOR", "") or "").strip()
        patente = str(getattr(camion, "CPA_CPATENTE", "") or "").strip()
        semi = str(getattr(camion, "CPA_CPATENTE_RAMPLA", "") or "").strip()
    else:
        transportista = str(datos_documento.get("transportista") or datos.get("ING_EMPRESA_TRANSPORTE") or "").strip()
        conductor = str(datos_documento.get("conductor") or datos.get("ING_NOMBRE_CONDUCTOR") or "").strip()
        rut_conductor = str(datos_documento.get("rut_conductor") or datos.get("ING_RUT_CONDUCTOR") or "").strip()
        telefono = str(datos_documento.get("telefono_conductor") or datos.get("ING_TELEFONO_CONDUCTOR") or "").strip()
        patente = str(datos_documento.get("patente") or datos.get("ING_PATENTE") or "").strip()
        semi = str(datos_documento.get("semi") or "").strip()

    detalle = CITACION_DESPACHO_DETALLE.objects.filter(CI_NID=citacion).first()
    snapshots = serializar_asignaciones_sap_planificadas(citacion, detalle)
    snapshot_by_abs = {str(f.get("sap_abs_id")): f for f in snapshots if f.get("sap_abs_id")}
    payloads = preparar_payloads(citacion, configuracion)
    resultado = {}
    for abs_id, payload in payloads.items():
        acuerdo = next(
            (a for a in configuracion.get("acuerdos", []) if int(a.get("sap_abs_id")) == int(abs_id)),
            None,
        )
        if not acuerdo:
            raise CargaInvalida("Payload sin acuerdo SAP de origen.")
        snap = snapshot_by_abs.get(str(abs_id), {})
        card_code = str(
            acuerdo.get("cliente_codigo")
            or snap.get("cliente_codigo")
            or (citacion.SN_NID.SN_CCODIGO_SAP if citacion.SN_NID else "")
            or ""
        ).strip()
        if not card_code:
            raise CargaInvalida("Falta CardCode SAP.")
        payload.update(
            {
                "ReserveInvoice": "tNO",
                "Indicator": str(indicator or "").strip(),
                "U_NXIndTras": tipo_traslado,
                "U_NXTipoDesp": tipo_despacho,
                "U_NXRutTransporte": str(datos_documento.get("rut_transporte") or "").strip(),
                "U_NXNombreTransporte": transportista,
                "U_NXRutChofer": rut_conductor,
                "U_NXNombreChofer": conductor,
                "U_NXTelefonoChofer": telefono,
                "U_NXPatente": patente,
                "U_NXSemi": semi,
                "U_NXOC": str(acuerdo.get("oc_cliente") or snap.get("oc_cliente") or "").strip(),
                "U_NXFechaOC": str(datos_documento.get("fecha_oc") or "").strip(),
                "CardCode": card_code,
                "DocObjectCode": "15",
                "Series": int(series if series is not None else payload.get("Series")),
            }
        )
        doc_date = str(datos_documento.get("doc_date") or "").strip()
        if doc_date:
            payload["DocDate"] = doc_date
        for line in payload.get("DocumentLines", []):
            line.setdefault("U_HCO_NSello", "")
            line.setdefault("U_HCO_DescAG", "")
            line.setdefault("U_NXTicket", "")
            line["AgreementNo"] = int(abs_id)
            batches = line.get("BatchNumbers") or []
            if batches and sum(Decimal(str(b.get("Quantity", 0))) for b in batches) != Decimal(str(line.get("Quantity", 0))):
                raise CargaInvalida("La suma de BatchNumbers debe coincidir con Quantity.")
        resultado[int(abs_id)] = payload
    if not resultado:
        raise CargaInvalida("No existen acuerdos SAP para construir el payload.")
    return resultado

