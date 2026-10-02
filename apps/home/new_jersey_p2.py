"""Internal New Jersey process 2 lifecycle. No truck or SAP side effects."""

import json

from django.db import transaction
from django.utils import timezone

from apps.home.models import (
    CAMPO, CITACION, CITACION_DETALLE_OPERACIONAL, DATO_OPERACION,
    DETALLE_SECUENCIA, ETAPA, ETAPA_LOG, OPERACION_NEW_JERSEY,
    OPERACION_NEW_JERSEY_PROCESO, OPERACION_PLANTA_LOG, SECUENCIA,
)

EMPRESA_NJ = 2
SECUENCIA_P2 = 'RECEPCION_NEW_JERSEY_P2_OPERACION_INTERNA'
SECUENCIAS_P1 = {'RECEPCION_NEW_JERSEY_P1_CON_CALIDAD', 'RECEPCION_NEW_JERSEY_P1_SIN_CALIDAD'}
PASO_TOMA = 'Toma de muestra'
PASO_CALIDAD = 'Calidad'
PASO_DESCARGA = 'Ciclo Descarga'
PASOS_P2 = (PASO_TOMA, PASO_CALIDAD, PASO_DESCARGA)
RESPONSABLE_P2 = 'ASISTENTE C D'
ESTADO_CITACION_PENDIENTE = 'PENDIENTE_PROCESO_2'
CAMPO_SNAPSHOT_P2 = 'NJ_P2_SNAPSHOT_P1'
LOG_CAMBIO_TK_P2 = 'NJ_P2_CAMBIO_TK_DESTINO'
MENSAJE_TK_INVALIDO_P2 = 'No debe crear la solicitud SAP sin un estanque destino válido.'
ETAPAS_P2 = (
    ('NJ_P2_PENDIENTE', 'Pendiente Proceso 2'),
    ('NJ_P2_TOMA_MUESTRA', PASO_TOMA),
    ('NJ_P2_CALIDAD', PASO_CALIDAD),
    ('NJ_P2_DESCARGA', PASO_DESCARGA),
)


def asegurar_secuencia_p2(usuario):
    """Configure only the Empresa 2 P2 sequence, including old placeholder rows."""
    secuencia, _ = SECUENCIA.objects.get_or_create(
        EP_NID_id=EMPRESA_NJ, SE_CCODIGO=SECUENCIA_P2,
        defaults={
            'US_NID': usuario, 'SE_CTIPO': 'RECEPCION',
            'SE_CNOMBRE': 'Sector New Jersey - Proceso 2 Operación interna',
            'SE_BHABILITADO': True,
        },
    )
    etapas = {}
    for numero, (codigo, nombre) in enumerate(ETAPAS_P2, start=1):
        etapa, _ = ETAPA.objects.get_or_create(
            EP_NID_id=EMPRESA_NJ, ET_CCODIGO=codigo,
            defaults={
                'US_NID': usuario, 'ET_CTIPO': 'OPERACION',
                'ET_CNOMBRE': nombre, 'ET_NCANTIDADMAXIMA': 1,
                'ET_BHABILITADO': True,
            },
        )
        cambios_etapa = []
        if etapa.ET_CNOMBRE != nombre:
            etapa.ET_CNOMBRE = nombre
            cambios_etapa.append('ET_CNOMBRE')
        if not etapa.ET_BHABILITADO:
            etapa.ET_BHABILITADO = True
            cambios_etapa.append('ET_BHABILITADO')
        if cambios_etapa:
            etapa.save(update_fields=cambios_etapa)
        detalles = list(DETALLE_SECUENCIA.objects.filter(
            EP_NID_id=EMPRESA_NJ, SC_NID=secuencia, SE_NPASO=numero,
        ).order_by('id')[:2])
        if len(detalles) > 1:
            raise ValueError(f'La etapa técnica P2 {numero} está duplicada.')
        if detalles:
            detalle = detalles[0]
            if detalle.ET_NID_id != etapa.id or not detalle.SE_BHABILITADO:
                detalle.ET_NID = etapa
                detalle.SE_BHABILITADO = True
                detalle.save(update_fields=['ET_NID', 'SE_BHABILITADO'])
        else:
            DETALLE_SECUENCIA.objects.create(
                US_NID=usuario, EP_NID_id=EMPRESA_NJ, SC_NID=secuencia,
                ET_NID=etapa, SE_NPASO=numero, SE_BHABILITADO=True,
                SE_BOBLIGATORIO=True,
            )
        etapas[nombre] = etapa
    return secuencia, etapas


