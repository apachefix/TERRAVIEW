# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.urls import path, re_path
from apps.home import views
from apps.home import tarifa_global_views
from apps.home import tarifa_ajuste_views
from apps.home.api_calidad import resultado_calidad_integracion_api
from django.contrib.auth.views import login_required
from django.conf import settings
from django.conf.urls.static import static




urlpatterns = [

    path(
        'api/integraciones/calidad/resultados/',
        resultado_calidad_integracion_api,
        name='api_integracion_calidad_resultados',
    ),

    # The home page
    path('dashboard_grafico/', login_required(views.DASHBOARD_GRAFICO), name="dashboard_grafico"),
    path('', login_required(views.inicio), name='home'),
    path('cambio_contraseña/', login_required(views.CambioContrasena.as_view()), name="cambio_contraseña"),
    #########################################
    ########         INICIO         ########
    #########################################
    path('inicio/', login_required(views.inicio), name='inicio'),
    path('obtener_detalles_citacion/<int:citacion_id>/', views.obtener_detalles_citacion, name='obtener_detalles_citacion'),
    path('get_detalle_citaciones/<int:id_citacion>/', views.get_detalle_citaciones, name='get_detalle_citaciones'),

    #########################################
    ########         SAP             ########
    #########################################
    path('api/sap/producto/', login_required(views.API_SAP_PRODUCTO), name='api_sap_producto'),
    path('api/sap/productos/', login_required(views.API_SAP_PRODUCTOS), name='api_sap_productos'),
    path('api/sap/recepcion-transferencia/estanque/', login_required(views.API_SAP_RECEPCION_TRANSFERENCIA_ESTANQUE), name='api_sap_recepcion_transferencia_estanque'),
    path('api/sap/clientes/', login_required(views.API_SAP_CLIENTES), name='api_sap_clientes'),
    path('api/sap/proveedores/', login_required(views.API_SAP_PROVEEDORES), name='api_sap_proveedores'),
    path('api/sap/pedido/', login_required(views.API_SAP_PEDIDO), name='api_sap_pedido'),
    path('api/sap/pedidos-por-producto/', login_required(views.API_SAP_PEDIDOS_POR_PRODUCTO), name='api_sap_pedidos_por_producto'),
    path('api/sap/pedido-detalle/', login_required(views.API_SAP_PEDIDO_DETALLE), name='api_sap_pedido_detalle'),
    path('api/sap/despacho-acuerdos/', login_required(views.API_SAP_DESPACHO_ACUERDOS), name='api_sap_despacho_acuerdos'),
    path('api/sap/despacho-stock/', login_required(views.API_SAP_DESPACHO_STOCK), name='api_sap_despacho_stock'),
    path('api/sap/despacho/estanques/', login_required(views.API_SAP_DESPACHO_ESTANQUES), name='api_sap_despacho_estanques'),
    path('api/sap/despacho/lotes/', login_required(views.API_SAP_DESPACHO_LOTES), name='api_sap_despacho_lotes'),
    path('sap/despacho/<int:pk>/crear-draft/', login_required(views.SAP_DESPACHO_CREAR_DRAFT), name='sap_despacho_crear_draft'),
    path('buscar-opor-codigo/', login_required(views.BUSCAR_OPOR_POR_CODIGO), name='buscar_opor_codigo'),
    path('buscar-opor-pedido/', login_required(views.BUSCAR_OPOR_POR_PEDIDO), name='buscar_opor_pedido'),

    #########################################
    ########    PLANIFICACIÓN CREAR    ######
    #########################################
    path('crear-planificacion-citacion/', login_required(views.CREAR_PLANIFICACION_CITACION), name='crear_planificacion_citacion'),
    path('crear-citacion-no-planificada/<int:pk>/', login_required(views.CREAR_CITACION_NO_PLANIFICADA), name='crear_citacion_no_planificada'),
    path('solicitar-camion-no-planificado/', login_required(views.SOLICITAR_CAMION_NO_PLANIFICADO), name='solicitar_camion_no_planificado'),
    path('rechazar-camion-no-planificado/', login_required(views.RECHAZAR_CAMION_NO_PLANIFICADO), name='rechazar_camion_no_planificado'),
    path('notificar-camion-no-planificado/', login_required(views.NOTIFICAR_CAMION_NO_PLANIFICADO), name='notificar_camion_no_planificado'),
    path('camiones-patio/registrar/', login_required(views.CAMIONES_PATIO_REGISTRAR), name='camiones_patio_registrar'),
    path('camiones-patio/consultar-citacion-patente/', login_required(views.consultar_citacion_patente_patio), name='camiones_patio_consultar_citacion_patente'),
    path('camiones-patio/control/', login_required(views.CAMIONES_PATIO_CONTROL), name='camiones_patio_control'),
    path('camiones-patio/control/data/', login_required(views.CAMIONES_PATIO_CONTROL_DATA), name='camiones_patio_control_data'),
    path('camiones-patio/', login_required(views.CAMIONES_PATIO_LIST), name='camiones_patio_list'),
    path('camiones-patio/mapa/', login_required(views.CAMIONES_PATIO_MAPA), name='camiones_patio_mapa'),
    path('camiones-patio/pendientes-citacion/<int:pk>/', login_required(views.CAMIONES_PATIO_PENDIENTES_CITACION), name='camiones_patio_pendientes_citacion'),
    path('camiones-patio/<int:pk>/detalle/', login_required(views.CAMION_PATIO_DETALLE), name='camion_patio_detalle'),
    path('camiones-patio/<int:pk>/no-planificado/', login_required(views.CAMION_PATIO_NO_PLANIFICADO_SOLICITAR), name='camion_patio_no_planificado_solicitar'),
    path('camiones-patio/no-planificado/<int:pk>/revisar/', login_required(views.CAMION_PATIO_NO_PLANIFICADO_REVISAR), name='camion_patio_no_planificado_revisar'),
    path('camiones-patio/no-planificado/<int:pk>/aprobar/', login_required(views.CAMION_PATIO_NO_PLANIFICADO_APROBAR), name='camion_patio_no_planificado_aprobar'),
    path('camiones-patio/no-planificado/<int:pk>/rechazar/', login_required(views.CAMION_PATIO_NO_PLANIFICADO_RECHAZAR), name='camion_patio_no_planificado_rechazar'),
    path('camiones-patio/no-planificado/<int:pk>/reintentar-teams/', login_required(views.CAMION_PATIO_NO_PLANIFICADO_REINTENTAR_TEAMS), name='camion_patio_no_planificado_reintentar_teams'),
    path('camiones-patio/<int:pk>/actualizar/', login_required(views.CAMION_PATIO_ACTUALIZAR), name='camion_patio_actualizar'),
    path('camiones-patio/<int:pk>/adjunto/', login_required(views.CAMION_PATIO_ADJUNTO_GUARDAR), name='camion_patio_adjunto_guardar'),
    path('camiones-patio/<int:pk>/retirar/', login_required(views.CAMION_PATIO_RETIRAR), name='camion_patio_retirar'),
    path('camiones-patio/adjunto/<int:pk>/', login_required(views.CAMION_PATIO_ADJUNTO_VER), name='camion_patio_adjunto_ver'),
    path('camiones-patio/adjunto/<int:pk>/eliminar/', login_required(views.CAMION_PATIO_ADJUNTO_ELIMINAR), name='camion_patio_adjunto_eliminar'),
    path('camiones-patio/<int:pk>/asociar/', login_required(views.CAMION_PATIO_ASOCIAR), name='camion_patio_asociar'),
    path('pla-citacion-ingreso-camion/<int:pk>/', login_required(views.PLANIFICACION_CITACION_INGRESO_CAMION), name='pla_citacion_ingreso_camion'),
    path('pla-citacion-avanzar-asistente/<int:pk>/', login_required(views.AVANZAR_INGRESO_CAMION_ASISTENTE), name='pla_citacion_avanzar_asistente'),
    path('pla-citacion-revision-asistente/<int:pk>/', login_required(views.PLANIFICACION_CITACION_REVISION_ASISTENTE), name='pla_citacion_revision_asistente'),
    path('pla-citacion-editar-ingreso-asistente/<int:pk>/', login_required(views.PLANIFICACION_CITACION_EDITAR_INGRESO_ASISTENTE), name='pla_citacion_editar_ingreso_asistente'),
    path('pla-citacion-guardar-ruta-asistente/<int:pk>/', login_required(views.GUARDAR_RUTA_CAMION_ASISTENTE), name='pla_citacion_guardar_ruta_asistente'),
    path('pla-citacion-guardar-documento-despacho-sbh/<int:pk>/', login_required(views.GUARDAR_DATOS_DOCUMENTO_DESPACHO_SBH), name='pla_citacion_guardar_documento_despacho_sbh'),
    path('pla-citacion-aprobar-asistente/<int:pk>/', login_required(views.APROBAR_CAMION_ASISTENTE), name='pla_citacion_aprobar_asistente'),
    path('pla-citacion-devolver-guardia/<int:pk>/', login_required(views.DEVOLVER_CAMION_GUARDIA), name='pla_citacion_devolver_guardia'),
    path('pla-citacion-enviar-guardia-porteria/<int:pk>/', login_required(views.ENVIAR_GUARDIA_PORTERIA), name='pla_citacion_enviar_guardia_porteria'),
    path('pla-citacion-resumen/<int:pk>/', login_required(views.PLANIFICACION_CITACION_RESUMEN), name='pla_citacion_resumen'),
    path('pla-citacion-estanque/<int:pk>/', login_required(views.PLANIFICACION_CITACION_ESTANQUE), name='pla_citacion_estanque'),
    path('pla-citacion-borrador-sap-peso-guia/<int:pk>/', login_required(views.PLANIFICACION_BORRADOR_SAP_PESO_GUIA), name='pla_citacion_borrador_sap_peso_guia'),
    path('pla-citacion-borrador-sap-peso-guia/<int:pk>/enviar/', login_required(views.PLANIFICACION_BORRADOR_SAP_PESO_GUIA_ENVIAR), name='pla_citacion_borrador_sap_peso_guia_enviar'),
    path('pla-citacion-estanque-avanzar/<int:pk>/', login_required(views.AVANZAR_ESTANQUE_SIGUIENTE_ETAPA), name='pla_citacion_estanque_avanzar'),
    path('ajax-rutas-transportista-revision/', login_required(views.AJAX_RUTAS_TRANSPORTISTA_REVISION), name='ajax_rutas_transportista_revision'),
    path('ajax-rutas-transportista-planificacion/', login_required(views.AJAX_RUTAS_TRANSPORTISTA_PLANIFICACION), name='ajax_rutas_transportista_planificacion'),
    path('ajax-rutas-transportista-despacho-terramar/', login_required(views.AJAX_RUTAS_TRANSPORTISTA_DESPACHO_TERRAMAR), name='ajax_rutas_transportista_despacho_terramar'),
        #########################################
    ########         EMPRESA     NUEVO    ########
    #########################################
    path('emp_listall/', login_required(views.EMPRESA_LISTALL), name='emp_listall'),
    path('emp_addone/', login_required(views.EMPRESA_ADDONE), name='emp_addone'),
    path('emp_update/<int:pk>', login_required(views.EMPRESA_UPDATE), name='emp_update'),

    # Selección de empresa activa para usuarios multiempresa
    path('seleccionar_empresa/', login_required(views.seleccionar_empresa), name='seleccionar_empresa'),
    path('cambiar_empresa/<int:empresa_id>/', login_required(views.cambiar_empresa), name='cambiar_empresa'),
    #########################################
    ########       CONDUCTOR         ########
    #########################################
    path('con_listall/', login_required(views.CONDUCTOR_LISTALL), name='con_listall'),
    path('con_listall_inhabilitado/', login_required(views.CONDUCTOR_LISTALL_INHABILITADO), name='con_listall_inhabilitado'),
    path('con_addone/', login_required(views.CONDUCTOR_ADDONE), name='con_addone'),
    path('api/conductor/validar-rut/', login_required(views.CONDUCTOR_VALIDAR_RUT), name='conductor_validar_rut'),
    path('con_update/<int:pk>', login_required(views.CONDUCTOR_UPDATE), name='con_update'),
    path('conductor/<int:pk>/licencia/deshabilitar/', login_required(views.CONDUCTOR_LICENCIA_DESHABILITAR), name='conductor_licencia_deshabilitar'),
    path('con_delete/<int:pk>', login_required(views.CONDUCTOR_DELETE), name='con_delete'),
    path('con_listone/<int:pk>', login_required(views.CONDUCTOR_LISTONE), name='con_listone'),
    path('con_habilitar/<int:pk>', login_required(views.CONDUCTOR_HABILITAR), name='con_habilitar'),
    path('control-flota/transportes/<int:pk>/conductores/alta-rapida/', login_required(views.CONDUCTOR_ALTA_RAPIDA_TRANSPORTE), name='conductor_alta_rapida_transporte'),
    path('control-flota/conductores/<int:pk>/patentes-documentos/', login_required(views.CONDUCTOR_PATENTES_DOCUMENTOS), name='conductor_patentes_documentos'),
    path('control-flota/camiones/buscar/', login_required(views.CAMION_BUSCAR_DOCUMENTOS_TERRAMAR), name='camion_buscar_documentos_terramar'),
    path('control-flota/camiones/<int:pk>/documentos/', login_required(views.CAMION_ESTADO_DOCUMENTAL_TERRAMAR), name='camion_estado_documental_terramar'),
    path('control-flota/alertas-documentales/', login_required(views.REGISTRAR_ALERTA_DOCUMENTAL_TERRAMAR), name='registrar_alerta_documental_terramar'),
    #########################################
    ########    DOCUMENTO CONDUCTOR    ######
    #########################################
    path('con_doc_addone/<int:pk>', login_required(views.DOCUMENTO_CONDUCTOR_ADDONE), name='con_doc_addone'),
    path('download_doc_con/<int:pk>', login_required(views.DOCUMENTO_CONDUCTOR_DOWNLOAD), name='download_doc_con'),
    path('delete_doc_con/<int:pk>', login_required(views.DOCUMENTO_CONDUCTOR_DELETE), name='delete_doc_con'),
    #########################################
    ########       PROVEEDOR         ########
    #########################################
    path('pro_listall/', login_required(views.PROVEEDOR_LISTALL), name='pro_listall'),
    path('pro_listall_inhabilitado/', login_required(views.PROVEEDOR_LISTALL_INHABILITADO), name='pro_listall_inhabilitado'),
    path('pro_delete/<int:pk>', login_required(views.PROVEEDOR_DELETE), name='pro_delete'),
    path('pro_listone/<int:pk>', login_required(views.PROVEEDOR_LISTONE), name='pro_listone'),
    path('pro_habilitar/<int:pk>', login_required(views.PROVEEDOR_HABILITAR), name='pro_habilitar'),
    path('ajax_data_proveedor/<int:pk>', login_required(views.ajax_data_proveedor), name='ajax_data_proveedor'),
    #########################################
    ########    DOCUMENTO PROVEEDOR    ######
    #########################################
    path('add_doc_pro/<int:pk>', login_required(views.DOCUMENTO_PROVEEDOR_ADDONE), name='add_doc_pro'),
    path('download_doc_pro/<int:pk>', login_required(views.DOCUMENTO_PROVEEDOR_DOWNLOAD), name='download_doc_pro'),
    #########################################
    ########        CLIENTE          ########
    #########################################
    path('cli_listall/', login_required(views.CLIENTE_LISTALL), name='cli_listall'),
    path('cli_listall_inhabilitado/', login_required(views.CLIENTE_LISTALL_INHABILITADO), name='cli_listall_inhabilitado'),
    path('cli_delete/<int:pk>', login_required(views.CLIENTE_DELETE), name='cli_delete'),
    path('cli_listone/<int:pk>', login_required(views.CLIENTE_LISTONE), name='cli_listone'),
    path('cli_habilitar/<int:pk>', login_required(views.CLIENTE_HABILITAR), name='cli_habilitar'),
    path('ajax_get_data_cliente/<int:pk>', views.ajax_get_data_cliente, name='ajax_get_data_cliente'),
    #########################################
    ########    DOCUMENTO CLIENTE    ########
    #########################################
    path('add_doc_cli/<int:pk>', login_required(views.DOCUMENTO_CLIENTE_ADDONE), name='add_doc_cli'),
    path('download_doc_cli/<int:pk>', login_required(views.DOCUMENTO_CLIENTE_DOWNLOAD), name='download_doc_cli'),
    #########################################
    ########         CAMION          ########
    #########################################
    path('cam_listall/', login_required(views.CAMION_LISTALL), name='cam_listall'),
    path('cam_listall_inhabilitado/', login_required(views.CAMION_LISTALL_INHABILITADO), name='cam_listall_inhabilitado'),
    path('cam_addone/', login_required(views.CAMION_ADDONE), name='cam_addone'),
    path('cam_update/<int:pk>', login_required(views.CAMION_UPDATE), name='cam_update'),
    path('cam_delete/<int:pk>', login_required(views.CAMION_DELETE), name='cam_delete'),
    path('cam_listone/<int:pk>', login_required(views.CAMION_LISTONE), name='cam_listone'),
    path('cam_habilitar/<int:pk>', login_required(views.CAMION_HABILITAR), name='cam_habilitar'),
    path('ajax_get_data_conductor_xcamion/<int:pk>', login_required(views.ajax_get_data_conductor_xcamion), name='ajax_get_data_conductor_xcamion'),
    path('cam_delete_selected/', login_required(views.CAMION_DELETE_SELECTED), name='cam_delete_selected'),
    path('con_delete_selected/', login_required(views.CONDUCTOR_DELETE_SELECTED), name='con_delete_selected'),
    #########################################
    ########    DOCUMENTO CAMION    #########
    #########################################
    path('add_doc_cam/<int:pk>', login_required(views.DOCUMENTO_CAMION_ADDONE), name='add_doc_cam'),
    path('download_doc_cam/<int:pk>', login_required(views.DOCUMENTO_CAMION_DOWNLOAD), name='download_doc_cam'),
    path('delete_doc_cam/<int:pk>', login_required(views.DOCUMENTO_CAMION_DELETE), name='delete_doc_cam'),
    #########################################
    ########       DOCUMENTO         ########
    #########################################
    path('doc_listall/', login_required(views.DOCUMENTO_LISTALL), name='doc_listall'),
    path('doc_addone/', login_required(views.DOCUMENTO_ADDONE), name='doc_addone'),
    path('doc_update/<int:pk>', login_required(views.DOCUMENTO_UPDATE), name='doc_update'),
    path('doc_delete/<int:pk>', login_required(views.DOCUMENTO_DELETE), name='doc_delete'),
    #########################################
    ########       CAMPO             ########
    #########################################
    path('camp_listall/', login_required(views.CAMPO_LISTALL), name='camp_listall'),
    path('camp_addone/', login_required(views.CAMPO_ADDONE), name='camp_addone'),
    path('camp_update/<int:pk>', login_required(views.CAMPO_UPDATE), name='camp_update'),
    path('camp_delete/<int:pk>', login_required(views.CAMPO_DELETE), name='camp_delete'),
    #########################################
    ########       ETAPA             ########
    #########################################
    path('etap_listall/', login_required(views.ETAPA_LISTALL), name='etap_listall'),
    path('etap_addone/', login_required(views.ETAPA_ADDONE), name='etap_addone'),
    path('etap_update/<int:pk>', login_required(views.ETAPA_UPDATE), name='etap_update'),
    path('etap_delete/<int:pk>', login_required(views.ETAPA_DELETE), name='etap_delete'),
    #########################################
    ########       SECUENCIA         ########
    #########################################
    path('sec_listall/', login_required(views.SECUENCIA_LISTALL), name='sec_listall'),
    path('sec_duplicar/', login_required(views.SECUENCIA_DUPLICAR), name='sec_duplicar'),
    path('sec_addone/', login_required(views.SECUENCIA_ADDONE), name='sec_addone'),
    path('sec_update/<int:pk>', login_required(views.SECUENCIA_UPDATE), name='sec_update'),
    path('sec_delete/<int:pk>', login_required(views.SECUENCIA_DELETE), name='sec_delete'),
    #########################################
    ########  DETALLE - SECUENCIA    ########
    #########################################
    path('det_sec_listall/', login_required(views.DETALLE_SECUENCIA_LISTALL), name='det_sec_listall'),
    path('det_sec_addone/', login_required(views.DETALLE_SECUENCIA_ADDONE), name='det_sec_addone'),
    path('det_sec_update/<int:pk>', login_required(views.DETALLE_SECUENCIA_UPDATE), name='det_sec_update'),
    path('det_sec_delete/<int:pk>', login_required(views.DETALLE_SECUENCIA_DELETE), name='det_sec_delete'),
    #########################################
    ########       DETALLE-ETAPA     ########
    #########################################
    path('det_etap_listall/', login_required(views.DETALLE_ETAPA_LISTALL), name='det_etap_listall'),
    path('det_etap_addone/', login_required(views.DETALLE_ETAPA_ADDONE), name='det_etap_addone'),
    path('det_etap_update/<int:pk>', login_required(views.DETALLE_ETAPA_UPDATE), name='det_etap_update'),
    path('det_etap_delete/<int:pk>', login_required(views.DETALLE_ETAPA_DELETE), name='det_etap_delete'),
    #########################################
    ########       CAMPO - OPCIONES  ########
    #########################################
    path('camp_op_listall/', login_required(views.CAMPO_OPCIONES_LISTALL), name='camp_op_listall'),
    path('camp_op_addone/', login_required(views.CAMPO_OPCIONES_ADDONE), name='camp_op_addone'),
    path('camp_op_update/<int:pk>', login_required(views.CAMPO_OPCIONES_UPDATE), name='camp_op_update'),
    path('camp_op_delete/<int:pk>', login_required(views.CAMPO_OPCIONES_DELETE), name='camp_op_delete'),
    #########################################
    ########       Usuario - Empresa  ########
    #########################################
    path('us_emp_listall/', login_required(views.EMPRESA_USUARIOS_LISTALL), name='us_emp_listall'),
    path('us_emp_addone/', login_required(views.EMPRESA_USUARIOS_ADDONE), name='us_emp_addone'),
    path('obtener-empresa-usuario/', views.OBTENER_EMPRESA_USUARIO, name='obtener_empresa_usuario'),
    path('us_emp_update/<int:pk>', login_required(views.EMPRESA_USUARIOS_UPDATE), name='us_emp_update'),
    path('us_emp_delete/<int:pk>', login_required(views.EMPRESA_USUARIOS_DELETE), name='us_emp_delete'),
    path('actualizar-empresa-usuario/<int:ep_id>', views.ACTUALIZAR_EMPRESA_USUARIO, name='actualizar-empresa-usuario'),
    #########################################
    ############  CALENDARIO  ###############
    #########################################
    path('cal_listall/', login_required(views.CALENDARIO_LISTALL), name='cal_listall'),
    path('cal_add_holiday/', login_required(views.CALENDARIO_ADD_HOLIDAY), name='cal_add_holiday'),
    path('cal_modify_hours/', login_required(views.CALENDARIO_MODIFY_HOURS), name='cal_modify_hours'),
    path('ajax_calendario_addone/', login_required(views.ajax_calendario_addone), name='ajax_calendario_addone'),
    #########################################
    ########       RUTAS            #########
    #########################################
    path('rut_listall/', login_required(views.RUTA_LISTALL), name='rut_listall'),
    path('rut_listall_inhabilitado/', login_required(views.RUTA_LISTALL_INHABILITADO), name='rut_listall_inhabilitado'),
    path('rut_addone/', login_required(views.RUTA_ADDONE), name='rut_addone'),
    path('rut_update/<int:pk>', login_required(views.RUTA_UPDATE), name='rut_update'),
    path('rut_delete/<int:pk>', login_required(views.RUTA_DELETE), name='rut_delete'),
    path('rut_habilitar/<int:pk>', login_required(views.RUTA_HABILITAR), name='rut_habilitar'),
    path('ajax_get_data_tarifa_ruta', login_required(views.ajax_get_data_tarifa_ruta), name='ajax_get_data_tarifa_ruta'),
    #########################################
    ######  LISTAR PROVINCIA Y COMUNA  ######
    #########################################
    path('get_provincias/', views.get_provincias, name='get_provincias'),
    path('get_comunas/', views.get_comunas, name='get_comunas'),
    #########################################
    ########       TARIFA GLOBAL     ########
    #########################################
    path('tg_listall/', login_required(tarifa_global_views.listar), name='tg_listall'),
    path('tg_listall_inhabilitado/', login_required(tarifa_global_views.listar_inhabilitadas), name='tg_listall_inhabilitado'),
    path('tg_addone/', login_required(tarifa_global_views.crear), name='tg_addone'),
    path('tg_update/<int:pk>', login_required(tarifa_global_views.editar), name='tg_update'),
    path('tg_delete/<int:pk>', login_required(tarifa_global_views.deshabilitar), name='tg_delete'),
    path('tg_habilitar/<int:pk>', login_required(tarifa_global_views.habilitar), name='tg_habilitar'),
    path('tg_listone/<int:pk>', login_required(tarifa_global_views.consultar), name='tg_listone'),
    path('tg_consultar_ict/', login_required(tarifa_global_views.consultar_ict), name='tg_consultar_ict'),
    path('tg_variacion/crear/', login_required(tarifa_ajuste_views.crear_concepto), name='tg_variacion_crear'),
    path('tg_variacion/<int:pk>/estado/', login_required(tarifa_ajuste_views.cambiar_estado_concepto), name='tg_variacion_estado'),
    path('tg_variacion/<int:pk>/preview/', login_required(tarifa_ajuste_views.preview_variacion), name='tg_variacion_preview'),
    path('tg_variacion/<int:pk>/aplicar/', login_required(tarifa_ajuste_views.aplicar_variacion), name='tg_variacion_aplicar'),
    path('tg_variacion/<int:pk>/historico/', login_required(tarifa_ajuste_views.historico_concepto), name='tg_variacion_historico'),
    path('tg_ict/preview/', login_required(tarifa_ajuste_views.preview_ict), name='tg_ict_preview'),
    path('tg_ict/aplicar/', login_required(tarifa_ajuste_views.aplicar_ict), name='tg_ict_aplicar'),
    path('tg_ajuste/reversar/', login_required(tarifa_ajuste_views.reversar_ajuste), name='tg_reversar_ajuste'),
    path('ajax_get_data_tarifa/<int:pk>', login_required(tarifa_global_views.datos_ajax), name='ajax_get_data_tarifa'),
    path('tg_addmasive/', login_required(views.TARIFA_GLOBAL_ADDMASIVE), name="tg_addmasive"),
    path('tg_download_platilla', login_required(views.TARIFA_GLOBAL_DOWNLOAD_PLANTILLA), name="tg_download_platilla"),
    #########################################
    ########  LISTAR SOCIOS Y RUTAS  ########
    #########################################
    path('get_socios_negocio/', views.get_socios_negocio, name='get_socios_negocio'),
    path('get_rutas_socios/', views.get_rutas_socios, name='get_rutas_socios'),
    #########################################
    ########       PREVIEW        ########
    #########################################
    path('get_preview_etapa/<int:pk>', views.ETAPA_PREVIEW, name='get_preview_etapa'),
    path('get_preview_secuencia/<int:pk>', views.SECUENCIA_PREVIEW, name='get_preview_secuencia'),
    #########################################
    ########       PARAMETROS        ########
    #########################################
    path('guardar_parametro/', views.guardar_parametro, name='guardar_parametro'),
    path('obtener_tarifas/', views.obtener_tarifas, name='obtener_tarifas'),
    #########################################
    ########     PLANIFICACION       ########
    #########################################
    path('pla_listall/', login_required(views.PLANIFICACION_LISTALL), name='pla_listall'),
    path('planificaciones/recepcion/transferencia/', login_required(views.PLANIFICACION_RECEPCION_TRANSFERENCIA), name='planificacion_recepcion_transferencia'),
    path('pla_listone/<int:pk>', login_required(views.PLANIFICACION_LISTONE), name='pla_listone'),
    path('pla_addone/', login_required(views.PLANIFICACION_ADDONE), name='pla_addone'),
    path('pla_filedone/<int:pk>', login_required(views.PLANIFICACION_FILEDONE), name="pla_filedone"),
    path('pla_filedlistall/', login_required(views.PLANIFICACION_FILEDLISTALL), name="pla_filedlistall"),
    path('planificaciones-archivadas/<int:pk>/', login_required(views.PLANIFICACION_ARCHIVADA_RESUMEN), name="pla_archivada_resumen"),
    path('ajax/transportistas-ingreso-camion/', login_required(views.AJAX_TRANSPORTISTAS_INGRESO_CAMION), name='ajax_transportistas_ingreso_camion'),
    path('ajax/conductores-ingreso-camion/', login_required(views.AJAX_CONDUCTORES_INGRESO_CAMION), name='ajax_conductores_ingreso_camion'),
    path('ajax_validar_calendario_planificacion/', login_required(views.ajax_validar_calendario_planificacion), name='ajax_validar_calendario_planificacion'),
    path('ajax_validar_nueva_planificacion/', login_required(views.ajax_validar_nueva_planificacion), name='ajax_validar_nueva_planificacion'),
    path('ajax_archivar_planificaciones/', login_required(views.ajax_archivar_planificaciones_seleccionadas), name="ajax_archivar_planificaciones"),
    #########################################
    ############     EXTRA       ############
    #########################################
    path('ext_listall/', login_required(views.EXTRA_LISTALL), name='ext_listall'),
    path('ext_listall_del/', login_required(views.EXTRA_LISTALL_INHABILITADOS), name='ext_listall_del'),
    path('ext_addone/', login_required(views.EXTRA_ADDONE), name='ext_addone'),
    path('ext_update/<int:pk>', login_required(views.EXTRA_UPDATE), name='ext_update'),
    path('ext_delete/<int:pk>', login_required(views.EXTRA_DELETE), name='ext_delete'),
    path('ext_habilitar/<int:pk>', login_required(views.EXTRA_HABILITAR), name='ext_habilitar'),
    #########################################
    ############     EXTRA       ############
    #########################################
    path('ajax_addone_extra/<int:pk>', login_required(views.ajax_addone_extra), name='ajax_addone_extra'),
    path('ciex_import/', login_required(views.CITACION_EXTRA_ADDMASIVO), name='ciex_import'),
    path('download_excel_plantilla_extra_citacion/', login_required(views.download_excel_plantilla_extra_citacion), name='download_excel_plantilla_extra_citacion'),
    path('download_excel_plantilla_extra_planificacion/', login_required(views.download_excel_plantilla_extra_planificacion), name='download_excel_plantilla_extra_planificacion'),
    #########################################
    #########       CITACION       ##########
    #########################################
    path('cit_listall_despachos/', login_required(views.CITACION_LISTALL_DESPACHOS), name='cit_listall_despachos'),
    path('cit_listall_recepciones/', login_required(views.CITACION_LISTALL_RECEPCIONES), name='cit_listall_recepciones'),
    path('cit_addvariospre/', login_required(views.CITACION_ADDVARIOSPRE), name='cit_addvariospre'),
    path('cit_addvarios/', login_required(views.CITACION_ADDVARIOS), name='cit_addvarios'),
    path('ajax_validar_citaciones/', login_required(views.ajax_validar_citaciones), name='ajax_validar_citaciones'),
    path('cit_listone/<int:pk>', login_required(views.CITACION_LISTONE), name='cit_listone'),
    path('operacion-planta/<int:pk>/', login_required(views.OPERACION_PLANTA_CITACION), name='operacion_planta_citacion'),
    path('operacion-planta/<int:pk>/guardar-paso/', login_required(views.OPERACION_PLANTA_GUARDAR_PASO), name='operacion_planta_guardar_paso'),
    path('operacion-planta/<int:pk>/despacho-terramar/ciclo-carga/documento/', login_required(views.ajax_operacion_planta_ciclo_carga_terramar_documento), name='ajax_operacion_planta_ciclo_carga_terramar_documento'),
    path('operacion-planta/<int:pk>/despacho-terramar/ciclo-carga/documento/<str:codigo>/', login_required(views.ajax_operacion_planta_ciclo_carga_terramar_documento_ver), name='ajax_operacion_planta_ciclo_carga_terramar_documento_ver'),
    path('operacion-planta/<int:pk>/despacho-terramar/ciclo-carga/completar/', login_required(views.ajax_operacion_planta_ciclo_carga_terramar_completar), name='ajax_operacion_planta_ciclo_carga_terramar_completar'),
    path('operacion-planta/<int:pk>/despacho-terramar/documentacion/encarpe/', login_required(views.ajax_operacion_planta_documentacion_despacho_terramar_encarpe), name='ajax_operacion_planta_documentacion_despacho_terramar_encarpe'),
    path('operacion-planta/<int:pk>/despacho-terramar/documentacion/guia/', login_required(views.ajax_operacion_planta_documentacion_despacho_terramar_guia), name='ajax_operacion_planta_documentacion_despacho_terramar_guia'),
    path('operacion-planta/<int:pk>/despacho-terramar/documentacion/guia/ver/', login_required(views.ajax_operacion_planta_documentacion_despacho_terramar_guia_ver), name='ajax_operacion_planta_documentacion_despacho_terramar_guia_ver'),
    path('operacion-planta/<int:pk>/despacho-terramar/documentacion/completar/', login_required(views.ajax_operacion_planta_documentacion_despacho_terramar_completar), name='ajax_operacion_planta_documentacion_despacho_terramar_completar'),
    path('operacion-planta/<int:pk>/despacho-terramar/autorizar-salida/', login_required(views.ajax_operacion_planta_autorizar_salida_despacho_terramar), name='ajax_operacion_planta_autorizar_salida_despacho_terramar'),
    path('operacion-planta/<int:pk>/registrar-accion-toma-muestra/', login_required(views.ajax_operacion_planta_registrar_accion_toma_muestra), name='ajax_operacion_planta_registrar_accion_toma_muestra'),
    path('operacion-planta/<int:pk>/enviar-vapor/', login_required(views.ajax_operacion_planta_enviar_vapor), name='ajax_operacion_planta_enviar_vapor'),
    path('operacion-planta/<int:pk>/finalizar-vapor/', login_required(views.ajax_operacion_planta_finalizar_vapor), name='ajax_operacion_planta_finalizar_vapor'),
    path('operacion-planta/<int:pk>/validar-calidad/', login_required(views.ajax_operacion_planta_validar_calidad), name='ajax_operacion_planta_validar_calidad'),
    path('operacion-planta/<int:pk>/registrar-resultado-calidad/', login_required(views.ajax_operacion_planta_registrar_resultado_calidad), name='ajax_operacion_planta_registrar_resultado_calidad'),
    path('operacion-planta/<int:pk>/guardar-observacion/', login_required(views.ajax_operacion_planta_guardar_observacion), name='ajax_operacion_planta_guardar_observacion'),
    path('operacion-planta/<int:pk>/guardar-preparacion-descarga/', login_required(views.ajax_operacion_planta_guardar_preparacion_descarga), name='ajax_operacion_planta_guardar_preparacion_descarga'),
    path('operacion-planta/<int:pk>/autorizar-salida-bodega-externa/', login_required(views.ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa), name='ajax_operacion_planta_iniciar_ciclo_recepcion_bodega_externa'),
    path('operacion-planta/<int:pk>/registrar-regreso-bodega-externa/', login_required(views.ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa), name='ajax_operacion_planta_finalizar_ciclo_recepcion_bodega_externa'),
    path('operacion-planta/<int:pk>/iniciar-ciclo-descarga/', login_required(views.ajax_operacion_planta_iniciar_ciclo_descarga), name='ajax_operacion_planta_iniciar_ciclo_descarga'),
    path('operacion-planta/<int:pk>/finalizar-proceso-despacho/', login_required(views.ajax_operacion_planta_finalizar_proceso_despacho), name='ajax_operacion_planta_finalizar_proceso_despacho'),
    path('operacion-planta/<int:pk>/finalizar-ciclo-descarga/', login_required(views.ajax_operacion_planta_finalizar_ciclo_descarga), name='ajax_operacion_planta_finalizar_ciclo_descarga'),
    path('operacion-planta/<int:pk>/borrador-sap-preview/', login_required(views.ajax_operacion_planta_borrador_sap_preview), name='ajax_operacion_planta_borrador_sap_preview'),
    path('operacion-planta/<int:pk>/borrador-sap-enviar/', login_required(views.ajax_operacion_planta_borrador_sap_enviar), name='ajax_operacion_planta_borrador_sap_enviar'),
    path('operacion-planta/<int:pk>/sap-despacho-actualizar/', login_required(views.ajax_operacion_planta_actualizar_sap_despacho), name='ajax_operacion_planta_actualizar_sap_despacho'),
    path('operacion-planta/<int:pk>/despacho-sbh/reabrir-cierre-carga/', login_required(views.ajax_operacion_planta_reabrir_cierre_carga_despacho_sbh), name='ajax_operacion_planta_reabrir_cierre_carga_despacho_sbh'),
    path('operacion-planta/<int:pk>/sap-recepcion-actualizar/', login_required(views.ajax_operacion_planta_actualizar_sap_recepcion), name='ajax_operacion_planta_actualizar_sap_recepcion'),
    path('operacion-planta/<int:pk>/autorizar-salida/', login_required(views.ajax_operacion_planta_autorizar_salida), name='ajax_operacion_planta_autorizar_salida'),
    path('operacion-planta/<int:pk>/terramar/validar-documentacion/', login_required(views.ajax_operacion_planta_validar_documentacion_terramar), name='ajax_operacion_planta_validar_documentacion_terramar'),
    path('operacion-planta/<int:pk>/terramar/timbrar-documentos/', login_required(views.ajax_operacion_planta_timbrar_documentos_terramar), name='ajax_operacion_planta_timbrar_documentos_terramar'),
    path('operacion-planta/<int:pk>/terramar/exportar-documentos/', login_required(views.ajax_operacion_planta_exportar_documentos_terramar), name='ajax_operacion_planta_exportar_documentos_terramar'),
    path('operacion-planta/<int:pk>/terramar/documento/<str:documento_key>/', login_required(views.ajax_operacion_planta_documento_terramar), name='ajax_operacion_planta_documento_terramar'),
    path('ajax/operacion-planta/ticket-pesaje/', login_required(views.ajax_operacion_planta_obtener_ticket_pesaje), name='ajax_operacion_planta_obtener_ticket_pesaje'),
    path('ajax/operacion-planta/ticket-pesaje/descargar/', login_required(views.ajax_operacion_planta_descargar_ticket_pesaje), name='ajax_operacion_planta_descargar_ticket_pesaje'),
    path('ajax/operacion-planta/documento-calidad/descargar/', login_required(views.ajax_operacion_planta_descargar_documento_calidad), name='ajax_operacion_planta_descargar_documento_calidad'),
    path('seguimiento-operacional/', login_required(views.SEGUIMIENTO_OPERACIONAL), name='seguimiento_operacional'),
    path('seguimiento-operacional/eliminar-camion/<int:pk>/', login_required(views.SEGUIMIENTO_OPERACIONAL_ELIMINAR_CAMION), name='seguimiento_operacional_eliminar_camion'),
    path('eli_listall/', login_required(views.ELI_LISTALL), name='eli_listall'),
    path('eli_listone/<int:pk>/', login_required(views.ELI_LISTONE), name='eli_listone'),
    path('eli_pdf/<int:pk>/', login_required(views.ELI_PDF), name='eli_pdf'),
    path('expediente-citacion/', login_required(views.EXPEDIENTE_CITACION_LIST), name='expediente_citacion_list'),
    path('expediente-citacion/<int:pk>/', login_required(views.EXPEDIENTE_CITACION_DETAIL), name='expediente_citacion_detail'),
    path('expediente-citacion/documento/<int:pk>/ver/', login_required(views.EXPEDIENTE_CITACION_DOCUMENTO_VER), name='expediente_citacion_documento_ver'),
    path('expediente-citacion/documento/<int:pk>/descargar/', login_required(views.EXPEDIENTE_CITACION_DOCUMENTO_DESCARGAR), name='expediente_citacion_documento_descargar'),
    path('expediente-citacion/documento/<int:pk>/reemplazar/', login_required(views.EXPEDIENTE_CITACION_DOCUMENTO_REEMPLAZAR), name='expediente_citacion_documento_reemplazar'),
    path('cit_update_data/<int:pk>', login_required(views.CITACION_UPDATE_DATA), name='cit_update_data'),
    path('cit_finalizar_secuencia/<int:pk>', login_required(views.FINALIZAR_SECUENCIA), name='cit_finalizar_secuencia'),
    path('cit_finalizar/<int:pk>', login_required(views.CITACION_FINALIZAR), name='cit_finalizar'),
    path('cit_delete/<int:pk>', login_required(views.CITACION_DELETE), name='cit_delete'),
    path('cit_iniciar_secuencia/<int:pk>', login_required(views.CITACION_INICIAR_SECUENCIA), name='cit_iniciar_secuencia'),
    path('cit_addstep/<int:pk>', login_required(views.CITACION_ADDSTEP), name='cit_addstep'),
    path('cit_download_file/<int:pk>', login_required(views.DOWNLOAD_DATO_OPERACION_FILE), name='cit_download_file'),
    path('ajax_listar_archivos_tickets/', login_required(views.ajax_listar_archivos_tickets), name='ajax_listar_archivos_tickets'),
    path('ajax_descargar_archivo_ticket/', login_required(views.ajax_descargar_archivo_ticket), name='ajax_descargar_archivo_ticket'),
    path('cit_editar_secuencia/<int:pk>', login_required(views.ajax_edit_secuencia), name='cit_editar_secuencia'),
    path('citacion_backward/<int:pk>', login_required(views.CITACION_BACKWARD), name='citacion_backward'),
    path('cam_validar_sap/', login_required(views.CITACION_CAMPO_VALIDAR_SAP), name='cam_validar_sap'),
    path('cit_add_lineas/', login_required(views.CITACION_ENVIAR_SAP), name='cit_add_lineas'),
    path('cit_omitir_etapa/', login_required(views.CITACION_OMITIR_ETAPA), name='cit_omitir_etapa'),
    path('cit_replace/<int:pk>', login_required(views.CITACION_REEMPLAZAR), name='cit_replace'),
    path('cit_data/<int:pk>', login_required(views.CITACION_DATA), name='cit_data'),
    path('cit_editar_etapa_terminada', login_required(views.CITACION_EDITAR_ETAPA_TERMINADA), name='cit_editar_etapa_terminada'),
    path('export_citaciones_despachos_excel/', views.export_citaciones_despachos_excel, name='export_citaciones_despachos_excel'),
    path('export_citaciones_recepciones_excel/', views.export_citaciones_recepciones_excel, name='export_citaciones_recepciones_excel'),
    path('cit_entrega_conforme/<int:pk>', login_required(views.CIT_CONFORME), name="cit_entrega_conforme"),
    path('citaciones/<int:pk>/iniciar-proforma/', views.CITACION_INICIAR_PROFORMA, name='citacion_iniciar_proforma'),
    #########################################
    ########     PERFILAMIENTO       ########
    #########################################
    path('per_listall/', login_required(views.PERFIL_LISTALL), name='per_listall'),
    path('per_assi_perm_prof/', login_required(views.PERFIL_ASSIGN_PERMISSION), name='per_assi_perm_prof'),
    path('per_assi_us_prof/', login_required(views.PERFIL_ASSIGN_USER), name='per_assi_us_prof'),
    path('modificar-permiso/', views.modificar_permiso, name='modificar_permiso'),
    path('verificar-permiso/', views.verificar_permiso, name='verificar_permiso'),
    path('modificar-perfil-usuario/', views.modificar_perfil_usuario, name='modificar_perfil_usuario'),
    path('verificar-perfil-usuario/', views.verificar_perfil_usuario, name='verificar_perfil_usuario'),
    #########################################
    ########     USUARIOS       ########
    #########################################
    path('usr_listall/', login_required(views.USERS_LISTALL), name='usr_listall'),
    path('usr_addone/', login_required(views.USERS_ADDONE), name='usr_addone'),
    path('usr_update/<int:pk>', login_required(views.USERS_UPDATE), name='usr_update'), 
    path('usr_updatepassword/<int:pk>', login_required(views.USERS_UPDATEPASSWORD), name='usr_updatepassword'),
    path('usr_delete/<int:pk>', login_required(views.USERS_DELETE), name='usr_delete'),
    path('usr_habilitar/<int:pk>', login_required(views.USERS_HABILITAR), name='usr_habilitar'),
    #########################################
    #########       PROFORMA       ##########
    #########################################
    path('proforma_listall', login_required(views.PROFORMA_LISTALL), name='proforma_listall'),
    path('proforma_listall_borrador', login_required(views.BORRADOR_PROFORMA_LISTALL), name='proforma_listall_borrador'),
    path('proforma_listone/<int:pk>', login_required(views.PROFORMA_LISTONE), name='proforma_listone'),
    path('proformas/terramar/<int:pk>/', views.PROFORMA_TERRAMAR_DETALLE, name='proforma_terramar_detalle'),
    path('proformas/terramar/citaciones/<int:citacion_id>/detalle/', views.PROFORMA_TERRAMAR_CITACION_OPERACIONAL, name='proforma_terramar_citacion_operacional'),
    path('proformas/terramar/<int:pk>/citaciones/<int:citacion_id>/', views.PROFORMA_TERRAMAR_CITACION_DETALLE, name='proforma_terramar_citacion_detalle'),
    path('proformas/terramar/<int:pk>/borrador.pdf', views.PROFORMA_TERRAMAR_BORRADOR_PDF, name='proforma_terramar_borrador_pdf'),
    path('proformas/terramar/<int:pk>/aprobar/', views.PROFORMA_TERRAMAR_APROBAR_BORRADOR, name='proforma_terramar_aprobar_borrador'),
    path('proformas/terramar/<int:pk>/borrar-carpeta/', views.PROFORMA_TERRAMAR_BORRAR_CARPETA, name='proforma_terramar_borrar_carpeta'),
    path('proformas/terramar/<int:pk>/citaciones/<int:citacion_id>/extras/agregar/', views.PROFORMA_TERRAMAR_EXTRA_AGREGAR, name='proforma_terramar_extra_agregar'),
    path('proformas/terramar/<int:pk>/citaciones/<int:citacion_id>/extras/<int:extra_id>/editar/', views.PROFORMA_TERRAMAR_EXTRA_EDITAR, name='proforma_terramar_extra_editar'),
    path('proformas/terramar/<int:pk>/citaciones/<int:citacion_id>/extras/<int:extra_id>/eliminar/', views.PROFORMA_TERRAMAR_EXTRA_ELIMINAR, name='proforma_terramar_extra_eliminar'),
    path('proforma_listone_extras/<int:pk>', login_required(views.PROFORMA_LISTONE_SOLO_EXTRAS), name="proforma_listone_extras"),
    path('proforma_delete/<int:pk>', login_required(views.PROFORMA_DELETE), name='proforma_delete'),
    path('prof_listall', login_required(views.PROFORMA_MENSUAL_LISTALL), name='prof_listall'),
    path('proformas/historicos/', login_required(views.PROFORMA_MENSUAL_HISTORICO), name='proforma_historico'),
    path('proformas/borrador-pdf/', views.PROFORMA_BORRADOR_PDF, name='proforma_borrador_pdf'),
    path('proformas/citaciones-terminadas/', login_required(views.PROFORMA_CITACIONES_TERMINADAS), name='proforma_citaciones_terminadas'),
    path('proformas/citaciones-terminadas/iniciar-lote/', views.PROFORMA_CITACIONES_TERMINADAS_INICIAR_LOTE, name='proforma_citaciones_terminadas_iniciar_lote'),
    path('proforma_extras_listall/', login_required(views.PROFORMA_EXTRAS_LISTALL), name="proforma_extras_listall"),
    path('proforma_extras/', login_required(views.PROFORMA_EXTRAS), name="proforma_extras"),
    path('proforma_unitaria/', login_required(views.PROFORMA_UNITARIA), name='proforma_unitaria'),
    path('proforma_todo/', login_required(views.PROFORMA_TODO), name='proforma_todo'),
    path('proforma_delete_citacion/<int:pk>', login_required(views.PROFORMA_DELETE_CITACION), name='proforma_delete_citacion'),
    path('proforma_add_citacion/<int:pk>', login_required(views.PROFORMA_ADD_CITACION), name='proforma_add_citacion'),
    path('proforma_delete_extra/<int:pk>', login_required(views.PROFORMA_DELETE_EXTRA), name='proforma_delete_extra'),
    path('proforma_autorizar/<int:pk>', login_required(views.PROFORMA_AUTORIZAR), name='proforma_autorizar'),
    path('proforma_autorizar_ajax/<int:pk>/', views.PROFORMA_AUTORIZAR_AJAX, name='proforma_autorizar_ajax'),
    path('cit_tarifa_ruta/<int:pk>', login_required(views.cit_tarifa_ruta), name="cit_tarifa_ruta"),
    path('get_ruta_xtarifa/<int:pk>', login_required(views.get_ruta_xtarifa), name="get_ruta_xtarifa"),
    path('proforma_modificar_tarifa', login_required(views.PROFORMA_MODIFICAR_TARIFA_CITACION), name="proforma_modificar_tarifa"),
    path('proforma_add_extra/<int:pk>', login_required(views.PROFORMA_ADD_EXTRA), name="proforma_add_extra"),
    path('proforma-manual/<int:pk>/', login_required(views.PROFORMA_LISTONE_MANUAL), name='proforma_manual_listone'),
    path('proforma-manual-add', login_required(views.PROFORMA_MANUAL_ADD), name='proforma_manual_add'),    
    path('ajax/proforma-manual/add-linea/', login_required(views.proforma_manual_add_linea), name='proforma_manual_add_linea'),
    path('ajax/proforma-manual/delete-linea/', login_required(views.proforma_manual_delete_linea), name='proforma_manual_delete_linea'),
    path('ajax/proforma-manual/get-linea/', login_required(views.proforma_manual_get_linea), name='proforma_manual_get_linea'),
    path('ajax/proforma-manual/edit-linea/', login_required(views.proforma_manual_edit_linea), name='proforma_manual_edit_linea'),
    path('documento_proforma_delete/<int:pk>/', login_required(views.DOCUMENTO_PROFORMA_DELETE), name='documento_proforma_delete'),
    #########################################
    #########          CHAT         #########
    #########################################
    path('axonask/', login_required(views.AXONASK), name='axonask'),
    path('axonmessage/', login_required(views.AXONCHECKMESSAGE), name='axonmessage'),
    path('axongetusers/', login_required(views.AXONGETUSERS), name='axongetusers'),
    path('check_notifications/', login_required(views.CHECK_NOTIFICATIONS), name='check_notifications'),
    path('limpiar-notificaciones/', login_required(views.LIMPIAR_NOTIFICACIONES), name='limpiar_notificaciones'),
    path('axongetcurrentuser/', login_required(views.AXONGETCURRENTUSER), name='axongetcurrentuser'),
    path('axongetunreadmessages/', login_required(views.AXONGETUNREADMESSAGES), name='axongetunreadmessages'),
    #########################################
    ########     CUPOS PROVEEDOR     ########
    #########################################
    path('cupo_addmasive/<int:pk>', login_required(views.CUPO_PROVEEDOR_ADD_MASIVE), name='cupo_addmasive'),
    path('cupo_addone/<int:pk>', login_required(views.CUPO_PROVEEDOR_ADDONE), name='cupo_addone'),
    path('download_plantilla_cupos/', login_required(views.download_plantilla_cupos), name='download_plantilla_cupos'),
    #########################################
    ########          ZONAS          ########
    #########################################
    path('zon_listall/', login_required(views.ZONA_LISTALL), name='zon_listall'),
    path('zon_addone/', login_required(views.ZONA_ADDONE), name='zon_addone'),
    path('zon_update/<int:pk>', login_required(views.ZONA_UPDATE), name='zon_update'),
    path('zon_delete/<int:pk>', login_required(views.ZONA_DELETE), name='zon_delete'),
    #########################################
    ########          PLANO ZONAS    ########
    #########################################
    path('guardar_posicion_zona', views.guardar_posicion_zona, name='guardar_posicion_zona'),
    path('obtener_posiciones_zonas', views.obtener_posiciones_zonas, name='obtener_posiciones_zonas'),
    path('guardar_zona', views.guardar_zona, name='guardar_zona'),
    path('obtener_zonas', views.obtener_zonas, name='obtener_zonas'),
    # NUEVA URL para actualizar coordenadas de zona
    path('actualizar_coordenadas_zona', views.actualizar_coordenadas_zona, name='actualizar_coordenadas_zona'),    
    # URL opcional para obtener coordenadas específicas de una zona
    path('obtener_coordenadas_zona', views.obtener_coordenadas_zona, name='obtener_coordenadas_zona'),
    # NUEVA URL para eliminar zona
    path('eliminar_zona', views.eliminar_zona, name='eliminar_zona'),
    path('cambiar_imagen_plano', views.cambiar_imagen_plano, name='cambiar_imagen_plano'),
    #########################################
    ########          ZONAS          ########
    #########################################
    path('cit_addmasive/<int:pk>', login_required(views.IMPORTACION_PLANIFICACION), name='cit_addmasive'),
    path('download_plantilla_planificacion/', login_required(views.download_plantilla_planificacion), name='download_plantilla_planificacion'),
    path('download_citaciones_data/<int:pk>', login_required(views.download_citaciones_data), name="download_citaciones_data"),
    path('obtener_cupos_disponibles', login_required(views.obtener_cupos_disponibles), name='obtener_cupos_disponibles'),
    path('get_citation_data/<int:pk>/', login_required(views.get_citation_data), name='get_citation_data'),
    path('editar-citacion-recepcion-terramar/<int:pk>/', login_required(views.editar_citacion_recepcion_terramar), name='editar_citacion_recepcion_terramar'),
    path('update_citation/<int:pk>/', login_required(views.update_citation), name='update_citation'),
    path('get_proveedor_data/<int:proveedor_id>/', login_required(views.get_proveedor_data), name='get_proveedor_data'),
    path('buscar_proveedores/', views.buscar_proveedores, name='buscar_proveedores'),
    path('buscar_clientes/', views.buscar_clientes, name='buscar_clientes'),
    path('update_extra/<int:pk>/', views.update_extra, name='update_extra'),
    path('delete_extra/<int:pk>/', views.delete_extra, name='delete_extra'),
    path('get_extra_data/<int:pk>/', views.get_extra_data, name='get_extra_data'),
    path("guardar_zona", views.guardar_zona, name="guardar_zona"),
    path('obtener_zonas', views.obtener_zonas, name='obtener_zonas'),
    path('get_camiones_zona', views.get_camiones_x_zona, name="get_camiones_zona"),
    path('cit_ruta_edit/<int:pk>', views.cit_ruta_edit, name='cit_ruta_edit'),
    path('proforma_download/<int:pk>', views.download_proforma_details, name='proforma_download'),
    path('get_flete_empresa', views.get_flete_empresa, name='get_flete_empresa'),
    path('cit_edit_flete/<int:pk>', views.CITACION_EDITAR_FLETE, name='cit_edit_flete'),
    path('cargar_documento_proforma/<int:pk>', views.DOCUMENTO_PROFORMA_ADDONE, name='cargar_documento_proforma'),
    path('download_documento_proforma/<int:pk>', views.DOCUMENTO_PROFORMA_DOWNLOAD, name='download_documento_proforma'),
    path('filter_proforma_inicio', views.filter_proforma_inicio, name='filter_proforma_inicio'),
    path('parametro_list', views.parametro_list, name='parametro_list'),
    path('parametro_create', views.parametro_create, name='parametro_create'),
    path('parametro_update/<int:pk>', views.parametro_update, name='parametro_update'),
    path('parametro_delete/<int:pk>', views.parametro_delete, name='parametro_delete'),
    path('ajax/info-proveedor/', views.info_proveedor, name='info_proveedor'),
    path('proforma_pdf/<int:pk>', login_required(views.PROFORMA_PDF), name='proforma_pdf'),
    path('ajax/get-tipos-items/', views.get_tipos_items, name='get_tipos_items'),
    path('estado-camion/', login_required(views.estado_camion_ajax), name='estado_camion_ajax'),
    path('estado-camion/registrar-ingreso-despacho-sbh/', login_required(views.estado_camion_registrar_ingreso_despacho_sbh), name='estado_camion_registrar_ingreso_despacho_sbh'),
    path('trazabilidad/buscar/', login_required(views.TRAZABILIDAD_BUSCAR), name='trazabilidad_buscar'),
    path('buscar-patente/', views.buscar_patente_ajax, name='buscar_patente'),
    path('ajax_obtener_pesaje/', views.ajax_obtener_pesaje, name='ajax_obtener_pesaje'),
    path('ajax_actualizar_peso_dato_operacion/', views.ajax_actualizar_peso_dato_operacion, name='ajax_actualizar_peso_dato_operacion'),
    
    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
