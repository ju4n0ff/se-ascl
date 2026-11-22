"""Reconocimiento REST: JSON ``(N, 1629)`` o binario ``Float32Array`` crudo."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limitar
from app.core.security import bearer_scheme, get_current_user_optional
from app.db.session import get_db
from app.ml.predictor import LSChPredictor, campos_history, formatear_etiqueta, validar_secuencia
from app.ml.static_model import StaticModel
from app.routes.deps import get_predictor, get_static_model
from app.schemas.schemas import (
    MAX_FRAMES_REST,
    MIN_FRAMES_REST,
    N_FEATURES_RAW,
    RecognitionRequest,
    RecognitionResponse,
)
from app.services.history import debe_guardarse, guardar_prediccion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["recognition"])

BYTES_POR_FRAME = N_FEATURES_RAW * 4  # 6516

_OPENAPI_BODY = {
    "requestBody": {
        "required": True,
        "description": (
            "JSON con `frames` (N x 1629) o `application/octet-stream` con un Float32Array "
            "little-endian de N*1629 valores (N*6516 bytes). En binario, `top_k`, "
            "`save_history` y `mode` van como query params."
        ),
        "content": {
            "application/json": {"schema": RecognitionRequest.model_json_schema()},
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


def _frames_desde_binario(cuerpo: bytes) -> np.ndarray:
    if not cuerpo or len(cuerpo) % BYTES_POR_FRAME != 0:
        raise ValueError(f"El cuerpo binario debe ser múltiplo de {BYTES_POR_FRAME} bytes")
    n = len(cuerpo) // BYTES_POR_FRAME
    if not MIN_FRAMES_REST <= n <= MAX_FRAMES_REST:
        raise ValueError(f"Se requieren entre {MIN_FRAMES_REST} y {MAX_FRAMES_REST} frames")
    return np.frombuffer(cuerpo, dtype="<f4").reshape(n, N_FEATURES_RAW)


def _error_422(detalle: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detalle)


async def _leer_solicitud(
    request: Request, top_k: int, save_history: bool, mode: str
) -> RecognitionRequest | tuple[np.ndarray, int, bool, str]:
    tipo = request.headers.get("content-type", "").split(";")[0].strip().lower()
    # El tope de 5 MB ya lo aplica BodySizeLimitMiddleware al leer el cuerpo.
    cuerpo = await request.body()

    if tipo == "application/octet-stream":
        try:
            frames = await asyncio.to_thread(_frames_desde_binario, cuerpo)
        except ValueError as exc:
            raise _error_422(str(exc)) from exc
        return frames, top_k, save_history, mode

    if tipo == "application/json":
        try:
            return await asyncio.to_thread(RecognitionRequest.model_validate_json, cuerpo)
        except ValidationError as exc:
            errores = [{**e, "loc": ("body", *e["loc"])} for e in exc.errors(include_input=False)]
            raise RequestValidationError(errores) from exc

    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Content-Type debe ser application/json o application/octet-stream",
    )


def _predecir_estatico(modelo: StaticModel, frames: Any) -> dict[str, Any]:
    """Postura estática: clasifica el frame central de la secuencia (en un hilo)."""
    secuencia = validar_secuencia(frames)
    etiqueta, confianza = modelo.predecir(secuencia[secuencia.shape[0] // 2])
    texto, es_pregunta = formatear_etiqueta(etiqueta)
    candidato = {
        "clase_raw": etiqueta,
        "texto": texto,
        "es_pregunta": es_pregunta,
        "confianza": round(confianza, 4),
    }
    return {
        "aceptada": True,
        "prediccion": candidato,
        "top_k": [candidato],
        "frames_recibidos": int(secuencia.shape[0]),
        "latencia_ms": 0.0,
    }


@router.post(
    "/recognize",
    response_model=RecognitionResponse,
    openapi_extra=_OPENAPI_BODY,
    dependencies=[Depends(limitar("recognize", "rate_limit_recognize_per_min"))],
)
async def recognize(
    request: Request,
    top_k: int = Query(default=3, ge=1, le=5, description="Solo para octet-stream"),
    save_history: bool = Query(default=False, description="Solo para octet-stream"),
    mode: Literal["dynamic", "static"] = Query(default="dynamic", description="Solo para octet-stream"),
    predictor: LSChPredictor = Depends(get_predictor),
    modelo_estatico: StaticModel | None = Depends(get_static_model),
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> RecognitionResponse:
    solicitud = await _leer_solicitud(request, top_k, save_history, mode)
    # El JWT opcional se resuelve después de leer el cuerpo: responder 401 con el
    # cuerpo sin consumir hace que uvicorn cierre el socket y el cliente vea un
    # reset de conexión en vez del 401.
    current_user = await get_current_user_optional(cred, db)
    if isinstance(solicitud, RecognitionRequest):
        frames: Any = solicitud.frames
        top_k, save_history, mode = solicitud.top_k, solicitud.save_history, solicitud.mode
    else:
        frames, top_k, save_history, mode = solicitud

    try:
        if mode == "static":
            if modelo_estatico is None or not modelo_estatico.disponible:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo estático no disponible"
                )
            resultado = await predictor.ejecutar_limitado(_predecir_estatico, modelo_estatico, frames)
        else:
            resultado = await predictor.predecir_async(frames, top_k)
    except ValueError as exc:
        # NaN/Inf en binario o valores que desbordan a inf en float32.
        raise _error_422("Secuencia inválida") from exc

    user_id = current_user.id if current_user else None
    guardado = debe_guardarse(user_id, save_history, resultado)
    if guardado:
        await guardar_prediccion(db, user_id, resultado, mode)

    return RecognitionResponse(
        **resultado,
        **campos_history(resultado, mode),
        timestamp=datetime.now(UTC),
        guardado_en_historial=guardado,
    )
