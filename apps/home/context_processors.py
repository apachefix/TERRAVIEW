##########################################################################
#####################  CONTEXTO GLOBAL EMPRESA ACTIVA  ###################
##########################################################################

from .models import EMPRESA, USERS_EMPRESA


def empresa_context(request):
    """
    Context processor para dejar disponible la empresa activa
    en todos los templates del sistema.

    Variables disponibles en templates:
    - empresa_activa
    - empresas_usuario
    - total_empresas_usuario
    """

    empresa_activa = None
    empresas_usuario = []
    total_empresas_usuario = 0

    try:
        if request.user.is_authenticated:
            empresa_id = request.session.get('empresa_id')

            if empresa_id:
                empresa_activa = EMPRESA.objects.filter(id=empresa_id).first()

            empresas_usuario = USERS_EMPRESA.objects.filter(
                US_NID=request.user
            ).select_related('EP_NID').order_by('EP_NID_id')

            total_empresas_usuario = empresas_usuario.count()

    except Exception as e:
        print(f'Error empresa_context: {str(e)}')

    return {
        'empresa_activa': empresa_activa,
        'empresas_usuario': empresas_usuario,
        'total_empresas_usuario': total_empresas_usuario
    }