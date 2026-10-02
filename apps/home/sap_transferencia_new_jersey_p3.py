"""StockTransfer final de Empresa 2 Recepcion New Jersey Proceso 3."""

import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from requests.exceptions import HTTPError

from apps.integrations.sap_b1.sap_recepcion import obtener_fecha_sistema_sap
from apps.integrations.sap_b1.service_layer_probe import SapServiceLayerClient, load_config

from . import new_jersey_p2 as nj_p2
from . import new_jersey_p3 as nj_p3
from .models import (
    CAMPO, CITACION, DATO_OPERACION, DETALLE_SECUENCIA, ETAPA,
    OPERACION_NEW_JERSEY, OPERACION_NEW_JERSEY_PROCESO, OPERACION_PLANTA_LOG,
)
from .sap_di_api import _rows
from .sap_recepcion_new_jersey import (
    get_new_jersey_virtual_warehouse,
    get_purchase_delivery_note_new_jersey_p1_status,
    obtener_lote_sap_new_jersey_p1,
)
from .sap_solicitud_new_jersey_p2 import estado_solicitud_traslado_new_jersey_p2
from .sap_transferencia_prosesa import (
    consultar_articulo_y_bodegas_prosesa,
    consultar_stock_lote_prosesa,
)


ENDPOINT_TRANSFERENCIA = '/StockTransfers'
LOG_TRANSFERENCIA = 'NJ_P3_STOCK_TRANSFER'
CAMPO_TRANSFERENCIA = 'NJ_P3_STOCK_TRANSFER_SAP'
CAMPO_TK_FINAL = 'NJ_P3_TK_DESTINO_FINAL'
CAMPO_PESO_REAL = 'NJ_PESO_FINAL_PRODUCTO_KG'
REFERENCIA_TERRAVIEW = 'TERRAVIEW'
FORMULA_PESO_REAL = '(P1_ENT - P1_SAL) - (P3_SAL - P3_ENT)'

CONFIGURACION_PESAJES = {
    'p1_ent': {'proceso': 'p1', 'tipo': 'ENT', 'codigo_qa': 'QA_NJ_P1_PESO_ENTRADA',
               'etiqueta': 'P1 - Pesaje Entrada', 'grupo': 'P1', 'nombre': 'Entrada'},
    'p1_sal': {'proceso': 'p1', 'tipo': 'SAL', 'codigo_qa': 'QA_NJ_P1_PESO_SALIDA',
               'etiqueta': 'P1 - Pesaje Salida', 'grupo': 'P1', 'nombre': 'Salida'},
    'p3_ent': {'proceso': 'p3', 'tipo': 'ENT', 'codigo_qa': 'QA_NJ_P3_PESO_ENTRADA',
               'etiqueta': 'P3 - Pesaje Entrada / tara camion', 'grupo': 'P3',
               'nombre': 'Entrada / tara'},
    'p3_sal': {'proceso': 'p3', 'tipo': 'SAL', 'codigo_qa': 'QA_NJ_P3_PESO_SALIDA',
               'etiqueta': 'P3 - Pesaje Salida con contenedor vacio', 'grupo': 'P3',
               'nombre': 'Salida'},
}


def _json_dict(valor):
    try:
        data = json.loads(valor or '{}')
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _decimal(valor, mensaje='El valor no es numerico.'):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(mensaje)


def es_new_jersey_p3_sap(citacion):
    return bool(
        citacion and citacion.EP_NID_id == nj_p3.EMPRESA_NJ
        and str(citacion.CI_CTIPO or '').upper() == 'RECEPCION'
        and citacion.SC_NID and citacion.SC_NID.SE_CCODIGO == nj_p3.SECUENCIA_P3
    )


def _relaciones(citacion):
    if not es_new_jersey_p3_sap(citacion):
        raise ValueError('La citacion no corresponde a New Jersey P3 de Empresa 2.')
    try:
        p3 = OPERACION_NEW_JERSEY_PROCESO.objects.select_related('ONJ_NID').get(
            CI_NID=citacion, EP_NID_id=nj_p3.EMPRESA_NJ,
            ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_3,
        )
        comunes = {
            'ONJ_NID': p3.ONJ_NID, 'EP_NID_id': nj_p3.EMPRESA_NJ,
        }
        p1 = OPERACION_NEW_JERSEY_PROCESO.objects.select_related(
            'CI_NID__SC_NID', 'CI_NID__detalle_operacional',
        ).get(ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_1, **comunes)
        p2 = OPERACION_NEW_JERSEY_PROCESO.objects.select_related(
            'CI_NID__SC_NID', 'CI_NID__detalle_operacional',
        ).get(ONJP_CTIPO=OPERACION_NEW_JERSEY_PROCESO.TipoProceso.PROCESO_2, **comunes)
    except OPERACION_NEW_JERSEY_PROCESO.DoesNotExist as exc:
        raise ValueError('Falta la relacion completa P1/P2/P3 de New Jersey.') from exc
    return p1, p2, p3


def _etapa(citacion):
    try:
        actual = citacion.ETAPA_ACTUAL
    except AttributeError:
        actual = None
    if actual:
        return actual
    detalle = DETALLE_SECUENCIA.objects.select_related('ET_NID').filter(
        SC_NID=citacion.SC_NID, EP_NID=citacion.EP_NID, SE_BHABILITADO=True,
    ).order_by('SE_NPASO', 'id').first()
    if detalle:
        return detalle.ET_NID
    etapa = ETAPA.objects.filter(
        EP_NID=citacion.EP_NID, ET_BHABILITADO=True,
    ).order_by('id').first()
    if not etapa:
        raise ValueError('La empresa no tiene etapa habilitada para persistir el dato.')
    return etapa


