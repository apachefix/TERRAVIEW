from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.home.models import PERFIL, PERMISO, VISTA


class Command(BaseCommand):
    help = 'Crea o actualiza de forma idempotente el perfil PRO_CIT y sus permisos. No crea usuarios.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--actor-username',
            required=True,
            help='Usuario existente que quedará registrado como creador de la configuración.',
        )
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        try:
            actor = User.objects.get(username=options['actor_username'])
        except User.DoesNotExist as exc:
            raise CommandError('El usuario actor no existe. El comando no crea usuarios.') from exc

        perfil, perfil_creado = PERFIL.objects.update_or_create(
            PR_CCODIGO='PRO_CIT',
            defaults={
                'US_NID': actor,
                'PR_CNOMBRE': 'Proforma Citaciones',
                'PR_CDESCRIPCION': 'Inicia proformas y consulta citaciones habilitadas.',
                'PR_BHABILITADO': True,
            },
        )

        resultados = []
        for codigo, nombre, descripcion in (
            ('iniciar_proforma', 'iniciar_proforma', 'Iniciar proforma desde el detalle de una citación.'),
            ('proforma_citaciones', 'proforma_citaciones', 'Consultar Proformas > Citaciones.'),
        ):
            vista, vista_creada = VISTA.objects.update_or_create(
                VI_CCODIGO=codigo,
                defaults={
                    'US_NID': actor,
                    'VI_CNOMBRE': nombre,
                    'VI_CDESCRIPCION': descripcion,
                    'VI_BHABILITADO': True,
                },
            )
            permiso, permiso_creado = PERMISO.objects.update_or_create(
                PR_NID=perfil,
                VI_NID=vista,
                defaults={'US_NID': actor, 'PE_BHABILITADO': True},
            )
            resultados.append((codigo, vista_creada, permiso_creado))

        if options['dry_run']:
            transaction.set_rollback(True)

        modo = 'DRY-RUN' if options['dry_run'] else 'APLICADO'
        self.stdout.write(self.style.SUCCESS(f'{modo}: PRO_CIT {"creado" if perfil_creado else "actualizado"}.'))
        for codigo, vista_creada, permiso_creado in resultados:
            self.stdout.write(
                f'- {codigo}: vista={"creada" if vista_creada else "actualizada"}, '
                f'permiso={"creado" if permiso_creado else "actualizado"}'
            )
        self.stdout.write('No se creó ni modificó ningún usuario.')
