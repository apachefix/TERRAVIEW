from django import template
from apps.home.models import PERFIL_USUARIO, PERMISO, USERS_EMPRESA, VISTA
from apps.home.services.permisos_planificacion import (
    usuario_es_planificador_terramar,
    usuario_planifica_solo_despacho_sbh,
    usuario_prioriza_planificacion_empresa,
)
from apps.home.services.proforma_service import usuario_tiene_permiso_pro_cit
import unicodedata

register = template.Library()

PERFILES_INGRESO_CAMION = {
    'GUARDIA',
    'GUARDIA PORTERIA',
    'GUA',
    'ASISTENTE DE RECEPCION',
    'ASISTENTE RECEPCION',
    'ASISTENTE C D',
    'ASISTENTE CD',
    'AR',
}

PERFILES_GUARDIA = {
    'GUARDIA',
    'GUA',
    'GUARDIA PORTERIA',
}

PERFILES_ASISTENTE_RECEPCION = {
    'ASISTENTE RECEPCION',
}

PERFILES_ASISTENTE_CD = {
    'ASISTENTE C D',
    'ASISTENTE CD',
}

USUARIOS_ASISTENTE_CD = {
    'ASISTENTE C D',
    'ASISTENTE CD',
}

USUARIOS_GUARDIA_PORTERIA = {
    'GUARDIA PORTERIA',
}

PERFILES_PLANIFICADOR = {
    'PLANIFICADOR',
    'PLAN',
}

PERFILES_OPERACION_PLANTA = {
    'OPERADOR ROMANA',
    'ASISTENTE C D',
    'ASISTENTE CD',
    'ASISTENTE DE RECEPCION',
    'ASISTENTE RECEPCION',
    'CALIDAD',
    'SALA CONTROL',
    'GUARDIA PORTERIA',
    'GUARDIA',
    'GUA',
}


def _normalizar_texto(valor):
    texto = str(valor or '').strip().upper()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return ' '.join(texto.replace('_', ' ').replace('-', ' ').split())


@register.filter(name='es_operador_romana')
def es_operador_romana(user):
    if getattr(user, 'is_superuser', False):
        return False

    username_normalizado = _normalizar_texto(getattr(user, 'username', ''))
    if username_normalizado == 'OPERADOR ROMANA' or username_normalizado.startswith('OPERADOR ROMANA'):
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)
        if nombre == 'OPERADOR ROMANA' or codigo == 'OPERADOR ROMANA':
            return True

    return False


@register.filter(name='es_asistente_despacho_empresa')
def es_asistente_despacho_empresa(user, empresa_id):
    """Asistente de Despacho habilitado y asignado a la empresa activa."""
    if (
        not getattr(user, 'is_authenticated', False)
        or not getattr(user, 'is_active', False)
        or not empresa_id
    ):
        return False
    return bool(
        USERS_EMPRESA.objects.filter(US_NID=user, EP_NID_id=empresa_id).exists()
        and PERFIL_USUARIO.objects.filter(
            US_NID=user,
            PE_BHABILITADO=True,
            PR_NID__PR_CCODIGO__iexact='ASISTENTE_DESPACHO',
            PR_NID__PR_BHABILITADO=True,
        ).exists()
    )


@register.filter(name='es_usuario_maesc')
def es_usuario_maesc(user):
    return _normalizar_texto(getattr(user, 'username', '')) == 'MAESC'

@register.filter(name='has_vista')
def has_vista(user, vista_codigo):
    """
    Verifica si un usuario tiene acceso a una vista específica.
    
    Uso en plantilla: 
    {% if request.user|has_vista:'NOMBRE_VISTA' %}
    """
    # Obtener perfiles activos del usuario
    perfiles_usuario = PERFIL_USUARIO.objects.filter(
        US_NID=user.id, 
        PE_BHABILITADO=True
    ).values_list('PR_NID', flat=True)
    
    if not perfiles_usuario:
        return False
    
    # Buscar la vista por su código
    vista = VISTA.objects.filter(
        VI_CCODIGO=vista_codigo,
        VI_BHABILITADO=True  # Aseguramos que la vista esté habilitada
    ).first()
    
    if not vista:
        return False
    
    # Verificar si existe un permiso habilitado
    return PERMISO.objects.filter(
        PR_NID__in=perfiles_usuario,
        VI_NID=vista.id,
        PE_BHABILITADO=True  # Aseguramos que el permiso esté habilitado
    ).exists()


