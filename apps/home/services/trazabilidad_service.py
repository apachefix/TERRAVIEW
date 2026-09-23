from collections import defaultdict
import json
import re
import unicodedata

from django.db.models import Prefetch, Q

from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_DOCUMENTO,
    CITACION_ITEM,
    DATO_OPERACION,
    ETAPA_LOG,
    OPERACION_PLANTA_LOG,
    RESULTADO_CALIDAD_HISTORIAL,
    RESULTADO_CALIDAD_OPERACION,
    SYSLOGGER,
)


CODIGOS_NUMERO_GUIA = ('CI_CNUMERODOCUMENTO', 'ING_NUMERO_GUIA')
SIN_INFORMACION = 'Sin informacion'
EVENTOS_SAP_RESUMIDOS = {
    'BORRADOR_SAP_RECEPCION_ENVIO': 'Borrador SAP recepción',
    'BORRADOR_SAP_RECEPCION': 'Borrador SAP recepción',
    'BORRADOR_SAP_GUIA_ENVIO': 'Borrador SAP recepción',
    'BORRADOR_SAP_DESPACHO_ENVIO': 'Borrador SAP despacho',
    'BORRADOR_SAP_DESPACHO': 'Borrador SAP despacho',
}
MARCADORES_EVENTO_TECNICO = {
    'API', 'HTTP', 'INTEGRACION', 'ODATA', 'SAP', 'SERVICE_LAYER', 'TOKEN', 'WEBHOOK',
}
MARCADORES_DATO_SENSIBLE = (
    'authorization', 'base sap', 'companydb', 'connection string', 'cookie', 'endpoint',
    'password', 'passwd', 'sap_username', 'secret', 'token', 'usuario sap',
)


def limpiar_termino_busqueda(valor):
    return str(valor or '').strip()[:128]


def _texto(valor):
    texto = str(valor or '').strip()
    return texto if texto and texto.lower() not in {'none', 'null', '-'} else ''


def _primero(*valores):
    for valor in valores:
        texto = _texto(valor)
        if texto:
            return texto
    return ''


def _etiqueta_tipo_recepcion(valor):
    texto = _texto(valor)
    return {
        'NACIONAL': 'Nacional',
        'EXTRANJERO': 'Extranjero',
        'IMPORTACION': 'Importación',
    }.get(texto.upper(), texto)


def _usuario_nombre(usuario):
    if not usuario:
        return ''
    nombre = usuario.get_full_name().strip()
    return nombre or usuario.username


def _normalizar_codigo(valor):
    texto = unicodedata.normalize('NFKD', _texto(valor))
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return re.sub(r'[^A-Z0-9]+', '_', texto.upper()).strip('_')


def _json_valido(valor):
    texto = _texto(valor)
    if not texto:
        return None
    try:
        dato = json.loads(texto)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return dato if isinstance(dato, (dict, list)) else None


def _es_evento_tecnico(nombre):
    codigo = _normalizar_codigo(nombre)
    return any(marcador in codigo.split('_') for marcador in MARCADORES_EVENTO_TECNICO)


def _detalle_visible(nombre, observacion):
    """Impide que datos estructurados o sensibles lleguen al HTML de trazabilidad."""
    texto = _texto(observacion)
    if not texto or _json_valido(texto) is not None or _es_evento_tecnico(nombre):
        return ''
    texto_minusculas = texto.lower()
    if any(marcador in texto_minusculas for marcador in MARCADORES_DATO_SENSIBLE):
        return ''
    return texto


def _buscar_docnum(valor):
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            if _normalizar_codigo(clave) in {'DOCNUM', 'DRAFT_DOCNUM', 'DOCUMENTO_SAP'}:
                docnum = _texto(contenido)
                if docnum:
                    return docnum
        for contenido in valor.values():
            docnum = _buscar_docnum(contenido)
            if docnum:
                return docnum
    elif isinstance(valor, list):
        for contenido in valor:
            docnum = _buscar_docnum(contenido)
            if docnum:
                return docnum
    return ''


