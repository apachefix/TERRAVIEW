import json
import logging
from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.home.sap_recepcion import get_goods_receipt_draft_guide_status
from apps.home.models import (
    CAMPO,
    CITACION,
    DATO_OPERACION,
    EVENTO_INTEGRACION_CALIDAD,
    OPERACION_PLANTA_LOG,
    RESULTADO_CALIDAD_HISTORIAL,
    RESULTADO_CALIDAD_OPERACION,
)

logger = logging.getLogger(__name__)

SECUENCIA_NEW_JERSEY_P2 = 'RECEPCION_NEW_JERSEY_P2_OPERACION_INTERNA'


def es_new_jersey_p2_calidad(citacion):
    return bool(
        citacion.EP_NID_id == 2
        and citacion.CI_CTIPO == 'RECEPCION'
        and citacion.SC_NID
        and citacion.SC_NID.SE_CCODIGO == SECUENCIA_NEW_JERSEY_P2
    )


PASO_ANALISIS_CALIDAD = 'Analisis y calidad'
PASO_RESULTADO_CALIDAD = 'Resultado Calidad'
CAMPO_RESULTADO_CALIDAD = 'OP_RESULTADO_CALIDAD'
PERFIL_CALIDAD = 'CALIDAD'
MENSAJE_RECHAZO_PENDIENTE_REVISION = (
    'Resultado rechazado por analisis automatico. '
    'Pendiente de revision manual de Calidad.'
)
MENSAJE_SALIDA_RECHAZO = 'Camión autorizado para salir de planta por rechazo de calidad'

TRANSICIONES_PERMITIDAS = {
    RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE: {
        RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
        RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
        RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION,
        RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE,
    },
    RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE: {
        RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
        RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
    },
    RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION: {
        RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
        RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
    },
}


class ProcesoCalidadNoEncontrado(ValueError):
    pass


class ProcesoCalidadAmbiguo(ValueError):
    pass


class ProcesoCalidadNoPreparado(ValueError):
    pass


def normalizar_numero_guia(numero_guia):
    return str(numero_guia or '').strip()


def buscar_resultado_calidad_por_guia(empresa_id, numero_guia):
    guia = normalizar_numero_guia(numero_guia)
    if not guia:
        raise ProcesoCalidadNoEncontrado('Numero de guia vacio.')
    coincidencias = list(
        RESULTADO_CALIDAD_OPERACION.objects.select_related(
            'EP_NID', 'CI_NID', 'CI_NID__SC_NID', 'CI_NID__PL_NID',
            'PL_NID', 'ET_NID', 'CA_NID', 'US_NID',
        ).filter(
            EP_NID_id=empresa_id,
            CI_NID__CI_BHABILITADO=True,
        ).filter(
            Q(RCO_CNUMERO_GUIA__iexact=guia)
            | Q(
                CI_NID__EP_NID_id=2,
                CI_NID__CI_CTIPO='RECEPCION',
                CI_NID__SC_NID__SE_CCODIGO=SECUENCIA_NEW_JERSEY_P2,
                CI_NID__CI_CNUMERODOCUMENTO__iexact=guia,
            ) & (Q(RCO_CNUMERO_GUIA='') | Q(RCO_CNUMERO_GUIA__isnull=True))
        ).order_by('-RCO_FINICIO', '-id')
    )
    if not coincidencias:
        citaciones = list(
            CITACION.objects.filter(
                EP_NID_id=empresa_id,
                CI_CNUMERODOCUMENTO__iexact=guia,
                CI_BHABILITADO=True,
            ).values_list('id', flat=True)[:2]
        )
        if len(citaciones) > 1:
            raise ProcesoCalidadAmbiguo(
                'Existe mas de una citacion para la empresa y guia informadas.'
            )
        if citaciones:
            raise ProcesoCalidadNoPreparado(
                'La guia existe, pero el proceso ANALISIS_Y_CALIDAD aun no esta preparado.'
            )
        raise ProcesoCalidadNoEncontrado(
            'No existe un proceso de Calidad asociado a la empresa y guia informadas.'
        )
    if len(coincidencias) > 1:
        # P1 y P2 comparten guia. Un P1 ya resuelto no debe impedir
        # entregar al Bot el unico proceso P2 que sigue esperando resultado.
        pendientes_p2 = [
            registro for registro in coincidencias
            if es_new_jersey_p2_calidad(registro.CI_NID)
            and registro.RCO_CESTADO == RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE
        ]
        cerrados = {
            RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
            RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
        }
        if len(pendientes_p2) == 1 and all(
            registro == pendientes_p2[0] or registro.RCO_CESTADO in cerrados
            for registro in coincidencias
        ):
            resultado = pendientes_p2[0]
        else:
            raise ProcesoCalidadAmbiguo(
                'Existe mas de un proceso de Calidad para la empresa y guia informadas.'
            )
    else:
        resultado = coincidencias[0]
    if resultado.CI_NID.EP_NID_id != int(empresa_id):
        raise ProcesoCalidadNoEncontrado(
            'El proceso de Calidad no pertenece a la empresa informada.'
        )
    return resultado


