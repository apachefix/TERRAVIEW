import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def parse_decimal(value):
    if value in [None, '']:
        return None
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None


def migrate_comentario_json(apps, schema_editor):
    Citacion = apps.get_model('home', 'CITACION')
    Detalle = apps.get_model('home', 'CITACION_DETALLE_OPERACIONAL')

    keys = {
        'origen',
        'inf_24hrs',
        'codigo',
        'insumo',
        'pedido',
        'sap_opor_id',
        'proveedor_codigo',
        'bl',
        'cantidad_disponible',
        'docentry',
        'productor',
        'almacen_destino',
        'estanque_destino',
        'observacion',
    }

    for citacion in Citacion.objects.exclude(CI_CCOMENTARIO__isnull=True).exclude(CI_CCOMENTARIO=''):
        try:
            data = json.loads(citacion.CI_CCOMENTARIO)
        except (TypeError, ValueError):
            continue

        if not isinstance(data, dict) or not keys.intersection(data.keys()):
            continue

        Detalle.objects.update_or_create(
            CI_NID_id=citacion.id,
            defaults={
                'EP_NID_id': citacion.EP_NID_id,
                'US_NID_id': citacion.US_NID_id,
                'CDO_CORIGEN': data.get('origen') or 'planificacion',
                'CDO_CINF_24HRS': data.get('inf_24hrs') or '',
                'CDO_CCODIGO_SAP': data.get('codigo') or '',
                'CDO_CINSUMO': data.get('insumo') or '',
                'CDO_CPEDIDO_SAP': data.get('pedido') or '',
                'CDO_CSAP_OPOR_ID': data.get('sap_opor_id') or '',
                'CDO_CPROVEEDOR_CODIGO': data.get('proveedor_codigo') or '',
                'CDO_CBL_CONTENEDOR': data.get('bl') or '',
                'CDO_NCANTIDAD_DISPONIBLE': parse_decimal(data.get('cantidad_disponible')),
                'CDO_CDOCENTRY': data.get('docentry') or '',
                'CDO_CPRODUCTOR': data.get('productor') or '',
                'CDO_CALMACEN_DESTINO': data.get('almacen_destino') or data.get('estanque_destino') or '',
                'CDO_CESTANQUE_DESTINO': data.get('estanque_destino') or '',
                'CDO_COBSERVACION': data.get('observacion') or '',
            }
        )

        citacion.CI_CCOMENTARIO = data.get('observacion') or ''
        citacion.save(update_fields=['CI_CCOMENTARIO'])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0073_etapa_log_el_caccion_etapa_log_el_cobservacion_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CITACION_DETALLE_OPERACIONAL',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('CDO_CORIGEN', models.CharField(blank=True, max_length=64, null=True, verbose_name='Origen')),
                ('CDO_CINF_24HRS', models.CharField(blank=True, max_length=16, null=True, verbose_name='Inf 24 hrs')),
                ('CDO_CCODIGO_SAP', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo SAP')),
                ('CDO_CINSUMO', models.CharField(blank=True, max_length=256, null=True, verbose_name='Insumo producto')),
                ('CDO_CPEDIDO_SAP', models.CharField(blank=True, max_length=128, null=True, verbose_name='Pedido SAP')),
                ('CDO_CSAP_OPOR_ID', models.CharField(blank=True, max_length=128, null=True, verbose_name='SAP OPOR id')),
                ('CDO_CPROVEEDOR_CODIGO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Codigo proveedor')),
                ('CDO_CBL_CONTENEDOR', models.CharField(blank=True, max_length=128, null=True, verbose_name='BL contenedor')),
                ('CDO_NCANTIDAD_DISPONIBLE', models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Cantidad disponible')),
                ('CDO_CDOCENTRY', models.CharField(blank=True, max_length=128, null=True, verbose_name='DocEntry')),
                ('CDO_CPRODUCTOR', models.CharField(blank=True, max_length=256, null=True, verbose_name='Productor')),
                ('CDO_CALMACEN_DESTINO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Almacen destino')),
                ('CDO_CESTANQUE_DESTINO', models.CharField(blank=True, max_length=128, null=True, verbose_name='Estanque destino')),
                ('CDO_COBSERVACION', models.TextField(blank=True, null=True, verbose_name='Observacion')),
                ('CDO_FFECHACREACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha creacion')),
                ('CI_NID', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='detalle_operacional', to='home.citacion', verbose_name='Id citacion')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('US_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Usuario creacion')),
            ],
            options={
                'db_table': 'CITACION_DETALLE_OPERACIONAL',
            },
        ),
        migrations.AddIndex(
            model_name='citacion_detalle_operacional',
            index=models.Index(fields=['EP_NID', 'CDO_CORIGEN'], name='CITACION_DE_EP_NID__cd1c92_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_detalle_operacional',
            index=models.Index(fields=['CDO_CCODIGO_SAP'], name='CITACION_DE_CDO_CCO_20d02e_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_detalle_operacional',
            index=models.Index(fields=['CDO_CPEDIDO_SAP'], name='CITACION_DE_CDO_CPE_bf9dd2_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_detalle_operacional',
            index=models.Index(fields=['CDO_CDOCENTRY'], name='CITACION_DE_CDO_CDO_14ae9a_idx'),
        ),
        migrations.RunPython(migrate_comentario_json, migrations.RunPython.noop),
    ]
