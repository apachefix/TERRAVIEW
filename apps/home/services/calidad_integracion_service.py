from dataclasses import dataclass
from datetime import timedelta
import json
import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.home.models import EMPRESA, EVENTO_INTEGRACION_CALIDAD, RESULTADO_CALIDAD_OPERACION
from apps.home.services.calidad_service import (
    ProcesoCalidadAmbiguo,
    ProcesoCalidadNoEncontrado,
    ProcesoCalidadNoPreparado,
    TRANSICIONES_PERMITIDAS,
    buscar_resultado_calidad_por_guia,
    procesar_resultado_calidad,
)
from apps.home.services.teams_service import TeamsNotificationResult, enviar_resultado_calidad_teams


logger = logging.getLogger(__name__)
ESTADOS_DEFINITIVOS = {
    RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
    RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
}


@dataclass
class ResultadoIntegracion:
    status_http: int
    payload: dict
    evento: EVENTO_INTEGRACION_CALIDAD | None = None
    procesado: bool = False


def _log_tecnico(codigo, evento_id='', detalle=''):
    evento_seguro = re.sub(r'[\r\n\t]+', ' ', str(evento_id or ''))[:128]
    detalle_seguro = re.sub(r'[\r\n\t]+', ' ', str(detalle or ''))[:500]
    logger.info('%s id_evento=%s detalle=%s', codigo, evento_seguro, detalle_seguro)


def sanitizar_error_tecnico(valor):
    texto = str(valor or '')
    texto = re.sub(r'https?://\S+', '[URL_REDACTADA]', texto, flags=re.IGNORECASE)
    texto = re.sub(
        r'(?i)\b(password|passwd|token|cookie|authorization|secret|api[_ -]?key)\b'
        r'(\s*[:=]\s*)([^\s,;]+)',
        r'\1\2[DATO_REDACTADO]',
        texto,
    )
    api_key = str(getattr(settings, 'TERRAVIEW_CALIDAD_API_KEY', '') or '')
    if api_key:
        texto = texto.replace(api_key, '[API_KEY_REDACTADA]')
    return texto[:2000]


def _payload_auditoria(datos):
    return json.dumps({
        'empresa_id': datos['empresa_id'],
        'numero_guia': datos['numero_guia'],
        'estado': datos['estado'],
        'origen': datos['origen'],
        'observacion': sanitizar_error_tecnico(datos.get('observacion', '')),
        'fecha_resultado': datos['fecha_resultado'].isoformat() if datos.get('fecha_resultado') else '',
        'id_evento': datos['id_evento'],
    }, ensure_ascii=False)


def _actualizar_error(evento, estado, codigo, mensaje, status_http):
    evento.EIC_CESTADO_PROCESAMIENTO = estado
    evento.EIC_CRESULTADO = codigo
    evento.EIC_CMENSAJE_TECNICO = sanitizar_error_tecnico(mensaje)
    evento.EIC_FPROCESAMIENTO = timezone.now()
    evento.EIC_NCODIGO_RESPUESTA = status_http
    evento.save(update_fields=[
        'EIC_CESTADO_PROCESAMIENTO', 'EIC_CRESULTADO', 'EIC_CMENSAJE_TECNICO',
        'EIC_FPROCESAMIENTO', 'EIC_NCODIGO_RESPUESTA',
    ])
    _log_tecnico('CALIDAD_API_VALIDACION_ERROR' if status_http < 500 else 'CALIDAD_API_ERROR', evento.EIC_CID_EVENTO, codigo)
    return ResultadoIntegracion(
        status_http,
        {'ok': False, 'codigo': codigo, 'mensaje': mensaje},
        evento=evento,
    )


def _accion_resultado(estado, cambiado):
    if not cambiado:
        return 'SIN_CAMBIOS'
    if estado == RESULTADO_CALIDAD_OPERACION.Estado.APROBADO:
        return 'ETAPA_CERRADA_Y_AVANZADA'
    if estado == RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO:
        return 'FLUJO_FINALIZADO_SALIDA_AUTORIZADA'
    return 'ESPERA_APROBACION_CLIENTE'


def _validar_reglas_origen(resultado, estado, origen):
    if origen == RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE:
        if estado not in ESTADOS_DEFINITIVOS:
            return 'TRANSICION_INVALIDA', 'CORREO_CLIENTE solo puede enviar APROBADO o RECHAZADO.'
        if resultado.RCO_CESTADO != RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE:
            return 'TRANSICION_INVALIDA', 'CORREO_CLIENTE solo puede resolver un proceso en APRUEBA_CLIENTE.'
        return None
    if origen != RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD:
        return 'ORIGEN_INVALIDO', 'El origen recibido no esta permitido para esta integracion.'
    if estado == resultado.RCO_CESTADO:
        return None
    if estado not in TRANSICIONES_PERMITIDAS.get(resultado.RCO_CESTADO, set()):
        return 'TRANSICION_INVALIDA', 'El estado recibido no es valido para el estado actual del proceso.'
    return None