def _numero_guia(citacion):
    return str(citacion.CI_CNUMERODOCUMENTO or '').strip()


def es_recepcion_bodega_externa_calidad(citacion):
    tipo = str(
        citacion.CI_CTIPO
        or (citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID else '')
        or ''
    ).strip().upper()
    codigo = str(citacion.SC_NID.SE_CCODIGO if citacion.SC_NID else '').strip().upper()
    return tipo == 'RECEPCION' and codigo == 'RECEPCION_BODEGA_EXTERNA'


def _usuario_responsable(citacion, usuario):
    if usuario is not None and getattr(usuario, 'pk', None):
        return usuario
    if citacion.US_NID_id:
        return citacion.US_NID
    if citacion.PL_NID and citacion.PL_NID.US_NID_id:
        return citacion.PL_NID.US_NID
    raise ValueError('Se requiere un usuario responsable para registrar calidad.')


def es_flujo_recepcion_estanque_sbh_calidad(citacion):
    tipo = str(
        citacion.CI_CTIPO
        or (citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID else '')
        or ''
    ).strip().upper()
    secuencia = str(
        citacion.SC_NID.SE_CCODIGO if citacion.SC_NID else ''
    ).strip().upper()
    return bool(
        citacion.EP_NID_id == 2
        and tipo == 'RECEPCION'
        and secuencia == 'RECEPCION_ESTANQUE_SBH'
    )


def es_rechazo_bot_revisable(citacion, evento_integracion):
    # Solo un evento externo persistido habilita el estado intermedio.
    if not (es_flujo_recepcion_estanque_sbh_calidad(citacion) or es_new_jersey_p2_calidad(citacion)):
        return False
    if not evento_integracion or not getattr(evento_integracion, 'pk', None):
        return False
    return bool(
        evento_integracion.EP_NID_id == citacion.EP_NID_id
        and evento_integracion.CI_NID_id == citacion.pk
        and evento_integracion.RCO_NID_id
        and evento_integracion.RCO_NID.CI_NID_id == citacion.pk
        and evento_integracion.EIC_CESTADO_SOLICITADO
        == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO
        and evento_integracion.EIC_CORIGEN
        == RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD
        and not evento_integracion.EIC_BDUPLICADO
    )


def _crear_borrador_sap_recepcion_interno_post_commit(citacion, usuario):
    # Import diferido para reutilizar el orquestador actual sin crear un ciclo
    # de imports entre views.py y el servicio canónico de Calidad.
    from apps.home.views import crear_borrador_sap_recepcion_interno
    return crear_borrador_sap_recepcion_interno(citacion, usuario)


def crear_borrador_sap_recepcion_por_calidad_aprobada(citacion_id, usuario_id):
    """Revalida y serializa el envío SAP después del commit de Calidad."""
    try:
        with transaction.atomic():
            citacion = CITACION.objects.select_for_update().get(pk=citacion_id)
            if not es_flujo_recepcion_estanque_sbh_calidad(citacion):
                return {'success': True, 'skipped': True, 'reason': 'flujo_no_aplicable'}

            resultado_calidad = RESULTADO_CALIDAD_OPERACION.objects.select_for_update().filter(
                CI_NID=citacion,
            ).first()
            if (
                not resultado_calidad
                or resultado_calidad.RCO_CESTADO != RESULTADO_CALIDAD_OPERACION.Estado.APROBADO
            ):
                return {'success': True, 'skipped': True, 'reason': 'calidad_no_aprobada'}

            estado_draft = get_goods_receipt_draft_guide_status(citacion)
            if estado_draft.get('sent') and estado_draft.get('docentry'):
                return {
                    'success': True,
                    'reused': True,
                    'status': estado_draft,
                }

            usuario = get_user_model().objects.filter(pk=usuario_id).first()
            usuario = usuario or _usuario_responsable(citacion, None)
            return _crear_borrador_sap_recepcion_interno_post_commit(citacion, usuario)
    except CITACION.DoesNotExist:
        logger.warning(
            'No se creó borrador SAP post-calidad: citación %s inexistente.',
            citacion_id,
        )
        return {'success': False, 'message': 'Citación no encontrada.'}
    except Exception:
        # Calidad ya fue confirmada; un error externo nunca debe revertirla.
        logger.exception(
            'Error al crear borrador SAP post-calidad para citación %s.',
            citacion_id,
        )
        return {'success': False, 'message': 'No fue posible crear el borrador SAP post-calidad.'}


