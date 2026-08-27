# Configuración documental mínima para el alta operacional de conductores SBH.

from django.db import migrations


NOMBRE_LICENCIA = 'LICENCIA DE CONDUCIR'


def crear_licencia_sbh(apps, schema_editor):
    Empresa = apps.get_model('home', 'EMPRESA')
    ListadoDocumento = apps.get_model('home', 'LISTADO_DOCUMENTO')
    empresa_sbh = Empresa.objects.filter(pk=2).first()
    if not empresa_sbh:
        return
    licencia = ListadoDocumento.objects.filter(
        EP_NID_id=2,
        LIS_CGRUPO__iexact='Conductor',
        LIS_CNOMBREDOCUMENTO__iexact=NOMBRE_LICENCIA,
    ).first()
    if licencia:
        if not licencia.LIS_BHABILITADO:
            licencia.LIS_BHABILITADO = True
            licencia.save(update_fields=['LIS_BHABILITADO'])
        return
    origen = ListadoDocumento.objects.filter(
        LIS_CGRUPO__iexact='Conductor',
        LIS_CNOMBREDOCUMENTO__iexact=NOMBRE_LICENCIA,
    ).order_by('id').first()
    ListadoDocumento.objects.create(
        EP_NID_id=2,
        US_NID_id=origen.US_NID_id if origen else None,
        LIS_CNOMBREDOCUMENTO=NOMBRE_LICENCIA,
        LIS_CGRUPO='Conductor',
        LIS_CCODIGO=origen.LIS_CCODIGO if origen else 'LC',
        LIS_CDESCRIPCION=origen.LIS_CDESCRIPCION if origen else 'Licencia de conducir',
        LIS_CFORMATO=origen.LIS_CFORMATO if origen else 'PDF',
        LIS_FFECHAREGISTRO=origen.LIS_FFECHAREGISTRO if origen else None,
        LIS_BOBLIGATORIO=origen.LIS_BOBLIGATORIO if origen else True,
        LIS_BHABILITADO=True,
    )


def revertir_licencia_sbh(apps, schema_editor):
    # No se elimina configuración documental que pueda haber sido usada después.
    return


class Migration(migrations.Migration):
    dependencies = [('home', '0114_conductor_empresa')]

    operations = [
        migrations.RunPython(crear_licencia_sbh, revertir_licencia_sbh),
    ]