def procesar_evento_integracion_calidad(datos):
    id_evento = datos['id_evento']
    payload_sanitizado = _payload_auditoria(datos)

    try:
        with transaction.atomic():
            evento = EVENTO_INTEGRACION_CALIDAD.objects.create(
                EIC_CID_EVENTO=id_evento,
                EP_NID=EMPRESA.objects.filter(pk=datos['empresa_id']).first(),
                EIC_CNUMERO_GUIA=datos['numero_guia'],
                EIC_CESTADO_SOLICITADO=datos['estado'],
                EIC_CORIGEN=datos['origen'],
                EIC_FRESULTADO=datos.get('fecha_resultado'),
                EIC_CPAYLOAD_SANITIZADO=payload_sanitizado,
            )
            _log_tecnico('CALIDAD_API_EVENTO_RECIBIDO', id_evento)

            if evento.EP_NID_id is None:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    'EMPRESA_NO_ENCONTRADA', 'La empresa informada no existe.', 404,
                )

            try:
                resultado = buscar_resultado_calidad_por_guia(datos['empresa_id'], datos['numero_guia'])
            except ProcesoCalidadNoEncontrado as exc:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    'GUIA_NO_ENCONTRADA', str(exc), 404,
                )
            except ProcesoCalidadNoPreparado as exc:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    'PROCESO_NO_PREPARADO', str(exc), 409,
                )
            except ProcesoCalidadAmbiguo as exc:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    'COINCIDENCIA_AMBIGUA', str(exc), 409,
                )

            evento.RCO_NID = resultado
            evento.CI_NID = resultado.CI_NID
            evento.save(update_fields=['RCO_NID', 'CI_NID'])
            error_origen = _validar_reglas_origen(resultado, datos['estado'], datos['origen'])
            if error_origen:
                codigo, mensaje = error_origen
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    codigo, mensaje, 409,
                )

            estado_anterior = resultado.RCO_CESTADO
            responsable_sistema = (
                'BOT_CALIDAD_CORREO'
                if datos['origen'] == RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE
                else 'BOT_CALIDAD_EXCEL'
            )
            try:
                # El savepoint mantiene utilizable la transaccion exterior para
                # registrar la auditoria aun si el servicio falla en base de datos.
                with transaction.atomic():
                    resultado, cambiado = procesar_resultado_calidad(
                        resultado.CI_NID,
                        datos['estado'],
                        datos['origen'],
                        observacion=datos.get('observacion', ''),
                        usuario=None,
                        responsable_sistema=responsable_sistema,
                        fecha_resultado=datos.get('fecha_resultado'),
                    )
            except ValueError:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_VALIDACION,
                    'TRANSICION_INVALIDA',
                    'El estado recibido no es valido para el estado actual del proceso.',
                    409,
                )
            except Exception:
                return _actualizar_error(
                    evento, evento.EstadoProcesamiento.ERROR_PROCESAMIENTO,
                    'ERROR_PROCESAMIENTO',
                    'No fue posible procesar el evento de Calidad.',
                    500,
                )

            accion = _accion_resultado(resultado.RCO_CESTADO, cambiado)
            enviar_teams = cambiado and resultado.RCO_CESTADO in ESTADOS_DEFINITIVOS
            evento.RCO_NID = resultado
            evento.CI_NID = resultado.CI_NID
            evento.EIC_CESTADO_PROCESAMIENTO = evento.EstadoProcesamiento.PROCESADO
            evento.EIC_CRESULTADO = accion
            evento.EIC_CMENSAJE_TECNICO = 'Evento aplicado mediante calidad_service.py.' if cambiado else 'Estado ya aplicado; sin cambios funcionales.'
            evento.EIC_FPROCESAMIENTO = timezone.now()
            evento.EIC_NCODIGO_RESPUESTA = 200
            evento.EIC_BTEAMS_PENDIENTE = enviar_teams
            evento.EIC_CESTADO_TEAMS = evento.EstadoTeams.PENDIENTE if enviar_teams else evento.EstadoTeams.NO_APLICA
            evento.save()
            _log_tecnico('CALIDAD_API_PROCESADO', id_evento, accion)
            if enviar_teams:
                _log_tecnico('CALIDAD_TEAMS_PENDIENTE', id_evento)
            return ResultadoIntegracion(
                200,
                {
                    'ok': True,
                    'procesado': bool(cambiado),
                    'duplicado': False,
                    'id_evento': id_evento,
                    'empresa_id': evento.EP_NID_id,
                    'numero_guia': evento.EIC_CNUMERO_GUIA,
                    'estado_anterior': estado_anterior,
                    'estado_actual': resultado.RCO_CESTADO,
                    'accion': accion,
                    'citacion': resultado.CI_NID_id,
                },
                evento=evento,
                procesado=bool(cambiado),
            )
    except IntegrityError:
        with transaction.atomic():
            evento = EVENTO_INTEGRACION_CALIDAD.objects.select_for_update().get(EIC_CID_EVENTO=id_evento)
            evento.EIC_BDUPLICADO = True
            evento.save(update_fields=['EIC_BDUPLICADO'])
        _log_tecnico('CALIDAD_API_EVENTO_DUPLICADO', id_evento)
        return ResultadoIntegracion(
            200,
            {
                'ok': True,
                'procesado': False,
                'duplicado': True,
                'id_evento': id_evento,
                'mensaje': 'El evento ya fue procesado anteriormente.',
            },
            evento=evento,
        )


