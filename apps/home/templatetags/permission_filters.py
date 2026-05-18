from django import template
from apps.home.models import PERFIL_USUARIO, PERMISO, VISTA

register = template.Library()

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