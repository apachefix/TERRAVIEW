"""Migración reservada sin provisión automática de perfiles legacy.

La versión inicial vinculó erróneamente cuentas legacy al perfil REC. Nunca
debe inferirse un perfil funcional desde UX_IS_*.
"""

from django.db import migrations


def neutralizar_provision_legacy(apps, schema_editor):
    """No-op deliberado: no lee ni modifica usuarios, flags ni perfiles."""


class Migration(migrations.Migration):
    dependencies = [('home', '0115_licencia_conducir_sbh')]

    operations = [
        migrations.RunPython(neutralizar_provision_legacy, migrations.RunPython.noop),
    ]
