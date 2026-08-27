from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.home.models import PERFIL, PERMISO, VISTA
from apps.home.services.proforma_service import (
    PERMISO_INICIAR_PROFORMA,
    PERMISO_PROFORMA_CITACIONES,
)


class Command(BaseCommand):
    help = (
        'Asigna al perfil CONTROL_FLOTA los permisos mínimos de consulta e '
        'inicio de Proforma. No crea perfiles ni usuarios.'
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

        resultados = []
        for codigo in (
            PERMISO_INICIAR_PROFORMA,
            PERMISO_PROFORMA_CITACIONES,
        ):
            vistas = VISTA.objects.filter(
                VI_CCODIGO=codigo, VI_BHABILITADO=True,
            )
            if vistas.count() != 1:
                raise CommandError(
                    f'Debe existir exactamente una vista habilitada {codigo}.'
                )
            vista = vistas.get()
            _, creado = PERMISO.objects.update_or_create(
                PR_NID=perfil,
                VI_NID=vista,
                defaults={
                    'US_NID': perfil.US_NID,
                    'PE_BHABILITADO': True,
                },
            )
            resultados.append((codigo, creado))

        if options['dry_run']:
            transaction.set_rollback(True)

        modo = 'DRY-RUN' if options['dry_run'] else 'APLICADO'
        self.stdout.write(self.style.SUCCESS(
            f'{modo}: acceso mínimo de Proforma para CONTROL_FLOTA.'
        ))
        for codigo, creado in resultados:
            self.stdout.write(
                f'- {codigo}: permiso={"creado" if creado else "actualizado"}'
            )
        self.stdout.write(
            'Sin permisos de autorización SAP, eliminación, edición, extras '
            'ni Proforma manual.'
        )
