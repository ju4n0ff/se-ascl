"""Validación de orígenes para CORS y para el ``Origin`` del WebSocket (anti-CSWSH)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

HOSTS_LOOPBACK = {"localhost", "127.0.0.1", "::1"}

MAX_LARGO_REGEX = 200
MAX_TRAMOS_VARIABLES = 2
MIN_LITERAL_COMPARTIDO = 3
# Dominios donde cualquier tercero puede crear un subdominio.
DOMINIOS_COMPARTIDOS = {
    "vercel.app", "netlify.app", "onrender.com", "github.io", "pages.dev",
    "herokuapp.com", "web.app", "firebaseapp.com", "supabase.co",
}
SUFIJOS_PUBLICOS = {"co", "com", "org", "net", "gob", "gov", "edu", "ac"}

# Gramática cerrada: literales y clases [a-z0-9-] con cuantificador. Sin '.', '|', grupos,
# '*', '?' ni clases negadas: tampoco deja lugar a backtracking exponencial.
_VARIABLE = r"\[(?:a-z|0-9|a-z0-9|a-z0-9-)\](?:\+|\{\d{1,2}(?:,\d{1,2})?\})"
_TRAMO = re.compile(rf"(?P<lit>(?:[a-z0-9]|\\?-)+)|(?P<var>{_VARIABLE})")
_PATRON = re.compile(r"\^?https://(?P<host>[^/$^]+)\$?")
_ETIQUETA_LITERAL = re.compile(r"[a-z0-9-]+")


def validar_origen(origen: str, debug: bool) -> str:
    """Devuelve el origen normalizado (``esquema://host[:puerto]``) o lanza ``ValueError``."""
    if "*" in origen:
        raise ValueError("ALLOWED_ORIGINS no admite comodines '*'")
    error = ValueError(f"Origen inválido en ALLOWED_ORIGINS: {origen!r}")
    limpio = origen.strip().rstrip("/").lower()
    try:
        partes = urlsplit(limpio)
        host, _ = partes.hostname, partes.port  # .port lanza ValueError si no es numérico
    except ValueError:
        raise error from None
    if (
        partes.scheme not in {"http", "https"}
        or not host
        or "@" in partes.netloc
        or re.search(r"[\s\\]", limpio)
        or f"{partes.scheme}://{partes.netloc}" != limpio  # sin ruta, query ni fragmento
    ):
        raise error
    if partes.scheme == "http" and not debug and host not in HOSTS_LOOPBACK:
        raise ValueError(
            f"ALLOWED_ORIGINS exige https:// con DEBUG=false (salvo loopback): {origen!r}"
        )
    return limpio


def _etiquetas(host: str) -> list[list[tuple[str, str]]]:
    r"""``senacl-[a-z0-9-]+\.vercel\.app`` -> etiquetas DNS, cada una lista de (tipo, texto)."""
    etiquetas = []
    for etiqueta in host.split(r"\."):
        tramos: list[tuple[str, str]] = []
        pos = 0
        while pos < len(etiqueta):
            m = _TRAMO.match(etiqueta, pos)
            if m is None:
                raise ValueError("ALLOWED_ORIGIN_REGEX usa construcciones no permitidas")
            tramos.append((m.lastgroup or "", m.group().replace("\\", "")))
            pos = m.end()
        if not tramos:
            raise ValueError("ALLOWED_ORIGIN_REGEX tiene una etiqueta de dominio vacía")
        etiquetas.append(tramos)
    return etiquetas


def validar_regex_origen(patron: str) -> str:
    r"""Acepta solo patrones cerrados, p. ej. ``^https://senacl-[a-z0-9-]+-equipo\.vercel\.app$``.

    El dominio registrable debe ser literal. En dominios compartidos (``vercel.app``...) la
    etiqueta variable debe empezar y terminar con literales propios del equipo.
    """
    patron = patron.strip()
    if not patron:
        return ""
    if len(patron) > MAX_LARGO_REGEX:
        raise ValueError("ALLOWED_ORIGIN_REGEX es demasiado largo")
    m = _PATRON.fullmatch(patron)
    if m is None:
        raise ValueError("ALLOWED_ORIGIN_REGEX debe ser https:// literal seguido de un dominio")

    etiquetas = _etiquetas(m.group("host"))
    textos = ["".join(texto for _, texto in tramos) for tramos in etiquetas]
    con_variable = [i for i, tramos in enumerate(etiquetas) if any(t == "var" for t, _ in tramos)]
    if sum(t == "var" for tramos in etiquetas for t, _ in tramos) > MAX_TRAMOS_VARIABLES:
        raise ValueError("ALLOWED_ORIGIN_REGEX tiene demasiados tramos variables")
    if (
        len(etiquetas) < 2
        or any(i >= len(etiquetas) - 2 for i in con_variable)
        or not all(_ETIQUETA_LITERAL.fullmatch(t) for t in textos[-2:])
    ):
        raise ValueError(r"ALLOWED_ORIGIN_REGEX debe fijar el dominio completo (p. ej. \.senacl\.cl)")
    if textos[-2] in SUFIJOS_PUBLICOS and len(etiquetas) - 3 in con_variable:
        raise ValueError("ALLOWED_ORIGIN_REGEX no puede abarcar un sufijo público")
    if ".".join(textos[-2:]) in DOMINIOS_COMPARTIDOS and con_variable:
        # La etiqueta pegada al dominio compartido es la que identifica al dueño.
        tramos = etiquetas[-3]
        extremos = (tramos[0], tramos[-1])
        if any(t != "lit" or len(v.strip("-")) < MIN_LITERAL_COMPARTIDO for t, v in extremos):
            raise ValueError(
                "ALLOWED_ORIGIN_REGEX en un dominio compartido debe fijar el prefijo del "
                "proyecto y el sufijo del equipo"
            )
    try:
        re.compile(patron)
    except re.error:
        raise ValueError("ALLOWED_ORIGIN_REGEX no es una expresión regular válida") from None
    return patron
