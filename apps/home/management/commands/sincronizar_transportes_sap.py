from django.core.management.base import BaseCommand, CommandError

from apps.home.services.transportes_sap import (
    EMPRESAS_TRANSPORTES_SAP,
    sincronizar_transportes_sap,
)


class Command(BaseCommand):
    help = 'Sincroniza transportistas OCRD activos desde SAP hacia SOCIONEGOCIO.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa',
            action='append',
            type=int,
            choices=EMPRESAS_TRANSPORTES_SAP,
            help='Empresa TERRAVIEW a sincronizar: 1 (Terramar) o 2 (SBH).',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Sincroniza Terramar (1) y SBH (2).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Consulta SAP y muestra resultados sin escribir PostgreSQL.',
        )

    def handle(self, *args, **options):
        empresas = options['empresa'] or []
        if options['all'] and empresas:
            raise CommandError('Use --all o --empresa, pero no ambos.')
        if not options['all'] and not empresas:
            raise CommandError('Indique --empresa 1, --empresa 2 o --all.')

        try:
            resultados = sincronizar_transportes_sap(
                empresas=EMPRESAS_TRANSPORTES_SAP if options['all'] else empresas,
                dry_run=options['dry_run'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        modo = 'DRY-RUN' if options['dry_run'] else 'APLICADO'
        for resultado in resultados:
            self.stdout.write(
                f"{modo} empresa={resultado['empresa_id']}: "
                f"encontrados={resultado['encontrados']}, "
                f"creados={resultado['creados']}, "
                f"actualizados={resultado['actualizados']}, "
                f"sin_cambios={resultado['sin_cambios']}, "
                f"ignorados={resultado['ignorados']}, "
                f"errores={resultado['errores']}."
            )
