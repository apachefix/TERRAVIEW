import re


class RutChilenoInvalido(ValueError):
    pass


def normalizar_rut_chileno(valor):
    """Normaliza un RUT chileno a 12345678-K y valida su DV módulo 11."""
    texto = str(valor or '').strip().upper()
    if not texto:
        return ''

    limpio = re.sub(r'[.\s-]', '', texto)
    if not re.fullmatch(r'\d{2,8}[0-9K]', limpio):
        raise RutChilenoInvalido('RUT inválido. Revise el número ingresado.')

    cuerpo_texto, dv_informado = limpio[:-1], limpio[-1]
    cuerpo = int(cuerpo_texto)
    suma = 0
    factor = 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resultado = 11 - (suma % 11)
    dv_esperado = '0' if resultado == 11 else ('K' if resultado == 10 else str(resultado))
    if dv_informado != dv_esperado:
        raise RutChilenoInvalido('RUT inválido. Revise el número ingresado.')
    return f'{cuerpo}-{dv_esperado}'
