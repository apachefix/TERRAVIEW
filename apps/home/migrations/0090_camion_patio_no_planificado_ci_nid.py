import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0089_camion_patio_no_planificado'),
    ]

    operations = [
        migrations.AddField(
            model_name='camion_patio_no_planificado',
            name='CI_NID',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='solicitudes_camion_patio_no_planificado',
                to='home.citacion',
                verbose_name='Citacion creada',
            ),
        ),
    ]