def _campo(citacion, usuario, codigo, etiqueta, tipo='TEXTO', obligatorio=False):
    campo, _ = CAMPO.objects.get_or_create(
        EP_NID=citacion.EP_NID, CA_CCODIGO=codigo,
        defaults={
            'US_NID': usuario, 'CA_CTIPO': tipo, 'CA_CETIQUETA': etiqueta,
            'CA_CPLACEMARK': etiqueta, 'CA_BOBLIGATORIO': obligatorio,
            'CA_BHABILITADO': True, 'CA_BASIGNARVALOR': False,
        },
    )
    return campo


def _ticket(citacion, tipo, etiqueta):
    codigo = f'OP_TICKET_PESAJE_{tipo}'
    dato = DATO_OPERACION.objects.filter(
        CI_NID=citacion, CAMP_NID__CA_CCODIGO=codigo,
    ).order_by('-DO_FFECHAREGISTRO', '-id').first()
    if not dato:
        raise ValueError(f'Falta {etiqueta}.')
    metadata = _json_dict(dato.DO_CVALOR)
    valor = dato.DO_NPESO
    if valor is None:
        valor = metadata.get('peso_bruto_kg', metadata.get('peso_neto'))
    peso = _decimal(valor, f'{etiqueta} no contiene un peso numerico.')
    if peso <= 0 or peso != peso.to_integral_value():
        raise ValueError(f'{etiqueta} debe ser un entero mayor que cero en kg.')
    return {
        'dato_id': dato.id, 'citacion_id': citacion.id, 'codigo_campo': codigo,
        'folio': str(metadata.get('folio') or ''),
        'patente': str(metadata.get('patente') or ''),
        'fecha_ticket': str(metadata.get('fecha_hora_ticket') or ''),
        'peso_original': int(peso), 'peso_efectivo': int(peso),
        'origen_peso': 'TICKET', 'override_dato_id': None,
    }


def _override_qa(citacion, configuracion, ticket):
    if not getattr(settings, 'QA_PESAJE', False):
        return ticket
    dato = DATO_OPERACION.objects.filter(
        CI_NID=citacion, CAMP_NID__CA_CCODIGO=configuracion['codigo_qa'],
    ).order_by('-DO_FFECHAREGISTRO', '-id').first()
    metadata = _json_dict(dato.DO_CVALOR) if dato else {}
    if (
        dato and metadata.get('activo', True)
        and dato.DO_NPESO is not None and dato.DO_NPESO > 0
        and metadata.get('ticket_dato_id') == ticket['dato_id']
    ):
        ticket.update({
            'peso_efectivo': dato.DO_NPESO, 'origen_peso': 'QA_OVERRIDE',
            'override_dato_id': dato.id,
        })
    return ticket


def resolver_pesajes_new_jersey_p3(citacion):
    p1_rel, p2_rel, p3_rel = _relaciones(citacion)
    datos = {
        'p1': p1_rel.CI_NID, 'p2': p2_rel.CI_NID, 'p3': p3_rel.CI_NID,
        'operacion': p3_rel.ONJ_NID, 'proceso_p3': p3_rel,
    }
    for clave, configuracion in CONFIGURACION_PESAJES.items():
        origen = datos['p1'] if configuracion['proceso'] == 'p1' else datos['p3']
        datos[clave] = _override_qa(
            origen, configuracion,
            _ticket(origen, configuracion['tipo'], configuracion['etiqueta']),
        )
    return datos


def calcular_peso_real_desde_pesajes(pesajes):
    valores = {clave: int(pesajes[clave]['peso_efectivo']) for clave in CONFIGURACION_PESAJES}
    cargado = valores['p1_ent'] - valores['p1_sal']
    vacio = valores['p3_sal'] - valores['p3_ent']
    real = cargado - vacio
    if cargado <= 0:
        raise ValueError(
            'Pesajes P1 inconsistentes: Entrada debe ser mayor que Salida '
            'para representar el conjunto cargado.'
        )
    if vacio <= 0:
        raise ValueError(
            'Pesajes P3 inconsistentes: Salida debe ser mayor que Entrada '
            'porque el camion sale con el contenedor vacio.'
        )
    if real <= 0:
        raise ValueError('El peso real New Jersey debe ser mayor que cero.')
    return {
        **valores, 'peso_conjunto_cargado_kg': cargado,
        'peso_contenedor_vacio_kg': vacio, 'peso_real_kg': real,
        'peso_real_mt': Decimal(real) / Decimal('1000'),
    }


def _firma(pesajes):
    firma = {}
    for clave in CONFIGURACION_PESAJES:
        ticket = pesajes[clave]
        firma.update({
            f'{clave}_dato_id': ticket['dato_id'],
            f'{clave}_override_dato_id': ticket['override_dato_id'],
            f'{clave}_peso_efectivo': ticket['peso_efectivo'],
            f'{clave}_origen': ticket['origen_peso'],
        })
    return firma


