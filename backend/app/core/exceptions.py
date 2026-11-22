"""Manejadores de excepciones.

* 422: el handler por defecto de FastAPI devuelve el ``input`` rechazado. Con
  landmarks eso significa reflejar arrays de hasta 1629 floats y un 500 cuando el
  valor es NaN/Infinity (no serializable). Aquí solo se devuelve ``loc``, ``msg``
  y ``type``, con un tope de errores.
* 500: nunca se envía traceback, SQL ni rutas al cliente; solo un ``request_id``
  que correlaciona con el log del servidor.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.middleware import cabeceras_seguridad

logger = logging.getLogger(__name__)

MAX_ERRORES = 10


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def errores_limpios(errores: list[dict]) -> list[dict]:
    return [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in errores[:MAX_ERRORES]
    ]


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errores_limpios(exc.errors()), "request_id": _request_id(request)},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.error(
        "Excepción no controlada [%s] %s %s",
        request_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    # Este handler corre fuera de los middlewares de usuario: se reponen las cabeceras.
    cabeceras = cabeceras_seguridad(request.url.path, get_settings().debug)
    cabeceras["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servidor", "request_id": request_id},
        headers=cabeceras,
    )


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
