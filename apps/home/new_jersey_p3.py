"""Planificación y llegada física de New Jersey Proceso 3."""

import json
import re
import unicodedata
from datetime import datetime, time

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.home.models import (
    CALENDARIO, CAMION_PATIO, CAMION_PATIO_TRAZABILIDAD_PLANIFICACION,
    CAMPO, CITACION, CITACION_DETALLE_OPERACIONAL, CITACION_ITEM, DATO_OPERACION,
    DETALLE_SECUENCIA, ETAPA_LOG, OPERACION_NEW_JERSEY, OPERACION_NEW_JERSEY_PROCESO,
    OPERACION_PLANTA_LOG, PLANIFICACION, SECUENCIA, SOCIONEGOCIO, SYSLOGGER,
)
from apps.home.sap_recepcion_new_jersey import obtener_lote_sap_new_jersey_p1

EMPRESA_NJ = 2
SECUENCIA_P3 = 'RECEPCION_NEW_JERSEY_P3_RETIRO_VACIO'
ESTADO_CITACION_P3_PENDIENTE = 'PENDIENTE_INGRESO_CAMION_P3'
ESTADO_CITACION_P3_CAMION_CONFIRMADO = 'CAMION_P3_CONFIRMADO'
CAMPO_SNAPSHOT_P3 = 'NJ_P3_SNAPSHOT'
RESULTADO_PATIO_P3 = 'NEW_JERSEY_P3_MATCH'


class CarpetaRecepcionP3Ambigua(ValueError):
    pass


class ProcesosVivosPatenteAmbiguos(ValueError):
    pass


def normalizar_patente(valor):
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return re.sub(r'[^A-Z0-9]', '', texto.upper())


def _normalizar_fecha_camion_patio(valor, etiqueta):
    """Usa el formato documental DDMMAAAA que admite CAMION_PATIO."""
    texto = str(valor or '').strip()
    if not texto:
        return ''
    for formato in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d%m%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto, formato).strftime('%d%m%Y')
        except ValueError:
            continue
    raise ValueError(f'{etiqueta} persistida no es válida para confirmar el camión P3.')


def _fecha_planificacion(planificacion):
    calendario = planificacion.CAL_NID
    return datetime(
        calendario.CA_NANO, calendario.CA_NMES, calendario.CA_NDIA,
    ).date()


def _intervalo_planificacion(calendario, fecha):
    inicio_hora = calendario.CA_FHORA_APERTURA or time(0, 0)
    fin_hora = calendario.CA_FHORA_CIERRE or time(23, 59, 59)
    inicio = timezone.make_aware(datetime.combine(fecha, inicio_hora))
    fin = timezone.make_aware(datetime.combine(fecha, fin_hora))
    return inicio, fin


def resolver_planificacion_recepcion_p3(usuario, ahora=None):
    """Resuelve una carpeta RECEPCION del día sin elegir duplicados arbitrariamente."""
    ahora = timezone.localtime(ahora or timezone.now())
    fecha = ahora.date()
    base = PLANIFICACION.objects.select_for_update().select_related('CAL_NID').filter(
        EP_NID_id=EMPRESA_NJ,
        PL_CTIPOCUPO='RECEPCION',
        PL_BARCHIVADO=False,
    ).filter(
        Q(CAL_NID__CA_NDIA=fecha.day,
          CAL_NID__CA_NMES=fecha.month,
          CAL_NID__CA_NANO=fecha.year)
        | Q(PL_FFECHAINICIO__date=fecha)
    ).order_by('PL_FFECHAINICIO', 'id')
    candidatas = list(base)
    activas = [
        plan for plan in candidatas
        if plan.PL_FFECHAINICIO
        and plan.PL_FFECHAINICIO <= ahora
        and (not plan.PL_FFECHAFIN or ahora <= plan.PL_FFECHAFIN)
    ]
    if len(activas) == 1:
        return activas[0], False
    if len(activas) > 1:
        raise CarpetaRecepcionP3Ambigua(
            'Existen varias carpetas de Recepción activas para hoy; debe corregirse la planificación antes de iniciar P3.'
        )
    if len(candidatas) == 1:
        return candidatas[0], False
    if len(candidatas) > 1:
        raise CarpetaRecepcionP3Ambigua(
            'Existen varias carpetas de Recepción para hoy y ninguna regla horaria permite resolver una única carpeta.'
        )

    calendarios = list(CALENDARIO.objects.select_for_update().filter(
        EP_NID_id=EMPRESA_NJ,
        CA_NDIA=fecha.day,
        CA_NMES=fecha.month,
        CA_NANO=fecha.year,
        CA_BHABILITADO=True,
    ).order_by('id')[:2])
    if len(calendarios) > 1:
        raise CarpetaRecepcionP3Ambigua(
            'Existen varios calendarios habilitados para hoy; no es posible crear automáticamente la carpeta P3.'
        )
    if calendarios:
        calendario = calendarios[0]
    else:
        calendario = CALENDARIO.objects.create(
            US_NID=usuario,
            EP_NID_id=EMPRESA_NJ,
            CA_CNOMBRE=f'ACEITES SBH: {fecha:%d/%m/%Y}',
            CA_FHORA_APERTURA=time(0, 0),
            CA_FHORA_CIERRE=time(23, 59),
            CA_NDIA=fecha.day,
            CA_NMES=fecha.month,
            CA_NANO=fecha.year,
            CA_NCANTIDADCUPOS=0,
            CA_BHABILITADO=True,
        )
    inicio, fin = _intervalo_planificacion(calendario, fecha)
    planificacion = PLANIFICACION.objects.create(
        US_NID=usuario,
        EP_NID_id=EMPRESA_NJ,
        CAL_NID=calendario,
        PL_CTIPOCUPO='RECEPCION',
        PL_FFECHAREGISTRO=timezone.now(),
        PL_FFECHAINICIO=inicio,
        PL_FFECHAFIN=fin,
        PL_NCANTIDADCUPOS=max(calendario.CA_NCANTIDADCUPOS or 0, 0),
        PL_NSOBRECUPO=True,
        PL_NCANTIDADSOBRECUPO=0,
        PL_BARCHIVADO=False,
    )
    return planificacion, True


