from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN


PRECISION_TONELADAS = Decimal('0.00001')
MAX_TONELADAS = Decimal('9999999999999.99999')
CAPACIDADES_DESPACHO_SBH = {
    'Cisterna': Decimal('27.5'),
    'Contenedor': Decimal('21.6'),
    'Isotank': Decimal('23.4'),
}


def decimal_toneladas(valor, nombre='cantidad'):
    try:
        numero = Decimal(str(valor).strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f'La {nombre} no es valida.') from exc
    if not numero.is_finite() or numero <= 0:
        raise ValueError(f'La {nombre} debe ser mayor que cero.')
    if numero > MAX_TONELADAS:
        raise ValueError(f'La {nombre} excede el maximo permitido.')
    return numero.quantize(PRECISION_TONELADAS)


def formato_decimal_natural(valor):
    numero = Decimal(str(valor))
    texto = format(numero, 'f')
    if '.' in texto:
        texto = texto.rstrip('0').rstrip('.')
    return texto or '0'


def capacidad_despacho_sbh(formato, ibc_por_camion=None):
    formato = str(formato or '').strip()
    if formato == 'IBC':
        # Regla operacional SBH: una rampla transporta siempre 20 IBC de 0.9 t.
        return Decimal('18.00000')
    try:
        return CAPACIDADES_DESPACHO_SBH[formato]
    except KeyError as exc:
        raise ValueError('El formato de despacho SBH no es valido.') from exc


def camiones_requeridos(total, capacidad):
    total = decimal_toneladas(total, 'cantidad total planificada')
    capacidad = decimal_toneladas(capacidad, 'capacidad de planificacion')
    return int((total / capacidad).to_integral_value(rounding=ROUND_CEILING))


def distribuir_tonelaje(total, capacidad, cantidad_borradores=None):
    """Distribuye con precision DB: inicial por capacidad; manual, equilibrada."""
    total = decimal_toneladas(total, 'cantidad total planificada')
    capacidad = decimal_toneladas(capacidad, 'capacidad de planificacion')
    if cantidad_borradores is None:
        cantidad_borradores = camiones_requeridos(total, capacidad)
        restante = total
        resultado = []
        for _ in range(cantidad_borradores):
            cantidad = min(capacidad, restante)
            resultado.append(cantidad.quantize(PRECISION_TONELADAS))
            restante -= cantidad
        return resultado

    try:
        cantidad_borradores = int(cantidad_borradores)
    except (TypeError, ValueError) as exc:
        raise ValueError('La cantidad de borradores no es valida.') from exc
    if cantidad_borradores <= 0:
        raise ValueError('Debe existir al menos un borrador de citacion.')
    if capacidad * cantidad_borradores < total:
        return [capacidad.quantize(PRECISION_TONELADAS)] * cantidad_borradores

    base = (total / cantidad_borradores).quantize(PRECISION_TONELADAS, rounding=ROUND_DOWN)
    resultado = [base] * cantidad_borradores
    restante = total - sum(resultado, Decimal('0'))
    unidades = int((restante / PRECISION_TONELADAS).to_integral_value())
    for indice in range(unidades):
        resultado[indice] += PRECISION_TONELADAS
    return resultado


def _identidad_asignacion(asignacion):
    return (
        str(asignacion.get('sap_abs_id') or asignacion.get('sap_opor_id') or '').strip(),
        str(asignacion.get('linea_acuerdo_sap') or asignacion.get('sap_linea_acuerdo') or '').strip(),
        str(asignacion.get('codigo_producto_sap') or asignacion.get('sap_codigo_producto') or '').strip(),
    )


