"""Manejadores de excepciones.

El handler 422 por defecto de FastAPI devuelve el ``input`` rechazado. Con
landmarks eso significa (a) reflejar arrays de hasta 1629 floats al cliente y
(b) un 500 cuando el valor es NaN/Infinity, porque no se puede serializar en
JSON. Aquí se devuelve solo ``loc``, ``msg`` y ``type``, con un tope de errores.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

MAX_ERRORES = 10


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errores = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()[:MAX_ERRORES]
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errores},
    )


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
