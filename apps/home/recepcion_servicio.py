import re
import uuid
from datetime import datetime, time, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import (
    CALENDARIO,
    CITACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    NOTIFICACION,
    OPERACION_PLANTA_LOG,
    PERFIL_USUARIO,
    PLANIFICACION,
    RECEPCION_SERVICIO_DETALLE,
    SECUENCIA,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
)
from .services.notification_service import crear_notificacion_interna


SECUENCIA_CODIGO = 'RECEPCION_SERVICIO'
PASO_RECEPCION_CONFORME = 'Recepción Conforme'
PASO_CONFIRMAR_SALIDA = 'Confirmar Salida'
PASOS_OPERACION = (
    (PASO_RECEPCION_CONFORME, ['ASISTENTE CD']),
    (PASO_CONFIRMAR_SALIDA, ['GUARDIA PORTERIA']),
)
RESULTADO_PLANIFICADA = 'RECEPCION_SERVICIO_PLANIFICADA'
ESTADO_PLANIFICADA = 'Insumo Programado'


def normalizar_patente(valor):
    return re.sub(r'[^A-Z0-9]', '', str(valor or '').strip().upper())


def es_recepcion_servicio(citacion):
    return bool(
        citacion
        and citacion.EP_NID_id in (1, 2)
        and str(citacion.CI_CTIPO or '').strip().upper() == 'RECEPCION'
        and getattr(citacion, 'SC_NID_id', None)
        and str(citacion.SC_NID.SE_CCODIGO or '').strip().upper() == SECUENCIA_CODIGO
    )


def _usuario_configuracion(empresa, usuario):
    if usuario and getattr(usuario, 'is_active', False):
        return usuario
    asignado = USERS_EMPRESA.objects.filter(
        EP_NID=empresa, US_NID__is_active=True,
    ).select_related('US_NID').first()
    if asignado:
        return asignado.US_NID
    raise ValueError('La empresa no tiene un usuario activo para configurar Recepción Servicio.')


def asegurar_configuracion(empresa, usuario):
    usuario_config = _usuario_configuracion(empresa, usuario)
    secuencia, _ = SECUENCIA.objects.get_or_create(
        EP_NID=empresa,
        SE_CCODIGO=SECUENCIA_CODIGO,
        defaults={
            'US_NID': usuario_config,
            'SE_CTIPO': 'RECEPCION',
            'SE_CNOMBRE': 'Recepción Servicio',
            'SE_BHABILITADO': True,
            'SE_FFECHAREGISTRO': timezone.now(),
        },
    )
    secuencia.US_NID = secuencia.US_NID or usuario_config
    secuencia.SE_CTIPO = 'RECEPCION'
    secuencia.SE_CNOMBRE = 'Recepción Servicio'
    secuencia.SE_BHABILITADO = True
    secuencia.save(update_fields=['US_NID', 'SE_CTIPO', 'SE_CNOMBRE', 'SE_BHABILITADO'])

    configuracion = (
        (1, 'RS_RECEPCION_CONFORME', PASO_RECEPCION_CONFORME, 'OPERACION'),
        (2, 'RS_CONFIRMAR_SALIDA', PASO_CONFIRMAR_SALIDA, 'SALIDA'),
    )
    for numero, codigo, nombre, tipo in configuracion:
        etapa, _ = ETAPA.objects.get_or_create(
            EP_NID=empresa,
            ET_CCODIGO=codigo,
            defaults={
                'US_NID': usuario_config,
                'ET_CTIPO': tipo,
                'ET_CNOMBRE': nombre,
                'ET_NCANTIDADMAXIMA': 1,
                'ET_BHABILITADO': True,
                'ET_BINTEGRARSAP': False,
                'ET_FFECHAREGISTRO': timezone.now(),
            },
        )
        ETAPA.objects.filter(pk=etapa.pk).update(
            ET_CTIPO=tipo,
            ET_CNOMBRE=nombre,
            ET_NCANTIDADMAXIMA=1,
            ET_BHABILITADO=True,
            ET_BINTEGRARSAP=False,
        )
        detalle = DETALLE_SECUENCIA.objects.filter(
            EP_NID=empresa, SC_NID=secuencia, ET_NID=etapa,
        ).order_by('id').first()
        if detalle is None:
            detalle = DETALLE_SECUENCIA.objects.create(
                US_NID=usuario_config,
                EP_NID=empresa,
                SC_NID=secuencia,
                ET_NID=etapa,
                SE_NPASO=numero,
                SE_BHABILITADO=True,
                SE_BOBLIGATORIO=True,
            )
        else:
            detalle.US_NID = detalle.US_NID or usuario_config
            detalle.SE_NPASO = numero
            detalle.SE_BHABILITADO = True
            detalle.SE_BOBLIGATORIO = True
            detalle.save(update_fields=['US_NID', 'SE_NPASO', 'SE_BHABILITADO', 'SE_BOBLIGATORIO'])
    return secuencia


