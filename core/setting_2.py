# -*- encoding: utf-8 -*-
"""
Configuración Django para TERRAVIEW
Dominio: http://terraview.terramar-group.com
"""

from ast import While
import os

from decouple import config
from dotenv import load_dotenv
from setuptools import logging
from unipath import Path


# =============================================================================
# RUTAS DEL PROYECTO
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

BASE_DIR = Path(__file__).parent

CORE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

# Carga el archivo .env ubicado junto a manage.py
load_dotenv(
    os.path.join(
        CORE_DIR,
        ".env",
    )
)


# =============================================================================
# SEGURIDAD
# =============================================================================

SECRET_KEY = config(
    "SECRET_KEY",
    default="cambiar-esta-clave-secreta-en-el-archivo-env",
)

DEBUG = config(
    "DEBUG",
    default=False,
    cast=bool,
)

ALLOWED_HOSTS = [
    host.strip()
    for host in config(
        "ALLOWED_HOSTS",
        default=(
            "terraview.terramar-group.com,"
            "localhost,"
            "127.0.0.1,"
            "101.44.3.251,"
            "172.16.1.144,"
            "186.10.67.182,"
            "terramar-portal.sapenlanube.com"
        ),
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config(
        "CSRF_TRUSTED_ORIGINS",
        default=(
            "http://terraview.terramar-group.com,"
            "https://terraview.terramar-group.com,"
            "http://terramar-portal.sapenlanube.com,"
            "https://terramar-portal.sapenlanube.com"
        ),
    ).split(",")
    if origin.strip()
]

CSRF_FAILURE_VIEW = "core.csrf.csrf_failure"

CSRF_COOKIE_SAMESITE = config(
    "CSRF_COOKIE_SAMESITE",
    default="Lax",
)

SESSION_COOKIE_SAMESITE = config(
    "SESSION_COOKIE_SAMESITE",
    default="Lax",
)

CSRF_COOKIE_HTTPONLY = False

SESSION_COOKIE_HTTPONLY = True

# Mientras la aplicación use HTTP, estas opciones deben permanecer en False.
CSRF_COOKIE_SECURE = config(
    "CSRF_COOKIE_SECURE",
    default=False,
    cast=bool,
)

SESSION_COOKIE_SECURE = config(
    "SESSION_COOKIE_SECURE",
    default=False,
    cast=bool,
)

SECURE_SSL_REDIRECT = config(
    "SECURE_SSL_REDIRECT",
    default=False,
    cast=bool,
)

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "SAMEORIGIN"


# =============================================================================
# APLICACIONES
# =============================================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.humanize",
    "apps.home",
]

SITE_ID = 1


# =============================================================================
# MIDDLEWARE
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =============================================================================
# URLS Y AUTENTICACIÓN
# =============================================================================

ROOT_URLCONF = "core.urls"

LOGIN_URL = "/login/"

LOGIN_REDIRECT_URL = "home"

LOGOUT_REDIRECT_URL = "home"


# =============================================================================
# PLANTILLAS
# =============================================================================

TEMPLATE_DIR = os.path.join(
    CORE_DIR,
    "apps",
    "templates",
)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            TEMPLATE_DIR,
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "custom_context_processor.get_users_active",
                "apps.home.context_processors.empresa_context",
            ],
        },
    },
]


# =============================================================================
# MICROSOFT GRAPH
# =============================================================================

MICROSOFT_GRAPH_TENANT_ID = config(
    "MICROSOFT_GRAPH_TENANT_ID",
    default="",
)

MICROSOFT_GRAPH_CLIENT_ID = config(
    "MICROSOFT_GRAPH_CLIENT_ID",
    default="",
)

MICROSOFT_GRAPH_CLIENT_SECRET = config(
    "MICROSOFT_GRAPH_CLIENT_SECRET",
    default="",
)

MICROSOFT_GRAPH_SENDER_USER = config(
    "MICROSOFT_GRAPH_SENDER_USER",
    default="",
)


# =============================================================================
# MICROSOFT TEAMS
# =============================================================================

TEAMS_WEBHOOK_URL = config(
    "TEAMS_WEBHOOK_URL",
    default="",
)

TEAMS_WEBHOOK_MODE = config(
    "TEAMS_WEBHOOK_MODE",
    default="adaptive",
)

CALIDAD_TEAMS_MAX_INTENTOS = config(
    "CALIDAD_TEAMS_MAX_INTENTOS",
    default=3,
    cast=int,
)


# =============================================================================
# CONFIGURACIÓN PÚBLICA DE TERRAVIEW
# =============================================================================

