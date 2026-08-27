from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0101_recepcion_sbh_vencimiento_producto'),
    ]

    operations = [
        migrations.AddField(
            model_name='proforma',
            name='PRO_FPERIODO_INICIO',
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name='Inicio periodo'),
        ),
        migrations.AddField(
            model_name='proforma',
            name='PRO_FPERIODO_FIN',
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name='Fin periodo'),
        ),
        migrations.AddConstraint(
            model_name='proforma',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ('EP_NID_id', 1),
                    ('PRO_BBORRADOR', True),
                    ('PRO_CESTADO', 'CREADO'),
                    ('PRO_FPERIODO_FIN__isnull', False),
                    ('PRO_FPERIODO_INICIO__isnull', False),
                ),
                fields=(
                    'EP_NID', 'SN_NID', 'PRO_CTIPO',
                    'PRO_FPERIODO_INICIO', 'PRO_FPERIODO_FIN',
                ),
                name='uniq_proforma_terramar_borrador_periodo',
            ),
        ),
        migrations.AddField(
            model_name='citacion_proforma',
            name='CIP_BREGLA_MENSUAL',
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name='citacion_proforma',
            constraint=models.UniqueConstraint(
                condition=models.Q(('CIP_BREGLA_MENSUAL', True)),
                fields=('CI_NID',),
                name='uniq_citacion_proforma_mensual',
            ),
        ),
    ]
