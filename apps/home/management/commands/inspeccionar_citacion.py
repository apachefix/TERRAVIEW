"""Informe temporal, estrictamente de lectura, para diagnosticar una citacion.

No importa views.py ni servicios operacionales: asi se evita, por diseno, que la
ejecucion active integraciones, notificaciones o cambios de estado.
"""
import html
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import ForeignKey, OneToOneField
from django.utils import timezone

from apps.home.models import CITACION, CITACION_ITEM, DATO_OPERACION, ETAPA_LOG, OPERACION_PLANTA_LOG


EMPTY = 'Sin informacion'
SENSITIVE = re.compile(r'(password|passwd|secret|token|credential|api.?key|cookie|webhook)', re.I)
DATE_HINT = re.compile(r'(fecha|ffecha|fecha|date|hora|time|registro|creacion|actualiza)', re.I)
ELI_WORDS = {
    'patente', 'conductor', 'proveedor', 'cliente', 'codigo sap', 'articulo', 'producto',
    'pedido', 'guia', 'peso bruto', 'tara', 'peso neto', 'fecha citacion', 'transportista',
    'sello', 'estanque', 'origen', 'destino', 'observacion', 'temperatura', 'folio',
}


def safe_value(value, field_name=''):
    """Serializa valores de BD sin exponer secretos ni leer archivos."""
    if SENSITIVE.search(field_name or ''):
        return '[OCULTO POR SEGURIDAD]'
    if value is None or value == '':
        return EMPTY
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=' ', timespec='seconds') if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, timedelta):
        return str(value)
    if hasattr(value, 'name') and value.__class__.__name__ in ('FieldFile', 'ImageFieldFile'):
        # storage.exists is intentionally the only file operation performed.
        try:
            exists = value.storage.exists(value.name) if value.name else False
        except Exception:
            exists = False
        return {'ruta': value.name or EMPTY, 'existe_fisicamente': exists}
    if isinstance(value, (dict, list, tuple)):
        return value
    return str(value) if not isinstance(value, (int, float, bool)) else value


def json_details(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return None
    return {'original': value, 'formateado': parsed, 'claves': list(parsed) if isinstance(parsed, dict) else []}


def serialize_instance(obj):
    rows = []
    for field in obj._meta.concrete_fields:
        raw = getattr(obj, field.name, None)
        value = safe_value(raw, field.name)
        row = {
            'campo': field.name, 'nombre': str(field.verbose_name), 'tipo': field.get_internal_type(),
            'valor': value, 'origen': obj._meta.db_table,
        }
        parsed = json_details(raw) if 'json' in field.name.lower() or isinstance(raw, str) else None
        if parsed:
            row['json'] = parsed
        if getattr(field, 'is_relation', False):
            row['relacion'] = str(raw) if raw is not None else EMPTY
        rows.append(row)
    return rows


def relation_field_for_citacion(model):
    for field in model._meta.concrete_fields:
        if isinstance(field, (ForeignKey, OneToOneField)) and field.remote_field.model is CITACION:
            return field
    # Legacy tables may retain an integer reference. Restrict it to names that
    # explicitly identify a citacion, avoiding speculative joins.
    for field in model._meta.concrete_fields:
        if field.name.lower() in ('ci_nid', 'ci_nid_id', 'citacion', 'citacion_id'):
            return field
    return None


def related_records(citacion):
    """Discover every installed model with a direct CITACION relation."""
    found, unconfirmed = {}, []
    for model in apps.get_models():
        if model is CITACION or model._meta.proxy or not model._meta.managed:
            continue
        field = relation_field_for_citacion(model)
        if not field:
            continue
        try:
            lookup = field.attname if isinstance(field, (ForeignKey, OneToOneField)) else field.name
            records = list(model.objects.filter(**{lookup: citacion.pk}).order_by('pk'))
            found[model._meta.db_table] = {
                'modelo': model._meta.label, 'campo_relacion': field.name,
                'registros': [serialize_instance(row) for row in records],
            }
        except Exception as exc:
            unconfirmed.append('%s: %s' % (model._meta.label, str(exc)))
    return found, unconfirmed


def configured_stages(citacion):
    try:
        model = apps.get_model('home', 'DETALLE_SECUENCIA')
        return [serialize_instance(row) for row in model.objects.filter(SC_NID=citacion.SC_NID).select_related('ET_NID').order_by('SE_NPASO')]
    except Exception as exc:
        return [{'aviso': 'No fue posible confirmar etapas configuradas: %s' % exc}]


def build_timeline(citacion, records):
    events = []
    for row in serialize_instance(citacion):
        if row['campo'] in ('CI_FFECHAREGISTRO', 'CI_FFECHAINICIO', 'CI_FFECHATERMINO', 'CI_FFECHACITACION') and row['valor'] != EMPTY:
            events.append({'fecha': row['valor'], 'evento': row['nombre'], 'etapa': '', 'usuario': '', 'perfil': '', 'fuente': 'CITACION', 'detalle': row['campo']})
    for table, source in records.items():
        for record in source['registros']:
            dates = [r for r in record if DATE_HINT.search(r['campo']) and r['valor'] != EMPTY]
            detail = '; '.join('%s=%s' % (r['campo'], r['valor']) for r in record[:8])
            for item in dates:
                events.append({'fecha': item['valor'], 'evento': table, 'etapa': '', 'usuario': '', 'perfil': '', 'fuente': table, 'detalle': detail})
    return sorted(events, key=lambda event: str(event['fecha']))


def field_words(row):
    return ('%s %s' % (row.get('campo', ''), row.get('nombre', ''))).lower().replace('_', ' ')


def eli_comparison(citacion_rows, records):
    all_rows = [('CITACION', row) for row in citacion_rows]
    all_rows += [(table, row) for table, source in records.items() for record in source['registros'] for row in record]
    result = []
    for source, row in all_rows:
        if row['valor'] == EMPTY or row.get('valor') == '[OCULTO POR SEGURIDAD]':
            continue
        appears = any(word in field_words(row) for word in ELI_WORDS)
        result.append({
            'dato': row['nombre'], 'fuente': source, 'valor': row['valor'],
            'aparece_en_eli': 'Probablemente si (coincidencia semantica)' if appears else 'No confirmado / no detectado',
            'recomendacion': 'evaluar' if not appears else 'dato duplicado',
        })
    return result


def duplicate_analysis(citacion_rows, records):
    values = defaultdict(list)
    for source, rows in [('CITACION', citacion_rows)]:
        for row in rows:
            if row['valor'] != EMPTY and not isinstance(row['valor'], (dict, list)):
                values[field_words(row)].append((source, row['valor']))
    for source, data in records.items():
        for record in data['registros']:
            for row in record:
                if row['valor'] != EMPTY and not isinstance(row['valor'], (dict, list)):
                    values[field_words(row)].append((source, row['valor']))
    return [{'dato': key, 'fuentes_y_valores': entries, 'coinciden': len({str(v) for _, v in entries}) == 1}
            for key, entries in values.items() if len(entries) > 1]


def to_jsonable(value):
    return value


def render_value(value):
    if isinstance(value, (dict, list)):
        return '<pre>%s</pre>' % html.escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    style = ' class="empty"' if value == EMPTY else ''
    return '<span%s>%s</span>' % (style, html.escape(str(value)))


def table(rows):
    if not rows:
        return '<p>Sin registros.</p>'
    if isinstance(rows[0], list):
        return ''.join('<details><summary>Registro %s</summary>%s</details>' % (i + 1, table(row)) for i, row in enumerate(rows))
    headers = list(rows[0].keys())
    return '<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (
        ''.join('<th>%s</th>' % html.escape(str(h)) for h in headers),
        ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % render_value(row.get(h, EMPTY)) for h in headers) for row in rows),
    )


