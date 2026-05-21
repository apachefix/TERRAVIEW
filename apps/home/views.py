from django import template
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, FileResponse
from django.template import loader
from django.urls import reverse, reverse_lazy
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.dateparse import parse_date
from django.views.generic import FormView
from django.contrib.auth import update_session_auth_hash, authenticate, logout
from django.conf import settings
from django.template.loader import render_to_string
from django.db.models import Q, Subquery, OuterRef, Count
from django.core.cache import cache
from django.db import connection
from django.db.models import Min


from .models import *
from .vars import *
from .forms import *
from .cypher import *
from .general_postgres import *
from .general_hana import *
from .general_sql_server import *
from .general_postgres import QueryParam
from .services.teams_service import (
    enviar_alerta_camion_no_planificado_teams,
    enviar_solicitud_camion_no_planificado_teams,
    enviar_rechazo_camion_no_planificado_teams,
)

from datetime import datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from googletrans import Translator
from PIL import Image

import os
import uuid
import calendar
import json
import openpyxl
import pandas as pd
import requests
import logging
import unicodedata

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


##########################################################################
#####################  PLANIFICACIÓN CREAR  ##########################
##########################################################################
def CREAR_PLANIFICACION_CITACION(request):
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'message': 'Método no permitido.'})

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'})

        usuario = request.user

        citaciones_json = request.POST.get('citaciones_json', '[]')
        es_sobrecupo = request.POST.get('es_sobrecupo', 'No').strip()
        cantidad_sobrecupo_raw = request.POST.get('cantidad_sobrecupo', '0')

        try:
            citaciones_data = json.loads(citaciones_json)
        except Exception:
            return JsonResponse({'success': False, 'message': 'No se pudieron leer las citaciones enviadas.'})

        if not citaciones_data:
            return JsonResponse({'success': False, 'message': 'Debe agregar al menos una citación antes de guardar.'})

        primera_citacion = citaciones_data[0]

        fecha_llegada = primera_citacion.get('fecha_llegada', '').strip()
        tipo_operacion = primera_citacion.get('tipo_operacion', '').strip()

        if not fecha_llegada:
            return JsonResponse({'success': False, 'message': 'Debe ingresar fecha de llegada.'})

        if not tipo_operacion:
            return JsonResponse({'success': False, 'message': 'Debe seleccionar tipo de operación.'})

        cantidad_repetir = len(citaciones_data)
        pl_sobrecupo = True if es_sobrecupo == 'Si' else False
        try:
            cantidad_sobrecupo = int(cantidad_sobrecupo_raw)
        except (TypeError, ValueError):
            cantidad_sobrecupo = 0

        if not pl_sobrecupo:
            cantidad_sobrecupo = 0

        if cantidad_sobrecupo < 0:
            cantidad_sobrecupo = 0

        fecha_llegada_obj = datetime.strptime(fecha_llegada, '%Y-%m-%d')
        fecha_termino_obj = fecha_llegada_obj.replace(hour=23, minute=59, second=0)

        secuencia_id = primera_citacion.get('secuencia_id')
        secuencia = None

        if secuencia_id:
            secuencia = SECUENCIA.objects.filter(
                pk=secuencia_id,
                EP_NID_id=Empresa,
                SE_CTIPO=tipo_operacion.upper(),
                SE_BHABILITADO=True
            ).first()

        if not secuencia:
            secuencia = SECUENCIA.objects.filter(
                EP_NID_id=Empresa,
                SE_CTIPO=tipo_operacion.upper(),
                SE_BHABILITADO=True
            ).first()

        if not secuencia:
            return JsonResponse({
                'success': False,
                'message': f'No existe una secuencia activa para el tipo {tipo_operacion}.'
            })

        calendario = CALENDARIO.objects.filter(
            EP_NID_id=Empresa,
            CA_NDIA=fecha_llegada_obj.day,
            CA_NMES=fecha_llegada_obj.month,
            CA_NANO=fecha_llegada_obj.year,
            CA_BHABILITADO=True
        ).first()

        if not calendario:
            calendario = CALENDARIO.objects.create(
                CA_CNOMBRE=f'ACEITES SBH: {fecha_llegada_obj.day}/{fecha_llegada_obj.month}/{fecha_llegada_obj.year}',
                CA_FHORA_APERTURA=time(0, 0),
                CA_FHORA_CIERRE=time(23, 59),
                CA_NDIA=fecha_llegada_obj.day,
                CA_NMES=fecha_llegada_obj.month,
                CA_NANO=fecha_llegada_obj.year,
                CA_NCANTIDADCUPOS=50,
                CA_BIS_FERIADO=False,
                CA_BHABILITADO=True,
                US_NID=usuario,
                EP_NID_id=Empresa
            )

        planificacion = PLANIFICACION()
        planificacion.US_NID = usuario
        planificacion.EP_NID_id = Empresa
        planificacion.CAL_NID = calendario
        planificacion.PL_FFECHAREGISTRO = timezone.now()
        planificacion.PL_FFECHAINICIO = fecha_llegada_obj
        planificacion.PL_FFECHAFIN = fecha_termino_obj
        planificacion.PL_CTIPOCUPO = tipo_operacion.upper()
        planificacion.PL_NCANTIDADCUPOS = cantidad_repetir
        planificacion.PL_NSOBRECUPO = pl_sobrecupo
        planificacion.PL_NCANTIDADSOBRECUPO = cantidad_sobrecupo
        planificacion.PL_BARCHIVADO = False
        planificacion.save()

        citaciones_creadas = []

        for i, item in enumerate(citaciones_data):
            cliente_codigo = item.get('cliente', '').strip()
            proveedor_codigo = item.get('proveedor', '').strip()
            proveedor_codigo_hidden = item.get('proveedor_codigo', '').strip()
            proveedor_codigo_final = proveedor_codigo_hidden or proveedor_codigo
            secuencia_item_id = item.get('secuencia_id') or secuencia_id
            secuencia_item = secuencia

            if secuencia_item_id:
                secuencia_item = SECUENCIA.objects.filter(
                    pk=secuencia_item_id,
                    EP_NID_id=Empresa,
                    SE_CTIPO=item.get('tipo_operacion', tipo_operacion).upper(),
                    SE_BHABILITADO=True
                ).first() or secuencia

            cliente_sn = SOCIONEGOCIO.objects.filter(
                EP_NID_id=Empresa,
                SN_CCODIGO_SAP=cliente_codigo,
                SN_CTIPO='C',
                SN_BHABILITADO=True
            ).first()

            proveedor_sn = SOCIONEGOCIO.objects.filter(
                EP_NID_id=Empresa,
                SN_CCODIGO_SAP=proveedor_codigo_final,
                SN_CTIPO='S',
                SN_BHABILITADO=True
            ).first()

            comentario = json.dumps(item, ensure_ascii=False)

            citacion = CITACION.objects.create(
                US_NID=usuario,
                EP_NID_id=Empresa,
                PL_NID=planificacion,
                SN_NID=cliente_sn,
                PRO_NID=proveedor_sn,
                SC_NID=secuencia_item,
                CI_FFECHAREGISTRO=timezone.now(),
                CI_FFECHACITACION=fecha_llegada_obj,
                CI_NCUPO=i + 1,
                CI_CTIPO=item.get('tipo_operacion', tipo_operacion),
                CI_CTIPO_FLETE=item.get('tipo_carga', ''),
                CI_CESTADO='Insumo Programado',
                CI_CCOMENTARIO=comentario,
                CI_BHABILITADO=True,
                CI_BARCHIVADO=False,
                CI_BSOBRECUPO=False,
                CI_BAVISADO=False,
                CI_BCONFIRMADO=False,
                CI_BARRIBADO=False,
                CI_BCONFORME=False
            )

            CITACION_ITEM.objects.create(
                CI_NID=citacion,
                EP_NID_id=Empresa,
                IT_NID_id=26
            )

            citaciones_creadas.append(citacion.id)

        return JsonResponse({
            'success': True,
            'message': f'Planificación y {len(citaciones_creadas)} citación(es) creadas correctamente.',
            'planificacion_id': planificacion.id,
            'citaciones': citaciones_creadas
        })

    except Exception as e:
        print('ERROR CREAR_PLANIFICACION_CITACION:', e)

        return JsonResponse({
            'success': False,
            'message': str(e)
        })

def CREAR_CITACION_NO_PLANIFICADA(request, pk):
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'message': 'MÃ©todo no permitido.'})

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'})

        planificacion = PLANIFICACION.objects.get(pk=pk, EP_NID_id=Empresa)
        tipo_operacion = planificacion.PL_CTIPOCUPO
        fecha_llegada = request.POST.get('fecha_llegada', '').strip()
        secuencia_id = request.POST.get('secuencia_id')

        if not fecha_llegada:
            fecha_llegada = planificacion.PL_FFECHAINICIO.strftime('%Y-%m-%d')

        secuencia = SECUENCIA.objects.filter(
            pk=secuencia_id,
            EP_NID_id=Empresa,
            SE_CTIPO=tipo_operacion,
            SE_BHABILITADO=True
        ).first()

        if not secuencia:
            return JsonResponse({
                'success': False,
                'message': f'Debe seleccionar una secuencia activa de tipo {tipo_operacion}.'
            })

        sobrecupos_disponibles = planificacion.PL_NCANTIDADSOBRECUPO or 0

        if sobrecupos_disponibles <= 0:
            return JsonResponse({
                'success': False,
                'message': 'No quedan sobrecupos disponibles para esta planificaciÃ³n.'
            })

        cliente_codigo = request.POST.get('cliente', '').strip()
        proveedor_codigo = request.POST.get('proveedor', '').strip()
        proveedor_codigo_hidden = request.POST.get('proveedor_codigo', '').strip()
        proveedor_codigo_final = proveedor_codigo_hidden or proveedor_codigo

        cliente_sn = SOCIONEGOCIO.objects.filter(
            EP_NID_id=Empresa,
            SN_CCODIGO_SAP=cliente_codigo,
            SN_CTIPO='C',
            SN_BHABILITADO=True
        ).first()

        proveedor_sn = SOCIONEGOCIO.objects.filter(
            EP_NID_id=Empresa,
            SN_CCODIGO_SAP=proveedor_codigo_final,
            SN_CTIPO='S',
            SN_BHABILITADO=True
        ).first()

        fecha_citacion = datetime.strptime(fecha_llegada, '%Y-%m-%d')
        numero_cupo = CITACION.objects.filter(PL_NID=planificacion).count() + 1

        comentario_data = {
            'origen': 'camion_no_planificado',
            'inf_24hrs': request.POST.get('inf_24hrs', ''),
            'codigo': request.POST.get('codigo', ''),
            'insumo': request.POST.get('insumo', ''),
            'pedido': request.POST.get('pedido', ''),
            'sap_opor_id': request.POST.get('sap_opor_id', ''),
            'proveedor_codigo': proveedor_codigo_final,
            'bl': request.POST.get('bl', ''),
            'cantidad_disponible': request.POST.get('cantidad_disponible', ''),
            'docentry': request.POST.get('docentry', ''),
            'productor': request.POST.get('productor', ''),
            'estanque_destino': request.POST.get('estanque_destino', ''),
            'observacion': request.POST.get('observacion', ''),
        }

        citacion = CITACION.objects.create(
            US_NID=request.user,
            EP_NID_id=Empresa,
            PL_NID=planificacion,
            SN_NID=cliente_sn,
            PRO_NID=proveedor_sn,
            SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=fecha_citacion,
            CI_NCUPO=numero_cupo,
            CI_CTIPO=tipo_operacion,
            CI_CTIPO_FLETE=request.POST.get('tipo_carga', ''),
            CI_CESTADO='Insumo Programado',
            CI_CCOMENTARIO=json.dumps(comentario_data, ensure_ascii=False),
            CI_BHABILITADO=True,
            CI_BARCHIVADO=False,
            CI_BSOBRECUPO=True,
            CI_BAVISADO=False,
            CI_BCONFIRMADO=False,
            CI_BARRIBADO=False,
            CI_BCONFORME=False
        )

        CITACION_ITEM.objects.create(
            CI_NID=citacion,
            EP_NID_id=Empresa,
            IT_NID_id=26
        )

        planificacion.PL_NSOBRECUPO = True
        planificacion.PL_NCANTIDADSOBRECUPO = max(sobrecupos_disponibles - 1, 0)
        planificacion.save(update_fields=['PL_NSOBRECUPO', 'PL_NCANTIDADSOBRECUPO'])

        return JsonResponse({
            'success': True,
            'message': 'CamiÃ³n no planificado agregado correctamente.',
            'citacion_id': citacion.id
        })

    except PLANIFICACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'No se encontrÃ³ la planificaciÃ³n.'})
    except Exception as e:
        print('ERROR CREAR_CITACION_NO_PLANIFICADA:', e)
        return JsonResponse({'success': False, 'message': str(e)})


def NOTIFICAR_CAMION_NO_PLANIFICADO_LEGACY(request):
    print("ENTRO A NOTIFICAR_CAMION_NO_PLANIFICADO")
    print(request.POST)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_puede_operar_ingreso_camion(request.user):
        return JsonResponse({
            'success': False,
            'message': 'No tiene permisos para notificar camiones no planificados.'
        }, status=403)

    Empresa = Verificar_empresa(request)

    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    empresa = EMPRESA.objects.filter(pk=Empresa).first()
    planificacion_id = request.POST.get('planificacion_id')
    log_estado = 'ERROR'
    log_detalle = ''

    try:
        planificacion = PLANIFICACION.objects.get(pk=planificacion_id, EP_NID_id=Empresa)
        planificador = User.objects.filter(username__iexact='MAESC', is_active=True).first()

        if not planificador:
            log_detalle = 'No se encontro el usuario MAESC.'
            return JsonResponse({'success': False, 'message': log_detalle}, status=404)

        if not planificador.email:
            log_detalle = 'El usuario MAESC no tiene email configurado.'
            return JsonResponse({'success': False, 'message': log_detalle}, status=400)

        fecha_hora = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')
        empresa_nombre = empresa.EP_CRAZONSOCIAL if empresa else str(Empresa)
        mensaje = (
            '🚛 ALERTA CAMIÓN NO PLANIFICADO\n\n'
            f'Guardia: {request.user.username}\n'
            f'Planificación: {planificacion.id}\n'
            f'Empresa: {empresa_nombre}\n'
            f'Fecha/hora: {fecha_hora}\n\n'
            'Acción requerida por planificación.'
        )

        notificacion = NOTIFICACION.objects.create(
            USER_SENDER_ID=request.user,
            USER_RECEIVER_ID=planificador,
            EP_NID=empresa,
            NOT_CCONTENIDO=mensaje,
            NOT_CURL=f'/pla_listone/{planificacion.id}'
        )

        resultado_teams = enviar_alerta_camion_no_planificado_teams(planificador.email, mensaje)
        log_estado = resultado_teams.status
        log_detalle = resultado_teams.detail

        return JsonResponse({
            'success': True,
            'message': 'Se notifico al planificador',
            'teams_status': resultado_teams.status,
            'teams_sent': resultado_teams.success,
            'notificacion_id': notificacion.id
        })

    except PLANIFICACION.DoesNotExist:
        log_detalle = 'No se encontro la planificacion para la empresa activa.'
        return JsonResponse({'success': False, 'message': log_detalle}, status=404)
    except Exception as e:
        log_detalle = str(e)
        return JsonResponse({'success': False, 'message': log_detalle}, status=500)
    finally:
        try:
            SYSLOGGER.objects.create(
                US_NID=request.user,
                EP_NID=empresa,
                LOG_FFECHAREGISTRO=timezone.now(),
                LOG_CMODULO='PLANIFICACION',
                LOG_COPERACION='NOTIF_NO_PLAN',
                LOG_CDESCRIPCION=f'Intento notificacion camion no planificado: {log_estado} - {log_detalle}'[:1024],
                LOG_CADD1=str(planificacion_id or '')[:128],
                LOG_CADD2='MAESC'
            )
        except Exception as log_error:
            print('ERROR LOG NOTIFICAR_CAMION_NO_PLANIFICADO:', log_error)


def obtener_planificador_camion_no_planificado():
    return User.objects.filter(username__iexact='MAESC', is_active=True).first()


def registrar_log_camion_no_planificado(usuario, empresa, operacion, descripcion, add1='', add2=''):
    try:
        SYSLOGGER.objects.create(
            US_NID=usuario,
            EP_NID=empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='PLANIFICACION',
            LOG_COPERACION=operacion,
            LOG_CDESCRIPCION=descripcion[:1024],
            LOG_CADD1=str(add1 or '')[:128],
            LOG_CADD2=str(add2 or '')[:128]
        )
    except Exception as log_error:
        print('ERROR LOG CAMION_NO_PLANIFICADO:', log_error)


def armar_mensaje_solicitud_camion_no_planificado(request, solicitud, empresa, planificacion):
    fecha_hora = timezone.localtime(solicitud.CNP_FFECHACREACION).strftime('%d/%m/%Y %H:%M:%S')
    empresa_nombre = empresa.EP_CRAZONSOCIAL if empresa else ''
    link_planificacion = request.build_absolute_uri(f'/pla_listone/{planificacion.id}')
    link_guia = request.build_absolute_uri(solicitud.CNP_FARCHIVOGUIA.url) if solicitud.CNP_FARCHIVOGUIA else ''

    return (
        f'Guardia: {solicitud.US_GUARDIA_ID.username}\n'
        f'Cliente: {solicitud.CLI_CNOMBRE}\n'
        f'Insumo: {solicitud.CNP_CINSUMO}\n'
        f'Guia: {solicitud.CNP_CNUMEROGUIA}\n'
        f'Patente: {solicitud.CNP_CPATENTE}\n'
        f'Empresa transporte: {solicitud.CNP_CEMPRESATRANSPORTE}\n'
        f'Observacion: {solicitud.CNP_COBSERVACION or "Sin observacion"}\n'
        f'Empresa: {empresa_nombre}\n'
        f'Planificacion: {planificacion.id}\n'
        f'Fecha/hora: {fecha_hora}\n'
        f'Link interno: {link_planificacion}\n'
        f'Guia escaneada: {link_guia}'
    )


def SOLICITAR_CAMION_NO_PLANIFICADO(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_puede_operar_ingreso_camion(request.user):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para solicitar camiones no planificados.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    empresa = EMPRESA.objects.filter(pk=Empresa).first()
    planificacion_id = request.POST.get('planificacion_id')

    try:
        planificacion = PLANIFICACION.objects.get(pk=planificacion_id, EP_NID_id=Empresa)
        planificador = obtener_planificador_camion_no_planificado()

        if not planificador:
            mensaje_error = 'No se encontro el usuario MAESC.'
            registrar_log_camion_no_planificado(request.user, empresa, 'SOL_NO_PLAN', mensaje_error, planificacion_id)
            return JsonResponse({'success': False, 'message': mensaje_error}, status=404)

        if not planificador.email:
            mensaje_error = 'El usuario MAESC no tiene email configurado.'
            registrar_log_camion_no_planificado(request.user, empresa, 'SOL_NO_PLAN', mensaje_error, planificacion_id)
            return JsonResponse({'success': False, 'message': mensaje_error}, status=400)

        archivo_guia = request.FILES.get('archivo_guia')
        if not archivo_guia:
            return JsonResponse({'success': False, 'message': 'Debe adjuntar la guia escaneada.'}, status=400)

        patente = str(request.POST.get('patente') or '').strip().upper()
        if not patente:
            return JsonResponse({'success': False, 'message': 'Debe ingresar la patente.'}, status=400)

        campos_requeridos = {
            'cliente': str(request.POST.get('cliente') or '').strip(),
            'insumo': str(request.POST.get('insumo') or '').strip(),
            'numero_guia': str(request.POST.get('numero_guia') or '').strip(),
            'empresa_transporte': str(request.POST.get('empresa_transporte') or '').strip(),
        }
        if any(not valor for valor in campos_requeridos.values()):
            return JsonResponse({'success': False, 'message': 'Debe completar cliente, insumo, numero guia y empresa transporte.'}, status=400)

        solicitud_existente = CAMION_NO_PLANIFICADO.objects.filter(
            EP_NID=empresa,
            PL_NID=planificacion,
            CNP_CPATENTE__iexact=patente,
            CNP_CESTADO=CAMION_NO_PLANIFICADO.ESTADO_PENDIENTE
        ).first()

        if solicitud_existente:
            return JsonResponse({
                'success': False,
                'message': f'Ya existe una solicitud pendiente para la patente {patente}.'
            }, status=409)

        cliente_codigo = str(request.POST.get('cliente') or '').strip()
        cliente_nombre = str(request.POST.get('cliente_nombre') or cliente_codigo).strip()

        solicitud = CAMION_NO_PLANIFICADO.objects.create(
            EP_NID=empresa,
            PL_NID=planificacion,
            US_GUARDIA_ID=request.user,
            CLI_CCODIGO=cliente_codigo,
            CLI_CNOMBRE=cliente_nombre,
            CNP_CINSUMO=campos_requeridos['insumo'],
            CNP_CNUMEROGUIA=campos_requeridos['numero_guia'],
            CNP_CPATENTE=patente,
            CNP_CEMPRESATRANSPORTE=campos_requeridos['empresa_transporte'],
            CNP_COBSERVACION=str(request.POST.get('observacion') or '').strip(),
            CNP_FARCHIVOGUIA=archivo_guia,
        )

        mensaje = armar_mensaje_solicitud_camion_no_planificado(request, solicitud, empresa, planificacion)
        notificacion = NOTIFICACION.objects.create(
            USER_SENDER_ID=request.user,
            USER_RECEIVER_ID=planificador,
            EP_NID=empresa,
            NOT_CCONTENIDO=f'Camion no planificado pendiente: patente {solicitud.CNP_CPATENTE}',
            NOT_CURL=f'/pla_listone/{planificacion.id}'
        )

        resultado_teams = enviar_solicitud_camion_no_planificado_teams(planificador.email, mensaje)
        registrar_log_camion_no_planificado(
            request.user,
            empresa,
            'SOL_NO_PLAN',
            f'Solicitud camion no planificado #{solicitud.id}: {resultado_teams.status} - {resultado_teams.detail}',
            planificacion_id,
            solicitud.CNP_CPATENTE
        )

        return JsonResponse({
            'success': True,
            'message': 'Solicitud enviada al planificador',
            'teams_status': resultado_teams.status,
            'teams_sent': resultado_teams.success,
            'solicitud_id': solicitud.id,
            'notificacion_id': notificacion.id
        })

    except PLANIFICACION.DoesNotExist:
        mensaje_error = 'No se encontro la planificacion para la empresa activa.'
        registrar_log_camion_no_planificado(request.user, empresa, 'SOL_NO_PLAN', mensaje_error, planificacion_id)
        return JsonResponse({'success': False, 'message': mensaje_error}, status=404)
    except Exception as e:
        mensaje_error = str(e)
        registrar_log_camion_no_planificado(request.user, empresa, 'SOL_NO_PLAN', mensaje_error, planificacion_id)
        return JsonResponse({'success': False, 'message': mensaje_error}, status=500)


def NOTIFICAR_CAMION_NO_PLANIFICADO(request):
    return SOLICITAR_CAMION_NO_PLANIFICADO(request)


def RECHAZAR_CAMION_NO_PLANIFICADO(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_planificador(request.user):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para rechazar solicitudes.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    empresa = EMPRESA.objects.filter(pk=Empresa).first()
    planificacion_id = request.POST.get('planificacion_id')
    patente = str(request.POST.get('patente') or '').strip().upper()
    observacion = str(request.POST.get('observacion_rechazo') or '').strip()

    if not patente:
        return JsonResponse({'success': False, 'message': 'Debe ingresar la patente.'}, status=400)

    if not observacion:
        return JsonResponse({'success': False, 'message': 'Debe ingresar el motivo u observacion de rechazo.'}, status=400)

    try:
        planificacion = PLANIFICACION.objects.get(pk=planificacion_id, EP_NID_id=Empresa)
        solicitud = CAMION_NO_PLANIFICADO.objects.select_related('US_GUARDIA_ID').filter(
            EP_NID=empresa,
            PL_NID=planificacion,
            CNP_CPATENTE__iexact=patente,
            CNP_CESTADO=CAMION_NO_PLANIFICADO.ESTADO_PENDIENTE
        ).order_by('-CNP_FFECHACREACION').first()

        if not solicitud:
            return JsonResponse({'success': False, 'message': f'No existe solicitud pendiente para la patente {patente}.'}, status=404)

        solicitud.CNP_CESTADO = CAMION_NO_PLANIFICADO.ESTADO_RECHAZADO
        solicitud.US_PLANIFICADOR_ID = request.user
        solicitud.CNP_COBSERVACION_RECHAZO = observacion
        solicitud.CNP_FFECHARESPUESTA = timezone.now()
        solicitud.save(update_fields=[
            'CNP_CESTADO',
            'US_PLANIFICADOR_ID',
            'CNP_COBSERVACION_RECHAZO',
            'CNP_FFECHARESPUESTA',
        ])

        mensaje = (
            f'Planificador: {request.user.username}\n'
            f'Patente: {solicitud.CNP_CPATENTE}\n'
            f'Cliente: {solicitud.CLI_CNOMBRE}\n'
            f'Insumo: {solicitud.CNP_CINSUMO}\n'
            f'Guia: {solicitud.CNP_CNUMEROGUIA}\n'
            f'Motivo/observacion: {observacion}\n'
            f'Guardia notificado: {solicitud.US_GUARDIA_ID.username}\n'
            f'Link interno: {request.build_absolute_uri(f"/pla_listone/{planificacion.id}")}'
        )

        NOTIFICACION.objects.create(
            USER_SENDER_ID=request.user,
            USER_RECEIVER_ID=solicitud.US_GUARDIA_ID,
            EP_NID=empresa,
            NOT_CCONTENIDO=f'Camion no planificado rechazado: patente {solicitud.CNP_CPATENTE}. Motivo: {observacion}',
            NOT_CURL=f'/pla_listone/{planificacion.id}'
        )

        resultado_teams = enviar_rechazo_camion_no_planificado_teams(solicitud.US_GUARDIA_ID.email, mensaje)
        registrar_log_camion_no_planificado(
            request.user,
            empresa,
            'RECH_NO_PLAN',
            f'Rechazo camion no planificado #{solicitud.id}: {resultado_teams.status} - {resultado_teams.detail}',
            planificacion_id,
            solicitud.CNP_CPATENTE
        )

        return JsonResponse({
            'success': True,
            'message': 'Solicitud rechazada y guardia notificado.',
            'solicitud_id': solicitud.id,
            'teams_status': resultado_teams.status,
            'teams_sent': resultado_teams.success
        })

    except PLANIFICACION.DoesNotExist:
        mensaje_error = 'No se encontro la planificacion para la empresa activa.'
        registrar_log_camion_no_planificado(request.user, empresa, 'RECH_NO_PLAN', mensaje_error, planificacion_id, patente)
        return JsonResponse({'success': False, 'message': mensaje_error}, status=404)
    except Exception as e:
        mensaje_error = str(e)
        registrar_log_camion_no_planificado(request.user, empresa, 'RECH_NO_PLAN', mensaje_error, planificacion_id, patente)
        return JsonResponse({'success': False, 'message': mensaje_error}, status=500)


def PLANIFICACION_CITACION_INGRESO_CAMION(request, pk):
    try:
        if not usuario_es_guardia(request.user):
            return JsonResponse({
                'success': False,
                'message': 'No tiene permisos para registrar ingreso de camion.'
            }, status=403)

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({
                'success': False,
                'message': 'Debe seleccionar una empresa.'
            }, status=400)

        citacion = CITACION.objects.select_related(
            'EP_NID',
            'PL_NID',
            'SC_NID',
            'PRO_NID',
            'CON_NID',
            'CA_NID'
        ).get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)

        etapa_actual = citacion.ETAPA_ACTUAL

        if request.method == 'GET':
            campos = obtener_campos_operacion_etapa(citacion, etapa_actual, request.user)
            registrar_log_camion_no_planificado(
                request.user,
                citacion.EP_NID,
                'OPEN_ING_CAMION',
                f'Apertura modal ingreso camion citacion #{citacion.id} etapa {etapa_actual.ET_CCODIGO}',
                citacion.id,
                etapa_actual.ET_CCODIGO
            )

            return JsonResponse({
                'success': True,
                'citacion': {
                    'id': citacion.id,
                    'estado': citacion.CI_CESTADO,
                    'cupo': citacion.CI_NCUPO,
                    'proveedor': citacion.PRO_NID.SN_CRAZONSOCIAL if citacion.PRO_NID else '',
                    'patente': citacion.CA_NID.CAM_CPATENTE if citacion.CA_NID else '',
                    'conductor': f'{citacion.CON_NID.CON_CNOMBRE} {citacion.CON_NID.CON_CAPELLIDO}' if citacion.CON_NID else '',
                },
                'etapa': {
                    'id': etapa_actual.id,
                    'codigo': etapa_actual.ET_CCODIGO,
                    'nombre': etapa_actual.ET_CNOMBRE,
                },
                'campos': campos
            })

        if request.method == 'POST':
            fue_edicion = guardar_operacion_etapa(citacion, request)

            return JsonResponse({
                'success': True,
                'message': 'Ingreso de camion actualizado correctamente.' if fue_edicion else 'Ingreso de camion registrado correctamente.',
                'modo': 'edicion' if fue_edicion else 'creacion'
            })

        return JsonResponse({
            'success': False,
            'message': 'Metodo no permitido.'
        }, status=405)

    except CITACION.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Citacion no encontrada para la empresa activa.'
        }, status=404)
    except Exception as e:
        print('ERROR PLANIFICACION_CITACION_INGRESO_CAMION:', e)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)


def obtener_dato_operacion_por_codigo(citacion, etapa, codigo):
    dato = DATO_OPERACION.objects.filter(
        CI_NID=citacion,
        SC_NID=citacion.SC_NID,
        ET_NID=etapa,
        CAMP_NID__CA_CCODIGO=codigo
    ).select_related('CAMP_NID').order_by('-id').first()

    if dato and dato.DO_CVALOR is not None:
        return str(dato.DO_CVALOR).strip()

    return ''


def validar_ingreso_camion_minimo(citacion, etapa):
    campos_requeridos = [
        ('CI_CNUMERODOCUMENTO', 'Numero guia'),
        ('ING_EMPRESA_TRANSPORTE', 'Empresa transporte'),
        ('ING_NOMBRE_CONDUCTOR', 'Nombre conductor'),
        ('ING_PATENTE', 'Patente'),
    ]

    faltantes = []
    valores = {}

    for codigo, etiqueta in campos_requeridos:
        valor = obtener_dato_operacion_por_codigo(citacion, etapa, codigo)
        if not valor:
            faltantes.append(etiqueta)
        valores[codigo] = valor

    return faltantes, valores


def obtener_usuarios_asistente_recepcion():
    perfiles = PERFIL_USUARIO.objects.select_related('PR_NID', 'US_NID').filter(
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
        US_NID__is_active=True
    )

    usuarios = []
    usuarios_ids = set()

    for perfil_usuario in perfiles:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_RECEPCION or codigo in PERFILES_ASISTENTE_RECEPCION:
            if perfil_usuario.US_NID_id not in usuarios_ids:
                usuarios.append(perfil_usuario.US_NID)
                usuarios_ids.add(perfil_usuario.US_NID_id)

    return usuarios


def obtener_usuarios_asistente_cd():
    perfiles = PERFIL_USUARIO.objects.select_related('PR_NID', 'US_NID').filter(
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
        US_NID__is_active=True
    )

    usuarios = []
    usuarios_ids = set()

    for perfil_usuario in perfiles:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_CD or codigo in PERFILES_ASISTENTE_CD:
            if perfil_usuario.US_NID_id not in usuarios_ids:
                usuarios.append(perfil_usuario.US_NID)
                usuarios_ids.add(perfil_usuario.US_NID_id)

    usuarios_fallback = User.objects.filter(
        username__in=['Asistente_C_D', 'ASISTENTE_C_D', 'Asistente CD', 'ASISTENTE CD'],
        is_active=True
    )
    for usuario in usuarios_fallback:
        if usuario.id not in usuarios_ids:
            usuarios.append(usuario)
            usuarios_ids.add(usuario.id)

    return usuarios


def AVANZAR_INGRESO_CAMION_ASISTENTE(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_guardia(request.user):
        return JsonResponse({'success': False, 'message': 'Solo Guardia puede enviar la citacion al asistente.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related('EP_NID', 'PL_NID', 'SC_NID').get(
            pk=pk,
            EP_NID_id=Empresa,
            CI_BHABILITADO=True
        )
        etapa_actual = citacion.ETAPA_ACTUAL
        detalle_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID,
            ET_NID=etapa_actual,
            SE_BHABILITADO=True
        ).first()

        if detalle_actual and detalle_actual.SE_NPASO > 1:
            return JsonResponse({
                'success': False,
                'message': 'Esta citacion ya fue enviada al Asistente de recepcion.'
            }, status=409)

        faltantes, valores = validar_ingreso_camion_minimo(citacion, etapa_actual)

        if faltantes:
            return JsonResponse({
                'success': False,
                'message': 'Debe completar antes de avanzar: ' + ', '.join(faltantes)
            }, status=400)

        siguiente_etapa = citacion.ETAPA_SIGUIENTE
        if not siguiente_etapa:
            return JsonResponse({'success': False, 'message': 'La citacion no tiene una etapa siguiente configurada.'}, status=400)

        etapa_log_actual, _ = ETAPA_LOG.objects.get_or_create(
            CI_NID=citacion,
            EP_NID=citacion.EP_NID,
            SC_NID=citacion.SC_NID,
            ET_NID=etapa_actual,
            EL_FFECHAFIN=None,
            defaults={'EL_FFECHAINICIO': datetime.now()}
        )
        etapa_log_actual.EL_FFECHAFIN = datetime.now()
        etapa_log_actual.US_FIN_ID = request.user
        etapa_log_actual.EL_CACCION = 'ENVIA_ASISTENTE'
        etapa_log_actual.save(update_fields=['EL_FFECHAFIN', 'US_FIN_ID', 'EL_CACCION'])

        etapa_log_siguiente, _ = ETAPA_LOG.objects.get_or_create(
            CI_NID=citacion,
            EP_NID=citacion.EP_NID,
            SC_NID=citacion.SC_NID,
            ET_NID=siguiente_etapa.ET_NID,
            EL_FFECHAFIN=None,
            defaults={
                'EL_FFECHAINICIO': datetime.now(),
                'US_INICIO_ID': request.user,
                'EL_CACCION': 'ENVIA_ASISTENTE',
            }
        )
        if etapa_log_siguiente.US_INICIO_ID_id is None or etapa_log_siguiente.EL_CACCION != 'ENVIA_ASISTENTE':
            etapa_log_siguiente.US_INICIO_ID = request.user
            etapa_log_siguiente.EL_CACCION = 'ENVIA_ASISTENTE'
            etapa_log_siguiente.save(update_fields=['US_INICIO_ID', 'EL_CACCION'])

        if citacion.CI_CESTADO != CIT_EN_PROCESO:
            citacion.CI_CESTADO = CIT_EN_PROCESO
            citacion.CI_FFECHAINICIO = citacion.CI_FFECHAINICIO or datetime.now()
            citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHAINICIO'])

        fecha_envio = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')
        mensaje = (
            f'Nuevo camion pendiente de aprobacion/revision.\n'
            f'Citacion: {citacion.id}\n'
            f'Patente: {valores.get("ING_PATENTE", "")}\n'
            f'Conductor: {valores.get("ING_NOMBRE_CONDUCTOR", "")}\n'
            f'Empresa transporte: {valores.get("ING_EMPRESA_TRANSPORTE", "")}\n'
            f'Fecha/hora envio: {fecha_envio}\n'
            f'Guardia: {request.user.username}'
        )

        asistentes = obtener_usuarios_asistente_recepcion()
        for asistente in asistentes:
            NOTIFICACION.objects.create(
                USER_SENDER_ID=request.user,
                USER_RECEIVER_ID=asistente,
                EP_NID=citacion.EP_NID,
                NOT_CCONTENIDO=mensaje,
                NOT_CURL=f'/pla_listone/{citacion.PL_NID_id}'
            )

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'AVANZA_AR',
            f'Citacion #{citacion.id} enviada a asistente desde etapa {etapa_actual.ET_CCODIGO} a {siguiente_etapa.ET_NID.ET_CCODIGO}. Notificados: {len(asistentes)}',
            citacion.id,
            valores.get('ING_PATENTE', '')
        )

        return JsonResponse({
            'success': True,
            'message': 'Citacion enviada al asistente de recepcion.',
            'notificados': len(asistentes),
            'siguiente_etapa': siguiente_etapa.ET_NID.ET_CCODIGO
        })

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada para la empresa activa.'}, status=404)
    except Exception as e:
        print('ERROR AVANZAR_INGRESO_CAMION_ASISTENTE:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def valor_no_registrado(valor):
    if valor is None or str(valor).strip() == '':
        return 'No registrado'
    return str(valor).strip()


ESTANQUES_POR_ALMACEN = {
    'PROSESA': [
        'PROSE_G2',
        'PROSE_T3',
        'PROSE_T4',
        'PROSE_T5',
        'PROSEG10',
    ],
    'SBH': [
        'PATIO_LF',
        'TK01',
        'TK02',
        'TK03',
        'TK04',
        'TK05',
        'TK06',
        'TK07',
        'TK08',
        'TK09',
        'TK10',
        'TK11',
        'TK12',
        'TK13',
        'TK14',
        'TK15',
        'TK16',
        'TK17',
        'TKMX01',
        'TKMX02',
        'TKMX03',
        'TKMX04',
        'Trasvasije',
    ],
}


def normalizar_almacen_planificacion(valor):
    almacen = normalizar_nombre_perfil(valor)
    if almacen.startswith('PROSESA') or almacen.startswith('PROSE'):
        return 'PROSESA'
    if almacen.startswith('SBH'):
        return 'SBH'
    return ''


def obtener_almacen_planificacion(citacion):
    comentario = obtener_comentario_json_citacion(citacion)
    return normalizar_almacen_planificacion(
        comentario.get('estanque_destino')
        or comentario.get('almacen')
        or comentario.get('almacén')
        or comentario.get('bodega')
        or ''
    )


def obtener_campo_estanque_operacional(citacion, usuario):
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID=citacion.EP_NID,
        CA_CCODIGO='ETA3_ESTANQUE',
        defaults={
            'US_NID': usuario,
            'CA_CTIPO': 'LISTA',
            'CA_CETIQUETA': 'Estanque',
            'CA_CPLACEMARK': 'Seleccione estanque',
            'CA_BOBLIGATORIO': True,
            'CA_BHABILITADO': True,
            'CA_BASIGNARVALOR': False,
        }
    )

    cambios = []
    if not campo.CA_BHABILITADO:
        campo.CA_BHABILITADO = True
        cambios.append('CA_BHABILITADO')
    if campo.CA_CTIPO != 'LISTA':
        campo.CA_CTIPO = 'LISTA'
        cambios.append('CA_CTIPO')
    if not campo.CA_BOBLIGATORIO:
        campo.CA_BOBLIGATORIO = True
        cambios.append('CA_BOBLIGATORIO')
    if cambios:
        campo.save(update_fields=cambios)

    return campo


def obtener_dato_estanque_operacional(citacion):
    return DATO_OPERACION.objects.filter(
        CI_NID=citacion,
        SC_NID=citacion.SC_NID,
        CAMP_NID__CA_CCODIGO='ETA3_ESTANQUE'
    ).select_related('US_NID', 'ET_NID').order_by('-id').first()


def obtener_comentario_json_citacion(citacion):
    if not citacion.CI_CCOMENTARIO:
        return {}
    try:
        data = json.loads(citacion.CI_CCOMENTARIO)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def obtener_datos_operacion_citacion(citacion):
    datos = {}
    documentos = []

    registros = DATO_OPERACION.objects.filter(
        CI_NID=citacion,
        SC_NID=citacion.SC_NID
    ).select_related('CAMP_NID', 'ET_NID').order_by('ET_NID_id', 'CAMP_NID_id', '-id')

    for dato in registros:
        campo = dato.CAMP_NID
        codigo = campo.CA_CCODIGO or f'CAMPO_{campo.id}'
        if codigo not in datos:
            datos[codigo] = dato

        if campo.CA_CTIPO.lower() == 'archivo':
            documentos.append({
                'label': campo.CA_CETIQUETA or codigo,
                'etapa': dato.ET_NID.ET_CNOMBRE if dato.ET_NID else '',
                'valor': dato.DO_CVALOR,
                'download_url': reverse('cit_download_file', args=[dato.id]) if dato.DO_CVALOR else '',
            })

    return datos, documentos


def obtener_guardias_relacionados_citacion(citacion):
    guardias = []
    guardias_ids = set()

    for dato in DATO_OPERACION.objects.filter(CI_NID=citacion, SC_NID=citacion.SC_NID).select_related('US_NID'):
        if dato.US_NID and usuario_es_guardia(dato.US_NID) and dato.US_NID_id not in guardias_ids:
            guardias.append(dato.US_NID)
            guardias_ids.add(dato.US_NID_id)

    if guardias:
        return guardias

    perfiles = PERFIL_USUARIO.objects.select_related('PR_NID', 'US_NID').filter(
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True,
        US_NID__is_active=True
    )

    for perfil_usuario in perfiles:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)
        if nombre in PERFILES_GUARDIA or codigo in PERFILES_GUARDIA:
            if perfil_usuario.US_NID_id not in guardias_ids:
                guardias.append(perfil_usuario.US_NID)
                guardias_ids.add(perfil_usuario.US_NID_id)

    return guardias


def avanzar_citacion_a_siguiente_etapa(citacion, usuario=None, accion='AVANZA_ETAPA', observacion=''):
    etapa_actual = citacion.ETAPA_ACTUAL
    siguiente_etapa = citacion.ETAPA_SIGUIENTE

    etapa_log_actual, _ = ETAPA_LOG.objects.get_or_create(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=etapa_actual,
        EL_FFECHAFIN=None,
        defaults={'EL_FFECHAINICIO': datetime.now()}
    )
    etapa_log_actual.EL_FFECHAFIN = datetime.now()
    etapa_log_actual.US_FIN_ID = usuario
    etapa_log_actual.EL_CACCION = accion
    etapa_log_actual.EL_COBSERVACION = observacion
    etapa_log_actual.save(update_fields=['EL_FFECHAFIN', 'US_FIN_ID', 'EL_CACCION', 'EL_COBSERVACION'])

    if not siguiente_etapa:
        citacion.CI_FFECHATERMINO = datetime.now()
        citacion.CI_CESTADO = CIT_TERMINADO
        citacion.save(update_fields=['CI_FFECHATERMINO', 'CI_CESTADO'])
        return etapa_actual, None

    etapa_log_siguiente, _ = ETAPA_LOG.objects.get_or_create(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=siguiente_etapa.ET_NID,
        EL_FFECHAFIN=None,
        defaults={
            'EL_FFECHAINICIO': datetime.now(),
            'US_INICIO_ID': usuario,
            'EL_CACCION': accion,
            'EL_COBSERVACION': observacion,
        }
    )
    if etapa_log_siguiente.US_INICIO_ID_id is None or etapa_log_siguiente.EL_CACCION != accion:
        etapa_log_siguiente.US_INICIO_ID = usuario
        etapa_log_siguiente.EL_CACCION = accion
        etapa_log_siguiente.EL_COBSERVACION = observacion
        etapa_log_siguiente.save(update_fields=['US_INICIO_ID', 'EL_CACCION', 'EL_COBSERVACION'])

    if citacion.CI_CESTADO != CIT_EN_PROCESO:
        citacion.CI_CESTADO = CIT_EN_PROCESO
        citacion.CI_FFECHAINICIO = citacion.CI_FFECHAINICIO or datetime.now()
        citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHAINICIO'])

    return etapa_actual, siguiente_etapa.ET_NID


def devolver_citacion_a_etapa_guardia(citacion, usuario=None, observacion=''):
    etapa_actual = citacion.ETAPA_ACTUAL
    detalle_guardia = DETALLE_SECUENCIA.objects.filter(
        SC_NID=citacion.SC_NID,
        SE_BHABILITADO=True
    ).order_by('SE_NPASO').first()

    if not detalle_guardia:
        raise Exception('No existe etapa inicial configurada para la secuencia.')

    ETAPA_LOG.objects.filter(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=etapa_actual,
        EL_FFECHAFIN=None
    ).update(
        EL_FFECHAFIN=datetime.now(),
        US_FIN_ID=usuario,
        EL_CACCION='DEVUELVE_GUARDIA',
        EL_COBSERVACION=observacion
    )

    ETAPA_LOG.objects.create(
        CI_NID=citacion,
        EP_NID=citacion.EP_NID,
        SC_NID=citacion.SC_NID,
        ET_NID=detalle_guardia.ET_NID,
        EL_FFECHAINICIO=datetime.now(),
        US_INICIO_ID=usuario,
        EL_CACCION='DEVUELVE_GUARDIA',
        EL_COBSERVACION=observacion
    )

    return etapa_actual, detalle_guardia.ET_NID


def PLANIFICACION_CITACION_REVISION_ASISTENTE(request, pk):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_asistente_recepcion(request.user) and not usuario_es_guardia(request.user):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para revisar camiones.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related(
            'EP_NID', 'PL_NID', 'SC_NID', 'PRO_NID', 'SN_NID', 'CON_NID', 'CA_NID'
        ).get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)

        citacion_item = CITACION_ITEM.objects.filter(CI_NID=citacion).select_related('IT_NID').first()
        comentario = obtener_comentario_json_citacion(citacion)
        datos_operacion, documentos = obtener_datos_operacion_citacion(citacion)

        def dato(codigo):
            registro = datos_operacion.get(codigo)
            return registro.DO_CVALOR if registro else ''

        bl = dato('ING_BL') or obtener_bl_inicial_citacion(citacion) or comentario.get('bl', '')
        detalle_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            SE_BHABILITADO=True
        ).first()
        etapa_abierta = ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            EL_FFECHAFIN=None
        ).exists()
        aprobado_asistente = citacion.CI_CESTADO == CIT_TERMINADO or not etapa_abierta or bool(detalle_actual and detalle_actual.SE_NPASO > 2)

        payload = {
            'success': True,
            'citacion_id': citacion.id,
            'aprobado_asistente': aprobado_asistente,
            'planificacion': {
                'Numero planificacion': citacion.PL_NID_id,
                'Fecha planificacion': citacion.PL_NID.PL_FFECHAINICIO.strftime('%d/%m/%Y %H:%M') if citacion.PL_NID and citacion.PL_NID.PL_FFECHAINICIO else '',
                'Cliente': citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else comentario.get('cliente_nombre', ''),
                'Proveedor': citacion.PRO_NID.SN_CRAZONSOCIAL if citacion.PRO_NID else '',
                'Insumo': citacion_item.IT_NID.IT_CNOMBRE if citacion_item and citacion_item.IT_NID else comentario.get('insumo', ''),
                'Pedido': comentario.get('pedido', ''),
                'BL': bl,
                'Tipo planificacion': citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID else '',
                'Empresa': citacion.EP_NID.EP_CRAZONSOCIAL if citacion.EP_NID else '',
                'DocEntry SAP': comentario.get('docentry', ''),
                'Productor': comentario.get('productor', ''),
                'Estanque destino': comentario.get('estanque_destino', ''),
            },
            'citacion': {
                'Numero citacion': citacion.id,
                'Fecha citacion': citacion.CI_FFECHACITACION.strftime('%d/%m/%Y %H:%M') if citacion.CI_FFECHACITACION else '',
                'Tipo documento': citacion.CI_CTIPODOCUMENTO,
                'Numero documento': citacion.CI_CNUMERODOCUMENTO,
                'Etapa actual': citacion.ETAPA_ACTUAL.ET_CNOMBRE if citacion.ETAPA_ACTUAL else '',
                'Secuencia actual': citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else '',
                'Estado': citacion.CI_CESTADO,
                'Tipo flujo': citacion.CI_CTIPO,
                'Empresa asociada': citacion.EP_NID.EP_CRAZONSOCIAL if citacion.EP_NID else '',
            },
            'guardia': {
                'Numero guia': dato('CI_CNUMERODOCUMENTO') or citacion.CI_CNUMERODOCUMENTO,
                'BL': bl,
                'Empresa transporte': dato('ING_EMPRESA_TRANSPORTE'),
                'Nombre conductor': dato('ING_NOMBRE_CONDUCTOR'),
                'Patente': dato('ING_PATENTE'),
                'Telefono conductor': dato('ING_TELEFONO_CONDUCTOR'),
                'Lote-contenedor': dato('ING_LOTE_CONTENEDOR'),
                'Observacion': dato('ING_OBSERVACION') or comentario.get('observacion', ''),
            },
            'documentos': documentos,
        }

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'REV_AR_OPEN',
            f'Apertura revision asistente citacion #{citacion.id}',
            citacion.id,
            citacion.ETAPA_ACTUAL.ET_CCODIGO if citacion.ETAPA_ACTUAL else ''
        )

        return JsonResponse(payload)

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada.'}, status=404)
    except Exception as e:
        print('ERROR PLANIFICACION_CITACION_REVISION_ASISTENTE:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def APROBAR_CAMION_ASISTENTE(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_asistente_recepcion(request.user):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para aprobar camiones.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related('EP_NID', 'SC_NID').get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)
        detalle_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            SE_BHABILITADO=True
        ).first()
        etapa_abierta = ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            EL_FFECHAFIN=None
        ).exists()

        if citacion.CI_CESTADO == CIT_TERMINADO or not etapa_abierta or (detalle_actual and detalle_actual.SE_NPASO > 2):
            return JsonResponse({
                'success': False,
                'message': 'Esta citacion ya fue aprobada por Asistente de recepcion.'
            }, status=409)

        etapa_origen, etapa_destino = avanzar_citacion_a_siguiente_etapa(
            citacion,
            usuario=request.user,
            accion='APRUEBA_ASISTENTE'
        )

        datos_operacion, _ = obtener_datos_operacion_citacion(citacion)

        def valor_operacion(codigo):
            dato = datos_operacion.get(codigo)
            return dato.DO_CVALOR if dato else ''

        almacen = obtener_almacen_planificacion(citacion)
        fecha_aprobacion = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')
        mensaje_cd = (
            'Citacion aprobada por Asistente de recepcion y pendiente de asignacion de estanque.\n'
            f'Citacion: {citacion.id}\n'
            f'Patente: {valor_operacion("ING_PATENTE")}\n'
            f'Conductor: {valor_operacion("ING_NOMBRE_CONDUCTOR")}\n'
            f'Empresa transporte: {valor_operacion("ING_EMPRESA_TRANSPORTE")}\n'
            f'Almacen: {almacen or "No registrado"}\n'
            f'Fecha/hora aprobacion: {fecha_aprobacion}\n'
            f'Asistente recepcion: {request.user.username}'
        )
        asistentes_cd = obtener_usuarios_asistente_cd()
        for asistente_cd in asistentes_cd:
            NOTIFICACION.objects.create(
                USER_SENDER_ID=request.user,
                USER_RECEIVER_ID=asistente_cd,
                EP_NID=citacion.EP_NID,
                NOT_CCONTENIDO=mensaje_cd,
                NOT_CURL=f'/pla_listone/{citacion.PL_NID_id}'
            )

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'APRUEBA_AR',
            f'Asistente aprueba citacion #{citacion.id} desde {etapa_origen.ET_CCODIGO} a {etapa_destino.ET_CCODIGO if etapa_destino else "FIN"}. Notificados Asistente_C_D: {len(asistentes_cd)}',
            citacion.id,
            etapa_destino.ET_CCODIGO if etapa_destino else 'FIN'
        )

        return JsonResponse({'success': True, 'message': 'Camion aprobado correctamente.', 'notificados_cd': len(asistentes_cd)})

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada.'}, status=404)
    except Exception as e:
        print('ERROR APROBAR_CAMION_ASISTENTE:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def DEVOLVER_CAMION_GUARDIA(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_asistente_recepcion(request.user):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para devolver camiones.'}, status=403)

    observacion = str(request.POST.get('observacion') or '').strip()
    if not observacion:
        return JsonResponse({'success': False, 'message': 'Debe ingresar una observacion para devolver a Guardia.'}, status=400)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related('EP_NID', 'SC_NID', 'PL_NID').get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)
        etapa_origen, etapa_destino = devolver_citacion_a_etapa_guardia(
            citacion,
            usuario=request.user,
            observacion=observacion
        )
        guardias = obtener_guardias_relacionados_citacion(citacion)

        mensaje = (
            f'Camion devuelto por Asistente de recepcion.\n'
            f'Citacion: {citacion.id}\n'
            f'Observacion: {observacion}\n'
            f'Asistente: {request.user.username}'
        )

        for guardia in guardias:
            NOTIFICACION.objects.create(
                USER_SENDER_ID=request.user,
                USER_RECEIVER_ID=guardia,
                EP_NID=citacion.EP_NID,
                NOT_CCONTENIDO=mensaje,
                NOT_CURL=f'/pla_listone/{citacion.PL_NID_id}'
            )

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'DEV_AR_GUA',
            f'Asistente devuelve citacion #{citacion.id} desde {etapa_origen.ET_CCODIGO} a {etapa_destino.ET_CCODIGO}. Observacion: {observacion}',
            citacion.id,
            etapa_destino.ET_CCODIGO
        )

        return JsonResponse({'success': True, 'message': 'Camion devuelto a Guardia.', 'notificados': len(guardias)})

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada.'}, status=404)
    except Exception as e:
        print('ERROR DEVOLVER_CAMION_GUARDIA:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def PLANIFICACION_CITACION_ESTANQUE(request, pk):
    if request.method not in ['GET', 'POST']:
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_asistente_cd(request.user) and not getattr(request.user, 'is_superuser', False):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para asignar estanque.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related(
            'EP_NID', 'PL_NID', 'SC_NID', 'PRO_NID', 'SN_NID', 'CON_NID', 'CA_NID'
        ).get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)

        detalle_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            SE_BHABILITADO=True
        ).first()
        if not detalle_actual or detalle_actual.SE_NPASO <= 2:
            return JsonResponse({'success': False, 'message': 'La citacion aun no fue aprobada por recepcion.'}, status=400)

        enviado_siguiente = citacion.CI_CESTADO == CIT_TERMINADO or detalle_actual.SE_NPASO > 3 or SYSLOGGER.objects.filter(
            LOG_COPERACION='ENVIA_CD_NEXT',
            LOG_CADD1=str(citacion.id)
        ).exists()

        almacen = obtener_almacen_planificacion(citacion)
        opciones_estanque = ESTANQUES_POR_ALMACEN.get(almacen, [])
        dato_estanque = obtener_dato_estanque_operacional(citacion)

        if request.method == 'POST':
            if enviado_siguiente:
                return JsonResponse({'success': False, 'message': 'Esta citacion ya fue enviada a la siguiente etapa.'}, status=409)

            if not almacen:
                return JsonResponse({'success': False, 'message': 'No existe almacen definido en planificacion.'}, status=400)

            estanque = str(request.POST.get('estanque') or '').strip()
            if not estanque:
                return JsonResponse({'success': False, 'message': 'Debe seleccionar estanque.'}, status=400)

            if estanque not in opciones_estanque:
                return JsonResponse({'success': False, 'message': 'El estanque seleccionado no corresponde al almacen definido.'}, status=400)

            campo_estanque = obtener_campo_estanque_operacional(citacion, request.user)
            DATO_OPERACION.objects.update_or_create(
                CI_NID=citacion,
                SC_NID=citacion.SC_NID,
                ET_NID=citacion.ETAPA_ACTUAL,
                CAMP_NID=campo_estanque,
                defaults={
                    'EP_NID': citacion.EP_NID,
                    'US_NID': request.user,
                    'DO_CVALOR': estanque,
                    'DO_FFECHAREGISTRO': datetime.now(),
                }
            )

            registrar_log_camion_no_planificado(
                request.user,
                citacion.EP_NID,
                'ESTANQUE_CD',
                f'Asistente_C_D guarda estanque {estanque} para citacion #{citacion.id}',
                citacion.id,
                estanque
            )

            return JsonResponse({'success': True, 'message': 'Estanque guardado correctamente.', 'estanque': estanque})

        citacion_item = CITACION_ITEM.objects.filter(CI_NID=citacion).select_related('IT_NID').first()
        comentario = obtener_comentario_json_citacion(citacion)
        datos_operacion, documentos = obtener_datos_operacion_citacion(citacion)
        log_aprobacion = SYSLOGGER.objects.select_related('US_NID').filter(
            LOG_COPERACION='APRUEBA_AR',
            LOG_CADD1=str(citacion.id)
        ).order_by('-LOG_FFECHAREGISTRO').first()

        def dato(codigo):
            registro = datos_operacion.get(codigo)
            return registro.DO_CVALOR if registro else ''

        bl = dato('ING_BL') or obtener_bl_inicial_citacion(citacion) or comentario.get('bl', '')
        payload = {
            'success': True,
            'citacion_id': citacion.id,
            'almacen': almacen,
            'opciones_estanque': opciones_estanque,
            'estanque_actual': dato_estanque.DO_CVALOR if dato_estanque else '',
            'enviado_siguiente': enviado_siguiente,
            'puede_editar': not enviado_siguiente and bool(almacen),
            'mensaje_bloqueo': '' if almacen else 'No existe almacen definido en planificacion',
            'planificacion': {
                'Planificacion': citacion.PL_NID_id,
                'Fecha planificacion': citacion.PL_NID.PL_FFECHAINICIO.strftime('%d/%m/%Y %H:%M') if citacion.PL_NID and citacion.PL_NID.PL_FFECHAINICIO else '',
                'Cliente': citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else comentario.get('cliente_nombre', ''),
                'Proveedor': citacion.PRO_NID.SN_CRAZONSOCIAL if citacion.PRO_NID else '',
                'Insumo': citacion_item.IT_NID.IT_CNOMBRE if citacion_item and citacion_item.IT_NID else comentario.get('insumo', ''),
                'Almacen definido': almacen,
                'Tipo planificacion': citacion.PL_NID.PL_CTIPOCUPO if citacion.PL_NID else '',
                'Fecha inicio': citacion.PL_NID.PL_FFECHAINICIO.strftime('%d/%m/%Y %H:%M') if citacion.PL_NID and citacion.PL_NID.PL_FFECHAINICIO else '',
                'Fecha termino': citacion.PL_NID.PL_FFECHAFIN.strftime('%d/%m/%Y %H:%M') if citacion.PL_NID and citacion.PL_NID.PL_FFECHAFIN else '',
            },
            'citacion': {
                'Numero citacion': citacion.id,
                'Estado': citacion.CI_CESTADO,
                'Etapa actual': citacion.ETAPA_ACTUAL.ET_CNOMBRE if citacion.ETAPA_ACTUAL else '',
                'Secuencia actual': citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else '',
                'Empresa': citacion.EP_NID.EP_CRAZONSOCIAL if citacion.EP_NID else '',
            },
            'guardia': {
                'Guia': dato('CI_CNUMERODOCUMENTO') or citacion.CI_CNUMERODOCUMENTO,
                'BL': bl,
                'Conductor': dato('ING_NOMBRE_CONDUCTOR'),
                'Patente': dato('ING_PATENTE'),
                'Empresa transporte': dato('ING_EMPRESA_TRANSPORTE'),
                'Telefono': dato('ING_TELEFONO_CONDUCTOR'),
                'Lote-contenedor': dato('ING_LOTE_CONTENEDOR'),
                'Documentos': 'Ver seccion documentos',
            },
            'aprobacion': {
                'Usuario aprobacion': log_aprobacion.US_NID.username if log_aprobacion and log_aprobacion.US_NID else '',
                'Fecha aprobacion': log_aprobacion.LOG_FFECHAREGISTRO.strftime('%d/%m/%Y %H:%M') if log_aprobacion and log_aprobacion.LOG_FFECHAREGISTRO else '',
                'Observacion': 'No registrado',
            },
            'documentos': documentos,
        }

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'ESTANQUE_OPEN',
            f'Apertura asignacion estanque citacion #{citacion.id}',
            citacion.id,
            almacen
        )

        return JsonResponse(payload)

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada.'}, status=404)
    except Exception as e:
        print('ERROR PLANIFICACION_CITACION_ESTANQUE:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def AVANZAR_ESTANQUE_SIGUIENTE_ETAPA(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Metodo no permitido.'}, status=405)

    if not usuario_es_asistente_cd(request.user) and not getattr(request.user, 'is_superuser', False):
        return JsonResponse({'success': False, 'message': 'No tiene permisos para enviar a la siguiente etapa.'}, status=403)

    Empresa = Verificar_empresa(request)
    if Empresa is None:
        return JsonResponse({'success': False, 'message': 'Debe seleccionar una empresa.'}, status=400)

    try:
        citacion = CITACION.objects.select_related('EP_NID', 'SC_NID', 'PL_NID').get(pk=pk, EP_NID_id=Empresa, CI_BHABILITADO=True)
        detalle_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID,
            ET_NID=citacion.ETAPA_ACTUAL,
            SE_BHABILITADO=True
        ).first()

        if not detalle_actual or detalle_actual.SE_NPASO <= 2:
            return JsonResponse({'success': False, 'message': 'La citacion aun no esta disponible para Asistente_C_D.'}, status=400)

        if citacion.CI_CESTADO == CIT_TERMINADO or detalle_actual.SE_NPASO > 3 or SYSLOGGER.objects.filter(LOG_COPERACION='ENVIA_CD_NEXT', LOG_CADD1=str(citacion.id)).exists():
            return JsonResponse({'success': False, 'message': 'Esta citacion ya fue enviada a la siguiente etapa.'}, status=409)

        dato_estanque = obtener_dato_estanque_operacional(citacion)
        if not dato_estanque or not str(dato_estanque.DO_CVALOR or '').strip():
            return JsonResponse({'success': False, 'message': 'Debe guardar un estanque antes de enviar.'}, status=400)

        etapa_origen, etapa_destino = avanzar_citacion_a_siguiente_etapa(
            citacion,
            usuario=request.user,
            accion='ENVIA_CD_NEXT',
            observacion=f'Estanque asignado: {dato_estanque.DO_CVALOR}'
        )

        registrar_log_camion_no_planificado(
            request.user,
            citacion.EP_NID,
            'ENVIA_CD_NEXT',
            f'Asistente_C_D envia citacion #{citacion.id} desde {etapa_origen.ET_CCODIGO} a {etapa_destino.ET_CCODIGO if etapa_destino else "FIN"} con estanque {dato_estanque.DO_CVALOR}',
            citacion.id,
            dato_estanque.DO_CVALOR
        )

        return JsonResponse({'success': True, 'message': 'Citacion enviada a la siguiente etapa.', 'estanque': dato_estanque.DO_CVALOR})

    except CITACION.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Citacion no encontrada.'}, status=404)
    except Exception as e:
        print('ERROR AVANZAR_ESTANQUE_SIGUIENTE_ETAPA:', e)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


##########################################################################
#####################  CONSULTA CLIENTES EN BD  ##########################
##########################################################################

def obtener_clientes_aceite(empresa_id):
    query = '''
        SELECT
            "SCA_CARDCODE",
            "SCA_CARDNAME"
        FROM "SAP_CLIENTES_ACEITE"
        WHERE "EP_NID_id" = %s
          AND "SCA_BHABILITADO" = true
        ORDER BY "SCA_CARDNAME"
    '''

    with connection.cursor() as cursor:
        cursor.execute(query, [empresa_id])
        rows = cursor.fetchall()

    clientes = []

    for row in rows:
        clientes.append({
            'SOP_CARDCODE': row[0],
            'SOP_CARDNAME': row[1],
        })

    return clientes


PERFILES_INGRESO_CAMION = {
    'GUARDIA',
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
}

PERFILES_ASISTENTE_RECEPCION = {
    'ASISTENTE DE RECEPCION',
    'ASISTENTE RECEPCION',
    'AR',
}

PERFILES_ASISTENTE_CD = {
    'ASISTENTE C D',
    'ASISTENTE CD',
}

USUARIOS_ASISTENTE_CD = {
    'ASISTENTE C D',
    'ASISTENTE CD',
}


PERFILES_PLANIFICADOR = {
    'PLANIFICADOR',
    'PLAN',
}


def normalizar_nombre_perfil(valor):
    texto = str(valor or '').strip().upper()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return ' '.join(texto.replace('_', ' ').replace('-', ' ').split())


def usuario_es_ingreso_camion(user):
    if getattr(user, 'is_superuser', False):
        return False

    if normalizar_nombre_perfil(getattr(user, 'username', '')) in USUARIOS_ASISTENTE_CD:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_INGRESO_CAMION or codigo in PERFILES_INGRESO_CAMION:
            return True

    return False


def usuario_es_guardia(user):
    if getattr(user, 'is_superuser', False):
        return False

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_GUARDIA or codigo in PERFILES_GUARDIA:
            return True

    return False


def usuario_es_asistente_recepcion(user):
    if getattr(user, 'is_superuser', False):
        return False

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_RECEPCION or codigo in PERFILES_ASISTENTE_RECEPCION:
            return True

    return False


def usuario_es_asistente_cd(user):
    if getattr(user, 'is_superuser', False):
        return False

    if normalizar_nombre_perfil(getattr(user, 'username', '')) in USUARIOS_ASISTENTE_CD:
        return True

    perfiles_usuario = PERFIL_USUARIO.objects.select_related('PR_NID').filter(
        US_NID=user.id,
        PE_BHABILITADO=True,
        PR_NID__PR_BHABILITADO=True
    )

    for perfil_usuario in perfiles_usuario:
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_ASISTENTE_CD or codigo in PERFILES_ASISTENTE_CD:
            return True

    return False


def usuario_es_planificador(user):
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
        nombre = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CNOMBRE)
        codigo = normalizar_nombre_perfil(perfil_usuario.PR_NID.PR_CCODIGO)

        if nombre in PERFILES_PLANIFICADOR or codigo in PERFILES_PLANIFICADOR:
            return True

    return False


CAMPOS_INGRESO_CAMION_DEFAULT = [
    {
        'codigo': 'CI_CNUMERODOCUMENTO',
        'etiqueta': 'Numero de guia',
        'tipo': 'TEXTO',
        'obligatorio': True,
        'asignar_citacion': True,
    },
    {
        'codigo': 'ING_BL',
        'etiqueta': 'BL',
        'tipo': 'TEXTO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_EMPRESA_TRANSPORTE',
        'etiqueta': 'Empresa transporte',
        'tipo': 'TEXTO',
        'obligatorio': True,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_NOMBRE_CONDUCTOR',
        'etiqueta': 'Nombre conductor',
        'tipo': 'TEXTO',
        'obligatorio': True,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_PATENTE',
        'etiqueta': 'Patente',
        'tipo': 'TEXTO',
        'obligatorio': True,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_TELEFONO_CONDUCTOR',
        'etiqueta': 'N telefono conductor',
        'tipo': 'TEXTO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_LOTE_CONTENEDOR',
        'etiqueta': 'Lote-contenedor',
        'tipo': 'TEXTO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_DOC_GUIA',
        'etiqueta': 'Escanear guia',
        'tipo': 'ARCHIVO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_DOC_TICKET_ORIGEN',
        'etiqueta': 'Escanear ticket origen',
        'tipo': 'ARCHIVO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
    {
        'codigo': 'ING_DOC_SERNAPESCA',
        'etiqueta': 'Escanear Sernapesca',
        'tipo': 'ARCHIVO',
        'obligatorio': False,
        'asignar_citacion': False,
    },
]


def usuario_puede_operar_ingreso_camion(user):
    return getattr(user, 'is_superuser', False) or usuario_es_ingreso_camion(user)


def obtener_base_folder_campo(empresa_id):
    if empresa_id == ID_TERRAMAR:
        return CAMPO_TERRAMAR_PATH
    if empresa_id == ID_ACEITES_SBH:
        return CAMPO_ACEITES_PATH
    return CAMPO_TERRAMAR_PATH


def guardar_archivo_dato_operacion(citacion, etapa, archivo):
    base_folder = obtener_base_folder_campo(citacion.EP_NID_id)
    folder_path = os.path.join(base_folder, str(citacion.SC_NID.SE_CCODIGO), str(etapa.ET_CCODIGO))
    os.makedirs(folder_path, exist_ok=True)

    file_extension = archivo.name.split('.')[-1]
    unique_filename = str(uuid.uuid4()) + '.' + file_extension
    file_path = os.path.join(folder_path, unique_filename)

    with open(file_path, 'wb+') as destination:
        for chunk in archivo.chunks():
            destination.write(chunk)

    return file_path


def asegurar_campos_ingreso_camion(citacion, etapa, usuario):
    for indice, definicion in enumerate(CAMPOS_INGRESO_CAMION_DEFAULT, start=1):
        campo = CAMPO.objects.filter(
            EP_NID=citacion.EP_NID,
            CA_CCODIGO=definicion['codigo']
        ).first()

        if not campo:
            campo = CAMPO.objects.create(
                EP_NID=citacion.EP_NID,
                US_NID=usuario,
                CA_CTIPO=definicion['tipo'],
                CA_CCODIGO=definicion['codigo'],
                CA_CETIQUETA=definicion['etiqueta'],
                CA_CPLACEMARK=definicion['etiqueta'],
                CA_BOBLIGATORIO=definicion['obligatorio'],
                CA_BHABILITADO=True,
                CA_BASIGNARVALOR=definicion['asignar_citacion'],
            )

        DETALLE_ETAPA.objects.update_or_create(
            EP_NID=citacion.EP_NID,
            ET_NID=etapa,
            CAMP_NID=campo,
            defaults={
                'US_NID': usuario,
                'DET_NPASO': indice,
                'DET_BOBLIGATORIO': definicion['obligatorio'],
                'DET_CETIQUETAETAPA': definicion['etiqueta'],
                'DET_BHABILITADO': True,
            }
        )


def obtener_bl_inicial_citacion(citacion):
    if not citacion.CI_CCOMENTARIO:
        return ''

    try:
        comentario = json.loads(citacion.CI_CCOMENTARIO)
    except (TypeError, ValueError):
        return ''

    if not isinstance(comentario, dict):
        return ''

    return (
        comentario.get('bl')
        or comentario.get('BL')
        or comentario.get('contenedor')
        or comentario.get('BL / Contenedor')
        or ''
    )


def obtener_campos_operacion_etapa(citacion, etapa, usuario):
    asegurar_campos_ingreso_camion(citacion, etapa, usuario)

    campos = []
    detalles = DETALLE_ETAPA.objects.filter(
        EP_NID=citacion.EP_NID,
        ET_NID=etapa,
        DET_BHABILITADO=True,
        CAMP_NID__CA_BHABILITADO=True
    ).select_related('CAMP_NID').order_by('DET_NPASO', 'id')

    for detalle in detalles:
        campo = detalle.CAMP_NID
        datos = []
        if campo.CA_CTIPO.lower() == 'lista' and campo.CA_CQUERY:
            try:
                datos = QueryParam(campo.CA_CQUERY)
            except Exception as e:
                print(f'Error al ejecutar query de campo {campo.id}: {e}')

        dato_operacion = DATO_OPERACION.objects.filter(
            CI_NID=citacion,
            SC_NID=citacion.SC_NID,
            ET_NID=etapa,
            CAMP_NID=campo
        ).order_by('-id').first()

        valor_default = dato_operacion.DO_CVALOR if dato_operacion else (campo.CA_CVALORDEFAULT or '')
        if not dato_operacion and campo.CA_CCODIGO == 'ING_BL':
            valor_default = obtener_bl_inicial_citacion(citacion)

        campos.append({
            'id': campo.id,
            'name': f'{etapa.ET_CCODIGO.replace(" ", "")}_{campo.id}',
            'label': detalle.DET_CETIQUETAETAPA or campo.CA_CETIQUETA,
            'type': campo.CA_CTIPO.lower(),
            'default': valor_default,
            'required': detalle.DET_BOBLIGATORIO or campo.CA_BOBLIGATORIO,
            'maxlength': campo.CA_NLARGO,
            'datos': datos,
            'has_file': bool(dato_operacion and campo.CA_CTIPO.lower() == 'archivo'),
            'download_url': reverse('cit_download_file', args=[dato_operacion.id]) if dato_operacion and campo.CA_CTIPO.lower() == 'archivo' else '',
        })

    return campos


def guardar_operacion_etapa(citacion, request):
    empresa = citacion.EP_NID
    secuencia = citacion.SC_NID
    etapa_actual = citacion.ETAPA_ACTUAL
    tuvo_datos_previos = DATO_OPERACION.objects.filter(
        CI_NID=citacion,
        SC_NID=secuencia,
        ET_NID=etapa_actual
    ).exists()

    if citacion.CI_CESTADO != CIT_EN_PROCESO:
        citacion.CI_CESTADO = CIT_EN_PROCESO
        citacion.CI_FFECHAINICIO = citacion.CI_FFECHAINICIO or datetime.now()
        citacion.save(update_fields=['CI_CESTADO', 'CI_FFECHAINICIO'])

    etapa_log_ingreso, _ = ETAPA_LOG.objects.get_or_create(
        CI_NID=citacion,
        EP_NID=empresa,
        SC_NID=secuencia,
        ET_NID=etapa_actual,
        EL_FFECHAFIN=None,
        defaults={
            'EL_FFECHAINICIO': datetime.now(),
            'US_INICIO_ID': request.user,
            'EL_CACCION': 'INGRESO_CAMION',
        }
    )
    if etapa_log_ingreso.US_INICIO_ID_id is None:
        etapa_log_ingreso.US_INICIO_ID = request.user
        etapa_log_ingreso.EL_CACCION = etapa_log_ingreso.EL_CACCION or 'INGRESO_CAMION'
        etapa_log_ingreso.save(update_fields=['US_INICIO_ID', 'EL_CACCION'])

    detalle_secuencia_actual = DETALLE_SECUENCIA.objects.filter(
        SC_NID=secuencia,
        ET_NID=etapa_actual,
        SE_BHABILITADO=True
    ).first()

    if not detalle_secuencia_actual:
        raise Exception('La etapa actual no esta habilitada en la secuencia.')

    campos_etapa = obtener_campos_operacion_etapa(citacion, etapa_actual, request.user)

    for campo_data in campos_etapa:
        campo = CAMPO.objects.get(id=campo_data['id'])
        input_name = campo_data['name']

        if campo.CA_CTIPO.lower() == 'archivo':
            archivo = request.FILES.get(input_name)
            if not archivo:
                if campo_data['required'] and not campo_data['has_file']:
                    raise Exception(f'Debe cargar el archivo {campo_data["label"]}.')
                continue
            valor_campo = guardar_archivo_dato_operacion(citacion, etapa_actual, archivo)
        else:
            valor_campo = request.POST.get(input_name)
            if campo.CA_CTIPO == 'CHECK' and valor_campo is None:
                valor_campo = False
            if campo_data['required'] and (valor_campo is None or str(valor_campo).strip() == ''):
                raise Exception(f'Debe completar {campo_data["label"]}.')

        if campo.CA_CCODIGO == 'CI_CNUMERODOCUMENTO':
            citacion.CI_CNUMERODOCUMENTO = valor_campo
            if not citacion.CI_CTIPODOCUMENTO:
                citacion.CI_CTIPODOCUMENTO = 'GUIA'
            citacion.save(update_fields=['CI_CNUMERODOCUMENTO', 'CI_CTIPODOCUMENTO'])
        elif campo.CA_BASIGNARVALOR and campo.CA_CCODIGO:
            setattr(citacion, campo.CA_CCODIGO, valor_campo)
            citacion.save(update_fields=[campo.CA_CCODIGO])

        DATO_OPERACION.objects.update_or_create(
            CI_NID=citacion,
            SC_NID=secuencia,
            ET_NID=etapa_actual,
            CAMP_NID=campo,
            defaults={
                'EP_NID': empresa,
                'US_NID': request.user,
                'DO_CVALOR': valor_campo,
                'DO_FFECHAREGISTRO': datetime.now(),
            }
        )

    registrar_log_camion_no_planificado(
        request.user,
        empresa,
        'ING_CAMION',
        f'{"Edicion" if tuvo_datos_previos else "Registro"} ingreso camion citacion #{citacion.id} etapa {etapa_actual.ET_CCODIGO}',
        citacion.id,
        etapa_actual.ET_CCODIGO
    )

    return tuvo_datos_previos


def PLANIFICACION_ADDONE(request):
    try:
        if usuario_es_ingreso_camion(request.user):
            messages.error(request, 'Su perfil puede ingresar camiones, pero no crear planificaciones.')
            return redirect('/pla_listall/')

        if request.user.is_superuser == False:
            usuario = request.user.id
            if not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        if request.method == 'POST':
            form = formPLANIFICACION(request.POST)

            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.EP_NID_id = Empresa
                form.instance.PL_FFECHAREGISTRO = datetime.now()
                planificacion = form.save()

                messages.success(request, 'Planificación creada correctamente')
                return redirect(f'/pla_listone/{planificacion.pk}')
            else:
                messages.error(request, f'Error en el formulario, {str(form.errors)}')
                return redirect('/pla_addone/')

        form = formPLANIFICACION()

        clientes_sap = obtener_clientes_aceite(Empresa)

        proveedores_sap = SAP_OPOR_PROGRAMACION.objects.filter(
            EP_NID_id=Empresa,
            SOP_BHABILITADO=True,
            SOP_CARDNAME__isnull=False
        ).exclude(
            SOP_CARDNAME=''
        ).values(
            'SOP_CARDCODE',
            'SOP_CARDNAME'
        ).distinct().order_by('SOP_CARDNAME')

        secuencias = SECUENCIA.objects.filter(
            EP_NID_id=Empresa,
            SE_BHABILITADO=True
        ).order_by("SE_CTIPO", "SE_CNOMBRE")

        ctx = {
            'form': form,
            'clientes_sap': clientes_sap,
            'proveedores_sap': proveedores_sap,
            'secuencias': secuencias
        }

        return render(request, 'home/PLANIFICACION/pla_addone.html', ctx)

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pla_listall/')

##########################################################################
#####################  CONSULTA SAP OPOR NUEVO  ##########################
##########################################################################

def BUSCAR_OPOR_POR_CODIGO(request):
    try:
        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'Debe seleccionar una empresa.'
            })

        codigo = request.GET.get('codigo', '').strip()

        if not codigo:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'Debe ingresar código SAP.'
            })

        registro = (
            SAP_OPOR_PROGRAMACION.objects
            .filter(
                EP_NID_id=Empresa,
                SOP_ITEMCODE=codigo,
                SOP_BHABILITADO=True
            )
            .values('SOP_ITEMCODE')
            .annotate(nombre_producto=Min('SOP_DSCRIPTIONS'))
            .order_by('SOP_ITEMCODE')
            .first()
        )

        if not registro:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'No se encontró producto para el código SAP ingresado.'
            })

        data = {
            'codigo': registro['SOP_ITEMCODE'],
            'insumo': registro['nombre_producto'] or '',
        }

        return JsonResponse({
            'success': True,
            'total': 1,
            'data': [data]
        })

    except Exception as e:
        print('ERROR BUSCAR_OPOR_POR_CODIGO:', e)
        return JsonResponse({
            'success': False,
            'total': 0,
            'message': str(e)
        })

def BUSCAR_OPOR_POR_PEDIDO(request):
    try:
        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'Debe seleccionar una empresa.'
            })

        codigo = request.GET.get('codigo', '').strip()
        pedido = request.GET.get('pedido', '').strip()

        if not codigo:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'Debe ingresar código SAP.'
            })

        if not pedido:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'Debe ingresar Pedido SAP.'
            })

        item = SAP_OPOR_PROGRAMACION.objects.filter(
            EP_NID_id=Empresa,
            SOP_ITEMCODE=codigo,
            SOP_DOCNUM=pedido,
            SOP_BHABILITADO=True
        ).first()

        if not item:
            return JsonResponse({
                'success': False,
                'total': 0,
                'message': 'No se encontró programación para el código SAP y Pedido SAP ingresado.'
            })

        data = {
            'sap_opor_id': item.id,
            'codigo': item.SOP_ITEMCODE or '',
            'pedido': item.SOP_DOCNUM or '',
            'cantidad_disponible': str(item.SOP_OPENQTY) if item.SOP_OPENQTY is not None else '',
            'docentry': item.SOP_DOCENTRY or '',
            'proveedor_codigo': item.SOP_CARDCODE or '',
            'proveedor_nombre': item.SOP_CARDNAME or '',
            'productor': item.SOP_PRODUCTOR or '',
            'empresa_id': item.EP_NID_id,
        }

        return JsonResponse({
            'success': True,
            'total': 1,
            'data': [data]
        })

    except Exception as e:
        print('ERROR BUSCAR_OPOR_POR_PEDIDO:', e)

        return JsonResponse({
            'success': False,
            'total': 0,
            'message': str(e)
        })

##########################################################################
#####################  VALIDACIÓN DE PERFIL   ############################
##########################################################################

def validar_perfiles_activos(id_user, template):
    perfiles_activos = list(PERFIL.objects.filter(PR_BHABILITADO = True).values_list('id', flat=True))
    perfiles_usuario = list(PERFIL_USUARIO.objects.filter(US_NID = id_user, PR_NID__in=perfiles_activos).values_list('PR_NID', flat=True))
    # Si el usuario no tiene perfiles asignados, retornar False
    if not perfiles_usuario:
        return False
    try:
        vista = VISTA.objects.get(VI_CNOMBRE = template, VI_BHABILITADO = True)
        permisos = PERMISO.objects.filter(PR_NID__in=perfiles_usuario, VI_NID = vista).exists()
        return permisos
    except VISTA.DoesNotExist:
        return False

##########################################################################
#####################  VALIDACIÓN DE EMPRESA ACTIVA NUEVO #####################
##########################################################################

def Verificar_empresa(request):
    """
    Retorna el ID de la empresa activa del usuario.

    Flujo:
    - Si existe empresa activa en session y el usuario tiene acceso, retorna esa empresa.
    - Si el usuario tiene solo una empresa asignada, la guarda en session y la retorna.
    - Si el usuario tiene más de una empresa asignada, retorna None para forzar selección.
    - Si el usuario no tiene empresa asignada, retorna None.
    """

    empresa_id = request.session.get('empresa_id')

    if empresa_id:
        acceso = USERS_EMPRESA.objects.filter(
            US_NID=request.user,
            EP_NID_id=empresa_id
        ).exists()

        if acceso:
            return empresa_id

        request.session.pop('empresa_id', None)

    empresas_usuario = USERS_EMPRESA.objects.filter(
        US_NID=request.user
    ).select_related('EP_NID')

    if empresas_usuario.count() == 1:
        empresa_id = empresas_usuario.first().EP_NID_id
        request.session['empresa_id'] = empresa_id
        return empresa_id

    if empresas_usuario.count() > 1:
        return None

    return None


def obtener_empresa_activa_o_redirect(request):
    """
    Función auxiliar para vistas.

    Retorna:
    - empresa_id, None si hay empresa activa.
    - None, redirect si el usuario debe seleccionar empresa.
    """

    empresa_id = Verificar_empresa(request)

    if empresa_id is None:
        return None, redirect('/seleccionar_empresa/')

    return empresa_id, None

##########################################################################
#####################  SELECCIÓN DE EMPRESA ACTIVA NUEVO  ######################
##########################################################################

def seleccionar_empresa(request):
    """
    Vista para seleccionar la empresa activa del usuario.

    Esta vista se usa cuando un usuario tiene acceso a más de una empresa.
    Ejemplo:
        admin -> TERRAMAR CHILE
        admin -> ACEITES SBH

    Flujo:
    - Busca todas las empresas asociadas al usuario en USERS_EMPRESA.
    - Si no tiene empresas, cierra flujo y redirige a logout.
    - Si tiene solo una empresa, la guarda automáticamente en session.
    - Si tiene más de una empresa, muestra el template selector.
    """

    try:
        empresas_usuario = USERS_EMPRESA.objects.filter(
            US_NID=request.user
        ).select_related('EP_NID').order_by('EP_NID_id')

        # Caso 1: usuario sin empresa asignada
        if not empresas_usuario.exists():
            logout(request)
            messages.error(request, 'Su usuario no tiene empresa asignada.')
            return redirect('login')

        # Caso 2: usuario con una sola empresa
        # Se asigna automáticamente y entra directo al sistema
        if empresas_usuario.count() == 1:
            empresa_id = empresas_usuario.first().EP_NID_id
            request.session['empresa_id'] = empresa_id
            return redirect('/')

        # Caso 3: usuario multiempresa
        # Se envía al template para que seleccione con cuál empresa trabajar
        ctx = {
            'empresas_usuario': empresas_usuario
        }

        return render(request, 'home/EMPRESA/seleccionar_empresa.html', ctx)

    except Exception as e:
        print(e)
        messages.error(request, f'Error al seleccionar empresa: {str(e)}')
        return redirect('/')


def cambiar_empresa(request, empresa_id):
    """
    Vista para cambiar o definir la empresa activa en session.

    Esta función se ejecuta cuando el usuario presiona "Entrar"
    en el selector de empresa.

    Flujo:
    - Valida que el usuario tenga acceso real a la empresa seleccionada.
    - Si tiene acceso, guarda empresa_id en request.session.
    - Luego redirige al home.
    """

    try:
        # Validar que el usuario tenga permiso sobre la empresa seleccionada
        acceso = USERS_EMPRESA.objects.filter(
            US_NID=request.user,
            EP_NID_id=empresa_id
        ).exists()

        if not acceso:
            messages.error(request, 'No tiene acceso a la empresa seleccionada.')
            return redirect('/seleccionar_empresa/')

        # Guardar empresa activa en session
        request.session['empresa_id'] = empresa_id

        # Mensaje informativo
        empresa = EMPRESA.objects.get(id=empresa_id)
        messages.success(request, f'Empresa activa: {empresa.EP_CRAZONSOCIAL}')

        return redirect('/')

    except Exception as e:
        print(e)
        messages.error(request, f'Error al cambiar empresa: {str(e)}')
        return redirect('/seleccionar_empresa/')
    

###########################################
##### TRADUCTOR DE TEXTO ##################
###########################################
def traductor(texto):
    # Create a Translator object
    translator = Translator(service_urls=['translate.google.com'])

    # Translate the text to Spanish
    translation = translator.translate(texto, dest='es')

    return translation.text

##################################################
########## CREADOR DE EXCEL ERRORES ##############
##################################################

def excel_errores(errores,columnas):
    abcedario = ['A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z']
    """Función para crear un archivo Excel que contenga las líneas con errores de datos.
        Args:
            errors (list): Una lista de diccionarios que contienen los errores de datos.
        Returns:
            El archivo Excel con los datos erróneos.
    """
    # Crea un nuevo libro de trabajo de Excel.
    workbook = openpyxl.Workbook()

    # Selecciona la hoja activa.
    worksheet = workbook.active
    for index in range(0,len(columnas)):
        worksheet[str(abcedario[index]) + '1'] = columnas[index]

    # Agrega los datos erróneos.
    for index, error in enumerate(errores, start=2):
        for i in range(0,len(error)):
            worksheet.cell(row=index, column=i+1, value=error[i])
    nombre_archivo = "errores_cargas_masivas/errores.xlsx"
    direccion = os.path.join(settings.MEDIA_ROOT, nombre_archivo)
    # Guarda el archivo Excel.
    workbook.save(direccion)

    return os.path.join(settings.MEDIA_URL, nombre_archivo)

##########################################################################
###############################  INICIO   ################################
##########################################################################

def inicio(request):
    try:
        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        citaciones_despachos = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CESTADO='EN PROCESO',
            CI_CTIPO=CIT_DESPACHO,
            CI_BARCHIVADO=False
        ).order_by('-id')

        citaciones_recepciones = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CESTADO='EN PROCESO',
            CI_CTIPO=CIT_RECEPCION,
            CI_BARCHIVADO=False
        ).order_by('-id')

        camiones_en_operacion = get_camiones_planta_operacion(Empresa)
        camiones_dia_semana_mes = get_camiones_dia_semana_mes(Empresa)
        camiones_item = get_camiones_item(Empresa)
        cupos_por_proveedor = get_cupos_por_proveedor(Empresa)
        citacion_en_proceso_terminado = get_citacion_enproceso_terminado(Empresa)
        citacion_terminada_noproforma = get_citacion_terminada_noproforma(Empresa)
        citaciones_por_etapa = get_citacion_por_etapa(Empresa)
        citacion_por_secuencia = get_citacion_por_secuencia(Empresa)

        citacion_tipos = [
            ('Despachos', citaciones_despachos.count()),
            ('Recepciones', citaciones_recepciones.count())
        ]

        object_list = []
        object_list_recepciones = []

        for citacion in citaciones_despachos:
            citacion_item = CITACION_ITEM.objects.filter(
                CI_NID_id=citacion.id
            ).first()

            if citacion_item:
                item = ITEM.objects.filter(
                    id=citacion_item.IT_NID_id
                ).first()

                if item:
                    object_list.append({
                        'citacion': citacion,
                        'item': item
                    })

        for citacion in citaciones_recepciones:
            citacion_item = CITACION_ITEM.objects.filter(
                CI_NID_id=citacion.id
            ).first()

            if citacion_item:
                item = ITEM.objects.filter(
                    id=citacion_item.IT_NID_id
                ).first()

                if item:
                    object_list_recepciones.append({
                        'citacion': citacion,
                        'item': item
                    })

        today = datetime.now()
        one_week_before = today - timedelta(days=7)

        proformas_por_socionegocio = PROFORMA.objects.filter(
            EP_NID_id=Empresa,
            PRO_FFECHAEMISION__date__range=[one_week_before, today],
            SN_NID__isnull=False
        ).values(
            'SN_NID__SN_CRAZONSOCIAL',
            'SN_NID'
        ).annotate(
            cantidad_proformas=Count('id')
        ).order_by('-cantidad_proformas')

        page = request.GET.get('page', 1)
        paginator = Paginator(object_list, 500)
        object_list_paginado = paginator.page(page)

        context = {
            'citacion_en_proceso': citacion_en_proceso_terminado[0][0],
            'citacion_terminado': citacion_en_proceso_terminado[0][1],
            'citacion_terminada_noproforma': citacion_terminada_noproforma[0],
            'camiones_item': camiones_item,
            'camiones_dia': camiones_dia_semana_mes[0][1],
            'camiones_semana': camiones_dia_semana_mes[1][1],
            'camiones_mes': camiones_dia_semana_mes[2][1],
            'camiones_en_operacion': camiones_en_operacion[0],
            'object_list': object_list_paginado,
            'object_list_recepciones': object_list_recepciones,
            'citacion_tipos': citacion_tipos,
            'cupos_por_proveedor': cupos_por_proveedor,
            'citacion_por_etapa': citaciones_por_etapa,
            'citacion_por_secuencia': citacion_por_secuencia,
            'proformas': proformas_por_socionegocio,
            'today': today.strftime('%d-%m-%Y'),
            'one_week_before': one_week_before.strftime('%d-%m-%Y')
        }

        return render(request, 'home/HOME/index.html', context)

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')
def obtener_detalles_citacion(request, citacion_id):
    try:
        citacion = CITACION.objects.get(id=citacion_id)
        # Obtén los detalles de la citación desde la base de datos
        detalle_citacion = get_detalle_citaciones(citacion_id)
        if citacion.CI_CTIPO == CIT_DESPACHO:
            camion = {
                "patente":detalle_citacion[0][0],
                "marca":detalle_citacion[0][1],
                "modelo":detalle_citacion[0][2],
                "anio":detalle_citacion[0][3],        
            }
            conductor = {
                "nombre":detalle_citacion[0][4],
                "apellido":detalle_citacion[0][5],
                "rut":detalle_citacion[0][6],        
                "email":detalle_citacion[0][7],
            }
            proveedor = {
                "razonsocial":detalle_citacion[0][8],
                "rut":detalle_citacion[0][9],
                "email":detalle_citacion[0][10],
            }
        elif citacion.CI_CTIPO == CIT_RECEPCION:
            camion = {}
            conductor = {}
            proveedor = {}

        etapas = detalle_citacion[0][11]
        etapas_array = etapas.split(',')
        etapas_log = []
        for etapa_info in etapas_array:
            etapa_parts = etapa_info.split('|')
            if len(etapa_parts) == 4:
                etapa = ETAPA.objects.get(pk = etapa_parts[3])
                fecha_inicio = datetime.strptime(etapa_parts[1], '%d/%m/%Y %H:%M')
                fecha_fin = datetime.now()
                if etapa_parts[2]:
                    fecha_fin = datetime.strptime(etapa_parts[2], '%d/%m/%Y %H:%M')

                diferencia = fecha_fin - fecha_inicio
                total_seconds = diferencia.total_seconds()
                horas_totales = int(total_seconds // 3600)  # Divide entre 3600 segundos para obtener horas totales
                minutos = int((total_seconds % 3600) // 60)  # Resto de horas convertido a minutos
                segundos = int(total_seconds % 60)  # Resto de minutos convertido a segundos

                if horas_totales < 10:
                    horas_totales = f'0{horas_totales}'
                if minutos < 10:
                    minutos = f'0{minutos}'
                if segundos < 10:
                    segundos = f'0{segundos}'
                
                etapas_log.append({
                    'etapa': etapa_parts[0],
                    'fechainicio': etapa_parts[1] if etapa_parts[1] else '-',
                    'fechafin': etapa_parts[2] if etapa_parts[2] else '-',
                    'diferencia': f'{horas_totales}:{minutos}:{segundos}',
                    'maximo': etapa.ET_TTIEMPOMAXIMO.strftime('%H:%M:%S')
                })
        secuencia = SECUENCIA.objects.get(id=citacion.SC_NID.id)
        tiempo_en_etapa_actual = get_tiempo_maximo_secuencia(secuencia.id)
        tiempo_total_secuencia = citacion.tiempo_total_secuencia

        tiempo_etapa_actual_formatted = str(timedelta(seconds=tiempo_en_etapa_actual.seconds))
        tiempo_total_secuencia_formatted = str(timedelta(seconds=tiempo_total_secuencia.seconds))

        data = {
            'valid': True,
            'camion': camion,
            'conductor': conductor,
            'proveedor': proveedor,
            'etapas_completadas': etapas_log,
            'tiempo_en_etapa_actual': tiempo_etapa_actual_formatted,
            'tiempo_total_secuencia': tiempo_total_secuencia_formatted,
            'tipo_citacion': citacion.CI_CTIPO
        }
        print("data:", data)
        return JsonResponse(data)
    except Exception as e:
        print(e)
        data = {
            'valid': False,
            'error': str(e)
        }
        return JsonResponse(data)

def pages(request):
    context = {}
    # All resource paths end in .html.
    # Pick out the html file name from the url. And load that template.
    try:

        load_template = request.path.split('/')[-1]

        if load_template == 'admin':
            return HttpResponseRedirect(reverse('admin:index'))
        context['segment'] = load_template

        html_template = loader.get_template('home/GRADIENT/' + load_template)
        return HttpResponse(html_template.render(context, request))

    except template.TemplateDoesNotExist:

        html_template = loader.get_template('home/GRADIENT/page-404.html')
        return HttpResponse(html_template.render(context, request))

    except:
        html_template = loader.get_template('home/GRADIENT/page-500.html')
        return HttpResponse(html_template.render(context, request))

def DASHBOARD_GRAFICO(request):
    try:
        Empresa = Verificar_empresa(request)
        zonas = get_list_zonas(Empresa)
        object_list = []
        object_list_zonas = []
        
        if zonas:
            for tupla in zonas:
                # Asegúrate de que el décimo elemento no sea None
                if len(tupla) > 10 and tupla[10] is not None:
                    object_list_zonas.append(list(tupla))
                else:
                    # Si es None, puedes asignar un color por defecto o manejarlo de otra manera
                    tupla = list(tupla)
                    tupla[10] = '#bada55'  # Color por defecto
                    object_list_zonas.append(tupla)

        citaciones = get_citaciones_zonas(Empresa)
        if citaciones:
            object_list = [list(tupla) for tupla in citaciones]

        ctx = {
            "object_list": object_list,
            'object_list_zonas': object_list_zonas,
            "lat_init": LAT_INIT,
            "lon_init": LON_INIT,
            'map_zoom': str(MAP_ZOOM_INIT),
            'map_height': MAP_HEIGHT_RAM,
        }
        return render(request, 'home/HOME/monitor.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect("/")

##########################################################################
######################   CAMBIO CONTRASEÑA   #############################
##########################################################################

class CambioContraseña(FormView):
    model = User
    form_class = PasswordChangeForm
    template_name= 'home/CONTRASEÑA/cambio_contraseña.html'
    success_url = reverse_lazy('/')

    def get_form(self, form_class=None):
        form = PasswordChangeForm(user=self.request.user)
        return form


    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.method == 'POST':
                form = PasswordChangeForm(user=request.user, data=request.POST)
                if form.is_valid():
                    form.save()
                    update_session_auth_hash(request, form.user) # Important!
                else:
                    messages.error(request, 'Datos incorrectos, intente nuevamente.')
            else:
                form = PasswordChangeForm(request.user)
        except Exception as e:
            messages.error(request, 'Error.')
            return redirect('home')
        messages.success(request, 'Contraseña actualizada correctamente!.')
        return redirect('home')
    
##########################################################################
############################   EMPRESA   #################################
##########################################################################

def EMPRESA_LISTALL(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "emp_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        object_list = EMPRESA.objects.all()

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/EMPRESA/emp_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def EMPRESA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        if request.method == 'POST':
            form = formEMPRESA(request.POST)
            if form.is_valid():
                password_bd = encrypt_string(form.instance.EP_CPASSWORDBD)
                password_sap = encrypt_string(form.instance.EP_CPASSWORD_SAP)
                form.instance.EP_CPASSWORDBD = password_bd
                form.instance.EP_CPASSWORD_SAP = password_sap
                form.save()
                messages.success(request, 'Empresa guardada correctamente')
                return redirect('/emp_listall/')

        form = formEMPRESA()
        ctx = {
            'form': form
        }
        return render(request, 'home/EMPRESA/emp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def EMPRESA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        empresa = EMPRESA.objects.get(id = pk)
        if request.method == 'POST':
            form = formEMPRESA(request.POST, instance=empresa)
            if form.is_valid():
                password_bd = form.instance.EP_CPASSWORDBD
                password_sap = form.instance.EP_CPASSWORD_SAP

                password_bd = encrypt_string(password_bd)
                password_sap = encrypt_string(password_sap)

                form.instance.EP_CPASSWORDBD = password_bd
                form.instance.EP_CPASSWORD_SAP = password_sap
                form.save()
                messages.success(request, 'Empresa actualizada correctamente')
                return redirect('/emp_listall/')

        form = formEMPRESA(instance=empresa)
        ctx = {
            'form': form
        }
        return render(request, 'home/EMPRESA/emp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/emp_listall/')

##########################################################################
#############################  CONDUCTOR   ###############################
##########################################################################

def CONDUCTOR_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        if request.user.userv.UX_IS_PROVEEDOR:
            usuario_socionegocio = USUARIO_SOCIONEGOCIO.objects.get(US_NID_id = request.user.id)
            object_list = CONDUCTOR.objects.filter(CON_BHABILITADO = True, EP_NID_id = Empresa, SN_NID_id = usuario_socionegocio.SN_NID_id)
        else:
            object_list = CONDUCTOR.objects.filter(CON_BHABILITADO = True, EP_NID_id = Empresa) 

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CONDUCTOR/con_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CONDUCTOR_LISTALL_INHABILITADO(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")
                return redirect('/')
        Empresa = Verificar_empresa(request)
        object_list = CONDUCTOR.objects.filter(CON_BHABILITADO = False, EP_NID_id = Empresa)

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CONDUCTOR/con_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CONDUCTOR_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)                
        documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Conductor',EP_NID_id = Empresa)
        if request.method == 'POST':
            # Establecer empresa en el formularios
            empresa_usuario = EMPRESA.objects.get(id = Empresa)
            post_data = request.POST.copy()
            post_data['EP_NID'] = empresa_usuario
            form = formCONDUCTOR(post_data)
            if form.is_valid():
                rut = form.instance.CON_CRUT.replace('.','').upper()
                conductor_duplicado = CONDUCTOR.objects.filter(CON_CRUT=rut, CON_BHABILITADO = True, EP_NID_id = Empresa).exists()
                if conductor_duplicado:
                    messages.error(request, 'Error al guardar el conductor, RUT duplicado')
                    return redirect('/con_addone/')

                form.instance.CON_CRUT = rut
                form.instance.US_NID = request.user
                form.instance.CON_FFECHAREGISTRO = datetime.now()
                form.save()

                id_conductor = form.instance.pk
                files = request.FILES
                for documento in documentos:
                    if files.get(f'DCON_CRUTADOC{str(documento.pk)}'):
                        tipo = request.POST.get(f'DCA_CTIPO{documento.pk}')
                        fecha_emision = request.POST.get(f'DCA_FFECHAEMISION{documento.pk}')
                        fecha_vencimiento = request.POST.get(f'DCA_FFECHAVENCIMIENTO{documento.pk}')
                        archivo = request.FILES.get(f'DCON_CRUTADOC{str(documento.pk)}')

                        # Create a new folder with CAM_CPATENTE if it doesn't exist
                        if form.instance.EP_NID.id == ID_TERRAMAR:
                            base_folder = DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH
                        elif form.instance.EP_NID.id == ID_ACEITES_SBH:
                            base_folder = DOCUMENTOS_CONDUCTORE_ACEITESS_PATH

                        folder_path = os.path.join(base_folder, rut)
                        if not os.path.exists(folder_path):
                            os.makedirs(folder_path)

                        # Save the file in the new folder and change the file name to a uuid
                        file_extension = archivo.name.split('.')[-1]
                        unique_filename = str(uuid.uuid4()) + '.' + file_extension
                        file_path = os.path.join(folder_path, unique_filename)
                        with open(file_path, 'wb+') as destination:
                            for chunk in archivo.chunks():
                                destination.write(chunk)
                        
                        DOCUMENTO_CONDUCTOR.objects.create(
                            EP_NID_id = form.instance.EP_NID,
                            CON_NID_id = id_conductor,
                            US_NID_id = request.user.id,
                            DCON_CTIPO = tipo,
                            DCON_FFECHAEMISION = fecha_emision,
                            DCON_FFECHAVENCIMIENTO = fecha_vencimiento,
                            DCON_CRUTADOC = file_path,
                            DCON_FFECHAREGISTRO = datetime.now()
                        )             
                messages.success(request, 'Conductor guardado correctamente')
                return redirect('/con_listall/')
            else:
                messages.error(request, 'Error al guardar el conductor')
                return redirect('/con_addone/')
        
        form = formCONDUCTOR()
        # Fetching choices for the form fields from the database
        form.fields['SN_NID'].choices = listarOpcionesTabla('CAST("id" AS text)', ''' "SN_CRUT" || ' - ' || "SN_CRAZONSOCIAL" ''', 'SOCIONEGOCIO', '', '', '''"SN_CTIPO" = 'S' AND "SN_BHABILITADO" = TRUE ''')
        ctx = {
            'form': form,
            'documentos': documentos
        }
        return render(request, 'home/CONDUCTOR/con_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')

def CONDUCTOR_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        conductor = CONDUCTOR.objects.get(id = pk)
        documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'CONDUCTOR', EP_NID_id = Empresa)
        documentos_cargados = listar_documentos_conductor(pk)
        if request.method == 'POST':
            form = formCONDUCTOR(request.POST, instance=conductor)
            if form.is_valid():
                rut = form.instance.CON_CRUT.replace('.','').upper()
                conductor_duplicado = CONDUCTOR.objects.filter(CON_CRUT=rut, CON_BHABILITADO = True, EP_NID_id = Empresa).exclude(id = pk).exists()
                if conductor_duplicado:
                    messages.error(request, 'Error al guardar el conductor, RUT duplicado')
                    return redirect(f'/con_listone/{pk}')
                form.instance.CON_CRUT = rut
                form.save()
                files = request.FILES
                for documento in documentos:
                    if files.get(f'DCON_CRUTADOC{str(documento.pk)}'):
                        tipo = request.POST.get(f'DCA_CTIPO{documento.pk}')
                        fecha_emision = request.POST.get(f'DCA_FFECHAEMISION{documento.pk}')
                        fecha_vencimiento = request.POST.get(f'DCA_FFECHAVENCIMIENTO{documento.pk}')
                        archivo = request.FILES.get(f'DCON_CRUTADOC{str(documento.pk)}')

                        # Create a new folder with CAM_CPATENTE if it doesn't exist
                        if conductor.EP_NID.id == ID_TERRAMAR:
                            base_folder = DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH
                        elif conductor.EP_NID.id == ID_ACEITES_SBH:                            
                            base_folder = DOCUMENTOS_CONDUCTORE_ACEITESS_PATH

                        folder_path = os.path.join(base_folder, rut)
                        if not os.path.exists(folder_path):
                            os.makedirs(folder_path)

                        # Save the file in the new folder and change the file name to a uuid
                        file_extension = archivo.name.split('.')[-1]
                        unique_filename = str(uuid.uuid4()) + '.' + file_extension
                        file_path = os.path.join(folder_path, unique_filename)
                        with open(file_path, 'wb+') as destination:
                            for chunk in archivo.chunks():
                                destination.write(chunk)
                        
                        DOCUMENTO_CONDUCTOR.objects.create(
                            EP_NID = conductor.EP_NID,
                            CON_NID_id = pk,
                            US_NID_id = request.user.id,
                            DCON_CTIPO = tipo,
                            DCON_FFECHAEMISION = fecha_emision,
                            DCON_FFECHAVENCIMIENTO = fecha_vencimiento,
                            DCON_CRUTADOC = file_path,
                            DCON_FFECHAREGISTRO = datetime.now()
                        )
                messages.success(request, 'Conductor actualizado correctamente')
                return redirect(f'/con_listone/{pk}')

        form = formCONDUCTOR(instance=conductor)
        form.fields['SN_NID'].choices = listarOpcionesTabla('CAST("id" AS text)', ''' "SN_CRUT" || ' - ' || "SN_CRAZONSOCIAL" ''', 'SOCIONEGOCIO', '', '', F'''"SN_CTIPO" = 'S' AND "SN_BHABILITADO" = TRUE AND "EP_NID_id" = {Empresa} ''')
        ctx = {
            'form': form,
            'documentos': documentos,
            'documentos_cargados': documentos_cargados
        }
        return render(request, 'home/CONDUCTOR/con_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall')

def CONDUCTOR_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        conductor = CONDUCTOR.objects.get(id = pk)

        listado_documentos = listado_y_estado_documentos_xconductor(pk)
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Conductor', EP_NID_id = Empresa).values_list('LIS_CNOMBREDOCUMENTO', flat=True))
        documentos = DOCUMENTO_CONDUCTOR.objects.filter(CON_NID = conductor, DCON_BHABILITADO = True, EP_NID_id = Empresa)

        count_list = []
        lista_documentos = []
        bool_dias = 0                              # bool_dias = 0 es para indicar que los documentos aun estan vigentes
        for i in documentos:
            dias_venc = i.DIAS_VENCIMIENTO
            if i.DCON_CTIPO in tipos_documentos:
                if dias_venc < 31 and dias_venc > 0:
                    bool_dias = 1                       # bool_dias = 1 es para indicar que hay documentos que estan proximos a vencer
                elif dias_venc <= 0:
                    bool_dias = 2                        # bool_dias = 2 es que hay documentos que ya vencieron 
                    break
        form_doc = formDOCUMENTO_CONDUCTOR()
        count_list.append(len(documentos))
        ###### LISTADO DE DOCUMENTOS FALTANTES PARA EL CONDUCTOR #####
        lista_documentos_faltantes = conductor.LISTA_DOCUMENTOS
        ###### LISTADO DE ESTADO DE DOCUMENTO MAS EL TIPO DE DOCUMENTO (POR DEFINIR SU USO)#####
        lista_estado_documentos = conductor.ESTADO_DOCUMENTOS
        for i in documentos:
            if i.DIAS_VENCIMIENTO < 1:
                lista_documentos.append(i.DCON_CTIPO)
            if i.DCON_CTIPO not in tipos_documentos:
                lista_documentos.append(i.DCON_CTIPO)
        ctx = {
            'conductor': conductor,
            'documentos': documentos,
            'bool_dias': bool_dias,
            'count_list': count_list,
            'lista_documentos': lista_documentos,
            'lista_documentos_faltantes': lista_documentos_faltantes,
            'lista_estado_documentos': lista_estado_documentos,
            'tipos_documentos': tipos_documentos,
            'list_doc': listado_documentos,
            'form_doc': form_doc
        }
        return render(request, 'home/CONDUCTOR/con_listone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')

def CONDUCTOR_DELETE(request, pk):
    try:
        if request.user.is_superuser == False and request.user.userv.UX_IS_ADMINISTRADOR_CONDUCTOR == False:                     
            return redirect('/')
        conductor = CONDUCTOR.objects.get(id = pk)
        conductor.CON_BHABILITADO = False
        conductor.save()

        messages.success(request, 'Conductor eliminado correctamente')
        return redirect('/con_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')

def CONDUCTOR_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        conductor = CONDUCTOR.objects.get(id = pk)
        conductor.CON_BHABILITADO = True
        conductor.save()

        messages.success(request, 'Conductor habilitado correctamente')
        return redirect('/con_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')

##########################################################################
########################   DOCUMENTO CONDUCTOR   #########################
##########################################################################

def DOCUMENTO_CONDUCTOR_ADDONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        conductor = CONDUCTOR.objects.get(id = pk)

        if request.method == 'POST':
            archivo = request.FILES['DCON_CRUTADOC']
            # Create a new folder with CON_CRUT if it doesn't exist

            if conductor.EP_NID.id == ID_TERRAMAR:
                base_folder = DOCUMENTOS_CONDUCTORES_TERRAMAR_PATH
            elif conductor.EP_NID.id == ID_ACEITES_SBH:
                base_folder = DOCUMENTOS_CONDUCTORE_ACEITESS_PATH

            folder_path = os.path.join(base_folder, conductor.CON_CRUT)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

            # Save the file in the new folder and change the file name to a uuid
            file_extension = archivo.name.split('.')[-1]
            unique_filename = str(uuid.uuid4()) + '.' + file_extension
            file_path = os.path.join(folder_path, unique_filename)
            with open(file_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            documentos_antiguos = actualizar_documentos_antiguos_xtipo(pk, request.POST.get('DCON_CTIPO'))
            if not documentos_antiguos:
                messages.error(request, 'Error al actualizar los documentos antiguos')
            else:
                DOCUMENTO_CONDUCTOR.objects.create(
                    EP_NID = conductor.EP_NID,
                    CON_NID_id = pk,
                    US_NID_id = request.user.id,
                    DCON_CTIPO = request.POST.get('DCON_CTIPO'),
                    DCON_FFECHAEMISION = request.POST.get('DCON_FFECHAEMISION'),
                    DCON_FFECHAVENCIMIENTO = request.POST.get('DCON_FFECHAVENCIMIENTO'),
                    DCON_CRUTADOC = file_path,
                    DCON_FFECHAREGISTRO = datetime.now()
                )
                messages.success(request, 'Documento cargado correctamente')
            return redirect(f'/con_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/con_listone/{pk}')

def DOCUMENTO_CONDUCTOR_DOWNLOAD(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "con_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DOCUMENTO_CONDUCTOR.objects.get(id = pk)
        file_path = documento.DCON_CRUTADOC
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            return redirect(f'/con_listone/{documento.CON_NID.pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')

def DOCUMENTO_CONDUCTOR_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        documento = DOCUMENTO_CONDUCTOR.objects.get(id = pk)
        documento.delete()
        messages.success(request, 'Documento eliminado correctamente')
        return redirect(f'/con_listone/{documento.CON_NID.pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')
##########################################################################
#############################  PROVEEDOR   ###############################
##########################################################################

def PROVEEDOR_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "pro_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
                
        Empresa = Verificar_empresa(request)
        object_list = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'S', EP_NID_id = Empresa)

        ctx = {

            'object_list': object_list
        }
        return render(request, 'home/PROVEEDOR/pro_listall.html', ctx)        
    except Exception as e:
        print(e)

        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PROVEEDOR_LISTALL_INHABILITADO(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "pro_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")                     
                return redirect('/')
        Empresa = Verificar_empresa(request)
        object_list = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = False, SN_CTIPO = 'S', EP_NID_id = Empresa)

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/PROVEEDOR/pro_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PROVEEDOR_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "pro_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        proveedor = SOCIONEGOCIO.objects.get(id = pk)
        list_doc = listado_y_estado_documentos_xproveedor(pk)
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Proveedor').values_list('LIS_CNOMBREDOCUMENTO', flat=True))
        documentos = DOCUMENTO_SOCIONEGOCIO.objects.filter(SN_NID = proveedor, DSN_BHABILITADO = True)
        tarifas = TARIFA_GLOBAL.objects.filter(SN_NID = proveedor)
        bool_dias = 0
        count_list = []
        lista_documentos = []
        for i in documentos:
            if i.DSN_CTIPO in tipos_documentos:
                dias_vencimiento = i.DIAS_VENCIMIENTO
                if dias_vencimiento < 31 and dias_vencimiento > 0:
                    bool_dias = 1
                elif dias_vencimiento <= 0:
                    bool_dias = 2
                    break
        ###### LISTADO DE DOCUMENTOS FALTANTES PARA EL CONDUCTOR #####
        lista_documentos_faltantes = proveedor.LISTA_DOCUMENTOS
        ###### LISTADO DE ESTADO DE DOCUMENTO MAS EL TIPO DE DOCUMENTO (POR DEFINIR SU USO)#####
        lista_estado_documentos = proveedor.ESTADO_DOCUMENTOS
        for i in documentos:
            if i.DIAS_VENCIMIENTO < 1:
                lista_documentos.append(i.DSN_CTIPO)
            if i.DSN_CTIPO not in tipos_documentos:
                lista_documentos.append(i.DSN_CTIPO)

        conductores = CONDUCTOR.objects.filter(CON_BHABILITADO = True, SN_NID = proveedor)
        camiones = CAMION.objects.filter(CAM_BHABILITADO = True, SN_NID = proveedor)
        count_list.append(len(conductores))
        count_list.append(len(camiones))
        count_list.append(len(documentos))
        count_list.append(len(tarifas))
        ctx = {
            'proveedor': proveedor,
            'tipos_documentos': tipos_documentos,
            'list_doc': list_doc,
            'bool_dias': bool_dias,
            'count_list': count_list,
            'documentos': documentos,
            'lista_documentos': lista_documentos,
            'lista_documentos_faltantes': lista_documentos_faltantes,
            'lista_estado_documentos': lista_estado_documentos,
            'conductores': conductores,
            'camiones': camiones,
            'tarifas': tarifas

        }
        return render(request, 'home/PROVEEDOR/pro_listone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pro_listall/')

def PROVEEDOR_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        proveedor = SOCIONEGOCIO.objects.get(id = pk)
        proveedor.SN_BHABILITADO = False
        proveedor.save()

        messages.success(request, 'Proveedor eliminado correctamente')
        return redirect('/pro_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pro_listall/')

def PROVEEDOR_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        proveedor = SOCIONEGOCIO.objects.get(id = pk)
        proveedor.SN_BHABILITADO = True
        proveedor.save()

        messages.success(request, 'Proveedor habilitado correctamente')
        return redirect('/pro_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pro_listall/')
    
def ajax_data_proveedor(request, pk):
    try:
        id_ruta = request.GET.get('id_ruta')

        proveedor = SOCIONEGOCIO.objects.get(id = pk)
        if not proveedor.SN_BGENERICO:
            camion = get_list_camiones_xproveedor(proveedor.id)
            camion_generico = CAMION.objects.get(id = 1)
            camion.insert(0, (camion_generico.pk, camion_generico.CAM_CPATENTE))
            conductores = get_list_conductores_xproveedor(proveedor.id)
            conductor_generico = CONDUCTOR.objects.get(id = 1)
            conductores.insert(0, (conductor_generico.pk, conductor_generico.CON_CNOMBRE + " " + conductor_generico.CON_CAPELLIDO))
            if id_ruta:
                tarifas = list(TARIFA_GLOBAL.objects.filter(EP_NID = proveedor.EP_NID, TAR_BHABILITADO = True, SN_NID = proveedor, RUT_NID = id_ruta).values_list('id', 'TAR_CNOMBRETARIFA', 'TAR_NVALOR'))
            else:
                tarifas = list(TARIFA_GLOBAL.objects.filter(EP_NID = proveedor.EP_NID, TAR_BHABILITADO = True, SN_NID = proveedor).values_list('id', 'TAR_CNOMBRETARIFA', 'TAR_NVALOR'))
            return JsonResponse({'valid': True, 'camiones': camion, 'conductores': conductores, 'tarifas': tarifas, 'generico': False})
        else:
            return JsonResponse({'valid': True, 'generico': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

##########################################################################
#######################  DOCUMENTO PROVEEDOR   ###########################
##########################################################################

def DOCUMENTO_PROVEEDOR_ADDONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "pro_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        proveedor = SOCIONEGOCIO.objects.get(id = pk)
        if request.method == 'POST':
            archivo = request.FILES['DSN_CRUTADOC']
            # Create a new folder with CON_CRUT if it doesn't exist
            if proveedor.EP_NID.id == ID_TERRAMAR:
                base_folder = DOCUMENTOS_PROVEEDORES_TERRAMAR_PATH
            elif proveedor.EP_NID.id == ID_ACEITES_SBH:
                base_folder = DOCUMENTOS_PROVEEDORES_ACEITES_PATH

            folder_path = os.path.join(base_folder, proveedor.SN_CRUT)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

            # Save the file in the new folder and change the file name to a uuid
            file_extension = archivo.name.split('.')[-1]
            unique_filename = str(uuid.uuid4()) + '.' + file_extension
            file_path = os.path.join(folder_path, unique_filename)
            with open(file_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            documentos_antiguos = actualizar_documentos_antiguos_xproveedor(pk, request.POST.get('DSN_CTIPO'))
            if not documentos_antiguos:
                messages.error(request, 'Error al actualizar los documentos antiguos')
            else:
                DOCUMENTO_SOCIONEGOCIO.objects.create(
                    EP_NID = proveedor.EP_NID,
                    SN_NID_id = pk,
                    US_NID_id = request.user.id,
                    DSN_CTIPO = request.POST.get('DSN_CTIPO'),
                    DSN_FFECHAEMISION = request.POST.get('DSN_FFECHAEMISION'),
                    DSN_FFECHAVENCIMIENTO = request.POST.get('DSN_FFECHAVENCIMIENTO'),
                    DSN_CRUTADOC = file_path,
                    DSN_FFECHAREGISTRO = datetime.now()
                )
                messages.success(request, 'Documento cargado correctamente')
        return redirect(f'/pro_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/pro_listone/{pk}')

def DOCUMENTO_PROVEEDOR_DOWNLOAD(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "pro_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DOCUMENTO_SOCIONEGOCIO.objects.get(id = pk)
        file_path = documento.DSN_CRUTADOC
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            return redirect(f'/pro_listone/{documento.SN_NID.pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pro_listall/')

##########################################################################
##############################  CLIENTE   ################################
##########################################################################

def CLIENTE_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cli_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        object_list = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'C', EP_NID_id = Empresa)

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CLIENTE/cli_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CLIENTE_LISTALL_INHABILITADO(request):
    try:
        if request.user.is_superuser == False:      
            usuario = request.user.id     
            if not validar_perfiles_activos(usuario, "cli_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")        
                return redirect('/')
        Empresa = Verificar_empresa(request)
        object_list = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = False, SN_CTIPO = 'C', EP_NID_id = Empresa)        

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CLIENTE/cli_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CLIENTE_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cli_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        cliente = SOCIONEGOCIO.objects.get(id = pk)
        listado_documentos = listado_y_estado_documentos_xcliente(pk)
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_CGRUPO = 'Cliente', LIS_BHABILITADO = True).values_list('LIS_CNOMBREDOCUMENTO', flat = True))
        documentos = list(DOCUMENTO_SOCIONEGOCIO.objects.filter(SN_NID = pk, DSN_BHABILITADO = True))
        tarifas = len(TARIFA_GLOBAL.objects.filter(SN_NID = cliente))
        bool_dias = 0
        count_list = [tarifas, len(documentos)]
        lista_documentos = []
        for i in documentos:
            if i.DSN_CTIPO in tipos_documentos:
                dias_vencimiento = i.DIAS_VENCIMIENTO
                if dias_vencimiento < 31 and dias_vencimiento > 0:
                    bool_dias = 1
                elif dias_vencimiento <= 0:
                    bool_dias = 2
                    break
        ###### LISTADO DE DOCUMENTOS FALTANTES PARA EL CONDUCTOR #####
        lista_documentos_faltantes = cliente.LISTA_DOCUMENTOS
        ###### LISTADO DE ESTADO DE DOCUMENTO MAS EL TIPO DE DOCUMENTO (POR DEFINIR SU USO)#####
        lista_estado_documentos = cliente.ESTADO_DOCUMENTOS

        for i in documentos:
            if i.DIAS_VENCIMIENTO < 1:
                lista_documentos.append(i.DSN_CTIPO)
            if i.DSN_CTIPO not in tipos_documentos:
                lista_documentos.append(i.DSN_CTIPO)
        ctx = {
            'cliente': cliente,
            'list_doc': listado_documentos,
            'bool_dias': bool_dias,
            'count_list': count_list,
            'documentos': documentos,
            'tipos_documentos': tipos_documentos,
            'lista_documentos_faltantes': lista_documentos_faltantes,
            'lista_estado_documentos': lista_estado_documentos,
            'lista_documentos': lista_documentos
        }
        return render(request, 'home/CLIENTE/cli_listone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cli_listall/')

def CLIENTE_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        cliente = SOCIONEGOCIO.objects.get(id = pk)
        cliente.SN_BHABILITADO = False
        cliente.save()

        messages.success(request, 'Cliente eliminado correctamente')
        return redirect('/cli_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cli_listall/')

def CLIENTE_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        cliente = SOCIONEGOCIO.objects.get(id = pk)
        cliente.SN_BHABILITADO = True
        cliente.save()

        messages.success(request, 'Cliente habilitado correctamente')
        return redirect('/cli_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cli_listall/')

def ajax_get_data_cliente(request, pk):
    try:
        tarifas = list(TARIFA_GLOBAL.objects.filter(SN_NID = pk, TAR_BHABILITADO = True).values_list('id', 'TAR_CNOMBRETARIFA'))
        rutas = list(RUTA.objects.filter(SN_NID = pk, RUT_BHABILITADO = True).values_list('id', 'RUT_CNOMBRE'))
        return JsonResponse({'tarifas': tarifas, 'rutas': rutas, 'valid': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

##########################################################################
#######################   DOCUMENTO CLIENTE   ############################
##########################################################################

def DOCUMENTO_CLIENTE_ADDONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cli_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        cliente = SOCIONEGOCIO.objects.get(id = pk)
        if request.method == 'POST':
            archivo = request.FILES['DSN_CRUTADOC']
            # Create a new folder with CON_CRUT if it doesn't exist
            if cliente.EP_NID.id == ID_TERRAMAR:
                base_folder = DOCUMENTOS_CLIENTES_TERRAMAR_PATH
            elif cliente.EP_NID.id == ID_ACEITES_SBH:
                base_folder = DOCUMENTOS_CLIENTES_ACEITES_PATH
            folder_path = os.path.join(base_folder, cliente.SN_CRUT)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

            # Save the file in the new folder and change the file name to a uuid
            file_extension = archivo.name.split('.')[-1]
            unique_filename = str(uuid.uuid4()) + '.' + file_extension
            file_path = os.path.join(folder_path, unique_filename)
            with open(file_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            documentos_antiguos = actualizar_documentos_antiguos_xcliente(pk, request.POST.get('DSN_CTIPO'))
            if not documentos_antiguos:
                messages.error(request, 'Error al actualizar los documentos antiguos')
            else:
                DOCUMENTO_SOCIONEGOCIO.objects.create(
                    EP_NID = cliente.EP_NID,
                    SN_NID_id = pk,
                    US_NID_id = request.user.id,
                    DSN_CTIPO = request.POST.get('DSN_CTIPO'),
                    DSN_FFECHAEMISION = request.POST.get('DSN_FFECHAEMISION'),
                    DSN_FFECHAVENCIMIENTO = request.POST.get('DSN_FFECHAVENCIMIENTO'),
                    DSN_CRUTADOC = file_path,
                    DSN_FFECHAREGISTRO = datetime.now()
                )
                messages.success(request, 'Documento cargado correctamente')
        return redirect(f'/cli_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cli_listall/')

def DOCUMENTO_CLIENTE_DOWNLOAD(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cli_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DOCUMENTO_SOCIONEGOCIO.objects.get(id = pk)
        file_path = documento.DSN_CRUTADOC
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            return redirect(f'/cli_listone/{documento.SN_NID.pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cli_listall/')

##########################################################################
##############################  CAMION   #################################
##########################################################################

def CAMION_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        if request.user.userv.UX_IS_PROVEEDOR:
            usuario_socionegocio = USUARIO_SOCIONEGOCIO.objects.get(US_NID_id = request.user.id)
            camiones = CAMION.objects.filter(CAM_BHABILITADO = True, EP_NID_id = Empresa, SN_NID_id = usuario_socionegocio.SN_NID_id)
        else:
            camiones = CAMION.objects.filter(CAM_BHABILITADO = True, EP_NID_id = Empresa)

        # Procesar el estado de documentos para cada camión
        object_list = []
        for camion in camiones:
            # Copiar el objeto camión para no modificar el original
            camion_data = camion
            estado_docs = {
                'estado': 'CORRECTO',
                'clase': 'text-success',
                'icono': 'fa-check'
            }

            if camion.LISTA_DOCUMENTOS and len(camion.LISTA_DOCUMENTOS) > 0:
                estado_docs = {
                    'estado': 'Faltan documentos',
                    'clase': 'text-danger',
                    'icono': 'fa-times'
                }
            else:
                tiene_vencidos = False
                tiene_por_vencer = False
                
                for doc in camion.ESTADO_DOCUMENTOS:
                    if doc[1] <= 0:  # Documento vencido
                        tiene_vencidos = True
                        break
                    elif doc[1] <= 30:  # Documento por vencer (30 días o menos)
                        tiene_por_vencer = True

                if tiene_vencidos:
                    estado_docs = {
                        'estado': 'Documentos vencidos',
                        'clase': 'text-danger',
                        'icono': 'fa-times'
                    }
                elif tiene_por_vencer:
                    estado_docs = {
                        'estado': 'Documentos próximos a vencer',
                        'clase': 'text-warning',
                        'icono': 'fa-exclamation'
                    }

            # Agregar el estado de documentos al objeto camión
            camion_data.estado_documentos = estado_docs
            object_list.append(camion_data)

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CAMION/cam_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CAMION_LISTALL_INHABILITADO(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")                
                return redirect('/')
        object_list = CAMION.objects.filter(CAM_BHABILITADO = False)

        ctx = {
            'object_list': object_list
        }

        return render(request, 'home/CAMION/cam_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CAMION_ADDONE(request):   
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        if request.method == 'POST':
            empresa_user = EMPRESA.objects.get(id = Empresa)
            post_data = request.POST.copy()
            post_data['EP_NID'] = empresa_user
            form = formCAMION(post_data)
            documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Camion')
            if form.is_valid():
                patente = form.instance.CAM_CPATENTE.upper()

                camion_duplicado = CAMION.objects.filter(CAM_CPATENTE = patente, CAM_BHABILITADO = True).exists()
                if camion_duplicado:
                    messages.error(request, 'Error al guardar el camión, patente duplicada')
                    return redirect('/cam_addone')

                form.instance.US_NID = request.user
                form.instance.CAM_FFECHAREGISTRO = datetime.now()
                form.save()

                camion_id = form.instance.id
                files = request.FILES
                for documento in documentos:
                    if files.get(f'DCON_CRUTADOC{str(documento.pk)}'):
                        tipo = request.POST.get(f'DCA_CTIPO{documento.pk}')
                        fecha_emision = request.POST.get(f'DCA_FFECHAEMISION{documento.pk}')
                        fecha_vencimiento = request.POST.get(f'DCA_FFECHAVENCIMIENTO{documento.pk}')
                        archivo = request.FILES.get(f'DCON_CRUTADOC{str(documento.pk)}')

                        # Create a new folder with CAM_CPATENTE if it doesn't exist
                        if form.instance.EP_NID.id == ID_TERRAMAR:
                            base_folder = DOCUMENTOS_CAMIONES_TERRAMAR_PATH
                        elif form.instance.EP_NID.id == ID_ACEITES_SBH:
                            base_folder = DOCUMENTOS_CAMIONES_ACEITES_PATH
                        folder_path = os.path.join(base_folder, patente)
                        if not os.path.exists(folder_path):
                            os.makedirs(folder_path)

                        # Save the file in the new folder and change the file name to a uuid
                        file_extension = archivo.name.split('.')[-1]
                        unique_filename = str(uuid.uuid4()) + '.' + file_extension
                        file_path = os.path.join(folder_path, unique_filename)
                        with open(file_path, 'wb+') as destination:
                            for chunk in archivo.chunks():
                                destination.write(chunk)
                        
                        DOCUMENTO_CAMION.objects.create(
                            EP_NID_id = form.instance.EP_NID,
                            CAM_NID_id = camion_id,
                            US_NID_id = request.user.id,
                            DCA_CTIPO = tipo,
                            DCA_FFECHAEMISION = fecha_emision,
                            DCA_FFECHAVENCIMIENTO = fecha_vencimiento,
                            DCA_CRUTADOC = file_path,
                            DCA_FFECHAREGISTRO = datetime.now()
                        )

                messages.success(request, 'Camión guardado correctamente')
                return redirect('/cam_listall/')
            else:
                messages.error(request, 'Error al guardar el camión')
                return redirect('/cam_addone/')
        
        form = formCAMION()
        form.fields['SN_NID'].choices = listarOpcionesTabla('CAST("id" AS text)', ''' "SN_CRUT" || ' - ' || "SN_CRAZONSOCIAL" ''', 'SOCIONEGOCIO', '', '', '''"SN_CTIPO" = 'S' AND "SN_BHABILITADO" = TRUE ''')
        documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Camion')
        ctx = {
            'form': form,
            'documentos': documentos
        }
        return render(request, 'home/CAMION/cam_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def CAMION_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        camion = CAMION.objects.get(id = pk)
        documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Camion')
        if request.method == 'POST':
            form = formCAMION(request.POST, instance=camion)

            patente = form.instance.CAM_CPATENTE.upper()
            camion_duplicado = CAMION.objects.filter(CAM_CPATENTE = patente, CAM_BHABILITADO = True).exclude(id = pk).exists()
            if camion_duplicado:
                messages.error(request, 'Error al guardar el camión, patente duplicada')
                return redirect(f'/cam_listone/{pk}')
            
            form.instance.CAM_CPATENTE = patente
            if form.is_valid():
                files = request.FILES
                for documento in documentos:
                    if files.get(f'DCON_CRUTADOC{str(documento.pk)}'):
                        tipo = request.POST.get(f'DCA_CTIPO{documento.pk}')
                        fecha_emision = request.POST.get(f'DCA_FFECHAEMISION{documento.pk}')
                        fecha_vencimiento = request.POST.get(f'DCA_FFECHAVENCIMIENTO{documento.pk}')
                        archivo = request.FILES.get(f'DCON_CRUTADOC{str(documento.pk)}')

                        # Create a new folder with CAM_CPATENTE if it doesn't exist
                        if camion.EP_NID.id == ID_TERRAMAR:
                            base_folder = DOCUMENTOS_CAMIONES_TERRAMAR_PATH
                        elif camion.EP_NID.id == ID_ACEITES_SBH:
                            base_folder = DOCUMENTOS_CAMIONES_ACEITES_PATH

                        folder_path = os.path.join(base_folder, patente)
                        if not os.path.exists(folder_path):
                            os.makedirs(folder_path)

                        # Save the file in the new folder and change the file name to a uuid
                        file_extension = archivo.name.split('.')[-1]
                        unique_filename = str(uuid.uuid4()) + '.' + file_extension
                        file_path = os.path.join(folder_path, unique_filename)
                        with open(file_path, 'wb+') as destination:
                            for chunk in archivo.chunks():
                                destination.write(chunk)
                        
                        DOCUMENTO_CAMION.objects.create(
                            EP_NID = camion.EP_NID,
                            CA_NID = camion,
                            US_NID_id = request.user.id,
                            DCA_CTIPO = tipo,
                            DCA_FFECHAEMISION = fecha_emision,
                            DCA_FFECHAVENCIMIENTO = fecha_vencimiento,
                            DCA_CRUTADOC = file_path,
                            DCA_FFECHAREGISTRO = datetime.now()
                        )
                form.save()
                messages.success(request, 'Camión actualizado correctamente')
                return redirect(f'/cam_listone/{pk}')

        form = formCAMION(instance=camion)
        form.fields['SN_NID'].choices = listarOpcionesTabla('CAST("id" AS text)', ''' "SN_CRUT" || ' - ' || "SN_CRAZONSOCIAL" ''', 'SOCIONEGOCIO', '', '', '''"SN_CTIPO" = 'S' AND "SN_BHABILITADO" = TRUE ''')
        documentos_cargados = listar_documentos_camion(pk)
        ctx = {
            'form': form,
            'documentos_cargados': documentos_cargados,
            'documentos': documentos
        }
        return render(request, 'home/CAMION/cam_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall')

def CAMION_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        camion = CAMION.objects.get(id = pk)

        listado_documentos = listado_y_estado_documentos_xcamion(pk)
        tipos_documentos = list(LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Camion').values_list('LIS_CNOMBREDOCUMENTO', flat=True))
        documentos = DOCUMENTO_CAMION.objects.filter(CA_NID = pk, DCA_BHABILITADO = True)

        count_list = []
        lista_documentos = []
        bool_dias = 0

        for doc in documentos:
            if doc.DCA_CTIPO in tipos_documentos:
                dias_vencimiento = doc.DIAS_VENCIMIENTO
                if dias_vencimiento < 31 and dias_vencimiento > 0:
                    bool_dias = 1
                elif dias_vencimiento <= 0:
                    bool_dias = 2
                    break
        
        count_list.append(len(documentos))
        ###### LISTADO DE DOCUMENTOS FALTANTES PARA EL CONDUCTOR #####
        lista_documentos_faltantes = camion.LISTA_DOCUMENTOS
        ###### LISTADO DE ESTADO DE DOCUMENTO MAS EL TIPO DE DOCUMENTO (POR DEFINIR SU USO)#####
        lista_estado_documentos = camion.ESTADO_DOCUMENTOS
        for i in documentos:
            if i.DIAS_VENCIMIENTO < 1:
                lista_documentos.append(i.DCA_CTIPO)
            if i.DCA_CTIPO not in tipos_documentos:
                lista_documentos.append(i.DCA_CTIPO)
        ctx = {
            'camion': camion,
            'list_doc': listado_documentos,
            'count_list': count_list,
            'lista_documentos': lista_documentos,
            'bool_dias': bool_dias,
            'lista_documentos_faltantes': lista_documentos_faltantes,
            'lista_estado_documentos': lista_estado_documentos,
            'tipos_documentos': tipos_documentos,
            'documentos': documentos
        }
        return render(request, 'home/CAMION/cam_listone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def CAMION_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_delete"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        camion = CAMION.objects.get(id = pk)
        camion.CAM_BHABILITADO = False
        camion.save()

        messages.success(request, 'Camión eliminado correctamente')
        return redirect('/cam_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def CAMION_DELETE_SELECTED(request):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        camiones = CAMION.objects.filter(id__in = request.POST.getlist('selectedIds'))
        for camion in camiones:
            camion.CAM_BHABILITADO = False
            camion.save()

        messages.success(request, 'Camión eliminado correctamente')
        return redirect('/cam_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def CONDUCTOR_DELETE_SELECTED(request):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        conductores = CONDUCTOR.objects.filter(id__in = request.POST.getlist('selectedIds'))
        for conductor in conductores:
            conductor.CON_BHABILITADO = False
            conductor.save()

        messages.success(request, 'Conductor eliminado correctamente')
        return redirect('/con_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/con_listall/')
    
def CAMION_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        camion = CAMION.objects.get(id = pk)
        camion.CAM_BHABILITADO = True
        camion.save()
        messages.success(request, 'Camión habilitado correctamente')
        return redirect('/cam_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def ajax_get_data_conductor_xcamion(request, pk):
    try:
        camion = CAMION.objects.get(id = pk)
        last_conductor = get_last_conductor_xcamion(camion.pk, camion.SN_NID.pk)
        return JsonResponse({'valid': True, 'conductor': last_conductor})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

##########################################################################
#########################  DOCUMENTO CAMION   ############################
##########################################################################

def DOCUMENTO_CAMION_ADDONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        camion = CAMION.objects.get(id = pk)
        if request.method == 'POST':
            archivo = request.FILES.get('DCA_CRUTADOC')
            # Create a new folder with CON_CRUT if it doesn't exist
            if camion.EP_NID.id == ID_TERRAMAR:
                base_folder = DOCUMENTOS_CAMIONES_TERRAMAR_PATH
            elif camion.EP_NID.id == ID_ACEITES_SBH:
                base_folder = DOCUMENTOS_CAMIONES_ACEITES_PATH

            folder_path = os.path.join(base_folder, camion.CAM_CPATENTE)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

            # Save the file in the new folder and change the file name to a uuid
            file_extension = archivo.name.split('.')[-1]
            unique_filename = str(uuid.uuid4()) + '.' + file_extension
            file_path = os.path.join(folder_path, unique_filename)
            with open(file_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            documentos_antiguos = actualizar_documentos_antiguos_xcamion(pk, request.POST.get('DCA_CTIPO'))
            if not documentos_antiguos:
                messages.error(request, 'Error al guardar el documento')
            else:
                DOCUMENTO_CAMION.objects.create(
                    EP_NID = camion.EP_NID,
                    CA_NID = camion,
                    US_NID_id = request.user.id,
                    DCA_CTIPO = request.POST.get('DCA_CTIPO'),
                    DCA_FFECHAEMISION = request.POST.get('DCA_FFECHAEMISION'),
                    DCA_FFECHAVENCIMIENTO = request.POST.get('DCA_FFECHAVENCIMIENTO'),
                    DCA_CRUTADOC = file_path,
                    DCA_FFECHAREGISTRO = datetime.now()
                )
                messages.success(request, 'Documento guardado correctamente')
            return redirect(f'/cam_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def DOCUMENTO_CAMION_DOWNLOAD(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cam_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DOCUMENTO_CAMION.objects.get(id = pk)
        file_path = documento.DCA_CRUTADOC
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            return redirect('/cam_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

def DOCUMENTO_CAMION_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        documento = DOCUMENTO_CAMION.objects.get(id = pk)
        documento.delete()
        messages.success(request, 'Documento eliminado correctamente')
        return redirect(f'/cam_listone/{documento.CA_NID.pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cam_listall/')

##########################################################################
############################  DOCUMENTO   ################################
##########################################################################

def DOCUMENTO_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "doc_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')                    
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        tipos_documentos = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, EP_NID_id = Empresa)
        ctx = {
            'object_list': tipos_documentos
        }
        return render(request, 'home/DOCUMENTO/doc_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def DOCUMENTO_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        if request.method == 'POST':
            Empresa = Verificar_empresa(request) 
            empresa_user = EMPRESA.objects.get(id = Empresa)
            post_data = request.POST.copy()
            post_data['EP_NID'] = empresa_user            
            form = formDOCUMENTO(post_data or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.LIS_FFECHAREGISTRO = datetime.now()
                form.save()
                messages.success(request, 'Documento guardado correctamente')
                return redirect('/doc_listall/') 
            else:
                messages.error(request, 'Error al guardar el documento')
                return redirect('/doc_addone/')
        form = formDOCUMENTO()
        ctx = {
            'form': form
        }
        return render(request, 'home/DOCUMENTO/doc_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/doc_listall/')

def DOCUMENTO_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        documento = LISTADO_DOCUMENTO.objects.get(id = pk)
        if request.method == 'POST':
            form = formDOCUMENTO(request.POST, instance=documento)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.LIS_FFECHAREGISTRO = datetime.now()
                form.save()
                messages.success(request, 'Documento actualizado correctamente')
                return redirect(f'/doc_listall/')

        form = formDOCUMENTO(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/DOCUMENTO/doc_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/doc_listall/')

def DOCUMENTO_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        documento = LISTADO_DOCUMENTO.objects.get(id = pk)
        documento.LIS_BHABILITADO = False
        documento.save()

        messages.success(request, 'Documento eliminado correctamente')
        return redirect('/doc_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/doc_listall')

##########################################################################
############################  CAMPO   ####################################
##########################################################################

def CAMPO_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        tipos_documentos = CAMPO.objects.filter(
            EP_NID_id = Empresa        )
        ctx = {
            'object_list': tipos_documentos
        }
        return render(request, 'home/CAMPO/camp_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CAMPO_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        
        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = Empresa

            form = formCAMPO(post_data or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                campo = form.save()
                if form.instance.CA_BVALIDARSAP:
                    CAMPO_OPCION.objects.create(
                        EP_NID_id = Empresa,
                        US_NID = request.user,
                        CAMP_NID = campo,
                        CA_CTABLA = request.POST.get('CA_CTABLA'),
                        CA_CNOMBRECAMPO = request.POST.get('CA_CNOMBRECAMPO'),
                        CA_BHABILITADO = True
                    )
                messages.success(request, 'Campo guardado correctamente')
                return redirect('/camp_listall/') 
            else:
                print(form.errors)
                messages.error(request, 'Error al guardar el Campo')
                return redirect('/camp_addone/')
        form = formCAMPO()
        form_opciones = formCAMPO_OPCIONES()
        ctx = {
            'form': form,
            'form_opciones': form_opciones
        }
        return render(request, 'home/CAMPO/camp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/camp_listall/')

def CAMPO_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = CAMPO.objects.get(id = pk)
        if request.method == 'POST':
            form = formCAMPO(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Campo actualizado correctamente')
                return redirect(f'/camp_listall/')

        form = formCAMPO(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/CAMPO/camp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/camp_listall/')

def CAMPO_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        campo = CAMPO.objects.get(id = pk)
        campo.CA_BHABILITADO = False
        campo.save()

        messages.success(request, 'Campo eliminado correctamente')
        return redirect('camp_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('camp_listall')

##########################################################################
#######################  CALENDARIO  #####################################
##########################################################################

def CALENDARIO_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cal_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)     
        planificaciones = get_list_planificaciones(Empresa)

        events = []
        if planificaciones:
            
            for planificacion in planificaciones:
                event = {
                    'id': str(planificacion[0]),
                    'title':f"🚩Planificación #{str(planificacion[0])}: {str(planificacion[4])}/{str(planificacion[3])} ",
                    'start': datetime.strptime(planificacion[1], '%Y-%m-%dT%H:%M:%S'),
                    'end': datetime.strptime(planificacion[2], '%Y-%m-%dT%H:%M:%S'),
                    'url': f'/pla_listone/{str(planificacion[0])}',
                    'borderColor': '#25A2E0',
                    'backgroundColor': '#25A2E0',
                }
                events.append(event)
        mes = request.GET.get('mes', datetime.now().month)
        ano = request.GET.get('ano', datetime.now().year)

        # eventos = CALENDARIO.objects.filter(CA_NMES=mes, CA_NANO=ano)
        eventos = CALENDARIO.objects
        if eventos.exists():
            feriados = eventos.filter(CA_BHABILITADO=True, CA_BIS_FERIADO=True, EP_NID_id = Empresa)
            horarios_distintos = eventos.filter(CA_BHABILITADO=True, CA_BIS_FERIADO=False, CA_CNOMBRE = '', EP_NID_id = Empresa)
        else:
            feriados = horarios_distintos = CALENDARIO.objects.none()
        
        # Obtener los días del mes actual
        num_dias = calendar.monthrange(int(ano), int(mes))[1]
        dias_mes = [datetime(int(ano), int(mes), dia) for dia in range(1, num_dias + 1)]

        context = {
            'feriados': feriados,
            'horarios_distintos': horarios_distintos,
            'dias_mes': dias_mes,
            'events': events,
            'mes': int(mes),
            'ano': int(ano),
        }
        return render(request, 'home/CALENDARIO/cal_listall.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CALENDARIO_ADD_HOLIDAY(request):
    try:        
        # TODO : CONSUULTAR QUE USUARIOS PUEDEN AGREGAR FERIADOS 
        if request.user.is_superuser == False:                                 
            return redirect('/')
        if request.method == 'POST':
            if request.user.is_superuser == True:
                id_empresa = request.GET.get('id_empresa', '1')
            else:
                if request.user.userv.UX_IS_TERRAMAR == True and request.user.userv.UX_IS_ACEITES == False:
                    id_empresa = '1'
                elif request.user.userv.UX_IS_TERRAMAR == False and request.user.userv.UX_IS_ACEITES == True:
                    id_empresa = '2'
                elif request.user.userv.UX_IS_TERRAMAR == True and request.user.userv.UX_IS_ACEITES == True:
                    id_empresa = request.GET.get('id_empresa', '1')
            title = request.POST.get('title')
            start_date = datetime.strptime(request.POST.get('start'), '%Y-%m-%d').date()
            end_date = request.POST.get('end')
            if end_date:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            else:
                end_date = start_date

            if end_date < start_date:
                messages.error(request, 'La fecha de finalización debe ser mayor o igual a la fecha de inicio.')
                return redirect('cal_listall')

            user = request.user
            current_date = start_date

            while current_date <= end_date:
                # Verificar si existe alguna planificación para ese día
                if PLANIFICACION.objects.filter(PL_FFECHAINICIO__date=current_date, PL_FFECHAFIN__date=current_date).exists():
                    messages.error(request, f'Ya existe una planificación para el día {current_date}.')
                    return redirect('cal_listall')

                CALENDARIO.objects.create(
                    US_NID=user,
                    EP_NID_id=int(id_empresa),
                    CA_CNOMBRE=title,
                    CA_NDIA=current_date.day,
                    CA_NMES=current_date.month,
                    CA_NANO=current_date.year,
                    CA_NCANTIDADCUPOS=0,
                    CA_BIS_FERIADO=True,
                    CA_BHABILITADO=True
                )
                current_date += timedelta(days=1)  # Incrementa el día
            messages.success(request, f'Feriado agregado exitosamente.')
            return redirect('cal_listall')
        return redirect('cal_listall')

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cal_listall/')

def CALENDARIO_MODIFY_HOURS(request):
    try:
        # TODO : CONSUULTAR QUE USUARIOS PUEDEN AGREGAR FERIADOS 
        if request.user.is_superuser == False:                                 
            return redirect('/')
        if request.method == 'POST':
            if request.user.is_superuser == True:
                id_empresa = request.GET.get('id_empresa', '1')
            else:
                if request.user.userv.UX_IS_TERRAMAR == True and request.user.userv.UX_IS_ACEITES == False:
                    id_empresa = '1'
                elif request.user.userv.UX_IS_TERRAMAR == False and request.user.userv.UX_IS_ACEITES == True:
                    id_empresa = '2'
                elif request.user.userv.UX_IS_TERRAMAR == True and request.user.userv.UX_IS_ACEITES == True:
                    id_empresa = request.GET.get('id_empresa', '1')
            modify_type = request.POST.get('type')
            start_time = request.POST.get('startTime')
            end_time = request.POST.get('endTime')

            # Validación de la hora de término
            if datetime.strptime(end_time, '%H:%M').time() <= datetime.strptime(start_time, '%H:%M').time():
                messages.error(request, 'La hora de término debe ser mayor que la hora de inicio.')
                return redirect('cal_listall')

            user = request.user
            print(f"Tipo de modificación: {modify_type}, Hora de inicio: {start_time}, Hora de cierre: {end_time}")

            if modify_type == 'single':
                date = datetime.strptime(request.POST.get('date'), '%Y-%m-%d').date()
                print(f"Modificando el día: {date}")
                # Verificar si es un feriado
                feriado = CALENDARIO.objects.filter(
                    CA_NDIA=date.day,
                    CA_NMES=date.month,
                    CA_NANO=date.year,
                    CA_BIS_FERIADO=True
                ).exists()
                print('feriado',feriado)
                if feriado:
                    messages.error(request, 'No se puede modificar un feriado.')
                    return redirect('cal_listall')
                planificacion = PLANIFICACION.objects.filter(
                    PL_FFECHAINICIO__date=date,
                    EP_NID_id=int(id_empresa)
                ).first()
                if planificacion and (planificacion.PL_FFECHAINICIO.time() < datetime.strptime(start_time, '%H:%M').time() or
                        planificacion.PL_FFECHAFIN.time() > datetime.strptime(end_time, '%H:%M').time()):
                    messages.error(request, 'La planificación existente no está dentro del nuevo horario.')
                    return redirect('cal_listall')
                CALENDARIO.objects.update_or_create(
                    US_NID=user,
                    EP_NID_id=int(id_empresa),
                    CA_CNOMBRE='',
                    CA_NDIA=date.day,
                    CA_NMES=date.month,
                    CA_NANO=date.year,
                    defaults={
                        'CA_NCANTIDADCUPOS': 32,
                        'CA_FHORA_APERTURA': start_time,
                        'CA_FHORA_CIERRE': end_time,
                        'CA_BHABILITADO': True
                    }
                )
                messages.success(request, f'Horario modificado exitosamente para el día {date}.')
            elif modify_type == 'range':
                start_date = datetime.strptime(request.POST.get('start'), '%Y-%m-%d').date()
                end_date = datetime.strptime(request.POST.get('end'), '%Y-%m-%d').date()
                print(f"Modificando desde: {start_date} hasta: {end_date}")

                current_date = start_date
                print(type(end_date))
                print(type(current_date))
                while current_date <= end_date:
                    print(f"Actualizando día: {current_date}")
                    # Verificar si es un feriado
                    feriado = CALENDARIO.objects.filter(
                        CA_NDIA=current_date.day,
                        CA_NMES=current_date.month,
                        CA_NANO=current_date.year,
                        CA_BIS_FERIADO=True
                    ).exists()
                    if feriado:
                        messages.error(request, f'No se puede modificar un feriado en el día {current_date}.')
                        current_date += timedelta(days=1)
                        continue
                    planificacion = PLANIFICACION.objects.filter(
                        PL_FFECHAINICIO__date=current_date,
                        EP_NID_id=int(id_empresa)
                    ).first()
                    if planificacion and (planificacion.PL_FFECHAINICIO.time() < datetime.strptime(start_time, '%H:%M').time() or
                            planificacion.PL_FFECHAFIN.time() > datetime.strptime(end_time, '%H:%M').time()):
                        messages.error(request, f'La planificación existente no está dentro del nuevo horario para el día {current_date}.')
                        current_date += timedelta(days=1)
                        continue
                    CALENDARIO.objects.update_or_create(
                        US_NID=user,
                        EP_NID_id=int(id_empresa),
                        CA_CNOMBRE='',
                        CA_NDIA=current_date.day,
                        CA_NMES=current_date.month,
                        CA_NANO=current_date.year,
                        defaults={
                            'CA_NCANTIDADCUPOS': 1,
                            'CA_FHORA_APERTURA': start_time,
                            'CA_FHORA_CIERRE': end_time,
                            'CA_BHABILITADO': True
                        }
                    )
                    messages.success(request, f'Horario modificado exitosamente.')
                    current_date += timedelta(days=1)

            return redirect('cal_listall')
        return redirect('cal_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/cal_listall/')

def ajax_calendario_addone(request):
    try:
        id_empresa = Verificar_empresa(request) 
        empresa = EMPRESA.objects.get(pk = id_empresa)

        dia = request.POST.get('dia')
        mes = request.POST.get('mes')
        ano = request.POST.get('ano')
        cupos_maximos = int(request.POST.get('cupos'))
        hora_inicio = request.POST.get('hora_inicio')
        hora_termino = request.POST.get('hora_termino')

        if hora_inicio >= hora_termino:
            return JsonResponse({
                'valid': False,
                'msg': 'La hora de apertura no puede ser mayor o igual a la hora de cierre'
            })
        
        if not cupos_maximos:
            return JsonResponse({
                'valid': False,
                'msg': 'Debe entregar un número '
            })

        calendario = CALENDARIO.objects.create(
            US_NID = request.user,
            EP_NID = empresa,
            CA_CNOMBRE = f'{empresa.EP_CRAZONSOCIAL}: {dia}/{mes}/{ano}',
            CA_FHORA_APERTURA = hora_inicio,
            CA_FHORA_CIERRE = hora_termino,
            CA_NDIA = dia,
            CA_NMES = mes,
            CA_NANO = ano,
            CA_NCANTIDADCUPOS = cupos_maximos,
            CA_BIS_FERIADO = False
        )
        return JsonResponse({
            'valid': True,
            'id_calendario': calendario.pk

        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

##########################################################################
############################  ETAPA   ####################################
##########################################################################

def ETAPA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "etap_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        etapa = ETAPA.objects.filter(EP_NID = Empresa)        
        ctx = {
            'object_list': etapa
        }
        return render(request, 'home/ETAPA/etap_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def ETAPA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "etap_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
            
        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = Empresa

            form = formETAPA(post_data or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.ET_FFECHAREGISTRO = datetime.now()
                form.save()
                messages.success(request, 'Etapa guardada correctamente')
                return redirect('/etap_listall/') 
            else:
                messages.error(request, 'Error al guardar la Etapa')
                return redirect('/etap_addone/')
        form = formETAPA()
        form.fields["ET_CENDPOINT"].widget.choices = listarOpcionesTabla('"PM_CDESCRIPCION"', '"PM_CVALOR1"', 'PARAMETRO', '', '', '''"PM_CGRUPO" = 'ENDPOINT' ''')
        ctx = {
            'form': form
        }
        return render(request, 'home/ETAPA/etap_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/etap_listall/')

def ETAPA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "etap_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = ETAPA.objects.get(id = pk)
        if request.method == 'POST':
            form = formETAPA(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Etapa actualizada correctamente')
                return redirect(f'/etap_listall/')

        form = formETAPA(instance=documento)
        ctx = {
            'form': form,
            'documento': documento
        }
        return render(request, 'home/ETAPA/etap_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/etap_listall/')

def ETAPA_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        etapa = ETAPA.objects.get(id = pk)
        etapa.delete()

        messages.success(request, 'Etapa eliminada correctamente')
        return redirect('etap_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('etap_listall')

def ETAPA_PREVIEW(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "etapa_preview"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        etapa = GetPreviewEtapa(pk)
        datos_etapa = ETAPA.objects.get(id = pk)
        if etapa is not None:
            etapa_data = []
            for campo in etapa:
                datos = []
                if campo[0].lower() == 'lista':
                    try:
                        datos = QueryParam(campo[5])
                    except Exception as e:
                        print("Error al ejecutar la consulta",e)
                        messages.warning(request, f'Error, {str(e)}')

                    
                etapa_data.append(
                    {
                        'TYPE': campo[0].lower(),
                        'DEFAULT_VALUE': campo[1],
                        'PLACEHOLDER': campo[2],
                        'LARGO': campo[3],
                        'OBLIGATORIO': campo[4],
                        'DATOS':datos
                    } )
            response_data = {
                'status': 'success',
                'data': etapa_data,
                'data_etapa': datos_etapa
            }

        return render(request,'home/ETAPA/etapa_preview.html',response_data)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('etap_listall')

##########################################################################
############################  SECUENCIA   ################################
##########################################################################

def SECUENCIA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "sec_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        secuencia = SECUENCIA.objects.filter(EP_NID_id = Empresa)
        ctx = {
            'object_list': secuencia
        }
        return render(request, 'home/SECUENCIA/sec_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def SECUENCIA_DUPLICAR(request):
    try:
        # primero obtenemos los datos asociados a la secuencia
        id_secuencia_original = SECUENCIA.objects.get(id = request.POST['id_secuencia'])
        # segundo,obtenemos los datos asociados al detalle de la secuencia
        detalle_secuencia_original = DETALLE_SECUENCIA.objects.filter(SC_NID = id_secuencia_original, SE_BHABILITADO = True)
        # tercero, duplicamos la secuencia,a la cual le asignamos todos los datos obtenidos desde el original
        try:
            secuencia_duplicada = SECUENCIA.objects.create(
                SE_CCODIGO = request.POST['codigo_secuencia'],
                SE_CNOMBRE= request.POST['nombre_secuencia'],
                EP_NID = id_secuencia_original.EP_NID,
                US_NID = request.user,
                SE_FFECHAREGISTRO = datetime.now(),
                SE_BHABILITADO = True
            )
        except Exception as e:
            print(f"No se pudo duplicar la secuencia: {str(e)}")
            raise e

        #cuarto generamos el detalle de la secuencia, a la cual le asignamos todos los datos obtenidos desde el original
        try:
            detalles_secuencia_duplicada = []
            for detalle in detalle_secuencia_original:
                detalles_secuencia_duplicada.append(DETALLE_SECUENCIA(
                    SE_NPASO=detalle.SE_NPASO,
                    SC_NID=secuencia_duplicada,
                    EP_NID=detalle.EP_NID,
                    ET_NID=detalle.ET_NID,
                    US_NID=request.user,
                    USERS_RESPONSABLE_ID=detalle.USERS_RESPONSABLE_ID,
                    SE_BHABILITADO=detalle.SE_BHABILITADO,
                    SE_BOBLIGATORIO=detalle.SE_BOBLIGATORIO
                ))
            DETALLE_SECUENCIA.objects.bulk_create(detalles_secuencia_duplicada)

        except Exception as e:
            print(f"No se pudo crear el detalle de la secuencia duplicada: {str(e)}")
            secuencia_duplicada.delete()
            raise e


        ctx = {
            'status': 'success',
            'message': 'Secuencia duplicada correctamente'
        }
        return JsonResponse(ctx)
    except Exception as e:
        print(e)
        ctx = {
            'status': 'error',
            'message': f'Error al duplicar la secuencia: {str(e)}'
        }
        return JsonResponse(ctx)

def SECUENCIA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "sec_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = Empresa
            form = formSECUENCIA(post_data or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.SE_FFECHAREGISTRO = datetime.now()
                form.save()
                messages.success(request, 'SECUENCIA guardada correctamente')
                return redirect('/sec_listall/') 
            else:
                messages.error(request, 'Error al guardar la SECUENCIA')
                return redirect('/sec_addone/')
        form = formSECUENCIA()
        ctx = {
            'form': form
        }
        return render(request, 'home/SECUENCIA/sec_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/sec_listall/')

def SECUENCIA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "sec_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = SECUENCIA.objects.get(id = pk)
        if request.method == 'POST':
            form = formSECUENCIA(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'SECUENCIA actualizada correctamente')
                return redirect(f'/sec_listall/')

        form = formSECUENCIA(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/SECUENCIA/sec_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/sec_listall/')

def SECUENCIA_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            return redirect('/')
        secuencia = SECUENCIA.objects.get(id = pk)
        secuencia.delete()

        messages.success(request, 'SECUENCIA eliminado correctamente')
        return redirect('sec_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('sec_listall')

##########################################
######### EMPRESA - USUARIOS #############
##########################################

def EMPRESA_USUARIOS_LISTALL(request):
    try:
        empresa = USERS_EMPRESA.objects.all()
        ctx = {
            'object_list': empresa
        }
        return render(request, 'home/USERS_EMPRESA/us_emp_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def SELECCION_EMPRESA(request):
    try:
        empresa = USERS_EMPRESA.objects.all()
        ctx = {
            'object_list': empresa
        }
        return render(request, 'home/USERS_EMPRESA/us_emp_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def OBTENER_EMPRESA_USUARIO(request):
    """
    Obtiene información de la empresa activa del usuario.

    Compatible con usuarios multiempresa.
    """

    try:

        Empresa = Verificar_empresa(request)

        # Si no hay empresa activa seleccionada
        if Empresa is None:
            return JsonResponse({
                'empresa': False,
                'lista_empresas': [],
                'perm_act': False
            })

        # Obtener nombre de empresa activa
        empresa = EMPRESA.objects.get(id=Empresa).EP_CRAZONSOCIAL

        # Obtener solo empresas asignadas al usuario
        lista_empresas = list(
            USERS_EMPRESA.objects.filter(
                US_NID=request.user
            ).select_related('EP_NID').values_list(
                'EP_NID__EP_CRAZONSOCIAL',
                'EP_NID__id'
            )
        )

        # Validación de permisos navbar
        perm_act = validar_perfiles_activos(request.user.id, 'nav')

        return JsonResponse({
            'empresa': empresa,
            'lista_empresas': lista_empresas,
            'perm_act': perm_act
        })

    except Exception as e:
        print(e)

        return JsonResponse({
            'empresa': False,
            'lista_empresas': [],
            'perm_act': False
        })

def ACTUALIZAR_EMPRESA_USUARIO(request,ep_id):
    try:
        empresa = USERS_EMPRESA.objects.filter(US_NID_id = request.user.id).update(EP_NID_id = ep_id)
        messages.success(request, 'Empresa actualizada correctamente')
        return redirect(request.META.get('HTTP_REFERER', '/'))
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
##########################################################################
#####################  VALIDACIÓN DE EMPRESA ACTIVA  #####################
##########################################################################

def Verificar_empresa(request):
    """
    Retorna el ID de la empresa activa del usuario.

    Flujo:
    - Si existe empresa activa en session y el usuario tiene acceso, retorna esa empresa.
    - Si el usuario tiene solo una empresa asignada, la guarda en session y la retorna.
    - Si el usuario tiene más de una empresa asignada, retorna None para forzar selección.
    - Si el usuario no tiene empresa asignada, retorna None.
    """

    try:

        # Buscar empresa activa en session
        empresa_id = request.session.get('empresa_id')

        # Validar acceso a empresa activa
        if empresa_id:

            acceso = USERS_EMPRESA.objects.filter(
                US_NID=request.user,
                EP_NID_id=empresa_id
            ).exists()

            if acceso:
                return empresa_id

            # Si perdió acceso, limpiar session
            request.session.pop('empresa_id', None)

        # Obtener todas las empresas del usuario
        empresas_usuario = USERS_EMPRESA.objects.filter(
            US_NID=request.user
        ).select_related('EP_NID')

        # Usuario con una sola empresa
        if empresas_usuario.count() == 1:

            empresa_id = empresas_usuario.first().EP_NID_id

            request.session['empresa_id'] = empresa_id

            return empresa_id

        # Usuario con múltiples empresas
        if empresas_usuario.count() > 1:
            return None

        # Usuario sin empresa
        messages.error(request, 'Solicite al administrador que asigne su empresa')
        return None

    except Exception as e:
        print(e)
        messages.error(request, 'Solicite al administrador que asigne su empresa')
        return None

def EMPRESA_USUARIOS_ADDONE(request):
    try:
        if request.method == 'POST':
            form = formUSERS_EMPRESA(request.POST or None)
            if form.is_valid():
                messages.success(request, 'Relacion Usuario - Empresa guardada correctamente')
                form.save()
                return redirect('/us_emp_listall/') 
            else:
                messages.error(request, f'Error al guardar la Relacion Usuario - Empresa')
                return redirect('/us_emp_addone/')
        form = formUSERS_EMPRESA()
        ctx = {
            'form': form
        }
        return render(request, 'home/USERS_EMPRESA/us_emp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/us_emp_listall/')

def EMPRESA_USUARIOS_UPDATE(request, pk):
    try:
        documento = USERS_EMPRESA.objects.get(id = pk)
        if request.method == 'POST':
            form = formUSERS_EMPRESA(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Relacion Usuario - Empresa actualizada correctamente')
                return redirect(f'/us_emp_listall/')

        form = formUSERS_EMPRESA(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/USERS_EMPRESA/us_emp_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/sec_listall/')

def EMPRESA_USUARIOS_DELETE(request, pk):
    try:
        empresa = USERS_EMPRESA.objects.get(id = pk)
        empresa.delete()

        messages.success(request, 'Relacion Usuario - Empresa eliminado correctamente')
        return redirect('us_emp_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('us_emp_listall')

def SECUENCIA_PREVIEW(request, pk):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "secuencia_preview"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        etapa = GetPreviewSecuencia(pk, Empresa)
        datos_etapa = SECUENCIA.objects.get(id=pk, EP_NID_id=Empresa)

        response_data = {
            'status': 'success',
            'grouped_data': {},
            'data_etapa': datos_etapa
        }

        if etapa is not None:
            grouped_data = {}

            for campo in etapa:
                datos = []

                if campo[1].lower() == 'lista':
                    try:
                        datos = QueryParam(campo[6])
                    except Exception as e:
                        print("Error al ejecutar la consulta", e)
                        messages.warning(request, f'Error, {str(e)}')

                step_key = campo[0]

                if step_key not in grouped_data:
                    grouped_data[step_key] = []

                grouped_data[step_key].append({
                    'TYPE': campo[1].lower(),
                    'DEFAULT_VALUE': campo[2],
                    'PLACEHOLDER': campo[3],
                    'LARGO': campo[4],
                    'OBLIGATORIO': campo[5],
                    'DATOS': datos
                })

            response_data['grouped_data'] = grouped_data

        return render(request, 'home/SECUENCIA/secuencia_preview.html', response_data)

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('sec_listall')
##########################################################################
######################  DETALLE_SECUENCIA   ##############################
##########################################################################

def DETALLE_SECUENCIA_LISTALL(request):

    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_sec_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        det_secuencia = DETALLE_SECUENCIA.objects.filter(EP_NID_id = Empresa, SE_BHABILITADO = True)
        ctx = {

            'object_list': det_secuencia
        }
        return render(request, 'home/DETALLE_SECUENCIA/det_sec_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def DETALLE_SECUENCIA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_sec_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = Empresa

            secuencia_id = post_data.get('SC_NID')
            etapa_id = post_data.get('ET_NID')
            paso = post_data.get('SE_NPASO')

            if DETALLE_SECUENCIA.objects.filter(
                SC_NID_id=secuencia_id, 
                ET_NID_id=etapa_id,
                SE_BHABILITADO = True
            ).exists():
                messages.error(request, 'Ya existe esta etapa en la secuencia')
                return redirect('/det_sec_addone/')
            if DETALLE_SECUENCIA.objects.filter(
                SC_NID_id=secuencia_id,
                SE_NPASO=paso,
                SE_BHABILITADO = True
            ).exists():
                messages.error(request, 'Ya existe este paso en la secuencia')
                return redirect('/det_sec_addone/')
            form = formDETALLESECUENCIA(post_data or None)
            if form.is_valid():
                
                form.instance.US_NID = request.user
                form.save()
                messages.success(request, 'Detalle de Secuencia guardada correctamente')
                return redirect('/det_sec_listall/') 
            else:
                messages.error(request, 'Error al guardar el Detalle de Secuencia')
                return redirect('/det_sec_addone/')
        form = formDETALLESECUENCIA()
        form.fields['SC_NID'].widget.choices = list(SECUENCIA.objects.filter(SE_BHABILITADO = True).values_list("id", "SE_CNOMBRE"))
        ctx = {
            'form': form
        }
        return render(request, 'home/DETALLE_SECUENCIA/det_sec_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/det_sec_listall/')

def DETALLE_SECUENCIA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_sec_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DETALLE_SECUENCIA.objects.get(id = pk)
        if request.method == 'POST':
            form = formDETALLESECUENCIA(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Detalle de Secuencia actualizado correctamente')
                return redirect(f'/det_sec_listall/')

        form = formDETALLESECUENCIA(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/DETALLE_SECUENCIA/det_sec_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/det_sec_listall/')

def DETALLE_SECUENCIA_DELETE(request, pk):
    try:        
        if request.user.is_superuser == False:                         
            return redirect('/')
        
        Empresa = Verificar_empresa(request) 
        documento = DETALLE_SECUENCIA.objects.get(id = pk)

        if documento.SE_NPASO:
            update_detalle_secuencia(documento.SC_NID_id, Empresa, documento.SE_NPASO)

        documento.SE_BHABILITADO = False
        documento.SE_FFECHAELIMICACION = datetime.now()
        documento.save()

        citaciones = list(ETAPA_LOG.objects.filter(SC_NID = documento.SC_NID, ET_NID = documento.ET_NID, EL_FFECHAFIN = None, CI_NID__CI_BARCHIVADO = False, CI_NID__CI_BHABILITADO = True).values_list('CI_NID_id', flat=True))
        detalle_secuencia = DETALLE_SECUENCIA.objects.get(SE_NPASO = documento.SE_NPASO, SC_NID = documento.SC_NID, SE_BHABILITADO = True)
        delete_ETAPA_LOG(documento.SC_NID_id, documento.ET_NID_id, documento.EP_NID_id)
        insert_ETAPA_LOG(documento.EP_NID_id, documento.SC_NID_id, detalle_secuencia.ET_NID_id, citaciones)


        messages.success(request, 'Detalle de Secuencia eliminado correctamente')
        return redirect('det_sec_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('det_sec_listall')

##########################################################################
############################  ETAPA - DETALLE   ##########################
##########################################################################

def DETALLE_ETAPA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_etap_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        det_etapa = DETALLE_ETAPA.objects.filter(EP_NID_id = Empresa)
        ctx = {
            'object_list': det_etapa
        }
        return render(request, 'home/DETALLE_ETAPA/det_etap_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def DETALLE_ETAPA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_etap_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
            
        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = Empresa

            etapa_id = post_data.get('ET_NID')
            campo_id = post_data.get('CAMP_NID')
            paso = post_data.get('DET_NPASO')
            if DETALLE_ETAPA.objects.filter(
                ET_NID_id=etapa_id,
                CAMP_NID_id=campo_id,
            ).exists():
                messages.error(request, 'Ya existe este campo en la etapa')
                return redirect('/det_etap_addone/')
            if DETALLE_ETAPA.objects.filter(
                ET_NID_id=etapa_id,
                DET_NPASO=paso,
            ).exists():
                messages.error(request, 'Ya existe este paso en la etapa')
                return redirect('/det_etap_addone/')
            form = formDETALLE_ETAPA(post_data or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                if form.instance.ET_NID != None:
                    if form.instance.ET_NID.ET_CTIPO in ['OPERACION', 'SEGUIMIENTO'] and (form.instance.DET_NPASO == None or form.instance.DET_NPASO == ''):
                        messages.error(request, 'Error al guardar el Detalle de Etapa, es necesario ingresar el paso de la etapa')
                        return redirect('/det_etap_addone/')
                form.save()
                messages.success(request, 'Detalle de Etapa guardado correctamente')
                return redirect('/det_etap_listall/') 
            else:
                messages.error(request, 'Error al guardar el Detalle de Etapa')
                return redirect('/det_etap_addone/')
        form = formDETALLE_ETAPA()
        ctx = {
            'form': form
        }
        return render(request, 'home/DETALLE_ETAPA/det_etap_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/det_etap_listall/')

def DETALLE_ETAPA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "det_etap_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = DETALLE_ETAPA.objects.get(id = pk)
        if request.method == 'POST':
            form = formDETALLE_ETAPA(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Detalle de Etapa actualizado correctamente')
                return redirect(f'/det_etap_listall/')

        form = formDETALLE_ETAPA(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/DETALLE_ETAPA/det_etap_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/det_etap_listall/')

def DETALLE_ETAPA_DELETE(request, pk):
    try:        
        if request.user.is_superuser == False:                                 
            return redirect('/')
        documento = DETALLE_ETAPA.objects.get(id = pk)
        documento.delete()

        messages.success(request, 'Detalle de Etapa eliminado correctamente')
        return redirect('det_etap_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('det_etap_listall')

##########################################################################
############################  CAMPO-OPCIONES  ############################
##########################################################################

def CAMPO_OPCIONES_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_op_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        tipos_documentos = CAMPO_OPCION.objects.filter(EP_NID_id = Empresa)
        ctx = {
            'object_list': tipos_documentos
        }
        return render(request, 'home/CAMPO_OPCION/camp_op_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def CAMPO_OPCIONES_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_op_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        if request.method == 'POST':
            form = formCAMPO_OPCIONES(request.POST or None)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.save()
                messages.success(request, 'Campo guardado correctamente')
                return redirect('camp_op_listall') 
            else:
                messages.error(request, 'Error al guardar el Campo')
                return redirect('camp_op_addone')
        form = formCAMPO_OPCIONES()
        ctx = {
            'form': form
        }
        return render(request, 'home/CAMPO_OPCION/camp_op_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('camp_op_listall/')

def CAMPO_OPCIONES_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "camp_op_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        documento = CAMPO_OPCION.objects.get(id = pk)
        if request.method == 'POST':
            form = formCAMPO_OPCIONES(request.POST, instance=documento)
            if form.is_valid():
                form.save()
                messages.success(request, 'Opciones Campo actualizado correctamente')
                return redirect(f'camp_op_listall')

        form = formCAMPO_OPCIONES(instance=documento)
        ctx = {
            'form': form
        }
        return render(request, 'home/CAMPO_OPCION/camp_op_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('camp_op_listall')

def CAMPO_OPCIONES_DELETE(request, pk):
    try:        
        if request.user.is_superuser == False:                                 
            return redirect('/')
        documento = CAMPO_OPCION.objects.get(id = pk)
        documento.delete()

        messages.success(request, 'Campo eliminado correctamente')
        return redirect('camp_op_listall')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('camp_op_listall')

##########################################################################
#########################   PLANIFICACIÓN   ##############################
##########################################################################

def PLANIFICACION_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not usuario_es_ingreso_camion(request.user) and not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        planificaciones = PLANIFICACION.objects.filter(
            EP_NID_id=Empresa,
            PL_BARCHIVADO=False
        )

        print(f'PLANIFICACION_LISTALL empresa activa: {Empresa} - planificaciones filtradas: {planificaciones.count()}')

        ctx = {
            'object_list': planificaciones
        }
        
        return render(request, 'home/PLANIFICACION/pla_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error: {str(e)}')
        return redirect('/')

def PLANIFICACION_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not usuario_es_ingreso_camion(request.user) and not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        empresa_activa = EMPRESA.objects.filter(pk=Empresa).first()

        planificacion = PLANIFICACION.objects.get(id=pk, EP_NID_id=Empresa)

        clientes_sap = obtener_clientes_aceite(Empresa)

        proveedores_sap = SAP_OPOR_PROGRAMACION.objects.filter(
            EP_NID_id=Empresa,
            SOP_BHABILITADO=True,
            SOP_CARDNAME__isnull=False
        ).exclude(
            SOP_CARDNAME=''
        ).values(
            'SOP_CARDCODE',
            'SOP_CARDNAME'
        ).distinct().order_by('SOP_CARDNAME')

        secuencias = SECUENCIA.objects.filter(
            EP_NID_id=Empresa,
            SE_CTIPO=planificacion.PL_CTIPOCUPO,
            SE_BHABILITADO=True
        ).order_by('SE_CNOMBRE')

        citaciones = CITACION.objects.filter(
            PL_NID=planificacion,
            CI_BHABILITADO=True
        ).annotate(
            valor_campo_38=Subquery(
                DATO_OPERACION.objects.filter(
                    CI_NID=OuterRef('pk'),
                    CAMP_NID_id=38
                ).values('DO_CVALOR')[:1]
            )
        )

        user_id = request.user.id

        despachos = []
        recepciones = []
        citaciones_responsable = []

        for row in citaciones:
            responsable = None
            secuencia = row.SC_NID
            etapa = row.ETAPA_ACTUAL

            detalle_secuencia = DETALLE_SECUENCIA.objects.get(
                SC_NID=secuencia,
                ET_NID=etapa,
                SE_BHABILITADO=True
            )

            if usuario_es_asistente_recepcion(request.user) and detalle_secuencia.SE_NPASO <= 1:
                continue

            enviado_asistente = detalle_secuencia.SE_NPASO > 1
            log_envio_asistente = None
            if enviado_asistente:
                log_envio_asistente = SYSLOGGER.objects.select_related('US_NID').filter(
                    LOG_COPERACION='AVANZA_AR',
                    LOG_CADD1=str(row.pk)
                ).order_by('-LOG_FFECHAREGISTRO').first()

            enviado_usuario = log_envio_asistente.US_NID.username if log_envio_asistente and log_envio_asistente.US_NID else ''
            enviado_fecha = log_envio_asistente.LOG_FFECHAREGISTRO if log_envio_asistente else None
            log_aprobacion_asistente = SYSLOGGER.objects.select_related('US_NID').filter(
                LOG_COPERACION='APRUEBA_AR',
                LOG_CADD1=str(row.pk)
            ).order_by('-LOG_FFECHAREGISTRO').first()
            aprobado_asistente = bool(log_aprobacion_asistente) or detalle_secuencia.SE_NPASO > 2
            aprobado_usuario = log_aprobacion_asistente.US_NID.username if log_aprobacion_asistente and log_aprobacion_asistente.US_NID else ''
            aprobado_fecha = log_aprobacion_asistente.LOG_FFECHAREGISTRO if log_aprobacion_asistente else None

            if usuario_es_asistente_cd(request.user) and not aprobado_asistente:
                continue

            dato_estanque = obtener_dato_estanque_operacional(row)
            log_estanque = SYSLOGGER.objects.select_related('US_NID').filter(
                LOG_COPERACION='ESTANQUE_CD',
                LOG_CADD1=str(row.pk)
            ).order_by('-LOG_FFECHAREGISTRO').first()
            log_envio_estanque = SYSLOGGER.objects.select_related('US_NID').filter(
                LOG_COPERACION='ENVIA_CD_NEXT',
                LOG_CADD1=str(row.pk)
            ).order_by('-LOG_FFECHAREGISTRO').first()
            estanque_valor = dato_estanque.DO_CVALOR if dato_estanque else ''
            estanque_usuario = log_estanque.US_NID.username if log_estanque and log_estanque.US_NID else ''
            estanque_fecha = log_estanque.LOG_FFECHAREGISTRO if log_estanque else None
            estanque_enviado = bool(log_envio_estanque) or detalle_secuencia.SE_NPASO > 3 or row.CI_CESTADO == CIT_TERMINADO
            estanque_enviado_usuario = log_envio_estanque.US_NID.username if log_envio_estanque and log_envio_estanque.US_NID else ''
            estanque_enviado_fecha = log_envio_estanque.LOG_FFECHAREGISTRO if log_envio_estanque else None

            responsables_str = detalle_secuencia.USERS_RESPONSABLE_ID

            if responsables_str:
                responsable = responsables_str.replace('[', '').replace(']', '').replace("'", '').replace('"', '').replace(' ', '').split(',')

                if responsable:
                    if str(user_id) in responsable:
                        citaciones_responsable.append(row.pk)

            citacion_item = CITACION_ITEM.objects.get(CI_NID=row)

            if row.CI_CTIPO == CIT_DESPACHO:
                despachos.append([
                    row.pk,
                    row.CI_FFECHACITACION,
                    secuencia.SE_CNOMBRE,
                    etapa.ET_CNOMBRE,
                    row.SN_NID.SN_CRAZONSOCIAL if row.SN_NID else '',
                    'Conductor Genérico' if not row.CON_NID else row.CON_NID.CON_CNOMBRE + ' ' + row.CON_NID.CON_CAPELLIDO,
                    'Camión Genérico' if not row.CA_NID else row.CA_NID.CAM_CPATENTE,
                    row.PRO_NID.SN_CRAZONSOCIAL if row.PRO_NID else '',
                    row.CI_NVALORTARIFA if row.CI_NVALORTARIFA else 0,
                    row.TAR_NID.TAR_CDIVISA if row.TAR_NID else '',
                    row.CI_BAVISADO,
                    row.CI_BCONFIRMADO,
                    row.CI_BARRIBADO,
                    row.CI_CTIPODOCUMENTO,
                    row.CI_CNUMERODOCUMENTO if row.CI_CNUMERODOCUMENTO else row.valor_campo_38,
                    citacion_item.IT_NID.IT_CNOMBRE,
                    row.CON_NID.CON_CTELEFONO if row.CON_NID else '',
                    row.CI_CESTADO,
                    row.CI_NVALORTARIFA if row.CI_NVALORTARIFA else 0,
                    row.TAR_NID.TAR_CDIVISA if row.TAR_NID else '',
                    row.CI_CTIPO_FLETE,
                    enviado_asistente,
                    enviado_usuario,
                    enviado_fecha,
                    aprobado_asistente,
                    aprobado_usuario,
                    aprobado_fecha,
                    estanque_valor,
                    estanque_usuario,
                    estanque_fecha,
                    estanque_enviado,
                    estanque_enviado_usuario,
                    estanque_enviado_fecha
                ])

            elif row.CI_CTIPO == CIT_RECEPCION:
                recepciones.append([
                    row.pk,
                    row.CI_FFECHACITACION,
                    row.CI_CTIPODOCUMENTO,
                    row.CI_CNUMERODOCUMENTO,
                    secuencia.SE_CNOMBRE,
                    etapa.ET_CNOMBRE,
                    citacion_item.IT_NID.IT_CNOMBRE,
                    row.PRO_NID.SN_CRAZONSOCIAL if row.PRO_NID else '',
                    'Camión Genérico' if not row.CA_NID else row.CA_NID.CAM_CPATENTE,
                    'Conductor Genérico' if not row.CON_NID else row.CON_NID.CON_CNOMBRE + ' ' + row.CON_NID.CON_CAPELLIDO,
                    row.CON_NID.CON_CTELEFONO if row.CON_NID else '',
                    row.CI_NVALORTARIFA if row.CI_NVALORTARIFA else 0,
                    row.CI_CESTADO,
                    row.CI_NVALORTARIFA if row.CI_NVALORTARIFA else 0,
                    row.CI_CTIPO_FLETE,
                    enviado_asistente,
                    enviado_usuario,
                    enviado_fecha,
                    aprobado_asistente,
                    aprobado_usuario,
                    aprobado_fecha,
                    estanque_valor,
                    estanque_usuario,
                    estanque_fecha,
                    estanque_enviado,
                    estanque_enviado_usuario,
                    estanque_enviado_fecha
                ])

        ctx = {
            'despachos': despachos,
            'recepciones': recepciones,
            'planificacion': planificacion,
            'planificacion_id': planificacion.id,
            'citaciones_responsable': citaciones_responsable,

            'empresa_activa': empresa_activa,
            'empresa_id': Empresa,
            'clientes_sap': clientes_sap,
            'proveedores_sap': proveedores_sap,
            'secuencias': secuencias,
        }

        return render(request, 'home/PLANIFICACION/pla_listone.html', ctx)

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pla_listall/')

def PLANIFICACION_FILEDONE(request, pk):
    try:
        if not request.user.is_superuser:
            usuario = request.user.id
            if not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_filedlistall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        
        if usuario_es_ingreso_camion(request.user):
            messages.error(request, 'Su perfil no puede archivar planificaciones.')
            return redirect('/pla_listall/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        planificacion = PLANIFICACION.objects.get(id=pk, EP_NID_id=Empresa)
        citaciones = CITACION.objects.filter(PL_NID = planificacion)
        archivo = not planificacion.PL_BARCHIVADO
        
        if citaciones:
            CITACION.objects.filter(PL_NID = planificacion).update(
                CI_BARCHIVADO = archivo
            )
        planificacion.PL_BARCHIVADO = archivo
        planificacion.save()
            
        messages.success(request, 'Planificación archivada correctamente')
        return redirect(f'/pla_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/pla_listone/{pk}')

def PLANIFICACION_FILEDLISTALL(request):
    try:
        if not request.user.is_superuser:
            usuario = request.user.id
            if not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_filedlistall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        
        if usuario_es_ingreso_camion(request.user):
            messages.error(request, 'Su perfil no puede acceder a planificaciones archivadas.')
            return redirect('/pla_listall/')

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return redirect('/seleccionar_empresa/')

        planificaciones = PLANIFICACION.objects.filter(
            EP_NID_id=Empresa,
            PL_BARCHIVADO=True
        )

        print(f'PLANIFICACION_FILEDLISTALL empresa activa: {Empresa} - planificaciones filtradas: {planificaciones.count()}')

        ctx = {
            'object_list': planificaciones,
            'archivados': True
        }
        
        return render(request, 'home/PLANIFICACION/pla_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, str(e)) 
        return redirect('/')

def ajax_validar_calendario_planificacion(request):
    try:
        dia = request.POST.get('dia')
        mes = request.POST.get('mes')
        ano = request.POST.get('ano')
        empresa = Verificar_empresa(request) 
        calendario = CALENDARIO.objects.filter(
            CA_NDIA = dia,
            CA_NMES = mes,
            CA_NANO = ano,
            EP_NID_id = int(empresa)
        ).first()

        id_calendario = None
        if calendario:
            id_calendario = calendario.pk

        return JsonResponse({
            'valid': True,
            'id_calendario': id_calendario
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

def ajax_validar_nueva_planificacion(request):
    try:
        id_calendario = request.POST.get('id_calendario')
        cupos_nueva_planificacion = int(request.POST.get('cupos'))
        fecha_nueva_planificacion_str = request.POST.get('fecha_inicio')
        fecha_nueva_planificacion_datetime = datetime.strptime(fecha_nueva_planificacion_str, '%Y-%m-%dT%H:%M')
        fecha_termino_str = request.POST.get('fecha_termino')
        fecha_termino_datetime = datetime.strptime(fecha_termino_str, '%Y-%m-%dT%H:%M')

        calendario = CALENDARIO.objects.get(pk = id_calendario)
        planificaciones = PLANIFICACION.objects.filter(CAL_NID = calendario)

        # Dividir las fechas y horas
        fecha_inicio = fecha_nueva_planificacion_datetime.date()
        hora_inicio = fecha_nueva_planificacion_datetime.time()
        fecha_fin = fecha_termino_datetime.date()
        hora_fin = fecha_termino_datetime.time()

        # Validar si las fechas son iguales
        if fecha_inicio == fecha_fin:
            # Verificar la diferencia de hora
            if hora_fin < hora_inicio:
                return JsonResponse({
                    'valid': False,
                    'msg': 'La hora de termino no puede ser anterior a la hora de inicio en el mismo día.'
                })
        elif fecha_fin < fecha_inicio:
            return JsonResponse({
                'valid': False,
                'msg': 'La fecha de termino no puede ser anterior a la fecha de inicio.'
            })
        # # VALIDAR SI EL CUPO INGRESADO SUPERA AL TOTAL DE CUPOS DISPONIBLES
        cupos_disponibles = calendario.TOTAL_CUPOS_DISPONIBLES
        if cupos_disponibles < cupos_nueva_planificacion:
            return JsonResponse({
                'valid': True,
                'continue': True,
                'valid_planificacion': False,
                'msg': f'El cupo ingresado supera la cantidad máxima cupos disponibles, el cual es {cupos_disponibles}. ¿Quieres continuar?'
            })
        
        #VALIDAR SI FECHA DE CITACION INGRESA ESTA DENTRO DEL RANGO DE HORA APERTURA Y CIERRA
        if (fecha_nueva_planificacion_datetime.year == calendario.CA_NANO and
            fecha_nueva_planificacion_datetime.month == calendario.CA_NMES and
            fecha_nueva_planificacion_datetime.day == calendario.CA_NDIA):
            if (fecha_termino_datetime.year == calendario.CA_NANO and
                fecha_termino_datetime.month == calendario.CA_NMES and
                fecha_termino_datetime.day == calendario.CA_NDIA):
                # Convertir las horas de apertura y cierre a datetime.time para comparación
                if calendario.CA_FHORA_APERTURA > fecha_nueva_planificacion_datetime.time() and fecha_termino_datetime.time() > calendario.CA_FHORA_CIERRE:
                    # La hora está fuera del rango
                    return JsonResponse({
                        'valid': True,
                        'continue': False,
                        'valid_planificacion': False,
                        'msg': 'La hora de la cita no está dentro del horario de apertura y cierre.'
                    })
            else:
                return JsonResponse({
                    'valid': False,
                    'msg': f'La fecha de termino no coincide con el día {str(calendario.CA_NDIA)}/{str(calendario.CA_NMES)}/{str(calendario.CA_NANO)}'
                })
        else:
            return JsonResponse({
                    'valid': False,
                    'msg': f'La fecha de inicio no coincide con el día {str(calendario.CA_NDIA)}/{str(calendario.CA_NMES)}/{str(calendario.CA_NANO)}'
                })
        for row in planificaciones:
            if row.PL_FFECHAINICIO.time() >= fecha_nueva_planificacion_datetime.time() and row.PL_FFECHAFIN.time() <= fecha_termino_datetime.time():
                return JsonResponse({
                    'valid': False,
                    'msg': f'Ya existe una planificación situada para el horario entre {str(row.PL_FFECHAINICIO.time())} - {str(row.PL_FFECHAFIN.time())}'
                })
            elif row.PL_FFECHAINICIO.time() <= fecha_nueva_planificacion_datetime.time() and row.PL_FFECHAFIN.time() >= fecha_termino_datetime.time():
                return JsonResponse({
                    'valid': False,
                    'msg': f'Ya existe una planificación situada para el horario entre {str(row.PL_FFECHAINICIO.time())} - {str(row.PL_FFECHAFIN.time())}'
                })
            elif row.PL_FFECHAINICIO.time() <= fecha_nueva_planificacion_datetime.time() and row.PL_FFECHAFIN.time() <= fecha_termino_datetime.time():
                return JsonResponse({
                    'valid': False,
                    'msg': f'Ya existe una planificación situada para el horario entre {str(row.PL_FFECHAINICIO.time())} - {str(row.PL_FFECHAFIN.time())}'
                })
            elif row.PL_FFECHAINICIO.time() == fecha_nueva_planificacion_datetime.time() and row.PL_FFECHAFIN.time() == fecha_termino_datetime.time():
                return JsonResponse({
                    'valid': False,
                    'msg': f'Ya existe una planificación situada para el horario entre {str(row.PL_FFECHAINICIO.time())} - {str(row.PL_FFECHAFIN.time())}'
                })
        
        return JsonResponse({
            'valid': True,
            'valid_planificacion': True,
        })            
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

def ajax_archivar_planificaciones_seleccionadas(request):
    try:
        if not request.user.is_superuser:
            usuario = request.user.id
            if not usuario_es_planificador(request.user) and not validar_perfiles_activos(usuario, "pla_filedlistall"):
                return JsonResponse({
                'success': False,
                'msg': 'No tienes permisos para archivar planificaciones'
            })
            
        if usuario_es_ingreso_camion(request.user):
            return JsonResponse({
                'success': False,
                'msg': 'Su perfil no puede archivar planificaciones'
            })

        Empresa = Verificar_empresa(request)

        if Empresa is None:
            return JsonResponse({
                'success': False,
                'msg': 'Debe seleccionar una empresa.'
            })

        id_planificaciones = json.loads(request.POST.get("planificaciones"))
        for row in id_planificaciones:
            planificacion = PLANIFICACION.objects.get(id=row, EP_NID_id=Empresa)
            citaciones = CITACION.objects.filter(PL_NID = planificacion)
            archivado = not planificacion.PL_BARCHIVADO
            
            if citaciones:
                CITACION.objects.filter(PL_NID = planificacion).update(
                    CI_BARCHIVADO = archivado
                )
                
            planificacion.PL_BARCHIVADO = archivado
            planificacion.save()
            
        return JsonResponse({
            'success': True
        })        
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'msg': str(e)
        })

def download_citaciones_data(request, pk):
    try:
        planificacion = PLANIFICACION.objects.get(id=pk)
        citaciones = CITACION.objects.filter(
            PL_NID=planificacion,
            CI_BHABILITADO=True, 
            CI_BARCHIVADO=False,
            CI_CESTADO__in=['EN PROCESO', 'TERMINADO', 'RECHAZADO']
        ).select_related('SC_NID', 'EP_NID', 'CA_NID')

        if not citaciones.exists():
            messages.warning(request, 'No hay datos para descargar')
            return redirect('pla_listone', pk=pk)

        data = []
        columnas = ['Número citación', 'Secuencia', 'Etapa', 'Zona', 'Campo', 'Valor', 'Estado']
        resumen_data = []
        resumen_columnas = ['Número citación', 'Secuencia', 'Etapa', 'Zona', 'Camión', 'Usuario', 'Fecha inicio', 'Fecha fin', 'Tiempo transcurrido', 'Tiempo maximo', 'Estado']

        for citacion in citaciones:
            secuencia = citacion.SC_NID
            etapas_id = get_etapa_operacion_xsecuencia(secuencia.pk, citacion.pk)
            
            if etapas_id:
                # Obtener el total de etapas para identificar la última
                total_etapas = len(etapas_id)
                
                for index, row in enumerate(etapas_id):
                    etapa = ETAPA.objects.get(id=row[0])
                    zona = etapa.ZON_NID.ZON_CNOMBRE if etapa.ZON_NID else "Sin zona"
                    campos = GetPreviewEtapa(etapa.pk)
                    if campos:
                        for campo in campos:
                            campo_obj = CAMPO.objects.get(pk=campo[6])
                            dato_operacion = DATO_OPERACION.objects.filter(
                                CI_NID=citacion, 
                                SC_NID=citacion.SC_NID, 
                                ET_NID=etapa, 
                                CAMP_NID=campo[6]
                            ).first()
                            
                            valor_campo = dato_operacion.DO_CVALOR if dato_operacion else ""
                            # Solo mostrar RECHAZADO en la última etapa
                            estado = "RECHAZADO" if (citacion.CI_CESTADO == "RECHAZADO" and index == total_etapas - 1) else ""
                            data.append([citacion.pk, secuencia.SE_CNOMBRE, etapa.ET_CNOMBRE, zona, campo_obj.CA_CETIQUETA, valor_campo, estado])

                    etapa_log = ETAPA_LOG.objects.filter(CI_NID=citacion, SC_NID=citacion.SC_NID, ET_NID=etapa).first()
                    dato_operacion_usuario = DATO_OPERACION.objects.filter(
                        CI_NID=citacion, 
                        SC_NID=citacion.SC_NID, 
                        ET_NID=etapa
                    ).first()

                    if etapa_log:
                        etapa_inicio = etapa_log.EL_FFECHAINICIO.replace(tzinfo=None)
                        etapa_fin = etapa_log.EL_FFECHAFIN.replace(tzinfo=None)
                        tiempo_transcurrido = (etapa_log.EL_FFECHAFIN - etapa_log.EL_FFECHAINICIO).total_seconds()
                        if tiempo_transcurrido > 3600:
                            tiempo_transcurrido -= 3600
                        horas, remainder = divmod(tiempo_transcurrido, 3600)
                        minutos, segundos = divmod(remainder, 60)
                        tiempo_transcurrido_formateado = f"{int(horas):02}:{int(minutos):02}:{int(segundos):02}"
                        
                        if dato_operacion_usuario and dato_operacion_usuario.US_NID:
                            nombre_completo = f"{dato_operacion_usuario.US_NID.first_name} {dato_operacion_usuario.US_NID.last_name}".strip()
                            nombre_usuario = nombre_completo if nombre_completo else dato_operacion_usuario.US_NID.username
                        else:
                            nombre_usuario = "Sin usuario"
                    else:
                        tiempo_transcurrido_formateado = "00:00:00"
                        nombre_usuario = "Sin usuario"
                        etapa_inicio = None
                        etapa_fin = None

                    tiempo_maximo = etapa_log.ET_NID.ET_TTIEMPOMAXIMO
                    patente_camion = citacion.CA_NID.CAM_CPATENTE if citacion.CA_NID else "Sin camión"
                    # Solo mostrar RECHAZADO en la última etapa
                    estado = "RECHAZADO" if (citacion.CI_CESTADO == "RECHAZADO" and index == total_etapas - 1) else ""
                    resumen_data.append([
                        citacion.pk, 
                        secuencia.SE_CNOMBRE, 
                        etapa.ET_CNOMBRE,
                        zona,
                        patente_camion,
                        nombre_usuario,
                        etapa_inicio,
                        etapa_fin, 
                        tiempo_transcurrido_formateado,
                        tiempo_maximo,
                        estado
                    ])

        if data:
            workbook = openpyxl.Workbook()
            worksheet = workbook.active
            worksheet.append(columnas)
            
            # Agregar filtros a las columnas
            worksheet.auto_filter.ref = f"A1:G{len(data) + 1}"
            
            for row in data:
                worksheet.append(row)

            resumen_worksheet = workbook.create_sheet(title='Resumen')
            resumen_worksheet.append(resumen_columnas)
            
            # Agregar filtros a las columnas del resumen
            resumen_worksheet.auto_filter.ref = f"A1:K{len(resumen_data) + 1}"
            
            for row in resumen_data:
                resumen_worksheet.append(row)

            filename = f'plantilla_citaciones_{planificacion.pk}_{timezone.now().strftime("%Y%m%d")}.xlsx'
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename={filename}'
            workbook.save(response)
            return response
        
        messages.warning(request, 'No hay datos para descargar')
        return redirect('pla_listone', pk=pk)
    
    except PLANIFICACION.DoesNotExist:
        messages.error(request, 'La planificación especificada no existe')
        return redirect('pla_listall')
    except Exception as e:
        messages.error(request, f'Error, {str(e)}')
        return redirect('pla_listone', pk=pk)
##########################################################################
############################  TARIFA GLOBAL   ############################
##########################################################################

def TARIFA_GLOBAL_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "tg_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        if Empresa is None:
            return redirect('/')
        object_list = TARIFA_GLOBAL.objects.filter(TAR_BHABILITADO = True, EP_NID_id = Empresa)
        ctx = {            
            'object_list': object_list
        }
        return render(request, 'home/TARIFA/tg_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def TARIFA_GLOBAL_LISTALL_INHABILITADO(request):
    try:        
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "tg_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")     
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        object_list = TARIFA_GLOBAL.objects.filter(TAR_BHABILITADO = False, EP_NID_id = Empresa)
        ctx = {            
            'object_list': object_list
        }
        return render(request, 'home/TARIFA/tg_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def TARIFA_GLOBAL_ADDONE(request):
    try:
        empresa_id = Verificar_empresa(request)
        if request.method == 'POST':
            # ESTABLECER EMPRESA EN EL FORMULARIO
            empresa = EMPRESA.objects.get(id = empresa_id)
            post_data = request.POST.copy()  # Hacer una copia mutable
            # Supongamos que quieres establecer un valor específico para 'EP_NID'
            post_data['EP_NID'] = empresa

            form = formTARIFA_GLOBAL(post_data)
            if form.is_valid():
                tarifa = form.save(commit=False)
                tarifa.US_NID = request.user
                tarifa.TAR_BHABILITADO = True
                if not tarifa.TAR_FFECHAREGISTRO:
                    tarifa.TAR_FFECHAREGISTRO = datetime.now()
                tarifa.save()

                # Crear registro en TARIFA_LOG
                TARIFA_LOG.objects.create(
                    TAR_NID=tarifa,
                    US_NID=request.user,
                    TL_FFECHAREGISTRO=datetime.now(),
                    TL_NVALOR=tarifa.TAR_NVALOR
                )

                messages.success(request, 'Tarifa global guardada correctamente')
                return redirect('/tg_listall/')
            else:
                print(form.errors)
                messages.error(request, form.errors)
                return redirect('/tg_addone/')
        else:
            form = formTARIFA_GLOBAL()
            form.fields['RUT_NID'].widget.choices = list(RUTA.objects.filter(RUT_BHABILITADO = True, EP_NID = empresa_id).values_list("id", "RUT_CNOMBRE"))
            form.fields['SN_NID'].widget.choices = list(SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, EP_NID = empresa_id, SN_CTIPO = 'S').values_list("id", "SN_CRAZONSOCIAL"))
            ctx = {
                'form': form
            }
            return render(request, 'home/TARIFA/tg_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_listall/')

def TARIFA_GLOBAL_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "tg_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        tarifa_global = TARIFA_GLOBAL.objects.get(id = pk)
        fecha_registro_original = tarifa_global.TAR_FFECHAREGISTRO
        valor_previo = tarifa_global.TAR_NVALOR
        if request.method == 'POST':
            form = formTARIFA_GLOBAL(request.POST, instance=tarifa_global)
            if form.is_valid():
                form.instance.TAR_FFECHAREGISTRO = fecha_registro_original
                form.instance.TAR_FFECHAULTIMAMODIFICACION = datetime.now()
                form.instance.TAR_NVALORPREVIO = valor_previo
                form.instance.TAR_BHABILITADO = True
                tarifa = form.save()
                
                # Crear registro en TARIFA_LOG
                TARIFA_LOG.objects.create(
                    TAR_NID=tarifa,
                    US_NID=request.user,
                    TL_FFECHAREGISTRO=datetime.now(),
                    TL_NVALOR=tarifa.TAR_NVALOR
                )

                messages.success(request, 'Tarifa global actualizada correctamente')
                return redirect(f'/tg_listall/')
        form = formTARIFA_GLOBAL(instance=tarifa_global)
        ctx = {
            'form': form
        }
        return render(request, 'home/TARIFA/tg_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_listall/')

def TARIFA_GLOBAL_DELETE(request, pk):
    try:        
        if request.user.is_superuser == False:
            return redirect('/')
        tarifa_global = TARIFA_GLOBAL.objects.get(id = pk)
        tarifa_global.TAR_BHABILITADO = False
        tarifa_global.save()
        messages.success(request, 'Tarifa global eliminada correctamente')
        return redirect('/tg_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_listall/')

def TARIFA_GLOBAL_HABILITAR(request, pk):
    try:        
        if request.user.is_superuser == False:
            return redirect('/')
        tarifa_global = TARIFA_GLOBAL.objects.get(id = pk)
        tarifa_global.TAR_BHABILITADO = True
        tarifa_global.save()
        messages.success(request, 'Tarifa global habilitada correctamente')
        return redirect('/tg_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_listall/')

def ajax_get_data_tarifa(request, pk):
    try:
        tarifa = TARIFA_GLOBAL.objects.get(id = pk)
        return JsonResponse({
            'valid': True,
            'tarifa_original': float(tarifa.TAR_NVALOR),
            'tarifa_valor': float(tarifa.TAR_NVALOR)
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

def TARIFA_GLOBAL_DOWNLOAD_PLANTILLA(request):
    try:
        columnas = ["ID TARIFA", "VALOR"]
        
        # Crea un nuevo libro de trabajo de Excel.
        workbook = openpyxl.Workbook()

        # Selecciona la hoja activa.
        worksheet = workbook.active
        # CARGAMOS LA COLUMNAS 
        worksheet.append(columnas)

        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=plantilla_modificador_tarifas.xlsx'
        workbook.save(response)

        return response
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_addmasive/')

from decimal import Decimal, InvalidOperation
import numpy as np
import pandas as pd

def convert_to_decimal(value):
    """
    Convierte diferentes tipos de datos a Decimal
    Maneja: str, int, float, numpy.int64, numpy.float64, etc.
    """
    try:
        # Si ya es Decimal, retornarlo
        if isinstance(value, Decimal):
            return value
        
        # Si es numpy int64, float64, etc., convertir a tipo nativo de Python
        if hasattr(value, 'item'):  # Esto detecta tipos numpy
            value = value.item()
        
        # Si es string, limpiar posibles espacios y caracteres especiales
        if isinstance(value, str):
            value = value.strip()
            # Reemplazar comas por puntos si es necesario (formato decimal europeo)
            value = value.replace(',', '.')
            # Eliminar espacios internos
            value = value.replace(' ', '')
            
            # Verificar que no esté vacío después de limpiar
            if not value or value in ['', 'nan', 'NaN', 'null', 'NULL']:
                raise ValueError("Valor vacío o nulo")
        
        # Convertir a Decimal
        return Decimal(str(value))
        
    except (ValueError, InvalidOperation, TypeError) as e:
        raise ValueError(f"No se puede convertir '{value}' (tipo: {type(value).__name__}) a Decimal: {str(e)}")

def TARIFA_GLOBAL_ADDMASIVE(request):
    try:
        if not request.user.is_superuser == True:
            messages.error(request, 'Solo los usuarios administradores pueden cargar masivo')
            return redirect('/tg_listall/')

        if request.method == 'POST':
            ltsErrors = []
            excel_file = request.FILES.get('file')
            df = pd.read_excel(excel_file, dtype=None)
            df = df.fillna(" ")
            
            for index, row in df.iterrows():
                try:
                    id_tarifa = row[0]
                    tarifa = TARIFA_GLOBAL.objects.get(id = id_tarifa)
                    
                    # Conversión mejorada con detección automática de tipo
                    raw_valor = row[1]
                    print(f"Fila {index + 1}: Valor original: {raw_valor}, Tipo: {type(raw_valor)}")
                    
                    try:
                        valor_tarifa = convert_to_decimal(raw_valor)
                        print(f"Fila {index + 1}: Valor convertido: {valor_tarifa}")
                    except ValueError as conversion_error:
                        raise Exception(f"Error en conversión de valor_tarifa: {str(conversion_error)}")
                    
                    valor_previo = tarifa.TAR_NVALOR
                    
                    # citaciones = CITACION.objects.filter(TAR_NID = tarifa, CI_CESTADO__in = ["CREADO", "EN PROCESO"], CI_BARCHIVADO = False, CI_BHABILITADO = True)
                    # if citaciones:
                    #     for citacion in citaciones:
                    #         citacion.CI_NVALORTARIFA = valor_tarifa
                    #         citacion.save()
                    
                    tarifa.TAR_NVALORPREVIO = valor_previo
                    tarifa.TAR_NVALOR = valor_tarifa
                    tarifa.TAR_FFECHAULTIMAMODIFICACION = datetime.now()
                    tarifa.MODIFICADO_POR = request.user
                    
                    tarifa.save()                        
                except Exception as e:
                    print(f"Error en fila {index + 1}: {e}")
                    excepcion = str(e)
                    error = ''
                    if 'El codigo de proveedor o la cantidad de cupos no puede ser nulo' in excepcion:
                        error = 'El codigo de proveedor o la cantidad de cupos no puede ser nulo'
                    elif 'El proveedor no existe' in excepcion:
                        error = 'El proveedor no existe'
                    elif 'Error en conversión de valor_tarifa' in excepcion:
                        error = f'Valor de tarifa inválido: {excepcion.split(": ", 1)[-1]}'
                    else:
                        error = excepcion

                    linea = list(row)
                    linea.append(error)
                    ltsErrors.append(linea)

            if len(ltsErrors) > 0:
                # OBTENEMOS LAS COLUMNAS DEL EXCEL CARGADO
                columnas = list(df.columns.values)
                # AGREGAMOS LA COLUMNA DE ERRORES
                columnas.append('Error')
                # ENVIAMOS EL LISTADO DE ERRORES Y LAS COLUMNAS A LA FUNCION DE CREACION DE EXCEL
                link = excel_errores(ltsErrors, columnas)
                # Agrega un mensaje de error con un enlace a la respuesta.
                message = 'Hay datos que no se pudieron guardar debido a que contienen errores, se ha generado un excel con los datos no guardados, cerrar este mensaje y descargar excel desde el link de la parte inferior del formulario.'
                messages.info(request, message, extra_tags='safe')
                # SE INDICA AL FRONT QUE EXISTEN ERRORES PARA QUE SE ACTIVE EL LINK DE DESCARGA DEL EXCEL ESPECIFICANDO DONDE ESTAN LAS FILAS CON ERRORES Y CUALES SON LOS ERRORES
                context = {
                    'link': link ,
                    'error': 1,
                }
                return render(request, 'home/TARIFA/tg_addmasive.html', context)
            else:
                messages.success(request, 'Tarifas modificadas correctamente')
                return redirect(f'/tg_listall/')
                    
        return render(request,"home/TARIFA/tg_addmasive.html")
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/tg_listall/')

##########################################################################
##############################  RUTAS  ###################################
##########################################################################

def RUTA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "rt_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        object_list = RUTA.objects.filter(RUT_BHABILITADO = True, EP_NID_id = Empresa)
        ctx = {
            'object_list': object_list
        }
        return render(request, 'home/RUTA/rt_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def RUTA_LISTALL_INHABILITADO(request):
    try:        
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "rt_listall_dis"):
                messages.error(request, "No tiene permiso para acceder a esta sección")
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        object_list = RUTA.objects.filter(RUT_BHABILITADO = False, EP_NID_id = Empresa)
        ctx = {            
            'object_list': object_list
        }
        return render(request, 'home/RUTA/rt_listall_dis.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def RUTA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "rt_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        if request.method == 'POST':
            empresa_id = Verificar_empresa(request)
            empresa = EMPRESA.objects.get(id = empresa_id)
            post_data = request.POST.copy()
            post_data['EP_NID'] = empresa

            form = formRUTA(post_data)
            if form.is_valid():                
                ruta = form.save(commit=False)
                # Obtener la comuna y región de inicio desde el formulario
                comuna_inicio = form.cleaned_data['COM_NID_INICIO']
                
                # Obtener la comuna y región de fin desde el formulario
                comuna_fin = form.cleaned_data['COM_NID_TERMINO']
                
                # Construir el nombre de la ruta con el formato específico
                nombre_ruta = f"{comuna_inicio} -> {comuna_fin}"
                
                # Asignar el nombre de la ruta al campo correspondiente                
                # Limpiar nombre de ruta para evitar cambios forzados de el front 
                ruta.RUT_CNOMBRE = ""
                
                ruta.RUT_CNOMBRE = nombre_ruta
                ruta.RUT_FFECHAREGISTRO = datetime.now()
                ruta.RUT_BHABILITADO = True
                ruta.US_NID = request.user
                ruta.save()
                messages.success(request, 'Ruta guardada correctamente')
                return redirect('/rut_listall/')
        else:
            form = formRUTA()
        return render(request, 'home/RUTA/rt_addone.html', {'form': form})
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/rut_listall/')

def RUTA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "rt_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        ruta = RUTA.objects.get(id = pk)
        if request.method == 'POST':
            form = formRUTA(request.POST, instance=ruta)
            if form.is_valid():
                ruta = form.save(commit=False)
                ruta.save()
                messages.success(request, 'Ruta actualizada correctamente')
                return redirect(f'/rut_listall/')
        form = formRUTA(instance=ruta)
        return render(request, 'home/RUTA/rt_addone.html', {'form': form})
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/rut_listall/')

def RUTA_DELETE(request, pk):
    try:    
        if request.user.is_superuser == False:
            return redirect('/')
        ruta = RUTA.objects.get(id = pk)
        ruta.RUT_BHABILITADO = False
        ruta.save()
        messages.success(request, 'Ruta eliminada correctamente')
        return redirect('/rut_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/rut_listall/')

def RUTA_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        ruta = RUTA.objects.get(id = pk)
        ruta.RUT_BHABILITADO = True
        ruta.save()
        messages.success(request, 'Ruta habilitada correctamente')
        return redirect('/rut_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/rut_listall/')

def ajax_get_data_tarifa_ruta(request):
    try:
        id_ruta = request.POST.get('id_ruta')
        id_proveedor = request.POST.get('id_proveedor')
        ruta = RUTA.objects.get(id = id_ruta)
        if id_proveedor:
            tarifas = list(TARIFA_GLOBAL.objects.filter(TAR_BHABILITADO = True, RUT_NID = ruta, SN_NID = id_proveedor).values_list('id', 'TAR_CNOMBRETARIFA'))
        else:
            tarifas = list(TARIFA_GLOBAL.objects.filter(TAR_BHABILITADO = True, RUT_NID = ruta).values_list('id', 'TAR_CNOMBRETARIFA'))
        return JsonResponse({
            'valid': True,
            'tarifas': tarifas
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

##########################################################################
#############################   EXTRA   ##################################
##########################################################################

def EXTRA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "ext_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)
        object_list = EXTRA.objects.filter(EXT_BHABILITADO = True, EXT_CTIPO_CITACION = request.GET.get('tipo_citacion'), EP_NID = Empresa)
            
        ctx = {
            'object_list': object_list,
            'tipo_citacion': request.GET.get('tipo_citacion')
        }
        return render(request, 'home/EXTRA/ext_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def EXTRA_LISTALL_INHABILITADOS(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "ext_listall_del"):
                messages.error(request, "No tiene permiso para acceder a esta sección")
                return redirect('/')
        Empresa = Verificar_empresa(request) 
        object_list = EXTRA.objects.filter(EXT_BHABILITADO = False, EP_NID_id = Empresa)
        ctx = {
            'object_list': object_list
        }
        return render(request, 'home/EXTRA/ext_listall_del.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def EXTRA_ADDONE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "ext_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        empresa = Verificar_empresa(request)
        if request.method == 'POST':
            post_data = request.POST.copy()
            post_data['EP_NID'] = empresa

            form = formEXTRA(post_data)
            if form.is_valid():
                form.instance.US_NID = request.user
                form.instance.EXT_FFECHAREGISTRO = datetime.now()
                form.save()

                messages.success(request, 'Extra creado correctamente')
                return redirect('/ext_listall/')
            else:
                messages.error(request, str(form.errors))
                return redirect('/ext_addone/')
        form = formEXTRA()
        ctx = {
            'form': form
        }
        return render(request, 'home/EXTRA/ext_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/ext_listall/')

def EXTRA_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "ext_addone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        extra = EXTRA.objects.get(id = pk)
        if request.method == 'POST':

            form = formEXTRA(request.POST, instance=extra)
            if form.is_valid():
                form.save()
                messages.success(request, 'Extra actualizado correctamente')
                return redirect('/ext_listall/')
            else:
                messages.error(request, f'Error, {str(e)}')
                return redirect(f'/ext_update/{pk}')
        form = formEXTRA(instance=extra)
        ctx = {
            'form': form
        }
        return render(request, 'home/EXTRA/ext_addone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/ext_listall/')

def EXTRA_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        extra = EXTRA.objects.get(id = pk)
        extra.EXT_BHABILITADO = False
        extra.save()
        messages.success(request, 'Extra eliminado correctamente.')
        return redirect('/ext_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/ext_listall/')

def EXTRA_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        extra = EXTRA.objects.get(id = pk)
        extra.EXT_BHABILITADO = True
        extra.save()
        messages.success(request, 'Extra retornado correctamente.')
        return redirect('/ext_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/ext_listall/')

##########################################################################
########################   CITACION EXTRA   ##############################
##########################################################################

def ajax_addone_extra(request, pk):
    try:
        if request.method == 'POST':
            citacion = CITACION.objects.get(id = pk)
            is_ingreso = EXTRA.objects.get(id = request.POST.get('EXT_NID')).EXT_BINGRESO
            valor = request.POST.get('CIE_NVALOR')
            comentario = request.POST.get('CIE_CCOMENTARIO')

            CITACION_EXTRA.objects.create(
                EP_NID = citacion.EP_NID,
                US_NID = request.user,
                EXT_NID_id = request.POST.get('EXT_NID'), 
                CI_NID = citacion,
                CIE_NVALOR = valor, 
                CIE_FFECHAREGISTRO = datetime.now(),
                CIE_BINGRESO = is_ingreso,
                CIE_CCOMENTARIO = comentario
            )
            
            messages.success(request, 'Extra agregado correctamente')
            return redirect(f'/cit_listone/{pk}')
    except Exception as e:
        print(e)
        return redirect(f'/cit_listone/{pk}')

def CITACION_EXTRA_ADDMASIVO(request):
    try:
        extra_created = 0
        listado_errores_excel = []
        if request.method == 'POST' and request.FILES['file']:
            excel_file = request.FILES['file']
            tipo = request.POST.get('tipo')
            df = pd.read_excel(excel_file, dtype=None)
            df = df.fillna(" ")
            fecha_actual = datetime.now()
            if tipo == 'Extra_citacion':
                id_citacion = request.POST.get('citacion_id')
                citacion = CITACION.objects.get(id = id_citacion)
                empresa = citacion.EP_NID
                usuario = request.user
                
                if request.user.is_superuser == False:
                    conductor = citacion.CON_NID
                    fecha_citacion = timezone.localtime(citacion.CI_FFECHACITACION)
                    diferencia_dias = (fecha_actual - fecha_citacion).days
                    if diferencia_dias > conductor.CON_NPERIODO_EXTRA:
                        messages.error(request, f'No se puede agregar extras mas de {conductor.CON_NPERIODO_EXTRA} dias posteriores a la fecha de la citación')
                        return redirect('/cit_listone/')
                
                for index, row in df.iterrows():
                    try:
                        if not row[0] or row[0] == '' or str(row[0]).strip() == '':
                            raise Exception("No se puede agregar un extra sin ID")
                        if not row[1] or row[1] == '' or str(row[1]).strip() == '':
                            raise Exception("No se puede agregar un extra sin valor")
                        
                        extra = EXTRA.objects.get(id = row[0])
                        if extra.EXT_CTIPO_CITACION != citacion.CI_CTIPO:
                            raise Exception("El tipo de citación del extra no coincide con el tipo de citación de la citación")
                        es_ingreso = extra.EXT_BINGRESO
                        valor = Decimal(row[1]).quantize(Decimal('0.00000'))
                        comentario = row[2]

                        CITACION_EXTRA.objects.create(
                            EP_NID = empresa,
                            US_NID = usuario,
                            EXT_NID = extra,
                            CI_NID = citacion,
                            CIE_NVALOR = valor,
                            CIE_FFECHAREGISTRO = datetime.now(),
                            CIE_BINGRESO = es_ingreso,
                            CIE_CCOMENTARIO = comentario
                        )
                        extra_created += 1
                    except Exception as e:
                        print(e)
                        exception = str(e)
                        if exception == "No se puede agregar un extra sin ID":
                            error = "No se puede agregar un extra sin ID"
                        elif exception == "No se puede agregar un extra sin valor":
                            error = "No se puede agregar un extra sin valor"
                        elif exception == "El tipo de citación del extra no coincide con el tipo de citación de la citación":
                            error = "El tipo de citación del extra no coincide con el tipo de citación de la citación"
                        else:
                            error = traductor(exception)
                        
                        linea = list(row)
                        linea.append(error)
                        listado_errores_excel.append(linea)
                
                if len(listado_errores_excel) != 0:
                    # OBTENEMOS LAS COLUMNAS DEL EXCEL CARGADO
                    columnas = list(df.columns.values)
                    # AGREGAMOS LA COLUMNA DE ERRORES
                    columnas.append('Error')
                    # ENVIAMOS EL LISTADO DE ERRORES Y LAS COLUMNAS A LA FUNCION DE CREACION DE EXCEL
                    link = excel_errores(listado_errores_excel, columnas)
                    # Agrega un mensaje de error con un enlace a la respuesta que es descargable.
                    message = f"Hay datos que no se pudieron guardar debido a que contienen errores, se ha generado un excel con los datos no guardados. <a href='{link}' download>Clic aquí para descargar el archivo Excel.</a>"
                    messages.info(request, message)
                    return redirect(f'/cit_listone/{id_citacion}')
                
                messages.success(request, f'Se agregaron {extra_created} extras correctamente')
                return redirect(f'/cit_listone/{id_citacion}')
            elif tipo == "Extra_masivo":
                usuario = request.user
                tipo_citacion = request.POST.get('tipo_citacion')
                for index, row in df.iterrows():
                    try:
                        if  not row[0] or row[0] == '' or str(row[0]).strip() == '':
                            raise Exception("No se puede agregar un extra sin ID de citación")
                        if not row[1] or row[1] == '' or str(row[1]).strip() == '':
                            raise Exception("No se puede agregar un extra ID")
                        if not row[2] or row[2] == '' or str(row[2]).strip() == '':
                            raise Exception("No se puede agregar un extra sin valor")
                        
                        citacion = CITACION.objects.get(id = row[0])
                        empresa = citacion.EP_NID
                        conductor = citacion.CON_NID
                        if usuario.is_superuser == False:
                            fecha_citacion = timezone.localtime(citacion.CI_FFECHACITACION)
                            diferencia_dias = (fecha_actual - fecha_citacion).days
                            if diferencia_dias > conductor.CON_NPERIODO_EXTRA:
                                raise Exception("No se puede agregar extras mas de " + str(conductor.CON_NPERIODO_EXTRA) + " días posteriores a la fecha de la citación")
                        
                        extra = EXTRA.objects.get(id = row[1])
                        if extra.EXT_CTIPO_CITACION != citacion.CI_CTIPO:
                            raise Exception("El tipo de citación del extra no coincide con el tipo de citación de la citación")
                        es_ingreso = extra.EXT_BINGRESO
                        valor = Decimal(row[1]).quantize(Decimal('0.00000'))
                        comentario = row[2]

                        CITACION_EXTRA.objects.create(
                            EP_NID = empresa,
                            US_NID = usuario,
                            EXT_NID = extra,
                            CI_NID = citacion,
                            CIE_NVALOR = valor,
                            CIE_FFECHAREGISTRO = datetime.now(),
                            CIE_BINGRESO = es_ingreso,
                            CIE_CCOMENTARIO = comentario
                        )
                        extra_created += 1
                    except Exception as e:
                        print(e)
                        exception = str(e)
                        if exception == "No se puede agregar un extra sin ID de citación":
                            error = "No se puede agregar un extra sin ID de citación"
                        elif exception == "No se puede agregar un extra ID":
                            error = "No se puede agregar un extra ID"
                        elif exception == "No se puede agregar un extra sin valor":
                            error = "No se puede agregar un extra sin valor"
                        elif exception == "No se puede agregar extras mas de " + str(conductor.CON_NPERIODO_EXTRA) + " días posteriores a la fecha de la citación":
                            error = "No se puede agregar extras mas de " + str(conductor.CON_NPERIODO_EXTRA) + " días posteriores a la fecha de la citación"
                        elif exception == "El tipo de citación del extra no coincide con el tipo de citación de la citación":
                            error = "El tipo de citación del extra no coincide con el tipo de citación de la citación"
                        else:
                            error = traductor(exception)
                        
                        linea = list(row)
                        linea.append(error)
                        listado_errores_excel.append(linea)
                
                if len(listado_errores_excel) != 0:
                    # OBTENEMOS LAS COLUMNAS DEL EXCEL CARGADO
                    columnas = list(df.columns.values)
                    # AGREGAMOS LA COLUMNA DE ERRORES
                    columnas.append('Error')
                    # ENVIAMOS EL LISTADO DE ERRORES Y LAS COLUMNAS A LA FUNCION DE CREACION DE EXCEL
                    link = excel_errores(listado_errores_excel, columnas)
                    # Agrega un mensaje de error con un enlace a la respuesta que es descargable.
                    message = f'Hay datos que no se pudieron guardar debido a que contienen errores, se ha generado un excel con los datos no guardados. <a href="{link}" download>Clic aquí para descargar el archivo Excel.</a>'
                    messages.info(request, message)
                    path = '/cit_listall_despachos/' if tipo_citacion == CIT_DESPACHO else '/cit_listall_recepciones/'
                    return redirect(path)
                
                messages.success(request, f'Se agregaron {extra_created} extras correctamente')
                path = '/cit_listall_despachos/' if tipo_citacion == CIT_DESPACHO else '/cit_listall_recepciones/'
                return redirect(path)
                
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def download_excel_plantilla_extra_citacion(request):
    try:
        columnas = ['ID EXTRA', 'VALOR', 'COMENTARIO']
        fila_ejemplo = ['1', '100', 'Comentario']
        # Crea un nuevo libro de trabajo de Excel.
        workbook = openpyxl.Workbook()

        # Selecciona la hoja activa.
        worksheet = workbook.active
        # CARGAMOS LA COLUMNAS 
        worksheet.append(columnas)

        # CARGAMOS LAS FILAS DE EJEMPLO
        worksheet.append(fila_ejemplo)

        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=plantilla_extra_citacion.xlsx'
        workbook.save(response)

        return response
    except Exception as e:
        print(e)
        return redirect('/')

def download_excel_plantilla_extra_planificacion(request):
    try:
        columnas = ['NÚMERO CITACION','ID EXTRA', 'VALOR', 'COMENTARIO']
        fila_ejemplo = ['1', '1', '100', 'Comentario']
        # Crea un nuevo libro de trabajo de Excel.
        workbook = openpyxl.Workbook()

        # Selecciona la hoja activa.
        worksheet = workbook.active
        # CARGAMOS LA COLUMNAS 
        worksheet.append(columnas)

        # CARGAMOS LAS FILAS DE EJEMPLO
        worksheet.append(fila_ejemplo)

        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=plantilla_extra.xlsx'
        workbook.save(response)

        return response
    except Exception as e:
        print(e)
        return redirect('/')

##########################################################################
###########################   CITACION   #################################
##########################################################################

def CITACION_LISTALL_DESPACHOS(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        else:
            usuario = request.user.id

        Empresa = Verificar_empresa(request)

        asignadas = USUARIO_SECUENCIA.objects.filter(
            US_NID_id=request.user.id,
            US_BHABILITADO=True
        ).values_list('SC_NID_id', flat=True)

        if asignadas.exists():
            secuencias = SECUENCIA.objects.filter(
                id__in=asignadas,
                SE_BHABILITADO=True,
                EP_NID_id=Empresa
            )
        else:
            secuencias = SECUENCIA.objects.filter(
                SE_BHABILITADO=True,
                EP_NID_id=Empresa
            )

        fecha_desde = request.GET.get('fecha_desde')
        fecha_hasta = request.GET.get('fecha_hasta')
        secuencia_id = request.GET.getlist('secuencia')
        proveedor = request.GET.get('proveedor')

        if not request.user.is_superuser:
            permiso_borrar = validar_perfiles_activos(usuario, "cit_delete")
        else:
            permiso_borrar = True

        if isinstance(fecha_desde, str):
            fecha_desde = parse_date(fecha_desde)
        if isinstance(fecha_hasta, str):
            fecha_hasta = parse_date(fecha_hasta)

        queryset = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CTIPO=CIT_DESPACHO,
            CI_BHABILITADO=True
        ).annotate(
            valor_campo_38=Subquery(
                DATO_OPERACION.objects.filter(
                    CI_NID=OuterRef('pk'),
                    CAMP_NID_id=38
                ).values('DO_CVALOR')[:1]
            )
        )

        if asignadas.exists():
            queryset = queryset.filter(SC_NID_id__in=asignadas)

        if secuencia_id:
            queryset = queryset.filter(SC_NID__in=secuencia_id)
            
        if fecha_desde and fecha_hasta:
            queryset = queryset.filter(CI_FFECHACITACION__date__range=[fecha_desde, fecha_hasta])
        else:
            if fecha_desde:
                queryset = queryset.filter(CI_FFECHACITACION__date__gte=fecha_desde)
            if fecha_hasta:
                queryset = queryset.filter(CI_FFECHACITACION__date__lte=fecha_hasta)
        
        if proveedor:
            queryset = queryset.filter(PRO_NID=proveedor)

        object_list = queryset.order_by('-id')
        
        paginator = Paginator(object_list, 100)
        page = request.GET.get('page')

        try:
            object_list = paginator.page(page)
        except PageNotAnInteger:
            object_list = paginator.page(1)
        except EmptyPage:
            object_list = paginator.page(paginator.num_pages)

        filtrado = 1 if (fecha_desde or fecha_hasta or secuencia_id or proveedor) else 0

        ltsProveedores = SOCIONEGOCIO.objects.filter(
            SN_CTIPO='S',
            SN_BHABILITADO=True
        )

        ctx = {
            'object_list': object_list,
            'filtrado': filtrado,
            'secuencias': secuencias,
            'secuencia_id': secuencia_id,
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'ltsProveedores': ltsProveedores,
            'permiso_borrar': permiso_borrar
        }

        query_params = request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')

        ctx['params'] = query_params.urlencode()

        return render(request, 'home/CITACION/cit_listall.html', ctx)

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/') 
    
def CITACION_LISTALL_RECEPCIONES(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        else:
            usuario = request.user.id

        Empresa = Verificar_empresa(request)

        asignadas = USUARIO_SECUENCIA.objects.filter(
            US_NID_id=request.user.id,
            US_BHABILITADO=True
        ).values_list('SC_NID_id', flat=True)

        if asignadas.exists():
            secuencias = SECUENCIA.objects.filter(
                id__in=asignadas,
                SE_BHABILITADO=True,
                EP_NID_id=Empresa
            )
        else:
            secuencias = SECUENCIA.objects.filter(
                SE_BHABILITADO=True,
                EP_NID_id=Empresa
            )

        fecha_desde = request.GET.get('fecha_desde')
        fecha_hasta = request.GET.get('fecha_hasta')
        secuencia_id = request.GET.getlist('secuencia')
        proveedor = request.GET.get('proveedor')

        if isinstance(fecha_desde, str):
            fecha_desde = parse_date(fecha_desde)

        if isinstance(fecha_hasta, str):
            fecha_hasta = parse_date(fecha_hasta)

        queryset = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CTIPO=CIT_RECEPCION,
            CI_BHABILITADO=True
        )

        # FILTRAR SOLO SECUENCIAS ASIGNADAS
        if asignadas.exists():
            queryset = queryset.filter(SC_NID_id__in=asignadas)

        if secuencia_id:
            queryset = queryset.filter(SC_NID__in=secuencia_id)
            
        if fecha_desde and fecha_hasta:
            queryset = queryset.filter(
                CI_FFECHACITACION__date__range=[fecha_desde, fecha_hasta]
            )
        else:
            if fecha_desde:
                queryset = queryset.filter(
                    CI_FFECHACITACION__date__gte=fecha_desde
                )

            if fecha_hasta:
                queryset = queryset.filter(
                    CI_FFECHACITACION__date__lte=fecha_hasta
                )
        
        if proveedor:
            queryset = queryset.filter(PRO_NID=proveedor)
        
        object_list = queryset.order_by('-id')
        
        paginator = Paginator(object_list, 100)
        page = request.GET.get('page')

        try:
            object_list = paginator.page(page)
        except PageNotAnInteger:
            object_list = paginator.page(1)
        except EmptyPage:
            object_list = paginator.page(paginator.num_pages)

        filtrado = 1 if (
            fecha_desde or 
            fecha_hasta or 
            secuencia_id or 
            proveedor
        ) else 0

        ltsProveedores = SOCIONEGOCIO.objects.filter(
            SN_CTIPO='S',
            SN_BHABILITADO=True
        )

        ctx = {
            'object_list': object_list,
            'filtrado': filtrado,
            'secuencias': secuencias,
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'secuencia_id': secuencia_id,
            'ltsProveedores': ltsProveedores
        }

        query_params = request.GET.copy()

        if 'page' in query_params:
            query_params.pop('page')

        ctx['params'] = query_params.urlencode()

        return render(
            request,
            'home/CITACION/cit_listall.html',
            ctx
        )

    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')  
def export_citaciones_despachos_excel(request):

    try:
        if not request.user.is_superuser:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        asignadas = USUARIO_SECUENCIA.objects.filter(
            US_NID_id=request.user.id,
            US_BHABILITADO=True
        ).values_list('SC_NID_id', flat=True)

        fecha_desde = request.GET.get('fecha_desde')
        fecha_hasta = request.GET.get('fecha_hasta')
        secuencia_id = request.GET.getlist('secuencia')

        if isinstance(fecha_desde, str):
            fecha_desde = parse_date(fecha_desde)
        if isinstance(fecha_hasta, str):
            fecha_hasta = parse_date(fecha_hasta)

        queryset = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CTIPO=CIT_DESPACHO,
            CI_BHABILITADO=True
        ).annotate(
            valor_campo_38=Subquery(
                DATO_OPERACION.objects.filter(
                    CI_NID=OuterRef('pk'),
                    CAMP_NID_id=38
                ).values('DO_CVALOR')[:1]
            )
        )

        if asignadas.exists():
            queryset = queryset.filter(SC_NID_id__in=asignadas)

        if secuencia_id:
            queryset = queryset.filter(SC_NID__in=secuencia_id)

        if fecha_desde and fecha_hasta:
            queryset = queryset.filter(CI_FFECHACITACION__date__range=[fecha_desde, fecha_hasta])
        else:
            if fecha_desde:
                queryset = queryset.filter(CI_FFECHACITACION__date__gte=fecha_desde)
            if fecha_hasta:
                queryset = queryset.filter(CI_FFECHACITACION__date__lte=fecha_hasta)

        object_list = queryset.order_by('-id')

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Citaciones Despachos"

        columnas = [
            'ID', 'Planificacion', 'Tipo de Documento', 'Número Documento',
            'Número Cupo', 'Fecha Citación', 'Nombre Secuencia',
            'Nombre Etapa', 'Cliente', 'Conductor', 'Camión', 'Proveedor'
        ]

        for col, header in enumerate(columnas, 1):
            worksheet.cell(row=1, column=col, value=header)

        for row, citacion in enumerate(object_list, 2):
            worksheet.cell(row=row, column=1, value=citacion.pk)
            worksheet.cell(row=row, column=2, value=citacion.PL_NID.id if citacion.PL_NID else '')
            worksheet.cell(row=row, column=3, value=citacion.CI_CTIPODOCUMENTO if citacion.CI_CTIPODOCUMENTO else '')
            worksheet.cell(row=row, column=4, value=citacion.valor_campo_38 if citacion.valor_campo_38 else citacion.CI_CNUMERODOCUMENTO)
            worksheet.cell(row=row, column=5, value=citacion.CI_NCUPO)
            worksheet.cell(row=row, column=6, value=citacion.CI_FFECHACITACION.strftime('%Y-%m-%d %H:%M') if citacion.CI_FFECHACITACION else '')
            worksheet.cell(row=row, column=7, value=citacion.SC_NID.SE_CCODIGO + ' - ' + citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else '')
            worksheet.cell(row=row, column=8, value=citacion.ETAPA_ACTUAL.ET_CCODIGO if citacion.ETAPA_ACTUAL else '')
            worksheet.cell(row=row, column=9, value=citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else '')
            worksheet.cell(row=row, column=10, value=(citacion.CON_NID.CON_CNOMBRE + ' ' + citacion.CON_NID.CON_CAPELLIDO) if citacion.CON_NID else '')
            worksheet.cell(row=row, column=11, value=citacion.CA_NID.CAM_CPATENTE if citacion.CA_NID else '')
            worksheet.cell(row=row, column=12, value=citacion.CON_NID.SN_NID.SN_CRAZONSOCIAL if citacion.CON_NID and citacion.CON_NID.SN_NID else '')

        for column in worksheet.columns:
            max_length = 0
            column = [cell for cell in column]
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column[0].column_letter].width = max_length + 2

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=citaciones_despachos_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        workbook.save(response)
        return response

    except Exception as e:
        print(e)
        messages.error(request, f'Error al exportar a Excel: {str(e)}')
        return redirect('cit_listall_despachos')
def export_citaciones_recepciones_excel(request):

    try:
        if not request.user.is_superuser:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)

        asignadas = USUARIO_SECUENCIA.objects.filter(
            US_NID_id=request.user.id,
            US_BHABILITADO=True
        ).values_list('SC_NID_id', flat=True)

        fecha_desde = request.GET.get('fecha_desde')
        fecha_hasta = request.GET.get('fecha_hasta')
        secuencia_id = request.GET.getlist('secuencia')

        if isinstance(fecha_desde, str):
            fecha_desde = parse_date(fecha_desde)
        if isinstance(fecha_hasta, str):
            fecha_hasta = parse_date(fecha_hasta)

        queryset = CITACION.objects.filter(
            EP_NID_id=Empresa,
            CI_CTIPO=CIT_RECEPCION,
            CI_BHABILITADO=True
        )

        if asignadas.exists():
            queryset = queryset.filter(SC_NID_id__in=asignadas)

        if secuencia_id:
            queryset = queryset.filter(SC_NID__in=secuencia_id)

        if fecha_desde and fecha_hasta:
            queryset = queryset.filter(CI_FFECHACITACION__date__range=[fecha_desde, fecha_hasta])
        else:
            if fecha_desde:
                queryset = queryset.filter(CI_FFECHACITACION__date__gte=fecha_desde)
            if fecha_hasta:
                queryset = queryset.filter(CI_FFECHACITACION__date__lte=fecha_hasta)

        object_list = queryset.order_by('-id')

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Citaciones Recepciones"

        columnas = [
            'ID', 'Planificacion', 'Tipo de Documento', 'Número Documento',
            'Número Cupo', 'Fecha Citación', 'Nombre Secuencia',
            'Nombre Etapa', 'Cliente', 'Conductor', 'Camión', 'Proveedor'
        ]

        for col, header in enumerate(columnas, 1):
            worksheet.cell(row=1, column=col, value=header)

        for row, citacion in enumerate(object_list, 2):
            worksheet.cell(row=row, column=1, value=citacion.pk)
            worksheet.cell(row=row, column=2, value=citacion.PL_NID.id if citacion.PL_NID else '')
            worksheet.cell(row=row, column=3, value=citacion.CI_CTIPODOCUMENTO if citacion.CI_CTIPODOCUMENTO else '')
            worksheet.cell(row=row, column=4, value=citacion.CI_CNUMERODOCUMENTO if citacion.CI_CNUMERODOCUMENTO else '')
            worksheet.cell(row=row, column=5, value=citacion.CI_NCUPO)
            worksheet.cell(row=row, column=6, value=citacion.CI_FFECHACITACION.strftime('%Y-%m-%d %H:%M') if citacion.CI_FFECHACITACION else '')
            worksheet.cell(row=row, column=7, value=citacion.SC_NID.SE_CCODIGO + ' - ' + citacion.SC_NID.SE_CNOMBRE if citacion.SC_NID else '')
            worksheet.cell(row=row, column=8, value=citacion.ETAPA_ACTUAL.ET_CCODIGO if citacion.ETAPA_ACTUAL else '')
            worksheet.cell(row=row, column=9, value=citacion.SN_NID.SN_CRAZONSOCIAL if citacion.SN_NID else '')
            worksheet.cell(row=row, column=10, value=(citacion.CON_NID.CON_CNOMBRE + ' ' + citacion.CON_NID.CON_CAPELLIDO) if citacion.CON_NID else '')
            worksheet.cell(row=row, column=11, value=citacion.CA_NID.CAM_CPATENTE if citacion.CA_NID else '')
            worksheet.cell(row=row, column=12, value=citacion.CON_NID.SN_NID.SN_CRAZONSOCIAL if citacion.CON_NID and citacion.CON_NID.SN_NID else '')

        for column in worksheet.columns:
            max_length = 0
            column = [cell for cell in column]
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column[0].column_letter].width = max_length + 2

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=citaciones_recepciones_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        workbook.save(response)
        return response

    except Exception as e:
        print(e)
        messages.error(request, f'Error al exportar a Excel: {str(e)}')
        return redirect('cit_listall_recepciones')

def CITACION_LISTONE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        
        notificacion = request.GET.get('notificacion')
        if notificacion:
            notificacion = NOTIFICACION.objects.get(id = int(notificacion))
            if notificacion.USER_RECEIVER_ID == request.user:
                notificacion.NOT_BREAD = True
                notificacion.save()
        
        citacion = CITACION.objects.get(id = pk)
        citacion_item = CITACION_ITEM.objects.get(CI_NID = citacion)
        citacion_extras = CITACION_EXTRA.objects.filter(CI_NID = citacion)
        extras = EXTRA.objects.filter(EP_NID = citacion.EP_NID, EXT_BHABILITADO = True, EXT_CTIPO_CITACION = citacion.CI_CTIPO)
        ltsSecuencias = None
        grouped_data = {}
        datos_etapa = {}
        lineas_etapa = None
        grouped_data_etapa_actual = None
        etapa_log = None

        # MODIFICACIÓN 1: Obtener solo etapas activas para la secuencia actual
        etapas = GetPreviewSecuenciaActiva(citacion.SC_NID.pk, citacion.EP_NID.pk)
        etapas_salida = getCantEtapaSalida(citacion.EP_NID.pk, citacion.SC_NID.pk)
        
        if etapas is not None:
            for campo in etapas:
                datos = []
                if campo[1].lower() == 'lista':
                    try:
                        datos = QueryParam(campo[6])
                    except Exception as e:
                        print("Error al ejecutar la consulta", e)
                        messages.warning(request, f'Error, {str(e)}')

                step_key = campo[0]  # Uso de la palabra como clave en un diccionario
                if step_key not in grouped_data:
                    grouped_data[step_key] = []

                grouped_data[step_key].append({
                    'TYPE': campo[1].lower(),
                    'DEFAULT_VALUE': campo[2],
                    'PLACEHOLDER': campo[3],
                    'LARGO': campo[4],
                    'OBLIGATORIO': campo[5],
                    'DATOS': datos,
                    'ID_CAMPO': step_key.replace(' ', '') + '_' + str(campo[7]),
                })
        
        # VERIFICAMOS SI EXISTE UNA NUEVA ETAPA
        etapa_actual = citacion.ETAPA_ACTUAL
        
        # MODIFICACIÓN 2: Verificar si la etapa actual está habilitada
        detalle_secuencia_actual = DETALLE_SECUENCIA.objects.filter(
            SC_NID=citacion.SC_NID, 
            ET_NID=etapa_actual, 
            SE_BHABILITADO=True
        ).first()
        
        # Si la etapa actual fue eliminada, reasignar automáticamente
        if not detalle_secuencia_actual and citacion.CI_CESTADO == 'EN PROCESO':
            # Cerrar log de etapa eliminada
            ETAPA_LOG.objects.filter(
                CI_NID=citacion,
                SC_NID=citacion.SC_NID,
                ET_NID=etapa_actual,
                EL_FFECHAFIN=None
            ).update(EL_FFECHAFIN=timezone.now())
            
            # Obtener nueva etapa actual después de la eliminación
            etapa_actual = citacion.ETAPA_ACTUAL
            detalle_secuencia_actual = DETALLE_SECUENCIA.objects.get( 
                SC_NID=citacion.SC_NID, 
                ET_NID=etapa_actual, 
                SE_BHABILITADO=True
            )
        
        siguiente_etapa = citacion.ETAPA_SIGUIENTE
        datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = etapa_actual)

        if siguiente_etapa or not datos_operacion:
            if etapa_actual.ET_CCODIGO in grouped_data:
                grouped_data_etapa_actual = grouped_data[etapa_actual.ET_CCODIGO]
                if etapa_actual.ET_BINTEGRARSAP == True and etapa_actual.ET_BISCABECERA == True:
                    etapa_linea = GetEtapaLinea(citacion.SC_NID.id, etapa_actual.id)
                    if etapa_linea and etapa_linea[3] in grouped_data:
                        lineas_etapa = grouped_data[etapa_linea[3]]
        
        campo_validate_sap = GetCampoValidateSap(etapa_actual.id)
        if campo_validate_sap:
            campo_validate_sap = [elemento for tupla in campo_validate_sap for elemento in tupla]

        # MODIFICACIÓN 3: Obtener logs de etapas con datos históricos
        if citacion.CI_CESTADO == CIT_CREADO or citacion.CI_CESTADO == CIT_EN_PROCESO:
            etapas_log = ETAPA_LOG.objects.filter(
                CI_NID=citacion, 
                SC_NID=citacion.SC_NID
            ).exclude(ET_NID=etapa_actual)
        else:
            etapas_log = ETAPA_LOG.objects.filter(CI_NID=citacion, SC_NID=citacion.SC_NID)

        # Obtener todos los pesos (DO_NPESO) de DATO_OPERACION para esta citación
        pesos_dato_operacion = {}
        datos_operacion_pesos = DATO_OPERACION.objects.filter(
            CI_NID=citacion,
            SC_NID=citacion.SC_NID
        ).exclude(DO_NPESO__isnull=True).exclude(DO_NPESO=0)
        
        for dato in datos_operacion_pesos:
            # Usar el ID del campo (CAMP_NID) como llave
            pesos_dato_operacion[dato.CAMP_NID.pk] = dato.DO_NPESO
        
        # MODIFICACIÓN 4: Solo mostrar etapas que tienen datos cargados
        for log in etapas_log:
            # Verificar si hay datos operacionales para esta etapa
            tiene_datos = DATO_OPERACION.objects.filter(
                CI_NID=citacion,
                SC_NID=citacion.SC_NID,
                ET_NID=log.ET_NID
            ).exists()
            
            # Solo procesar si tiene datos cargados
            if tiene_datos:
                step_key = log.ET_NID.ET_CCODIGO
                campos = GetPreviewEtapaConDatos(log.ET_NID.pk, citacion.pk, citacion.SC_NID.pk)
                
                if campos:  # Solo agregar si tiene campos con datos
                    if step_key not in datos_etapa:
                        datos_etapa[step_key] = []
                    
                    for campo in campos:
                        campo_id = campo[6]  # ID del campo principal (campo[6] según GetPreviewEtapaConDatos)
                        peso_campo = pesos_dato_operacion.get(campo_id)
                        
                        # Obtener datos de lista si el campo es de tipo 'lista'
                        datos_lista = []
                        if campo[0].lower() == 'lista' and campo[5]:  # campo[5] es QUERY
                            try:
                                datos_lista = QueryParam(campo[5])
                            except Exception as e:
                                print(f"Error al ejecutar la consulta para campo {campo_id}: {e}")
                                datos_lista = []
                        
                        datos_etapa[step_key].append({
                            'TYPE': campo[0].lower(),
                            'ETIQUETA': campo[7],
                            'VALOR': campo[8],  # Valor del dato operacional
                            'ID': campo[9],      # ID del dato operacional
                            'ID_CAMPO': campo_id,  # ID del campo principal
                            'PESO': peso_campo,  # Peso del campo desde DO_NPESO
                            'DATOS': datos_lista  # Datos para campos de tipo lista
                        })
                
        if citacion.CI_CESTADO == CIT_CREADO:
            ltsSecuencias = SECUENCIA.objects.filter(SE_BHABILITADO = True).exclude(id = citacion.SC_NID.id)
        else:
            etapa_log = ETAPA_LOG.objects.filter(CI_NID = citacion)

        responsables = []
        
        if citacion.CI_CESTADO == CIT_EN_PROCESO and detalle_secuencia_actual:
            responsables_str = detalle_secuencia_actual.USERS_RESPONSABLE_ID
            responsables_str = responsables_str.replace('[', '')
            responsables_str = responsables_str.replace(']', '')
            listado = responsables_str.split(',')
            for numero in listado:
                numero_sin_comillas = numero.replace("'", '').replace('"', '')
                id_usuario = int(numero_sin_comillas)
                responsables.append(id_usuario)
            usuarios_admin = User.objects.filter(is_superuser = True)
            for user in usuarios_admin:
                responsables.append(user.pk)
            
        ltsConductores = []
        ltsCamiones = []
        ltsProveedores = []
        if citacion.CON_NID:
            ltsConductores = CONDUCTOR.objects.filter(
                SN_NID = citacion.PRO_NID.pk, 
                CON_BHABILITADO = True
            ).exclude(id = citacion.CON_NID.pk)
        if citacion.CA_NID:
            ltsCamiones = CAMION.objects.filter(
                CAM_BHABILITADO = True, 
                SN_NID = citacion.PRO_NID.pk
            ).exclude(id = citacion.CA_NID.pk)
        if citacion.PRO_NID:
            ltsProveedores = SOCIONEGOCIO.objects.filter(
                EP_NID = citacion.EP_NID,
                SN_BHABILITADO = True,
                SN_CTIPO = 'S'
            ).exclude(id = citacion.PRO_NID.pk)
        
        cupos_proveedor = CUPO_PROVEEDOR.objects.filter(PLA_NID = citacion.PL_NID)

        has_permiso = False
        if request.user.is_superuser == False:
            if validar_perfiles_activos(usuario, "marcar_conforme"):
                has_permiso = True
        else:
            has_permiso = True
        
        proforma = CITACION_PROFORMA.objects.filter().first()
        if not proforma:
            rutas = RUTA.objects.filter(RUT_BHABILITADO = True)
        else:
            if proforma.PRO_NID.PRO_CESTADO != 'AUTORIZADO':
                rutas = RUTA.objects.filter(RUT_BHABILITADO = True)
            else:
                rutas = []
                
        fletes = PARAMETRO.objects.filter(PM_CGRUPO = 'TIPO_FLETE', PM_NVALOR1 = citacion.EP_NID.pk)
        
        ctx = {
            'citacion': citacion,
            'citacion_item': citacion_item,
            'citacion_extras': citacion_extras,
            'detalles_secuencia': grouped_data,
            'grouped_data_etapa_actual': grouped_data_etapa_actual,
            'lineas_etapa': lineas_etapa,
            'datos_etapa': datos_etapa,
            'ltsSecuencias': ltsSecuencias,
            'detalle_secuencia_actual': detalle_secuencia_actual,
            'campo_validate_sap': campo_validate_sap,
            'etapas_salida': etapas_salida,
            'extras': extras,
            'etapa_log': etapa_log,
            'ltsConductores': ltsConductores,
            'ltsCamiones': ltsCamiones,
            'ltsProveedores': ltsProveedores,
            'responsables': responsables,
            'cupos_proveedor': cupos_proveedor,
            'has_permiso': has_permiso,
            'rutas': rutas,
            'ltsFlete': fletes,
            'pesos_dato_operacion': pesos_dato_operacion  # Diccionario con pesos por campo_id
        }

        return render(request, 'home/CITACION/cit_listone.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{pk}')


def CITACION_EDITAR_FLETE(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        
        flete = request.POST.get('flete')
        
        citacion.CI_CTIPO_FLETE = flete
        citacion.save()
        
        messages.success(request, 'Flete editado correctamente')
        return redirect(f'/cit_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{pk}')


def FINALIZAR_SECUENCIA(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        etapa_actual = citacion.ETAPA_ACTUAL
        siguiente_etapa = citacion.ETAPA_SIGUIENTE
        if siguiente_etapa is None:
            etapa_log = ETAPA_LOG.objects.filter(CI_NID = citacion, ET_NID = etapa_actual, SC_NID = citacion.SC_NID).first()
            etapa_log.ET_FFECHATERMINO = datetime.now()
            etapa_log.save()

            citacion.CI_FFECHATERMINO = datetime.now()
            citacion.CI_CESTADO = CIT_TERMINADO

            citacion.save()
            messages.success(request, 'Secuencia finalizada correctamente')
            return redirect(f'/cit_listone/{pk}')

        etapas = GetPreviewSecuencia(citacion.SC_NID.pk, citacion.EP_NID.pk)
        id_etapa_salida, etapa_salida = getEtapaSalida(citacion.EP_NID.pk, citacion.SC_NID.pk)
        if etapas is not None:
            grouped_data = {}
            for campo in etapas:
                if campo[8] != id_etapa_salida:
                    continue
                datos = []
                if campo[1].lower() == 'lista':
                    try:
                        datos = QueryParam(campo[6])
                    except Exception as e:
                        print("Error al ejecutar la consulta", e)
                        messages.warning(request, f'Error, {str(e)}')

                step_key = campo[0]  # Uso de la palabra como clave en un diccionario
                if step_key not in grouped_data:
                    grouped_data[step_key] = []

                grouped_data[step_key].append({
                    'TYPE': campo[1].lower(),
                    'DEFAULT_VALUE': campo[2],
                    'PLACEHOLDER': campo[3],
                    'LARGO': campo[4],
                    'OBLIGATORIO': campo[5],
                    'DATOS': datos,
                    'ID_CAMPO': step_key.replace(' ', '') + '_' + str(campo[7]),
                })

        #en el caso de que la etapa sea de salida es necesario que no se muestre

        grouped_data_etapa_actual = grouped_data[etapa_salida]

        datos_secuencia = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = citacion.SC_NID)
        datos_etapa = {}
        for valor_campo in datos_secuencia:
            step_key = valor_campo.ET_NID.ET_CCODIGO
            if step_key not in datos_etapa:
                datos_etapa[step_key] = []

            datos_etapa[step_key].append({
                'TYPE': valor_campo.CAMP_NID.CA_CTIPO.lower(),
                'ETIQUETA': valor_campo.CAMP_NID.CA_CETIQUETA,
                'VALOR': valor_campo.DO_CVALOR,
                'ID': valor_campo.pk
            })

        ctx = {
            'citacion': citacion,
            'detalles_secuencia': grouped_data,
            'grouped_data_etapa_actual': grouped_data_etapa_actual,
            'datos_etapa': datos_etapa,
            'etapas_salida': id_etapa_salida
        }

        return render(request, 'home/CITACION/cit_finalizar_secuencia.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        path = '/cit_listall_despachos/' if citacion.CI_CTIPO == 'DESPACHO' else '/cit_listall_recepciones/'
        return redirect(path)

def CITACION_ADDVARIOSPRE(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_addvarios"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        num_citaciones = request.GET.get('cantidad_citaciones')
        es_venta = request.GET.get('is-venta')
        pl_nid = request.GET.get('PL_NID')
        tipo_secuencia = CIT_DESPACHO if es_venta else CIT_RECEPCION
        planificacion = PLANIFICACION.objects.get(pk = pl_nid)
        ltsDocumento = LISTADO_DOCUMENTO.objects.filter(LIS_BHABILITADO = True, LIS_CGRUPO = 'Citacion').order_by('id')
        if es_venta:
            ltsProveedores = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'S')
            ltsRutas = RUTA.objects.filter(RUT_BHABILITADO = True)
            ltsTarifas = []
            ltsSocios = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'C')
            ltsConductores = []
            ltsCamiones = []
            venta = True
        else:
            ltsProveedores = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'S')
            venta = False
            ltsCamiones = None
            ltsSocios = None
            ltsConductores = None
            ltsRutas = RUTA.objects.filter(RUT_BHABILITADO = True)
            ltsTarifas = []


        ltsSecuencias = SECUENCIA.objects.filter(SE_BHABILITADO = True, SE_CTIPO = tipo_secuencia)
        ltsItems = ITEM.objects.filter()

        row_citaciones = [i for i in range(1, int(num_citaciones)+1)]
        ltsFlete = []
        ltsEmpresas = EMPRESA.objects.all()
        
        ltsClientes = SOCIONEGOCIO.objects.filter(SN_BHABILITADO = True, SN_CTIPO = 'C')

        ctx = {
            'num_citaciones': num_citaciones,
            'row_citaciones': row_citaciones,
            'planificacion': planificacion,
            'ltsRutas': ltsRutas,
            'ltsTarifas': ltsTarifas,
            'ltsSocios': ltsSocios,
            'ltsConductores': ltsConductores,
            'ltsCamiones': ltsCamiones,
            'ltsSecuencias': ltsSecuencias,
            'ltsItems': ltsItems,
            'venta': venta,
            'ltsDocumento': ltsDocumento,
            'ltsProveedores': ltsProveedores,
            'ltsFlete': ltsFlete,
            'ltsEmpresas': ltsEmpresas,
            'ltsClientes': ltsClientes
        }
        return render(request, 'home/CITACION/cit_addvarios.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/pla_listone/{pl_nid}')
    
def CITACION_ADDVARIOS(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_addvarios"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        if request.method == 'POST':
            tableData = json.loads(request.POST.get('data'))
            id_planificacion = request.POST.get('id_planificacion')

            planificacion = PLANIFICACION.objects.get(id = id_planificacion)
            empresa = planificacion.EP_NID

            num_citaciones_planificacion = CITACION.objects.filter(PL_NID = planificacion).count()
            es_venta = True if request.POST.get('venta') == 'true' else False
            tipo_citacion = CIT_DESPACHO if es_venta else CIT_RECEPCION
            tarifa = ''
            for index, row in enumerate(tableData):
                proveedor = SOCIONEGOCIO.objects.get(id = row['id_proveedor'])
                
                if row["empresa"]:
                   empresa = EMPRESA.objects.get(id = row["empresa"]) 
                
                if es_venta:
                    
                    proveedor = SOCIONEGOCIO.objects.get(id = row['id_proveedor'])
                    if not proveedor.SN_BGENERICO:
                        conductor = CONDUCTOR.objects.get(id = row['id_conductor'])
                        camion = CAMION.objects.get(id = row['id_camion'])
                        if row['id_tarifa']:
                            tarifa = TARIFA_GLOBAL.objects.get(id = row['id_tarifa'])
                        else:
                            tarifa = None
                    else:
                        conductor = CONDUCTOR.objects.filter(EP_NID = empresa, SN_NID = proveedor, CON_BHABILITADO = True, CON_CNOMBRE__icontains = row['id_conductor']).first()
                        if not conductor:
                            conductor = CONDUCTOR.objects.create(
                                EP_NID = empresa,
                                SN_NID = proveedor,
                                US_NID = request.user,
                                CON_CNOMBRE = row['id_conductor'],
                                CON_CAPELLIDO = "",
                                CON_CRUT = '55555555-5'
                            )
                        camion = CAMION.objects.filter(EP_NID= empresa, SN_NID = proveedor, CAM_BHABILITADO = True, CAM_CPATENTE__icontains = row['id_camion']).first()
                        if not camion:
                            camion = CAMION.objects.create(
                                EP_NID = empresa,
                                SN_NID = proveedor,
                                US_NID = request.user,
                                CAM_CPATENTE = row['id_camion'],
                                CAM_FFECHAREGISTRO = datetime.now()
                            )
                else:

                    if not proveedor.SN_BGENERICO:
                        conductor = CONDUCTOR.objects.get(id = row['id_conductor'])
                        camion = CAMION.objects.get(id = row['id_camion'])
                        if row['id_tarifa']:
                            tarifa = TARIFA_GLOBAL.objects.get(id = row['id_tarifa'])
                        else:
                            tarifa = None

                    else:
                        conductor = CONDUCTOR.objects.filter(EP_NID = empresa, SN_NID = proveedor, CON_BHABILITADO = True, CON_CNOMBRE__icontains = row['id_conductor']).first()
                        if not conductor:
                            conductor = CONDUCTOR.objects.create(
                                EP_NID = empresa,
                                SN_NID = proveedor,
                                US_NID = request.user,
                                CON_CNOMBRE = row['id_conductor'],
                                CON_CAPELLIDO = "",
                                CON_CRUT = '55555555-5'
                            )
                        camion = CAMION.objects.filter(EP_NID= empresa, SN_NID = proveedor, CAM_BHABILITADO = True, CAM_CPATENTE__icontains = row['id_camion']).first()
                        if not camion:
                            camion = CAMION.objects.create(
                                EP_NID = empresa,
                                SN_NID = proveedor,
                                US_NID = request.user,
                                CAM_CPATENTE = row['id_camion'],
                                CAM_FFECHAREGISTRO = datetime.now()
                            )

                item = ITEM.objects.get(id = row['id_producto'])
                ncupo = num_citaciones_planificacion + (index + 1)
                secuencia = SECUENCIA.objects.get(id = row['id_secuencia'])
                tipo_flete = row['tipo_flete']
                cliente = None
                if es_venta:
                    cliente = SOCIONEGOCIO.objects.get(id = row["id_cliente"])

                hora_citacion = row['hora_citacion']
                fecha_citacion_str = planificacion.PL_FFECHAINICIO.strftime('%Y-%m-%d') + ' ' + hora_citacion
                fecha_citacion = datetime.strptime(fecha_citacion_str, '%Y-%m-%d %H:%M')
                if proveedor.SN_BGENERICO:
                    tarifa = None  # Asignar tarifa automática
                    valor_tarifa = None  # Obtener valor de tarifa si existe
                else:
                    valor_tarifa = tarifa.TAR_NVALOR if tarifa else None   # Asignar valor de tarifa solo si no es venta
                citacion = CITACION.objects.create(
                    PL_NID = planificacion,
                    EP_NID = empresa,
                    CON_NID = conductor,
                    CA_NID = camion,
                    SC_NID = secuencia,
                    US_NID = request.user,
                    PRO_NID = proveedor,
                    TAR_NID = tarifa if not es_venta and tarifa else None,  # Asignar tarifa solo si no es venta
                    RUT_NID = tarifa.RUT_NID if not es_venta and tarifa else None,
                    CI_FFECHAREGISTRO = datetime.now(),
                    CI_FFECHACITACION = fecha_citacion,
                    CI_CESTADO = CIT_CREADO,
                    CI_NCUPO = ncupo,
                    CI_CCOMENTARIO = row['observacion'],
                    CI_CTIPODOCUMENTO = row['tipo_documento'],
                    CI_CNUMERODOCUMENTO = row['numero_documento'],
                    CI_CTIPO = tipo_citacion,
                    CI_NVALORTARIFA = valor_tarifa,
                    CI_CTIPO_FLETE = tipo_flete,
                    SN_NID = cliente
                )
                CITACION_ITEM.objects.create(
                    EP_NID = empresa,
                    CI_NID = citacion,
                    IT_NID = item
                )
            return JsonResponse({'valid': True})
    except Exception as e:
        print('Error ',e)
        messages.error(request, f'Error, {str(e)}')
        return JsonResponse({'valid': False, 'msg': str(e)})

def buscar_proveedores(request):
    query = request.GET.get('q', '')
    empresa_id = request.GET.get('empresa_id')  # Asegúrate de pasar el ID de la empresa desde el frontend

    proveedores = SOCIONEGOCIO.objects.filter(
        EP_NID_id=empresa_id,
        SN_BHABILITADO=True,
        SN_CTIPO='S'
    ).filter(
        Q(SN_CRAZONSOCIAL__icontains=query) | Q(SN_CRUT__icontains=query)
    )[:20]  # Limitar a 20 resultados

    data = {
        'items': [{'id': p.id, 'text': f"{p.SN_CRAZONSOCIAL} ({p.SN_CRUT})"} for p in proveedores],
        'total_count': proveedores.count(),
    }

    return JsonResponse(data)

def buscar_clientes(request):
    query = request.GET.get('q', '')
    empresa_id = request.GET.get('empresa_id')  # Asegúrate de pasar el ID de la empresa desde el frontend

    clientes = SOCIONEGOCIO.objects.filter(
        EP_NID_id=empresa_id,
        SN_BHABILITADO=True,
        SN_CTIPO='C'
    ).filter(
        Q(SN_CRAZONSOCIAL__icontains=query) | Q(SN_CRUT__icontains=query)
    )[:20]  # Limitar a 20 resultados

    data = {
        'items': [{'id': c.id, 'text': f"{c.SN_CRAZONSOCIAL} ({c.SN_CRUT})"} for c in clientes],
        'total_count': clientes.count(),
    }

    return JsonResponse(data)

def get_citation_data(request, pk):
    try:
        citacion = CITACION.objects.get(id=pk)
        empresa = citacion.EP_NID
        citacion_item = CITACION_ITEM.objects.get(CI_NID=citacion)

        # Obtener la lista de documentos
        ltsDocumento = LISTADO_DOCUMENTO.objects.filter(EP_NID=empresa, LIS_BHABILITADO=True, LIS_CGRUPO='Citacion')

        # Obtener otras listas necesarias
        ltsProveedores = SOCIONEGOCIO.objects.filter(EP_NID=empresa, SN_BHABILITADO=True, SN_CTIPO='S')
        ltsClientes = SOCIONEGOCIO.objects.filter(EP_NID=empresa, SN_BHABILITADO=True, SN_CTIPO='C')
        ltsConductores = CONDUCTOR.objects.filter(EP_NID=empresa, CON_BHABILITADO=True)
        ltsCamiones = CAMION.objects.filter(EP_NID=empresa, CAM_BHABILITADO=True)
        ltsSecuencias = SECUENCIA.objects.filter(EP_NID=empresa, SE_BHABILITADO=True)
        ltsItems = ITEM.objects.filter(EP_NID=empresa)
        ltsTarifas = TARIFA_GLOBAL.objects.filter(EP_NID=empresa, TAR_BHABILITADO=True)
        proveedor = citacion.PRO_NID

        data = {
            'tipos_documento': render_to_string('home/partials/select_options.html', {
                'options': [{'id': doc.LIS_CNOMBREDOCUMENTO, 'name': doc.LIS_CNOMBREDOCUMENTO} for doc in ltsDocumento],
                'selected': citacion.CI_CTIPODOCUMENTO
            }),
            'numero_documento': citacion.CI_CNUMERODOCUMENTO,
            'proveedor': {
                'id': citacion.PRO_NID.id,
                'text': f"{citacion.PRO_NID.SN_CRAZONSOCIAL} ({citacion.PRO_NID.SN_CRUT})"
            },
            'cliente': {
                'id': citacion.SN_NID.id if citacion.SN_NID else None,
                'text': f"{citacion.SN_NID.SN_CRAZONSOCIAL} ({citacion.SN_NID.SN_CRUT})" if citacion.SN_NID else None
            },
            'tipo_citacion': citacion.CI_CTIPO,
            'conductores': render_to_string('home/partials/select_options.html', {
                'options': [{'id': cond.id, 'name': f"{cond.CON_CNOMBRE} {cond.CON_CAPELLIDO}"} for cond in ltsConductores],
                'selected': citacion.CON_NID.id if citacion.CON_NID else 1
            }),
            'camiones': render_to_string('home/partials/select_options.html', {
                'options': [{'id': cam.id, 'name': cam.CAM_CPATENTE} for cam in ltsCamiones],
                'selected': citacion.CA_NID.id if citacion.CA_NID else 1
            }),
            'secuencias': render_to_string('home/partials/select_options.html', {
                'options': [{'id': sec.id, 'name': sec.SE_CNOMBRE} for sec in ltsSecuencias],
                'selected': citacion.SC_NID.id
            }),
            'hora_citacion': citacion.CI_FFECHACITACION.strftime('%H:%M'),
            'productos': render_to_string('home/partials/select_options.html', {
                'options': [{'id': item.id, 'name': item.IT_CNOMBRE} for item in ltsItems],
                'selected': citacion_item.IT_NID.id
            }),
            'tarifas': render_to_string('home/partials/select_options.html', {
                'options': [{'id': tar.id, 'name': f"{tar.TAR_CNOMBRETARIFA} - {tar.TAR_NVALOR:,.0f}"} for tar in ltsTarifas],
                'selected': citacion.TAR_NID.id if citacion.TAR_NID else ''
            }),
            'observacion': citacion.CI_CCOMENTARIO,
            'estado': citacion.CI_CESTADO,

        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

def get_proveedor_data(request, proveedor_id):
    try:
        proveedor = SOCIONEGOCIO.objects.get(id=proveedor_id)
        empresa = proveedor.EP_NID

        # Obtener los valores actuales de la citación si existe
        citacion_id = request.GET.get('citacion_id')
        conductor_selected = ''
        camion_selected = ''
        tarifa_selected = ''
        
        if citacion_id:
            try:
                citacion = CITACION.objects.get(id=citacion_id)
                conductor_selected = citacion.CON_NID.id if citacion.CON_NID else 1
                camion_selected = citacion.CA_NID.id if citacion.CA_NID else 1
                tarifa_selected = citacion.TAR_NID.id if citacion.TAR_NID else ''
            except CITACION.DoesNotExist:
                pass

        conductores = CONDUCTOR.objects.filter(EP_NID=empresa, SN_NID=proveedor, CON_BHABILITADO=True)
        camiones = CAMION.objects.filter(EP_NID=empresa, SN_NID=proveedor, CAM_BHABILITADO=True)
        tarifas = TARIFA_GLOBAL.objects.filter(EP_NID=empresa, SN_NID=proveedor, TAR_BHABILITADO=True)

        data = {
            'conductores': render_to_string('home/partials/select_options.html', {
                'options': [{'id': cond.id, 'name': f"{cond.CON_CNOMBRE} {cond.CON_CAPELLIDO}"} for cond in conductores] + [{'id': 1, 'name': 'Conductor Genérico'}],
                'selected': conductor_selected
            }),
            'camiones': render_to_string('home/partials/select_options.html', {
                'options': [{'id': cam.id, 'name': cam.CAM_CPATENTE} for cam in camiones] + [{'id': 1, 'name': 'Camión Genérico'}],
                'selected': camion_selected
            }),
            'tarifas': render_to_string('home/partials/select_options.html', {
                'options': [{'id': tar.id, 'name': f"{tar.TAR_CNOMBRETARIFA} - {tar.TAR_NVALOR:,.0f}"} for tar in tarifas],
                'selected': tarifa_selected
            }),
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

def update_citation(request, pk):
    if request.method == 'POST':
        try:
            citacion = CITACION.objects.get(id=pk)
            
            # Update citation fields
            citacion.CI_CTIPODOCUMENTO = request.POST.get('tipo_documento')
            citacion.CI_CNUMERODOCUMENTO = request.POST.get('numero_documento')
            citacion.PRO_NID = SOCIONEGOCIO.objects.get(id=request.POST.get('id_proveedor'))
            
            # Actualizar cliente solo si es un despacho
            if citacion.CI_CTIPO == CIT_DESPACHO:
                cliente_id = request.POST.get('id_cliente')
                if cliente_id:
                    try:
                        citacion.SN_NID = SOCIONEGOCIO.objects.get(id=cliente_id)
                    except SOCIONEGOCIO.DoesNotExist:
                        return JsonResponse({'valid': False, 'msg': 'El cliente seleccionado no existe'})
                else:
                    citacion.SN_NID = None
            
            conductor_id = int(request.POST.get('id_conductor'))
            if conductor_id == 1:
                citacion.CON_NID = None
            else:
                citacion.CON_NID = CONDUCTOR.objects.get(id=conductor_id)
            
            camion_id = int(request.POST.get('id_camion'))
            if camion_id == 1:
                citacion.CA_NID = None
            else:
                citacion.CA_NID = CAMION.objects.get(id=camion_id)

            # Verificar si existe la secuencia antes de asignarla
            secuencia_id = request.POST.get('id_secuencia')
            if secuencia_id:
                try:
                    secuencia = SECUENCIA.objects.get(id=secuencia_id)
                    citacion.SC_NID = secuencia
                except SECUENCIA.DoesNotExist:
                    return JsonResponse({'valid': False, 'msg': 'La secuencia seleccionada no existe'})
            
            # Update citation time
            fecha_citacion = citacion.CI_FFECHACITACION.date()
            hora_citacion = datetime.strptime(request.POST.get('hora_citacion'), '%H:%M').time()
            citacion.CI_FFECHACITACION = datetime.combine(fecha_citacion, hora_citacion)
            
            # Actualizar tarifa y su valor
            tarifa_id = request.POST.get('id_tarifa')
            if tarifa_id:
                try:
                    tarifa = TARIFA_GLOBAL.objects.get(id=tarifa_id)
                    citacion.TAR_NID = tarifa
                    citacion.CI_NVALORTARIFA = tarifa.TAR_NVALOR
                except TARIFA_GLOBAL.DoesNotExist:
                    citacion.TAR_NID = None
                    citacion.CI_NVALORTARIFA = None
            else:
                citacion.TAR_NID = None
                citacion.CI_NVALORTARIFA = None

            citacion.CI_CCOMENTARIO = request.POST.get('observacion')
            citacion.save()
            
            # Update or create CITACION_ITEM
            producto_id = request.POST.get('id_producto')
            if producto_id:
                citacion_item, created = CITACION_ITEM.objects.update_or_create(
                    CI_NID=citacion,
                    defaults={'IT_NID': ITEM.objects.get(id=producto_id)}
                )
            
            return JsonResponse({'valid': True})
        except Exception as e:
            return JsonResponse({'valid': False, 'msg': str(e)})
    return JsonResponse({'valid': False, 'msg': 'Invalid request method'})

def CITACION_DELETE(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        proforma = CITACION_PROFORMA.objects.filter(CI_NID = citacion)
        if proforma:
            messages.error(request, 'No se puede eliminar la citación porque está asociada a una proforma.')
            return redirect(f'/cit_listall_despachos/')
        citacion.CI_BHABILITADO = False
        citacion.save()
        messages.success(request, 'Citación eliminada correctamente.')
        path = '/cit_listall_despachos/' if citacion.CI_CTIPO == CIT_DESPACHO else '/cit_listall_recepciones/'
        return redirect(path)
    except Exception as e:
        print(e)
        path = '/cit_listall_despachos/' if citacion.CI_CTIPO == CIT_DESPACHO else '/cit_listall_recepciones/'
        messages.error(request, f'Error, {str(e)}')
        return redirect(path)

def CITACION_INICIAR_SECUENCIA(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        citacion.CI_CESTADO = CIT_EN_PROCESO
        citacion.CI_FFECHAINICIO = datetime.now()
        citacion.save()
        ETAPA_LOG.objects.create(
            CI_NID = citacion,
            EP_NID = citacion.EP_NID,
            SC_NID = citacion.SC_NID,
            ET_NID = citacion.ETAPA_ACTUAL,
            EL_FFECHAINICIO = datetime.now()
        )        
        messages.success(request, 'Secuencia iniciada correctamente.')
        return redirect(f'/cit_listone/{citacion.id}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{citacion.id}')

def CITACION_ADDSTEP(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        empresa = citacion.EP_NID
        secuencia = citacion.SC_NID
        etapa_actual = citacion.ETAPA_ACTUAL
        detalle_secuencia_actual = DETALLE_SECUENCIA.objects.get(SC_NID = secuencia, ET_NID = etapa_actual)
        
        campos_etapa = GetCamposEtapa(etapa_actual.id)
        for campo_row in campos_etapa:
            campo = CAMPO.objects.get(id = campo_row[0])
            campo_opcion = CAMPO_OPCION.objects.filter(CAMP_NID = campo, CA_BHABILITADO = True).first()  # Agregado .first()

            # EN CASO DE SER ARCHIVO EL CAMPO PRIMERO SE DEBE ESTABLECER LA RUTA
            if campo.CA_CTIPO.lower() == 'archivo':
                valor_campo = request.FILES.get(f'{etapa_actual.ET_CCODIGO.replace(" ", "")}_{campo_row[0]}')
                # IDENTIFICAMOS QUE PATH BASE UTLIZAR
                if citacion.EP_NID.id == ID_TERRAMAR:
                    base_folder = CAMPO_TERRAMAR_PATH
                elif citacion.EP_NID.id == ID_ACEITES_SBH:
                    base_folder = CAMPO_ACEITES_PATH

                # VERIFICAMOS QUE LA RUTA DE LA SECUENCIA EXISTE, SI NO EXISTE LA CREAMOS
                folder_path = os.path.join(base_folder, str(citacion.SC_NID.SE_CCODIGO))
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                # VERIFICAMOS QUE LA RUTA DE LA ETAPA EXISTE, SI NO EXISTE LA CREAMOS
                folder_path = os.path.join(folder_path, str(etapa_actual.ET_CCODIGO))
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                # GUARDAMOS EL ARCHIVO EN LA RUTA ESTABLECIDA
                file_extension = valor_campo.name.split('.')[-1]
                unique_filename = str(uuid.uuid4()) + '.' + file_extension
                file_path = os.path.join(folder_path, unique_filename)
                with open(file_path, 'wb+') as destination:
                    for chunk in valor_campo.chunks():
                        destination.write(chunk)
                try:
                    DATO_OPERACION.objects.create(
                        EP_NID = empresa,
                        CI_NID = citacion,
                        CAMP_NID = campo,
                        SC_NID = secuencia,
                        ET_NID = etapa_actual,
                        US_NID = request.user,
                        DO_CVALOR = file_path,
                        DO_FFECHAREGISTRO = datetime.now()
                    )                    
                except Exception as e:
                    print(e)
                    datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
                    if datos_operacion:
                        datos_operacion.delete()
                    messages.error(request, f'Error, {str(e)}')
                    return redirect(f'/cit_listone/{citacion.id}')
            else:
                valor_campo = request.POST.get(f'{etapa_actual.ET_CCODIGO.replace(" ", "")}_{campo_row[0]}')
                if campo.CA_CTIPO == 'CHECK' and valor_campo == None:
                    valor_campo = False

                if campo.CA_BASIGNARVALOR == True:
                    codigo_campo = campo.CA_CCODIGO
                    update_field_citacion(citacion.pk, codigo_campo, valor_campo)
                if campo_opcion:  # Si existe un campo_opcion
                    campo_nombre = campo_opcion.CA_CNOMBRECAMPO
                    try:
                        # Asignar el valor directamente al campo de la citación
                        setattr(citacion, campo_nombre, valor_campo)
                        citacion.save()
                    except Exception as e:
                        print(e)
                        messages.error(request, f'Error al actualizar el campo {campo_nombre}: {str(e)}')
                        return redirect(f'/cit_listone/{citacion.id}')

                try:
                    DATO_OPERACION.objects.create(
                        EP_NID = empresa,
                        CI_NID = citacion,
                        CAMP_NID = campo,
                        SC_NID = secuencia,
                        ET_NID = etapa_actual,
                        US_NID = request.user,
                        DO_CVALOR = valor_campo,
                        DO_FFECHAREGISTRO = datetime.now()
                    )                    
                except Exception as e:
                    print(e)
                    datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
                    if datos_operacion:
                        datos_operacion.delete()
                    messages.error(request, f'Error, {str(e)}')
                    return redirect(f'/cit_listone/{citacion.id}')
        # Verificar si se realiza el update de la etapa log
        etapa_log_actualizada = ETAPA_LOG.objects.filter(
            CI_NID=citacion,
            EP_NID=empresa,
            SC_NID=secuencia,
            ET_NID=etapa_actual
        ).update(
            EL_FFECHAFIN=datetime.now()
        )

        
        siguiente_etapa = citacion.ETAPA_SIGUIENTE
        if not siguiente_etapa:
            citacion.CI_FFECHATERMINO = datetime.now()
            citacion.CI_CESTADO = CIT_TERMINADO
            citacion.save()
            messages.success(request, 'Secuencia finalizada correctamente.')
            return redirect(f'/cit_listone/{citacion.id}')
        else:                               
            ETAPA_LOG.objects.create(
                CI_NID = citacion,
                EP_NID = empresa,
                SC_NID = secuencia,
                ET_NID = siguiente_etapa.ET_NID,
                EL_FFECHAINICIO = datetime.now()
            )

        # AXONINSERTPUSH(request.user, siguiente_etapa.USER_RESPONSABLE_ID, empresa, f'Citación {str(citacion.pk)} ha pasado tu etapa {siguiente_etapa.ET_NID.ET_CNOMBRE}')
        usuarios_responsables_str = siguiente_etapa.USERS_RESPONSABLE_ID
        if usuarios_responsables_str:
            usuarios_responsables = usuarios_responsables_str.replace('[','').replace(']','').replace(' ','').replace("'","").replace('"','').split(',')
            for usuario_responsable in usuarios_responsables:
                user = User.objects.get(id = usuario_responsable)
                if citacion.CA_NID:
                    contenido = f'Citación {str(citacion.pk)} - {citacion.CA_NID.CAM_CPATENTE} ha pasado a tu etapa {siguiente_etapa.ET_NID.ET_CNOMBRE}'
                else:
                    contenido = f'Citación {str(citacion.pk)} ha pasado a tu etapa {siguiente_etapa.ET_NID.ET_CNOMBRE}'

                notificacion = NOTIFICACION.objects.create(
                    USER_SENDER_ID = request.user,
                    USER_RECEIVER_ID = user,
                    EP_NID = empresa,
                    NOT_CCONTENIDO = contenido
                )
                notificacion.NOT_CURL = f'/cit_listone/{citacion.pk}?notificacion={str(notificacion.pk)}'
                notificacion.save()

        messages.success(request, 'Operación existosa.')
        return redirect(f'/cit_listone/{citacion.id}')
    except Exception as e:
        print(e)
        datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
        if datos_operacion:
            datos_operacion.delete()
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{citacion.id}')

def CITACION_FINALIZAR(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        empresa = citacion.EP_NID
        secuencia = citacion.SC_NID

        etapa_actual = citacion.ETAPA_SALIDA
        campos_etapa = GetCamposEtapa(etapa_actual.id)
        for campo_row in campos_etapa:
            campo = CAMPO.objects.get(id = campo_row[0])
            # EN CASO DE SER ARCHIVO EL CAMPO PRIMERO SE DEBE ESTABLECER LA RUTA
            if campo.CA_CTIPO.lower() == 'archivo':
                valor_campo = request.FILES.get(f'{etapa_actual.ET_CCODIGO.replace(" ", "")}_{campo_row[0]}')

                # IDENTIFICAMOS QUE PATH BASE UTLIZAR
                if citacion.EP_NID.id == ID_TERRAMAR:
                    base_folder = CAMPO_TERRAMAR_PATH
                elif citacion.EP_NID.id == ID_ACEITES_SBH:
                    base_folder = CAMPO_ACEITES_PATH

                # VERIFICAMOS QUE LA RUTA DE LA SECUENCIA EXISTE, SI NO EXISTE LA CREAMOS
                folder_path = os.path.join(base_folder, str(citacion.SC_NID.SE_CCODIGO))
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                # VERIFICAMOS QUE LA RUTA DE LA ETAPA EXISTE, SI NO EXISTE LA CREAMOS
                folder_path = os.path.join(folder_path, str(etapa_actual.ET_CCODIGO))
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                # GUARDAMOS EL ARCHIVO EN LA RUTA ESTABLECIDA
                file_extension = valor_campo.name.split('.')[-1]
                unique_filename = str(uuid.uuid4()) + '.' + file_extension
                file_path = os.path.join(folder_path, unique_filename)
                with open(file_path, 'wb+') as destination:
                    for chunk in valor_campo.chunks():
                        destination.write(chunk)
                try:
                    DATO_OPERACION.objects.create(
                        EP_NID = empresa,
                        CI_NID = citacion,
                        CAMP_NID = campo,
                        SC_NID = secuencia,
                        ET_NID = etapa_actual,
                        US_NID = request.user,
                        DO_CVALOR = file_path,
                        DO_FFECHAREGISTRO = datetime.now()
                    )
                except Exception as e:
                    print(e)
                    datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
                    if datos_operacion:
                        datos_operacion.delete()
                    messages.error(request, f'Error, {str(e)}')
                    return redirect(f'/cit_listone/{citacion.id}')
            else:
                valor_campo = request.POST.get(f'{etapa_actual.ET_CCODIGO.replace(" ", "")}_{campo_row[0]}')
                try:
                    DATO_OPERACION.objects.create(
                        EP_NID = empresa,
                        CI_NID = citacion,
                        CAMP_NID = campo,
                        SC_NID = secuencia,
                        ET_NID = etapa_actual,
                        US_NID = request.user,
                        DO_CVALOR = valor_campo,
                        DO_FFECHAREGISTRO = datetime.now()
                    )
                except Exception as e:
                    print(e)
                    datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
                    if datos_operacion:
                        datos_operacion.delete()
                    messages.error(request, f'Error, {str(e)}')
                    return redirect(f'/cit_listone/{citacion.id}')

        citacion.CI_FFECHATERMINO = datetime.now()
        citacion.CI_CESTADO = CIT_RECHAZADO
        citacion.save()
           
        messages.success(request, 'Operación existosa.')
        return redirect(f'/cit_listone/{citacion.id}')
    except Exception as e:
        print(e)
        datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = secuencia, ET_NID = etapa_actual)
        if datos_operacion:
            datos_operacion.delete()
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{citacion.id}')

def get_extra_data(request, pk):
    try:
        extra = CITACION_EXTRA.objects.get(id=pk)
        data = {
            'EXT_NID': extra.EXT_NID.id,
            'CIE_NVALOR': extra.CIE_NVALOR,
            'CIE_CCOMENTARIO': extra.CIE_CCOMENTARIO
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

def update_extra(request, pk):
    if request.method == 'POST':
        try:
            extra = CITACION_EXTRA.objects.get(id=pk)
            extra.EXT_NID = EXTRA.objects.get(id=request.POST.get('EXT_NID'))
            extra.CIE_NVALOR = request.POST.get('CIE_NVALOR')
            extra.CIE_CCOMENTARIO = request.POST.get('CIE_CCOMENTARIO')
            extra.save()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'})

def delete_extra(request, pk):
    if request.method == 'POST':
        try:
            extra = CITACION_EXTRA.objects.get(id=pk)
            extra.delete()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'})

def CITACION_BACKWARD(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        empresa = citacion.EP_NID       
        etapa_actual = citacion.ETAPA_ACTUAL
        detalle_secuencia_actual = DETALLE_SECUENCIA.objects.get(EP_NID = citacion.EP_NID, SC_NID = citacion.SC_NID, ET_NID = etapa_actual)

        campos_etapa_actual = GetPreviewEtapa(etapa_actual.pk)
        if campos_etapa_actual:
            for campo in campos_etapa_actual:
                campo_obj = CAMPO.objects.get(id = campo[6])
                if campo_obj.CA_BASIGNARVALOR == True:
                    codigo_campo = campo_obj.CA_CCODIGO
                    update_field_citacion_null(pk, codigo_campo)
        
        detalle_etapa_anterior = DETALLE_SECUENCIA.objects.filter(EP_NID = citacion.EP_NID, SC_NID = citacion.SC_NID, SE_NPASO = detalle_secuencia_actual.SE_NPASO - 1).first()
        if detalle_etapa_anterior:
            datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = detalle_etapa_anterior.ET_NID)
            if datos_operacion:
                datos_operacion.delete()
            etapa_log = ETAPA_LOG.objects.get(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = detalle_etapa_anterior.ET_NID)
            etapa_log.EL_FFECHAFIN = None
            etapa_log.save()
            usuarios_responsables_str = detalle_etapa_anterior.USERS_RESPONSABLE_ID
            if usuarios_responsables_str:
                usuarios_responsables = usuarios_responsables_str.replace('[','').replace(']','').replace(' ','').replace("'","").replace('"','').split(',')
                for usuario_responsable in usuarios_responsables:
                    user = User.objects.get(id = usuario_responsable)
                    notificacion = NOTIFICACION.objects.create(
                        USER_SENDER_ID = request.user,
                        USER_RECEIVER_ID = user,
                        EP_NID = empresa,
                        NOT_CCONTENIDO = f'Citación {str(citacion.pk)} ha retornado a tu etapa {detalle_etapa_anterior.ET_NID.ET_CNOMBRE}',
                    )
                notificacion.NOT_CURL = f'/cit_listone/{citacion.pk}?notificacion={str(notificacion.pk)}'
                notificacion.save()
        else:
            messages.error(request, 'No se puede volver a la etapa anterior')
            return redirect(f'/cit_listone/{citacion.id}')
        
        etapa_log_actual = ETAPA_LOG.objects.get(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = etapa_actual)
        etapa_log_actual.delete()

        datos_operacion = DATO_OPERACION.objects.filter(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = etapa_actual)
        if datos_operacion:
            datos_operacion.delete()

        messages.success(request, 'Retorno a etapa anterior!')
        return redirect(f'/cit_listone/{citacion.id}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{pk}')

def ajax_validar_citaciones(request):
    try:
        id_planificacion = request.POST.get('id_planificacion')
        tableData = json.loads(request.POST.get('data'))
        es_venta = True if request.POST.get('venta') == 'true' else False
        planificacion = PLANIFICACION.objects.get(id = id_planificacion)
        hora_inicio_local = timezone.localtime(planificacion.PL_FFECHAINICIO).time()
        hora_fin_local = timezone.localtime(planificacion.PL_FFECHAFIN).time()
        advertencias = []
        
        for index, row in enumerate(tableData):
            # VALIDAR HORA DE CITACION
            hora_citacion = row['hora_citacion']
            hora_citacion_obj = datetime.strptime(hora_citacion, '%H:%M').time()
            if hora_citacion_obj < hora_inicio_local or hora_citacion_obj > hora_fin_local:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La hora de citación {index + 1} no está dentro del rango de la planificación',
                })

            # VALIDAR PROVEEDOR
            if not row["id_proveedor"]:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La citación {index + 1} no posee proveedor valido',
                })
            proveedor = SOCIONEGOCIO.objects.get(id = row["id_proveedor"])
            
            # VALIDAR CONDUCTOR
            if not row['id_conductor']:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La citación {index + 1} no posee conductor valido',
                })
            if proveedor.SN_CRAZONSOCIAL != 'Puesto en planta':
                conductor = CONDUCTOR.objects.get(id = row['id_conductor'])
                
                # VERIFICAR DOCUMENTOS DEL CONDUCTOR
                if conductor.CON_CNOMBRE != 'CONDUCTOR':
                    documentos_conductor = conductor.ESTADO_DOCUMENTOS
                    if documentos_conductor:
                        for doc in documentos_conductor:
                            if doc[1] == -999:
                                advertencias.append(f'El conductor {conductor.CON_CNOMBRE} {conductor.CON_CAPELLIDO} no tiene el documento {doc[0]} cargado')
                            elif doc[1] <= 0:
                                advertencias.append(f'El documento {doc[0]} del conductor {conductor.CON_CNOMBRE} {conductor.CON_CAPELLIDO} está vencido')
                            elif doc[1] <= 30:
                                advertencias.append(f'El documento {doc[0]} del conductor {conductor.CON_CNOMBRE} {conductor.CON_CAPELLIDO} vence en {doc[1]} días')
                                
            # VALIDAR CAMION
            if not row['id_camion']:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La citación {index + 1} no posee camión valido',
                })
            if proveedor.SN_CRAZONSOCIAL != 'Puesto en planta':

                camion = CAMION.objects.get(id = row['id_camion'])
            
                # VERIFICAR DOCUMENTOS DEL CAMION
                if camion.CAM_CPATENTE != 'CAMION_GENERICO':
                    documentos_camion = camion.ESTADO_DOCUMENTOS
                    if documentos_camion:
                        for doc in documentos_camion:
                            if doc[1] == -999:
                                advertencias.append(f'El camión {camion.CAM_CPATENTE} no tiene el documento {doc[0]} cargado')
                            elif doc[1] <= 0:
                                advertencias.append(f'El documento {doc[0]} del camión {camion.CAM_CPATENTE} está vencido')
                            elif doc[1] <= 30:
                                advertencias.append(f'El documento {doc[0]} del camión {camion.CAM_CPATENTE} vence en {doc[1]} días')

            # VALIDAR SECUENCIA
            if not row['id_secuencia']:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La citación {index + 1} no posee secuencia valida',
                })

            # VALIDAR ITEM
            if not row['id_producto']:
                return JsonResponse({
                    'valid': False, 
                    'msg': f'La citación {index + 1} no posee item valido',
                })

        # VALIDAR NUMERO DE CITACIONES
        num_citaciones_planificacion = CITACION.objects.filter(PL_NID = planificacion).count() + len(tableData)
        if num_citaciones_planificacion > planificacion.PL_NCANTIDADCUPOS:
            return JsonResponse({
                'valid': True, 
                'continue': False,
                'msg': f'La planificación ya posee el número máximo de citaciones, ¿quieres marcarla como sobrecupo?',
            })
            
        # Si hay advertencias, las mostramos pero permitimos continuar
        if advertencias:
            return JsonResponse({
                'valid': True,
                'continue': False,
                'has_warnings': True,
                'warnings': advertencias,
                'msg': f'Se encontraron problemas con documentos.{advertencias} ¿Desea continuar de todas formas?'
            })
            
        return JsonResponse({'valid': True, 'continue': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def DOWNLOAD_DATO_OPERACION_FILE(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        dato_operacion = DATO_OPERACION.objects.get(id = pk)
        file_path = dato_operacion.DO_CVALOR
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            return redirect(f'/cit_listone/{dato_operacion.CI_NID.pk}')
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

def ajax_listar_archivos_tickets(request):
    """Lista archivos en \tickets que contengan el número de citación y la patente"""
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listone"):
                return JsonResponse({'success': False, 'msg': 'No tiene permisos'})

        citacion_id = request.GET.get('citacion_id')
        patente = request.GET.get('patente')
        
        if not citacion_id or not patente:
            return JsonResponse({'success': False, 'msg': 'Faltan parámetros'})
        
        # Asegurar que citacion_id sea string sin espacios
        citacion_id = str(citacion_id).strip()
        patente = patente.strip()
        
        # Ruta del directorio tickets - buscar en apps/tickets relativo al proyecto
        # El archivo views.py está en apps/home/, entonces apps/tickets está en ../tickets
        base_dir = os.path.dirname(os.path.dirname(__file__))  # apps/
        tickets_path = os.path.join(base_dir, 'tickets')
        
        # Si no existe, intentar otras rutas
        if not os.path.exists(tickets_path) or not os.path.isdir(tickets_path):
            posibles_rutas = [
                r'C:\tickets',
                r'\tickets',
                r'tickets',
            ]
            tickets_path = None
            for ruta in posibles_rutas:
                if os.path.exists(ruta) and os.path.isdir(ruta):
                    tickets_path = ruta
                    break
        
        if not tickets_path or not os.path.exists(tickets_path):
            print(f"Directorio tickets no encontrado. Ruta buscada: {os.path.join(base_dir, 'tickets')}")
            return JsonResponse({'success': True, 'archivos': [], 'msg': 'Directorio tickets no encontrado'})
        
        # Buscar archivos PDF cuyo primer segmento (antes del primer "_") coincida con el número de citación
        archivos = []
        try:
            citacion_id_str = str(citacion_id).strip()
            
            print(f"=== BÚSQUEDA DE ARCHIVOS PDF ===")
            print(f"Directorio: {tickets_path}")
            print(f"Citación ID buscada: '{citacion_id_str}'")
            print(f"Buscando archivos cuyo primer segmento (antes del '_') sea '{citacion_id_str}'")
            print("")
            
            for filename in os.listdir(tickets_path):
                file_path = os.path.join(tickets_path, filename)
                # Verificar que sea un archivo PDF
                if os.path.isfile(file_path) and filename.lower().endswith('.pdf'):
                    # Extraer el primer segmento del nombre del archivo (antes del primer "_")
                    # Ejemplo: "29386_COM_SAL_ZU5787_26_01_20_14_42.pdf" -> "29386"
                    primer_segmento = filename.split('_')[0] if '_' in filename else filename.split('.')[0]
                    
                    # Comparar el primer segmento con el número de citación
                    coincide_citacion = primer_segmento == citacion_id_str
                    
                    if coincide_citacion:
                        file_size = os.path.getsize(file_path)
                        archivo_info = {
                            'nombre': filename,
                            'ruta': file_path,
                            'tamaño': file_size,
                            'tamaño_formateado': f"{file_size / 1024:.2f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024 * 1024):.2f} MB"
                        }
                        archivos.append(archivo_info)
                        print(f"✓ AGREGADO: {filename} (primer segmento: '{primer_segmento}')")
                    else:
                        print(f"✗ IGNORADO: {filename} (primer segmento: '{primer_segmento}', buscado: '{citacion_id_str}')")
            
            print("")
            print(f"=== RESULTADO ===")
            print(f"Total de archivos encontrados: {len(archivos)}")
            for archivo in archivos:
                print(f"  - {archivo['nombre']}")
        except Exception as e:
            print(f"Error al listar archivos: {e}")
            return JsonResponse({'success': False, 'msg': f'Error al listar archivos: {str(e)}'})
        
        return JsonResponse({'success': True, 'archivos': archivos})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False, 'msg': str(e)})

def ajax_descargar_archivo_ticket(request):
    """Descarga un archivo de tickets"""
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        file_path = request.GET.get('file_path')
        
        if not file_path:
            messages.error(request, 'Ruta de archivo no proporcionada')
            return redirect('/')
        
        # Normalizar la ruta del archivo
        file_path = os.path.normpath(file_path)
        
        # Validar que el archivo esté en el directorio tickets
        # Obtener la ruta base de tickets
        base_dir = os.path.dirname(os.path.dirname(__file__))  # apps/
        tickets_path = os.path.join(base_dir, 'tickets')
        
        # Verificar que el archivo existe y está dentro del directorio tickets
        if not os.path.exists(file_path):
            # Intentar construir la ruta completa si es relativa
            if not os.path.isabs(file_path):
                file_path = os.path.join(tickets_path, file_path)
        
        # Verificar que el archivo existe y está dentro del directorio tickets permitido
        if not os.path.exists(file_path):
            messages.error(request, 'Archivo no encontrado')
            return redirect('/')
        
        # Verificar que el archivo está dentro de un directorio tickets válido
        normalized_file = os.path.normpath(file_path)
        normalized_tickets = os.path.normpath(tickets_path)
        
        if not normalized_file.startswith(normalized_tickets):
            # Intentar otras rutas posibles
            otras_rutas = [r'C:\tickets', r'\tickets']
            es_valido = False
            for ruta in otras_rutas:
                if normalized_file.startswith(os.path.normpath(ruta)):
                    es_valido = True
                    break
            if not es_valido:
                messages.error(request, 'Ruta de archivo no válida')
                return redirect('/')
        
        # Determinar el content-type según la extensión del archivo
        file_extension = os.path.splitext(file_path)[1].lower()
        content_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.txt': 'text/plain',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        content_type = content_types.get(file_extension, 'application/octet-stream')
        
        # Abrir y retornar el archivo
        file_handle = open(file_path, 'rb')
        response = FileResponse(file_handle, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
        return response
        
    except Exception as e:
        print(f"Error al descargar archivo: {e}")
        import traceback
        traceback.print_exc()
        return HttpResponse(f'Error al descargar archivo: {str(e)}', status=500, content_type='text/plain')

def ajax_edit_secuencia(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        if citacion.CI_CESTADO != CIT_CREADO:
            return JsonResponse({'valid': False, 'msg': 'La citación ya ha sido iniciada'})
        
        id_secuencia = request.POST.get('new_secuencia')
        secuencia = SECUENCIA.objects.get(id = id_secuencia)
        if secuencia.SE_BHABILITADO == False:
            return JsonResponse({'valid': False, 'msg': 'La secuencia no está habilitada'})
        
        citacion.SC_NID = secuencia
        citacion.save()
        
        return JsonResponse({'valid': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_CAMPO_VALIDAR_SAP(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_listone"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        id_citacion = request.POST.get('id_citacion')
        campos = json.loads(request.POST.get('campos'))

        citacion = CITACION.objects.get(id = id_citacion)
        empresa = citacion.EP_NID
        credenciales = {
            "usuario": empresa.EP_CUSUARIOSBD,
            "password": decrypt_string(empresa.EP_CPASSWORDBD),
            "base_datos": empresa.EP_CBASEDATOS,
            "host": empresa.EP_CHOST,
            "puerto": empresa.EP_CPORT,
        }
        for campo in campos:
            id_campo = campo['id_campo']
            valor_campo = campo['valor_campo']
            objeto_campo = CAMPO.objects.get(id = id_campo)

            # VALIDAR QUE EL CAMPO NO SEA OBLIGATORIO Y NO TENGA UN VALOR
            if not objeto_campo.CA_BOBLIGATORIO and not valor_campo:
                continue
            
            opciones_campo = CAMPO_OPCION.objects.get(CA_NID = objeto_campo)
            if empresa.pk == ID_TERRAMAR:
                result = validar_campo_terramar(credenciales, opciones_campo.CA_CTABLA, opciones_campo.CA_CNOMBRECAMPO, valor_campo)
                if result is None:
                    return JsonResponse({'valid': False, 'msg': 'Error al validar el campo'})
                elif result == False:
                    return JsonResponse({'valid': False, 'msg': f'El campo {objeto_campo.CA_CETIQUETA} no existe en SAP'})
            # elif empresa.pk == ID_ACEITES_SBH:
                # result = validar_campo_aceites_sbh(credenciales, objeto_campo, valor_campo)
                # if result is None:
                    # return JsonResponse({'valid': False, 'msg': 'Error al validar el campo'})
                # elif result == False:
                #     return JsonResponse({'valid': False, 'msg': f'El campo {objeto_campo.CA_CETIQUETA} no existe en SAP'})
        return JsonResponse({'valid': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_ENVIAR_SAP(request):
    try:
        id_citacion = request.POST.get('id_citacion')
        cabecera_sap = json.loads(request.POST.get("cabecera"))
        lineas_sap = json.loads(request.POST.get("lineas"))

        citacion = CITACION.objects.get(id = id_citacion)
        empresa = citacion.EP_NID
        etapa_actual = citacion.ETAPA_ACTUAL
        detalle_secuencia = DETALLE_SECUENCIA.objects.get(SC_NID = citacion.SC_NID, ET_NID = etapa_actual)

        etapa_lineas = GetEtapaLinea(citacion.SC_NID.pk, etapa_actual.pk)

        payload = {
            "empresa": empresa.pk,
            "credenciales": {
                "sb1_Server":empresa.EP_CSERVER,       
                "sb1_CompanyDB":empresa.EP_CBASEDATOS,
                "sb1_LicenseServer":empresa.EP_CLISENCESERVER,
                "sb1_DbUserName":empresa.EP_CUSUARIOSBD,
                 "sb1_DbServerType":empresa.EP_CDB_SERVER_TYPE,
                "sb1_UserName":empresa.EP_CUSUARIOSBD,
                "sb1_Password":decrypt_string(empresa.EP_CPASSWORD_SAP),
                "sb1_UseTrusted":"False",
            },
            "objeto": {
                "numero": etapa_actual.ET_CNUMEROOBJETOSAP,
                "nombre": etapa_actual.ET_CNOMBREOBJETOSAP,
            },
            "cabecera": {},
            "tipos_datos_cabecera": {},
            "lines": [],
            "tipos_datos_lineas": {},
        }
        for key, row in cabecera_sap.items():
            id_campo = key.split('_')[1]
            campo = CAMPO.objects.get(id = id_campo)
            payload['cabecera'][campo.CA_CCODIGO] = row
            payload['tipos_datos_cabecera'][campo.CA_CCODIGO] = campo.CA_CTIPO

        for row in lineas_sap:
            line = {}
            for key, value in row.items():
                id_campo = key.split('_')[1]
                campo = CAMPO.objects.get(id = id_campo)
                line[campo.CA_CCODIGO] = value
                if campo.CA_CCODIGO not in payload['tipos_datos_lineas']:
                    payload['tipos_datos_lineas'][campo.CA_CCODIGO] = campo.CA_CTIPO
            payload['lines'].append(line)

        etapa_accion_cabecera = ETAPA_ACCION.objects.create(
            US_NID = request.user,
            EP_NID = empresa,
            SC_NID = citacion.SC_NID,
            ET_NID = etapa_actual,
            CI_NID = citacion,
            EA_CENDPOINT = etapa_actual.ET_CENDPOINT,
            EA_NPASO = detalle_secuencia.SE_NPASO,
            EA_FFECHAREGISTRO = datetime.now(),
            EA_CPAYLOAD = str(payload['cabecera']),
        )

        etapa_accion_lineas = ETAPA_ACCION.objects.create(
            US_NID = request.user,
            EP_NID = empresa,
            SC_NID = citacion.SC_NID,
            ET_NID_id = etapa_lineas[0],
            CI_NID = citacion,
            EA_CENDPOINT = etapa_lineas[1],
            EA_NPASO = etapa_lineas[2],
            EA_FFECHAREGISTRO = datetime.now(),
            EA_CPAYLOAD = str(payload['lines']),
        )

        payload = encrypt_payload(payload)

        response_login = requests.post(f"{URL_BASE_API}login", json={'username': 'CIROS', 'password': 'Ciros.2023'})
        token = response_login.text
        url = f"{URL_BASE_API}{etapa_actual.ET_CENDPOINT}"
        response = requests.post(url, json={'payload': payload}, headers={'Authorization': f'Bearer {token}', 'Content-type': 'application/json'})

        DATO_ACCION.objects.create(
            US_NID = request.user,
            EP_NID = empresa,
            EA_NID = etapa_accion_cabecera,
            CI_NID = citacion,
            DA_FFECHAREGISTRO = datetime.now(),
            DA_CPAYLOAD = str(payload['cabecera']),
            DA_CCODIGORETORNO = response.status_code,
            DA_CRESPONSE = str(response.json()),
        )

        DATO_ACCION.objects.create(
            US_NID = request.user,
            EP_NID = empresa,
            EA_NID = etapa_accion_lineas,
            CI_NID = citacion,
            DA_FFECHAREGISTRO = datetime.now(),
            DA_CPAYLOAD = str(payload['lines']),
            DA_CCODIGORETORNO = response.status_code,
            DA_CRESPONSE = str(response.json()),
        )

        if response.status_code == 200:
            for key, row in cabecera_sap.items():
                id_campo = key.split('_')[1]
                campo = CAMPO.objects.get(id = id_campo)
                DATO_OPERACION.objects.create(
                    US_NID = request.user,
                    EP_NID = empresa,
                    CI_NID = citacion,
                    CAMP_NID = campo,
                    DO_CVALOR = row,
                    DO_FFECHAREGISTRO = datetime.now(),
                )
            
            for row in lineas_sap:
                line = {}
                for key, value in row.items():
                    id_campo = key.split('_')[1]
                    campo = CAMPO.objects.get(id = id_campo)
                    DATO_OPERACION.objects.create(
                        US_NID = request.user,
                        EP_NID = empresa,
                        CI_NID = citacion,
                        CAMP_NID = campo,
                        DO_CVALOR = row,
                        DO_FFECHAREGISTRO = datetime.now(),
                    )
            etapa_log_cabecera = ETAPA_LOG.objects.get(
                CI_NID = citacion, 
                SC_NID = citacion.SC_NID, 
                ET_NID = etapa_actual
            )

            etapa_log_lineas = ETAPA_LOG.objects.create(
                CI_NID = citacion,
                SC_NID = citacion.SC_NID,
                ET_NID = etapa_lineas[0],
                EP_NID = empresa,
                EL_FFECHAINICIO = etapa_log_cabecera.EL_FFECHAINICIO,
            )
            
            etapa_log_cabecera.EL_FFECHAFIN = datetime.now()
            etapa_log_cabecera.save()

            etapa_log_lineas.EL_FFECHAFIN = datetime.now()
            etapa_log_lineas.save()

            return JsonResponse({'valid': True})
        else:
            return JsonResponse({'valid': False, 'msg': 'Error al enviar a SAP'})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_OMITIR_ETAPA(request):
    try:
        id_citacion = request.POST.get('id_citacion')
        etapa_actual = request.POST.get('etapa_actual')

        citacion = CITACION.objects.get(id = id_citacion)
        detalle_secuencia = DETALLE_SECUENCIA.objects.get(SC_NID = citacion.SC_NID, ET_NID = etapa_actual)
        
        # Modificar el registro actual para que no tenga tiempo transcurrido
        etapa_log = ETAPA_LOG.objects.get(CI_NID = citacion, SC_NID = citacion.SC_NID, ET_NID = etapa_actual)
        tiempo_actual = datetime.now()
        etapa_log.EL_FFECHAINICIO = tiempo_actual  # Establecer la fecha de inicio igual a la de fin
        etapa_log.EL_FFECHAFIN = tiempo_actual     # Para que el tiempo transcurrido sea 0
        etapa_log.save()
        
        # Crear el registro para la siguiente etapa
        siguiente_etapa = citacion.ETAPA_SIGUIENTE
        if siguiente_etapa is not None:
            ETAPA_LOG.objects.create(
                CI_NID = citacion,
                SC_NID = citacion.SC_NID,
                ET_NID = siguiente_etapa.ET_NID,
                EP_NID = citacion.EP_NID,
                EL_FFECHAINICIO = datetime.now(),
            )
        return JsonResponse({'valid': True})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_REEMPLAZAR(request, pk):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "cit_replace"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)

        citacion_original = CITACION.objects.get(id = pk)
        citacion_item = CITACION_ITEM.objects.get(CI_NID = citacion_original)
        citacion_proforma = CITACION_PROFORMA.objects.filter(CI_NID = citacion_original).exists()
        if citacion_proforma:
            return JsonResponse({'valid': False, 'msg': 'La citación no puede ser reemplazada, ya que posee una proforma'})
        
        if citacion_original.CI_CTIPO == CIT_DESPACHO:
            id_nuevo_proveedor = request.POST.get('nuevo_proveedor')
            nuevo_proveedor = SOCIONEGOCIO.objects.get(id = id_nuevo_proveedor)

            id_nuevo_conductor = request.POST.get('nuevo_conductor')
            nuevo_conductor = CONDUCTOR.objects.get(id = id_nuevo_conductor)

            id_nuevo_camion = request.POST.get('nuevo_camion')
            nuevo_camion = CAMION.objects.get(id = id_nuevo_camion)

            id_nueva_tarifa = request.POST.get('nuevo_tarifa')
            nueva_tarifa = TARIFA_GLOBAL.objects.get(id = id_nueva_tarifa)

            nuevo_valor_tarifa = Decimal(request.POST.get('nuevo_valor_tarifa'))
            diferencia_valor_tarifa = nueva_tarifa.TAR_NVALOR - nuevo_valor_tarifa

        elif citacion_original.CI_CTIPO == CIT_RECEPCION:
            nuevo_proveedor = None
            nuevo_conductor = None
            nuevo_camion = None
            nueva_tarifa = None
            nuevo_valor_tarifa = None
            diferencia_valor_tarifa = None

        citacion_duplicado = CITACION.objects.create(
            CI_NID_REF = citacion_original.pk,
            EP_NID = citacion_original.EP_NID,
            RUT_NID = citacion_original.RUT_NID,
            PL_NID = citacion_original.PL_NID,
            SC_NID = citacion_original.SC_NID,
            CI_FFECHACITACION = citacion_original.CI_FFECHACITACION,
            CI_NCUPO = citacion_original.CI_NCUPO,
            CI_CTIPODOCUMENTO = citacion_original.CI_CTIPODOCUMENTO,
            CI_CNUMERODOCUMENTO = citacion_original.CI_CNUMERODOCUMENTO,
            CI_CCOMENTARIO = citacion_original.CI_CCOMENTARIO,
            CI_CTIPO = citacion_original.CI_CTIPO,
            US_NID = request.user,
            CI_CESTADO = CIT_CREADO,
            CI_FFECHAREGISTRO = datetime.now(),
            CI_BAVISADO = False,
            CI_BCONFIRMADO = False,
            CI_BARRIBADO = False,
            CI_BHABILITADO = True,
            PRO_NID = nuevo_proveedor,
            CON_NID = nuevo_conductor,
            CA_NID = nuevo_camion,
            TAR_NID = nueva_tarifa,
            CI_NVALORTARIFA = nuevo_valor_tarifa,
            CI_NDIFERENCIATARIFA = diferencia_valor_tarifa,
        )

        CITACION_ITEM.objects.create(
            EP_NID = citacion_duplicado.EP_NID,
            IT_NID = citacion_item.IT_NID,
            CI_NID = citacion_duplicado
        )

        citacion_original.CI_BHABILITADO = False
        citacion_original.save()

        return JsonResponse({'valid': True, 'id_citacion': citacion_duplicado.pk})
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_DATA(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        
        # EXTRAEMOS LA INFORMACION DE LA CITACION ORIGINAL
        proveedor_orignal = [citacion.PRO_NID.id, citacion.PRO_NID.SN_CRAZONSOCIAL]
        conductor_original = [citacion.CON_NID.id, citacion.CON_NID.CON_CNOMBRE + ' ' + citacion.CON_NID.CON_CAPELLIDO ]
        camion_original = [citacion.CA_NID.id, citacion.CA_NID.CAM_CMODELO + ' - ' + citacion.CA_NID.CAM_CPATENTE]
        tarifa_original = [citacion.TAR_NID.id, citacion.TAR_NID.TAR_CNOMBRETARIFA]
        valor_tarifa_citacion = float(citacion.CI_NVALORTARIFA)
        valor_original_tarifa_citacion = float(citacion.TAR_NID.TAR_NVALOR)

        proveedores = list(SOCIONEGOCIO.objects.filter(EP_NID = citacion.EP_NID, SN_BHABILITADO = True, SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL').exclude(id = citacion.PRO_NID.id))
        conductores = list(CONDUCTOR.objects.filter(EP_NID = citacion.EP_NID, CON_BHABILITADO = True, SN_NID = citacion.PRO_NID).values_list('id', 'CON_CNOMBRE', 'CON_CAPELLIDO').exclude(id = citacion.CON_NID.id))
        camiones = list(CAMION.objects.filter(EP_NID = citacion.EP_NID, CAM_BHABILITADO = True, SN_NID = citacion.PRO_NID).values_list('id', 'CAM_CMODELO', 'CAM_CPATENTE').exclude(id = citacion.CA_NID.id))
        tarifas = list(TARIFA_GLOBAL.objects.filter(EP_NID = citacion.EP_NID, TAR_BHABILITADO = True, SN_NID = citacion.PRO_NID, RUT_NID = citacion.RUT_NID).values_list('id', 'TAR_CNOMBRETARIFA').exclude(id = citacion.TAR_NID.id))

        return JsonResponse({
            'valid': True, 
            'proveedor_original': proveedor_orignal, 
            'conductor_original': conductor_original, 
            'camion_original': camion_original, 
            'tarifa_original': tarifa_original,
            'valor_tarifa_citacion': valor_tarifa_citacion,
            'valor_original_tarifa_citacion': valor_original_tarifa_citacion,
            'proveedores': proveedores,
            'conductores': conductores,
            'camiones': camiones,
            'tarifas': tarifas
        })
    except Exception as e:
        print(e)
        return JsonResponse({'valid': False, 'msg': str(e)})

def CITACION_UPDATE_DATA(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        conductor = request.POST.get('CON_NID')
        camion = request.POST.get('CA_NID')
        proveedor = request.POST.get('PRO_NID')

        if conductor:
            citacion.CON_NID_id = conductor
        if camion:
            citacion.CA_NID_id = camion
        if proveedor:
            citacion.PRO_NID_id = proveedor

        citacion.save()

        return redirect(f'/cit_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{pk}')

def CIT_CONFORME(request, pk):
    try:
        if request.user.is_superuser == False:
            if not validar_perfiles_activos(request.user.id, "marcar_conforme"):
                messages.error(request, "No puedes marcarlo como conforme esta citacion")
                return redirect(f'/cit_listone/{pk}')

        citacion = CITACION.objects.get(id = pk)
        citacion.CI_BCONFORME = True
        citacion.save()

        messages.success(request, "Citacion marcada como conforme")
        return redirect(f'/cit_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f"Error, {str(e)}")
        return redirect(f'/cit_listone/{pk}')

##########################################################################
#######################  PROVINCIAS Y COMUNAS  ###########################
##########################################################################

def get_provincias(request):
    try:
        region_pk = request.GET.get('region_pk')
        provincias = listar_provincias(region_pk)
        return JsonResponse({'success': True, 'provincias': provincias})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

def get_comunas(request):
    try:
        provincia_pk = request.GET.get('provincia_pk')
        comunas = listar_comunas(provincia_pk)
        return JsonResponse({'success': True, 'comunas': comunas})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

##########################################################################
#######################  LISTAR SOCIOS Y RUTAS  ##########################

def get_socios_negocio(request):
    try:
        empresa_pk = request.GET.get('empresa_pk')
        socios_negocio = listar_socios_negocio(empresa_pk)
        return JsonResponse({'success': True, 'socios_negocio': socios_negocio})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

def get_rutas_socios(request):
    try:
        socio_negocio_pk = request.GET.get('socio_negocio_pk')
        rutas_socios = listar_rutas_socios(socio_negocio_pk)
        return JsonResponse({'success': True, 'rutas_socios': rutas_socios})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

##########################################################################
############################  PARAMETROS  ################################
##########################################################################

def guardar_parametro(request):
    if request.method == 'POST':
        grupo = request.POST.get('grupo')
        codigo = request.POST.get('codigo')
        descripcion = request.POST.get('descripcion')

        parametro = PARAMETRO(
            PM_CGRUPO=grupo,
            PM_CCODIGO=codigo,
            PM_CDESCRIPCION=descripcion,
            PM_CVALOR1 =codigo
        )
        parametro.save()

        return JsonResponse({'success': True})

    return JsonResponse({'success': False})

def obtener_tarifas(request):
    tarifas = PARAMETRO.objects.filter(PM_CGRUPO='TIPO_TARIFA')
    divisas = PARAMETRO.objects.filter(PM_CGRUPO='DIVISA')
    data = {
        'tarifas': list(tarifas.values('PM_CCODIGO', 'PM_CDESCRIPCION')),
        'divisas': list(divisas.values('PM_CCODIGO', 'PM_CDESCRIPCION'))
    }
    
    return JsonResponse(data)

##########################################################################
############################  PERFILES  ##################################
##########################################################################

def PERFIL_LISTALL(request):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        object_list = PERFIL.objects.filter()
        ctx = {
            'object_list': object_list
        }
        return render(request, 'home/PERFILAMIENTO/per_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PERFIL_ASSIGN_PERMISSION(request):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        vistas = VISTA.objects.filter(VI_BHABILITADO = True)
        object_list = []
        for vista in vistas:
            permisos = list(PERMISO.objects.filter(VI_NID = vista, PE_BHABILITADO = True).values_list("PR_NID_id", flat=True))
            object_list.append([vista, permisos])
        perfiles = PERFIL.objects.filter(PR_BHABILITADO = True)
        permisos = PERMISO.objects.all()

        ctx = {
            'vistas': object_list,
            'perfiles': perfiles,
            'permisos': permisos

        }

        return render(request, 'home/PERFILAMIENTO/ASSIGNMENT/PERMISSION/per_assi_perm_prof.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PERFIL_ASSIGN_USER(request):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        object_list = []
        perfiles = PERFIL.objects.filter(PR_BHABILITADO = True)
        users = User.objects.filter(is_active = True)
        for user in users:
            perfiles_usuario = list(PERFIL_USUARIO.objects.filter(
                US_NID = user,
                PE_BHABILITADO = True
            ).values_list('PR_NID_id', flat=True))
            object_list.append([user, perfiles_usuario])
        ctx = {
            'perfiles': perfiles,
            'users': object_list
        }
        return render(request, 'home/PERFILAMIENTO/ASSIGNMENT/USER/per_assi_us_prof.html', ctx)
    except Exception as e:



        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def modificar_permiso(request):
    if request.method == 'POST':
        try:
            perfil_id = request.POST.get('perfil_id')
            vista_id = request.POST.get('vista_id')
            checked = request.POST.get('checked') == 'true'

            perfil = PERFIL.objects.get(id=perfil_id)
            vista = VISTA.objects.get(id=vista_id)

            try:
                permiso = PERMISO.objects.get(
                    US_NID=request.user,  # Asignar el usuario actual al campo US_NID
                    PR_NID=perfil,
                    VI_NID=vista
                )
                permiso.PE_BHABILITADO = checked
                permiso.save()
                mensaje = 'Permiso actualizado correctamente'
            except PERMISO.DoesNotExist:
                permiso = PERMISO.objects.create(
                    US_NID=request.user,
                    PR_NID=perfil,
                    VI_NID=vista,
                    PE_BHABILITADO=checked
                )
                mensaje = 'Permiso creado correctamente'

            return JsonResponse({'message': mensaje})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido'}, status=405)

def verificar_permiso(request):
    if request.method == 'POST':
        try:
            perfil_id = request.POST.get('perfil_id')
            vista_id = request.POST.get('vista_id')
            
            perfil = PERFIL.objects.get(id=perfil_id)
            vista = VISTA.objects.get(id=vista_id)
            
            permiso_habilitado = tiene_permiso_perfil(vista, perfil)
            
            return JsonResponse({'permiso_habilitado': permiso_habilitado})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def modificar_perfil_usuario(request):
    if request.method == 'POST':
        try:
            perfil_id = request.POST.get('perfil_id')
            usuario_id = request.POST.get('user_id')
            checked = request.POST.get('checked') == 'true'
            
            usuario = User.objects.get(id=usuario_id)
            perfil = PERFIL.objects.get(id = perfil_id)
            nombre_perfil = perfil.PR_CNOMBRE
            
            if perfil.PR_CCODIGO == 'AD':
                # Si el perfil_id es 1, se modifica el campo is_superuser del usuario
                usuario.is_superuser = checked
                usuario.save()
                mensaje = 'Perfil de superusuario actualizado correctamente'
            else:                
                # Para cualquier otro perfil_id, se verifica si existe el registro en PERFIL_USUARIO
                try:
                    perfil = PERFIL.objects.get(id=perfil_id)
                    perfil_usuario = PERFIL_USUARIO.objects.get(PR_NID=perfil, US_NID=usuario)
                    perfil_usuario.PE_BHABILITADO = checked
                    perfil_usuario.save()
                    mensaje = 'Perfil de usuario actualizado correctamente'
                except PERFIL_USUARIO.DoesNotExist:
                    # Si no existe el registro en PERFIL_USUARIO, se crea uno nuevo
                    perfil_usuario = PERFIL_USUARIO.objects.create(
                        PR_NID=perfil,
                        US_NID=usuario,
                        PE_BHABILITADO=checked
                    )
                    mensaje = 'Perfil de usuario creado correctamente'

            users_extension, created = USERS_EXTENSION.objects.get_or_create(US_NID=usuario)

            if nombre_perfil == 'Administrador de Secuencia':
                users_extension.UX_IS_ADMINISTRADOR_SECUENCIA = checked
            elif nombre_perfil == 'Administrador de Etapa':
                users_extension.UX_IS_ADMINISTRADOR_ETAPA = checked
            elif nombre_perfil == 'Planificador':
                users_extension.UX_IS_PLANIFICADOR = checked
            elif nombre_perfil == 'Recepcionista':
                users_extension.UX_IS_RECEPCIONISTA = checked
            elif nombre_perfil == 'Cliente':
                users_extension.UX_IS_CLIENTE = checked
            elif nombre_perfil == 'Proveedor':
                users_extension.UX_IS_PROVEEDOR = checked
            elif nombre_perfil == 'Conductor':
                users_extension.UX_IS_CONDUCTOR = checked
            elif nombre_perfil == 'Operador':
                users_extension.UX_IS_OPERADOR = checked
            elif nombre_perfil == 'Reportes':
                users_extension.UX_IS_REPORTES = checked
            elif nombre_perfil == 'Proforma':
                users_extension.UX_IS_PROFORMA = checked
            elif nombre_perfil == 'Administrador de Conductor':
                users_extension.UX_IS_ADMINISTRADOR_CONDUCTOR = checked
            users_extension.save()
            mensaje = 'Extensión de usuario actualizada correctamente'
            return JsonResponse({'message': mensaje})
        except Exception as e:
            print(f"Error en modificar_perfil_usuario: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def verificar_perfil_usuario(request):    
    if request.method == 'POST':
        try:
            perfil_id = request.POST.get('perfil_id')
            usuario_id = request.POST.get('user_id')
            
            perfil = PERFIL.objects.get(id=perfil_id)
            usuario = User.objects.get(id=usuario_id)

            if usuario.is_superuser:
                es_admin = True
            else:
                es_admin = False
            
            perfil_usuario_habilitado = tiene_perfil_usuario(perfil, usuario)

            return JsonResponse({'perfil_usuario_habilitado': perfil_usuario_habilitado, 'es_admin': es_admin})
        except Exception as e:


            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

##########################################################################
############################  USUARIOS  ##################################
##########################################################################

def USERS_LISTALL(request):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        Empresa = Verificar_empresa(request)
        user_empresa_ids = USERS_EMPRESA.objects.filter(EP_NID_id=Empresa).values_list('US_NID_id', flat=True)
        object_list = User.objects.filter(id__in=user_empresa_ids)
        ctx = {
            'object_list': object_list
        }
        return render(request, 'home/PERFILAMIENTO/USERS/usr_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def USERS_ADDONE(request):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        if request.method == 'POST':
            form = SignUpForm(request.POST)
            if form.is_valid():
                form.save()
                username = form.cleaned_data.get("username")
                raw_password = form.cleaned_data.get("password1")
                user = authenticate(username=username, password=raw_password)
                messages.success(request, 'Usuario creado correctamente')
                return redirect('/usr_listall/')
        else:
            form = SignUpForm()
        return render(request, 'home/PERFILAMIENTO/USERS/usr_addone.html', {'form': form})
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def USERS_UPDATE(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        objeto = User.objects.get(id=pk)
        if request.method == 'POST':
            form = SignUpForm(request.POST or None, instance=objeto)
            if form.is_valid():
                form.save()
                messages.success(request, 'Usuario actualizado correctamente')
                return redirect('/usr_listall/')
        form = SignUpForm(instance=objeto)
        return render(request, 'home/PERFILAMIENTO/USERS/usr_addone.html', {'form': form})
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def USERS_UPDATEPASSWORD(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        objeto = User.objects.get(id=pk)
        if request.method == 'POST':
            form = UserSimpleUpdateForm(request.POST, instance=objeto)
            if form.is_valid():
                form.save()
                messages.success(request, 'Usuario actualizado correctamente')
                return redirect('/usr_listall/')
            else:
                messages.error(request, f'Error en el formulario: {form.errors}')
        form = UserSimpleUpdateForm(instance=objeto)
        return render(request, 'home/PERFILAMIENTO/USERS/usr_update1.html', {'form': form})
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')
def USERS_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        objeto = User.objects.get(id=pk)
        objeto.is_active = False
        objeto.save()
        messages.success(request, 'Usuario eliminado correctamente')
        return redirect('/usr_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def USERS_HABILITAR(request, pk):
    try:
        if request.user.is_superuser == False:
            return redirect('/')
        objeto = User.objects.get(id=pk)
        objeto.is_active = True
        objeto.save()
        messages.success(request, 'Usuario habilitado correctamente')
        return redirect('/usr_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

##########################################################################
###########################   PROFORMA   #################################
##########################################################################

def PROFORMA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_listall"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        proveedor = ""
        fecha_desde = ""
        fecha_hasta = ""
        filtrado = False
        empresa = ID_TERRAMAR

        if request.method == 'POST':
            proveedor = request.POST.get('proveedor', '')
            fecha_desde = request.POST.get('fecha_desde', '')
            fecha_hasta = request.POST.get('fecha_hasta', '')
            empresa = request.POST.get('empresa')
            
        if proveedor or fecha_desde or fecha_hasta or empresa:
            filtrado = True

        object_list = get_PROFORMA(
            empresa = empresa,
            proveedor=proveedor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta
        )
        
        lstProveedores = SOCIONEGOCIO.objects.filter(SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL')
        ltsEmpresas = EMPRESA.objects.all()
        
        ctx = {
            'object_list': object_list,
            'lstProveedores': lstProveedores,
            'ltsEmpresas': ltsEmpresas,
            'selectedempresa': int(empresa) if empresa is not None else None, 
            'selectedproveedor': int(proveedor) if proveedor else None,
            'fecha_hasta': fecha_hasta,
            'fecha_desde': fecha_desde,
            'filtrado': filtrado
        }
        return render(request, 'home/PROFORMA/proforma_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')
    
def BORRADOR_PROFORMA_LISTALL(request):
    try:
        if request.user.is_superuser == False:                     
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_listall_borrador"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
            
        proveedor = None
        fecha_desde = None
        fecha_hasta = None
        filtrado = False
        empresa = ID_TERRAMAR
        if request.method == 'POST':
            proveedor = request.POST.get('proveedor', None)
            fecha_desde = request.POST.get('fecha_desde', None)
            fecha_hasta = request.POST.get('fecha_hasta', None)
            empresa = request.POST.get('empresa')
            if not empresa:
                empresa = ID_TERRAMAR
            
        if proveedor or fecha_desde  or fecha_hasta or empresa:
            filtrado = True

        object_list = get_PROFORMA(
            empresa=empresa,
            borrador='True',
            proveedor=proveedor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta
        )
        
        lstProveedores = SOCIONEGOCIO.objects.filter(SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL')
        ltsEmpresas = EMPRESA.objects.all()
        
        ctx = {
            'object_list': object_list,
            'filtrado': filtrado,
            'lstProveedores': lstProveedores,
            'ltsEmpresas': ltsEmpresas,
            'selectedempresa': int(empresa) if empresa is not None else None, 
            'selectedproveedor': int(proveedor) if proveedor else None,
            'fecha_hasta': fecha_hasta,
            'fecha_desde': fecha_desde,
        }
        return render(request, 'home/PROFORMA/proforma_listall_borrador.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')
    
def PROFORMA_DELETE(request, pk):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_delete"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        proforma = PROFORMA.objects.get(id=pk)
        
        if not proforma.PRO_BBORRADOR:
            messages.error(request, f"Solo se pueden eliminar proformas borradores")
            return redirect(f'/proforma_listall')

        if proforma.PRO_CESTADO == "AUTORIZADO":
            messages.error(request, "No se puede eliminar una proforma autorizada")
            return redirect(f'/proforma_listall')

        citacion_proforma = CITACION_PROFORMA.objects.filter(PRO_NID = proforma)
        if citacion_proforma:
            citacion_proforma.delete()

        extra_proforma = EXTRA_PROFORMA.objects.filter(PRO_NID = proforma)
        if extra_proforma:
            extra_proforma.delete()
            
        lineas_proforma = LINEA_PROFORMA.objects.filter(PRO_NID = proforma)
        if lineas_proforma:
            lineas_proforma.delete()

        proforma.delete()
        messages.success(request, 'Proforma eliminada correctamente')
        return redirect(f'/proforma_listall_borrador')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/proforma_listall_borrador')

def PROFORMA_CITACION_LISTALL(request):
    try:
        tipo_citacion = 'RECEPCION'
        proveedor = None
        fecha_desde = None
        fecha_hasta = None
        filtrado = False
        empresa = ID_TERRAMAR

        if request.method == 'POST':
            proveedor = request.POST.get('proveedor', '')
            fecha_desde = request.POST.get('fecha_desde', '')
            fecha_hasta = request.POST.get('fecha_hasta', '')
            tipo_citacion = request.POST.get('tipo_citacion', '')
            empresa = request.POST.get('empresa', '')
            
        if proveedor or fecha_desde or fecha_hasta or tipo_citacion or empresa:
            filtrado = True
        
        citaciones = get_list_citaciones_proforma(
            proveedor = proveedor,
            fecha_desde = fecha_desde,
            fecha_hasta = fecha_hasta,
            tipo_citacion = tipo_citacion,
            empresa = empresa
        )

        # Configurar paginación
        paginator = Paginator(citaciones, 500)  # 50 registros por página
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        lstProveedores = SOCIONEGOCIO.objects.filter(SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL')
        ltsEmpresas = EMPRESA.objects.all()
                
        ctx = {
            'object_list': page_obj.object_list,
            'page_obj': page_obj,
            'paginator': paginator,
            'total_records': len(citaciones),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'lstProveedores': lstProveedores,
            'selectedproveedor': int(proveedor) if proveedor else None,
            'selectedempresa': int(empresa) if empresa is not None else None, 
            'ltsEmpresas': ltsEmpresas,
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'tipo_citacion': tipo_citacion,
            'filtrado': filtrado,
        }
        return render(request, 'home/PROFORMA/proforma_citacion_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PROFORMA_EXTRAS_LISTALL(request):
    try:
        tipo_citacion = 'RECEPCION'
        proveedor = None
        fecha_desde = None
        fecha_hasta = None
        empresa = ID_TERRAMAR
        filtrado = False
        if request.method == 'POST':
            proveedor = request.POST.get('proveedor', '')
            fecha_desde = request.POST.get('fecha_desde', '')
            fecha_hasta = request.POST.get('fecha_hasta', '')
            tipo_citacion = request.POST.get('tipo_citacion', '')
            empresa = request.POST.get('empresa', '')
                        
        if proveedor or fecha_desde or fecha_hasta or tipo_citacion or empresa:
            filtrado = True
        
        object_list = get_EXTRAS_PROFORMA(
            proveedor = proveedor,
            fecha_desde = fecha_desde,
            fecha_hasta = fecha_hasta,
            tipo_citacion = tipo_citacion,
            empresa = empresa
        )
        
        lstProveedores = SOCIONEGOCIO.objects.filter(SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL')
        ltsEmpresas = EMPRESA.objects.all()
                
        ctx = {
            'object_list': object_list,
            'lstProveedores': lstProveedores,
            'ltsEmpresas': ltsEmpresas,
            'selectedproveedor': int(proveedor) if proveedor else None,
            'selectedempresa': int(empresa) if empresa is not None else None, 
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'empresa': empresa,
            'filtrado': filtrado
        }
        return render(request, 'home/PROFORMA/proforma_extras_listall.html', ctx)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PROFORMA_EXTRAS(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_todo"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            id_extras = json.loads(request.POST.get('extras'))
            comentario = request.POST.get('comentario')
            sub_total_proforma = 0
            total_proforma = 0
            total_extras_ingreso = 0
            total_extras_descuento = 0
            proveedor = None
            tipo_citacion = None
            empresa = None
            
            for id_extra in id_extras:
                citacion_extra = CITACION_EXTRA.objects.get(id = id_extra)
                
                # VALIDACIÓN POR TIPO DE CITACIÓN (RECEPCIÓN/DESPACHO)
                if tipo_citacion is not None:
                    if tipo_citacion != citacion_extra.CI_NID.CI_CTIPO:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear proforma para citaciones de diferentes proveedores',
                            'redirect_url': f'/proforma_extra_listall/'
                        })
                else:
                    tipo_citacion = citacion_extra.CI_NID.CI_CTIPO
                
                # VALIDACIÓN POR PROVEEDOR DE LA CITACIÓN 
                if proveedor is not None:
                    if citacion_extra.CI_NID.PRO_NID.pk != proveedor:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear proforma para citaciones de diferentes proveedores',
                            'redirect_url': f'/proforma_extra_listall/'
                        })
                else:
                    proveedor = citacion_extra.CI_NID.PRO_NID.pk
                
                # VALIDACIÓN POR EMPRESA DE LA CITACIÓN (TERRAMAR/ACEITES)
                if empresa is not None:
                    if citacion_extra.EP_NID_id != empresa:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear una proforma con extras de citaciones de diferentes empresas',
                            'redirect_url': f'/proforma_extra_listall/'
                        })
                else:
                    empresa = citacion_extra.EP_NID.pk

                if citacion_extra.CIE_BINGRESO:
                    sub_total_proforma += citacion_extra.CIE_NVALOR
                    total_extras_ingreso  += citacion_extra.CIE_NVALOR
                else:
                    sub_total_proforma -= citacion_extra.CIE_NVALOR
                    total_extras_descuento -= citacion_extra.CIE_NVALOR
                
            iva = sub_total_proforma * Decimal(0.19).quantize(Decimal('0.00'))
            total_proforma = sub_total_proforma + iva
            
            proforma = PROFORMA.objects.create(
                EP_NID_id = empresa,
                US_NID = request.user,
                SN_NID_id = proveedor,
                PRO_CESTADO = 'CREADO',
                PRO_CCOMENTARIO = comentario,
                PRO_NSUBTOTAL = total_proforma,
                PRO_NIVA = iva,
                PRO_NTOTAL = total_proforma,
                PRO_NINGRESO = total_extras_ingreso,
                PRO_NDESCUENTO = total_extras_descuento,
                PRO_FFECHAREGISTRO = datetime.now(),
                PRO_FFECHAEMISION = datetime.now(),
                PRO_CTIPO = f'{tipo_citacion} EXTRAS',
                PRO_BSINEXTRAS = False,
                PRO_BSOLOEXTRAS = True
            )
            
            for id_extra in id_extras:
                extra = CITACION_EXTRA.objects.get(id = id_extra)
                EXTRA_PROFORMA.objects.create(
                    EP_NID_id = empresa,
                    PRO_NID = proforma,
                    CIE_NID = extra,
                    EPR_NVALOR = extra.CIE_NVALOR,
                    EPR_BINGRESO = extra.CIE_BINGRESO
                )

            return JsonResponse({
                'valid': True,
                'proforma': proforma.pk
            })
    except Exception as e:
        print(e)
        return JsonResponse({
            "success": False,
            "Error": str(e)
        })

def PROFORMA_UNITARIA(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_unitaria"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)
        tipo =  None
        if request.method == 'POST':
            citaciones = json.loads(request.POST.get('citaciones'))
            comentario = request.POST.get('comentario')
            for id_citacion in citaciones:
                citacion = CITACION.objects.get(id=id_citacion)
                if tipo is None:
                    tipo = citacion.CI_CTIPO
                total_extras_ingreso = 0
                total_extras_descuento = 0
                tarifa_citacion = citacion.CI_NVALORTARIFA if citacion.CI_NVALORTARIFA is not None else 0

                extras = CITACION_EXTRA.objects.filter(CI_NID = citacion)
                for extra in extras:
                    if extra.CIE_BINGRESO == True:
                        total_extras_ingreso += extra.CIE_NVALOR
                    else:
                        total_extras_descuento += extra.CIE_NVALOR
                
                sub_total_citacion = tarifa_citacion + total_extras_ingreso - total_extras_descuento
                iva = sub_total_citacion * Decimal(0.19).quantize(Decimal('0.00'))
                total_proforma = sub_total_citacion + iva
                proveedor = citacion.CON_NID.SN_NID
                proforma = PROFORMA.objects.create(
                    EP_NID_id = Empresa,
                    US_NID = request.user,
                    SN_NID = proveedor,
                    PRO_CESTADO = 'CREADO',
                    PRO_CCOMENTARIO = comentario,
                    PRO_NSUBTOTAL = total_proforma,
                    PRO_NIVA = iva,
                    PRO_NTOTAL = total_proforma,
                    PRO_NINGRESO = total_extras_ingreso,
                    PRO_NDESCUENTO = total_extras_descuento,
                    PRO_FFECHAREGISTRO = datetime.now(),
                    PRO_FFECHAEMISION = datetime.now(),
                    PRO_CTIPO = citacion.CI_CTIPO
                )
                for extra in extras:
                    EXTRA_PROFORMA.objects.create(
                        EP_NID_id = Empresa,
                        PRO_NID = proforma,
                        CIE_NID = extra,
                        EPR_NVALOR = extra.CIE_NVALOR,
                        EPR_BINGRESO = extra.CIE_BINGRESO
                    )
                CITACION_PROFORMA.objects.create(
                    EP_NID_id = Empresa,
                    PRO_NID = proforma,
                    CI_NID = citacion,
                    CIP_NSUBTOTAL = tarifa_citacion
                )
            return JsonResponse({
                'valid': True,
                'tipo': tipo
            })
    except Exception as e:
        print(e)
        return JsonResponse({
            'valid': False,
            'msg': str(e)
        })

def PROFORMA_TODO(request):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_todo"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        Empresa = Verificar_empresa(request)
        if request.method == 'POST':
            citaciones = json.loads(request.POST.get('citaciones'))
            comentario = request.POST.get('comentario')

            # Conversión correcta de string a booleano
            sin_extras_raw = request.POST.get("sin_extras", "false")
            sin_extras = sin_extras_raw.lower() == 'true'
            sub_total_proforma = 0
            total_proforma = 0
            total_extras_ingreso = 0
            total_extras_descuento = 0
            proveedor = None
            tipo_citacion = None
            empresa = None
            for citacion in citaciones:
                citacion = CITACION.objects.get(id=citacion)
                
                if not citacion.RUT_NID:
                    tarifa = citacion.TAR_NID
                    if tarifa:
                        citacion.RUT_NID = tarifa.RUT_NID
                        citacion.save()
                
                if tipo_citacion is None:
                    tipo_citacion = citacion.CI_CTIPO
                else:
                    if tipo_citacion != citacion.CI_CTIPO:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear proforma para citaciones de diferente tipo',
                            'redirect_url': f'/prof_listall/'
                        })
                        
                
                if proveedor is not None:
                    if citacion.PRO_NID.pk != proveedor:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear proforma para citaciones de diferentes proveedores',
                            'redirect_url': f'/prof_listall/'
                        })
                else:
                    proveedor = citacion.PRO_NID.pk
                
                if empresa is not None:
                    if citacion.EP_NID.pk != empresa:
                        return JsonResponse({
                            'valid': False,
                            'msg': 'No se puede crear una proforma con citaciones de diferentes empresas',
                            'redirect_url': f'/proforma_extra_listall/'
                        })
                else:
                    empresa = citacion.EP_NID.pk
                
                if not sin_extras:
                    extras = CITACION_EXTRA.objects.filter(CI_NID = citacion)
                    for extra in extras:
                        if not EXTRA_PROFORMA.objects.filter(CIE_NID = extra).exists():
                            if extra.CIE_BINGRESO == True:
                                total_extras_ingreso += extra.CIE_NVALOR
                            else:
                                total_extras_descuento += extra.CIE_NVALOR

                if citacion.CI_NVALORTARIFA is not None:
                    sub_total_proforma += citacion.CI_NVALORTARIFA
            
            sub_total_proforma += total_extras_ingreso - total_extras_descuento
            iva = sub_total_proforma * Decimal(0.19).quantize(Decimal('0.00'))
            total_proforma = sub_total_proforma + iva

            proforma = PROFORMA.objects.create(
                EP_NID_id = empresa,
                US_NID = request.user,
                SN_NID_id = proveedor,
                PRO_CESTADO = 'CREADO',
                PRO_CCOMENTARIO = comentario,
                PRO_NSUBTOTAL = total_proforma,
                PRO_NIVA = iva,
                PRO_NTOTAL = total_proforma,
                PRO_NINGRESO = total_extras_ingreso,
                PRO_NDESCUENTO = total_extras_descuento,
                PRO_FFECHAREGISTRO = datetime.now(),
                PRO_FFECHAEMISION = datetime.now(),
                PRO_CTIPO = f'{tipo_citacion}',
                PRO_BSINEXTRAS = sin_extras
            )

            for citacion in citaciones:
                citacion = CITACION.objects.get(id=citacion)
                
                if not sin_extras:
                    extras = CITACION_EXTRA.objects.filter(CI_NID = citacion)
                    for extra in extras:
                        if not EXTRA_PROFORMA.objects.filter(CIE_NID = extra).exists():
                            EXTRA_PROFORMA.objects.create(
                                EP_NID_id = empresa,
                                PRO_NID = proforma,
                                CIE_NID = extra,
                                EPR_NVALOR = extra.CIE_NVALOR,
                                EPR_BINGRESO = extra.CIE_BINGRESO
                            )

                CITACION_PROFORMA.objects.create(
                    EP_NID_id = empresa,
                    PRO_NID = proforma,
                    CI_NID = citacion,
                    CIP_NSUBTOTAL = citacion.CI_NVALORTARIFA if citacion.CI_NVALORTARIFA is not None else 0
                )
            return JsonResponse({
                'valid': True,
                'proforma': proforma.pk
            })
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def PROFORMA_LISTONE(request, pk):
    proforma = None
    try:
        proforma = PROFORMA.objects.get(id=pk)
        proveedor = proforma.SN_NID

        documentos = DOCUMENTO_PROFORMA.objects.filter(PRO_NID=proforma)
        listado_citaciones = get_list_citaciones_xproveedor(proveedor.pk, proforma.EP_NID.pk)

        citaciones_proforma = CITACION_PROFORMA.objects.filter(PRO_NID=proforma).annotate(
            valor_campo_38=Subquery(
                DATO_OPERACION.objects.filter(
                    CI_NID=OuterRef('CI_NID'),
                    CAMP_NID_id=38
                ).values('DO_CVALOR')[:1]
            )
        )

        # Para proformas manuales
        lineas_proforma = LINEA_PROFORMA.objects.filter(PRO_NID=proforma)

        # Extras actualmente habilitados
        extras_proforma_ingreso = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma,
            EPR_BINGRESO=True,
            EPR_BHABILITADO=True
        )
        extras_proforma_descuento = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma,
            EPR_BINGRESO=False,
            EPR_BHABILITADO=True
        )

        total_extras_ingreso = sum(
            extra.EPR_NVALOR or 0 for extra in extras_proforma_ingreso
        )
        total_extras_descuento = sum(
            extra.EPR_NVALOR or 0 for extra in extras_proforma_descuento
        )

        total_tarifas = Decimal('0.00')

        # =========================================================
        # 1) PROFORMAS MANUALES: calcular desde LINEA_PROFORMA
        # =========================================================
        if lineas_proforma.exists():
            for linea in lineas_proforma:
                cantidad = Decimal(linea.LP_NCANTIDAD or 0)
                precio = Decimal(linea.LP_NPRECIO_UNITARIO or 0)
                total_tarifas += cantidad * precio

        # =========================================================
        # 2) PROFORMAS POR CITACIÓN: calcular desde CITACION_PROFORMA
        #    y además crear extras faltantes si corresponde
        # =========================================================
        else:
            extras_existentes = set(
                EXTRA_PROFORMA.objects.filter(PRO_NID=proforma).values_list('CIE_NID', flat=True)
            )

            for citacion_proforma in citaciones_proforma:
                citacion = citacion_proforma.CI_NID

                if proforma.PRO_BSINEXTRAS is False:
                    extras = CITACION_EXTRA.objects.filter(CI_NID=citacion).exclude(
                        id__in=extras_existentes
                    )

                    for extra in extras:
                        extra_proforma, created = EXTRA_PROFORMA.objects.get_or_create(
                            EP_NID=proforma.EP_NID,
                            PRO_NID=proforma,
                            CIE_NID=extra,
                            defaults={
                                'EPR_NVALOR': extra.CIE_NVALOR,
                                'EPR_BINGRESO': extra.CIE_BINGRESO,
                                'EPR_BHABILITADO': True
                            }
                        )

                        # Si se creó recién, actualizar acumulados locales
                        if created:
                            if extra.CIE_BINGRESO:
                                total_extras_ingreso += Decimal(extra.CIE_NVALOR or 0)
                            else:
                                total_extras_descuento += Decimal(extra.CIE_NVALOR or 0)

                total_tarifas += Decimal(citacion.CI_NVALORTARIFA or 0)

        # =========================================================
        # 3) Totales finales
        # =========================================================
        sub_total_proforma = total_tarifas + Decimal(total_extras_ingreso) - Decimal(total_extras_descuento)
        nuevo_iva = (sub_total_proforma * Decimal('0.19')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        nuevo_total_proforma = sub_total_proforma + nuevo_iva

        # Guardar solo si cambió algo
        if (
            Decimal(proforma.PRO_NDESCUENTO or 0) != Decimal(total_extras_descuento) or
            Decimal(proforma.PRO_NINGRESO or 0) != Decimal(total_extras_ingreso) or
            Decimal(proforma.PRO_NSUBTOTAL or 0) != sub_total_proforma or
            Decimal(proforma.PRO_NIVA or 0) != nuevo_iva or
            Decimal(proforma.PRO_NTOTAL or 0) != nuevo_total_proforma
        ):
            proforma.PRO_NDESCUENTO = total_extras_descuento
            proforma.PRO_NINGRESO = total_extras_ingreso
            proforma.PRO_NSUBTOTAL = sub_total_proforma
            proforma.PRO_NIVA = nuevo_iva
            proforma.PRO_NTOTAL = nuevo_total_proforma
            proforma.save(update_fields=[
                'PRO_NDESCUENTO',
                'PRO_NINGRESO',
                'PRO_NSUBTOTAL',
                'PRO_NIVA',
                'PRO_NTOTAL',
            ])

        # Reconsultar extras habilitados por si se creó alguno nuevo
        extras_proforma_ingreso = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma,
            EPR_BINGRESO=True,
            EPR_BHABILITADO=True
        )
        extras_proforma_descuento = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma,
            EPR_BINGRESO=False,
            EPR_BHABILITADO=True
        )

        total_extras_ingreso = sum(extra.EPR_NVALOR or 0 for extra in extras_proforma_ingreso)
        total_extras_descuento = sum(extra.EPR_NVALOR or 0 for extra in extras_proforma_descuento)

        tipos_extras_ingreso = get_list_extras_ingreso(proforma.id)
        tipos_extras_descuento = get_list_extras_descuento(proforma.id)
        total_ingresos_mas_tarifas = total_tarifas + Decimal(total_extras_ingreso)

        logs_proforma = SYSLOGGER.objects.filter(
            LOG_CMODULO='PROFORMA',
            LOG_CADD1=f'Proforma: {proforma.pk}'
        ).order_by('-LOG_FFECHAREGISTRO')

        has_permiso_modificaciones = False
        if request.user.is_superuser is False:
            if validar_perfiles_activos(request.user.id, "modificar_proforma"):
                has_permiso_modificaciones = True
        else:
            has_permiso_modificaciones = True

        ltsRutas = []
        if proforma.PRO_CESTADO == 'CREADO' and proforma.PRO_BBORRADOR:
            ltsRutas = RUTA.objects.all()

        ctx = {
            'proforma': proforma,
            'citaciones_proforma': citaciones_proforma,
            'lineas_proforma': lineas_proforma,
            'listado_citaciones': listado_citaciones,
            'extras_proforma_ingreso': extras_proforma_ingreso,
            'extras_proforma_descuento': extras_proforma_descuento,
            'total_extras_ingreso': total_extras_ingreso,
            'total_extras_descuento': total_extras_descuento,
            'tipos_extras_ingreso': tipos_extras_ingreso,
            'tipos_extras_descuento': tipos_extras_descuento,
            'total_tarifas': total_tarifas,
            'total_ingresos_mas_tarifas': total_ingresos_mas_tarifas,
            'logs_proforma': logs_proforma,
            'has_permiso_modificaciones': has_permiso_modificaciones,
            'ltsRutas': ltsRutas,
            'documentos': documentos,
        }
        return render(request, 'home/PROFORMA/proforma_listone.html', ctx)

    except Exception as e:
        print(f"Error en PROFORMA_LISTONE: {e}")
        messages.error(request, f'Error, {str(e)}')
        if proforma:
            return redirect(f'/proforma_listall/{proforma.PRO_CTIPO}/')
        return redirect('/proforma_listall/')
    
def PROFORMA_LISTONE_SOLO_EXTRAS(request, pk):
    try:
        proforma = PROFORMA.objects.get(id=pk)
        proveedor = proforma.SN_NID
        documentos = DOCUMENTO_PROFORMA.objects.filter(PRO_NID = proforma)
                
        # Solo trabajamos con extras de la proforma
        extras_proforma_ingreso = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma, 
            EPR_BINGRESO=True, 
            EPR_BHABILITADO=True
        )
        extras_proforma_descuento = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma, 
            EPR_BINGRESO=False, 
            EPR_BHABILITADO=True
        )
        
        # Calcular totales solo con extras habilitados
        total_extras_ingreso = 0
        total_extras_descuento = 0
        total_extras = 0
        
        for extra_ingreso in extras_proforma_ingreso:
            total_extras_ingreso += extra_ingreso.EPR_NVALOR
            total_extras += extra_ingreso.EPR_NVALOR
            
        for extra_descuento in extras_proforma_descuento:
            total_extras_descuento += extra_descuento.EPR_NVALOR
            total_extras -= extra_descuento.EPR_NVALOR
        
        # El subtotal solo considera extras (sin tarifas)
        sub_total_proforma = total_extras_ingreso - total_extras_descuento
        
        # Calcular IVA y total
        nuevo_iva = round(sub_total_proforma * Decimal(0.19).quantize(Decimal('0.00')), 0)
        nuevo_total_proforma = sub_total_proforma + nuevo_iva
        
        # Actualizar los valores de la proforma si han cambiado
        if (proforma.PRO_NSUBTOTAL != sub_total_proforma or 
            proforma.PRO_NIVA != nuevo_iva or 
            proforma.PRO_NTOTAL != nuevo_total_proforma):
            
            proforma.PRO_NDESCUENTO = total_extras_descuento
            proforma.PRO_NINGRESO = total_extras_ingreso
            proforma.PRO_NSUBTOTAL = sub_total_proforma
            proforma.PRO_NIVA = nuevo_iva
            proforma.PRO_NTOTAL = nuevo_total_proforma
            proforma.save()
                
        # Obtener logs relacionados con esta proforma
        logs_proforma = SYSLOGGER.objects.filter(
            LOG_CMODULO='PROFORMA',
            LOG_CADD1=f'Proforma: {proforma.pk}'
        ).order_by('-LOG_FFECHAREGISTRO')

        # Verificar permisos de modificación
        has_permiso_modificaciones = False
        if request.user.is_superuser == False:
            if validar_perfiles_activos(request.user.id, "modificar_proforma"):
                has_permiso_modificaciones = True
        else:
            has_permiso_modificaciones = True

        extras_disponibles = get_EXTRAS_PROFORMA(
            proveedor = proveedor.pk,
            empresa = proforma.EP_NID.pk
        )
        
        extras_proforma = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma, 
            EPR_BHABILITADO=True
        )
        
        has_permiso_nuevo_extra = False
        if not request.user.is_superuser:
            usuario = request.user.id
            if validar_perfiles_activos(usuario, "proforma_add_extra"):
                has_permiso_nuevo_extra = True
        else:
            has_permiso_nuevo_extra = True
        
        ctx = {
            'proforma': proforma,
            'extras_proforma': extras_proforma,
            'total_extras': total_extras,
            'logs_proforma': logs_proforma,
            'has_permiso_modificaciones': has_permiso_modificaciones,
            'extras_disponibles': extras_disponibles,
            'has_permiso_nuevo_extra': has_permiso_nuevo_extra,
            'documentos': documentos
        }
        return render(request, 'home/PROFORMA/proforma_listone_solo_extras.html', ctx)
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/proforma_listall/{proforma.PRO_CTIPO}/')

def PROFORMA_LISTONE_MANUAL(request, pk):
    try:
        proforma = PROFORMA.objects.get(id=pk)
        proveedor = proforma.SN_NID
        empresa = proforma.EP_NID
        
        # Obtener documentos asociados a la proforma
        documentos = DOCUMENTO_PROFORMA.objects.filter(PRO_NID=proforma)
        
        # Obtener todas las líneas de la proforma
        lineas_proforma = LINEA_PROFORMA.objects.filter(PRO_NID=proforma).order_by('id')
        
        # Calcular totales basados en las líneas
        subtotal_calculado = Decimal(0)
        for linea in lineas_proforma:
            total_linea = linea.LP_NPRECIO_UNITARIO * linea.LP_NCANTIDAD
            subtotal_calculado += total_linea
        
        # Calcular IVA y total
        iva_calculado = round(subtotal_calculado * Decimal(0.19).quantize(Decimal('0.00')), 0)
        total_calculado = subtotal_calculado + iva_calculado
        
        # Actualizar los valores de la proforma si han cambiado
        if (proforma.PRO_NSUBTOTAL != subtotal_calculado or 
            proforma.PRO_NIVA != iva_calculado or 
            proforma.PRO_NTOTAL != total_calculado):
            
            proforma.PRO_NSUBTOTAL = subtotal_calculado
            proforma.PRO_NIVA = iva_calculado
            proforma.PRO_NTOTAL = total_calculado
            proforma.PRO_NINGRESO = Decimal(0)  # No hay extras en manual
            proforma.PRO_NDESCUENTO = Decimal(0)  # No hay extras en manual
            proforma.save()
        
        # Obtener logs relacionados con esta proforma
        logs_proforma = SYSLOGGER.objects.filter(
            LOG_CMODULO='PROFORMA',
            LOG_CADD1=f'Proforma: {proforma.pk}'
        ).order_by('-LOG_FFECHAREGISTRO')
        
        # Verificar permisos de modificación
        has_permiso_modificaciones = False
        if request.user.is_superuser == False:
            if validar_perfiles_activos(request.user.id, "modificar_proforma"):
                has_permiso_modificaciones = True
        else:
            has_permiso_modificaciones = True
        
        ctx = {
            'proforma': proforma,
            'proveedor': proveedor,
            'empresa': empresa,
            'lineas_proforma': lineas_proforma,
            'documentos': documentos,
            'logs_proforma': logs_proforma,
            'has_permiso_modificaciones': has_permiso_modificaciones,
        }
        return render(request, "home/PROFORMA/proforma_manual_listone.html", ctx)
        
    except PROFORMA.DoesNotExist:
        messages.error(request, f"La proforma #{pk} no existe")
        return redirect('/proforma_listall')
    except Exception as e:
        print(f"Error en PROFORMA_LISTONE_MANUAL: {e}")
        messages.error(request, f"Error: {str(e)}")
        return redirect('/proforma_listall')

def PROFORMA_DELETE_CITACION(request, pk):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_delete_citacion"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')

        # Obtener la citación y su proforma asociada
        citacion_proforma = CITACION_PROFORMA.objects.select_related('PRO_NID', 'CI_NID').get(CI_NID=pk)
        proforma = citacion_proforma.PRO_NID

        # Guardar los valores actuales para restar
        valor_tarifa = citacion_proforma.CI_NID.CI_NVALORTARIFA or 0
        
        # Obtener y eliminar los extras asociados
        extras_proforma = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma,
            CIE_NID__CI_NID=citacion_proforma.CI_NID
        )

        # Actualizar los totales de la proforma
        for extra in extras_proforma:
            if extra.EPR_BINGRESO:
                proforma.PRO_NINGRESO = (proforma.PRO_NINGRESO or 0) - extra.EPR_NVALOR
                proforma.PRO_NSUBTOTAL = (proforma.PRO_NSUBTOTAL or 0) - extra.EPR_NVALOR
            else:
                proforma.PRO_NDESCUENTO = (proforma.PRO_NDESCUENTO or 0) - extra.EPR_NVALOR
                proforma.PRO_NSUBTOTAL = (proforma.PRO_NSUBTOTAL or 0) + extra.EPR_NVALOR

        # Restar el valor de la tarifa
        proforma.PRO_NSUBTOTAL = (proforma.PRO_NSUBTOTAL or 0) - valor_tarifa

        # Recalcular IVA y total
        proforma.PRO_NIVA = proforma.PRO_NSUBTOTAL * Decimal('0.19')
        proforma.PRO_NTOTAL = proforma.PRO_NSUBTOTAL + proforma.PRO_NIVA

        # Eliminar los extras y la citación
        extras_proforma.delete()
        citacion_proforma.delete()

        # Guardar los cambios en la proforma
        proforma.save()

        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Eliminación de citación {pk} de la proforma. Valor tarifa eliminado: ${valor_tarifa}',
            LOG_COPERACION='ELIMINAR_CITACION',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Citación: {pk}'
        )

        messages.success(request, 'Citación eliminada correctamente')
        return redirect('proforma_listone', pk=proforma.pk)

    except CITACION_PROFORMA.DoesNotExist:
        messages.error(request, 'La citación no existe o ya fue eliminada')
        return redirect('home')
    except Exception as e:
        print(f"Error en PROFORMA_DELETE_CITACION: {str(e)}")
        messages.error(request, f'Error al eliminar la citación: {str(e)}')
        return redirect('home')

def PROFORMA_ADD_CITACION(request, pk):
    try:
        if request.method != 'POST':
            return JsonResponse({
                'valid': False,
                'msg': 'Método no permitido'
            }, status=405)

        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_add_citacion"):
                return JsonResponse({
                    'valid': False,
                    'msg': 'No tiene permisos para acceder a esta sección'
                }, status=403)

        proforma = PROFORMA.objects.get(id=pk)
        id_citacion = request.POST.get('CI_NID')
        
        # Validaciones básicas
        if not id_citacion:
            return JsonResponse({
                'valid': False,
                'msg': 'No se recibió ID de citación'
            }, status=400)

        try:
            citacion = CITACION.objects.get(id=id_citacion)
        except CITACION.DoesNotExist:
            return JsonResponse({
                'valid': False,
                'msg': 'La citación no existe'
            }, status=404)

        # Verificar si la citación ya está asociada a la proforma
        if CITACION_PROFORMA.objects.filter(CI_NID=citacion).exists():
            return JsonResponse({
                'valid': False,
                'msg': 'La citación ya está asociada a esta proforma'
            }, status=400)

        if citacion.EP_NID.pk != proforma.EP_NID.pk:
            return JsonResponse({
                'valid': False,
                'msg': 'La citación pertenece a otra empresa'
            }, status=400)
        
        # Crear la asociación citación-proforma
        citacion_proforma = CITACION_PROFORMA.objects.create(
            EP_NID=citacion.EP_NID,
            PRO_NID=proforma,
            CI_NID=citacion,
            CIP_NSUBTOTAL=citacion.CI_NVALORTARIFA if citacion.CI_NVALORTARIFA is not None else 0
        )

        # Agregar los extras de la citación a la proforma
        if proforma.PRO_BSINEXTRAS == False:
            extras = CITACION_EXTRA.objects.filter(CI_NID=citacion)
            extras_count = extras.count()
            
            for extra in extras:
                EXTRA_PROFORMA.objects.create(
                    EP_NID=citacion.EP_NID,
                    PRO_NID=proforma,
                    CIE_NID=extra,
                    EPR_NVALOR=extra.CIE_NVALOR,
                    EPR_BINGRESO=extra.CIE_BINGRESO
                )

        # Actualizar los totales de la proforma
        subtotal_proforma = proforma.PRO_NSUBTOTAL or 0
        total_extras_ingreso = proforma.PRO_NINGRESO or 0
        total_extras_descuento = proforma.PRO_NDESCUENTO or 0

        # Agregar el valor de la tarifa de la citación
        if citacion.CI_NVALORTARIFA:
            subtotal_proforma += citacion.CI_NVALORTARIFA

        # Agregar los valores de los extras
        if proforma.PRO_BSINEXTRAS == False:
            for extra in extras:
                if extra.CIE_BINGRESO:
                    total_extras_ingreso += extra.CIE_NVALOR
                    subtotal_proforma += extra.CIE_NVALOR
                else:
                    total_extras_descuento += extra.CIE_NVALOR
                    subtotal_proforma -= extra.CIE_NVALOR

        # Calcular IVA y total
        iva = subtotal_proforma * Decimal('0.19').quantize(Decimal('0.00'))
        total_proforma = subtotal_proforma + iva

        # Actualizar la proforma
        proforma.PRO_NSUBTOTAL = subtotal_proforma
        proforma.PRO_NIVA = iva
        proforma.PRO_NTOTAL = total_proforma
        proforma.PRO_NINGRESO = total_extras_ingreso
        proforma.PRO_NDESCUENTO = total_extras_descuento
        proforma.save()

        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Agregada citación {id_citacion} a la proforma. Valor tarifa: ${citacion.CI_NVALORTARIFA or 0}, Extras agregados: {extras_count}',
            LOG_COPERACION='AGREGAR_CITACION',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Citación: {id_citacion}'
        )

        return JsonResponse({
            'valid': True,
            'msg': 'Citación agregada correctamente'
        })

    except Exception as e:
        print(f"Error en PROFORMA_ADD_CITACION: {str(e)}")
        return JsonResponse({
            'valid': False,
            'msg': f'Error: {str(e)}'
        }, status=500)

def PROFORMA_DELETE_EXTRA(request, pk):
    extra = EXTRA_PROFORMA.objects.get(id=pk)
    proforma = extra.PRO_NID
    try:
        # Guardar valores antes de la modificación para el log
        valor_eliminado = extra.EPR_NVALOR
        tipo_extra = "Ingreso" if extra.EPR_BINGRESO else "Descuento"
        nombre_extra = extra.CIE_NID.EXT_NID.EXT_CNOMBRE if extra.CIE_NID and extra.CIE_NID.EXT_NID else "Extra desconocido"
        
        subtotal_proforma = proforma.PRO_NSUBTOTAL
        total_extras_ingreso = proforma.PRO_NINGRESO
        total_extras_descuento = proforma.PRO_NDESCUENTO

        # IDENTIFICAMOS SI EL EXTRA ES DE INGRESO/DESCUENTO
        if extra.EPR_BINGRESO == True:
            total_extras_ingreso -= extra.EPR_NVALOR
            subtotal_proforma -= extra.EPR_NVALOR
        else:
            total_extras_descuento -= extra.EPR_NVALOR
            subtotal_proforma += extra.EPR_NVALOR

        # RECALCULAMOS EL IVA Y EL TOTAL
        iva = subtotal_proforma * Decimal(0.19).quantize(Decimal('0.00'))
        total_proforma = subtotal_proforma + iva

        # GUARDAMOS TODOS LOS VALORES OBTENIDOS
        proforma.PRO_NINGRESO = total_extras_ingreso
        proforma.PRO_NDESCUENTO = total_extras_descuento
        proforma.PRO_NSUBTOTAL = subtotal_proforma
        proforma.PRO_NIVA = iva
        proforma.PRO_NTOTAL = total_proforma
        proforma.save()

        extra.EPR_BHABILITADO = False
        extra.save()

        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Eliminación de extra "{nombre_extra}" ({tipo_extra}) por valor ${valor_eliminado}',
            LOG_COPERACION='ELIMINAR_EXTRA',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Extra ID: {pk}'
        )

        return redirect('/proforma_listone/' + str(extra.PRO_NID.pk))
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/proforma_listone/' + str(extra.PRO_NID.pk))

def PROFORMA_AUTORIZAR(request, pk):
    try:
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_autorizar"):
                messages.error(request, 'No tiene permisos para acceder a esta sección')
                return redirect('/')
        
        proforma = PROFORMA.objects.get(id=pk)
        
        if proforma.PRO_CESTADO == 'CREADO' and proforma.PRO_DOC_ENTRY is None:
            Result, Response = CREAR_OC(pk)
            if Result:
                # Guardar valores antes de la autorización para el log
                estado_anterior = proforma.PRO_CESTADO
                
                proforma.PRO_CESTADO = 'AUTORIZADO'
                proforma.PRO_BBORRADOR = False
                proforma.PRO_DOC_NUM = Response['doc_num']
                proforma.PRO_DOC_ENTRY = Response['doc_entry']
                proforma.PRO_FOLIO = pk
                proforma.save()

                # Crear registro en SYSLOGGER
                SYSLOGGER.objects.create(
                    US_NID=request.user,
                    EP_NID_id=proforma.EP_NID.pk,
                    LOG_FFECHAREGISTRO=datetime.now(),
                    LOG_CMODULO='PROFORMA',
                    LOG_CDESCRIPCION=f'Autorización de proforma. Estado anterior: {estado_anterior}, Nuevo estado: AUTORIZADO. DocNum: {Response["doc_num"]}, DocEntry: {Response["doc_entry"]}',
                    LOG_COPERACION='AUTORIZAR_PROFORMA',
                    LOG_CADD1=f'Proforma: {pk}',
                    LOG_CADD2=f'DocNum: {Response["doc_num"]}'
                )

                messages.success(request, 'Proforma autorizada correctamente')
                return redirect(f'/proforma_listone/{pk}')
            else:
                # Crear registro de error en SYSLOGGER
                SYSLOGGER.objects.create(
                    US_NID=request.user,
                    EP_NID_id=proforma.EP_NID.pk,
                    LOG_FFECHAREGISTRO=datetime.now(),
                    LOG_CMODULO='PROFORMA',
                    LOG_CDESCRIPCION=f'Error al autorizar proforma: {Response}',
                    LOG_COPERACION='ERROR_AUTORIZAR',
                    LOG_CADD1=f'Proforma: {pk}',
                    LOG_CADD2='Error en CREAR_OC'
                )
                
                messages.error(request, f'Error, {Response}')
                return redirect(f'/proforma_listone/{pk}')
        else:
            # Crear registro de intento de autorización no válido
            SYSLOGGER.objects.create(
                US_NID=request.user,
                EP_NID_id=proforma.EP_NID.pk,
                LOG_FFECHAREGISTRO=datetime.now(),
                LOG_CMODULO='PROFORMA',
                LOG_CDESCRIPCION=f'Intento de autorización no válido. Estado actual: {proforma.PRO_CESTADO}, DocEntry: {proforma.PRO_DOC_ENTRY}',
                LOG_COPERACION='INTENTO_AUTORIZAR',
                LOG_CADD1=f'Proforma: {pk}',
                LOG_CADD2='No autorizable'
            )
            
            messages.error(request, 'La proforma no se puede autorizar')
            return redirect(f'/proforma_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/proforma_listone/{pk}')

def PROFORMA_AUTORIZAR_AJAX(request, pk):
    """Vista AJAX para autorizar proforma con estados progresivos"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'})
    
    try:
        # Estado 1: Validando proforma
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_autorizar"):
                return JsonResponse({
                    'success': False, 
                    'error': 'No tiene permisos para acceder a esta sección'
                })
        
        proforma = PROFORMA.objects.get(id=pk)
        
        if not (proforma.PRO_CESTADO == 'CREADO' and proforma.PRO_DOC_ENTRY is None):
            return JsonResponse({
                'success': False,
                'error': 'La proforma no se puede autorizar'
            })
                
        # Estado 3: Generando Orden de Compra
        Result, Response = CREAR_OC(pk)
        
        if Result:
            # Estado 5: Almacenando datos
            estado_anterior = proforma.PRO_CESTADO
            
            proforma.PRO_CESTADO = 'AUTORIZADO'
            proforma.PRO_BBORRADOR = False
            proforma.PRO_DOC_NUM = Response['doc_num']
            proforma.PRO_DOC_ENTRY = Response['doc_entry']
            proforma.PRO_FOLIO = pk
            proforma.save()

            # Crear registro en SYSLOGGER
            SYSLOGGER.objects.create(
                US_NID=request.user,
                EP_NID_id=proforma.EP_NID.pk,
                LOG_FFECHAREGISTRO=datetime.now(),
                LOG_CMODULO='PROFORMA',
                LOG_CDESCRIPCION=f'Autorización de proforma. Estado anterior: {estado_anterior}, Nuevo estado: AUTORIZADO. DocNum: {Response["doc_num"]}, DocEntry: {Response["doc_entry"]}',
                LOG_COPERACION='AUTORIZAR_PROFORMA',
                LOG_CADD1=f'Proforma: {pk}',
                LOG_CADD2=f'DocNum: {Response["doc_num"]}'
            )

            return JsonResponse({
                'success': True,
                'message': 'Proforma autorizada correctamente',
                'doc_num': Response['doc_num'],
                'doc_entry': Response['doc_entry']
            })
        else:
            # Crear registro de error en SYSLOGGER
            SYSLOGGER.objects.create(
                US_NID=request.user,
                EP_NID_id=proforma.EP_NID.pk,
                LOG_FFECHAREGISTRO=datetime.now(),
                LOG_CMODULO='PROFORMA',
                LOG_CDESCRIPCION=f'Error al autorizar proforma: {Response}',
                LOG_COPERACION='ERROR_AUTORIZAR',
                LOG_CADD1=f'Proforma: {pk}',
                LOG_CADD2='Error en CREAR_OC'
            )
            
            return JsonResponse({
                'success': False,
                'error': f'Error: {Response}'
            })
            
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        })

def cit_tarifa_ruta(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        ruta = citacion.RUT_NID
        
        proforma = CITACION_PROFORMA.objects.get(CI_NID = citacion).PRO_NID
        
        # Obtener el valor del campo 38 (número de documento) si existe
        numero_documento = None
        try:
            dato_operacion = DATO_OPERACION.objects.filter(CI_NID=citacion, CAMP_NID_id=38).first()
            if dato_operacion:
                numero_documento = dato_operacion.DO_CVALOR
            else:
                # Si no existe el campo 38, usar el número de documento de la citación
                numero_documento = citacion.CI_CNUMERODOCUMENTO
        except Exception as e:
            print(f"Error al obtener número de documento: {e}")
            numero_documento = citacion.CI_CNUMERODOCUMENTO
            
        return JsonResponse({
            'success': True,
            'id_proforma': proforma.pk,
            'id_citacion': pk,
            'id_ruta': ruta.pk if ruta else None ,
            'valor_tarifa': citacion.CI_NVALORTARIFA,
            'numero_documento': numero_documento
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def get_ruta_xtarifa(request, pk):
    try:
        tarifa = TARIFA_GLOBAL.objects.get(id = pk)
        
        return JsonResponse({
            'success': True,
            'nombre_ruta': tarifa.RUT_NID.RUT_CNOMBRE,
            'id_ruta': tarifa.RUT_NID.pk,
            'valor_tarifa': tarifa.TAR_NVALOR
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
        
def PROFORMA_MODIFICAR_TARIFA_CITACION(request):
    try:
        id_proforma = request.POST.get('id_proforma')
        id_citacion = request.POST.get('id_citacion')
        
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "modificar_proforma"):
                messages.error(request, 'No tiene permisos para modificar la tarifa de la citación')
                return redirect(f'/proforma_listone/{id_proforma}/')

        id_tarifa = request.POST.get('tarifa', '')
        id_ruta = request.POST.get('ruta', '')
        valor_tarifa = request.POST.get('valor_tarifa')
        numero_documento = request.POST.get('numero_documento', '').strip()
        
        if not id_proforma or not id_citacion:
            messages.error(request, 'No se puede modificar la tarifa')
            return redirect('proforma_listall_borrador')
        
        # Validar que el valor de tarifa sea válido
        if not valor_tarifa:
            messages.error(request, 'Debe ingresar un valor de tarifa')
            return redirect(f'/proforma_listone/{id_proforma}/')
        
        try:
            valor_tarifa = Decimal(str(valor_tarifa))
        except (InvalidOperation, ValueError):
            messages.error(request, 'El valor de tarifa debe ser un número válido')
            return redirect(f'/proforma_listone/{id_proforma}/')
        
        proforma = PROFORMA.objects.get(id=id_proforma)
        citacion = CITACION.objects.get(id=id_citacion)
        citacion_proforma = CITACION_PROFORMA.objects.get(CI_NID=citacion, PRO_NID=proforma)
        
        # Guardar el valor anterior para calcular la diferencia
        valor_anterior = citacion.CI_NVALORTARIFA or Decimal('0')
        
        if not id_tarifa:
            if id_ruta:
                citacion.RUT_NID_id = id_ruta

            # Caso: No existe id_tarifa - Solo modificar valores
            citacion.CI_NVALORTARIFA = valor_tarifa
            citacion.save()
            
        else:
            # Caso: Existe id_tarifa - Actualizar tarifa, ruta y valor
            try:
                tarifa = TARIFA_GLOBAL.objects.get(id=id_tarifa)
                
                # Si se proporciona ruta, validarla
                if id_ruta:
                    ruta = RUTA.objects.get(id=id_ruta)
                    citacion.RUT_NID = ruta
                else:
                    # Si no se proporciona ruta, usar la ruta de la tarifa
                    citacion.RUT_NID = tarifa.RUT_NID
                
                # Actualizar la tarifa y el valor
                citacion.TAR_NID = tarifa
                citacion.CI_NVALORTARIFA = valor_tarifa
                citacion.save()
                
            except TARIFA_GLOBAL.DoesNotExist:
                messages.error(request, 'La tarifa seleccionada no existe')
                return redirect(f'/proforma_listone/{id_proforma}/')
            except RUTA.DoesNotExist:
                messages.error(request, 'La ruta seleccionada no existe')
                return redirect(f'/proforma_listone/{id_proforma}/')
        
        # Actualizar o crear DATO_OPERACION para el campo 38 (número de documento)
        if numero_documento:
            try:
                campo_38 = CAMPO.objects.get(id=38)
                # Buscar si ya existe un DATO_OPERACION para este campo y citación
                dato_operacion_existente = DATO_OPERACION.objects.filter(
                    CI_NID=citacion,
                    CAMP_NID_id=38
                ).first()
                
                if dato_operacion_existente:
                    # Actualizar el valor existente
                    dato_operacion_existente.DO_CVALOR = numero_documento
                    dato_operacion_existente.DO_FFECHAREGISTRO = datetime.now()
                    dato_operacion_existente.US_NID = request.user
                    dato_operacion_existente.save()
                else:
                    # Crear nuevo DATO_OPERACION
                    # Obtener la etapa actual de la citación
                    etapa_actual = citacion.ETAPA_ACTUAL
                    DATO_OPERACION.objects.create(
                        US_NID=request.user,
                        EP_NID=citacion.EP_NID,
                        CI_NID=citacion,
                        CAMP_NID=campo_38,
                        SC_NID=citacion.SC_NID,
                        ET_NID=etapa_actual,
                        DO_CVALOR=numero_documento,
                        DO_FFECHAREGISTRO=datetime.now()
                    )
            except CAMPO.DoesNotExist:
                print(f"Error: Campo con id=38 no existe")
            except Exception as e:
                print(f"Error al guardar número de documento: {e}")
        
        # Actualizar CITACION_PROFORMA con el nuevo subtotal
        citacion_proforma.CIP_NSUBTOTAL = valor_tarifa
        citacion_proforma.save()
        
        # Recalcular totales de la proforma siguiendo la lógica de creación
        # Obtener todos los extras de la proforma (solo los habilitados)
        extras_proforma = EXTRA_PROFORMA.objects.filter(PRO_NID=proforma, EPR_BHABILITADO=True)
        
        total_extras_ingreso = Decimal('0')
        total_extras_descuento = Decimal('0')
        
        for extra in extras_proforma:
            if extra.EPR_BINGRESO:
                total_extras_ingreso += extra.EPR_NVALOR
            else:
                total_extras_descuento += extra.EPR_NVALOR
        
        # Obtener el total de todas las tarifas de citaciones en esta proforma
        citaciones_en_proforma = CITACION_PROFORMA.objects.filter(PRO_NID=proforma)
        total_tarifas = Decimal('0')
        
        for cit_prof in citaciones_en_proforma:
            if cit_prof.CI_NID.id == int(id_citacion):
                # Usar el nuevo valor para esta citación
                total_tarifas += valor_tarifa
            else:
                # Usar el valor actual para las otras citaciones
                total_tarifas += cit_prof.CI_NID.CI_NVALORTARIFA or Decimal('0')
        
        # Calcular subtotal real (sin IVA)
        subtotal_real = total_tarifas + total_extras_ingreso - total_extras_descuento
        
        # Calcular IVA (19%)
        iva = subtotal_real * Decimal('0.19').quantize(Decimal('0.00'))
        
        # El total incluye IVA
        total_con_iva = subtotal_real + iva
        
        # Actualizar la proforma siguiendo la lógica de creación
        # PRO_NSUBTOTAL almacena el total CON IVA (como en la creación)
        proforma.PRO_NSUBTOTAL = total_con_iva
        proforma.PRO_NIVA = iva
        proforma.PRO_NTOTAL = total_con_iva  # Igual a PRO_NSUBTOTAL
        proforma.PRO_NINGRESO = total_extras_ingreso
        proforma.PRO_NDESCUENTO = total_extras_descuento
        
        proforma.save()
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Modificación de tarifa en citación {id_citacion}. Valor anterior: ${valor_anterior}, Valor nuevo: ${valor_tarifa}',
            LOG_COPERACION='MODIFICAR_TARIFA',
            LOG_CADD1=f'Proforma: {id_proforma}',
            LOG_CADD2=f'Citación: {id_citacion}'
        )
        
        messages.success(request, 'Tarifa modificada exitosamente')
        return redirect(f'/proforma_listone/{id_proforma}')
        
    except PROFORMA.DoesNotExist:
        messages.error(request, 'La proforma no existe')
        return redirect('proforma_listall_borrador')
    except CITACION.DoesNotExist:
        messages.error(request, 'La citación no existe')
        return redirect('proforma_listall_borrador')
    except CITACION_PROFORMA.DoesNotExist:
        messages.error(request, 'La relación citación-proforma no existe')
        return redirect('proforma_listall_borrador')
    except Exception as e:
        print(e)
        messages.error(request, f'Error al modificar la tarifa: {str(e)}')
        return redirect('proforma_listall_borrador')

def PROFORMA_ADD_EXTRA(request, pk):
    try:
        proforma = PROFORMA.objects.get(id = pk)
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "proforma_add_extra"):
                return JsonResponse({
                    'valid': False,
                    'msg': 'No tiene permisos para acceder a esta sección'
                }, status=403)

        id_extra = request.POST.get('CIE_NID')
        
        if not id_extra:
            return JsonResponse({
                'valid': False,
                'msg': 'No se recibió ID del extra'
            }, status=400)
            
        try:
            extra = CITACION_EXTRA.objects.get(id = id_extra)
        except CITACION_EXTRA.DoesNotExist:
            return JsonResponse({
                'valid': False,
                'msg': 'El extra no existe'
            }, status=404)

        if EXTRA_PROFORMA.objects.filter(CIE_NID = extra).exists():
            return JsonResponse({
                'valid': False,
                'msg': 'El extra ya está asociada a una proforma'
            }, status=400)
        
        extra_proforma = EXTRA_PROFORMA.objects.create(
            EP_NID = proforma.EP_NID,
            CIE_NID = extra,
            PRO_NID = proforma,
            EPR_NVALOR = extra.CIE_NVALOR,
            EPR_BINGRESO = extra.CIE_BINGRESO,
        )
        
        # Actualizar los totales de la proforma
        subtotal_proforma = proforma.PRO_NSUBTOTAL or 0
        total_extras_ingreso = proforma.PRO_NINGRESO or 0
        total_extras_descuento = proforma.PRO_NDESCUENTO or 0
        
        if extra.CIE_BINGRESO:
            subtotal_proforma += extra.CIE_NVALOR
            total_extras_ingreso += extra.CIE_NVALOR
        else:
            subtotal_proforma -= extra.CIE_NVALOR
            total_extras_descuento += extra.CIE_NVALOR
        
        # Calcular IVA y total
        iva = round(subtotal_proforma * Decimal('0.19').quantize(Decimal('0.00')), 0)
        total_proforma = subtotal_proforma + iva
        
        # Actualizar la proforma
        proforma.PRO_NSUBTOTAL = subtotal_proforma
        proforma.PRO_NIVA = iva
        proforma.PRO_NTOTAL = total_proforma
        proforma.PRO_NINGRESO = total_extras_ingreso
        proforma.PRO_NDESCUENTO = total_extras_descuento
        proforma.save()
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Agregada extra {extra.EXT_NID.EXT_CNOMBRE} a la proforma. Valor del extra: ${extra.CIE_NVALOR or 0}',
            LOG_COPERACION='AGREGAR_CITACION',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Extra: {extra.pk}'
        )
        messages.success(request, f'Extra agregado correctamente')
        return redirect(f'/proforma_listone_extras/{pk}') 
    
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/proforma_listone_extras/{pk}') 

def DOCUMENTO_PROFORMA_ADDONE(request, pk):
    try:

        proforma = PROFORMA.objects.get(id = pk)
        if request.method == 'POST':
            archivo = request.FILES['file_proforma']
            # Create a new folder with CON_CRUT if it doesn't exist
            if proforma.EP_NID.id == ID_TERRAMAR:
                base_folder = DOCUMENTOS_PROFORMA_TERRAMAR_PATH
            elif proforma.EP_NID.id == ID_ACEITES_SBH:
                base_folder = DOCUMENTOS_PROFORMA_ACEITESS_PATH

            folder_path = os.path.join(base_folder, str(proforma.pk))
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

            # Save the file in the new folder and change the file name to a uuid
            file_extension = archivo.name.split('.')[-1]
            file_name = archivo.name.split('.')[0]
            file_path = os.path.join(folder_path, file_name+'.'+file_extension)
            with open(file_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            
            documento = DOCUMENTO_PROFORMA.objects.create(
                EP_NID = proforma.EP_NID,
                US_NID = request.user,
                PRO_NID = proforma,
                DP_CNOMBREDOCUMENTO = file_name,
                DP_CRUTADOC = file_path,
                DP_FFECHAREGISTRO = datetime.now(),
                DP_BHABILITADO = True
            )
            if "EXTRA" in proforma.PRO_CTIPO:
                return redirect(f'/proforma_listone_extras/{str(proforma.pk)}')
            elif proforma.PRO_CTIPO == "MANUAL":
                return redirect(f'/proforma-manual/{str(proforma.pk)}/')
            else:
                return redirect(f'/proforma_listone/{str(proforma.pk)}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        if "EXTRA" in proforma.PRO_CTIPO:
            return redirect(f'/proforma_listone_extras/{str(proforma.pk)}')
        elif proforma.PRO_CTIPO == "MANUAL":
            return redirect(f'/proforma-manual/{str(proforma.pk)}/')
        else:
            return redirect(f'/proforma_listone/{str(proforma.pk)}')

def DOCUMENTO_PROFORMA_DELETE(request, pk):
    try:
        documento = DOCUMENTO_PROFORMA.objects.get(id=pk)
        proforma = documento.PRO_NID
        
        # Validar permisos si es necesario
        if request.user.is_superuser == False:
            usuario = request.user.id
            if not validar_perfiles_activos(usuario, "documento_proforma_delete"):
                messages.error(request, 'No tiene permisos para eliminar documentos')
                if "EXTRA" in proforma.PRO_CTIPO:
                    return redirect(f'/proforma_listone_extras/{str(proforma.pk)}')
                elif proforma.PRO_CTIPO == "MANUAL":
                    return redirect(f'/proforma-manual/{str(proforma.pk)}/')
                else:
                    return redirect(f'/proforma_listone/{str(proforma.pk)}')
        
        # Guardar información para el log antes de eliminar
        nombre_documento = documento.DP_CNOMBREDOCUMENTO
        ruta_documento = documento.DP_CRUTADOC
        documento_pk = documento.pk
        
        # Eliminar el archivo físico si existe
        if os.path.exists(ruta_documento):
            os.remove(ruta_documento)
            
            # Opcional: Eliminar la carpeta si está vacía
            folder_path = os.path.dirname(ruta_documento)
            if os.path.exists(folder_path) and not os.listdir(folder_path):
                os.rmdir(folder_path)
        
        # Eliminar el registro de la base de datos
        documento.delete()
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID=proforma.EP_NID,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Eliminado documento "{nombre_documento}" de la proforma',
            LOG_COPERACION='ELIMINAR_DOCUMENTO',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Documento: {documento_pk}'
        )
        
        messages.success(request, f'Documento "{nombre_documento}" eliminado correctamente')
        
        if "EXTRA" in proforma.PRO_CTIPO:
            return redirect(f'/proforma_listone_extras/{str(proforma.pk)}')
        elif proforma.PRO_CTIPO == "MANUAL":
            return redirect(f'/proforma-manual/{str(proforma.pk)}/')
        else:
            return redirect(f'/proforma_listone/{str(proforma.pk)}')
            
    except DOCUMENTO_PROFORMA.DoesNotExist:
        messages.error(request, 'El documento no existe')
        return redirect('/proforma_list/')
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al eliminar el documento: {str(e)}')
        try:
            if "EXTRA" in proforma.PRO_CTIPO:
                return redirect(f'/proforma_listone_extras/{str(proforma.pk)}')
            elif proforma.PRO_CTIPO == "MANUAL":
                return redirect(f'/proforma-manual/{str(proforma.pk)}/')
            else:
                return redirect(f'/proforma_listone/{str(proforma.pk)}')
        except:
            return redirect('/proforma_list/')

def DOCUMENTO_PROFORMA_DOWNLOAD(request, pk):
    try:
        documento = DOCUMENTO_PROFORMA.objects.get(id = pk)
        file_path = documento.DP_CRUTADOC
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            return response
        else:
            messages.error(request, 'Documento no encontrado')
            if "EXTRA" in documento.PRO_NID.PRO_CTIPO:
                return redirect(f'/proforma_listone_extras/{str(documento.PRO_NID.pk)}')
            else:
                return redirect(f'/proforma_listone/{str(documento.PRO_NID.pk)}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/proforma_listall/')

def PROFORMA_MANUAL_ADD(request):
    try:
        if request.method == "POST":
            # Obtener datos del formulario
            empresa_id = request.POST.get('empresa')
            proveedor_id = request.POST.get('proveedor')
            comentarios = request.POST.get('comentarios', '')
            cantidad_lineas = int(request.POST.get('cantidad_lineas', 0))
            
            # Obtener valores de totales
            subtotal = Decimal(request.POST.get('subtotal_proforma_input', 0))
            iva = Decimal(request.POST.get('total_iva_input', 0))
            total = Decimal(request.POST.get('total_proforma_input', 0))
            
            # Validar que existan empresa y proveedor
            if not empresa_id or not proveedor_id:
                messages.error(request, "Debe seleccionar una empresa y un proveedor")
                return redirect('/proforma_manual_add')
            
            # Obtener instancias
            empresa = EMPRESA.objects.get(pk=empresa_id)
            proveedor = SOCIONEGOCIO.objects.get(pk=proveedor_id)
            
            # Manejar fecha de emisión
            fecha_emision_input = request.POST.get('fecha_emision')
            if fecha_emision_input:
                # Si se proporcionó una fecha personalizada
                fecha_emision = timezone.datetime.strptime(fecha_emision_input, '%Y-%m-%d')
                fecha_emision = timezone.make_aware(fecha_emision)
            else:
                # Usar fecha actual
                fecha_emision = timezone.now()
            
            # Crear la proforma
            proforma = PROFORMA.objects.create(
                EP_NID=empresa,
                US_NID=request.user,
                SN_NID=proveedor,
                PRO_CESTADO='CREADO',
                PRO_CCOMENTARIO=comentarios,
                PRO_NSUBTOTAL=subtotal,
                PRO_NIVA=iva,
                PRO_NTOTAL=total,
                PRO_NINGRESO=Decimal(0),
                PRO_NDESCUENTO=Decimal(0),
                PRO_FFECHAREGISTRO=timezone.now(),
                PRO_FFECHAEMISION=fecha_emision,
                PRO_CTIPO='MANUAL',
                PRO_BBORRADOR=True,
                PRO_BSINEXTRAS=False,
                PRO_BSOLOEXTRAS=False
            )
            
            # Crear las líneas de la proforma
            for i in range(1, cantidad_lineas + 1):
                tipo_item = request.POST.get(f'LP_CTIPO_ITEM_{i}')
                descripcion = request.POST.get(f'LP_CDESCRIPCION_{i}')
                precio_unitario = request.POST.get(f'LP_NPRECIO_UNITARIO_{i}')
                cantidad = request.POST.get(f'LP_NCANTIDAD_{i}')
                
                # Validar que existan todos los datos de la línea
                if tipo_item and descripcion and precio_unitario and cantidad:
                    LINEA_PROFORMA.objects.create(
                        PRO_NID=proforma,
                        LP_CTIPO_ITEM=tipo_item,
                        LP_NCANTIDAD=int(cantidad),
                        LP_NPRECIO_UNITARIO=Decimal(precio_unitario),
                        LP_CDESCRIPCION=descripcion,
                        US_NID=request.user
                    )
            
            messages.success(request, f"Proforma Manual #{proforma.pk} creada exitosamente")
            return redirect(f'/proforma_manual_listone/{str(proforma.pk)}')
        
        # GET request
        proveedores = SOCIONEGOCIO.objects.filter(SN_CTIPO='S', SN_BHABILITADO=True).order_by('SN_CRAZONSOCIAL')
        empresas = EMPRESA.objects.all().order_by('EP_CRAZONSOCIAL')
        fecha_actual = timezone.now()
        
        ctx = {
            "proveedores": proveedores,
            'empresas': empresas,
            'fecha_actual': fecha_actual
        }
        return render(request, "home/PROFORMA/proforma_manual_add.html", ctx)
        
    except EMPRESA.DoesNotExist:
        messages.error(request, "La empresa seleccionada no existe")
        return redirect('/proforma_manual_add')
    except SOCIONEGOCIO.DoesNotExist:
        messages.error(request, "El proveedor seleccionado no existe")
        return redirect('/proforma_manual_add')
    except ValueError as e:
        messages.error(request, f"Error en los valores ingresados: {str(e)}")
        return redirect('/proforma_manual_add')
    except Exception as e:
        print(f"Error en PROFORMA_MANUAL_ADD: {e}")
        messages.error(request, f"Error al crear la proforma: {str(e)}")
        return redirect('/proforma_manual_add')

def proforma_manual_add_linea(request):
    """Vista AJAX para agregar una línea a la proforma manual"""
    try:
        proforma_id = request.POST.get('proforma_id')
        tipo_item = request.POST.get('tipo_item')
        descripcion = request.POST.get('descripcion')
        precio_unitario = request.POST.get('precio_unitario')
        cantidad = request.POST.get('cantidad')
        
        # Validar datos
        if not all([proforma_id, tipo_item, descripcion, precio_unitario, cantidad]):
            return JsonResponse({
                'valid': False,
                'msg': 'Todos los campos son obligatorios'
            })
        
        # Obtener la proforma
        proforma = PROFORMA.objects.get(id=proforma_id)
        
        # Verificar que sea borrador
        if not proforma.PRO_BBORRADOR:
            return JsonResponse({
                'valid': False,
                'msg': 'No se pueden agregar líneas a una proforma aprobada'
            })
        
        # Crear la línea
        linea = LINEA_PROFORMA.objects.create(
            PRO_NID=proforma,
            LP_CTIPO_ITEM=tipo_item,
            LP_NCANTIDAD=int(cantidad),
            LP_NPRECIO_UNITARIO=Decimal(precio_unitario),
            LP_CDESCRIPCION=descripcion,
            US_NID=request.user
        )
        
        # Calcular el total de la línea
        total_linea = Decimal(precio_unitario) * int(cantidad)
        
        # Recalcular totales
        recalcular_totales_proforma(proforma)
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Agregada nueva línea a proforma manual.',
            LOG_COPERACION='AGREGAR_LINEA',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Línea ID: {linea.id}'
        )
        
        return JsonResponse({
            'valid': True,
            'msg': 'Línea agregada exitosamente',
            'linea_id': linea.id
        })
        
    except PROFORMA.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'msg': 'La proforma no existe'
        })
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'msg': f'Error al agregar línea: {str(e)}'
        })

def proforma_manual_delete_linea(request):
    """Vista AJAX para eliminar una línea de la proforma manual"""
    try:
        linea_id = request.POST.get('linea_id')
        
        if not linea_id:
            return JsonResponse({
                'valid': False,
                'msg': 'ID de línea no proporcionado'
            })
        
        linea = LINEA_PROFORMA.objects.get(id=linea_id)
        proforma = linea.PRO_NID
        
        # Verificar que sea borrador
        if not proforma.PRO_BBORRADOR:
            return JsonResponse({
                'valid': False,
                'msg': 'No se pueden eliminar líneas de una proforma aprobada'
            })
        
        # Guardar datos de la línea antes de eliminarla para el log
        tipo_item = linea.LP_CTIPO_ITEM
        descripcion = linea.LP_CDESCRIPCION
        precio_unitario = linea.LP_NPRECIO_UNITARIO
        cantidad = linea.LP_NCANTIDAD
        total_linea = precio_unitario * cantidad
        
        # Eliminar la línea
        linea.delete()
        
        # Recalcular totales
        recalcular_totales_proforma(proforma)
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Eliminada línea de proforma manual. Tipo: {tipo_item}, Descripción: {descripcion}, Cantidad: {cantidad}, Precio Unitario: ${precio_unitario}, Total eliminado: ${total_linea}',
            LOG_COPERACION='ELIMINAR_LINEA',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Línea ID: {linea_id}'
        )
        
        return JsonResponse({
            'valid': True,
            'msg': 'Línea eliminada exitosamente'
        })
        
    except LINEA_PROFORMA.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'msg': 'La línea no existe'
        })
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'msg': f'Error al eliminar línea: {str(e)}'
        })

def proforma_manual_get_linea(request):
    """Vista AJAX para obtener datos de una línea"""
    try:
        linea_id = request.GET.get('linea_id')
        
        if not linea_id:
            return JsonResponse({
                'valid': False,
                'msg': 'ID de línea no proporcionado'
            })
        
        linea = LINEA_PROFORMA.objects.get(id=linea_id)
        
        return JsonResponse({
            'valid': True,
            'linea': {
                'id': linea.id,
                'tipo_item': linea.LP_CTIPO_ITEM,
                'descripcion': linea.LP_CDESCRIPCION,
                'precio_unitario': str(linea.LP_NPRECIO_UNITARIO),
                'cantidad': linea.LP_NCANTIDAD
            }
        })
        
    except LINEA_PROFORMA.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'msg': 'La línea no existe'
        })
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'msg': f'Error al obtener línea: {str(e)}'
        })
        
def proforma_manual_edit_linea(request):
    """Vista AJAX para editar una línea de la proforma manual"""
    try:
        linea_id = request.POST.get('linea_id')
        tipo_item = request.POST.get('tipo_item')
        descripcion = request.POST.get('descripcion')
        precio_unitario = request.POST.get('precio_unitario')
        cantidad = request.POST.get('cantidad')
        
        # Validar datos
        if not all([linea_id, tipo_item, descripcion, precio_unitario, cantidad]):
            return JsonResponse({
                'valid': False,
                'msg': 'Todos los campos son obligatorios'
            })
        
        linea = LINEA_PROFORMA.objects.get(id=linea_id)
        proforma = linea.PRO_NID
        
        # Verificar que sea borrador
        if not proforma.PRO_BBORRADOR:
            return JsonResponse({
                'valid': False,
                'msg': 'No se pueden editar líneas de una proforma aprobada'
            })
        
        # Guardar valores anteriores para el log
        tipo_item_anterior = linea.LP_CTIPO_ITEM
        descripcion_anterior = linea.LP_CDESCRIPCION
        precio_unitario_anterior = linea.LP_NPRECIO_UNITARIO
        cantidad_anterior = linea.LP_NCANTIDAD
        total_anterior = precio_unitario_anterior * cantidad_anterior
        
        # Actualizar la línea
        linea.LP_CTIPO_ITEM = tipo_item
        linea.LP_CDESCRIPCION = descripcion
        linea.LP_NPRECIO_UNITARIO = Decimal(precio_unitario)
        linea.LP_NCANTIDAD = int(cantidad)
        linea.save()
        
        # Calcular nuevo total
        total_nuevo = Decimal(precio_unitario) * int(cantidad)
        
        # Recalcular totales
        recalcular_totales_proforma(proforma)
        
        # Construir descripción detallada del cambio
        cambios = []
        if tipo_item_anterior != tipo_item:
            cambios.append(f"Tipo: '{tipo_item_anterior}' → '{tipo_item}'")
        if descripcion_anterior != descripcion:
            cambios.append(f"Descripción: '{descripcion_anterior}' → '{descripcion}'")
        if precio_unitario_anterior != Decimal(precio_unitario):
            cambios.append(f"Precio Unitario: ${precio_unitario_anterior} → ${precio_unitario}")
        if cantidad_anterior != int(cantidad):
            cambios.append(f"Cantidad: {cantidad_anterior} → {cantidad}")
        if total_anterior != total_nuevo:
            cambios.append(f"Total: ${total_anterior} → ${total_nuevo}")
        
        cambios_texto = ", ".join(cambios) if cambios else "Sin cambios en valores"
        
        # Crear registro en SYSLOGGER
        SYSLOGGER.objects.create(
            US_NID=request.user,
            EP_NID_id=proforma.EP_NID.pk,
            LOG_FFECHAREGISTRO=datetime.now(),
            LOG_CMODULO='PROFORMA',
            LOG_CDESCRIPCION=f'Editada línea de proforma manual. Cambios: {cambios_texto}',
            LOG_COPERACION='EDITAR_LINEA',
            LOG_CADD1=f'Proforma: {proforma.pk}',
            LOG_CADD2=f'Línea ID: {linea_id}'
        )
        
        return JsonResponse({
            'valid': True,
            'msg': 'Línea actualizada exitosamente'
        })
        
    except LINEA_PROFORMA.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'msg': 'La línea no existe'
        })
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'msg': f'Error al actualizar línea: {str(e)}'
        })

def recalcular_totales_proforma(proforma):
    """Función auxiliar para recalcular los totales de una proforma manual"""
    lineas = LINEA_PROFORMA.objects.filter(PRO_NID=proforma)
    
    subtotal = Decimal(0)
    for linea in lineas:
        subtotal += linea.LP_NPRECIO_UNITARIO * linea.LP_NCANTIDAD
    
    iva = round(subtotal * Decimal(0.19).quantize(Decimal('0.00')), 0)
    total = subtotal + iva
    
    proforma.PRO_NSUBTOTAL = subtotal
    proforma.PRO_NIVA = iva
    proforma.PRO_NTOTAL = total
    proforma.save()

##########################################################################
##############################   CHAT   ##################################
##########################################################################

def get_token(username):
    # Intenta obtener el token del caché
    cache_key = f'api_token_{username}'
    token = cache.get(cache_key)
    
    if token is None:
        # Si no está en caché, obtén un nuevo token
        url = 'http://34.225.254.125:91/login'
        psw = 'neuronia'
        
        body = json.dumps({
            'username': username,
            'password': psw,
        })
        
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=body,
        )
        
        if response.status_code == 200:
            token_data = response.json()
            token = token_data["token"]
            
            # Guarda el token en caché por un tiempo determinado (por ejemplo, 1 hora)
            cache.set(cache_key, token, timeout=3600)
        else:
            raise Exception(f"No se pudo obtener el token: {response.text}")
    
    return token

def AXONASK(request):
    try:
        ask = request.POST.get('ask')
        to = request.POST.get('to')
        usr = request.user.username

        # Obtén el token usando la función auxiliar
        try:
            token = get_token(usr)
        except Exception as e:
            return JsonResponse({'message': f'ALERT!!!lo siento {usr} no encuentro tu autorización: {str(e)}'}, status=200)
        

        url = 'http://34.225.254.125:91/insertpush'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }
        #username = request.user.username
        body = json.dumps({
            'ask': ask,
        })
        response = requests.post(
            f'{url}/{usr}/{to}/{ask}',
            headers=headers,
            data=body,
        )
        print(response)
        if response.status_code == 201:
            responseData = response.json()
            print(responseData)
            if isinstance(responseData.get('Message'), str):
                apiResponseText = responseData['Message']
                response_message = ""
            else:
                #if isinstance(responseData.get('Message'), list) and all(isinstance(item, list) for item in responseData.get('Message')):
                    try:
                        response_message = ""
                    except Exception as e:
                        response_message = "ALERT!!!No puedo manejar el formato de la respuesta"
                #else:
                #    response_message = "No puedo manejar el formato de la respuesta"
                #response_message = "No puedo manejar el formato de la respuesta"
        else:
            response_message = "ALERT!!!No entiendo esto"

        print("ask",ask)
        response=f"{response_message}"
    

        return JsonResponse({'message': response}, status=200)
    except Exception as e:  
        print("ERROR:",e)
        return JsonResponse({'message': "No puedo responder ahora, lo siento"}, status=200)

def AXONCHECKMESSAGE(request):
    try:
        from_user = request.POST.get('from_user')
        url = 'http://34.225.254.125:91/login'
        usr = request.user.username

        # Obtén el token usando la función auxiliar
        try:
            tokenAPI = get_token(usr)
        except Exception as e:
            return JsonResponse({'message': f'ALERT!!!lo siento {usr} no encuentro tu autorización: {str(e)}'}, status=200)
        
        url = f'http://34.225.254.125:91/push/{usr}/{from_user}'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {tokenAPI}',
        }
        response = requests.post(
            url,
            headers=headers,
        )
        print(response)
        if response.status_code == 201:
            responseData = response.json()
            print(responseData)
            if isinstance(responseData.get('Message'), str):
                apiResponseText = responseData['Message']
                response_message = apiResponseText
            else:
                try:
                    response_message = list(sublist[1] for sublist in responseData.get('Message'))
                except Exception as e:
                    response_message = "ALERT!!!No puedo manejar el formato de la respuesta"
        else:
            response_message = None
        response=response_message
    
        return JsonResponse({'message': response}, status=200)
    except Exception as e:
        print(e)

def AXONGETUSERS(request):
    try:
        url = 'http://34.225.254.125:91/login'
        usr = request.user.username
        # Obtén el token usando la función auxiliar
        try:
            tokenAPI = get_token(usr)
        except Exception as e:
            return JsonResponse({'message': f'ALERT!!!lo siento {usr} no encuentro tu autorización: {str(e)}'}, status=200)

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {tokenAPI}',
        }
        url = f'http://34.225.254.125:91/get-user-msg/{usr}'

        response = requests.get(
            url,
            headers=headers,
        )
        responseData = response.json()
        if response.status_code == 201:
            apiResponseText = responseData['Message']
            return JsonResponse({'main': request.user.username,'users': apiResponseText}, status=200)
        else:
            response_message = responseData['ERROR']
            return JsonResponse({'message': response_message}, status=400)
    except Exception as e:
        print(e)
        return JsonResponse({'message': 'ALERT!!!No puedo responder ahora, lo siento'}, status=400)
    
def AXONGETUNREADMESSAGES(request):
    try:
        url = 'http://34.225.254.125:91/login'
        usr = request.user.username
        # Obtén el token usando la función auxiliar
        try:
            tokenAPI = get_token(usr)
        except Exception as e:
            return JsonResponse({'message': f'ALERT!!!lo siento {usr} no encuentro tu autorización: {str(e)}'}, status=200)

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {tokenAPI}',
        }

        url = f'http://34.225.254.125:91/get-unread-msg/{usr}'
        response = requests.get(
            url,
            headers=headers,
        )
        responseData = response.json()
        if response.status_code == 201:
            apiResponseText = responseData['Message']
            return JsonResponse({'users': apiResponseText}, status=200)
        else:
            response_message = responseData['ERROR']
            return JsonResponse({'message': response_message}, status=400)
    except Exception as e:
        print(e)
        return JsonResponse({'message': 'ALERT!!!No puedo responder ahora, lo siento'}, status=400)

def AXONGETCURRENTUSER(request):
    try:
        url = 'http://34.225.254.125:91/login'
        usr = request.user.username
        # Obtén el token usando la función auxiliar
        try:
            tokenAPI = get_token(usr)
        except Exception as e:
            return JsonResponse({'message': f'ALERT!!!lo siento {usr} no encuentro tu autorización: {str(e)}'}, status=200)

        url = f'http://34.225.254.125:91/get-user-msg/{usr}'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {tokenAPI}',
        }
        response = requests.get(
            url,
            headers=headers,
        )
        responseData = response.json()
        if response.status_code == 201:
            apiResponseText = responseData['Message']
            if apiResponseText is not None:
                return JsonResponse({'user': apiResponseText[0][0]}, status=200)
            else:
                user = User.objects.filter(is_active=True).exclude(id=request.user.id).order_by('username').first()
                return JsonResponse({'user': user.username}, status=200)
        else:
            response_message = responseData['ERROR']
            return JsonResponse({'message': response_message}, status=400)
    except Exception as e:
        print(e)
        return JsonResponse({'message': 'ALERT!!!No puedo responder ahora, lo siento'}, status=400)

##########################################################################
##########################   NOTIFICACIONES   ############################
##########################################################################

def CHECK_NOTIFICATIONS(request):
    try:
        notificaciones = get_notificaciones(request.user.id)
        return JsonResponse({
            'notificaciones': notificaciones,
            'user_id': request.user.id
        }, status=200)
    except Exception as e:
        print(e)


def LIMPIAR_NOTIFICACIONES(request):
    try:
        if request.method != 'POST':
            return JsonResponse({
                'success': False,
                'message': 'Metodo no permitido.'
            }, status=405)

        notificaciones = NOTIFICACION.objects.filter(
            USER_RECEIVER_ID=request.user,
            NOT_BREAD=False,
            NOT_BHABILITADO=True
        )
        cantidad = notificaciones.count()
        notificaciones.update(
            NOT_BREAD=True,
            NOT_FFECHALEIDO=timezone.now()
        )

        return JsonResponse({
            'success': True,
            'message': 'Notificaciones limpiadas correctamente.',
            'cantidad': cantidad
        }, status=200)

    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

##########################################################################
#########################   CUPOS PROVEEDOR   ############################
##########################################################################

def CUPO_PROVEEDOR_ADD_MASIVE(request, pk):
    try:
        planificacion = PLANIFICACION.objects.get(id = pk)
        if request.method == 'POST' and request.FILES['excel_file']:
            ltsErrors = []
            cupos_disponibles = planificacion.TOTAL_CUPOS_DISPONIBLES
            total_cupos_proveedor = 0
            excel_file = request.FILES.get('excel_file')
            df = pd.read_excel(excel_file, dtype=None)
            df = df.fillna(" ")
            for index, row in df.iterrows():
                try:
                    cod_proveedor = row[0]
                    cupos = int(row[1])

                    if not cod_proveedor or not cupos:
                        raise Exception('El codigo de proveedor o la cantidad de cupos no puede ser nulo')

                    proveedor = SOCIONEGOCIO.objects.filter(SN_CCODIGO_SAP = cod_proveedor).first()
                    if not proveedor:
                        raise Exception('El proveedor no existe')
                    
                    total_cupos_proveedor += cupos
                    cupo_proveedor = CUPO_PROVEEDOR.objects.filter(PLA_NID = planificacion, PRO_NID = proveedor).first()

                    if not cupo_proveedor:
                        sobrecupo = False
                        if total_cupos_proveedor > cupos_disponibles:
                            sobrecupo = True

                        CUPO_PROVEEDOR.objects.create(
                            PLA_NID = planificacion, 
                            PRO_NID = proveedor, 
                            CUP_NVALOR = cupos,
                            CUP_BSOBRECUPO = sobrecupo
                        )
                    else:
                        old_cupos = cupo_proveedor.CUP_NCUPOS
                        cupos_ocupados = get_cupos_proveedor(planificacion.id, proveedor.id)
                        if cupos_ocupados == old_cupos and old_cupos > cupos:
                            diferencia = old_cupos - cupos
                            if diferencia < 0:
                                diferencia = diferencia * -1

                            result = update_citaciones_sobre_cupo(planificacion.id, proveedor.id, diferencia)

                            if result is None:
                                raise Exception('No se pudo actualizar las citaciones sobre cupo')
                            else:
                                cupo_proveedor.CUP_NCUPOS = cupos
                                cupo_proveedor.CUP_BSOBRECUPO = True
                                cupo_proveedor.save()

                        elif cupos_ocupados == old_cupos and old_cupos < cupos:

                            cupo_proveedor.CUP_NCUPOS = cupos
                            cupo_proveedor.CUP_BSOBRECUPO = True
                            cupo_proveedor.save()

                        elif cupos_ocupados < old_cupos and old_cupos < cupos:

                            diferencia = cupos - old_cupos
                            sobrecupo = False

                            if total_cupos_proveedor > cupos_disponibles:
                                sobrecupo = True

                            cupo_proveedor.CUP_NCUPOS = cupos
                            cupo_proveedor.CUP_BSOBRECUPO = sobrecupo
                            cupo_proveedor.save()
                        elif cupos_ocupados < old_cupos and old_cupos > cupos:
                            if cupos < cupos_ocupados:
                                diferencia = cupos_ocupados - cupos
                                result = update_citaciones_sobre_cupo(planificacion.id, proveedor.id, diferencia)

                                if result is None:
                                    raise Exception('No se pudo actualizar las citaciones sobre cupo')
                                else:
                                    cupo_proveedor.CUP_NCUPOS = cupos
                                    cupo_proveedor.CUP_BSOBRECUPO = True
                                    cupo_proveedor.save()
                            else:
                                sobrecupo = False
                                if total_cupos_proveedor > cupos_disponibles:
                                    sobrecupo = True

                                cupo_proveedor.CUP_NCUPOS = cupos
                                cupo_proveedor.CUP_BSOBRECUPO = sobrecupo
                                cupo_proveedor.save()
                        else:
                            sobrecupo = False
                            if total_cupos_proveedor > cupos_disponibles:
                                sobrecupo = True

                                cupo_proveedor.CUP_NCUPOS = cupos
                                cupo_proveedor.CUP_BSOBRECUPO = sobrecupo
                                cupo_proveedor.save()
                except Exception as e:
                    print(e)
                    excepcion = str(e)
                    error = ''
                    if excepcion == 'El codigo de proveedor o la cantidad de cupos no puede ser nulo':
                        error = 'El codigo de proveedor o la cantidad de cupos no puede ser nulo'
                    elif excepcion == 'El proveedor no existe':
                        error = 'El proveedor no existe'
                    else:
                        error = excepcion

                    linea = list(row)
                    linea.append(error)
                    ltsErrors.append(linea)

            if len(ltsErrors) > 0:
                # OBTENEMOS LAS COLUMNAS DEL EXCEL CARGADO
                columnas = list(df.columns.values)
                # AGREGAMOS LA COLUMNA DE ERRORES
                columnas.append('Error')
                # ENVIAMOS EL LISTADO DE ERRORES Y LAS COLUMNAS A LA FUNCION DE CREACION DE EXCEL
                link = excel_errores(ltsErrors, columnas)
                # Agrega un mensaje de error con un enlace a la respuesta.
                message = 'Hay datos que no se pudieron guardar debido a que contienen errores, se ha generado un excel con los datos no guardados, cerrar este mensaje y descargar excel desde el link de la parte inferior del formulario.'
                messages.info(request, message, extra_tags='safe')
                # SE INDICA AL FRONT QUE EXISTEN ERRORES PARA QUE SE ACTIVE EL LINK DE DESCARGA DEL EXCEL ESPECIFICANDO DONDE ESTAN LAS FILAS CON ERRORES Y CUALES SON LOS ERRORES
                context = {
                    'link': link ,
                    'error': 1,
                    'planificacion': planificacion
                }
                return render(request, 'home/PLANIFICACION/cupo_proveedor_add_masive.html', context)
            else:
                messages.success(request, 'Cupos agregados correctamente')
                return redirect(f'/pla_listone/{pk}')
                
        context = {
            'planificacion': planificacion,
        }
        return render(request, 'home/PLANIFICACION/cupo_proveedor_add_masive.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/pla_listone/{pk}')

def download_plantilla_cupos(request):
    columnas = ['CÓDIGO PROVEEDOR', 'CANTIDAD DE CUPOS']

    # Crea un nuevo libro de trabajo de Excel.
    workbook = openpyxl.Workbook()

    # Selecciona la hoja activa.
    worksheet = workbook.active
    # CARGAMOS LA COLUMNAS 
    worksheet.append(columnas)

    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename=plantilla_cupos_proveedor.xlsx'
    workbook.save(response)

    return response

def CUPO_PROVEEDOR_ADDONE(request, pk):
    try:
        planificacion = PLANIFICACION.objects.get(id = pk)
        if request.method == 'POST':
            form = formCUPO_PROVEEDOR(request.POST)
            if form.is_valid():
                planificacion = form.cleaned_data['PLA_NID']
                proveedor = form.cleaned_data['PRO_NID']
                cupos = form.cleaned_data['CUP_NVALOR']
                cupo_proveedor = CUPO_PROVEEDOR.objects.filter(PLA_NID = planificacion, PRO_NID = proveedor).first()
                if cupo_proveedor:
                    messages.error(request, 'El proveedor ya tiene un cupo asignado')
                    return redirect(f'/pla_listone/{pk}')
                cupos_disponibles = planificacion.TOTAL_CUPOS_DISPONIBLES
                
                if cupos > cupos_disponibles:
                    form.instance.CUP_BSOBRECUPO = True
                    

                form.save()
                messages.success(request, 'Cupo agregado correctamente')
                return redirect(f'/pla_listone/{pk}')
            else:
                messages.error(request, f'Error, {str(form.errors)}')
                return redirect(f'/pla_listone/{pk}')
        else:
            form = formCUPO_PROVEEDOR()
            form.fields['PRO_NID'].widget.choices = list(SOCIONEGOCIO.objects.filter(SN_CTIPO = 'S').values_list('id', 'SN_CRAZONSOCIAL'))

        context = {
            'form': form,
            'planificacion': planificacion
        }
        return render(request, 'home/PLANIFICACION/cupo_proveedor_addone.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/pla_listone/')

##########################################################################
##########################   ZONA   ######################################
##########################################################################

def ZONA_LISTALL(request):
    try:
        Empresa = Verificar_empresa(request)
        if Empresa is None:
            messages.error(request, 'No se pudo verificar la empresa')
            return redirect('/')

        zonas = ZONA.objects.filter(EP_NID = Empresa)
        context = {
            'object_list': zonas
        }
        return render(request, 'home/ZONA/zon_listall.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/')

def ZONA_ADDONE(request):
    try:
        if request.method == 'POST':
            form = formZONA(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Zona agregada correctamente')
                return redirect('/zon_listall/')
            else:
                messages.error(request, f'Error, {str(form.errors)}')
                return redirect('/zon_addone/')
        form = formZONA()
        context = {
            'form': form
        }
        return render(request, 'home/ZONA/zon_addone.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/zon_listall/')
    
def ZONA_UPDATE(request, pk):
    try:
        zona = ZONA.objects.get(id = pk)
        if request.method == 'POST':
            form = formZONA(request.POST, instance=zona)
            if form.is_valid():
                form.save()
                messages.success(request, 'Zona actualizada correctamente')
                return redirect('/zon_listall/')
            else:
                messages.error(request, f'Error, {str(form.errors)}')
                return redirect(f'/zon_update/{pk}')
        form = formZONA(instance=zona)
        context = {
            'form': form,
            'zona': zona
        }
        return render(request, 'home/ZONA/zon_addone.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/zon_listall/')

def ZONA_DELETE(request, pk):
    try:
        zona = ZONA.objects.get(id = pk)
        etapas = ETAPA.objects.filter(ZON_NID = zona, ET_BHABILITADO = True)
        if etapas.exists():
            messages.error(request, 'La zona tiene etapas asociadas')
            return redirect('/zon_listall/')
        
        zona.ZON_BHABILITADO = False
        zona.save()
        messages.success(request, 'Zona eliminada correctamente')
        return redirect('/zon_listall/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect('/zon_listall/')

##########################################################################
####################   IMPORTACION PLANIFICACION   #######################
##########################################################################

def IMPORTACION_PLANIFICACION(request, pk):
    try:
        planificacion = PLANIFICACION.objects.get(id = pk)
        fecha_planificacion = planificacion.PL_FFECHAINICIO.strftime('%Y-%m-%d')
        ltsErrors = []
        if request.method == 'POST' and request.FILES['file']:
            excel_file = request.FILES.get('file')
            df = pd.read_excel(excel_file, dtype=None)
            df = df.fillna(" ")
            for index, row in df.iterrows():
                try:
                    tipo_citacion = row[0]
                    proveedor = row[1]
                    conductor = row[2]
                    camion = row[3]
                    secuencia = row[4]
                    hora_citacion = row[5]
                    producto = row[6]
                    cliente = row[7]
                    ruta = row[8]
                    documento = row[9]
                    numero_documento = row[10]
                    observaciones = row[11]

                    if not tipo_citacion or not proveedor or not conductor or not camion or not secuencia or not hora_citacion or not producto or not cliente or not ruta or not documento:
                        raise Exception('Faltan datos en los campos obligatorios')
                    
                    if not numero_documento:
                        numero_documento = None

                    if not observaciones:
                        observaciones = None
                    
                    proveedor = SOCIONEGOCIO.objects.filter(SN_CCODIGO_SAP = proveedor).first()
                    if not proveedor:
                        raise Exception('El proveedor no existe')

                    conductor = CONDUCTOR.objects.filter(CON_CRUT = conductor, SN_NID = proveedor).first()
                    if not conductor:
                        raise Exception('El conductor no existe')

                    camion = CAMION.objects.filter(CAM_CPATENTE = camion, SN_NID = proveedor).first()
                    if not camion:
                        raise Exception('El camion no existe')

                    secuencia = SECUENCIA.objects.filter(SE_CNOMBRE = secuencia).first()
                    if not secuencia:
                        raise Exception('La secuencia no existe')
                    
                    producto = ITEM.objects.filter(IT_CCODIGO = producto).first()
                    if not producto:
                        raise Exception('El producto no existe')

                    cliente = SOCIONEGOCIO.objects.filter(SN_CCODIGO_SAP = cliente).first()
                    if not cliente:
                        raise Exception('El cliente no existe')

                    ruta = RUTA.objects.filter(RUT_CNOMBRE = ruta).first()
                    if not ruta:
                        raise Exception('La ruta no existe')

                    documento_obj = DOCUMENTO_SOCIONEGOCIO.objects.filter(DSN_CTIPO = documento, LIS_CGRUPO = '').first()
                    if not documento_obj:
                        raise Exception('El documento no existe')
                    
                    tarifa = TARIFA_GLOBAL.objects.filter(RUT_NID = ruta, SN_NID = proveedor, TAR_BHABILITADO = True).first()
                    if not tarifa:
                        raise Exception('La tarifa no existe')

                    fecha_citacion = fecha_planificacion + ' ' + hora_citacion
                    fecha_citacion = datetime.strptime(fecha_citacion, '%Y-%m-%d %H:%M')
                    valor_tarifa = tarifa.TAR_NVALOR
                    diferencia_tarifa = 0

                    citacion = CITACION.objects.create(
                        PL_NID = planificacion,
                        EP_NID = planificacion.EP_NID,
                        SN_NID = cliente,
                        CON_NID = conductor,
                        CA_NID = camion,
                        RUT_NID = ruta,
                        SC_NID = secuencia,
                        TAR_NID = tarifa,
                        US_NID = request.user,
                        PRO_NID = proveedor,
                        CI_FFECHAREGISTRO = datetime.now(),
                        CI_FFECHACITACION = fecha_citacion,
                        CI_CESTADO = CIT_CREADO,
                        CI_NDIFERENCIATARIFA = diferencia_tarifa,
                        CI_NVALORTARIFA = valor_tarifa,
                        CI_CCOMENTARIO = row['observacion'],
                        CI_CTIPODOCUMENTO = documento,
                        CI_CNUMERODOCUMENTO = numero_documento,
                        CI_CTIPO = tipo_citacion
                    )
                    CITACION_ITEM.objects.create(
                        CI_NID = citacion,
                        IT_NID = producto,
                        EP_NID = planificacion.EP_NID
                    )
                except Exception as e:
                    excepcion = str(e)
                    if excepcion == 'Faltan datos en los campos obligatorios':
                        error = 'Faltan datos en los campos obligatorios'
                    elif excepcion == 'El proveedor no existe':
                        error = 'El proveedor no existe'
                    elif excepcion == 'El conductor no existe':
                        error = 'El conductor no existe'
                    elif excepcion == 'El camion no existe':
                        error = 'El camion no existe'
                    elif excepcion == 'La secuencia no existe':
                        error = 'La secuencia no existe'
                    elif excepcion == 'El producto no existe':
                        error = 'El producto no existe'
                    else:
                        error = excepcion
                    linea = list(row)
                    linea.append(error)
                    ltsErrors.append(linea)

            if len(ltsErrors) > 0:
                columnas = list(df.columns.values)
                columnas.append('Error')
                link = excel_errores(ltsErrors, columnas)
                message = 'Hay datos que no se pudieron guardar debido a que contienen errores, se ha generado un excel con los datos no guardados, cerrar este mensaje y descargar excel desde el link de la parte inferior del formulario.'
                messages.info(request, message, extra_tags='safe')
                context = {
                    'link': link ,
                    'error': 1,
                    'planificacion': planificacion
                }
                return render(request, 'home/PLANIFICACION/importacion_planificacion.html', context)
            else:
                messages.success(request, 'Planificacion importada correctamente')
                return redirect(f'/pla_listone/{pk}')
        context = {
            'planificacion': planificacion
        }
        return render(request, 'home/PLANIFICACION/importacion_planificacion.html', context)
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/pla_listone/{pk}')

def download_plantilla_planificacion(request):
    columnas = ['TIPO CITACION*','PROVEEDOR*', 'CONDUCTOR*', 'CAMION*', 'SECUENCIA*', 'HORA CITACION*','PRODUCTO*', 'CLIENTE*', 'RUTA*', 'DOCUMENTO*', 'NÚMERO DOCUMENTO (Opcional)', 'OBSERVACIONES (Opcional)']

    # Crea un nuevo libro de trabajo de Excel.
    workbook = openpyxl.Workbook()

    # Selecciona la hoja activa.
    worksheet = workbook.active

    # CARGAMOS LA COLUMNAS 
    worksheet.append(columnas)

    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename=plantilla_citaciones.xlsx'
    workbook.save(response)    

    return response


def obtener_cupos_disponibles(request):
    try:
        cupos_disponibles_por_zona = get_cupos_zona()
        return JsonResponse(cupos_disponibles_por_zona, safe=False)  # Asegúrate de que el formato sea correcto
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)  # Retorna un error en caso de excepción


def CITACION_EDITAR_ETAPA_TERMINADA(request):
    if request.method == 'POST':
        try:
            # Manejar campos regulares
            for key, value in request.POST.items():
                if key.startswith('campo_'):
                    campo_id = key.split('_')[1]
                    dato_operacion = DATO_OPERACION.objects.filter(id=campo_id).first()
                    
                    # Si es un campo de archivo, verificar si hay un archivo actual
                    archivo_actual_key = f'archivo_actual_{campo_id}'
                    if archivo_actual_key in request.POST:
                        continue  # Saltamos porque este campo se maneja con FILES
                    
                    # Para campos no archivo
                    if dato_operacion:
                        # Para checkboxes: Django envía una lista si hay múltiples valores con el mismo nombre
                        # Si el checkbox está marcado, se enviará ['off', 'on'], si no está marcado solo ['off']
                        valores = request.POST.getlist(key)
                        if len(valores) > 1 and 'on' in valores:
                            # Checkbox marcado
                            dato_operacion.DO_CVALOR = 'on'
                            dato_operacion.save()
                        elif len(valores) == 1 and valores[0] == 'off':
                            # Checkbox no marcado
                            dato_operacion.DO_CVALOR = 'off'
                            dato_operacion.save()
                        elif value and value != 'off':
                            # Otros tipos de campos
                            dato_operacion.DO_CVALOR = value
                            dato_operacion.save()
            
            # Manejar archivos
            for key, file in request.FILES.items():
                if key.startswith('campo_'):
                    campo_id = key.split('_')[1]
                    dato_operacion = DATO_OPERACION.objects.filter(id=campo_id).first()
                    
                    if dato_operacion:
                        # Guardar el nuevo archivo
                        file_path = handle_uploaded_file(file)  # Necesitas implementar esta función
                        dato_operacion.DO_CVALOR = file_path
                        dato_operacion.save()
                
            return JsonResponse({'status': 'success'})
        except Exception as e:
            print(f"Error en CITACION_EDITAR_ETAPA_TERMINADA: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'Error al procesar la solicitud: {str(e)}'}, status=400)

def CREAR_OC(pk):
    try:
        proforma = PROFORMA.objects.get(id = pk)
        proforma_lineas = CITACION_PROFORMA.objects.filter(PRO_NID = proforma)
        lineas_proforma = LINEA_PROFORMA.objects.filter(PRO_NID = proforma)
        if not proforma.PRO_BSOLOEXTRAS and not proforma_lineas and not lineas_proforma:
            raise Exception('No hay lineas en la proforma')
        
        if proforma.EP_NID_id == ID_TERRAMAR:
            ruta_credenciales = r"C:\inetpub\wwwroot\TERRAMAR-CAMIONES\loginHDB.json"
            serial = 79 # Serie NAC
        elif  proforma.EP_NID_id == ID_ACEITES_SBH:
            ruta_credenciales = r"C:\inetpub\wwwroot\TERRAMAR-CAMIONES\loginMSS.json"
            serial = 1
        
        #Conectar a SAP
        vCompany = sapConnect(
            ruta_credenciales=ruta_credenciales
        )
        if vCompany is None:
            raise Exception('No se pudo conectar a SAP')
        
        #Crear la orden de compra
        opor = vCompany.GetBusinessObject(OPOR)

        opor.Series = serial # Serie Dependiendo de la empresa
        opor.CardCode = proforma.SN_NID.SN_CCODIGO_SAP  # Código del proveedor
        opor.DocDate = proforma.PRO_FFECHAREGISTRO  # Fecha del documento
        opor.DocDueDate = proforma.PRO_FFECHAREGISTRO  # Fecha de vencimiento
        opor.TaxDate = proforma.PRO_FFECHAREGISTRO  # Fecha de contabilización
        opor.DocCurrency = "CLP"
        opor.UserFields.Fields.Item("U_CodProf").Value = str(pk)
        
        for linea in proforma_lineas:
            item_code, account_number = linea.GET_ITEM_CODE()
            opor.Lines.ItemCode = item_code
            opor.Lines.ItemDescription = f"Servicio de transporte - Citación {str(linea.CI_NID_id)}"
            opor.Lines.Quantity = 1
            opor.Lines.Price = linea.CIP_NSUBTOTAL
            opor.Lines.AccountCode = account_number
            opor.Lines.WarehouseCode = "EP"  # Reemplaza con el código correcto
            opor.Lines.Add()
        
        extras_proforma = EXTRA_PROFORMA.objects.filter(PRO_NID = proforma)
        for extra in extras_proforma:
            opor.Lines.ItemCode = extra.CIE_NID.EXT_NID.EXT_CARTICULOSAP
            opor.Lines.ItemDescription = f'Extra {extra.CIE_NID.EXT_NID.EXT_CNOMBRE} - Citación {str(extra.CIE_NID.CI_NID_id)}'
            opor.Lines.Quantity = 1
            if extra.CIE_NID.CIE_BINGRESO:
                opor.Lines.Price = extra.EPR_NVALOR
            else:
                opor.Lines.Price = (extra.EPR_NVALOR * -1)                
            opor.Lines.AccountCode = extra.CIE_NID.EXT_NID.EXT_CCUENTASAP
            opor.Lines.WarehouseCode = "EP"  # Reemplaza con el código correcto
            opor.Lines.Add()
        
        for linea in lineas_proforma:
            item_code, account_number = linea.GET_ITEM_CODE()
            
            opor.Lines.ItemCode = item_code
            opor.Lines.ItemDescription = f'{linea.LP_CDESCRIPCION}'
            opor.Lines.Quantity = int(linea.LP_NCANTIDAD)
            opor.Lines.Price = linea.LP_NPRECIO_UNITARIO        
            opor.Lines.AccountCode = account_number
            opor.Lines.WarehouseCode = "EP"  # Reemplaza con el código correcto
            opor.Lines.Add()
        
        # 5. Intentar guardar la orden
        res = opor.Add()
        if res != 0:
            print("Error al crear la orden:", vCompany.GetLastErrorDescription())
            vCompany.Disconnect()
            return None, vCompany.GetLastErrorDescription()
        else:
            doc_entry = vCompany.GetNewObjectKey()
            
            # Recuperar el documento recién creado para obtener el DocNum
            opor_created = vCompany.GetBusinessObject(OPOR)
            if opor_created.GetByKey(doc_entry):
                doc_num = opor_created.DocNum
                print(f"Orden creada - DocEntry: {doc_entry}, DocNum: {doc_num}")
                vCompany.Disconnect()
                return True, {"doc_entry": doc_entry, "doc_num": doc_num}
            else:
                vCompany.Disconnect()
                return True, {"doc_entry": doc_entry, "doc_num": None}
    except Exception as e:
        print(e)
        vCompany.Disconnect()
        return False, str(e)
    
def handle_uploaded_file(file):
    """
    Función auxiliar para manejar el guardado de archivos
    """
    # Definir la carpeta donde se guardarán los archivos
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generar un nombre único para el archivo
    filename = f"{uuid.uuid4()}_{file.name}"
    file_path = os.path.join(upload_dir, filename)
    
    # Guardar el archivo
    with open(file_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)
    
    return file_path

def guardar_zona(request):
    try:
        # Obtener los datos del request
        data = json.loads(request.body)
        
        # Extraer la información
        nombre = data.get('nombre')
        cupo_maximo = data.get('cupoMaximo')
        coordenadas = data.get('coordenadas', [])
        
        # Validar que tenemos los datos necesarios
        if not nombre or not cupo_maximo:
            return JsonResponse({
                "success": False,
                "error": "Nombre y cupo máximo son requeridos"
            })
        
        # Validar que tenemos suficientes coordenadas (3 o 4 puntos)
        if len(coordenadas) < 6:  # Al menos 3 puntos (6 coordenadas)
            return JsonResponse({
                "success": False,
                "error": "Se requieren al menos 3 puntos para crear una zona"
            })
        
        # Limitar a 4 puntos (8 coordenadas)
        if len(coordenadas) > 8:
            coordenadas = coordenadas[:8]
        
        # Obtener la empresa actual (ajustar según cómo manejes la empresa en tu sistema)
        # Esta línea debe ser ajustada según tu lógica de negocio
        empresa = EMPRESA.objects.get(id=1)  # Por defecto usamos ID 1, ajustar según necesidad
        
        # Crear la nueva zona
        nueva_zona = ZONA(
            EP_NID=empresa,
            ZON_CNOMBRE=nombre,
            ZON_NCANTIDADCUPOS=cupo_maximo
        )
        
        # Asignar coordenadas según los puntos disponibles
        if len(coordenadas) >= 2:
            nueva_zona.ZON_CLATITUD1 = str(coordenadas[0])
            nueva_zona.ZON_CLONGITUD1 = str(coordenadas[1])
        
        if len(coordenadas) >= 4:
            nueva_zona.ZON_CLATITUD2 = str(coordenadas[2])
            nueva_zona.ZON_CLONGITUD2 = str(coordenadas[3])
        
        if len(coordenadas) >= 6:
            nueva_zona.ZON_CLATITUD3 = str(coordenadas[4])
            nueva_zona.ZON_CLONGITUD3 = str(coordenadas[5])
        
        if len(coordenadas) >= 8:
            nueva_zona.ZON_CLATITUD4 = str(coordenadas[6])
            nueva_zona.ZON_CLONGITUD4 = str(coordenadas[7])
        
        # Guardar la zona en la base de datos
        nueva_zona.save()
        
        # Preparar objeto de respuesta con la información necesaria para actualizar la UI
        respuesta = {
            "success": True,
            "id": nueva_zona.id,
            "zona": {
                "nombre": nombre,
                "cupoMaximo": cupo_maximo,
                "coordenadas": coordenadas
            },
            "mensaje": f"Zona '{nombre}' creada exitosamente"
        }
        
        return JsonResponse(respuesta)
    
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Formato JSON inválido"
        })
    except EMPRESA.DoesNotExist:
        return JsonResponse({
            "success": False,
            "error": "Empresa no encontrada"
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            "success": False,
            "error": str(e)
        })

def obtener_zonas(request):
    """
    Vista para obtener todas las zonas activas
    """
    try:
        # Obtener todas las zonas de la empresa actual (habilitadas)
        zonas = ZONA.objects.filter(ZON_BHABILITADO=True)
        
        # Formatear las zonas para el frontend
        zonas_formateadas = []
        for zona in zonas:
            zona_data = [
                zona.ZON_CNOMBRE,  # Nombre - posición 0
                
                # Convertir coordenadas a números si es posible
                float(zona.ZON_CLATITUD1) if zona.ZON_CLATITUD1 and zona.ZON_CLATITUD1.strip() else "",
                float(zona.ZON_CLONGITUD1) if zona.ZON_CLONGITUD1 and zona.ZON_CLONGITUD1.strip() else "",
                
                float(zona.ZON_CLATITUD2) if zona.ZON_CLATITUD2 and zona.ZON_CLATITUD2.strip() else "",
                float(zona.ZON_CLONGITUD2) if zona.ZON_CLONGITUD2 and zona.ZON_CLONGITUD2.strip() else "",
                
                float(zona.ZON_CLATITUD3) if zona.ZON_CLATITUD3 and zona.ZON_CLATITUD3.strip() else "",
                float(zona.ZON_CLONGITUD3) if zona.ZON_CLONGITUD3 and zona.ZON_CLONGITUD3.strip() else "",
                
                float(zona.ZON_CLATITUD4) if zona.ZON_CLATITUD4 and zona.ZON_CLATITUD4.strip() else "",
                float(zona.ZON_CLONGITUD4) if zona.ZON_CLONGITUD4 and zona.ZON_CLONGITUD4.strip() else "",
                
                "", "",  # Vacíos - posiciones 9 y 10
                
                zona.ZON_CCOLOR or "#4caf50",  # Color - posición 11
                zona.ZON_CNOMBRE,  # Identificador - posición 12
                0,  # Cupos ocupados (se podría calcular dinámicamente) - posición 13
                zona.ZON_NCANTIDADCUPOS or 0,  # Cupos máximos - posición 14
                zona.pk
            ]
            zonas_formateadas.append(zona_data)
            
        return JsonResponse({
            "success": True,
            "zonas": zonas_formateadas
        })
    except Exception as e:
        print(f"Error al obtener zonas: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)

def get_camiones_x_zona(request):
    try:
        id_zona = request.GET.get("id_zona")
        zona = ZONA.objects.get(id = id_zona)
        camiones_zona = get_camiones_por_zona(id_zona)
        
        return JsonResponse({
            'success': True,
            'nombre_zona': zona.ZON_CNOMBRE,
            'total_camiones': len(camiones_zona),
            'cupos_total': zona.ZON_NCANTIDADCUPOS,
            'camiones_zona': camiones_zona
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            "success": False,
            "error": str(e)
        })

def guardar_posicion_zona(request):
    """
    Vista para guardar la posición de una zona en el plano
    """
    try:
        if not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No puedes realizar esta acción'
            })
        
        if request.method != 'POST':
            return JsonResponse({
                'success': False,
                'error': 'Método no permitido'
            })
        
        # Obtener datos del request
        id_zona = request.POST.get('id_zona')
        coordenadas = request.POST.get('coordenadas')
        accion = request.POST.get('accion', 'actualizar')
        
        # Validar datos requeridos
        if not id_zona:
            return JsonResponse({
                'success': False,
                'error': 'ID de zona requerido'
            })
        
        if not coordenadas and accion != 'eliminar':
            return JsonResponse({
                'success': False,
                'error': 'Coordenadas requeridas'
            })
        
        # Buscar la zona existente
        try:
            # Buscar la zona sin importar el estado de ZON_BHABILITADO para crear/actualizar
            # Solo verificar ZON_BHABILITADO=True para eliminar
            if accion == 'eliminar':
                zona = ZONA.objects.get(id=id_zona, ZON_BHABILITADO=True)
            else:
                zona = ZONA.objects.get(id=id_zona)
        except ZONA.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Zona no encontrada'
            })
        
        if accion == 'eliminar':
            # Soft delete - marcar como deshabilitada (disponible para agregar nuevamente)
            zona.ZON_BHABILITADO = False
            zona.save()
            
            return JsonResponse({
                'success': True,
                'mensaje': f'Zona {zona.ZON_CNOMBRE} eliminada del plano'
            })
        
        else:
            # Actualizar coordenadas de la zona
            try:
                coordenadas_list = json.loads(coordenadas)
                
                # Validar que tenemos coordenadas válidas
                if len(coordenadas_list) < 6:  # Al menos 3 puntos
                    return JsonResponse({
                        'success': False,
                        'error': 'Se requieren al menos 3 puntos'
                    })
                
                # Limitar a 4 puntos máximo
                if len(coordenadas_list) > 8:
                    coordenadas_list = coordenadas_list[:8]
                
                # Actualizar las coordenadas en la zona
                if len(coordenadas_list) >= 2:
                    zona.ZON_CLATITUD1 = str(coordenadas_list[0])
                    zona.ZON_CLONGITUD1 = str(coordenadas_list[1])
                
                if len(coordenadas_list) >= 4:
                    zona.ZON_CLATITUD2 = str(coordenadas_list[2])
                    zona.ZON_CLONGITUD2 = str(coordenadas_list[3])
                
                if len(coordenadas_list) >= 6:
                    zona.ZON_CLATITUD3 = str(coordenadas_list[4])
                    zona.ZON_CLONGITUD3 = str(coordenadas_list[5])
                
                if len(coordenadas_list) >= 8:
                    zona.ZON_CLATITUD4 = str(coordenadas_list[6])
                    zona.ZON_CLONGITUD4 = str(coordenadas_list[7])
                else:
                    # Limpiar coordenadas del punto 4 si no se proporciona
                    zona.ZON_CLATITUD4 = ""
                    zona.ZON_CLONGITUD4 = ""
                
                # Marcar la zona como habilitada (en uso en el mapa)
                zona.ZON_BHABILITADO = True
                
                # Guardar los cambios
                zona.save()
                
                return JsonResponse({
                    'success': True,
                    'mensaje': f'Posición de zona {zona.ZON_CNOMBRE} actualizada ({accion})'
                })
                
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Formato de coordenadas inválido'
                })
    
    except Exception as e:
        print(f"Error en guardar_posicion_zona: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
    
def obtener_posiciones_zonas(request):
    """
    Vista para cargar las posiciones guardadas al inicializar el plano
    """
    try:
        Empresa = Verificar_empresa(request)
        
        # Obtener zonas activas con coordenadas guardadas
        zonas = ZONA.objects.filter(
            EP_NID_id=Empresa, 
            ZON_BHABILITADO=True
        ).exclude(
            ZON_CLATITUD1__isnull=True
        ).exclude(
            ZON_CLATITUD1__exact=''
        )
        
        posiciones = []
        for zona in zonas:
            # Construir array de coordenadas
            coordenadas = []
            
            if zona.ZON_CLATITUD1 and zona.ZON_CLONGITUD1:
                coordenadas.extend([float(zona.ZON_CLATITUD1), float(zona.ZON_CLONGITUD1)])
            
            if zona.ZON_CLATITUD2 and zona.ZON_CLONGITUD2:
                coordenadas.extend([float(zona.ZON_CLATITUD2), float(zona.ZON_CLONGITUD2)])
            
            if zona.ZON_CLATITUD3 and zona.ZON_CLONGITUD3:
                coordenadas.extend([float(zona.ZON_CLATITUD3), float(zona.ZON_CLONGITUD3)])
            
            if zona.ZON_CLATITUD4 and zona.ZON_CLONGITUD4:
                coordenadas.extend([float(zona.ZON_CLATITUD4), float(zona.ZON_CLONGITUD4)])
            
            # Solo incluir si tiene al menos 3 puntos (6 coordenadas)
            if len(coordenadas) >= 6:
                zona_data = [
                    zona.ZON_CNOMBRE,  # 0
                    zona.ZON_CLATITUD1, zona.ZON_CLONGITUD1,  # 1,2
                    zona.ZON_CLATITUD2, zona.ZON_CLONGITUD2,  # 3,4
                    zona.ZON_CLATITUD3, zona.ZON_CLONGITUD3,  # 5,6
                    zona.ZON_CLATITUD4, zona.ZON_CLONGITUD4,  # 7,8
                    "", "",  # 9,10
                    zona.ZON_CCOLOR or "#4caf50",  # 11
                    zona.ZON_CNOMBRE,  # 12
                    len(get_camiones_por_zona(zona.pk)),  # 13 - cupos ocupados (puedes calcularlo)
                    zona.ZON_NCANTIDADCUPOS or 0,  # 14
                    zona.pk  # 15
                ]
                
                posiciones.append({
                    'id_zona': zona.id,
                    'coordenadas': json.dumps(coordenadas),
                    'zona_data': zona_data
                })
        
        return JsonResponse({
            'success': True,
            'posiciones': posiciones
        })
        
    except Exception as e:
        print(f"Error al obtener posiciones: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def actualizar_coordenadas_zona(request):
    """
    Vista para actualizar las coordenadas de una zona existente
    """
    try:
        if not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No puedes realizar esta acción'
            })
        # Obtener datos del request
        id_zona = request.POST.get('id_zona')
        coordenadas = request.POST.get('coordenadas')
        
        # Validar datos requeridos
        if not id_zona:
            return JsonResponse({
                'success': False,
                'error': 'ID de zona requerido'
            })
        
        if not coordenadas:
            return JsonResponse({
                'success': False,
                'error': 'Coordenadas requeridas'
            })
        
        # Buscar la zona existente
        try:
            zona = ZONA.objects.get(id=id_zona, ZON_BHABILITADO=True)
        except ZONA.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Zona no encontrada o no está habilitada'
            })
        
        # Parsear las coordenadas
        try:
            coordenadas_list = json.loads(coordenadas)
            
            # Validar que tenemos coordenadas válidas
            if len(coordenadas_list) < 6:  # Al menos 3 puntos (6 coordenadas)
                return JsonResponse({
                    'success': False,
                    'error': 'Se requieren al menos 3 puntos (6 coordenadas)'
                })
            
            # Limitar a 4 puntos máximo (8 coordenadas)
            if len(coordenadas_list) > 8:
                coordenadas_list = coordenadas_list[:8]
            
            # Limpiar todas las coordenadas primero
            zona.ZON_CLATITUD1 = ""
            zona.ZON_CLONGITUD1 = ""
            zona.ZON_CLATITUD2 = ""
            zona.ZON_CLONGITUD2 = ""
            zona.ZON_CLATITUD3 = ""
            zona.ZON_CLONGITUD3 = ""
            zona.ZON_CLATITUD4 = ""
            zona.ZON_CLONGITUD4 = ""
            
            # Asignar las nuevas coordenadas
            if len(coordenadas_list) >= 2:
                zona.ZON_CLATITUD1 = str(coordenadas_list[0])
                zona.ZON_CLONGITUD1 = str(coordenadas_list[1])
            
            if len(coordenadas_list) >= 4:
                zona.ZON_CLATITUD2 = str(coordenadas_list[2])
                zona.ZON_CLONGITUD2 = str(coordenadas_list[3])
            
            if len(coordenadas_list) >= 6:
                zona.ZON_CLATITUD3 = str(coordenadas_list[4])
                zona.ZON_CLONGITUD3 = str(coordenadas_list[5])
            
            if len(coordenadas_list) >= 8:
                zona.ZON_CLATITUD4 = str(coordenadas_list[6])
                zona.ZON_CLONGITUD4 = str(coordenadas_list[7])
            
            # Guardar los cambios
            zona.save()
            
            return JsonResponse({
                'success': True,
                'mensaje': f'Coordenadas de la zona "{zona.ZON_CNOMBRE}" actualizadas correctamente',
                'zona_id': zona.id,
                'zona_nombre': zona.ZON_CNOMBRE,
                'coordenadas_actualizadas': coordenadas_list
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Formato de coordenadas inválido. Debe ser un JSON válido.'
            })
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': f'Error en los valores de coordenadas: {str(e)}'
            })
    
    except Exception as e:
        print(f"Error en actualizar_coordenadas_zona: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)

def obtener_coordenadas_zona(request):
    """
    Vista para obtener las coordenadas actuales de una zona específica
    """
    try:
        id_zona = request.GET.get('id_zona')
        
        if not id_zona:
            return JsonResponse({
                'success': False,
                'error': 'ID de zona requerido'
            })
        
        try:
            zona = ZONA.objects.get(id=id_zona, ZON_BHABILITADO=True)
        except ZONA.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Zona no encontrada'
            })
        
        # Construir array de coordenadas
        coordenadas = []
        
        if zona.ZON_CLATITUD1 and zona.ZON_CLONGITUD1:
            try:
                coordenadas.extend([float(zona.ZON_CLATITUD1), float(zona.ZON_CLONGITUD1)])
            except ValueError:
                pass
        
        if zona.ZON_CLATITUD2 and zona.ZON_CLONGITUD2:
            try:
                coordenadas.extend([float(zona.ZON_CLATITUD2), float(zona.ZON_CLONGITUD2)])
            except ValueError:
                pass
        
        if zona.ZON_CLATITUD3 and zona.ZON_CLONGITUD3:
            try:
                coordenadas.extend([float(zona.ZON_CLATITUD3), float(zona.ZON_CLONGITUD3)])
            except ValueError:
                pass
        
        if zona.ZON_CLATITUD4 and zona.ZON_CLONGITUD4:
            try:
                coordenadas.extend([float(zona.ZON_CLATITUD4), float(zona.ZON_CLONGITUD4)])
            except ValueError:
                pass
        
        return JsonResponse({
            'success': True,
            'zona_id': zona.id,
            'zona_nombre': zona.ZON_CNOMBRE,
            'coordenadas': coordenadas,
            'numero_puntos': len(coordenadas) // 2
        })
        
    except Exception as e:
        print(f"Error en obtener_coordenadas_zona: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)

def eliminar_zona(request):
    """
    Vista para eliminar una zona (soft delete - cambiar ZON_BHABILITADO a False)
    """
    try:
        if not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No puedes realizar esta acción'
            })
        # Obtener datos del request
        id_zona = request.POST.get('id_zona')
        
        # Validar datos requeridos
        if not id_zona:
            return JsonResponse({
                'success': False,
                'error': 'ID de zona requerido'
            })
        
        # Buscar la zona existente
        try:
            zona = ZONA.objects.get(id=id_zona, ZON_BHABILITADO=True)
        except ZONA.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Zona no encontrada o ya está deshabilitada'
            })
        
        camiones_x_zona = get_camiones_por_zona(id_zona)
        if camiones_x_zona:
            return JsonResponse({
                'success': False,
                'error': f'Dentro de la zona aun hay camiones'
            })
        
        # Realizar soft delete - marcar como deshabilitada
        zona_nombre = zona.ZON_CNOMBRE
        zona.ZON_BHABILITADO = False
        zona.save()
        
        # Log de la acción (opcional)
        print(f"Zona eliminada (soft delete): ID={id_zona}, Nombre={zona_nombre}")
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Zona "{zona_nombre}" eliminada correctamente',
            'zona_id': zona.id,
            'zona_nombre': zona_nombre
        })
    
    except Exception as e:
        print(f"Error en eliminar_zona: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)

def cambiar_imagen_plano(request):
    """
    Vista para cambiar la imagen del plano
    """
    try:
        import time
        logger = logging.getLogger(__name__)
        # Verificar que se haya enviado un archivo
        if 'imagen' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No se ha enviado ningún archivo de imagen'
            })
        
        archivo_imagen = request.FILES['imagen']
        
        # Validar tipo de archivo
        tipos_permitidos = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
        if archivo_imagen.content_type not in tipos_permitidos:
            return JsonResponse({
                'success': False,
                'error': 'Tipo de archivo no permitido. Use JPG, PNG o GIF.'
            })
        
        # Validar tamaño del archivo (10MB máximo)
        max_size = 10 * 1024 * 1024  # 10MB
        if archivo_imagen.size > max_size:
            return JsonResponse({
                'success': False,
                'error': 'El archivo es muy grande. Máximo 10MB permitido.'
            })
        
        # Validar que es una imagen válida usando PIL
        try:
            img = Image.open(archivo_imagen)
            img.verify()  # Verificar que es una imagen válida
            archivo_imagen.seek(0)  # Resetear el puntero del archivo
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': 'El archivo no es una imagen válida.'
            })
        
        # Hacer backup de la imagen anterior (opcional)
        try:
            ruta_anterior = os.path.join(settings.STATIC_ROOT or settings.BASE_DIR, 'static', 'assets/images/planoPlanta.png')
            if os.path.exists(ruta_anterior):
                backup_name = f"planoPlanta_backup_{uuid.uuid4()}.png"
                backup_dir = os.path.join(settings.STATIC_ROOT or settings.BASE_DIR, 'static', 'assets/images/backups')
                
                # Crear directorio de backups si no existe
                os.makedirs(backup_dir, exist_ok=True)
                
                ruta_backup = os.path.join(backup_dir, backup_name)
                
                # Copiar archivo anterior como backup
                import shutil
                shutil.copy2(ruta_anterior, ruta_backup)
                logger.info(f"Backup creado: {ruta_backup}")
                
        except Exception as e:
            logger.warning(f"No se pudo crear backup: {e}")
            # No fallar si no se puede hacer backup
        
        # Reemplazar la imagen principal
        try:
            ruta_principal = os.path.join(settings.STATIC_ROOT or settings.BASE_DIR, 'static', 'assets/images/planoPlanta.png')
            
            # Eliminar imagen anterior si existe
            if os.path.exists(ruta_principal):
                os.remove(ruta_principal)
            
            # Guardar nueva imagen directamente como planoPlanta.png
            with open(ruta_principal, 'wb+') as destino:
                for chunk in archivo_imagen.chunks():
                    destino.write(chunk)
            
            # Verificar que el archivo se guardó correctamente
            if not os.path.exists(ruta_principal):
                raise Exception("El archivo no se guardó correctamente")
                
        except Exception as e:
            logger.error(f"Error al reemplazar imagen principal: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Error al actualizar la imagen principal: {str(e)}'
            })
        
        # Obtener información de la nueva imagen
        try:
            img_info = Image.open(ruta_principal)
            ancho, alto = img_info.size
            
            info_imagen = {
                'ancho': ancho,
                'alto': alto,
                'tamaño_bytes': os.path.getsize(ruta_principal),
                'formato': img_info.format
            }
        except Exception as e:
            logger.warning(f"No se pudo obtener info de imagen: {e}")
            info_imagen = {}
        
        # URL pública de la nueva imagen CON TIMESTAMP para evitar caché
        timestamp = int(time.time())
        nueva_url = f"/static/assets/images/planoPlanta.png?v={timestamp}"
        
        logger.info(f"Imagen del plano cambiada exitosamente: {ruta_principal}")
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Imagen del plano cambiada exitosamente',
            'nueva_ruta': nueva_url,
            'info_imagen': info_imagen,
            'timestamp': timestamp  # Enviamos el timestamp para JavaScript
        })
        
    except Exception as e:
        logger.error(f"Error en cambiar_imagen_plano: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)

def cit_ruta_edit(request, pk):
    try:
        citacion = CITACION.objects.get(id = pk)
        id_ruta = request.POST.get('RUT_NID')
        
        if not id_ruta:
            messages.error(request, 'No se ha seleccionado una ruta')
            return redirect(f'/cit_listone/{pk}')
        
        try:
            ruta = RUTA.objects.get(id = id_ruta)
        except RUTA.DoesNotExist:
            messages.error(request, 'La ruta seleccionada no existe')
            return redirect(f'/cit_listone/{pk}')
        
        citacion.RUT_NID = ruta
        citacion.save()
        messages.success(request, 'Ruta asignada correctamente')       
        return redirect(f'/cit_listone/{pk}')
    except Exception as e:
        print(e)
        messages.error(request, f'Error, {str(e)}')
        return redirect(f'/cit_listone/{pk}')

def download_proforma_details(request, pk):
    try:
        proforma = PROFORMA.objects.get(id=pk)
        citaciones = CITACION_PROFORMA.objects.filter(PRO_NID=proforma)
        extras = EXTRA_PROFORMA.objects.filter(PRO_NID=proforma)
        
        # Crea un nuevo libro de trabajo de Excel
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)  # Eliminar la hoja por defecto
        
        # Procesar citaciones si existen
        if citaciones.exists():
            worksheet_citaciones = workbook.create_sheet(title="CITACIONES")
            
            # Definir columnas para citaciones
            columnas_citaciones = [
                "NUMERO PROFORMA", "NUMERO CITACION", "FECHA CITACION", 
                "TIPO DOCUMENTO", "NUMERO DOCUMENTO", "PROVEEDOR", 
                "CONDUCTOR", "CAMION", "RUTA", "TARIFA", "SUBTOTAL"
            ]
            
            # Escribir encabezados
            worksheet_citaciones.append(columnas_citaciones)
            
            # Escribir datos de citaciones
            for citacion in citaciones:
                ci = citacion.CI_NID
                
                # Obtener información relacionada
                proveedor = ci.PRO_NID.SN_CRAZONSOCIAL if ci.PRO_NID else ""
                conductor = f"{ci.CON_NID.CON_CNOMBRE} {ci.CON_NID.CON_CAPELLIDO}" if ci.CON_NID else ""
                camion = ci.CA_NID.CAM_CPATENTE if ci.CA_NID else ""
                ruta = ci.RUT_NID.RUT_CNOMBRE if ci.RUT_NID else ""
                tarifa = ci.TAR_NID.TAR_CNOMBRETARIFA if ci.TAR_NID else ""
                
                # Formatear fecha
                fecha_citacion = ci.CI_FFECHAREGISTRO.strftime('%d/%m/%Y') if ci.CI_FFECHAREGISTRO else ""
                
                fila = [
                    pk,
                    ci.pk,
                    fecha_citacion,
                    ci.CI_CTIPODOCUMENTO if ci.CI_CTIPODOCUMENTO else "",
                    ci.CI_CNUMERODOCUMENTO if ci.CI_CNUMERODOCUMENTO else "",
                    proveedor,
                    conductor,
                    camion,
                    ruta,
                    tarifa,
                    float(citacion.CIP_NSUBTOTAL)
                ]
                
                worksheet_citaciones.append(fila)
        
        # Procesar extras si existen
        if extras.exists():
            worksheet_extras = workbook.create_sheet(title="EXTRAS")
            
            # Definir columnas para extras
            columnas_extras = [
                "NUMERO PROFORMA", "NUMERO CITACION","EXTRA", "DESCRIPCION", 
                "VALOR", "ES INGRESO", "NUMERO CITACION"
            ]
            
            # Escribir encabezados
            worksheet_extras.append(columnas_extras)
            
            # Escribir datos de extras
            for extra in extras:
                cie = extra.CIE_NID
                ext = cie.EXT_NID
                
                es_ingreso = "Sí" if extra.EPR_BINGRESO else "No"
                
                fila = [
                    pk,
                    cie.CI_NID.pk,
                    ext.EXT_CNOMBRE,
                    ext.EXT_CDESCRIPCION if ext.EXT_CDESCRIPCION else "",
                    float(extra.EPR_NVALOR),
                    es_ingreso,
                    cie.CI_NID.pk
                ]
                
                worksheet_extras.append(fila)
        
        # Verificar que al menos se creó una hoja
        if len(workbook.sheetnames) == 0:
            messages.warning(request, 'No hay datos para exportar')
            return redirect('/')
        
        # Preparar respuesta HTTP con el archivo Excel
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename=proforma_{pk}_detalle.xlsx'
        
        # Guardar el libro en la respuesta
        workbook.save(response)
        
        return response
        
    except PROFORMA.DoesNotExist:
        messages.error(request, 'La proforma no existe')
        return redirect('/')
    except Exception as e:
        print(e)
        messages.error(request, f'Error: {str(e)}')
        return redirect('/')

def get_flete_empresa(request):
    try:
        id_empresa = request.GET.get('id_empresa')
        empresa = EMPRESA.objects.get(id=id_empresa)
        
        # Corrección: values_list con flat=True, o values sin flat
        fletes = list(PARAMETRO.objects.filter(
            PM_CGRUPO='TIPO_FLETE', 
            PM_NVALOR1=id_empresa
        ).values_list('PM_CDESCRIPCION', flat=True))
        
        return JsonResponse({
            'success': True,
            'fletes': fletes
        })
        
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'error': str(e)  # Cambié 'Error' a 'error' para consistencia
        })

def filter_proforma_inicio(request):
    try:
        Empresa = Verificar_empresa(request)
        fecha_desde = request.GET.get('fecha_desde')
        fecha_hasta = request.GET.get('fecha_hasta')
        today = datetime.now()
        
        if not fecha_desde:
            fecha_desde = today - timedelta(days=7)
        else:
            fecha_desde = datetime.strptime(fecha_desde, '%Y-%m-%d')  # Especifica el formato

        if not fecha_hasta:
            fecha_hasta = today
        else:
            fecha_hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d')  # Especifica el formato
        
        proformas_por_socionegocio = PROFORMA.objects.filter(
            EP_NID_id=Empresa,
            PRO_FFECHAEMISION__date__range=[fecha_desde, fecha_hasta],  # Corregí las variables
            SN_NID__isnull=False
        ).values(
            'SN_NID__SN_CRAZONSOCIAL',
            'SN_NID'
        ).annotate(
            cantidad_proformas=Count('id')
        ).order_by('-cantidad_proformas')
        
        # Convertir QuerySet a lista de diccionarios
        proformas_list = list(proformas_por_socionegocio)
        
        return JsonResponse({
            "success": True,
            "proformas_por_socionegocio": proformas_list
        })
    except Exception as e:
        print(e)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def parametro_list(request):
    try:
        search = request.GET.get('search', '')
        grupo = request.GET.get('grupo', '')
        
        parametros = PARAMETRO.objects.all()
        
        # Filtros
        if search:
            parametros = parametros.filter(
                Q(PM_CCODIGO__icontains=search) |
                Q(PM_CDESCRIPCION__icontains=search) |
                Q(PM_CGRUPO__icontains=search)
            )
        
        if grupo:
            parametros = parametros.filter(PM_CGRUPO=grupo)
        
        parametros = parametros.order_by('PM_CGRUPO', 'PM_CCODIGO')
        
        # Obtener grupos únicos para el filtro
        grupos = PARAMETRO.objects.values_list('PM_CGRUPO', flat=True).distinct().order_by('PM_CGRUPO')
        
        # Paginación
        page = request.GET.get('page', 1)
        paginator = Paginator(parametros, 50)
        parametros_paginados = paginator.page(page)
        
        context = {
            'parametros': parametros_paginados,
            'grupos': grupos,
            'search': search,
            'grupo_selected': grupo
        }
        
        return render(request, 'home/PARAMETRO/parametro_list.html', context)
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al listar parámetros: {str(e)}')
        return redirect('/')

# CREAR
def parametro_create(request):
    try:
        if request.method == 'POST':
            grupo = request.POST.get('PM_CGRUPO')
            codigo = request.POST.get('PM_CCODIGO')
            descripcion = request.POST.get('PM_CDESCRIPCION')
            valor1 = request.POST.get('PM_CVALOR1')
            valor2 = request.POST.get('PM_CVALOR2', '')
            valor3 = request.POST.get('PM_CVALOR3', '')
            nvalor1 = request.POST.get('PM_NVALOR1', None)
            nvalor2 = request.POST.get('PM_NVALOR2', None)
            nvalor3 = request.POST.get('PM_NVALOR3', None)
            
            # Validar campos obligatorios
            if not grupo or not codigo or not descripcion or not valor1:
                messages.error(request, 'Los campos Grupo, Código, Descripción y Valor 1 son obligatorios')
                return redirect('parametro_create')
            
            # Verificar si ya existe
            if PARAMETRO.objects.filter(PM_CGRUPO=grupo, PM_CCODIGO=codigo).exists():
                messages.error(request, 'Ya existe un parámetro con ese Grupo y Código')
                return redirect('parametro_create')
            
            # Crear parámetro
            parametro = PARAMETRO.objects.create(
                PM_CGRUPO=grupo,
                PM_CCODIGO=codigo,
                PM_CDESCRIPCION=descripcion,
                PM_CVALOR1=valor1,
                PM_CVALOR2=valor2 if valor2 else None,
                PM_CVALOR3=valor3 if valor3 else None,
                PM_NVALOR1=nvalor1 if nvalor1 else None,
                PM_NVALOR2=nvalor2 if nvalor2 else None,
                PM_NVALOR3=nvalor3 if nvalor3 else None
            )
            
            messages.success(request, 'Parámetro creado exitosamente')
            return redirect('parametro_list')
        
        # Obtener grupos existentes para sugerencias
        grupos = PARAMETRO.objects.values_list('PM_CGRUPO', flat=True).distinct().order_by('PM_CGRUPO')
        
        context = {
            'grupos': grupos
        }
        
        return render(request, 'home/PARAMETRO/parametro_form.html', context)
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al crear parámetro: {str(e)}')
        return redirect('parametro_list')

# EDITAR
def parametro_update(request, pk):
    try:
        parametro = get_object_or_404(PARAMETRO, pk=pk)
        
        if request.method == 'POST':
            descripcion = request.POST.get('PM_CDESCRIPCION')
            valor1 = request.POST.get('PM_CVALOR1')
            valor2 = request.POST.get('PM_CVALOR2', '')
            valor3 = request.POST.get('PM_CVALOR3', '')
            nvalor1 = request.POST.get('PM_NVALOR1', None)
            nvalor2 = request.POST.get('PM_NVALOR2', None)
            nvalor3 = request.POST.get('PM_NVALOR3', None)
            
            # Validar campos obligatorios
            if not descripcion or not valor1:
                messages.error(request, 'Los campos Descripción y Valor 1 son obligatorios')
                return redirect('parametro_update', pk=pk)
            
            # Actualizar parámetro
            parametro.PM_CDESCRIPCION = descripcion
            parametro.PM_CVALOR1 = valor1
            parametro.PM_CVALOR2 = valor2 if valor2 else None
            parametro.PM_CVALOR3 = valor3 if valor3 else None
            parametro.PM_NVALOR1 = nvalor1 if nvalor1 else None
            parametro.PM_NVALOR2 = nvalor2 if nvalor2 else None
            parametro.PM_NVALOR3 = nvalor3 if nvalor3 else None
            parametro.save()
            
            messages.success(request, 'Parámetro actualizado exitosamente')
            return redirect('parametro_list')
        
        context = {
            'parametro': parametro,
            'is_update': True
        }
        
        return render(request, 'home/PARAMETRO/parametro_form.html', context)
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al editar parámetro: {str(e)}')
        return redirect('parametro_list')

# ELIMINAR
def parametro_delete(request, pk):
    try:
        parametro = get_object_or_404(PARAMETRO, pk=pk)
        
        if request.method == 'POST':
            grupo = parametro.PM_CGRUPO
            codigo = parametro.PM_CCODIGO
            parametro.delete()
            
            messages.success(request, f'Parámetro {grupo} - {codigo} eliminado exitosamente')
            return redirect('parametro_list')
        
        context = {
            'parametro': parametro
        }
        
        return render(request, 'parametros/parametro_confirm_delete.html', context)
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al eliminar parámetro: {str(e)}')
        return redirect('parametro_list')


def info_proveedor(request):
    """
    Vista AJAX para obtener información del proveedor
    """
    proveedor_id = request.GET.get('proveedor', None)
    
    if not proveedor_id:
        return JsonResponse({'error': 'No se proporcionó ID de proveedor'}, status=400)
    
    try:
        proveedor = SOCIONEGOCIO.objects.get(pk=proveedor_id)
        
        data = {
            'razon_social': proveedor.SN_CRAZONSOCIAL,
            'rut': proveedor.SN_CRUT,
            'direccion': proveedor.SN_CDIRECCION or '',
            'telefono': proveedor.SN_CTELEFONO or '',
            'email': proveedor.SN_CEMAIL or '',
            'contacto': proveedor.SN_CCONTACTO or ''
        }
        
        return JsonResponse(data)
        
    except SOCIONEGOCIO.DoesNotExist:
        return JsonResponse({'error': 'Proveedor no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def get_tipos_items(request):
    """
    Vista AJAX para obtener los tipos de items según la empresa
    Los tipos de items están en PARAMETRO donde PM_NVALOR1 = ID de empresa
    """
    empresa_id = request.GET.get('empresa', None)
    
    if not empresa_id:
        return JsonResponse({'error': 'No se proporcionó ID de empresa'}, status=400)
    
    try:
        # Convertir empresa_id a Decimal para comparar con PM_NVALOR1
        empresa_id_decimal = Decimal(empresa_id)
        
        # Obtener tipos de items para la empresa
        # Ajusta 'TIPO_ITEM' según el nombre real de tu grupo de parámetros
        tipos_items = PARAMETRO.objects.filter(
            PM_CGRUPO='TIPO_ITEM',  # AJUSTA ESTE VALOR SEGÚN TU CONFIGURACIÓN
            PM_NVALOR1=empresa_id_decimal
        ).values('PM_CDESCRIPCION')
        
        # Formatear lista de tipos de items
        lista_tipos = [
            {
                'id': tipo['PM_CDESCRIPCION'],
                'nombre': tipo['PM_CDESCRIPCION']
            }
            for tipo in tipos_items
        ]
        
        data = {
            'tipos_items': lista_tipos
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def PROFORMA_PDF(request, pk):
    """
    Vista para generar PDF de la proforma usando Python
    """
    try:
        if not WEASYPRINT_AVAILABLE:
            messages.error(request, 'La librería weasyprint no está instalada. Por favor instálela con: pip install weasyprint')
            return redirect(f'/proforma_listone/{pk}')
        
        proforma = PROFORMA.objects.get(id=pk)
        proveedor = proforma.SN_NID
        documentos = DOCUMENTO_PROFORMA.objects.filter(PRO_NID=proforma)
        
        # Verificar que proveedor y EP_NID existan antes de usarlos
        if not proveedor or not proforma.EP_NID:
            messages.error(request, 'Error: La proforma no tiene proveedor o empresa asociada')
            return redirect(f'/proforma_listone/{pk}')
        
        listado_citaciones = get_list_citaciones_xproveedor(proveedor.pk, proforma.EP_NID.pk)
        
        # Modificar la consulta de citaciones_proforma para incluir el valor_campo_38
        citaciones_proforma = CITACION_PROFORMA.objects.filter(PRO_NID=proforma).annotate(
            valor_campo_38=Subquery(
                DATO_OPERACION.objects.filter(
                    CI_NID=OuterRef('CI_NID'),
                    CAMP_NID_id=38
                ).values('DO_CVALOR')[:1]
            )
        )

        extras_proforma_ingreso = EXTRA_PROFORMA.objects.filter(PRO_NID=proforma, EPR_BINGRESO=True, EPR_BHABILITADO=True)
        extras_proforma_descuento = EXTRA_PROFORMA.objects.filter(PRO_NID=proforma, EPR_BINGRESO=False, EPR_BHABILITADO=True)
        
        # Calcular totales usando la misma estructura que PROFORMA_LISTONE
        total_extras_ingreso = 0
        total_extras_descuento = 0
        
        # Calcular totales de extras solo con los habilitados
        for extra_ingreso in extras_proforma_ingreso:
            total_extras_ingreso += extra_ingreso.EPR_NVALOR
            
        for extra_descuento in extras_proforma_descuento:
            total_extras_descuento += extra_descuento.EPR_NVALOR
        
        total_tarifas = 0
        for citacion_proforma in citaciones_proforma:
            citacion = citacion_proforma.CI_NID
            total_tarifas += citacion.CI_NVALORTARIFA if citacion.CI_NVALORTARIFA is not None else 0
        
        # Obtener tipos_extras usando la misma estructura que PROFORMA_LISTONE
        tipos_extras_ingreso = get_list_extras_ingreso(proforma.id)
        tipos_extras_descuento = get_list_extras_descuento(proforma.id)
        
        # Contexto para el template PDF - misma estructura que PROFORMA_LISTONE
        ctx = {
            'proforma': proforma,
            'citaciones_proforma': citaciones_proforma,
            'extras_proforma_ingreso': extras_proforma_ingreso,
            'extras_proforma_descuento': extras_proforma_descuento,
            'total_extras_ingreso': total_extras_ingreso,
            'total_extras_descuento': total_extras_descuento,
            'tipos_extras_ingreso': tipos_extras_ingreso,
            'tipos_extras_descuento': tipos_extras_descuento,
            'total_tarifas': total_tarifas,
        }
        
        # Renderizar el template HTML
        html = render_to_string('home/PROFORMA/proforma_pdf.html', ctx, request=request)
        
        # Crear respuesta PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f'Proforma_{proforma.pk}_{datetime.now().strftime("%Y-%m-%d")}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Convertir HTML a PDF usando WeasyPrint
        try:
            # Configurar base_url para recursos estáticos
            base_url = request.build_absolute_uri('/')
            
            # Generar PDF con WeasyPrint
            HTML(string=html, base_url=base_url).write_pdf(
                response,
                stylesheets=[CSS(string='''
                    @page {
                        size: A4 landscape;
                        margin: 1cm;
                    }
                ''')]
            )
        except Exception as e:
            print(f"Error al generar PDF con WeasyPrint: {e}")
            messages.error(request, f'Error al generar el PDF: {str(e)}')
            return redirect(f'/proforma_listone/{pk}')
        
        return response
        
    except Exception as e:
        print(e)
        messages.error(request, f'Error al generar PDF: {str(e)}')
        return redirect(f'/proforma_listone/{pk}')



##########################################################################
# PESAJE
##########################################################################
# def buscar_citacion_por_patente(patente):
#     """
#     Busca en la base de datos citaciones.db el registro de la tabla citaciones cuyo campo cam_cpatente coincide con la patente (ignorando mayúsculas/minúsculas).
#     Devuelve el registro completo si lo encuentra; en caso contrario, devuelve False.
#     """
#     import sqlite3

#     db_path = r'C:\inetpub\wwwroot\pesaje_api\citaciones.db'
#     try:
#         conn = sqlite3.connect(db_path)
#         conn.row_factory = sqlite3.Row  # Para obtener resultados como diccionarios
#         cursor = conn.cursor()

#         # Buscar usando upper en ambos lados para evitar problemas de case
#         # Ordenar por fecha descendente (más reciente primero) y luego por tiempo
#         query = """
#             SELECT * FROM citaciones 
#             WHERE UPPER(cam_cpatente) = UPPER(?)
#             ORDER BY fecha DESC, tiempo DESC
#             LIMIT 1
#         """
#         cursor.execute(query, (patente,))
#         row = cursor.fetchone()
#         conn.close()

#         if row:
#             return dict(row)
#         else:
#             return False
#     except Exception as e:
#         print(f"Error al buscar citación: {e}")
#         return False

def buscar_patente_ajax(request):
    """
    Vista AJAX para buscar patente y retornar los datos de pesaje.
    """
    if request.method == 'GET':
        patente = request.GET.get('patente', '').strip()
        
        if not patente:
            return JsonResponse({
                'success': False,
                'message': 'Por favor ingrese una patente'
            })
        
        resultado = obtener_citacion_por_patente(patente)
        
        if resultado:
            # Convertir el diccionario a un formato JSON serializable
            datos = {}
            for key, value in resultado.items():
                # Convertir tipos que no son serializables por defecto
                if isinstance(value, (int, float, str, bool, type(None))):
                    datos[key] = value
                else:
                    datos[key] = str(value)
            
            return JsonResponse({
                'success': True,
                'data': datos
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No hay pesos registrados para la patente'
            })
    
    return JsonResponse({
        'success': False,
        'message': 'Método no permitido'
    })




##################################
# PESAJE
##################################
import sqlite3

def obtener_citacion_por_patente(patente):
    """
    Obtiene un registro completo de la tabla citaciones desde una base de datos sqlite.

    Args:
        patente (str): La patente del camión a consultar.

    Returns:
        dict: Un diccionario con los datos de la citación si existe, None en caso contrario.
    """
    db_path = r'C:\inetpub\wwwroot\pesaje_api\citaciones.db'
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Seleccionar todos los campos de la tabla citaciones
        cursor.execute("SELECT * FROM citaciones WHERE cam_cpatente = ? order by fecha desc, tiempo desc limit 1", (patente,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        else:
            return None
    except Exception as e:
        print(f"Error al obtener la citación: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

def ajax_obtener_pesaje(request):
    """
    Vista AJAX para obtener el peso desde la base de datos de pesaje.
    Calcula el campo 'peso': si con_npeso_salida es NULL o 0, usa con_npeso_entrada, 
    de lo contrario usa con_npeso_salida.
    """
    try:
        patente = request.GET.get('patente')
        if not patente:
            return JsonResponse({'valid': False, 'msg': 'Patente no proporcionada'})
        
        datos_pesaje = obtener_citacion_por_patente(patente)
        
        if datos_pesaje:
            peso_salida = datos_pesaje.get('con_npeso_nsalida') or datos_pesaje.get('con_npeso_salida')
            peso_entrada = datos_pesaje.get('con_npeso_entrada')
            
            # Calcular el peso según la lógica: si peso_salida es NULL o 0, usar peso_entrada
            try:
                if peso_salida is not None:
                    peso_salida_float = float(peso_salida) if isinstance(peso_salida, str) else float(peso_salida)
                    if peso_salida_float != 0:
                        peso = peso_salida
                    else:
                        peso = peso_entrada
                else:
                    peso = peso_entrada
            except (ValueError, TypeError):
                peso = peso_entrada
            
            if peso is not None:
                return JsonResponse({
                    'valid': True, 
                    'peso_entrada': peso,
                    'datos': datos_pesaje
                })
            else:
                return JsonResponse({
                    'valid': False, 
                    'msg': 'No se encontraron datos de peso para esta patente'
                })
        else:
            return JsonResponse({
                'valid': False, 
                'msg': 'No se encontraron datos de pesaje para esta patente'
            })
    except Exception as e:
        print(f"Error en ajax_obtener_pesaje: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'valid': False, 'msg': f'Error al obtener el pesaje: {str(e)}'})

def ajax_actualizar_peso_dato_operacion(request):
    """
    Vista AJAX para actualizar el campo DO_NPESO en la tabla DATO_OPERACION.
    Usa SOLO el id del campo principal (CAMP_NID) como llave, junto con el id de la citación.
    """
    try:
        campo_id = request.POST.get('campo_id')
        citacion_id = request.POST.get('citacion_id')
        peso = request.POST.get('peso')
        
        print(f"DEBUG ajax_actualizar_peso_dato_operacion - campo_id: {campo_id}, citacion_id: {citacion_id}, peso: {peso}")
        
        if not campo_id or not peso:
            return JsonResponse({
                'valid': False, 
                'msg': 'Faltan parámetros requeridos (campo_id, peso)'
            })
        
        # Validar que el peso no sea vacío, nulo o cero
        try:
            peso_float = float(peso)
            if peso_float == 0:
                return JsonResponse({
                    'valid': False, 
                    'msg': 'El peso no puede ser cero'
                })
        except (ValueError, TypeError):
            return JsonResponse({
                'valid': False, 
                'msg': 'El peso debe ser un número válido'
            })
        
        # Convertir campo_id a entero
        try:
            campo_id_int = int(campo_id)
        except (ValueError, TypeError):
            return JsonResponse({
                'valid': False, 
                'msg': 'El campo_id debe ser un número válido'
            })
        
        # Buscar el registro en DATO_OPERACION usando CAMP_NID_id (ID del campo principal) como llave
        # Si hay citacion_id, también lo usamos para filtrar más específicamente
        try:
            if citacion_id:
                try:
                    citacion_id_int = int(citacion_id)
                    dato_operacion = DATO_OPERACION.objects.filter(
                        CAMP_NID_id=campo_id_int,
                        CI_NID_id=citacion_id_int
                    ).first()
                except (ValueError, TypeError):
                    dato_operacion = DATO_OPERACION.objects.filter(
                        CAMP_NID_id=campo_id_int
                    ).first()
            else:
                # Si no hay citacion_id, buscar solo por CAMP_NID_id (ID del campo principal)
                dato_operacion = DATO_OPERACION.objects.filter(
                    CAMP_NID_id=campo_id_int
                ).first()
            
            print(f"DEBUG ajax_actualizar_peso_dato_operacion - Registro encontrado: {dato_operacion}")
            
            if dato_operacion:
                # Actualizar el campo DO_NPESO
                dato_operacion.DO_NPESO = int(peso_float)
                dato_operacion.save()
                
                print(f"DEBUG ajax_actualizar_peso_dato_operacion - Peso actualizado: {dato_operacion.DO_NPESO}")
                
                return JsonResponse({
                    'valid': True, 
                    'msg': 'Peso actualizado correctamente',
                    'peso_actualizado': dato_operacion.DO_NPESO
                })
            else:
                # Si no se encuentra, intentar buscar todos los registros con ese CAMP_NID_id para debug
                registros_existentes = DATO_OPERACION.objects.filter(CAMP_NID_id=campo_id_int).count()
                print(f"DEBUG ajax_actualizar_peso_dato_operacion - No se encontró registro. Registros con CAMP_NID_id {campo_id_int}: {registros_existentes}")
                
                return JsonResponse({
                    'valid': False, 
                    'msg': f'No se encontró el registro en DATO_OPERACION para el campo_id {campo_id_int}' + (f' y citacion_id {citacion_id}' if citacion_id else '')
                })
        except Exception as e:
            print(f"Error al actualizar DATO_OPERACION: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'valid': False, 
                'msg': f'Error al actualizar el peso: {str(e)}'
            })
    except Exception as e:
        print(f"Error en ajax_actualizar_peso_dato_operacion: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'valid': False, 'msg': f'Error al actualizar el peso: {str(e)}'})


