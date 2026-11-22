from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.ml.predictor import LSChPredictor, campos_history, formatear_etiqueta, validar_secuencia
from app.ml.static_model import StaticModel
from app.routes.deps import get_predictor, get_static_model
from app.schemas.schemas import RecognitionRequest, RecognitionResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["recognition"])


def _predecir_estatico(modelo: StaticModel, frames: list[list[float]]) -> dict[str, Any]:
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


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize(
    payload: RecognitionRequest,
    predictor: LSChPredictor = Depends(get_predictor),
    modelo_estatico: StaticModel | None = Depends(get_static_model),
) -> RecognitionResponse:
    try:
        if payload.mode == "static":
            if modelo_estatico is None or not modelo_estatico.disponible:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo estático no disponible"
                )
            resultado = await predictor.ejecutar_limitado(
                _predecir_estatico, modelo_estatico, payload.frames
            )
        else:
            resultado = await predictor.predecir_async(payload.frames, payload.top_k)
    except ValueError as exc:
        # p. ej. valores finitos en float64 que desbordan a inf en float32.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Secuencia inválida"
        ) from exc

    # La persistencia en history (JWT + aceptada + save_history) llega en la Fase 3.
    return RecognitionResponse(
        **resultado,
        **campos_history(resultado, payload.mode),
        timestamp=datetime.now(timezone.utc),
    )