def html_report(report):
    sections = []
    for title, body in report['secciones'].items():
        anchor = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        content = table(body) if isinstance(body, list) else '<pre>%s</pre>' % html.escape(json.dumps(body, ensure_ascii=False, indent=2, default=str))
        sections.append('<section id="%s"><details open><summary>%s</summary>%s</details></section>' % (anchor, html.escape(title), content))
    index = ''.join('<li><a href="#%s">%s</a></li>' % (re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-'), html.escape(t)) for t in report['secciones'])
    return '''<!doctype html><html lang="es"><meta charset="utf-8"><title>Inspeccion citacion %(id)s</title><style>
body{font:14px Arial;margin:24px;color:#17212b}table{border-collapse:collapse;width:100%%;margin:12px 0}th,td{border:1px solid #ccd6dd;padding:7px;text-align:left;vertical-align:top}th{background:#eaf2f7}.empty{color:#8b1e1e;background:#fff2f2}summary{font-size:18px;font-weight:bold;cursor:pointer;padding:12px;background:#f3f6f8}section{margin:16px 0}pre{white-space:pre-wrap;word-break:break-word;margin:0}.notice{background:#fff7db;padding:12px;border-left:4px solid #d79b00}</style>
<h1>Informe temporal de diagnostico â€” Citacion %(id)s</h1><p class="notice">Solo lectura. Generado: %(generated)s. No modifica E.L.I. ni datos operacionales.</p><h2>Indice</h2><ol>%(index)s</ol>%(sections)s</html>''' % {'id': report['citacion_id'], 'generated': report['generado_en'], 'index': index, 'sections': ''.join(sections)}


class Command(BaseCommand):
    help = 'Genera un informe temporal y de solo lectura para una citacion.'

    def add_arguments(self, parser):
        parser.add_argument('citacion_id', type=int)
        parser.add_argument('--formato', choices=('html', 'json', 'texto'), default='html')

    def handle(self, *args, **options):
        query_counter = []
        def contar_consulta(execute, sql, params, many, context):
            query_counter.append(sql)
            return execute(sql, params, many, context)
        query_wrapper = connection.execute_wrapper(contar_consulta)
        query_wrapper.__enter__()
        try:
            citacion = CITACION.objects.select_related('EP_NID', 'PL_NID', 'SN_NID', 'PRO_NID', 'RUT_NID', 'TAR_NID', 'SC_NID', 'CON_NID', 'CA_NID', 'US_NID').get(pk=options['citacion_id'])
        except CITACION.DoesNotExist:
            raise CommandError('No existe la citacion %s.' % options['citacion_id'])

        citacion_rows = serialize_instance(citacion)
        records, unconfirmed = related_records(citacion)
        plan_rows = serialize_instance(citacion.PL_NID) if citacion.PL_NID_id else []
        stages = configured_stages(citacion)
        timeline = build_timeline(citacion, records)
        duplicates = duplicate_analysis(citacion_rows, records)
        nonempty = sum(row['valor'] != EMPTY for row in citacion_rows) + sum(row['valor'] != EMPTY for data in records.values() for record in data['registros'] for row in record)
        total_records = sum(len(data['registros']) for data in records.values())
        sections = {
            '1. Identificacion de la citacion': citacion_rows,
            '2. Empresa, tipo y secuencia': [row for row in citacion_rows if row['campo'] in ('EP_NID', 'CI_CTIPO', 'SC_NID', 'CI_CESTADO', 'CI_FFECHAREGISTRO', 'CI_FFECHAINICIO', 'CI_FFECHATERMINO', 'US_NID', 'PL_NID')],
            '3. Planificacion': plan_rows,
            '4. Camion, conductor y transporte': [{'fuente': source, 'registros': data['registros']} for source, data in records.items() if any(word in source.lower() for word in ('camion', 'patio'))] + [r for r in citacion_rows if r['campo'] in ('CA_NID', 'CON_NID', 'RUT_NID')],
            '5. Datos operacionales': records.get('DATO_OPERACION', {}).get('registros', []),
            '6. Etapas configuradas': stages,
            '7. Logs de operacion planta': records.get('OPERACION_PLANTA_LOG', {}).get('registros', []),
            '8. Historial y auditoria': records.get('ETAPA_LOG', {}).get('registros', []),
            '9. Documentos': [data for table_name, data in records.items() if 'DOCUMENTO' in table_name or 'ADJUNTO' in table_name],
            '10. Pesajes': [data for table_name, data in records.items() if any(w in table_name for w in ('PESAJE', 'ROMANA', 'PESO'))],
            '11. Calidad y toma de muestra': [data for table_name, data in records.items() if any(w in table_name for w in ('CALIDAD', 'MUESTRA'))],
            '12. Carga o descarga': [data for table_name, data in records.items() if 'DETALLE' in table_name] + [r for r in citacion_rows if r['campo'] == 'CI_CTIPO'],
            '13. SAP local': [data for table_name, data in records.items() if 'SAP' in json.dumps(data, ensure_ascii=False, default=str).upper() or 'DETALLE' in table_name],
            '14. Informacion disponible que actualmente no aparece en E.L.I.': eli_comparison(citacion_rows, records),
            '15. Datos duplicados o contradictorios': duplicates,
            '16. Linea de tiempo completa': timeline,
            '17. Resumen final': [{'tablas_relacionadas': len(records), 'registros_totales': total_records, 'documentos': sum(len(v['registros']) for k, v in records.items() if 'DOCUMENTO' in k), 'etapas_log': len(records.get('ETAPA_LOG', {}).get('registros', [])), 'logs_operacion': len(records.get('OPERACION_PLANTA_LOG', {}).get('registros', [])), 'campos_con_informacion': nonempty, 'duplicados_o_contradicciones': len(duplicates), 'relaciones_no_confirmadas': len(unconfirmed)}],
            'Modelos y relaciones inspeccionados': [{'tabla': table_name, 'modelo': data['modelo'], 'campo_relacion': data['campo_relacion'], 'registros': len(data['registros'])} for table_name, data in records.items()],
            'Relaciones no confirmadas': [{'detalle': item} for item in unconfirmed],
        }
        report = {'citacion_id': citacion.pk, 'generado_en': timezone.now().isoformat(), 'solo_lectura': True, 'secciones': sections}
        output = Path(settings.BASE_DIR).parent / 'tmp' / 'inspeccion_citaciones'
        output.mkdir(parents=True, exist_ok=True)
        fmt = options['formato']
        filename = {'html': 'citacion_%s_informe.html', 'json': 'citacion_%s_datos.json', 'texto': 'citacion_%s_resumen.txt'}[fmt] % citacion.pk
        path = output / filename
        if fmt == 'html':
            path.write_text(html_report(report), encoding='utf-8')
        elif fmt == 'json':
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        else:
            path.write_text('INSPECCION TEMPORAL SOLO LECTURA - CITACION %s\n\n%s' % (citacion.pk, json.dumps(sections['17. Resumen final'], ensure_ascii=False, indent=2, default=str)), encoding='utf-8')
        query_wrapper.__exit__(None, None, None)
        query_count = len(query_counter)
        self.stdout.write(self.style.SUCCESS('Informe generado: %s' % path))
        self.stdout.write('Consultas ORM/DB registradas: %s. Solo se ejecutaron lecturas; no se llamaron servicios externos.' % query_count)



