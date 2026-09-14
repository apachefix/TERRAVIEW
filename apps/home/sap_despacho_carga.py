"""Consultas HANA de solo lectura, exclusivas de la carga DESPACHO SBH.

Vencimiento: OBTN.ExpDate (SAP DATE, sin zona horaria), ISO YYYY-MM-DD.
Stock: OBTQ.Quantity por ItemCode + SysNumber + WhsCode. No se usa InDate
como vencimiento. El maestro OBTN se enlaza por ItemCode + SysNumber.
"""
import re

from apps.integrations.sap_b1.sap_config import get_sap_company_db
from .sap_di_api import _rows


def _schema():
    schema = get_sap_company_db(2, for_write=False)
    if not re.fullmatch(r'[A-Za-z0-9_]+', schema):
        raise ValueError('CompanyDB SBH inválida.')
    return schema


def consultar_productos_acuerdo(abs_id):
    schema = _schema()
    return _rows(f'''
        SELECT A."AbsID" AS "sap_abs_id", A."Number" AS "numero_acuerdo",
               A."BpCode" AS "cliente_codigo", A."BpName" AS "cliente_nombre",
               A."NumAtCard" AS "oc_cliente", L."AgrLineNum" AS "linea_acuerdo",
               L."ItemCode" AS "item_code", L."ItemName" AS "item_name",
               L."InvntryUom" AS "unidad_medida",
               COALESCE(L."PlanQty", 0) - COALESCE(L."CumQty", 0) AS "saldo"
        FROM "{schema}"."OOAT" A
        JOIN "{schema}"."OAT1" L ON L."AgrNo" = A."AbsID"
        WHERE A."AbsID" = ? AND A."BpType" = 'C'
          AND A."Status" = 'A' AND L."LineStatus" = 'O'
        ORDER BY L."AgrLineNum"
    ''', [int(abs_id)])


def consultar_stock_producto(item_code):
    schema = _schema()
    return _rows(f'''
        SELECT Q."WhsCode" AS "warehouse_code", B."ItemCode" AS "item_code",
               B."DistNumber" AS "batch_number", Q."Quantity" AS "stock",
               TO_CHAR(B."ExpDate", 'yyyy-mm-dd') AS "fecha_vencimiento"
        FROM "{schema}"."OBTQ" Q
        JOIN "{schema}"."OBTN" B
          ON B."ItemCode" = Q."ItemCode" AND B."SysNumber" = Q."SysNumber"
        JOIN "{schema}"."OWHS" W ON W."WhsCode" = Q."WhsCode"
        WHERE Q."ItemCode" = ? AND Q."Quantity" > 0
          AND W."Inactive" = 'N'
        ORDER BY B."ExpDate" ASC NULLS LAST, B."DistNumber", Q."WhsCode"
    ''', [item_code])
