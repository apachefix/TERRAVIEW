import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home import recepcion_servicio as rs
from apps.home import views
from apps.home.models import (
    CAMION_PATIO,
    CITACION,
    CITACION_DOCUMENTO,
    EMPRESA,
    NOTIFICACION,
    OPERACION_PLANTA_LOG,
    PERFIL,
    PERFIL_USUARIO,
    RECEPCION_SERVICIO_DETALLE,
    SECUENCIA,
    SOCIONEGOCIO,
    SYSLOGGER,
    USERS_EMPRESA,
)


class RecepcionServicioGeneralTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('rs_admin', 'rs_admin@example.com', 'test')
        cls.maesc = User.objects.create_user('MAESC', password='test')
        cls.jnovoa = User.objects.create_user('JNOVOA', password='test')
        cls.asistente_recepcion = User.objects.create_user('rs_asistente_recepcion', password='test')
        cls.guardia = User.objects.create_user('rs_guardia_porteria', password='test')
        cls.asistente_cd = User.objects.create_user('rs_asistente_cd', password='test')

        cls.empresa_1 = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR', EP_CRUT='11-1',
            EP_CBASEDATOS='TEST1', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )
        cls.empresa_2 = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='22-2',
            EP_CBASEDATOS='TEST2', EP_CUSUARIOSBD='test', EP_CPORT='0',
        )

        perfiles = {}
        for codigo, nombre in (
            ('PLAN', 'PLAN'),
            ('ASISTENTE_RECEPCION', 'ASISTENTE RECEPCION'),
            ('GUARDIA_PORTERIA', 'GUARDIA PORTERIA'),
            ('ASISTENTE_CD', 'ASISTENTE CD'),
        ):
            perfiles[codigo] = PERFIL.objects.create(
                US_NID=cls.admin, PR_CCODIGO=codigo, PR_CNOMBRE=nombre,
                PR_BHABILITADO=True,
            )
        for usuario, perfil in (
            (cls.maesc, perfiles['PLAN']),
            (cls.jnovoa, perfiles['PLAN']),
            (cls.asistente_recepcion, perfiles['ASISTENTE_RECEPCION']),
            (cls.guardia, perfiles['GUARDIA_PORTERIA']),
            (cls.asistente_cd, perfiles['ASISTENTE_CD']),
        ):
            PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil, PE_BHABILITADO=True)

        for usuario, empresa in (
            (cls.maesc, cls.empresa_2),
            (cls.jnovoa, cls.empresa_1),
            (cls.asistente_recepcion, cls.empresa_1),
            (cls.asistente_recepcion, cls.empresa_2),
            (cls.guardia, cls.empresa_1),
            (cls.guardia, cls.empresa_2),
            (cls.asistente_cd, cls.empresa_1),
        ):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=empresa)

        cls.proveedor_1 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa_1, SN_CCODIGO_SAP='SERV-1',
            SN_CRAZONSOCIAL='Proveedor Servicio Terramar', SN_CRUT='11111111-1',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.proveedor_2 = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa_2, SN_CCODIGO_SAP='SERV-2',
            SN_CRAZONSOCIAL='Proveedor Servicio SBH', SN_CRUT='22222222-2',
            SN_CTIPO='S', SN_BHABILITADO=True,
        )
        cls.proveedor_inactivo = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa_1, SN_CCODIGO_SAP='SERV-X',
            SN_CRAZONSOCIAL='Proveedor Inactivo', SN_CRUT='33333333-3',
            SN_CTIPO='S', SN_BHABILITADO=False,
        )

    def planificar(self, usuario, empresa, proveedor, patente='RSVC10', tipo='GAS', token=None):
        self.client.force_login(usuario)
        fecha = timezone.localdate() + timedelta(days=1)
        return self.client.post(reverse('recepcion_servicio_registro'), {
            '_empresa_id': empresa.id,
            'section': 'planificacion',
            'idempotencia': str(token or uuid.uuid4()),
            'tipo_servicio': tipo,
            'proveedor_id': proveedor.id,
            'patente': patente,
            'nombre_chofer': 'Chofer Servicio',
            'fecha': fecha.isoformat(),
            'hora': '10:30',
            'observacion': 'Visita de servicio',
        })

    def crear_detalle_1(self, patente='RSVC10', tipo='GAS'):
        response = self.planificar(
            self.jnovoa, self.empresa_1, self.proveedor_1,
            patente=patente, tipo=tipo,
        )
        self.assertEqual(response.status_code, 302, response.content)
        return RECEPCION_SERVICIO_DETALLE.objects.latest('id')

    def confirmar_ingreso(self, detalle, usuario=None):
        self.client.force_login(usuario or self.guardia)
        return self.client.post(
            reverse('recepcion_servicio_confirmar_ingreso', args=[detalle.CI_NID_id]),
            {'_empresa_id': detalle.EP_NID_id, 'patente': detalle.RSD_CPATENTE},
        )

    def test_acceso_asistente_y_planificadores_por_empresa(self):
        casos_permitidos = (
            (self.asistente_recepcion, self.empresa_1),
            (self.asistente_recepcion, self.empresa_2),
            (self.maesc, self.empresa_2),
            (self.jnovoa, self.empresa_1),
        )
        for usuario, empresa in casos_permitidos:
            with self.subTest(usuario=usuario.username, empresa=empresa.id):
                self.client.force_login(usuario)
                response = self.client.get(reverse('recepcion_servicio_registro'), {
                    '_empresa_id': empresa.id, 'section': 'planificacion',
                })
                self.assertEqual(response.status_code, 200, response.content)
                self.assertContains(response, 'id="btn-nueva-planificacion-servicio"', html=False)
                self.assertContains(response, 'id="modalNuevaPlanificacionServicio"', html=False)
                for campo in (
                    'tipo_servicio', 'proveedor_id', 'patente', 'nombre_chofer',
                    'fecha', 'hora', 'observacion',
                ):
                    self.assertContains(response, f'name="{campo}"', html=False)
                for tipo in ('GAS', 'PALLET', 'MAXIS', 'PETROLEO', 'NITROGENO'):
                    self.assertContains(response, f'value="{tipo}"', html=False)
        for usuario, empresa in (
            (self.jnovoa, self.empresa_2),
            (self.maesc, self.empresa_1),
            (self.asistente_cd, self.empresa_1),
        ):
            with self.subTest(usuario=usuario.username, empresa=empresa.id):
                self.client.force_login(usuario)
                response = self.client.get(reverse('recepcion_servicio_registro'), {
                    '_empresa_id': empresa.id, 'section': 'planificacion',
                })
                self.assertEqual(response.status_code, 403)

    def test_alias_seccion_y_proveedores_aislados(self):
        self.client.force_login(self.jnovoa)
        response = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 1, 'seccion': 'planificacion',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.proveedor_1.SN_CRAZONSOCIAL)
        self.assertNotContains(response, self.proveedor_2.SN_CRAZONSOCIAL)
        self.assertNotContains(response, self.proveedor_inactivo.SN_CRAZONSOCIAL)

    def test_asistente_recepcion_puede_crear_en_empresa_asignada(self):
        response = self.planificar(
            self.asistente_recepcion, self.empresa_2, self.proveedor_2,
            patente='as-r 200', tipo='NITROGENO',
        )
        self.assertEqual(response.status_code, 302, response.content)
        detalle = RECEPCION_SERVICIO_DETALLE.objects.get()
        self.assertEqual(detalle.EP_NID_id, self.empresa_2.id)
        self.assertEqual(detalle.RSD_CPATENTE, 'ASR200')
        self.assertEqual(detalle.RSD_CTIPO_SERVICIO, 'NITROGENO')

    def test_campos_obligatorios_se_validan_en_backend(self):
        fecha = (timezone.localdate() + timedelta(days=1)).isoformat()
        base = {
            '_empresa_id': self.empresa_1.id,
            'section': 'planificacion',
            'idempotencia': str(uuid.uuid4()),
            'tipo_servicio': 'GAS',
            'proveedor_id': self.proveedor_1.id,
            'patente': 'REQ100',
            'nombre_chofer': 'Chofer Requerido',
            'fecha': fecha,
            'hora': '10:30',
            'observacion': 'Validación',
        }
        self.client.force_login(self.jnovoa)
        for campo in ('tipo_servicio', 'proveedor_id', 'patente', 'nombre_chofer', 'fecha', 'hora'):
            with self.subTest(campo=campo):
                datos = base.copy()
                datos['idempotencia'] = str(uuid.uuid4())
                datos[campo] = ''
                response = self.client.post(reverse('recepcion_servicio_registro'), datos)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertContains(response, 'modalNuevaPlanificacionServicio', status_code=400)
                self.assertContains(
                    response,
                    "jQuery('#modalNuevaPlanificacionServicio').modal('show')",
                    status_code=400,
                )
        self.assertEqual(RECEPCION_SERVICIO_DETALLE.objects.count(), 0)
        self.assertEqual(CITACION.objects.count(), 0)

    def test_crea_gas_repetible_idempotente_y_sin_camion_patio(self):
        token = uuid.uuid4()
        primera = self.planificar(
            self.jnovoa, self.empresa_1, self.proveedor_1,
            patente='ga-s 100', token=token,
        )
        repetida = self.planificar(
            self.jnovoa, self.empresa_1, self.proveedor_1,
            patente='GAS100', token=token,
        )
        segunda_visita = self.planificar(
            self.jnovoa, self.empresa_1, self.proveedor_1,
            patente='GAS100', token=uuid.uuid4(),
        )
        self.assertEqual((primera.status_code, repetida.status_code, segunda_visita.status_code), (302, 302, 302))
        detalles = RECEPCION_SERVICIO_DETALLE.objects.filter(RSD_CPATENTE='GAS100')
        self.assertEqual(detalles.count(), 2)
        self.assertEqual(set(detalles.values_list('RSD_CTIPO_SERVICIO', flat=True)), {'GAS'})
        self.assertEqual(CAMION_PATIO.objects.filter(CI_NID_id__in=detalles.values('CI_NID_id')).count(), 0)
        self.assertEqual(CITACION.objects.filter(
            pk__in=detalles.values('CI_NID_id'),
            EP_NID=self.empresa_1,
            PL_NID__isnull=False,
            SC_NID__SE_CCODIGO=rs.SECUENCIA_CODIGO,
        ).count(), 2)
        self.assertEqual(SECUENCIA.objects.filter(EP_NID=1, SE_CCODIGO=rs.SECUENCIA_CODIGO).count(), 1)
        self.assertGreaterEqual(NOTIFICACION.objects.filter(EP_NID=1, USER_RECEIVER_ID=self.guardia).count(), 2)
        self.client.force_login(self.jnovoa)
        listado = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 1, 'section': 'planificacion', 'estado': 'TODOS',
        })
        self.assertContains(listado, 'GAS100')

    def test_empresa_y_proveedor_ajenos_bloqueados_backend(self):
        bloqueado = self.planificar(self.jnovoa, self.empresa_2, self.proveedor_2)
        self.assertEqual(bloqueado.status_code, 403)
        proveedor_ajeno = self.planificar(self.jnovoa, self.empresa_1, self.proveedor_2)
        self.assertEqual(proveedor_ajeno.status_code, 400)
        self.assertEqual(RECEPCION_SERVICIO_DETALLE.objects.count(), 0)

    def test_estado_camion_encuentra_solo_proceso_vivo(self):
        detalle = self.crear_detalle_1('LIVE10')
        self.client.force_login(self.guardia)
        response = self.client.get(reverse('estado_camion_ajax'), {
            '_empresa_id': 1, 'patente': 'live-10',
        })
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload['tipo_resultado'], rs.RESULTADO_PLANIFICADA)
        self.assertEqual(payload['data']['candidatos'][0]['citacion_id'], detalle.CI_NID_id)
        detalle.CI_NID.CI_CESTADO = views.CIT_TERMINADO
        detalle.CI_NID.CI_FFECHATERMINO = timezone.now()
        detalle.CI_NID.save(update_fields=['CI_CESTADO', 'CI_FFECHATERMINO'])
        terminado = self.client.get(reverse('estado_camion_ajax'), {
            '_empresa_id': 1, 'patente': 'LIVE10',
        })
        self.assertNotEqual(terminado.json().get('tipo_resultado'), rs.RESULTADO_PLANIFICADA)

    def test_guardia_confirma_ingreso_una_vez_y_habilita_operacion(self):
        detalle = self.crear_detalle_1('ENTRY10')
        primera = self.confirmar_ingreso(detalle)
        segunda = self.confirmar_ingreso(detalle)
        self.assertEqual((primera.status_code, segunda.status_code), (200, 200))
        self.assertTrue(segunda.json()['idempotent'])
        self.assertEqual(CAMION_PATIO.objects.filter(CI_NID_id=detalle.CI_NID_id).count(), 1)
        self.assertEqual(SYSLOGGER.objects.filter(
            LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(detalle.CI_NID_id),
        ).count(), 1)
        detalle.CI_NID.refresh_from_db()
        self.assertTrue(views.citacion_habilitada_operacion(detalle.CI_NID))
        self.assertEqual(NOTIFICACION.objects.filter(
            EP_NID=1, USER_RECEIVER_ID=self.asistente_cd,
            NOT_CCONTENIDO__contains=f'#{detalle.CI_NID_id}',
        ).count(), 1)

    def test_empresa_2_sin_asistente_cd_no_inventa_destinatario(self):
        detalle = self.planificar(
            self.maesc, self.empresa_2, self.proveedor_2, patente='SBH200',
        )
        self.assertEqual(detalle.status_code, 302)
        registro = RECEPCION_SERVICIO_DETALLE.objects.get(RSD_CPATENTE='SBH200')
        response = self.confirmar_ingreso(registro)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['notificados_asistente_cd'], 0)

    def test_operacion_tiene_dos_pasos_y_ui_sin_sap_calidad_pesaje(self):
        detalle = self.crear_detalle_1('FLOW10')
        self.assertEqual(self.confirmar_ingreso(detalle).status_code, 200)
        citacion = CITACION.objects.select_related('SC_NID').get(pk=detalle.CI_NID_id)
        nombre, pasos = views.obtener_pasos_operacion_citacion(citacion)
        self.assertEqual(nombre, 'RECEPCIÓN SERVICIO')
        self.assertEqual(list(pasos), list(rs.PASOS_OPERACION))
        self.client.force_login(self.asistente_cd)
        response = self.client.get(reverse('operacion_planta_citacion', args=[citacion.id]), {'_empresa_id': 1})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, 'Recepción Conforme')
        self.assertContains(response, 'Confirmar Salida')
        self.assertNotContains(response, 'operacion-sap-recepcion-preview-card')
        self.assertNotContains(response, 'Análisis y Calidad')
        self.assertNotContains(response, 'Finalizar Pesaje Entrada')
        self.assertNotContains(response, 'Finalizar Pesaje Salida')

    def test_recepcion_conforme_documentos_acumulativos_e_idempotencia(self):
        detalle = self.crear_detalle_1('DOCS10')
        self.assertEqual(self.confirmar_ingreso(detalle).status_code, 200)
        self.client.force_login(self.asistente_cd)
        with tempfile.TemporaryDirectory() as folder:
            original = views.EXPEDIENTE_CITACION_ROOT
            views.EXPEDIENTE_CITACION_ROOT = folder
            try:
                response = self.client.post(
                    reverse('operacion_planta_recepcion_servicio_conforme', args=[detalle.CI_NID_id]),
                    {
                        '_empresa_id': 1,
                        'recepcion_conforme': 'SI',
                        'observacion': 'Servicio recibido conforme.',
                        'documentos': [
                            SimpleUploadedFile('uno.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
                            SimpleUploadedFile('dos.png', b'png-test', content_type='image/png'),
                        ],
                    },
                )
                self.assertEqual(response.status_code, 302, response.content)
                documentos = CITACION_DOCUMENTO.objects.filter(
                    CI_NID_id=detalle.CI_NID_id,
                    CD_CTIPO=CITACION_DOCUMENTO.TIPO_RECEPCION_SERVICIO,
                )
                self.assertEqual(documentos.count(), 2)
                self.assertEqual(documentos.filter(CD_BACTIVO=True).count(), 2)
                repetida = self.client.post(
                    reverse('operacion_planta_recepcion_servicio_conforme', args=[detalle.CI_NID_id]),
                    {
                        '_empresa_id': 1,
                        'recepcion_conforme': 'SI',
                        'documentos': SimpleUploadedFile('tres.jpg', b'jpg-test', content_type='image/jpeg'),
                    },
                )
                self.assertEqual(repetida.status_code, 302)
                self.assertEqual(documentos.count(), 2)
                self.assertTrue(all(Path(doc.CD_CRUTA_ARCHIVO).is_file() for doc in documentos))
            finally:
                views.EXPEDIENTE_CITACION_ROOT = original
        citacion = CITACION.objects.get(pk=detalle.CI_NID_id)
        self.assertTrue(citacion.CI_BCONFORME)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion, OPL_CPASO=rs.PASO_RECEPCION_CONFORME,
        ).count(), 1)
        self.assertEqual(NOTIFICACION.objects.filter(
            EP_NID=1, USER_RECEIVER_ID=self.guardia,
            NOT_CCONTENIDO__contains=f'#{citacion.id}',
        ).count(), 2)

    def test_confirmar_salida_solo_guardia_cierra_citacion_y_camion(self):
        detalle = self.crear_detalle_1('EXIT10')
        self.assertEqual(self.confirmar_ingreso(detalle).status_code, 200)
        self.client.force_login(self.asistente_cd)
        conforme = self.client.post(
            reverse('operacion_planta_recepcion_servicio_conforme', args=[detalle.CI_NID_id]),
            {'_empresa_id': 1, 'recepcion_conforme': 'NO', 'observacion': 'Recepción observada.'},
        )
        self.assertEqual(conforme.status_code, 302)
        indebido = self.client.post(
            reverse('operacion_planta_guardar_paso', args=[detalle.CI_NID_id]),
            {'_empresa_id': 1, 'paso': rs.PASO_CONFIRMAR_SALIDA},
        )
        self.assertEqual(indebido.status_code, 403, indebido.content)
        self.client.force_login(self.guardia)
        salida = self.client.post(
            reverse('operacion_planta_guardar_paso', args=[detalle.CI_NID_id]),
            {'_empresa_id': 1, 'paso': rs.PASO_CONFIRMAR_SALIDA, 'observacion': 'Salida física confirmada.'},
        )
        self.assertEqual(salida.status_code, 200, salida.content)
        citacion = CITACION.objects.get(pk=detalle.CI_NID_id)
        camion = CAMION_PATIO.objects.get(CI_NID=citacion)
        self.assertEqual(citacion.CI_CESTADO, views.CIT_TERMINADO)
        self.assertIsNotNone(citacion.CI_FFECHATERMINO)
        self.assertEqual(camion.CPA_CESTADO, CAMION_PATIO.ESTADO_SALIDA_CONFIRMADA)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.filter(
            CI_NID=citacion, OPL_CPASO=rs.PASO_CONFIRMAR_SALIDA,
        ).count(), 1)

    def test_aislamiento_y_regresion_codigos_existentes(self):
        uno = self.crear_detalle_1('ISO10')
        response = self.planificar(self.maesc, self.empresa_2, self.proveedor_2, patente='ISO20')
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.jnovoa)
        listado = self.client.get(reverse('recepcion_servicio_registro'), {
            '_empresa_id': 1, 'section': 'planificacion', 'estado': 'TODOS',
        })
        self.assertContains(listado, 'ISO10')
        self.assertNotContains(listado, 'ISO20')
        for codigo in (
            views.SECUENCIA_RECEPCION_PROSESA_PISO_1,
            views.SECUENCIA_RECEPCION_NEW_JERSEY_P3,
        ):
            secuencia = SECUENCIA.objects.create(
                US_NID=self.admin, EP_NID=self.empresa_2, SE_CTIPO='RECEPCION',
                SE_CCODIGO=codigo, SE_CNOMBRE=codigo, SE_BHABILITADO=True,
            )
            citacion = CITACION(EP_NID=self.empresa_2, SC_NID=secuencia, CI_CTIPO='RECEPCION')
            self.assertFalse(rs.es_recepcion_servicio(citacion))
        self.assertEqual(uno.EP_NID_id, 1)
