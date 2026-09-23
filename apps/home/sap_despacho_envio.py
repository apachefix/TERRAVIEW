"""Envío idempotente de Drafts SAP para la carga multiacuerdo SBH."""

import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from requests.exceptions import HTTPError

from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient, load_config

from .despacho_carga import (
    CargaInvalida,
    _citacion_mantiene_reserva,
    catalogo_acuerdo,
    validar_configuracion,
)
from .models import (
    CITACION_DESPACHO_ACUERDO_LOTE,
    CITACION_DESPACHO_CARGA,
    CITACION_DESPACHO_DRAFT_SAP,
    EMPRESA,
)
from .sap_despacho_documentos import reserva_acuerdo_liberada, verificacion_sap_persistida
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


MENSAJE_CONTEXTO_OBSOLETO = (
    "La disponibilidad de los lotes cambió mientras se preparaba este despacho. "
    "Se actualizaron documentos SAP relacionados con el stock seleccionado. "
    "Debe volver a seleccionar los lotes antes de continuar."
)


class ContextoCargaObsoleto(CargaInvalida):
    def __init__(self, diagnosticos=None):
        super().__init__(MENSAJE_CONTEXTO_OBSOLETO)
        self.diagnosticos = diagnosticos or []


def _decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def configuracion_persistida(citacion, *, carga=None, catalogos=None):
    """Reconstruye la entrada y repite validación SAP/FEFO antes del envío."""
    try:
        carga = carga or CITACION_DESPACHO_CARGA.objects.prefetch_related(
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
    return validar_configuracion(citacion, data, catalogos=catalogos)


def _fecha_verificacion(verificacion):
    fecha = parse_datetime(str(verificacion.get('fecha_iso') or ''))
    if fecha and timezone.is_naive(fecha):
        fecha = timezone.make_aware(fecha)
    return fecha


def _catalogos_y_stock_actual(citacion, carga):
    catalogos = {}
    stocks = {}
    for acuerdo in carga.acuerdos.all():
        abs_id = int(acuerdo.sap_abs_id)
        if abs_id in catalogos:
            continue
        catalogo = catalogo_acuerdo(citacion, abs_id)
        catalogos[abs_id] = catalogo
        for item_code, filas in catalogo.get('stocks', {}).items():
            destino = stocks.setdefault(str(item_code), [])
            for fila in filas:
                copia = dict(fila)
                copia['stock'] = copia.get('stock_sap', copia.get('stock'))
                destino.append(copia)
    return catalogos, stocks


def _indice_stock(catalogos):
    indice = {}
    for catalogo in catalogos.values():
        for item_code, filas in catalogo.get('stocks', {}).items():
            for fila in filas:
                clave = (
                    str(fila.get('item_code') or item_code),
                    str(fila.get('warehouse_code') or ''),
                    str(fila.get('batch_number') or ''),
                )
                indice[clave] = {
                    'stock_sap': _decimal(fila.get('stock_sap', fila.get('stock'))),
                    'reservado': _decimal(fila.get('reservado')),
                    'disponible': _decimal(fila.get('disponible', fila.get('stock'))),
                }
    return indice


def validar_contexto_pre_draft(citacion, carga):
    """Revalida stock/reservas y detecta cambios posteriores al guardado."""
    catalogos, stocks_actuales = _catalogos_y_stock_actual(citacion, carga)
    stock_por_clave = _indice_stock(catalogos)
    lotes_actuales = list(
        CITACION_DESPACHO_ACUERDO_LOTE.objects
        .select_related('estanque__acuerdo')
        .filter(estanque__acuerdo__carga=carga)
    )
    claves_actuales = {
        (
            str(lote.estanque.item_code),
            str(lote.estanque.warehouse_code),
            str(lote.batch_number),
        )
        for lote in lotes_actuales
    }
    diagnosticos = []

    for lote in lotes_actuales:
        clave = (
            str(lote.estanque.item_code),
            str(lote.estanque.warehouse_code),
            str(lote.batch_number),
        )
        actual = stock_por_clave.get(clave)
        stock_actual = actual['stock_sap'] if actual else Decimal('0')
        if stock_actual != _decimal(lote.stock_snapshot):
            diagnosticos.append({
                'motivo': 'stock SAP modificado despues del ultimo guardado',
                'lote': clave[2],
                'item_code': clave[0],
                'warehouse_code': clave[1],
                'stock_guardado': str(lote.stock_snapshot),
                'stock_actual': str(stock_actual),
                'disponibilidad_actual': str(actual['disponible'] if actual else 0),
            })

    externos = (
        CITACION_DESPACHO_ACUERDO_LOTE.objects
        .select_related(
            'estanque__acuerdo__carga__CI_NID',
            'estanque__acuerdo__draft',
        )
        .exclude(estanque__acuerdo__carga=carga)
        .filter(estanque__item_code__in={clave[0] for clave in claves_actuales})
    )
    for lote in externos:
        clave = (
            str(lote.estanque.item_code),
            str(lote.estanque.warehouse_code),
            str(lote.batch_number),
        )
        if clave not in claves_actuales:
            continue
        acuerdo = lote.estanque.acuerdo
        carga_externa = acuerdo.carga
        try:
            draft = acuerdo.draft
        except CITACION_DESPACHO_DRAFT_SAP.DoesNotExist:
            draft = None
        liberada = bool(
            draft and reserva_acuerdo_liberada(draft, stocks=stocks_actuales)
        )
        verificacion = verificacion_sap_persistida(draft) if draft else {}
        fecha_verificacion = _fecha_verificacion(verificacion)
        if fecha_verificacion and fecha_verificacion > carga.actualizado and liberada:
            actual = stock_por_clave.get(clave, {})
            diagnosticos.append({
                'motivo': 'reserva externa modificada despues del ultimo guardado',
                'lote': clave[2],
                'item_code': clave[0],
                'warehouse_code': clave[1],
                'citacion_relacionada': carga_externa.CI_NID_id,
                'acuerdo_relacionado': acuerdo.numero_acuerdo,
                'draft_relacionado': draft.docentry,
                'carga_actual_guardada': carga.actualizado.isoformat(),
                'verificacion_sap_externa': fecha_verificacion.isoformat(),
                'stock_actual': str(actual.get('stock_sap', '')),
                'disponibilidad_actual': str(actual.get('disponible', '')),
            })
        elif (
            carga_externa.actualizado > carga.actualizado
            and _citacion_mantiene_reserva(carga_externa.CI_NID)
            and not liberada
        ):
            actual = stock_por_clave.get(clave, {})
            diagnosticos.append({
                'motivo': 'reserva externa creada o modificada despues del ultimo guardado',
                'lote': clave[2],
                'item_code': clave[0],
                'warehouse_code': clave[1],
                'citacion_relacionada': carga_externa.CI_NID_id,
                'acuerdo_relacionado': acuerdo.numero_acuerdo,
                'carga_actual_guardada': carga.actualizado.isoformat(),
                'carga_externa_actualizada': carga_externa.actualizado.isoformat(),
                'stock_actual': str(actual.get('stock_sap', '')),
                'disponibilidad_actual': str(actual.get('disponible', '')),
            })

    if diagnosticos:
        LOGGER.warning(
            'VALIDACION_PRE_DRAFT_FALLIDA citacion=%s version=%s diagnosticos=%s',
            citacion.pk,
            carga.version,
            json.dumps(diagnosticos, ensure_ascii=False, default=str),
        )
        raise ContextoCargaObsoleto(diagnosticos)
    try:
        return configuracion_persistida(
            citacion,
            carga=carga,
            catalogos=catalogos,
        )
    except CargaInvalida as exc:
        diagnosticos = [{'motivo': 'revalidacion operacional fallida', 'detalle': str(exc)}]
        LOGGER.warning(
            'VALIDACION_PRE_DRAFT_FALLIDA citacion=%s version=%s diagnosticos=%s',
            citacion.pk,
            carga.version,
            json.dumps(diagnosticos, ensure_ascii=False, default=str),
        )
        raise ContextoCargaObsoleto(diagnosticos) from exc


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


def _crear_borradores_sap_despacho(
    citacion, usuario, config_operacional, *, client_factory=SapServiceLayerClient,
):
    """Valida, construye y crea un Draft por acuerdo, omitiendo los ya creados."""
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


@transaction.atomic
def _crear_borradores_bajo_bloqueo(
    citacion, usuario, *, client_factory=SapServiceLayerClient,
):
    """Mantiene el mutex desde la validacion hasta finalizar los intentos SAP."""
    EMPRESA.objects.select_for_update().get(pk=2)
    carga = (
        CITACION_DESPACHO_CARGA.objects.select_for_update()
        .prefetch_related('acuerdos__estanques__lotes')
        .get(CI_NID=citacion)
    )
    list(
        CITACION_DESPACHO_DRAFT_SAP.objects.select_for_update()
        .filter(acuerdo__carga=carga)
        .order_by('acuerdo__orden', 'id')
    )
    config_operacional = validar_contexto_pre_draft(citacion, carga)
    try:
        resultados = _crear_borradores_sap_despacho(
            citacion,
            usuario,
            config_operacional,
            client_factory=client_factory,
        )
    except EnvioDraftSapError as exc:
        # El error se relanza fuera del atomic para conservar estados de
        # conciliacion (CREADO/ERROR/INCIERTO) ya registrados localmente.
        return None, exc
    return resultados, None


def crear_borradores_sap_despacho(citacion, usuario, *, client_factory=SapServiceLayerClient):
    resultados, error = _crear_borradores_bajo_bloqueo(
        citacion,
        usuario,
        client_factory=client_factory,
    )
    if error:
        raise error
    return resultados
