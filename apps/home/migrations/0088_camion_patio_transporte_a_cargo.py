from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0087_citacion_despacho_detalle_update_sap'),
    ]

    operations = [
        migrations.AddField(
            model_name='camion_patio',
            name='transporte_a_cargo',
            field=models.CharField(
                choices=[('TERRAMAR', 'Terramar'), ('CLIENTE', 'Cliente')],
                default='TERRAMAR',
                max_length=20,
                verbose_name='Transporte a cargo de',
            ),
        ),
    ]