def distribuir_asignaciones(asignaciones, cantidades_borrador):
    """Matriz proporcional exacta: conserva sumas por contrato y borrador."""
    cantidades = [decimal_toneladas(valor, 'cantidad estimada') for valor in cantidades_borrador]
    totales = [
        decimal_toneladas(item.get('cantidad_intentada_despachar'), 'cantidad intentada a despachar')
        for item in asignaciones
    ]
    total_origen = sum(totales, Decimal('0'))
    total_destino = sum(cantidades, Decimal('0'))
    if total_destino > total_origen:
        raise ValueError('Las cantidades estimadas superan el total planificado.')

    escala = int(Decimal('1') / PRECISION_TONELADAS)
    filas = [int(valor * escala) for valor in totales]
    columnas = [int(valor * escala) for valor in cantidades]
    total_unidades = sum(filas)
    matriz = [[0 for _ in columnas] for _ in filas]
    residuos_fila = filas[:]
    residuos_columna = columnas[:]
    fracciones = []
    for i, fila in enumerate(filas):
        for j, columna in enumerate(columnas):
            numerador = fila * columna
            base = numerador // total_unidades
            matriz[i][j] = base
            residuos_fila[i] -= base
            residuos_columna[j] -= base
            fracciones.append((numerador % total_unidades, i, j))

    fracciones.sort(key=lambda item: (-item[0], item[1], item[2]))
    while sum(residuos_columna) > 0:
        progreso = False
        for _, i, j in fracciones:
            if residuos_fila[i] > 0 and residuos_columna[j] > 0:
                matriz[i][j] += 1
                residuos_fila[i] -= 1
                residuos_columna[j] -= 1
                progreso = True
        if not progreso:
            raise ValueError('No fue posible distribuir las asignaciones SAP.')

    resultado = []
    for j in range(len(columnas)):
        asignaciones_borrador = []
        for i, original in enumerate(asignaciones):
            unidades = matriz[i][j]
            if unidades <= 0:
                continue
            copia = dict(original)
            copia['cantidad_intentada_despachar'] = str(
                (Decimal(unidades) / escala).quantize(PRECISION_TONELADAS)
            )
            copia['orden'] = len(asignaciones_borrador) + 1
            copia['estado'] = 'PLANIFICADA'
            asignaciones_borrador.append(copia)
        resultado.append(asignaciones_borrador)
    return resultado