APP_PUBLIC_BASE_URL = config(
    "APP_PUBLIC_BASE_URL",
    default="http://terraview.terramar-group.com",
)

TERRAVIEW_CALIDAD_API_KEY = config(
    "TERRAVIEW_CALIDAD_API_KEY",
    default="",
)


# =============================================================================
# INTEGRACIÓN SAP
# =============================================================================

SAP_GOODS_RECEIPT_DRAFT_SERIES = config(
    "SAP_GOODS_RECEIPT_DRAFT_SERIES",
    default=17,
    cast=int,
)

SAP_GOODS_RECEIPT_DRAFT_OBJECT_CODE = config(
    "SAP_GOODS_RECEIPT_DRAFT_OBJECT_CODE",
    default="20",
)

SAP_DRAFT_QA_COMPANY_DB = config(
    "SAP_DRAFT_QA_COMPANY_DB",
    default="",
)

SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT = config(
    "SAP_RECEPCION_ENVIAR_LOTE_EN_UPDATE_DRAFT",
    default=False,
    cast=bool,
)


# =============================================================================
# WSGI
# =============================================================================

WSGI_APPLICATION = "core.wsgi.application"


# =============================================================================
# BASE DE DATOS POSTGRESQL
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config(
            "DB_NAME",
            default="TERRA_CONTROL",
        ),
        "USER": config(
            "DB_USER",
            default="postgres",
        ),
        "PASSWORD": config(
            "DB_PASSWORD",
            default="admin",
        ),
        "HOST": config(
            "DB_HOST",
            default="127.0.0.1",
        ),
        "PORT": config(
            "DB_PORT",
            default="5432",
        ),
        "CONN_MAX_AGE": config(
            "DB_CONN_MAX_AGE",
            default=60,
            cast=int,
        ),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}


# =============================================================================
# CACHÉ
# =============================================================================

# Para la demo se usa caché local.
# Esto evita depender de Redis en el servidor.

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "terraview-demo-cache",
        "TIMEOUT": 300,
        "OPTIONS": {
            "MAX_ENTRIES": 1000,
        },
    }
}


# =============================================================================
# VALIDACIÓN DE CONTRASEÑAS
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# =============================================================================
# IDIOMA Y ZONA HORARIA
# =============================================================================

LANGUAGE_CODE = "es-cl"

TIME_ZONE = "America/Santiago"

USE_I18N = True

USE_TZ = True


# =============================================================================
# ARCHIVOS ESTÁTICOS
# =============================================================================

STATIC_URL = "/static/"

STATIC_ROOT = os.path.join(
    CORE_DIR,
    "staticfiles",
)

STATICFILES_DIRS = [
    os.path.join(
        CORE_DIR,
        "apps",
        "static",
    ),
]

# Se utiliza CompressedStaticFilesStorage y no ManifestStorage porque
# algunos CSS del proyecto hacen referencia a archivos .map inexistentes.

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

WHITENOISE_USE_FINDERS = False

WHITENOISE_AUTOREFRESH = False


# =============================================================================
# ARCHIVOS MEDIA
# =============================================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = os.path.join(
    CORE_DIR,
    "media",
)
TERRAMAR_DOCUMENTOS_FIRMADOS_DIR = os.environ.get(
    "TERRAMAR_DOCUMENTOS_FIRMADOS_DIR",
    r"C:\Documentos_firmados",
)


# =============================================================================
# SESIONES
# =============================================================================

SESSION_ENGINE = "django.contrib.sessions.backends.db"

SESSION_COOKIE_AGE = config(
    "SESSION_COOKIE_AGE",
    default=28800,
    cast=int,
)

SESSION_SAVE_EVERY_REQUEST = False

SESSION_EXPIRE_AT_BROWSER_CLOSE = False


# =============================================================================
# REGISTRO DE EVENTOS
# =============================================================================

LOG_DIR = os.path.join(
    CORE_DIR,
    "logs",
)

os.makedirs(
    LOG_DIR,
    exist_ok=True,
)



LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "{levelname} "
                "{asctime} "
                "{name} "
                "{module} "
                "{message}"
            ),
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(
                LOG_DIR,
                "terraview.log",
            ),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": [
            "console",
            "file",
        ],
        "level": config(
            "LOG_LEVEL",
            default="INFO",
        ),
    },
    "loggers": {
        "django": {
            "handlers": [
                "console",
                "file",
            ],
            "level": config(
                "DJANGO_LOG_LEVEL",
                default="INFO",
            ),
            "propagate": False,
        },
    },
}