def _relaciones_operacion(operacion):
    procesos = {
        proceso.ONJP_CTIPO: proceso
        for proceso in OPERACION_NEW_JERSEY_PROCESO.objects.select_related(
            'CI_NID__detalle_operacional', 'CI_NID__SC_NID', 'CI_NID__PRO_NID',
            'CI_NID__SN_NID',
        ).filter(ONJ_NID=operacion)
    }
    return (
        procesos.get(OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1),
        procesos.get(OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2),
        procesos.get(OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3),
    )


@transaction.atomic
def asegurar_citacion_item_p3(citacion, proceso_p1=None):
    """Hereda el ítem operacional legacy desde P1 sin crear catálogos nuevos."""
    citacion_id = getattr(citacion, 'pk', citacion)
    citacion = CITACION.objects.select_for_update().get(
        pk=citacion_id,
        EP_NID_id=EMPRESA_NJ,
    )
    existentes = list(CITACION_ITEM.objects.select_related('IT_NID').filter(
        CI_NID=citacion,
    ).order_by('id')[:2])
    if len(existentes) > 1:
        raise ValueError('La citación P3 tiene más de un insumo operacional asociado.')
    if existentes:
        relacion = existentes[0]
        if relacion.EP_NID_id != EMPRESA_NJ:
            raise ValueError('La relación de insumo operacional de P3 no pertenece a Empresa 2.')
        return relacion, False

    if proceso_p1 is None:
        proceso_p3 = OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            CI_NID=citacion,
            EP_NID_id=EMPRESA_NJ,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ).select_related('ONJ_NID').first()
        if not proceso_p3:
            raise ValueError('La citación P3 no tiene una operación New Jersey asociada.')
        proceso_p1 = OPERACION_NEW_JERSEY_PROCESO.objects.filter(
            ONJ_NID=proceso_p3.ONJ_NID,
            EP_NID_id=EMPRESA_NJ,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
        ).select_related('CI_NID').first()
    if not proceso_p1:
        raise ValueError('La operación New Jersey P3 no tiene una citación P1 de origen.')

    origenes = list(CITACION_ITEM.objects.select_related('IT_NID').filter(
        CI_NID=proceso_p1.CI_NID,
        EP_NID_id=EMPRESA_NJ,
    ).order_by('id')[:2])
    if not origenes:
        raise ValueError('La citación P1 de origen no tiene un insumo operacional asociado.')
    if len(origenes) > 1:
        raise ValueError('La citación P1 de origen tiene más de un insumo operacional asociado.')

    return CITACION_ITEM.objects.create(
        EP_NID=citacion.EP_NID,
        IT_NID=origenes[0].IT_NID,
        CI_NID=citacion,
    ), True