def _agendar_borrador_sap_recepcion_aprobada(citacion, usuario):
    if es_new_jersey_p2_calidad(citacion):
        return
    if not es_flujo_recepcion_estanque_sbh_calidad(citacion):
        return False
    transaction.on_commit(partial(
        crear_borrador_sap_recepcion_por_calidad_aprobada,
        citacion.pk,
        usuario.pk,
    ))
    return True


def _responsable_texto(usuario, responsable_sistema):
    if responsable_sistema:
        return str(responsable_sistema).strip()[:128]
    if usuario:
        return usuario.get_full_name().strip() or usuario.username
    return ''


def _detalle_evento(registro, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema):
    return {
        'proceso_id': registro.PL_NID_id,
        'empresa_id': registro.EP_NID_id,
        'citacion_id': registro.CI_NID_id,
        'guia': registro.RCO_CNUMERO_GUIA or '',
        'estado_anterior': estado_anterior or '',
        'estado_nuevo': estado_nuevo,
        'origen': origen,
        'resultado': estado_nuevo,
        'observacion': observacion or '',
        'responsable': _responsable_texto(usuario, responsable_sistema),
    }


def _crear_log(registro, usuario, codigo, detalle, estado=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO):
    log, _ = OPERACION_PLANTA_LOG.objects.get_or_create(
        CI_NID=registro.CI_NID,
        OPL_CPASO=codigo,
        defaults={
            'US_NID': usuario,
            'EP_NID': registro.EP_NID,
            'PL_NID': registro.PL_NID,
            'OPL_CPERFIL_RESPONSABLE': PERFIL_CALIDAD,
            'OPL_CESTADO': estado,
            'OPL_COBSERVACION': json.dumps(detalle, ensure_ascii=False),
        },
    )
    return log


def _crear_historial(registro, evento, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema, fecha):
    return RESULTADO_CALIDAD_HISTORIAL.objects.create(
        RCO_NID=registro,
        EP_NID=registro.EP_NID,
        CI_NID=registro.CI_NID,
        RCH_CEVENTO=evento,
        RCH_CESTADO_ANTERIOR=estado_anterior or '',
        RCH_CESTADO_NUEVO=estado_nuevo,
        RCH_CORIGEN=origen,
        RCH_CRESULTADO=estado_nuevo,
        RCH_COBSERVACION=observacion or '',
        US_NID=usuario,
        RCH_CRESPONSABLE_SISTEMA=responsable_sistema or '',
        RCH_FFECHAREGISTRO=fecha,
    )


def _sincronizar_metadata_legacy(registro, usuario, fecha):
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID=registro.EP_NID,
        CA_CCODIGO=CAMPO_RESULTADO_CALIDAD,
        defaults={
            'US_NID': usuario,
            'CA_CTIPO': 'TEXTO',
            'CA_CETIQUETA': 'Resultado analisis y calidad',
            'CA_CPLACEMARK': 'Metadata operacional de calidad',
            'CA_BOBLIGATORIO': True,
            'CA_BHABILITADO': True,
            'CA_BASIGNARVALOR': False,
        },
    )
    metadata = {
        'resultado_calidad': registro.RCO_CESTADO,
        'comentario': registro.RCO_COBSERVACION or '',
        'usuario_id': usuario.id if usuario else None,
        'usuario': _responsable_texto(usuario, registro.RCO_CRESPONSABLE_SISTEMA),
        'fecha_hora': timezone.localtime(fecha).strftime('%d/%m/%Y %H:%M'),
        'fecha_iso': fecha.isoformat(),
        'citacion_id': registro.CI_NID_id,
        'paso_operacion': PASO_ANALISIS_CALIDAD,
        'origen': registro.RCO_CORIGEN,
        'cierre_automatico': registro.RCO_BCIERRE_AUTOMATICO,
        'autoriza_salida': registro.RCO_BAUTORIZA_SALIDA,
    }
    DATO_OPERACION.objects.update_or_create(
        CI_NID=registro.CI_NID,
        CAMP_NID=campo,
        defaults={
            'EP_NID': registro.EP_NID,
            'US_NID': usuario,
            'SC_NID': registro.CI_NID.SC_NID,
            'ET_NID': registro.ET_NID or registro.CI_NID.ETAPA_ACTUAL,
            'DO_CVALOR': json.dumps(metadata, ensure_ascii=False),
            'DO_NPESO': None,
            'DO_FFECHAREGISTRO': fecha,
        },
    )


