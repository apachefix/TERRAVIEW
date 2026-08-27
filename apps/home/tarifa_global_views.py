"""Vistas acotadas de Tarifas Globales para CONTROL_FLOTA.
"""

import logging

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import formTARIFA_GLOBAL
from .models import AJUSTE_TARIFA, CONCEPTO_VARIACION_TARIFA, TARIFA_GLOBAL, TARIFA_LOG
from .services.ajuste_tarifas import actualizar_ajustes_vencidos, obtener_ultimo_ajuste
from .services.ict_ine import ICTConsultaError, obtener_acumulativo_ict_6_meses
from .services.tarifa_global_service import (
    configurar_form_tarifa_empresa,
    puede_administrar_tarifas,
    usuario_es_control_flota,
)
from .views import (
    _empresa_control_flota_o_404,
    _objeto_control_flota_o_404,
    validar_perfiles_activos,
)


logger = logging.getLogger(__name__)


def _tiene_acceso(request, permiso_legacy):
    return puede_administrar_tarifas(request.user) or validar_perfiles_activos(
        request.user.id,
        permiso_legacy,
    )


def _rechazar(mensaje="No tiene permisos para acceder a esta sección"):
    return mensaje

def _contexto_variaciones(empresa_id):
    actualizar_ajustes_vencidos(empresa_id)
    conceptos = list(CONCEPTO_VARIACION_TARIFA.objects.filter(EP_NID_id=empresa_id))
    for concepto in conceptos:
        concepto.ultima_aplicacion = AJUSTE_TARIFA.objects.filter(
            EP_NID_id=empresa_id, CVT_NID=concepto
        ).order_by('-AJT_FFECHAAPLICACION', '-id').first()
    ultimo = obtener_ultimo_ajuste(empresa_id)
    return {
        'conceptos_variacion': conceptos,
        'ultimo_ajuste': ultimo,
        'ultimo_ajuste_reversible': bool(ultimo and ultimo.AJT_CESTADO != AJUSTE_TARIFA.ESTADO_REVERSADO),
    }



def listar(request):
    if not _tiene_acceso(request, "tg_listall"):
        messages.error(request, _rechazar())
        return redirect("/")
    empresa_id = _empresa_control_flota_o_404(request)
    tarifas = TARIFA_GLOBAL.objects.filter(
        TAR_BHABILITADO=True,
        EP_NID_id=empresa_id,
    )
    administrar = puede_administrar_tarifas(request.user)
    contexto = {
        "object_list": tarifas,
        "puede_administrar_tarifas": administrar,
        "muestra_panel_ict": usuario_es_control_flota(request.user),
    }
    if contexto['muestra_panel_ict']:
        contexto.update(_contexto_variaciones(empresa_id))
    return render(request, "home/TARIFA/tg_listall.html", contexto)


def listar_inhabilitadas(request):
    if not _tiene_acceso(request, "tg_listall_dis"):
        messages.error(request, _rechazar())
        return redirect("/")
    empresa_id = _empresa_control_flota_o_404(request)
    tarifas = TARIFA_GLOBAL.objects.filter(
        TAR_BHABILITADO=False,
        EP_NID_id=empresa_id,
    )
    return render(request, "home/TARIFA/tg_listall_dis.html", {
        "object_list": tarifas,
        "puede_administrar_tarifas": puede_administrar_tarifas(request.user),
    })


def crear(request):
    if not _tiene_acceso(request, "tg_addone"):
        messages.error(request, _rechazar())
        return redirect("/")
    empresa_id = _empresa_control_flota_o_404(request)

    if request.method == "POST":
        datos = request.POST.copy()
        datos["EP_NID"] = empresa_id
        form = configurar_form_tarifa_empresa(formTARIFA_GLOBAL(datos), empresa_id)
        if form.is_valid():
            tarifa = form.save(commit=False)
            tarifa.EP_NID_id = empresa_id
            tarifa.US_NID = request.user
            tarifa.TAR_BHABILITADO = True
            tarifa.TAR_FFECHAREGISTRO = tarifa.TAR_FFECHAREGISTRO or timezone.now()
            tarifa.save()
            TARIFA_LOG.objects.create(
                TAR_NID=tarifa,
                US_NID=request.user,
                TL_FFECHAREGISTRO=timezone.now(),
                TL_NVALOR=tarifa.TAR_NVALOR,
            )
            messages.success(request, "Tarifa global guardada correctamente")
            return redirect("tg_listall")
        messages.error(request, form.errors)
    else:
        form = configurar_form_tarifa_empresa(formTARIFA_GLOBAL(), empresa_id)

    return render(request, "home/TARIFA/tg_addone.html", {"form": form})


