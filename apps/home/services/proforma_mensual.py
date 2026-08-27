from calendar import monthrange
from datetime import date
from decimal import Decimal
import unicodedata

from django.db import IntegrityError, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_EXTRA,
    CITACION_PROFORMA,
    EXTRA_PROFORMA,
    PROFORMA,
    SOCIONEGOCIO,
    SYSLOGGER,
    TARIFA_GLOBAL,
)
from apps.home.services.proforma_service import (
    PERMISO_INICIAR_PROFORMA,
    PERMISO_PROFORMA_CITACIONES,
    resolver_transporte_estructurado,
    usuario_tiene_empresa,
    usuario_tiene_permiso_pro_cit,
)


EMPRESA_TERRAMAR = 1
TIPOS_OPERACION = {'RECEPCION', 'DESPACHO'}
TIPOS_FLETE = {'RECEPCION', 'DESPACHO'}
TIPOS_EXTRAS = {'RECEPCION EXTRAS', 'DESPACHO EXTRAS'}


def tipo_operacion_proforma(tipo):
    valor = str(tipo or '').strip().upper()
    return valor[:-7].strip() if valor.endswith(' EXTRAS') else valor


def categoria_proforma(tipo):
    return 'EXTRAS' if str(tipo or '').strip().upper() in TIPOS_EXTRAS else 'FLETE'


def tipo_extras_operacion(tipo):
    operacion = tipo_operacion_proforma(tipo)
    if operacion not in TIPOS_OPERACION:
        raise ValueError('El tipo debe ser RECEPCION o DESPACHO.')
    return f'{operacion} EXTRAS'
MENSAJE_CAMBIO_SELECCION = (
    'Las citaciones cambiaron desde la selección. Revise nuevamente el '
    'período antes de generar la Proforma.'
)


def _normalizar_nombre(valor):
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return ' '.join(texto.upper().split())


def periodo_mensual(valor):
    try:
        ano, mes = (int(parte) for parte in str(valor or '').split('-', 1))
        inicio = date(ano, mes, 1)
    except (TypeError, ValueError):
        raise ValueError('El período debe tener formato AAAA-MM.')
    return inicio, date(ano, mes, monthrange(ano, mes)[1])


def periodo_citacion(citacion):
    fecha = timezone.localtime(citacion.CI_FFECHACITACION).date()
    return fecha.replace(day=1), fecha.replace(
        day=monthrange(fecha.year, fecha.month)[1]
    )


def _resultado_error(codigo, mensaje, **extra):
    return {'ok': False, 'codigo': codigo, 'mensaje': mensaje, **extra}


def _es_historica_para_fallback(citacion):
    aplicada = (
        MigrationRecorder.Migration.objects.filter(
            app='home', name='0102_proforma_periodo_mensual_terramar'
        )
        .values_list('applied', flat=True)
        .first()
    )
    return bool(
        aplicada
        and citacion.CI_FFECHAREGISTRO
        and citacion.CI_FFECHAREGISTRO <= aplicada
    )


def _validar_citacion(
    citacion, empresa_id, transporte_id, tipo, inicio, fin,
    transporte_historico_id=None,
):
    transporte_coincide = citacion.PRO_NID_id == transporte_id
    if (
        citacion.PRO_NID_id is None
        and transporte_historico_id == transporte_id
        and _es_historica_para_fallback(citacion)
    ):
        transporte_coincide = True
    if (
        citacion.EP_NID_id != empresa_id
        or not transporte_coincide
        or citacion.CI_CTIPO != tipo
        or periodo_citacion(citacion) != (inicio, fin)
    ):
        return _resultado_error('GRUPO_INCOMPATIBLE', MENSAJE_CAMBIO_SELECCION)
    if not (
        citacion.CI_BHABILITADO
        and citacion.CI_BCONFORME
        and citacion.CI_CESTADO == 'TERMINADO'
    ):
        return _resultado_error('NO_ELEGIBLE', MENSAJE_CAMBIO_SELECCION)
    transporte = resolver_transporte_estructurado(citacion)
    if not transporte['es_terramar']:
        return _resultado_error('NO_ELEGIBLE', MENSAJE_CAMBIO_SELECCION)
    return {'ok': True}


