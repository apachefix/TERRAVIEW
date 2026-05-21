import requests
from django.conf import settings


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


def _crear_payload_webhook(mensaje, titulo='ALERTA CAMION NO PLANIFICADO'):
    if _teams_webhook_mode() == 'text':
        return {'text': f'{titulo}\n\n{mensaje}'}

    return {
        'type': 'message',
        'attachments': [
            {
                'contentType': 'application/vnd.microsoft.card.adaptive',
                'content': {
                    '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
                    'type': 'AdaptiveCard',
                    'version': '1.4',
                    'body': [
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
                }
            }
        ]
    }


def _enviar_por_webhook(mensaje, titulo='ALERTA CAMION NO PLANIFICADO'):
    webhook_url = _teams_webhook_url()

    if not webhook_url:
        return None

    response = None

    try:
        payload = _crear_payload_webhook(mensaje, titulo)
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


def enviar_alerta_camion_no_planificado_teams(destinatario_email, mensaje, titulo='ALERTA CAMION NO PLANIFICADO'):
    resultado_webhook = _enviar_por_webhook(mensaje, titulo)

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
