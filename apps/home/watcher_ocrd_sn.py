from win32com import *
from win32com.client import *
from win32com.client import dynamic
from win32com.server.util import wrap as wrap

from hdbcli import dbapi
import psycopg2
import pyodbc
import json

from vars import *
from cypher import *

try:
    config_postgres = 'dbname=TERRAMAR_CAMIONES user=postgres password=Terramar2024 host=localhost port=5432'
    conn_postgres = psycopg2.connect(config_postgres)
    cursor_postgres = conn_postgres.cursor()
except Exception as e:
    print(e)

# HANA FUNCTIONS
def get_credentials_hana():
    try:
        query = f'''
                SELECT 
                    "id",
                    "EP_CBASEDATOS",
                    "EP_CUSUARIOSBD",
                    "EP_CPASSWORDBD",
                    "EP_CPORT",
                    "EP_CHOST"
                FROM "EMPRESA"
                WHERE "EP_CDB_SERVER_TYPE" = '9'
                '''
        cursor_postgres.execute(query)
        result = cursor_postgres.fetchone()
        return result
    except Exception as e:
        print(e)

def connect_hana(credentials):
    try:
        credentials_hana = json.load(open("C:\\inetpub\\wwwroot\\TERRAMAR-CAMIONES\\hana_credentials.json"))
        print(credentials_hana)
        conn = dbapi.connect(credentials_hana["ServerAddress"], credentials_hana["ServerPort"], credentials_hana['DbUserName'], credentials_hana["DbPassword"])
        return conn, conn.cursor()
    except Exception as e:
        print(e)

def obtener_datos_socionegocio_hana(sociosnegocio, crendentials):
    try:
        query = f'''
                SELECT
                    "CardCode",
                    "CardName",
                    "LicTradNum",
                    "Address",
                    "CardFName",
                    "Phone1",
                    "E_Mail",
                    "CardType"
                FROM {crendentials[1]}.OCRD
                WHERE 
                    "CardCode" IS NOT NULL AND
                    "CardName" IS NOT NULL AND
                    "LicTradNum" IS NOT NULL AND
                    "U_Transporte" = 'Si'
                    
                '''
        if sociosnegocio != '':
            query += f" AND \"CardCode\" NOT IN ({sociosnegocio})"
        print(query)
        cursor_hana.execute(query)
        result = cursor_hana.fetchall()
        return result
    except Exception as e:
        print(e)
        return None

def obtener_datos_items_hana(items, crendentials):
    try:
        query = f'''
                SELECT
                    "ItmsGrpCod",
                    "ItmsGrpNam"
                FROM {crendentials[1]}.OITB
                '''
        if items != '':
            query += f"WHERE \"ItmsGrpCod\" NOT IN ({items})"
        cursor_hana.execute(query)
        result = cursor_hana.fetchall()
        return result
    except Exception as e:
        print(e)
        return None

# SQL SERVER FUNCTIONS
# def get_credentials_sql_server():
#     try:
#         query = f'''
#                 SELECT 
#                     "id",
#                     "EP_CBASEDATOS",
#                     "EP_CUSUARIOSBD",
#                     "EP_CPASSWORDBD",
#                     "EP_CPORT",
#                     "EP_CHOST"
#                 FROM "EMPRESA"
#                 WHERE "EP_CDB_SERVER_TYPE" <> '9' 
#                 '''
#         cursor_postgres.execute(query)
#         result = cursor_postgres.fetchone()
#         return result
#     except Exception as e:
#         print(e)

# def connect_sql_server(credentials):
#     try:
#         conn = pyodbc.connect("DRIVER={ODBC Driver 17 for SQL Server};SERVER="+credentials[5]+";DATABASE="+credentials[1]+";UID="+credentials[2]+";PWD="+credentials[3]+"")
#         return conn, conn.cursor()
#     except Exception as e:
#         print(e)

# def obtener_datos_socionegocio_sql_server(sociosnegocio, credentials):
#     try:
#         query = f'''
#                 SELECT
#                     "CardCode",
#                     "CardName",
#                     "LicTradNum",
#                     "Address",
#                     "CardFName",
#                     "Phone1",
#                     "E_Mail",
#                     "CardType"
#                 FROM {credentials[1]}.OCRD
#                 WHERE "CardCode" NOT IN ({sociosnegocio})
#                 '''
#         cursor_sql_server.execute(query)
#         result = cursor_sql_server.fetchall()
#         return result
#     except Exception as e:
#         print(e)
#         return None
    