def usuarios_por_perfiles(empresa_id, perfiles):
    buscados = {str(valor).strip().upper().replace('_', ' ') for valor in perfiles}
    asignados = USERS_EMPRESA.objects.filter(
        EP_NID_id=empresa_id,
    ).values_list('US_NID_id', flat=True)
    relaciones = PERFIL_USUARIO.objects.select_related('PR_NID', 'US_NID').filter(
        US_NID_id__in=asignados,
        US_NID__is_active=True,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
    )
    resultado = []
    vistos = set()
    for relacion in relaciones:
        valores = {
            str(relacion.PR_NID.PR_CCODIGO or '').strip().upper().replace('_', ' '),
            str(relacion.PR_NID.PR_CNOMBRE or '').strip().upper().replace('_', ' '),
        }
        if buscados & valores and relacion.US_NID_id not in vistos:
            resultado.append(relacion.US_NID)
            vistos.add(relacion.US_NID_id)
    return resultado


def notificar(citacion, emisor, destinatarios, contenido, url):
    creadas = 0
    for receptor in destinatarios:
        existe = NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=receptor,
            EP_NID=citacion.EP_NID,
            NOT_CCONTENIDO=contenido,
            NOT_CURL=url,
            NOT_BHABILITADO=True,
        ).exists()
        if existe:
            continue
        crear_notificacion_interna(
            USER_SENDER_ID=emisor,
            USER_RECEIVER_ID=receptor,
            EP_NID=citacion.EP_NID,
            NOT_CCONTENIDO=contenido,
            NOT_CURL=url,
        )
        creadas += 1
    return creadas


def notificar_guardia(citacion, emisor):
    url = f'{reverse("recepcion_servicio_registro")}?section=planificacion&_empresa_id={citacion.EP_NID_id}'
    detalle = citacion.detalle_recepcion_servicio
    contenido = (
        f'Recepción Servicio planificada: citación #{citacion.id}, '
        f'{detalle.get_RSD_CTIPO_SERVICIO_display()}, patente {detalle.RSD_CPATENTE}.'
    )
    return notificar(
        citacion, emisor,
        usuarios_por_perfiles(citacion.EP_NID_id, {'GUARDIA PORTERIA'}),
        contenido, url,
    )


def notificar_asistente_cd(citacion, emisor):
    url = f'{reverse("operacion_planta_citacion", args=[citacion.id])}?_empresa_id={citacion.EP_NID_id}'
    contenido = f'Recepción Servicio #{citacion.id} ingresó a planta y requiere Recepción Conforme.'
    return notificar(
        citacion, emisor,
        usuarios_por_perfiles(citacion.EP_NID_id, {'ASISTENTE CD', 'ASISTENTE C D'}),
        contenido, url,
    )


def notificar_guardia_salida(citacion, emisor):
    url = f'{reverse("operacion_planta_citacion", args=[citacion.id])}?_empresa_id={citacion.EP_NID_id}'
    contenido = f'Recepción Servicio #{citacion.id} tiene Recepción Conforme registrada y espera Confirmar Salida.'
    return notificar(
        citacion, emisor,
        usuarios_por_perfiles(citacion.EP_NID_id, {'GUARDIA PORTERIA'}),
        contenido, url,
    )


def estado(detalle):
    citacion = detalle.CI_NID
    if citacion.CI_FFECHATERMINO or OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion,
        OPL_CPASO=PASO_CONFIRMAR_SALIDA,
        OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).exists():
        return 'COMPLETADA'
    if SYSLOGGER.objects.filter(
        LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
        LOG_CADD1=str(citacion.id),
    ).exists():
        return 'ACTIVA'
    return 'PENDIENTE'


def _fecha_hora(fecha_texto, hora_texto):
    try:
        fecha = datetime.strptime(fecha_texto, '%Y-%m-%d').date()
        hora = datetime.strptime(hora_texto, '%H:%M').time()
    except (TypeError, ValueError):
        raise ValueError('Debe ingresar una fecha y hora válidas.')
    valor = datetime.combine(fecha, hora)
    return timezone.make_aware(valor, timezone.get_current_timezone())