def _resumen_borrador_sap(citacion, nombre, estado, observacion):
    codigo = _normalizar_codigo(nombre)
    es_borrador_sap = 'BORRADOR' in codigo.split('_') and 'SAP' in codigo.split('_')
    if not es_borrador_sap:
        return None

    tipo = _normalizar_codigo(citacion.CI_CTIPO)
    nombre_visible = EVENTOS_SAP_RESUMIDOS.get(codigo)
    if not nombre_visible:
        nombre_visible = (
            'Borrador SAP despacho' if 'DESPACHO' in codigo or tipo == 'DESPACHO'
            else 'Borrador SAP recepción'
        )

    contenido = _json_valido(observacion)
    estado_visible = _normalizar_codigo(estado) or 'COMPLETADO'
    if (
        any(marcador in estado_visible for marcador in ('ERROR', 'FALL'))
        or isinstance(contenido, dict) and contenido.get('success') is False
    ):
        estado_visible = 'ERROR'

    docnum = _buscar_docnum(contenido)
    if not docnum:
        coincidencia = re.search(r'\bDocNum\s*:\s*([A-Za-z0-9.-]+)', _texto(observacion), re.IGNORECASE)
        docnum = coincidencia.group(1) if coincidencia else ''
    if not docnum and tipo == 'DESPACHO':
        docnum = _texto(getattr(getattr(citacion, 'detalle_despacho', None), 'CDD_CSAP_DRAFT_DOCNUM', ''))

    return {
        'nombre': nombre_visible,
        'estado': estado_visible,
        'datos': [{'etiqueta': 'Documento SAP', 'valor': docnum}] if docnum else [],
        'detalle_visible': '',
    }


def queryset_citaciones_trazabilidad(empresa_id):
    datos = DATO_OPERACION.objects.select_related('CAMP_NID', 'ET_NID', 'US_NID').order_by(
        'DO_FFECHAREGISTRO', 'id'
    )
    etapas = ETAPA_LOG.objects.select_related('ET_NID', 'US_INICIO_ID', 'US_FIN_ID').order_by(
        'EL_FFECHAINICIO', 'id'
    )
    operacion = OPERACION_PLANTA_LOG.objects.select_related('US_NID').order_by(
        'OPL_FFECHAREGISTRO', 'id'
    )
    documentos = CITACION_DOCUMENTO.objects.select_related(
        'US_SUBE_NID', 'US_MODIFICA_NID', 'DO_NID'
    ).filter(CD_BACTIVO=True).order_by('CD_FFECHASUBIDA', 'id')
    camiones = CAMION_PATIO.objects.select_related('US_GUARDIA_ID', 'US_ASOCIA_ID').prefetch_related(
        'adjuntos',
    ).order_by('-CPA_FFECHAASOCIACION', '-id')
    items = CITACION_ITEM.objects.select_related('IT_NID').order_by('id')
    historial_calidad = RESULTADO_CALIDAD_HISTORIAL.objects.select_related('US_NID').order_by(
        'RCH_FFECHAREGISTRO', 'id'
    )
    resultados_calidad = RESULTADO_CALIDAD_OPERACION.objects.select_related('US_NID').prefetch_related(
        Prefetch('historial', queryset=historial_calidad, to_attr='trazabilidad_historial')
    )

    return CITACION.objects.filter(
        EP_NID_id=empresa_id,
        CI_BHABILITADO=True,
    ).select_related(
        'EP_NID', 'PL_NID__US_NID', 'PL_NID__CAL_NID', 'SC_NID', 'SN_NID', 'PRO_NID',
        'CON_NID', 'CA_NID', 'RUT_NID', 'detalle_operacional', 'detalle_despacho',
    ).prefetch_related(
        Prefetch('dato_operacion_set', queryset=datos, to_attr='trazabilidad_datos'),
        Prefetch('etapa_log_set', queryset=etapas, to_attr='trazabilidad_etapas'),
        Prefetch('operacion_planta_log_set', queryset=operacion, to_attr='trazabilidad_operacion'),
        Prefetch('documentos_expediente', queryset=documentos, to_attr='trazabilidad_documentos'),
        Prefetch('camiones_patio', queryset=camiones, to_attr='trazabilidad_camiones'),
        Prefetch('citacion_item_set', queryset=items, to_attr='trazabilidad_items'),
        Prefetch('resultado_calidad_operacion', queryset=resultados_calidad, to_attr='trazabilidad_calidad'),
    )


