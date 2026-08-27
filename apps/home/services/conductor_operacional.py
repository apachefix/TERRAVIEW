import hashlib
import logging
import os
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import get_valid_filename

from apps.home.conductor_utils import RutChilenoInvalido, normalizar_rut_chileno
from apps.home.forms import formCONDUCTOR
from apps.home.models import CONDUCTOR, DOCUMENTO_CONDUCTOR, LISTADO_DOCUMENTO, SOCIONEGOCIO, SYSLOGGER
from apps.home.phone_utils import normalize_international_phone
from apps.home.services.padron_conductores import (
    RUTS_NO_OPERATIVOS_SBH,
    asegurar_membresia_conductor_empresa,
    resolver_conductor_por_rut_sbh,
)
from apps.home.vars import ID_ACEITES_SBH


logger = logging.getLogger(__name__)
LOG_REGISTRA_PATENTE_CONDUCTOR = 'REG_PATENTE_CONDUCTOR'


class AltaConductorOperacionalError(Exception):
    def __init__(self, mensaje, campo=None, errores_formulario=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campo = campo
        self.errores_formulario = errores_formulario


def buscar_conductores_por_rut_normalizado(
        *, empresa, rut_normalizado, bloquear=False, excluir_pk=None):
    """Busca coincidencias tolerando formatos históricos sin asumir unicidad física."""
    if not rut_normalizado:
        return []
    queryset = CONDUCTOR.objects.filter(EP_NID=empresa).exclude(CON_CRUT='')
    if excluir_pk is not None:
        queryset = queryset.exclude(pk=excluir_pk)
    queryset = queryset.only(
        'id', 'CON_CRUT', 'CON_BHABILITADO', 'EP_NID_id',
    ).order_by('-CON_BHABILITADO', 'id')
    if bloquear:
        queryset = queryset.select_for_update()
    coincidencias = []
    for conductor in queryset:
        try:
            rut_existente = normalizar_rut_chileno(conductor.CON_CRUT)
        except RutChilenoInvalido:
            continue
        if rut_existente == rut_normalizado:
            coincidencias.append(conductor)
    return coincidencias


def _bloquear_alta_rut(empresa_id, rut_normalizado):
    if not rut_normalizado or connection.vendor != 'postgresql':
        return
    llave = int.from_bytes(
        hashlib.sha256(f'CONDUCTOR:{empresa_id}:{rut_normalizado}'.encode()).digest()[:8],
        byteorder='big', signed=True,
    )
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [llave])


def diagnostico_duplicidad_rut(
        *, empresa, rut_normalizado, bloquear=False, excluir_pk=None):
    coincidencias = buscar_conductores_por_rut_normalizado(
        empresa=empresa, rut_normalizado=rut_normalizado, bloquear=bloquear,
        excluir_pk=excluir_pk,
    )
    habilitados = sum(bool(item.CON_BHABILITADO) for item in coincidencias)
    return {
        'existe': bool(coincidencias),
        'cantidad': len(coincidencias),
        'habilitados': habilitados,
        'inhabilitados': len(coincidencias) - habilitados,
        'duplicados_historicos': len(coincidencias) > 1,
    }


def formulario_conductor_operacional(post_data=None, *, empresa_id, transporte_id=None, usuario_id):
    if post_data is None:
        formulario = formCONDUCTOR(initial={
            'EP_NID': empresa_id,
            'SN_NID': transporte_id,
            'US_NID': usuario_id,
            'CON_BHABILITADO': True,
            'CON_NPERIODO_EXTRA': 10,
        })
        formulario.fields['CON_CRUT'].required = False
        for campo in ('CON_CNOMBRE', 'CON_CAPELLIDO', 'CON_CTELEFONO', 'CON_CEMAIL'):
            formulario.fields[campo].required = True
        return formulario

    datos = post_data.copy()
    datos['EP_NID'] = str(empresa_id)
    datos['SN_NID'] = str(transporte_id)
    datos['US_NID'] = str(usuario_id)
    datos['CON_BHABILITADO'] = 'on'
    datos['CON_NPERIODO_EXTRA'] = '10'
    datos.setdefault('CON_CRUT', '')
    formulario = formCONDUCTOR(datos)
    formulario.fields['CON_CRUT'].required = False
    for campo in ('CON_CNOMBRE', 'CON_CAPELLIDO', 'CON_CTELEFONO', 'CON_CEMAIL'):
        formulario.fields[campo].required = True
    return formulario


