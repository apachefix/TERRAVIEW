import hashlib
import json
import os
import tempfile
from datetime import time
from unittest.mock import patch

import fitz
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO,
    CAMPO,
    CAMION_PATIO,
    CAMION_PATIO_ADJUNTO,
    CITACION,
    CITACION_DOCUMENTO,
    DATO_OPERACION,
    DETALLE_SECUENCIA,
    EMPRESA,
    ETAPA,
    OPERACION_PLANTA_LOG,
    PERFIL,
    PERFIL_USUARIO,
    PLANIFICACION,
    SECUENCIA,
    SYSLOGGER,
    USERS_EMPRESA,
)


class OperacionPlantaTerramarEtapa2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.operador = User.objects.create_user('Operador_romana1', password='test')
        cls.bodega = User.objects.create_user('Asistente_bodega', password='test')
        cls.recepcion = User.objects.create_user('Asistente_Recepción', password='test')
        cls.despacho = User.objects.create_user('Asistente_Despacho', password='test')
        cls.guardia = User.objects.create_user('Guardia_Porteria', password='test')
        cls.ajeno = User.objects.create_user('Asistente_Despacho_ajeno', password='test')
        cls.empresa = EMPRESA.objects.create(
            id=1,
            EP_CRAZONSOCIAL='TERRAMAR CHILE',
            EP_CRUT='76.957.638-K',
            EP_CBASEDATOS='terramar_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        cls.otra_empresa = EMPRESA.objects.create(
            id=2,
            EP_CRAZONSOCIAL='OTRA EMPRESA',
            EP_CRUT='2-7',
            EP_CBASEDATOS='otra_test',
            EP_CUSUARIOSBD='test',
            EP_CPORT='5432',
        )
        for user in (cls.operador, cls.bodega, cls.recepcion, cls.despacho, cls.guardia):
            USERS_EMPRESA.objects.create(US_NID=user, EP_NID=cls.empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.ajeno, EP_NID=cls.otra_empresa)
        perfil_bodega = PERFIL.objects.create(
            US_NID=cls.bodega,
            PR_CCODIGO='ASISTENTE_CD',
            PR_CNOMBRE='ASISTENTE CD',
        )
        PERFIL_USUARIO.objects.create(US_NID=cls.bodega, PR_NID=perfil_bodega)
        cls.calendario = CALENDARIO.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            CA_CNOMBRE='Operacion Terramar Etapa 2',
            CA_FHORA_APERTURA=time(8),
            CA_FHORA_CIERRE=time(18),
            CA_NDIA=5,
            CA_NMES=8,
            CA_NANO=2026,
            CA_NCANTIDADCUPOS=10,
        )
        cls.planificacion = PLANIFICACION.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            CAL_NID=cls.calendario,
            PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.now(),
            PL_NCANTIDADCUPOS=10,
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TERRAMAR',
            SE_CNOMBRE='Recepcion Terramar',
            SE_BHABILITADO=True,
        )
        cls.etapa = ETAPA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_OPERACION_PLANTA',
            ET_CNOMBRE='Operacion Planta Terramar',
            ET_NCANTIDADMAXIMA=10,
            ET_BHABILITADO=True,
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            SC_NID=cls.secuencia,
            ET_NID=cls.etapa,
            SE_NPASO=1,
            SE_BHABILITADO=True,
            SE_BOBLIGATORIO=True,
        )
        cls.citacion = CITACION.objects.create(
            US_NID=cls.operador,
            EP_NID=cls.empresa,
            PL_NID=cls.planificacion,
            SC_NID=cls.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=1,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-ETAPA2',
        )

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.export_dir = os.path.join(self.tempdir.name, 'documentos_firmados')
        os.makedirs(self.export_dir, exist_ok=True)
        settings_context = self.settings(
            MEDIA_ROOT=self.tempdir.name,
            TERRAMAR_DOCUMENTOS_FIRMADOS_DIR=self.export_dir,
        )
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        self.ticket_dir = os.path.join(self.tempdir.name, 'tickets')
        os.makedirs(self.ticket_dir, exist_ok=True)
        ticket_patch = patch('apps.home.views.TICKET_PESAJE_LOCAL_PATH', self.ticket_dir)
        ticket_patch.start()
        self.addCleanup(ticket_patch.stop)

        SYSLOGGER.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            LOG_FFECHAREGISTRO=timezone.now(),
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(self.citacion.id),
        )
        for paso, user, perfil in (
            ('Pesaje Entrada', self.operador, 'OPERADOR ROMANA'),
            ('Ciclo Descarga', self.bodega, 'ASISTENTE CD'),
            ('Pesaje Salida', self.operador, 'OPERADOR ROMANA'),
        ):
            OPERACION_PLANTA_LOG.objects.create(
                US_NID=user,
                EP_NID=self.empresa,
                PL_NID=self.planificacion,
                CI_NID=self.citacion,
                OPL_CPASO=paso,
                OPL_CPERFIL_RESPONSABLE=perfil,
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            )

        self.pdf_path = os.path.join(self.tempdir.name, 'guia_original.pdf')
        self._crear_pdf(self.pdf_path, 'GUIA ORIGINAL TERRAMAR')
        self.image_path = os.path.join(self.tempdir.name, 'sernapesca_original.png')
        Image.new('RGB', (900, 1200), color='white').save(self.image_path)
        self.pdf_hash_original = self._hash(self.pdf_path)
        self.image_hash_original = self._hash(self.image_path)
        CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            CD_CTIPO=CITACION_DOCUMENTO.TIPO_GUIA,
            CD_CRUTA_ARCHIVO=self.pdf_path,
            CD_CNOMBRE_ARCHIVO='guia_original.pdf',
            US_SUBE_NID=self.recepcion,
        )
        CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            CD_CTIPO=CITACION_DOCUMENTO.TIPO_SERNAPESCA,
            CD_CRUTA_ARCHIVO=self.image_path,
            CD_CNOMBRE_ARCHIVO='sernapesca_original.png',
            US_SUBE_NID=self.recepcion,
        )
        self.camion = CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CI_NID=self.citacion,
            CPA_CPATENTE='ABCD12',
            CPA_CNOMBRE_CONDUCTOR='Conductor Terramar',
            CPA_CTELEFONO_CONDUCTOR='912345678',
            CPA_CCODIGO_PAIS_TELEFONO='+56',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.guardia,
        )
        with open(self.pdf_path, 'rb') as source:
            CAMION_PATIO_ADJUNTO.objects.create(
                CPA_NID=self.camion,
                CPA_FARCHIVO=ContentFile(source.read(), name='guia_duplicada.pdf'),
                CPA_CTIPO_DOCUMENTO=CAMION_PATIO_ADJUNTO.TIPO_GUIA,
                US_CARGA_ID=self.recepcion,
            )
        patio_other_path = os.path.join(self.tempdir.name, 'patio_otro.pdf')
        self._crear_pdf(patio_other_path, 'DOCUMENTO PATIO DIFERENTE')
        with open(patio_other_path, 'rb') as source:
            CAMION_PATIO_ADJUNTO.objects.create(
                CPA_NID=self.camion,
                CPA_FARCHIVO=ContentFile(source.read(), name='patio_otro.pdf'),
                CPA_CTIPO_DOCUMENTO=CAMION_PATIO_ADJUNTO.TIPO_OTRO,
                US_CARGA_ID=self.recepcion,
            )
        self._crear_ticket('ENT', 'Pesaje Entrada', 12000)
        self._crear_ticket('SAL', 'Pesaje Salida', 8000)

    def _crear_pdf(self, path, text):
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), text)
        document.save(path)
        document.close()

    def _hash(self, path):
        digest = hashlib.sha256()
        with open(path, 'rb') as source:
            digest.update(source.read())
        return digest.hexdigest()

    def _crear_ticket(self, tipo, paso, peso):
        path = os.path.join(self.ticket_dir, f'COM_{tipo}_ABCD12_26_08_05_10_00.pdf')
        self._crear_pdf(path, f'TICKET {tipo}')
        campo = views._obtener_campo_ticket_pesaje(self.citacion, tipo, self.operador)
        return DATO_OPERACION.objects.create(
            US_NID=self.operador,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            CAMP_NID=campo,
            CI_NID=self.citacion,
            DO_FFECHAREGISTRO=timezone.now(),
            DO_NPESO=peso,
            DO_CVALOR=json.dumps({
                'folio': f'FOLIO-{tipo}',
                'peso_neto': peso,
                'ruta_real_pdf': path,
                'nombre_archivo_pdf': os.path.basename(path),
                'patente': 'ABCD12',
                'tipo_ticket': tipo,
                'citacion_id': self.citacion.id,
                'paso_operacion': paso,
                'usuario_id': self.operador.id,
            }),
        )

    def endpoint(self, name, *extra):
        return '{}?_empresa_id={}&empresa_id={}'.format(
            reverse(name, args=[self.citacion.id, *extra]),
            self.empresa.id,
            self.empresa.id,
        )

    def post(self, user, name, data=None):
        self.client.force_login(user)
        return self.client.post(self.endpoint(name), data or {})

    def validar_documentacion(self):
        return self.post(
            self.recepcion,
            'ajax_operacion_planta_validar_documentacion_terramar',
            {'documentacion_validada': '1', 'observacion': 'Documentos revisados y conformes.'},
        )

    def timbrar(self, user=None):
        paso_activo = views.obtener_paso_activo_operacion(self.citacion)[0]
        responsable = user or (
            self.recepcion
            if (
                self.secuencia.SE_CCODIGO == 'RECEPCION_TERRAMAR'
                and paso_activo == views.PASO_DOCUMENTACION_TERRAMAR
            )
            else self.despacho
        )
        return self.post(responsable, 'ajax_operacion_planta_timbrar_documentos_terramar')
    def exportar(self, user=None):
        return self.post(
            user or self.despacho,
            'ajax_operacion_planta_exportar_documentos_terramar',
        )

    def test_fuentes_documentales_separan_tickets_y_deduplican_copia_patio(self):
        operational_path = os.path.join(self.tempdir.name, 'operacional.pdf')
        self._crear_pdf(operational_path, 'DOCUMENTO OPERACIONAL')
        campo = CAMPO.objects.create(
            US_NID=self.recepcion,
            EP_NID=self.empresa,
            CA_CCODIGO='OP_ARCHIVO_PRUEBA',
            CA_CTIPO='ARCHIVO',
            CA_CETIQUETA='Documento operacional',
            CA_CPLACEMARK='Documento operacional',
        )
        DATO_OPERACION.objects.create(
            US_NID=self.recepcion,
            EP_NID=self.empresa,
            SC_NID=self.secuencia,
            ET_NID=self.etapa,
            CAMP_NID=campo,
            CI_NID=self.citacion,
            DO_CVALOR=operational_path,
            DO_FFECHAREGISTRO=timezone.now(),
        )
        payload = views._payload_documentacion_terramar(self.citacion)
        self.assertEqual(len(payload['originales']), 2)
        self.assertEqual(len(payload['tickets']), 1)
        self.assertEqual(len(payload['antecedentes']), 1)
        self.assertEqual(
            {item['origen'] for item in payload['originales']},
            {'CITACION_DOCUMENTO'},
        )
        self.assertEqual(payload['tickets'][0]['tipo'], 'Ticket Pesaje Salida')
        self.assertEqual(payload['antecedentes'][0]['tipo'], 'Ticket Pesaje Entrada')
        self.assertNotIn('COM_ENT', json.dumps(payload['timbrados']))
        self.assertNotIn(self.tempdir.name, json.dumps(payload))
        self.assertTrue(all(item['download_url'] for item in payload['originales'] + payload['tickets'] + payload['antecedentes']))

    def test_documentacion_exige_checkbox_perfil_empresa_y_es_idempotente_409(self):
        sin_checkbox = self.post(self.recepcion, 'ajax_operacion_planta_validar_documentacion_terramar')
        self.assertEqual(sin_checkbox.status_code, 400, sin_checkbox.content)
        for user in (self.operador, self.bodega, self.despacho, self.guardia, self.ajeno):
            with self.subTest(user=user.username):
                response = self.post(
                    user,
                    'ajax_operacion_planta_validar_documentacion_terramar',
                    {'documentacion_validada': '1'},
                )
                self.assertEqual(response.status_code, 403, response.content)

        pendiente = self.validar_documentacion()
        self.assertEqual(pendiente.status_code, 409, pendiente.content)
        self.assertIn('timbrar', pendiente.json()['message'].lower())
        self.assertEqual(self.timbrar().status_code, 200)

        response = self.validar_documentacion()
        self.assertEqual(response.status_code, 200, response.content)
        log = OPERACION_PLANTA_LOG.objects.get(CI_NID=self.citacion, OPL_CPASO='Documentación')
        self.assertEqual(log.US_NID, self.recepcion)
        self.assertEqual(log.OPL_CPERFIL_RESPONSABLE, 'ASISTENTE RECEPCION')
        self.assertEqual(log.OPL_COBSERVACION, 'Documentos revisados y conformes.')
        self.assertTrue(response.json()['salida_autorizada'])
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')
        metadata = views._leer_metadata_terramar(
            self.citacion,
            views.CAMPO_DOCUMENTACION_TERRAMAR,
        )
        self.assertTrue(metadata['validada'])
        self.assertTrue(metadata['salida_autorizada'])
        self.assertEqual(metadata['accion'], 'AUTORIZA_SALIDA')
        self.assertEqual(metadata['usuario_autorizacion_id'], self.recepcion.id)
        self.assertEqual(
            OPERACION_PLANTA_LOG.objects.filter(
                CI_NID=self.citacion,
                OPL_CPASO='Documentación',
                OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            ).count(),
            1,
        )
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Autorizar Salida',
        ).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUT_SALIDA_TER',
            LOG_CADD1=str(self.citacion.id),
        ).exists())
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='DOC_VALIDA_TER',
            LOG_CADD1=str(self.citacion.id),
        ).exists())
        repeated = self.validar_documentacion()
        self.assertEqual(repeated.status_code, 409, repeated.content)

    def test_timbrado_pdf_imagen_conserva_originales_contenido_e_idempotencia(self):
        response = self.timbrar()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['generados'], 3)
        self.assertEqual(self._hash(self.pdf_path), self.pdf_hash_original)
        self.assertEqual(self._hash(self.image_path), self.image_hash_original)

        metadata = views._leer_metadata_terramar(self.citacion, views.CAMPO_TIMBRADO_TERRAMAR)
        self.assertEqual(len(metadata['documentos']), 3)
        self.assertEqual(metadata['stamp_version'], 2)
        self.assertTrue(all(item['stamp_version'] == 2 for item in metadata['documentos']))
        pdf_stamped = next(item for item in metadata['documentos'] if item['source_name'] == 'guia_original.pdf')
        image_stamped = next(item for item in metadata['documentos'] if item['source_name'] == 'sernapesca_original.png')
        with fitz.open(pdf_stamped['stamped_path']) as document:
            text = ''.join(page.get_text() for page in document)
        self.assertIn('ÁREA DE RECEPCIÓN', text)
        self.assertIn('Oficina de Operaciones', text)
        self.assertIn('Terramar Chile SpA', text)
        self.assertIn('77.620.020-4', text)
        codigos = [item['codigo_validacion'] for item in metadata['documentos']]
        self.assertEqual(len(codigos), len(set(codigos)))
        self.assertTrue(all(len(codigo) == 24 for codigo in codigos))
        self.assertIn(pdf_stamped['codigo_validacion'], text)
        expediente_eli = views.construir_archivo_eli(self.citacion, sincronizar=False)
        validaciones_eli = expediente_eli['validaciones_documentos_terramar']
        self.assertEqual(
            {item['codigo_validacion'] for item in validaciones_eli},
            set(codigos),
        )
        self.assertTrue(all(item['citacion_id'] == self.citacion.id for item in validaciones_eli))
        self.assertTrue(all(item['empresa_id'] == self.empresa.id for item in validaciones_eli))
        self.assertTrue(all(item['usuario_id'] == self.recepcion.id for item in validaciones_eli))
        self.assertTrue(all(item['hash_original'] and item['hash_timbrado'] for item in validaciones_eli))
        self.assertIn(self.recepcion.username, text)
        self.assertIn(pdf_stamped['fecha_timbrado'].split(' ')[0], text)
        with Image.open(image_stamped['stamped_path']) as image:
            image.verify()
        repeated = self.timbrar()
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.json()['generados'], 0)
        self.assertEqual(repeated.json()['reutilizados'], 3)

    def test_timbrado_restringe_perfiles_y_rechaza_documento_manipulado(self):
        for user in (self.despacho, self.bodega, self.guardia, self.operador, self.ajeno):
            with self.subTest(user=user.username):
                response = self.post(user, 'ajax_operacion_planta_timbrar_documentos_terramar')
                self.assertEqual(response.status_code, 403, response.content)
        self.client.force_login(self.despacho)
        manipulated = self.client.get(self.endpoint('ajax_operacion_planta_documento_terramar', 'clave-manipulada'))
        self.assertEqual(manipulated.status_code, 404, manipulated.content)

    def test_descarga_original_y_timbrado_quedan_protegidas_por_citacion(self):
        self.assertEqual(self.timbrar().status_code, 200)
        self.assertEqual(self.validar_documentacion().status_code, 200)
        source = views._documentos_fuente_terramar(self.citacion)[0]
        self.client.force_login(self.despacho)
        original = self.client.get(self.endpoint('ajax_operacion_planta_documento_terramar', source['key']))
        self.assertEqual(original.status_code, 200)
        for closer in original._resource_closers:
            closer()
        stamped_url = self.endpoint('ajax_operacion_planta_documento_terramar', source['key']).replace('?_empresa', '?version=timbrado&_empresa')
        stamped = self.client.get(stamped_url)
        self.assertEqual(stamped.status_code, 200)
        for closer in stamped._resource_closers:
            closer()
        antecedente = views._payload_documentacion_terramar(self.citacion)['antecedentes'][0]
        antecedente_timbrado_url = self.endpoint(
            'ajax_operacion_planta_documento_terramar',
            antecedente['key'],
        ).replace('?_empresa', '?version=timbrado&_empresa')
        antecedente_timbrado = self.client.get(antecedente_timbrado_url)
        self.assertEqual(antecedente_timbrado.status_code, 404, antecedente_timbrado.content)

        self.client.force_login(self.ajeno)
        forbidden = self.client.get(self.endpoint('ajax_operacion_planta_documento_terramar', source['key']))
        self.assertEqual(forbidden.status_code, 403, forbidden.content)

    def test_exportacion_incluye_citacion_documento_com_sal_excluye_com_ent_y_es_idempotente(self):
        self.assertEqual(self.timbrar().status_code, 200)

        response = self.exportar(self.recepcion)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertFalse(payload['partial'])
        self.assertEqual(payload['cantidad_copiada'], 3)
        self.assertEqual(payload['cantidad_reutilizada'], 0)
        self.assertRegex(os.path.basename(payload['carpeta']), rf'^ABCD12_\d{{8}}_CIT{self.citacion.id}$')
        archivos = os.listdir(payload['carpeta'])
        self.assertEqual(len(archivos), 3)
        self.assertTrue(any(nombre.startswith('COM_SAL') for nombre in archivos))
        self.assertFalse(any(nombre.startswith('COM_ENT') for nombre in archivos))
        self.assertTrue(any(nombre.startswith('guia_original_') for nombre in archivos))
        self.assertTrue(any(nombre.startswith('sernapesca_original_') for nombre in archivos))

        repeated = self.exportar(self.recepcion)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.json()['cantidad_copiada'], 0)
        self.assertEqual(repeated.json()['cantidad_reutilizada'], 3)
        self.assertEqual(os.listdir(payload['carpeta']), archivos)
        self.assertTrue(SYSLOGGER.objects.filter(
            EP_NID=self.empresa,
            LOG_COPERACION='EXPORTA_DOC_TER',
            LOG_CADD1=str(self.citacion.id),
        ).exists())
        self.assertEqual(self.validar_documentacion().status_code, 200)

    def test_exportacion_admite_bodega_externa_y_restringe_perfil(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        self.assertEqual(self.validar_documentacion().status_code, 200)
        _, pasos = views.obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(dict(pasos)['Autorizar Salida'], ['ASISTENTE DESPACHO'])
        self.client.force_login(self.despacho)
        panel = self.client.get(self.endpoint('operacion_planta_citacion'))
        self.assertContains(panel, 'Paquete documental de salida')
        self.assertEqual(self.timbrar().status_code, 200)
        forbidden = self.exportar(self.recepcion)
        self.assertEqual(forbidden.status_code, 403, forbidden.content)
        allowed = self.exportar()
        self.assertEqual(allowed.status_code, 200, allowed.content)

    def test_exportacion_rechaza_sbh_sin_carpeta_ni_auditoria(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_ESTANQUE_SBH'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        response = self.exportar()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(os.path.exists(os.path.join(self.export_dir, 'ABCD12')))
        self.assertFalse(SYSLOGGER.objects.filter(
            LOG_COPERACION='EXPORTA_DOC_TER',
            LOG_CADD1=str(self.citacion.id),
        ).exists())

    def test_documentacion_autoriza_salida_directa_sin_invocar_sap(self):
        endpoint_anterior = self.post(self.recepcion, 'ajax_operacion_planta_autorizar_salida')
        self.assertEqual(endpoint_anterior.status_code, 409, endpoint_anterior.content)
        self.assertIn('documentacion', endpoint_anterior.json()['message'].lower())

        before_stamp = self.validar_documentacion()
        self.assertEqual(before_stamp.status_code, 409, before_stamp.content)
        self.assertEqual(self.timbrar().status_code, 200)

        with (
            patch('apps.home.views.get_goods_receipt_draft_update_status', side_effect=AssertionError('SAP no debe consultarse')),
            patch('apps.home.views.send_goods_receipt_draft_update_to_sap', side_effect=AssertionError('SAP no debe actualizarse')),
        ):
            response = self.validar_documentacion()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['salida_autorizada'])
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Autorizar Salida',
        ).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUT_SALIDA_TER',
            LOG_CADD1=str(self.citacion.id),
        ).exists())
        repeated = self.post(self.recepcion, 'ajax_operacion_planta_autorizar_salida')
        self.assertEqual(repeated.status_code, 409, repeated.content)

    def test_autorizar_desde_documentacion_restringe_perfiles_y_exige_ticket_salida(self):
        self.assertEqual(self.timbrar().status_code, 200)
        for user in (self.despacho, self.bodega, self.operador, self.guardia, self.ajeno):
            with self.subTest(user=user.username):
                response = self.post(
                    user,
                    'ajax_operacion_planta_validar_documentacion_terramar',
                    {'documentacion_validada': '1'},
                )
                self.assertEqual(response.status_code, 403, response.content)
        DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views._codigo_campo_ticket_pesaje('SAL'),
        ).delete()
        missing_ticket = self.validar_documentacion()
        self.assertEqual(missing_ticket.status_code, 409, missing_ticket.content)
        self.assertIn('ticket', missing_ticket.json()['message'].lower())
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Documentación',
        ).exists())

    def test_documentacion_sin_originales_exige_timbrar_com_sal(self):
        CITACION_DOCUMENTO.objects.filter(CI_NID=self.citacion).delete()
        payload = views._payload_documentacion_terramar(self.citacion)
        self.assertEqual(payload['originales'], [])
        self.assertEqual([item['tipo'] for item in payload['tickets']], ['Ticket Pesaje Salida'])

        pendiente = self.validar_documentacion()
        self.assertEqual(pendiente.status_code, 409, pendiente.content)
        stamp = self.timbrar()
        self.assertEqual(stamp.status_code, 200, stamp.content)
        self.assertEqual(stamp.json()['generados'], 1)
        self.assertEqual(self.validar_documentacion().status_code, 200)

    def test_documentacion_sin_ticket_salida_bloquea_autorizacion(self):
        CITACION_DOCUMENTO.objects.filter(CI_NID=self.citacion).delete()
        DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO__in={
                views._codigo_campo_ticket_pesaje('ENT'),
                views._codigo_campo_ticket_pesaje('SAL'),
            },
        ).delete()

        payload = views._payload_documentacion_terramar(self.citacion)
        self.assertEqual(payload['total_documentos'], 0)
        response = self.validar_documentacion()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn('ticket', response.json()['message'].lower())

    def test_timbraje_en_documentacion_no_se_renderiza_en_bodega_externa(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        self.client.force_login(self.recepcion)
        response = self.client.get(self.endpoint('operacion_planta_citacion'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotContains(response, 'class="btn btn-dark btn-timbrar-documentos-terramar"')
        self.assertEqual(self.validar_documentacion().status_code, 200)
        self.assertEqual(self.timbrar().status_code, 200)

    def test_panel_documentacion_renderiza_autorizacion_final_y_cinco_etapas(self):
        _, pasos = views.obtener_pasos_operacion_citacion(self.citacion)
        self.assertEqual(
            [nombre for nombre, _ in pasos],
            [
                'Pesaje Entrada',
                'Ciclo Descarga',
                'Pesaje Salida',
                'Documentación',
                'Confirmar Salida',
            ],
        )
        self.assertNotIn('Autorizar Salida', dict(pasos))
        self.assertEqual(dict(pasos)['Confirmar Salida'], ['GUARDIA PORTERIA'])

        self.client.force_login(self.recepcion)
        response = self.client.get(self.endpoint('operacion_planta_citacion'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, 'He validado la documentación')
        self.assertContains(response, 'AUTORIZAR SALIDA')
        self.assertNotContains(response, 'operacion-autorizar-terramar-simple')
        self.assertContains(response, 'guia_original.pdf')
        self.assertContains(response, 'Ticket Pesaje Salida')
        self.assertContains(response, 'Antecedentes no incluidos en salida')
        self.assertContains(response, 'Documentos timbrados')
        self.assertContains(response, 'Timbrar documentos')
        self.assertContains(
            response,
            reverse('ajax_operacion_planta_timbrar_documentos_terramar', args=[self.citacion.id]),
        )
        self.assertNotContains(response, self.tempdir.name)

        self.assertEqual(self.timbrar().status_code, 200)
        stamped_panel = self.client.get(self.endpoint('operacion_planta_citacion'))
        self.assertContains(stamped_panel, '_timbrado')
        self.assertEqual(self.validar_documentacion().status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')

        timbrado_fuera_de_etapa = self.post(
            self.recepcion,
            'ajax_operacion_planta_timbrar_documentos_terramar',
        )
        self.assertEqual(timbrado_fuera_de_etapa.status_code, 409, timbrado_fuera_de_etapa.content)
        exportacion_fuera_de_etapa = self.exportar(self.recepcion)
        self.assertEqual(exportacion_fuera_de_etapa.status_code, 409, exportacion_fuera_de_etapa.content)

    def test_documentacion_historica_completada_resuelve_confirmar_sin_etapa_intermedia(self):
        views._guardar_metadata_terramar(
            self.citacion,
            self.recepcion,
            views.CAMPO_DOCUMENTACION_TERRAMAR,
            'Validacion documental Terramar',
            {
                'validada': True,
                'usuario_id': self.recepcion.id,
                'usuario': self.recepcion.username,
                'citacion_id': self.citacion.id,
                'paso_operacion': 'Documentación',
            },
        )
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.recepcion,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO='Documentación',
            OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Autorizar Salida',
        ).exists())
        repeated_documentation = self.validar_documentacion()
        self.assertEqual(repeated_documentation.status_code, 409, repeated_documentation.content)

    def test_confirmar_salida_solo_guardia_despues_de_autorizacion(self):
        early = self.post(
            self.guardia,
            'operacion_planta_guardar_paso',
            {'paso': 'Confirmar Salida', 'observacion': 'Salida física.'},
        )
        self.assertEqual(early.status_code, 409, early.content)
        self.assertEqual(self.timbrar().status_code, 200)
        self.assertEqual(self.validar_documentacion().status_code, 200)
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')
        wrong_user = self.post(
            self.despacho,
            'operacion_planta_guardar_paso',
            {'paso': 'Confirmar Salida'},
        )
        self.assertEqual(wrong_user.status_code, 403, wrong_user.content)
        with patch.object(views, 'liberar_reservas_estanque_citacion') as liberar_reservas:
            confirmed = self.post(
                self.guardia,
                'operacion_planta_guardar_paso',
                {'paso': 'Confirmar Salida', 'observacion': 'Salida física confirmada.'},
            )
        liberar_reservas.assert_not_called()
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.citacion.refresh_from_db()
        self.camion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertEqual(
            self.camion.CPA_CESTADO,
            CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA,
        )
        self.assertEqual(self.camion.CI_NID_id, self.citacion.id)
        self.assertIsNone(
            views._camion_patio_activo_por_patente(
                self.camion.CPA_CPATENTE, self.empresa.id,
            )
        )
        self.client.force_login(self.guardia)
        estado_response = self.client.get(
            reverse('estado_camion_ajax'),
            {
                '_empresa_id': self.empresa.id,
                'empresa_id': self.empresa.id,
                'patente': self.camion.CPA_CPATENTE,
            },
        )
        self.assertNotIn(
            estado_response.json().get('tipo_resultado'),
            {'PROCESO_ACTIVO', 'INGRESO_PATIO_PENDIENTE'},
        )
        nuevo_camion = CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CPA_CPATENTE=self.camion.CPA_CPATENTE,
            CPA_CNOMBRE_CONDUCTOR='Nuevo ciclo',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=self.guardia,
        )
        self.assertNotEqual(nuevo_camion.id, self.camion.id)
        self.assertTrue(CAMION_PATIO.objects.filter(pk=self.camion.id).exists())
        self.assertEqual(
            views._camion_patio_activo_por_patente(
                self.camion.CPA_CPATENTE, self.empresa.id,
            ).id,
            nuevo_camion.id,
        )
        repeated = self.post(self.guardia, 'operacion_planta_guardar_paso', {'paso': 'Confirmar Salida'})
        self.assertEqual(repeated.status_code, 409, repeated.content)

    def test_confirmar_salida_no_completado_no_cierra_ciclo(self):
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO=views.PASO_CONFIRMAR_SALIDA,
            OPL_CPERFIL_RESPONSABLE='GUARDIA PORTERIA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
        )

        activo = views._camion_patio_activo_por_patente(
            self.camion.CPA_CPATENTE, self.empresa.id,
        )
        self.assertEqual(activo.id, self.camion.id)
        self.camion.refresh_from_db()
        self.assertEqual(
            self.camion.CPA_CESTADO,
            CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        )

    def test_asociado_legado_con_salida_completada_se_normaliza_lazy(self):
        citacion_historica_id = self.camion.CI_NID_id
        fecha_actualizacion_anterior = self.camion.CPA_FFECHAACTUALIZACION
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.guardia,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            CI_NID=self.citacion,
            OPL_CPASO=views.PASO_CONFIRMAR_SALIDA,
            OPL_CPERFIL_RESPONSABLE='GUARDIA PORTERIA',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
        )

        self.assertIsNone(views._camion_patio_activo_por_patente(
            self.camion.CPA_CPATENTE, self.empresa.id,
        ))
        self.camion.refresh_from_db()
        self.assertEqual(
            self.camion.CPA_CESTADO,
            CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA,
        )
        self.assertEqual(self.camion.CI_NID_id, citacion_historica_id)
        self.assertGreater(
            self.camion.CPA_FFECHAACTUALIZACION,
            fecha_actualizacion_anterior,
        )

        self.client.force_login(self.guardia)
        estado = self.client.get(reverse('estado_camion_ajax'), {
            '_empresa_id': self.empresa.id,
            'empresa_id': self.empresa.id,
            'patente': self.camion.CPA_CPATENTE,
        })
        self.assertNotIn(
            estado.json().get('tipo_resultado'),
            {'PROCESO_ACTIVO', 'INGRESO_PATIO_PENDIENTE'},
        )

    def test_estados_pendiente_y_asociado_bloquean_como_ciclos_activos(self):
        asociado = views._camion_patio_activo_por_patente(
            self.camion.CPA_CPATENTE, self.empresa.id,
        )
        self.assertEqual(asociado.id, self.camion.id)
        pendiente = CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CPA_CPATENTE='PEND01',
            CPA_CNOMBRE_CONDUCTOR='Pendiente',
            CPA_CTIPO_DOCUMENTO=CAMION_PATIO.TIPO_DOCUMENTO_GUIA_DESPACHO,
            CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION,
            US_GUARDIA_ID=self.guardia,
        )
        self.assertEqual(
            views._camion_patio_activo_por_patente('PEND01', self.empresa.id).id,
            pendiente.id,
        )

    def test_error_al_cerrar_camion_revierte_confirmacion_de_salida(self):
        self.assertEqual(self.timbrar().status_code, 200)
        self.assertEqual(self.validar_documentacion().status_code, 200)
        with patch.object(
            views, '_cerrar_ciclo_camion_patio',
            side_effect=RuntimeError('fallo controlado'),
        ):
            with self.assertRaises(RuntimeError):
                self.post(
                    self.guardia,
                    'operacion_planta_guardar_paso',
                    {'paso': 'Confirmar Salida'},
                )
        self.citacion.refresh_from_db()
        self.camion.refresh_from_db()
        self.assertEqual(self.citacion.CI_CESTADO, 'EN PROCESO')
        self.assertEqual(
            self.camion.CPA_CESTADO,
            CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
        )
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Confirmar Salida',
        ).exists())

    def test_formato_obligatorio_no_compatible_bloquea_autorizacion_sin_corromper(self):
        unsupported = os.path.join(self.tempdir.name, 'documento_obligatorio.txt')
        with open(unsupported, 'wb') as target:
            target.write(b'contenido original no compatible')
        original_hash = self._hash(unsupported)
        CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion,
            EP_NID=self.empresa,
            CD_CTIPO=CITACION_DOCUMENTO.TIPO_TICKET_ORIGEN,
            CD_CRUTA_ARCHIVO=unsupported,
            CD_CNOMBRE_ARCHIVO='documento_obligatorio.txt',
            US_SUBE_NID=self.recepcion,
        )
        stamp = self.timbrar()
        self.assertEqual(stamp.status_code, 200, stamp.content)
        self.assertEqual(self._hash(unsupported), original_hash)
        metadata = views._leer_metadata_terramar(self.citacion, views.CAMPO_TIMBRADO_TERRAMAR)
        record = next(item for item in metadata['documentos'] if item['source_name'].endswith('.txt'))
        self.assertEqual(record['estado'], 'NO_COMPATIBLE')
        validation = self.validar_documentacion()
        self.assertEqual(validation.status_code, 409, validation.content)
        self.assertFalse(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=self.citacion,
            OPL_CPASO='Documentación',
        ).exists())

    def test_stamp_version_1_se_regenera_y_version_2_se_reutiliza(self):
        self.assertEqual(self.timbrar().status_code, 200)
        metadata = views._leer_metadata_terramar(
            self.citacion,
            views.CAMPO_TIMBRADO_TERRAMAR,
        )
        metadata['stamp_version'] = 1
        for documento in metadata['documentos']:
            documento['stamp_version'] = 1
        views._guardar_metadata_terramar(
            self.citacion,
            self.recepcion,
            views.CAMPO_TIMBRADO_TERRAMAR,
            'Documentos timbrados Terramar',
            metadata,
        )

        regenerated = self.timbrar()
        self.assertEqual(regenerated.status_code, 200, regenerated.content)
        self.assertEqual(regenerated.json()['generados'], 3)
        self.assertEqual(regenerated.json()['reutilizados'], 0)
        repeated = self.timbrar()
        self.assertEqual(repeated.json()['generados'], 0)
        self.assertEqual(repeated.json()['reutilizados'], 3)

    def test_com_ent_no_se_timbra_ni_es_requisito_para_autorizar(self):
        DATO_OPERACION.objects.filter(
            CI_NID=self.citacion,
            CAMP_NID__CA_CCODIGO=views._codigo_campo_ticket_pesaje('ENT'),
        ).delete()
        stamp = self.timbrar()
        self.assertEqual(stamp.status_code, 200, stamp.content)
        metadata = views._leer_metadata_terramar(
            self.citacion,
            views.CAMPO_TIMBRADO_TERRAMAR,
        )
        self.assertFalse(any('COM_ENT' in item['source_name'] for item in metadata['documentos']))
        self.assertTrue(any('COM_SAL' in item['source_name'] for item in metadata['documentos']))
        authorization = self.validar_documentacion()
        self.assertEqual(authorization.status_code, 200, authorization.content)
        self.assertTrue(authorization.json()['salida_autorizada'])
        self.assertEqual(views.obtener_paso_activo_operacion(self.citacion)[0], 'Confirmar Salida')

    def test_paquete_salida_excluye_otra_citacion_y_otra_empresa(self):
        otra_citacion = CITACION.objects.create(
            US_NID=self.operador,
            EP_NID=self.empresa,
            PL_NID=self.planificacion,
            SC_NID=self.secuencia,
            CI_FFECHAREGISTRO=timezone.now(),
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=2,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO='GUIA-OTRA-CITACION',
        )
        otro_documento = CITACION_DOCUMENTO.objects.create(
            CI_NID=otra_citacion,
            EP_NID=self.empresa,
            CD_CTIPO=CITACION_DOCUMENTO.TIPO_GUIA,
            CD_CRUTA_ARCHIVO=self.pdf_path,
            CD_CNOMBRE_ARCHIVO='otra_citacion.pdf',
            US_SUBE_NID=self.recepcion,
        )
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='OTRA EMPRESA',
            EP_CRUT='1-9',
            EP_CBASEDATOS='otra',
            EP_CUSUARIOSBD='otra',
            EP_CPORT='5432',
        )
        otro_empresa_documento = CITACION_DOCUMENTO.objects.create(
            CI_NID=self.citacion,
            EP_NID=otra_empresa,
            CD_CTIPO=CITACION_DOCUMENTO.TIPO_GUIA,
            CD_CRUTA_ARCHIVO=self.pdf_path,
            CD_CNOMBRE_ARCHIVO='otra_empresa.pdf',
            US_SUBE_NID=self.recepcion,
        )
        referencias = {
            item['source_ref']
            for item in views.obtener_documentos_salida_terramar(self.citacion)
        }
        self.assertNotIn(f'CITACION_DOCUMENTO:{otro_documento.id}', referencias)
        self.assertNotIn(f'CITACION_DOCUMENTO:{otro_empresa_documento.id}', referencias)

    def test_segunda_secuencia_terramar_comparte_etapa2(self):
        self.secuencia.SE_CCODIGO = 'RECEPCION_TERRAMAR_BODEGA_EXTERNA'
        self.secuencia.save(update_fields=['SE_CCODIGO'])
        self.assertEqual(self.validar_documentacion().status_code, 200)
        self.assertEqual(self.timbrar().status_code, 200)
        self.assertEqual(self.post(self.despacho, 'ajax_operacion_planta_autorizar_salida').status_code, 200)
        confirmed = self.post(self.guardia, 'operacion_planta_guardar_paso', {'paso': 'Confirmar Salida'})
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