def _copiar_detalle(origen, destino, usuario, operacion):
    detalle_origen = getattr(origen, 'detalle_operacional', None)
    valores = {}
    if detalle_origen:
        valores = {
            campo.name: getattr(detalle_origen, campo.name)
            for campo in CITACION_DETALLE_OPERACIONAL._meta.fields
            if campo.name.startswith('CDO_') and campo.name != 'CDO_FFECHACREACION'
        }
    valores.update({
        'CDO_CORIGEN': 'new_jersey_p3',
        'CDO_CGUIA': origen.CI_CNUMERODOCUMENTO or valores.get('CDO_CGUIA') or '',
        'CDO_CCODIGO_SAP': operacion.ONJ_CITEM_CODE or valores.get('CDO_CCODIGO_SAP'),
        'CDO_CINSUMO': operacion.ONJ_CPRODUCTO or valores.get('CDO_CINSUMO'),
        'CDO_CPEDIDO_SAP': operacion.ONJ_CPURCHASE_ORDER or valores.get('CDO_CPEDIDO_SAP'),
        'CDO_CSAP_OPOR_ID': operacion.ONJ_CBASE_ENTRY or valores.get('CDO_CSAP_OPOR_ID'),
        'CDO_CDOCENTRY': operacion.ONJ_CBASE_ENTRY or valores.get('CDO_CDOCENTRY'),
        'CDO_CESTANQUE_DESTINO': (
            getattr(detalle_origen, 'CDO_CESTANQUE_DESTINO', '')
            or operacion.ONJ_CTK_DESTINO
            or ''
        ),
    })
    return CITACION_DETALLE_OPERACIONAL.objects.create(
        CI_NID=destino,
        EP_NID=destino.EP_NID,
        US_NID=usuario,
        **valores,
    )


def _etapa_p3(secuencia):
    detalle = DETALLE_SECUENCIA.objects.select_related('ET_NID').filter(
        SC_NID=secuencia, EP_NID_id=EMPRESA_NJ, SE_BHABILITADO=True,
    ).order_by('SE_NPASO', 'id').first()
    if not detalle:
        raise ValueError('La secuencia P3 no tiene una etapa habilitada.')
    return detalle.ET_NID


def _guardar_snapshot(citacion, usuario, etapa, metadata):
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID=citacion.EP_NID,
        CA_CCODIGO=CAMPO_SNAPSHOT_P3,
        defaults={
            'US_NID': usuario,
            'CA_CTIPO': 'TEXTO',
            'CA_CETIQUETA': 'Snapshot New Jersey P3',
            'CA_CPLACEMARK': 'Snapshot New Jersey P3',
            'CA_BOBLIGATORIO': False,
            'CA_BHABILITADO': True,
            'CA_BASIGNARVALOR': False,
        },
    )
    DATO_OPERACION.objects.update_or_create(
        CI_NID=citacion,
        CAMP_NID=campo,
        defaults={
            'US_NID': usuario,
            'EP_NID': citacion.EP_NID,
            'SC_NID': citacion.SC_NID,
            'ET_NID': etapa,
            'DO_FFECHAREGISTRO': timezone.now(),
            'DO_CVALOR': json.dumps(metadata, ensure_ascii=False),
        },
    )