# def obtener_datos_items_sql_server(items, credentials):
#     try:
#         query = f'''
#                 SELECT
#                     "ItemCode",
#                     "ItemName"
#                 FROM {credentials[1]}.OITM
#                 WHERE "ItemCode" NOT IN ({items})
#                 '''
#         cursor_sql_server.execute(query)
#         result = cursor_sql_server.fetchall()
#         return result
#     except Exception as e:
#         print(e)
#         return None

#####################################################################
###########################   POSTGRES   ############################
#####################################################################

# OBTENER SOCIONEGOCIO DE LA EMPRESA
def get_socionegocio_empresa(id_empresa):
    try:
        query = f'''
                SELECT 
                    "SN_CCODIGO_SAP"
                FROM "SOCIONEGOCIO"
                WHERE "EP_NID_id" = {id_empresa} AND "SN_CCODIGO_SAP" IS NOT NULL
                '''
        cursor_postgres.execute(query)
        result = cursor_postgres.fetchall()
        return result
    except Exception as e:
        print(e)

# OBTENER ITEMS DE LA EMPRESA
def get_items_empresa(id_empresa):
    try:
        query = f'''
                SELECT 
                    "IT_CCODIGO"
                FROM "ITEM"
                WHERE "EP_NID_id" = {id_empresa} AND "IT_CCODIGO" IS NOT NULL
                '''
        cursor_postgres.execute(query)
        result = cursor_postgres.fetchall()
        return result
    except Exception as e:
        print(e)

# INSERTS
def insert_socionegocio_empresa(data):
    try:
        query = f'''
                INSERT INTO "SOCIONEGOCIO" (
                            "EP_NID_id", 
                            "SN_CCODIGO_SAP",
                            "SN_CRAZONSOCIAL",
                            "SN_CRUT",
                            "SN_CDIRECCION",
                            "SN_CCONTACTO",
                            "SN_CTELEFONO",
                            "SN_CEMAIL",
                            "SN_CTIPO",
                            "SN_BHABILITADO",
                            "SN_BGENERICO"
                        ) 
                VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            TRUE,
                            FALSE
                        )
                '''
        cursor_postgres.executemany(query, data)
        conn_postgres.commit()
    except Exception as e:
        print(e)

def insert_items_empresa(data):
    try:
        query = f'''
                INSERT INTO "ITEM" (
                            "EP_NID_id", 
                            "IT_CCODIGO",
                            "IT_CNOMBRE"
                ) VALUES (
                            %s, 
                            %s, 
                            %s
                        )
                '''
        cursor_postgres.executemany(query, data)
        conn_postgres.commit()
    except Exception as e:
        print(e)
        return None

def insert_user(data):
    try:
        query = f'''
                INSERT INTO auth_user (
                        "username",
                        "password",
                        "first_name",
                        "email",
                        "date_joined"
                ) VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    CURRENT_DATE
                ) RETURNING id
                '''
        cursor_postgres.execute(query, data)
        user_id = cursor_postgres.fetchone()[0]  # Capturar el ID retornado
        conn_postgres.commit()
        return user_id  # Devolver el ID del nuevo usuario
    except Exception as e:
        print(e)
        return False

def insert_user_extension(US_NID_id, UX_IS_PROVEEDOR, UX_IS_CLIENTE, UX_IS_TERRAMAR, UX_IS_ACEITES):
    try:
        query = f'''
                INSERT INTO "USERS_EXTENSION" (
                        "US_NID_id",
                        "UX_IS_ADMINISTRADOR_SECUENCIA",
                        "UX_IS_ADMINISTRADOR_ETAPA",
                        "UX_IS_PLANIFICADOR",
                        "UX_IS_RECEPCIONISTA",
                        "UX_IS_CLIENTE",
                        "UX_IS_PROVEEDOR",
                        "UX_IS_OPERADOR",
                        "UX_IS_REPORTES",
                        "UX_IS_PROFORMA",
                        "UX_IS_TERRAMAR",
                        "UX_IS_ACEITES"
                ) VALUES (
                    {US_NID_id},
                    FALSE,
                    FALSE,
                    FALSE,
                    FALSE,
                    {UX_IS_CLIENTE},
                    {UX_IS_PROVEEDOR},
                    FALSE,
                    FALSE,
                    FALSE,
                    {UX_IS_TERRAMAR},
                    {UX_IS_ACEITES}
                ); 
                '''
        cursor_postgres.execute(query)
        conn_postgres.commit()
        return True
    except Exception as e:
        print(e)
        return False
    
