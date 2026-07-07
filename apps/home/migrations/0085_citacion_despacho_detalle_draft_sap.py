from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('home', '0084_citacion_despacho_detalle_cdd_npeso_informado_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CJSON_DRAFT_REQUEST',
            field=models.TextField(blank=True, null=True, verbose_name='JSON request draft SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CJSON_DRAFT_RESPONSE',
            field=models.TextField(blank=True, null=True, verbose_name='JSON response draft SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CSAP_DRAFT_DOCENTRY',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='DocEntry draft SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CSAP_DRAFT_DOCNUM',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='DocNum draft SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_FFECHA_DRAFT_SAP',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha draft SAP despacho'),
        ),
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_USUARIO_DRAFT_SAP',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='despacho_drafts_sap', to=settings.AUTH_USER_MODEL, verbose_name='Usuario draft SAP despacho'),
        ),
    ]
