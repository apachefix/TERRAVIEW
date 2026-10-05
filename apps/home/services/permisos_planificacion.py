from apps.home.models import PERFIL_USUARIO, USERS_EMPRESA
from apps.home.vars import ID_TERRAMAR


PERFILES_PLANIFICADOR = {'PLAN', 'PLANIFICADOR'}


def _normalizar(valor):
    return ' '.join(str(valor or '').upper().replace('_', ' ').replace('-', ' ').split())


def usuario_es_planificador_terramar(user, empresa_id):
    """PLAN activo y pertenencia a TERRAMAR CHILE para permisos de planificación."""
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError):
        return False

    if empresa_id != ID_TERRAMAR:
        return False
    if not USERS_EMPRESA.objects.filter(US_NID=user, EP_NID_id=empresa_id).exists():
        return False

    perfiles = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
    )
    return any(
        _normalizar(valor) in PERFILES_PLANIFICADOR
        for perfil in perfiles
        for valor in (perfil.PR_NID.PR_CNOMBRE, perfil.PR_NID.PR_CCODIGO)
    )
