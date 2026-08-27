from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0099_tarifa_variaciones_ajustes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AJUSTE_TARIFA_CITACION_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('AJTC_NVALORANTERIOR', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Valor citacion anterior')),
                ('AJTC_NVALORNUEVO', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Valor citacion nuevo')),
                ('AJTC_FFECHAREGISTRO', models.DateTimeField(auto_now_add=True, verbose_name='Fecha registro')),
                ('AJT_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='detalles_citaciones', to='home.ajuste_tarifa', verbose_name='Ajuste tarifa')),
                ('CI_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.citacion', verbose_name='Citacion')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('TAR_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.tarifa_global', verbose_name='Tarifa')),
                ('US_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario aplicador')),
            ],
            options={'db_table': 'AJUSTE_TARIFA_CITACION_DETALLE'},
        ),
        migrations.AddConstraint(
            model_name='ajuste_tarifa_citacion_detalle',
            constraint=models.UniqueConstraint(fields=('AJT_NID', 'CI_NID'), name='uq_ajuste_tarifa_citacion_detalle'),
        ),
    ]
