"""Politicas compartidas del modulo de Tarifas Globales."""

from django.db.models import Q

from apps.home.models import EMPRESA, PERFIL_USUARIO, RUTA, SOCIONEGOCIO


def usuario_es_control_flota(user):
    """Reconoce CONTROL_FLOTA exclusivamente mediante un perfil activo."""
    if not getattr(user, "is_authenticated", False):
        return False
    return PERFIL_USUARIO.objects.filter(
        US_NID=user,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
    ).filter(
        Q(PR_NID__PR_CCODIGO__iexact="CONTROL_FLOTA")
        | Q(PR_NID__PR_CCODIGO__iexact="CONTROL FLOTA")
        | Q(PR_NID__PR_CNOMBRE__iexact="CONTROL_FLOTA")
        | Q(PR_NID__PR_CNOMBRE__iexact="CONTROL FLOTA")
    ).exists()


def puede_administrar_tarifas(user):
    return bool(getattr(user, "is_superuser", False) or usuario_es_control_flota(user))


def configurar_form_tarifa_empresa(form, empresa_id):
    """Impide publicar rutas o transportes de una empresa distinta a la activa."""
    form.fields["EP_NID"].queryset = EMPRESA.objects.filter(pk=empresa_id)
    form.fields["RUT_NID"].queryset = RUTA.objects.filter(
        RUT_BHABILITADO=True,
        EP_NID_id=empresa_id,
    )
    form.fields["SN_NID"].queryset = SOCIONEGOCIO.objects.filter(
        SN_BHABILITADO=True,
        EP_NID_id=empresa_id,
        SN_CTIPO="S",
    )
    return form