@transaction.atomic
def guardar_overrides_qa_pesaje_new_jersey_p3(citacion, overrides, usuario):
    if not getattr(settings, 'QA_PESAJE', False):
        raise PermissionError('QA_PESAJE esta deshabilitado; no se permiten overrides manuales.')
    if estado_transferencia_new_jersey_p3(citacion).get('bloqueada'):
        raise ValueError('Los pesos QA no pueden modificarse despues de crear o iniciar la transferencia SAP.')
    pesajes = resolver_pesajes_new_jersey_p3(citacion)
    guardados = []
    overrides = overrides or {}
    for clave, configuracion in CONFIGURACION_PESAJES.items():
        if clave not in overrides:
            continue
        valor = overrides.get(clave)
        ticket = pesajes[clave]
        origen = pesajes['p1'] if clave.startswith('p1_') else pesajes['p3']
        campo = _campo(
            origen, usuario, configuracion['codigo_qa'],
            f"Override QA {configuracion['etiqueta']}", 'NUMERO',
        )
        existente = DATO_OPERACION.objects.filter(
            CI_NID=origen, CAMP_NID=campo,
        ).order_by('-DO_FFECHAREGISTRO', '-id').first()
        metadata_existente = _json_dict(existente.DO_CVALOR) if existente else {}
        activo_existente = bool(
            existente and metadata_existente.get('activo', True)
            and metadata_existente.get('ticket_dato_id') == ticket['dato_id']
            and existente.DO_NPESO is not None and existente.DO_NPESO > 0
        )
        activo = False
        peso = None
        if valor not in (None, ''):
            try:
                peso_decimal = Decimal(str(valor).strip())
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f"{configuracion['etiqueta']} debe ser numerico.")
            if not peso_decimal.is_finite():
                raise ValueError(f"{configuracion['etiqueta']} no admite NaN ni infinito.")
            if peso_decimal <= 0:
                raise ValueError(f"{configuracion['etiqueta']} debe ser mayor que cero.")
            if peso_decimal != peso_decimal.to_integral_value():
                raise ValueError(
                    f"{configuracion['etiqueta']} debe expresarse en kg enteros "
                    'porque DO_NPESO almacena pesos enteros.'
                )
            peso = int(peso_decimal)
            activo = peso != ticket['peso_original']
        if activo:
            if activo_existente and existente.DO_NPESO == peso:
                continue
        elif not activo_existente:
            continue
        ahora = timezone.now()
        metadata = {
            'tipo': 'QA_OVERRIDE_PESAJE_NEW_JERSEY_P3',
            'accion': 'APLICAR' if activo else 'LIMPIAR', 'activo': activo,
            'clave_pesaje': clave, 'proceso': configuracion['proceso'].upper(),
            'operacion_new_jersey_id': pesajes['operacion'].id,
            'citacion_origen_id': origen.id, 'citacion_p3_id': pesajes['p3'].id,
            'ticket_dato_id': ticket['dato_id'], 'ticket_folio': ticket['folio'],
            'ticket_peso_original_kg': ticket['peso_original'],
            'peso_override_kg': peso if activo else None,
            'usuario': usuario.username, 'usuario_id': usuario.id,
            'fecha_override': ahora.isoformat(),
        }
        guardados.append(DATO_OPERACION.objects.create(
            US_NID=usuario, EP_NID=origen.EP_NID, SC_NID=origen.SC_NID,
            ET_NID=_etapa(origen), CAMP_NID=campo, CI_NID=origen,
            DO_CVALOR=json.dumps(metadata, ensure_ascii=False),
            DO_NPESO=peso if activo else None, DO_FFECHAREGISTRO=ahora,
        ))
    if guardados:
        peso_validado = _dato_peso(citacion)
        if peso_validado:
            metadata_peso = _json_dict(peso_validado.DO_CVALOR)
            metadata_peso.update({
                'invalidado': True,
                'motivo_invalidacion': 'Los pesos QA fueron modificados; debe recalcular.',
                'fecha_invalidacion': timezone.now().isoformat(),
                'usuario_invalidacion': usuario.username,
                'usuario_invalidacion_id': usuario.id,
            })
            peso_validado.DO_CVALOR = json.dumps(metadata_peso, ensure_ascii=False)
            peso_validado.save(update_fields=['DO_CVALOR'])
    return guardados


def _dato_peso(citacion):
    return DATO_OPERACION.objects.filter(
        CI_NID=citacion, CAMP_NID__CA_CCODIGO=CAMPO_PESO_REAL,
    ).order_by('-DO_FFECHAREGISTRO', '-id').first()


@transaction.atomic
def aplicar_overrides_qa_pesaje_new_jersey_p3(citacion, overrides, usuario):
    guardados = guardar_overrides_qa_pesaje_new_jersey_p3(citacion, overrides, usuario)
    pesajes = resolver_pesajes_new_jersey_p3(citacion)
    valores = {
        clave: int(pesajes[clave]['peso_efectivo'])
        for clave in CONFIGURACION_PESAJES
    }
    cargado = valores['p1_ent'] - valores['p1_sal']
    vacio = valores['p3_sal'] - valores['p3_ent']
    real = cargado - vacio
    error = ''
    try:
        calcular_peso_real_desde_pesajes(pesajes)
    except ValueError as exc:
        error = str(exc)
    dato_peso = _dato_peso(citacion)
    metadata_peso = _json_dict(dato_peso.DO_CVALOR) if dato_peso else {}
    return {
        'actualizado': bool(guardados),
        'overrides_guardados': len(guardados),
        'peso_real_invalidado': bool(metadata_peso.get('invalidado')),
        'pesajes': [
            {
                'clave': clave,
                'peso_original': pesajes[clave]['peso_original'],
                'peso_efectivo': pesajes[clave]['peso_efectivo'],
                'fuente': 'QA' if pesajes[clave]['origen_peso'] == 'QA_OVERRIDE' else 'TICKET',
                'override_dato_id': pesajes[clave]['override_dato_id'],
            }
            for clave in CONFIGURACION_PESAJES
        ],
        'peso_conjunto_cargado_kg': cargado,
        'peso_contenedor_vacio_kg': vacio,
        'peso_real_kg': real,
        'peso_real_mt': float(Decimal(real) / Decimal('1000')),
        'calculo_valido': not error,
        'error_calculo': error,
        'formula': FORMULA_PESO_REAL,
    }


