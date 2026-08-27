from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.home.models import (
    CAMION,
    CITACION,
    DOCUMENTO_CAMION,
    DOCUMENTO_CONDUCTOR,
    LISTADO_DOCUMENTO,
    SYSLOGGER,
)


ESTADO_FALTANTE = 'FALTANTE'
ESTADO_VENCIDO = 'VENCIDO'
ESTADO_POR_VENCER = 'POR VENCER'
ESTADO_VIGENTE = 'VIGENTE'
DIAS_POR_VENCER = 30

LOG_ALERTA_CONDUCTOR = 'ALERTA_DOC_CONDUCTOR'
LOG_ALERTA_CAMION = 'ALERTA_DOC_CAMION'


def _estado_por_vencimiento(fecha_vencimiento, hoy=None):
    hoy = hoy or timezone.localdate()
    if not fecha_vencimiento:
        return ESTADO_FALTANTE, None
    dias = (fecha_vencimiento - hoy).days
    if dias <= 0:
        return ESTADO_VENCIDO, dias
    if dias <= DIAS_POR_VENCER:
        return ESTADO_POR_VENCER, dias
    return ESTADO_VIGENTE, dias


def _evaluar_documentos(*, empresa_id, grupo, modelo_documento, relacion, objeto_id,
                        campo_tipo, campo_emision, campo_vencimiento, campo_archivo,
                        campo_habilitado):
    obligatorios = list(
        LISTADO_DOCUMENTO.objects.filter(
            EP_NID_id=empresa_id,
            LIS_CGRUPO__iexact=grupo,
            LIS_BOBLIGATORIO=True,
            LIS_BHABILITADO=True,
        ).order_by('LIS_CNOMBREDOCUMENTO', 'id')
    )
    documentos = modelo_documento.objects.filter(
        EP_NID_id=empresa_id,
        **{relacion: objeto_id, campo_habilitado: True},
    ).order_by(f'-{campo_vencimiento}', '-id')
    activos_por_tipo = {}
    for documento in documentos:
        clave = str(getattr(documento, campo_tipo) or '').strip().upper()
        activos_por_tipo.setdefault(clave, documento)

    resultado = []
    for requerido in obligatorios:
        nombre = str(requerido.LIS_CNOMBREDOCUMENTO or '').strip()
        documento = activos_por_tipo.get(nombre.upper())
        if documento is None:
            estado, dias = ESTADO_FALTANTE, None
            emision = vencimiento = archivo = documento_id = None
        else:
            emision = getattr(documento, campo_emision)
            vencimiento = getattr(documento, campo_vencimiento)
            archivo = getattr(documento, campo_archivo)
            documento_id = documento.pk
            estado, dias = _estado_por_vencimiento(vencimiento)
        resultado.append({
            'documento': nombre,
            'codigo': requerido.LIS_CCODIGO,
            'obligatorio': True,
            'estado': estado,
            'dias_vencimiento': dias,
            'fecha_emision': emision.isoformat() if emision else None,
            'fecha_vencimiento': vencimiento.isoformat() if vencimiento else None,
            'archivo': archivo or None,
            'documento_id': documento_id,
        })
    return resultado


def evaluar_documentos_conductor(conductor):
    return _evaluar_documentos(
        empresa_id=conductor.EP_NID_id,
        grupo='Conductor',
        modelo_documento=DOCUMENTO_CONDUCTOR,
        relacion='CON_NID_id',
        objeto_id=conductor.pk,
        campo_tipo='DCON_CTIPO',
        campo_emision='DCON_FFECHAEMISION',
        campo_vencimiento='DCON_FFECHAVENCIMIENTO',
        campo_archivo='DCON_CRUTADOC',
        campo_habilitado='DCON_BHABILITADO',
    )


