"""Selección de transporte para nuevos despachos SBH de planificación."""

import unicodedata

from django.db.models import QuerySet

from .models import COMUNA, TARIFA_GLOBAL


EMPRESA_ACEITES_SBH_ID = 2
TARIFAS_EXCLUIDAS_SELECTOR_DESPACHO_SBH = frozenset({1080, 1112, 1134})

# Las claves son códigos de dirección CRD1.Address normalizados. El alias se
# usa sólo después de filtrar por las FK geográficas de RUTA.
DESTINOS_SAP_CONTROLADOS = {
    'OSORNO': {'comuna': 'Osorno', 'alias_ruta': ''},
    'CORONEL': {'comuna': 'Coronel', 'alias_ruta': ''},
    'PARGUA': {'comuna': 'Calbuco', 'alias_ruta': 'PARGUA'},
}


def normalizar_texto_geografico(valor):
    texto = unicodedata.normalize('NFKD', str(valor or '').strip())
    return ' '.join(
        ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
        .upper()
        .split()
    )


def resolver_destino_despacho_sap(direccion_sap):
    """Resuelve una dirección SAP validada hacia COMUNA y contexto de ruta."""
    direccion_codigo = str(direccion_sap.get('direccion_codigo') or '').strip()
    ciudad = str(direccion_sap.get('ciudad') or '').strip()
    clave_direccion = normalizar_texto_geografico(direccion_codigo)
    configuracion = DESTINOS_SAP_CONTROLADOS.get(clave_direccion)

    if configuracion:
        comuna_nombre = configuracion['comuna']
        alias_ruta = configuracion['alias_ruta']
    else:
        # Fallback deliberadamente estricto: sólo se acepta una ciudad SAP que
        # coincida exactamente con una comuna local. No se buscan rutas por texto.
        comuna_nombre = ciudad
        alias_ruta = ''

    clave_comuna = normalizar_texto_geografico(comuna_nombre)
    if not clave_comuna:
        raise ValueError(
            f'La dirección SAP {direccion_codigo or "seleccionada"} no tiene un destino TERRAVIEW configurado.'
        )

    comunas = [
        comuna for comuna in COMUNA.objects.all().order_by('id')
        if normalizar_texto_geografico(comuna.COM_CNOMBRE) == clave_comuna
    ]
    if len(comunas) != 1:
        raise ValueError(
            f'No fue posible resolver de forma unívoca la dirección SAP {direccion_codigo or comuna_nombre}.'
        )

    return {
        'comuna': comunas[0],
        'comuna_id': comunas[0].id,
        'comuna_nombre': comunas[0].COM_CNOMBRE,
        'direccion_codigo': direccion_codigo,
        'alias_ruta': alias_ruta,
    }


def queryset_alternativas_transporte_sbh(destino_resuelto) -> QuerySet:
    """Tarifas reales, habilitadas y compatibles con origen/destino SBH."""
    filtros = {
        'EP_NID_id': EMPRESA_ACEITES_SBH_ID,
        'TAR_BHABILITADO': True,
        'RUT_NID__EP_NID_id': EMPRESA_ACEITES_SBH_ID,
        'RUT_NID__RUT_BHABILITADO': True,
        'RUT_NID__COM_NID_INICIO__COM_CNOMBRE__iexact': 'Coronel',
        'RUT_NID__COM_NID_TERMINO_id': destino_resuelto['comuna_id'],
        'SN_NID__EP_NID_id': EMPRESA_ACEITES_SBH_ID,
        'SN_NID__SN_CTIPO': 'S',
        'SN_NID__SN_BHABILITADO': True,
    }
    tarifas = TARIFA_GLOBAL.objects.filter(**filtros).exclude(
        id__in=TARIFAS_EXCLUIDAS_SELECTOR_DESPACHO_SBH
    )
    if destino_resuelto.get('alias_ruta'):
        tarifas = tarifas.filter(
            RUT_NID__RUT_CNOMBRE__icontains=destino_resuelto['alias_ruta']
        )
    return tarifas.select_related(
        'SN_NID', 'RUT_NID', 'RUT_NID__COM_NID_INICIO',
        'RUT_NID__COM_NID_TERMINO',
    ).order_by(
        'TAR_CDIVISA', 'TAR_NVALOR', 'SN_NID__SN_CRAZONSOCIAL',
        'RUT_NID__RUT_CNOMBRE', 'id',
    )


def serializar_alternativa_transporte_sbh(tarifa):
    ruta = tarifa.RUT_NID
    transportista = tarifa.SN_NID
    return {
        'transportista_id': transportista.id,
        'transportista_nombre': transportista.SN_CRAZONSOCIAL,
        'transportista_rut': transportista.SN_CRUT,
        'ruta_id': ruta.id,
        'ruta_nombre': ruta.RUT_CNOMBRE,
        'origen': ruta.COM_NID_INICIO.COM_CNOMBRE,
        'destino': ruta.COM_NID_TERMINO.COM_CNOMBRE,
        'tarifa_id': tarifa.id,
        'tarifa_valor': str(tarifa.TAR_NVALOR),
        'tarifa_moneda': tarifa.TAR_CDIVISA,
    }


def obtener_alternativas_transporte_sbh(destino_resuelto):
    return [
        serializar_alternativa_transporte_sbh(tarifa)
        for tarifa in queryset_alternativas_transporte_sbh(destino_resuelto)
    ]


def validar_alternativa_transporte_sbh(
    *, destino_resuelto, transportista_id, ruta_id, tarifa_id,
):
    """Revalida la unidad tarifa+ruta+transportista enviada por el navegador."""
    ids = {
        'transportista': str(transportista_id or '').strip(),
        'ruta': str(ruta_id or '').strip(),
        'tarifa': str(tarifa_id or '').strip(),
    }
    if not all(valor.isdigit() for valor in ids.values()):
        return None, 'Debe seleccionar una alternativa de Transporte / Ruta / Tarifa válida.'

    tarifa = queryset_alternativas_transporte_sbh(destino_resuelto).filter(
        pk=ids['tarifa'],
        RUT_NID_id=ids['ruta'],
        SN_NID_id=ids['transportista'],
    ).first()
    if not tarifa:
        return None, (
            'La alternativa de Transporte / Ruta / Tarifa no corresponde a la '
            'dirección SAP seleccionada o ya no está habilitada.'
        )
    return tarifa, ''
