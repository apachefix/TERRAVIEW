"""Company-scoped, bounded-query read model for dashboard_grafico.

Uses the existing operational resolver with preloaded sources. Does not call any
operational view, timer initializer, SAP client, signal or model property that
queries per truck. No operational writes are performed here.
"""
import json
from collections import Counter, defaultdict
from time import perf_counter
from urllib.parse import urlencode

from django.db.models import CharField, Exists, F, OuterRef
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.home.models import (
    CITACION, DATO_OPERACION, DETALLE_SECUENCIA, EMPRESA, ESTANQUE_RESERVA,
    ETAPA_LOG, OPERACION_PLANTA_LOG, SYSLOGGER, ZONA,
)
from .mapa_operacional_config import (
    ESTANQUES_CONFIRMADOS, REGLAS, REGLAS_ETAPA, ZONAS_FISICAS, zonas_configuradas,
)

CERRADOS = ('TERMINADO', 'RECHAZADO', 'ANULADO', 'CANCELADO', 'COMPLETADO',
            'COMPLETADA', 'SALIDA_CONFIRMADA')
CAMPOS = (
    'ING_PATENTE', 'ING_CONDUCTOR', 'ING_TRANSPORTISTA', 'ETA3_ESTANQUE',
    'ACD_ESTANQUE_ORIGEN', 'ACD_ZONA_CARGA', 'OP_CICLO_DESCARGA',
    'OP_TOMA_MUESTRA_ACCION', 'OP_TOMA_MUESTRA_VAPOR',
    'OP_TOMA_MUESTRA_TIEMPO_VAPOR', 'DESP_TERR_DOC_TEMPORIZADOR',
)


class CitacionPrecargada:
    """Read adapter; ETAPA_ACTUAL comes from the batch, never its ORM property."""
    def __init__(self, citacion, etapa):
        self.citacion = citacion
        self.ETAPA_ACTUAL = etapa

    def __getattr__(self, nombre):
        return getattr(self.citacion, nombre)


def _json(dato):
    try:
        valor = json.loads(dato.DO_CVALOR) if dato else {}
        return valor if isinstance(valor, dict) else {}
    except (TypeError, ValueError):
        return {}


def _fecha(valor):
    if not valor:
        return None
    try:
        fecha = parse_datetime(str(valor))
        if fecha and timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, timezone.get_current_timezone())
        return fecha
    except (TypeError, ValueError, OverflowError):
        return None


def _relacion(citacion, nombre):
    valor = getattr(citacion, nombre, None)
    return valor if valor and valor.EP_NID_id == citacion.EP_NID_id else None


def _valor(datos, codigo):
    dato = datos.get(codigo)
    return str(dato.DO_CVALOR or '').strip() if dato else ''


def _zona_y_reloj(citacion, paso, reglas, datos, calidad, logs, etapa_log, pasos):
    zona = reglas.get(paso, 'OTRO')
    inicio = fin = None
    fuente = ''
    ciclo = _json(datos.get('OP_CICLO_DESCARGA'))
    if paso == 'Ciclo Descarga':
        inicio, fin = _fecha(ciclo.get('inicio_descarga')), _fecha(ciclo.get('fin_descarga'))
        fuente = 'OP_CICLO_DESCARGA.inicio_descarga' if inicio else ''
        if not inicio:
            zona = 'ESPERA'
            inicio = _fecha(ciclo.get('inicio_espera_descarga'))
            fuente = 'OP_CICLO_DESCARGA.inicio_espera_descarga' if inicio else ''
    if paso in ('Toma de muestra', 'Analisis y calidad', 'Resultado Calidad'):
        accion = max((datos[c] for c in ('OP_TOMA_MUESTRA_ACCION', 'OP_TOMA_MUESTRA_VAPOR')
                      if c in datos), key=lambda d: d.id, default=None)
        muestra = _json(accion)
        vapor = _json(datos.get('OP_TOMA_MUESTRA_TIEMPO_VAPOR'))
        vapor_inicio = _fecha(vapor.get('inicio_vapor'))
        if not vapor_inicio and (muestra.get('tipo_accion') == 'vapor' or muestra.get('enviado_vapor')):
            vapor_inicio = _fecha(muestra.get('fecha_iso')) or (accion.DO_FFECHAREGISTRO if accion else None)
        if vapor_inicio and not vapor.get('fin_vapor'):
            zona, inicio, fuente = 'VAPOR', vapor_inicio, 'OP_TOMA_MUESTRA_TIEMPO_VAPOR / accion'
        elif paso == 'Toma de muestra':
            inicio, fin = _fecha(muestra.get('fecha_iso')), _fecha(muestra.get('fecha_fin_iso'))
            fuente = 'OP_TOMA_MUESTRA_ACCION.fecha_iso' if inicio else ''
        elif paso == 'Analisis y calidad' and calidad:
            inicio, fin = calidad.RCO_FINICIO, calidad.RCO_FDETENCION_TEMPORIZADOR
            fuente = 'RESULTADO_CALIDAD_OPERACION.RCO_FINICIO'
    if paso == 'Documentación' and citacion.CI_CTIPO == 'DESPACHO':
        doc = _json(datos.get('DESP_TERR_DOC_TEMPORIZADOR'))
        inicio, fin = _fecha(doc.get('inicio_iso')), _fecha(doc.get('fin_iso'))
        fuente = 'DESP_TERR_DOC_TEMPORIZADOR.inicio_iso' if inicio else ''
    if not inicio and etapa_log and etapa_log.EL_FFECHAFIN is None:
        # A technical log is evidence only when it represents THIS operational step.
        from apps.home.views import obtener_boton_operacional_desde_etapa_tecnica
        if obtener_boton_operacional_desde_etapa_tecnica(citacion) == paso:
            inicio, fuente = etapa_log.EL_FFECHAINICIO, 'ETAPA_LOG.EL_FFECHAINICIO'
    if not inicio:
        indice = pasos.index(paso) if paso in pasos else -1
        anterior = pasos[indice - 1] if indice > 0 else 'Habilitar Operacion Planta'
        transicion = next((l for l in reversed(logs) if l.OPL_CPASO == anterior
                           and l.OPL_CESTADO == 'COMPLETADO'), None)
        if transicion:
            inicio, fuente = transicion.OPL_FFECHAREGISTRO, 'OPERACION_PLANTA_LOG: ' + anterior
    return zona, inicio, fin, fuente


