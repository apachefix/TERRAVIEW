import re
from datetime import date, datetime
from decimal import Decimal

from decouple import config
from hdbcli import dbapi


HANA_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_]+$')


class SapDiApiError(Exception):
    pass


def _load_config():
    values = {
        'ServerAddress': config('SAP_HANA_SERVER_ADDRESS', default='').strip(),
        'ServerPort': config('SAP_HANA_SERVER_PORT', default='').strip(),
        'CompanyDB': config('SAP_HANA_COMPANY_DB', default='').strip(),
        'DbUserName': config('SAP_HANA_DB_USERNAME', default='').strip(),
        'DbPassword': config('SAP_HANA_DB_PASSWORD', default=''),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise SapDiApiError('Faltan variables SAP HANA en .env: ' + ', '.join(missing))
    return values


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


def consultar_productos_sap(busqueda=None):
    busqueda = (busqueda or '').strip()
    filtros = ''
    params = []

    if busqueda:
        termino = f'%{busqueda.upper()}%'
        filtros = '''
          AND (
              UPPER(T1."ItemCode") LIKE ?
              OR UPPER(T1."Dscription") LIKE ?
          )
        '''
        params = [termino, termino]

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
          {filtros}
        ORDER BY T0."DocNum" DESC
    '''.format(filtros=filtros)

    pedidos_abiertos = _rows(sql, params)
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
            T3."Number" AS "ContratoSap",
            T1."LineNum",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        LEFT JOIN OOAT T3
            ON T1."AgrNo" = T3."AbsID"
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
            'codigo_proveedor_sap': row['CardCode'],
            'proveedor_nombre': row['CardName'],
            'proveedor': row['CardName'],
            'contrato_sap': row.get('ContratoSap') or '',
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
        'line_num': row.get('LineNum'),
        'linenum': row.get('LineNum'),
        'cardcode': row['CardCode'],
        'cardname': row['CardName'],
        'proveedor_codigo': row['CardCode'],
        'codigo_proveedor_sap': row['CardCode'],
        'proveedor_nombre': row['CardName'],
        'proveedor': row['CardName'],
        'contrato_sap': row.get('ContratoSap') or '',
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
            T3."Number" AS "ContratoSap",
            T1."LineNum",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        LEFT JOIN OOAT T3
            ON T1."AgrNo" = T3."AbsID"
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
            T3."Number" AS "ContratoSap",
            T1."LineNum",
            T1."ItemCode",
            T1."Dscription",
            T1."OpenQty",
            T1."U_NXContenedor"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        LEFT JOIN OOAT T3
            ON T1."AgrNo" = T3."AbsID"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
          AND T0."DocNum" = ?
        ORDER BY T1."LineNum"
    '''

    return {
        'ok': True,
        'pedido': int(pedido),
        'lineas': [_pedido_row_to_dict(row) for row in _rows(sql, [int(pedido)])]
    }


def consultar_acuerdos_despacho_sap(termino):
    termino = (termino or '').strip()

    if len(termino) < 2:
        return {
            'ok': True,
            'resultados': []
        }

    termino_like = f'%{termino}%'
    termino_like_upper = f'%{termino.upper()}%'

    sql = '''
        SELECT
            TOP 50
            A."AbsID"      AS "sap_abs_id",
            A."Number"     AS "sap_acuerdo_numero",
            A."BpCode"     AS "cliente_codigo",
            A."BpName"     AS "cliente_nombre",
            A."NumAtCard"  AS "oc_cliente",
            A."Descript"   AS "descripcion_acuerdo",
            A."StartDate"  AS "fecha_inicio",
            A."EndDate"    AS "fecha_fin",
            A."Status"     AS "estado_acuerdo",

            L."AgrLineNum" AS "linea_acuerdo",
            L."ItemCode"   AS "codigo_insumo",
            L."ItemName"   AS "nombre_insumo",
            L."PlanQty"    AS "cantidad_planificada",
            L."CumQty"     AS "cantidad_consumida",
            L."UndlvQty"   AS "cantidad_pendiente",
            COALESCE(L."PlanQty", 0) - COALESCE(L."CumQty", 0) AS "saldo_contrato_sap",

            CASE
                WHEN COALESCE(L."PlanQty", 0) - COALESCE(L."CumQty", 0) <= 0 THEN 'SIN_SALDO'
                ELSE 'DISPONIBLE'
            END AS "estado_saldo",

            L."InvntryUom" AS "unidad_medida",
            L."UnitPrice"  AS "precio_unitario",
            L."Currency"   AS "moneda",
            L."LineStatus" AS "estado_linea",
            L."TrnspCode"  AS "codigo_transporte",
            L."U_CostEstim" AS "centro_costo_estimado",
            L."U_FeeMt"     AS "tarifa_mt",
            L."U_U_Incoterms" AS "incoterms"
        FROM "SBO_TST_SBH_USD"."OOAT" A
        INNER JOIN "SBO_TST_SBH_USD"."OAT1" L
            ON L."AgrNo" = A."AbsID"
        WHERE A."BpType" = 'C'
          AND A."Status" = 'A'
          AND L."LineStatus" = 'O'
          AND (
                CAST(A."Number" AS NVARCHAR) LIKE ?
                OR A."NumAtCard" LIKE ?
                OR UPPER(A."Descript") LIKE ?
                OR UPPER(A."BpName") LIKE ?
                OR A."BpCode" LIKE ?
              )
        ORDER BY A."CreateDate" DESC, A."Number" DESC, L."AgrLineNum"
    '''

    params = [
        termino_like,
        termino_like,
        termino_like_upper,
        termino_like_upper,
        termino_like,
    ]

    return {
        'ok': True,
        'resultados': _rows(sql, params)
    }