def leer_snapshot_p3(citacion):
    dato = DATO_OPERACION.objects.filter(
        CI_NID=citacion,
        CAMP_NID__CA_CCODIGO=CAMPO_SNAPSHOT_P3,
    ).select_related('CAMP_NID').order_by('-id').first()
    if not dato:
        return {}
    try:
        metadata = json.loads(dato.DO_CVALOR or '{}')
    except (TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def preparar_revision_asistente_p3(citacion, usuario):
    """Deja el camión confirmado en el mismo punto de revisión que una recepción normal."""
    detalles = list(DETALLE_SECUENCIA.objects.select_related('ET_NID').filter(
        SC_NID=citacion.SC_NID,
        EP_NID_id=EMPRESA_NJ,
        SE_BHABILITADO=True,
    ).order_by('SE_NPASO', 'id')[:2])
    if len(detalles) < 2:
        raise ValueError('La secuencia P3 requiere al menos dos etapas para la revisión del camión.')

    ahora = timezone.now()
    primera, revision = detalles

    revision_cerrada = ETAPA_LOG.objects.filter(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=revision.ET_NID,
        EL_FFECHAFIN__isnull=False,
    ).order_by('-EL_FFECHAFIN', '-id').first()
    if revision_cerrada:
        return revision_cerrada

    log_primera, _ = ETAPA_LOG.objects.get_or_create(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=primera.ET_NID,
        defaults={
            'EL_FFECHAINICIO': citacion.CI_FFECHAINICIO or ahora,
            'US_INICIO_ID': usuario,
            'EL_CACCION': 'CAMION_P3_CONFIRMADO',
        },
    )
    if log_primera.EL_FFECHAFIN is None:
        log_primera.EL_FFECHAFIN = ahora
        log_primera.US_FIN_ID = usuario
        log_primera.EL_CACCION = 'CAMION_P3_CONFIRMADO'
        log_primera.EL_COBSERVACION = 'Camión P3 asociado físicamente; pendiente de revisión Asistente Recepción.'
        log_primera.save(update_fields=[
            'EL_FFECHAFIN', 'US_FIN_ID', 'EL_CACCION', 'EL_COBSERVACION',
        ])

    log_revision, _ = ETAPA_LOG.objects.get_or_create(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=revision.ET_NID,
        EL_FFECHAFIN=None,
        defaults={
            'EL_FFECHAINICIO': ahora,
            'US_INICIO_ID': usuario,
            'EL_CACCION': 'ENVIA_ASISTENTE',
            'EL_COBSERVACION': 'Camión P3 confirmado y pendiente de revisión Asistente Recepción.',
        },
    )
    cambios = []
    if log_revision.EL_CACCION != 'ENVIA_ASISTENTE':
        log_revision.EL_CACCION = 'ENVIA_ASISTENTE'
        cambios.append('EL_CACCION')
    if not log_revision.EL_COBSERVACION:
        log_revision.EL_COBSERVACION = 'Camión P3 confirmado y pendiente de revisión Asistente Recepción.'
        cambios.append('EL_COBSERVACION')
    if log_revision.US_INICIO_ID_id is None:
        log_revision.US_INICIO_ID = usuario
        cambios.append('US_INICIO_ID')
    if cambios:
        log_revision.save(update_fields=cambios)
    return log_revision


@transaction.atomic
def completar_p3(citacion, usuario, fecha=None):
    """Cierra la relación P3 y la operación New Jersey al confirmar la salida física."""
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.select_for_update().select_related(
        'ONJ_NID'
    ).get(
        CI_NID=citacion,
        EP_NID_id=EMPRESA_NJ,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
    )
    if proceso.ONJP_CESTADO != proceso.Estado.COMPLETADO:
        proceso.ONJP_CESTADO = proceso.Estado.COMPLETADO
        proceso.save(update_fields=['ONJP_CESTADO', 'ONJP_FFECHAMODIFICACION'])
    operacion = proceso.ONJ_NID
    if operacion.ONJ_CESTADO != operacion.Estado.COMPLETADA:
        operacion.ONJ_CESTADO = operacion.Estado.COMPLETADA
        operacion.ONJ_FFECHA_OPERACION = fecha or timezone.now()
        operacion.save(update_fields=[
            'ONJ_CESTADO', 'ONJ_FFECHA_OPERACION', 'ONJ_FFECHAMODIFICACION',
        ])
    return proceso


@transaction.atomic
def iniciar_p3(operacion_id, usuario, transportista_id, patente, ahora=None):
    operacion = OPERACION_NEW_JERSEY.objects.select_for_update(of=('self',)).select_related(
        'EP_NID', 'PRO_NID'
    ).get(pk=operacion_id, EP_NID_id=EMPRESA_NJ, ONJ_BHABILITADO=True)
    p1_rel, p2_rel, existente = _relaciones_operacion(operacion)
    if existente:
        asegurar_citacion_item_p3(existente.CI_NID, p1_rel)
        return {
            'proceso': existente,
            'citacion': existente.CI_NID,
            'planificacion': existente.CI_NID.PL_NID,
            'created': False,
        }
    if (
        operacion.ONJ_CESTADO != operacion.Estado.PENDIENTE_PROCESO_3
        or not p2_rel
        or p2_rel.ONJP_CESTADO != p2_rel.Estado.COMPLETADO
        or p2_rel.CI_NID.CI_CESTADO != 'TERMINADO'
    ):
        raise ValueError('P2 debe estar completado antes de iniciar P3.')
    transportista_id = str(transportista_id or '').strip()
    if not transportista_id.isdigit():
        raise ValueError('Debe seleccionar una empresa de transporte válida.')
    transportista = SOCIONEGOCIO.objects.filter(
        pk=int(transportista_id),
        EP_NID_id=EMPRESA_NJ,
        SN_BHABILITADO=True,
        SN_CTIPO='S',
    ).first()
    if not transportista:
        raise ValueError('Debe seleccionar una empresa de transporte válida.')
    patente = normalizar_patente(patente)
    if not patente:
        raise ValueError('Debe ingresar la patente planificada para P3.')

    secuencia = SECUENCIA.objects.filter(
        EP_NID_id=EMPRESA_NJ,
        SE_CCODIGO=SECUENCIA_P3,
        SE_BHABILITADO=True,
    ).first()
    if not secuencia:
        raise ValueError('La secuencia New Jersey P3 no está configurada.')
    etapa = _etapa_p3(secuencia)
    planificacion, carpeta_creada = resolver_planificacion_recepcion_p3(usuario, ahora=ahora)
    ahora = timezone.localtime(ahora or timezone.now())
    sin_cupo = planificacion.TOTAL_CUPOS_DISPONIBLES <= 0
    p2 = p2_rel.CI_NID
    p3 = CITACION.objects.create(
        US_NID=usuario,
        EP_NID=operacion.EP_NID,
        PL_NID=planificacion,
        SC_NID=secuencia,
        PRO_NID=p2.PRO_NID,
        SN_NID=p2.SN_NID,
        CI_FFECHAREGISTRO=timezone.now(),
        CI_FFECHACITACION=ahora,
        CI_NCUPO=planificacion.TOTAL_CITACIONES + 1,
        CI_CTIPO='RECEPCION',
        CI_CESTADO=ESTADO_CITACION_P3_PENDIENTE,
        CI_CTIPODOCUMENTO=p2.CI_CTIPODOCUMENTO,
        CI_CNUMERODOCUMENTO=p2.CI_CNUMERODOCUMENTO,
        CI_NID_REF=p2.id,
        CI_BHABILITADO=True,
        CI_BSOBRECUPO=sin_cupo,
    )
    detalle = _copiar_detalle(p2, p3, usuario, operacion)
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.create(
        ONJ_NID=operacion,
        CI_NID=p3,
        EP_NID=operacion.EP_NID,
        US_NID=usuario,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO,
    )
    asegurar_citacion_item_p3(p3, p1_rel)
    lote = obtener_lote_sap_new_jersey_p1(p1_rel.CI_NID) if p1_rel else {}
    metadata = {
        'operacion_id': operacion.id,
        'citacion_p1_id': p1_rel.CI_NID_id if p1_rel else None,
        'citacion_p2_id': p2.id,
        'citacion_p3_id': p3.id,
        'planificacion_id': planificacion.id,
        'carpeta_creada': carpeta_creada,
        'patente_esperada': patente,
        'transportista_id': transportista.id,
        'empresa_transporte': transportista.SN_CRAZONSOCIAL,
        'guia': p3.CI_CNUMERODOCUMENTO or '',
        'contenedor': detalle.CDO_CBL_CONTENEDOR or '',
        'item_code': operacion.ONJ_CITEM_CODE or detalle.CDO_CCODIGO_SAP or '',
        'producto': operacion.ONJ_CPRODUCTO or detalle.CDO_CINSUMO or '',
        'purchase_order': operacion.ONJ_CPURCHASE_ORDER or detalle.CDO_CPEDIDO_SAP or '',
        'base_entry': operacion.ONJ_CBASE_ENTRY or detalle.CDO_CDOCENTRY or '',
        'base_line': operacion.ONJ_CBASE_LINE or '',
        'tk_destino': detalle.CDO_CESTANQUE_DESTINO or operacion.ONJ_CTK_DESTINO or '',
        'lote_sap': lote.get('batch_number') or '',
        'usuario': getattr(usuario, 'username', ''),
        'usuario_id': getattr(usuario, 'pk', None),
        'fecha_hora': ahora.isoformat(),
    }
    _guardar_snapshot(p3, usuario, etapa, metadata)
    OPERACION_PLANTA_LOG.objects.create(
        US_NID=usuario,
        EP_NID=p3.EP_NID,
        PL_NID=planificacion,
        CI_NID=p3,
        OPL_CPASO='Iniciar Proceso 3',
        OPL_CPERFIL_RESPONSABLE='PLANIFICADOR',
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        OPL_COBSERVACION=(
            f'P3 iniciado. Patente esperada {patente}. '
            f'Transportista {transportista.SN_CRAZONSOCIAL}. Carpeta #{planificacion.id}.'
        ),
    )
    return {
        'proceso': proceso,
        'citacion': p3,
        'planificacion': planificacion,
        'created': True,
    }


def _proceso_p3_vivo(proceso):
    citacion = proceso.CI_NID
    return bool(
        proceso.ONJP_CESTADO == proceso.Estado.EN_PROCESO
        and citacion.CI_BHABILITADO
        and str(citacion.CI_CESTADO or '').strip().upper() not in {
            'TERMINADO', 'COMPLETADO', 'COMPLETADA', 'CANCELADO', 'ANULADO',
            'SALIDA_CONFIRMADA',
        }
    )


def datos_proceso_p3(proceso):
    citacion = proceso.CI_NID
    operacion = proceso.ONJ_NID
    snapshot = leer_snapshot_p3(citacion)
    detalle = getattr(citacion, 'detalle_operacional', None)
    p1_rel, p2_rel, _ = _relaciones_operacion(operacion)
    return {
        'proceso': 'P3',
        'operacion_id': operacion.id,
        'citacion_id': citacion.id,
        'citacion_p1_id': p1_rel.CI_NID_id if p1_rel else None,
        'citacion_p2_id': p2_rel.CI_NID_id if p2_rel else None,
        'patente_esperada': snapshot.get('patente_esperada') or '',
        'transportista_id': snapshot.get('transportista_id'),
        'empresa_transporte': snapshot.get('empresa_transporte') or '',
        'guia': citacion.CI_CNUMERODOCUMENTO or getattr(detalle, 'CDO_CGUIA', '') or '',
        'tipo_documento': citacion.CI_CTIPODOCUMENTO or '',
        'contenedor': getattr(detalle, 'CDO_CBL_CONTENEDOR', '') or '',
        'bl': getattr(detalle, 'CDO_CBL', '') or '',
        'tipo_recepcion': getattr(detalle, 'CDO_CTIPO_RECEPCION', '') or '',
        'cda': getattr(detalle, 'CDO_CCDA', '') or '',
        'di': getattr(detalle, 'CDO_CDI', '') or '',
        'booking': getattr(detalle, 'CDO_CBOOKING', '') or '',
        'naviera': getattr(detalle, 'CDO_CNAVE_NAVIERA', '') or '',
        'fecha_produccion': getattr(detalle, 'CDO_CFECHA_PRODUCCION', '') or '',
        'fecha_vencimiento': getattr(detalle, 'CDO_CFECHA_VENCIMIENTO', '') or '',
        'item_code': operacion.ONJ_CITEM_CODE or getattr(detalle, 'CDO_CCODIGO_SAP', '') or '',
        'producto': operacion.ONJ_CPRODUCTO or getattr(detalle, 'CDO_CINSUMO', '') or '',
        'proveedor': (
            operacion.PRO_NID.SN_CRAZONSOCIAL if operacion.PRO_NID_id
            else getattr(detalle, 'CDO_CPRODUCTOR', '') or ''
        ),
        'cliente': citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID_id else '',
        'pedido_sap': operacion.ONJ_CPURCHASE_ORDER or getattr(detalle, 'CDO_CPEDIDO_SAP', '') or '',
        'docentry': operacion.ONJ_CBASE_ENTRY or getattr(detalle, 'CDO_CDOCENTRY', '') or '',
        'base_line': operacion.ONJ_CBASE_LINE or snapshot.get('base_line') or '',
        'lote_sap': snapshot.get('lote_sap') or '',
        'tk_destino': getattr(detalle, 'CDO_CESTANQUE_DESTINO', '') or operacion.ONJ_CTK_DESTINO or '',
        'modalidad': operacion.ONJ_CMODALIDAD,
        'estado': proceso.ONJP_CESTADO,
        'camion_id': CAMION_PATIO.objects.filter(CI_NID=citacion).values_list('id', flat=True).first(),
    }


def buscar_procesos_vivos(empresa_id, patente=None, guia=None):
    """Retorna todos los P3 vivos compatibles, sin elegir candidatos arbitrariamente."""
    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError):
        return []
    if empresa_id != EMPRESA_NJ:
        return []
    patente = normalizar_patente(patente)
    guia = str(guia or '').strip().casefold()
    if not patente and not guia:
        return []

    candidatos = []
    procesos = OPERACION_NEW_JERSEY_PROCESO.objects.select_related(
        'CI_NID__detalle_operacional', 'CI_NID__SN_NID', 'ONJ_NID__PRO_NID',
    ).filter(
        EP_NID_id=EMPRESA_NJ,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO,
        ONJ_NID__ONJ_BHABILITADO=True,
    )
    for proceso in procesos:
        if not _proceso_p3_vivo(proceso):
            continue
        datos = datos_proceso_p3(proceso)
        if patente and normalizar_patente(datos['patente_esperada']) != patente:
            continue
        if guia and str(datos['guia'] or '').strip().casefold() != guia:
            continue
        candidatos.append(datos)
    return candidatos