@transaction.atomic
def asegurar_calidad_iniciada(proceso_operacion, usuario=None, origen=RESULTADO_CALIDAD_OPERACION.Origen.OPERACION_PLANTA, responsable_sistema='', fecha_inicio=None):
    citacion_id = proceso_operacion.pk if isinstance(proceso_operacion, CITACION) else proceso_operacion
    citacion = CITACION.objects.select_for_update().get(pk=citacion_id)
    usuario = _usuario_responsable(citacion, usuario)
    fecha = fecha_inicio or timezone.now()
    registro, creado = RESULTADO_CALIDAD_OPERACION.objects.select_for_update().get_or_create(
        CI_NID=citacion,
        defaults={
            'EP_NID': citacion.EP_NID,
            'PL_NID': citacion.PL_NID,
            'ET_NID': citacion.ETAPA_ACTUAL,
            'CA_NID': citacion.CA_NID,
            'RCO_CNUMERO_GUIA': _numero_guia(citacion),
            'RCO_CESTADO': RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE,
            'RCO_CORIGEN': origen,
            'RCO_FINICIO': fecha,
            'RCO_COBSERVACION': 'En espera de resultados de análisis',
            'US_NID': usuario,
            'RCO_CRESPONSABLE_SISTEMA': responsable_sistema or '',
        },
    )
    if not creado:
        if es_new_jersey_p2_calidad(citacion) and not registro.RCO_CNUMERO_GUIA:
            guia = _numero_guia(citacion)
            if guia:
                registro.RCO_CNUMERO_GUIA = guia
                registro.save(update_fields=['RCO_CNUMERO_GUIA'])
        return registro, False

    detalle = _detalle_evento(
        registro, '', registro.RCO_CESTADO, origen,
        'En espera de resultados de análisis', usuario, responsable_sistema,
    )
    _crear_historial(
        registro, 'CALIDAD_INICIO', '', registro.RCO_CESTADO, origen,
        'En espera de resultados de análisis', usuario, responsable_sistema, fecha,
    )
    _crear_log(registro, usuario, 'CALIDAD_INICIO', detalle)
    _crear_log(registro, usuario, 'CALIDAD_ESPERANDO_RESULTADO', detalle)
    _sincronizar_metadata_legacy(registro, usuario, fecha)
    return registro, True


