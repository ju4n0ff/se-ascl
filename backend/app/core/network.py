"""IP real del cliente, resistente a ``X-Forwarded-For`` falsificado.

Cada proxy **agrega** al final de ``X-Forwarded-For`` la IP de quien se le conectó. Lo
que mande el cliente queda a la izquierda, así que solo se confía en las últimas
``TRUST_PROXY_HOPS`` entradas y se toma la primera de ese tramo.

Requiere uvicorn con ``--no-proxy-headers``: por defecto uvicorn reescribe
``client.host`` con ``X-Forwarded-For`` (y Render define ``FORWARDED_ALLOW_IPS=*``, con lo
que tomaría la entrada de más a la izquierda, controlada por el cliente).
"""
from __future__ import annotations

import ipaddress
import logging

from starlette.requests import HTTPConnection

from app.core.config import get_settings

logger = logging.getLogger(__name__)

IP_DESCONOCIDA = "desconocida"
_aviso_emitido = False

IP = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip_valida(texto: str) -> IP | None:
    try:
        ip = ipaddress.ip_address(texto.strip())
    except ValueError:
        return None
    # ::ffff:1.2.3.4 y 1.2.3.4 son el mismo cliente: una sola clave de rate limit.
    return getattr(ip, "ipv4_mapped", None) or ip


def _avisar_si_es_interna(ip: IP, entradas: int, saltos: int) -> None:
    """Una IP privada es casi siempre otro proxy: faltan saltos (se avisa una vez, sin IPs)."""
    global _aviso_emitido
    if _aviso_emitido or not ip.is_private:
        return
    _aviso_emitido = True
    logger.warning(
        "TRUST_PROXY_HOPS=%d resuelve a una IP interna (X-Forwarded-For trae %d entradas): "
        "los clientes comparten cupo de rate limit. Revisa TRUST_PROXY_HOPS.",
        saltos,
        entradas,
    )


def obtener_ip_cliente(conexion: HTTPConnection) -> str:
    """IP para rate limiting y tope de conexiones (sirve para HTTP y WebSocket)."""
    cliente = conexion.client
    directa = cliente.host if cliente and cliente.host else IP_DESCONOCIDA
    saltos = get_settings().trust_proxy_hops
    if saltos == 0:
        return directa

    # Varias cabeceras equivalen a una sola concatenada en orden (RFC 9110, 5.3).
    entradas = ",".join(conexion.headers.getlist("x-forwarded-for")).split(",")
    if len(entradas) < saltos:
        return directa  # nunca se cae a una entrada que pudo escribir el cliente
    # Solo se validan las entradas escritas por los proxies: basura a la izquierda no influye.
    confiables = [_ip_valida(e) for e in entradas[-saltos:]]
    ip = confiables[0]
    if ip is None or None in confiables:
        return directa
    _avisar_si_es_interna(ip, len(entradas), saltos)
    return str(ip)
