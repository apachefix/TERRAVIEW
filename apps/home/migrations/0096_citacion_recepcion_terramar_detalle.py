from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0095_conductor_phone_country_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='CITACION_RECEPCION_TERRAMAR_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('RTD_CCONTENEDOR_CRT', models.CharField(blank=True, max_length=128, null=True, verbose_name='Contenedor / CRT')),
                ('RTD_CBODEGA', models.CharField(max_length=128, verbose_name='Bodega destino')),
                ('RTD_CTRANSPORTE_A_CARGO', models.CharField(max_length=16, verbose_name='Transporte a cargo de')),
                ('RTD_CEMPRESA_TRANSPORTE', models.CharField(blank=True, max_length=256, null=True, verbose_name='Empresa transporte declarada')),
                ('RTD_CCONDUCTOR', models.CharField(blank=True, max_length=256, null=True, verbose_name='Conductor declarado')),
                ('RTD_CCODIGO_PAIS_TELEFONO', models.CharField(blank=True, max_length=5, null=True, verbose_name='Codigo pais telefono')),
                ('RTD_CTELEFONO_CONDUCTOR', models.CharField(blank=True, max_length=64, null=True, verbose_name='Telefono conductor')),
                ('RTD_CPATENTE', models.CharField(blank=True, max_length=32, null=True, verbose_name='Patente camion')),
                ('RTD_FFECHACREACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha creacion')),
                ('CI_NID', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='detalle_recepcion_terramar', to='home.citacion', verbose_name='Id citacion')),
                ('CON_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='home.conductor', verbose_name='Conductor maestro')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('SN_NID_TRANSPORTISTA', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='home.socionegocio', verbose_name='Transportista maestro')),
                ('US_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario creacion')),
            ],
            options={'db_table': 'CITACION_RECEPCION_TERRAMAR_DETALLE'},
        ),
    ]