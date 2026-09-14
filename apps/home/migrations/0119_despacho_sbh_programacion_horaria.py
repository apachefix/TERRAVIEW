from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0118_citacion_transferencia_detalle'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FFECHA_DESPACHO',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FHORA_LLEGADA_PLANTA',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora llegada a planta'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FHORA_LLEGADA_DESTINO',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora llegada a destino'),
        ),
    ]