@transaction.atomic
def procesar_resultado_calidad(
    proceso_operacion,
    estado_solicitado,
    origen,
    observacion='',
    usuario=None,
    responsable_sistema='',
    fecha_resultado=None,
    evento_integracion=None,
):
    citacion_id = proceso_operacion.pk if isinstance(proceso_operacion, CITACION) else proceso_operacion
    citacion = CITACION.objects.select_for_update().get(pk=citacion_id)
    usuario = _usuario_responsable(citacion, usuario)
    if origen not in RESULTADO_CALIDAD_OPERACION.Origen.values:
        raise ValueError('Origen de calidad no valido.')
    estado_solicitado_normalizado = str(estado_solicitado or '').strip().upper()
    if estado_solicitado_normalizado not in RESULTADO_CALIDAD_OPERACION.Estado.values:
        raise ValueError('Estado de calidad no valido.')
    if (
        estado_solicitado_normalizado
        == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION
    ):
        raise ValueError(
            'El estado pendiente de revision solo puede originarse desde un rechazo BOT validado.'
        )

    es_p2 = es_new_jersey_p2_calidad(citacion)
    registro, _ = asegurar_calidad_iniciada(citacion, usuario, origen, responsable_sistema)
    registro = RESULTADO_CALIDAD_OPERACION.objects.select_for_update().get(pk=registro.pk)
    estado_nuevo = estado_solicitado_normalizado
    if (
        estado_solicitado_normalizado == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO
        and es_rechazo_bot_revisable(citacion, evento_integracion)
    ):
        estado_nuevo = RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION
    estado_anterior = registro.RCO_CESTADO
    if estado_nuevo == estado_anterior:
        if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO:
            _agendar_borrador_sap_recepcion_aprobada(citacion, usuario)
        return registro, False
    correccion_p2 = (
        es_p2 and estado_anterior == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO
        and estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO
    )
    if not correccion_p2 and estado_nuevo not in TRANSICIONES_PERMITIDAS.get(estado_anterior, set()):
        raise ValueError(f'Transicion de calidad no permitida: {estado_anterior} -> {estado_nuevo}.')

    fecha = fecha_resultado or timezone.now()
    duracion = max(int((fecha - registro.RCO_FINICIO).total_seconds()), 0)
    registro.RCO_CESTADO = estado_nuevo
    registro.RCO_CORIGEN = origen
    registro.RCO_COBSERVACION = str(observacion or '').strip()
    registro.RCO_FACTUALIZACION = fecha
    registro.US_NID = usuario
    registro.RCO_CRESPONSABLE_SISTEMA = responsable_sistema or ''
    registro.RCO_FDETENCION_TEMPORIZADOR = (None if correccion_p2 else registro.RCO_FDETENCION_TEMPORIZADOR) or fecha
    registro.RCO_NDURACION_SEGUNDOS = max(registro.RCO_NDURACION_SEGUNDOS, duracion)

    if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
        registro.RCO_FSOLICITUD_CLIENTE = fecha
        evento = 'CALIDAD_APRUEBA_CLIENTE'
    elif estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION:
        registro.RCO_FRESOLUCION_FINAL = None
        registro.RCO_FCIERRE = None
        registro.RCO_BCIERRE_AUTOMATICO = False
        registro.RCO_BAUTORIZA_SALIDA = False
        evento = 'CALIDAD_RECHAZADA_PENDIENTE_REVISION'
    else:
        registro.RCO_FRESOLUCION_FINAL = fecha
        registro.RCO_FCIERRE = fecha
        registro.RCO_BCIERRE_AUTOMATICO = True
        registro.RCO_BAUTORIZA_SALIDA = estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO and not es_p2
        if es_p2 and estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO:
            registro.RCO_FCIERRE = None
            registro.RCO_BCIERRE_AUTOMATICO = False
            registro.RCO_FDETENCION_TEMPORIZADOR = None
        if estado_anterior == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
            evento = f'CALIDAD_RESPUESTA_CLIENTE_{"APROBADA" if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO else "RECHAZADA"}'
        elif estado_anterior == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION:
            evento = (
                'CALIDAD_REVISION_MANUAL_APROBADA'
                if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO
                else 'CALIDAD_REVISION_MANUAL_RECHAZADA'
            )
        else:
            evento = 'CALIDAD_APROBADA' if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO else 'CALIDAD_RECHAZADA'

    registro.save()
    detalle = _detalle_evento(registro, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema)
    _crear_historial(registro, evento, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema, fecha)
    _crear_log(registro, usuario, evento, detalle)

    if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
        _crear_log(registro, usuario, 'CALIDAD_ESPERANDO_CLIENTE', detalle)
    elif estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO_PENDIENTE_REVISION:
        _crear_log(registro, usuario, 'CALIDAD_PENDIENTE_REVISION_MANUAL', detalle)
    elif not es_p2:
        OPERACION_PLANTA_LOG.objects.get_or_create(
            CI_NID=citacion,
            OPL_CPASO=PASO_ANALISIS_CALIDAD,
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            defaults={
                'US_NID': usuario,
                'EP_NID': citacion.EP_NID,
                'PL_NID': citacion.PL_NID,
                'OPL_CPERFIL_RESPONSABLE': PERFIL_CALIDAD,
                'OPL_COBSERVACION': json.dumps(detalle, ensure_ascii=False),
                'OPL_FFECHAREGISTRO': fecha,
            },
        )
        _crear_log(registro, usuario, 'CALIDAD_CIERRE_AUTOMATICO', detalle)
        if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO:
            _crear_log(registro, usuario, 'CALIDAD_AVANCE_AUTOMATICO', detalle)
        else:
            salida_detalle = dict(detalle, observacion=MENSAJE_SALIDA_RECHAZO)
            _crear_log(registro, usuario, 'CALIDAD_SALIDA_AUTORIZADA', salida_detalle)
            if not es_recepcion_bodega_externa_calidad(citacion):
                citacion.CI_CESTADO = 'RECHAZADO'
                citacion.CI_FFECHATERMINO = fecha
                citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHATERMINO'])

    _sincronizar_metadata_legacy(registro, usuario, fecha)
    if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO:
        _agendar_borrador_sap_recepcion_aprobada(citacion, usuario)
    return registro, True


