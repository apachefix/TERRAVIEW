# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os
import sys

# Agregar la carpeta gtk/bin al PATH para que WeasyPrint encuentre las DLLs de GTK3
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTK_BIN_PATH = os.path.join(BASE_DIR, 'gtk', 'bin')

if os.path.exists(GTK_BIN_PATH):
    # Agregar al PATH del sistema
    os.environ['PATH'] = GTK_BIN_PATH + os.pathsep + os.environ.get('PATH', '')
    # También agregar al sys.path para que Python pueda encontrar las DLLs
    if GTK_BIN_PATH not in sys.path:
        sys.path.insert(0, GTK_BIN_PATH)

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

application = get_wsgi_application()
