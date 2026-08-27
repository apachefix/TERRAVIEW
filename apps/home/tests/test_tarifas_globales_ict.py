from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.home.models import (
    CITACION,
    COMUNA,
    EMPRESA,
    PERFIL,
    PERFIL_USUARIO,
    PROFORMA,
    PROVINCIA,
    REGION,
    RUTA,
    SOCIONEGOCIO,
    TARIFA_GLOBAL,
    TARIFA_LOG,
    USERS_EMPRESA,
)
from apps.home.services.ict_ine import (
    ICTAcumuladoResultado,
    ICTComponente,
    ICTConsultaError,
    ICTResultado,
    calcular_acumulado_compuesto,
    extraer_ultimo_ict,
    obtener_acumulativo_ict_6_meses,
)


class ICTINEServiceTests(TestCase):
    def test_extrae_ultimo_comunicado_oficial_y_normaliza_decimal(self):
        contenido = b"""
        <html><body>
          <a href="/sala-de-prensa/prensa/general/noticia/2026/07/10/ict-junio">
            Indice de Costos del Transporte registro una variacion mensual de -3,5% en junio de 2026
          </a>
          <a href="/sala-de-prensa/prensa/general/noticia/2026/08/11/ict-julio">
            Indice de Costos del Transporte registro una variacion mensual de -2,9% en julio de 2026
          </a>
        </body></html>
        """
        resultado = extraer_ultimo_ict(contenido)
        self.assertEqual(resultado.periodo, "Julio 2026")
        self.assertEqual(resultado.variacion, Decimal("-2.9"))
        self.assertEqual(resultado.fecha_publicacion, date(2026, 8, 11))
        self.assertTrue(resultado.url.startswith("https://www.ine.gob.cl/"))

    def test_rechaza_estructura_ambigua_o_sin_dato(self):
        with self.assertRaises(ICTConsultaError):
            extraer_ultimo_ict(b"<html><body>sin indicador verificable</body></html>")

    def test_acumulado_usa_composicion_porcentual_decimal(self):
        variaciones = ('0.2', '-0.5', '2.3', '11.3', '1.5', '-3.5')
        acumulado = calcular_acumulado_compuesto(variaciones)
        self.assertEqual(acumulado, Decimal('11.1872'))
        self.assertNotEqual(acumulado, sum(Decimal(x) for x in variaciones))

    def test_fuente_con_solo_cinco_periodos_no_calcula(self):
        class Respuesta:
            def __init__(self, contenido=b'', datos=None, url='https://calculadoraict.ine.cl/'):
                self.content = contenido
                self._datos = datos
                self.url = url

            def raise_for_status(self):
                return None

            def json(self):
                return self._datos

        class Cliente:
            def get(self, url, **kwargs):
                if 'GetMesesPorAnio' in url:
                    return Respuesta(datos={
                        'tipo': 'OK',
                        'data': [
                            {'valor': mes, 'texto': str(mes)}
                            for mes in range(1, 6)
                        ],
                    })
                return Respuesta(
                    b'<select id="ano_termino"><option value="2026">2026</option></select>'
                )

            def post(self, *args, **kwargs):
                raise AssertionError('No debe calcular con solo cinco períodos')

        with self.assertRaisesMessage(
            ICTConsultaError,
            'No fue posible obtener los 6 períodos ICT necesarios',
        ):
            obtener_acumulativo_ict_6_meses(cliente=Cliente())