@transaction.atomic
def calcular_y_persistir_peso_real_new_jersey_p3(citacion, usuario):
    citacion = CITACION.objects.select_for_update().select_related('SC_NID').get(
        pk=citacion.pk, EP_NID_id=nj_p3.EMPRESA_NJ, CI_BHABILITADO=True,
    )
    pesajes = resolver_pesajes_new_jersey_p3(citacion)
    calculo = calcular_peso_real_desde_pesajes(pesajes)
    firma = _firma(pesajes)
    campo = _campo(citacion, usuario, CAMPO_PESO_REAL, 'Peso real producto New Jersey P3',
                   'NUMERO', True)
    existente = DATO_OPERACION.objects.select_for_update().filter(
        CI_NID=citacion, CAMP_NID=campo,
    ).order_by('-id').first()
    anterior = _json_dict(existente.DO_CVALOR) if existente else {}
    if (
        existente and existente.DO_NPESO == calculo['peso_real_kg']
        and all(anterior.get(k) == v for k, v in firma.items())
    ):
        return existente, False
    fuentes = {
        clave: {
            'citacion_id': pesajes[clave]['citacion_id'],
            'codigo_dato': pesajes[clave]['codigo_campo'],
            'ticket_dato_id': pesajes[clave]['dato_id'],
            'folio': pesajes[clave]['folio'], 'patente': pesajes[clave]['patente'],
            'fecha_ticket': pesajes[clave]['fecha_ticket'],
            'peso_ticket_kg': pesajes[clave]['peso_original'],
            'peso_efectivo_kg': pesajes[clave]['peso_efectivo'],
            'origen': pesajes[clave]['origen_peso'],
            'override_dato_id': pesajes[clave]['override_dato_id'],
        } for clave in CONFIGURACION_PESAJES
    }
    ahora = timezone.now()
    metadata = {
        'operacion_new_jersey_id': pesajes['operacion'].id,
        'citacion_p1_id': pesajes['p1'].id, 'citacion_p2_id': pesajes['p2'].id,
        'citacion_p3_id': citacion.id, **firma, 'fuentes_pesajes': fuentes,
        'formula': FORMULA_PESO_REAL, 'version_formula': 1,
        'peso_conjunto_cargado_kg': calculo['peso_conjunto_cargado_kg'],
        'peso_contenedor_vacio_kg': calculo['peso_contenedor_vacio_kg'],
        'peso_real_kg': calculo['peso_real_kg'],
        'peso_real_mt': float(calculo['peso_real_mt']), 'unidad_origen': 'kg',
        'unidad_sap_esperada': 'MT', 'usuario': usuario.username,
        'usuario_id': usuario.id, 'fecha_calculo': ahora.isoformat(),
        'historial_calculos': list(anterior.get('historial_calculos') or []) + (
            [{'fecha_reemplazo': ahora.isoformat(), 'peso_real_kg': anterior.get('peso_real_kg'),
              'fuentes': anterior.get('fuentes_pesajes') or {}}] if anterior else []
        ),
    }
    valores = {
        'US_NID': usuario, 'EP_NID': citacion.EP_NID, 'SC_NID': citacion.SC_NID,
        'ET_NID': _etapa(citacion), 'DO_CVALOR': json.dumps(metadata, ensure_ascii=False),
        'DO_NPESO': calculo['peso_real_kg'], 'DO_FFECHAREGISTRO': ahora,
    }
    if existente:
        for nombre, valor in valores.items():
            setattr(existente, nombre, valor)
        existente.save(update_fields=list(valores))
        dato = existente
    else:
        dato = DATO_OPERACION.objects.create(CI_NID=citacion, CAMP_NID=campo, **valores)
    operacion = pesajes['operacion']
    if operacion.ONJ_CESTADO == OPERACION_NEW_JERSEY.Estado.PENDIENTE_PROCESO_3:
        operacion.ONJ_CESTADO = OPERACION_NEW_JERSEY.Estado.PENDIENTE_PESO_FINAL
        operacion.save(update_fields=['ONJ_CESTADO', 'ONJ_FFECHAMODIFICACION'])
    return dato, True


def obtener_peso_real_new_jersey_p3_para_sap(citacion):
    pesajes = resolver_pesajes_new_jersey_p3(citacion)
    dato = _dato_peso(citacion)
    if not dato or not dato.DO_NPESO or dato.DO_NPESO <= 0:
        raise ValueError('Debe calcular y validar el peso real New Jersey antes de SAP.')
    metadata = _json_dict(dato.DO_CVALOR)
    if metadata.get('invalidado'):
        raise ValueError('Los pesos QA cambiaron; debe recalcular y validar el peso real antes de SAP.')
    if metadata.get('citacion_p3_id') != citacion.id:
        raise ValueError('El peso real persistido no corresponde a esta P3.')
    if any(metadata.get(k) != v for k, v in _firma(pesajes).items()):
        raise ValueError('Los tickets o pesos QA cambiaron; debe recalcular antes de SAP.')
    calcular_peso_real_desde_pesajes(pesajes)
    return dato.DO_NPESO


def _dato_tk(citacion):
    return DATO_OPERACION.objects.filter(
        CI_NID=citacion, CAMP_NID__CA_CCODIGO=CAMPO_TK_FINAL,
    ).order_by('-DO_FFECHAREGISTRO', '-id').first()


def destino_vigente_p3(citacion):
    dato = _dato_tk(citacion)
    metadata = _json_dict(dato.DO_CVALOR) if dato else {}
    if metadata.get('tk_p3_final'):
        return str(metadata['tk_p3_final']).strip()
    try:
        _, p2, p3 = _relaciones(citacion)
    except ValueError:
        return ''
    detalle_p3 = getattr(p3.CI_NID, 'detalle_operacional', None)
    detalle_p2 = getattr(p2.CI_NID, 'detalle_operacional', None)
    return str(
        getattr(detalle_p3, 'CDO_CESTANQUE_DESTINO', '')
        or getattr(detalle_p2, 'CDO_CESTANQUE_DESTINO', '')
        or p3.ONJ_NID.ONJ_CTK_DESTINO or ''
    ).strip()


