from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.home.models import CITACION, RESULTADO_CALIDAD_OPERACION
from apps.home.services.calidad_service import procesar_resultado_calidad, serializar_resultado_calidad


class Command(BaseCommand):
    help = 'Actualiza un resultado de calidad usando el servicio central interno.'

    def add_arguments(self, parser):
        parser.add_argument('--guia', required=True)
        parser.add_argument('--estado', required=True, choices=RESULTADO_CALIDAD_OPERACION.Estado.values)
        parser.add_argument('--empresa', required=True, type=int, dest='empresa_id')
        parser.add_argument('--usuario', required=True, help='Username responsable del cambio')
        parser.add_argument('--observacion', default='')

    def handle(self, *args, **options):
        guia = str(options['guia']).strip()
        coincidencias = list(CITACION.objects.filter(
            EP_NID_id=options['empresa_id'],
            CI_CNUMERODOCUMENTO__iexact=guia,
            CI_BHABILITADO=True,
        ).select_related('EP_NID', 'PL_NID', 'SC_NID', 'CA_NID', 'US_NID')[:2])
        if not coincidencias:
            raise CommandError('No existe una citacion habilitada para la empresa y guia indicadas.')
        if len(coincidencias) > 1:
            raise CommandError('La guia tiene mas de una citacion en la empresa; use una guia univoca para esta prueba.')
        try:
            usuario = get_user_model().objects.get(username=options['usuario'])
        except get_user_model().DoesNotExist as exc:
            raise CommandError('Usuario responsable no encontrado.') from exc

        try:
            registro, cambiado = procesar_resultado_calidad(
                coincidencias[0],
                options['estado'],
                RESULTADO_CALIDAD_OPERACION.Origen.MANUAL_PRUEBA,
                observacion=options['observacion'],
                usuario=usuario,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        payload = serializar_resultado_calidad(registro)
        accion = 'actualizado' if cambiado else 'sin cambios (ejecucion idempotente)'
        self.stdout.write(self.style.SUCCESS(
            f'Calidad {accion}: citacion #{registro.CI_NID_id}, guia {registro.RCO_CNUMERO_GUIA}, '
            f'estado {payload["estado"]}, duracion {payload["duracion_legible"]}.'
        ))