def crear_conductor_operacional(*, post_data, files, usuario, empresa, transporte, base_folder):
    formulario = formulario_conductor_operacional(
        post_data,
        empresa_id=empresa.pk,
        transporte_id=transporte.pk,
        usuario_id=usuario.pk,
    )
    if not formulario.is_valid():
        mensajes = {
            'CON_CNOMBRE': 'Debe ingresar el nombre del conductor.',
            'CON_CAPELLIDO': 'Debe ingresar el apellido del conductor.',
            'CON_CEMAIL': 'Debe ingresar el correo electrónico del conductor.',
            'CON_CTELEFONO': 'Debe ingresar el teléfono del conductor.',
            'SN_NID': 'Debe seleccionar un Transporte válido.',
        }
        campo = next(iter(formulario.errors), None)
        logger.warning(
            'Alta operacional de conductor inválida. usuario=%s empresa=%s campos_post=%s errores=%s',
            usuario.pk, empresa.pk, sorted(post_data.keys()), formulario.errors.as_json(),
        )
        raise AltaConductorOperacionalError(
            mensajes.get(campo, 'Revise los datos ingresados.'),
            campo=campo,
            errores_formulario=formulario.errors,
        )

    try:
        rut = normalizar_rut_chileno(formulario.cleaned_data.get('CON_CRUT'))
    except RutChilenoInvalido as exc:
        raise AltaConductorOperacionalError(str(exc), campo='CON_CRUT') from exc
    if empresa.pk == ID_ACEITES_SBH and not rut:
        raise AltaConductorOperacionalError(
            'Debe ingresar un RUT válido para incorporarlo al padrón operativo SBH.',
            campo='CON_CRUT',
        )

    correo = str(formulario.cleaned_data.get('CON_CEMAIL') or '').strip()
    try:
        validate_email(correo)
    except ValidationError as exc:
        raise AltaConductorOperacionalError(
            'Ingrese un correo electrónico válido.', campo='CON_CEMAIL',
        ) from exc

    try:
        telefono = normalize_international_phone(
            '+56', formulario.cleaned_data.get('CON_CTELEFONO'), required=True,
        )
    except ValueError as exc:
        raise AltaConductorOperacionalError(str(exc), campo='CON_CTELEFONO') from exc

    archivo = files.get('licencia_archivo')
    if not archivo:
        raise AltaConductorOperacionalError(
            'Debe adjuntar la licencia de conducir.', campo='licencia_archivo',
        )
    vencimiento_texto = str(post_data.get('licencia_fecha_vencimiento') or '').strip()
    if not vencimiento_texto:
        raise AltaConductorOperacionalError(
            'Debe ingresar la fecha de vencimiento de la licencia.',
            campo='licencia_fecha_vencimiento',
        )
    fecha_vencimiento = parse_date(vencimiento_texto)
    if fecha_vencimiento is None:
        raise AltaConductorOperacionalError(
            'La fecha de vencimiento de la licencia no es válida.',
            campo='licencia_fecha_vencimiento',
        )

    # El esquema actual declara DCON_FFECHAEMISION NOT NULL; no se inventa una fecha.
    emision_texto = str(post_data.get('licencia_fecha_emision') or '').strip()
    if not emision_texto:
        raise AltaConductorOperacionalError(
            'Debe ingresar la fecha de emisión de la licencia.',
            campo='licencia_fecha_emision',
        )
    fecha_emision = parse_date(emision_texto)
    if fecha_emision is None:
        raise AltaConductorOperacionalError(
            'La fecha de emisión de la licencia no es válida.',
            campo='licencia_fecha_emision',
        )

    tipo_licencia = LISTADO_DOCUMENTO.objects.filter(
        EP_NID=empresa,
        LIS_CGRUPO__iexact='Conductor',
        LIS_CNOMBREDOCUMENTO__iexact='LICENCIA DE CONDUCIR',
        LIS_BHABILITADO=True,
    ).values_list('LIS_CNOMBREDOCUMENTO', flat=True).first()
    if not tipo_licencia:
        raise AltaConductorOperacionalError(
            'No existe un tipo documental habilitado para LICENCIA DE CONDUCIR.'
        )

    patente = str(post_data.get('patente_informada') or '').strip().upper()[:128]
    file_path = None
    folder_path = None
    try:
        with transaction.atomic():
            _bloquear_alta_rut(empresa.pk, rut)
            conductor = None
            if empresa.pk == ID_ACEITES_SBH and rut:
                if rut in RUTS_NO_OPERATIVOS_SBH:
                    raise AltaConductorOperacionalError(
                        'El RUT corresponde a un registro genérico o legado y no puede incorporarse al padrón SBH.',
                        campo='CON_CRUT',
                    )
                resolucion = resolver_conductor_por_rut_sbh(rut, bloquear=True)
                if resolucion['estado'] == 'conflicto':
                    raise AltaConductorOperacionalError(
                        'El RUT tiene múltiples conductores habilitados; no se puede asociar SBH automáticamente.',
                        campo='CON_CRUT',
                    )
                if resolucion['estado'] == 'encontrado':
                    conductor = resolucion['conductor']
                    asegurar_membresia_conductor_empresa(
                        conductor=conductor, empresa=empresa, usuario=usuario,
                    )
                elif resolucion['estado'] == 'inhabilitado_o_generico':
                    raise AltaConductorOperacionalError(
                        'El RUT pertenece a un conductor inhabilitado o genérico y no puede incorporarse a SBH.',
                        campo='CON_CRUT',
                    )

            if conductor is None:
                duplicidad = diagnostico_duplicidad_rut(
                    empresa=empresa, rut_normalizado=rut, bloquear=True,
                )
                if duplicidad['habilitados']:
                    mensaje = (
                        'RUT ya existe. No se puede crear nuevamente el conductor. '
                        f'Este conductor ya se encuentra registrado en {empresa.EP_CRAZONSOCIAL} '
                        'y puede utilizarse con otro Transporte en Planificación.'
                    )
                    if duplicidad['duplicados_historicos']:
                        mensaje += (
                            ' Existen registros históricos duplicados para este RUT; '
                            'no se creará un nuevo conductor.'
                        )
                    raise AltaConductorOperacionalError(mensaje, campo='CON_CRUT')
                if duplicidad['inhabilitados']:
                    raise AltaConductorOperacionalError(
                        'Este conductor ya existe en esta empresa pero se encuentra inhabilitado. '
                        'Revise o reactive el registro mediante el flujo existente.',
                        campo='CON_CRUT',
                    )
                conductor = formulario.save(commit=False)
                conductor.EP_NID = empresa
                conductor.SN_NID = transporte
                conductor.US_NID = usuario
                conductor.CON_CRUT = rut
                conductor.CON_CEMAIL = correo
                conductor.CON_CCODIGO_PAIS_TELEFONO = telefono['country_code']
                conductor.CON_CTELEFONO = telefono['local_number']
                conductor.CON_NPERIODO_EXTRA = 10
                conductor.CON_FFECHAREGISTRO = timezone.now()
                conductor.CON_BHABILITADO = True
                conductor.save()
                if empresa.pk == ID_ACEITES_SBH:
                    asegurar_membresia_conductor_empresa(
                        conductor=conductor, empresa=empresa, usuario=usuario,
                    )

            carpeta = rut or f'CONDUCTOR_{conductor.pk}'
            folder_path = os.path.join(base_folder, carpeta)
            os.makedirs(folder_path, exist_ok=True)
            extension = os.path.splitext(get_valid_filename(archivo.name))[1].lower()
            file_path = os.path.join(folder_path, f'{uuid.uuid4()}{extension}')
            with open(file_path, 'wb+') as destino:
                for chunk in archivo.chunks():
                    destino.write(chunk)

            dias = (fecha_vencimiento - timezone.localdate()).days
            estado = 'VENCIDO' if dias <= 0 else ('POR VENCER' if dias <= 30 else 'VIGENTE')
            documento = DOCUMENTO_CONDUCTOR.objects.create(
                EP_NID=empresa, CON_NID=conductor, US_NID=usuario,
                DCON_CTIPO=tipo_licencia, DCON_CESTADO=estado,
                DCON_CRUTADOC=file_path, DCON_FFECHAREGISTRO=timezone.now(),
                DCON_FFECHAEMISION=fecha_emision,
                DCON_FFECHAVENCIMIENTO=fecha_vencimiento,
                DCON_BHABILITADO=True,
            )
            if patente:
                SYSLOGGER.objects.create(
                    US_NID=usuario, EP_NID=empresa,
                    LOG_FFECHAREGISTRO=timezone.now(),
                    LOG_CMODULO='CONTROL_FLOTA',
                    LOG_COPERACION=LOG_REGISTRA_PATENTE_CONDUCTOR,
                    LOG_CADD1=str(conductor.pk), LOG_CADD2=patente,
                    LOG_CDESCRIPCION=(
                        'Patente informada al registrar conductor. '
                        'No representa asociación permanente conductor-camión.'
                    ),
                )
    except AltaConductorOperacionalError:
        raise
    except Exception:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if folder_path and os.path.isdir(folder_path) and not os.listdir(folder_path):
            os.rmdir(folder_path)
        logger.exception(
            'Error transaccional en alta operacional de conductor. usuario=%s empresa=%s transporte=%s',
            usuario.pk, empresa.pk, transporte.pk,
        )
        raise AltaConductorOperacionalError(
            'No fue posible guardar el conductor y su licencia. No se guardaron cambios parciales.'
        )
    return conductor, documento, estado, patente, formulario


