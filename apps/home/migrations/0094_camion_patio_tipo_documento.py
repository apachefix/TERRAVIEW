from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0093_evento_integracion_calidad'),
    ]

    operations = [
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CTIPO_DOCUMENTO',
            field=models.CharField(
                choices=[
                    ('GD', 'Guía de despacho'),
                    ('FE', 'Factura electrónica'),
                ],
                default='GD',
                max_length=2,
                verbose_name='Tipo de documento',
            ),
            preserve_default=False,
        ),
    ]
