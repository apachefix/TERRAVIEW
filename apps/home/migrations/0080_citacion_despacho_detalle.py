from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0079_camion_patio_datos_operativos'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CITACION_DESPACHO_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('CDD_CDESTINO', models.CharField(blank=True, max_length=256, null=True, verbose_name='Destino')),
                ('CDD_COC_CLIENTE', models.CharField(blank=True, max_length=128, null=True, verbose_name='OC cliente')),
                ('CDD_NCANTIDAD_INTENTADA_DESPACHAR', models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Cantidad intentada a despachar')),
                ('CDD_CCONDICION_ENTREGA', models.CharField(blank=True, max_length=128, null=True, verbose_name='Condicion de entrega')),
                ('CDD_CEMPRESA_TRANSPORTE', models.CharField(blank=True, max_length=256, null=True, verbose_name='Empresa transporte')),
                ('CDD_CCONDUCTOR', models.CharField(blank=True, max_length=256, null=True, verbose_name='Conductor')),
                ('CDD_CTELEFONO_CONDUCTOR', models.CharField(blank=True, max_length=64, null=True, verbose_name='Telefono conductor')),
                ('CDD_CPATENTE', models.CharField(blank=True, max_length=32, null=True, verbose_name='Patente')),
                ('CDD_CORDEN_CARGA', models.CharField(blank=True, max_length=128, null=True, verbose_name='Orden de carga')),
                ('CDD_CVENTANA_HORARIA_DESPACHO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Ventana horaria despacho')),
                ('CDD_CBODEGA', models.CharField(blank=True, max_length=128, null=True, verbose_name='Bodega')),
                ('CDD_CSECUENCIA_OPERACIONAL_CODIGO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo secuencia operacional')),
                ('CDD_CSECUENCIA_OPERACIONAL_NOMBRE', models.CharField(blank=True, max_length=256, null=True, verbose_name='Nombre secuencia operacional')),
                ('CDD_CSAP_ABS_ID', models.CharField(blank=True, max_length=128, null=True, verbose_name='SAP AbsID')),
                ('CDD_CSAP_NUMERO_ACUERDO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Numero acuerdo SAP')),
                ('CDD_CSAP_LINEA_ACUERDO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Linea acuerdo SAP')),
                ('CDD_CSAP_CLIENTE_CODIGO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo cliente SAP')),
                ('CDD_CSAP_CLIENTE_NOMBRE', models.CharField(blank=True, max_length=256, null=True, verbose_name='Nombre cliente SAP')),
                ('CDD_CSAP_OC_CLIENTE', models.CharField(blank=True, max_length=128, null=True, verbose_name='OC cliente SAP')),
                ('CDD_CSAP_CODIGO_PRODUCTO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo producto SAP')),
                ('CDD_CSAP_NOMBRE_PRODUCTO', models.CharField(blank=True, max_length=256, null=True, verbose_name='Nombre producto SAP')),
                ('CDD_NSAP_CANTIDAD_PLANIFICADA', models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Cantidad planificada SAP')),
                ('CDD_NSAP_CANTIDAD_CONSUMIDA', models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Cantidad consumida SAP')),
                ('CDD_NSAP_SALDO_CONTRATO', models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Saldo contrato SAP')),
                ('CDD_CSAP_UNIDAD_MEDIDA', models.CharField(blank=True, max_length=64, null=True, verbose_name='Unidad medida SAP')),
                ('CDD_FFECHACREACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha creacion')),
                ('CDD_FFECHAACTUALIZACION', models.DateTimeField(auto_now=True, verbose_name='Fecha actualizacion')),
                ('CI_NID', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='detalle_despacho', to='home.citacion', verbose_name='Id citacion')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('US_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario creacion')),
            ],
            options={
                'db_table': 'CITACION_DESPACHO_DETALLE',
                'indexes': [
                    models.Index(fields=['EP_NID', 'CDD_COC_CLIENTE'], name='CIT_DESP_EP_OC_IDX'),
                    models.Index(fields=['CDD_CPATENTE'], name='CIT_DESP_PATENTE_IDX'),
                    models.Index(fields=['CDD_CSAP_NUMERO_ACUERDO'], name='CIT_DESP_SAP_ACUERDO_IDX'),
                ],
            },
        ),
    ]
