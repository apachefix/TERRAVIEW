import json
from collections import defaultdict

from django.db.models import Prefetch, Count, Q

from apps.home.models import (
    CAMION_NO_PLANIFICADO,
    CAMION_PATIO,
    CAMION_PATIO_NO_PLANIFICADO,
    CITACION,
    CITACION_ITEM,
    DATO_OPERACION,
    SOCIONEGOCIO,
)
from apps.home.vars import CIT_TERMINADO


CODIGOS_CLIENTE_HISTORICO = (
    'PLAN_CODIGO_CLIENTE_SAP',
    'PLAN_CLIENTE_CODIGO_SAP',
)


def _normalizar_codigo_cliente(valor):
    return str(valor or '').strip().upper()


def _codigo_cliente_estructurado(citacion):
    detalle_despacho = getattr(citacion, 'detalle_despacho', None)
    codigo = _normalizar_codigo_cliente(
        getattr(detalle_despacho, 'CDD_CSAP_CLIENTE_CODIGO', '')
    )
    if codigo:
        return codigo

    for dato in getattr(citacion, 'datos_cliente_historico', []):
        codigo = _normalizar_codigo_cliente(dato.DO_CVALOR)
        if codigo:
            return codigo

    try:
        metadata = json.loads(citacion.CI_CCOMENTARIO or '')
    except (TypeError, ValueError):
        metadata = {}
    if isinstance(metadata, dict):
        return _normalizar_codigo_cliente(
            metadata.get('cliente_codigo') or metadata.get('sap_cliente_codigo')
        )
    return ''


def _resolver_clientes_historicos(citaciones, empresa_id):
    codigos_por_citacion = {
        citacion.id: _codigo_cliente_estructurado(citacion)
        for citacion in citaciones
        if citacion.SN_NID_id is None
    }
    codigos = {codigo for codigo in codigos_por_citacion.values() if codigo}
    if not codigos:
        return {}

    filtro_codigos = Q()
    for codigo in codigos:
        filtro_codigos |= Q(SN_CCODIGO_SAP__iexact=codigo)

    candidatos = defaultdict(list)
    for socio in SOCIONEGOCIO.objects.filter(
        filtro_codigos,
        EP_NID_id=empresa_id,
        SN_CTIPO='C',
        SN_BHABILITADO=True,
    ):
        candidatos[_normalizar_codigo_cliente(socio.SN_CCODIGO_SAP)].append(socio)

    unicos = {
        codigo: socios[0]
        for codigo, socios in candidatos.items()
        if len(socios) == 1
    }
    return {
        citacion_id: unicos[codigo]
        for citacion_id, codigo in codigos_por_citacion.items()
        if codigo in unicos
    }


def _cliente_key(citacion, socio_resuelto=None):
    """Clave estable de cliente, siempre acotada a la empresa."""
    socio_id = citacion.SN_NID_id or getattr(socio_resuelto, 'id', None)
    return (citacion.EP_NID_id, socio_id)


def _cliente_data(citacion, socio_resuelto=None):
    socio = citacion.SN_NID or socio_resuelto
    return {
        'key': _cliente_key(citacion, socio_resuelto),
        'id': socio.id if socio else None,
        'codigo': socio.SN_CCODIGO_SAP if socio else '',
        'nombre': socio.SN_CRAZONSOCIAL if socio else 'Cliente no identificado',
    }


def _fila_citacion(citacion, categoria, socio_resuelto=None):
    camion = citacion.camiones_historicos[0] if citacion.camiones_historicos else None
    item = citacion.items_historicos[0].IT_NID if citacion.items_historicos else None
    return {
        'id': citacion.id,
        'numero': citacion.id,
        'cliente': _cliente_data(citacion, socio_resuelto),
        'fecha': citacion.CI_FFECHACITACION,
        'cupo': citacion.CI_NCUPO,
        'articulo': item.IT_CNOMBRE if item else '',
        'proveedor': citacion.PRO_NID.SN_CRAZONSOCIAL if citacion.PRO_NID else '',
        'estado': citacion.CI_CESTADO,
        'fecha_cierre': citacion.CI_FFECHATERMINO,
        'patente': camion.CPA_CPATENTE if camion else '',
        'camion': camion,
        'categoria': categoria,
    }


