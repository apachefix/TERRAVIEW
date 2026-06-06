from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('home', '0076_operacion_planta_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='CITACION_DOCUMENTO',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('CD_CTIPO', models.CharField(choices=[('GUIA', 'Guia'), ('TICKET_ORIGEN', 'Ticket origen'), ('SERNAPESCA', 'Sernapesca')], max_length=64, verbose_name='Tipo documento')),
                ('CD_CRUTA_ARCHIVO', models.TextField(verbose_name='Ruta archivo')),
                ('CD_CNOMBRE_ARCHIVO', models.CharField(max_length=255, verbose_name='Nombre archivo')),
                ('CD_FFECHASUBIDA', models.DateTimeField(auto_now_add=True, verbose_name='Fecha subida')),
                ('CD_FFECHAMODIFICACION', models.DateTimeField(blank=True, null=True, verbose_name='Fecha modificacion')),
                ('CD_BACTIVO', models.BooleanField(default=True, verbose_name='Estado activo')),
                ('CI_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_expediente', to='home.citacion', verbose_name='Id citacion')),
                ('DO_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documentos_expediente', to='home.dato_operacion', verbose_name='Id dato operacion')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='home.empresa', verbose_name='Id empresa')),
                ('US_MODIFICA_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='citacion_documentos_modificados', to=settings.AUTH_USER_MODEL, verbose_name='Usuario modificacion')),
                ('US_SUBE_NID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='citacion_documentos_subidos', to=settings.AUTH_USER_MODEL, verbose_name='Usuario subida')),
            ],
            options={
                'db_table': 'CITACION_DOCUMENTO',
            },
        ),
        migrations.AddIndex(
            model_name='citacion_documento',
            index=models.Index(fields=['EP_NID', 'CD_BACTIVO'], name='CIT_DOC_EP_ACT_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_documento',
            index=models.Index(fields=['CI_NID', 'CD_CTIPO', 'CD_BACTIVO'], name='CIT_DOC_CI_TIPO_ACT_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_documento',
            index=models.Index(fields=['CD_CTIPO'], name='CIT_DOC_TIPO_idx'),
        ),
        migrations.AddIndex(
            model_name='citacion_documento',
            index=models.Index(fields=['CD_FFECHASUBIDA'], name='CIT_DOC_FECHA_idx'),
        ),
    ]