@register.filter(name='tiene_permiso_pro_cit')
def tiene_permiso_pro_cit(user, permiso_codigo):
    return (
        usuario_tiene_permiso_pro_cit(user, permiso_codigo)
        and USERS_EMPRESA.objects.filter(US_NID=user).exists()
    )


@register.filter(name='has_perfil')
def has_perfil(user, perfiles):
    """
    Verifica si el usuario tiene alguno de los perfiles indicados.
    Acepta nombres o codigos separados por coma.
    """
    perfiles_buscados = {
        _normalizar_texto(perfil)
        for perfil in str(perfiles or '').split(',')
        if str(perfil or '').strip()
    }

    if not perfiles_buscados:
        return False

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in perfiles_buscados or codigo in perfiles_buscados:
            return True

    return False


@register.filter(name='nombre_usuario_visible')
def nombre_usuario_visible(user):
    """Nombre legible para UI, conservando username como respaldo."""
    if not getattr(user, 'is_authenticated', False):
        return ''

    nombre_completo = ' '.join(
        parte.strip()
        for parte in (
            getattr(user, 'first_name', ''),
            getattr(user, 'last_name', ''),
        )
        if parte and parte.strip()
    )
    return nombre_completo or getattr(user, 'username', '')


@register.filter(name='es_proveedor_legacy')
def es_proveedor_legacy(user):
    userv = getattr(user, 'userv', None)
    return bool(userv and getattr(userv, 'UX_IS_PROVEEDOR', False))


@register.filter(name='es_admin_conductor_legacy')
def es_admin_conductor_legacy(user):
    userv = getattr(user, 'userv', None)
    return bool(userv and getattr(userv, 'UX_IS_ADMINISTRADOR_CONDUCTOR', False))


@register.filter(name='es_ingreso_camion')
def es_ingreso_camion(user):
    """
    Perfil operativo que ve planificaciones como ingreso de camion
    y no debe crear/archivar planificaciones.
    """
    if getattr(user, 'is_superuser', False):
        return False

    username_normalizado = _normalizar_texto(getattr(user, 'username', ''))

    if username_normalizado in PERFILES_INGRESO_CAMION:
        return True

    if username_normalizado in USUARIOS_ASISTENTE_CD:
        return True

    if username_normalizado in USUARIOS_GUARDIA_PORTERIA:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_INGRESO_CAMION or codigo in PERFILES_INGRESO_CAMION:
            return True

    return False


@register.filter(name='es_guardia')
def es_guardia(user):
    if getattr(user, 'is_superuser', False):
        return False

    username_normalizado = _normalizar_texto(getattr(user, 'username', ''))

    if username_normalizado in PERFILES_GUARDIA or username_normalizado in USUARIOS_GUARDIA_PORTERIA:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_GUARDIA or codigo in PERFILES_GUARDIA:
            return True

    return False


@register.filter(name='es_guardia_porteria')
def es_guardia_porteria(user):
    if getattr(user, 'is_superuser', False):
        return False

    username_normalizado = _normalizar_texto(getattr(user, 'username', ''))

    if username_normalizado in USUARIOS_GUARDIA_PORTERIA:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in USUARIOS_GUARDIA_PORTERIA or codigo in USUARIOS_GUARDIA_PORTERIA:
            return True

    return False


@register.filter(name='es_asistente_recepcion')
def es_asistente_recepcion(user):
    if getattr(user, 'is_superuser', False):
        return False

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_RECEPCION or codigo in PERFILES_ASISTENTE_RECEPCION:
            return True

    return False