def buscar_citaciones(empresa_id, termino):
    termino = limpiar_termino_busqueda(termino)
    if not termino:
        return [], ''

    base = queryset_citaciones_trazabilidad(empresa_id)
    if termino.isdigit():
        citacion = base.filter(pk=int(termino)).first()
        if citacion:
            return [citacion], 'citacion'

    coincidencias = base.filter(
        Q(CI_CNUMERODOCUMENTO__iexact=termino)
        | Q(
            dato_operacion__CAMP_NID__CA_CCODIGO__in=CODIGOS_NUMERO_GUIA,
            dato_operacion__DO_CVALOR__iexact=termino,
        )
        | Q(camiones_patio__CPA_CNUMERO_GUIA__iexact=termino)
    ).distinct().order_by('-CI_FFECHACITACION', '-id')
    coincidencias = list(coincidencias)
    if coincidencias:
        return coincidencias, 'guia'

    patentes = base.filter(
        Q(CA_NID__CAM_CPATENTE__iexact=termino)
        | Q(detalle_despacho__CDD_CPATENTE__iexact=termino)
        | Q(camiones_patio__CPA_CPATENTE__iexact=termino)
        | Q(
            dato_operacion__CAMP_NID__CA_CCODIGO='ING_PATENTE',
            dato_operacion__DO_CVALOR__iexact=termino,
        )
    ).distinct().order_by('-CI_FFECHACITACION', '-id')
    return list(patentes), 'patente'


def obtener_numero_guia(citacion, datos_operacion=None):
    """Fuente oficial: CITACION; respaldos: datos de operacion y camion de patio."""
    directo = _texto(citacion.CI_CNUMERODOCUMENTO)
    if directo:
        return directo

    datos = datos_operacion
    if datos is None:
        datos = getattr(citacion, 'trazabilidad_datos', None)
    if datos is None:
        datos = DATO_OPERACION.objects.select_related('CAMP_NID').filter(
            CI_NID=citacion,
            CAMP_NID__CA_CCODIGO__in=CODIGOS_NUMERO_GUIA,
        ).order_by('-DO_FFECHAREGISTRO', '-id')
    valores_por_codigo = defaultdict(list)
    for dato in datos:
        codigo = _texto(getattr(dato.CAMP_NID, 'CA_CCODIGO', ''))
        if codigo in CODIGOS_NUMERO_GUIA:
            valores_por_codigo[codigo].append(dato.DO_CVALOR)
    for codigo in CODIGOS_NUMERO_GUIA:
        for valor in reversed(valores_por_codigo[codigo]):
            texto = _texto(valor)
            if texto:
                return texto

    camiones = getattr(citacion, 'trazabilidad_camiones', None)
    if camiones is None:
        camiones = citacion.camiones_patio.order_by('-CPA_FFECHAASOCIACION', '-id')
    for camion in camiones:
        texto = _texto(camion.CPA_CNUMERO_GUIA)
        if texto:
            return texto
    return ''


def _datos_por_etapa(datos):
    agrupados = defaultdict(list)
    for dato in datos:
        etiqueta = _primero(dato.CAMP_NID.CA_CETIQUETA, dato.CAMP_NID.CA_CCODIGO, 'Dato')
        agrupados[dato.ET_NID_id].append({
            'etiqueta': etiqueta,
            'valor': _texto(dato.DO_CVALOR) or SIN_INFORMACION,
            'fecha': dato.DO_FFECHAREGISTRO,
            'responsable': _usuario_nombre(dato.US_NID),
        })
    return agrupados


