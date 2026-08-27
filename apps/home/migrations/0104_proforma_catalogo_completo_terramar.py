from decimal import Decimal

from django.db import migrations
from django.utils import timezone


CONFIGURACION = {
    'SOBRESTADIA': (Decimal('45000'), True),
    'FERIADO': (Decimal('30000'), False),
    'NOCHE': (Decimal('15000'), False),
    'RETORNO VACIO': (Decimal('250000'), False),
    'REDESTINACION': (Decimal('250000'), False),
    'FLETE FALSO': (Decimal('100000'), False),
}


def completar_catalogo_terramar(apps, schema_editor):
    Empresa = apps.get_model('home', 'EMPRESA')
    if not Empresa.objects.filter(pk=1).exists():
        return
    Extra = apps.get_model('home', 'EXTRA')
    for nombre, (valor_base, permite_cantidad) in CONFIGURACION.items():
        fuente = Extra.objects.filter(
            EP_NID_id=1,
            EXT_CTIPO_CITACION='DESPACHO',
            EXT_CNOMBRE__iexact=nombre,
        ).order_by('pk').first()
        for tipo in ('RECEPCION', 'DESPACHO'):
            extra = Extra.objects.filter(
                EP_NID_id=1,
                EXT_CTIPO_CITACION=tipo,
                EXT_CNOMBRE__iexact=nombre,
            ).order_by('pk').first()
            if extra is None:
                extra = Extra.objects.create(
                    EP_NID_id=1,
                    EXT_CNOMBRE=nombre,
                    EXT_CDESCRIPCION=getattr(fuente, 'EXT_CDESCRIPCION', None),
                    EXT_FFECHAREGISTRO=timezone.now(),
                    EXT_BINGRESO=(fuente.EXT_BINGRESO if fuente else True),
                    EXT_CTIPO_CITACION=tipo,
                    EXT_CARTICULOSAP=getattr(fuente, 'EXT_CARTICULOSAP', None),
                    EXT_CCUENTASAP=getattr(fuente, 'EXT_CCUENTASAP', None),
                )
            extra.EXT_BHABILITADO = True
            extra.EXT_NVALORBASE = valor_base
            extra.EXT_BPERMITECANTIDAD = permite_cantidad
            extra.EXT_BPERMITEEDITARVALOR = True
            extra.save(update_fields=[
                'EXT_BHABILITADO',
                'EXT_NVALORBASE',
                'EXT_BPERMITECANTIDAD',
                'EXT_BPERMITEEDITARVALOR',
            ])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0103_proforma_extras_configuracion_terramar'),
    ]

    operations = [
        migrations.RunPython(completar_catalogo_terramar, migrations.RunPython.noop),
    ]
