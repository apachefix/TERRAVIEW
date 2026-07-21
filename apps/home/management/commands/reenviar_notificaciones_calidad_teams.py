from django.core.management.base import BaseCommand, CommandError

from apps.home.models import EVENTO_INTEGRACION_CALIDAD
from apps.home.services.calidad_integracion_service import (
    intentar_notificacion_calidad_teams,
    maximo_intentos_teams,
)


class Command(BaseCommand):
    help = 'Reintenta notificaciones Teams pendientes de resultados definitivos de Calidad.'

    def add_arguments(self, parser):
        parser.add_argument('--id-evento', dest='id_evento', default='')

    def handle(self, *args, **options):
        queryset = EVENTO_INTEGRACION_CALIDAD.objects.filter(
            EIC_CESTADO_PROCESAMIENTO=EVENTO_INTEGRACION_CALIDAD.EstadoProcesamiento.PROCESADO,
            EIC_BTEAMS_PENDIENTE=True,
            EIC_BTEAMS_ENVIADO=False,
            EIC_NINTENTOS_TEAMS__lt=maximo_intentos_teams(),
        ).order_by('EIC_FRECEPCION', 'id')
        if options['id_evento']:
            queryset = queryset.filter(EIC_CID_EVENTO=options['id_evento'])
            if not queryset.exists():
                raise CommandError('No existe una notificacion pendiente reintentable para el id_evento indicado.')

        procesadas = enviadas = fallidas = 0
        for evento_id in queryset.values_list('id', flat=True):
            evento, intentado = intentar_notificacion_calidad_teams(evento_id, es_reintento=True)
            if not intentado:
                continue
            procesadas += 1
            if evento.EIC_BTEAMS_ENVIADO:
                enviadas += 1
            else:
                fallidas += 1

        self.stdout.write(
            f'Reintentos procesados: {procesadas}; enviados: {enviadas}; pendientes/error: {fallidas}.'
        )