def _cabecera(citacion, datos, camiones):
    valores = {}
    for dato in datos:
        codigo = _texto(dato.CAMP_NID.CA_CCODIGO)
        valor = _texto(dato.DO_CVALOR)
        if codigo and valor:
            valores[codigo] = valor

    detalle_operacional = getattr(citacion, 'detalle_operacional', None)
    detalle_despacho = getattr(citacion, 'detalle_despacho', None)
    item = citacion.trazabilidad_items[0].IT_NID if getattr(citacion, 'trazabilidad_items', []) else None
    camion = camiones[0] if camiones else None
    es_despacho = _texto(citacion.CI_CTIPO).upper() == 'DESPACHO'

    codigo_sap = _primero(
        getattr(detalle_despacho, 'CDD_CSAP_CODIGO_PRODUCTO', ''),
        getattr(detalle_operacional, 'CDO_CCODIGO_SAP', ''),
        getattr(item, 'IT_CCODIGO', ''),
    )
    articulo_sap = _primero(
        getattr(detalle_despacho, 'CDD_CSAP_NOMBRE_PRODUCTO', ''),
        getattr(detalle_operacional, 'CDO_CINSUMO', ''),
        getattr(item, 'IT_CNOMBRE', ''),
        getattr(camion, 'CPA_CINSUMO_DECLARADO_GUIA', ''),
    )
    proveedor = _primero(
        getattr(getattr(citacion, 'PRO_NID', None), 'SN_CRAZONSOCIAL', ''),
        getattr(camion, 'CPA_CPROVEEDOR_DECLARADO', ''),
    )
    cliente = _primero(
        getattr(detalle_despacho, 'CDD_CSAP_CLIENTE_NOMBRE', ''),
        getattr(getattr(citacion, 'SN_NID', None), 'SN_CRAZONSOCIAL', ''),
        getattr(camion, 'CPA_CCLIENTE_DECLARADO', ''),
    )
    conductor_maestro = ''
    if citacion.CON_NID:
        conductor_maestro = f'{citacion.CON_NID.CON_CNOMBRE} {citacion.CON_NID.CON_CAPELLIDO}'.strip()

    return {
        'citacion': citacion.id,
        'numero_guia': obtener_numero_guia(citacion, datos),
        'patente': _primero(
            valores.get('ING_PATENTE'), getattr(detalle_despacho, 'CDD_CPATENTE', ''),
            getattr(getattr(citacion, 'CA_NID', None), 'CAM_CPATENTE', ''), getattr(camion, 'CPA_CPATENTE', ''),
        ),
        'empresa': citacion.EP_NID.EP_CRAZONSOCIAL,
        'tipo': _primero(citacion.CI_CTIPO, citacion.PL_NID.PL_CTIPOCUPO),
        'tipo_recepcion': _etiqueta_tipo_recepcion(
            getattr(detalle_operacional, 'CDO_CTIPO_RECEPCION', '')
        ) if not es_despacho else '',
        'flujo': _primero(getattr(citacion.SC_NID, 'SE_CNOMBRE', ''), getattr(citacion.SC_NID, 'SE_CCODIGO', '')),
        'codigo_sap': codigo_sap,
        'nombre_articulo_sap': articulo_sap,
        'producto': articulo_sap,
        'proveedor': proveedor,
        'cliente': cliente,
        'fecha_planificacion': _primero(citacion.PL_NID.PL_FFECHAINICIO, citacion.PL_NID.PL_FFECHAREGISTRO),
        'fecha_ingreso': _primero(valores.get('ING_FECHA_INGRESO'), citacion.CI_FFECHAINICIO, getattr(camion, 'CPA_FFECHALLEGADA', '')),
        'conductor': _primero(valores.get('ING_NOMBRE_CONDUCTOR'), getattr(detalle_despacho, 'CDD_CCONDUCTOR', ''), conductor_maestro, getattr(camion, 'CPA_CNOMBRE_CONDUCTOR', '')),
        'transportista': _primero(valores.get('ING_EMPRESA_TRANSPORTE'), getattr(detalle_despacho, 'CDD_CEMPRESA_TRANSPORTE', ''), getattr(camion, 'CPA_CTRANSPORTISTA_DECLARADO', '')),
        'transporte_a_cargo': _primero(getattr(camion, 'get_transporte_a_cargo_display', lambda: '')()),
        'ruta_transportista': _primero(getattr(getattr(citacion, 'RUT_NID', None), 'RUT_CNOMBRE', ''), valores.get('AR_RUTA_TRANSPORTISTA')),
        'planificacion': citacion.PL_NID_id,
        'observaciones': _detalle_visible(
            'Observaciones',
            _primero(
                citacion.CI_CCOMENTARIO,
                getattr(detalle_operacional, 'CDO_COBSERVACION', ''),
                getattr(camion, 'CPA_COBSERVACION', ''),
            ),
        ),
        'es_despacho': es_despacho,
    }


