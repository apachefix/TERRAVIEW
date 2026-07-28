from django.db import connection

from .vars import *

import pandas as pd

def normalizarFileNameS3(filename):
    try:
        newname = filename.replace(" ", "")
        newname = newname.replace("-", "")
        newname = newname.replace(",", "")
        newname = newname.replace("/", "")
        newname = newname.replace("@", "")
        return newname.lower()
    except Exception as e:
        return filename

def logthis(modulo, operacion, descripcion, add1='', add2='', userid=0, empresa=0):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    INSERT INTO "SYSLOGGER" (
                          "LOG_FFECHAREGISTRO",
                          "US_NID_id",
                          "EMP_NID_id",
                          "LOG_CMODULO",
                          "LOG_COPERACION",
                          "LOG_CDESCRIPCION",
                          "LOG_CADD1",
                          "LOG_CADD2"
                      )
                      VALUES (
                          CURRENT_DATE,
                          {int(userid)},
                          {int(empresa)},
                          '{modulo}',
                          '{operacion}',
                          '{descripcion}',
                          '{add1}',
                          '{add2}'
                      );
                    '''
            cursor.execute(query)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        connection.rollback()
        return False

####################################################
# LISTAR OPCIONES DE MENU PARA EL CHOICES EN FORMS #
####################################################

def listarOpcionesTabla(retValue, retDisplay, tablename, orderfield, sortoption, whereclause = ""):
    resultado = listarTabla(retValue, retDisplay,
                            tablename, orderfield, sortoption, whereclause)
    return tuple(tuple(sub) for sub in resultado)

def listarTabla(retValue, retDisplay, tablename, orderfield, sortoption="DESC", whereclause=""):
    """
    Obtiene los datos de una tabla indicada

    Parameters
    ----------
    retValue : str
        indica el campo de tipo 'valor' que será retornado
    retDisplay : str
        indica el campo de tipo 'texto' que será retornado
    tablename : str
        indica el nombre de la tabla para leer
    orderfield : str
        indica el campo para ordenar
    sortoption : str
        default="DESC", indica la forma del ordenamiento
    whereclause=str
        default="", indica la clausula de filtro (NO INLUIR WHERE)

    Returns
    -------
    list
        Una lista de datos
    """

    with connection.cursor() as cursor:
        cquery = f'''SELECT '', 'Seleccione una opcion' UNION ALL 
                    SELECT {retValue}, {retDisplay}  FROM "{tablename}" '''
        if whereclause != "":
            cquery += f''' WHERE {whereclause} '''
        if orderfield != "" and sortoption != "":
            cquery += f''' ORDER BY "{orderfield}" {sortoption} '''
        cursor.execute(cquery)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado
    
def GetPreviewSecuenciaActiva(pk, empresa):
    """
    Obtiene solo las etapas ACTIVAS de una secuencia (SE_BHABILITADO = True)
    """
    with connection.cursor() as cursor:
        cquery = f''' 
            SELECT
            "ETAPA"."ET_CCODIGO",
            "CAMPO"."CA_CTIPO" AS "TYPE",
            "CAMPO"."CA_CVALORDEFAULT" AS "DEFAULT_VALUE",
            "CAMPO"."CA_CETIQUETA" AS "PLACEHOLDER",
            "CAMPO"."CA_NLARGO" AS "LARGO",
            "CAMPO"."CA_BOBLIGATORIO" AS "OBLIGATORIO",
            "CAMPO"."CA_CQUERY" as "QUERY",
            "CAMPO"."id" as "ID_CAMPO",
            "ETAPA"."id" as "ID_ETAPA"
            FROM "DETALLE_SECUENCIA"
            LEFT JOIN "DETALLE_ETAPA" on "DETALLE_ETAPA"."ET_NID_id" = "DETALLE_SECUENCIA"."ET_NID_id"
            LEFT JOIN "CAMPO" ON "CAMPO"."id" = "DETALLE_ETAPA"."CAMP_NID_id"
            LEFT JOIN "ETAPA" ON "ETAPA"."id" = "DETALLE_ETAPA"."ET_NID_id"
            WHERE "DETALLE_SECUENCIA"."SC_NID_id" = {pk}
            AND "DET_BHABILITADO" = TRUE
            AND "CAMPO"."CA_BHABILITADO" = TRUE
            AND "DETALLE_SECUENCIA"."SE_BHABILITADO" = TRUE
            AND "DETALLE_SECUENCIA"."SE_NPASO" IS NOT NULL
            AND "DETALLE_ETAPA"."DET_NPASO" IS NOT NULL
            ORDER BY "SE_NPASO" ASC, "DET_NPASO" ASC
        '''
        print(cquery)
        cursor.execute(cquery)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado

def GetPreviewEtapaConDatos(pk, citacion_id, secuencia_id):
    """
    Obtiene los campos de una etapa que tienen datos cargados para una citación específica
    """
    with connection.cursor() as cursor:
        cquery = f''' 
            SELECT
                "CAMPO"."CA_CTIPO" AS "TYPE",
                "CAMPO"."CA_CVALORDEFAULT" AS "DEFAULT_VALUE",
                "CAMPO"."CA_CPLACEMARK" AS "PLACEHOLDER",
                "CAMPO"."CA_NLARGO" AS "LARGO",
                "CAMPO"."CA_BOBLIGATORIO" AS "OBLIGATORIO",
                "CAMPO"."CA_CQUERY" AS "QUERY",
                "CAMPO"."id" AS "ID_CAMPO",
                "CAMPO"."CA_CETIQUETA" AS "ETIQUETA",
                "DATO_OPERACION"."DO_CVALOR" AS "VALOR_DATO",
                "DATO_OPERACION"."id" AS "ID_DATO"
            FROM "DETALLE_ETAPA"
            LEFT JOIN "CAMPO" ON "CAMPO"."id" = "DETALLE_ETAPA"."CAMP_NID_id"
            INNER JOIN "DATO_OPERACION" ON "DATO_OPERACION"."CAMP_NID_id" = "CAMPO"."id"
            WHERE "DETALLE_ETAPA"."ET_NID_id" = {pk}
            AND "DET_BHABILITADO" = TRUE
            AND "CAMPO"."CA_BHABILITADO" = TRUE
            AND "DATO_OPERACION"."CI_NID_id" = {citacion_id}
            AND "DATO_OPERACION"."SC_NID_id" = {secuencia_id}
            AND "DATO_OPERACION"."ET_NID_id" = {pk}
            ORDER BY "DET_NPASO" ASC
        '''
        cursor.execute(cquery)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado

def GetPreviewEtapa(pk):
    """
    Obtiene los datos de una tabla indicada

    Parameters
    ----------
    retValue : str
        indica el campo de tipo 'valor' que será retornado
    retDisplay : str
        indica el campo de tipo 'texto' que será retornado
    tablename : str
        indica el nombre de la tabla para leer
    orderfield : str
        indica el campo para ordenar
    sortoption : str
        default="DESC", indica la forma del ordenamiento
    whereclause=str
        default="", indica la clausula de filtro (NO INLUIR WHERE)

    Returns
    -------
    list
        Una lista de datos
    """


    with connection.cursor() as cursor:
        cquery = f''' 
            SELECT
                "CAMPO"."CA_CTIPO" AS "TYPE",
                "CAMPO"."CA_CVALORDEFAULT" AS "DEFAULT_VALUE",
                "CAMPO"."CA_CPLACEMARK" AS "PLACEHOLDER",
                "CAMPO"."CA_NLARGO" AS "LARGO",
                "CAMPO"."CA_BOBLIGATORIO" AS "OBLIGATORIO",
                "CAMPO"."CA_CQUERY" AS "QUERY",
                "CAMPO"."id" AS "ID_CAMPO",
                "CAMPO"."CA_CETIQUETA" AS "ETIQUETA"
            FROM "DETALLE_ETAPA"
            LEFT JOIN "CAMPO" ON "CAMPO"."id" = "DETALLE_ETAPA"."CAMP_NID_id"
            WHERE "DETALLE_ETAPA"."ET_NID_id" = {pk}
            AND "DET_BHABILITADO" = TRUE
            AND "CAMPO"."CA_BHABILITADO" = TRUE 
            ORDER BY "DET_NPASO" ASC
        '''
        cursor.execute(cquery)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado
def GetPreviewSecuencia(pk,empresa):
    """
    Obtiene los datos de una tabla indicada

    Parameters
    ----------
    retValue : str
        indica el campo de tipo 'valor' que será retornado
    retDisplay : str
        indica el campo de tipo 'texto' que será retornado
    tablename : str
        indica el nombre de la tabla para leer
    orderfield : str
        indica el campo para ordenar
    sortoption : str
        default="DESC", indica la forma del ordenamiento
    whereclause=str
        default="", indica la clausula de filtro (NO INLUIR WHERE)

    Returns
    -------
    list
        Una lista de datos
    """

    with connection.cursor() as cursor:
        cquery = f''' 
            SELECT
            "ETAPA"."ET_CCODIGO",
            "CAMPO"."CA_CTIPO" AS "TYPE",
            "CAMPO"."CA_CVALORDEFAULT" AS "DEFAULT_VALUE",
            "CAMPO"."CA_CETIQUETA" AS "PLACEHOLDER",
            "CAMPO"."CA_NLARGO" AS "LARGO",
            "CAMPO"."CA_BOBLIGATORIO" AS "OBLIGATORIO",
            "CAMPO"."CA_CQUERY" as "QUERY",
            "CAMPO"."id" as "ID_CAMPO",
            "ETAPA"."id" as "ID_ETAPA"
            FROM "DETALLE_SECUENCIA"
            LEFT JOIN "DETALLE_ETAPA" on "DETALLE_ETAPA"."ET_NID_id" = "DETALLE_SECUENCIA"."ET_NID_id"
            LEFT JOIN "CAMPO" ON "CAMPO"."id" = "DETALLE_ETAPA"."CAMP_NID_id"
            LEFT JOIN "ETAPA" ON "ETAPA"."id" = "DETALLE_ETAPA"."ET_NID_id"
            WHERE "DETALLE_SECUENCIA"."SC_NID_id" = {pk}
            AND "DET_BHABILITADO" = TRUE
            AND "CAMPO"."CA_BHABILITADO" = TRUE
            AND "DETALLE_SECUENCIA"."SE_BHABILITADO" = TRUE
            AND "DETALLE_SECUENCIA"."SE_NPASO" IS NOT NULL
            AND "DETALLE_ETAPA"."DET_NPASO" IS NOT NULL
            ORDER BY "SE_NPASO" ASC, "DET_NPASO" ASC
        '''
        print(cquery)
        cursor.execute(cquery)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado

def QueryParam(query):
    """
    Obtiene los datos de una tabla indicada

    Parameters
    ----------
    retValue : str
        indica el campo de tipo 'valor' que será retornado
    retDisplay : str
        indica el campo de tipo 'texto' que será retornado
    tablename : str
        indica el nombre de la tabla para leer
    orderfield : str
        indica el campo para ordenar
    sortoption : str
        default="DESC", indica la forma del ordenamiento
    whereclause=str
        default="", indica la clausula de filtro (NO INLUIR WHERE)

    Returns
    -------
    list
        Una lista de datos
    """

    with connection.cursor() as cursor:
        cursor.execute(query)
        resultado = cursor.fetchall()
        if resultado == None:
            return None
        return resultado

###################################################
#############  DOCUMENTOS DE CONDUCTOR ############
###################################################

def listar_documentos_conductor(id_conductor):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            "DCON_CTIPO", 
                            "DCON_FFECHAVENCIMIENTO", 
                            "DCON_FFECHAEMISION", 
                            "DCON_CRUTADOC"
                        FROM "DOCUMENTO_CONDUCTOR"
                        WHERE 
                            "CON_NID_id" = {id_conductor} AND
                            "DCON_BHABILITADO" = TRUE;
                    '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def listado_y_estado_documentos_xconductor(id_conductor):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            ld."LIS_CNOMBREDOCUMENTO",
                            CASE
                                WHEN dc.id IS NULL THEN 'NO CARGADO'
                                ELSE 'CARGADO'
                            END AS ESTADO,
                            CASE
                                WHEN dc."DCON_FFECHAVENCIMIENTO" IS NULL THEN '--'
                                ELSE 
                                    CASE 
                                        WHEN dc."DCON_FFECHAVENCIMIENTO" > CURRENT_DATE THEN 'AL DÍA'
                                        WHEN dc."DCON_FFECHAVENCIMIENTO" < CURRENT_DATE THEN 'VENCIDO'
                                    END
                            END AS ESTADO_DOCUMENTO,
                            dc."DCON_CRUTADOC",
                            dc."id"
                        FROM "LISTADO_DOCUMENTO" AS ld
                        LEFT JOIN
                            "DOCUMENTO_CONDUCTOR" AS dc ON ld."LIS_CNOMBREDOCUMENTO" = dc."DCON_CTIPO" AND dc."CON_NID_id" = {id_conductor} AND dc."DCON_BHABILITADO" = TRUE
                        WHERE  
                            ld."LIS_CGRUPO" = 'Conductor' AND 
                            ld."LIS_BHABILITADO" = TRUE
                    '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def actualizar_documentos_antiguos_xtipo(id_conductor, tipo_documento):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        UPDATE "DOCUMENTO_CONDUCTOR" 
                        SET "DCON_BHABILITADO" = FALSE 
                        WHERE 
                            "CON_NID_id" = {id_conductor} AND 
                            "DCON_CTIPO" = '{tipo_documento}' AND 
                            "DCON_BHABILITADO" = TRUE
                        '''
            print(cquery)
            cursor.execute(cquery)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        return False

