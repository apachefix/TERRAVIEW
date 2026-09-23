import re
from datetime import date, datetime
from decimal import Decimal

from decouple import config
from hdbcli import dbapi

from apps.integrations.sap_b1.sap_config import SapConfigError, get_sap_company_db


HANA_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_]+$')


class SapDiApiError(Exception):
    pass


def _configured_hana_schema(variable_name):
    company_db = config(variable_name, default="").strip()
    if not company_db:
        raise SapDiApiError(f"Falta variable SAP HANA en .env: {variable_name}")
    if not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError(f"{variable_name} tiene un formato no valido.")
    return company_db


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


def consultar_transportistas_sap(company_db):
    """Obtiene desde OCRD los proveedores activos clasificados como transporte.

    ``company_db`` proviene de la configuración central por empresa; se valida
    antes de interpolarlo porque los identificadores HANA no admiten parámetros.
    """
    company_db = str(company_db or '').strip()
    if not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError('CompanyDB HANA tiene un formato no valido.')

    return _rows(f'''
        SELECT
            "CardCode",
            "CardName",
            "LicTradNum",
            "Address",
            "CardFName",
            "Phone1",
            "E_Mail",
            "CardType",
            "U_Transporte" AS "EsTransporte",
            "validFor",
            "frozenFor"
        FROM "{company_db}"."OCRD"
        WHERE
            "CardCode" IS NOT NULL
            AND "CardName" IS NOT NULL
            AND "LicTradNum" IS NOT NULL
            AND "CardType" = 'S'
            AND "U_Transporte" = 'Si'
            AND "validFor" = 'Y'
            AND "frozenFor" = 'N'
        ORDER BY "CardCode"
    ''')


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
    company_db = _configured_hana_schema("SAP_HANA_CLIENTES_COMPANY_DB")
    sql = f'''
        SELECT
            T0."CardCode",
            T0."CardName",
            T0."CardType",
            T0."validFor"
        FROM "{company_db}"."OCRD" T0
        WHERE T0."CardType" = 'C'
          AND T0."validFor" = 'Y'
          AND COALESCE(T0."frozenFor", 'N') = 'N'
        ORDER BY T0."CardName"
    '''

    clientes = [
        {
            'cardcode': row['CardCode'],
            'cardname': row['CardName'],
            'cardtype': row['CardType'],
            'validfor': row['validFor']
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


def consultar_productos_recepcion_transferencia_sap(estanque):
    """Obtiene el inventario disponible del estanque PROSESA para Transferencia SBH."""
    estanque = (estanque or '').strip()
    if not estanque:
        raise SapDiApiError('Debe seleccionar un estanque origen.')

    company_db = (_load_config().get('CompanyDB') or '').strip()
    if not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError('CompanyDB HANA tiene un formato no valido.')

    sql = f'''
        SELECT
            T1."WhsCode" AS "EstanqueOrigen",
            T0."ItemCode" AS "CodigoSAP",
            T0."ItemName" AS "Insumo",
            NULLIF(T0."U_Propiedad", '') AS "CodigoPropietario",
            T2."CardName" AS "PropiedadProducto",
            T1."OnHand" AS "StockFisico",
            T1."IsCommited" AS "StockComprometido",
            T1."OnHand" - T1."IsCommited" AS "StockDisponible",
            T0."InvntryUom" AS "UnidadInventario"
        FROM "{company_db}"."OITM" T0
        INNER JOIN "{company_db}"."OITW" T1
            ON T1."ItemCode" = T0."ItemCode"
        LEFT JOIN "{company_db}"."OCRD" T2
            ON T2."CardCode" = NULLIF(T0."U_Propiedad", '')
        WHERE T1."WhsCode" = ?
          AND (T1."OnHand" - T1."IsCommited") > 0
        ORDER BY T1."OnHand" DESC, T0."ItemCode"
    '''

    return {
        'estanque': estanque,
        'productos': [
            {
                'codigo_sap': row['CodigoSAP'],
                'insumo': row['Insumo'],
                'codigo_propietario': row['CodigoPropietario'],
                'propiedad_producto': row['PropiedadProducto'],
                'stock_disponible': row['StockDisponible'],
                'unidad': row['UnidadInventario'],
            }
            for row in _rows(sql, [estanque])
        ],
    }


def consultar_pedido_sap(pedido, codigo, proveedor_codigo=''):
    pedido = (pedido or '').strip()
    codigo = (codigo or '').strip()
    proveedor_codigo = (proveedor_codigo or '').strip()

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
            T1."U_NXContenedor" AS "Contenedor",
            T1."U_HCO_Invoice" AS "Guia",
            T1."U_HCO_FVEN" AS "FechaProduccion",
            T1."U_NXFlote" AS "FechaVencimiento",
            T1."U_CDA" AS "CDA",
            T1."U_DI" AS "DI",
            T1."U_SUI" AS "SUI",
            T1."U_BL" AS "BL",
            T1."U_HCO_NAVIERAS" AS "NaveNaviera",
            T1."U_HCO_BOOKING" AS "Booking"
        FROM OPOR T0
        INNER JOIN POR1 T1
            ON T0."DocEntry" = T1."DocEntry"
        LEFT JOIN OOAT T3
            ON T1."AgrNo" = T3."AbsID"
        WHERE T0."DocStatus" = 'O'
          AND T1."OpenQty" > 0
          AND T0."DocNum" = ?
          AND T1."ItemCode" = ?
          {filtro_proveedor}
    '''

    filtro_proveedor = 'AND T0."CardCode" = ?' if proveedor_codigo else ''
    sql = sql.format(filtro_proveedor=filtro_proveedor)
    params = [pedido_num, codigo]
    if proveedor_codigo:
        params.append(proveedor_codigo)

    row = _first_row(sql, params)

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
            'contenedor': row.get('Contenedor') or '',
            'bl': row.get('BL') or '',
            'bl_contenedor': row.get('Contenedor') or '',
            'guia': row.get('Guia') or '',
            'fecha_produccion': row.get('FechaProduccion') or '',
            'fecha_vencimiento': row.get('FechaVencimiento') or '',
            'cda': row.get('CDA') or '',
            'di': row.get('DI') or '',
            'sui': row.get('SUI') or '',
            'nave_naviera': row.get('NaveNaviera') or '',
            'booking': row.get('Booking') or ''
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
    contenedor = row.get('Contenedor') or row.get('U_NXContenedor') or ''

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
        'bl': row.get('BL') or '',
        'bl_contenedor': contenedor,
        'guia': row.get('Guia') or '',
        'fecha_produccion': row.get('FechaProduccion') or '',
        'fecha_vencimiento': row.get('FechaVencimiento') or '',
        'cda': row.get('CDA') or '',
        'di': row.get('DI') or '',
        'sui': row.get('SUI') or '',
        'nave_naviera': row.get('NaveNaviera') or '',
        'booking': row.get('Booking') or '',
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
            T1."U_NXContenedor" AS "Contenedor",
            T1."U_HCO_Invoice" AS "Guia",
            T1."U_HCO_FVEN" AS "FechaProduccion",
            T1."U_NXFlote" AS "FechaVencimiento",
            T1."U_CDA" AS "CDA",
            T1."U_DI" AS "DI",
            T1."U_SUI" AS "SUI",
            T1."U_BL" AS "BL",
            T1."U_HCO_NAVIERAS" AS "NaveNaviera",
            T1."U_HCO_BOOKING" AS "Booking"
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
            T1."U_NXContenedor" AS "Contenedor",
            T1."U_HCO_Invoice" AS "Guia",
            T1."U_HCO_FVEN" AS "FechaProduccion",
            T1."U_NXFlote" AS "FechaVencimiento",
            T1."U_CDA" AS "CDA",
            T1."U_DI" AS "DI",
            T1."U_SUI" AS "SUI",
            T1."U_BL" AS "BL",
            T1."U_HCO_NAVIERAS" AS "NaveNaviera",
            T1."U_HCO_BOOKING" AS "Booking"
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


def _expresion_incoterms_sbh(company_db):
    """Resuelve el UDF opcional de OAT1 sin invalidar toda la búsqueda."""
    columnas = _rows(
        '''
        SELECT "COLUMN_NAME"
        FROM "SYS"."TABLE_COLUMNS"
        WHERE "SCHEMA_NAME" = ?
          AND "TABLE_NAME" = 'OAT1'
          AND "COLUMN_NAME" IN ('U_Incoterms', 'U_U_Incoterms')
        ''',
        [company_db],
    )
    disponibles = {str(fila.get('COLUMN_NAME') or '') for fila in columnas}
    if 'U_Incoterms' in disponibles:
        return 'L."U_Incoterms"'
    if 'U_U_Incoterms' in disponibles:
        return 'L."U_U_Incoterms"'
    return 'CAST(NULL AS NVARCHAR(50))'

def consultar_acuerdos_despacho_sap(termino, empresa_id=None):
    if str(empresa_id or '') == '2':
        try:
            company_db = get_sap_company_db(2)
        except SapConfigError as exc:
            raise SapDiApiError(str(exc)) from exc
        if not HANA_IDENTIFIER_RE.match(company_db):
            raise SapDiApiError('SAP_SBH_COMPANY_DB tiene un formato no valido.')
        incoterms_sql = _expresion_incoterms_sbh(company_db)
    else:
        # Compatibilidad sin cambios para Terramar y consumidores legacy.
        company_db = _configured_hana_schema("SAP_HANA_ACUERDOS_COMPANY_DB")
        incoterms_sql = 'L."U_U_Incoterms"'
    termino = (termino or '').strip()

    if len(termino) < 2:
        return {
            'ok': True,
            'resultados': []
        }

    termino_like = f'%{termino}%'
    termino_like_upper = f'%{termino.upper()}%'

    sql = f'''
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
            {incoterms_sql} AS "incoterms"
        FROM "{company_db}"."OOAT" A
        INNER JOIN "{company_db}"."OAT1" L
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

    resultados = _rows(sql, params)
    if str(empresa_id or '') == '2':
        motivo_sin_oc = (
            'Este acuerdo no posee una OC asociada y no puede utilizarse para planificar.'
        )
        for resultado in resultados:
            has_oc = bool(str(resultado.get('oc_cliente') or '').strip())
            resultado.update({
                'has_oc': has_oc,
                'selectable': has_oc,
                'selection_block_reason': '' if has_oc else motivo_sin_oc,
            })

    return {
        'ok': True,
        'resultados': resultados
    }

def consultar_direcciones_despacho_sap(cliente_codigo, empresa_id=None):
    """Obtiene exclusivamente direcciones de despacho (CRD1 tipo S) de SBH."""
    if str(empresa_id or '') != '2':
        raise SapDiApiError('La consulta de direcciones de despacho sólo está disponible para SBH.')

    cliente_codigo = str(cliente_codigo or '').strip()
    if not cliente_codigo:
        raise SapDiApiError('Debe indicar el cliente SAP para consultar sus direcciones de despacho.')

    try:
        company_db = get_sap_company_db(2)
    except SapConfigError as exc:
        raise SapDiApiError(str(exc)) from exc
    if not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError('SAP_SBH_COMPANY_DB tiene un formato no válido.')

    sql = f'''
        SELECT
            D."CardCode" AS "cliente_codigo",
            D."Address" AS "direccion_codigo",
            D."AdresType" AS "tipo_direccion",
            D."Street" AS "calle",
            D."Block" AS "sector",
            D."City" AS "ciudad",
            D."County" AS "comuna_sap",
            D."State" AS "region_sap",
            D."Country" AS "pais",
            D."ZipCode" AS "codigo_postal"
        FROM "{company_db}"."CRD1" D
        INNER JOIN "{company_db}"."OCRD" C
            ON C."CardCode" = D."CardCode"
        WHERE D."CardCode" = ?
          AND D."AdresType" = 'S'
          AND C."CardType" = 'C'
        ORDER BY D."Address"
    '''
    return _rows(sql, [cliente_codigo])


def consultar_stock_fisico_despacho_sap(item_code, empresa_id=None):
    """Consulta informativa de existencia física por warehouse para un ItemCode."""
    if str(empresa_id or '') != '2':
        raise SapDiApiError('La consulta de stock físico de despacho sólo está disponible para SBH.')

    item_code = str(item_code or '').strip()
    if not item_code:
        raise SapDiApiError('Debe indicar el ItemCode para consultar stock físico SAP.')

    try:
        company_db = get_sap_company_db(2)
    except SapConfigError as exc:
        raise SapDiApiError(str(exc)) from exc
    if not HANA_IDENTIFIER_RE.match(company_db):
        raise SapDiApiError('SAP_SBH_COMPANY_DB tiene un formato no válido.')

    sql = f'''
        SELECT
            W."ItemCode" AS "item_code",
            W."WhsCode" AS "whs_code",
            H."WhsName" AS "whs_name",
            W."OnHand" AS "on_hand",
            W."IsCommited" AS "committed",
            W."OnOrder" AS "on_order",
            W."OnHand" - W."IsCommited" AS "net_available",
            I."InvntryUom" AS "unit"
        FROM "{company_db}"."OITW" W
        INNER JOIN "{company_db}"."OWHS" H
            ON H."WhsCode" = W."WhsCode"
        INNER JOIN "{company_db}"."OITM" I
            ON I."ItemCode" = W."ItemCode"
        WHERE W."ItemCode" = ?
          AND W."OnHand" > 0
        ORDER BY W."OnHand" DESC, W."WhsCode"
    '''
    warehouses = _rows(sql, [item_code])
    stock_total = sum(float(row.get('on_hand') or 0) for row in warehouses)
    unidad = next((str(row.get('unit') or '').strip() for row in warehouses if row.get('unit')), '')
    return {
        'ok': True,
        'available': True,
        'item_code': item_code,
        'unit': unidad,
        'stock_total': stock_total,
        'warehouses': warehouses,
    }
