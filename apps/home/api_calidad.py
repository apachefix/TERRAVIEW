import json
import logging
import secrets
import unicodedata

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from apps.home.models import RESULTADO_CALIDAD_OPERACION
from apps.home.services.calidad_integracion_service import (
    intentar_notificacion_calidad_teams,
    procesar_evento_integracion_calidad,
    sanitizar_error_tecnico,
)


logger = logging.getLogger(__name__)
CAMPOS_OBLIGATORIOS = ('empresa_id', 'numero_guia', 'estado', 'origen', 'id_evento')
ESTADOS_API = {
    'APROBADO': RESULTADO_CALIDAD_OPERACION.Estado.APROBADO,
    'RECHAZADO': RESULTADO_CALIDAD_OPERACION.Estado.RECHAZADO,
    'APRUEBA_CLIENTE': RESULTADO_CALIDAD_OPERACION.Estado.APRUEBA_CLIENTE,
}
ORIGENES_API = {
    RESULTADO_CALIDAD_OPERACION.Origen.EXCEL_CALIDAD,
    RESULTADO_CALIDAD_OPERACION.Origen.CORREO_CLIENTE,
}


def _respuesta_error(status, codigo, mensaje):
    return JsonResponse({'ok': False, 'codigo': codigo, 'mensaje': mensaje}, status=status)


def _normalizar_codigo(valor):
    texto = unicodedata.normalize('NFKD', str(valor or '').strip())
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return '_'.join(texto.upper().replace('-', ' ').replace('_', ' ').split())


def _validar_payload(data):
    if not isinstance(data, dict):
        return None, _respuesta_error(400, 'JSON_INVALIDO', 'El cuerpo JSON debe ser un objeto.')
    faltantes = [campo for campo in CAMPOS_OBLIGATORIOS if data.get(campo) in (None, '')]
    if faltantes:
        return None, _respuesta_error(
            400, 'CAMPO_REQUERIDO', f'Falta el campo obligatorio: {faltantes[0]}.'
        )
    try:
        empresa_id = int(data['empresa_id'])
        if empresa_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, _respuesta_error(400, 'EMPRESA_INVALIDA', 'empresa_id debe ser un entero positivo.')

    numero_guia = str(data['numero_guia']).strip()
    id_evento = str(data['id_evento']).strip()
    if not numero_guia or len(numero_guia) > 128:
        return None, _respuesta_error(400, 'GUIA_INVALIDA', 'numero_guia es invalido.')
    if not id_evento or len(id_evento) > 128:
        return None, _respuesta_error(400, 'ID_EVENTO_INVALIDO', 'id_evento es invalido.')

    estado = ESTADOS_API.get(_normalizar_codigo(data['estado']))
    if not estado:
        return None, _respuesta_error(400, 'ESTADO_INVALIDO', 'El estado recibido no es valido.')
    origen = _normalizar_codigo(data['origen'])
    if origen not in ORIGENES_API:
        return None, _respuesta_error(400, 'ORIGEN_INVALIDO', 'El origen recibido no esta permitido.')

    fecha_resultado = None
    if data.get('fecha_resultado') not in (None, ''):
        fecha_resultado = parse_datetime(str(data['fecha_resultado']).strip())
        if fecha_resultado is None:
            return None, _respuesta_error(400, 'FECHA_INVALIDA', 'fecha_resultado debe usar formato ISO 8601.')
        if timezone.is_naive(fecha_resultado):
            fecha_resultado = timezone.make_aware(fecha_resultado, timezone.get_current_timezone())

    return {
        'empresa_id': empresa_id,
        'numero_guia': numero_guia,
        'estado': estado,
        'origen': origen,
        'observacion': sanitizar_error_tecnico(str(data.get('observacion') or '').strip()),
        'fecha_resultado': fecha_resultado,
        'id_evento': id_evento,
    }, None


@csrf_exempt
def resultado_calidad_integracion_api(request):
    if request.method != 'POST':
        return _respuesta_error(405, 'METODO_NO_PERMITIDO', 'Metodo no permitido.')

    api_key_configurada = str(getattr(settings, 'TERRAVIEW_CALIDAD_API_KEY', '') or '')
    api_key_recibida = str(request.headers.get('X-TERRAVIEW-API-KEY') or '')
    if not api_key_recibida:
        logger.warning('CALIDAD_API_VALIDACION_ERROR credencial_ausente')
        return _respuesta_error(401, 'CREDENCIAL_AUSENTE', 'Falta la credencial de integracion.')
    if not api_key_configurada:
        logger.error('CALIDAD_API_ERROR integracion_no_configurada')
        return _respuesta_error(503, 'INTEGRACION_NO_CONFIGURADA', 'La integracion de Calidad no esta configurada.')
    if not secrets.compare_digest(api_key_recibida, api_key_configurada):
        logger.warning('CALIDAD_API_VALIDACION_ERROR credencial_incorrecta')
        return _respuesta_error(403, 'CREDENCIAL_INCORRECTA', 'La credencial de integracion no es valida.')

    try:
        data = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return _respuesta_error(400, 'JSON_INVALIDO', 'El cuerpo de la solicitud no contiene JSON valido.')

    datos, error = _validar_payload(data)
    if error:
        return error

    try:
        resultado = procesar_evento_integracion_calidad(datos)
    except Exception:
        logger.exception('CALIDAD_API_ERROR id_evento=%s', datos['id_evento'])
        return _respuesta_error(500, 'ERROR_INTERNO', 'No fue posible procesar la solicitud.')

    if resultado.status_http == 200 and resultado.procesado and resultado.evento.EIC_BTEAMS_PENDIENTE:
        evento, _ = intentar_notificacion_calidad_teams(resultado.evento.id)
        resultado.payload['teams_enviado'] = evento.EIC_BTEAMS_ENVIADO
        resultado.payload['teams_pendiente'] = evento.EIC_BTEAMS_PENDIENTE
    return JsonResponse(resultado.payload, status=resultado.status_http)