def getCantEtapaSalida(empresa,secuencia):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                SELECT 
                    COUNT("DETALLE_ETAPA"."id")
                FROM "DETALLE_SECUENCIA" 
                LEFT JOIN "DETALLE_ETAPA" ON "DETALLE_ETAPA"."ET_NID_id" = "DETALLE_SECUENCIA"."ET_NID_id"
                LEFT JOIN "ETAPA" ON "ETAPA"."id" = "DETALLE_ETAPA"."ET_NID_id"
                WHERE "DETALLE_SECUENCIA"."SC_NID_id" = {secuencia}
                AND "ETAPA"."ET_CTIPO" = 'SALIDA'
                        '''
            cursor.execute(cquery)
            resultado = cursor.fetchone()  # fetchall se utliza para llamar a mas de un valor
            if resultado == None:
                return False
            if resultado[0] > 0:
                return True
            return False
    except Exception as e:
        print(e)
        return False

def getEtapaSalida(empresa,secuencia):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                SELECT 
                    Distinct "ETAPA"."id",
                    "ETAPA"."ET_CCODIGO"
                FROM "DETALLE_SECUENCIA" 
                LEFT JOIN "DETALLE_ETAPA" ON "DETALLE_ETAPA"."ET_NID_id" = "DETALLE_SECUENCIA"."ET_NID_id"
                LEFT JOIN "ETAPA" ON "ETAPA"."id" = "DETALLE_ETAPA"."ET_NID_id"
                WHERE "DETALLE_SECUENCIA"."SC_NID_id" = {secuencia}
                AND "DETALLE_SECUENCIA"."SE_BHABILITADO" = True
                AND "ETAPA"."ET_CTIPO" = 'SALIDA'
                        '''
            cursor.execute(cquery)
            resultado = cursor.fetchone()  # fetchall se utliza para llamar a mas de un valor
            if resultado == None:
                return None
            return resultado[0] ,resultado[1]
    except Exception as e:
        print(e)
        return None

def getEtapaAdicionales(id_etapa, id_secuencia):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        "ETAPA"."ET_CCODIGO"
                    FROM "DETALLE_SECUENCIA"
                    INNER JOIN
                        "ETAPA" ON "ETAPA"."id" = "DETALLE_SECUENCIA"."ET_NID_id"
                    WHERE
                        "ETAPA"."ET_NID_REF_ADICIONALES" = {id_etapa} AND
                        "DETALLE_SECUENCIA"."SC_NID_id" = {id_secuencia}
                    '''
            print(query)
            cursor.execute(query)
            resultado = cursor.fetchone()
            if resultado == None:
                return None
            return resultado[0]
    except Exception as e:
        print(e)
        return None
    
###################################################
###############  DOCUMENTOS DE CAMION #############
###################################################

def listar_documentos_camion(id_camion):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            DCA_CTIPO, 
                            DCA_FFECHAVENCIMIENTO, 
                            DCA_FFECHAEMISION, 
                            DCA_CRUTADOC
                        FROM DOCUMENTOS_CAMION
                        WHERE 
                            CA_NID_id = {id_camion} AND
                            DCA_CHABILITADO = 1
                    '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def listado_y_estado_documentos_xcamion(id_camion):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            ld."LIS_CNOMBREDOCUMENTO",
                            CASE
                                WHEN dc.id IS NULL THEN 'NO CARGADO'
                                ELSE 'CARGADO'
                            END AS ESTADO,
                            CASE
                                WHEN dc."DCA_FFECHAVENCIMIENTO" IS NULL THEN '--'
                                ELSE 
                                    CASE 
                                        WHEN dc."DCA_FFECHAVENCIMIENTO" > CURRENT_DATE THEN 'AL DÍA'
                                        WHEN dc."DCA_FFECHAVENCIMIENTO" < CURRENT_DATE THEN 'VENCIDO'
                                    END
                            END AS ESTADO_DOCUMENTO,
                            dc."DCA_CRUTADOC",
                            dc."id"
                        FROM "LISTADO_DOCUMENTO" AS ld
                        LEFT JOIN
                            "DOCUMENTO_CAMION" AS dc ON ld."LIS_CNOMBREDOCUMENTO" = dc."DCA_CTIPO" AND dc."CA_NID_id" = {id_camion} AND dc."DCA_BHABILITADO" = TRUE
                        WHERE  
                            ld."LIS_CGRUPO" = 'Camion' AND 
                            ld."LIS_BHABILITADO" = TRUE
                    '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def actualizar_documentos_antiguos_xcamion(id_camion, tipo_documento):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        UPDATE "DOCUMENTO_CAMION" 
                        SET "DCA_BHABILITADO" = FALSE 
                        WHERE 
                            "CA_NID_id" = {id_camion} AND 
                            "DCA_CTIPO" = '{tipo_documento}' AND 
                            "DCA_BHABILITADO" = TRUE
                        '''
            print(cquery)
            cursor.execute(cquery)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        return False

###################################################
#############  DOCUMENTOS DE PROVEEDOR  ###########
###################################################

def listar_documentos_proveedor(id_proveedor):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            DSN_CTIPO, 
                            DSN_FFECHAVENCIMIENTO, 
                            DSN_FFECHAEMISION, 
                            DSN_CRUTADOC
                        FROM DOCUMENTOS_PROVEEDOR
                        WHERE 
                            PRO_NID_id = {id_proveedor} AND
                            DSN_CHABILITADO = 1
                    '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def listado_y_estado_documentos_xproveedor(id_proveedor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        ld."LIS_CNOMBREDOCUMENTO",
                        CASE
                            WHEN dc.id IS NULL THEN 'NO CARGADO'
                            ELSE 'CARGADO'
                        END AS ESTADO,
                        CASE
                                WHEN dc."DSN_FFECHAVENCIMIENTO" IS NULL THEN '--'
                                ELSE 
                                    CASE 
                                        WHEN dc."DSN_FFECHAVENCIMIENTO" > CURRENT_DATE THEN 'AL DÍA'
                                        WHEN dc."DSN_FFECHAVENCIMIENTO" < CURRENT_DATE THEN 'VENCIDO'
                                    END
                            END AS ESTADO_DOCUMENTO,
                            dc."DSN_CRUTADOC",
                            dc."id"
                    FROM "LISTADO_DOCUMENTO" AS ld
                    LEFT JOIN
                        "DOCUMENTO_SOCIONEGOCIO" AS dc ON ld."LIS_CNOMBREDOCUMENTO" = dc."DSN_CTIPO" AND dc."SN_NID_id" = {id_proveedor} AND dc."DSN_BHABILITADO" = TRUE
                    WHERE  
                        ld."LIS_CGRUPO" = 'Proveedor' AND 
                        ld."LIS_BHABILITADO" = TRUE
                    '''
            print(query)
            cursor.execute(query)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def actualizar_documentos_antiguos_xproveedor(id_proveedor, tipo_documento):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        UPDATE "DOCUMENTO_SOCIONEGOCIO" 
                        SET "DSN_BHABILITADO" = FALSE 
                        WHERE 
                            "SN_NID_id" = {id_proveedor} AND 
                            "DSN_CTIPO" = '{tipo_documento}' AND 
                            "DSN_BHABILITADO" = TRUE
                        '''
            print(cquery)
            cursor.execute(cquery)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        return False