def _relacion_p1(citacion_p1):
    if (
        citacion_p1.EP_NID_id != EMPRESA_NJ
        or citacion_p1.CI_CTIPO != 'RECEPCION'
        or citacion_p1.SC_NID.SE_CCODIGO not in SECUENCIAS_P1
    ):
        raise ValueError('La citación no corresponde a New Jersey Proceso 1.')
    relacion = OPERACION_NEW_JERSEY_PROCESO.objects.select_related('ONJ_NID').filter(
        CI_NID=citacion_p1,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1,
        EP_NID_id=EMPRESA_NJ,
    ).first()
    if not relacion:
        raise ValueError('No existe operación New Jersey asociada a P1.')
    return relacion


def _snapshot_p1(citacion_p1, operacion, guia, contenedor):
    return {
        'operacion_id': operacion.id,
        'citacion_p1_id': citacion_p1.id,
        'guia': guia,
        'contenedor': contenedor,
        'item_code': operacion.ONJ_CITEM_CODE or '',
        'producto': operacion.ONJ_CPRODUCTO or '',
        'purchase_order': operacion.ONJ_CPURCHASE_ORDER or '',
        'base_entry': operacion.ONJ_CBASE_ENTRY or '',
        'base_line': operacion.ONJ_CBASE_LINE or '',
        'tk_destino': operacion.ONJ_CTK_DESTINO or '',
    }

