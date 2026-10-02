from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0127_operacion_new_jersey'),
    ]

    operations = [
        migrations.AlterField(
            model_name='camion_patio',
            name='CPA_CESTADO',
            field=models.CharField(
                choices=[
                    ('PENDIENTE_ASOCIACION', 'Pendiente asociacion'),
                    ('EN_REVISION_RECEPCION', 'En revision recepcion'),
                    ('ASOCIADO_CITACION', 'Asociado a citacion'),
                    ('FUERA_TEMPORAL', 'Fuera temporalmente de planta'),
                    ('SALIDA_CONFIRMADA', 'Salida confirmada'),
                    ('RECHAZADO', 'Rechazado'),
                    ('CANCELADO', 'Cancelado'),
                ],
                default='PENDIENTE_ASOCIACION',
                max_length=32,
                verbose_name='Estado',
            ),
        ),
    ]