def buscar_procesos_vivos_por_patente(patente, empresa_id):
    return buscar_procesos_vivos(empresa_id, patente=patente)


def consultar_proceso_vivo_por_patente(patente, empresa_id):
    candidatos = buscar_procesos_vivos_por_patente(patente, empresa_id)
    if len(candidatos) > 1:
        raise ProcesosVivosPatenteAmbiguos(
            'La patente está asociada a más de un proceso operativo vivo. Debe corregirse la inconsistencia antes de continuar.'
        )
    return candidatos[0] if candidatos else None


@transaction.atomic
def confirmar_camion_p3(
    citacion_id,
    patente,
    usuario,
    *,
    transportista_id=None,
    empresa_transporte=None,
    nombre_conductor='',
    rut_conductor='',
    codigo_pais='',
    telefono_conductor='',
):
    patente = normalizar_patente(patente)
    citacion = CITACION.objects.select_for_update(of=('self',)).select_related(
        'EP_NID', 'PL_NID', 'SC_NID', 'SN_NID', 'detalle_operacional'
    ).get(pk=citacion_id, EP_NID_id=EMPRESA_NJ, CI_BHABILITADO=True)
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.select_for_update(of=('self',)).select_related(
        'ONJ_NID__PRO_NID'
    ).get(
        CI_NID=citacion,
        EP_NID_id=EMPRESA_NJ,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
    )
    if not _proceso_p3_vivo(proceso):
        raise ValueError('El proceso P3 ya no está activo.')
    datos = datos_proceso_p3(proceso)
    transportista_esperado = str(datos.get('transportista_id') or '').strip()
    transportista_recibido = str(transportista_id or '').strip()
    if transportista_id is not None and transportista_recibido != transportista_esperado:
        raise ValueError('La empresa de transporte no coincide con la planificada para P3.')
    empresa_esperada = ' '.join(str(datos.get('empresa_transporte') or '').split())
    empresa_recibida = ' '.join(str(empresa_transporte or '').split())
    if empresa_transporte is not None and empresa_recibida.casefold() != empresa_esperada.casefold():
        raise ValueError('La empresa de transporte no coincide con la planificada para P3.')
    esperada = normalizar_patente(datos['patente_esperada'])
    if not patente or patente != esperada:
        raise ValueError('La patente ingresada no coincide con la patente planificada para P3.')
    existentes = list(CAMION_PATIO.objects.select_for_update().filter(CI_NID=citacion).order_by('id')[:2])
    if len(existentes) > 1:
        raise ValueError('La citación P3 tiene más de un CAMION_PATIO asociado.')
    if existentes:
        camion = existentes[0]
        if normalizar_patente(camion.CPA_CPATENTE) != esperada:
            raise ValueError('El CAMION_PATIO existente no coincide con la patente planificada para P3.')
        preparar_revision_asistente_p3(citacion, usuario)
        return camion, False
    otros = [
        camion for camion in CAMION_PATIO.objects.select_for_update().filter(
            EP_NID_id=EMPRESA_NJ,
            CPA_CESTADO__in=CAMION_PATIO.ESTADOS_ACTIVOS,
        ).exclude(CI_NID=citacion)
        if normalizar_patente(camion.CPA_CPATENTE) == esperada
    ]
    if otros:
        raise ValueError('La patente ya tiene otro proceso activo en patio.')
    detalle = citacion.detalle_operacional
    camion = CAMION_PATIO.objects.create(
        EP_NID=citacion.EP_NID,
        CI_NID=citacion,
        CPA_CPATENTE=esperada,
        CPA_CNOMBRE_CONDUCTOR=str(nombre_conductor or '').strip(),
        CPA_CRUT_CONDUCTOR=str(rut_conductor or '').strip(),
        CPA_CTELEFONO_CONDUCTOR=str(telefono_conductor or '').strip(),
        CPA_CCODIGO_PAIS_TELEFONO=str(codigo_pais or '').strip(),
        CPA_CTRANSPORTISTA_DECLARADO=empresa_esperada,
        CPA_CPROVEEDOR_DECLARADO=datos['proveedor'],
        CPA_CCLIENTE_DECLARADO=datos['cliente'],
        CPA_CPRODUCTO_DECLARADO=datos['producto'],
        CPA_CINSUMO_DECLARADO_GUIA=datos['producto'],
        CPA_CTIPO_RECEPCION=datos['tipo_recepcion'],
        CPA_CCDA=datos['cda'],
        CPA_CDI=datos['di'],
        CPA_CNAVE_NAVIERA=datos['naviera'],
        CPA_CFECHAPRODUCCION=_normalizar_fecha_camion_patio(datos['fecha_produccion'], 'La fecha de producción'),
        CPA_CFECHAVENCIMIENTOPRODUCTO=_normalizar_fecha_camion_patio(datos['fecha_vencimiento'], 'La fecha de vencimiento'),
        CPA_CTIPO_DOCUMENTO=citacion.CI_CTIPODOCUMENTO or CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
        CPA_CNUMERO_GUIA=datos['guia'],
        CPA_CBL=datos['bl'],
        CPA_CLOTE_CONTENEDOR=datos['contenedor'],
        CPA_COBSERVACION=f'New Jersey P3 · Operación #{proceso.ONJ_NID_id}',
        CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        US_GUARDIA_ID=usuario,
        US_ASOCIA_ID=usuario,
        CPA_FFECHAASOCIACION=timezone.now(),
    )
    CAMION_PATIO_TRAZABILIDAD_PLANIFICACION.objects.create(
        CPA_NID=camion,
        CI_NID=citacion,
        PL_NID=citacion.PL_NID,
        EP_NID=citacion.EP_NID,
        CPTR_CPATENTE_CONSULTADA=patente,
        CPTR_CRESULTADO_BUSQUEDA=RESULTADO_PATIO_P3,
        CPTR_BCARGADO_DESDE_PLANIFICACION=True,
        CPTR_CPATENTE_PLANIFICADA=esperada,
        CPTR_CPATENTE_LLEGADA=esperada,
        CPTR_CGUIA_ESPERADA=datos['guia'],
        CPTR_CGUIA_RECIBIDA=datos['guia'],
        CPTR_CRESULTADO_GUIA='COINCIDE',
        US_NID=usuario,
        CPTR_FFECHACONSULTA=timezone.now(),
    )
    citacion.CI_CESTADO = ESTADO_CITACION_P3_CAMION_CONFIRMADO
    citacion.CI_FFECHAINICIO = citacion.CI_FFECHAINICIO or timezone.now()
    citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHAINICIO'])
    preparar_revision_asistente_p3(citacion, usuario)
    OPERACION_PLANTA_LOG.objects.create(
        US_NID=usuario,
        EP_NID=citacion.EP_NID,
        PL_NID=citacion.PL_NID,
        CI_NID=citacion,
        OPL_CPASO='Confirmar Camión P3',
        OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        OPL_COBSERVACION=json.dumps({
            'operacion_new_jersey': proceso.ONJ_NID_id,
            'citacion_p3': citacion.id,
            'patente_consultada': patente,
            'patente_esperada': esperada,
            'transportista': datos['empresa_transporte'],
            'usuario': getattr(usuario, 'username', ''),
            'fecha_hora': timezone.now().isoformat(),
        }, ensure_ascii=False),
    )
    return camion, True

