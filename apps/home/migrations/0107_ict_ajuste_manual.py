from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0106_ict_acumulado_6_meses'),
    ]

    operations = [
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_NPORCENTAJEMANUAL',
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=9, null=True,
                verbose_name='Ajuste manual',
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_CORIGENPORCENTAJE',
            field=models.CharField(
                blank=True,
                choices=[('ICT', 'ICT calculado'), ('MANUAL', 'Ajuste manual')],
                max_length=16,
                null=True,
                verbose_name='Origen porcentaje aplicado',
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_CMOTIVOMANUAL',
            field=models.TextField(
                blank=True, null=True, verbose_name='Motivo ajuste manual',
            ),
        ),
    ]
