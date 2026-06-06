import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from hdbcli import dbapi


LOGIN_HDB_FILE = Path(__file__).resolve().parents[2] / 'loginHDB.json'
HANA_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_]+$')


class SapDiApiError(Exception):
    pass


def _load_config():
    try:
        with LOGIN_HDB_FILE.open('r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise SapDiApiError('No se encontro el archivo loginHDB.json para conectar a SAP HANA.') from exc
    except json.JSONDecodeError as exc:
        raise SapDiApiError('El archivo loginHDB.json no tiene un formato valido.') from exc


def _connect_hana():
    config = _load_config()

    try:
        conn = dbapi.connect(
            address=config.get('ServerAddress', ''),
            port=int(config.get('ServerPort', 30015)),
            user=config.get('DbUserName', ''),
            password=config.get('DbPassword', '')
        )

        company_db = (config.get('CompanyDB') or '').strip()

        if company_db:
            if not HANA_IDENTIFIER_RE.match(company_db):
                raise SapDiApiError('CompanyDB HANA tiene un formato no valido.')

            cursor = conn.cursor()
            try:
                cursor.execute(f'SET SCHEMA "{company_db}"')
            finally:
                cursor.close()

        return conn
    except Exception as exc:
        raise SapDiApiError(f'No fue posible conectar a SAP HANA: {str(exc)}') from exc


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _first_row(sql, params=None):
    conn = None
    cursor = None

    try:
        conn = _connect_hana()
        cursor = conn.cursor()
        cursor.execute(sql, params or [])
        row = cursor.fetchone()

        if row is None:
            return None

        columns = [column[0] for column in cursor.description]

        return {
            columns[index]: _json_value(value)
            for index, value in enumerate(row)
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _rows(sql, params=None):
    conn = None
    cursor = None

    try:
        conn = _connect_hana()
        cursor = conn.cursor()
        cursor.execute(sql, params or [])
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        return [
            {
                columns[index]: _json_value(value)
                for index, value in enumerate(row)
            }
            for row in rows
        ]
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def consultar_proveedores_sap():
    sql = '''
        SELECT DISTINCT
            T0."CardCode",
            T0."CardName"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
        ORDER BY T0."CardName"
    '''

    proveedores = [
        {
            'cardcode': row['CardCode'],
            'cardname': row['CardName']
        }
        for row in _rows(sql)
    ]

    return {
        'ok': True,
        'proveedores': proveedores
    }


def consultar_clientes_sap():
    sql = '''
        SELECT DISTINCT
            T0."CardCode",
            T0."CardName"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
        ORDER BY T0."CardName"
    '''

    clientes = [
        {
            'cardcode': row['CardCode'],
            'cardname': row['CardName'],
            'cardtype': '',
            'validfor': ''
        }
        for row in _rows(sql)
    ]

    return {
        'ok': True,
        'clientes': clientes
    }


def consultar_productos_sap():
    sql = '''
        SELECT
            TOP 50
            T1."ItemCode",
            T1."Dscription",
            T0."DocNum",
            T0."CardName",
            T1."OpenQty"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
        ORDER BY T0."DocNum" DESC
    '''

    pedidos_abiertos = _rows(sql)
    productos = []
    itemcodes = set()

    for row in pedidos_abiertos:
        itemcode = row['ItemCode']

        if itemcode in itemcodes:
            continue

        itemcodes.add(itemcode)
        productos.append({
            'itemcode': itemcode,
            'itemname': row['Dscription'],
            'docnum': row['DocNum'],
            'cardname': row['CardName'],
            'openqty': row['OpenQty']
        })

    return {
        'ok': True,
        'productos': productos,
        'pedidos_abiertos': [
            {
                'itemcode': row['ItemCode'],
                'descripcion': row['Dscription'],
                'docnum': row['DocNum'],
                'cardname': row['CardName'],
                'openqty': row['OpenQty']
            }
            for row in pedidos_abiertos
        ]
    }


def consultar_producto_sap(codigo):
    codigo = (codigo or '').strip()

    if not codigo:
        return {
            'ok': False,
            'mensaje': 'Debe ingresar codigo SAP.',
            'message': 'Debe ingresar codigo SAP.'
        }

    sql = '''
        SELECT
            T0."ItemCode",
            T0."ItemName",
            T0."InvntItem"
        FROM OITM T0
        WHERE T0."InvntItem" <> 'N'
          AND T0."ItemCode" = ?
    '''

    row = _first_row(sql, [codigo])

    if row is None:
        return {
            'ok': False,
            'mensaje': 'Codigo SAP no encontrado',
            'message': 'Codigo SAP no encontrado'
        }

    return {
        'ok': True,
        'item_code': row['ItemCode'],
        'item_name': row['ItemName']
    }


def consultar_pedido_sap(pedido, codigo, proveedor_codigo=''):
    pedido = (pedido or '').strip()
    codigo = (codigo or '').strip()

    if not pedido:
        return {
            'ok': False,
            'mensaje': 'Debe ingresar Pedido SAP.',
            'message': 'Debe ingresar Pedido SAP.'
        }

    if not pedido.isdigit():
        return {
            'ok': False,
            'mensaje': 'El Pedido SAP debe ser numerico.',
            'message': 'El Pedido SAP debe ser numerico.'
        }

    if not codigo:
        return {
            'ok': False,
            'mensaje': 'Debe ingresar codigo SAP antes de consultar el pedido.',
            'message': 'Debe ingresar codigo SAP antes de consultar el pedido.'
        }

    pedido_num = int(pedido)

    sql = '''
        SELECT
            T0."DocEntry",
            T0."DocNum",
            T0."CardCode",
            T0."CardName",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
          AND T0."DocNum" = ?
          AND T1."ItemCode" = ?
    '''

    row = _first_row(sql, [pedido_num, codigo])

    if row is not None:
        return {
            'ok': True,
            'docentry': row['DocEntry'],
            'docnum': row['DocNum'],
            'pedido': row['DocNum'],
            'cardcode': row['CardCode'],
            'cardname': row['CardName'],
            'proveedor_codigo': row['CardCode'],
            'proveedor_nombre': row['CardName'],
            'proveedor': row['CardName'],
            'itemcode': row['ItemCode'],
            'descripcion': row['Dscription'],
            'producto': row['Dscription'],
            'openqty': row['OpenQty'],
            'cantidad_disponible': row['OpenQty'],
            'contenedor': row.get('U_NXContenedor') or '',
            'bl': row.get('U_NXContenedor') or '',
            'bl_contenedor': row.get('U_NXContenedor') or ''
        }

    estado_sql = '''
        SELECT
            T0."DocStatus"
        FROM OPOR T0
        WHERE T0."DocNum" = ?
    '''

    estado = _first_row(estado_sql, [pedido_num])

    if estado is None:
        return {
            'ok': False,
            'mensaje': 'Pedido SAP no encontrado',
            'message': 'Pedido SAP no encontrado'
        }

    if str(estado['DocStatus']) != 'O':
        return {
            'ok': False,
            'mensaje': 'Pedido SAP cerrado',
            'message': 'Pedido SAP cerrado'
        }

    item_sql = '''
        SELECT
            T1."ItemCode",
            T1."OpenQty"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocNum" = ?
          AND T1."ItemCode" = ?
    '''

    item = _first_row(item_sql, [pedido_num, codigo])

    if item is None:
        return {
            'ok': False,
            'mensaje': 'No existe pedido abierto con saldo disponible para el producto seleccionado.',
            'message': 'No existe pedido abierto con saldo disponible para el producto seleccionado.'
        }

    return {
        'ok': False,
        'mensaje': 'No existe pedido abierto con saldo disponible para el producto seleccionado.',
        'message': 'No existe pedido abierto con saldo disponible para el producto seleccionado.'
    }


def _pedido_row_to_dict(row):
    contenedor = row.get('U_NXContenedor') or ''

    return {
        'docentry': row['DocEntry'],
        'docnum': row['DocNum'],
        'pedido': row['DocNum'],
        'cardcode': row['CardCode'],
        'cardname': row['CardName'],
        'proveedor_codigo': row['CardCode'],
        'proveedor_nombre': row['CardName'],
        'proveedor': row['CardName'],
        'itemcode': row['ItemCode'],
        'codigo': row['ItemCode'],
        'descripcion': row['Dscription'],
        'producto': row['Dscription'],
        'openqty': row['OpenQty'],
        'cantidad_disponible': row['OpenQty'],
        'contenedor': contenedor,
        'bl': contenedor,
        'bl_contenedor': contenedor,
    }


def consultar_pedidos_por_producto_sap(codigo):
    codigo = (codigo or '').strip()

    if not codigo:
        return {
            'ok': False,
            'mensaje': 'Debe ingresar codigo SAP.',
            'message': 'Debe ingresar codigo SAP.'
        }

    sql = '''
        SELECT
            T0."DocEntry",
            T0."DocNum",
            T0."CardCode",
            T0."CardName",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
          AND T1."ItemCode" = ?
        ORDER BY T0."DocNum" DESC
    '''

    return {
        'ok': True,
        'pedidos': [_pedido_row_to_dict(row) for row in _rows(sql, [codigo])]
    }


def consultar_detalle_pedido_sap(pedido):
    pedido = (pedido or '').strip()

    if not pedido:
        return {
            'ok': False,
            'mensaje': 'Debe ingresar Pedido SAP.',
            'message': 'Debe ingresar Pedido SAP.'
        }

    if not pedido.isdigit():
        return {
            'ok': False,
            'mensaje': 'El Pedido SAP debe ser numerico.',
            'message': 'El Pedido SAP debe ser numerico.'
        }

    sql = '''
        SELECT
            T0."DocEntry",
            T0."DocNum",
            T0."CardCode",
            T0."CardName",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
          AND T0."DocNum" = ?
        ORDER BY T1."Dscription"
    '''

    return {
        'ok': True,
        'pedido': int(pedido),
        'lineas': [_pedido_row_to_dict(row) for row in _rows(sql, [int(pedido)])]
    }