def formulario_edicion_conductor_operacional(
        post_data=None, *, conductor, usuario, puede_deshabilitar=False):
    if post_data is None:
        formulario = formCONDUCTOR(instance=conductor)
    else:
        datos = post_data.copy()
        datos['EP_NID'] = str(conductor.EP_NID_id)
        datos['US_NID'] = str(conductor.US_NID_id or usuario.pk)
        datos['CON_NPERIODO_EXTRA'] = str(conductor.CON_NPERIODO_EXTRA)
        if not puede_deshabilitar:
            datos['CON_BHABILITADO'] = 'on' if conductor.CON_BHABILITADO else ''
        datos.setdefault('CON_CRUT', '')
        formulario = formCONDUCTOR(datos, instance=conductor)
    formulario.fields['SN_NID'].queryset = SOCIONEGOCIO.objects.filter(
        EP_NID=conductor.EP_NID, SN_CTIPO='S', SN_BHABILITADO=True,
    )
    formulario.fields['CON_CRUT'].required = False
    formulario.fields['CON_CEMAIL'].required = False
    formulario.fields['CON_CTELEFONO'].required = False
    return formulario


def actualizar_conductor_operacional(
        *, post_data, files, usuario, conductor, base_folder,
        puede_deshabilitar=False):
    formulario = formulario_edicion_conductor_operacional(
        post_data, conductor=conductor, usuario=usuario,
        puede_deshabilitar=puede_deshabilitar,
    )
    if not formulario.is_valid():
        campo = next(iter(formulario.errors), None)
        raise AltaConductorOperacionalError(
            'Revise los datos ingresados.', campo=campo,
            errores_formulario=formulario.errors,
        )
    try:
        rut = normalizar_rut_chileno(formulario.cleaned_data.get('CON_CRUT'))
    except RutChilenoInvalido as exc:
        raise AltaConductorOperacionalError(str(exc), campo='CON_CRUT') from exc

    correo = str(formulario.cleaned_data.get('CON_CEMAIL') or '').strip()
    if correo:
        try:
            validate_email(correo)
        except ValidationError as exc:
            raise AltaConductorOperacionalError(
                'Ingrese un correo electrÃ³nico vÃ¡lido.', campo='CON_CEMAIL',
            ) from exc
    try:
        telefono = normalize_international_phone(
            conductor.CON_CCODIGO_PAIS_TELEFONO or '+56',
            formulario.cleaned_data.get('CON_CTELEFONO'), required=False,
        )
    except ValueError as exc:
        raise AltaConductorOperacionalError(str(exc), campo='CON_CTELEFONO') from exc

    archivo = files.get('licencia_archivo')
    licencia_actual = DOCUMENTO_CONDUCTOR.objects.filter(
        EP_NID=conductor.EP_NID, CON_NID=conductor,
        DCON_CTIPO__iexact='LICENCIA DE CONDUCIR', DCON_BHABILITADO=True,
    ).order_by('-DCON_FFECHAREGISTRO', '-id').first()
    requiere_fechas = bool(licencia_actual or archivo)
    emision_texto = str(post_data.get('licencia_fecha_emision') or '').strip()
    vencimiento_texto = str(post_data.get('licencia_fecha_vencimiento') or '').strip()
    fecha_emision = parse_date(emision_texto) if emision_texto else None
    fecha_vencimiento = parse_date(vencimiento_texto) if vencimiento_texto else None
    if requiere_fechas and not fecha_emision:
        raise AltaConductorOperacionalError(
            'Debe ingresar una fecha de emisiÃ³n vÃ¡lida.', campo='licencia_fecha_emision',
        )
    if requiere_fechas and not fecha_vencimiento:
        raise AltaConductorOperacionalError(
            'Debe ingresar una fecha de vencimiento vÃ¡lida.', campo='licencia_fecha_vencimiento',
        )

    tipo_licencia = None
    if archivo:
        tipo_licencia = LISTADO_DOCUMENTO.objects.filter(
            EP_NID=conductor.EP_NID,
            LIS_CGRUPO__iexact='Conductor',
            LIS_CNOMBREDOCUMENTO__iexact='LICENCIA DE CONDUCIR',
            LIS_BHABILITADO=True,
        ).values_list('LIS_CNOMBREDOCUMENTO', flat=True).first()
        if not tipo_licencia:
            raise AltaConductorOperacionalError(
                'No existe un tipo documental habilitado para LICENCIA DE CONDUCIR.'
            )

    file_path = None
    folder_path = None
    try:
        with transaction.atomic():
            conductor_bloqueado = CONDUCTOR.objects.select_for_update().get(
                pk=conductor.pk, EP_NID=conductor.EP_NID,
            )
            rut_original = normalizar_rut_chileno(conductor_bloqueado.CON_CRUT)
            if rut != rut_original:
                _bloquear_alta_rut(conductor.EP_NID_id, rut)
                duplicidad = diagnostico_duplicidad_rut(
                    empresa=conductor.EP_NID, rut_normalizado=rut,
                    bloquear=True, excluir_pk=conductor.pk,
                )
                if duplicidad['habilitados']:
                    raise AltaConductorOperacionalError(
                        'RUT ya existe. No se puede asignar a este conductor.',
                        campo='CON_CRUT',
                    )
                if duplicidad['inhabilitados']:
                    raise AltaConductorOperacionalError(
                        'Este RUT pertenece a un conductor inhabilitado en esta empresa.',
                        campo='CON_CRUT',
                    )

            actualizado = formulario.save(commit=False)
            actualizado.EP_NID = conductor.EP_NID
            actualizado.US_NID = conductor.US_NID or usuario
            actualizado.CON_FFECHAREGISTRO = conductor_bloqueado.CON_FFECHAREGISTRO
            actualizado.CON_NPERIODO_EXTRA = conductor_bloqueado.CON_NPERIODO_EXTRA
            actualizado.CON_CRUT = rut
            actualizado.CON_CEMAIL = correo
            actualizado.CON_CCODIGO_PAIS_TELEFONO = telefono['country_code'] if telefono else ''
            actualizado.CON_CTELEFONO = telefono['local_number'] if telefono else ''
            if not puede_deshabilitar:
                actualizado.CON_BHABILITADO = conductor_bloqueado.CON_BHABILITADO
            actualizado.save()

            documentos_activos = DOCUMENTO_CONDUCTOR.objects.select_for_update().filter(
                EP_NID=conductor.EP_NID, CON_NID=conductor,
                DCON_CTIPO__iexact='LICENCIA DE CONDUCIR', DCON_BHABILITADO=True,
            ).order_by('-DCON_FFECHAREGISTRO', '-id')
            licencia_bloqueada = documentos_activos.first()
            estado = None
            if requiere_fechas:
                dias = (fecha_vencimiento - timezone.localdate()).days
                estado = 'VENCIDO' if dias <= 0 else ('POR VENCER' if dias <= 30 else 'VIGENTE')
            if archivo:
                carpeta = rut or f'CONDUCTOR_{conductor.pk}'
                folder_path = os.path.join(base_folder, carpeta)
                os.makedirs(folder_path, exist_ok=True)
                extension = os.path.splitext(get_valid_filename(archivo.name))[1].lower()
                file_path = os.path.join(folder_path, f'{uuid.uuid4()}{extension}')
                with open(file_path, 'wb+') as destino:
                    for chunk in archivo.chunks():
                        destino.write(chunk)
                documentos_activos.update(DCON_BHABILITADO=False)
                DOCUMENTO_CONDUCTOR.objects.create(
                    EP_NID=conductor.EP_NID, CON_NID=conductor, US_NID=usuario,
                    DCON_CTIPO=tipo_licencia, DCON_CESTADO=estado,
                    DCON_CRUTADOC=file_path, DCON_FFECHAREGISTRO=timezone.now(),
                    DCON_FFECHAEMISION=fecha_emision,
                    DCON_FFECHAVENCIMIENTO=fecha_vencimiento,
                    DCON_BHABILITADO=True,
                )
                operacion = 'REEMPLAZA_LIC_CONDUCTOR' if licencia_bloqueada else 'CARGA_LIC_CONDUCTOR'
            elif licencia_bloqueada:
                licencia_bloqueada.DCON_FFECHAEMISION = fecha_emision
                licencia_bloqueada.DCON_FFECHAVENCIMIENTO = fecha_vencimiento
                licencia_bloqueada.DCON_CESTADO = estado
                licencia_bloqueada.US_NID = usuario
                licencia_bloqueada.save(update_fields=[
                    'DCON_FFECHAEMISION', 'DCON_FFECHAVENCIMIENTO',
                    'DCON_CESTADO', 'US_NID',
                ])
                operacion = 'ACTUALIZA_LIC_CONDUCTOR'
            else:
                operacion = 'ACTUALIZA_CONDUCTOR'
            SYSLOGGER.objects.create(
                US_NID=usuario, EP_NID=conductor.EP_NID,
                LOG_FFECHAREGISTRO=timezone.now(), LOG_CMODULO='CONTROL_FLOTA',
                LOG_COPERACION=operacion, LOG_CADD1=str(conductor.pk),
                LOG_CADD2=str(getattr(licencia_bloqueada, 'pk', '') or ''),
                LOG_CDESCRIPCION='ActualizaciÃ³n moderna de conductor y licencia.',
            )
    except AltaConductorOperacionalError:
        raise
    except Exception:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if folder_path and os.path.isdir(folder_path) and not os.listdir(folder_path):
            os.rmdir(folder_path)
        logger.exception(
            'Error transaccional al actualizar conductor. usuario=%s conductor=%s',
            usuario.pk, conductor.pk,
        )
        raise AltaConductorOperacionalError(
            'No fue posible actualizar el conductor y su licencia. No se guardaron cambios parciales.'
        )
    return actualizado, estado, formulario
