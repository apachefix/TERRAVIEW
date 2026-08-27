from django.db import migrations


CONCEPTOS_TERRAMAR = (
    'SOBRESTADIA',
    'FERIADO',
    'NOCHE',
    'RETORNO VACIO',
    'REDESTINACION',
    'FLETE FALSO',
)


def habilitar_cantidad_extras_terramar(apps, schema_editor):
    Extra = apps.get_model('home', 'EXTRA')
    Extra.objects.filter(
        EP_NID_id=1,
        EXT_CTIPO_CITACION__in=('RECEPCION', 'DESPACHO'),
        EXT_CNOMBRE__in=CONCEPTOS_TERRAMAR,
    ).update(EXT_BPERMITECANTIDAD=True)


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0104_proforma_catalogo_completo_terramar'),
    ]

    operations = [
        migrations.RunPython(
            habilitar_cantidad_extras_terramar,
            migrations.RunPython.noop,
        ),
    ]