@register.filter(name='es_asistente_recepcion_rbac')
def es_asistente_recepcion_rbac(user):
    """Perfil real de Asistente de Recepcion; no acepta usernames legacy."""
    if not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False):
        return False
    return any(
        _normalizar_texto(valor) in PERFILES_ASISTENTE_RECEPCION
        for perfil_usuario in PERFIL_USUARIO.objects.select_related('PR_NID').filter(
            US_NID=user.id,
            PE_BHABILITADO=True,
            PR_NID__PR_BHABILITADO=True,
        )
        for valor in (
            perfil_usuario.PR_NID.PR_CNOMBRE,
            perfil_usuario.PR_NID.PR_CCODIGO,
        )
    )


@register.filter(name='es_asistente_cd')
def es_asistente_cd(user):
    if getattr(user, 'is_superuser', False):
        return False

    if _normalizar_texto(getattr(user, 'username', '')) in USUARIOS_ASISTENTE_CD:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_CD or codigo in PERFILES_ASISTENTE_CD:
            return True

    return False


@register.filter(name='es_planificador')
def es_planificador(user):
    if getattr(user, 'is_superuser', False):
        return True

    userv = getattr(user, 'userv', None)

    if userv and getattr(userv, 'UX_IS_PLANIFICADOR', False):
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_PLANIFICADOR or codigo in PERFILES_PLANIFICADOR:
            return True

    return False


@register.filter(name='puede_gestionar_planificaciones')
def puede_gestionar_planificaciones(user):
    if es_ingreso_camion(user) or has_perfil(user, 'ASISTENTE_DESPACHO'):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    if es_planificador(user):
        return True

    userv = getattr(user, 'userv', None)

    if not userv:
        return False

    return any([
        getattr(userv, 'UX_IS_PLANIFICADOR', False),
        getattr(userv, 'UX_IS_RECEPCIONISTA', False),
        getattr(userv, 'UX_IS_CLIENTE', False),
        getattr(userv, 'UX_IS_ADMINISTRADOR_SECUENCIA', False),
        getattr(userv, 'UX_IS_OPERADOR', False),
    ])


@register.filter(name='es_planificador_terramar')
def es_planificador_terramar(user, empresa_id):
    return usuario_es_planificador_terramar(user, empresa_id)


@register.filter(name='prioriza_planificacion_empresa')
def prioriza_planificacion_empresa(user, empresa_id):
    return usuario_prioriza_planificacion_empresa(user, empresa_id)


@register.filter(name='planifica_solo_despacho_sbh')
def planifica_solo_despacho_sbh(user, empresa_id):
    return usuario_planifica_solo_despacho_sbh(user, empresa_id)


@register.filter(name='puede_gestionar_planificaciones_empresa')
def puede_gestionar_planificaciones_empresa(user, empresa_id):
    return puede_gestionar_planificaciones(user) or usuario_prioriza_planificacion_empresa(user, empresa_id)

@register.filter(name='es_asistente_despacho_terramar')
def es_asistente_despacho_terramar(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if not USERS_EMPRESA.objects.filter(US_NID=user, EP_NID_id=1).exists():
        return False
    if _normalizar_texto(getattr(user, 'username', '')) == 'ASISTENTE DESPACHO':
        return True
    return any(
        _normalizar_texto(valor) == 'ASISTENTE DESPACHO'
        for perfil in PERFIL_USUARIO.objects.select_related('PR_NID').filter(
            US_NID=user.id,
            PE_BHABILITADO=True,
            PR_NID__PR_BHABILITADO=True,
        )
        for valor in (perfil.PR_NID.PR_CNOMBRE, perfil.PR_NID.PR_CCODIGO)
    )


@register.filter(name='es_operacion_planta')
def es_operacion_planta(user):
    if getattr(user, 'is_superuser', False):
        return True

    if es_operador_romana(user):
        return True

    username_normalizado = _normalizar_texto(getattr(user, 'username', ''))
    if username_normalizado in PERFILES_OPERACION_PLANTA:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = _normalizar_texto(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = _normalizar_texto(perfil_usuario.PR_NID.PR_CCODIGO)
        if nombre in PERFILES_OPERACION_PLANTA or codigo in PERFILES_OPERACION_PLANTA:
            return True

    return False


@register.filter(name='es_seguimiento_operacional')
def es_seguimiento_operacional(user):
    return es_operacion_planta(user)
