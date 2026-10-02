from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0129_recepcion_servicio'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CCONTENEDOR_2_CRT',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Contenedor 2 / CRT despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CPATENTE_RAMPLA',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='Patente rampla despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_NMAXIS_1',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Numero Maxis 1 despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_NMAXIS_2',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Numero Maxis 2 despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_NPESO_1',
            field=models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Peso 1 despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_NPESO_2',
            field=models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Peso 2 despacho Terramar'),
        ),
    ]