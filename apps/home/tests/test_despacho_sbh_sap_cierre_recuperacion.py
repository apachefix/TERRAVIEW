import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase

from apps.home import views


class DespachoSbhSapCierreTests(SimpleTestCase):
    def setUp(self):
        self.usuario = SimpleNamespace(username='admin', is_superuser=True)

    def _citacion(self, flujo='EST_SBH_CLIENTE', empresa_id=2, tipo='DESPACHO'):
        return SimpleNamespace(
            id=38651,
            EP_NID_id=empresa_id,
            EP_NID=SimpleNamespace(id=empresa_id),
            CI_CTIPO=tipo,
            PL_NID=None,
            SC_NID=SimpleNamespace(SE_CCODIGO=flujo),
            ETAPA_ACTUAL=SimpleNamespace(id=1),
        )

    def test_aislamiento_solo_tres_flujos_despacho_sbh(self):
        for flujo in views.FLUJOS_DESPACHO_SBH_SAP_UPDATE:
            self.assertTrue(views.es_despacho_sbh_operacion(self._citacion(flujo)))
        self.assertFalse(views.es_despacho_sbh_operacion(self._citacion('BODEGA_EXTERNA_CLIENTE')))
        self.assertFalse(views.es_despacho_sbh_operacion(self._citacion('DESPACHO_TERRAMAR', empresa_id=1)))
        self.assertFalse(views.es_despacho_sbh_operacion(self._citacion(tipo='RECEPCION')))

    @patch('apps.home.views.sap_despacho_actualizar_borrador')
    def test_post_pesaje_ejecuta_update_sap_solo_para_despacho_sbh(self, actualizar):
        actualizar.return_value = {'success': True}

        resultado = views._actualizar_sap_despacho_post_pesaje(
            self._citacion(), self.usuario
        )

        self.assertTrue(resultado['success'])
        actualizar.assert_called_once()
        actualizar.reset_mock()
        self.assertIsNone(views._actualizar_sap_despacho_post_pesaje(
            self._citacion('DESPACHO_TERRAMAR', empresa_id=1), self.usuario
        ))
        actualizar.assert_not_called()

    @patch('apps.home.views.guardar_dato_operacion_codigo')
    @patch('apps.home.views.get_sap_despacho_update_status', return_value={'updated': False})
    def test_cierre_bloqueado_si_sap_no_esta_actualizado(self, _estado, guardar_dato):
        ok, mensaje = views.guardar_cierre_carga_despacho(
            self._citacion(),
            {'despacho_cierre_nro_sellos': 'S1', 'despacho_cierre_temperatura': '20'},
            self.usuario,
        )

        self.assertFalse(ok)
        self.assertIn('SAP no pudo actualizar', mensaje)
        guardar_dato.assert_not_called()

    @patch('apps.home.views._documentos_sellos_despacho', return_value=[])
    @patch('apps.home.views.guardar_dato_operacion_codigo')
    @patch('apps.home.views.get_sap_despacho_update_status', return_value={'updated': True})
    def test_cierre_bloqueado_sin_imagen(self, _estado, guardar_dato, _documentos):
        ok, mensaje = views.guardar_cierre_carga_despacho(
            self._citacion(),
            {'despacho_cierre_nro_sellos': 'S1', 'despacho_cierre_temperatura': '20'},
            self.usuario,
        )

        self.assertFalse(ok)
        self.assertIn('al menos una imagen', mensaje)
        guardar_dato.assert_not_called()

    @patch('apps.home.views.CITACION_DOCUMENTO.objects.create')
    @patch('apps.home.views.guardar_archivo_expediente_citacion', return_value=('ruta/uuid.jpg', 'uuid.jpg'))
    def test_subida_inmediata_crea_imagen_en_citacion_documento(
        self, _guardar_archivo, crear_documento
    ):
        archivo = SimpleUploadedFile('SELLO.jpg', b'jpg', content_type='image/jpeg')

        views._guardar_imagenes_sellos_despacho(
            self._citacion(), [archivo], self.usuario
        )

        self.assertEqual(
            crear_documento.call_args.kwargs['CD_CTIPO'],
            views.CITACION_DOCUMENTO.TIPO_IMAGEN_SELLO_DESPACHO,
        )
        self.assertEqual(crear_documento.call_args.kwargs['CD_CNOMBRE_ARCHIVO'], 'SELLO.jpg')

    @patch('apps.home.views.CITACION_DOCUMENTO.objects.create')
    @patch('apps.home.views.guardar_archivo_expediente_citacion')
    def test_guarda_todas_las_imagenes_seleccionadas_simultaneamente(
        self, guardar_archivo, crear_documento
    ):
        guardar_archivo.side_effect = [
            ('ruta/uuid-1.jpg', 'uuid-1.jpg'),
            ('ruta/uuid-2.jpg', 'uuid-2.jpg'),
            ('ruta/uuid-3.png', 'uuid-3.png'),
        ]
        archivos = [
            SimpleUploadedFile('sello1.jpg', b'jpg-1', content_type='image/jpeg'),
            SimpleUploadedFile('sello2.jpg', b'jpg-2', content_type='image/jpeg'),
            SimpleUploadedFile('sello3.png', b'png-3', content_type='image/png'),
        ]

        views._guardar_imagenes_sellos_despacho(
            self._citacion(), archivos, self.usuario
        )

        self.assertEqual(guardar_archivo.call_count, 3)
        self.assertEqual(crear_documento.call_count, 3)
        self.assertEqual(
            [llamada.kwargs['CD_CNOMBRE_ARCHIVO'] for llamada in crear_documento.call_args_list],
            ['sello1.jpg', 'sello2.jpg', 'sello3.png'],
        )
        self.assertTrue(all(
            llamada.kwargs['CD_CTIPO'] == views.CITACION_DOCUMENTO.TIPO_IMAGEN_SELLO_DESPACHO
            for llamada in crear_documento.call_args_list
        ))

    @patch('apps.home.views.CITACION_DOCUMENTO.objects.filter')
    @patch('apps.home.views.CITACION_DOCUMENTO.objects.create')
    @patch('apps.home.views.guardar_archivo_expediente_citacion')
    def test_nuevas_imagenes_no_reemplazan_las_existentes(
        self, guardar_archivo, crear_documento, filtrar_documentos
    ):
        guardar_archivo.side_effect = [
            ('ruta/uuid-3.jpg', 'uuid-3.jpg'),
            ('ruta/uuid-4.png', 'uuid-4.png'),
        ]
        nuevas = [
            SimpleUploadedFile('sello3.jpg', b'jpg-3', content_type='image/jpeg'),
            SimpleUploadedFile('sello4.png', b'png-4', content_type='image/png'),
        ]

        views._guardar_imagenes_sellos_despacho(
            self._citacion(), nuevas, self.usuario
        )

        self.assertEqual(crear_documento.call_count, 2)
        filtrar_documentos.assert_not_called()

    def test_rechaza_cada_imagen_que_supere_diez_mb(self):
        archivo = Mock(
            content_type='image/jpeg',
            size=views.DESPACHO_SELLO_MAX_BYTES + 1,
        )
        archivo.name = 'sello-grande.jpg'

        with self.assertRaisesRegex(ValueError, 'maximo 10 MB'):
            views._validar_imagen_sello_despacho(archivo)

    @patch('apps.home.views._guardar_imagenes_sellos_despacho')
    @patch('apps.home.views._documentos_sellos_despacho', return_value=[{'nombre': 'sello-existente.jpg'}])
    @patch('apps.home.views.guardar_dato_operacion_codigo')
    @patch('apps.home.views.get_sap_despacho_update_status', return_value={'updated': True})
    def test_imagen_existente_permite_cerrar_sin_repetir_la_carga(
        self, _estado, guardar_dato, _documentos, guardar_imagenes
    ):
        guardar_dato.return_value = SimpleNamespace(id=55)

        ok, resultado = views.guardar_cierre_carga_despacho(
            self._citacion(),
            {'despacho_cierre_nro_sellos': 'S1', 'despacho_cierre_temperatura': '20'},
            self.usuario,
        )

        self.assertTrue(ok)
        self.assertEqual(resultado['imagenes_sellos'][0]['nombre'], 'sello-existente.jpg')
        guardar_imagenes.assert_not_called()


