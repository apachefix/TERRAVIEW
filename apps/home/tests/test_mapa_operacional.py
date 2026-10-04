import json
from copy import deepcopy
from datetime import timedelta
from time import perf_counter
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CAMION, CAMION_PATIO, CAMPO, CITACION, DATO_OPERACION,
    DETALLE_SECUENCIA, EMPRESA, ETAPA, ETAPA_LOG, OPERACION_PLANTA_LOG,
    PERFIL, PERFIL_USUARIO, PLANIFICACION, RESULTADO_CALIDAD_OPERACION,
    SECUENCIA, SYSLOGGER, USERS_EMPRESA,
)
from apps.home.services.mapa_operacional import obtener_estado_mapa_operacional
from apps.home.services.mapa_operacional_config import REGLAS, zonas_configuradas


class MapaOperacionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('mapa_admin', is_superuser=True)
        cls.empresas = {}
        cls.planes = {}
        cls.secuencias = {}
        for eid, nombre in ((1, 'TERRAMAR CHILE'), (2, 'ACEITES SBH')):
            e = EMPRESA.objects.create(id=eid, EP_CRAZONSOCIAL=nombre, EP_CRUT=str(eid),
                                      EP_CBASEDATOS='test', EP_CUSUARIOSBD='test', EP_CPORT='5432')
            cls.empresas[eid] = e
            USERS_EMPRESA.objects.create(US_NID=cls.user, EP_NID=e)
            cal = CALENDARIO.objects.create(EP_NID=e, CA_NDIA=4, CA_NMES=10, CA_NANO=2026,
                                           CA_NCANTIDADCUPOS=100)
            cls.planes[eid] = PLANIFICACION.objects.create(EP_NID=e, CAL_NID=cal, PL_CTIPOCUPO='RECEPCION')
            for tipo, codigo in (
                ('RECEPCION', 'RECEPCION_TERRAMAR' if eid == 1 else 'RECEPCION_ESTANQUE_SBH'),
                ('DESPACHO', 'DESPACHO_TERRAMAR' if eid == 1 else 'EST_SBH_CLIENTE'),
            ):
                s = SECUENCIA.objects.create(EP_NID=e, SE_CTIPO=tipo, SE_CCODIGO=codigo,
                                            SE_CNOMBRE=codigo, SE_BHABILITADO=True)
                cls.secuencias[eid, tipo] = s
                etapa = ETAPA.objects.create(EP_NID=e, ET_CTIPO='OPERACION', ET_CCODIGO='PROGRAMADO',
                                            ET_CNOMBRE='Programado', ET_NCANTIDADMAXIMA=100, ET_BHABILITADO=True)
                DETALLE_SECUENCIA.objects.create(US_NID=cls.user, EP_NID=e, SC_NID=s,
                                                ET_NID=etapa, SE_NPASO=1, SE_BHABILITADO=True)

    def cita(self, empresa=1, tipo='RECEPCION', ingreso=True, **overrides):
        fields = dict(EP_NID=self.empresas[empresa], PL_NID=self.planes[empresa],
                      SC_NID=self.secuencias[empresa, tipo], CI_CTIPO=tipo, CI_CESTADO='EN PROCESO',
                      CI_NCUPO=1, CI_FFECHACITACION=timezone.now(), CI_FFECHAINICIO=timezone.now())
        fields.update(overrides)
        c = CITACION.objects.create(**fields)
        if ingreso:
            SYSLOGGER.objects.create(US_NID=self.user, EP_NID=c.EP_NID, LOG_COPERACION='AUTORIZA_INGRESO_PLANTA',
                                     LOG_CADD1=str(c.id), LOG_FFECHAREGISTRO=timezone.now())
            self.log(c, 'Habilitar Operacion Planta')
        return c

    def log(self, c, paso, **kwargs):
        fields = dict(US_NID=self.user, EP_NID=c.EP_NID, PL_NID=c.PL_NID, CI_NID=c,
                      OPL_CPASO=paso, OPL_CPERFIL_RESPONSABLE='TEST', OPL_CESTADO='COMPLETADO',
                      OPL_FFECHAREGISTRO=timezone.now() - timedelta(minutes=5))
        fields.update(kwargs)
        return OPERACION_PLANTA_LOG.objects.create(**fields)

    def dato(self, c, codigo, valor, **kwargs):
        campo = CAMPO.objects.create(EP_NID=c.EP_NID, CA_CTIPO='TEXTO', CA_CCODIGO=codigo, CA_CETIQUETA=codigo)
        fields = dict(US_NID=self.user, EP_NID=c.EP_NID, SC_NID=c.SC_NID, CI_NID=c,
                      ET_NID=DETALLE_SECUENCIA.objects.filter(SC_NID=c.SC_NID).first().ET_NID,
                      CAMP_NID=campo, DO_CVALOR=json.dumps(valor) if isinstance(valor, dict) else valor)
        fields.update(kwargs)
        return DATO_OPERACION.objects.create(**fields)

    def camion(self, empresa=1):
        return obtener_estado_mapa_operacional(empresa)['camiones'][0]

    def test_empresas_y_colores(self):
        a = self.cita(1)
        b = self.cita(2, 'DESPACHO')
        self.assertEqual([t['citacion_id'] for t in obtener_estado_mapa_operacional(1)['camiones']], [a.id])
        self.assertEqual([t['citacion_id'] for t in obtener_estado_mapa_operacional(2)['camiones']], [b.id])
        self.assertEqual(self.camion(1)['color'], 'verde')
        self.assertEqual(self.camion(2)['color'], 'azul')

    def test_cerrados_archivados_deshabilitados_y_sin_ingreso(self):
        for estado in ('TERMINADO', 'RECHAZADO', 'SALIDA_CONFIRMADA', 'ANULADO', 'CANCELADO'):
            self.cita(CI_CESTADO=estado)
        self.cita(CI_BARCHIVADO=True)
        self.cita(CI_BHABILITADO=False)
        self.cita(CI_FFECHATERMINO=timezone.now())
        self.cita(ingreso=False)
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_plan_archivado_excluido(self):
        self.cita()
        self.planes[1].PL_BARCHIVADO = True
        self.planes[1].save(update_fields=['PL_BARCHIVADO'])
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_patio_no_equivale_a_ingreso(self):
        c = self.cita(ingreso=False)
        CAMION_PATIO.objects.create(EP_NID=c.EP_NID, CI_NID=c, US_GUARDIA_ID=self.user, CPA_CPATENTE='PATIO1')
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_salida_confirmada_excluye_aunque_citacion_siga_abierta(self):
        c = self.cita()
        self.log(c, 'Confirmar Salida')
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_pesaje_transicion_espera_descarga_y_timer_persistente(self):
        c = self.cita()
        self.assertEqual(self.camion()['zona'], 'ROMANA')
        pesaje = self.log(c, 'Pesaje Entrada')
        t = self.camion()
        self.assertEqual(t['zona_operacional'], 'ESPERA')
        self.assertEqual(t['zona'], 'ZONA_ESPERA')
        self.assertEqual(t['inicio_etapa'], pesaje.OPL_FFECHAREGISTRO.isoformat())
        inicio = timezone.now() - timedelta(seconds=90)
        self.dato(c, 'OP_CICLO_DESCARGA', {'inicio_descarga': inicio.isoformat()})
        t = self.camion()
        self.assertEqual(t['zona_operacional'], 'DESCARGA')
        self.assertEqual(t['zona'], 'ZONA_CARGA_DESCARGA')
        self.assertAlmostEqual(t['segundos_etapa'], 90, delta=2)
        self.log(c, 'Ciclo Descarga')
        self.assertEqual(self.camion()['zona'], 'ROMANA')

    def test_calidad_y_vapor_segun_datos_reales(self):
        c = self.cita(2)
        self.log(c, 'Pesaje Entrada')
        self.assertEqual(self.camion(2)['zona'], 'MUESTREO')
        self.dato(c, 'OP_TOMA_MUESTRA_ACCION', {'tipo_accion': 'vapor', 'fecha_iso': timezone.now().isoformat()})
        self.assertEqual(self.camion(2)['zona'], 'VAPOR')
        self.dato(c, 'OP_TOMA_MUESTRA_TIEMPO_VAPOR', {'inicio_vapor': timezone.now().isoformat(), 'fin_vapor': timezone.now().isoformat()})
        self.log(c, 'Toma de muestra')
        self.assertEqual(self.camion(2)['zona_operacional'], 'ESPERA_CALIDAD')
        self.assertEqual(self.camion(2)['zona'], 'ZONA_ESPERA')

    def test_origen_y_destino_confirmados_no_se_inventan(self):
        for tipo, codigo, campo in [('RECEPCION', 'RECEPCION_ESTANQUE_SBH', 'ETA3_ESTANQUE'),
                                     ('DESPACHO', 'EST_SBH_CLIENTE', 'ACD_ESTANQUE_ORIGEN')]:
            with self.subTest(tipo=tipo):
                c = self.cita(2, tipo)
                for paso in ('Pesaje Entrada', 'Toma de muestra', 'Analisis y calidad', 'Resultado Calidad'):
                    self.log(c, paso)
                self.dato(c, 'OP_CICLO_DESCARGA', {'inicio_descarga': timezone.now().isoformat()})
                self.dato(c, campo, 'TK08')
                key = (2, codigo, '', 'TK08')
                with patch.dict('apps.home.services.mapa_operacional.ESTANQUES_CONFIRMADOS', {key: 'TK-08'}):
                    t = next(t for t in obtener_estado_mapa_operacional(2)['camiones'] if t['citacion_id'] == c.id)
                    self.assertEqual(t['zona'], 'TK-08')
                t = next(t for t in obtener_estado_mapa_operacional(2)['camiones'] if t['citacion_id'] == c.id)
                self.assertIn(t['zona_operacional'], ('CARGA', 'DESCARGA'))
                self.assertEqual(t['zona'], 'ZONA_CARGA_DESCARGA')

    def test_datos_y_logs_ajenos_no_contaminan(self):
        c = self.cita()
        self.log(c, 'Pesaje Entrada', EP_NID=self.empresas[2])
        self.dato(c, 'ING_PATENTE', 'AJENO', EP_NID=self.empresas[2])
        self.dato(c, 'ING_PATENTE', 'OTRA-SECUENCIA', SC_NID=self.secuencias[1, 'DESPACHO'])
        t = self.camion()
        self.assertEqual(t['zona'], 'ROMANA')
        self.assertEqual(t['patente'], 'Sin patente')
        self.assertNotIn('Pesaje Entrada', [e['paso'] for e in t['eventos']])

    def test_ingreso_de_otra_empresa_no_habilita(self):
        c = self.cita(ingreso=False)
        self.log(c, 'Habilitar Operacion Planta')
        SYSLOGGER.objects.create(US_NID=self.user, EP_NID=self.empresas[2], LOG_COPERACION='AUTORIZA_INGRESO_PLANTA', LOG_CADD1=str(c.id))
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_reglas_no_se_comparten_entre_secuencias(self):
        original = deepcopy(REGLAS)
        with patch.dict(REGLAS[(1, 'RECEPCION_TERRAMAR', 'RECEPCION')], {'Pesaje Entrada': 'OTRO'}):
            self.cita(1)
            self.cita(2)
            self.assertEqual(self.camion(1)['zona'], 'OTRO')
            self.assertEqual(self.camion(2)['zona'], 'ROMANA')
        self.assertEqual(REGLAS, original)

    def test_secuencia_no_configurada_no_hereda_reglas(self):
        c = self.cita()
        c.SC_NID.SE_CCODIGO = 'RECEPCION_SERVICIO'
        c.SC_NID.save(update_fields=['SE_CCODIGO'])
        data = obtener_estado_mapa_operacional(1)
        self.assertEqual(data['camiones'], [])
        self.assertEqual(data['sin_soporte'], 1)

    def test_autenticacion_empresa_valida_y_metodos_en_ambas_rutas(self):
        for name in ('dashboard_grafico', 'dashboard_grafico_estado'):
            url = reverse(name)
            for empresa in (1, 2):
                response = self.client.get(url, {'_empresa_id': empresa})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith('/login/?next='))
        lector = get_user_model().objects.create_user('mapa_lector_sin_asignacion')
        self.client.force_login(lector)
        for name in ('dashboard_grafico', 'dashboard_grafico_estado'):
            url = reverse(name)
            for method in ('post', 'put', 'patch', 'delete'):
                response = getattr(self.client, method)(url + '?_empresa_id=1')
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response['Allow'], 'GET')
            for empresa in ('invalid', 0, 3, -1):
                self.assertEqual(self.client.get(url, {'_empresa_id': empresa}).status_code, 400)
            for empresa in (1, 2):
                self.assertEqual(self.client.get(url, {'_empresa_id': empresa}).status_code, 200)

    def test_asignacion_a_una_empresa_no_restringe_visualizacion_de_otra(self):
        citas = {empresa: self.cita(empresa) for empresa in (1, 2)}
        for asignada in (1, 2):
            lector = get_user_model().objects.create_user(f'mapa_empresa_{asignada}')
            USERS_EMPRESA.objects.create(US_NID=lector, EP_NID=self.empresas[asignada])
            self.client.force_login(lector)
            session = self.client.session
            session['empresa_id'] = asignada
            session.save()
            for empresa in (1, 2):
                with self.subTest(asignada=asignada, visualizar=empresa):
                    page = self.client.get(reverse('dashboard_grafico'), {'_empresa_id': empresa})
                    self.assertEqual(page.status_code, 200)
                    self.assertContains(page, f'data-empresa="{empresa}"')
                    response = self.client.get(reverse('dashboard_grafico_estado'), {'_empresa_id': empresa})
                    self.assertEqual(response.status_code, 200)
                    data = response.json()
                    self.assertEqual(data['empresa_id'], empresa)
                    self.assertEqual([t['citacion_id'] for t in data['camiones']], [citas[empresa].id])
                    self.assertTrue(all(t['empresa_id'] == empresa for t in data['camiones']))
                    self.assertEqual(self.client.session['empresa_id'], asignada)
            self.assertEqual(list(USERS_EMPRESA.objects.filter(US_NID=lector).values_list('EP_NID_id', flat=True)), [asignada])

    def test_todos_los_perfiles_pueden_ver_ambas_empresas(self):
        nombres = ('Planificador', 'Recepcionista', 'Guardia', 'Guardia Portería',
                   'Asistente Recepción', 'Asistente Despacho', 'Asistente_C_D',
                   'Operador Romana', 'Calidad', 'Sala Control', 'MAESC', 'PRO_CIT',
                   'PERFIL_AJENO_A_OPERACION')
        for index, nombre in enumerate(nombres):
            lector = get_user_model().objects.create_user(f'mapa_perfil_{index}')
            perfil = PERFIL.objects.create(US_NID=lector, PR_CCODIGO=nombre, PR_CNOMBRE=nombre)
            PERFIL_USUARIO.objects.create(US_NID=lector, PR_NID=perfil)
            self.client.force_login(lector)
            for empresa in (1, 2):
                for name in ('dashboard_grafico', 'dashboard_grafico_estado'):
                    with self.subTest(perfil=nombre, empresa=empresa, ruta=name):
                        self.assertEqual(self.client.get(reverse(name), {'_empresa_id': empresa}).status_code, 200)

    def test_endpoint_no_filtra_por_secuencias_operacionales_del_usuario(self):
        lector = get_user_model().objects.create_user('mapa_secuencias_restringidas')
        c1, c2 = self.cita(1), self.cita(2)
        self.client.force_login(lector)
        with patch.object(views, 'obtener_secuencias_asignadas_usuario', return_value=[c1.SC_NID_id]) as asignadas:
            for empresa, cita in ((1, c1), (2, c2)):
                response = self.client.get(reverse('dashboard_grafico_estado'), {'_empresa_id': empresa})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([t['citacion_id'] for t in response.json()['camiones']], [cita.id])
            asignadas.assert_not_called()

    def test_visualizar_no_concede_permiso_operacional_ni_administrativo(self):
        lector = get_user_model().objects.create_user('mapa_visualizacion_sin_operacion')
        USERS_EMPRESA.objects.create(US_NID=lector, EP_NID=self.empresas[1])
        c = self.cita(2)
        self.client.force_login(lector)
        page = self.client.get(reverse('dashboard_grafico'), {'_empresa_id': 2})
        self.assertEqual(page.status_code, 200)
        self.assertFalse(views.usuario_es_operacion_planta(lector))
        self.assertFalse(views.usuario_tiene_empresa(page.wsgi_request, 2))
        self.assertFalse(views.usuario_puede_paso_operacion(lector, ['OPERADOR ROMANA']))
        antes = OPERACION_PLANTA_LOG.objects.count()
        detalle = self.client.get(reverse('operacion_planta_citacion', args=[c.id]), {'_empresa_id': 2})
        self.assertEqual(detalle.status_code, 302)
        guardar = self.client.post(reverse('operacion_planta_guardar_paso', args=[c.id]),
                                   {'_empresa_id': 2, 'paso': 'Pesaje Entrada'})
        self.assertEqual(guardar.status_code, 403)
        self.assertEqual(OPERACION_PLANTA_LOG.objects.count(), antes)
        self.assertEqual(self.client.get(reverse('emp_addone')).status_code, 302)

    def test_polling_solo_select_y_sin_callbacks(self):
        self.cita(1)
        self.cita(2)
        lector = get_user_model().objects.create_user('mapa_lectura_sin_perfil')
        self.client.force_login(lector)
        def read_only(execute, sql, params, many, context):
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'), sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch.object(views, 'asegurar_calidad_iniciada') as calidad:
            for empresa in (1, 2):
                for name in ('dashboard_grafico', 'dashboard_grafico_estado'):
                    for _ in range(2):
                        response = self.client.get(reverse(name), {'_empresa_id': empresa})
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('no-store', response['Cache-Control'])
            calidad.assert_not_called()

    def test_dashboard_reutiliza_template_sin_capa_editable(self):
        self.client.force_login(self.user)
        for empresa in (1, 2):
            response = self.client.get(reverse('dashboard_grafico'), {'_empresa_id': empresa})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'mapa-operacional.js')
            self.assertContains(response, f'data-empresa="{empresa}"')
            self.assertNotContains(response, 'assets/js/flat.js')

    def test_sin_timestamp_no_inventa_inicio(self):
        c = self.cita()
        self.log(c, 'Pesaje Entrada')
        self.log(c, 'Ciclo Descarga')
        self.log(c, 'Pesaje Salida')
        OPERACION_PLANTA_LOG.objects.filter(CI_NID=c, OPL_CPASO='Pesaje Salida').delete()
        # Technical step can outrank completed steps on SBH; no valid start evidence.
        b = self.cita(2)
        e = ETAPA.objects.create(EP_NID=self.empresas[2], ET_CTIPO='OPERACION', ET_CCODIGO='ANALISIS_CALIDAD', ET_CNOMBRE='Analisis y calidad', ET_NCANTIDADMAXIMA=10)
        DETALLE_SECUENCIA.objects.create(US_NID=self.user, EP_NID=b.EP_NID, SC_NID=b.SC_NID, ET_NID=e, SE_NPASO=3, SE_BHABILITADO=True)
        ETAPA_LOG.objects.create(CI_NID=b, EP_NID=b.EP_NID, SC_NID=b.SC_NID, ET_NID=e)
        t = self.camion(2)
        self.assertIsNone(t['inicio_etapa'])
        self.assertIsNone(t['segundos_etapa'])
        self.assertFalse(t['timer_activo'])

    def test_queries_constantes_para_1_y_30_camiones(self):
        self.cita()
        with CaptureQueriesContext(connection) as first:
            obtener_estado_mapa_operacional(1)
        for _ in range(29):
            self.cita()
        start = perf_counter()
        with CaptureQueriesContext(connection) as many:
            data = obtener_estado_mapa_operacional(1)
        self.assertEqual(len(data['camiones']), 30)
        self.assertEqual(len(first), len(many))
        self.assertLessEqual(len(many), 8)
        print(f'MAPA: 1 camion={len(first)} queries; 30 camiones={len(many)} queries; {(perf_counter()-start)*1000:.2f}ms')

    def test_resolver_precargado_conserva_resultado_operacional(self):
        for empresa in (1, 2):
            c = self.cita(empresa)
            self.log(c, 'Pesaje Entrada')
            paso, _, _ = views.obtener_paso_activo_operacion(c)
            self.assertEqual(self.camion(empresa)['paso_operacional'], paso)

    def test_etapa_tecnica_actual_sin_nuevo_estado(self):
        c = self.cita(2)
        e = ETAPA.objects.create(EP_NID=self.empresas[2], ET_CTIPO='OPERACION', ET_CCODIGO='ANALISIS_CALIDAD', ET_CNOMBRE='Analisis y calidad', ET_NCANTIDADMAXIMA=10)
        d = DETALLE_SECUENCIA.objects.create(US_NID=self.user, EP_NID=c.EP_NID, SC_NID=c.SC_NID, ET_NID=e, SE_NPASO=3, SE_BHABILITADO=True)
        log = ETAPA_LOG.objects.create(CI_NID=c, EP_NID=c.EP_NID, SC_NID=c.SC_NID, ET_NID=e, EL_FFECHAINICIO=timezone.now())
        t = self.camion(2)
        self.assertEqual(t['zona_operacional'], 'ESPERA_CALIDAD')
        self.assertEqual(t['zona'], 'ZONA_ESPERA')
        self.assertEqual(t['detalle_secuencia_id'], d.id)
        self.assertEqual(t['inicio_etapa'], log.EL_FFECHAINICIO.isoformat())

    def test_empresa_plan_o_secuencia_inconsistente_no_filtra(self):
        self.cita(SC_NID=self.secuencias[2, 'RECEPCION'])
        self.cita(PL_NID=self.planes[2])
        self.assertEqual(obtener_estado_mapa_operacional(1)['camiones'], [])

    def test_zonas_manuales_en_todas_las_secuencias_auditadas(self):
        for (empresa, codigo, tipo), reglas in REGLAS.items():
            with self.subTest(empresa=empresa, secuencia=codigo):
                secuencia = self.secuencias[empresa, tipo]
                secuencia.SE_CCODIGO = codigo
                # Reception workflow also uses the persisted sequence name.
                secuencia.SE_CNOMBRE = codigo.replace('RECEPCION_', '').replace('_', ' ')
                secuencia.save(update_fields=['SE_CCODIGO', 'SE_CNOMBRE'])
                c = self.cita(empresa, tipo)
                self.log(c, 'Pesaje Entrada')
                for paso in ('Toma de muestra', 'Analisis y calidad', 'Resultado Calidad'):
                    if paso in reglas:
                        self.log(c, paso)
                def actual():
                    return next(t for t in obtener_estado_mapa_operacional(empresa)['camiones'] if t['citacion_id'] == c.id)
                if 'Ciclo Descarga' in reglas:
                    self.assertEqual(actual()['zona'], 'ZONA_ESPERA')
                    self.assertEqual(actual()['zona_operacional'], 'ESPERA')
                    self.dato(c, 'OP_CICLO_DESCARGA', {'inicio_descarga': timezone.now().isoformat()})
                t = actual()
                self.assertEqual(t['zona'], 'ZONA_CARGA_DESCARGA')
                self.assertEqual(t['zona_operacional'], 'CARGA' if tipo == 'DESPACHO' else 'DESCARGA')
                self.assertEqual(t['color'], 'azul' if tipo == 'DESPACHO' else 'verde')

    def test_espera_calidad_no_cambia_kpi_ni_reloj(self):
        c = self.cita(2)
        self.log(c, 'Pesaje Entrada')
        muestra = self.log(c, 'Toma de muestra')
        data = obtener_estado_mapa_operacional(2)
        t = data['camiones'][0]
        self.assertEqual(t['paso_operacional'], 'Analisis y calidad')
        self.assertEqual(t['zona'], 'ZONA_ESPERA')
        self.assertEqual(t['inicio_etapa'], muestra.OPL_FFECHAREGISTRO.isoformat())
        self.assertEqual(data['kpis']['calidad'], 1)
        self.assertEqual(data['kpis']['carga_descarga'], 0)
        self.log(c, 'Analisis y calidad')
        t = self.camion(2)
        self.assertEqual(t['paso_operacional'], 'Resultado Calidad')
        self.assertEqual(t['zona'], 'ZONA_ESPERA')

    def test_plano_vacio_y_zonas_sin_coordenadas(self):
        self.client.force_login(self.user)
        for empresa in (1, 2):
            with self.subTest(empresa=empresa):
                data = obtener_estado_mapa_operacional(empresa)
                self.assertEqual(data['camiones'], [])
                response = self.client.get(reverse('dashboard_grafico'), {'_empresa_id': empresa})
                self.assertContains(response, 'id="mapa-imagen"')
                self.assertContains(response, 'assets/plano/plantilla_planta.png')
                self.assertContains(response, 'id="mapa-zonas"')
                zonas = {z['codigo']: z for z in data['zonas']}
                for codigo in ('ROMANA', 'VAPOR', 'SALIDA', 'MUESTREO'):
                    self.assertIsNone(zonas[codigo]['x_pct'])
                    self.assertIsNone(zonas[codigo]['y_pct'])
                self.cita(empresa)
                self.assertEqual(self.camion(empresa)['zona'], 'ROMANA')

    def test_consultas_constantes_con_zonas_fisicas_ambas_empresas(self):
        for empresa in (1, 2):
            with self.subTest(empresa=empresa):
                counts = []
                for i in range(30):
                    tipo = 'DESPACHO' if i % 2 else 'RECEPCION'
                    c = self.cita(empresa, tipo)
                    self.log(c, 'Pesaje Entrada')
                    for paso in ('Toma de muestra', 'Analisis y calidad', 'Resultado Calidad'):
                        self.log(c, paso)
                    if i % 3:
                        self.dato(c, 'OP_CICLO_DESCARGA', {'inicio_descarga': timezone.now().isoformat()})
                    if i in (0, 29):
                        with CaptureQueriesContext(connection) as queries:
                            data = obtener_estado_mapa_operacional(empresa)
                        counts.append(len(queries))
                        self.assertEqual(len(data['camiones']), i + 1)
                        self.assertTrue(all(t['zona'] in ('ZONA_ESPERA', 'ZONA_CARGA_DESCARGA') for t in data['camiones']))
                self.assertEqual(counts, [8, 8])
                self.assertEqual(data['kpis']['carga_descarga'], sum(t['zona'] == 'ZONA_CARGA_DESCARGA' for t in data['camiones']))

    def test_rectangulos_y_slots_centralizados(self):
        zonas = zonas_configuradas()
        for codigo in ('ZONA_ESPERA', 'ZONA_CARGA_DESCARGA'):
            z = zonas[codigo]
            self.assertGreater(z['width_pct'], 0)
            self.assertGreater(z['height_pct'], 0)
            self.assertLessEqual(z['x_pct'] + z['width_pct'], 100)
            self.assertLessEqual(z['y_pct'] + z['height_pct'], 100)
        self.assertEqual(zonas['ZONA_CARGA_DESCARGA']['slots_por_tipo'], 4)
