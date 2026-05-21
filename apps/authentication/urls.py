# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.urls import path
from .views import login_view, register_user
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('login/', login_view, name="login"),
    path('register/', login_required(register_user), name="register"),
    path("logout/", login_required(LogoutView.as_view(next_page="/login/")), name="logout")
]