@transaction.atomic
def guardar_destino_final_p3(citacion, usuario, tk_destino):
    citacion = CITACION.objects.select_for_update().select_related('SC_NID').get(
        pk=citacion.pk, EP_NID_id=nj_p3.EMPRESA_NJ, CI_BHABILITADO=True,
    )
    p1, p2, p3 = _relaciones(citacion)
    if p3.ONJP_CESTADO != OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO:
        raise ValueError('New Jersey P3 no esta en proceso.')
    if estado_transferencia_new_jersey_p3(citacion)['bloqueada']:
        raise ValueError('El TK final no puede cambiarse despues de iniciar la transferencia SAP.')
    tk_destino = str(tk_destino or '').strip().upper()
    if tk_destino not in nj_p2.estanques_validos_p2():
        raise ValueError(nj_p2.MENSAJE_TK_INVALIDO_P2)
    anterior = destino_vigente_p3(citacion)
    d1, d2 = getattr(p1.CI_NID, 'detalle_operacional', None), getattr(p2.CI_NID, 'detalle_operacional', None)
    metadata = {
        'operacion_new_jersey_id': p3.ONJ_NID_id,
        'citacion_p1_id': p1.CI_NID_id, 'citacion_p2_id': p2.CI_NID_id,
        'citacion_p3_id': citacion.id,
        'tk_p1': str(getattr(d1, 'CDO_CESTANQUE_DESTINO', '') or p3.ONJ_NID.ONJ_CTK_DESTINO or '').strip(),
        'tk_p2_solicitado': str(getattr(d2, 'CDO_CESTANQUE_DESTINO', '') or '').strip(),
        'tk_p3_anterior': anterior, 'tk_p3_final': tk_destino,
        'usuario': usuario.username, 'usuario_id': usuario.id,
        'fecha_hora': timezone.now().isoformat(),
    }
    campo = _campo(citacion, usuario, CAMPO_TK_FINAL, 'TK destino final New Jersey P3')
    DATO_OPERACION.objects.update_or_create(
        CI_NID=citacion, CAMP_NID=campo,
        defaults={
            'US_NID': usuario, 'EP_NID': citacion.EP_NID, 'SC_NID': citacion.SC_NID,
            'ET_NID': _etapa(citacion), 'DO_CVALOR': json.dumps(metadata, ensure_ascii=False),
            'DO_FFECHAREGISTRO': timezone.now(),
        },
    )
    return {'tk_destino': tk_destino, 'tk_anterior': anterior,
            'changed': anterior != tk_destino, 'trazabilidad': metadata}


def estado_transferencia_new_jersey_p3(citacion):
    rechazado = None
    for log in OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion, OPL_CPASO=LOG_TRANSFERENCIA,
    ).select_related('US_NID').order_by('-OPL_FFECHAREGISTRO', '-id'):
        data = _json_dict(log.OPL_COBSERVACION)
        estado, response = data.get('estado'), data.get('response') or {}
        if estado == 'CREADO' and log.OPL_CESTADO == OPERACION_PLANTA_LOG.ESTADO_COMPLETADO and response.get('DocEntry'):
            return {
                'creada': True, 'bloqueada': True, 'estado': estado,
                'docentry': response.get('DocEntry'), 'docnum': response.get('DocNum'),
                'origen': data.get('origen'), 'destino': data.get('destino'),
                'item_code': data.get('item_code'), 'batch_number': data.get('batch_number'),
                'peso_real_kg': data.get('peso_real_kg'), 'quantity_mt': data.get('quantity_mt'),
                'usuario': data.get('usuario'),
                'fecha': data.get('fecha_resultado') or data.get('fecha_intento'),
            }
        if estado in {'ENVIANDO', 'INCIERTO'}:
            return {'creada': False, 'bloqueada': True, 'estado': estado}
        rechazado = estado
    return {'creada': False, 'bloqueada': False, 'estado': rechazado or 'NO_CREADA'}


def _schema_sap():
    config = load_config(nj_p3.EMPRESA_NJ, for_write=False)
    if not re.fullmatch(r'[A-Za-z0-9_]+', config.company_db or ''):
        raise ValueError('CompanyDB SAP invalida para la transferencia P3.')
    return config.company_db


def consultar_ingreso_virtual_new_jersey_p1(schema, status):
    lineas = (status.get('request_json') or {}).get('DocumentLines') or []
    if len(lineas) != 1:
        raise ValueError('El ingreso SAP P1 no conserva una linea unica auditable.')
    rows = _rows(f"""
        SELECT H."DocEntry" AS "docentry", H."DocNum" AS "docnum",
               L."ItemCode" AS "item_code", L."WhsCode" AS "warehouse",
               L."Quantity" AS "quantity", L."UomCode" AS "uom_code"
        FROM "{schema}"."OPDN" H
        JOIN "{schema}"."PDN1" L ON L."DocEntry" = H."DocEntry"
        WHERE H."DocEntry" = ? AND L."LineNum" = 0 AND H."CANCELED" = 'N'
    """, [status.get('docentry')])
    if len(rows) != 1:
        raise ValueError('No se encontro el ingreso SAP real de P1 en OPDN/PDN1.')
    row, linea = rows[0], lineas[0]
    if row.get('item_code') != linea.get('ItemCode') or row.get('warehouse') != linea.get('WarehouseCode'):
        raise ValueError('El ingreso SAP P1 no coincide con su payload confirmado.')
    if str(row.get('uom_code') or '').strip().upper() != 'MT':
        raise ValueError('La unidad del ingreso SAP P1 no es MT.')
    cantidad = _decimal(row.get('quantity'), 'Cantidad de ingreso SAP no numerica.')
    if cantidad <= 0:
        raise ValueError('El ingreso SAP P1 no tiene cantidad positiva.')
    return {**row, 'quantity': cantidad}


def buscar_transferencia_sap_new_jersey_p3(schema, citacion_id):
    rows = _rows(f"""
        SELECT "DocEntry" AS "docentry", "DocNum" AS "docnum",
               "Filler" AS "origen", "ToWhsCode" AS "destino"
        FROM "{schema}"."OWTR"
        WHERE "Ref1" = ? AND "Ref2" = ? AND "CANCELED" = 'N'
        ORDER BY "DocEntry" DESC
    """, [REFERENCIA_TERRAVIEW, str(citacion_id)])
    return rows[0] if rows else None