def crear_planificacion(empresa_id, usuario, datos):
    if empresa_id not in (1, 2):
        raise ValueError('Recepción Servicio solo está disponible para Terramar y Aceites SBH.')
    tipo = str(datos.get('tipo_servicio') or '').strip().upper()
    tipos_validos = {valor for valor, _ in RECEPCION_SERVICIO_DETALLE.TipoServicio.choices}
    if tipo not in tipos_validos:
        raise ValueError('Seleccione un tipo de servicio válido.')
    patente = normalizar_patente(datos.get('patente'))
    if not patente:
        raise ValueError('Debe ingresar la patente del camión.')
    chofer = ' '.join(str(datos.get('nombre_chofer') or '').split())
    if not chofer:
        raise ValueError('Debe ingresar el nombre del chofer.')
    try:
        proveedor_id = int(datos.get('proveedor_id'))
    except (TypeError, ValueError):
        raise ValueError('Seleccione un proveedor válido.')
    try:
        clave = uuid.UUID(str(datos.get('idempotencia') or ''))
    except (TypeError, ValueError, AttributeError):
        raise ValueError('La solicitud de planificación no tiene una clave válida.')
    fecha_citacion = _fecha_hora(datos.get('fecha'), datos.get('hora'))
    observacion = str(datos.get('observacion') or '').strip()

    with transaction.atomic():
        empresa = EMPRESA.objects.select_for_update().get(pk=empresa_id)
        existente = RECEPCION_SERVICIO_DETALLE.objects.select_related('CI_NID').filter(
            RSD_CIDEMPOTENCIA=clave,
        ).first()
        if existente:
            if existente.EP_NID_id != empresa_id or existente.US_NID_id != usuario.id:
                raise ValueError('La clave de planificación ya fue utilizada.')
            return existente, False
        proveedor = SOCIONEGOCIO.objects.get(
            pk=proveedor_id,
            EP_NID=empresa,
            SN_CTIPO='S',
            SN_BHABILITADO=True,
        )
        secuencia = asegurar_configuracion(empresa, usuario)
        fecha = timezone.localtime(fecha_citacion).date()
        calendario, _ = CALENDARIO.objects.get_or_create(
            EP_NID=empresa,
            CA_NDIA=fecha.day,
            CA_NMES=fecha.month,
            CA_NANO=fecha.year,
            CA_CNOMBRE=f'Recepción Servicio {fecha:%Y-%m-%d}',
            defaults={
                'US_NID': usuario,
                'CA_FHORA_APERTURA': time(0, 0),
                'CA_FHORA_CIERRE': time(23, 59),
                'CA_NCANTIDADCUPOS': 9999,
                'CA_BHABILITADO': True,
            },
        )
        planificacion = PLANIFICACION.objects.create(
            US_NID=usuario,
            EP_NID=empresa,
            CAL_NID=calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAREGISTRO=timezone.now(),
            PL_FFECHAINICIO=fecha_citacion,
            PL_FFECHAFIN=fecha_citacion + timedelta(hours=1),
            PL_NCANTIDADCUPOS=1,
        )
        citacion = CITACION.objects.create(
            US_NID=usuario,
            EP_NID=empresa,
            PL_NID=planificacion,
            PRO_NID=proveedor,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=fecha_citacion,
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO=ESTADO_PLANIFICADA,
            CI_CCOMENTARIO=observacion,
        )
        detalle = RECEPCION_SERVICIO_DETALLE.objects.create(
            EP_NID=empresa,
            CI_NID=citacion,
            PRO_NID=proveedor,
            RSD_CTIPO_SERVICIO=tipo,
            RSD_CPATENTE=patente,
            RSD_CNOMBRE_CHOFER=chofer,
            RSD_COBSERVACION=observacion,
            US_NID=usuario,
            RSD_CIDEMPOTENCIA=clave,
        )
        notificar_guardia(citacion, usuario)
        return detalle, True


def listar(empresa_id, filtro='PENDIENTES'):
    detalles = RECEPCION_SERVICIO_DETALLE.objects.select_related(
        'CI_NID', 'CI_NID__PL_NID', 'CI_NID__EP_NID', 'PRO_NID', 'US_NID',
    ).filter(
        EP_NID_id=empresa_id,
        CI_NID__CI_BHABILITADO=True,
        CI_NID__SC_NID__SE_CCODIGO=SECUENCIA_CODIGO,
    ).order_by('-CI_NID__CI_FFECHACITACION', '-id')
    resultado = []
    for detalle in detalles:
        estado_actual = estado(detalle)
        if filtro == 'PENDIENTES' and estado_actual != 'PENDIENTE':
            continue
        if filtro == 'ACTIVOS' and estado_actual != 'ACTIVA':
            continue
        if filtro == 'COMPLETADOS' and estado_actual != 'COMPLETADA':
            continue
        resultado.append({'detalle': detalle, 'estado': estado_actual})
    return resultado


def pendientes_por_patente(empresa_id, patente):
    patente = normalizar_patente(patente)
    if not patente:
        return []
    candidatos = RECEPCION_SERVICIO_DETALLE.objects.select_related(
        'CI_NID', 'CI_NID__PL_NID', 'CI_NID__EP_NID', 'CI_NID__SC_NID', 'PRO_NID',
    ).filter(
        EP_NID_id=empresa_id,
        RSD_CPATENTE=patente,
        CI_NID__CI_BHABILITADO=True,
        CI_NID__CI_CESTADO=ESTADO_PLANIFICADA,
        CI_NID__CI_FFECHATERMINO__isnull=True,
        CI_NID__SC_NID__SE_CCODIGO=SECUENCIA_CODIGO,
    ).order_by('CI_NID__CI_FFECHACITACION', 'id')
    ids_autorizados = {
        int(valor) for valor in SYSLOGGER.objects.filter(
            EP_NID_id=empresa_id,
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1__in=[str(d.CI_NID_id) for d in candidatos],
        ).values_list('LOG_CADD1', flat=True)
        if str(valor).isdigit()
    }
    return [detalle for detalle in candidatos if detalle.CI_NID_id not in ids_autorizados]
