from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0108_control_flota_autorizar_proforma'),
    ]

    operations = [
        migrations.AlterField(
            model_name='citacion_detalle_operacional',
            name='CDO_CBL_CONTENEDOR',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Contenedor'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CBL',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='BL'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CGUIA',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Guia'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CFECHA_PRODUCCION',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Fecha produccion'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CFECHA_VENCIMIENTO',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Fecha vencimiento'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CCDA',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='CDA'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CDI',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='DI'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CSUI',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='SUI'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CNAVE_NAVIERA',
            field=models.CharField(blank=True, max_length=256, null=True, verbose_name='Nave naviera'),
        ),
        migrations.AddField(
            model_name='citacion_detalle_operacional',
            name='CDO_CBOOKING',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Booking'),
        ),
    ]
