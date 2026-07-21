import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode


class TeamsNotificationResult:
    def __init__(self, success, status, detail=''):
        self.success = success
        self.status = status
        self.detail = detail


def _graph_config():
    tenant_id = getattr(settings, 'MICROSOFT_GRAPH_TENANT_ID', '')
    client_id = getattr(settings, 'MICROSOFT_GRAPH_CLIENT_ID', '')
    client_secret = getattr(settings, 'MICROSOFT_GRAPH_CLIENT_SECRET', '')
    sender_user = getattr(settings, 'MICROSOFT_GRAPH_SENDER_USER', '')

    if not tenant_id or not client_id or not client_secret or not sender_user:
        return None

    return {
        'tenant_id': tenant_id,
        'client_id': client_id,
        'client_secret': client_secret,
        'sender_user': sender_user,
    }


def _teams_webhook_url():
    return getattr(settings, 'TEAMS_WEBHOOK_URL', None)


def _teams_webhook_mode():
    return str(getattr(settings, 'TEAMS_WEBHOOK_MODE', 'adaptive') or 'adaptive').strip().lower()


def _crear_payload_webhook(mensaje, titulo='ALERTA CAMION NO PLANIFICADO', hechos=None, documentos=None, acciones=None):
    if _teams_webhook_mode() == 'text':
        return {'text': f'{titulo}\n\n{mensaje}'}

    cuerpo = [
        {
            'type': 'TextBlock',
            'text': titulo,
            'weight': 'Bolder',
            'size': 'Medium'
        },
        {
            'type': 'TextBlock',
            'text': mensaje,
            'wrap': True
        }
    ]
    if hechos:
        cuerpo.append({
            'type': 'FactSet',
            'facts': [
                {'title': str(titulo_hecho), 'value': str(valor or '-')}
                for titulo_hecho, valor in hechos
            ]
        })
    if documentos:
        cuerpo.append({
            'type': 'TextBlock',
            'text': '**Documentos**',
            'weight': 'Bolder',
            'wrap': True
        })
        for nombre, url in documentos:
            cuerpo.append({
                'type': 'TextBlock',
                'text': f'[{nombre}]({url})',
                'wrap': True,
                'spacing': 'Small'
            })
    elif documentos == []:
        cuerpo.append({
            'type': 'TextBlock',
            'text': '**Documentos**\n\nSin documentos adjuntos',
            'wrap': True
        })

    acciones_card = [
        {'type': 'Action.OpenUrl', 'title': str(nombre), 'url': str(url)}
        for nombre, url in (acciones or []) if url
    ]

    return {
        'type': 'message',
        'attachments': [
            {
                'contentType': 'application/vnd.microsoft.card.adaptive',
                'content': {
                    '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
                    'type': 'AdaptiveCard',
                    'version': '1.4',
                    'body': cuerpo,
                    **({'actions': acciones_card} if acciones_card else {})
                }
            }
        ]
    }


