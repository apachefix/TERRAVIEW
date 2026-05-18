import psycopg2
import pandas as pd

# Configuración de la conexión a PostgreSQL
config_postgres = 'dbname=TERRAMAR_CAMIONES user=postgres password=Terramar2024 host=localhost port=5432'

try:
    conn_postgres = psycopg2.connect(config_postgres)
    cursor_postgres = conn_postgres.cursor()
except Exception as e:
    print(f"Error conectando a la base de datos: {e}")
    exit(1)

def read_excel_data(file_path):
    try:
        df = pd.read_excel(file_path)
        # Asumiendo que las columnas se llaman 'RAZÓN SOCIAL' y 'RUT'
        return df[['RAZÓN SOCIAL', 'RUT']].values.tolist()
    except Exception as e:
        print(f"Error leyendo el archivo Excel: {e}")
        return []

def delete_socio_negocio(razon_social, rut):
    try:
        # Primero obtenemos el ID del usuario y socio negocio
        query_get_ids = """
            SELECT au.id, sn.id 
            FROM auth_user au
            JOIN "USUARIO_SOCIONEGOCIO" us ON us."US_NID_id" = au.id
            JOIN "SOCIONEGOCIO" sn ON sn.id = us."SN_NID_id"
            WHERE sn."SN_CRAZONSOCIAL" = %s AND sn."SN_CRUT" = %s
        """
        cursor_postgres.execute(query_get_ids, [razon_social, rut])
        result = cursor_postgres.fetchone()
        
        if not result:
            print(f"No se encontró el socio de negocio: {razon_social} (RUT: {rut})")
            return False

        user_id, socio_id = result

        # Eliminamos en orden para mantener la integridad referencial
        # 1. Eliminar de PERFIL_USUARIO
        cursor_postgres.execute("""
            DELETE FROM "PERFIL_USUARIO"
            WHERE "US_NID_id" = %s
        """, [user_id])

        # 2. Eliminar de USERS_EXTENSION
        cursor_postgres.execute("""
            DELETE FROM "USERS_EXTENSION"
            WHERE "US_NID_id" = %s
        """, [user_id])

        # 3. Eliminar de USERS_EMPRESA
        cursor_postgres.execute("""
            DELETE FROM "USERS_EMPRESA"
            WHERE "US_NID_id" = %s
        """, [user_id])

        # 4. Eliminar de USUARIO_SOCIONEGOCIO
        cursor_postgres.execute("""
            DELETE FROM "USUARIO_SOCIONEGOCIO"
            WHERE "US_NID_id" = %s
        """, [user_id])

        # 5. Eliminar de auth_user
        cursor_postgres.execute("""
            DELETE FROM auth_user
            WHERE id = %s
        """, [user_id])

        # 6. Eliminar de SOCIONEGOCIO
        cursor_postgres.execute("""
            DELETE FROM "SOCIONEGOCIO"
            WHERE id = %s
        """, [socio_id])

        conn_postgres.commit()
        print(f"Eliminado exitosamente: {razon_social} (RUT: {rut})")
        return True

    except Exception as e:
        print(f"Error eliminando socio de negocio {razon_social} (RUT: {rut}): {e}")
        conn_postgres.rollback()
        return False

def main():
    # Ajusta esta ruta a la ubicación de tu archivo Excel
    # excel_path = 'C:/Users/rcamp/Downloads/proveedores.xlsx'
    excel_path = 'C:/Users/EXTNEORONIA/Desktop/proveedores.xlsx'
    socios_to_delete = read_excel_data(excel_path)
    
    print(f"Se encontraron {len(socios_to_delete)} socios de negocio para eliminar")

    successful_deletions = 0
    failed_deletions = 0
    failed_list = []

    for razon_social, rut in socios_to_delete:
        print(f"\nProcesando: {razon_social} (RUT: {rut})")
        if delete_socio_negocio(razon_social, rut):
            successful_deletions += 1
        else:
            failed_deletions += 1
            failed_list.append((razon_social, rut))

    print("\nResumen del proceso:")
    print(f"Total procesados: {len(socios_to_delete)}")
    print(f"Eliminados exitosamente: {successful_deletions}")
    print(f"Fallidos: {failed_deletions}")

    if failed_list:
        print("\nRegistros que no se pudieron eliminar:")
        for razon_social, rut in failed_list:
            print(f"- {razon_social} (RUT: {rut})")

if __name__ == "__main__":
    try:
        main()
    finally:
        conn_postgres.close() 