def recalcular_totales(proforma):
    """Recalcula un único documento sin mezclar Fletes con Extras."""
    categoria = categoria_proforma(proforma.PRO_CTIPO)
    if categoria == 'FLETE':
        subtotal = CITACION_PROFORMA.objects.filter(PRO_NID=proforma).aggregate(
            total=Sum('CIP_NSUBTOTAL')
        )['total'] or Decimal('0')
        ingresos = Decimal('0')
        descuentos = Decimal('0')
    else:
        extras = EXTRA_PROFORMA.objects.filter(
            PRO_NID=proforma, EPR_BHABILITADO=True
        )
        ingresos = extras.filter(EPR_BINGRESO=True).aggregate(
            total=Sum('EPR_NVALOR')
        )['total'] or Decimal('0')
        descuentos = extras.filter(EPR_BINGRESO=False).aggregate(
            total=Sum('EPR_NVALOR')
        )['total'] or Decimal('0')
        subtotal = ingresos - descuentos
    iva = subtotal * Decimal('0.19')
    proforma.PRO_NSUBTOTAL = subtotal
    proforma.PRO_NIVA = iva
    proforma.PRO_NTOTAL = subtotal + iva
    proforma.PRO_NINGRESO = ingresos
    proforma.PRO_NDESCUENTO = descuentos
    proforma.save(update_fields=[
        'PRO_NSUBTOTAL', 'PRO_NIVA', 'PRO_NTOTAL',
        'PRO_NINGRESO', 'PRO_NDESCUENTO',
    ])
    return proforma


def _auditar_documento(user, proforma, operacion, descripcion):
    SYSLOGGER.objects.create(
        US_NID=user,
        EP_NID_id=proforma.EP_NID_id,
        LOG_FFECHAREGISTRO=timezone.now(),
        LOG_CMODULO='PROFORMA',
        LOG_COPERACION=operacion,
        LOG_CADD1=f'Proforma: {proforma.pk}',
        LOG_CADD2=f'Tipo: {proforma.PRO_CTIPO}',
        LOG_CDESCRIPCION=descripcion,
    )


def obtener_o_crear_borrador_extras(
    *, user, empresa_id, transporte_id, tipo, inicio, fin, comentario=''
):
    tipo_extras = tipo_extras_operacion(tipo)
    borrador = PROFORMA.objects.select_for_update().filter(
        EP_NID_id=empresa_id,
        SN_NID_id=transporte_id,
        PRO_CTIPO=tipo_extras,
        PRO_FPERIODO_INICIO=inicio,
        PRO_FPERIODO_FIN=fin,
        PRO_CESTADO='CREADO',
        PRO_BBORRADOR=True,
        PRO_DOC_ENTRY__isnull=True,
    ).order_by('-pk').first()
    if borrador:
        return borrador, False
    borrador = PROFORMA.objects.create(
        EP_NID_id=empresa_id,
        US_NID=user,
        SN_NID_id=transporte_id,
        PRO_CESTADO='CREADO',
        PRO_CCOMENTARIO=comentario,
        PRO_NSUBTOTAL=Decimal('0'),
        PRO_NIVA=Decimal('0'),
        PRO_NTOTAL=Decimal('0'),
        PRO_NINGRESO=Decimal('0'),
        PRO_NDESCUENTO=Decimal('0'),
        PRO_FFECHAREGISTRO=timezone.now(),
        PRO_FFECHAEMISION=timezone.now(),
        PRO_CTIPO=tipo_extras,
        PRO_BSINEXTRAS=False,
        PRO_BSOLOEXTRAS=True,
        PRO_FPERIODO_INICIO=inicio,
        PRO_FPERIODO_FIN=fin,
    )
    _auditar_documento(
        user, borrador, 'PROFORMA_EXTRAS_CREADA',
        'Proforma de Extras creada como documento independiente.',
    )
    return borrador, True


