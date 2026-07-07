from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('home', '0086_citacion_despacho_detalle_estado_draft_sap'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CSAP_UPDATE_ESTADO',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='Estado update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CSAP_UPDATE_DOCENTRY',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='DocEntry update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CJSON_UPDATE_REQUEST',
            field=models.TextField(blank=True, null=True, verbose_name='JSON request update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CJSON_UPDATE_RESPONSE',
            field=models.TextField(blank=True, null=True, verbose_name='JSON response update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FFECHA_UPDATE_SAP',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_USUARIO_UPDATE_SAP',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='despacho_updates_sap', to=settings.AUTH_USER_MODEL, verbose_name='Usuario update SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_NSAP_PESO_SALIDA',
            field=models.DecimalField(blank=True, decimal_places=5, max_digits=18, null=True, verbose_name='Peso salida SAP despacho'),
        ),
    ]