def construir_trazabilidad(citacion, logs_sistema=None):
    datos = list(getattr(citacion, 'trazabilidad_datos', []))
    etapas_log = list(getattr(citacion, 'trazabilidad_etapas', []))
    operacion_log = list(getattr(citacion, 'trazabilidad_operacion', []))
    camiones = list(getattr(citacion, 'trazabilidad_camiones', []))
    por_etapa = _datos_por_etapa(datos)
    eventos = []

    eventos.append({
        'tipo_evento': 'planificacion',
        'nombre': 'Etapa 0 - Planificacion creada',
        'estado': 'Registrada',
        'fecha': citacion.PL_NID.PL_FFECHAREGISTRO or citacion.PL_NID.PL_FFECHAINICIO,
        'responsable': _usuario_nombre(citacion.PL_NID.US_NID),
        'datos': [
            {'etiqueta': 'Planificacion', 'valor': f'#{citacion.PL_NID_id}'},
            {'etiqueta': 'Tipo', 'valor': _primero(citacion.PL_NID.PL_CTIPOCUPO, SIN_INFORMACION)},
        ],
        'detalle_visible': '',
    })
    eventos.append({
        'tipo_evento': 'citacion',
        'nombre': 'Citacion creada',
        'estado': _primero(citacion.CI_CESTADO, 'Registrada'),
        'fecha': citacion.CI_FFECHAREGISTRO or citacion.CI_FFECHACITACION,
        'responsable': _usuario_nombre(citacion.US_NID),
        'datos': [{'etiqueta': 'Citacion', 'valor': f'#{citacion.id}'}],
        'detalle_visible': _detalle_visible('Citacion creada', citacion.CI_CCOMENTARIO),
    })

    for log in etapas_log:
        responsable = log.US_FIN_ID if log.EL_FFECHAFIN else log.US_INICIO_ID
        eventos.append({
            'tipo_evento': 'etapa',
            'nombre': _primero(log.ET_NID.ET_CNOMBRE, log.ET_NID.ET_CCODIGO),
            'estado': 'Completada' if log.EL_FFECHAFIN else 'En curso',
            'fecha': log.EL_FFECHAFIN or log.EL_FFECHAINICIO,
            'fecha_inicio': log.EL_FFECHAINICIO,
            'fecha_fin': log.EL_FFECHAFIN,
            'responsable': _usuario_nombre(responsable),
            'datos': por_etapa.get(log.ET_NID_id, []),
            'detalle_visible': _detalle_visible(
                _primero(log.ET_NID.ET_CNOMBRE, log.ET_NID.ET_CCODIGO),
                _primero(log.EL_COBSERVACION, log.EL_CACCION),
            ),
        })

    etapas_con_log = {log.ET_NID_id for log in etapas_log}
    for etapa_id, datos_etapa in por_etapa.items():
        if etapa_id in etapas_con_log or not datos_etapa:
            continue
        dato_referencia = max(
            (dato for dato in datos if dato.ET_NID_id == etapa_id),
            key=lambda dato: (dato.DO_FFECHAREGISTRO is not None, dato.DO_FFECHAREGISTRO, dato.id),
        )
        eventos.append({
            'tipo_evento': 'etapa',
            'nombre': _primero(dato_referencia.ET_NID.ET_CNOMBRE, dato_referencia.ET_NID.ET_CCODIGO),
            'estado': 'Datos registrados',
            'fecha': dato_referencia.DO_FFECHAREGISTRO,
            'responsable': _usuario_nombre(dato_referencia.US_NID),
            'datos': datos_etapa,
            'detalle_visible': '',
        })

    for log in operacion_log:
        resumen_sap = _resumen_borrador_sap(
            citacion, log.OPL_CPASO, log.OPL_CESTADO, log.OPL_COBSERVACION
        )
        eventos.append({
            'tipo_evento': 'operacion_planta',
            'nombre': resumen_sap['nombre'] if resumen_sap else log.OPL_CPASO,
            'estado': resumen_sap['estado'] if resumen_sap else log.OPL_CESTADO,
            'fecha': log.OPL_FFECHAREGISTRO,
            'responsable': _usuario_nombre(log.US_NID),
            'datos': resumen_sap['datos'] if resumen_sap else [],
            'detalle_visible': (
                resumen_sap['detalle_visible'] if resumen_sap
                else _detalle_visible(log.OPL_CPASO, log.OPL_COBSERVACION)
            ),
        })

    calidad = getattr(citacion, 'trazabilidad_calidad', None)
    if calidad:
        for cambio in getattr(calidad, 'trazabilidad_historial', []):
            eventos.append({
                'tipo_evento': 'calidad',
                'nombre': cambio.RCH_CEVENTO,
                'estado': cambio.RCH_CESTADO_NUEVO,
                'fecha': cambio.RCH_FFECHAREGISTRO,
                'responsable': _usuario_nombre(cambio.US_NID) or _texto(cambio.RCH_CRESPONSABLE_SISTEMA),
                'datos': [
                    {'etiqueta': 'Estado anterior', 'valor': _texto(cambio.RCH_CESTADO_ANTERIOR) or SIN_INFORMACION},
                    {'etiqueta': 'Estado nuevo', 'valor': cambio.RCH_CESTADO_NUEVO},
                    {'etiqueta': 'Origen', 'valor': cambio.RCH_CORIGEN},
                    {'etiqueta': 'Guia', 'valor': calidad.RCO_CNUMERO_GUIA or SIN_INFORMACION},
                    {'etiqueta': 'Citacion', 'valor': f'#{citacion.id}'},
                    {'etiqueta': 'Resultado', 'valor': cambio.RCH_CRESULTADO or SIN_INFORMACION},
                    {'etiqueta': 'Observacion', 'valor': cambio.RCH_COBSERVACION or SIN_INFORMACION},
                ],
                'detalle_visible': '',
            })

    if logs_sistema is None:
        logs_sistema = SYSLOGGER.objects.select_related('US_NID').filter(
            EP_NID_id=citacion.EP_NID_id,
            LOG_CADD1=str(citacion.id),
        ).order_by('LOG_FFECHAREGISTRO', 'id')
    for log in logs_sistema:
        eventos.append({
            'tipo_evento': 'sistema',
            'nombre': _primero(log.LOG_COPERACION, log.LOG_CMODULO, 'Evento de sistema'),
            'estado': 'Registrado',
            'fecha': log.LOG_FFECHAREGISTRO,
            'responsable': _usuario_nombre(log.US_NID),
            'datos': [],
            'detalle_visible': _detalle_visible(
                _primero(log.LOG_COPERACION, log.LOG_CMODULO, 'Evento de sistema'),
                log.LOG_CDESCRIPCION,
            ),
        })

    eventos.sort(key=lambda evento: (evento.get('fecha') is not None, evento.get('fecha') or citacion.CI_FFECHACITACION))
    etapa_actual = next(
        (evento for evento in reversed(eventos) if evento['tipo_evento'] == 'etapa' and evento['estado'] == 'En curso'),
        None,
    )
    if etapa_actual is None:
        etapa_actual = next(
            (evento for evento in reversed(eventos) if evento['tipo_evento'] in {'etapa', 'operacion_planta'}),
            eventos[-1] if eventos else None,
        )
    if etapa_actual:
        etapa_actual['actual'] = True

    documentos = []
    for documento in getattr(citacion, 'trazabilidad_documentos', []):
        documentos.append({
            'tipo': documento.get_CD_CTIPO_display(),
            'nombre': documento.CD_CNOMBRE_ARCHIVO,
            'ruta': documento.CD_CRUTA_ARCHIVO,
            'fecha': documento.CD_FFECHASUBIDA,
            'responsable': _usuario_nombre(documento.US_SUBE_NID),
        })
    for camion in camiones:
        for adjunto in camion.adjuntos.all():
            documentos.append({
                'tipo': adjunto.get_CPA_CTIPO_DOCUMENTO_display(),
                'nombre': adjunto.CPA_FARCHIVO.name.rsplit('/', 1)[-1],
                'ruta': adjunto.CPA_FARCHIVO.url if adjunto.CPA_FARCHIVO else '',
                'fecha': adjunto.CPA_FFECHACARGA,
                'responsable': _usuario_nombre(adjunto.US_CARGA_ID),
            })

    cabecera = _cabecera(citacion, datos, camiones)
    cabecera['ultima_etapa'] = etapa_actual['nombre'] if etapa_actual else ''
    cabecera['ultimo_estado'] = etapa_actual['estado'] if etapa_actual else _texto(citacion.CI_CESTADO)
    return {'cabecera': cabecera, 'etapas': eventos, 'documentos': documentos}


def construir_resultados_trazabilidad(citaciones):
    citaciones = list(citaciones)
    ids = [str(citacion.id) for citacion in citaciones]
    logs_por_citacion = defaultdict(list)
    for log in SYSLOGGER.objects.select_related('US_NID').filter(
        EP_NID_id__in={citacion.EP_NID_id for citacion in citaciones},
        LOG_CADD1__in=ids,
    ).order_by('LOG_FFECHAREGISTRO', 'id'):
        logs_por_citacion[_texto(log.LOG_CADD1)].append(log)
    return [construir_trazabilidad(citacion, logs_por_citacion[str(citacion.id)]) for citacion in citaciones]