@transaction.atomic
def preparar_p2_desde_cierre_p1(citacion_p1, usuario, guia):
    """Create one pending P2 from a completed P1, preserving its source snapshot."""
    relacion_p1 = _relacion_p1(citacion_p1)
    operacion = OPERACION_NEW_JERSEY.objects.select_for_update().get(
        pk=relacion_p1.ONJ_NID_id, EP_NID_id=EMPRESA_NJ,
    )
    if citacion_p1.CI_CESTADO != 'TERMINADO' or not OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion_p1, OPL_CPASO='Confirmar Salida',
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).exists():
        raise ValueError('P1 debe estar cerrado antes de preparar Proceso 2.')
    existente = OPERACION_NEW_JERSEY_PROCESO.objects.filter(
        ONJ_NID=operacion,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
    ).select_related('CI_NID').first()
    if existente:
        if relacion_p1.ONJP_CESTADO != relacion_p1.Estado.COMPLETADO:
            relacion_p1.ONJP_CESTADO = relacion_p1.Estado.COMPLETADO
            relacion_p1.save(update_fields=['ONJP_CESTADO'])
        if existente.ONJP_CESTADO == existente.Estado.PENDIENTE and operacion.ONJ_CESTADO == operacion.Estado.PENDIENTE_PROCESO_1:
            operacion.ONJ_CESTADO = operacion.Estado.PENDIENTE_PROCESO_2
            operacion.save(update_fields=['ONJ_CESTADO'])
        return existente, False

    guia = str(guia or '').strip()
    detalle_p1 = CITACION_DETALLE_OPERACIONAL.objects.filter(CI_NID=citacion_p1).first()
    contenedor = str(getattr(detalle_p1, 'CDO_CBL_CONTENEDOR', '') or '').strip()
    if not guia:
        raise ValueError('P1 no tiene guía para heredar a Proceso 2.')
    if not contenedor:
        raise ValueError('P1 no tiene contenedor para heredar a Proceso 2.')
    secuencia, etapas = asegurar_secuencia_p2(usuario)
    p2 = CITACION.objects.create(
        US_NID=usuario, EP_NID=citacion_p1.EP_NID, PL_NID=citacion_p1.PL_NID,
        SC_NID=secuencia, PRO_NID=citacion_p1.PRO_NID,
        SN_NID=citacion_p1.SN_NID, CI_FFECHAREGISTRO=timezone.now(),
        CI_FFECHACITACION=citacion_p1.CI_FFECHACITACION,
        CI_NCUPO=0, CI_CTIPO='RECEPCION',
        CI_CESTADO=ESTADO_CITACION_PENDIENTE,
        CI_CTIPODOCUMENTO=citacion_p1.CI_CTIPODOCUMENTO,
        CI_CNUMERODOCUMENTO=guia, CI_NID_REF=citacion_p1.id,
        CI_BHABILITADO=True,
    )
    detalle_valores = {}
    if detalle_p1:
        detalle_valores = {
            campo.name: getattr(detalle_p1, campo.name)
            for campo in CITACION_DETALLE_OPERACIONAL._meta.fields
            if campo.name.startswith('CDO_') and campo.name != 'CDO_FFECHACREACION'
        }
    detalle_valores.update({
        'CDO_CORIGEN': 'new_jersey_p1',
        'CDO_CGUIA': guia,
        'CDO_CBL_CONTENEDOR': contenedor,
        'CDO_CCODIGO_SAP': operacion.ONJ_CITEM_CODE or detalle_valores.get('CDO_CCODIGO_SAP'),
        'CDO_CINSUMO': operacion.ONJ_CPRODUCTO or detalle_valores.get('CDO_CINSUMO'),
        'CDO_CPEDIDO_SAP': operacion.ONJ_CPURCHASE_ORDER or detalle_valores.get('CDO_CPEDIDO_SAP'),
        'CDO_CSAP_OPOR_ID': operacion.ONJ_CBASE_ENTRY or detalle_valores.get('CDO_CSAP_OPOR_ID'),
        'CDO_CDOCENTRY': operacion.ONJ_CBASE_ENTRY or detalle_valores.get('CDO_CDOCENTRY'),
        'CDO_CESTANQUE_DESTINO': operacion.ONJ_CTK_DESTINO or detalle_valores.get('CDO_CESTANQUE_DESTINO'),
    })
    CITACION_DETALLE_OPERACIONAL.objects.create(
        CI_NID=p2, EP_NID=p2.EP_NID, US_NID=usuario, **detalle_valores,
    )
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.create(
        ONJ_NID=operacion, CI_NID=p2, EP_NID=p2.EP_NID, US_NID=usuario,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
        ONJP_CESTADO=OPERACION_NEW_JERSEY_PROCESO.Estado.PENDIENTE,
    )
    snapshot = _snapshot_p1(citacion_p1, operacion, guia, contenedor)
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID_id=EMPRESA_NJ, CA_CCODIGO=CAMPO_SNAPSHOT_P2,
        defaults={
            'US_NID': usuario, 'CA_CTIPO': 'TEXTO',
            'CA_CETIQUETA': 'Snapshot New Jersey P2 desde P1',
            'CA_BHABILITADO': True,
        },
    )
    DATO_OPERACION.objects.create(
        US_NID=usuario, EP_NID=p2.EP_NID, SC_NID=secuencia,
        ET_NID=etapas['Pendiente Proceso 2'], CAMP_NID=campo, CI_NID=p2,
        DO_FFECHAREGISTRO=timezone.now(),
        DO_CVALOR=json.dumps(snapshot, ensure_ascii=False),
    )
    relacion_p1.ONJP_CESTADO = relacion_p1.Estado.COMPLETADO
    relacion_p1.save(update_fields=['ONJP_CESTADO'])
    operacion.ONJ_CESTADO = operacion.Estado.PENDIENTE_PROCESO_2
    operacion.save(update_fields=['ONJ_CESTADO'])
    return proceso, True


def obtener_proceso_p2(citacion):
    if (
        citacion.EP_NID_id != EMPRESA_NJ
        or citacion.CI_CTIPO != 'RECEPCION'
        or citacion.SC_NID.SE_CCODIGO != SECUENCIA_P2
    ):
        raise ValueError('La citación no corresponde a New Jersey Proceso 2.')
    return OPERACION_NEW_JERSEY_PROCESO.objects.select_related('ONJ_NID').get(
        CI_NID=citacion, EP_NID_id=EMPRESA_NJ,
        ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2,
    )


def estanques_validos_p2():
    """Reuse the existing SBH catalogue, restricted to physical TK tanks."""
    from .views import obtener_estanques_por_almacen
    return tuple(tk for tk in obtener_estanques_por_almacen('SBH') if tk.startswith('TK'))


def destino_vigente_p2(citacion):
    """P2 owns its current destination; P1 retains the original."""
    detalle = CITACION_DETALLE_OPERACIONAL.objects.filter(CI_NID=citacion).first()
    return str(detalle.CDO_CESTANQUE_DESTINO or '').strip() if detalle else ''


