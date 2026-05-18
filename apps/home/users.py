import psycopg2
from django.contrib.auth.hashers import make_password
import hashlib

# Configuración de la conexión a PostgreSQL
config_postgres = 'dbname=TERRAMAR_CAMIONES user=postgres password=Terramar2024 host=localhost port=5432'

try:
    conn_postgres = psycopg2.connect(config_postgres)
    cursor_postgres = conn_postgres.cursor()
except Exception as e:
    print(f"Error conectando a la base de datos: {e}")
    exit(1)


def get_providers():
    try:
        query = """
            SELECT 
                sn.id,
                sn."SN_CRUT",
                sn."SN_CRAZONSOCIAL",
                sn."SN_CEMAIL",
                sn."EP_NID_id"
            FROM "SOCIONEGOCIO" sn
            WHERE sn."SN_CTIPO" = 'S'
            AND sn."SN_CRUT" NOT IN (
                SELECT username 
                FROM auth_user
            )
            AND sn."SN_BHABILITADO" = TRUE
        """
        cursor_postgres.execute(query)
        return cursor_postgres.fetchall()
    except Exception as e:
        print(f"Error obteniendo proveedores: {e}")
        return []

def insert_user(data):
    try:
        query = """
            INSERT INTO auth_user (
                username,
                password,
                first_name,
                email,
                is_active,
                date_joined,
                is_staff,
                is_superuser,
                last_name,
                last_login
            ) VALUES (
                %s,
                %s,
                %s,
                %s,
                TRUE,
                CURRENT_TIMESTAMP,
                FALSE,
                FALSE,
                '',
                CURRENT_TIMESTAMP
            ) RETURNING id
        """
        cursor_postgres.execute(query, data)
        user_id = cursor_postgres.fetchone()[0]
        conn_postgres.commit()
        return user_id
    except Exception as e:
        print(f"Error insertando usuario: {e}")
        conn_postgres.rollback()
        return None

def insert_user_extension(user_id):
    try:
        query = """
            INSERT INTO "USERS_EXTENSION" (
                "US_NID_id",
                "UX_IS_ADMINISTRADOR_SECUENCIA",
                "UX_IS_ADMINISTRADOR_ETAPA",
                "UX_IS_PLANIFICADOR",
                "UX_IS_CONDUCTOR",
                "UX_IS_RECEPCIONISTA",
                "UX_IS_CLIENTE",
                "UX_IS_PROVEEDOR",
                "UX_IS_OPERADOR",
                "UX_IS_REPORTES",
                "UX_IS_PROFORMA",
                "UX_IS_TERRAMAR",
                "UX_IS_ACEITES",
                "UX_IS_ADMINISTRADOR_CONDUCTOR"
            ) VALUES (
                %s,
                FALSE,
                FALSE,
                FALSE,
                FALSE,
                FALSE,
                FALSE,
                TRUE,
                FALSE,
                FALSE,
                FALSE,
                FALSE,
                FALSE,
                FALSE
            )
        """
        cursor_postgres.execute(query, [user_id])
        conn_postgres.commit()
        return True
    except Exception as e:
        print(f"Error insertando extensión de usuario: {e}")
        conn_postgres.rollback()
        return False

def insert_usuario_socionegocio(empresa_id, user_id, socio_id):
    try:
        query = """
            INSERT INTO "USUARIO_SOCIONEGOCIO" (
                "EP_NID_id",
                "US_NID_id",
                "SN_NID_id",
                "USC_CTIPO"
            ) VALUES (
                %s,
                %s,
                %s,
                'S'
            )
        """
        cursor_postgres.execute(query, [empresa_id, user_id, socio_id])
        conn_postgres.commit()
        return True
    except Exception as e:
        print(f"Error insertando usuario-socionegocio: {e}")
        conn_postgres.rollback()
        return False

def insert_users_empresa(user_id):
    try:
        query = """
            INSERT INTO "USERS_EMPRESA" (
                "EP_NID_id",
                "US_NID_id"
            ) VALUES (
                1,
                %s
            )
        """
        cursor_postgres.execute(query, [user_id])
        conn_postgres.commit()
        return True
    except Exception as e:
        print(f"Error insertando usuario-empresa: {e}")
        conn_postgres.rollback()
        return False

def insert_perfil_usuario(user_id):
    try:
        query = """
            INSERT INTO "PERFIL_USUARIO" (
                "PE_BHABILITADO",
                "PR_NID_id",
                "US_NID_id"
            ) VALUES (
                TRUE,
                7,  -- ID del perfil de proveedor
                %s
            )
        """
        cursor_postgres.execute(query, [user_id])
        conn_postgres.commit()
        return True
    except Exception as e:
        print(f"Error insertando perfil-usuario: {e}")
        conn_postgres.rollback()
        return False

def main():
    providers = get_providers()
    print(f"Se encontraron {len(providers)} proveedores sin usuario")

    for provider in providers:
        socio_id, rut, razon_social, email, empresa_id = provider
        
        # Preparar datos del usuario
        user_data = [
            rut,  # username
            'pbkdf2_sha256$720000$hC1M8TiQyMnSwe86u75zj2$JseeUSrIWPM39q5FWbjpuLVUDZU1jS1GhUMwW9w73s0=',  # password hasheado
            razon_social,  # first_name
            email if email else ''  # email
        ]

        print(f"\nProcesando proveedor: {razon_social} (RUT: {rut})")
        
        # Crear usuario
        user_id = insert_user(user_data)
        if not user_id:
            print(f"Error al crear usuario para {razon_social}")
            continue

        # Crear extensión de usuario
        if not insert_user_extension(user_id):
            print(f"Error al crear extensión de usuario para {razon_social}")
            continue

        # Crear relación usuario-empresa
        if not insert_users_empresa(user_id):
            print(f"Error al crear relación usuario-empresa para {razon_social}")
            continue

        # Crear relación usuario-socionegocio
        if not insert_usuario_socionegocio(empresa_id, user_id, socio_id):
            print(f"Error al crear relación usuario-socionegocio para {razon_social}")
            continue

        # Crear relación perfil-usuario
        if not insert_perfil_usuario(user_id):
            print(f"Error al crear relación perfil-usuario para {razon_social}")
            continue

        print(f"Usuario creado exitosamente para {razon_social}")

    print("\nProceso completado")

if __name__ == "__main__":
    main()
    conn_postgres.close()