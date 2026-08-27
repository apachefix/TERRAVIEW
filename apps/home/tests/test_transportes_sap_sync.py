from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.home import sap_di_api
from apps.home.models import EMPRESA, SOCIONEGOCIO, USERS_EMPRESA
from apps.home.services import transportes_sap


class TransporteSapQueryTests(SimpleTestCase):
    @patch('apps.home.sap_di_api._rows', return_value=[])
    def test_consulta_ocrd_aplica_regla_completa_y_schema_validado(self, rows_mock):
        sap_di_api.consultar_transportistas_sap('SBO_SBH_USD')

        sql = rows_mock.call_args.args[0]
        self.assertIn('FROM "SBO_SBH_USD"."OCRD"', sql)
        self.assertIn('"CardType" = \'S\'', sql)
        self.assertIn('"U_Transporte" = \'Si\'', sql)
        self.assertIn('"validFor" = \'Y\'', sql)
        self.assertIn('"frozenFor" = \'N\'', sql)

    def test_watcher_no_ejecuta_main_al_importarse(self):
        source = Path('apps/home/watcher_ocrd_sn.py').read_text(encoding='utf-8')
        self.assertIn("if __name__ == '__main__':", source)
        self.assertNotIn('\nmain()\n', source)


class TransportesSapSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.terramar = EMPRESA.objects.create(
            id=1, EP_CRAZONSOCIAL='TERRAMAR CHILE', EP_CRUT='1-9',
            EP_CBASEDATOS='legacy_terramar', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )
        cls.sbh = EMPRESA.objects.create(
            id=2, EP_CRAZONSOCIAL='ACEITES SBH', EP_CRUT='2-9',
            EP_CBASEDATOS='legacy_sbh', EP_CUSUARIOSBD='test', EP_CPORT='5432',
        )

    @staticmethod
    def fila_sap(**cambios):
        fila = {
            'CardCode': 'P77665886',
            'CardName': 'Transportes Prueba Limitada',
            'LicTradNum': '77665886-1',
            'Address': 'Ruta 5 100',
            'CardFName': 'Contacto SAP',
            'Phone1': '+56 9 1234 5678',
            'E_Mail': 'transporte@example.test',
            'CardType': 'S',
            'EsTransporte': 'Si',
            'validFor': 'Y',
            'frozenFor': 'N',
        }
        fila.update(cambios)
        return fila

    def sincronizar(self, filas_por_empresa, *, empresas=(1, 2), dry_run=False):
        schemas = {1: 'TESTTERRACHILE', 2: 'SBO_TST_SBH_USD'}
        with patch(
            'apps.home.services.transportes_sap.get_sap_company_db',
            side_effect=lambda empresa_id: schemas[empresa_id],
        ), patch(
            'apps.home.services.transportes_sap.consultar_transportistas_sap',
            side_effect=lambda schema: filas_por_empresa.get(schema, []),
        ):
            return transportes_sap.sincronizar_transportes_sap(
                empresas=empresas,
                dry_run=dry_run,
            )

    def test_terramar_y_sbh_crean_transportes_en_su_empresa(self):
        filas = {
            'TESTTERRACHILE': [self.fila_sap()],
            'SBO_TST_SBH_USD': [self.fila_sap(CardName='Transportes SBH')],
        }

        resultados = self.sincronizar(filas)

        self.assertEqual([resultado['creados'] for resultado in resultados], [1, 1])
        self.assertEqual(
            SOCIONEGOCIO.objects.filter(SN_CCODIGO_SAP='P77665886').count(), 2
        )
        self.assertEqual(
            SOCIONEGOCIO.objects.get(EP_NID=self.terramar, SN_CCODIGO_SAP='P77665886').SN_CRAZONSOCIAL,
            'Transportes Prueba Limitada',
        )
        self.assertEqual(
            SOCIONEGOCIO.objects.get(EP_NID=self.sbh, SN_CCODIGO_SAP='P77665886').SN_CRAZONSOCIAL,
            'Transportes SBH',
        )

    def test_filas_que_no_cumplen_regla_no_se_crean(self):
        for campo, valor in (
            ('EsTransporte', 'No'),
            ('CardType', 'C'),
            ('validFor', 'N'),
            ('frozenFor', 'Y'),
        ):
            with self.subTest(campo=campo):
                resultado = self.sincronizar(
                    {'TESTTERRACHILE': [self.fila_sap(**{campo: valor})]},
                    empresas=(1,),
                )[0]
                self.assertEqual(resultado['ignorados'], 1)
                self.assertFalse(SOCIONEGOCIO.objects.filter(EP_NID_id=1).exists())

    def test_es_idempotente_y_actualiza_solo_registro_de_su_empresa(self):
        filas = {'TESTTERRACHILE': [self.fila_sap()]}
        self.sincronizar(filas, empresas=(1,))
        self.sincronizar(filas, empresas=(1,))
        self.assertEqual(
            SOCIONEGOCIO.objects.filter(EP_NID_id=1, SN_CCODIGO_SAP='P77665886').count(),
            1,
        )

        filas['TESTTERRACHILE'] = [self.fila_sap(
            CardName='Transportes Actualizados SpA', Phone1='+56 2 2222 2222'
        )]
        resultado = self.sincronizar(filas, empresas=(1,))[0]
        socio = SOCIONEGOCIO.objects.get(EP_NID_id=1, SN_CCODIGO_SAP='P77665886')
        self.assertEqual(resultado['actualizados'], 1)
        self.assertEqual(socio.SN_CRAZONSOCIAL, 'Transportes Actualizados SpA')
        self.assertEqual(socio.SN_CTELEFONO, '+56 2 2222 2222')

    def test_dry_run_no_escribe_postgresql(self):
        resultado = self.sincronizar(
            {'SBO_TST_SBH_USD': [self.fila_sap()]}, empresas=(2,), dry_run=True
        )[0]

        self.assertEqual(resultado['creados'], 1)
        self.assertFalse(SOCIONEGOCIO.objects.filter(EP_NID_id=2).exists())

    def test_proveedor_listall_mantiene_aislamiento_por_empresa(self):
        SOCIONEGOCIO.objects.create(
            EP_NID=self.terramar, SN_CCODIGO_SAP='T-1', SN_CRAZONSOCIAL='Terramar',
            SN_CRUT='11111111-1', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        SOCIONEGOCIO.objects.create(
            EP_NID=self.sbh, SN_CCODIGO_SAP='S-1', SN_CRAZONSOCIAL='SBH',
            SN_CRUT='22222222-2', SN_CTIPO='S', SN_BHABILITADO=True,
        )
        usuario = get_user_model().objects.create_superuser(
            'admin_transportes_sync', 'admin@example.test', 'test-pass'
        )
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.terramar)
        USERS_EMPRESA.objects.create(US_NID=usuario, EP_NID=self.sbh)
        self.client.force_login(usuario)

        terramar = self.client.get(reverse('pro_listall'), {'_empresa_id': 1})
        sbh = self.client.get(reverse('pro_listall'), {'_empresa_id': 2})

        self.assertEqual(
            list(terramar.context['object_list'].values_list('EP_NID_id', flat=True)),
            [1],
        )
        self.assertEqual(
            list(sbh.context['object_list'].values_list('EP_NID_id', flat=True)),
            [2],
        )

    @patch('apps.home.management.commands.sincronizar_transportes_sap.sincronizar_transportes_sap')
    def test_comando_exige_ejecucion_explicita_y_soporta_dry_run(self, sincronizar_mock):
        sincronizar_mock.return_value = [{
            'empresa_id': 2, 'encontrados': 1, 'creados': 1,
            'actualizados': 0, 'sin_cambios': 0, 'ignorados': 0, 'errores': 0,
        }]
        salida = StringIO()

        call_command('sincronizar_transportes_sap', '--empresa', '2', '--dry-run', stdout=salida)

        sincronizar_mock.assert_called_once_with(empresas=[2], dry_run=True)
        self.assertIn('DRY-RUN empresa=2: encontrados=1, creados=1', salida.getvalue())