def construir_resumen_planificacion(planificacion):
    """Resumen histórico sin joins multiplicadores ni cálculos críticos en cliente."""
    empresa_id = planificacion.EP_NID_id
    camiones_asociados = CAMION_PATIO.objects.filter(
        EP_NID_id=empresa_id,
        CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
    ).select_related('US_GUARDIA_ID', 'US_ASOCIA_ID')
    citaciones = list(
        CITACION.objects.filter(
            PL_NID=planificacion,
            EP_NID_id=empresa_id,
            CI_BHABILITADO=True,
        ).select_related('SN_NID', 'PRO_NID', 'detalle_despacho').prefetch_related(
            Prefetch('camiones_patio', queryset=camiones_asociados, to_attr='camiones_historicos'),
            Prefetch('citacion_item_set', queryset=CITACION_ITEM.objects.select_related('IT_NID'), to_attr='items_historicos'),
            Prefetch(
                'dato_operacion_set',
                queryset=DATO_OPERACION.objects.filter(
                    EP_NID_id=empresa_id,
                    CAMP_NID__CA_CCODIGO__in=CODIGOS_CLIENTE_HISTORICO,
                ).select_related('CAMP_NID'),
                to_attr='datos_cliente_historico',
            ),
        ).order_by('CI_FFECHACITACION', 'id')
    )
    clientes_resueltos = _resolver_clientes_historicos(citaciones, empresa_id)

    grupos = {}
    cerradas, abiertas, sin_camion = [], [], []
    for citacion in citaciones:
        socio_resuelto = clientes_resueltos.get(citacion.id)
        cliente = _cliente_data(citacion, socio_resuelto)
        grupo = grupos.setdefault(cliente['key'], {
            **cliente,
            'citaciones_creadas': 0,
            'camiones_asociados': 0,
            'citaciones_cerradas': 0,
            'citaciones_abiertas_con_camion': 0,
            'citaciones_sin_camion': 0,
            'camiones_no_planificados': 0,
            'unplanned_trucks': [],
            'citaciones': {'cerradas': [], 'abiertas': [], 'sin_camion': [], 'no_planificadas': []},
        })
        grupo['citaciones_creadas'] += 1
        tiene_camion = bool(citacion.camiones_historicos)
        if citacion.CI_CESTADO == CIT_TERMINADO:
            fila = _fila_citacion(citacion, 'cerrada', socio_resuelto)
            cerradas.append(fila)
            grupo['citaciones_cerradas'] += 1
            grupo['citaciones']['cerradas'].append(fila)
            if tiene_camion:
                grupo['camiones_asociados'] += 1
        elif tiene_camion:
            fila = _fila_citacion(citacion, 'abierta', socio_resuelto)
            abiertas.append(fila)
            grupo['camiones_asociados'] += 1
            grupo['citaciones_abiertas_con_camion'] += 1
            grupo['citaciones']['abiertas'].append(fila)
        else:
            fila = _fila_citacion(citacion, 'sin_camion', socio_resuelto)
            sin_camion.append(fila)
            grupo['citaciones_sin_camion'] += 1
            grupo['citaciones']['sin_camion'].append(fila)

    solicitudes_patio = list(CAMION_PATIO_NO_PLANIFICADO.objects.filter(
        EP_NID_id=empresa_id,
        PL_NID=planificacion,
        CPNP_CESTADO=CAMION_PATIO_NO_PLANIFICADO.ESTADO_APROBADO,
    ).select_related('CPA_NID', 'CI_NID__SN_NID', 'US_SOLICITA_ID'))
    patentes_patio = set()
    citaciones_no_planificadas = set()
    no_planificados = []
    for solicitud in solicitudes_patio:
        camion = solicitud.CPA_NID
        patente = (camion.CPA_CPATENTE or '').strip().upper()
        if patente:
            patentes_patio.add(patente)
        if solicitud.CI_NID_id:
            citaciones_no_planificadas.add(solicitud.CI_NID_id)
        cliente = _cliente_data(
            solicitud.CI_NID,
            clientes_resueltos.get(solicitud.CI_NID_id),
        ) if solicitud.CI_NID else {
            'key': (empresa_id, None), 'id': None, 'codigo': '', 'nombre': 'Cliente no identificado'
        }
        fila = {
            'patente': camion.CPA_CPATENTE,
            'cliente': cliente,
            'conductor': camion.CPA_CNOMBRE_CONDUCTOR,
            'transportista': camion.CPA_CTRANSPORTISTA_DECLARADO,
            'fecha_llegada': camion.CPA_FFECHALLEGADA,
            'tipo': planificacion.PL_CTIPOCUPO,
            'citacion_id': solicitud.CI_NID_id,
            'estado': camion.CPA_CESTADO,
            'usuario': solicitud.US_SOLICITA_ID,
            'origen': 'patio',
        }
        no_planificados.append(fila)

    # El flujo legado se agrega sólo si no representa el mismo camión/citación de patio.
    for solicitud in CAMION_NO_PLANIFICADO.objects.filter(
        EP_NID_id=empresa_id, PL_NID=planificacion,
        CNP_CESTADO=CAMION_NO_PLANIFICADO.ESTADO_PLANIFICADO,
    ).select_related('US_GUARDIA_ID'):
        patente = (solicitud.CNP_CPATENTE or '').strip().upper()
        if patente and patente in patentes_patio:
            continue
        cliente = {'key': (empresa_id, None), 'id': None, 'codigo': solicitud.CLI_CCODIGO or '',
                   'nombre': solicitud.CLI_CNOMBRE or 'Cliente no identificado'}
        no_planificados.append({
            'patente': solicitud.CNP_CPATENTE, 'cliente': cliente,
            'conductor': '', 'transportista': solicitud.CNP_CEMPRESATRANSPORTE,
            'fecha_llegada': solicitud.CNP_FFECHACREACION, 'tipo': planificacion.PL_CTIPOCUPO,
            'citacion_id': None, 'estado': solicitud.CNP_CESTADO,
            'usuario': solicitud.US_GUARDIA_ID, 'origen': 'legado',
        })

    for fila in no_planificados:
        grupo = grupos.setdefault(fila['cliente']['key'], {
            **fila['cliente'], 'citaciones_creadas': 0, 'camiones_asociados': 0,
            'citaciones_cerradas': 0, 'citaciones_abiertas_con_camion': 0,
            'citaciones_sin_camion': 0, 'camiones_no_planificados': 0,
            'unplanned_trucks': [], 'citaciones': {'cerradas': [], 'abiertas': [], 'sin_camion': [], 'no_planificadas': []},
        })
        grupo['camiones_no_planificados'] += 1
        grupo['unplanned_trucks'].append(fila)
        grupo['citaciones']['no_planificadas'].append(fila)

    for grupo in grupos.values():
        grupo['total_camiones_recibidos'] = grupo['camiones_asociados'] + grupo['camiones_no_planificados']
        grupo['porcentaje_llegada'] = round((grupo['camiones_asociados'] / grupo['citaciones_creadas'] * 100), 1) if grupo['citaciones_creadas'] else 0
        estados = []
        if grupo['citaciones_sin_camion']:
            estados.append('Incompleto')
        if grupo['citaciones_abiertas_con_camion']:
            estados.append('Con operaciones abiertas')
        if grupo['camiones_no_planificados']:
            estados.append('Con ingresos adicionales')
        if grupo['citaciones_creadas'] and not grupo['citaciones_sin_camion']:
            estados.insert(0, 'Completo')
        grupo['estado'] = ' · '.join(estados) or 'Sin citaciones'
        grupo['mensaje_cumplimiento'] = '{}: {} de {} camiones recibidos; {} citación(es) sin camión'.format(
            grupo['nombre'], grupo['camiones_asociados'], grupo['citaciones_creadas'], grupo['citaciones_sin_camion'])

    citaciones_normales = sum(1 for citacion in citaciones if not citacion.CI_BSOBRECUPO)
    summary = {
        'cupos_planificados': planificacion.PL_NCANTIDADCUPOS or 0,
        'citaciones_creadas': len(citaciones),
        'camiones_asociados': sum(grupo['camiones_asociados'] for grupo in grupos.values()),
        'citaciones_cerradas': len(cerradas),
        'citaciones_abiertas_con_camion': len(abiertas),
        'citaciones_sin_camion': len(sin_camion),
        'cupos_no_utilizados': max((planificacion.PL_NCANTIDADCUPOS or 0) - citaciones_normales, 0),
        'camiones_no_planificados': len(no_planificados),
        'clientes': len(grupos),
    }
    summary['total_camiones_recibidos'] = summary['camiones_asociados'] + summary['camiones_no_planificados']
    return {
        'summary': summary,
        'client_summaries': sorted(grupos.values(), key=lambda grupo: (grupo['nombre'] or '').upper()),
        'closed_citations': cerradas,
        'open_citations': abiertas,
        'citations_without_truck': sin_camion,
        'unplanned_trucks': no_planificados,
    }