def obtener_estado_mapa_operacional(empresa_id, *, secuencias_permitidas=None):
    from apps.home import views
    comienzo = perf_counter()
    ahora = timezone.now()
    zonas = zonas_configuradas()
    habilitado = OPERACION_PLANTA_LOG.objects.filter(
        CI_NID_id=OuterRef('pk'), EP_NID_id=empresa_id,
        PL_NID_id=OuterRef('PL_NID_id'), OPL_CPASO='Habilitar Operacion Planta',
        OPL_CESTADO='COMPLETADO')
    ingreso = SYSLOGGER.objects.filter(
        EP_NID_id=empresa_id, LOG_CADD1=Cast(OuterRef('pk'), CharField()),
        LOG_COPERACION='AUTORIZA_INGRESO_PLANTA')
    salida = OPERACION_PLANTA_LOG.objects.filter(
        CI_NID_id=OuterRef('pk'), EP_NID_id=empresa_id, PL_NID_id=OuterRef('PL_NID_id'),
        OPL_CPASO='Confirmar Salida', OPL_CESTADO='COMPLETADO')
    consulta = CITACION.objects.filter(
        EP_NID_id=empresa_id, SC_NID__EP_NID_id=empresa_id,
        PL_NID__EP_NID_id=empresa_id, CI_BHABILITADO=True, CI_BARCHIVADO=False,
        PL_NID__PL_BARCHIVADO=False, CI_FFECHATERMINO__isnull=True,
        CI_CTIPO__in=('RECEPCION', 'DESPACHO'),
    ).exclude(CI_CESTADO__in=CERRADOS).filter(
        Exists(habilitado), Exists(ingreso), ~Exists(salida))
    if secuencias_permitidas is not None:
        consulta = consulta.filter(SC_NID_id__in=secuencias_permitidas)
    citas = list(consulta.select_related(
        'SC_NID', 'PL_NID', 'EP_NID', 'CA_NID', 'CON_NID',
        'detalle_operacional', 'detalle_despacho', 'detalle_recepcion_terramar',
        'resultado_calidad_operacion').order_by('id'))
    soportadas = [c for c in citas if (empresa_id, c.SC_NID.SE_CCODIGO, c.CI_CTIPO) in REGLAS]
    ids = [c.id for c in soportadas]
    detalles, tecnicos, logs, datos, reservas = (defaultdict(list) for _ in range(5))
    if ids:
        for d in DETALLE_SECUENCIA.objects.filter(
            EP_NID_id=empresa_id, SC_NID_id__in={c.SC_NID_id for c in soportadas},
            SE_BHABILITADO=True, SE_FFECHAELIMICACION__isnull=True,
        ).select_related('ET_NID').order_by('SE_NPASO', 'id'):
            detalles[d.SC_NID_id].append(d)
        for l in ETAPA_LOG.objects.filter(
            CI_NID_id__in=ids, EP_NID_id=empresa_id, SC_NID_id=F('CI_NID__SC_NID_id'),
        ).order_by('id'):
            tecnicos[l.CI_NID_id].append(l)
        for l in OPERACION_PLANTA_LOG.objects.filter(
            CI_NID_id__in=ids, EP_NID_id=empresa_id, PL_NID_id=F('CI_NID__PL_NID_id'),
        ).order_by('OPL_FFECHAREGISTRO', 'id'):
            logs[l.CI_NID_id].append(l)
        for d in DATO_OPERACION.objects.filter(
            CI_NID_id__in=ids, EP_NID_id=empresa_id,
            SC_NID_id=F('CI_NID__SC_NID_id'), CAMP_NID__EP_NID_id=empresa_id,
            CAMP_NID__CA_CCODIGO__in=CAMPOS,
        ).select_related('CAMP_NID').order_by('id'):
            datos[d.CI_NID_id].append(d)
        for r in ESTANQUE_RESERVA.objects.filter(
            CI_NID_id__in=ids, EP_NID_id=empresa_id, PL_NID_id=F('CI_NID__PL_NID_id'),
            ER_CESTADO='OCUPADO',
        ).order_by('ER_FFECHA_ASIGNACION', 'id'):
            reservas[r.CI_NID_id].append(r)

    camiones = []
    for c in soportadas:
        ds = detalles[c.SC_NID_id]
        por_etapa = {d.ET_NID_id: d for d in ds}
        tls = [l for l in tecnicos[c.id] if l.ET_NID_id in por_etapa]
        abierto = next((l for l in tls if l.EL_FFECHAFIN is None), None)
        tecnico = abierto or max(tls, key=lambda l: (l.EL_FFECHAFIN, l.id), default=None)
        detalle = por_etapa.get(tecnico.ET_NID_id) if tecnico else next((d for d in ds if d.SE_NPASO == 1), None)
        etapa = detalle.ET_NID if detalle else None
        adaptada = CitacionPrecargada(c, etapa)
        _, pasos_config = views.obtener_pasos_operacion_citacion(adaptada)
        pasos = [p for p, _ in pasos_config]
        completados = {l.OPL_CPASO for l in logs[c.id] if l.OPL_CESTADO == 'COMPLETADO'}
        calidad = _relacion(c, 'resultado_calidad_operacion')
        if calidad and calidad.PL_NID_id != c.PL_NID_id:
            calidad = None
        if calidad and calidad.RCO_CESTADO == 'RECHAZADO' and calidad.RCO_FCIERRE:
            continue
        paso = views.resolver_estado_operacional_visible(
            adaptada, pasos_config, completados, resultado_calidad=calidad)
        if not pasos or all(p in completados for p in pasos):
            continue
        cod = c.SC_NID.SE_CCODIGO
        reglas = dict(REGLAS[(empresa_id, cod, c.CI_CTIPO)])
        if etapa:
            override = REGLAS_ETAPA.get((empresa_id, cod, etapa.ET_CCODIGO, paso))
            if override:
                reglas[paso] = override
        valores = {d.CAMP_NID.CA_CCODIGO: d for d in datos[c.id]}
        zona, inicio, fin, fuente = _zona_y_reloj(adaptada, paso, reglas, valores, calidad, logs[c.id], abierto, pasos)
        operacional = _relacion(c, 'detalle_operacional')
        despacho = _relacion(c, 'detalle_despacho')
        recepcion = _relacion(c, 'detalle_recepcion_terramar')
        reserva = reservas[c.id][-1] if reservas[c.id] else None
        destino = (_valor(valores, 'ETA3_ESTANQUE') or getattr(operacional, 'CDO_CESTANQUE_DESTINO', '')
                   or getattr(reserva, 'ER_CESTANQUE', '') or '')
        origen = _valor(valores, 'ACD_ESTANQUE_ORIGEN') or getattr(operacional, 'CDO_CESTANQUE_ORIGEN', '') or ''
        almacen = (getattr(operacional, 'CDO_CALMACEN_DESTINO', '')
                   or getattr(reserva, 'ER_CALMACEN', '') or '')
        if c.CI_CTIPO == 'DESPACHO':
            almacen = _valor(valores, 'ACD_ZONA_CARGA')
        zona_operacional = zona
        zona = ZONAS_FISICAS.get(zona_operacional, zona_operacional)
        if zona_operacional in ('CARGA', 'DESCARGA'):
            estanque = origen if c.CI_CTIPO == 'DESPACHO' else destino
            precisa = ESTANQUES_CONFIRMADOS.get((empresa_id, cod, almacen, estanque))
            if precisa in zonas and zonas[precisa]['habilitado']:
                zona = precisa
        if zona not in zonas or not zonas[zona]['habilitado']:
            zona = 'OTRO'
        camion = _relacion(c, 'CA_NID')
        conductor = _relacion(c, 'CON_NID')
        patente = (_valor(valores, 'ING_PATENTE') or getattr(despacho, 'CDD_CPATENTE', '')
                   or getattr(recepcion, 'RTD_CPATENTE', '') or getattr(camion, 'CAM_CPATENTE', '') or 'Sin patente')
        camiones.append({
            'citacion_id': c.id, 'patente': patente, 'empresa_id': empresa_id,
            'empresa': c.EP_NID.EP_CRAZONSOCIAL, 'tipo': c.CI_CTIPO,
            'color': 'verde' if c.CI_CTIPO == 'RECEPCION' else 'azul',
            'secuencia_id': c.SC_NID_id, 'secuencia': cod, 'secuencia_nombre': c.SC_NID.SE_CNOMBRE,
            'etapa': views.nombre_visible_paso_operacion(adaptada, paso), 'paso_operacional': paso,
            'etapa_id': etapa.id if etapa else None, 'etapa_codigo': etapa.ET_CCODIGO if etapa else None,
            'detalle_secuencia_id': detalle.id if detalle else None, 'paso_tecnico': detalle.SE_NPASO if detalle else None,
            'zona': zona, 'zona_operacional': zona_operacional, 'estado': c.CI_CESTADO,
            'inicio_etapa': inicio.isoformat() if inicio else None,
            'fin_temporizador': fin.isoformat() if fin else None,
            'segundos_etapa': max(0, int(((fin or ahora) - inicio).total_seconds())) if inicio else None,
            'timer_activo': bool(inicio and not fin), 'fuente_timestamp': fuente,
            'producto': getattr(operacional, 'CDO_CINSUMO', '') or getattr(despacho, 'CDD_CSAP_NOMBRE_PRODUCTO', '') or '',
            'transportista': _valor(valores, 'ING_TRANSPORTISTA') or getattr(despacho, 'CDD_CEMPRESA_TRANSPORTE', '') or getattr(recepcion, 'RTD_CEMPRESA_TRANSPORTE', '') or '',
            'conductor': _valor(valores, 'ING_CONDUCTOR') or getattr(despacho, 'CDD_CCONDUCTOR', '') or getattr(recepcion, 'RTD_CCONDUCTOR', '') or ' '.join(filter(None, [getattr(conductor, 'CON_CNOMBRE', ''), getattr(conductor, 'CON_CAPELLIDO', '')])),
            'documento': getattr(operacional, 'CDO_CGUIA', '') or c.CI_CNUMERODOCUMENTO or '',
            'estanque_origen': origen, 'estanque_destino': destino,
            'eventos': [{'paso': l.OPL_CPASO, 'estado': l.OPL_CESTADO,
                         'fecha': l.OPL_FFECHAREGISTRO.isoformat()} for l in logs[c.id][-5:]],
            'trazabilidad_url': reverse('trazabilidad_buscar') + '?' + urlencode({'_empresa_id': empresa_id, 'q': c.id}),
            'zona_legacy_id': etapa.ZON_NID_id if etapa else None,
        })
    por_zona = Counter(c['zona_operacional'] for c in camiones)
    cupos = Counter(c['zona_legacy_id'] for c in camiones)
    capacidades = [{'id': z.id, 'nombre': z.ZON_CNOMBRE, 'ocupados': cupos[z.id],
                    'maximos': z.ZON_NCANTIDADCUPOS} for z in ZONA.objects.filter(EP_NID_id=empresa_id, ZON_BHABILITADO=True)]
    empresa_nombre = EMPRESA.objects.filter(pk=empresa_id).values_list('EP_CRAZONSOCIAL', flat=True).first()
    return {'empresa_id': empresa_id, 'empresa': empresa_nombre, 'generado_en': ahora.isoformat(), 'poll_segundos': 15,
            'camiones': camiones, 'zonas': list(zonas.values()), 'cupos': capacidades,
            'sin_soporte': len(citas) - len(soportadas),
            'kpis': {'total': len(camiones), 'recepciones': sum(c['tipo'] == 'RECEPCION' for c in camiones),
                     'despachos': sum(c['tipo'] == 'DESPACHO' for c in camiones), 'romana': por_zona['ROMANA'],
                     'calidad': por_zona['ESPERA_CALIDAD'], 'carga_descarga': por_zona['CARGA'] + por_zona['DESCARGA'],
                     'salida': por_zona['SALIDA']},
            'backend_ms': round((perf_counter() - comienzo) * 1000, 2)}
