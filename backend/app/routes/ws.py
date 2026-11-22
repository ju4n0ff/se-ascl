"""WebSocket de reconocimiento en streaming (contrato v3).

Cliente -> servidor:
* ``{"type": "frame", "data": [1629 floats]}`` o binario ``Float32Array`` (6516 bytes, little-endian).
* ``{"type": "config", "modo": "auto"|"manual", "umbral": 0.55, "top_k": 3}``
* ``{"type": "manual_start"}`` / ``{"type": "manual_stop"}`` / ``{"type": "reset"}``

Servidor -> cliente:
* ``{"type": "estado", "estado": "ESPERANDO"|"GRABANDO", "modo": ..., "frames_acumulados": n}``
* ``{"type": "prediccion", "origen": "auto"|"manual", "aviso": ..., <contrato v3>, <campos history>}``
* ``{"type": "descartado", "motivo": "ruido", "frames": n, "min_frames": 12}``
* ``{"type": "error", "codigo": ..., "detalle": ...}``

Los frames solo viven en la memoria de la sesión de cada conexión.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ml.predictor import N_FEATURES_RAW, LSChPredictor, campos_history
from app.services.segmenter import MIN_FRAMES_SENA, Evento, SesionReconocimiento

logger = logging.getLogger(__name__)
router = APIRouter()

BYTES_FRAME_BINARIO = N_FEATURES_RAW * 4  # 6516


class ConfigMensaje(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modo: Literal["auto", "manual"] | None = None
    umbral: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    top_k: int | None = Field(default=None, ge=1, le=5)


class FrameInvalido(ValueError):
    pass


def _validar_frame(arr: np.ndarray) -> np.ndarray:
    if arr.shape != (N_FEATURES_RAW,):
        raise FrameInvalido(f"El frame debe tener exactamente {N_FEATURES_RAW} floats")
    if not np.isfinite(arr).all():
        raise FrameInvalido("El frame contiene valores no finitos (NaN/Inf)")
    return arr


def frame_desde_json(data: Any) -> np.ndarray:
    if not isinstance(data, list) or len(data) != N_FEATURES_RAW:
        raise FrameInvalido(f"El frame debe tener exactamente {N_FEATURES_RAW} floats")
    if not all(type(v) in (int, float) for v in data):
        raise FrameInvalido("El frame solo admite números")
    return _validar_frame(np.asarray(data, dtype=np.float32))


def frame_desde_binario(data: bytes) -> np.ndarray:
    if len(data) != BYTES_FRAME_BINARIO:
        raise FrameInvalido(f"El frame binario debe pesar {BYTES_FRAME_BINARIO} bytes")
    return _validar_frame(np.frombuffer(data, dtype="<f4").copy())


def _msg_estado(sesion: SesionReconocimiento) -> dict[str, Any]:
    return {
        "type": "estado",
        "estado": sesion.estado,
        "modo": sesion.modo,
        "frames_acumulados": sesion.frames_acumulados,
    }


def _msg_error(codigo: str, detalle: str) -> dict[str, Any]:
    return {"type": "error", "codigo": codigo, "detalle": detalle}


async def _emitir(
    websocket: WebSocket,
    predictor: LSChPredictor,
    sesion: SesionReconocimiento,
    eventos: list[Evento],
) -> None:
    for ev in eventos:
        if ev.tipo == "estado":
            await websocket.send_json(_msg_estado(sesion))
        elif ev.tipo == "ruido":
            await websocket.send_json(
                {"type": "descartado", "motivo": "ruido", "frames": ev.n_frames,
                 "min_frames": MIN_FRAMES_SENA}
            )
        else:  # secuencia
            try:
                resultado = await predictor.predecir_async(ev.frames, sesion.top_k, sesion.umbral)
            except Exception:
                logger.exception("Fallo de inferencia en WebSocket")
                await websocket.send_json(_msg_error("inferencia", "Error en inferencia"))
                continue
            await websocket.send_json(
                {
                    "type": "prediccion",
                    "origen": ev.origen,
                    "aviso": ev.aviso,
                    **resultado,
                    **campos_history(resultado, "dynamic"),
                }
            )


def _procesar_comando(sesion: SesionReconocimiento, msg: dict[str, Any]) -> list[Evento]:
    tipo = msg.get("type")
    if tipo == "frame":
        return sesion.procesar_frame(frame_desde_json(msg.get("data")))
    if tipo == "config":
        try:
            cfg = ConfigMensaje.model_validate(msg)
        except ValidationError as exc:
            raise FrameInvalido("Configuración inválida") from exc
        return [sesion.configurar(modo=cfg.modo, umbral=cfg.umbral, top_k=cfg.top_k)]
    if tipo == "manual_start":
        return [sesion.manual_start()]
    if tipo == "manual_stop":
        return sesion.manual_stop()
    if tipo == "reset":
        return [sesion.reset()]
    raise FrameInvalido("Tipo de mensaje desconocido")


@router.websocket("/ws/recognize")
async def ws_recognize(websocket: WebSocket) -> None:
    predictor: LSChPredictor | None = getattr(websocket.app.state, "predictor", None)
    await websocket.accept()
    if predictor is None:
        await websocket.close(code=1011, reason="Modelo no disponible")
        return

    sesion = SesionReconocimiento(umbral=predictor.umbral)
    await websocket.send_json(_msg_estado(sesion))

    try:
        while True:
            mensaje = await websocket.receive()
            if mensaje["type"] == "websocket.disconnect":
                break
            try:
                if mensaje.get("bytes") is not None:
                    eventos = sesion.procesar_frame(frame_desde_binario(mensaje["bytes"]))
                else:
                    try:
                        msg = json.loads(mensaje.get("text") or "")
                    except json.JSONDecodeError as exc:
                        raise FrameInvalido("JSON inválido") from exc
                    if not isinstance(msg, dict):
                        raise FrameInvalido("Se esperaba un objeto JSON")
                    eventos = _procesar_comando(sesion, msg)
            except FrameInvalido as exc:
                await websocket.send_json(_msg_error("mensaje_invalido", str(exc)))
                continue
            await _emitir(websocket, predictor, sesion, eventos)
    except WebSocketDisconnect:
        pass
    finally:
        sesion.reset()  # descarta cualquier frame en memoria
