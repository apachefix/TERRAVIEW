from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0109_recepcion_sbh_documentos_sap'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CTIPO_RECEPCION',
            field=models.CharField(
                blank=True,
                max_length=20,
                null=True,
                verbose_name='Tipo recepcion',
            ),
        ),
    ]
