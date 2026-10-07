"""Run map/regression tests on a disposable in-memory DB, never the configured DB.

From the repository root: venv/Scripts/python.exe -m apps.home.tests.run_mapa_operacional
Bootstrap tables before importing legacy forms, whose class definitions query DB.
"""
import os


def main():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
    from django.conf import settings
    settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
    settings.MIGRATION_MODULES = {'home': None}
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    settings.ALLOWED_HOSTS = ['testserver', 'localhost']
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', run_syncdb=True, skip_checks=True, verbosity=0)
    from django.test.runner import DiscoverRunner
    return bool(DiscoverRunner(verbosity=1).run_tests([
        'apps.home.tests.test_mapa_operacional',
        'apps.home.tests.test_operacion_planta_terramar_etapa1',
        'apps.home.tests.test_operaciones_terminadas',
    ]))


if __name__ == '__main__':
    raise SystemExit(main())