@transaction.atomic
def reparar_transicion_guardia_p3(citacion_id):
    """Convierte la transición legacy P3 a la aprobación canónica hacia Guardia."""
    citacion = CITACION.objects.select_for_update().select_related(
        'EP_NID', 'SC_NID', 'PL_NID'
    ).get(pk=citacion_id)

    if citacion.EP_NID_id != EMPRESA_NJ or not citacion.SC_NID or citacion.SC_NID.SE_CCODIGO != SECUENCIA_P3:
        raise ValueError('La citación indicada no corresponde a New Jersey P3 de Empresa 2.')

    relacion_p3 = OPERACION_NEW_JERSEY_PROCESO.objects.select_for_update().filter(
        CI_NID=citacion,
        EP_NID_id=EMPRESA_NJ,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
    ).first()
    if not relacion_p3:
        raise ValueError('La citación no tiene una relación New Jersey P3 válida.')

    transiciones_erroneas = SYSLOGGER.objects.select_for_update().filter(
        LOG_COPERACION='ENVIA_CD_NEXT',
        LOG_CADD1=str(citacion.id),
    )
    aprobacion_existente = SYSLOGGER.objects.filter(
        LOG_COPERACION='APRUEBA_AR',
        LOG_CADD1=str(citacion.id),
    ).exists()
    if not transiciones_erroneas.exists() and not aprobacion_existente:
        raise ValueError('La citación P3 no registra una aprobación de Asistente Recepción para reparar.')

    syslogger_corregidos = transiciones_erroneas.update(LOG_COPERACION='APRUEBA_AR')
    etapas_corregidas = ETAPA_LOG.objects.select_for_update().filter(
        CI_NID=citacion,
        EL_CACCION='ENVIA_CD_NEXT',
    ).update(EL_CACCION='APRUEBA_ASISTENTE')

    if SYSLOGGER.objects.filter(
        LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
        LOG_CADD1=str(citacion.id),
    ).exists():
        responsable_siguiente = 'OPERACION_PLANTA'
    elif SYSLOGGER.objects.filter(
        LOG_COPERACION='ENVIA_GUARDIA_PORTERIA',
        LOG_CADD1=str(citacion.id),
    ).exists():
        responsable_siguiente = 'GUARDIA_PORTERIA'
    else:
        responsable_siguiente = 'GUARDIA'

    return {
        'citacion_id': citacion.id,
        'planificacion_id': citacion.PL_NID_id,
        'syslogger_corregidos': syslogger_corregidos,
        'etapas_corregidas': etapas_corregidas,
        'responsable_siguiente': responsable_siguiente,
        'aprobacion_conservada': SYSLOGGER.objects.filter(
            LOG_COPERACION='APRUEBA_AR',
            LOG_CADD1=str(citacion.id),
        ).exists(),
    }
