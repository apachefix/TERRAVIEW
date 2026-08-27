from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0100_ajuste_tarifa_citacion_detalle'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion',
            name='CI_CFECHAVENCIMIENTOPRODUCTO',
            field=models.CharField(
                blank=True, max_length=8, null=True,
                verbose_name='Fecha vencimiento producto DDMMAAAA',
            ),
        ),
        migrations.AddField(
            model_name='camion_patio',
            name='CPA_CFECHAVENCIMIENTOPRODUCTO',
            field=models.CharField(
                blank=True, max_length=8, null=True,
                verbose_name='Fecha vencimiento producto DDMMAAAA',
            ),
        ),
    ]
