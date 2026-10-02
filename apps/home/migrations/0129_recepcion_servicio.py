# Generated manually for the isolated Recepcion Servicio flow.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


SECUENCIA_CODIGO = 'RECEPCION_SERVICIO'
ETAPAS = (
    (1, 'RS_RECEPCION_CONFORME', 'Recepción Conforme', 'OPERACION'),
    (2, 'RS_CONFIRMAR_SALIDA', 'Confirmar Salida', 'SALIDA'),
)


def crear_configuracion_recepcion_servicio(apps, schema_editor):
    Empresa = apps.get_model('home', 'EMPRESA')
    Secuencia = apps.get_model('home', 'SECUENCIA')
    Etapa = apps.get_model('home', 'ETAPA')
    DetalleSecuencia = apps.get_model('home', 'DETALLE_SECUENCIA')
    UsersEmpresa = apps.get_model('home', 'USERS_EMPRESA')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    for empresa in Empresa.objects.filter(pk__in=(1, 2)):
        usuario_id = (
            UsersEmpresa.objects.filter(EP_NID_id=empresa.pk, US_NID__is_active=True)
            .values_list('US_NID_id', flat=True)
            .first()
            or User.objects.filter(is_active=True).values_list('id', flat=True).first()
        )
        secuencia, _ = Secuencia.objects.get_or_create(
            EP_NID_id=empresa.pk,
            SE_CCODIGO=SECUENCIA_CODIGO,
            defaults={
                'US_NID_id': usuario_id,
                'SE_CTIPO': 'RECEPCION',
                'SE_CNOMBRE': 'Recepción Servicio',
                'SE_BHABILITADO': True,
            },
        )
        cambios_secuencia = []
        for campo, valor in (
            ('SE_CTIPO', 'RECEPCION'),
            ('SE_CNOMBRE', 'Recepción Servicio'),
            ('SE_BHABILITADO', True),
        ):
            if getattr(secuencia, campo) != valor:
                setattr(secuencia, campo, valor)
                cambios_secuencia.append(campo)
        if usuario_id and not secuencia.US_NID_id:
            secuencia.US_NID_id = usuario_id
            cambios_secuencia.append('US_NID')
        if cambios_secuencia:
            secuencia.save(update_fields=cambios_secuencia)

        for paso, codigo, nombre, tipo in ETAPAS:
            etapa, _ = Etapa.objects.get_or_create(
                EP_NID_id=empresa.pk,
                ET_CCODIGO=codigo,
                defaults={
                    'US_NID_id': usuario_id,
                    'ET_CTIPO': tipo,
                    'ET_CNOMBRE': nombre,
                    'ET_NCANTIDADMAXIMA': 1,
                    'ET_BHABILITADO': True,
                    'ET_BINTEGRARSAP': False,
                },
            )
            Etapa.objects.filter(pk=etapa.pk).update(
                ET_CTIPO=tipo,
                ET_CNOMBRE=nombre,
                ET_NCANTIDADMAXIMA=1,
                ET_BHABILITADO=True,
                ET_BINTEGRARSAP=False,
            )
            if usuario_id:
                detalle, _ = DetalleSecuencia.objects.get_or_create(
                    EP_NID_id=empresa.pk,
                    SC_NID_id=secuencia.pk,
                    ET_NID_id=etapa.pk,
                    defaults={
                        'US_NID_id': usuario_id,
                        'SE_NPASO': paso,
                        'SE_BHABILITADO': True,
                        'SE_BOBLIGATORIO': True,
                    },
                )
                DetalleSecuencia.objects.filter(pk=detalle.pk).update(
                    US_NID_id=usuario_id,
                    SE_NPASO=paso,
                    SE_BHABILITADO=True,
                    SE_BOBLIGATORIO=True,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0128_camion_patio_fuera_temporal'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='citacion_documento',
            name='CD_CTIPO',
            field=models.CharField(
                choices=[
                    ('GUIA', 'Guia'),
                    ('TICKET_ORIGEN', 'Ticket origen'),
                    ('SERNAPESCA', 'Sernapesca'),
                    ('IMAGEN_SELLO_DESPACHO', 'Imagen sello despacho'),
                    ('RECEPCION_SERVICIO', 'Recepcion Servicio'),
                ],
                max_length=64,
                verbose_name='Tipo documento',
            ),
        ),
        migrations.CreateModel(
            name='RECEPCION_SERVICIO_DETALLE',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('RSD_CTIPO_SERVICIO', models.CharField(choices=[('GAS', 'Gas'), ('PALLET', 'Pallet'), ('MAXIS', 'Maxis'), ('PETROLEO', 'Petróleo'), ('NITROGENO', 'Nitrógeno')], max_length=20, verbose_name='Tipo de servicio')),
                ('RSD_CPATENTE', models.CharField(db_index=True, max_length=32, verbose_name='Patente')),
                ('RSD_CNOMBRE_CHOFER', models.CharField(max_length=256, verbose_name='Nombre chofer')),
                ('RSD_COBSERVACION', models.TextField(blank=True, verbose_name='Observación')),
                ('RSD_FFECHACREACION', models.DateTimeField(auto_now_add=True, verbose_name='Fecha creación')),
                ('RSD_CIDEMPOTENCIA', models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='Clave idempotencia')),
                ('CI_NID', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='detalle_recepcion_servicio', to='home.citacion', verbose_name='Citación')),
                ('EP_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recepciones_servicio', to='home.empresa', verbose_name='Empresa')),
                ('PRO_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recepciones_servicio', to='home.socionegocio', verbose_name='Proveedor')),
                ('US_NID', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recepciones_servicio_creadas', to=settings.AUTH_USER_MODEL, verbose_name='Usuario creación')),
            ],
            options={
                'db_table': 'RECEPCION_SERVICIO_DETALLE',
                'indexes': [
                    models.Index(fields=['EP_NID', 'RSD_CPATENTE'], name='RS_DET_EP_PAT_IDX'),
                    models.Index(fields=['EP_NID', 'RSD_CTIPO_SERVICIO'], name='RS_DET_EP_TIPO_IDX'),
                ],
            },
        ),
        migrations.RunPython(
            crear_configuracion_recepcion_servicio,
            migrations.RunPython.noop,
        ),
    ]
