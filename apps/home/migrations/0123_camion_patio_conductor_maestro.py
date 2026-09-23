from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0122_camion_patio_salida_confirmada'),
    ]

    operations = [
        migrations.AddField(
            model_name='camion_patio',
            name='CON_NID',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='camiones_patio',
                to='home.conductor',
                verbose_name='Conductor maestro',
            ),
        ),
    ]
