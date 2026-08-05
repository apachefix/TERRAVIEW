import json

from django.contrib.auth import get_user_model
from django.db import DataError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.home import views
from apps.home.models import (
    CAMION_PATIO, CAMPO, CITACION, COMUNA, CONDUCTOR, DATO_OPERACION,
    DETALLE_SECUENCIA, EMPRESA, ETAPA, ETAPA_LOG, ITEM, OPERACION_PLANTA_LOG, PLANIFICACION, PROVINCIA, REGION, RUTA, SECUENCIA,
    SOCIONEGOCIO, SYSLOGGER, TARIFA_GLOBAL, USERS_EMPRESA, USERS_EXTENSION,
)


class CrearPlanificacionTerramarRutaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='planificador_terramar_ruta', password='test-pass'
        )
        cls.empresa = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR CHILE', EP_CRUT='1-9',
            EP_CBASEDATOS='terramar_test', EP_CUSUARIOSBD='test', EP_CPORT='5432'
        )
        USERS_EXTENSION.objects.create(
            US_NID=cls.usuario, UX_IS_PLANIFICADOR=True, UX_IS_TERRAMAR=True
        )
        USERS_EMPRESA.objects.create(US_NID=cls.usuario, EP_NID=cls.empresa)

        cls.region = REGION.objects.create(RG_CNOMBRE='Biobio', RG_CCODIGO='08')
        cls.provincia = PROVINCIA.objects.create(
            RG_NID=cls.region, PV_CNOMBRE='Concepcion', PV_CCODIGO='081'
        )
        cls.comuna_origen = COMUNA.objects.create(
            PV_NID=cls.provincia, COM_CNOMBRE='Coronel', COM_CCODIGO='08101'
        )
        cls.comuna_destino = COMUNA.objects.create(
            PV_NID=cls.provincia, COM_CNOMBRE='Chillan', COM_CCODIGO='16101'
        )
        cls.ruta = RUTA.objects.create(
            EP_NID=cls.empresa, RG_NID_INICIO=cls.region,
            PV_NID_INICIO=cls.provincia, COM_NID_INICIO=cls.comuna_origen,
            RG_NID_TERMINO=cls.region, PV_NID_TERMINO=cls.provincia,
            COM_NID_TERMINO=cls.comuna_destino,
            RUT_NTIEMPOMAXIMOENTREGA=1, RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE='Coronel -> Chillan', RUT_CCODIGO='R-TEST',
            RUT_BHABILITADO=True
        )
        cls.transportista = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa, SN_CCODIGO_SAP='TR-TEST',
            SN_CRAZONSOCIAL='Transportes Test', SN_CRUT='77-7',
            SN_CTIPO='S', SN_BHABILITADO=True
        )
        cls.conductor = CONDUCTOR.objects.create(
            EP_NID=cls.empresa, SN_NID=cls.transportista, US_NID=cls.usuario,
            CON_CNOMBRE='Juan', CON_CAPELLIDO='Conductor', CON_CRUT='11-1',
            CON_CTELEFONO='912345678', CON_CCODIGO_PAIS_TELEFONO='+56',
            CON_BHABILITADO=True
        )
        cls.cliente = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa, SN_CCODIGO_SAP='CLI-TEST',
            SN_CRAZONSOCIAL='Cliente Test', SN_CRUT='66-6',
            SN_CTIPO='C', SN_BHABILITADO=True
        )
        cls.proveedor = SOCIONEGOCIO.objects.create(
            EP_NID=cls.empresa, SN_CCODIGO_SAP='PROV-TEST',
            SN_CRAZONSOCIAL='Proveedor Test', SN_CRUT='55-5',
            SN_CTIPO='S', SN_BHABILITADO=True
        )
        cls.item = ITEM.objects.create(
            EP_NID=cls.empresa, IT_CCODIGO='500000', IT_CNOMBRE='Harina test'
        )
        cls.secuencia = SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SE_CTIPO='RECEPCION',
            SE_CCODIGO='RECEPCION_TERRAMAR', SE_CNOMBRE='Recepcion Terramar',
            SE_BHABILITADO=True
        )
        cls.etapa_planificacion = ETAPA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='REC_TER_PLANIFICACION', ET_CNOMBRE='Planificacion',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True
        )
        DETALLE_SECUENCIA.objects.create(
            US_NID=cls.usuario, EP_NID=cls.empresa, SC_NID=cls.secuencia,
            ET_NID=cls.etapa_planificacion, SE_NPASO=1, SE_BHABILITADO=True
        )

        cls.tarifa = TARIFA_GLOBAL.objects.create(
            EP_NID=cls.empresa, RUT_NID=cls.ruta, US_NID=cls.usuario,
            MODIFICADO_POR=cls.usuario, SN_NID=cls.transportista,
            TAR_NVALOR=320213, TAR_NVALORPREVIO=320000,
            TAR_CNOMBRETARIFA='Tarifa test', TAR_CTIPOTARIFA='FLETE',
            TAR_CDIVISA='CLP', TAR_BHABILITADO=True
        )

    def payload(self):
        return {
            'citaciones_json': json.dumps([{
                'fecha_llegada': '2026-08-10', 'hora_citacion': '08:00',
                'tipo_operacion': 'RECEPCION', 'recepcion_terramar': True,
                'item_id': self.item.id, 'insumo': self.item.IT_CNOMBRE,
                'bodega': 'Bodega test', 'numero_guia': 'GUIA-TEST',
                'secuencia_id': self.secuencia.id, 'transporte_a_cargo': 'Terramar',
                'empresa_transporte_id': self.transportista.id,
                'conductor_id': self.conductor.id, 'patente': 'TEST11',
                'telefono_codigo_pais': '+56', 'telefono_conductor': '912345678',
                'cliente': self.cliente.SN_CCODIGO_SAP,
                'cliente_codigo': self.cliente.SN_CCODIGO_SAP,
                'proveedor': self.proveedor.SN_CCODIGO_SAP,
                'proveedor_codigo': self.proveedor.SN_CCODIGO_SAP,
                'proveedor_sap': self.proveedor.SN_CRAZONSOCIAL,
                'ruta_id': self.ruta.id, 'tarifa_id': self.tarifa.id,
            }]),
            'es_sobrecupo': 'No', 'cantidad_sobrecupo': '0',
        }

    def autenticar(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def crear_dato_operacion(self, citacion, *args, **kwargs):
        etapa = ETAPA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='TEST_ETAPA', ET_CNOMBRE='Etapa test',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True
        )
        campo = CAMPO.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, CA_CTIPO='TEXTO',
            CA_CCODIGO='TEST_DATO', CA_CETIQUETA='Dato test',
            CA_BHABILITADO=True
        )
        return DATO_OPERACION.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SC_NID=citacion.SC_NID,
            ET_NID=etapa, CAMP_NID=campo, CI_NID=citacion,
            DO_FFECHAREGISTRO=timezone.now(), DO_CVALOR='Proveedor Test'
        )

    def test_crea_planificacion_citacion_ruta_tarifa_dato_y_auditoria(self):
        self.autenticar()
        with patch.object(views, 'guardar_detalle_operacional_citacion'),              patch.object(views, 'guardar_detalle_despacho_citacion'),              patch.object(views, 'guardar_detalle_recepcion_terramar_citacion'),              patch.object(views, 'guardar_ruta_transportista_revision'),              patch.object(views, 'guardar_datos_planificacion_operacional',
                           side_effect=self.crear_dato_operacion):
            response = self.client.post(
                reverse('crear_planificacion_citacion'), self.payload()
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        planificacion = PLANIFICACION.objects.get(
            pk=response.json()['planificacion_id']
        )
        citacion = CITACION.objects.get(pk=response.json()['citaciones'][0])
        self.assertEqual(citacion.PL_NID_id, planificacion.id)
        self.assertEqual(citacion.RUT_NID_id, self.ruta.id)
        self.assertEqual(citacion.TAR_NID_id, self.tarifa.id)
        self.assertEqual(citacion.CI_NVALORTARIFA, self.tarifa.TAR_NVALOR)
        self.assertTrue(DATO_OPERACION.objects.filter(CI_NID=citacion).exists())
        self.assertTrue(SYSLOGGER.objects.filter(
            EP_NID=self.empresa,
            LOG_COPERACION=views.SYSLOGGER_OP_ASIGNA_RUTA_PLANIF,
            LOG_CADD1=str(citacion.id),
        ).exists())
        self.assertFalse(
            SYSLOGGER.objects.filter(
                LOG_COPERACION__regex=r'^.{25,}$'
            ).exists()
        )

    def test_error_de_auditoria_revierte_planificacion_y_citacion(self):
        self.autenticar()
        with patch.object(views.SYSLOGGER.objects, 'create',
                          side_effect=DataError('audit failure')),              patch.object(views, 'guardar_detalle_operacional_citacion'),              patch.object(views, 'guardar_detalle_despacho_citacion'),              patch.object(views, 'guardar_detalle_recepcion_terramar_citacion'),              patch.object(views, 'guardar_ruta_transportista_revision'),              patch.object(views, 'guardar_datos_planificacion_operacional',
                           side_effect=self.crear_dato_operacion):
            self.client.raise_request_exception = False
            response = self.client.post(
                reverse('crear_planificacion_citacion'), self.payload()
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        self.assertFalse(PLANIFICACION.objects.exists())
        self.assertFalse(CITACION.objects.exists())
        self.assertFalse(DATO_OPERACION.objects.exists())
    def crear_citacion_para_edicion(self):
        self.autenticar()
        with patch.object(views, 'guardar_detalle_operacional_citacion'), \
             patch.object(views, 'guardar_detalle_despacho_citacion'), \
             patch.object(views, 'guardar_detalle_recepcion_terramar_citacion'), \
             patch.object(views, 'guardar_ruta_transportista_revision'), \
             patch.object(
                 views, 'guardar_datos_planificacion_operacional',
                 side_effect=self.crear_dato_operacion
             ):
            response = self.client.post(
                reverse('crear_planificacion_citacion'), self.payload()
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'], response.content)
        return CITACION.objects.get(pk=response.json()['citaciones'][0])

    def agregar_dato(self, citacion, codigo, valor):
        campo = CAMPO.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, CA_CTIPO='TEXTO',
            CA_CCODIGO=codigo, CA_CETIQUETA=codigo, CA_BHABILITADO=True
        )
        return DATO_OPERACION.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, SC_NID=citacion.SC_NID,
            ET_NID=self.etapa_planificacion, CAMP_NID=campo, CI_NID=citacion,
            DO_FFECHAREGISTRO=timezone.now(), DO_CVALOR=str(valor)
        )

    def test_metadata_ruta_y_auditoria_asignacion_no_bloquean_edicion(self):
        citacion = self.crear_citacion_para_edicion()
        self.agregar_dato(citacion, 'AR_RUTA_ID', self.ruta.id)
        self.agregar_dato(citacion, 'AR_TARIFA_ID', self.tarifa.id)

        editable, motivo, evidencia = views.citacion_recepcion_terramar_es_editable(citacion)

        self.assertTrue(editable, (motivo, evidencia))
        response = self.client.get(
            reverse('editar_citacion_recepcion_terramar', args=[citacion.id])
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['detalle']['ruta_id'], str(self.ruta.id))
        self.assertEqual(response.json()['detalle']['tarifa_id'], str(self.tarifa.id))

    def test_citacion_inicial_sin_ruta_tambien_es_editable(self):
        citacion = self.crear_citacion_para_edicion()
        CITACION.objects.filter(pk=citacion.pk).update(
            RUT_NID=None, TAR_NID=None, CI_NVALORTARIFA=None
        )
        citacion.refresh_from_db()

        editable, motivo, evidencia = views.citacion_recepcion_terramar_es_editable(citacion)

        self.assertTrue(editable, (motivo, evidencia))
        response = self.client.get(
            reverse('editar_citacion_recepcion_terramar', args=[citacion.id])
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['detalle']['ruta_id'], '')
        self.assertEqual(response.json()['detalle']['tarifa_id'], '')

    def test_dato_de_ejecucion_operacional_bloquea_edicion(self):
        citacion = self.crear_citacion_para_edicion()
        self.agregar_dato(citacion, 'OP_TICKET_PESAJE_ENT', 'ticket.pdf')

        editable, motivo, evidencia = views.citacion_recepcion_terramar_es_editable(citacion)

        self.assertFalse(editable)
        self.assertEqual(evidencia['tipo'], 'dato_operacion')
        response = self.client.get(
            reverse('editar_citacion_recepcion_terramar', args=[citacion.id])
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('ejecucion operacional', response.json()['error'])

    def test_camion_en_patio_bloquea_edicion(self):
        citacion = self.crear_citacion_para_edicion()
        CAMION_PATIO.objects.create(
            EP_NID=self.empresa, CI_NID=citacion, CPA_CPATENTE='TEST11',
            CPA_CNOMBRE_CONDUCTOR='Juan Conductor', CPA_CTIPO_DOCUMENTO='GD',
            US_GUARDIA_ID=self.usuario
        )

        editable, motivo, evidencia = views.citacion_recepcion_terramar_es_editable(citacion)

        self.assertFalse(editable)
        self.assertEqual(evidencia['tipo'], 'camion_patio')

    def test_resumen_terramar_muestra_nombre_ruta_sin_tarifa(self):
        citacion = self.crear_citacion_para_edicion()

        response = self.client.get(
            reverse('pla_citacion_resumen', args=[citacion.id])
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        ruta = next(
            item for item in data['datos_operacionales']
            if item['label'] == 'Ruta del transportista'
        )
        self.assertEqual(ruta['value'], self.ruta.RUT_CNOMBRE)
        self.assertEqual(data['ruta_transportista'], {
            'id': self.ruta.id, 'nombre': self.ruta.RUT_CNOMBRE
        })
        visible = json.dumps(data['datos_operacionales'], ensure_ascii=False)
        self.assertNotIn('CLP', visible)
        self.assertNotIn(str(self.tarifa.TAR_NVALOR), visible)

    def test_resumen_terramar_sin_ruta_usa_fallback(self):
        citacion = self.crear_citacion_para_edicion()
        CITACION.objects.filter(pk=citacion.pk).update(
            RUT_NID=None, TAR_NID=None, CI_NVALORTARIFA=None
        )

        response = self.client.get(
            reverse('pla_citacion_resumen', args=[citacion.id])
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        ruta = next(
            item for item in data['datos_operacionales']
            if item['label'] == 'Ruta del transportista'
        )
        self.assertEqual(ruta['value'], 'Sin ruta asignada')
        self.assertEqual(data['ruta_transportista'], {
            'id': None, 'nombre': 'Sin ruta asignada'
        })

    def test_operacion_planta_bloquea_edicion(self):
        citacion = self.crear_citacion_para_edicion()
        OPERACION_PLANTA_LOG.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO='PESAJE_ENTRADA',
            OPL_CPERFIL_RESPONSABLE='OPERADOR'
        )

        editable, motivo, evidencia = views.citacion_recepcion_terramar_es_editable(citacion)

        self.assertFalse(editable)
        self.assertEqual(evidencia['tipo'], 'operacion_planta')

    def test_etapa_posterior_devuelve_409(self):
        citacion = self.crear_citacion_para_edicion()
        etapa_patio = ETAPA.objects.create(
            US_NID=self.usuario, EP_NID=self.empresa, ET_CTIPO='OPERACION',
            ET_CCODIGO='AUTORIZACION_INGRESO_PATIO',
            ET_CNOMBRE='Autorizacion ingreso a patio',
            ET_NCANTIDADMAXIMA=1, ET_BHABILITADO=True
        )
        ETAPA_LOG.objects.create(
            CI_NID=citacion, EP_NID=self.empresa, SC_NID=self.secuencia,
            ET_NID=etapa_patio, US_INICIO_ID=self.usuario,
            EL_FFECHAINICIO=timezone.now()
        )

        response = self.client.get(
            reverse('editar_citacion_recepcion_terramar', args=[citacion.id])
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['evidencia']['tipo'], 'etapa')

    def test_endpoint_no_confia_en_empresa_solicitada(self):
        citacion = self.crear_citacion_para_edicion()
        session = self.client.session
        session['empresa_id'] = 999999
        session.save()

        response = self.client.get(
            reverse('editar_citacion_recepcion_terramar', args=[citacion.id]),
            {'_empresa_id': 999999}
        )

        self.assertEqual(response.status_code, 400)

    def test_post_revalida_editabilidad_dentro_del_atomic(self):
        citacion = self.crear_citacion_para_edicion()
        numero_original = citacion.CI_CNUMERODOCUMENTO
        post = {
            'item_id': self.item.id,
            'secuencia_id': self.secuencia.id,
            'fecha_llegada': '2026-08-11',
            'hora_citacion': '09:30',
            'contenedor_crt': 'CRT-TEST',
            'bodega': 'Bodega modificada',
            'numero_guia': 'GUIA-NUEVA',
            'transporte_a_cargo': 'Terramar',
            'empresa_transporte_id': self.transportista.id,
            'conductor_id': self.conductor.id,
            'codigo_pais': '+56',
            'telefono': '912345678',
            'patente': 'TEST11',
            'ruta_id': self.ruta.id,
            'tarifa_id': self.tarifa.id,
        }
        with patch.object(
            views, 'citacion_recepcion_terramar_es_editable',
            side_effect=[
                (True, '', {}),
                (False, 'La citacion avanzo mientras estaba abierta.', {
                    'tipo': 'operacion_planta'
                }),
            ]
        ):
            response = self.client.post(
                reverse('editar_citacion_recepcion_terramar', args=[citacion.id]),
                post
            )

        self.assertEqual(response.status_code, 409, response.content)
        citacion.refresh_from_db()
        self.assertEqual(citacion.CI_CNUMERODOCUMENTO, numero_original)