class DespachoSbhUploadInmediatoTests(SimpleTestCase):
    def setUp(self):
        self.usuario = SimpleNamespace(username='asistente', is_superuser=False)
        self.citacion = SimpleNamespace(
            id=38651,
            EP_NID_id=2,
            EP_NID=SimpleNamespace(id=2),
            PL_NID=None,
            SC_NID=SimpleNamespace(SE_CCODIGO='EST_SBH_CLIENTE'),
            CI_CTIPO='DESPACHO',
            CI_BHABILITADO=True,
        )

    def _request(self, archivos):
        request = RequestFactory().post('/operacion-planta/38651/guardar-paso/', {
            'accion': 'subir_imagenes_sellos',
            'paso': views.PASO_CIERRE_CARGA,
            '_empresa_id': '2',
            'imagenes_sellos': archivos,
        })
        request.user = self.usuario
        return request

    def test_endpoint_persiste_todos_los_archivos_y_devuelve_ambos_bloques(self):
        archivos = [
            SimpleUploadedFile('lado1.jpg', b'jpg-1', content_type='image/jpeg'),
            SimpleUploadedFile('lado2.jpg', b'jpg-2', content_type='image/jpeg'),
            SimpleUploadedFile('etiqueta.png', b'png-3', content_type='image/png'),
        ]
        imagenes = [
            {'id': 1, 'nombre': 'lado1.jpg', 'fecha': '', 'usuario': 'asistente', 'download_url': '/doc/1/'},
            {'id': 2, 'nombre': 'lado2.jpg', 'fecha': '', 'usuario': 'asistente', 'download_url': '/doc/2/'},
            {'id': 3, 'nombre': 'etiqueta.png', 'fecha': '', 'usuario': 'asistente', 'download_url': '/doc/3/'},
        ]
        documentos = [
            {'nombre_archivo': imagen['nombre'], 'etapa': views.PASO_CIERRE_CARGA, 'download_url': imagen['download_url']}
            for imagen in imagenes
        ]

        with patch('apps.home.views.usuario_es_operacion_planta', return_value=True), \
             patch('apps.home.views.Verificar_empresa', return_value=2), \
             patch('apps.home.views.CITACION.objects') as citaciones, \
             patch('apps.home.views.citacion_habilitada_operacion', return_value=True), \
             patch('apps.home.views.operacion_planta_esta_terminada', return_value=False), \
             patch('apps.home.views.obtener_pasos_operacion_citacion', return_value=('SBH', [(views.PASO_CIERRE_CARGA, ['Asistente_Recepcion'])])), \
             patch('apps.home.views.OPERACION_PLANTA_LOG.objects') as logs, \
             patch('apps.home.views.resolver_estado_operacional_visible', return_value=views.PASO_CIERRE_CARGA), \
             patch('apps.home.views.usuario_puede_paso_operacion', return_value=True), \
             patch('apps.home.views.es_despacho_sbh_operacion', return_value=True), \
             patch('apps.home.views._guardar_imagenes_sellos_despacho') as guardar, \
             patch('apps.home.views._documentos_sellos_despacho', return_value=imagenes), \
             patch('apps.home.views.obtener_datos_operacion_citacion', return_value=({}, documentos)), \
             patch('apps.home.views.transaction.atomic', return_value=nullcontext()):
            citaciones.select_related.return_value.get.return_value = self.citacion
            logs.filter.return_value.values_list.return_value = []

            response = views.OPERACION_PLANTA_GUARDAR_PASO(
                self._request(archivos), self.citacion.id
            )

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(len(payload['imagenes']), 3)
        self.assertEqual(len(payload['documentos_operacion']), 3)
        archivos_guardados = guardar.call_args.args[1]
        self.assertEqual([archivo.name for archivo in archivos_guardados], ['lado1.jpg', 'lado2.jpg', 'etiqueta.png'])

    @patch('apps.home.views._documentos_sellos_despacho', return_value=[{
        'id': 4,
        'nombre': 'sello4.png',
        'fecha': '11/08/2026 10:00',
        'usuario': 'asistente',
        'download_url': '/doc/4/',
        'etapa': views.PASO_CIERRE_CARGA,
    }])
    @patch('apps.home.views.DATO_OPERACION.objects')
    @patch('apps.home.views._dato_ticket_pesaje', return_value=None)
    @patch('apps.home.views.es_despacho_sbh_operacion', return_value=True)
    def test_recarga_incluye_imagen_en_documentos_adjuntos(
        self, _es_sbh, _ticket, datos_operacion, _imagenes
    ):
        datos_operacion.filter.return_value.select_related.return_value.order_by.return_value = []

        _, documentos = views.obtener_datos_operacion_citacion(self.citacion)

        self.assertEqual(documentos[0]['nombre_archivo'], 'sello4.png')
        self.assertEqual(documentos[0]['etapa'], views.PASO_CIERRE_CARGA)
        self.assertEqual(documentos[0]['download_url'], '/doc/4/')