def validar_lote_borradores_sbh(citaciones, resolver_acuerdo=None):
    if not isinstance(citaciones, list) or not citaciones:
        raise ValueError('Debe enviar al menos un borrador de citacion.')
    if len(citaciones) > 50:
        raise ValueError('La planificacion admite un maximo de 50 borradores de citacion.')
    primera = citaciones[0]
    originales = primera.get('asignaciones_planificacion_sap')
    if not isinstance(originales, list) or not originales:
        raise ValueError('El despacho SBH debe conservar sus contratos SAP de planificacion.')

    identidades = []
    cliente = str(primera.get('cliente_codigo') or primera.get('cliente') or '').strip()
    for indice, asignacion in enumerate(originales, start=1):
        identidad = _identidad_asignacion(asignacion)
        if not all(identidad):
            raise ValueError(f'El contrato SAP {indice} no tiene una identidad completa.')
        if identidad in identidades:
            raise ValueError('No puede repetir una linea de acuerdo SAP en la planificacion.')
        if str(asignacion.get('cliente_codigo') or '').strip() != cliente:
            raise ValueError('Todos los contratos SAP deben pertenecer al cliente del despacho.')
        decimal_toneladas(asignacion.get('cantidad_intentada_despachar'), 'cantidad intentada a despachar')
        if resolver_acuerdo:
            fila_sap = resolver_acuerdo(asignacion)
            if not fila_sap:
                raise ValueError(f'El contrato SAP {indice} no existe o ya no esta disponible en SAP.')
            oc_cliente = str(fila_sap.get('oc_cliente') or '').strip()
            if not oc_cliente:
                numero_acuerdo = str(
                    fila_sap.get('sap_acuerdo_numero')
                    or asignacion.get('contrato_sap')
                    or asignacion.get('sap_numero_acuerdo')
                    or ''
                ).strip()
                raise ValueError(
                    f'El acuerdo SAP {numero_acuerdo} no posee una OC asociada '
                    'y no puede utilizarse para planificar.'
                )
            asignacion.update({
                'nombre_producto_sap': str(fila_sap.get('nombre_insumo') or '').strip(),
                'cliente_nombre': str(fila_sap.get('cliente_nombre') or '').strip(),
                'oc_cliente': oc_cliente,
                'cantidad_planificada_sap': fila_sap.get('cantidad_planificada'),
                'cantidad_consumida_sap': fila_sap.get('cantidad_consumida'),
                'saldo_contrato_sap': fila_sap.get('saldo_contrato_sap'),
                'unidad_medida': str(fila_sap.get('unidad_medida') or '').strip(),
            })
        identidades.append(identidad)

    total = sum(
        (decimal_toneladas(item.get('cantidad_intentada_despachar'), 'cantidad intentada a despachar') for item in originales),
        Decimal('0'),
    ).quantize(PRECISION_TONELADAS)
    total_recibido = decimal_toneladas(
        primera.get('total_planificado_despacho'), 'cantidad total planificada'
    )
    if total_recibido != total:
        raise ValueError('El total planificado fue manipulado.')
    if len(citaciones) > int(total / PRECISION_TONELADAS):
        raise ValueError('La cantidad de borradores no permite asignar una cantidad positiva a cada citacion.')
    formato = str(primera.get('tipo_carga') or '').strip()
    capacidad = capacidad_despacho_sbh(formato, primera.get('ibc_por_camion'))
    modo_distribucion = str(primera.get('distribucion_borradores') or '').strip().upper()
    if modo_distribucion == 'INICIAL_CAPACIDAD':
        cantidades = distribuir_tonelaje(total, capacidad)
        if len(cantidades) != len(citaciones):
            raise ValueError('La cantidad inicial de borradores fue manipulada.')
    elif modo_distribucion == 'EQUILIBRADA':
        cantidades = distribuir_tonelaje(total, capacidad, len(citaciones))
    else:
        raise ValueError('El modo de distribucion de borradores no es valido.')
    asignaciones_esperadas = distribuir_asignaciones(originales, cantidades)

    campos_comunes = (
        'cliente', 'cliente_codigo', 'cliente_nombre', 'fecha_llegada',
        'fecha_despacho', 'fecha_llegada_destino', 'hora_llegada_planta',
        'hora_llegada_destino', 'orden_carga',
        'tipo_operacion', 'secuencia_id', 'tipo_carga', 'destino', 'salida_documento',
        'estanque_destino', 'estanque_destino_texto', 'ibc_por_camion',
        'distribucion_borradores',
    )
    for indice, item in enumerate(citaciones):
        if not item.get('despacho_sbh_etapa0'):
            raise ValueError('El lote contiene una citacion fuera del flujo Despacho SBH Etapa 0.')
        if str(item.get('tipo_operacion') or '').strip().upper() != 'DESPACHO':
            raise ValueError('El lote SBH solo permite citaciones de despacho.')
        if any(str(item.get(campo) or '') != str(primera.get(campo) or '') for campo in campos_comunes):
            raise ValueError('Los borradores no pertenecen a la misma planificacion de despacho.')
        if str(item.get('total_planificado_despacho') or '') != str(primera.get('total_planificado_despacho') or ''):
            raise ValueError('El total planificado no es consistente entre los borradores.')
        recibido = decimal_toneladas(item.get('cantidad_estimada'), 'cantidad estimada')
        if recibido != cantidades[indice]:
            raise ValueError('Las cantidades estimadas de los borradores fueron manipuladas.')
        recibidas = item.get('asignaciones_sap')
        esperadas = asignaciones_esperadas[indice]
        if not isinstance(recibidas, list) or len(recibidas) != len(esperadas):
            raise ValueError('Las asignaciones SAP del borrador fueron manipuladas.')
        for recibida, esperada in zip(recibidas, esperadas):
            if _identidad_asignacion(recibida) != _identidad_asignacion(esperada):
                raise ValueError('Una asignacion SAP no corresponde a la planificacion.')
            if decimal_toneladas(recibida.get('cantidad_intentada_despachar')) != decimal_toneladas(esperada.get('cantidad_intentada_despachar')):
                raise ValueError('La cantidad de una asignacion SAP fue manipulada.')

        item['cantidad_estimada'] = str(cantidades[indice])
        item['cantidad_intentada_despachar'] = str(cantidades[indice])
        item['capacidad_planificacion'] = str(capacidad)
        item['total_planificado_despacho'] = str(total)
        item['asignaciones_sap'] = esperadas
    return {
        'total': total,
        'capacidad': capacidad,
        'formato': formato,
        'cantidad_borradores': len(citaciones),
        'camiones_estimados': camiones_requeridos(total, capacidad),
        'capacidad_insuficiente': capacidad * len(citaciones) < total,
    }
