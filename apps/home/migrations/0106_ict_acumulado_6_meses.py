from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0105_proforma_extras_cantidad_terramar'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ajuste_tarifa',
            name='AJT_CTIPO',
            field=models.CharField(
                choices=[
                    ('ICT', 'ICT legacy'),
                    ('ICT_ACUMULADO_6_MESES', 'ICT acumulado 6 meses'),
                    ('VARIACION_MANUAL', 'Variacion manual'),
                ],
                max_length=32,
                verbose_name='Tipo ajuste',
            ),
        ),
        migrations.AlterField(
            model_name='ajuste_tarifa',
            name='AJT_NPORCENTAJE',
            field=models.DecimalField(
                decimal_places=4,
                max_digits=9,
                verbose_name='Porcentaje aplicado',
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_NPORCENTAJECALCULADO',
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                max_digits=9,
                null=True,
                verbose_name='ICT acumulado calculado',
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_FPERIODOICTINICIO',
            field=models.DateField(
                blank=True, null=True, verbose_name='Inicio periodo ICT'
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_FPERIODOICTFIN',
            field=models.DateField(
                blank=True, null=True, verbose_name='Fin periodo ICT'
            ),
        ),
        migrations.AddField(
            model_name='ajuste_tarifa',
            name='AJT_CCOMPONENTESICT',
            field=models.TextField(
                blank=True, null=True, verbose_name='Componentes mensuales ICT'
            ),
        ),
    ]