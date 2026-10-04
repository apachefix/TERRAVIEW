"""Presentation configuration only. Never advances or persists workflow state.

Keys are (company, sequence code, citation type); no fallback across sequences.
OPL_CPASO is the existing workflow's persisted natural key, not an ET_CNOMBRE
comparison. Optional overrides use (company, sequence code, ET_CCODIGO, OPL_CPASO).
Physical coordinates require verification against this PDF, not the legacy map.
"""
from copy import deepcopy
import json
from pathlib import Path


ZONAS = {
    codigo: {'codigo': codigo, 'nombre': nombre, 'x_pct': None, 'y_pct': None,
             'width_pct': 16, 'height_pct': 10, 'habilitado': True}
    for codigo, nombre in (
        ('ROMANA', 'Romana'), ('MUESTREO', 'Muestreo'),
        ('ESPERA_CALIDAD', 'Espera de calidad'), ('VAPOR', 'Vapor'),
        ('ESPERA', 'Espera de carga / descarga'), ('CARGA', 'Carga'),
        ('DESCARGA', 'Descarga'), ('DOCUMENTACION', 'Documentación'),
        ('SALIDA', 'Portería / salida'), ('OTRO', 'Sin zona configurada'),
    )
}

# Manual rectangles, relative to the FULL PNG (top-left origin). Initial visual
# supplied by the user on 2026-10-04: waiting at (44,66), operation at (45,37).
# Initial coordinates, not final physical calibration.
# Edit only these four percentages to calibrate; no template/JS coordinates.
ZONAS.update({
    'ZONA_ESPERA': {
        'codigo': 'ZONA_ESPERA', 'nombre': 'Zona de espera',
        'x_pct': 44, 'y_pct': 66, 'width_pct': 22, 'height_pct': 16,
        'habilitado': True, 'distribucion': 'espera', 'columnas': 4,
    },
    'ZONA_CARGA_DESCARGA': {
        'codigo': 'ZONA_CARGA_DESCARGA', 'nombre': 'Carga / descarga',
        'x_pct': 45, 'y_pct': 37, 'width_pct': 21, 'height_pct': 18,
        'habilitado': True, 'distribucion': 'por_tipo', 'slots_por_tipo': 4,
    },
})

# Translate audited operational categories AFTER resolving workflow and timers.
# Do not merge KPI categories or infer zones from visible labels.
ZONAS_FISICAS = {
    'ESPERA': 'ZONA_ESPERA',
    'ESPERA_CALIDAD': 'ZONA_ESPERA',
    'CARGA': 'ZONA_CARGA_DESCARGA',
    'DESCARGA': 'ZONA_CARGA_DESCARGA',
}

# Explicit, independent dictionaries: changing one sequence cannot change another.
def _reglas(ciclo, zona_ciclo, calidad=False, cierre=False):
    reglas = {'Pesaje Entrada': 'ROMANA', 'Pesaje Salida': 'ROMANA',
              ciclo: zona_ciclo, 'Autorizar Salida': 'SALIDA',
              'Confirmar Salida': 'SALIDA'}
    if calidad:
        reglas.update({'Toma de muestra': 'MUESTREO', 'Analisis y calidad': 'ESPERA_CALIDAD',
                       'Resultado Calidad': 'ESPERA_CALIDAD'})
    if cierre:
        reglas.update({'Cierre Proceso de Carga': 'DOCUMENTACION',
                       'Emision de documentos': 'DOCUMENTACION'})
    else:
        reglas['Documentación'] = 'DOCUMENTACION'
    return reglas


REGLAS = {
    (1, 'RECEPCION_TERRAMAR', 'RECEPCION'): _reglas('Ciclo Descarga', 'DESCARGA'),
    (1, 'DESPACHO_TERRAMAR', 'DESPACHO'): _reglas('Ciclo Carga', 'CARGA'),
    (2, 'RECEPCION_ESTANQUE_SBH', 'RECEPCION'): _reglas('Ciclo Descarga', 'DESCARGA', calidad=True),
    (2, 'RECEPCION_TRASVASIJE', 'RECEPCION'): _reglas('Ciclo Descarga', 'DESCARGA', calidad=True),
    (2, 'RECEPCION_PATIO_LF_CON_CALIDAD', 'RECEPCION'): _reglas('Ciclo Descarga', 'DESCARGA', calidad=True),
    (2, 'RECEPCION_PATIO_LF_SIN_CALIDAD', 'RECEPCION'): _reglas('Ciclo Descarga', 'DESCARGA'),
    (2, 'EST_SBH_CLIENTE', 'DESPACHO'): _reglas('Ciclo Descarga', 'CARGA', cierre=True),
    (2, 'TRASVASIJE_CLIENTE', 'DESPACHO'): _reglas('Ciclo Descarga', 'CARGA', cierre=True),
    (2, 'BODEGA_PATIO_CLIENTE', 'DESPACHO'): _reglas('Ciclo Descarga', 'CARGA', cierre=True),
}

# Overrides are scoped to a sequence and technical stage, never a global stage name.
REGLAS_ETAPA = {}

# Coordinates extracted from PDF text labels (percent of the full page).
# These identify physical tanks only; they do NOT assert a database alias.
ESTANQUES_PLANO = json.loads((Path(__file__).resolve().parents[2] / 'static/assets/plano/estanques_plano.json').read_text(encoding='utf-8'))

# Populate only with confirmed equivalences, e.g.
# (2, 'RECEPCION_ESTANQUE_SBH', 'SBH', 'TK08'): 'TK-08'.
# TKMX*, TK13+, PROSE* and different sequences must never inherit this mapping.
ESTANQUES_CONFIRMADOS = {}


def zonas_configuradas():
    return deepcopy({**ZONAS, **ESTANQUES_PLANO})
