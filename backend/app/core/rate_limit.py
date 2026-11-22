"""Rate limiter en memoria (ventana deslizante por clave).

* Purga periódica de entradas expiradas y tope de claves rastreadas (anti-OOM):
  si se supera ``max_claves`` tras purgar, se descartan las claves más antiguas.
* ``reset()`` limpia el estado (usado por los tests entre casos).
* Es por proceso: con varios workers de uvicorn cada uno lleva su propia cuenta.

La IP se toma de la conexión TCP (``request.client.host``); no se confía en
``X-Forwarded-For`` porque el cliente puede falsificarlo.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

VENTANA_S = 60.0


class RateLimiter:
    def __init__(self, max_claves: int = 10_000, intervalo_purga_s: float = VENTANA_S) -> None:
        self.max_claves = max_claves
        self.intervalo_purga_s = intervalo_purga_s
        self._hits: dict[str, tuple[float, deque[float]]] = {}
        self._ultima_purga = time.monotonic()

    def __len__(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        self._hits.clear()
        self._ultima_purga = time.monotonic()

    def _purgar(self, ahora: float) -> None:
        expiradas = [
            clave
            for clave, (ventana, marcas) in self._hits.items()
            if not marcas or ahora - marcas[-1] >= ventana
        ]
        for clave in expiradas:
            del self._hits[clave]
        # Tope duro: descarta las claves más antiguas (orden de inserción del dict).
        exceso = len(self._hits) - self.max_claves
        if exceso > 0:
            for clave in list(self._hits)[:exceso]:
                del self._hits[clave]
        self._ultima_purga = ahora

    def hit(self, clave: str, limite: int, ventana: float = VENTANA_S) -> tuple[bool, int]:
        """Registra un intento. Devuelve ``(permitido, segundos_para_reintentar)``."""
        ahora = time.monotonic()
        if ahora - self._ultima_purga >= self.intervalo_purga_s or len(self._hits) >= self.max_claves:
            self._purgar(ahora)

        _, marcas = self._hits.setdefault(clave, (ventana, deque()))
        while marcas and ahora - marcas[0] >= ventana:
            marcas.popleft()
        if len(marcas) >= limite:
            return False, max(1, math.ceil(ventana - (ahora - marcas[0])))
        marcas.append(ahora)
        return True, 0


rate_limiter = RateLimiter()


def ip_cliente(request_o_ws) -> str:
    cliente = getattr(request_o_ws, "client", None)
    return cliente.host if cliente and cliente.host else "desconocida"


def limitar(ambito: str, campo_limite: str) -> Callable:
    """Dependencia FastAPI: ``ambito`` agrupa la cuenta, ``campo_limite`` es un campo de Settings."""

    async def _dependencia(request: Request) -> None:
        limite = int(getattr(get_settings(), campo_limite))
        permitido, reintento = rate_limiter.hit(f"{ambito}:{ip_cliente(request)}", limite)
        if not permitido:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes, intenta más tarde",
                headers={"Retry-After": str(reintento)},
            )

    return _dependencia
