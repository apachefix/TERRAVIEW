from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0117_perfil_asistente_recepcion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CITACION_TRANSFERENCIA_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('CTD_CESTANQUE_ORIGEN', models.CharField(max_length=128, verbose_name='Estanque origen')),
                ('CTD_CCODIGO_SAP', models.CharField(max_length=128, verbose_name='Codigo SAP')),
                ('CTD_CINSUMO', models.CharField(max_length=256, verbose_name='Insumo')),
                ('CTD_CCODIGO_PROPIETARIO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo propietario')),
                ('CTD_CPROPIEDAD_PRODUCTO', models.CharField(blank=True, max_length=256, null=True, verbose_name='Propiedad producto')),
                ('CTD_NSTOCK_DISPONIBLE', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Stock disponible snapshot')),
                ('CTD_CUNIDAD_INVENTARIO', models.CharField(max_length=128, verbose_name='Unidad inventario snapshot')),
                ('CTD_NCANTIDAD_A_MOVER', models.DecimalField(decimal_places=5, max_digits=18, verbose_name='Cantidad a mover')),
                ('CTD_NORDEN', models.PositiveIntegerField(verbose_name='Orden')),
                ('CTD_FFECHACREACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha creacion')),
                ('CI_NID', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detalles_transferencia', to='home.citacion', verbose_name='Id citacion')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('US_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario creacion')),
            ],
            options={
                'db_table': 'CITACION_TRANSFERENCIA_DETALLE',
                'ordering': ['CTD_NORDEN', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='citacion_transferencia_detalle',
            constraint=models.UniqueConstraint(fields=('CI_NID', 'CTD_CESTANQUE_ORIGEN', 'CTD_CCODIGO_SAP'), name='CIT_TRANSF_UNQ_ESTANQUE_ITEM'),
        ),
        migrations.AddConstraint(
            model_name='citacion_transferencia_detalle',
            constraint=models.UniqueConstraint(fields=('CI_NID', 'CTD_NORDEN'), name='CIT_TRANSF_UNQ_ORDEN'),
        ),
        migrations.AddIndex(
            model_name='citacion_transferencia_detalle',
            index=models.Index(fields=['EP_NID', 'CTD_CESTANQUE_ORIGEN'], name='CIT_TRANSF_EP_EST_IDX'),
        ),
        migrations.AddIndex(
            model_name='citacion_transferencia_detalle',
            index=models.Index(fields=['CTD_CCODIGO_SAP'], name='CIT_TRANSF_COD_IDX'),
        ),
    ]
