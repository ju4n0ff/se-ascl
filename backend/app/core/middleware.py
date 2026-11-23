"""Middlewares ASGI puros (sin BaseHTTPMiddleware, para no bufferizar respuestas).

* ``SecurityHeadersMiddleware``: genera ``request_id`` y agrega cabeceras de
  seguridad a todas las respuestas HTTP.
* ``BodySizeLimitMiddleware``: rechaza cuerpos HTTP mayores al tope con ``413``,
  tanto por ``Content-Length`` como contando bytes en streaming (chunked).
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import HTTPException, status
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

PREFIJOS_NO_STORE = ("/api/auth", "/api/history", "/api/users")
RUTAS_DOCS = ("/docs", "/redoc")


def cabeceras_seguridad(path: str, debug: bool) -> dict[str, str]:
    cabeceras = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if not path.startswith(RUTAS_DOCS):
        # API JSON: no carga recursos. Swagger/ReDoc (solo en DEBUG) usan CDN.
        cabeceras["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if path.startswith(PREFIJOS_NO_STORE):
        cabeceras["Cache-Control"] = "no-store"
        cabeceras["Pragma"] = "no-cache"
    if not debug:
        cabeceras["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return cabeceras


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, debug: bool) -> None:
        self.app = app
        self.debug = debug

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)
        extra = cabeceras_seguridad(scope.get("path", ""), self.debug)

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for clave, valor in extra.items():
                    if clave not in headers:
                        headers[clave] = valor
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            request_id_ctx.reset(token)


async def _drenar(receive: Receive, message: Message, ya_leidos: int, tope: int) -> None:
    """Lee y descarta (sin acumular) el resto del cuerpo hasta ``tope`` bytes.

    Si se responde 413 con el cuerpo sin consumir, uvicorn cierra el socket y el
    cliente suele ver un reset de conexión en vez del 413. Descartar no usa memoria;
    pasado ``tope`` se deja de leer y la conexión se cierra igual.
    """
    leidos = ya_leidos
    while message.get("more_body", False) and leidos <= tope:
        message = await receive()
        if message["type"] != "http.request":
            return
        leidos += len(message.get("body", b""))


class BodySizeLimitMiddleware:
    FACTOR_DRENAJE = 4  # se descartan hasta 4x el tope antes de cortar

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.tope_drenaje = max_bytes * self.FACTOR_DRENAJE

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for nombre, valor in scope.get("headers", []):
            if nombre == b"content-length":
                try:
                    largo = int(valor)
                except ValueError:
                    largo = -1
                if largo < 0:
                    respuesta = JSONResponse(
                        {"detail": "Content-Length inválido"},
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                    await respuesta(scope, receive, send)
                    return
                if largo > self.max_bytes:
                    if largo <= self.tope_drenaje:
                        await _drenar(receive, {"more_body": True}, 0, self.tope_drenaje)
                    respuesta = JSONResponse(
                        {"detail": "Cuerpo de la solicitud demasiado grande"},
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    )
                    await respuesta(scope, receive, send)
                    return
                break

        recibidos = 0

        async def _receive() -> Message:
            nonlocal recibidos
            message = await receive()
            if message["type"] == "http.request":
                recibidos += len(message.get("body", b""))
                if recibidos > self.max_bytes:
                    # Sin Content-Length (chunked): se corta al superar el tope.
                    await _drenar(receive, message, recibidos, self.tope_drenaje)
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        "Cuerpo de la solicitud demasiado grande",
                    )
            return message

        await self.app(scope, _receive, send)
