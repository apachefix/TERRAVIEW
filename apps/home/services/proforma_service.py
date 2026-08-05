from django.db import transaction
from django.utils import timezone

from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_PROFORMA,
    PERFIL_USUARIO,
    PERMISO,
    SYSLOGGER,
    USERS_EMPRESA,
)


PERFIL_PRO_CIT = 'PRO_CIT'
PERMISO_INICIAR_PROFORMA = 'iniciar_proforma'
PERMISO_PROFORMA_CITACIONES = 'proforma_citaciones'


def usuario_tiene_permiso_pro_cit(user, permiso_codigo):
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    perfiles_ids = PERFIL_USUARIO.objects.filter(
        US_NID=user,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
        PR_NID__PR_CCODIGO=PERFIL_PRO_CIT,
    ).values_list('PR_NID_id', flat=True)

    return PERMISO.objects.filter(
        PR_NID_id__in=perfiles_ids,
        PE_BHABILITADO=True,
        VI_NID__VI_BHABILITADO=True,
        VI_NID__VI_CCODIGO=permiso_codigo,
    ).exists()


def usuario_tiene_empresa(user, empresa_id):
    if not user or not getattr(user, 'is_authenticated', False) or not empresa_id:
        return False
    return USERS_EMPRESA.objects.filter(
        US_NID=user,
        EP_NID_id=empresa_id,
    ).exists()


def resolver_transporte_estructurado(citacion):
    camiones = list(
        CAMION_PATIO.objects.filter(
            CI_NID=citacion,
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        ).only('id', 'EP_NID_id', 'transporte_a_cargo')
    )

    if len(camiones) == 0:
        return {
            'es_terramar': False,
            'fuente': 'CAMION_PATIO',
            'codigo': 'SIN_CAMION_PATIO',
            'mensaje': 'La citación no tiene un CAMION_PATIO asociado.',
        }

    if len(camiones) > 1:
        return {
            'es_terramar': False,
            'fuente': 'CAMION_PATIO',
            'codigo': 'MULTIPLES_CAMIONES_PATIO',
            'mensaje': 'La citación tiene múltiples CAMION_PATIO asociados.',
        }

    camion = camiones[0]
    if camion.EP_NID_id != citacion.EP_NID_id:
        return {
            'es_terramar': False,
            'fuente': 'CAMION_PATIO',
            'codigo': 'EMPRESA_INCONSISTENTE',
            'mensaje': 'El CAMION_PATIO asociado pertenece a otra empresa.',
        }

    transporte = str(camion.transporte_a_cargo or '').strip().upper()
    if transporte != 'TERRAMAR':
        codigo = 'TRANSPORTE_CLIENTE' if transporte == 'CLIENTE' else 'TRANSPORTE_INVALIDO'
        return {
            'es_terramar': False,
            'fuente': 'CAMION_PATIO',
            'codigo': codigo,
            'valor': transporte,
            'mensaje': 'El transporte de la citación no está a cargo de Terramar.',
        }

    return {
        'es_terramar': True,
        'fuente': 'CAMION_PATIO',
        'codigo': 'TERRAMAR',
        'valor': transporte,
        'camion_patio_id': camion.id,
        'mensaje': '',
    }


def evaluar_inicio_proforma(citacion, user, permitir_iniciada=False):
    if not usuario_tiene_permiso_pro_cit(user, PERMISO_INICIAR_PROFORMA):
        return {'elegible': False, 'codigo': 'SIN_PERMISO', 'mensaje': 'No tiene permiso para iniciar proformas.'}

    if not usuario_tiene_empresa(user, citacion.EP_NID_id):
        return {'elegible': False, 'codigo': 'SIN_EMPRESA', 'mensaje': 'No tiene acceso a la empresa de la citación.'}

    if citacion.CI_BCONFORME:
        if permitir_iniciada:
            return {'elegible': True, 'codigo': 'YA_INICIADA', 'mensaje': ''}
        return {'elegible': False, 'codigo': 'YA_INICIADA', 'mensaje': 'La proforma de la citación ya fue iniciada.'}

    if citacion.CI_CESTADO != 'TERMINADO':
        return {'elegible': False, 'codigo': 'ESTADO_INVALIDO', 'mensaje': 'La citación debe estar terminada.'}

    if not citacion.CI_BHABILITADO:
        return {'elegible': False, 'codigo': 'CITACION_INHABILITADA', 'mensaje': 'La citación no está habilitada.'}

    if CITACION_PROFORMA.objects.filter(CI_NID=citacion).exists():
        return {
            'elegible': False,
            'codigo': 'ASOCIACION_INCOMPATIBLE',
            'mensaje': 'La citación ya está asociada a una proforma.',
        }

    transporte = resolver_transporte_estructurado(citacion)
    if not transporte['es_terramar']:
        return {
            'elegible': False,
            'codigo': transporte['codigo'],
            'mensaje': transporte['mensaje'],
            'transporte': transporte,
        }

    return {
        'elegible': True,
        'codigo': 'ELEGIBLE',
        'mensaje': '',
        'transporte': transporte,
    }


