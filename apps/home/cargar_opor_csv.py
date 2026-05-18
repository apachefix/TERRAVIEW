import os
import sys
import django
import pandas as pd
from decimal import Decimal, InvalidOperation

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from apps.home.models import EMPRESA, SAP_OPOR_PROGRAMACION


CSV_PATH = r'C:\APP_PRODUCCIÓN\TERRAMAR-CAMIONES\apps\home\data\OPOR 2.csv'

# 1 = TERRAMAR CHILE / Harinas
# 2 = ACEITES SBH
EMPRESA_ID = 2


def limpiar_texto(valor):
    if pd.isna(valor):
        return None

    valor = str(valor).strip()

    if valor == '' or valor == '?':
        return None

    return valor


def limpiar_entero_sap(valor):
    """
    Limpia números SAP que vienen con punto como separador de miles.

    Ejemplos:
    DocEntry: 1.485 -> 1485
    DocNum: 10.000.350 -> 10000350
    """

    if pd.isna(valor):
        return None

    valor = str(valor).strip()

    if valor == '' or valor == '?':
        return None

    valor = valor.replace('.', '').replace(',', '')

    return valor


def limpiar_decimal(valor):
    """
    Limpia cantidades con formato chileno.

    Ejemplo:
    OpenQty: 1.659,50 -> 1659.50
    """

    if pd.isna(valor):
        return Decimal('0')

    valor = str(valor).strip()

    if valor == '' or valor == '?':
        return Decimal('0')

    valor = valor.replace('.', '').replace(',', '.')

    try:
        return Decimal(valor)
    except InvalidOperation:
        return Decimal('0')


def limpiar_fecha(valor):
    if pd.isna(valor):
        return None

    valor = str(valor).strip()

    if valor == '' or valor == '?':
        return None

    fecha = pd.to_datetime(valor, dayfirst=True, errors='coerce')

    if pd.isna(fecha):
        return None

    return fecha.to_pydatetime()


def obtener_valor(row, nombre_base):
    """
    Busca una columna por nombre base, ignorando descripciones entre paréntesis.
    Ejemplo:
    - DocNum
    - DocNum (N PEDIDO)
    """

    for columna in row.index:
        columna_limpia = str(columna).strip()

        if columna_limpia == nombre_base:
            return row.get(columna)

        if columna_limpia.startswith(nombre_base + ' '):
            return row.get(columna)

        if columna_limpia.startswith(nombre_base + '('):
            return row.get(columna)

    return None


def main():
    empresa = EMPRESA.objects.get(id=EMPRESA_ID)

    df = pd.read_csv(
        CSV_PATH,
        sep=';',
        encoding='latin1',
        dtype=str
    )

    df.columns = [str(col).strip() for col in df.columns]

    creados = 0
    actualizados = 0
    omitidos = 0
    errores = 0

    for index, row in df.iterrows():
        try:
            docentry = limpiar_entero_sap(obtener_valor(row, 'DocEntry'))
            itemcode = limpiar_texto(obtener_valor(row, 'ItemCode'))

            if not docentry or not itemcode:
                omitidos += 1
                continue

            _, created = SAP_OPOR_PROGRAMACION.objects.update_or_create(
                EP_NID=empresa,
                SOP_DOCENTRY=docentry,
                SOP_ITEMCODE=itemcode,
                defaults={
                    'SOP_DOCNUM': limpiar_entero_sap(obtener_valor(row, 'DocNum')),
                    'SOP_DOCSTATUS': limpiar_texto(obtener_valor(row, 'DocStatus')),
                    'SOP_CARDCODE': limpiar_texto(obtener_valor(row, 'CardCode')),
                    'SOP_CARDNAME': limpiar_texto(obtener_valor(row, 'CardName')),
                    'SOP_DOCDATE': limpiar_fecha(obtener_valor(row, 'DocDate')),
                    'SOP_TAXDATE': limpiar_fecha(obtener_valor(row, 'TaxDate')),
                    'SOP_DOCDUEDATE': limpiar_fecha(obtener_valor(row, 'DocDueDate')),
                    'SOP_CREATEDATE': limpiar_fecha(obtener_valor(row, 'CreateDate')),
                    'SOP_DSCRIPTIONS': limpiar_texto(obtener_valor(row, 'Dscription')),
                    'SOP_OPENQTY': limpiar_decimal(obtener_valor(row, 'OpenQty')),
                    'SOP_CONTENEDOR': limpiar_texto(obtener_valor(row, 'U_NXContenedor')),
                    'SOP_PRODUCTOR': limpiar_texto(obtener_valor(row, 'U_NXProductor')),
                    'SOP_BHABILITADO': True,
                }
            )

            if created:
                creados += 1
            else:
                actualizados += 1

        except Exception as e:
            errores += 1
            print(f'Error fila {index + 1}: {e}')

    print('--------------------------------')
    print('Carga OPOR finalizada')
    print(f'Empresa ID: {EMPRESA_ID}')
    print(f'Creados: {creados}')
    print(f'Actualizados: {actualizados}')
    print(f'Omitidos: {omitidos}')
    print(f'Errores: {errores}')
    print('--------------------------------')


if __name__ == '__main__':
    main()