@transaction.atomic
def guardar_destino_p2(citacion_id, usuario, tk_destino):
    from .sap_solicitud_new_jersey_p2 import estado_solicitud_traslado_new_jersey_p2

    citacion = CITACION.objects.select_for_update().select_related('SC_NID').get(
        pk=citacion_id, EP_NID_id=EMPRESA_NJ, CI_BHABILITADO=True,
    )
    proceso = obtener_proceso_p2(citacion)
    if proceso.ONJP_CESTADO != proceso.Estado.EN_PROCESO or paso_actual_p2(citacion) != PASO_DESCARGA:
        raise ValueError('Ciclo Descarga P2 no es el paso activo.')
    if estado_solicitud_traslado_new_jersey_p2(citacion)['blocked']:
        raise ValueError('El estanque destino no puede cambiarse después de iniciar la solicitud SAP.')
    tk_destino = str(tk_destino or '').strip()
    if tk_destino not in estanques_validos_p2():
        raise ValueError(MENSAJE_TK_INVALIDO_P2)
    detalle = CITACION_DETALLE_OPERACIONAL.objects.select_for_update().get(
        CI_NID=citacion, EP_NID_id=EMPRESA_NJ,
    )
    anterior = str(detalle.CDO_CESTANQUE_DESTINO or '').strip()
    if anterior != tk_destino:
        detalle.CDO_CESTANQUE_DESTINO = tk_destino
        detalle.save(update_fields=['CDO_CESTANQUE_DESTINO'])
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=usuario, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO=LOG_CAMBIO_TK_P2,
            OPL_CPERFIL_RESPONSABLE=RESPONSABLE_P2,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_COBSERVACION=json.dumps({
                'tk_heredado_p1': proceso.ONJ_NID.ONJ_CTK_DESTINO or '',
                'tk_anterior_p2': anterior, 'tk_seleccionado_p2': tk_destino,
                'usuario': usuario.username, 'fecha': timezone.now().isoformat(),
            }, ensure_ascii=False),
        )
    return {
        'tk_destino': tk_destino,
        'tk_heredado_p1': proceso.ONJ_NID.ONJ_CTK_DESTINO or '',
        'changed': anterior != tk_destino,
    }


def paso_actual_p2(citacion):
    completados = set(OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion, OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).values_list('OPL_CPASO', flat=True))
    if 'Descarga' in completados:
        completados.add(PASO_DESCARGA)
    # Calidad tiene estado propio y no condiciona el avance operacional.
    return next((paso for paso in (PASO_TOMA, PASO_DESCARGA) if paso not in completados), None)


def _registrar_log(citacion, usuario, paso, observacion=''):
    return OPERACION_PLANTA_LOG.objects.create(
        US_NID=usuario, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
        CI_NID=citacion, OPL_CPASO=paso,
        OPL_CPERFIL_RESPONSABLE=RESPONSABLE_P2,
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        OPL_COBSERVACION=observacion,
    )

@transaction.atomic
def activar_p2(proceso_id, usuario):
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.select_for_update().select_related(
        'CI_NID__SC_NID', 'ONJ_NID'
    ).get(pk=proceso_id, EP_NID_id=EMPRESA_NJ,
          ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2)
    p2 = CITACION.objects.select_for_update().get(pk=proceso.CI_NID_id)
    p1 = CITACION.objects.get(pk=p2.CI_NID_REF, EP_NID_id=EMPRESA_NJ)
    if p1.CI_CESTADO != 'TERMINADO' or not OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=p1, OPL_CPASO='Confirmar Salida',
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).exists():
        raise ValueError('P1 debe estar terminado antes de activar P2.')
    if (
        proceso.ONJP_CESTADO != proceso.Estado.PENDIENTE
        or proceso.ONJ_NID.ONJ_CESTADO != proceso.ONJ_NID.Estado.PENDIENTE_PROCESO_2
        or p2.CI_CESTADO != ESTADO_CITACION_PENDIENTE
    ):
        raise ValueError('P2 ya fue activado o completado.')
    asegurar_secuencia_p2(usuario)
    proceso.ONJP_CESTADO = proceso.Estado.EN_PROCESO
    proceso.save(update_fields=['ONJP_CESTADO'])
    p2.CI_CESTADO = 'EN PROCESO'
    p2.CI_FFECHAINICIO = timezone.now()
    p2.save(update_fields=['CI_CESTADO', 'CI_FFECHAINICIO'])
    _registrar_log(p2, usuario, 'Activar Proceso 2',
                   f'Planificador activó Proceso 2 desde P1 #{p1.id}.')
    return proceso


