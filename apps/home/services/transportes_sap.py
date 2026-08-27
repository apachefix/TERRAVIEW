"""Sincronización controlada de transportistas OCRD hacia TERRAVIEW."""

import logging

from django.db import transaction

from apps.home.models import SOCIONEGOCIO
from apps.home.sap_di_api import consultar_transportistas_sap
from apps.integrations.sap_b1.sap_config import (
    SAP_EMPRESA_SBH,
    SAP_EMPRESA_TERRAMAR,
    get_sap_company_db,
)


logger = logging.getLogger(__name__)

EMPRESAS_TRANSPORTES_SAP = (SAP_EMPRESA_TERRAMAR, SAP_EMPRESA_SBH)


def _texto(valor):
    return str(valor or '').strip()


def es_transporte_sap_activo(fila):
    """Defensa adicional a los filtros OCRD ejecutados en SAP."""
    return (
        _texto(fila.get('CardType')).upper() == 'S'
        and _texto(fila.get('EsTransporte')) == 'Si'
        and _texto(fila.get('validFor')).upper() == 'Y'
        and _texto(fila.get('frozenFor')).upper() == 'N'
        and bool(_texto(fila.get('CardCode')))
        and bool(_texto(fila.get('CardName')))
        and bool(_texto(fila.get('LicTradNum')))
    )


def datos_maestros_transporte(fila):
    """Campos de SOCIONEGOCIO cuya fuente maestra es OCRD."""
    return {
        'SN_CCODIGO_SAP': _texto(fila.get('CardCode')),
        'SN_CRAZONSOCIAL': _texto(fila.get('CardName')),
        'SN_CRUT': _texto(fila.get('LicTradNum')),
        'SN_CDIRECCION': _texto(fila.get('Address')),
        'SN_CCONTACTO': _texto(fila.get('CardFName')),
        'SN_CTELEFONO': _texto(fila.get('Phone1')),
        'SN_CEMAIL': _texto(fila.get('E_Mail')),
        'SN_CTIPO': 'S',
        'SN_BHABILITADO': True,
    }


def sincronizar_transportes_empresa(empresa_id, *, dry_run=False):
    """Crea o actualiza transportistas activos de una empresa SAP.

    La clave lógica es ``EP_NID_id + SN_CCODIGO_SAP``. No se eliminan ni se
    reasignan registros, y esta fase no deshabilita automáticamente los que
    dejan de cumplir la regla SAP.
    """
    empresa_id = int(empresa_id)
    company_db = get_sap_company_db(empresa_id)
    filas = consultar_transportistas_sap(company_db)
    resumen = {
        'empresa_id': empresa_id,
        'encontrados': len(filas),
        'creados': 0,
        'actualizados': 0,
        'sin_cambios': 0,
        'ignorados': 0,
        'errores': 0,
    }

    for fila in filas:
        if not es_transporte_sap_activo(fila):
            resumen['ignorados'] += 1
            continue

        datos = datos_maestros_transporte(fila)
        try:
            with transaction.atomic():
                socio = SOCIONEGOCIO.objects.select_for_update().filter(
                    EP_NID_id=empresa_id,
                    SN_CCODIGO_SAP=datos['SN_CCODIGO_SAP'],
                ).order_by('id').first()
                if socio is None:
                    resumen['creados'] += 1
                    if not dry_run:
                        SOCIONEGOCIO.objects.create(
                            EP_NID_id=empresa_id,
                            SN_BGENERICO=False,
                            **datos,
                        )
                    continue

                campos_actualizados = [
                    campo for campo, valor in datos.items()
                    if getattr(socio, campo) != valor
                ]
                if not campos_actualizados:
                    resumen['sin_cambios'] += 1
                    continue

                resumen['actualizados'] += 1
                if not dry_run:
                    for campo in campos_actualizados:
                        setattr(socio, campo, datos[campo])
                    socio.save(update_fields=campos_actualizados)
        except Exception:
            resumen['errores'] += 1
            logger.exception(
                'No fue posible sincronizar transporte SAP empresa=%s cardcode=%s.',
                empresa_id,
                datos['SN_CCODIGO_SAP'],
            )

    return resumen


def sincronizar_transportes_sap(*, empresas=None, dry_run=False):
    """Sincroniza explícitamente Terramar y/o SBH, sin efectos al importar."""
    empresas = tuple(empresas or EMPRESAS_TRANSPORTES_SAP)
    invalidas = set(empresas) - set(EMPRESAS_TRANSPORTES_SAP)
    if invalidas:
        raise ValueError(f'Empresas no admitidas para sincronización SAP: {sorted(invalidas)}')
    return [
        sincronizar_transportes_empresa(empresa_id, dry_run=dry_run)
        for empresa_id in empresas
    ]
