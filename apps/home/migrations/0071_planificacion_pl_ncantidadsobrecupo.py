# Generated manually on 2026-05-18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0070_sap_opor_programacion_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='planificacion',
            name='PL_NCANTIDADSOBRECUPO',
            field=models.IntegerField(default=0, verbose_name='Cantidad de sobrecupos'),
        ),
    ]