def serializar_resultado_calidad(registro, ahora=None):
    ahora = ahora or timezone.now()
    fin = registro.RCO_FDETENCION_TEMPORIZADOR or ahora
    duracion = registro.RCO_NDURACION_SEGUNDOS
    if registro.temporizador_activo:
        duracion = max(int((fin - registro.RCO_FINICIO).total_seconds()), 0)
    horas, resto = divmod(duracion, 3600)
    minutos, segundos = divmod(resto, 60)
    mensajes = {
        registro.Estado.PENDIENTE: 'En espera de resultados de análisis',
        registro.Estado.APROBADO: 'Resultado de calidad: APROBADO',
        registro.Estado.RECHAZADO: (
            'Resultado de calidad: RECHAZADO'
            if es_new_jersey_p2_calidad(registro.CI_NID) else MENSAJE_SALIDA_RECHAZO
        ),
        registro.Estado.RECHAZADO_PENDIENTE_REVISION: MENSAJE_RECHAZO_PENDIENTE_REVISION,
        registro.Estado.APRUEBA_CLIENTE: 'Análisis interno finalizado. En espera de aprobación del cliente.',
    }
    return {
        'id': registro.id,
        'estado': registro.RCO_CESTADO,
        'resultado_calidad': registro.RCO_CESTADO,
        'origen': registro.RCO_CORIGEN,
        'observacion': registro.RCO_COBSERVACION or '',
        'comentario': registro.RCO_COBSERVACION or '',
        'usuario': _responsable_texto(registro.US_NID, registro.RCO_CRESPONSABLE_SISTEMA),
        'inicio_iso': registro.RCO_FINICIO.isoformat(),
        'inicio': timezone.localtime(registro.RCO_FINICIO).strftime('%d/%m/%Y %H:%M'),
        'ultimo_cambio': timezone.localtime(registro.RCO_FACTUALIZACION).strftime('%d/%m/%Y %H:%M'),
        'cierre': timezone.localtime(registro.RCO_FCIERRE).strftime('%d/%m/%Y %H:%M') if registro.RCO_FCIERRE else '',
        'solicitud_cliente': timezone.localtime(registro.RCO_FSOLICITUD_CLIENTE).strftime('%d/%m/%Y %H:%M') if registro.RCO_FSOLICITUD_CLIENTE else '',
        'resolucion_final': timezone.localtime(registro.RCO_FRESOLUCION_FINAL).strftime('%d/%m/%Y %H:%M') if registro.RCO_FRESOLUCION_FINAL else '',
        'temporizador_activo': registro.temporizador_activo,
        'duracion_segundos': duracion,
        'duracion_legible': f'{horas:02d}:{minutos:02d}:{segundos:02d}',
        'cierre_automatico': registro.RCO_BCIERRE_AUTOMATICO,
        'autoriza_salida': registro.RCO_BAUTORIZA_SALIDA,
        'mensaje': mensajes[registro.RCO_CESTADO],
        'historial': [
            {
                'evento': item.RCH_CEVENTO,
                'estado_anterior': item.RCH_CESTADO_ANTERIOR or '',
                'estado_nuevo': item.RCH_CESTADO_NUEVO,
                'origen': item.RCH_CORIGEN,
                'observacion': item.RCH_COBSERVACION or '',
                'responsable': _responsable_texto(item.US_NID, item.RCH_CRESPONSABLE_SISTEMA),
                'fecha': timezone.localtime(item.RCH_FFECHAREGISTRO).strftime('%d/%m/%Y %H:%M'),
            }
            for item in registro.historial.select_related('US_NID').order_by('RCH_FFECHAREGISTRO', 'id')
        ],
    }
