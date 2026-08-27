from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0097_camion_patio_trazabilidad_planificacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_BPALLET',
            field=models.BooleanField(blank=True, null=True, verbose_name='Carga con pallet despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_BRELLENO',
            field=models.BooleanField(blank=True, null=True, verbose_name='Carga con relleno despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CCODIGO_PAIS_TELEFONO',
            field=models.CharField(blank=True, max_length=5, null=True, verbose_name='Codigo pais telefono despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CCONTENEDOR_CRT',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Contenedor / CRT despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CHORA_CITACION',
            field=models.CharField(blank=True, max_length=5, null=True, verbose_name='Hora citacion despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CTIPO_CAMION',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='Tipo camion despacho Terramar'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CTRANSPORTE_A_CARGO',
            field=models.CharField(blank=True, max_length=16, null=True, verbose_name='Transporte a cargo despacho Terramar'),
        ),
    ]