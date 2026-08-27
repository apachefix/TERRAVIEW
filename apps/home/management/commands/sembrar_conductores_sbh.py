from django.core.management.base import BaseCommand, CommandError

from apps.home.services.padron_conductores import (
    cargar_ruts_sbh_desde_csv,
    sembrar_conductores_sbh_desde_ruts,
)


class Command(BaseCommand):
    help = 'Crea membresías operativas SBH desde un CSV con columna RUT.'

    def add_arguments(self, parser):
        parser.add_argument('--archivo', required=True, help='CSV UTF-8 con columna RUT.')
        parser.add_argument('--dry-run', action='store_true', help='Informa resultados sin escribir.')

    def handle(self, *args, **options):
        try:
            ruts = cargar_ruts_sbh_desde_csv(options['archivo'])
            resultado = sembrar_conductores_sbh_desde_ruts(
                ruts, dry_run=options['dry_run'],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        modo = 'DRY-RUN' if options['dry_run'] else 'APLICADO'
        self.stdout.write(
            f"{modo}: fuente={resultado['fuente']}; recibidos={len(resultado['ruts_recibidos'])}; "
            f"encontrados_unicos={len(resultado['encontrados'])}; "
            f"ya_asociados={len(resultado['ya_asociados'])}; "
            f"nuevas_membresias={len(resultado['nuevas_membresias'])}; "
            f"conflictos={len(resultado['conflictos'])}; no_encontrados={len(resultado['no_encontrados'])}; "
            f"inhabilitados_o_genericos={len(resultado['inhabilitados_o_genericos'])}; "
            f"ruts_invalidos={len(resultado['ruts_invalidos'])}."
        )
        for clave in ('conflictos', 'no_encontrados', 'inhabilitados_o_genericos', 'ruts_invalidos', 'duplicados_fuente'):
            if resultado[clave]:
                self.stdout.write(f'{clave}: {resultado[clave]}')