def build_stock_transfer_new_jersey_p3(citacion):
    result = {
        'document_type': 'StockTransfers', 'endpoint': ENDPOINT_TRANSFERENCIA,
        'flow': nj_p3.SECUENCIA_P3, 'ready_for_post': False, 'payload': {},
        'errors': [], 'validations': [],
        'source_data': {'citacion_p3': getattr(citacion, 'pk', None)},
        'status': estado_transferencia_new_jersey_p3(citacion),
    }
    errors, source = result['errors'], result['source_data']
    if not es_new_jersey_p3_sap(citacion):
        errors.append('La citacion no corresponde a New Jersey P3 de Empresa 2.')
        return result
    try:
        p1_rel, p2_rel, p3_rel = _relaciones(citacion)
    except ValueError as exc:
        errors.append(str(exc))
        return result
    p1, p2, operacion = p1_rel.CI_NID, p2_rel.CI_NID, p3_rel.ONJ_NID
    source.update({'operacion_new_jersey': operacion.id, 'citacion_p1': p1.id, 'citacion_p2': p2.id})
    if p3_rel.ONJP_CESTADO != OPERACION_NEW_JERSEY_PROCESO.Estado.EN_PROCESO:
        errors.append('New Jersey P3 debe estar en proceso para crear la transferencia SAP.')
    completados = set(OPERACION_PLANTA_LOG.objects.filter(
        CI_NID=citacion, OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_COMPLETADO,
    ).values_list('OPL_CPASO', flat=True))
    for paso in ('Pesaje Entrada', 'Carga / Descarga', 'Pesaje Salida'):
        if paso not in completados:
            errors.append(f'Debe completar {paso} antes de la transferencia SAP.')
    item, origen, destino = (
        str(operacion.ONJ_CITEM_CODE or '').strip(),
        str(get_new_jersey_virtual_warehouse() or '').strip(),
        destino_vigente_p3(citacion),
    )
    lote_info = obtener_lote_sap_new_jersey_p1(p1)
    lote = str(lote_info.get('batch_number') or '').strip()
    detalle = getattr(citacion, 'detalle_operacional', None)
    source.update({
        'guia': str(citacion.CI_CNUMERODOCUMENTO or '').strip(),
        'contenedor': str(getattr(detalle, 'CDO_CBL_CONTENEDOR', '') or '').strip(),
        'item_code': item, 'batch_number': lote, 'origen': origen, 'destino': destino,
        'tk_p1': str(operacion.ONJ_CTK_DESTINO or '').strip(),
        'tk_p2_solicitado': str(getattr(getattr(p2, 'detalle_operacional', None), 'CDO_CESTANQUE_DESTINO', '') or '').strip(),
    })
    if not item:
        errors.append('Falta ItemCode heredado de la operacion New Jersey.')
    if not origen:
        errors.append('Debe configurar BODEGA_VIRTUAL_NEW_JERSEY.')
    if destino not in nj_p2.estanques_validos_p2():
        errors.append(nj_p2.MENSAJE_TK_INVALIDO_P2)
    if origen and destino and origen == destino:
        errors.append('La bodega virtual y el TK destino deben ser distintos.')
    if not lote:
        errors.append('P1 no tiene un lote SAP persistido para reutilizar en P3.')
    elif str(lote_info.get('item_code') or '').strip() != item:
        errors.append('El lote SAP P1 corresponde a otro ItemCode.')
    ingreso_status = get_purchase_delivery_note_new_jersey_p1_status(p1)
    solicitud_status = estado_solicitud_traslado_new_jersey_p2(p2)
    source.update({
        'ingreso_p1_docentry': ingreso_status.get('docentry'),
        'ingreso_p1_docnum': ingreso_status.get('docnum'),
        'solicitud_p2_docentry': solicitud_status.get('docentry'),
        'solicitud_p2_docnum': solicitud_status.get('docnum'),
        'cantidad_provisional_p2_mt': solicitud_status.get('quantity_mt'),
    })
    if not ingreso_status.get('sent'):
        errors.append('P1 no tiene un PurchaseDeliveryNotes real confirmado.')
    if not solicitud_status.get('created'):
        errors.append('P2 no tiene una InventoryTransferRequest confirmada.')
    try:
        peso = _decimal(obtener_peso_real_new_jersey_p3_para_sap(citacion))
        cantidad = peso / Decimal('1000')
        source.update({'peso_real_kg': float(peso), 'quantity_mt': float(cantidad), 'unidad_sap': 'MT'})
    except ValueError as exc:
        peso, cantidad = None, None
        errors.append(str(exc))
    if result['status']['bloqueada']:
        errors.append('La transferencia SAP ya fue creada o tiene envio pendiente de conciliacion.')
    if errors:
        return result
    try:
        schema = _schema_sap()
        source['company_db'] = schema
        ingreso = consultar_ingreso_virtual_new_jersey_p1(schema, ingreso_status)
        source.update({
            'peso_ingresado_virtual_mt': float(ingreso['quantity']),
            'peso_ingresado_virtual_kg': float(ingreso['quantity'] * 1000),
            'remanente_ingreso_mt': float(ingreso['quantity'] - cantidad),
            'remanente_ingreso_kg': float((ingreso['quantity'] - cantidad) * 1000),
        })
        if ingreso['item_code'] != item or ingreso['warehouse'] != origen:
            errors.append('ItemCode o bodega virtual no coinciden con el ingreso SAP P1.')
        if cantidad > ingreso['quantity']:
            errors.append('El peso real supera la cantidad ingresada a bodega virtual.')
        articulo = consultar_articulo_y_bodegas_prosesa(schema, item, origen, destino)
        source['unidad_sap'] = articulo.get('unit')
        stock = consultar_stock_lote_prosesa(schema, item, origen, lote)
        source.update({
            'stock_lote_mt': float(stock['stock']),
            'stock_lote_disponible_mt': float(stock['available']),
            'remanente_lote_mt': float(stock['available'] - cantidad),
        })
        if stock['available'] < cantidad:
            errors.append('Stock disponible del lote en bodega virtual insuficiente.')
        source['fecha_sap'] = obtener_fecha_sistema_sap(schema)
        existente = buscar_transferencia_sap_new_jersey_p3(schema, citacion.id)
        if existente:
            result['status'] = {
                'creada': True, 'bloqueada': True, 'estado': 'CREADO_EN_SAP',
                'docentry': existente.get('docentry'), 'docnum': existente.get('docnum'),
            }
            errors.append('La transferencia SAP de esta P3 ya existe.')
    except Exception as exc:
        errors.append(f'No fue posible validar datos SAP para P3: {exc}')
    if errors:
        return result
    comentario = (
        f'NJ P3 #{citacion.id}; P2 #{p2.id}; P1 #{p1.id}; '
        f'Guia {source["guia"]}; Contenedor {source["contenedor"]}; '
        f'Solicitud P2 {source["solicitud_p2_docentry"]}'
    )[:254]
    result['payload'] = {
        'DocDate': source['fecha_sap'], 'FromWarehouse': origen, 'ToWarehouse': destino,
        'Reference1': REFERENCIA_TERRAVIEW, 'Reference2': str(citacion.id),
        'Comments': comentario,
        'StockTransferLines': [{
            'ItemCode': item, 'Quantity': float(cantidad),
            'FromWarehouseCode': origen, 'WarehouseCode': destino,
            'BatchNumbers': [{'BatchNumber': lote, 'Quantity': float(cantidad)}],
        }],
    }
    result['ready_for_post'] = True
    result['validations'].append(
        'Peso real validado; lote disponible; Quantity coincide con BatchNumbers.Quantity.'
    )
    return result