def iniciar_proforma(citacion_id, user):
    with transaction.atomic():
        citacion = CITACION.objects.select_for_update().get(pk=citacion_id)

        if citacion.CI_BCONFORME:
            if not usuario_tiene_permiso_pro_cit(user, PERMISO_INICIAR_PROFORMA):
                return citacion, {'ok': False, 'codigo': 'SIN_PERMISO', 'mensaje': 'No tiene permiso para iniciar proformas.'}
            if not usuario_tiene_empresa(user, citacion.EP_NID_id):
                return citacion, {'ok': False, 'codigo': 'SIN_EMPRESA', 'mensaje': 'No tiene acceso a la empresa de la citación.'}
            return citacion, {
                'ok': True,
                'codigo': 'YA_INICIADA',
                'mensaje': 'La citación ya estaba habilitada para iniciar su proforma.',
            }

        evaluacion = evaluar_inicio_proforma(citacion, user)
        if not evaluacion['elegible']:
            return citacion, {'ok': False, **evaluacion}

        estado_anterior = citacion.CI_BCONFORME
        citacion.CI_BCONFORME = True
        citacion.save(update_fields=['CI_BCONFORME'])

        SYSLOGGER.objects.create(
            US_NID=user,
            EP_NID=citacion.EP_NID,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='PROFORMA',
            LOG_COPERACION='INICIAR_PROFORMA',
            LOG_CADD1=f'Citacion: {citacion.id}',
            LOG_CADD2='Transporte: TERRAMAR; Fuente: CAMION_PATIO',
            LOG_CDESCRIPCION=(
                'Inicio de proforma exitoso. '
                f'CI_BCONFORME anterior: {estado_anterior}. '
                f'CI_BCONFORME nuevo: {citacion.CI_BCONFORME}. '
                f'Estado citación: {citacion.CI_CESTADO}. '
                'Transporte: TERRAMAR. Fuente: CAMION_PATIO.'
            ),
        )

        return citacion, {
            'ok': True,
            'codigo': 'INICIADA',
            'mensaje': 'Citación habilitada correctamente para iniciar su proforma.',
        }


def _normalizar_transportista_lote(valor):
    return str(valor or '').strip().upper()


def evaluar_lote_inicio_proforma(
    citaciones,
    user,
    empresa_id,
    transportista_esperado,
):
    if not usuario_tiene_permiso_pro_cit(user, PERMISO_INICIAR_PROFORMA):
        return {
            'ok': False,
            'codigo': 'SIN_PERMISO',
            'mensaje': 'No tiene permiso para iniciar proformas.',
        }

    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError):
        return {
            'ok': False,
            'codigo': 'EMPRESA_INVALIDA',
            'mensaje': 'La empresa seleccionada no es válida.',
        }

    if not usuario_tiene_empresa(user, empresa_id):
        return {
            'ok': False,
            'codigo': 'SIN_EMPRESA',
            'mensaje': 'No tiene acceso a la empresa seleccionada.',
        }

    transportista_esperado = _normalizar_transportista_lote(
        transportista_esperado
    )
    if not transportista_esperado or transportista_esperado == 'CLIENTE':
        return {
            'ok': False,
            'codigo': 'TRANSPORTISTA_INVALIDO',
            'mensaje': 'Debe seleccionar un transportista Terramar elegible.',
        }

    if not citaciones:
        return {
            'ok': False,
            'codigo': 'SIN_CITACIONES',
            'mensaje': 'Debe seleccionar al menos una citación.',
        }

    ids = [citacion.pk for citacion in citaciones]
    asociaciones = set(
        CITACION_PROFORMA.objects.filter(
            CI_NID_id__in=ids,
        ).values_list('CI_NID_id', flat=True)
    )
    camiones_por_citacion = {}
    camiones = CAMION_PATIO.objects.filter(
        CI_NID_id__in=ids,
        CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
    ).only(
        'id',
        'CI_NID_id',
        'EP_NID_id',
        'transporte_a_cargo',
        'CPA_CTRANSPORTISTA_DECLARADO',
    )
    for camion in camiones:
        camiones_por_citacion.setdefault(camion.CI_NID_id, []).append(camion)

    estados_inicio = {citacion.CI_BCONFORME for citacion in citaciones}
    if len(estados_inicio) > 1:
        return {
            'ok': False,
            'codigo': 'ESTADOS_MIXTOS',
            'mensaje': 'No se pueden mezclar citaciones iniciadas y pendientes.',
        }

    for citacion in citaciones:
        if citacion.EP_NID_id != empresa_id:
            return {
                'ok': False,
                'codigo': 'EMPRESAS_MIXTAS',
                'mensaje': 'Todas las citaciones deben pertenecer a la misma empresa.',
            }
        if citacion.CI_CESTADO != 'TERMINADO':
            return {
                'ok': False,
                'codigo': 'ESTADO_INVALIDO',
                'mensaje': f'La citación {citacion.pk} no está terminada.',
            }
        if not citacion.CI_BHABILITADO:
            return {
                'ok': False,
                'codigo': 'CITACION_INHABILITADA',
                'mensaje': f'La citación {citacion.pk} está inhabilitada.',
            }
        if citacion.pk in asociaciones:
            return {
                'ok': False,
                'codigo': 'ASOCIACION_INCOMPATIBLE',
                'mensaje': f'La citación {citacion.pk} ya tiene una proforma.',
            }

        camiones_citacion = camiones_por_citacion.get(citacion.pk, [])
        if len(camiones_citacion) != 1:
            return {
                'ok': False,
                'codigo': 'CAMION_PATIO_INVALIDO',
                'mensaje': (
                    f'La citación {citacion.pk} debe tener exactamente un '
                    'CAMION_PATIO asociado.'
                ),
            }
        camion = camiones_citacion[0]
        transportista = _normalizar_transportista_lote(
            camion.CPA_CTRANSPORTISTA_DECLARADO
        )
        if (
            camion.EP_NID_id != empresa_id
            or _normalizar_transportista_lote(camion.transporte_a_cargo)
            != 'TERRAMAR'
            or not transportista
            or transportista == 'CLIENTE'
        ):
            return {
                'ok': False,
                'codigo': 'TRANSPORTE_INVALIDO',
                'mensaje': f'La citación {citacion.pk} no tiene transporte Terramar válido.',
            }
        if transportista != transportista_esperado:
            return {
                'ok': False,
                'codigo': 'TRANSPORTISTAS_MIXTOS',
                'mensaje': 'Todas las citaciones deben compartir el transportista.',
            }

    return {
        'ok': True,
        'codigo': (
            'LOTE_YA_INICIADO' if estados_inicio == {True} else 'LOTE_ELEGIBLE'
        ),
        'mensaje': '',
        'empresa_id': empresa_id,
        'transportista': transportista_esperado,
        'citacion_ids': ids,
    }


