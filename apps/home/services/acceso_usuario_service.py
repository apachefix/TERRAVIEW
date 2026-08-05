from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.home.models import EMPRESA, PERFIL, PERFIL_USUARIO, PERMISO, SYSLOGGER, USERS_EMPRESA


ROL_ASISTENTE_CD = {'ASISTENTE C D', 'ASISTENTE CD'}
PERFIL_CANONICO_ASISTENTE_CD = ('ASISTENTE_CD', 'ASISTENTE CD')


def _normalizar(valor):
    return ' '.join(str(valor or '').upper().replace('_', ' ').replace('-', ' ').split())


@dataclass
class ResumenClonacionAcceso:
    origen: str
    destino: str
    empresa_id: int
    perfiles: list = field(default_factory=list)
    permisos: list = field(default_factory=list)
    empresas_eliminadas: list = field(default_factory=list)
    perfil_heredado: str = ''
    dry_run: bool = False


def _perfiles_habilitados(usuario):
    return list(
        PERFIL_USUARIO.objects.select_related('PR_NID').filter(
            US_NID=usuario,
            PE_BHABILITADO=True,
            PR_NID__PR_BHABILITADO=True,
        ).order_by('PR_NID_id', 'id')
    )


def sincronizar_acceso_usuario(origen_username, destino_username, empresa_id, dry_run=False):
    User = get_user_model()
    with transaction.atomic():
        origen = User.objects.get(username=origen_username)
        destino = User.objects.get(username=destino_username)
        empresa = EMPRESA.objects.get(pk=empresa_id)
        if empresa_id != 1 or _normalizar(empresa.EP_CRAZONSOCIAL) != 'TERRAMAR CHILE':
            raise ValueError('La empresa autorizada debe ser EMPRESA.id=1, TERRAMAR CHILE.')

        perfiles_origen = _perfiles_habilitados(origen)
        perfil_heredado = ''
        perfiles_objetivo = [fila.PR_NID for fila in perfiles_origen]

        # Compatibilidad de roles heredados: el rol se transforma en PERFIL,
        # nunca se concede por el username del destino.
        if not perfiles_objetivo and _normalizar(origen.username) in ROL_ASISTENTE_CD:
            perfil_heredado = PERFIL_CANONICO_ASISTENTE_CD[0]
            perfil_existente = PERFIL.objects.filter(
                PR_CCODIGO=PERFIL_CANONICO_ASISTENTE_CD[0]
            ).first()
            if perfil_existente:
                perfiles_objetivo = [perfil_existente]

        permisos_origen = list(PERMISO.objects.filter(US_NID=origen).select_related('PR_NID', 'VI_NID'))

        resumen = ResumenClonacionAcceso(
            origen=origen.username,
            destino=destino.username,
            empresa_id=empresa.id,
            perfiles=[perfil.PR_CCODIGO for perfil in perfiles_objetivo] or ([perfil_heredado] if perfil_heredado else []),
            permisos=[
                (permiso.PR_NID_id, permiso.VI_NID_id, permiso.PE_BHABILITADO)
                for permiso in permisos_origen
            ],
            empresas_eliminadas=list(
                USERS_EMPRESA.objects.filter(US_NID=destino).exclude(EP_NID=empresa)
                .values_list('EP_NID_id', flat=True)
            ),
            perfil_heredado=perfil_heredado,
            dry_run=dry_run,
        )
        if dry_run:
            transaction.set_rollback(True)
            return resumen

        if perfil_heredado and not perfiles_objetivo:
            perfil, _ = PERFIL.objects.get_or_create(
                PR_CCODIGO=PERFIL_CANONICO_ASISTENTE_CD[0],
                defaults={
                    'US_NID': origen,
                    'PR_CNOMBRE': PERFIL_CANONICO_ASISTENTE_CD[1],
                    'PR_CDESCRIPCION': 'Rol operativo de Asistente CD.',
                    'PR_BHABILITADO': True,
                },
            )
            if not perfil.PR_BHABILITADO:
                perfil.PR_BHABILITADO = True
                perfil.save(update_fields=['PR_BHABILITADO'])
            perfiles_objetivo = [perfil]
            resumen.perfiles = [perfil.PR_CCODIGO]

        perfiles_ids = [perfil.id for perfil in perfiles_objetivo]
        PERFIL_USUARIO.objects.filter(US_NID=destino).exclude(PR_NID_id__in=perfiles_ids).update(PE_BHABILITADO=False)
        for perfil in perfiles_objetivo:
            asignaciones = PERFIL_USUARIO.objects.filter(US_NID=destino, PR_NID=perfil).order_by('id')
            asignacion = asignaciones.first()
            if asignacion:
                if not asignacion.PE_BHABILITADO:
                    asignacion.PE_BHABILITADO = True
                    asignacion.save(update_fields=['PE_BHABILITADO'])
                asignaciones.exclude(pk=asignacion.pk).update(PE_BHABILITADO=False)
            else:
                PERFIL_USUARIO.objects.create(US_NID=destino, PR_NID=perfil, PE_BHABILITADO=True)

        for permiso in permisos_origen:
            existente = PERMISO.objects.filter(
                US_NID=destino,
                PR_NID=permiso.PR_NID,
                VI_NID=permiso.VI_NID,
            ).order_by('id').first()
            if existente:
                if existente.PE_BHABILITADO != permiso.PE_BHABILITADO:
                    existente.PE_BHABILITADO = permiso.PE_BHABILITADO
                    existente.save(update_fields=['PE_BHABILITADO'])
            else:
                PERMISO.objects.create(
                    US_NID=destino,
                    PR_NID=permiso.PR_NID,
                    VI_NID=permiso.VI_NID,
                    PE_BHABILITADO=permiso.PE_BHABILITADO,
                )

        USERS_EMPRESA.objects.filter(US_NID=destino).exclude(EP_NID=empresa).delete()
        USERS_EMPRESA.objects.get_or_create(US_NID=destino, EP_NID=empresa)

        SYSLOGGER.objects.create(
            US_NID=origen,
            EP_NID=empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_CMODULO='SEGURIDAD',
            LOG_COPERACION='CLONAR_ACCESO_USUARIO',
            LOG_CDESCRIPCION=(
                f'Acceso sincronizado desde {origen.username} hacia {destino.username}; '
                f'empresa restringida a {empresa.EP_CRAZONSOCIAL}.'
            ),
            LOG_CADD1=str(destino.id),
            LOG_CADD2=','.join(resumen.perfiles)[:128],
        )
        return resumen