def _actualizar_intento(log, audit, estado, response=None, error='', status_code=None):
    audit.update({
        'estado': estado, 'response': response or {}, 'error': error,
        'status_code': status_code, 'fecha_resultado': timezone.now().isoformat(),
    })
    log.OPL_COBSERVACION = json.dumps(audit, ensure_ascii=False, default=str)
    log.OPL_CESTADO = (
        OPERACION_PLANTA_LOG.ESTADO_COMPLETADO if estado == 'CREADO'
        else OPERACION_PLANTA_LOG.ESTADO_PENDIENTE
    )
    log.save(update_fields=['OPL_COBSERVACION', 'OPL_CESTADO'])


def send_stock_transfer_new_jersey_p3_to_sap(citacion, usuario):
    if not es_new_jersey_p3_sap(citacion):
        return {'success': False, 'message': 'Flujo SAP New Jersey P3 no aplicable.'}
    try:
        config = load_config(nj_p3.EMPRESA_NJ, for_write=True)
    except Exception as exc:
        return {'success': False, 'message': f'Configuracion SAP invalida: {exc}'}
    preview = build_stock_transfer_new_jersey_p3(citacion)
    if not preview['ready_for_post']:
        return {'success': False, 'message': 'Transferencia SAP New Jersey P3 no valida.', 'preview': preview}
    source, payload = preview['source_data'], preview['payload']
    audit = {
        'accion': LOG_TRANSFERENCIA, 'estado': 'ENVIANDO',
        'endpoint': ENDPOINT_TRANSFERENCIA, 'company_db': config.company_db,
        'operacion_new_jersey_id': source['operacion_new_jersey'],
        'citacion_p1': source['citacion_p1'], 'citacion_p2': source['citacion_p2'],
        'citacion_p3': citacion.id, 'ingreso_p1_docentry': source['ingreso_p1_docentry'],
        'solicitud_p2_docentry': source['solicitud_p2_docentry'],
        'item_code': source['item_code'], 'batch_number': source['batch_number'],
        'peso_real_kg': source['peso_real_kg'], 'quantity_mt': source['quantity_mt'],
        'origen': source['origen'], 'destino': source['destino'],
        'fecha_sap': source['fecha_sap'], 'usuario': usuario.username,
        'usuario_id': usuario.id, 'payload': payload,
        'fecha_intento': timezone.now().isoformat(),
    }
    with transaction.atomic():
        bloqueada = CITACION.objects.select_for_update().select_related('SC_NID').get(
            pk=citacion.pk, EP_NID_id=nj_p3.EMPRESA_NJ, CI_BHABILITADO=True,
        )
        estado = estado_transferencia_new_jersey_p3(bloqueada)
        if estado['bloqueada']:
            return {'success': False, 'message': 'Transferencia creada o pendiente de conciliacion.', 'status': estado}
        if destino_vigente_p3(bloqueada) != payload['ToWarehouse']:
            return {'success': False, 'message': 'El TK final cambio. Previsualice nuevamente.'}
        try:
            if _schema_sap() != config.company_db:
                raise ValueError('CompanyDB de lectura y escritura no coinciden.')
            existente = buscar_transferencia_sap_new_jersey_p3(config.company_db, citacion.id)
            if existente:
                return {'success': False, 'message': 'La transferencia SAP de esta P3 ya existe.', 'status': existente}
            obtener_peso_real_new_jersey_p3_para_sap(bloqueada)
            stock = consultar_stock_lote_prosesa(
                config.company_db, source['item_code'], source['origen'], source['batch_number'],
            )
        except Exception as exc:
            return {'success': False, 'message': f'No fue posible revalidar antes de enviar: {exc}'}
        if stock['available'] < _decimal(source['quantity_mt']):
            return {'success': False, 'message': 'Stock disponible del lote insuficiente antes de enviar.'}
        log = OPERACION_PLANTA_LOG.objects.create(
            US_NID=usuario, EP_NID=citacion.EP_NID, PL_NID=citacion.PL_NID,
            CI_NID=citacion, OPL_CPASO=LOG_TRANSFERENCIA,
            OPL_CPERFIL_RESPONSABLE='ASISTENTE RECEPCION',
            OPL_CESTADO=OPERACION_PLANTA_LOG.ESTADO_PENDIENTE,
            OPL_COBSERVACION=json.dumps(audit, ensure_ascii=False, default=str),
        )
    client, post_iniciado = SapServiceLayerClient(config), False
    try:
        client.login()
        post_iniciado = True
        resultado = client.post_stock_transfer(payload)
        response = resultado.get('data') or {}
        if not response.get('DocEntry'):
            raise ValueError('SAP respondio sin DocEntry; resultado incierto.')
    except Exception as exc:
        status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
        rechazado = (
            not post_iniciado
            or isinstance(exc, HTTPError) and status_code and 400 <= status_code < 500
        )
        estado_error = 'RECHAZADO' if rechazado else 'INCIERTO'
        _actualizar_intento(log, audit, estado_error, error=str(exc), status_code=status_code)
        return {
            'success': False,
            'message': (
                'SAP rechazo la transferencia.' if rechazado
                else 'Resultado SAP incierto. No reintentar antes de conciliar Reference2.'
            ),
            'status': {'creada': False, 'bloqueada': not rechazado, 'estado': estado_error},
        }
    finally:
        client.logout()
    with transaction.atomic():
        _actualizar_intento(log, audit, 'CREADO', response=response,
                           status_code=resultado.get('status_code'))
        campo = _campo(citacion, usuario, CAMPO_TRANSFERENCIA, 'StockTransfer final New Jersey P3')
        DATO_OPERACION.objects.update_or_create(
            CI_NID=citacion, CAMP_NID=campo,
            defaults={
                'US_NID': usuario, 'EP_NID': citacion.EP_NID, 'SC_NID': citacion.SC_NID,
                'ET_NID': _etapa(citacion),
                'DO_CVALOR': json.dumps(audit, ensure_ascii=False, default=str),
                'DO_FFECHAREGISTRO': timezone.now(),
            },
        )
        operacion = OPERACION_NEW_JERSEY.objects.select_for_update().get(
            pk=source['operacion_new_jersey'], EP_NID_id=nj_p3.EMPRESA_NJ,
        )
        if operacion.ONJ_CESTADO != OPERACION_NEW_JERSEY.Estado.COMPLETADA:
            operacion.ONJ_CESTADO = OPERACION_NEW_JERSEY.Estado.LISTA_TRANSFERENCIA_SAP
            operacion.save(update_fields=['ONJ_CESTADO', 'ONJ_FFECHAMODIFICACION'])
    return {
        'success': True, 'message': 'Transferencia SAP final New Jersey creada.',
        'transferencia_sap_creada': True, 'docentry': response['DocEntry'],
        'docnum': response.get('DocNum'), 'origen': source['origen'],
        'destino': source['destino'], 'item_code': source['item_code'],
        'batch_number': source['batch_number'], 'peso_real_kg': source['peso_real_kg'],
        'quantity_mt': source['quantity_mt'],
    }