def insert_usuario_socionegocio(data):
    try:
        query = f'''
                INSERT INTO "USUARIO_SOCIONEGOCIO" (
                        "EP_NID_id",
                        "US_NID_id",
                        "SN_NID_id",
                        "USC_CTIPO"
                ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s
                )
                '''
        cursor_postgres.execute(query, data)
        conn_postgres.commit()
        return True
    except Exception as e:
        print(e)
        return False

# OBTENER USUARIO CLIENTE/PROVEEDOR DUPLICADO
def duplicated_rut(rut_socionegocio):
    try:
        query = f'''
                SELECT
                    "id"
                FROM "auth_user"
                WHERE "username" = '{rut_socionegocio}';
                '''
        cursor_postgres.execute(query)
        result = cursor_postgres.fetchone()
        if not result:
            return None
        return result[0]
    except Exception as e:
        print(e)
        return None

# OBTENER ID SOCIONEGOCIO
def get_id_socionegocio(SN_CRUT, EP_NID, SN_CTIPO):
    try:
        query = f'''
                SELECT
                    "id"
                FROM "SOCIONEGOCIO"
                WHERE 
                    "SN_CRUT" = '{SN_CRUT}' AND 
                    "EP_NID_id" = {EP_NID} AND
                    "SN_CTIPO" = '{SN_CTIPO}'
                '''
        cursor_postgres.execute(query)
        result = cursor_postgres.fetchone()
        return result[0]
    except Exception as e:
        print(e)
        return None

# ACTUALIZAR VALOR DE UN CAMPO EN TABLA USERS_EXTENSION
def actualizar_usersextension(CAMPO, VALOR, WHERE):
    try:
        query = f'''
                UPDATE "USERS_EXTENSION"
                SET "{CAMPO}" = {VALOR}
                WHERE {WHERE}
                '''
        cursor_postgres.execute(query)
        conn_postgres.commit()
        return True
    except Exception as e:
        print(e)
        conn_postgres.rollback()
        return False

