from django.db import migrations, models


def marcar_drafts_existentes(apps, schema_editor):
    detalle_model = apps.get_model('home', 'CITACION_DESPACHO_DETALLE')
    detalle_model.objects.filter(
        CDD_CSAP_DRAFT_DOCENTRY__isnull=False,
        CDD_CESTADO_DRAFT_SAP__isnull=True,
    ).exclude(CDD_CSAP_DRAFT_DOCENTRY='').update(CDD_CESTADO_DRAFT_SAP='CREADO')


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0085_citacion_despacho_detalle_draft_sap'),
    ]

    operations = [
        migrations.AddField(
            model_name='citacion_despacho_detalle',
            name='CDD_CESTADO_DRAFT_SAP',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='Estado draft SAP despacho'),
        ),
        migrations.RunPython(marcar_drafts_existentes, migrations.RunPython.noop),
    ]
