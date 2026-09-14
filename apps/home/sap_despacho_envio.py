"""Envío idempotente de Drafts SAP para la carga multiacuerdo SBH."""

import json
import logging

from django.db import transaction
from requests.exceptions import HTTPError

from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient, load_config

from .despacho_carga import CargaInvalida, validar_configuracion
from .models import (
    CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DRAFT_SAP,
)
from .sap_despacho_payload import construir_payload_despacho


LOGGER = logging.getLogger(__name__)


def _imprimir_log_sap(evento, **contexto):
    """Replica el JSON legible que Recepción SBH muestra en la terminal."""
    print(f"\n[Borrador SAP][Despacho SBH][{evento}]")
    print(json.dumps(contexto, indent=2, ensure_ascii=False, default=str))


class EnvioDraftSapError(RuntimeError):
    def __init__(self, message, *, acuerdo=None, estado=None):
        super().__init__(message)
        self.acuerdo = acuerdo
        self.estado = estado


def configuracion_persistida(citacion):
    """Reconstruye la entrada y repite validación SAP/FEFO antes del envío."""
    try:
        carga = CITACION_DESPACHO_CARGA.objects.prefetch_related(
            "acuerdos__estanques__lotes"
        ).get(CI_NID=citacion)
    except CITACION_DESPACHO_CARGA.DoesNotExist as exc:
        raise CargaInvalida("Debe guardar la distribución operacional antes de avanzar.") from exc
    data = {
        "cantidad_total": str(carga.cantidad_total),
        "zona_carga": carga.zona_carga,
        "acuerdos": [],
    }
    for acuerdo in carga.acuerdos.all():
        raw_acuerdo = {
            "sap_abs_id": acuerdo.sap_abs_id,
            "cantidad": str(acuerdo.cantidad),
            "estanques": [],
        }
        for estanque in acuerdo.estanques.all():
            raw_acuerdo["estanques"].append(
                {
                    "warehouse_code": estanque.warehouse_code,
                    "item_code": estanque.item_code,
                    "linea_acuerdo": estanque.linea_acuerdo,
                    "cantidad": str(estanque.cantidad),
                    "lotes": [
                        {"batch_number": lote.batch_number, "cantidad": str(lote.cantidad)}
                        for lote in estanque.lotes.all()
                    ],
                }
            )
        data["acuerdos"].append(raw_acuerdo)
    return validar_configuracion(citacion, data)


def borradores_creados(citacion):
    drafts = CITACION_DESPACHO_DRAFT_SAP.objects.filter(acuerdo__carga__CI_NID=citacion)
    return drafts.exists() and not drafts.exclude(estado="CREADO").exists() and not drafts.filter(docentry="").exists()


def _error_sap_legible(exc):
    if isinstance(exc, HTTPError) and exc.response is not None:
        try:
            data = exc.response.json()
        except ValueError:
            data = {}
        error = data.get("error", {}) if isinstance(data, dict) else {}
        message = error.get("message", {}) if isinstance(error, dict) else {}
        if isinstance(message, dict):
            return str(message.get("value") or "").strip()
        if message:
            return str(message).strip()
    return str(exc).strip()


