from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CALENDARIO, CITACION, DETALLE_SECUENCIA, EMPRESA, ETAPA,
    OPERACION_PLANTA_LOG, PERFIL, PERFIL_USUARIO, PLANIFICACION, SECUENCIA,
    SYSLOGGER, USERS_EMPRESA,
)


class OperacionesTerminadasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.operador = User.objects.create_user('Operador_historial', password='test')
        cls.guardia = User.objects.create_user('Guardia_Porteria_historial', password='test')
        cls.solo_terramar = User.objects.create_user('Operador_solo_terramar', password='test')
        cls.terramar = cls.empresa(1, 'TERRAMAR CHILE')
        cls.sbh = cls.empresa(2, 'ACEITES SBH')
        for empresa in (cls.terramar, cls.sbh):
            USERS_EMPRESA.objects.create(US_NID=cls.operador, EP_NID=empresa)
            USERS_EMPRESA.objects.create(US_NID=cls.guardia, EP_NID=empresa)
        USERS_EMPRESA.objects.create(US_NID=cls.solo_terramar, EP_NID=cls.terramar)
        for usuario in (cls.operador, cls.solo_terramar):
            perfil = PERFIL.objects.create(
                US_NID=usuario, PR_CCODIGO=f'OPERADOR_ROMANA_{usuario.id}',
                PR_CNOMBRE='OPERADOR ROMANA',
            )
            PERFIL_USUARIO.objects.create(US_NID=usuario, PR_NID=perfil)
        perfil_guardia = PERFIL.objects.create(
            US_NID=cls.guardia, PR_CCODIGO='GUARDIA_PORTERIA_HIST',
            PR_CNOMBRE='GUARDIA PORTERIA',
        )
        PERFIL_USUARIO.objects.create(US_NID=cls.guardia, PR_NID=perfil_guardia)
        cls.citaciones = {}
        for empresa in (cls.terramar, cls.sbh):
            calendario = CALENDARIO.objects.create(
                US_NID=cls.operador, EP_NID=empresa, CA_CNOMBRE=f'Historial {empresa.id}',
                CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
                CA_NDIA=5, CA_NMES=8, CA_NANO=2026, CA_NCANTIDADCUPOS=20,
            )
            for tipo in ('RECEPCION', 'DESPACHO'):
                plan = PLANIFICACION.objects.create(
                    US_NID=cls.operador, EP_NID=empresa, CAL_NID=calendario,
                    PL_CTIPOCUPO=tipo, PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=20,
                )
                codigo = 'RECEPCION_TERRAMAR' if tipo == 'RECEPCION' and empresa.id == 1 else (
                    'RECEPCION_ESTANQUE_SBH' if tipo == 'RECEPCION' else 'EST_SBH_CLIENTE'
                )
                secuencia = SECUENCIA.objects.create(
                    US_NID=cls.operador, EP_NID=empresa, SE_CTIPO=tipo,
                    SE_CCODIGO=codigo, SE_CNOMBRE=codigo, SE_BHABILITADO=True,
                )
                etapa = ETAPA.objects.create(
                    US_NID=cls.operador, EP_NID=empresa, ET_CTIPO='OPERACION',
                    ET_CCODIGO=f'OP_{empresa.id}_{tipo}', ET_CNOMBRE='Operacion Planta',
                    ET_NCANTIDADMAXIMA=20, ET_BHABILITADO=True,
                )
                DETALLE_SECUENCIA.objects.create(
                    US_NID=cls.operador, EP_NID=empresa, SC_NID=secuencia,
                    ET_NID=etapa, SE_NPASO=1, SE_BHABILITADO=True, SE_BOBLIGATORIO=True,
                )
                activa = cls.crear_citacion(empresa, plan, secuencia, tipo, 1)
                terminada = cls.crear_citacion(empresa, plan, secuencia, tipo, 2)
                cls.habilitar(activa)
                cls.habilitar(terminada)
                cls.confirmar(terminada, timezone.now() - timedelta(minutes=empresa.id * 10))
                cls.citaciones[(empresa.id, tipo, 'activa')] = activa
                cls.citaciones[(empresa.id, tipo, 'terminada')] = terminada
        base = cls.citaciones[(1, 'RECEPCION', 'activa')]
        cls.intermedia = cls.crear_citacion(cls.terramar, base.PL_NID, base.SC_NID, 'RECEPCION', 3)
        cls.habilitar(cls.intermedia)
        for paso in ('Pesaje Salida', 'Autorizar Salida'):
            cls.log(cls.intermedia, paso, cls.operador)
        cls.antigua = cls.crear_citacion(cls.terramar, base.PL_NID, base.SC_NID, 'RECEPCION', 4)
        cls.habilitar(cls.antigua)
        cls.confirmar(cls.antigua, timezone.now() - timedelta(days=2))

    @classmethod
    def empresa(cls, pk, nombre):
        return EMPRESA.objects.create(
            id=pk, EP_CRAZONSOCIAL=nombre, EP_CRUT=f'{pk}-9',
            EP_CBASEDATOS='test', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )

    @classmethod
    def crear_citacion(cls, empresa, plan, secuencia, tipo, cupo):
        return CITACION.objects.create(
            US_NID=cls.operador, EP_NID=empresa, PL_NID=plan, SC_NID=secuencia,
            CI_FFECHAREGISTRO=timezone.now(), CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=cupo, CI_CTIPO=tipo, CI_CESTADO='EN PROCESO',
            CI_CNUMERODOCUMENTO=f'DOC-{empresa.id}-{tipo}-{cupo}',
        )

    @classmethod
    def log(cls, citacion, paso, usuario, fecha=None):
        return OPERACION_PLANTA_LOG.objects.create(
            US_NID=usuario, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO=paso, OPL_CPERFIL_RESPONSABLE='TEST',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
            OPL_FFECHAREGISTRO=fecha or timezone.now(),
        )

    @classmethod
    def habilitar(cls, citacion):
        cls.log(citacion, 'Habilitar Operacion Planta', cls.operador)
        SYSLOGGER.objects.create(
            US_NID=cls.guardia, EP_NID=citacion.EP_NID,
            LOG_FFECHAREGISTRO=timezone.now(), LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
            LOG_CADD1=str(citacion.id),
        )

    @classmethod
    def confirmar(cls, citacion, fecha):
        return cls.log(citacion, 'Confirmar Salida', cls.guardia, fecha)

    def url(self, empresa, tipo, terminadas=False):
        contexto = 'operacion_planta_terminadas' if terminadas else 'operacion_planta'
        return f"{reverse('cit_listall_recepciones')}?contexto={contexto}&tipo={tipo}&empresa_id={empresa.id}&_empresa_id={empresa.id}"

    @staticmethod
    def ids(response):
        return [obj.id for obj in response.context['object_list']]

    def test_activa_excluye_confirmadas_y_no_mueve_intermedias(self):
        self.client.force_login(self.operador)
        response = self.client.get(self.url(self.terramar, 'RECEPCION'))
        ids = self.ids(response)
        self.assertIn(self.citaciones[(1, 'RECEPCION', 'activa')].id, ids)
        self.assertIn(self.intermedia.id, ids)
        self.assertNotIn(self.citaciones[(1, 'RECEPCION', 'terminada')].id, ids)

    def test_confirmar_salida_mueve_inmediatamente_entre_bandejas(self):
        citacion = self.citaciones[(1, 'RECEPCION', 'activa')]
        for paso in ('Pesaje Entrada', 'Ciclo Descarga', 'Pesaje Salida', 'Documentación', 'Autorizar Salida'):
            self.log(citacion, paso, self.operador)
        self.client.force_login(self.guardia)
        confirmado = self.client.post(
            f"{reverse('operacion_planta_guardar_paso', args=[citacion.id])}?empresa_id=1",
            {'paso': 'Confirmar Salida', 'observacion': 'Salida confirmada por Guardia.'},
        )
        self.assertEqual(confirmado.status_code, 200, confirmado.content)

        self.client.force_login(self.operador)
        self.assertNotIn(citacion.id, self.ids(self.client.get(self.url(self.terramar, 'RECEPCION'))))
        self.assertIn(citacion.id, self.ids(self.client.get(self.url(self.terramar, 'RECEPCION', True))))
    def test_historico_ambas_empresas_tipos_filtros_y_paginacion(self):
        self.client.force_login(self.operador)
        for empresa in (self.terramar, self.sbh):
            for tipo in ('RECEPCION', 'DESPACHO'):
                with self.subTest(empresa=empresa.id, tipo=tipo):
                    response = self.client.get(self.url(empresa, tipo, True))
                    self.assertEqual(response.status_code, 200)
                    ids = self.ids(response)
                    self.assertIn(self.citaciones[(empresa.id, tipo, 'terminada')].id, ids)
                    self.assertNotIn(self.citaciones[(empresa.id, tipo, 'activa')].id, ids)
                    self.assertContains(response, 'Ver historial')
                    self.assertEqual(response.context['object_list'].paginator.per_page, 100)

    def test_historico_ordena_por_fecha_confirmacion_descendente(self):
        self.client.force_login(self.operador)
        ids = self.ids(self.client.get(self.url(self.terramar, 'RECEPCION', True)))
        self.assertLess(ids.index(self.citaciones[(1, 'RECEPCION', 'terminada')].id), ids.index(self.antigua.id))

    def test_detalle_terminado_es_solo_lectura_y_backend_rechaza_post(self):
        self.client.force_login(self.operador)
        citacion = self.citaciones[(1, 'RECEPCION', 'terminada')]
        detalle = self.client.get(f"{reverse('operacion_planta_citacion', args=[citacion.id])}?empresa_id=1&modo=historial")
        self.assertEqual(detalle.status_code, 200)
        self.assertTrue(detalle.context['operacion_solo_lectura'])
        self.assertContains(detalle, 'Historial disponible en modo solo lectura')
        bloqueo = self.client.post(
            f"{reverse('operacion_planta_guardar_paso', args=[citacion.id])}?empresa_id=1",
            {'paso': 'Confirmar Salida'},
        )
        self.assertEqual(bloqueo.status_code, 409)

    def test_seguridad_empresa_menu_y_parametros(self):
        self.client.force_login(self.solo_terramar)
        permitido = self.client.get(self.url(self.terramar, 'RECEPCION', True))
        self.assertContains(permitido, 'Bandeja Operaci&oacute;n Planta')
        self.assertContains(permitido, 'Bandeja Operaciones Terminadas')
        denegado = self.client.get(self.url(self.sbh, 'RECEPCION', True))
        if denegado.status_code == 200 and denegado.context:
            self.assertNotIn(self.citaciones[(2, 'RECEPCION', 'terminada')].id, self.ids(denegado))
        else:
            self.assertIn(denegado.status_code, {302, 403})

        self.client.force_login(self.operador)
        base = reverse('cit_listall_recepciones')
        self.assertEqual(self.client.get(f'{base}?contexto=operacion_planta_terminadas&tipo=OTRO&_empresa_id=1').status_code, 400)
        self.assertEqual(self.client.get(f'{base}?contexto=operacion_planta_admin&tipo=RECEPCION&_empresa_id=1').status_code, 400)