def acumular_extras_pendientes(
    *, user, citacion_ids, empresa_id, transporte_id, tipo, inicio, fin,
    comentario=''
):
    pendientes = list(
        CITACION_EXTRA.objects.select_for_update()
        .filter(EP_NID_id=empresa_id, CI_NID_id__in=citacion_ids)
        .annotate(tiene_snapshot=Exists(
            EXTRA_PROFORMA.objects.filter(CIE_NID_id=OuterRef('pk'))
        ))
        .filter(tiene_snapshot=False)
        .order_by('pk')
    )
    if not pendientes:
        return None
    proforma, _ = obtener_o_crear_borrador_extras(
        user=user,
        empresa_id=empresa_id,
        transporte_id=transporte_id,
        tipo=tipo,
        inicio=inicio,
        fin=fin,
        comentario=comentario,
    )
    EXTRA_PROFORMA.objects.bulk_create([
        EXTRA_PROFORMA(
            EP_NID_id=empresa_id,
            PRO_NID=proforma,
            CIE_NID=extra,
            EPR_NVALOR=extra.CIE_NVALOR,
            EPR_BINGRESO=extra.CIE_BINGRESO,
            EPR_NCANTIDAD=extra.CIE_NCANTIDAD,
            EPR_NVALORUNITARIO=extra.CIE_NVALORUNITARIO,
        )
        for extra in pendientes
    ])
    recalcular_totales(proforma)
    return proforma