def crear_borradores_sap_despacho(citacion, usuario, *, client_factory=SapServiceLayerClient):
    """Valida, construye y crea un Draft por acuerdo, omitiendo los ya creados."""
    config_operacional = configuracion_persistida(citacion)
    payloads = construir_payload_despacho(citacion, config_operacional)
    client = None
    resultados = []
    try:
        for abs_id, payload in payloads.items():
            error_pendiente = None
            post_iniciado = False
            with transaction.atomic():
                draft = (
                    CITACION_DESPACHO_DRAFT_SAP.objects.select_for_update()
                    .select_related("acuerdo")
                    .get(acuerdo__carga__CI_NID=citacion, acuerdo__sap_abs_id=abs_id)
                )
                if draft.estado == "CREADO" and draft.docentry:
                    _imprimir_log_sap(
                        "Ya existente, no se reenvía",
                        citacion=citacion.pk,
                        acuerdo_abs_id=abs_id,
                        endpoint="/Drafts",
                        estado=draft.estado,
                        DocEntry=draft.docentry,
                        DocNum=draft.docnum,
                    )
                    resultados.append(
                        {"sap_abs_id": abs_id, "docentry": draft.docentry, "docnum": draft.docnum, "reutilizado": True}
                    )
                    continue
                if draft.estado in {"ENVIANDO", "INCIERTO"}:
                    raise EnvioDraftSapError(
                        f"El borrador SAP del acuerdo {draft.acuerdo.numero_acuerdo} requiere conciliación antes de reintentar.",
                        acuerdo=draft.acuerdo.numero_acuerdo,
                        estado=draft.estado,
                    )
                draft.estado = "ENVIANDO"
                draft.payload = payload
                draft.error = ""
                draft.intentos += 1
                draft.save(update_fields=["estado", "payload", "error", "intentos", "actualizado"])
                try:
                    if client is None:
                        client = client_factory(load_config(citacion.EP_NID_id, for_write=True))
                        client.login()
                    _imprimir_log_sap(
                        "Enviar",
                        citacion=citacion.pk,
                        acuerdo_abs_id=abs_id,
                        endpoint="/Drafts",
                        payload=payload,
                    )
                    post_iniciado = True
                    response = client.post_draft(payload)
                    data = response.get("data") or {}
                    docentry = str(data.get("DocEntry") or data.get("docentry") or "").strip()
                    docnum = str(data.get("DocNum") or data.get("docnum") or "").strip()
                    if not docentry:
                        raise EnvioDraftSapError("SAP respondió sin DocEntry para el borrador.")
                    _imprimir_log_sap(
                        "Respuesta SAP",
                        citacion=citacion.pk,
                        acuerdo_abs_id=abs_id,
                        endpoint="/Drafts",
                        status_http=response.get("status_code"),
                        estado="CREADO",
                        DocEntry=docentry,
                        DocNum=docnum,
                    )
                    draft.estado = "CREADO"
                    draft.docentry = docentry
                    draft.docnum = docnum
                    draft.respuesta = data
                    draft.error = ""
                    draft.save(update_fields=["estado", "docentry", "docnum", "respuesta", "error", "actualizado"])
                    resultados.append(
                        {"sap_abs_id": abs_id, "docentry": docentry, "docnum": docnum, "reutilizado": False}
                    )
                except Exception as exc:
                    status = exc.response.status_code if isinstance(exc, HTTPError) and exc.response is not None else None
                    sap_error = {}
                    if isinstance(exc, HTTPError) and exc.response is not None:
                        try:
                            sap_error = exc.response.json()
                        except ValueError:
                            sap_error = {"message": exc.response.text}
                    if not sap_error:
                        sap_error = {"message": str(exc)}
                    draft.estado = "ERROR" if not post_iniciado or (status is not None and 400 <= status < 500) else "INCIERTO"
                    _imprimir_log_sap(
                        "Error SAP",
                        citacion=citacion.pk,
                        acuerdo_abs_id=abs_id,
                        endpoint="/Drafts",
                        status_http=status,
                        estado=draft.estado,
                        payload=payload,
                        sap_error=sap_error,
                        mensaje_sap=_error_sap_legible(exc),
                    )
                    draft.error = _error_sap_legible(exc)[:2000]
                    draft.save(update_fields=["estado", "error", "actualizado"])
                    error_pendiente = EnvioDraftSapError(
                        f"No fue posible crear el borrador SAP del acuerdo {draft.acuerdo.numero_acuerdo}.",
                        acuerdo=draft.acuerdo.numero_acuerdo,
                        estado=draft.estado,
                    )
                    LOGGER.exception(
                        "Error creando Draft SAP despacho citacion=%s acuerdo_abs_id=%s estado=%s",
                        citacion.pk,
                        abs_id,
                        draft.estado,
                    )
            if error_pendiente:
                raise error_pendiente
    finally:
        if client is not None:
            client.logout()
    if not borradores_creados(citacion):
        raise EnvioDraftSapError("No todos los borradores SAP quedaron creados; la citación no puede avanzar.")
    return resultados

