# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from apps.home.models import USUARIO_SOCIONEGOCIO
from .forms import LoginForm, SignUpForm


def login_view(request):
    form = LoginForm(request.POST or None)

    msg = None  

    if request.method == "POST":

        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user is not None:

                login(request, user)
                # Verificar si el usuario tiene un objeto USERS_EXTENSION asociado
                if hasattr(request.user, 'userv') and request.user.userv.UX_IS_PROVEEDOR:
                    usuario_socionegocio = USUARIO_SOCIONEGOCIO.objects.get(US_NID_id = request.user.id)
                    return redirect("/pro_listone/" + str(usuario_socionegocio.SN_NID_id))
                else:
                    return redirect("/")
            else:
                messages.warning(request, 'Usuario y/o contraseña invalidos')
                msg = 'Credenciales inválidas'
        else:
            msg = 'Error validando el formulario'

    return render(request, "accounts/login.html", {"form": form, "msg": msg})


def register_user(request):
    msg = None
    success = False

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get("username")
            raw_password = form.cleaned_data.get("password1")
            user = authenticate(username=username, password=raw_password)

            msg = 'User created - please <a href="/login">login</a>.'
            success = True

            # return redirect("/login/")

        else:
            msg = 'Form is not valid'
    else:
        form = SignUpForm()

    return render(request, "accounts/register.html", {"form": form, "msg": msg, "success": success})
