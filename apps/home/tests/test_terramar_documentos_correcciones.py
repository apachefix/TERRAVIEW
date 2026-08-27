import hashlib
import os
import tempfile

import fitz
from django.test import SimpleTestCase

from apps.home.services.terramar_documentos import STAMP_VERSION, timbrar_documento


class TimbradoTerramarVersion2Tests(SimpleTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original = os.path.join(self.tempdir.name, 'geometrias.pdf')
        self.timbrado = os.path.join(self.tempdir.name, 'geometrias_timbrado.pdf')
        document = fitz.open()
        document.new_page(width=595, height=842).insert_text((40, 60), 'VERTICAL')
        document.new_page(width=842, height=595).insert_text((40, 60), 'HORIZONTAL')
        rotated = document.new_page(width=595, height=842)
        rotated.insert_text((40, 60), 'ROTADA')
        rotated.set_rotation(90)
        cropped = document.new_page(width=420, height=300)
        cropped.set_cropbox(fitz.Rect(25, 20, 390, 275))
        cropped.insert_text((40, 60), 'CROPBOX')
        document.save(self.original)
        document.close()
        self.lines = [
            'ÁREA DE RECEPCIÓN',
            'Oficina de Operaciones',
            '05/08/2026 12:34',
            'Asistente de Despacho con Nombre Extenso',
            'Terramar SBH',
            '76.957.638-K',
        ]

    @staticmethod
    def _hash(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as source:
            digest.update(source.read())
        return digest.hexdigest()

    def test_version_2_sella_todas_las_geometrias_sin_alterar_original(self):
        original_hash = self._hash(self.original)
        resultado = timbrar_documento(self.original, self.timbrado, self.lines)
        self.assertEqual(STAMP_VERSION, 2)
        self.assertEqual(resultado['format'], 'PDF')
        self.assertEqual(self._hash(self.original), original_hash)

        with fitz.open(self.timbrado) as document:
            self.assertEqual(document.page_count, 4)
            for page in document:
                text = page.get_text()
                for line in self.lines:
                    self.assertIn(line, text)
                cropbox = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
                stamp_spans = [
                    span
                    for block in page.get_text('dict')['blocks']
                    for line in block.get('lines', [])
                    for span in line.get('spans', [])
                    if span.get('text') in self.lines
                ]
                self.assertEqual(len(stamp_spans), len(self.lines))
                for span in stamp_spans:
                    rect = fitz.Rect(span['bbox'])
                    self.assertGreaterEqual(rect.x0, cropbox.x0 - 1)
                    self.assertGreaterEqual(rect.y0, cropbox.y0 - 1)
                    self.assertLessEqual(rect.x1, cropbox.x1 + 1)
                    self.assertLessEqual(rect.y1, cropbox.y1 + 1)

    def test_pdf_resultante_abre_y_contiene_texto_en_todas_las_paginas(self):
        timbrar_documento(self.original, self.timbrado, self.lines)
        with fitz.open(self.timbrado) as document:
            self.assertEqual(
                sum('Terramar SBH' in page.get_text() for page in document),
                document.page_count,
            )
