from apps.home.models import PERFIL_USUARIO, USERS_EMPRESA
from apps.home.vars import ID_ACEITES_SBH, ID_TERRAMAR


ALCANCE_PLANIFICACION_COMPLETO = 'COMPLETO'
ALCANCE_PLANIFICACION_DESPACHO = 'DESPACHO'
PERFILES_PLANIFICADOR = {'PLAN', 'PLANIFICADOR'}
PERFILES_ASISTENTE_DESPACHO = {'ASISTENTE DESPACHO'}


def _normalizar(valor):
    return ' '.join(str(valor or '').upper().replace('_', ' ').replace('-', ' ').split())


def _perfiles_activos(user):
    return {
        _normalizar(valor)
        for perfil in PERFIL_USUARIO.objects.select_related('PR_NID').filter(
            US_NID=user,
            PE_BHABILITADO=True,
            PR_NID__PR_BHABILITADO=True,
        )
        for valor in (perfil.PR_NID.PR_CNOMBRE, perfil.PR_NID.PR_CCODIGO)
    }


def alcance_planificacion_por_empresa(user, empresa_id):
    """Alcance que prevalece sobre un rol operativo dentro de Planificaciones."""
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return ''

    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError):
        return ''

    if not USERS_EMPRESA.objects.filter(US_NID=user, EP_NID_id=empresa_id).exists():
        return ''

    perfiles = _perfiles_activos(user)
    if not perfiles.intersection(PERFILES_PLANIFICADOR):
        return ''
    if empresa_id == ID_TERRAMAR:
        return ALCANCE_PLANIFICACION_COMPLETO
    if empresa_id == ID_ACEITES_SBH and perfiles.intersection(PERFILES_ASISTENTE_DESPACHO):
        return ALCANCE_PLANIFICACION_DESPACHO
    return ''


def usuario_prioriza_planificacion_empresa(user, empresa_id):
    return bool(alcance_planificacion_por_empresa(user, empresa_id))


def usuario_es_planificador_terramar(user, empresa_id):
    return alcance_planificacion_por_empresa(user, empresa_id) == ALCANCE_PLANIFICACION_COMPLETO


def usuario_planifica_solo_despacho_sbh(user, empresa_id):
    return alcance_planificacion_por_empresa(user, empresa_id) == ALCANCE_PLANIFICACION_DESPACHO
