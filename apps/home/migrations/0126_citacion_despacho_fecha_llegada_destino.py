from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0125_calidad_revision_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FFECHA_LLEGADA_DESTINO',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Fecha llegada a destino',
            ),
        ),
    ]