def crear_o_ampliar_proforma_mensual(
    *, user, citacion_ids, empresa_id, transporte_id, tipo, periodo,
    comentario='', sin_extras=False, proforma_id=None,
    transporte_historico_id=None,
):
    if not usuario_tiene_permiso_pro_cit(user, PERMISO_PROFORMA_CITACIONES):
        return _resultado_error('SIN_PERMISO', 'No tiene permiso para generar Proformas.')
    try:
        empresa_id = int(empresa_id)
        transporte_id = int(transporte_id)
        ids = [int(valor) for valor in citacion_ids]
        inicio, fin = periodo_mensual(periodo)
    except (TypeError, ValueError):
        return _resultado_error('PAYLOAD_INVALIDO', 'Los datos de la agrupación no son válidos.')
    tipo = str(tipo or '').strip().upper()
    if empresa_id != EMPRESA_TERRAMAR:
        return _resultado_error('EMPRESA_FUERA_ALCANCE', 'El flujo mensual solo está disponible para Terramar.')
    if not usuario_tiene_empresa(user, empresa_id):
        return _resultado_error('SIN_EMPRESA', 'No tiene acceso a Terramar.')
    if tipo not in TIPOS_OPERACION:
        return _resultado_error('TIPO_INVALIDO', 'El tipo debe ser RECEPCION o DESPACHO.')
    if not ids or len(ids) != len(set(ids)) or len(ids) > 500:
        return _resultado_error('PAYLOAD_INVALIDO', 'Seleccione entre 1 y 500 citaciones sin duplicados.')

    try:
        with transaction.atomic():
            citaciones = list(
                CITACION.objects.select_for_update()
                .filter(pk__in=ids)
                .order_by('pk')
            )
            if len(citaciones) != len(ids):
                return _resultado_error('CITACION_INEXISTENTE', MENSAJE_CAMBIO_SELECCION)
            # La responsabilidad del transporte forma parte de la elegibilidad.
            # Bloqueamos sus registros antes de revalidarla para que no pueda
            # cambiar mientras se materializa la agrupación mensual.
            list(
                CAMION_PATIO.objects.select_for_update()
                .filter(
                    CI_NID_id__in=ids,
                    CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
                )
                .order_by('pk')
            )
            if CITACION_PROFORMA.objects.select_for_update().filter(
                CI_NID_id__in=ids
            ).exists():
                return _resultado_error('YA_PROFORMADA', MENSAJE_CAMBIO_SELECCION)
            for citacion in citaciones:
                validacion = _validar_citacion(
                    citacion, empresa_id, transporte_id, tipo, inicio, fin,
                    transporte_historico_id=transporte_historico_id,
                )
                if not validacion['ok']:
                    return validacion

            grupo = PROFORMA.objects.select_for_update().filter(
                EP_NID_id=empresa_id,
                SN_NID_id=transporte_id,
                PRO_CTIPO=tipo,
                PRO_FPERIODO_INICIO=inicio,
                PRO_FPERIODO_FIN=fin,
            )
            proforma = None
            if proforma_id:
                proforma = grupo.filter(pk=proforma_id).first()
                if not proforma:
                    return _resultado_error('PROFORMA_INCOMPATIBLE', 'La Proforma no pertenece al grupo mensual seleccionado.')
            else:
                existente = grupo.filter(
                    PRO_CESTADO='CREADO',
                    PRO_BBORRADOR=True,
                    PRO_DOC_ENTRY__isnull=True,
                ).order_by('-pk').first()
                if existente:
                    return _resultado_error(
                        'PROFORMA_EXISTENTE',
                        'Ya existe un borrador de Fletes para este Transporte, tipo y período.',
                        proforma=existente.pk,
                    )

            if proforma:
                if not (proforma.PRO_CESTADO == 'CREADO' and proforma.PRO_BBORRADOR and proforma.PRO_DOC_ENTRY is None):
                    codigo = (
                        'PROFORMA_AUTORIZADA' if proforma.PRO_CESTADO == 'AUTORIZADO'
                        else 'PROFORMA_APROBADA' if proforma.PRO_CESTADO == 'APROBADO'
                        else 'ESTADO_INCOMPATIBLE'
                    )
                    return _resultado_error(codigo, 'Solo se pueden agregar citaciones a una Proforma de Fletes en borrador.')
                if EXTRA_PROFORMA.objects.filter(
                    PRO_NID=proforma, EPR_BHABILITADO=True
                ).exists():
                    return _resultado_error(
                        'BORRADOR_MIXTO_REQUIERE_SEPARACION',
                        'El borrador contiene Fletes y Extras. Debe separarse antes de continuar.',
                        proforma=proforma.pk,
                    )
            else:
                proforma = PROFORMA.objects.create(
                    EP_NID_id=empresa_id,
                    US_NID=user,
                    SN_NID_id=transporte_id,
                    PRO_CESTADO='CREADO',
                    PRO_CCOMENTARIO=comentario,
                    PRO_NSUBTOTAL=Decimal('0'),
                    PRO_NIVA=Decimal('0'),
                    PRO_NTOTAL=Decimal('0'),
                    PRO_NINGRESO=Decimal('0'),
                    PRO_NDESCUENTO=Decimal('0'),
                    PRO_FFECHAREGISTRO=timezone.now(),
                    PRO_FFECHAEMISION=timezone.now(),
                    PRO_CTIPO=tipo,
                    PRO_BSINEXTRAS=True,
                    PRO_BSOLOEXTRAS=False,
                    PRO_FPERIODO_INICIO=inicio,
                    PRO_FPERIODO_FIN=fin,
                )
                _auditar_documento(
                    user, proforma, 'PROFORMA_FLETE_CREADA',
                    'Proforma de Fletes creada como documento independiente.',
                )
            asociaciones = [
                CITACION_PROFORMA(
                    EP_NID_id=empresa_id,
                    PRO_NID=proforma,
                    CI_NID=citacion,
                    CIP_NSUBTOTAL=citacion.CI_NVALORTARIFA or Decimal('0'),
                    CIP_BREGLA_MENSUAL=True,
                )
                for citacion in citaciones
            ]
            CITACION_PROFORMA.objects.bulk_create(asociaciones)

            recalcular_totales(proforma)
            proforma_extras = acumular_extras_pendientes(
                user=user,
                citacion_ids=ids,
                empresa_id=empresa_id,
                transporte_id=transporte_id,
                tipo=tipo,
                inicio=inicio,
                fin=fin,
                comentario=comentario,
            )
            return {
                'ok': True,
                'codigo': 'PROFORMA_AMPLIADA' if proforma_id else 'PROFORMA_CREADA',
                'proforma': proforma.pk,
                'proforma_extras': proforma_extras.pk if proforma_extras else None,
                'estado': proforma.PRO_CESTADO,
                'total': str(proforma.PRO_NTOTAL),
                'doc_entry': proforma.PRO_DOC_ENTRY,
                'doc_num': proforma.PRO_DOC_NUM,
            }
    except IntegrityError:
        return _resultado_error(
            'CONCURRENCIA',
            'Otra operación creó o modificó esta agrupación. Revise nuevamente el período.',
        )


