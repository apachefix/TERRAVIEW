##########################################################################
#####################  CONTEXTO GLOBAL EMPRESA ACTIVA  ###################
##########################################################################

from .models import EMPRESA, USERS_EMPRESA

EMPRESA_ACTIVA_PARAM = '_empresa_id'


def obtener_empresa_request_id(request):
    empresa_id = request.GET.get(EMPRESA_ACTIVA_PARAM) or request.POST.get(EMPRESA_ACTIVA_PARAM)

    if empresa_id and str(empresa_id).isdigit():
        return int(empresa_id)

    return None


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
            empresa_id = obtener_empresa_request_id(request) or request.session.get('empresa_id')

            if empresa_id:
                tiene_acceso = USERS_EMPRESA.objects.filter(
                    US_NID=request.user,
                    EP_NID_id=empresa_id
                ).exists()

                if tiene_acceso:
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
