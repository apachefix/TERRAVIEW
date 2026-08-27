"""Consulta y cálculo del acumulado ICT desde fuentes oficiales del INE."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import logging
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from lxml import html
import requests


logger = logging.getLogger(__name__)

ICT_INE_URL = (
    "https://www.ine.gob.cl/estadisticas-por-tema/precios-e-inflacion/"
    "indice-de-costos-del-transporte"
)
ICT_CALCULADORA_URL = "https://calculadoraict.ine.cl/"
ICT_MESES_URL = urljoin(ICT_CALCULADORA_URL, "Home/GetMesesPorAnio")
ICT_CALCULO_URL = urljoin(ICT_CALCULADORA_URL, "Home/CalularIpC")
HEADERS = {"User-Agent": "TERRAVIEW/1.0 consulta-ict"}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
NOMBRES_MESES = {numero: nombre.capitalize() for nombre, numero in MESES.items()}
PRECISION_ACUMULADO = Decimal("0.0001")


class ICTConsultaError(RuntimeError):
    """La fuente oficial no respondió o no entregó datos inequívocos."""


@dataclass(frozen=True)
class ICTResultado:
    periodo: str
    variacion: Decimal
    fecha_publicacion: date
    fuente: str
    url: str

    def como_dict(self):
        return {
            "periodo": self.periodo,
            "variacion": str(self.variacion),
            "fecha_publicacion": self.fecha_publicacion.isoformat(),
            "fuente": self.fuente,
            "url": self.url,
        }


@dataclass(frozen=True)
class ICTComponente:
    periodo_fecha: date
    periodo: str
    variacion: Decimal

    def como_dict(self):
        return {
            "periodo_fecha": self.periodo_fecha.isoformat(),
            "periodo": self.periodo,
            "variacion": str(self.variacion),
        }


@dataclass(frozen=True)
class ICTAcumuladoResultado:
    componentes: tuple
    acumulado: Decimal
    fecha_publicacion: date
    fuente: str
    url: str
    url_publicacion: str

    @property
    def periodo_inicio(self):
        return self.componentes[0].periodo_fecha

    @property
    def periodo_fin(self):
        return self.componentes[-1].periodo_fecha

    @property
    def periodo(self):
        return f"{self.componentes[0].periodo} → {self.componentes[-1].periodo}"

    @property
    def variacion(self):
        """Alias compatible con consumidores anteriores."""
        return self.acumulado

    def como_dict(self):
        return {
            "periodo": self.periodo,
            "periodo_inicio": self.periodo_inicio.isoformat(),
            "periodo_fin": self.periodo_fin.isoformat(),
            "componentes": [item.como_dict() for item in self.componentes],
            "acumulado": str(self.acumulado),
            "variacion": str(self.acumulado),
            "fecha_publicacion": self.fecha_publicacion.isoformat(),
            "fuente": self.fuente,
            "url": self.url,
            "url_publicacion": self.url_publicacion,
        }


def _texto_normalizado(valor):
    texto = " ".join(str(valor or "").split())
    return unicodedata.normalize("NFC", texto)


def _fecha_desde_url(url):
    coincidencia = re.search(r"/noticia/(20\d{2})/(\d{2})/(\d{2})/", url)
    if not coincidencia:
        raise ICTConsultaError("La publicación ICT no contiene una fecha verificable.")
    try:
        return date(*(int(valor) for valor in coincidencia.groups()))
    except ValueError as exc:
        raise ICTConsultaError("La fecha de publicación ICT es inválida.") from exc


def _decimal_porcentaje(valor):
    texto = str(valor or "").replace("%", "").replace(" ", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise ICTConsultaError("La variación mensual ICT es inválida.") from exc
    if not numero.is_finite() or not Decimal("-100") < numero < Decimal("100"):
        raise ICTConsultaError("La variación mensual ICT está fuera de rango.")
    return numero


def _candidatos_publicaciones(contenido, url_fuente=ICT_INE_URL):
    try:
        documento = html.fromstring(contenido)
    except (TypeError, ValueError) as exc:
        raise ICTConsultaError("La respuesta del INE no contiene HTML válido.") from exc

    candidatos = []
    patron = re.compile(
        r"indice de costos del transporte registro una variacion mensual de\s*"
        r"([+-]?\d+(?:[.,]\d+)?)\s*%?\s+en\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
        r"\s+de\s+(20\d{2})",
        re.IGNORECASE,
    )
    for enlace in documento.xpath("//a[@href]"):
        titulo = _texto_normalizado(enlace.text_content())
        titulo_sin_tildes = "".join(
            caracter
            for caracter in unicodedata.normalize("NFKD", titulo)
            if not unicodedata.combining(caracter)
        )
        coincidencia = patron.search(titulo_sin_tildes)
        if not coincidencia:
            continue
        url_publicacion = urljoin(url_fuente, enlace.get("href"))
        host = (urlparse(url_publicacion).hostname or "").lower()
        if host not in {"ine.gob.cl", "www.ine.gob.cl"}:
            continue
        valor_texto, mes_texto, anio_texto = coincidencia.groups()
        variacion = _decimal_porcentaje(valor_texto)
        fecha_publicacion = _fecha_desde_url(url_publicacion)
        mes = MESES[mes_texto.lower()]
        anio = int(anio_texto)
        if fecha_publicacion < date(anio, mes, 1):
            raise ICTConsultaError("El período ICT no concuerda con su publicación.")
        candidatos.append(ICTResultado(
            periodo=f"{NOMBRES_MESES[mes]} {anio}",
            variacion=variacion,
            fecha_publicacion=fecha_publicacion,
            fuente="INE",
            url=url_publicacion,
        ))
    return candidatos


def extraer_ultimo_ict(contenido, url_fuente=ICT_INE_URL):
    candidatos = _candidatos_publicaciones(contenido, url_fuente)
    if not candidatos:
        raise ICTConsultaError("La estructura publicada por INE no contiene un ICT válido.")
    return max(candidatos, key=lambda resultado: resultado.fecha_publicacion)


def calcular_acumulado_compuesto(variaciones):
    factor = Decimal("1")
    valores = tuple(Decimal(str(valor)) for valor in variaciones)
    if not valores:
        raise ICTConsultaError("No existen variaciones ICT para calcular el acumulado.")
    for valor in valores:
        if not valor.is_finite() or not Decimal("-100") < valor < Decimal("100"):
            raise ICTConsultaError("La variación mensual ICT está fuera de rango.")
        factor *= Decimal("1") + valor / Decimal("100")
    return ((factor - Decimal("1")) * Decimal("100")).quantize(
        PRECISION_ACUMULADO
    )


def _periodo_anterior(periodo):
    return (
        date(periodo.year - 1, 12, 1)
        if periodo.month == 1
        else date(periodo.year, periodo.month - 1, 1)
    )


def _periodos_son_consecutivos(periodos):
    return all(
        _periodo_anterior(actual) == anterior
        for anterior, actual in zip(periodos, periodos[1:])
    )


def _json_respuesta(respuesta, mensaje):
    respuesta.raise_for_status()
    try:
        return respuesta.json()
    except (TypeError, ValueError) as exc:
        raise ICTConsultaError(mensaje) from exc


def _obtener_periodos_disponibles(cliente, timeout):
    portada = cliente.get(
        ICT_CALCULADORA_URL, timeout=timeout, headers=HEADERS
    )
    portada.raise_for_status()
    try:
        documento = html.fromstring(portada.content)
        anios = {
            int(valor)
            for valor in documento.xpath("//select[@id='ano_termino']/option/@value")
            if str(valor).isdigit()
        }
    except (TypeError, ValueError) as exc:
        raise ICTConsultaError(
            "La calculadora INE no informó los años disponibles."
        ) from exc
    if not anios:
        raise ICTConsultaError("La calculadora INE no informó períodos disponibles.")

    periodos = set()
    for anio in sorted(anios, reverse=True):
        datos = _json_respuesta(
            cliente.get(
                ICT_MESES_URL,
                params={"Anio": anio},
                timeout=timeout,
                headers=HEADERS,
            ),
            "La calculadora INE no entregó meses válidos.",
        )
        if datos.get("tipo") != "OK" or not isinstance(datos.get("data"), list):
            raise ICTConsultaError("La calculadora INE no entregó meses válidos.")
        for item in datos["data"]:
            try:
                mes = int(item["valor"])
                periodos.add(date(anio, mes, 1))
            except (KeyError, TypeError, ValueError):
                raise ICTConsultaError("La calculadora INE contiene un período inválido.")
        if len(periodos) >= 6:
            break

    ultimos = tuple(sorted(periodos)[-6:])
    if len(ultimos) != 6 or not _periodos_son_consecutivos(ultimos):
        raise ICTConsultaError(
            "No fue posible obtener los 6 períodos ICT necesarios para calcular el acumulado."
        )
    return ultimos


def _obtener_variacion_mensual(cliente, periodo, timeout):
    anterior = _periodo_anterior(periodo)
    datos = _json_respuesta(
        cliente.post(
            ICT_CALCULO_URL,
            json={
                "mesInicio": anterior.month,
                "AnioInicio": anterior.year,
                "mesTermino": periodo.month,
                "AnioTermino": periodo.year,
                "valor_a_ajustar": "100000",
            },
            timeout=timeout,
            headers=HEADERS,
        ),
        "La calculadora INE no entregó una variación mensual válida.",
    )
    if str(datos.get("cantidad_meses")) != "1":
        raise ICTConsultaError(
            "La calculadora INE no confirmó un período mensual consecutivo."
        )
    return _decimal_porcentaje(datos.get("variacion_ipc"))


def obtener_acumulativo_ict_6_meses(timeout=12, cliente=requests):
    """Obtiene seis períodos oficiales y compone sus variaciones mensuales."""
    try:
        periodos = _obtener_periodos_disponibles(cliente, timeout)
        componentes = tuple(
            ICTComponente(
                periodo_fecha=periodo,
                periodo=f"{NOMBRES_MESES[periodo.month]} {periodo.year}",
                variacion=_obtener_variacion_mensual(cliente, periodo, timeout),
            )
            for periodo in periodos
        )
        publicacion_respuesta = cliente.get(
            ICT_INE_URL, timeout=timeout, headers=HEADERS
        )
        publicacion_respuesta.raise_for_status()
        ultima_publicacion = extraer_ultimo_ict(
            publicacion_respuesta.content,
            publicacion_respuesta.url or ICT_INE_URL,
        )
    except requests.RequestException as exc:
        logger.exception("No fue posible consultar el acumulado ICT desde INE")
        raise ICTConsultaError(
            "No fue posible obtener los 6 períodos ICT necesarios para calcular el acumulado."
        ) from exc

    ultimo = componentes[-1]
    if (
        ultima_publicacion.periodo != ultimo.periodo
        or ultima_publicacion.variacion != ultimo.variacion
    ):
        raise ICTConsultaError(
            "El último período de la calculadora no coincide con la publicación oficial del INE."
        )
    return ICTAcumuladoResultado(
        componentes=componentes,
        acumulado=calcular_acumulado_compuesto(
            componente.variacion for componente in componentes
        ),
        fecha_publicacion=ultima_publicacion.fecha_publicacion,
        fuente="INE",
        url=ICT_CALCULADORA_URL,
        url_publicacion=ultima_publicacion.url,
    )


def obtener_ultimo_ict(timeout=12):
    """Compatibilidad para consumidores legacy del último comunicado ICT."""
    try:
        respuesta = requests.get(ICT_INE_URL, timeout=timeout, headers=HEADERS)
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("No fue posible consultar el ICT desde INE")
        raise ICTConsultaError("No fue posible consultar el último ICT desde INE.") from exc
    return extraer_ultimo_ict(respuesta.content, respuesta.url or ICT_INE_URL)