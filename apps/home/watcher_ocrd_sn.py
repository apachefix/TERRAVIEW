"""Compatibilidad para ejecuciones heredadas del sincronizador OCRD.

No abre conexiones ni sincroniza al importarse. Para uso operativo se prefiere
``py manage.py sincronizar_transportes_sap --all``.
"""

from apps.home.services.transportes_sap import sincronizar_transportes_sap


def main(*, dry_run=False):
    """Ejecuta explícitamente la sincronización de transportistas de ambas empresas."""
    return sincronizar_transportes_sap(dry_run=dry_run)


if __name__ == '__main__':
    main()
