"""WebSocket de reconocimiento en streaming (contrato v3, endurecido).

Cliente -> servidor:
* Binario ``Float32Array`` little-endian de 1629 valores (6516 bytes): **formato recomendado**.
* ``{"type": "frame", "data": [1629 floats]}`` (JSON; útil para pruebas manuales).
* ``{"type": "config", "modo": "auto"|"manual", "umbral": 0.55, "top_k": 3, "save_history": false}``
* ``{"type": "manual_start"}`` / ``{"type": "manual_stop"}`` / ``{"type": "reset"}``
* ``{"type": "auth", "token": "<JWT>"}`` (opcional; el token nunca va en la URL).

Servidor -> cliente:
* ``{"type": "estado", "estado": "ESPERANDO"|"GRABANDO", "modo": ..., "frames_acumulados": n}``
* ``{"type": "prediccion", "origen": ..., "aviso": ..., "guardado_en_historial": ..., <v3>, <history>}``
* ``{"type": "descartado", "motivo": "ruido", "frames": n, "min_frames": 12}``
* ``{"type": "auth", "ok": true}`` / ``{"type": "error", "codigo": ..., "detalle": ...}``

Controles: ``Origin`` en lista blanca (anti-CSWSH, ``1008``), tope de conexiones por
IP (``1008``), mensajes > ``WS_MAX_MESSAGE_BYTES`` (``1009``), tope de mensajes por
segundo (descarta y avisa; ``1008`` si persiste), *idle timeout* (``1001``) y el
semáforo de inferencias compartido con REST. Los frames solo viven en RAM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.network import obtener_ip_cliente
from app.core.security import usuario_desde_token
from app.db import session as db_session
from app.ml.predictor import N_FEATURES_RAW, LSChPredictor, campos_history
from app.services.history import debe_guardarse, guardar_prediccion
from app.services.segmenter import MIN_FRAMES_SENA, Evento, SesionReconocimiento

logger = logging.getLogger(__name__)
router = APIRouter()

BYTES_FRAME_BINARIO = N_FEATURES_RAW * 4  # 6516
MAX_LARGO_TOKEN = 4096
VENTANAS_EXCEDIDAS_PARA_CERRAR = 5

CLOSE_GOING_AWAY = 1001
CLOSE_POLICY_VIOLATION = 1008
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_INTERNAL_ERROR = 1011


class ConfigMensaje(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modo: Literal["auto", "manual"] | None = None
    umbral: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    top_k: int | None = Field(default=None, ge=1, le=5)
    save_history: bool | None = None


class FrameInvalido(ValueError):
    pass


class RegistroConexiones:
    """Cuenta conexiones WebSocket abiertas por IP (en memoria, por proceso)."""

    def __init__(self) -> None:
        self._por_ip: defaultdict[str, int] = defaultdict(int)

    def adquirir(self, ip: str, maximo: int) -> bool:
        if self._por_ip[ip] >= maximo:
            return False
        self._por_ip[ip] += 1
        return True

    def liberar(self, ip: str) -> None:
        self._por_ip[ip] -= 1
        if self._por_ip[ip] <= 0:
            del self._por_ip[ip]

    def activas(self, ip: str) -> int:
        return self._por_ip.get(ip, 0)

    def reset(self) -> None:
        self._por_ip.clear()


conexiones_ws = RegistroConexiones()


class LimitadorMensajes:
    """Ventana fija de 1 s por conexión."""

    def __init__(self, maximo_por_seg: int) -> None:
        self.maximo = maximo_por_seg
        self.inicio = time.monotonic()
        self.cuenta = 0
        self.avisado = False
        self.ventanas_excedidas = 0

    def permitir(self) -> bool:
        ahora = time.monotonic()
        if ahora - self.inicio >= 1.0:
            excedida = self.cuenta > self.maximo
            self.ventanas_excedidas = self.ventanas_excedidas + 1 if excedida else 0
            self.inicio, self.cuenta, self.avisado = ahora, 0, False
        self.cuenta += 1
        return self.cuenta <= self.maximo

    @property
    def abuso_persistente(self) -> bool:
        return self.ventanas_excedidas >= VENTANAS_EXCEDIDAS_PARA_CERRAR


class Conexion:
    """Estado aislado por conexión: segmentador + identidad + preferencias."""

    def __init__(self, umbral: float, max_msgs_seg: int) -> None:
        self.sesion = SesionReconocimiento(umbral=umbral)
        self.limitador = LimitadorMensajes(max_msgs_seg)
        self.user_id: int | None = None
        self.save_history = False


def origen_permitido(origen: str | None) -> bool:
    settings = get_settings()
    if origen is None:
        # Clientes no navegador (scripts, Postman) no envían Origin: solo en DEBUG.
        return settings.debug
    return settings.origen_en_lista_blanca(origen.rstrip("/"))


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
    with np.errstate(over="ignore"):  # el desborde a inf se detecta con isfinite
        arr = np.asarray(data, dtype=np.float32)
    return _validar_frame(arr)


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


async def _persistir(user_id: int, resultado: dict[str, Any]) -> bool:
    try:
        async with db_session.async_session() as db:
            await guardar_prediccion(db, user_id, resultado, "dynamic")
            await db.commit()
        return True
    except Exception:
        logger.exception("No se pudo guardar la predicción en history (WS)")
        return False


async def _emitir(
    websocket: WebSocket, predictor: LSChPredictor, conn: Conexion, eventos: list[Evento]
) -> None:
    sesion = conn.sesion
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
            guardado = False
            if debe_guardarse(conn.user_id, conn.save_history, resultado):
                guardado = await _persistir(conn.user_id, resultado)
            await websocket.send_json(
                {
                    "type": "prediccion",
                    "origen": ev.origen,
                    "aviso": ev.aviso,
                    "guardado_en_historial": guardado,
                    **resultado,
                    **campos_history(resultado, "dynamic"),
                }
            )


async def _autenticar(websocket: WebSocket, conn: Conexion, token: Any) -> None:
    if not isinstance(token, str) or not 0 < len(token) <= MAX_LARGO_TOKEN:
        await websocket.send_json(_msg_error("auth_invalida", "Token inválido"))
        return
    async with db_session.async_session() as db:
        user = await usuario_desde_token(token, db)
    if user is None:
        await websocket.send_json(_msg_error("auth_invalida", "Token inválido"))
        return
    conn.user_id = user.id
    await websocket.send_json({"type": "auth", "ok": True})


def _procesar_comando(conn: Conexion, msg: dict[str, Any]) -> list[Evento]:
    sesion = conn.sesion
    tipo = msg.get("type")
    if tipo == "frame":
        return sesion.procesar_frame(frame_desde_json(msg.get("data")))
    if tipo == "config":
        try:
            cfg = ConfigMensaje.model_validate(msg)
        except ValidationError as exc:
            raise FrameInvalido("Configuración inválida") from exc
        if cfg.save_history is not None:
            conn.save_history = cfg.save_history
        return [sesion.configurar(modo=cfg.modo, umbral=cfg.umbral, top_k=cfg.top_k)]
    if tipo == "manual_start":
        return [sesion.manual_start()]
    if tipo == "manual_stop":
        return sesion.manual_stop()
    if tipo == "reset":
        return [sesion.reset()]
    raise FrameInvalido("Tipo de mensaje desconocido")


def _tamano(mensaje: dict[str, Any]) -> int:
    if mensaje.get("bytes") is not None:
        return len(mensaje["bytes"])
    texto = mensaje.get("text") or ""
    return len(texto.encode("utf-8"))


@router.websocket("/ws/recognize")
async def ws_recognize(websocket: WebSocket) -> None:
    settings = get_settings()

    # Rechazo antes del handshake: en uvicorn el cliente recibe HTTP 403.
    if not origen_permitido(websocket.headers.get("origin")):
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="Origin no permitido")
        return
    ip = obtener_ip_cliente(websocket)
    if not conexiones_ws.adquirir(ip, settings.ws_max_connections_per_ip):
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="Demasiadas conexiones")
        return

    try:
        predictor: LSChPredictor | None = getattr(websocket.app.state, "predictor", None)
        await websocket.accept()
        if predictor is None:
            await websocket.close(code=CLOSE_INTERNAL_ERROR, reason="Modelo no disponible")
            return

        conn = Conexion(predictor.umbral, settings.ws_max_messages_per_sec)
        await websocket.send_json(_msg_estado(conn.sesion))

        while True:
            try:
                mensaje = await asyncio.wait_for(
                    websocket.receive(), timeout=settings.ws_idle_timeout_s
                )
            except TimeoutError:
                await websocket.close(code=CLOSE_GOING_AWAY, reason="Inactividad")
                return
            if mensaje["type"] == "websocket.disconnect":
                return

            if _tamano(mensaje) > settings.ws_max_message_bytes:
                await websocket.close(code=CLOSE_MESSAGE_TOO_BIG, reason="Mensaje demasiado grande")
                return

            if not conn.limitador.permitir():
                if conn.limitador.abuso_persistente:
                    await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="Rate limit")
                    return
                if not conn.limitador.avisado:
                    conn.limitador.avisado = True
                    await websocket.send_json(
                        _msg_error("rate_limit", f"Máximo {settings.ws_max_messages_per_sec} mensajes/s")
                    )
                continue

            try:
                if mensaje.get("bytes") is not None:
                    eventos = conn.sesion.procesar_frame(frame_desde_binario(mensaje["bytes"]))
                else:
                    try:
                        msg = json.loads(mensaje.get("text") or "")
                    except json.JSONDecodeError as exc:
                        raise FrameInvalido("JSON inválido") from exc
                    if not isinstance(msg, dict):
                        raise FrameInvalido("Se esperaba un objeto JSON")
                    if msg.get("type") == "auth":
                        await _autenticar(websocket, conn, msg.get("token"))
                        continue
                    eventos = _procesar_comando(conn, msg)
            except FrameInvalido as exc:
                await websocket.send_json(_msg_error("mensaje_invalido", str(exc)))
                continue
            await _emitir(websocket, predictor, conn, eventos)
    except WebSocketDisconnect:
        pass
    finally:
        conexiones_ws.liberar(ip)