def construir_resumenes_planificaciones_archivadas(planificaciones, empresa_id):
    """Indicadores del listado en consultas compartidas, sin resumen individual por fila."""
    planificaciones = list(planificaciones)
    ids = [planificacion.id for planificacion in planificaciones]
    resultado = {p.id: {'cupos_planificados': p.PL_NCANTIDADCUPOS or 0, 'citaciones_creadas': 0, 'camiones_asociados': 0, 'citaciones_cerradas': 0, 'citaciones_abiertas_con_camion': 0, 'citaciones_sin_camion': 0, 'cupos_no_utilizados': p.PL_NCANTIDADCUPOS or 0, 'camiones_no_planificados': 0, 'clientes': 0, 'total_camiones_recibidos': 0} for p in planificaciones}
    if not ids: return resultado
    citaciones = list(CITACION.objects.filter(PL_NID_id__in=ids, EP_NID_id=empresa_id, CI_BHABILITADO=True).values('id', 'PL_NID_id', 'SN_NID_id', 'CI_CESTADO', 'CI_BSOBRECUPO'))
    asociados = set(CAMION_PATIO.objects.filter(EP_NID_id=empresa_id, CI_NID_id__in=[c['id'] for c in citaciones], CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION).values_list('CI_NID_id', flat=True))
    clientes, normales = {i:set() for i in ids}, {i:0 for i in ids}
    for c in citaciones:
        r = resultado[c['PL_NID_id']]; r['citaciones_creadas'] += 1; clientes[c['PL_NID_id']].add(c['SN_NID_id'])
        if not c['CI_BSOBRECUPO']: normales[c['PL_NID_id']] += 1
        if c['CI_CESTADO'] == CIT_TERMINADO: r['citaciones_cerradas'] += 1
        elif c['id'] in asociados: r['citaciones_abiertas_con_camion'] += 1
        else: r['citaciones_sin_camion'] += 1
        if c['id'] in asociados: r['camiones_asociados'] += 1
    for fila in CAMION_PATIO_NO_PLANIFICADO.objects.filter(EP_NID_id=empresa_id, PL_NID_id__in=ids, CPNP_CESTADO=CAMION_PATIO_NO_PLANIFICADO.ESTADO_APROBADO).values('PL_NID_id').annotate(total=Count('id')):
        resultado[fila['PL_NID_id']]['camiones_no_planificados'] = fila['total']
    for p in planificaciones:
        r=resultado[p.id]; r['clientes']=len(clientes[p.id]); r['cupos_no_utilizados']=max((p.PL_NCANTIDADCUPOS or 0)-normales[p.id],0); r['total_camiones_recibidos']=r['camiones_asociados']+r['camiones_no_planificados']
    return resultado