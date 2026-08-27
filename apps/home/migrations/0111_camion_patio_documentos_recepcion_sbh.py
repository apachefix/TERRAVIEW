from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0110_citacion_detalle_tipo_recepcion_sbh'),
    ]

    operations = [
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CCDA',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='CDA'),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CDI',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='DI'),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CFECHAPRODUCCION',
            field=models.CharField(blank=True, max_length=8, null=True, verbose_name='Fecha produccion DDMMAAAA'),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CNAVE_NAVIERA',
            field=models.CharField(blank=True, max_length=256, null=True, verbose_name='Nave / Naviera'),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CSUI',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='SUI'),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CTIPO_RECEPCION',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='Tipo de recepcion'),
        ),
    ]
