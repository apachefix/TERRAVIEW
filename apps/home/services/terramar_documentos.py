import hashlib
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
from io import BytesIO

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps
from django.utils.text import get_valid_filename
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics import renderPM


MAX_DOCUMENT_SIZE = 25 * 1024 * 1024
STAMP_VERSION = 2
PDF_EXTENSIONS = {'.pdf'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff'}
PATENTE_EXPORTACION_PATTERN = re.compile(r'^[A-Z0-9_-]+$')


def sha256_archivo(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def mime_archivo(path):
    return mimetypes.guess_type(path)[0] or 'application/octet-stream'


def formato_timbrable(path):
    extension = os.path.splitext(str(path or ''))[1].lower()
    if extension in PDF_EXTENSIONS:
        return 'PDF'
    if extension in IMAGE_EXTENSIONS:
        return 'IMAGEN'
    return ''


def validar_archivo_fuente(path):
    if not path or not os.path.isfile(path):
        raise ValueError('El archivo original no está disponible.')
    size = os.path.getsize(path)
    if size <= 0:
        raise ValueError('El archivo original está vacío.')
    if size > MAX_DOCUMENT_SIZE:
        raise ValueError('El archivo supera el máximo de 25 MB para timbrado.')
    return size


def sanitizar_patente_exportacion(value):
    raw = str(value or '').strip().upper()
    normalized = re.sub(r'\s+', '', raw)
    if (
        not normalized
        or '..' in normalized
        or not PATENTE_EXPORTACION_PATTERN.fullmatch(normalized)
    ):
        raise ValueError('La patente no es válida para crear la carpeta de documentos.')
    return normalized


def copiar_archivo_atomico(source_path, destination_path):
    source_size = validar_archivo_fuente(source_path)
    source_hash = sha256_archivo(source_path)
    destination_folder = os.path.dirname(destination_path)
    if not os.path.isdir(destination_folder):
        raise ValueError('La carpeta de destino no existe.')
    reemplaza_archivo = os.path.exists(destination_path)
    if reemplaza_archivo:
        if not os.path.isfile(destination_path):
            raise ValueError('El destino existe y no es un archivo.')
        if (
            os.path.getsize(destination_path) == source_size
            and sha256_archivo(destination_path) == source_hash
        ):
            return {
                'estado': 'REUTILIZADO',
                'hash': source_hash,
                'size': source_size,
            }

    descriptor, temporary_path = tempfile.mkstemp(
        prefix='.exporta_terramar_',
        suffix='.tmp',
        dir=destination_folder,
    )
    try:
        with os.fdopen(descriptor, 'wb') as destination, open(source_path, 'rb') as source:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if os.path.getsize(temporary_path) != source_size:
            raise OSError('La copia temporal no conserva el tamaño del documento.')
        if sha256_archivo(temporary_path) != source_hash:
            raise OSError('La copia temporal no conserva el contenido del documento.')
        os.replace(temporary_path, destination_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return {
        'estado': 'REEMPLAZADO' if reemplaza_archivo else 'COPIADO',
        'hash': source_hash,
        'size': source_size,
    }


def nombre_carpeta_exportacion_terramar(patente, fecha_exportacion, citacion_id):
    patente = sanitizar_patente_exportacion(patente)
    fecha = str(fecha_exportacion or '').strip()
    if not re.fullmatch(r'\d{8}', fecha):
        raise ValueError('La fecha de exportación no es válida.')
    try:
        citacion_id = int(citacion_id)
    except (TypeError, ValueError):
        raise ValueError('La citación no es válida.')
    if citacion_id <= 0:
        raise ValueError('La citación no es válida.')
    return sanitizar_patente_exportacion(f'{patente}_{fecha}_CIT{citacion_id}')


def exportar_documentos_timbrados(base_dir, patente, documentos, fecha_exportacion, citacion_id):
    """Copia un paquete Terramar ya validado a una carpeta local por citación."""
    base_dir = os.path.abspath(os.path.expandvars(str(base_dir or '').strip()))
    if not os.path.isdir(base_dir):
        raise ValueError(f'La carpeta base no existe: {base_dir}')

    carpeta_nombre = nombre_carpeta_exportacion_terramar(patente, fecha_exportacion, citacion_id)
    carpeta = os.path.abspath(os.path.join(base_dir, carpeta_nombre))
    if os.path.normcase(os.path.commonpath([base_dir, carpeta])) != os.path.normcase(base_dir):
        raise ValueError('La carpeta de patente no es segura.')
    os.makedirs(carpeta, exist_ok=True)

    copiados = []
    reutilizados = []
    reemplazados = []
    fallidos = []
    nombres_usados = set()
    for documento in documentos:
        nombre_fuente = documento.get('stamped_name') or documento.get('nombre') or 'documento'
        ruta = documento.get('stamped_path') if documento.get('timbrado_disponible') else ''
        try:
            if not ruta:
                raise ValueError('No existe una version timbrada disponible.')
            nombre = get_valid_filename(os.path.basename(nombre_fuente))
            if not nombre or nombre in {'.', '..'}:
                raise ValueError('El nombre del documento no es valido.')
            if nombre.lower() in nombres_usados:
                base_nombre, extension = os.path.splitext(nombre)
                clave = re.sub(r'[^A-Za-z0-9_-]', '', str(documento.get('key') or ''))[:10]
                nombre = f'{base_nombre}_{clave or "documento"}{extension}'
            nombres_usados.add(nombre.lower())

            destino = os.path.abspath(os.path.join(carpeta, nombre))
            if os.path.normcase(os.path.commonpath([carpeta, destino])) != os.path.normcase(carpeta):
                raise ValueError('El nombre del documento genera una ruta insegura.')
            resultado = copiar_archivo_atomico(ruta, destino)
            detalle = {
                'archivo': nombre,
                'hash': resultado['hash'],
                'size': resultado['size'],
                'mime': mime_archivo(ruta),
            }
            {
                'COPIADO': copiados,
                'REUTILIZADO': reutilizados,
                'REEMPLAZADO': reemplazados,
            }[resultado['estado']].append(detalle)
        except (OSError, ValueError) as exc:
            fallidos.append({'archivo': os.path.basename(nombre_fuente), 'error': str(exc)})

    total = len(copiados) + len(reutilizados) + len(reemplazados) + len(fallidos)
    disponibles = total - len(fallidos)
    return {
        'carpeta': carpeta,
        'archivos_copiados': copiados,
        'archivos_reutilizados': reutilizados,
        'archivos_reemplazados': reemplazados,
        'archivos_fallidos': fallidos,
        'total': total,
        'cantidad_disponible': disponibles,
        'cantidad_copiada': len(copiados),
        'cantidad_reutilizada': len(reutilizados),
        'cantidad_reemplazada': len(reemplazados),
        'cantidad_fallida': len(fallidos),
        'success': disponibles > 0 and not fallidos,
        'partial': disponibles > 0 and bool(fallidos),
    }

def _fuente_sello(size):
    for name in ('arialbd.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _codigo_barras_png(codigo, width=420, height=90):
    drawing = createBarcodeDrawing(
        'Code128', value=codigo, barHeight=55, barWidth=1.1,
        humanReadable=False, width=width, height=height,
    )
    return renderPM.drawToString(drawing, fmt='PNG')


def _timbrar_pdf(source_path, destination_path, stamp_lines, codigo_validacion):
    document = fitz.open(source_path)
    if document.page_count < 1:
        document.close()
        raise ValueError('El PDF no contiene páginas válidas.')
    try:
        for page in document:
            # Drawing coordinates are relative to the CropBox origin, even when
            # the CropBox itself has a non-zero position inside the MediaBox.
            # Its unrotated dimensions keep rotated and cropped pages visible.
            bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
            shortest_side = min(bounds.width, bounds.height)
            margin = min(max(shortest_side * 0.02, 4), 14)
            usable_width = max(bounds.width - (margin * 2), 1)
            usable_height = max(bounds.height - (margin * 2), 1)
            stamp_width = min(max(bounds.width * 0.38, 120), 285, usable_width)
            stamp_height = min(max(bounds.height * 0.16, 78), 126, usable_height)
            rect = fitz.Rect(
                bounds.x1 - margin - stamp_width,
                bounds.y1 - margin - stamp_height,
                bounds.x1 - margin,
                bounds.y1 - margin,
            )
            border_width = max(min(shortest_side / 600, 1.4), 0.6)
            padding = max(min(stamp_width, stamp_height) * 0.055, 3)
            barcode_height = min(max(stamp_height * 0.28, 22), 38)
            page.draw_rect(
                rect,
                color=(0, 0, 0),
                fill=(1, 1, 1),
                fill_opacity=0.90,
                width=border_width,
                overlay=True,
            )
            barcode_rect = fitz.Rect(rect.x0 + padding, rect.y0 + padding, rect.x1 - padding, rect.y0 + padding + barcode_height)
            page.insert_image(barcode_rect, stream=_codigo_barras_png(codigo_validacion), overlay=True)
            inner_width = max(stamp_width - (padding * 2), 1)
            inner_height = max(stamp_height - (padding * 2) - barcode_height, 1)
            line_count = max(len(stamp_lines), 1)
            base_size = max(min(11, inner_height / (line_count * 1.28)), 4.5)
            line_step = inner_height / line_count
            for index, raw_line in enumerate(stamp_lines):
                line = str(raw_line or '').strip()
                font_size = base_size
                text_width = fitz.get_text_length(line, fontname='helv', fontsize=font_size)
                if text_width > inner_width and text_width:
                    font_size = max(4, font_size * inner_width / text_width)
                    text_width = fitz.get_text_length(line, fontname='helv', fontsize=font_size)
                x = rect.x0 + padding + max((inner_width - text_width) / 2, 0)
                baseline = rect.y0 + padding + barcode_height + (index * line_step) + min(font_size, line_step * 0.82)
                page.insert_text(
                    (x, baseline),
                    line,
                    fontname='helv',
                    fontsize=font_size,
                    color=(0, 0, 0),
                    overlay=True,
                )
        document.save(destination_path, garbage=4, deflate=True)
    finally:
        document.close()
    verification = fitz.open(destination_path)
    try:
        if verification.page_count < 1:
            raise ValueError('La copia PDF timbrada no pudo validarse.')
        for page in verification:
            extracted = page.get_text()
            codigo_visible_requerido = any(codigo_validacion in str(line) for line in stamp_lines)
            if ('Oficina de Operaciones' not in extracted or
                    (codigo_visible_requerido and codigo_validacion not in extracted)):
                raise ValueError('El sello PDF no contiene el texto obligatorio visible.')
    finally:
        verification.close()


def _timbrar_imagen(source_path, destination_path, stamp_lines, codigo_validacion):
    with Image.open(source_path) as original:
        image = ImageOps.exif_transpose(original).convert('RGBA')
        width, height = image.size
        margin = max(int(min(width, height) * 0.025), 8)
        stamp_width = min(max(int(width * 0.42), 260), max(width - (margin * 2), 1))
        font_size = max(int(stamp_width / 30), 10)
        font = _fuente_sello(font_size)
        available_text_width = max(stamp_width - 16, 1)
        while font_size > 6:
            widest = max(
                (
                    ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox(
                        (0, 0),
                        str(line or ''),
                        font=font,
                    )[2]
                    for line in stamp_lines
                ),
                default=0,
            )
            if widest <= available_text_width:
                break
            font_size -= 1
            font = _fuente_sello(font_size)
        line_height = max(font_size + 4, 14)
        barcode_height = max(int(stamp_width * 0.18), 48)
        stamp_height = min((line_height * len(stamp_lines)) + barcode_height + 24, max(height - (margin * 2), 1))
        left = max(width - margin - stamp_width, 0)
        top = max(height - margin - stamp_height, 0)
        overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(
            (left, top, left + stamp_width, top + stamp_height),
            fill=(255, 255, 255, 215),
            outline=(0, 0, 0, 255),
            width=max(int(min(width, height) / 700), 2),
        )
        barcode_image = Image.open(BytesIO(_codigo_barras_png(codigo_validacion))).convert('RGBA')
        barcode_image.thumbnail((stamp_width - 16, barcode_height))
        overlay.alpha_composite(barcode_image, (left + 8, top + 8))
        y = top + 12 + barcode_image.height
        for line in stamp_lines:
            box = draw.textbbox((0, 0), line, font=font)
            text_width = box[2] - box[0]
            draw.text(
                (left + max((stamp_width - text_width) / 2, 4), y),
                line,
                fill=(0, 0, 0, 255),
                font=font,
            )
            y += line_height
        stamped = Image.alpha_composite(image, overlay)
        extension = os.path.splitext(destination_path)[1].lower()
        if extension in {'.jpg', '.jpeg'}:
            stamped.convert('RGB').save(destination_path, format='JPEG', quality=92)
        elif extension in {'.tif', '.tiff'}:
            stamped.convert('RGB').save(destination_path, format='TIFF')
        else:
            stamped.save(destination_path, format='PNG')
    with Image.open(destination_path) as verification:
        verification.verify()


def timbrar_documento(source_path, destination_path, stamp_lines, codigo_validacion=None):
    codigo_validacion = codigo_validacion or secrets.token_hex(12).upper()
    validar_archivo_fuente(source_path)
    document_type = formato_timbrable(source_path)
    if not document_type:
        raise ValueError('Formato no compatible con timbrado.')

    destination_folder = os.path.dirname(destination_path)
    os.makedirs(destination_folder, exist_ok=True)
    suffix = os.path.splitext(destination_path)[1]
    descriptor, temporary_path = tempfile.mkstemp(prefix='.timbrado_', suffix=suffix, dir=destination_folder)
    os.close(descriptor)
    try:
        if document_type == 'PDF':
            _timbrar_pdf(source_path, temporary_path, stamp_lines, codigo_validacion)
        else:
            _timbrar_imagen(source_path, temporary_path, stamp_lines, codigo_validacion)
        os.replace(temporary_path, destination_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise
    return {
        'mime': mime_archivo(destination_path),
        'size': os.path.getsize(destination_path),
        'hash': sha256_archivo(destination_path),
        'format': document_type,
    }
