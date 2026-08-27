from datetime import datetime, time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.home import views
from apps.home.models import (
    CALENDARIO, CITACION, CONDUCTOR, CONDUCTOR_EMPRESA, EMPRESA,
    PLANIFICACION, SECUENCIA, SOCIONEGOCIO,
)
from apps.home.services.padron_conductores import (
    asegurar_membresia_conductor_empresa, sembrar_conductores_sbh_desde_ruts,
)


class PadronConductoresSbhTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base_empresa = {'EP_CBASEDATOS': 'test', 'EP_CUSUARIOSBD': 'test', 'EP_CPORT': '5432'}
        cls.terramar = EMPRESA.objects.create(id=1, EP_CRAZONSOCIAL='Terramar', EP_CRUT='1-9', **base_empresa)
        cls.sbh = EMPRESA.objects.create(id=2, EP_CRAZONSOCIAL='Aceites SBH', EP_CRUT='2-9', **base_empresa)
        cls.transporte_tm = cls._transporte(cls.terramar, '76000001-1')
        cls.transporte_sbh = cls._transporte(cls.sbh, '76000002-2')
        cls.compartido = cls._conductor(cls.terramar, 'Compartido', '10674376-2')
        cls.solo_terramar = cls._conductor(cls.terramar, 'Sólo TM', '10891933-7')
        cls.inhabilitado = cls._conductor(cls.terramar, 'Inhabilitado', '11497938-4', habilitado=False)
        cls.puesto = cls._conductor(cls.terramar, 'Puesto', '55555555-5')
        cls.generico = cls._conductor(cls.terramar, 'Genérico', '99999999-9')
        asegurar_membresia_conductor_empresa(conductor=cls.compartido, empresa=cls.terramar)
        asegurar_membresia_conductor_empresa(conductor=cls.compartido, empresa=cls.sbh)
        asegurar_membresia_conductor_empresa(conductor=cls.inhabilitado, empresa=cls.sbh)
        asegurar_membresia_conductor_empresa(conductor=cls.puesto, empresa=cls.sbh)
        asegurar_membresia_conductor_empresa(conductor=cls.generico, empresa=cls.sbh)

    @classmethod
    def _transporte(cls, empresa, rut):
        return SOCIONEGOCIO.objects.create(
            EP_NID=empresa, SN_CRAZONSOCIAL=f'Transporte {empresa.pk}', SN_CRUT=rut,
            SN_CTIPO='S', SN_BHABILITADO=True,
        )

    @classmethod
    def _conductor(cls, empresa, nombre, rut, habilitado=True):
        return CONDUCTOR.objects.create(
            EP_NID=empresa,
            SN_NID=cls.transporte_tm if empresa.pk == 1 else cls.transporte_sbh,
            CON_CNOMBRE=nombre, CON_CAPELLIDO='Prueba', CON_CRUT=rut,
            CON_BHABILITADO=habilitado,
        )

    def _ids_sbh(self):
        return set(views.queryset_conductores_operativos(2).values_list('id', flat=True))

    def test_legacy_terramar_con_membresia_sbh_aparece_en_sbh_y_ambas_empresas(self):
        self.assertIn(self.compartido.pk, self._ids_sbh())
        self.assertIn(self.compartido.pk, set(views.queryset_conductores_operativos(1).values_list('id', flat=True)))

    def test_sin_membresia_sbh_no_aparece_y_terramar_conserva_universo_legacy(self):
        self.assertNotIn(self.solo_terramar.pk, self._ids_sbh())
        self.assertIn(self.solo_terramar.pk, set(views.queryset_conductores_operativos(1).values_list('id', flat=True)))

    def test_sbh_excluye_genericos_e_inhabilitados_aun_con_membresia(self):
        ids = self._ids_sbh()
        self.assertNotIn(self.inhabilitado.pk, ids)
        self.assertNotIn(self.puesto.pk, ids)
        self.assertNotIn(self.generico.pk, ids)

    def test_sbh_excluye_rut_sin_formato_valido_aun_con_membresia(self):
        invalido = self._conductor(self.terramar, 'Formato malo', 'rut-sin-validar')
        asegurar_membresia_conductor_empresa(conductor=invalido, empresa=self.sbh)
        self.assertNotIn(invalido.pk, self._ids_sbh())

    def test_semilla_no_escribe_dry_run_y_es_idempotente(self):
        resultado = sembrar_conductores_sbh_desde_ruts(['10891933-7'], dry_run=True)
        self.assertEqual(resultado['nuevas_membresias'], [self.solo_terramar.pk])
        self.assertFalse(CONDUCTOR_EMPRESA.objects.filter(CON_NID=self.solo_terramar, EP_NID=self.sbh).exists())
        sembrar_conductores_sbh_desde_ruts(['10.891.933-7'])
        segundo = sembrar_conductores_sbh_desde_ruts(['10891933-7'])
        self.assertEqual(segundo['ya_asociados'], [self.solo_terramar.pk])
        self.assertEqual(CONDUCTOR_EMPRESA.objects.filter(CON_NID=self.solo_terramar, EP_NID=self.sbh).count(), 1)

    def test_semilla_excluye_ruts_malos_genericos_e_inhabilitados(self):
        resultado = sembrar_conductores_sbh_desde_ruts(['55555555-5', '99999999-9', '11497938-4', 'RUT-MALO'])
        self.assertIn('RUT-MALO', resultado['ruts_invalidos'])
        self.assertIn('55555555-5', resultado['inhabilitados_o_genericos'])
        self.assertIn('99999999-9', resultado['inhabilitados_o_genericos'])
        self.assertIn('11497938-4', resultado['inhabilitados_o_genericos'])

    def test_rut_duplicado_activo_es_conflicto_y_no_se_asocia(self):
        duplicado = self._conductor(self.terramar, 'Duplicado', '10674376-2')
        CONDUCTOR_EMPRESA.objects.filter(CON_NID=self.compartido, EP_NID=self.sbh).delete()
        resultado = sembrar_conductores_sbh_desde_ruts(['10674376-2'])
        self.assertEqual(resultado['conflictos'][0]['conductores'], [self.compartido.pk, duplicado.pk])
        self.assertFalse(CONDUCTOR_EMPRESA.objects.filter(CON_NID__in=[self.compartido, duplicado], EP_NID=self.sbh).exists())

    def test_comando_csv_reporta_sin_crear_en_dry_run(self):
        with TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'conductores_sbh.csv'
            archivo.write_text('RUT,nombre\n10891933-7,Solo TM\n', encoding='utf-8')
            salida = StringIO()
            call_command('sembrar_conductores_sbh', '--archivo', str(archivo), '--dry-run', stdout=salida)
        self.assertIn('DRY-RUN', salida.getvalue())
        self.assertFalse(CONDUCTOR_EMPRESA.objects.filter(CON_NID=self.solo_terramar, EP_NID=self.sbh).exists())

    def test_consulta_y_semilla_no_modifican_sn_nid_ni_citacion(self):
        calendario = CALENDARIO.objects.create(
            EP_NID=self.sbh, CA_NDIA=1, CA_NMES=7, CA_NANO=2026,
            CA_NCANTIDADCUPOS=1, CA_FHORA_APERTURA=time(8), CA_FHORA_CIERRE=time(18),
        )
        planificacion = PLANIFICACION.objects.create(
            EP_NID=self.sbh, CAL_NID=calendario, PL_CTIPOCUPO='RECEPCION',
            PL_FFECHAINICIO=timezone.make_aware(datetime(2026, 7, 1, 8)), PL_NCANTIDADCUPOS=1,
        )
        secuencia = SECUENCIA.objects.create(
            EP_NID=self.sbh, SE_CTIPO='RECEPCION', SE_CCODIGO='PADRON_TEST',
            SE_CNOMBRE='Padrón test', SE_BHABILITADO=True,
        )
        citacion = CITACION.objects.create(
            EP_NID=self.sbh, PL_NID=planificacion, SC_NID=secuencia, CON_NID=self.solo_terramar,
            CI_FFECHACITACION=timezone.make_aware(datetime(2026, 7, 1, 8)),
            CI_NCUPO=1, CI_CESTADO='Insumo Programado', CI_CTIPO='RECEPCION',
        )
        antes = (self.solo_terramar.SN_NID_id, citacion.CON_NID_id, CITACION.objects.count())
        list(views.queryset_conductores_operativos(2))
        sembrar_conductores_sbh_desde_ruts(['10891933-7'])
        self.solo_terramar.refresh_from_db()
        citacion.refresh_from_db()
        self.assertEqual((self.solo_terramar.SN_NID_id, citacion.CON_NID_id, CITACION.objects.count()), antes)