def resolver_transporte_mensual(
    *, citaciones, empresa_id, transportista_esperado,
):
    """Resuelve el proveedor de transporte sin reescribir citaciones históricas."""
    esperado = _normalizar_nombre(transportista_esperado)
    ids_tarifa = {
        citacion.TAR_NID_id
        for citacion in citaciones
        if citacion.TAR_NID_id
    }
    tarifas = {
        tarifa.pk: tarifa
        for tarifa in TARIFA_GLOBAL.objects.select_for_update().filter(
            pk__in=ids_tarifa,
            EP_NID_id=empresa_id,
        ).only('id', 'EP_NID_id', 'SN_NID_id')
    }
    ids_socios = {
        valor
        for citacion in citaciones
        for valor in (
            citacion.PRO_NID_id,
            getattr(tarifas.get(citacion.TAR_NID_id), 'SN_NID_id', None),
        )
        if valor
    }
    socios = {
        socio.pk: socio
        for socio in SOCIONEGOCIO.objects.select_for_update().filter(
            pk__in=ids_socios
        ).only(
            'id', 'EP_NID_id', 'SN_CRAZONSOCIAL', 'SN_CRUT',
            'SN_CCODIGO_SAP', 'SN_CTIPO', 'SN_BHABILITADO',
        )
    }

    def socio_valido(socio):
        return bool(
            socio
            and socio.EP_NID_id == empresa_id
            and socio.SN_BHABILITADO
            and socio.SN_CTIPO == 'S'
        )

    fallback = list(
        SOCIONEGOCIO.objects.select_for_update().filter(
            EP_NID_id=empresa_id,
            SN_BHABILITADO=True,
            SN_CTIPO='S',
        ).only(
            'id', 'EP_NID_id', 'SN_CRAZONSOCIAL', 'SN_CRUT',
            'SN_CCODIGO_SAP', 'SN_CTIPO', 'SN_BHABILITADO',
        )
    )
    fallback = [
        socio for socio in fallback
        if _normalizar_nombre(socio.SN_CRAZONSOCIAL) == esperado
    ]

    resueltos = []
    fuentes = {}
    for citacion in citaciones:
        if citacion.PRO_NID_id is not None:
            socio = socios.get(citacion.PRO_NID_id)
            fuente = 'CITACION.PRO_NID'
            if not socio_valido(socio):
                return _resultado_error(
                    'TRANSPORTE_FORMAL_INVALIDO',
                    f'El Transporte formal de la citación {citacion.pk} no es válido.',
                    citacion=citacion.pk,
                )
        else:
            if not _es_historica_para_fallback(citacion):
                return _resultado_error(
                    'PRO_NID_REQUERIDO',
                    f'La citación nueva {citacion.pk} requiere PRO_NID.',
                    citacion=citacion.pk,
                )
            tarifa = tarifas.get(citacion.TAR_NID_id)
            socio_tarifa = socios.get(
                getattr(tarifa, 'SN_NID_id', None)
            )
            if socio_valido(socio_tarifa):
                socio = socio_tarifa
                fuente = 'TARIFA_GLOBAL.SN_NID'
            elif len(fallback) == 1:
                socio = fallback[0]
                fuente = 'CAMION_PATIO.NOMBRE_NORMALIZADO'
            else:
                return _resultado_error(
                    'MAESTRO_TRANSPORTE_AMBIGUO',
                    (
                        'No fue posible identificar de forma única el '
                        f'Transporte de la citación {citacion.pk}. '
                        'Revise los datos antes de continuar.'
                    ),
                    citacion=citacion.pk,
                )

        if _normalizar_nombre(socio.SN_CRAZONSOCIAL) != esperado:
            return _resultado_error(
                'TRANSPORTE_INCONSISTENTE',
                (
                    f'El Transporte estructurado de la citación {citacion.pk} '
                    'no coincide con el declarado en patio.'
                ),
                citacion=citacion.pk,
            )
        resueltos.append(socio)
        fuentes[citacion.pk] = fuente

    ids_resueltos = {socio.pk for socio in resueltos}
    if len(ids_resueltos) != 1:
        return _resultado_error(
            'TRANSPORTISTAS_MIXTOS',
            'Las citaciones seleccionadas pertenecen a Transportes distintos.',
        )
    transporte = resueltos[0]
    return {
        'ok': True,
        'codigo': 'TRANSPORTE_RESUELTO',
        'transporte': transporte,
        'fuentes': fuentes,
    }

