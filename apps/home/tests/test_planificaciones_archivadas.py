import json
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.template.loader import get_template
from django.utils import timezone

from apps.home.models import CALENDARIO, CAMION_PATIO, CAMION_PATIO_NO_PLANIFICADO, CITACION, CITACION_DESPACHO_DETALLE, DATO_OPERACION, EMPRESA, PLANIFICACION, SECUENCIA, SOCIONEGOCIO, USERS_EMPRESA, USERS_EXTENSION
from apps.home.services.planificacion_historica import construir_resumen_planificacion, construir_resumenes_planificaciones_archivadas
from apps.home.views import _citaciones_disponibles_para_patio


class ResumenPlanificacionArchivadaTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user('archivo-test')
        USERS_EXTENSION.objects.create(US_NID=self.usuario, UX_IS_PLANIFICADOR=True)
        self.empresa = EMPRESA.objects.create(EP_CRAZONSOCIAL='Empresa prueba', EP_CRUT='1-9', EP_CBASEDATOS='TEST', EP_CUSUARIOSBD='test', EP_CPORT='0')
        USERS_EMPRESA.objects.create(US_NID=self.usuario, EP_NID=self.empresa)
        self.calendario = CALENDARIO.objects.create(US_NID=self.usuario, EP_NID=self.empresa, CA_CNOMBRE='Calendario', CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18), CA_NDIA=1, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=20)
        self.secuencia = SECUENCIA.objects.create(US_NID=self.usuario, EP_NID=self.empresa, SE_CTIPO='RECEPCION', SE_CCODIGO='REC', SE_CNOMBRE='Recepción', SE_BHABILITADO=True)
        self.planificacion = PLANIFICACION.objects.create(US_NID=self.usuario, EP_NID=self.empresa, CAL_NID=self.calendario, PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=10, PL_BARCHIVADO=True)
        self.ewos = SOCIONEGOCIO.objects.create(EP_NID=self.empresa, SN_CCODIGO_SAP='EWOS', SN_CRAZONSOCIAL='EWOS CHILE ALIMENTOS LTDA', SN_CRUT='2-7', SN_CTIPO='C', SN_BHABILITADO=True)

    def crear_citacion(self, numero, cliente=None, estado='PENDIENTE', sobrecupo=False):
        return CITACION.objects.create(US_NID=self.usuario, EP_NID=self.empresa, PL_NID=self.planificacion, SN_NID=cliente, SC_NID=self.secuencia, CI_FFECHACITACION=timezone.now(), CI_NCUPO=numero, CI_CTIPO='RECEPCION', CI_CESTADO=estado, CI_BSOBRECUPO=sobrecupo)

    def asociar(self, citacion):
        return CAMION_PATIO.objects.create(EP_NID=self.empresa, CI_NID=citacion, CPA_CPATENTE='AA-BB-01', CPA_CNOMBRE_CONDUCTOR='Conductor', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION, US_GUARDIA_ID=self.usuario)

    def crear_camion_pendiente(self):
        return CAMION_PATIO.objects.create(EP_NID=self.empresa, CPA_CPATENTE='PT-IO-01', CPA_CNOMBRE_CONDUCTOR='Pendiente', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION, US_GUARDIA_ID=self.usuario)

    def ids_candidatas(self, camion):
        return [item['id'] for item in self.candidatas(camion)]

    def candidatas(self, camion):
        with patch(
            'apps.home.views.obtener_etapa_actual_operacional_citacion',
            return_value='Insumo Programado',
        ):
            return _citaciones_disponibles_para_patio(camion)

    def test_ewos_diez_citaciones_nueve_camiones(self):
        citaciones = [self.crear_citacion(numero, self.ewos) for numero in range(1, 11)]
        for citacion in citaciones[:9]: self.asociar(citacion)
        resumen = construir_resumen_planificacion(self.planificacion)
        cliente = resumen['client_summaries'][0]
        self.assertEqual(cliente['citaciones_creadas'], 10)
        self.assertEqual(cliente['camiones_asociados'], 9)
        self.assertEqual(cliente['citaciones_sin_camion'], 1)
        self.assertEqual(cliente['porcentaje_llegada'], 90)

    def test_camion_maestro_no_es_llegada(self):
        self.crear_citacion(1, self.ewos)
        resumen = construir_resumen_planificacion(self.planificacion)
        self.assertEqual(resumen['summary']['camiones_asociados'], 0)
        self.assertEqual(resumen['summary']['citaciones_sin_camion'], 1)

    def test_sobrecupos_no_consumen_cupos_normales(self):
        for numero in range(1, 10): self.crear_citacion(numero, self.ewos)
        for numero in range(10, 12): self.crear_citacion(numero, self.ewos, sobrecupo=True)
        resumen = construir_resumen_planificacion(self.planificacion)
        self.assertEqual(resumen['summary']['cupos_no_utilizados'], 1)

    def test_terminada_y_abierta_son_categorias_exclusivas(self):
        cerrada = self.crear_citacion(1, self.ewos, estado='TERMINADO')
        abierta = self.crear_citacion(2, self.ewos)
        self.asociar(cerrada); self.asociar(abierta)
        resumen = construir_resumen_planificacion(self.planificacion)['summary']
        self.assertEqual(resumen['citaciones_creadas'], resumen['citaciones_cerradas'] + resumen['citaciones_abiertas_con_camion'] + resumen['citaciones_sin_camion'])

    def test_endpoint_masivo_archiva_y_no_modifica_citacion(self):
        self.planificacion.PL_BARCHIVADO = False
        self.planificacion.save(update_fields=['PL_BARCHIVADO'])
        citacion = self.crear_citacion(1, self.ewos)
        self.client.force_login(self.usuario); session=self.client.session; session['empresa_id']=self.empresa.id; session.save()
        respuesta=self.client.post(reverse('ajax_archivar_planificaciones'), {'planificaciones': '[%s]' % self.planificacion.id})
        self.assertTrue(respuesta.json()['success']); self.planificacion.refresh_from_db(); citacion.refresh_from_db()
        self.assertTrue(self.planificacion.PL_BARCHIVADO); self.assertEqual(self.planificacion.US_ARCHIVADOR_ID, self.usuario); self.assertIsNotNone(self.planificacion.PL_FFECHAARCHIVADO); self.assertFalse(citacion.CI_BARCHIVADO)

    def test_endpoint_masivo_rechaza_get_y_lista_vacia(self):
        self.client.force_login(self.usuario); session=self.client.session; session['empresa_id']=self.empresa.id; session.save()
        self.assertEqual(self.client.get(reverse('ajax_archivar_planificaciones')).status_code, 405)
        self.assertEqual(self.client.post(reverse('ajax_archivar_planificaciones'), {'planificaciones': '[]'}).status_code, 400)

    def test_no_planificado_no_aumenta_porcentaje(self):
        citacion=self.crear_citacion(1, self.ewos); self.asociar(citacion)
        camion=CAMION_PATIO.objects.create(EP_NID=self.empresa, CPA_CPATENTE='CC-DD-02', CPA_CNOMBRE_CONDUCTOR='Otro', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION, US_GUARDIA_ID=self.usuario)
        CAMION_PATIO_NO_PLANIFICADO.objects.create(CPA_NID=camion, EP_NID=self.empresa, PL_NID=self.planificacion, CI_NID=citacion, CPNP_CESTADO=CAMION_PATIO_NO_PLANIFICADO.ESTADO_APROBADO, US_SOLICITA_ID=self.usuario)
        cliente=construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertEqual(cliente['porcentaje_llegada'], 100); self.assertEqual(cliente['camiones_no_planificados'], 1)
    def autenticar(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def crear_planificacion(self, archivada=True, empresa=None, calendario=None, usuario=None):
        empresa = empresa or self.empresa
        usuario = usuario or self.usuario
        calendario = calendario or self.calendario
        return PLANIFICACION.objects.create(US_NID=usuario, EP_NID=empresa, CAL_NID=calendario, PL_CTIPOCUPO='RECEPCION', PL_FFECHAINICIO=timezone.now(), PL_NCANTIDADCUPOS=10, PL_BARCHIVADO=archivada, US_ARCHIVADOR_ID=usuario if archivada else None, PL_FFECHAARCHIVADO=timezone.localdate() if archivada else None)

    def crear_empresa_secundaria(self):
        empresa = EMPRESA.objects.create(EP_CRAZONSOCIAL='Empresa ajena', EP_CRUT='9-9', EP_CBASEDATOS='OTRA', EP_CUSUARIOSBD='otra', EP_CPORT='0')
        calendario = CALENDARIO.objects.create(US_NID=self.usuario, EP_NID=empresa, CA_CNOMBRE='Calendario ajeno', CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18), CA_NDIA=2, CA_NMES=1, CA_NANO=2026, CA_NCANTIDADCUPOS=20)
        return empresa, calendario

    def test_archivado_individual_solo_post_y_sin_toggle(self):
        self.autenticar()
        self.planificacion.PL_BARCHIVADO = False
        self.planificacion.US_ARCHIVADOR_ID = None
        self.planificacion.PL_FFECHAARCHIVADO = None
        self.planificacion.save(update_fields=['PL_BARCHIVADO', 'US_ARCHIVADOR_ID', 'PL_FFECHAARCHIVADO'])
        citacion = self.crear_citacion(1, self.ewos)
        url = reverse('pla_filedone', args=[self.planificacion.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.planificacion.refresh_from_db()
        self.assertFalse(self.planificacion.PL_BARCHIVADO)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.planificacion.refresh_from_db(); citacion.refresh_from_db()
        self.assertTrue(self.planificacion.PL_BARCHIVADO)
        self.assertEqual(self.planificacion.US_ARCHIVADOR_ID, self.usuario)
        self.assertEqual(self.planificacion.PL_FFECHAARCHIVADO, timezone.localdate())
        self.assertFalse(citacion.CI_BARCHIVADO)
        self.client.post(url)
        self.planificacion.refresh_from_db()
        self.assertTrue(self.planificacion.PL_BARCHIVADO)

    def test_archivado_individual_y_masivo_aislan_empresa(self):
        self.autenticar()
        empresa_2, calendario_2 = self.crear_empresa_secundaria()
        ajena = self.crear_planificacion(False, empresa_2, calendario_2)
        propia = self.crear_planificacion(False)
        self.client.post(reverse('pla_filedone', args=[ajena.id]))
        ajena.refresh_from_db(); self.assertFalse(ajena.PL_BARCHIVADO)
        respuesta = self.client.post(reverse('ajax_archivar_planificaciones'), {'planificaciones': '[%s,%s]' % (propia.id, ajena.id)}).json()
        propia.refresh_from_db(); ajena.refresh_from_db()
        self.assertTrue(propia.PL_BARCHIVADO); self.assertFalse(ajena.PL_BARCHIVADO)
        self.assertEqual(respuesta['ids_archivados'], [propia.id])
        self.assertEqual(respuesta['cantidad_archivada'], 1)

    def test_listado_archivado_filtra_empresa_y_es_solo_lectura(self):
        self.autenticar()
        activa = self.crear_planificacion(False)
        empresa_2, calendario_2 = self.crear_empresa_secundaria()
        ajena = self.crear_planificacion(True, empresa_2, calendario_2)
        respuesta = self.client.get(reverse('pla_filedlistall'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'home/PLANIFICACION/pla_archived_list.html')
        contenido = get_template('home/PLANIFICACION/pla_archived_list.html').template.source
        self.assertContains(respuesta, 'Ver resumen histórico')
        self.assertContains(respuesta, reverse('pla_archivada_resumen', args=[self.planificacion.id]))
        self.assertNotContains(respuesta, reverse('pla_archivada_resumen', args=[activa.id]))
        self.assertNotContains(respuesta, reverse('pla_archivada_resumen', args=[ajena.id]))
        for texto in ['Asociar camión', 'enviar-sap', 'Avanzar etapa', '<form']:
            self.assertNotIn(texto, contenido)

    def test_listado_archivado_estado_vacio(self):
        self.autenticar()
        PLANIFICACION.objects.filter(EP_NID=self.empresa).update(PL_BARCHIVADO=False)
        respuesta = self.client.get(reverse('pla_filedlistall'))
        self.assertContains(respuesta, 'No hay planificaciones archivadas.')

    def test_detalle_historico_autorizado_y_solo_lectura(self):
        self.autenticar()
        cerrada = self.crear_citacion(1, self.ewos, 'TERMINADO')
        abierta = self.crear_citacion(2, self.ewos)
        pendiente = self.crear_citacion(3, None)
        self.asociar(cerrada); self.asociar(abierta)
        url = reverse('pla_archivada_resumen', args=[self.planificacion.id])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'home/PLANIFICACION/pla_archived_detail.html')
        for texto in ['Resultado por cliente', 'Citaciones cerradas', 'Citaciones abiertas con camión', 'Sin camión asociado', 'Cliente no identificado', str(pendiente.id)]:
            self.assertContains(respuesta, texto)
        contenido = get_template('home/PLANIFICACION/pla_archived_detail.html').template.source
        for texto in ['method="post"', 'Asociar camión', 'enviar-sap', 'Avanzar etapa', 'Editar']:
            self.assertNotIn(texto, contenido)
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_detalle_historico_rechaza_activa_ajena_y_empresa_get(self):
        self.autenticar()
        activa = self.crear_planificacion(False)
        empresa_2, calendario_2 = self.crear_empresa_secundaria()
        ajena = self.crear_planificacion(True, empresa_2, calendario_2)
        self.assertEqual(self.client.get(reverse('pla_archivada_resumen', args=[activa.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('pla_archivada_resumen', args=[ajena.id])).status_code, 404)
        respuesta = self.client.get(reverse('pla_archivada_resumen', args=[ajena.id]), {'_empresa_id': empresa_2.id})
        self.assertNotEqual(respuesta.status_code, 200)

    def test_clientes_y_totales_coinciden_sin_duplicar_camiones(self):
        bunge = SOCIONEGOCIO.objects.create(EP_NID=self.empresa, SN_CCODIGO_SAP='BUNGE', SN_CRAZONSOCIAL='BUNGE', SN_CRUT='3-5', SN_CTIPO='C', SN_BHABILITADO=True)
        c1 = self.crear_citacion(1, self.ewos); c2 = self.crear_citacion(2, self.ewos); c3 = self.crear_citacion(3, bunge); self.crear_citacion(4, None)
        self.asociar(c1); self.asociar(c2); self.asociar(c3)
        CAMION_PATIO.objects.create(EP_NID=self.empresa, CI_NID=c1, CPA_CPATENTE='ZZ-ZZ-99', CPA_CNOMBRE_CONDUCTOR='Duplicado', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION, US_GUARDIA_ID=self.usuario)
        resultado = construir_resumen_planificacion(self.planificacion)
        grupos = resultado['client_summaries']; general = resultado['summary']
        self.assertEqual(len(grupos), 3)
        self.assertEqual(general['citaciones_creadas'], sum(g['citaciones_creadas'] for g in grupos))
        self.assertEqual(general['camiones_asociados'], sum(g['camiones_asociados'] for g in grupos))
        self.assertEqual(general['citaciones_sin_camion'], sum(g['citaciones_sin_camion'] for g in grupos))
        for grupo in grupos:
            self.assertEqual(grupo['citaciones_creadas'], grupo['citaciones_cerradas'] + grupo['citaciones_abiertas_con_camion'] + grupo['citaciones_sin_camion'])
            self.assertLessEqual(grupo['porcentaje_llegada'], 100)

    def test_camion_y_no_planificado_de_otra_empresa_no_se_incluyen(self):
        citacion = self.crear_citacion(1, self.ewos)
        empresa_2, _ = self.crear_empresa_secundaria()
        CAMION_PATIO.objects.create(EP_NID=empresa_2, CI_NID=citacion, CPA_CPATENTE='OT-RA-01', CPA_CNOMBRE_CONDUCTOR='Ajeno', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION, US_GUARDIA_ID=self.usuario)
        camion = CAMION_PATIO.objects.create(EP_NID=empresa_2, CPA_CPATENTE='OT-RA-02', CPA_CNOMBRE_CONDUCTOR='Ajeno', CPA_CTIPO_DOCUMENTO='GD', CPA_CESTADO=CAMION_PATIO.ESTADO_PENDIENTE_ASOCIACION, US_GUARDIA_ID=self.usuario)
        CAMION_PATIO_NO_PLANIFICADO.objects.create(CPA_NID=camion, EP_NID=empresa_2, PL_NID=self.planificacion, CPNP_CESTADO=CAMION_PATIO_NO_PLANIFICADO.ESTADO_APROBADO, US_SOLICITA_ID=self.usuario)
        resumen = construir_resumen_planificacion(self.planificacion)['summary']
        self.assertEqual(resumen['camiones_asociados'], 0)
        self.assertEqual(resumen['camiones_no_planificados'], 0)

    def test_resumen_lote_consultas_constantes_para_una_y_cinco(self):
        una = PLANIFICACION.objects.filter(pk=self.planificacion.pk)
        with CaptureQueriesContext(connection) as consultas_una:
            construir_resumenes_planificaciones_archivadas(una, self.empresa.id)
        adicionales = [self.crear_planificacion(True) for _ in range(4)]
        cinco = PLANIFICACION.objects.filter(pk__in=[self.planificacion.id] + [p.id for p in adicionales])
        with CaptureQueriesContext(connection) as consultas_cinco:
            construir_resumenes_planificaciones_archivadas(cinco, self.empresa.id)
        self.assertEqual((len(consultas_una), len(consultas_cinco)), (3, 3))
    def test_mismo_cardcode_en_otra_empresa_no_se_agrupa(self):
        self.crear_citacion(1, self.ewos)
        empresa_2, calendario_2 = self.crear_empresa_secundaria()
        secuencia_2 = SECUENCIA.objects.create(US_NID=self.usuario, EP_NID=empresa_2, SE_CTIPO='RECEPCION', SE_CCODIGO='REC2', SE_CNOMBRE='Recepción 2', SE_BHABILITADO=True)
        planificacion_2 = self.crear_planificacion(True, empresa_2, calendario_2)
        ewos_2 = SOCIONEGOCIO.objects.create(EP_NID=empresa_2, SN_CCODIGO_SAP='EWOS', SN_CRAZONSOCIAL='EWOS OTRA EMPRESA', SN_CRUT='8-8', SN_CTIPO='C', SN_BHABILITADO=True)
        CITACION.objects.create(US_NID=self.usuario, EP_NID=empresa_2, PL_NID=planificacion_2, SN_NID=ewos_2, SC_NID=secuencia_2, CI_FFECHACITACION=timezone.now(), CI_NCUPO=1, CI_CTIPO='RECEPCION', CI_CESTADO='PENDIENTE')
        grupos = construir_resumen_planificacion(self.planificacion)['client_summaries']
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]['id'], self.ewos.id)
        self.assertEqual(grupos[0]['citaciones_creadas'], 1)
    def test_cliente_directo_sn_nid_tiene_prioridad(self):
        citacion = self.crear_citacion(1, self.ewos)
        citacion.CI_CCOMENTARIO = json.dumps({'cliente_codigo': 'INEXISTENTE'})
        citacion.save(update_fields=['CI_CCOMENTARIO'])
        cliente = construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertEqual(cliente['id'], self.ewos.id)
        self.assertEqual(cliente['codigo'], 'EWOS')
        self.assertEqual(cliente['nombre'], 'EWOS CHILE ALIMENTOS LTDA')

    def test_sn_null_payload_etapa_cero_planificacion_resuelve_cliente(self):
        citacion = self.crear_citacion(1)
        citacion.CI_CCOMENTARIO = json.dumps({'cliente_codigo': 'EWOS'})
        citacion.save(update_fields=['CI_CCOMENTARIO'])
        cliente = construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertEqual(cliente['id'], self.ewos.id)
        self.assertEqual(cliente['nombre'], 'EWOS CHILE ALIMENTOS LTDA')

    def test_sn_null_cardcode_detalle_despacho_resuelve_misma_empresa(self):
        citacion = self.crear_citacion(1)
        CITACION_DESPACHO_DETALLE.objects.create(
            CI_NID=citacion,
            EP_NID=self.empresa,
            CDD_CSAP_CLIENTE_CODIGO='EWOS',
            CDD_CSAP_CLIENTE_NOMBRE='Nombre informativo no usado',
        )
        cliente = construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertEqual(cliente['id'], self.ewos.id)
        self.assertEqual(cliente['codigo'], 'EWOS')

    def test_cardcode_historico_no_resuelve_socio_de_otra_empresa(self):
        empresa_2, _ = self.crear_empresa_secundaria()
        SOCIONEGOCIO.objects.create(
            EP_NID=empresa_2,
            SN_CCODIGO_SAP='SOLO-OTRA',
            SN_CRAZONSOCIAL='Cliente de otra empresa',
            SN_CRUT='7-1',
            SN_CTIPO='C',
            SN_BHABILITADO=True,
        )
        citacion = self.crear_citacion(1)
        CITACION_DESPACHO_DETALLE.objects.create(
            CI_NID=citacion,
            EP_NID=self.empresa,
            CDD_CSAP_CLIENTE_CODIGO='SOLO-OTRA',
        )
        cliente = construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertIsNone(cliente['id'])
        self.assertEqual(cliente['nombre'], 'Cliente no identificado')

    def test_sin_fuente_estructurada_permanece_no_identificado(self):
        self.crear_citacion(1)
        cliente = construir_resumen_planificacion(self.planificacion)['client_summaries'][0]
        self.assertIsNone(cliente['id'])
        self.assertEqual(cliente['codigo'], '')
        self.assertEqual(cliente['nombre'], 'Cliente no identificado')

    def test_resolucion_historica_no_escribe_en_base_de_datos(self):
        citacion = self.crear_citacion(1)
        citacion.CI_CCOMENTARIO = json.dumps({'cliente_codigo': 'EWOS'})
        citacion.save(update_fields=['CI_CCOMENTARIO'])
        conteos_antes = (
            CITACION.objects.count(),
            SOCIONEGOCIO.objects.count(),
            CITACION_DESPACHO_DETALLE.objects.count(),
            DATO_OPERACION.objects.count(),
        )
        construir_resumen_planificacion(self.planificacion)
        citacion.refresh_from_db()
        conteos_despues = (
            CITACION.objects.count(),
            SOCIONEGOCIO.objects.count(),
            CITACION_DESPACHO_DETALLE.objects.count(),
            DATO_OPERACION.objects.count(),
        )
        self.assertIsNone(citacion.SN_NID_id)
        self.assertEqual(conteos_antes, conteos_despues)

    def test_listado_renderiza_columna_acciones_sticky(self):
        contenido = get_template('home/PLANIFICACION/pla_archived_list.html').template.source
        self.assertIn('class="sticky-actions">Acciones</th>', contenido)
        self.assertIn('class="action-cell sticky-actions"', contenido)
        self.assertIn('.archived-plans-table .sticky-actions', contenido)

    def test_listado_renderiza_barra_superior_sincronizada(self):
        contenido = get_template('home/PLANIFICACION/pla_archived_list.html').template.source
        self.assertIn('id="archived-table-scroll-top"', contenido)
        self.assertIn('id="archived-table-scroll-top-content"', contenido)
        self.assertIn('id="archived-table-scroll-main"', contenido)
        self.assertIn('mainScroll.scrollWidth > mainScroll.clientWidth + 1', contenido)
        self.assertIn('synchronize(topScroll, mainScroll)', contenido)
        self.assertIn('synchronize(mainScroll, topScroll)', contenido)

    def crear_citacion_planificacion(self, planificacion, numero, estado='PENDIENTE', empresa=None, secuencia=None):
        return CITACION.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa or planificacion.EP_NID,
            PL_NID=planificacion,
            SC_NID=secuencia or self.secuencia,
            CI_FFECHACITACION=timezone.now(),
            CI_NCUPO=numero,
            CI_CTIPO='RECEPCION',
            CI_CESTADO=estado,
        )

    def test_modal_incluye_activa_y_excluye_archivada(self):
        camion = self.crear_camion_pendiente()
        activa = self.crear_planificacion(False)
        candidata_activa = self.crear_citacion_planificacion(activa, 1)
        candidata_archivada = self.crear_citacion(2, self.ewos)

        ids = self.ids_candidatas(camion)

        self.assertIn(candidata_activa.id, ids)
        self.assertNotIn(candidata_archivada.id, ids)

    def test_archivar_retira_del_modal_sin_tocar_citacion_y_conserva_historico(self):
        self.autenticar()
        camion = self.crear_camion_pendiente()
        activa = self.crear_planificacion(False)
        citacion = self.crear_citacion_planificacion(activa, 1)
        self.assertIn(citacion.id, self.ids_candidatas(camion))

        respuesta = self.client.post(
            reverse('ajax_archivar_planificaciones'),
            {'planificaciones': '[%s]' % activa.id},
        )

        self.assertTrue(respuesta.json()['success'])
        citacion.refresh_from_db()
        self.assertFalse(citacion.CI_BARCHIVADO)
        self.assertNotIn(citacion.id, self.ids_candidatas(camion))
        self.assertEqual(
            construir_resumen_planificacion(activa)['summary']['citaciones_creadas'],
            1,
        )

    def test_modal_excluye_archivada_de_otra_empresa(self):
        camion = self.crear_camion_pendiente()
        empresa_2, calendario_2 = self.crear_empresa_secundaria()
        secuencia_2 = SECUENCIA.objects.create(
            US_NID=self.usuario,
            EP_NID=empresa_2,
            SE_CTIPO='RECEPCION',
            SE_CCODIGO='REC-AJENA',
            SE_CNOMBRE='Recepción ajena',
            SE_BHABILITADO=True,
        )
        archivada_ajena = self.crear_planificacion(True, empresa_2, calendario_2)
        citacion_ajena = self.crear_citacion_planificacion(
            archivada_ajena, 1, empresa=empresa_2, secuencia=secuencia_2,
        )

        self.assertNotIn(citacion_ajena.id, self.ids_candidatas(camion))

    def test_modal_excluye_citacion_ya_asociada(self):
        camion = self.crear_camion_pendiente()
        activa = self.crear_planificacion(False)
        citacion = self.crear_citacion_planificacion(activa, 1)
        self.asociar(citacion)

        self.assertNotIn(citacion.id, self.ids_candidatas(camion))

    def test_modal_conserva_score_de_horario_cercano(self):
        camion = self.crear_camion_pendiente()
        activa = self.crear_planificacion(False)
        citacion = self.crear_citacion_planificacion(activa, 1)

        candidata = next(
            item for item in self.candidatas(camion)
            if item['id'] == citacion.id
        )

        self.assertEqual(candidata['score'], 10)
        self.assertEqual(candidata['razones'], ['Horario cercano'])

    def test_modal_devuelve_exactamente_cuatro_candidatas_activas(self):
        camion = self.crear_camion_pendiente()
        activa = self.crear_planificacion(False)
        citaciones = [
            self.crear_citacion_planificacion(activa, numero)
            for numero in range(1, 5)
        ]

        self.assertEqual(
            set(self.ids_candidatas(camion)),
            {citacion.id for citacion in citaciones},
        )

    def test_terminada_asociada_no_se_clasifica_como_abierta(self):
        terminada = self.crear_citacion(1, self.ewos, estado='TERMINADO')
        self.asociar(terminada)

        resumen = construir_resumen_planificacion(self.planificacion)['summary']

        self.assertEqual(resumen['citaciones_cerradas'], 1)
        self.assertEqual(resumen['citaciones_abiertas_con_camion'], 0)

    def test_no_terminada_asociada_se_clasifica_como_abierta(self):
        abierta = self.crear_citacion(1, self.ewos)
        self.asociar(abierta)

        resumen = construir_resumen_planificacion(self.planificacion)['summary']

        self.assertEqual(resumen['citaciones_cerradas'], 0)
        self.assertEqual(resumen['citaciones_abiertas_con_camion'], 1)

    def test_varios_camiones_no_duplican_citacion_abierta(self):
        abierta = self.crear_citacion(1, self.ewos)
        self.asociar(abierta)
        CAMION_PATIO.objects.create(
            EP_NID=self.empresa,
            CI_NID=abierta,
            CPA_CPATENTE='DU-PL-02',
            CPA_CNOMBRE_CONDUCTOR='Duplicado',
            CPA_CTIPO_DOCUMENTO='GD',
            CPA_CESTADO=CAMION_PATIO.ESTADO_ASOCIADO_CITACION,
            US_GUARDIA_ID=self.usuario,
        )

        resumen = construir_resumen_planificacion(self.planificacion)['summary']

        self.assertEqual(resumen['citaciones_creadas'], 1)
        self.assertEqual(resumen['citaciones_abiertas_con_camion'], 1)

    def test_listado_archivado_ordena_por_fecha_descendente(self):
        self.autenticar()
        anterior = self.crear_planificacion(True)
        reciente = self.crear_planificacion(True)
        PLANIFICACION.objects.filter(pk=anterior.pk).update(
            PL_FFECHAINICIO=timezone.now() - timedelta(days=2),
        )
        PLANIFICACION.objects.filter(pk=reciente.pk).update(
            PL_FFECHAINICIO=timezone.now() + timedelta(days=2),
        )

        respuesta = self.client.get(reverse('pla_filedlistall'))
        ids = [item['planificacion'].id for item in respuesta.context['resumenes']]

        self.assertLess(ids.index(reciente.id), ids.index(anterior.id))