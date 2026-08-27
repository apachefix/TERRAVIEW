from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.home.models import PERFIL, PERMISO, VISTA
from apps.home.services.proforma_service import PERMISO_BORRAR_PROFORMA


class Command(BaseCommand):
    help = (
        'Crea/reutiliza el permiso mínimo para borrar borradores Terramar y '
        'lo asigna exclusivamente al perfil CONTROL_FLOTA.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        perfiles = PERFIL.objects.filter(
            PR_CCODIGO='CONTROL_FLOTA', PR_BHABILITADO=True,
        )
        if perfiles.count() != 1:
            raise CommandError(
                'Debe existir exactamente un perfil CONTROL_FLOTA habilitado.'
            )
        perfil = perfiles.get()
        vistas = VISTA.objects.filter(VI_CCODIGO=PERMISO_BORRAR_PROFORMA)
        if vistas.count() > 1:
            raise CommandError(
                f'Existe más de una VISTA {PERMISO_BORRAR_PROFORMA}; corrija el maestro.'
            )
        if vistas.exists():
            vista = vistas.get()
            vista.VI_BHABILITADO = True
            vista.VI_CNOMBRE = 'Borrar carpeta de Proforma borrador'
            vista.VI_CDESCRIPCION = (
                'Deshace exclusivamente borradores mensuales Terramar sin SAP.'
            )
            vista.save(update_fields=[
                'VI_BHABILITADO', 'VI_CNOMBRE', 'VI_CDESCRIPCION'
            ])
            vista_creada = False
        else:
            vista = VISTA.objects.create(
                US_NID=perfil.US_NID,
                VI_CCODIGO=PERMISO_BORRAR_PROFORMA,
                VI_CNOMBRE='Borrar carpeta de Proforma borrador',
                VI_CDESCRIPCION=(
                    'Deshace exclusivamente borradores mensuales Terramar sin SAP.'
                ),
                VI_BHABILITADO=True,
            )
            vista_creada = True
        permisos = PERMISO.objects.filter(PR_NID=perfil, VI_NID=vista)
        if permisos.count() > 1:
            raise CommandError('Existe más de un PERMISO para CONTROL_FLOTA y la VISTA.')
        if permisos.exists():
            permiso = permisos.get()
            permiso.PE_BHABILITADO = True
            permiso.save(update_fields=['PE_BHABILITADO'])
            permiso_creado = False
        else:
            PERMISO.objects.create(
                US_NID=perfil.US_NID,
                PR_NID=perfil,
                VI_NID=vista,
                PE_BHABILITADO=True,
            )
            permiso_creado = True
        if options['dry_run']:
            transaction.set_rollback(True)
        modo = 'DRY-RUN' if options['dry_run'] else 'APLICADO'
        self.stdout.write(self.style.SUCCESS(
            f'{modo}: {PERMISO_BORRAR_PROFORMA} asignado solo a CONTROL_FLOTA.'
        ))
        self.stdout.write(
            f'VISTA: {"creada" if vista_creada else "actualizada"}; '
            f'PERMISO: {"creado" if permiso_creado else "actualizado"}.'
        )