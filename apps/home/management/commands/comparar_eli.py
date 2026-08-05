from django.core.management.base import BaseCommand, CommandError
from apps.home.models import CITACION
from apps.home.views import _construir_archivo_eli_legacy, construir_archivo_eli
from apps.home.services.eli.comparison import comparar_expedientes_eli

class Command(BaseCommand):
    help = "Compara E.L.I. legacy y la capa de presentacion en modo estrictamente de solo lectura."

    def add_arguments(self, parser):
        parser.add_argument("citacion_id", type=int)
        parser.add_argument("--empresa-id", type=int, required=True)

    def handle(self, *args, **options):
        citacion = CITACION.objects.filter(pk=options["citacion_id"], EP_NID_id=options["empresa_id"]).select_related("EP_NID", "SC_NID").first()
        if not citacion:
            raise CommandError("Citacion no encontrada para la empresa indicada.")
        legacy = _construir_archivo_eli_legacy(citacion, sincronizar=False)
        nuevo = construir_archivo_eli(citacion, sincronizar=False)
        diferencias = comparar_expedientes_eli(legacy, nuevo)
        if diferencias:
            for diferencia in diferencias:
                self.stderr.write(diferencia)
            raise CommandError("Existen diferencias relevantes.")
        self.stdout.write(self.style.SUCCESS("E.L.I. legacy y nuevo: IGUAL"))