def contexto_transferencia_new_jersey_p3(citacion):
    contexto = {
        'aplicable': es_new_jersey_p3_sap(citacion),
        'qa_habilitado': bool(getattr(settings, 'QA_PESAJE', False)),
        'preview_habilitado': bool(getattr(settings, 'SAP_RECEPCION_PREVIEW_ENABLED', False)),
        'formula': FORMULA_PESO_REAL, 'disponible': False, 'resultado_valido': False,
        'pesajes': [], 'pesajes_por_clave': {}, 'opciones_tk': [],
    }
    if not contexto['aplicable']:
        return contexto
    contexto['opciones_tk'] = nj_p2.estanques_validos_p2()
    contexto['tk_destino'] = destino_vigente_p3(citacion)
    try:
        pesajes = resolver_pesajes_new_jersey_p3(citacion)
        for clave, cfg in CONFIGURACION_PESAJES.items():
            ticket = pesajes[clave]
            fila = {
                'clave': clave, 'grupo': cfg['grupo'], 'nombre': cfg['nombre'],
                'codigo_qa': cfg['codigo_qa'], 'folio': ticket['folio'],
                'ticket_dato_id': ticket['dato_id'], 'citacion_id': ticket['citacion_id'],
                'patente': ticket['patente'], 'fecha_ticket': ticket['fecha_ticket'],
                'peso_original': ticket['peso_original'], 'peso_efectivo': ticket['peso_efectivo'],
                'origen': ticket['origen_peso'],
                'fuente': 'QA' if ticket['origen_peso'] == 'QA_OVERRIDE' else 'TICKET',
                'peso_qa': ticket['peso_efectivo'] if ticket['origen_peso'] == 'QA_OVERRIDE' else '',
                'override_dato_id': ticket['override_dato_id'],
            }
            contexto['pesajes'].append(fila)
            contexto['pesajes_por_clave'][clave] = fila
        valores = {
            clave: int(pesajes[clave]['peso_efectivo'])
            for clave in CONFIGURACION_PESAJES
        }
        cargado = valores['p1_ent'] - valores['p1_sal']
        vacio = valores['p3_sal'] - valores['p3_ent']
        real = cargado - vacio
        contexto.update({
            'disponible': True, 'calculo_valido': False,
            'peso_conjunto_cargado_kg': cargado,
            'peso_contenedor_vacio_kg': vacio,
            'peso_real_kg': real,
            'peso_real_mt': float(Decimal(real) / Decimal('1000')),
            'citacion_p1_id': pesajes['p1'].id,
            'citacion_p2_id': pesajes['p2'].id,
            'citacion_p3_id': pesajes['p3'].id,
        })
        try:
            calcular_peso_real_desde_pesajes(pesajes)
            contexto['calculo_valido'] = True
        except ValueError as exc:
            contexto['error'] = str(exc)
        try:
            peso_persistido = obtener_peso_real_new_jersey_p3_para_sap(citacion)
            contexto['peso_real_persistido'] = peso_persistido
            contexto['peso_real_persistido_mt'] = float(
                Decimal(peso_persistido) / Decimal('1000')
            )
            contexto['resultado_valido'] = True
        except ValueError as exc:
            contexto['resultado_persistido_error'] = str(exc)
    except ValueError as exc:
        contexto['error'] = str(exc)
    contexto['transferencia_sap'] = build_stock_transfer_new_jersey_p3(citacion)
    contexto['transferencia_sap_creada'] = bool(
        contexto['transferencia_sap']['status'].get('creada')
    )
    contexto['tk_bloqueado'] = bool(contexto['transferencia_sap']['status'].get('bloqueada'))
    return contexto
