from django.core.management.base import BaseCommand, CommandError

from apps.home.services.acceso_usuario_service import sincronizar_acceso_usuario


class Command(BaseCommand):
    help = 'Clona el acceso efectivo de un usuario y restringe al destino a una empresa.'

    def add_arguments(self, parser):
        parser.add_argument('--origen', required=True)
        parser.add_argument('--destino', required=True)
        parser.add_argument('--empresa-id', required=True, type=int)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **options):
        if not options['confirm'] and not options['dry_run']:
            raise CommandError('Use --confirm para aplicar cambios o --dry-run para revisar el plan.')

        try:
            resumen = sincronizar_acceso_usuario(
                options['origen'], options['destino'], options['empresa_id'],
                dry_run=options['dry_run'],
            )
        except (ValueError, LookupError) as exc:
            raise CommandError(str(exc))

        self.stdout.write(f'Origen: {resumen.origen}; destino: {resumen.destino}')
        self.stdout.write(f'Perfiles: {resumen.perfiles or "ninguno"}')
        self.stdout.write(f'Permisos directos: {len(resumen.permisos)}')
        self.stdout.write(f'Empresas a retirar: {resumen.empresas_eliminadas or "ninguna"}')
        if resumen.perfil_heredado:
            self.stdout.write(f'Rol heredado normalizado: {resumen.perfil_heredado}')
        self.stdout.write(self.style.WARNING('Dry-run: sin cambios.') if resumen.dry_run else self.style.SUCCESS('Sincronización completada.'))