"""Segmentación de señas en streaming (paridad con ``conversor/test_local.py``).

Modo automático (``SegmentadorAuto``):
* ``ESPERANDO`` -> ``GRABANDO`` tras ``FRAMES_INICIO`` frames consecutivos con mano,
  conservando esos frames iniciales en el buffer.
* ``GRABANDO`` -> fin tras ``FRAMES_FIN`` frames consecutivos sin manos o al llegar a
  ``MAX_FRAMES_AUTO``. Se recorta la cola sin manos; si quedan menos de
  ``MIN_FRAMES_SENA`` frames se descarta como ruido.

Modo manual (``SesionReconocimiento``): ``manual_start`` / ``manual_stop`` con tope
``MAX_FRAMES_MANUAL``. Como en ``test_local.py``, una secuencia manual corta se
predice igualmente, pero se marca con un aviso.

Cada conexión WebSocket crea su propia ``SesionReconocimiento``: no hay buffers
globales compartidos entre clientes. Todo vive en RAM y se descarta al cerrar.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from app.ml.predictor import hay_manos

FRAMES_INICIO = 3
FRAMES_FIN = 10
MAX_FRAMES_AUTO = 90
MIN_FRAMES_SENA = 12
MAX_FRAMES_MANUAL = 600

ESPERANDO = "ESPERANDO"
GRABANDO = "GRABANDO"

Modo = Literal["auto", "manual"]


class SegmentadorAuto:
    ESPERANDO, GRABANDO = ESPERANDO, GRABANDO

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.estado = self.ESPERANDO
        self.buffer: list[np.ndarray] = []
        self.racha_manos = 0
        self.racha_sin_manos = 0
        self.previos: deque[np.ndarray] = deque(maxlen=FRAMES_INICIO)

    @property
    def n_frames(self) -> int:
        return len(self.buffer)

    def actualizar(self, vec: np.ndarray, con_manos: bool):
        """Devuelve ``(evento, dato)``: ``(None, None)``, ``("inicio", None)``,
        ``("fin", frames)`` o ``("ruido", n)``."""
        if self.estado == self.ESPERANDO:
            if con_manos:
                self.racha_manos += 1
                self.previos.append(vec)
            else:
                self.racha_manos = 0
                self.previos.clear()
            if self.racha_manos >= FRAMES_INICIO:
                self.estado = self.GRABANDO
                self.buffer = list(self.previos)
                self.previos.clear()
                self.racha_sin_manos = 0
                return "inicio", None
            return None, None

        # GRABANDO
        self.buffer.append(vec)
        self.racha_sin_manos = 0 if con_manos else self.racha_sin_manos + 1

        if self.racha_sin_manos >= FRAMES_FIN or len(self.buffer) >= MAX_FRAMES_AUTO:
            if self.racha_sin_manos > 0:
                frames = self.buffer[: -self.racha_sin_manos]
            else:
                frames = self.buffer
            self.reset()
            if len(frames) < MIN_FRAMES_SENA:
                return "ruido", len(frames)
            return "fin", frames
        return None, None


@dataclass
class Evento:
    """Resultado de procesar un frame o comando.

    ``tipo``: ``"estado"`` (cambio o avance de grabación), ``"secuencia"``
    (lista para predecir) o ``"ruido"`` (segmento descartado).
    """

    tipo: Literal["estado", "secuencia", "ruido"]
    frames: list[np.ndarray] = field(default_factory=list)
    origen: Modo = "auto"
    n_frames: int = 0
    aviso: str | None = None


class SesionReconocimiento:
    """Estado aislado por conexión: modo, umbral, segmentador y buffer manual."""

    def __init__(self, umbral: float, top_k: int = 3) -> None:
        self.modo: Modo = "auto"
        self.umbral = umbral
        self.top_k = top_k
        self.seg = SegmentadorAuto()
        self.grabando_manual = False
        self.buffer_manual: list[np.ndarray] = []

    # ------------------------------------------------------------ estado
    @property
    def estado(self) -> str:
        if self.modo == "auto":
            return self.seg.estado
        return GRABANDO if self.grabando_manual else ESPERANDO

    @property
    def frames_acumulados(self) -> int:
        return self.seg.n_frames if self.modo == "auto" else len(self.buffer_manual)

    def _evento_estado(self) -> Evento:
        return Evento(tipo="estado", origen=self.modo, n_frames=self.frames_acumulados)

    # ---------------------------------------------------------- comandos
    def configurar(
        self, modo: Modo | None = None, umbral: float | None = None, top_k: int | None = None
    ) -> Evento:
        if umbral is not None:
            self.umbral = umbral
        if top_k is not None:
            self.top_k = top_k
        if modo is not None and modo != self.modo:
            self.modo = modo
            self.grabando_manual, self.buffer_manual = False, []
            self.seg.reset()
        return self._evento_estado()

    def manual_start(self) -> Evento:
        if self.modo != "manual":
            self.modo = "manual"
            self.seg.reset()
        self.grabando_manual, self.buffer_manual = True, []
        return self._evento_estado()

    def manual_stop(self) -> list[Evento]:
        if self.modo != "manual" or not self.grabando_manual:
            return [self._evento_estado()]
        frames = self.buffer_manual
        self.grabando_manual, self.buffer_manual = False, []
        eventos = [self._evento_estado()]
        if frames:
            aviso = "secuencia_corta" if len(frames) < MIN_FRAMES_SENA else None
            eventos.insert(
                0, Evento(tipo="secuencia", frames=frames, origen="manual",
                          n_frames=len(frames), aviso=aviso)
            )
        return eventos

    def reset(self) -> Evento:
        self.grabando_manual, self.buffer_manual = False, []
        self.seg.reset()
        return self._evento_estado()

    # ------------------------------------------------------------- frames
    def procesar_frame(self, vec: np.ndarray) -> list[Evento]:
        if self.modo == "auto":
            evento, dato = self.seg.actualizar(vec, hay_manos(vec))
            if evento == "fin":
                return [
                    Evento(tipo="secuencia", frames=dato, origen="auto", n_frames=len(dato)),
                    self._evento_estado(),
                ]
            if evento == "ruido":
                return [
                    Evento(tipo="ruido", origen="auto", n_frames=dato),
                    self._evento_estado(),
                ]
            if evento == "inicio" or self.seg.estado == GRABANDO:
                return [self._evento_estado()]
            return []

        # Manual
        if not self.grabando_manual:
            return []
        self.buffer_manual.append(vec)
        if len(self.buffer_manual) >= MAX_FRAMES_MANUAL:
            frames = self.buffer_manual
            self.grabando_manual, self.buffer_manual = False, []
            return [
                Evento(tipo="secuencia", frames=frames, origen="manual",
                       n_frames=len(frames), aviso="tope_manual"),
                self._evento_estado(),
            ]
        return [self._evento_estado()]
