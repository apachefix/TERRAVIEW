from django import template
from apps.home.models import PERFIL_USUARIO
import locale
import logging

register = template.Library()

# Logger para registrar problemas con locale
logger = logging.getLogger(__name__)

def setup_chile_locale():
    """
    Configura el locale chileno específicamente
    """
    try:
        locale.setlocale(locale.LC_ALL, 'es_CL.UTF-8')
        logger.info("Locale es_CL.UTF-8 configurado exitosamente")
        return True
    except locale.Error as e:
        logger.error(f"No se pudo configurar es_CL.UTF-8: {e}")
        return False

def check_and_reset_chile_locale():
    """
    Verifica si el locale chileno está activo y lo resetea si es necesario
    """
    try:
        current_locale = locale.getlocale(locale.LC_NUMERIC)
        
        # Verificar si es el locale chileno
        if not current_locale[0] or current_locale[0] != 'es_CL':
            logger.warning(f"Locale actual no es es_CL: {current_locale}, reconfigurando...")
            return setup_chile_locale()
        
        return True
    except Exception as e:
        logger.error(f"Error al verificar locale: {e}, reconfigurando...")
        return setup_chile_locale()

# Configuración inicial
setup_chile_locale()

@register.filter
def custom_number_format(value):
    """
    Formatea números con separadores de miles chilenos
    """
    # Verificar y resetear locale chileno si es necesario
    locale_ok = check_and_reset_chile_locale()
    
    # Si value es None o no se puede convertir a float, se trata como 0
    try:
        valor = float(value)
    except (TypeError, ValueError):
        valor = 0

    if locale_ok:
        try:
            # Comprobamos si el número es entero comparándolo con su versión entera
            if valor == int(valor):
                # Formatear como número entero (sin decimales)
                formatted_number = locale.format_string('%d', int(valor), grouping=True)
            else:
                # Formatear como número con decimales
                formatted_number = locale.format_string('%.3f', valor, grouping=True)
            
            return formatted_number
            
        except locale.Error as e:
            logger.error(f"Error de locale chileno al formatear {value}: {e}")
            # Fallback a formateo manual chileno
            return chile_manual_format(valor)
    else:
        # Si no se pudo configurar el locale chileno, usar formateo manual
        logger.warning("Usando formateo manual chileno por falta de locale del sistema")
        return chile_manual_format(valor)

def chile_manual_format(value):
    """
    Formateo manual específico para Chile cuando locale no está disponible
    Formato chileno: separador de miles con punto (.) y decimales con coma (,)
    """
    try:
        valor = float(value)
        
        if valor == int(valor):
            # Número entero - separador de miles con punto
            num_str = f"{int(valor):,}".replace(',', '.')
        else:
            # Número con decimales - miles con punto, decimales con coma
            # Primero formatear con separadores estándar
            formatted = f"{valor:,.3f}"
            # Intercambiar: comas por puntos (miles) y punto por coma (decimales)
            num_str = formatted.replace(',', 'TEMP').replace('.', ',').replace('TEMP', '.')
        
        return num_str
    except Exception as e:
        logger.error(f"Error en formateo manual chileno: {e}")
        return str(value)

@register.simple_tag
def check_permisos(perfil, vista):
    return perfil.CHECK_PERMISOS(perfil.id, vista)

@register.simple_tag
def chile_locale_status():
    """
    Tag para verificar el estado del locale chileno (útil para debugging)
    """
    try:
        current = locale.getlocale()
        return f"Locale actual: {current[0] if current[0] else 'No configurado'}"
    except:
        return "Error al obtener locale"

@register.filter
def multiply(value, arg):
    """Multiplica dos números"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
