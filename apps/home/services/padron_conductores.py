"""Servicios para el padrón operacional conductor ↔ empresa."""

import csv
from collections import Counter

from django.db import transaction

from apps.home.conductor_utils import RutChilenoInvalido, normalizar_rut_chileno
from apps.home.models import CITACION, CONDUCTOR, CONDUCTOR_EMPRESA, EMPRESA, SOCIONEGOCIO
from apps.home.vars import ID_ACEITES_SBH


RUT_LEGACY_PUESTO_EN_PLANTA = '55555555-5'
RUT_CONDUCTOR_GENERICO = '99999999-9'
RUTS_NO_OPERATIVOS_SBH = {RUT_LEGACY_PUESTO_EN_PLANTA, RUT_CONDUCTOR_GENERICO}
ID_CONDUCTOR_GENERICO = 1


def conductor_es_operativo_sbh(conductor):
    """Evita que legados/généricos se conviertan en padrón operativo."""
    return bool(
        conductor.CON_BHABILITADO
        and conductor.pk != ID_CONDUCTOR_GENERICO
        and conductor.CON_CRUT not in RUTS_NO_OPERATIVOS_SBH
    )


def queryset_conductores_operativos(empresa_id, socio_negocio_id=None):
    """Terramar conserva su fuente legacy; SBH usa sólo membresías explícitas."""
    queryset = CONDUCTOR.objects.filter(CON_BHABILITADO=True)
    if empresa_id == ID_ACEITES_SBH:
        queryset = queryset.filter(
            empresas_operacionales__EP_NID_id=empresa_id,
            empresas_operacionales__CEM_BHABILITADO=True,
            CON_CRUT__regex=r'^\d{2,8}-[0-9K]$',
        ).exclude(
            CON_CRUT__in=RUTS_NO_OPERATIVOS_SBH,
        ).exclude(pk=ID_CONDUCTOR_GENERICO)
    else:
        queryset = queryset.filter(EP_NID_id=empresa_id)
    if socio_negocio_id is not None:
        queryset = queryset.filter(SN_NID_id=socio_negocio_id)
    return queryset.distinct()


def asignar_transporte_operacional_sbh(conductores):
    """Asigna una etiqueta visual SBH sin usar ``CONDUCTOR.SN_NID``.

    Las citaciones guardan proveedores históricos. El CardCode permite llevar
    esa referencia al maestro SBH vigente sin alterar la citación original.
    """
    conductores = list(conductores)
    ids = [conductor.pk for conductor in conductores]
    if not ids:
        return conductores

    codigos_por_conductor = {}
    for conductor_id, codigo in CITACION.objects.filter(
        EP_NID_id=ID_ACEITES_SBH,
        CON_NID_id__in=ids,
        PRO_NID__isnull=False,
    ).exclude(
        PRO_NID__SN_CCODIGO_SAP__isnull=True,
    ).exclude(
        PRO_NID__SN_CCODIGO_SAP='',
    ).values_list('CON_NID_id', 'PRO_NID__SN_CCODIGO_SAP').distinct():
        codigos_por_conductor.setdefault(conductor_id, set()).add(str(codigo).strip())

    codigos = {codigo for valores in codigos_por_conductor.values() for codigo in valores}
    nombres_por_codigo = {}
    if codigos:
        for codigo, nombre in SOCIONEGOCIO.objects.filter(
            EP_NID_id=ID_ACEITES_SBH,
            SN_CTIPO='S',
            SN_BHABILITADO=True,
            SN_CCODIGO_SAP__in=codigos,
        ).values_list('SN_CCODIGO_SAP', 'SN_CRAZONSOCIAL'):
            nombres_por_codigo.setdefault(str(codigo).strip(), set()).add(nombre)

    for conductor in conductores:
        nombres = {
            nombre
            for codigo in codigos_por_conductor.get(conductor.pk, set())
            for nombre in nombres_por_codigo.get(codigo, set())
        }
        conductor.transporte_operacional_sbh = (
            next(iter(nombres)) if len(nombres) == 1 else ('Varios' if nombres else '-')
        )
    return conductores


def queryset_conductores_por_transporte_sbh(proveedor):
    """Conductores activos del padrón SBH usados con el CardCode indicado."""
    codigo_sap = str(proveedor.SN_CCODIGO_SAP or '').strip()
    if not codigo_sap:
        return CONDUCTOR.objects.none()
    conductores_historicos = CITACION.objects.filter(
        EP_NID_id=ID_ACEITES_SBH,
        CON_NID_id__isnull=False,
        PRO_NID__SN_CCODIGO_SAP=codigo_sap,
    ).values_list('CON_NID_id', flat=True)
    return CONDUCTOR.objects.filter(
        pk__in=conductores_historicos,
        CON_BHABILITADO=True,
        empresas_operacionales__EP_NID_id=ID_ACEITES_SBH,
        empresas_operacionales__CEM_BHABILITADO=True,
    ).exclude(
        CON_CRUT__in=RUTS_NO_OPERATIVOS_SBH,
    ).exclude(pk=ID_CONDUCTOR_GENERICO).distinct()


