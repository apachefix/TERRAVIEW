from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0090_camion_patio_no_planificado_ci_nid'),
    ]

    operations = [
        migrations.AlterField(
            model_name='citacion',
            name='CI_CNUMERODOCUMENTO',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=128,
                null=True,
                verbose_name='Numero documento',
            ),
        ),
    ]