###################################################
#############  DOCUMENTOS DE CLIENTE  #############
###################################################

def listado_y_estado_documentos_xcliente(id_cliente):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        ld."LIS_CNOMBREDOCUMENTO",
                        CASE
                            WHEN dc.id IS NULL THEN 'NO CARGADO'
                            ELSE 'CARGADO'
                        END AS ESTADO,
                        CASE
                                WHEN dc."DSN_FFECHAVENCIMIENTO" IS NULL THEN '--'
                                ELSE 
                                    CASE 
                                        WHEN dc."DSN_FFECHAVENCIMIENTO" > CURRENT_DATE THEN 'AL DÍA'
                                        WHEN dc."DSN_FFECHAVENCIMIENTO" < CURRENT_DATE THEN 'VENCIDO'
                                    END
                            END AS ESTADO_DOCUMENTO,
                            dc."DSN_CRUTADOC",
                            dc."id"
                    FROM "LISTADO_DOCUMENTO" AS ld
                    LEFT JOIN
                        "DOCUMENTO_SOCIONEGOCIO" AS dc ON ld."LIS_CNOMBREDOCUMENTO" = dc."DSN_CTIPO" AND dc."SN_NID_id" = {id_cliente} AND dc."DSN_BHABILITADO" = TRUE
                    WHERE  
                        ld."LIS_CGRUPO" = 'Cliente' AND 
                        ld."LIS_BHABILITADO" = TRUE
                    '''
            print(query)
            cursor.execute(query)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            return resultado
    except Exception as e:
        print(e)
        return None

def actualizar_documentos_antiguos_xcliente(id_cliente, tipo_documento):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        UPDATE "DOCUMENTO_SOCIONEGOCIO" 
                        SET "DSN_BHABILITADO" = FALSE 
                        WHERE 
                            "SN_NID_id" = {id_cliente} AND 
                            "DSN_CTIPO" = '{tipo_documento}' AND 
                            "DSN_BHABILITADO" = TRUE
                        '''
            print(cquery)
            cursor.execute(cquery)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        return False


###################################################
##########  SOCIOS DE NEGOCIO Y RUTAS #############
###################################################

def listar_socios_negocio(id_empresa):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            id, 
                            "SN_CRAZONSOCIAL"
                        FROM 
                            "SOCIONEGOCIO" 
                        WHERE 
                            "EP_NID_id" = {id_empresa} AND 
                            "SN_BHABILITADO" = TRUE AND 
                            "SN_CTIPO" = 'C'
                        '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            print(resultado)
            return resultado
    except Exception as e:
        print(e)
        return None

def listar_rutas_socios(id_socio):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            id, 
                            "RUT_CNOMBRE"
                        FROM "RUTA" 
                        WHERE 
                            "SN_NID_id" = {id_socio}
                            AND "RUT_BHABILITADO" = True
                        '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            print(resultado)
            return resultado
    except Exception as e:
        print(e)
        return None
    
##########################################################################
###########################   CALENDARIO   ###############################
##########################################################################

def get_list_planificaciones(EP_NID = ''):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        pl."id",
                        to_char(pl."PL_FFECHAINICIO", 'YYYY-MM-DD"T"HH24:MI:SS'),
                        to_char(pl."PL_FFECHAFIN", 'YYYY-MM-DD"T"HH24:MI:SS'),
                        pl."PL_NCANTIDADCUPOS",
                        COALESCE(COUNT(ci."id"), 0)
                    FROM "PLANIFICACION" AS pl
                    LEFT JOIN
                        "CITACION" AS ci ON pl."id" = ci."PL_NID_id"
                    '''
            if EP_NID != '':
                query += f'''
                        WHERE
                            pl."EP_NID_id" = {EP_NID}
                        '''
            query += '''
                    GROUP BY pl."id", pl."PL_FFECHAINICIO", pl."PL_FFECHAFIN", pl."PL_NCANTIDADCUPOS"
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            if not result:
                return None
            return result
    except Exception as e:
        print(e)
        return None

def get_list_citaciones_xplanificación(id_planificacion):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        DISTINCT ON (ci."id")
                        sc."SE_CNOMBRE",
                        sc."SE_CCODIGO",
                        COALESCE(et."ET_CNOMBRE", ''),
                        COALESCE(et."ET_CCODIGO", ''),
                        COALESCE(ea."EA_NPASO", '1'),
                        to_char(ci."CI_FFECHACITACION", 'DD/MM/YYYY HH24:MI'),
                        ci."CI_BAVISADO",
                        ci."CI_BCONFIRMADO",
                        ci."CI_BARRIBADO",
                        ci."CI_NCUPO",
                        ci."CI_NVALORTARIFA"
                    FROM "CITACION" AS ci
                    INNER JOIN
                        "SECUENCIA" AS sc ON ci."SC_NID_id" = sc."id"
                    LEFT JOIN
                        "ETAPA_ACCION" AS ea ON ci."id" = ea."CI_NID_id"
                    LEFT JOIN
                        "ETAPA" AS et ON ea."ET_NID_id" = et."id"
                    INNER JOIN
                        "SOCIONEGOCIO" AS sn ON ci."SN_NID_id" = sn."id"
                    INNER JOIN
                        "CONDUCTOR" AS con ON ci."CON_NID_id" = con."id"
                    INNER JOIN
                        "SOCIONEGOCIO" AS sn1 ON con."SN_NID_id" = sn1."id"               
                    WHERE ci."PL_NID_id" = {id_planificacion}
                    ORDER BY
                        ci."id" DESC, ea."EA_FFECHAREGISTRO" DESC NULLS LAST;
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            if not result:
                return None
            return result
    except Exception as e:
        print(e)
        return None
    
###################################################
############# PROVINCIAS Y COMUNAS ################
###################################################

def listar_provincias(id_region):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            id, 
                            "PV_CNOMBRE"
                        FROM "PROVINCIA"
                        WHERE
                            "RG_NID_id" = {id_region}
                        '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            print(resultado)
            return resultado
    except Exception as e:
        print(e)
        return None

def listar_comunas(id_provincia):
    try:
        with connection.cursor() as cursor:
            cquery = f'''
                        SELECT 
                            id, 
                            "COM_CNOMBRE"
                        FROM "COMUNA"
                        WHERE
                            "PV_NID_id" = {id_provincia}
                        '''
            print(cquery)
            cursor.execute(cquery)
            resultado = cursor.fetchall()  # fetchall se utliza para llamar a mas de un valor
            print(resultado)
            return resultado
    except Exception as e:
        print(e)
        return None
    
###################################################
################# CITACION ########################
###################################################

