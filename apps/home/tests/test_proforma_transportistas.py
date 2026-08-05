from django.db import connection
from django.test import TestCase

from apps.home.general_postgres import (
    get_list_citaciones_terminadas_proforma,
    get_transportistas_citaciones_terminadas_proforma,
)
from apps.home.models import CITACION, EMPRESA
from apps.home.tests.test_iniciar_proforma import IniciarProformaFixtureMixin


class ProformaTransportistasTests(IniciarProformaFixtureMixin, TestCase):
    def setUp(self):
        self.crear_datos_base()
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = 'TRANSPORTES SAEZ LIMITADA'
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])

    def _requiere_postgresql(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Los selectores usan SQL específico de PostgreSQL.')

    def _crear_citacion_terramar(self, transportista, patente):
        citacion = CITACION.objects.create(
            US_NID=self.user,
            EP_NID=self.empresa,
            PL_NID=self.citacion.PL_NID,
            SC_NID=self.citacion.SC_NID,
            CI_FFECHAREGISTRO=self.citacion.CI_FFECHAREGISTRO,
            CI_FFECHACITACION=self.citacion.CI_FFECHACITACION,
            CI_NCUPO=2,
            CI_CTIPO='RECEPCION',
            CI_CESTADO='TERMINADO',
            CI_BHABILITADO=True,
            CI_BCONFORME=False,
            CI_CTIPO_FLETE='Flete Cliente',
        )
        camion = self.crear_camion(citacion, 'TERRAMAR', patente=patente)
        camion.CPA_CTRANSPORTISTA_DECLARADO = transportista
        camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])
        return citacion

    def _filas(self, transportista=None, empresa=None, buscar_transportista=None):
        return get_list_citaciones_terminadas_proforma(
            fecha_desde=None,
            fecha_hasta=None,
            tipo_citacion=None,
            empresa=empresa or self.empresa.pk,
            transportista=transportista,
            buscar_transportista=buscar_transportista,
        ) or []

    def test_catalogo_agrupa_saez_y_filtra_transportistas_independientes(self):
        self._requiere_postgresql()
        segunda_saez = self._crear_citacion_terramar(
            'TRANSPORTES SAEZ LIMITADA',
            'SAEZ02',
        )
        delsava = self._crear_citacion_terramar(
            'COMERCIAL DELSAVA Y COMPAÑIA LIMITADA',
            'DEL01',
        )
        pascal = self._crear_citacion_terramar(
            'LOGISTICA & TRANSPORTE PASCAL LTDA',
            'PAS01',
        )

        catalogo = get_transportistas_citaciones_terminadas_proforma(
            self.empresa.pk,
        )
        codigos = [fila[0] for fila in catalogo]

        self.assertCountEqual(
            codigos,
            [
                'TRANSPORTES SAEZ LIMITADA',
                'COMERCIAL DELSAVA Y COMPAÑIA LIMITADA',
                'LOGISTICA & TRANSPORTE PASCAL LTDA',
            ],
        )
        filas_saez = self._filas('transportes saez limitada')
        self.assertCountEqual(
            [fila[0] for fila in filas_saez],
            [self.citacion.pk, segunda_saez.pk],
        )
        self.assertEqual(
            [fila[0] for fila in self._filas('COMERCIAL DELSAVA Y COMPAÑIA LIMITADA')],
            [delsava.pk],
        )
        self.assertEqual(
            [fila[0] for fila in self._filas('LOGISTICA & TRANSPORTE PASCAL LTDA')],
            [pascal.pk],
        )

    def test_busqueda_parcial_normalizada_por_transportista(self):
        self._requiere_postgresql()
        delsava = self._crear_citacion_terramar(
            'COMERCIAL DELSAVA Y COMPAÑIA LIMITADA',
            'DEL02',
        )
        pascal = self._crear_citacion_terramar(
            'LOGISTICA & TRANSPORTE PASCAL LTDA',
            'PAS02',
        )

        self.assertEqual(
            [fila[0] for fila in self._filas(buscar_transportista='delsava')],
            [delsava.pk],
        )
        self.assertEqual(
            [fila[0] for fila in self._filas(buscar_transportista='PASCAL')],
            [pascal.pk],
        )

    def test_cliente_no_es_elegible_ni_aparece_en_catalogo(self):
        self._requiere_postgresql()
        self.camion.CPA_CTRANSPORTISTA_DECLARADO = ' CLIENTE '
        self.camion.save(update_fields=['CPA_CTRANSPORTISTA_DECLARADO'])

        self.assertNotIn(self.citacion.pk, [fila[0] for fila in self._filas()])
        catalogo = get_transportistas_citaciones_terminadas_proforma(
            self.empresa.pk,
        )
        self.assertNotIn('CLIENTE', [fila[0] for fila in catalogo])

    def test_catalogo_y_listado_no_cruzan_empresas(self):
        self._requiere_postgresql()
        otra_empresa = EMPRESA.objects.create(
            EP_CRAZONSOCIAL='Empresa sin citaciones elegibles',
            EP_CRUT=f'EMP-{self.token}',
            EP_CBASEDATOS='db_otra',
            EP_CUSUARIOSBD='db_user',
            EP_CPORT='5432',
        )

        self.assertEqual(
            get_transportistas_citaciones_terminadas_proforma(otra_empresa.pk),
            [],
        )
        self.assertEqual(self._filas(empresa=otra_empresa.pk), [])