class DespachoSbhReaperturaTests(SimpleTestCase):
    @patch('apps.home.views.registrar_log_camion_no_planificado')
    @patch('apps.home.views.transaction.atomic', return_value=nullcontext())
    @patch('apps.home.views._recargar_citacion_bloqueada_operacion')
    @patch('apps.home.views.es_despacho_sbh_operacion', return_value=True)
    @patch('apps.home.views._obtener_citacion_operacion_planta_ajax')
    @patch('apps.home.views.usuario_puede_reabrir_cierre_carga', return_value=True)
    @patch('apps.home.views.OPERACION_PLANTA_LOG.objects')
    def test_reapertura_conserva_registro_y_lo_marca_reabierto(
        self, objetos, _permiso, obtener_citacion, _es_sbh,
        recargar, _atomic, registrar_auditoria
    ):
        citacion = SimpleNamespace(id=38651, EP_NID=SimpleNamespace(id=2))
        cierre = SimpleNamespace(OPL_COBSERVACION='Sellos: S1', save=Mock())
        objetos.filter.return_value.exists.return_value = False
        objetos.select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = cierre
        obtener_citacion.return_value = (citacion, None)
        recargar.return_value = citacion
        request = RequestFactory().post('/reabrir/', {'motivo': 'Correccion tecnica'})
        request.user = SimpleNamespace(username='admin', is_superuser=True)

        response = views.ajax_operacion_planta_reabrir_cierre_carga_despacho_sbh(
            request, 38651
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['success'])
        self.assertEqual(cierre.OPL_CESTADO, 'REABIERTO')
        cierre.save.assert_called_once_with(update_fields=['OPL_CESTADO', 'OPL_COBSERVACION'])
        registrar_auditoria.assert_called_once()

