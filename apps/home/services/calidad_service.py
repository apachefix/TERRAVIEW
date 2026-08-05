import json

from django.db import transaction
from django.utils import timezone

from apps.home.models import (
    CAMPO,
    CITACION,
    DATO_OPERACION,
    OPERACION_PLANTA_LOG,
    RESULTADO_CALIDAD_HISTORIAL,
    RESULTADO_CALIDAD_OPERACION,
)


PASO_ANALISIS_CALIDAD = 'Analisis y calidad'
PASO_RESULTADO_CALIDAD = 'Resultado Calidad'
CAMPO_RESULTADO_CALIDAD = 'OP_RESULTADO_CALIDAD'
PERFIL_CALIDAD = 'CALIDAD'
MENSAJE_SALIDA_RECHAZO = 'Camión autorizado para salir de planta por rechazo de calidad'

TRANSICIONES_PERMITIDAS = {
    RESULTADO_CALIDAD_OPERACION.Estado.PENDIENTE: {
        RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
        RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
        RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE,
    },
    RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE: {
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
            RCO_CNUMERO_GUIA__iexact=guia,
            CI_NID__CI_BHABILITADO=True,
        ).order_by('-RCO_FINICIO', '-id')[:2]
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
        raise ProcesoCalidadAmbiguo(
            'Existe mas de un proceso de Calidad para la empresa y guia informadas.'
        )
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
def procesar_resultado_calidad(proceso_operacion, estado_solicitado, origen, observacion='', usuario=None, responsable_sistema='', fecha_resultado=None):
    citacion_id = proceso_operacion.pk if isinstance(proceso_operacion, CITACION) else proceso_operacion
    citacion = CITACION.objects.select_for_update().get(pk=citacion_id)
    usuario = _usuario_responsable(citacion, usuario)
    if origen not in RESULTADO_CALIDAD_OPERACION.Origen.values:
        raise ValueError('Origen de calidad no valido.')
    estado_nuevo = str(estado_solicitado or '').strip().upper()
    if estado_nuevo not in RESULTADO_CALIDAD_OPERACION.Estado.values:
        raise ValueError('Estado de calidad no valido.')

    registro, _ = asegurar_calidad_iniciada(citacion, usuario, origen, responsable_sistema)
    registro = RESULTADO_CALIDAD_OPERACION.objects.select_for_update().get(pk=registro.pk)
    estado_anterior = registro.RCO_CESTADO
    if estado_nuevo == estado_anterior:
        return registro, False
    if estado_nuevo not in TRANSICIONES_PERMITIDAS.get(estado_anterior, set()):
        raise ValueError(f'Transicion de calidad no permitida: {estado_anterior} -> {estado_nuevo}.')

    fecha = fecha_resultado or timezone.now()
    duracion = max(int((fecha - registro.RCO_FINICIO).total_seconds()), 0)
    registro.RCO_CESTADO = estado_nuevo
    registro.RCO_CORIGEN = origen
    registro.RCO_COBSERVACION = str(observacion or '').strip()
    registro.RCO_FACTUALIZACION = fecha
    registro.US_NID = usuario
    registro.RCO_CRESPONSABLE_SISTEMA = responsable_sistema or ''
    registro.RCO_FDETENCION_TEMPORIZADOR = registro.RCO_FDETENCION_TEMPORIZADOR or fecha
    registro.RCO_NDURACION_SEGUNDOS = max(registro.RCO_NDURACION_SEGUNDOS, duracion)

    if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
        registro.RCO_FSOLICITUD_CLIENTE = fecha
        evento = 'CALIDAD_APRUEBA_CLIENTE'
    else:
        registro.RCO_FRESOLUCION_FINAL = fecha
        registro.RCO_FCIERRE = fecha
        registro.RCO_BCIERRE_AUTOMATICO = True
        registro.RCO_BAUTORIZA_SALIDA = estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO
        if estado_anterior == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
            evento = f'CALIDAD_RESPUESTA_CLIENTE_{"APROBADA" if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO else "RECHAZADA"}'
        else:
            evento = 'CALIDAD_APROBADA' if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO else 'CALIDAD_RECHAZADA'

    registro.save()
    detalle = _detalle_evento(registro, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema)
    _crear_historial(registro, evento, estado_anterior, estado_nuevo, origen, observacion, usuario, responsable_sistema, fecha)
    _crear_log(registro, usuario, evento, detalle)

    if estado_nuevo == RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
        _crear_log(registro, usuario, 'CALIDAD_ESPERANDO_CLIENTE', detalle)
    else:
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
        registro.Estado.RECHAZADO: MENSAJE_SALIDA_RECHAZO,
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