def evaluar_documentos_camion(camion):
    return _evaluar_documentos(
        empresa_id=camion.EP_NID_id,
        grupo='Camion',
        modelo_documento=DOCUMENTO_CAMION,
        relacion='CA_NID_id',
        objeto_id=camion.pk,
        campo_tipo='DCA_CTIPO',
        campo_emision='DCA_FFECHAEMISION',
        campo_vencimiento='DCA_FFECHAVENCIMIENTO',
        campo_archivo='DCA_CRUTADOC',
        campo_habilitado='DCA_BHABILITADO',
    )


def licencia_conducir_estado(conductor):
    for documento in evaluar_documentos_conductor(conductor):
        if documento['documento'].strip().upper() == 'LICENCIA DE CONDUCIR':
            return documento
    return {
        'documento': 'LICENCIA DE CONDUCIR',
        'codigo': '',
        'obligatorio': True,
        'estado': ESTADO_FALTANTE,
        'dias_vencimiento': None,
        'fecha_emision': None,
        'fecha_vencimiento': None,
        'archivo': None,
        'documento_id': None,
    }


def patentes_historicas_conductor(conductor):
    filas = (
        CITACION.objects.filter(
            EP_NID_id=conductor.EP_NID_id,
            CON_NID_id=conductor.pk,
            CA_NID__isnull=False,
            CI_BHABILITADO=True,
        )
        .exclude(Q(CA_NID__CAM_CPATENTE__isnull=True) | Q(CA_NID__CAM_CPATENTE=''))
        .values('CA_NID__CAM_CPATENTE')
        .annotate(
            ultima_utilizacion=Max('CI_FFECHACITACION'),
            cantidad_usos=Count('id'),
        )
        .order_by('-ultima_utilizacion', 'CA_NID__CAM_CPATENTE')
    )
    return [{
        'patente': str(fila['CA_NID__CAM_CPATENTE'] or '').strip().upper(),
        'ultima_utilizacion': (
            fila['ultima_utilizacion'].isoformat()
            if fila['ultima_utilizacion'] else None
        ),
        'cantidad_usos': fila['cantidad_usos'],
    } for fila in filas]


def buscar_camiones_terramar(*, empresa_id, termino='', limite=20):
    consulta = CAMION.objects.filter(
        EP_NID_id=empresa_id,
        CAM_BHABILITADO=True,
    ).select_related('SN_NID').order_by('CAM_CPATENTE', 'id')
    termino = str(termino or '').strip()
    if termino:
        consulta = consulta.filter(CAM_CPATENTE__icontains=termino)
    return list(consulta[:limite])


def registrar_alertas_documentales(*, usuario, empresa, modulo, operacion,
                                   entidad_id, documentos, citacion_id=None,
                                   patente=''):
    ahora = timezone.now()
    desde = ahora - timedelta(minutes=5)
    creados = []
    for documento in documentos:
        if documento.get('estado') == ESTADO_VIGENTE:
            continue
        tipo = str(documento.get('documento') or '').strip()
        estado = str(documento.get('estado') or '').strip()
        vencimiento = documento.get('fecha_vencimiento') or 'sin fecha'
        add1 = str(citacion_id or '')[:128]
        add2 = f'{entidad_id}:{tipo}'[:128]
        descripcion = (
            f'{operacion}; entidad={entidad_id}; documento={tipo}; estado={estado}; '
            f'vencimiento={vencimiento}; patente={patente or ""}; usuario advertido; '
            'advertido; operacion permitida.'
        )[:1024]
        existe = SYSLOGGER.objects.filter(
            US_NID=usuario,
            EP_NID=empresa,
            LOG_CMODULO=modulo,
            LOG_COPERACION=operacion,
            LOG_CADD1=add1,
            LOG_CADD2=add2,
            LOG_FFECHAREGISTRO__gte=desde,
        ).exists()
        if not existe:
            creados.append(SYSLOGGER.objects.create(
                US_NID=usuario,
                EP_NID=empresa,
                LOG_FFECHAREGISTRO=ahora,
                LOG_CMODULO=modulo,
                LOG_COPERACION=operacion,
                LOG_CDESCRIPCION=descripcion,
                LOG_CADD1=add1,
                LOG_CADD2=add2,
            ))
    return creados