def editar(request, pk):
    if not _tiene_acceso(request, "tg_addone"):
        messages.error(request, _rechazar())
        return redirect("/")
    empresa_id = _empresa_control_flota_o_404(request)
    tarifa = _objeto_control_flota_o_404(request, TARIFA_GLOBAL, pk=pk)
    fecha_registro = tarifa.TAR_FFECHAREGISTRO
    valor_anterior = tarifa.TAR_NVALOR

    if request.method == "POST":
        datos = request.POST.copy()
        datos["EP_NID"] = empresa_id
        form = configurar_form_tarifa_empresa(
            formTARIFA_GLOBAL(datos, instance=tarifa),
            empresa_id,
        )
        if form.is_valid():
            actualizada = form.save(commit=False)
            actualizada.EP_NID_id = empresa_id
            actualizada.TAR_FFECHAREGISTRO = fecha_registro
            actualizada.TAR_FFECHAULTIMAMODIFICACION = timezone.now()
            actualizada.TAR_NVALORPREVIO = valor_anterior
            actualizada.TAR_BHABILITADO = True
            actualizada.MODIFICADO_POR = request.user
            actualizada.save()
            TARIFA_LOG.objects.create(
                TAR_NID=actualizada,
                US_NID=request.user,
                TL_FFECHAREGISTRO=timezone.now(),
                TL_NVALOR=actualizada.TAR_NVALOR,
            )
            messages.success(request, "Tarifa global actualizada correctamente")
            return redirect("tg_listall")
        messages.error(request, form.errors)
    else:
        form = configurar_form_tarifa_empresa(
            formTARIFA_GLOBAL(instance=tarifa),
            empresa_id,
        )
    return render(request, "home/TARIFA/tg_addone.html", {"form": form})


def consultar(request, pk):
    if not _tiene_acceso(request, "tg_listall"):
        messages.error(request, _rechazar("No tiene permisos para consultar tarifas"))
        return redirect("/")
    tarifa = _objeto_control_flota_o_404(request, TARIFA_GLOBAL, pk=pk)
    logs = TARIFA_LOG.objects.filter(TAR_NID=tarifa).select_related("US_NID").order_by(
        "-TL_FFECHAREGISTRO",
        "-id",
    )
    return render(request, "home/TARIFA/tg_listone.html", {
        "tarifa": tarifa,
        "logs": logs,
        "puede_administrar_tarifas": puede_administrar_tarifas(request.user),
    })


def deshabilitar(request, pk):
    if not puede_administrar_tarifas(request.user):
        messages.error(request, "No tiene permisos para deshabilitar tarifas")
        return redirect("/")
    tarifa = _objeto_control_flota_o_404(request, TARIFA_GLOBAL, pk=pk)
    tarifa.TAR_BHABILITADO = False
    tarifa.MODIFICADO_POR = request.user
    tarifa.TAR_FFECHAULTIMAMODIFICACION = timezone.now()
    tarifa.save(update_fields=[
        "TAR_BHABILITADO",
        "MODIFICADO_POR",
        "TAR_FFECHAULTIMAMODIFICACION",
    ])
    messages.success(request, "Tarifa global deshabilitada correctamente")
    return redirect("tg_listall")


def habilitar(request, pk):
    if not puede_administrar_tarifas(request.user):
        messages.error(request, "No tiene permisos para habilitar tarifas")
        return redirect("/")
    tarifa = _objeto_control_flota_o_404(request, TARIFA_GLOBAL, pk=pk)
    tarifa.TAR_BHABILITADO = True
    tarifa.MODIFICADO_POR = request.user
    tarifa.TAR_FFECHAULTIMAMODIFICACION = timezone.now()
    tarifa.save(update_fields=[
        "TAR_BHABILITADO",
        "MODIFICADO_POR",
        "TAR_FFECHAULTIMAMODIFICACION",
    ])
    messages.success(request, "Tarifa global habilitada correctamente")
    return redirect("tg_listall_inhabilitado")


def datos_ajax(request, pk):
    try:
        tarifa = _objeto_control_flota_o_404(request, TARIFA_GLOBAL, pk=pk)
    except Http404:
        return JsonResponse({"valid": False, "msg": "Tarifa no encontrada."}, status=404)
    return JsonResponse({
        "valid": True,
        "tarifa_original": float(tarifa.TAR_NVALOR),
        "tarifa_valor": float(tarifa.TAR_NVALOR),
    })


@require_POST
def consultar_ict(request):
    if not usuario_es_control_flota(request.user):
        return JsonResponse(
            {"valid": False, "msg": "No tiene permisos para consultar ICT."},
            status=403,
        )
    _empresa_control_flota_o_404(request)
    try:
        resultado = obtener_acumulativo_ict_6_meses()
    except ICTConsultaError:
        return JsonResponse({
            "valid": False,
            "msg": "No fue posible obtener los 6 períodos ICT necesarios para calcular el acumulado.",
        }, status=502)
    request.session['ict_acumulado_6_meses_validado'] = resultado.como_dict()
    request.session.modified = True
    return JsonResponse({"valid": True, "ict": resultado.como_dict()})