@transaction.atomic
def registrar_accion_p2(citacion_id, usuario, paso, accion, observacion=''):
    citacion = CITACION.objects.select_for_update().select_related('SC_NID').get(
        pk=citacion_id, EP_NID_id=EMPRESA_NJ, CI_BHABILITADO=True,
    )
    proceso = OPERACION_NEW_JERSEY_PROCESO.objects.select_for_update().select_related(
        'ONJ_NID'
    ).get(CI_NID=citacion, ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2)
    if proceso.ONJP_CESTADO != proceso.Estado.EN_PROCESO or citacion.CI_CESTADO != 'EN PROCESO':
        raise ValueError('P2 no está activo.')
    if paso not in (PASO_TOMA, PASO_DESCARGA) or paso_actual_p2(citacion) != paso:
        raise ValueError('El paso P2 indicado no es el activo.')
    if paso == PASO_DESCARGA and accion == 'iniciar':
        from .sap_solicitud_new_jersey_p2 import (
            MENSAJE_SOLICITUD_REQUERIDA,
            estado_solicitud_traslado_new_jersey_p2,
        )
        if not estado_solicitud_traslado_new_jersey_p2(citacion)['created']:
            raise ValueError(MENSAJE_SOLICITUD_REQUERIDA)
    _, etapas = asegurar_secuencia_p2(usuario)
    ahora = timezone.now()
    etapa = etapas[paso]
    abierto = ETAPA_LOG.objects.select_for_update().filter(
        CI_NID=citacion, SC_NID=citacion.SC_NID, ET_NID=etapa,
        EL_FFECHAFIN__isnull=True,
    ).order_by('-id').first()
    if paso in {PASO_TOMA, PASO_DESCARGA} and accion == 'iniciar':
        if abierto:
            raise ValueError(f'{paso} ya fue iniciado.')
        ETAPA_LOG.objects.create(
            CI_NID=citacion, EP_NID=citacion.EP_NID, SC_NID=citacion.SC_NID,
            ET_NID=etapa, US_INICIO_ID=usuario, EL_FFECHAINICIO=ahora,
            EL_CACCION='INICIAR',
        )
        return {'paso': paso, 'accion': accion, 'siguiente': paso}
    if accion != 'completar':
        raise ValueError('Acción P2 no válida.')
    if not abierto:
        raise ValueError(f'Debe iniciar {paso} antes de completarlo.')
    abierto.EL_FFECHAFIN = ahora
    abierto.US_FIN_ID = usuario
    abierto.EL_CACCION = 'COMPLETAR'
    abierto.EL_COBSERVACION = observacion
    abierto.save(update_fields=['EL_FFECHAFIN', 'US_FIN_ID', 'EL_CACCION', 'EL_COBSERVACION'])
    _registrar_log(citacion, usuario, paso, observacion)
    if paso == PASO_TOMA:
        ETAPA_LOG.objects.create(
            CI_NID=citacion, EP_NID=citacion.EP_NID, SC_NID=citacion.SC_NID,
            ET_NID=etapas[PASO_CALIDAD], US_INICIO_ID=usuario,
            EL_FFECHAINICIO=ahora, EL_CACCION='INICIAR',
        )
    elif paso == PASO_DESCARGA:
        citacion.CI_CESTADO = 'TERMINADO'
        citacion.CI_FFECHATERMINO = ahora
        citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHATERMINO'])
        proceso.ONJP_CESTADO = proceso.Estado.COMPLETADO
        proceso.save(update_fields=['ONJP_CESTADO'])
        operacion = OPERACION_NEW_JERSEY.objects.select_for_update().get(pk=proceso.ONJ_NID_id)
        operacion.ONJ_CESTADO = operacion.Estado.PENDIENTE_PROCESO_3
        operacion.save(update_fields=['ONJ_CESTADO'])
    return {'paso': paso, 'accion': accion, 'siguiente': paso_actual_p2(citacion)}