def iniciar_lote_proforma(
    citacion_ids,
    user,
    empresa_id,
    transportista_esperado,
):
    from uuid import uuid4

    try:
        ids = sorted({int(citacion_id) for citacion_id in citacion_ids})
    except (TypeError, ValueError):
        return {
            'ok': False,
            'codigo': 'PAYLOAD_INVALIDO',
            'mensaje': 'La selección de citaciones no es válida.',
        }

    if not ids:
        return {
            'ok': False,
            'codigo': 'SIN_CITACIONES',
            'mensaje': 'Debe seleccionar al menos una citación.',
        }
    if len(ids) > 500:
        return {
            'ok': False,
            'codigo': 'LOTE_MUY_GRANDE',
            'mensaje': 'El lote no puede superar 500 citaciones.',
        }

    with transaction.atomic():
        citaciones = list(
            CITACION.objects.select_for_update()
            .filter(pk__in=ids)
            .order_by('pk')
        )
        if len(citaciones) != len(ids):
            return {
                'ok': False,
                'codigo': 'CITACION_INEXISTENTE',
                'mensaje': 'Una o más citaciones seleccionadas no existen.',
            }

        evaluacion = evaluar_lote_inicio_proforma(
            citaciones=citaciones,
            user=user,
            empresa_id=empresa_id,
            transportista_esperado=transportista_esperado,
        )
        if not evaluacion['ok']:
            return evaluacion

        if evaluacion['codigo'] == 'LOTE_YA_INICIADO':
            return {
                **evaluacion,
                'mensaje': 'El lote ya había sido iniciado anteriormente.',
            }

        lote_id = uuid4().hex
        CITACION.objects.filter(pk__in=ids).update(CI_BCONFORME=True)
        momento = timezone.now()
        SYSLOGGER.objects.bulk_create(
            [
                SYSLOGGER(
                    US_NID=user,
                    EP_NID_id=evaluacion['empresa_id'],
                    LOG_FFECHAREGISTRO=momento,
                    LOG_CMODULO='PROFORMA',
                    LOG_COPERACION='INICIAR_PROFORMA_LOTE',
                    LOG_CADD1=(
                        f'Lote: {lote_id}; Citacion: {citacion.pk}'
                    ),
                    LOG_CADD2=(
                        f"Transportista: {evaluacion['transportista']}"
                    ),
                    LOG_CDESCRIPCION=(
                        'Inicio de proforma por lote. '
                        f'Citacion: {citacion.pk}. '
                        'CI_BCONFORME: False -> True. '
                        f"Empresa: {evaluacion['empresa_id']}. "
                        f"Transportista: {evaluacion['transportista']}. "
                        'Transporte: TERRAMAR. Fuente: CAMION_PATIO.'
                    ),
                )
                for citacion in citaciones
            ]
        )

        return {
            'ok': True,
            'codigo': 'LOTE_INICIADO',
            'mensaje': (
                f'{len(ids)} citaciones fueron iniciadas correctamente.'
            ),
            'lote_id': lote_id,
            'empresa_id': evaluacion['empresa_id'],
            'transportista': evaluacion['transportista'],
            'citacion_ids': ids,
        }
