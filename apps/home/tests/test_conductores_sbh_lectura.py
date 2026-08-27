from datetime import datetime, time

from django.contrib.auth.models import User
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from apps.home.models import (
    CALENDARIO, CAMION, CITACION, CONDUCTOR, CONDUCTOR_EMPRESA, EMPRESA,
    PLANIFICACION, SECUENCIA, SOCIONEGOCIO, USERS_EMPRESA,
)
from apps.home.services.padron_conductores import (
    asignar_transporte_operacional_sbh,
    asegurar_membresia_conductor_empresa,
    queryset_conductores_operativos,
    queryset_conductores_por_transporte_sbh,
)


class ConductoresSbhLecturaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        datos_empresa = {'EP_CBASEDATOS': 'test', 'EP_CUSUARIOSBD': 'test', 'EP_CPORT': '5432'}
        cls.terramar = EMPRESA.objects.create(id=1, EP_CRAZONSOCIAL='Terramar', EP_CRUT='1-9', **datos_empresa)
        cls.sbh = EMPRESA.objects.create(id=2, EP_CRAZONSOCIAL='SBH', EP_CRUT='2-9', **datos_empresa)
        cls.usuario = User.objects.create_superuser('sbh_lectura', 'sbh@example.com', 'test')
        USERS_EMPRESA.objects.create(US_NID=cls.usuario, EP_NID=cls.terramar)
        USERS_EMPRESA.objects.create(US_NID=cls.usuario, EP_NID=cls.sbh)
        cls.transporte_historico = cls._transporte(cls.terramar, 'Pascal histórico', 'P77665886')
        cls.pascal_sbh = cls._transporte(cls.sbh, 'Pascal SBH', 'P77665886')
        cls.otro_historico = cls._transporte(cls.terramar, 'Otro histórico', 'OTRO01')
        cls.otro_sbh = cls._transporte(cls.sbh, 'Otro SBH', 'OTRO01')
        cls.legacy_visual = cls._transporte(cls.terramar, 'Legacy no operativo', 'LEGACY01')
        cls.compartido = cls._conductor('Compartido', '10674376-2', cls.legacy_visual)
        cls.sin_membresia = cls._conductor('Sin membresía', '10891933-7', cls.legacy_visual)
        cls.sin_historial = cls._conductor('Sin historial', '12065284-2', cls.legacy_visual)
        cls.generico = cls._conductor('Genérico', '99999999-9', cls.legacy_visual)
        cls.camion = CAMION.objects.create(
            EP_NID=cls.sbh, SN_NID=cls.pascal_sbh, US_NID=cls.usuario,
            CAM_CPATENTE='SBH001', CAM_BHABILITADO=True,
        )
        asegurar_membresia_conductor_empresa(conductor=cls.compartido, empresa=cls.sbh)
        asegurar_membresia_conductor_empresa(conductor=cls.sin_historial, empresa=cls.sbh)
        asegurar_membresia_conductor_empresa(conductor=cls.generico, empresa=cls.sbh)
        cls.planificacion, cls.secuencia = cls._contexto_citacion()
        cls._citacion(cls.compartido, cls.transporte_historico, 1)
        cls._citacion(cls.generico, cls.transporte_historico, 2)

    @classmethod
    def _transporte(cls, empresa, nombre, codigo):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL=nombre, SN_CRUT=f'76{empresa.pk}00000-{empresa.pk}',
            SN_CCODIGO_SAP=codigo, SN_CTIPO='S', SN_BHABILITADO=True,
        )

    @classmethod
    def _conductor(cls, nombre, rut, transporte):
        return CONDUCTOR.objects.create(
            EP_NID=cls.terramar, SN_NID=transporte, CON_CNOMBRE=nombre,
            CON_CAPELLIDO='Prueba', CON_CRUT=rut, CON_BHABILITADO=True,
        )

    @classmethod
    def _contexto_citacion(cls):
        calendario = CALENDARIO.objects.create(
            EP_NID=cls.sbh, CA_NDIA=1, CA_NMES=7, CA_NANO=2026,
            CA_NCANTIDADCUPOS=10, CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
        )
        planificacion = PLANIFICACION.objects.create(
            EP_NID=cls.sbh, CAL_NID=calendario, PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.make_aware(datetime(2026, 7, 1, 8)), PL_NCANTIDADCUPOS=10,
        )
        secuencia = SECUENCIA.objects.create(
            EP_NID=cls.sbh, SE_CTIPO='RECEPCION', SE_CCODIGO='SBH_LECTURA',
            SE_CNOMBRE='SBH lectura', SE_BHABILITADO=True,
        )
        return planificacion, secuencia

    @classmethod
    def _citacion(cls, conductor, proveedor, cupo):
        return CITACION.objects.create(
            EP_NID=cls.sbh, PL_NID=cls.planificacion, SC_NID=cls.secuencia,
            CON_NID=conductor, PRO_NID=proveedor,
            CI_FFECHACITACION=timezone.make_aware(datetime(2026, 7, 1, 8)),
            CI_NCUPO=cupo, CI_CESTADO='Insumo Programado', CI_CTIPO='RECEPCION',
        )

    def _activar(self, empresa):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion['empresa_id'] = empresa.pk
        sesion.save()

    def test_miembro_sbh_legacy_abre_detalle_y_sin_membresia_da_404(self):
        self._activar(self.sbh)
        respuesta = self.client.get(f'/con_listone/{self.compartido.pk}?_empresa_id=2')
        self.assertEqual(respuesta.status_code, 200)
        respuesta = self.client.get(f'/con_listone/{self.sin_membresia.pk}?_empresa_id=2')
        self.assertEqual(respuesta.status_code, 404)

    def test_miembro_sin_historial_abre_y_lista_transporte_vacio(self):
        self._activar(self.sbh)
        respuesta = self.client.get(f'/con_listone/{self.sin_historial.pk}?_empresa_id=2')
        self.assertEqual(respuesta.status_code, 200)
        listado = asignar_transporte_operacional_sbh([self.sin_historial])
        self.assertEqual(listado[0].transporte_operacional_sbh, '-')

    def test_transporte_sbh_usa_cardcode_no_sn_legacy(self):
        listado = asignar_transporte_operacional_sbh([self.compartido])
        self.assertEqual(listado[0].transporte_operacional_sbh, 'Pascal SBH')
        self.assertNotEqual(listado[0].transporte_operacional_sbh, self.legacy_visual.SN_CRAZONSOCIAL)
        self._activar(self.sbh)
        respuesta = self.client.get('/con_listall/?_empresa_id=2')
        self.assertContains(respuesta, 'Pascal SBH')
        self.assertNotContains(respuesta, 'Legacy no operativo')

    def test_varios_transportes_sbh_se_muestran_como_varios(self):
        self._citacion(self.compartido, self.otro_historico, 3)
        listado = asignar_transporte_operacional_sbh([self.compartido])
        self.assertEqual(listado[0].transporte_operacional_sbh, 'Varios')

    def test_ficha_proveedor_sbh_recupera_historico_por_cardcode_y_excluye_generico(self):
        conductores = queryset_conductores_por_transporte_sbh(self.pascal_sbh)
        self.assertEqual(list(conductores.values_list('pk', flat=True)), [self.compartido.pk])
        self._activar(self.sbh)
        respuesta = self.client.get(f'/pro_listone/{self.pascal_sbh.pk}?_empresa_id=2')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Compartido Prueba')
        self.assertNotContains(respuesta, 'Genérico Prueba')

    def test_listado_sbh_hace_consulta_lote_para_transportes(self):
        conductores = queryset_conductores_operativos(2)
        with CaptureQueriesContext(connection) as consultas:
            resultado = asignar_transporte_operacional_sbh(conductores)
        self.assertLessEqual(len(consultas), 3)
        self.assertEqual(len(resultado), 2)

    def test_terramar_conserva_listado_y_detalle_legacy(self):
        self.assertIn(self.sin_membresia.pk, queryset_conductores_operativos(1).values_list('pk', flat=True))
        self._activar(self.terramar)
        respuesta = self.client.get(f'/con_listone/{self.sin_membresia.pk}?_empresa_id=1')
        self.assertEqual(respuesta.status_code, 200)

    def test_lectura_no_modifica_conductor_citacion_ni_membresias(self):
        citacion = CITACION.objects.get(CON_NID=self.compartido, PRO_NID=self.transporte_historico)
        antes = (
            self.compartido.SN_NID_id, citacion.PRO_NID_id,
            CONDUCTOR_EMPRESA.objects.count(), self.camion.SN_NID_id,
        )
        list(asignar_transporte_operacional_sbh(queryset_conductores_operativos(2)))
        list(queryset_conductores_por_transporte_sbh(self.pascal_sbh))
        self.compartido.refresh_from_db()
        citacion.refresh_from_db()
        self.camion.refresh_from_db()
        self.assertEqual(
            (
                self.compartido.SN_NID_id, citacion.PRO_NID_id,
                CONDUCTOR_EMPRESA.objects.count(), self.camion.SN_NID_id,
            ), antes,
        )
