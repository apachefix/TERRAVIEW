"""Crea la definición funcional de Asistente de Recepción, sin membresías."""

from django.db import migrations


def crear_perfil_asistente_recepcion(apps, schema_editor):
    Perfil = apps.get_model('home', 'PERFIL')
    User = apps.get_model('auth', 'User')

    if Perfil.objects.filter(PR_CCODIGO='ASISTENTE_RECEPCION').exists():
        return

    propietario = User.objects.order_by('id').first()
    if propietario is None:
        return

    Perfil.objects.create(
        US_NID_id=propietario.id,
        PR_CCODIGO='ASISTENTE_RECEPCION',
        PR_CNOMBRE='Asistente de Recepción',
        PR_BHABILITADO=True,
    )


class Migration(migrations.Migration):
    dependencies = [('home', '0116_perfil_recepcionista_legacy')]

    operations = [
        migrations.RunPython(
            crear_perfil_asistente_recepcion,
            migrations.RunPython.noop,
        ),
    ]