class TarifasGlobalesControlFlotaTests(TestCase):
    def setUp(self):
        self.terramar = self._empresa(1, "TERRAMAR CHILE")
        self.sbh = self._empresa(2, "ACEITES SBH")
        self.control = self._usuario("FLOTA_ICT", "CONTROL_FLOTA", "Control Flota")
        self.planificador = self._usuario("PLAN_ICT", "PLANIFICADOR", "Planificador")
        for usuario in (self.control, self.planificador):
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
            USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)

        self.transporte_terramar = self._transporte(self.terramar, "76111111-1")
        self.transporte_sbh = self._transporte(self.sbh, "76222222-2")
        self.ruta_terramar = self._ruta(self.terramar, "RUTA-T")
        self.ruta_sbh = self._ruta(self.sbh, "RUTA-S")
        self.tarifa_terramar = self._tarifa(
            self.terramar, self.transporte_terramar, self.ruta_terramar, "Tarifa Terramar", 1000
        )
        self.tarifa_sbh = self._tarifa(
            self.sbh, self.transporte_sbh, self.ruta_sbh, "Tarifa SBH", 2000
        )
        TARIFA_LOG.objects.create(
            TAR_NID=self.tarifa_terramar,
            US_NID=self.control,
            TL_FFECHAREGISTRO=timezone.now(),
            TL_NVALOR=1000,
        )

    def _empresa(self, pk, nombre):
        return EMPRESA.objects.create(
            pk=pk,
            EP_CRAZONSOCIAL=nombre,
            EP_CRUT=f"7600000{pk}-{pk}",
            EP_CBASEDATOS=f"db{pk}",
            EP_CUSUARIOSBD="user",
            EP_CPORT="5432",
        )

    def _usuario(self, username, codigo, nombre):
        usuario = User.objects.create_user(username=username, password="test")
        perfil = PERFIL.objects.create(
            US_NID=usuario,
            PR_CCODIGO=codigo,
            PR_CNOMBRE=nombre,
            PR_BHABILITADO=True,
        )
        PERFIL_USUARIO.objects.create(
            US_NID=usuario,
            PR_NID=perfil,
            PE_BHABILITADO=True,
        )
        return usuario

    def _transporte(self, empresa, rut):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa,
            SN_CRAZONSOCIAL=f"Transporte {empresa.pk}",
            SN_CRUT=rut,
            SN_CTIPO="S",
            SN_BHABILITADO=True,
        )

    def _ruta(self, empresa, codigo):
        region = REGION.objects.create(RG_CNOMBRE=codigo, RG_CCODIGO=codigo)
        provincia = PROVINCIA.objects.create(
            RG_NID=region,
            PV_CNOMBRE=codigo,
            PV_CCODIGO=codigo,
        )
        comuna = COMUNA.objects.create(
            PV_NID=provincia,
            COM_CNOMBRE=codigo,
            COM_CCODIGO=codigo,
        )
        return RUTA.objects.create(
            EP_NID=empresa,
            RG_NID_INICIO=region,
            PV_NID_INICIO=provincia,
            COM_NID_INICIO=comuna,
            RG_NID_TERMINO=region,
            PV_NID_TERMINO=provincia,
            COM_NID_TERMINO=comuna,
            RUT_NTIEMPOMAXIMOENTREGA=1,
            RUT_NTIEMPOESTADIAPLANTA=1,
            RUT_CNOMBRE=codigo,
            RUT_CCODIGO=codigo,
            RUT_BHABILITADO=True,
        )

    def _tarifa(self, empresa, transporte, ruta, nombre, valor):
        return TARIFA_GLOBAL.objects.create(
            EP_NID=empresa,
            RUT_NID=ruta,
            SN_NID=transporte,
            US_NID=self.control,
            TAR_NVALOR=valor,
            TAR_CNOMBRETARIFA=nombre,
            TAR_CTIPOTARIFA="FLETE",
            TAR_CDIVISA="CLP",
            TAR_BHABILITADO=True,
        )

    def _login_empresa(self, usuario, empresa):
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion["empresa_id"] = empresa.pk
        sesion.save()

    def test_control_flota_crea_y_edita_con_log_en_empresa_activa(self):
        self._login_empresa(self.control, self.terramar)
        datos = {
            "EP_NID": self.sbh.pk,  # El backend debe ignorar esta manipulacion.
            "RUT_NID": self.ruta_terramar.pk,
            "SN_NID": self.transporte_terramar.pk,
            "TAR_NVALOR": "3500",
            "TAR_NVALORPREVIO": "",
            "TAR_CNOMBRETARIFA": "Tarifa creada por Flota",
            "TAR_CTIPOTARIFA": "FLETE",
            "TAR_CDIVISA": "CLP",
            "TAR_FFECHAREGISTRO": "",
            "TAR_FFECHAULTIMAMODIFICACION": "",
            "TAR_BHABILITADO": "on",
        }
        respuesta = self.client.post(reverse("tg_addone"), datos)
        self.assertRedirects(respuesta, reverse("tg_listall"))
        tarifa = TARIFA_GLOBAL.objects.get(TAR_CNOMBRETARIFA="Tarifa creada por Flota")
        self.assertEqual(tarifa.EP_NID, self.terramar)
        self.assertEqual(tarifa.TAR_NVALOR, Decimal("3500"))
        self.assertEqual(TARIFA_LOG.objects.filter(TAR_NID=tarifa).count(), 1)

        datos.update({
            "EP_NID": self.sbh.pk,
            "TAR_NVALOR": "3750",
            "TAR_CNOMBRETARIFA": "Tarifa editada por Flota",
        })
        respuesta = self.client.post(reverse("tg_update", args=[tarifa.pk]), datos)
        self.assertRedirects(respuesta, reverse("tg_listall"))
        tarifa.refresh_from_db()
        self.assertEqual(tarifa.EP_NID, self.terramar)
        self.assertEqual(tarifa.TAR_NVALORPREVIO, Decimal("3500"))
        self.assertEqual(tarifa.TAR_NVALOR, Decimal("3750"))
        self.assertEqual(tarifa.MODIFICADO_POR, self.control)
        self.assertEqual(TARIFA_LOG.objects.filter(TAR_NID=tarifa).count(), 2)

        datos_cruzados = datos.copy()
        datos_cruzados.update({
            "RUT_NID": self.ruta_sbh.pk,
            "SN_NID": self.transporte_sbh.pk,
        })
        respuesta = self.client.post(reverse("tg_update", args=[tarifa.pk]), datos_cruzados)
        self.assertEqual(respuesta.status_code, 200)
        tarifa.refresh_from_db()
        self.assertEqual(tarifa.RUT_NID, self.ruta_terramar)
        self.assertEqual(tarifa.SN_NID, self.transporte_terramar)

    def test_control_flota_ve_panel_acciones_e_historico_sin_users_extension(self):
        self._login_empresa(self.control, self.terramar)
        respuesta = self.client.get(reverse("tg_listall"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Reajuste ICT")
        self.assertContains(respuesta, "Consultar acumulativo ICT 6 meses")
        self.assertContains(respuesta, reverse("tg_update", args=[self.tarifa_terramar.pk]))
        self.assertContains(respuesta, reverse("tg_delete", args=[self.tarifa_terramar.pk]))
        self.assertContains(respuesta, reverse("tg_listone", args=[self.tarifa_terramar.pk]))
        self.assertNotContains(respuesta, "Agregar masivo")
        self.assertNotContains(respuesta, "Tarifa SBH")

        detalle = self.client.get(reverse("tg_listone", args=[self.tarifa_terramar.pk]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, "Histórico registrado")
        self.assertContains(detalle, "1.000")

    def test_planificador_no_recibe_acceso_ni_panel_ict(self):
        self._login_empresa(self.planificador, self.terramar)
        self.assertRedirects(self.client.get(reverse("tg_listall")), "/")
        respuesta = self.client.post(reverse("tg_consultar_ict"))
        self.assertEqual(respuesta.status_code, 403)

    def test_deshabilitar_rehabilitar_y_pk_cruzado_respetan_empresa(self):
        self._login_empresa(self.control, self.terramar)
        respuesta = self.client.get(reverse("tg_delete", args=[self.tarifa_terramar.pk]))
        self.assertRedirects(respuesta, reverse("tg_listall"))
        self.tarifa_terramar.refresh_from_db()
        self.assertFalse(self.tarifa_terramar.TAR_BHABILITADO)

        respuesta = self.client.get(reverse("tg_habilitar", args=[self.tarifa_terramar.pk]))
        self.assertRedirects(respuesta, reverse("tg_listall_inhabilitado"))
        self.tarifa_terramar.refresh_from_db()
        self.assertTrue(self.tarifa_terramar.TAR_BHABILITADO)

        self.assertEqual(
            self.client.get(reverse("tg_update", args=[self.tarifa_sbh.pk])).status_code,
            404,
        )
        self.tarifa_sbh.refresh_from_db()
        self.assertEqual(self.tarifa_sbh.TAR_NVALOR, Decimal("2000"))

    @patch("apps.home.tarifa_global_views.obtener_acumulativo_ict_6_meses")
    def test_consulta_ict_valida_no_modifica_datos(self, consulta):
        componentes = tuple(
            ICTComponente(
                periodo_fecha=date(2026, mes, 1),
                periodo=f'Mes {mes} 2026',
                variacion=Decimal(valor),
            )
            for mes, valor in enumerate(
                ('0.2', '-0.5', '2.3', '11.3', '1.5', '-3.5'), start=2
            )
        )
        consulta.return_value = ICTAcumuladoResultado(
            componentes=componentes,
            acumulado=Decimal('11.1872'),
            fecha_publicacion=date(2026, 8, 11),
            fuente='INE',
            url='https://calculadoraict.ine.cl/',
            url_publicacion='https://www.ine.gob.cl/noticia/ict-julio',
        )
        self._login_empresa(self.control, self.terramar)
        tarifa_antes = list(TARIFA_GLOBAL.objects.values_list('pk', 'TAR_NVALOR'))
        logs_antes = TARIFA_LOG.objects.count()
        citaciones_antes = CITACION.objects.count()
        proformas_antes = PROFORMA.objects.count()

        respuesta = self.client.post(reverse('tg_consultar_ict'))
        self.assertEqual(respuesta.status_code, 200)
        ict = respuesta.json()['ict']
        self.assertEqual(ict['acumulado'], '11.1872')
        self.assertEqual(len(ict['componentes']), 6)
        self.assertEqual(
            list(TARIFA_GLOBAL.objects.values_list('pk', 'TAR_NVALOR')),
            tarifa_antes,
        )
        self.assertEqual(TARIFA_LOG.objects.count(), logs_antes)
        self.assertEqual(CITACION.objects.count(), citaciones_antes)
        self.assertEqual(PROFORMA.objects.count(), proformas_antes)
    @patch("apps.home.tarifa_global_views.obtener_acumulativo_ict_6_meses")
    def test_error_ine_entrega_mensaje_claro_y_no_modifica_tarifas(self, consulta):
        consulta.side_effect = ICTConsultaError("estructura invalida")
        self._login_empresa(self.control, self.sbh)
        valores = list(TARIFA_GLOBAL.objects.values_list("pk", "TAR_NVALOR"))
        respuesta = self.client.post(reverse("tg_consultar_ict"))
        self.assertEqual(respuesta.status_code, 502)
        self.assertFalse(respuesta.json()["valid"])
        self.assertIn("6 períodos ICT", respuesta.json()["msg"])
        self.assertEqual(list(TARIFA_GLOBAL.objects.values_list("pk", "TAR_NVALOR")), valores)
