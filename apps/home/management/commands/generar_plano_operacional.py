"""Offline conversion of the audited PDF. Does not access the database.

Removes vehicle vector paint operations fully contained in reviewed rectangles;
keeps crossing infrastructure paths, images and original page coordinates.
No redaction rectangles, generative redraw or runtime PDF rendering.
"""
import io
import json
import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# PDF points, origin at top left. Vehicle silhouettes reviewed on the source PDF.
VEHICULOS = (
    (490, 76, 656, 111), (463, 447, 630, 485),
    (205, 517, 387, 571), (205, 571, 387, 627),
    (205, 625, 387, 678), (205, 679, 387, 732), (205, 728, 387, 772),
    (1058, 190, 1119, 436), (0, 1220, 25, 1684),
)


def _filtrar_subtrazos(operations, alto, rectangles, fitz):
    """A single PDF paint can contain multiple independent subpaths (e.g. cabs).

    Remove only complete subpaths inside reviewed vehicle footprints, preserving
    crossing plant lines. The audited PDF uses straight m/l/h paths only.
    """
    matrix = (1., 0., 0., 1., 0., 0.)
    stack, result, paths, points, path = [], [], [], [], []
    removed = 0

    def flush_path():
        nonlocal path, points
        if path:
            paths.append((path, points))
        path, points = [], []

    def flush_paths(filter_vehicles):
        nonlocal removed
        flush_path()
        for commands, coords in paths:
            bounds = fitz.Rect(min(x for x, y in coords), min(y for x, y in coords),
                               max(x for x, y in coords), max(y for x, y in coords)) if coords else None
            inside = bounds is not None and any(
                r.x0 <= bounds.x0 <= bounds.x1 <= r.x1 and r.y0 <= bounds.y0 <= bounds.y1 <= r.y1
                for r in rectangles)
            if filter_vehicles and inside:
                removed += 1
            else:
                result.extend(commands)
        paths.clear()

    for args, op in operations:
        if op == b'm':
            flush_path()
        if op in (b'm', b'l', b'h'):
            path.append((args, op))
            if op != b'h':
                a, b, c, d, e, f = matrix
                x, y = map(float, args)
                points.append((a*x+c*y+e, alto-(b*x+d*y+f)))
            continue
        if op in (b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'):
            flush_paths(True)
        elif paths or path:
            # Clipping paths and non-paint operations must remain intact.
            flush_paths(False)
        if op == b'q':
            stack.append(matrix)
        elif op == b'Q':
            matrix = stack.pop()
        elif op == b'cm':
            a,b,c,d,e,f = matrix
            A,B,C,D,E,F = map(float, args)
            matrix = (a*A+c*B, b*A+d*B, a*C+c*D, b*C+d*D, a*E+c*F+e, b*E+d*F+f)
        result.append((args, op))
    flush_paths(False)
    return result, removed


class Command(BaseCommand):
    help = 'Genera PNG estático y coordenadas TK desde el PDF original, sin acceder a BD.'
    requires_system_checks = []

    def handle(self, *args, **options):
        import fitz
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ContentStream

        carpeta = Path(settings.CORE_DIR) / 'apps/static/assets/plano'
        origen = carpeta / 'plantilla_planta.pdf'
        if hashlib.sha256(origen.read_bytes()).hexdigest() != '3fc225e0d0b00feb71b36ba4ff5fd4cdde4fc5193c261f1ebd8f05ae3ceb6083':
            raise CommandError('El PDF cambió: revisar geometría, vehículos y hash antes de regenerar.')
        doc = fitz.open(origen)
        if len(doc) != 1:
            raise CommandError('Se esperaba el PDF auditado de una página.')
        pagina = doc[0]
        cajas = pagina.get_bboxlog()
        reader = PdfReader(origen)
        contenido = ContentStream(reader.pages[0].get_contents(), reader)
        rectangles = [fitz.Rect(*r) for r in VEHICULOS]
        indice, retirados = 0, 0
        operations = []
        kinds = {b'S': ['stroke-path'], b's': ['stroke-path'],
                 b'f': ['fill-path'], b'F': ['fill-path'], b'f*': ['fill-path'],
                 b'B': ['fill-path', 'stroke-path'], b'B*': ['fill-path', 'stroke-path'],
                 b'b': ['fill-path', 'stroke-path'], b'b*': ['fill-path', 'stroke-path'],
                 b'Tj': ['fill-text'], b'TJ': ['fill-text'], b'Do': ['fill-image']}
        for argumentos, operador in contenido.operations:
            expected = kinds.get(operador, [])
            boxes = cajas[indice:indice + len(expected)]
            if [b[0] for b in boxes] != expected:
                raise CommandError('Estructura PDF distinta: revisar antes de convertir.')
            indice += len(expected)
            if expected and all(k.endswith('-path') for k in expected) and all(
                any(r.contains(fitz.Rect(*b[1])) for r in rectangles) for b in boxes
            ):
                operations.append(([], b'n'))
                retirados += 1
            else:
                operations.append((argumentos, operador))
        if indice != len(cajas):
            raise CommandError('Operaciones PDF no reconocidas: no se generó imagen.')
        contenido.operations, subtrazos = _filtrar_subtrazos(operations, pagina.rect.height, rectangles, fitz)
        reader.pages[0].replace_contents(contenido)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        copia = io.BytesIO()
        writer.write(copia)
        limpio = fitz.open(stream=copia.getvalue(), filetype='pdf')
        imagen = limpio[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        imagen.save(carpeta / 'plantilla_planta.png')
        tanques = {}
        for x0, y0, x1, y1, palabra, *_ in pagina.get_text('words'):
            if palabra.startswith('TK-'):
                tanques[palabra] = {
                    'codigo': palabra, 'nombre': palabra, 'tipo': 'ESTANQUE',
                    'x_pct': round((x0 + x1) / 2 / pagina.rect.width * 100, 4),
                    'y_pct': round((y0 + y1) / 2 / pagina.rect.height * 100, 4),
                    'width_pct': 15, 'height_pct': 7, 'habilitado': True,
                }
        if len(tanques) != 12:
            raise CommandError('No se reconocieron los 12 estanques del plano.')
        (carpeta / 'estanques_plano.json').write_text(json.dumps(tanques, indent=2), encoding='utf-8')
        self.stdout.write(f'PNG {imagen.width}x{imagen.height}; {retirados} pinturas y {subtrazos} subtrazos de vehículos retirados; 12 TK. PDF original intacto.')