def get_list_conductores_xproveedor(id_proveedor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        id,
                        "CON_CRUT" || ' - ' || "CON_CNOMBRE" || ' ' || "CON_CAPELLIDO"
                    FROM "CONDUCTOR"
                    WHERE
                        "SN_NID_id" = {id_proveedor}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_list_camiones_xproveedor(id_proveedor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        id,
                        COALESCE("CAM_CMARCA", 'Sin modelo') || ' - ' || "CAM_CPATENTE"
                    FROM "CAMION"
                    WHERE
                        "CAM_BHABILITADO" = True AND
                        "SN_NID_id" = {id_proveedor}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None 

def get_list_conductores_xempresa(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        id,
                        "CON_CRUT" || ' - ' || "CON_CNOMBRE" || ' ' || "CON_CAPELLIDO"
                    FROM "CONDUCTOR"
                    WHERE
                        "EP_NID_id" = {id_empresa} AND
                        "CON_BHABILITADO" = True AND
                        id NOT IN (SELECT "CON_NID_id" FROM "CITACION" WHERE "CI_CESTADO" <> 'TERMINADO')
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None
    
def get_list_camiones_xempresa(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "id",
                        "CAM_CMARCA" || ' - ' || "CAM_CPATENTE"
                    FROM "CAMION"
                    WHERE
                        "EP_NID_id" = {id_empresa} AND
                        "CAM_BHABILITADO" = True AND
                        id NOT IN (SELECT "CA_NID_id" FROM "CITACION" WHERE "CI_CESTADO" <> 'TERMINADO')
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_last_conductor_xcamion(id_camion, id_proveedor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "CONDUCTOR"."id"
                    FROM "CITACION"
                    INNER JOIN
                        "CONDUCTOR" ON "CITACION"."CON_NID_id" = "CONDUCTOR"."id"
                    WHERE
                        "CONDUCTOR"."SN_NID_id" = {id_proveedor} AND
                        "CITACION"."CA_NID_id" = {id_camion} AND
                        "CITACION"."CI_BHABILITADO" = TRUE
                    ORDER BY "CITACION"."id" DESC
                    LIMIT 1;
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            if not result:
                return None
            return result[0]
    except Exception as e:
        print(e)
        return None

def GetCamposEtapa(id_etapa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "CAMPO"."id"
                    FROM "CAMPO"
                    INNER JOIN 
                        "DETALLE_ETAPA" ON "CAMPO"."id" = "DETALLE_ETAPA"."CAMP_NID_id"
                    WHERE 
                        "DETALLE_ETAPA"."ET_NID_id" = {id_etapa} AND 
                        "CAMPO"."CA_BHABILITADO" = True and
                        "DETALLE_ETAPA"."DET_BHABILITADO" = True
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def GetDatosSecuencia(id_secuencia, id_empresa, id_citacion):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "ETAPA"."ET_CCODIGO",
                        "CAMPO"."CA_CTIPO" AS "TYPE",
                        "CAMPO"."CA_CETIQUETA" AS "ETIQUETA",
                        "DATO_OPERACION"."DO_CVALOR" AS "VALOR"
                    FROM "DATO_OPERACION"
                    INNER JOIN 
                        "ETAPA" ON "DATO_OPERACION"."ET_NID_id" = "ETAPA"."id"
                    INNER JOIN
                        "CAMPO" ON "DATO_OPERACION"."CAMP_NID_id" = "CAMPO"."id"
                    INNER JOIN
                        "DETALLE_SECUENCIA" ON "DATO_OPERACION"."SC_NID_id" = "DETALLE_SECUENCIA"."SC_NID_id"
                    INNER JOIN
                        "DETALLE_ETAPA" ON "DATO_OPERACION"."ET_NID_id" = "DETALLE_ETAPA"."ET_NID_id"
                    WHERE 
                        "DATO_OPERACION"."CI_NID_id" = {id_citacion} AND 
                        "DETALLE_SECUENCIA"."EP_NID_id" = {id_empresa} AND 
                        "DETALLE_SECUENCIA"."SC_NID_id" = {id_secuencia}
                    ORDER BY "DETALLE_SECUENCIA"."SE_NPASO", "DETALLE_ETAPA"."DET_NPASO" ASC
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def GetCampoValidateSap(id_etapa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                        SELECT 
                            REGEXP_REPLACE("ETAPA"."ET_CCODIGO", '\\s', '', 'g') || '_' || CAST("CAMPO"."id" AS VARCHAR)
                        FROM "DETALLE_ETAPA"
                        INNER JOIN 
                            "CAMPO" ON "DETALLE_ETAPA"."CAMP_NID_id" = "CAMPO"."id"
                        INNER JOIN
                            "ETAPA" ON "DETALLE_ETAPA"."ET_NID_id" = "ETAPA"."id"
                        WHERE 
                            "DETALLE_ETAPA"."ET_NID_id" = {id_etapa} AND
                            "DETALLE_ETAPA"."DET_BHABILITADO" = True AND
                            "CAMPO"."CA_BHABILITADO" = True AND
                            "CAMPO"."CA_BVALIDARSAP" = True
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

###################################################
################# PERFILAMIENTO ###################
###################################################

def tiene_permiso_perfil(vista, perfil):
    try:
        with connection.cursor() as cursor:
            cursor.execute('''
                SELECT EXISTS (
                    SELECT 1
                    FROM "PERMISO"
                    WHERE "VI_NID_id" = %s AND "PR_NID_id" = %s AND "PE_BHABILITADO" = TRUE
                );
            ''', [vista.id, perfil.id])
            return cursor.fetchone()[0]
    except Exception as e:
        print(e)
        return None
    
def tiene_perfil_usuario(vista, perfil):
    try:
        with connection.cursor() as cursor:
            cursor.execute('''
                SELECT EXISTS (
                    SELECT 1
                    FROM "PERFIL_USUARIO"
                    WHERE "US_NID_id" = %s AND "PR_NID_id" = %s AND "PE_BHABILITADO" = TRUE
                );
            ''', [vista.id, perfil.id])
            return cursor.fetchone()[0]
    except Exception as e:
        print(e)
        return None

###################################################
################# PROFORMA ########################
###################################################

def get_list_citaciones_proforma(proveedor, fecha_desde, fecha_hasta, tipo_citacion, empresa):
    from django.db import connection
    
    try:
        with connection.cursor() as cursor:
            query = '''
                    SELECT
                        "CITACION"."id" AS "numero_citacion",
                        "CITACION"."PL_NID_id" AS "PLANIFICACION",
                        TO_CHAR("CITACION"."CI_FFECHACITACION", 'DD/MM/YYYY HH24:MI') "fecha_citacion",
                        COALESCE(sc."SE_CCODIGO" || ' - ' || sc."SE_CNOMBRE", '') "secuencia",
                        COALESCE(cl."SN_CRAZONSOCIAL", '') "cliente",
                        COALESCE(con."CON_CNOMBRE" || ' ' || con."CON_CAPELLIDO" , '') "conductor",
                        COALESCE(cam."CAM_CPATENTE", '') "camion",
                        COALESCE(pro."SN_CRAZONSOCIAL", '') "proveedor",
                        COALESCE(tg."TAR_CNOMBRETARIFA", '') "nombre_tarifa",
                        COALESCE("CITACION"."CI_NVALORTARIFA", 0) "tarifa",
                        COALESCE(tg."TAR_CDIVISA", '') "divisa",
                        COALESCE(SUM(cie."CIE_NVALOR"), 0) "extras_ingreso",
                        COALESCE(SUM(cie2."CIE_NVALOR"), 0) "extras_descuento",
                        COALESCE("CITACION"."CI_CTIPODOCUMENTO", '') "tipo_documento",
                        CASE "CITACION"."CI_CTIPO"
                            WHEN 'DESPACHO' THEN "DATO_OPERACION"."DO_CVALOR"
                            ELSE "CITACION"."CI_CNUMERODOCUMENTO"
                        END AS "numero_documento"
                    FROM "CITACION"
                    LEFT JOIN "SOCIONEGOCIO" AS cl ON "CITACION"."SN_NID_id" = cl."id"
                    LEFT JOIN "RUTA" AS r ON "CITACION"."RUT_NID_id" = r."id"
                    LEFT JOIN "CONDUCTOR" AS con ON "CITACION"."CON_NID_id" = con."id"
                    LEFT JOIN "CAMION" AS cam ON "CITACION"."CA_NID_id" = cam."id"
                    LEFT JOIN "SECUENCIA" AS sc ON "CITACION"."SC_NID_id" = sc."id"
                    LEFT JOIN "CITACION_EXTRA" AS cie ON "CITACION"."id" = cie."CI_NID_id" and cie."CIE_BINGRESO" = True
                    LEFT JOIN "CITACION_EXTRA" AS cie2 ON "CITACION"."id" = cie2."CI_NID_id" and cie2."CIE_BINGRESO" = False
                    LEFT JOIN "SOCIONEGOCIO" AS pro ON "CITACION"."PRO_NID_id" = pro."id"
                    LEFT JOIN "TARIFA_GLOBAL" AS tg ON "CITACION"."TAR_NID_id" = tg."id"
                    LEFT JOIN "DATO_OPERACION" ON "CITACION"."id" = "DATO_OPERACION"."CI_NID_id" AND "DATO_OPERACION"."CAMP_NID_id" = 38
                    INNER JOIN (
                        SELECT
                            "CI_NID_id",
                            MIN("EP_NID_id") AS "EP_NID_id"
                        FROM "CAMION_PATIO"
                        WHERE "CPA_CESTADO" = 'ASOCIADO_CITACION'
                        GROUP BY "CI_NID_id"
                        HAVING
                            COUNT(*) = 1
                            AND MAX(UPPER(TRIM(COALESCE("transporte_a_cargo", '')))) = 'TERRAMAR'
                    ) AS cp ON cp."CI_NID_id" = "CITACION"."id"
                        AND cp."EP_NID_id" = "CITACION"."EP_NID_id"
                    WHERE
                        "CITACION"."CI_CESTADO" = 'TERMINADO' AND
                        "CITACION"."CI_BHABILITADO" = True AND
                        "CITACION"."id" NOT IN (SELECT "CI_NID_id" FROM "CITACION_PROFORMA")
                    '''
            
            params = []
            
            if proveedor and proveedor != 'None':
                query += ' AND pro."id" = %s'
                params.append(int(proveedor))
            
            if fecha_desde and fecha_desde != 'None':
                query += ' AND "CITACION"."CI_FFECHAREGISTRO"::date >= %s'
                params.append(fecha_desde)

            if fecha_hasta and fecha_hasta != 'None':
                query += ' AND "CITACION"."CI_FFECHAREGISTRO"::date <= %s'
                params.append(fecha_hasta)
                        
            if tipo_citacion and tipo_citacion != 'None':
                query += ' AND "CITACION"."CI_CTIPO" = %s'
                params.append(tipo_citacion)
            
            if empresa and empresa != 'None':
                query += ' AND "CITACION"."EP_NID_id" = %s'
                params.append(int(empresa))
            
            query += '''
                        AND "CITACION"."CI_BCONFORME" = TRUE
                    GROUP BY
                        "CITACION"."id",
                        "CITACION"."CI_CTIPO",
                        sc."SE_CCODIGO",
                        sc."SE_CNOMBRE",
                        cl."SN_CRAZONSOCIAL",
                        con."CON_CNOMBRE",
                        con."CON_CAPELLIDO",
                        cam."CAM_CPATENTE",
                        pro."SN_CRAZONSOCIAL",
                        tg."TAR_CNOMBRETARIFA",
                        "CITACION"."CI_NVALORTARIFA",
                        tg."TAR_CDIVISA",
                        "CITACION"."CI_CTIPODOCUMENTO",
                        "DATO_OPERACION"."DO_CVALOR",
                        "CITACION"."CI_CNUMERODOCUMENTO"
                    ORDER BY "CITACION"."id" DESC
                    '''
            
            print("=== EJECUTANDO QUERY ===")
            cursor.execute(query, params)
            
            # Intentar obtener resultados de diferentes formas
            print("=== INTENTANDO FETCHALL ===")
            result = cursor.fetchall()
            print(f"Fetchall retornó: {len(result)} filas")
            
            # Si fetchall no funciona, intentar con fetchone
            if not result:
                print("=== INTENTANDO CON NUEVA EJECUCIÓN ===")
                cursor.execute(query, params)
                rows = []
                while True:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    rows.append(row)
                print(f"Fetchone retornó: {len(rows)} filas")
                result = rows
            
            return result
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_list_citaciones_xproveedor(id_proveedor, empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "CITACION"."id",
                        CAST("CITACION"."id" AS VARCHAR) || ' || ' ||
                        COALESCE("CONDUCTOR"."CON_CNOMBRE" || ' ' || "CONDUCTOR"."CON_CAPELLIDO", 'Sin Conductor') || ' || ' ||
                        COALESCE("CAMION"."CAM_CPATENTE", 'Sin Patente') || ' || ' ||
                        COALESCE("SOCIONEGOCIO"."SN_CRAZONSOCIAL", 'Sin Cliente') || ' || ' ||
                        COALESCE("RUTA"."RUT_CNOMBRE", 'Sin Ruta') || ' || $ ' ||
                        COALESCE(CAST(CAST("CITACION"."CI_NVALORTARIFA" AS INTEGER) AS VARCHAR), '0')
                    FROM "CITACION"
                    LEFT JOIN
                        "CONDUCTOR" ON "CITACION"."CON_NID_id" = "CONDUCTOR"."id"
                    LEFT JOIN
                        "SOCIONEGOCIO" ON "CITACION"."SN_NID_id" = "SOCIONEGOCIO"."id"
                    LEFT JOIN
                        "RUTA" ON "CITACION"."RUT_NID_id" = "RUTA"."id"
                    LEFT JOIN
                        "CAMION" ON "CITACION"."CA_NID_id" = "CAMION"."id"
                    LEFT JOIN
                        "TARIFA_GLOBAL" ON "CITACION"."TAR_NID_id" = "TARIFA_GLOBAL"."id"
                    WHERE 
                        "CITACION"."CI_CESTADO" = 'TERMINADO' AND 
                        "CITACION"."CI_BHABILITADO" = True AND
                        "CITACION"."PRO_NID_id" = {id_proveedor} AND
                        "CITACION"."id" NOT IN (SELECT "CI_NID_id" FROM "CITACION_PROFORMA") AND
                        "CITACION"."CI_BCONFORME" = TRUE AND
                        "CITACION"."EP_NID_id" = {empresa}
                    ORDER BY "CITACION"."id" DESC
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_list_extras_ingreso(proforma_id):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        CAST("EXTRA"."id" AS INT),
                        "EXTRA"."EXT_CNOMBRE",
                        SUM("EXTRA_PROFORMA"."EPR_NVALOR")
                    FROM "EXTRA_PROFORMA"
                    INNER JOIN
                        "CITACION_EXTRA" ON "EXTRA_PROFORMA"."CIE_NID_id" = "CITACION_EXTRA"."id"
                    INNER JOIN
                        "EXTRA" ON "CITACION_EXTRA"."EXT_NID_id" = "EXTRA"."id"
                    WHERE 
                        "EXTRA_PROFORMA"."PRO_NID_id" = {proforma_id} AND 
                        "EXTRA_PROFORMA"."EPR_BINGRESO" = True AND
                        "EXTRA_PROFORMA"."EPR_BHABILITADO" = True
                    GROUP BY "EXTRA"."id", "EXTRA"."EXT_CNOMBRE"
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None
    
def get_list_extras_descuento(proforma_id):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        CAST("EXTRA"."id" AS INT),
                        "EXTRA"."EXT_CNOMBRE",
                        SUM("EXTRA_PROFORMA"."EPR_NVALOR")
                    FROM "EXTRA_PROFORMA"
                    INNER JOIN
                        "CITACION_EXTRA" ON "EXTRA_PROFORMA"."CIE_NID_id" = "CITACION_EXTRA"."id"
                    INNER JOIN
                        "EXTRA" ON "CITACION_EXTRA"."EXT_NID_id" = "EXTRA"."id"
                    WHERE 
                        "EXTRA_PROFORMA"."PRO_NID_id" = {proforma_id} AND 
                        "EXTRA_PROFORMA"."EPR_BINGRESO" = False AND
                        "EXTRA_PROFORMA"."EPR_BHABILITADO" = True
                    GROUP BY "EXTRA"."id", "EXTRA"."EXT_CNOMBRE"
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

###################################################
############### DETALLE SECUENCIA #################
###################################################

def update_detalle_secuencia(id_secuencia, id_empresa, paso):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    UPDATE "DETALLE_SECUENCIA"
                    SET "SE_NPASO" = "SE_NPASO" - 1
                    WHERE 
                        "EP_NID_id" = {id_empresa} AND 
                        "SC_NID_id" = {id_secuencia} AND
                        "SE_NPASO" > {paso}
                    '''
            print(query)
            cursor.execute(query)
            connection.commit()
            return True
    except Exception as e:
        connection.rollback()
        print(e)
        return None
    
def GetEtapaLinea(id_secuencia, id_etapa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "ETAPA"."id",
                        "ETAPA"."ET_CENDPOINT",
                        "DETALLE_SECUENCIA"."SE_NPASO",
                        "ETAPA"."ET_CCODIGO"
                    FROM "DETALLE_SECUENCIA"
                    INNER JOIN
                        "ETAPA" ON "DETALLE_SECUENCIA"."ET_NID_id" = "ETAPA"."id"
                    WHERE
                        "DETALLE_SECUENCIA"."SC_NID_id" = {id_secuencia} AND
                        "ETAPA"."ET_BISLINEA" = True AND
                        "ETAPA"."ET_NID_REF" = {id_etapa}
                    ''' 
            
            cursor.execute(query)
            result = cursor.fetchone()
            return result
    except Exception as e:
        print(e)
        return None
    
def get_list_cabecera():
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "ETAPA"."id",
                        "ETAPA"."ET_CCODIGO"
                    FROM "ETAPA"
                    WHERE
                        "ETAPA"."ET_BISCABECERA" = True AND
                        "ETAPA"."ET_BHABILITADO" = True
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None
    
def get_etapa_adicionales():
    try:
        with connection.cursor() as cursor:
            query = f''''''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

###################################################
#################### INICIO #######################
###################################################

def get_detalle_citaciones(id_citacion):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        -- CAMION
                        CAM."CAM_CPATENTE" AS PATENTE_CAMION,
                        CAM."CAM_CMARCA" AS MARCA_CAMION,
                        CAM."CAM_CMODELO" AS MODELO_CAMION,
                        CAM."CAM_NANO" AS ANIO_CAMION,
                        -- CONDUCTOR
                        CON."CON_CNOMBRE" AS NOMBRE_CONDUCTOR,
                        CON."CON_CAPELLIDO" AS APELLIDO_CONDUCTOR,
                        CON."CON_CRUT" AS RUT_CONDUCTOR,
                        CON."CON_CEMAIL" AS EMAIL_CONDUCTOR,
                        -- PROVEEDOR
                        SN."SN_CRAZONSOCIAL" AS RAZON_SOCIAL_PROVEEDOR,
                        SN."SN_CRUT" AS RUT_PROVEEDOR,
                        SN."SN_CEMAIL" AS EMAIL_PROVEEDOR,
                        -- ETAPAS
                        ARRAY_TO_STRING(ARRAY_AGG(DISTINCT CONCAT(
                            ET."ET_CNOMBRE", '|',
                            to_char(EL."EL_FFECHAINICIO", 'DD/MM/YYYY HH24:MI'), '|',
                            COALESCE(to_char(EL."EL_FFECHAFIN", 'DD/MM/YYYY HH24:MI'), ''), '|',
                            EL."ET_NID_id"
                        )), ', ') AS ETAPAS_DATO_OPERACION
                        -- DATO OPERACION
                        -- 	DOP.*
                    FROM 
                        "CITACION" AS CI
                        LEFT JOIN 
                        "CAMION" AS CAM
                        ON CI."CA_NID_id" = CAM.id
                        LEFT JOIN 
                        "CONDUCTOR" AS CON
                        ON CI."CON_NID_id" = CON.id
                        LEFT JOIN 
                        "ETAPA_LOG" AS EL
                        ON CI.id = EL."CI_NID_id"
                        LEFT JOIN
                        "ETAPA" AS ET
                        ON EL."ET_NID_id" = ET.id
                        LEFT JOIN 
                        "SOCIONEGOCIO" AS SN
                        ON CI."SN_NID_id" = SN.id
                    WHERE
                        CI.id = {id_citacion}
                    GROUP BY
                        PATENTE_CAMION,
                        MARCA_CAMION,
                        MODELO_CAMION,
                        ANIO_CAMION,
                        NOMBRE_CONDUCTOR,
                        APELLIDO_CONDUCTOR,
                        RUT_CONDUCTOR,
                        EMAIL_CONDUCTOR,
                        RAZON_SOCIAL_PROVEEDOR,
                        RUT_PROVEEDOR,
                        EMAIL_PROVEEDOR;
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_citacion_item_code(Descripcion, Empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        "PARAMETRO"."PM_CVALOR1",
	                    "PARAMETRO"."PM_CVALOR2"
                    FROM "PARAMETRO" 
                    WHERE 
                        "PARAMETRO"."PM_CGRUPO" = 'TIPO_FLETE' AND 
                        "PARAMETRO"."PM_CDESCRIPCION" = '{Descripcion}' AND
                        "PARAMETRO"."PM_NVALOR1" = {Empresa}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
            else:
                return None, None
    except Exception as e:
        print(e)
        return None, None

def get_linea_item_code(Descripcion, Empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        "PARAMETRO"."PM_CVALOR1",
	                    "PARAMETRO"."PM_CVALOR2"
                    FROM "PARAMETRO" 
                    WHERE 
                        "PARAMETRO"."PM_CGRUPO" = 'TIPO_ITEM' AND 
                        "PARAMETRO"."PM_CDESCRIPCION" = '{Descripcion}' AND
                        "PARAMETRO"."PM_NVALOR1" = {Empresa}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
            else:
                return None, None
    except Exception as e:
        print(e)
        return None, None


def get_citaciones_zonas(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "CITACION"."id" AS "CITACION",
                        TO_CHAR("CITACION"."CI_FFECHACITACION", 'YYYY-MM-DD HH24:MI') AS "FECHA_CITACION",
                        "CONDUCTOR"."CON_CNOMBRE" || ' ' || "CONDUCTOR"."CON_CAPELLIDO" AS "CONDUCTOR",
                        "CAMION"."CAM_CPATENTE" AS "CAMION",
                        "ETAPA"."ET_CNOMBRE" AS "ETAPA",
                        TO_CHAR("ETAPA_LOG"."EL_FFECHAINICIO", 'YYYY-MM-DD HH24:MI') AS "INGRESO",
                        "ZONA"."id" AS "ID_ZONA",
                        "SECUENCIA"."SE_CNOMBRE" AS "SECUENCIA",
                        "ITEM"."IT_CNOMBRE" AS "ITEM",
                        (SELECT 
                            (
                                EXTRACT(EPOCH FROM (current_timestamp AT TIME ZONE 'UTC') - ("EL_FFECHAINICIO" AT TIME ZONE 'UTC')) / 3600
                            )::integer::text
                            || ':' ||
                            LPAD(
                                ((EXTRACT(EPOCH FROM (current_timestamp AT TIME ZONE 'UTC') - ("EL_FFECHAINICIO" AT TIME ZONE 'UTC')) / 60)::integer % 60)::text,
                                2,
                                '0'
                            ) || ':' ||
                            LPAD(
                                (EXTRACT(EPOCH FROM (current_timestamp AT TIME ZONE 'UTC') - ("EL_FFECHAINICIO" AT TIME ZONE 'UTC'))::integer % 60)::text,
                                2,
                                '0'
                            ) AS diferencia_tiempo
                        FROM 
                            "ETAPA_LOG"
                        WHERE
                            "EL_FFECHAFIN" IS NULL AND
                            "CI_NID_id" = "CITACION"."id"
                        )
                    FROM "CITACION"
                    INNER JOIN
                        "ETAPA_LOG" ON "CITACION"."id" = "ETAPA_LOG"."CI_NID_id"
                    INNER JOIN
                        "ETAPA" ON "ETAPA_LOG"."ET_NID_id" = "ETAPA"."id"
                    INNER JOIN
                        "ZONA" ON "ETAPA"."ZON_NID_id" = "ZONA"."id"
                    INNER JOIN
                        "CONDUCTOR" ON "CITACION"."CON_NID_id" = "CONDUCTOR"."id"
                    INNER JOIN
                        "CAMION" ON "CITACION"."CA_NID_id" = "CAMION"."id"
                    INNER JOIN
                        "SECUENCIA" ON "CITACION"."SC_NID_id" = "SECUENCIA"."id"
                    LEFT JOIN
                        "CITACION_ITEM" ON "CITACION"."id" = "CITACION_ITEM"."CI_NID_id"
                    LEFT JOIN
                        "ITEM" ON "CITACION_ITEM"."IT_NID_id" = "ITEM"."id"
                    WHERE 
                        "CITACION"."CI_CESTADO" = 'EN PROCESO' AND
                        "CITACION"."CI_BHABILITADO" = True AND
                        "ETAPA_LOG"."EL_FFECHAFIN" IS NULL AND
                        "ETAPA"."ET_CTIPO" = 'OPERACION' AND
                        "ETAPA"."ET_CCODIGO" != 'SECUENCIA TERMINADA' AND
                        "CITACION"."EP_NID_id" = {id_empresa}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_camiones_planta_operacion(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        COUNT(CA.*)
                    FROM 
                        "CITACION" AS CI
                        LEFT JOIN "ETAPA_LOG" AS EL
                        ON CI.id = EL."CI_NID_id"
                        LEFT JOIN "ETAPA" AS ET
                        ON EL."ET_NID_id" = ET.id
                        LEFT JOIN "CAMION" AS CA
                        ON CI."CA_NID_id" = CA.id
                    WHERE 
                        EL."EL_FFECHAFIN" IS NULL
                        AND 
                        ET."ET_CTIPO" = 'OPERACION'
                        AND
                        CI."CI_CESTADO" = 'EN PROCESO'
                        AND
                        CI."EP_NID_id" = {id_empresa}
                        AND
                        CI."CI_BARCHIVADO" = FALSE
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            return result
    except Exception as e:
        print(e)
        return None

def get_camiones_dia_semana_mes(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        periodo,
                        cantidad_citaciones
                    FROM (
                        SELECT 
                            'Hoy' AS periodo,
                            COUNT(CASE WHEN DATE_TRUNC('day', CI."CI_FFECHACITACION") = DATE_TRUNC('day', CURRENT_DATE) THEN 1 END) AS cantidad_citaciones,
                            1 AS orden
                        FROM 
                            "CITACION" AS CI
                        WHERE 
                            CI."CI_CESTADO" IN ('EN PROCESO', 'TERMINADO')
                            AND CI."EP_NID_id" = {id_empresa}
                            AND DATE_TRUNC('day', CI."CI_FFECHACITACION") = DATE_TRUNC('day', CURRENT_DATE)

                        UNION ALL

                        SELECT 
                            'Esta semana' AS periodo,
                            COUNT(CASE WHEN DATE_TRUNC('day', CI."CI_FFECHACITACION") >= DATE_TRUNC('week', CURRENT_DATE) THEN 1 END) AS cantidad_citaciones,
                            2 AS orden
                        FROM 
                            "CITACION" AS CI
                        WHERE 
                            CI."CI_CESTADO" IN ('EN PROCESO', 'TERMINADO')
                            AND CI."EP_NID_id" = {id_empresa}
                            AND DATE_TRUNC('day', CI."CI_FFECHACITACION") >= DATE_TRUNC('week', CURRENT_DATE)

                        UNION ALL

                        SELECT 
                            'Este mes' AS periodo,
                            COUNT(CASE WHEN DATE_TRUNC('day', CI."CI_FFECHACITACION") >= DATE_TRUNC('month', CURRENT_DATE) THEN 1 END) AS cantidad_citaciones,
                            3 AS orden
                        FROM 
                            "CITACION" AS CI
                        WHERE 
                            CI."CI_CESTADO" IN ('EN PROCESO', 'TERMINADO')
                            AND CI."EP_NID_id" = {id_empresa}
                            AND DATE_TRUNC('day', CI."CI_FFECHACITACION") >= DATE_TRUNC('month', CURRENT_DATE)
                            AND CI."CI_BARCHIVADO" = FALSE
                    ) AS resultados
                    ORDER BY 
                        orden;
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()            
            return result
    except Exception as e:
        print(e)
        return None
    
def get_camiones_item(id_empresa):    
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        IT."IT_CNOMBRE",
                        COUNT(CI.id) AS cantidad_citaciones
                    FROM "CITACION" AS CI
                    LEFT JOIN 
                        "CITACION_ITEM" AS CII
                        ON CI.id = CII."CI_NID_id"
                    LEFT JOIN
                        "ITEM" AS IT
                        ON CII."IT_NID_id" = IT.id
                    WHERE
                        CI."CI_CESTADO" = 'EN PROCESO'
                        AND CI."EP_NID_id" = {id_empresa}
                        AND IT."IT_CNOMBRE" is not null
                        AND CI."CI_BARCHIVADO" = FALSE
                    GROUP BY
                        IT."IT_CNOMBRE";
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_list_zonas(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "ZONA"."ZON_CNOMBRE",
                        "ZONA"."ZON_CLATITUD1",
                        "ZONA"."ZON_CLONGITUD1",
                        "ZONA"."ZON_CLATITUD2",
                        "ZONA"."ZON_CLONGITUD2",
                        "ZONA"."ZON_CLATITUD3",
                        "ZONA"."ZON_CLONGITUD3",
                        "ZONA"."ZON_CLATITUD4",
                        "ZONA"."ZON_CLONGITUD4",
                        "ZONA"."id",
                        "ZONA"."ZON_CCOLOR",
                        (
                            SELECT 
                                COUNT("CITACION"."id") 
                            FROM "CITACION" 
                            INNER JOIN 
                                "ETAPA_LOG" ON "CITACION"."id" = "ETAPA_LOG"."CI_NID_id" AND "ETAPA_LOG"."EL_FFECHAFIN" IS NULL
                            INNER JOIN
                                "ETAPA" ON "ETAPA_LOG"."ET_NID_id" = "ETAPA"."id"
                            WHERE 
                                "ETAPA"."ZON_NID_id" = "ZONA"."id" AND 
                                "ETAPA"."ET_CTIPO" = 'OPERACION' AND 
                                "CITACION"."CI_CESTADO" = 'EN PROCESO' AND
                                "CITACION"."CI_BHABILITADO" = True AND
                                "CITACION"."EP_NID_id" = {id_empresa}
                        ) AS cantidad_citaciones
                    FROM "ZONA"
                    WHERE 
                        "EP_NID_id" = {id_empresa} AND 
                        "ZON_BHABILITADO" = True
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None
    
def get_citacion_enproceso_terminado(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        COUNT(CASE WHEN "CI_CESTADO" = 'EN PROCESO' THEN 1 END) AS citaciones_en_proceso,
                        COUNT(CASE WHEN "CI_CESTADO" = 'TERMINADO' THEN 1 END) AS citaciones_terminadas
                    FROM 
                        "CITACION" AS CI
                    WHERE
                        CI."EP_NID_id" = {id_empresa}
                        AND CI."CI_BARCHIVADO" = FALSE
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_citacion_terminada_noproforma(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        COUNT(CI.*)
                    FROM 
                        "CITACION" AS CI
                    LEFT JOIN
                        "CITACION_PROFORMA" AS CIP
                        ON CIP."CI_NID_id" = CI.id
                    WHERE 
                        CI."CI_CESTADO" = 'TERMINADO'
                        AND CIP."CI_NID_id" IS NULL
                        AND CI."EP_NID_id" = {id_empresa}
                        AND CI."CI_CTIPO" = 'DESPACHO'
                        AND CI."CI_BARCHIVADO" = FALSE;
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            return result
    except Exception as e:
        print(e)
        return None

def get_tiempo_maximo_secuencia(id_secuencia):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        SUM("ETAPA"."ET_TTIEMPOMAXIMO")
                    FROM "DETALLE_SECUENCIA"
                    INNER JOIN
                        "ETAPA" ON "DETALLE_SECUENCIA"."ET_NID_id" = "ETAPA"."id"
                    WHERE 
                        "DETALLE_SECUENCIA"."SE_BHABILITADO" = True AND
                        "DETALLE_SECUENCIA"."SC_NID_id" = {id_secuencia}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            if not result:
                return 0
            return result[0]
    except Exception as e:
        print(e)
        return None

def get_citacion_xtipo(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "CI_CTIPO",
	                    COALESCE(COUNT("id"), 0)
                    FROM "CITACION"
                    WHERE 
                        "CI_CESTADO" = 'EN PROCESO' AND
                        "EP_NID_id" = {id_empresa} AND
                        "CI_BHABILITADO" = True AND
                        "CI_BARCHIVADO" = FALSE
                    GROUP BY
                        "CI_CTIPO"
                    ORDER BY 
                        "CI_CTIPO"
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_notificaciones(id_usuario, empresa_id):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT 
                        n."id",
                        n."NOT_CCONTENIDO",
                        n."NOT_CURL",
                        au."first_name" || ' ' || au."last_name" AS "username",
                        TO_CHAR(n."NOT_FFECHAREGISTRO" AT TIME ZONE 'America/Santiago', 'YYYY-MM-DD HH24:MI') AS "fecha_registro"
                    FROM "NOTIFICACION" AS n
                    INNER JOIN
                        "auth_user" AS au ON n."USER_SENDER_ID_id" = au."id"
                    WHERE 
                        n."USER_RECEIVER_ID_id" = %s AND
                        n."EP_NID_id" = %s AND
                        n."NOT_BREAD" = False AND
                        n."NOT_BHABILITADO" = True AND
                        n."NOT_CURL" IS NOT NULL
                    ORDER BY n."NOT_FFECHAREGISTRO" DESC 
                    LIMIT 10;
                    '''
            # print(query)
            cursor.execute(query, [id_usuario, empresa_id])
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return []


def get_siguiente_etapa(id_secuencia, num_paso):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "DETALLE_SECUENCIA"."id"
                    FROM "SECUENCIA"
                    INNER JOIN
                        "DETALLE_SECUENCIA" ON "SECUENCIA"."id" = "DETALLE_SECUENCIA"."SC_NID_id"
                    INNER JOIN
                        "ETAPA" ON "DETALLE_SECUENCIA"."ET_NID_id" = "ETAPA"."id"
                    WHERE
                        "ETAPA"."ET_BHABILITADO" = True AND
                        "SECUENCIA"."id" = {id_secuencia} AND
                        "ETAPA"."ET_CTIPO" <> 'SALIDA' AND
                        "DETALLE_SECUENCIA"."SE_NPASO" > {num_paso}
                        AND "DETALLE_SECUENCIA"."SE_BHABILITADO" = True
                    ORDER BY "DETALLE_SECUENCIA"."SE_NPASO", "DETALLE_SECUENCIA"."id" ASC
                    LIMIT 1;
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            return result
    except Exception as e:
        print(e)
        return None

def get_actuve_users():
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        CAST("auth_user"."id" AS VARCHAR),
                        "auth_user"."first_name" || ' ' || "auth_user"."last_name" || ' - ' || "auth_user"."username" AS "username"
                    FROM "auth_user"
                    WHERE
                        "auth_user"."is_active" = True
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def get_cupos_proveedor(id_planificacion, id_proveedor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        COUNT("CITACION"."id")
                    FROM "CITACION"
                    WHERE
                        "CITACION"."CI_BHABILITADO" = True AND
                        "CITACION"."PLA_NID_id" = {id_planificacion} AND
                        "CITACION"."PRO_NID_id" = {id_proveedor}
                    '''
            print(query)
            cursor.execute(query)
            result = cursor.fetchone()
            if not result:
                return 0
            return result[0]
    except Exception as e:
        print(e)
        return None

def update_citaciones_sobre_cupo(id_planificacion, id_proveedor, cupos):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    UPDATE "CITACION"
                    SET
                        "CI_BSOBRECUPO" = True
                    WHERE
                        "id" IN (
                            SELECT
                                id
                            FROM "CITACION"
                            WHERE
                                "PLA_NID_id" = {id_planificacion} AND
                                "PRO_NID_id" = {id_proveedor}
                                "CI_BHABILITADO" = True AND
                                "CI_BARCHIVADO" = False
                            ORDER BY "id" DESC
                            LIMIT {cupos}
                        )
                    '''
            print(query)
            cursor.execute(query)
            connection.commit()
    except Exception as e:
        connection.rollback()
        print(e)
        return None

def get_etapa_operacion_xsecuencia(secuencia_id, citacion_id):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        "ETAPA".id
                    FROM "SECUENCIA"
                    INNER JOIN
                        "DETALLE_SECUENCIA" ON "SECUENCIA".id = "DETALLE_SECUENCIA"."SC_NID_id"
                    INNER JOIN
                        "ETAPA" ON "DETALLE_SECUENCIA"."ET_NID_id" = "ETAPA".id
                    INNER JOIN
                        "ETAPA_LOG" ON "ETAPA".id = "ETAPA_LOG"."ET_NID_id"
                    WHERE
                        "SECUENCIA".id = {secuencia_id} AND
                        "ETAPA"."ET_CTIPO" = 'OPERACION' AND
                        "ETAPA"."ET_BHABILITADO" = True AND
                        "DETALLE_SECUENCIA"."SE_BHABILITADO" = True AND
                        "ETAPA_LOG"."CI_NID_id" = {citacion_id} AND
                        "ETAPA_LOG"."SC_NID_id" =  {secuencia_id} AND
                        "ETAPA_LOG"."EL_FFECHAFIN" IS NOT NULL
                    ORDER BY "SE_NPASO" ASC                    
                    '''
            # print(query)
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except Exception as e:
        print(e)
        return None

def update_field_citacion(id_citacion, campo, valor):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    UPDATE "CITACION"
                    SET
                        "{campo}" = '{valor}'
                    WHERE id = {id_citacion}
                    '''
            print(query)
            cursor.execute(query)
            connection.commit()
    except Exception as e:
        connection.rollback()
        print(e)
        return None

def update_field_citacion_null(id_citacion, campo):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    UPDATE "CITACION"
                    SET
                        "{campo}" = NULL
                    WHERE id = {id_citacion}
                    '''
            print(query)
            cursor.execute(query)
            connection.commit()
    except Exception as e:
        connection.rollback()
        print(e)
        return None

def get_cupos_por_proveedor(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        SN."SN_CRAZONSOCIAL",
                        COUNT(CASE WHEN "CI_CESTADO" = 'EN PROCESO' THEN 1 END) AS citaciones_en_proceso
                    FROM
                        "CITACION" AS CI
                        LEFT JOIN "SOCIONEGOCIO" AS SN ON SN.id = CI."PRO_NID_id"
                    WHERE
                        CI."CI_BARCHIVADO" = FALSE
                        AND CI."EP_NID_id" = {id_empresa}

                    GROUP BY
                        SN."SN_CRAZONSOCIAL"
                    HAVING
                        COUNT(CASE WHEN "CI_CESTADO" = 'EN PROCESO' THEN 1 END) > 0
                    '''
            cursor.execute(query)
            results = cursor.fetchall()
            return results
    except Exception as e:
        print(e)
        return None

def get_citacion_por_secuencia(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    SELECT
                        S."SE_CNOMBRE",
                        COUNT(CI."SC_NID_id") AS citaciones_en_proceso
                    FROM
                        "CITACION" AS CI
                        LEFT JOIN "SECUENCIA" AS S ON S.id = CI."SC_NID_id"
                    WHERE
                        CI."CI_BARCHIVADO" = FALSE
                        AND CI."EP_NID_id" = {id_empresa}
                        AND CI."CI_CESTADO" IN( 'EN PROCESO')

                    GROUP BY
                            S."SE_CNOMBRE"
                    '''
            cursor.execute(query)
            results = cursor.fetchall()
            return results
    except Exception as e:
        print(e)
        return None
def get_citacion_por_etapa(id_empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                                        SELECT
                        E."ET_CNOMBRE",
                        COUNT(DISTINCT CI.id) AS cantidad_citaciones
                    FROM 
                        "CITACION" AS CI
                        LEFT JOIN "ETAPA_LOG" EL ON EL."CI_NID_id" = CI.id
                        LEFT JOIN "ETAPA" E ON E."id" = EL."ET_NID_id"
                    WHERE CI."CI_CESTADO" IN ('EN PROCESO')
                            AND CI."CI_BARCHIVADO" = False
                            AND E."ET_BHABILITADO" = True
                            AND EL."EL_FFECHAFIN" IS NULL  -- Solo contar etapas donde EL_FFECHAFIN es nulo
                            AND CI."EP_NID_id" = {id_empresa}
                    GROUP BY E."ET_CNOMBRE"
                    '''
            cursor.execute(query)
            results =cursor.fetchall()
            return results
    except Exception as e:
        print(e)
        return None
    
def get_cupos_zona():
    try:
        with connection.cursor() as cursor:
            query = f'''
                SELECT 
                    "ZONA"."ZON_CNOMBRE",
                    COUNT(DISTINCT CASE 
                        WHEN "CITACION"."CI_CESTADO" = 'EN PROCESO' 
                        AND "CITACION"."CI_BARCHIVADO" = False 
                        AND "ETAPA_LOG"."EL_FFECHAFIN" IS NULL 
                        AND "CITACION"."EP_NID_id" = 1 
                        THEN "CITACION".id 
                        ELSE NULL 
                    END) AS citaciones,
                    COALESCE("ZONA"."ZON_NCANTIDADCUPOS", 0) AS cantidad_cupos,
                    (COALESCE("ZONA"."ZON_NCANTIDADCUPOS", 0) - COUNT(DISTINCT CASE 
                        WHEN "CITACION"."CI_CESTADO" = 'EN PROCESO' 
                        AND "CITACION"."CI_BARCHIVADO" = False 
                        AND "ETAPA_LOG"."EL_FFECHAFIN" IS NULL 
                        AND "CITACION"."EP_NID_id" = 1 
                        THEN "CITACION".id 
                        ELSE NULL 
                    END)) AS cupos_libres,
                    "ZONA"."ZON_CCOLOR"
                FROM 
                    "ZONA"
                LEFT JOIN 
                    "ETAPA" ON "ZONA".id = "ETAPA"."ZON_NID_id"
                LEFT JOIN 
                    "ETAPA_LOG" ON "ETAPA"."id" = "ETAPA_LOG"."ET_NID_id"
                LEFT JOIN 
                    "CITACION" ON "ETAPA_LOG"."CI_NID_id" = "CITACION".id
                WHERE 
                    "ZONA"."ZON_BHABILITADO" = True
                GROUP BY 
                    "ZONA".id, 
                    "ZONA"."ZON_CNOMBRE", 
                    "ZONA"."ZON_NCANTIDADCUPOS", 
                    "ZONA"."ZON_CCOLOR"
                ORDER BY 
                    "ZONA"."ZON_CNOMBRE";
            '''
            cursor.execute(query)
            results = cursor.fetchall()
            return results
    except Exception as e:
        print(e)
        return None

def get_camiones_por_zona(id_zona):
    try:
        query = f'''
            SELECT 
                "CITACION"."id" as "id",
                "CAMION"."CAM_CPATENTE" AS "Patente",
                "SECUENCIA"."SE_CNOMBRE" AS "Secuencia",
                "ETAPA"."ET_CNOMBRE" AS "Etapa",
                TO_CHAR("ETAPA_LOG"."EL_FFECHAINICIO", 'DD/MM/YYYY HH24:MI') AS "Tiempo_entrada",
                CASE 
                    WHEN EXTRACT(DAY FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO")) > 0 
                    THEN 
                        CONCAT(
                            EXTRACT(DAY FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO")), ' d ',
                            LPAD(EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' hrs ',
                            LPAD(EXTRACT(MINUTE FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' min ',
                            LPAD(EXTRACT(SECOND FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' seg'
                        )
                    ELSE 
                        CONCAT(
                            LPAD(EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' hrs ',
                            LPAD(EXTRACT(MINUTE FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' min ',
                            LPAD(EXTRACT(SECOND FROM (CURRENT_TIMESTAMP - "ETAPA_LOG"."EL_FFECHAINICIO"))::TEXT, 2, '0'), ' seg'
                        )
                END AS "Tiempo_transcurrido"
            FROM 
                "CITACION"
            LEFT JOIN 
                "ETAPA_LOG" ON "CITACION"."id" = "ETAPA_LOG"."CI_NID_id" 
            LEFT JOIN
                "ETAPA" ON "ETAPA_LOG"."ET_NID_id" = "ETAPA"."id"
            INNER JOIN 
                "ZONA" ON "ZONA".id = "ETAPA"."ZON_NID_id"
            LEFT JOIN
                "CAMION" ON "CITACION"."CA_NID_id" = "CAMION"."id"
            LEFT JOIN 
                "SECUENCIA" ON "CITACION"."SC_NID_id" = "SECUENCIA"."id"
            WHERE 
                "CITACION"."CI_CESTADO" = 'EN PROCESO' AND
                "CITACION"."CI_BARCHIVADO" = False AND
                "ETAPA_LOG"."EL_FFECHAFIN" IS NULL AND
                "CITACION"."EP_NID_id" = 1 AND
                "ZONA"."id" = {id_zona}
        '''
        df = pd.read_sql(query, connection)
        result = df.to_dict(orient='records')
        return result
    except Exception as e:
        print(e)
        return None
    
def insert_ETAPA_LOG(empresa, secuencia, etapa, citaciones):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    INSERT INTO "ETAPA_LOG"
                    (
                       "EP_NID_id",
                       "SC_NID_id",
                       "ET_NID_id",
                       "EL_FFECHAINICIO",
                       "CI_NID_id"
                    ) VALUES 
                    (
                        {empresa},
                        {secuencia},
                        {etapa},
                        CURRENT_TIMESTAMP,
                        %s
                    )
                    '''
            # SOLUCIÓN 1: Convertir lista de IDs a lista de tuplas
            citaciones_tuplas = [(citacion_id,) for citacion_id in citaciones]
            cursor.executemany(query, citaciones_tuplas)
            connection.commit()
            return True
    except Exception as e:
        print(f"Error en insert_ETAPA_LOG: {e}")
        connection.rollback()
        return None
    
def delete_ETAPA_LOG(secuencia, etapa, empresa):
    try:
        with connection.cursor() as cursor:
            query = f'''
                    DELETE FROM "ETAPA_LOG"
                    WHERE 
                        "SC_NID_id" = {secuencia} AND
                        "ET_NID_id" = {etapa} AND 
                        "EP_NID_id" = {empresa} AND
                        "EL_FFECHAFIN" IS NULL
                    '''
            cursor.execute(query)
            connection.commit()
            return True
    except Exception as e:
        print(e)
        connection.rollback()
        return None

def get_PROFORMA(empresa = 1, borrador = 'False', proveedor = "", fecha_desde = "", fecha_hasta = ""):
    try:
        query = f'''
                SELECT
                    p."id",
                    p."PRO_NDESCUENTO",
                    p."PRO_NINGRESO",
                    p."PRO_NSUBTOTAL",
                    p."PRO_NIVA",
                    p."PRO_NTOTAL",
                    p."PRO_CCOMENTARIO",
                    p."PRO_FFECHAREGISTRO",
                    p."PRO_FFECHAEMISION",
                    p."PRO_DOC_NUM",
                    p."PRO_CESTADO",
                    p."PRO_BSOLOEXTRAS",
                    e."EP_CRAZONSOCIAL",
                    p."PRO_CTIPO",
                    sn."SN_CRAZONSOCIAL"
                FROM "PROFORMA" p
                INNER JOIN
                    "EMPRESA" e ON p."EP_NID_id" = e."id"
                INNER JOIN
                    "SOCIONEGOCIO" sn ON p."SN_NID_id" = sn."id"
                WHERE
                    p."PRO_BBORRADOR" = {borrador}
                '''
        if empresa:
            query += f' AND p."EP_NID_id" = {empresa} '
        if proveedor:
            query += f' AND p."SN_NID_id" = {proveedor} '
        if fecha_desde:
            query += f''' AND p."PRO_FFECHAEMISION" >= '{fecha_desde}' '''
        if fecha_hasta:
            query += f''' AND p."PRO_FFECHAEMISION" <= '{fecha_hasta}' '''
            
        query += ' ORDER BY p."id" DESC'
        df = pd.read_sql(query, connection)
        return df.to_dict(orient='records')
    except Exception as e:
        print(e)
        return None
    
def get_EXTRAS_PROFORMA(proveedor = "", fecha_desde = "", fecha_hasta = "", tipo_citacion = "", empresa = 1):
    try:
        query = f'''
                SELECT
                    ec."id" as "id_extra",
                    c."id" as "id_citacion",
                    ec."CIE_NVALOR",
                    ec."CIE_BINGRESO",
                    ec."CIE_CCOMENTARIO",
                    e."EXT_CNOMBRE",
                    c."CI_FFECHAREGISTRO",
                    pro."SN_CRAZONSOCIAL",
                    con."CON_CNOMBRE" || ' ' || con."CON_CAPELLIDO" AS "CON_CNOMBRE",
                    c."CI_CTIPODOCUMENTO" AS "TIPO_DOCUMENTO",
                    c."CI_CNUMERODOCUMENTO" AS "NUMERO_DOCUMENTO"
                FROM "CITACION_EXTRA" ec
                INNER JOIN
                    "CITACION" c ON ec."CI_NID_id" = c."id"
                INNER JOIN
                    "EXTRA" e ON ec."EXT_NID_id" = e."id"
                LEFT JOIN
                    "CONDUCTOR" AS con ON c."CON_NID_id" = con."id"
                LEFT JOIN
                    "SOCIONEGOCIO" AS pro ON con."SN_NID_id" = pro."id"
                WHERE 
                    c."CI_CESTADO" = 'TERMINADO'
                    AND c."CI_BHABILITADO" = True 
                    AND c."CI_BCONFORME" = True
                    AND ec."id" NOT IN (SELECT "CIE_NID_id" FROM "EXTRA_PROFORMA" WHERE "EPR_BHABILITADO" = True)
                    AND c."CI_CTIPO_FLETE" <> 'Flete Cliente'
                '''
                
        if proveedor != '' and proveedor != None and proveedor != 'None':
            query += f'''
                    AND pro."id" = {proveedor}
                '''
        if fecha_desde != '' and fecha_desde != None and fecha_desde != 'None':
            query += f'''
                    AND c."CI_FFECHAREGISTRO" >= '{fecha_desde}'
                    '''

        if fecha_hasta != '' and fecha_hasta != None and fecha_hasta != 'None':
            query += f'''
                    AND c."CI_FFECHAREGISTRO" <= '{fecha_hasta}'
                    '''
        if tipo_citacion != '' and tipo_citacion != None and tipo_citacion != 'None':
            query += f'''
                    AND c."CI_CTIPO" = '{tipo_citacion}'
                    '''
        
        if empresa != '' and empresa != None and empresa != 'None':
            query += f'''
                    AND c."EP_NID_id" = {empresa}
                    '''
        
        query += f''' ORDER BY ec."id" DESC'''
        
        df = pd.read_sql(query, connection)
        return df.to_dict(orient='records')
    except Exception as e:
        print(e)
        return None

    