from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0098_citacion_despacho_detalle_terramar'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CONCEPTO_VARIACION_TARIFA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('CVT_CNOMBRE', models.CharField(max_length=128, verbose_name='Nombre variacion')),
                ('CVT_CDESCRIPCION', models.TextField(blank=True, null=True, verbose_name='Descripcion variacion')),
                ('CVT_NPORCENTAJEDEFAULT', models.DecimalField(blank=True, decimal_places=4, max_digits=9, null=True, verbose_name='Porcentaje sugerido')),
                ('CVT_FFECHAINICIODEFAULT', models.DateField(blank=True, null=True, verbose_name='Fecha inicio sugerida')),
                ('CVT_FFECHAVENCIMIENTODEFAULT', models.DateField(blank=True, null=True, verbose_name='Fecha vencimiento sugerida')),
                ('CVT_BHABILITADO', models.BooleanField(default=True, verbose_name='Habilitado')),
                ('CVT_FFECHAREGISTRO', models.DateTimeField(auto_now_add=True, verbose_name='Fecha registro')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('US_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario creador')),
            ],
            options={
                'db_table': 'CONCEPTO_VARIACION_TARIFA',
                'ordering': ['CVT_CNOMBRE', 'id'],
            },
        ),
        migrations.CreateModel(
            name='AJUSTE_TARIFA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('AJT_CTIPO', models.CharField(choices=[('ICT', 'ICT'), ('VARIACION_MANUAL', 'Variacion manual')], max_length=32, verbose_name='Tipo ajuste')),
                ('AJT_NPORCENTAJE', models.DecimalField(decimal_places=4, max_digits=9, verbose_name='Porcentaje')),
                ('AJT_FFECHAINICIO', models.DateField(verbose_name='Fecha inicio')),
                ('AJT_FFECHAVENCIMIENTO', models.DateField(verbose_name='Fecha vencimiento')),
                ('AJT_FFECHAAPLICACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha aplicacion')),
                ('AJT_CESTADO', models.CharField(choices=[('APLICADO', 'Aplicado'), ('VENCIDO', 'Vencido'), ('REVERSADO', 'Reversado')], default='APLICADO', max_length=16, verbose_name='Estado')),
                ('AJT_CFUENTE', models.CharField(blank=True, max_length=256, null=True, verbose_name='Fuente')),
                ('AJT_CURLFUENTE', models.URLField(blank=True, max_length=512, null=True, verbose_name='URL fuente')),
                ('AJT_CPERIODOICT', models.CharField(blank=True, max_length=64, null=True, verbose_name='Periodo ICT')),
                ('AJT_COBSERVACION', models.TextField(blank=True, null=True, verbose_name='Observacion')),
                ('AJT_FFECHAREVERSA', models.DateTimeField(blank=True, null=True, verbose_name='Fecha reversa')),
                ('AJT_CMOTIVOREVERSA', models.TextField(blank=True, null=True, verbose_name='Motivo reversa')),
                ('CVT_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ajustes', to='home.concepto_variacion_tarifa', verbose_name='Concepto')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('REVERSADO_POR', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ajustes_tarifa_reversados', to=settings.AUTH_USER_MODEL, verbose_name='Usuario reversa')),
                ('US_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ajustes_tarifa_aplicados', to=settings.AUTH_USER_MODEL, verbose_name='Usuario aplicador')),
            ],
            options={
                'db_table': 'AJUSTE_TARIFA',
                'ordering': ['-AJT_FFECHAAPLICACION', '-id'],
            },
        ),
        migrations.CreateModel(
            name='AJUSTE_TARIFA_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('AJTD_NVALORANTERIOR', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Valor anterior')),
                ('AJTD_NVALORNUEVO', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Valor nuevo')),
                ('AJTD_NPORCENTAJE', models.DecimalField(decimal_places=4, max_digits=9, verbose_name='Porcentaje')),
                ('AJTD_FFECHAREGISTRO', models.DateTimeField(auto_now_add=True, verbose_name='Fecha registro')),
                ('AJT_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='detalles', to='home.ajuste_tarifa', verbose_name='Ajuste tarifa')),
                ('TAR_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.tarifa_global', verbose_name='Tarifa')),
            ],
            options={
                'db_table': 'AJUSTE_TARIFA_DETALLE',
            },
        ),
        migrations.AddConstraint(
            model_name='ajuste_tarifa_detalle',
            constraint=models.UniqueConstraint(fields=('AJT_NID', 'TAR_NID'), name='uq_ajuste_tarifa_detalle'),
        ),
    ]