def _enviar_por_webhook(mensaje, titulo='ALERTA CAMION NO PLANIFICADO', hechos=None, documentos=None, acciones=None):
    webhook_url = _teams_webhook_url()

    if not webhook_url:
        return None

    response = None

    try:
        payload = _crear_payload_webhook(
            mensaje,
            titulo,
            hechos=hechos,
            documentos=documentos,
            acciones=acciones
        )
        response = requests.post(
            webhook_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        response.raise_for_status()

        return TeamsNotificationResult(
            success=True,
            status='TEAMS_WEBHOOK_OK',
            detail=f'HTTP {response.status_code}: {response.text[:250]}'
        )

    except Exception as exc:
        detalle = str(exc)
        if response is not None:
            detalle = f'HTTP {response.status_code}: {response.text[:500]} - {detalle}'

        return TeamsNotificationResult(
            success=False,
            status='TEAMS_WEBHOOK_ERROR',
            detail=detalle
        )


def enviar_alerta_camion_no_planificado_teams(
    destinatario_email,
    mensaje,
    titulo='ALERTA CAMION NO PLANIFICADO',
    hechos=None,
    documentos=None,
    acciones=None
):
    resultado_webhook = _enviar_por_webhook(
        mensaje,
        titulo,
        hechos=hechos,
        documentos=documentos,
        acciones=acciones
    )

    if resultado_webhook is not None:
        return resultado_webhook

    config = _graph_config()

    if not config:
        return TeamsNotificationResult(
            success=False,
            status='GRAPH_NO_CONFIGURADO',
            detail='Microsoft Graph no tiene credenciales configuradas.'
        )

    try:
        token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
        token_response = requests.post(
            token_url,
            data={
                'client_id': config['client_id'],
                'client_secret': config['client_secret'],
                'scope': 'https://graph.microsoft.com/.default',
                'grant_type': 'client_credentials',
            },
            timeout=15
        )
        token_response.raise_for_status()
        access_token = token_response.json().get('access_token')

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        chat_response = requests.post(
            'https://graph.microsoft.com/v1.0/chats',
            headers=headers,
            json={
                'chatType': 'oneOnOne',
                'members': [
                    {
                        '@odata.type': '#microsoft.graph.aadUserConversationMember',
                        'roles': ['owner'],
                        'user@odata.bind': f"https://graph.microsoft.com/v1.0/users('{config['sender_user']}')"
                    },
                    {
                        '@odata.type': '#microsoft.graph.aadUserConversationMember',
                        'roles': ['owner'],
                        'user@odata.bind': f"https://graph.microsoft.com/v1.0/users('{destinatario_email}')"
                    }
                ]
            },
            timeout=15
        )
        chat_response.raise_for_status()
        chat_id = chat_response.json().get('id')

        message_response = requests.post(
            f'https://graph.microsoft.com/v1.0/chats/{chat_id}/messages',
            headers=headers,
            json={
                'body': {
                    'contentType': 'text',
                    'content': f'{titulo}\n\n{mensaje}'.replace('\n', '<br>')
                }
            },
            timeout=15
        )
        message_response.raise_for_status()

        return TeamsNotificationResult(
            success=True,
            status='TEAMS_ENVIADO',
            detail='Mensaje enviado a Microsoft Teams.'
        )

    except Exception as exc:
        return TeamsNotificationResult(
            success=False,
            status='TEAMS_ERROR',
            detail=str(exc)
        )


def enviar_solicitud_camion_no_planificado_teams(destinatario_email, mensaje):
    return enviar_alerta_camion_no_planificado_teams(
        destinatario_email,
        mensaje,
        titulo='\U0001F69B CAMION NO PLANIFICADO'
    )


def enviar_rechazo_camion_no_planificado_teams(destinatario_email, mensaje):
    return enviar_alerta_camion_no_planificado_teams(
        destinatario_email,
        mensaje,
        titulo='\u26D4 CAMION NO PLANIFICADO RECHAZADO'
    )


def enviar_solicitud_camion_patio_no_planificado_teams(
    destinatario_email,
    mensaje,
    hechos,
    documentos,
    revisar_url,
    camion_url
):
    return enviar_alerta_camion_no_planificado_teams(
        destinatario_email,
        mensaje,
        titulo='Camión no planificado pendiente de revisión',
        hechos=hechos,
        documentos=documentos,
        acciones=[
            ('Revisar solicitud', revisar_url),
            ('Ver camion en patio', camion_url),
        ]
    )


def _valor_calidad(valor):
    texto = str(valor or '').strip()
    return texto or '-'


def _datos_resultado_calidad(resultado_calidad):
    citacion = resultado_calidad.CI_NID
    patente = getattr(resultado_calidad.CA_NID, 'CAM_CPATENTE', '')
    if not patente and citacion.CA_NID_id:
        patente = citacion.CA_NID.CAM_CPATENTE

    detalle = getattr(citacion, 'detalle_operacional', None)
    insumo = getattr(detalle, 'CDO_CINSUMO', '') if detalle else ''
    if not insumo:
        item = citacion.citacion_item_set.select_related('IT_NID').order_by('id').first()
        insumo = item.IT_NID.IT_CNOMBRE if item else ''
    if not insumo:
        camion_patio = citacion.camiones_patio.order_by('-CPA_FFECHAASOCIACION', '-id').first()
        if camion_patio:
            patente = patente or camion_patio.CPA_CPATENTE
            insumo = camion_patio.CPA_CINSUMO_DECLARADO_GUIA
    return patente, insumo


def enviar_resultado_calidad_teams(resultado_calidad, evento_integracion):
    base_url = str(getattr(settings, 'APP_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if not base_url:
        return TeamsNotificationResult(
            success=False,
            status='APP_PUBLIC_BASE_URL_NO_CONFIGURADO',
            detail='APP_PUBLIC_BASE_URL no esta configurada para construir enlaces de Teams.',
        )
    if not _teams_webhook_url():
        return TeamsNotificationResult(
            success=False,
            status='TEAMS_WEBHOOK_NO_CONFIGURADO',
            detail='TEAMS_WEBHOOK_URL no esta configurada para el canal de Calidad.',
        )

    citacion = resultado_calidad.CI_NID
    empresa_id = resultado_calidad.EP_NID_id
    patente, insumo = _datos_resultado_calidad(resultado_calidad)
    params_operacion = urlencode({
        'empresa_id': empresa_id,
        '_empresa_id': empresa_id,
        'etapa_codigo': 'ANALISIS_Y_CALIDAD',
    })
    params_trazabilidad = urlencode({
        'empresa_id': empresa_id,
        '_empresa_id': empresa_id,
        'q': resultado_calidad.RCO_CNUMERO_GUIA or '',
    })
    operacion_url = f'{base_url}{reverse("operacion_planta_citacion", args=[citacion.id])}?{params_operacion}'
    trazabilidad_url = f'{base_url}{reverse("trazabilidad_buscar")}?{params_trazabilidad}'
    aprobado = resultado_calidad.RCO_CESTADO == resultado_calidad.Estado.APROBADO
    titulo = 'Resultado de calidad aprobado' if aprobado else 'Resultado de calidad rechazado'
    mensaje = (
        'Los resultados de calidad se encuentran disponibles para continuar con el proceso.'
        if aprobado
        else 'El análisis de calidad fue rechazado. El camión debe salir de planta.'
    )
    fecha = evento_integracion.EIC_FRESULTADO or resultado_calidad.RCO_FACTUALIZACION
    fecha_texto = timezone.localtime(fecha).strftime('%d/%m/%Y %H:%M:%S') if fecha else '-'
    hechos = [
        ('Resultado', resultado_calidad.RCO_CESTADO),
        ('Citacion', f'#{citacion.id}'),
        ('Numero de guia', _valor_calidad(resultado_calidad.RCO_CNUMERO_GUIA)),
        ('Patente', _valor_calidad(patente)),
        ('Insumo', _valor_calidad(insumo)),
        ('Empresa', _valor_calidad(resultado_calidad.EP_NID.EP_CRAZONSOCIAL)),
        ('Origen', _valor_calidad(evento_integracion.EIC_CORIGEN)),
        ('Fecha resultado', fecha_texto),
    ]
    return enviar_alerta_camion_no_planificado_teams(
        '',
        mensaje,
        titulo=titulo,
        hechos=hechos,
        acciones=[
            ('Ver Operacion Planta', operacion_url),
            ('Ver trazabilidad', trazabilidad_url),
        ],
    )
