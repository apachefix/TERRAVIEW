from django.db import migrations


PERFIL_CONTROL_FLOTA = 'CONTROL_FLOTA'
VISTA_AUTORIZAR_PROFORMA = 'proforma_autorizar'


def habilitar_autorizacion_proforma_control_flota(apps, schema_editor):
    Perfil = apps.get_model('home', 'PERFIL')
    Vista = apps.get_model('home', 'VISTA')
    Permiso = apps.get_model('home', 'PERMISO')

    perfiles = Perfil.objects.filter(
        PR_CCODIGO__iexact=PERFIL_CONTROL_FLOTA,
        PR_BHABILITADO=True,
    )
    perfil_referencia = perfiles.order_by('pk').first()
    if perfil_referencia is None:
        return

    vista = Vista.objects.filter(
        VI_CNOMBRE=VISTA_AUTORIZAR_PROFORMA,
        VI_BHABILITADO=True,
    ).order_by('pk').first()
    if vista is None:
        vista = Vista.objects.create(
            US_NID_id=perfil_referencia.US_NID_id,
            VI_CCODIGO=VISTA_AUTORIZAR_PROFORMA,
            VI_CNOMBRE=VISTA_AUTORIZAR_PROFORMA,
            VI_CDESCRIPCION=(
                'Autorizar Proforma y generar su Orden de Compra SAP.'
            ),
            VI_BHABILITADO=True,
        )

    for perfil in perfiles:
        permiso = Permiso.objects.filter(
            PR_NID_id=perfil.pk,
            VI_NID_id=vista.pk,
        ).order_by('pk').first()
        if permiso is None:
            Permiso.objects.create(
                US_NID_id=perfil.US_NID_id,
                PR_NID_id=perfil.pk,
                VI_NID_id=vista.pk,
                PE_BHABILITADO=True,
            )
        elif not permiso.PE_BHABILITADO:
            permiso.PE_BHABILITADO = True
            permiso.save(update_fields=['PE_BHABILITADO'])


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0107_ict_ajuste_manual'),
    ]

    operations = [
        migrations.RunPython(
            habilitar_autorizacion_proforma_control_flota,
            migrations.RunPython.noop,
        ),
    ]