def continuar_borrador_desde_terminadas(
    *, user, citacion_ids, empresa_id, transportista_esperado,
):
    """Materializa atómicamente el lote seleccionado en un borrador mensual."""
    if not usuario_tiene_permiso_pro_cit(user, PERMISO_INICIAR_PROFORMA):
        return _resultado_error('SIN_PERMISO', 'No tiene permiso para iniciar Proformas.')
    if not usuario_tiene_permiso_pro_cit(user, PERMISO_PROFORMA_CITACIONES):
        return _resultado_error('SIN_PERMISO', 'No tiene permiso para generar Proformas.')
    try:
        empresa_id = int(empresa_id)
        ids = sorted({int(valor) for valor in citacion_ids})
    except (TypeError, ValueError):
        return _resultado_error('PAYLOAD_INVALIDO', 'La selección no es válida.')
    if empresa_id != EMPRESA_TERRAMAR:
        return _resultado_error('EMPRESA_FUERA_ALCANCE', 'Este flujo solo está disponible para Terramar.')
    if not usuario_tiene_empresa(user, empresa_id):
        return _resultado_error('SIN_EMPRESA', 'No tiene acceso a Terramar.')
    if not ids or len(ids) > 500:
        return _resultado_error('PAYLOAD_INVALIDO', 'Seleccione entre 1 y 500 citaciones.')

    esperado = _normalizar_nombre(transportista_esperado)
    if not esperado or esperado == 'CLIENTE':
        return _resultado_error('TRANSPORTISTA_INVALIDO', 'Seleccione un Transporte Terramar válido.')

    try:
        with transaction.atomic():
            citaciones = list(
                CITACION.objects.select_for_update().filter(pk__in=ids).order_by('pk')
            )
            if len(citaciones) != len(ids):
                return _resultado_error('CITACION_INEXISTENTE', MENSAJE_CAMBIO_SELECCION)
            if CITACION_PROFORMA.objects.select_for_update().filter(CI_NID_id__in=ids).exists():
                return _resultado_error('YA_PROFORMADA', MENSAJE_CAMBIO_SELECCION)

            patios = list(
                CAMION_PATIO.objects.select_for_update().filter(
                    CI_NID_id__in=ids,
                    CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
                ).order_by('pk')
            )
            patios_por_citacion = {}
            for patio in patios:
                patios_por_citacion.setdefault(patio.CI_NID_id, []).append(patio)

            tipos = {str(citacion.CI_CTIPO or '').upper() for citacion in citaciones}
            periodos = {periodo_citacion(citacion) for citacion in citaciones}
            if len(tipos) != 1 or next(iter(tipos), None) not in TIPOS_OPERACION or len(periodos) != 1:
                return _resultado_error('GRUPO_INCOMPATIBLE', MENSAJE_CAMBIO_SELECCION)
            tipo = str(citaciones[0].CI_CTIPO).upper()
            inicio, fin = next(iter(periodos))

            for citacion in citaciones:
                patio_citacion = patios_por_citacion.get(citacion.pk, [])
                if (
                    citacion.EP_NID_id != empresa_id
                    or citacion.CI_CESTADO != 'TERMINADO'
                    or not citacion.CI_BHABILITADO
                    or len(patio_citacion) != 1
                ):
                    return _resultado_error('NO_ELEGIBLE', MENSAJE_CAMBIO_SELECCION)
                patio = patio_citacion[0]
                declarado = _normalizar_nombre(patio.CPA_CTRANSPORTISTA_DECLARADO)
                if (
                    patio.EP_NID_id != empresa_id
                    or str(patio.transporte_a_cargo or '').strip().upper() != 'TERRAMAR'
                    or declarado != esperado
                ):
                    return _resultado_error('TRANSPORTISTA_INVALIDO', MENSAJE_CAMBIO_SELECCION)

            resolucion = resolver_transporte_mensual(
                citaciones=citaciones,
                empresa_id=empresa_id,
                transportista_esperado=transportista_esperado,
            )
            if not resolucion['ok']:
                return resolucion
            transporte = resolucion['transporte']

            grupo = PROFORMA.objects.select_for_update().filter(
                EP_NID_id=empresa_id,
                SN_NID_id=transporte.pk,
                PRO_CTIPO=tipo,
                PRO_FPERIODO_INICIO=inicio,
                PRO_FPERIODO_FIN=fin,
            )
            borrador = grupo.filter(
                PRO_CESTADO='CREADO',
                PRO_BBORRADOR=True,
                PRO_DOC_ENTRY__isnull=True,
            ).order_by('-pk').first()

            CITACION.objects.filter(pk__in=ids).update(
                CI_BCONFORME=True,
            )
            resultado = crear_o_ampliar_proforma_mensual(
                user=user,
                citacion_ids=ids,
                empresa_id=empresa_id,
                transporte_id=transporte.pk,
                tipo=tipo,
                periodo=inicio.strftime('%Y-%m'),
                sin_extras=True,
                proforma_id=(borrador.pk if borrador else None),
                transporte_historico_id=(
                    transporte.pk
                    if any(citacion.PRO_NID_id is None for citacion in citaciones)
                    else None
                ),
            )
            if not resultado['ok']:
                transaction.set_rollback(True)
                return resultado

            SYSLOGGER.objects.bulk_create([
                SYSLOGGER(
                    US_NID=user,
                    EP_NID_id=empresa_id,
                    LOG_FFECHAREGISTRO=timezone.now(),
                    LOG_CMODULO='PROFORMA',
                    LOG_COPERACION='BORRADOR_MENSUAL',
                    LOG_CADD1=f'Citacion: {citacion.pk}',
                    LOG_CADD2=f'Proforma: {resultado["proforma"]}',
                    LOG_CDESCRIPCION=(
                        'Citación asociada atómicamente a borrador mensual. '
                        f'Transporte: {transporte.SN_CRAZONSOCIAL}. '
                        f'Tipo: {tipo}. Período: {inicio:%Y-%m}.'
                    ),
                )
                for citacion in citaciones
            ])
            resultado['mensaje'] = (
                f'Proforma borrador N° {resultado["proforma"]} '
                'creada/actualizada correctamente.'
            )
            return resultado
    except IntegrityError:
        return _resultado_error('CONCURRENCIA', MENSAJE_CAMBIO_SELECCION)