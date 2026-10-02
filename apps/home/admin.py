# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from import_export.admin import ExportActionMixin
from .models import *

# Register your models here.

admin.site.site_header = 'Administración'
class Users_Extension_Inline(admin.StackedInline):
    model = USERS_EXTENSION
    can_delete = False
    verbose_name_plural = 'Extension de usuarios'

class CustomizedUserAdmin(UserAdmin,ExportActionMixin,admin.ModelAdmin):
    inlines = (Users_Extension_Inline, )
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'last_login', 'get_administrador_secuencia', 'get_administrador_etapa', 'get_planificador', 'get_recepcionista', 'get_cliente', 'get_proveedor', 'get_operador', 'get_reporte', 'get_proforma')
    def get_administrador_secuencia(self, obj):
        return obj.userv.UX_IS_ADMINISTRADOR_SECUENCIA if hasattr(obj,'userv') else None    
    def get_administrador_etapa(self, obj):
        return obj.userv.UX_IS_ADMINISTRADOR_ETAPA if hasattr(obj,'userv') else None    
    def get_planificador(self, obj):
        return obj.userv.UX_IS_PLANIFICADOR if hasattr(obj,'userv') else None
    def get_recepcionista(self, obj):
        return obj.userv.UX_IS_RECEPCIONISTA if hasattr(obj,'userv') else None
    def get_cliente(self, obj):
        return obj.userv.UX_IS_CLIENTE if hasattr(obj,'userv') else None
    def get_proveedor(self, obj):
        return obj.userv.UX_IS_PROVEEDOR if hasattr(obj,'userv') else None
    def get_operador(self, obj):
        return obj.userv.UX_IS_OPERADOR if hasattr(obj,'userv') else None
    def get_reporte(self, obj):
        return obj.userv.UX_IS_REPORTES if hasattr(obj,'userv') else None
    def get_proforma(self, obj):
        return obj.userv.UX_IS_PROFORMA if hasattr(obj,'userv') else None
    
    get_administrador_secuencia.short_description = 'Administrador secuencia'
    get_administrador_etapa.short_description = 'Administrador etapa'
    get_planificador.short_description = 'Planificador'
    get_recepcionista.short_description = 'Recepcionista'
    get_cliente.short_description = 'Cliente'
    get_proveedor.short_description = 'Proveedor'
    get_operador.short_description = 'Operador'
    get_reporte.short_description = 'Reporte'
    get_proforma.short_description = 'Proforma'

admin.site.unregister(User)
admin.site.register(User, CustomizedUserAdmin)


@admin.register(OPERACION_NEW_JERSEY)
class OperacionNewJerseyAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'EP_NID', 'ONJ_CMODALIDAD', 'ONJ_CESTADO',
        'ONJ_CITEM_CODE', 'ONJ_CPURCHASE_ORDER', 'ONJ_BHABILITADO',
    )
    list_filter = ('EP_NID', 'ONJ_CMODALIDAD', 'ONJ_CESTADO', 'ONJ_BHABILITADO')
    search_fields = ('ONJ_CITEM_CODE', 'ONJ_CPRODUCTO', 'ONJ_CPURCHASE_ORDER')


@admin.register(OPERACION_NEW_JERSEY_PROCESO)
class OperacionNewJerseyProcesoAdmin(admin.ModelAdmin):
    list_display = ('id', 'ONJ_NID', 'ONJP_CTIPO', 'CI_NID', 'ONJP_CESTADO')
    list_filter = ('EP_NID', 'ONJP_CTIPO', 'ONJP_CESTADO')
    search_fields = ('ONJ_NID__id', 'CI_NID__id')
