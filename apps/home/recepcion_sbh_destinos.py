"""Maestro operacional de destinos para Planificacion - Recepcion SBH - Etapa 0."""


ALMACENES_DESTINO_RECEPCION_SBH = {
    'CANOPY': [f'TK{numero:02d}' for numero in range(13, 19)],
    'CISTERNA': [f'CISTER{numero}' for numero in range(10, 62)] + [
        'CISTERSN',
    ] + [f'CISTER_{numero}' for numero in range(1, 10)],
    'PATIO DE CAMIONES': [
        'PATIO_PC',
    ],
    'PATIO SBH': [
        'B_TRANSI',
        'F_ESTANQ',
        'ISOTANK1',
        'ISOTANK2',
        'ISOTANK3',
        'ISOTANK4',
        'ISOTANK5',
        'PATIO_BO',
        'PATIO_CA',
        'PATIO_LF',
        'PATIO_NJ',
        'S_PRODUC',
    ],
    'PROSESA': [
        'PROCESA',
        'PROSEG10',
        'PROSE_G2',
        'PROSE_G4',
        'PROSE_G9',
        'PROSE_T3',
        'PROSE_T4',
        'PROSE_T5',
        'PROSE_T8',
    ],
    'PUERTO': [
        'PTO SBH',
        'Z_PRIMAR',
    ],
    'SBH': [f'TK{numero:02d}' for numero in range(1, 13)] + [
        f'TKMX{numero:02d}' for numero in range(1, 5)
    ],
}


ALMACENES_RECEPCION_SBH_ETAPA_0 = tuple(
    (codigo, codigo) for codigo in ALMACENES_DESTINO_RECEPCION_SBH
)


def validar_destino_recepcion_sbh(almacen, ubicacion):
    almacen = str(almacen or '').strip()
    ubicacion = str(ubicacion or '').strip()
    if almacen not in ALMACENES_DESTINO_RECEPCION_SBH:
        return False, 'El almacén destino seleccionado no es válido.'
    if ubicacion not in ALMACENES_DESTINO_RECEPCION_SBH[almacen]:
        return False, 'La ubicación seleccionada no pertenece al almacén destino.'
    return True, ''