def maximo_intentos_teams():
    try:
        return max(int(getattr(settings, 'CALIDAD_TEAMS_MAX_INTENTOS', 3)), 1)
    except (TypeError, ValueError):
        return 3


def intentar_notificacion_calidad_teams(evento_id, es_reintento=False):
    ahora = timezone.now()
    with transaction.atomic():
        evento = EVENTO_INTEGRACION_CALIDAD.objects.select_for_update().get(pk=evento_id)
        if evento.EIC_BTEAMS_ENVIADO or not evento.EIC_BTEAMS_PENDIENTE:
            return evento, False
        if evento.EIC_NINTENTOS_TEAMS >= maximo_intentos_teams():
            return evento, False
        if (
            evento.EIC_CESTADO_TEAMS == evento.EstadoTeams.ENVIANDO
            and evento.EIC_FULTIMO_INTENTO_TEAMS
            and evento.EIC_FULTIMO_INTENTO_TEAMS > ahora - timedelta(minutes=10)
        ):
            return evento, False
        evento.EIC_CESTADO_TEAMS = evento.EstadoTeams.ENVIANDO
        evento.EIC_NINTENTOS_TEAMS += 1
        evento.EIC_FULTIMO_INTENTO_TEAMS = ahora
        evento.EIC_CERROR_TEAMS = ''
        evento.save(update_fields=[
            'EIC_CESTADO_TEAMS', 'EIC_NINTENTOS_TEAMS',
            'EIC_FULTIMO_INTENTO_TEAMS', 'EIC_CERROR_TEAMS',
        ])

    _log_tecnico('CALIDAD_TEAMS_REINTENTO' if es_reintento else 'CALIDAD_TEAMS_PENDIENTE', evento.EIC_CID_EVENTO)
    try:
        resultado = enviar_resultado_calidad_teams(evento.RCO_NID, evento)
    except Exception as exc:
        resultado = TeamsNotificationResult(False, 'TEAMS_ERROR', str(exc))

    with transaction.atomic():
        evento = EVENTO_INTEGRACION_CALIDAD.objects.select_for_update().get(pk=evento_id)
        evento.EIC_BTEAMS_ENVIADO = bool(resultado.success)
        evento.EIC_BTEAMS_PENDIENTE = not bool(resultado.success)
        evento.EIC_CESTADO_TEAMS = evento.EstadoTeams.ENVIADO if resultado.success else evento.EstadoTeams.ERROR
        evento.EIC_CERROR_TEAMS = '' if resultado.success else sanitizar_error_tecnico(resultado.detail)
        evento.EIC_CMENSAJE_TECNICO = sanitizar_error_tecnico(
            f'{evento.EIC_CMENSAJE_TECNICO or ""} Teams: {resultado.status}.'
        )
        evento.save(update_fields=[
            'EIC_BTEAMS_ENVIADO', 'EIC_BTEAMS_PENDIENTE', 'EIC_CESTADO_TEAMS',
            'EIC_CERROR_TEAMS', 'EIC_CMENSAJE_TECNICO',
        ])
    _log_tecnico(
        'CALIDAD_TEAMS_ENVIADO' if resultado.success else 'CALIDAD_TEAMS_ERROR',
        evento.EIC_CID_EVENTO,
        resultado.status,
    )
    return evento, True