def asegurar_membresia_conductor_empresa(*, conductor, empresa, usuario=None):
    """Crea o reactiva una única membresía sin tocar el maestro conductor."""
    membresia, creada = CONDUCTOR_EMPRESA.objects.get_or_create(
        CON_NID=conductor,
        EP_NID=empresa,
        defaults={'CEM_BHABILITADO': True, 'US_NID': usuario},
    )
    if not creada and not membresia.CEM_BHABILITADO:
        membresia.CEM_BHABILITADO = True
        if usuario is not None:
            membresia.US_NID = usuario
        membresia.save(update_fields=['CEM_BHABILITADO', 'US_NID'])
    return membresia, creada


def resolver_conductor_por_rut_sbh(rut_normalizado, *, bloquear=False):
    """Resuelve sólo una coincidencia habilitada; duplicados activos son conflicto."""
    queryset = CONDUCTOR.objects.exclude(CON_CRUT='').order_by('id')
    if bloquear:
        queryset = queryset.select_for_update()
    coincidencias = []
    for conductor in queryset:
        try:
            if normalizar_rut_chileno(conductor.CON_CRUT) == rut_normalizado:
                coincidencias.append(conductor)
        except RutChilenoInvalido:
            continue
    elegibles = [item for item in coincidencias if conductor_es_operativo_sbh(item)]
    if len(elegibles) == 1:
        return {'estado': 'encontrado', 'conductor': elegibles[0], 'coincidencias': coincidencias}
    if len(elegibles) > 1:
        return {'estado': 'conflicto', 'conductor': None, 'coincidencias': elegibles}
    if coincidencias:
        return {'estado': 'inhabilitado_o_generico', 'conductor': None, 'coincidencias': coincidencias}
    return {'estado': 'no_encontrado', 'conductor': None, 'coincidencias': []}


def cargar_ruts_sbh_desde_csv(archivo):
    """Lee columna RUT sin inferir identidad por nombre ni por IDs legacy."""
    with open(archivo, encoding='utf-8-sig', newline='') as fuente:
        lector = csv.DictReader(fuente)
        if not lector.fieldnames:
            raise ValueError('El archivo no tiene encabezados; se requiere la columna RUT.')
        columnas = {str(nombre).strip().upper(): nombre for nombre in lector.fieldnames if nombre}
        if 'RUT' not in columnas:
            raise ValueError('El archivo debe incluir una columna llamada RUT.')
        return [str(fila.get(columnas['RUT']) or '').strip() for fila in lector]


def sembrar_conductores_sbh_desde_ruts(ruts, *, dry_run=False, usuario=None):
    """Previsualiza o crea membresías SBH, sin alterar conductor/SN/citaciones/camiones."""
    empresa_sbh = EMPRESA.objects.get(pk=ID_ACEITES_SBH)
    resultado = {
        'fuente': len(ruts), 'ruts_recibidos': [], 'encontrados': [], 'ya_asociados': [],
        'nuevas_membresias': [], 'conflictos': [], 'no_encontrados': [],
        'inhabilitados_o_genericos': [], 'ruts_invalidos': [], 'duplicados_fuente': [],
    }
    vistos = Counter()
    normalizados = []
    for valor in ruts:
        try:
            rut = normalizar_rut_chileno(valor)
        except RutChilenoInvalido:
            resultado['ruts_invalidos'].append(str(valor))
            continue
        if not rut:
            resultado['ruts_invalidos'].append(str(valor))
            continue
        vistos[rut] += 1
        if vistos[rut] == 1:
            normalizados.append(rut)
            resultado['ruts_recibidos'].append(rut)
    resultado['duplicados_fuente'] = sorted(rut for rut, cantidad in vistos.items() if cantidad > 1)

    with transaction.atomic():
        for rut in normalizados:
            if rut in RUTS_NO_OPERATIVOS_SBH:
                resultado['inhabilitados_o_genericos'].append(rut)
                continue
            resolucion = resolver_conductor_por_rut_sbh(rut, bloquear=not dry_run)
            estado = resolucion['estado']
            if estado == 'conflicto':
                resultado['conflictos'].append({
                    'rut': rut, 'conductores': [item.pk for item in resolucion['coincidencias']],
                })
                continue
            if estado == 'no_encontrado':
                resultado['no_encontrados'].append(rut)
                continue
            if estado == 'inhabilitado_o_generico':
                resultado['inhabilitados_o_genericos'].append(rut)
                continue
            conductor = resolucion['conductor']
            resultado['encontrados'].append(conductor.pk)
            existente = CONDUCTOR_EMPRESA.objects.filter(CON_NID=conductor, EP_NID=empresa_sbh).first()
            if existente and existente.CEM_BHABILITADO:
                resultado['ya_asociados'].append(conductor.pk)
            else:
                resultado['nuevas_membresias'].append(conductor.pk)
                if not dry_run:
                    asegurar_membresia_conductor_empresa(
                        conductor=conductor, empresa=empresa_sbh, usuario=usuario,
                    )
        if dry_run:
            transaction.set_rollback(True)
    return resultado