#####################################################################
#############################   MAIN   ##############################
#####################################################################
def main():
    try:
        #####################################################################
        #############################   HANA   ##############################
        #####################################################################

        socionegocio_postgres = get_socionegocio_empresa(credentials_hana[0])
        if socionegocio_postgres:
            socionegocio_postgres_array = [elemento for tupla in socionegocio_postgres for elemento in tupla]
            socionegocio_postgres_str = str(socionegocio_postgres_array).replace("[", "").replace("]", "")
        else:
            socionegocio_postgres_str = ''
        
        socionegocio_hana = obtener_datos_socionegocio_hana(socionegocio_postgres_str, credentials_hana)
        if socionegocio_hana:
            socionegocio_hana_array = [list(tupla) for tupla in socionegocio_hana]
            for array in socionegocio_hana_array:
                array.insert(0, credentials_hana[0])

            insert_socionegocio_empresa(socionegocio_hana_array)
            # for row in socionegocio_hana_array:
            #     id_user = duplicated_rut(row[2])
            #     id_socionegocio = get_id_socionegocio(row[2], credentials_hana[0], row[7])
            #     if not id_user:
            #         socionegocio_user_hana_array = [row[2]]
            #         es_cliente = 'TRUE'
            #         es_proveedor = 'FALSE'
            #         if row[7] == 'C':
            #             socionegocio_user_hana_array.append(USER_DEFAULT_PASSWORD_CLIENTE)
            #         elif row[7] == 'S':
            #             es_cliente = 'FALSE'
            #             es_proveedor = 'TRUE'
            #             socionegocio_user_hana_array.append(USER_DEFAULT_PASSWORD_PROVEEDOR)
                    
            #         socionegocio_user_hana_array.append(row[1])
            #         socionegocio_user_hana_array.append(row[6])
            #         id_user = insert_user(socionegocio_user_hana_array)
            #         insert_user_extension(id_user, es_cliente, es_proveedor, 'TRUE', 'FALSE')
            #     else:
            #         if row[7] == 'C':
            #             actualizar_usersextension("UX_IS_CLIENTE", "TRUE", f'"US_NID_id" = {id_user}')
            #         elif row[7] == 'S':
            #             actualizar_usersextension("UX_IS_PROVEEDOR", "TRUE", f'"US_NID_id" = {id_user}')
            #         actualizar_usersextension("UX_IS_TERRAMAR", "TRUE", f'"US_NID_id" = {id_user}')

            #     insert_usuario_socionegocio(credentials_hana[0], id_user, id_socionegocio ,row[7])
        items_postgres = get_items_empresa(credentials_hana[0])
        if items_postgres:
            items_postgres_array = [elemento for tupla in items_postgres for elemento in tupla]
            items_postgres_str = str(items_postgres_array).replace("[", "").replace("]", "")
        else:
            items_postgres_str = ''

        items_hana = obtener_datos_items_hana(items_postgres_str, credentials_hana)
        if items_hana:
            items_hana_array = [list(tupla) for tupla in items_hana]
            for array in items_hana_array:
                array.insert(0, credentials_hana[0])
            insert_items_empresa(items_hana_array)

        #####################################################################
        ##########################   SQL SERVER   ###########################
        #####################################################################

        # socionegocio_postgres = get_socionegocio_empresa(credentials_sql_server[0])
        # if socionegocio_postgres:
        #     socionegocio_postgres_array = [elemento for tupla in socionegocio_postgres for elemento in tupla]
        #     socionegocio_postgres_str = str(socionegocio_postgres_array).replace("[", "").replace("]", "")
        # else:
        #     socionegocio_postgres_str = ''
        
        # socionegocio_sql_server = obtener_datos_socionegocio_sql_server(socionegocio_postgres_str, credentials_sql_server)
        # if socionegocio_sql_server:
        #     socionegocio_sql_server_array = [list(tupla) for tupla in socionegocio_sql_server]
        #     for array in socionegocio_sql_server_array:
        #         array.insert(0, credentials_sql_server[0])
        #     insert_socionegocio_empresa(socionegocio_sql_server_array)

        #     for row in socionegocio_sql_server_array:
        #         id_user = duplicated_rut(row[2])
        #         id_socionegocio = get_id_socionegocio(row[2], credentials_sql_server[0], row[7])
        #         if not id_user:
        #             socionegocio_user_sql_server_array = [row[2]]
        #             es_cliente = 'TRUE'
        #             es_proveedor = 'FALSE'
        #             if row[7] == 'C':
        #                 socionegocio_user_sql_server_array.append(USER_DEFAULT_PASSWORD_CLIENTE)
        #             elif row[7] == 'S':
        #                 es_cliente = 'FALSE'
        #                 es_proveedor = 'TRUE'
        #                 socionegocio_user_sql_server_array.append(USER_DEFAULT_PASSWORD_PROVEEDOR)

        #             socionegocio_user_sql_server_array.append(row[1])
        #             socionegocio_user_sql_server_array.append(row[6])
        #             id_user = insert_user(socionegocio_user_sql_server_array)
        #             insert_user_extension(id_user, es_cliente, es_proveedor)
        #         else:
        #             if row[7] == 'C':
        #                 actualizar_usersextension("UX_IS_CLIENTE", "TRUE", f'"US_NID_id" = {id_user}')
        #             elif row[7] == 'S':
        #                 actualizar_usersextension("UX_IS_PROVEEDOR", "TRUE", f'"US_NID_id" = {id_user}')
        #             actualizar_usersextension("UX_IS_ACEITES", "TRUE", f'"US_NID_id" = {id_user}')
                    
        #         insert_usuario_socionegocio(credentials_sql_server[0], id_user, id_socionegocio ,row[7], 'FALSE', 'TRUE')

        # items_postgres = get_items_empresa(credentials_sql_server[0])
        # if items_postgres:
        #     items_postgres_array = [elemento for tupla in items_postgres for elemento in tupla]
        #     items_postgres_str = str(items_postgres_array).replace("[", "").replace("]", "")
        # else:
        #     items_postgres_str = ''
        
        # items_sql_server = obtener_datos_items_sql_server(items_postgres_str, credentials_sql_server)
        # if items_sql_server:
        #     items_sql_server_array = [list(tupla) for tupla in items_sql_server]
        #     for array in items_sql_server_array:
        #         array.insert(0, credentials_sql_server[0])
        #     insert_items_empresa(items_sql_server_array)

    except Exception as e:
        print(e)

credentials_hana = get_credentials_hana()
conn_hana, cursor_hana = connect_hana(credentials_hana)
main()
# credentials_sql_server = get_credentials_sql_server()
# conn_sql_server, cursor_sql_server = connect_sql_server(credentials_sql_server)

# if credentials_hana and credentials_sql_server:
#     main()
