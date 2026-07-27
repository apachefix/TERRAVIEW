from django.utils import timezone
from apps.home.models import NOTIFICACION, USERS_EMPRESA


def usuario_tiene_acceso_notificacion_empresa(user, empresa):
    empresa_id = getattr(empresa, 'pk', empresa)
    if not user or not empresa_id:
        return False
    return USERS_EMPRESA.objects.filter(
        US_NID=user,
        EP_NID_id=empresa_id,
    ).exists()


def crear_notificacion_interna(**datos):
    """Crea una notificacion solo si el receptor pertenece a la empresa del evento."""
    receptor = datos.get('USER_RECEIVER_ID')
    empresa = datos.get('EP_NID')
    if not usuario_tiene_acceso_notificacion_empresa(receptor, empresa):
        return None
    return NOTIFICACION.objects.create(**datos)


def marcar_notificacion_interna_leida(*, notificacion_id, receptor, empresa_id):
    if not usuario_tiene_acceso_notificacion_empresa(receptor, empresa_id):
        return False
    actualizadas = NOTIFICACION.objects.filter(
        id=notificacion_id,
        USER_RECEIVER_ID=receptor,
        EP_NID_id=empresa_id,
        NOT_BHABILITADO=True,
        NOT_BREAD=False,
    ).update(NOT_BREAD=True, NOT_FFECHALEIDO=timezone.now())
    return actualizadas == 1
