"""Servicio de inferencia LSCh v3 (``mejor_modelo_lsch.keras`` + ``features_lsch.py``).

Invariantes (README_ML.md):
* Cada frame trae exactamente 1629 float32 (Pose 99 + Rostro 1404 + Mano Izq 63 +
  Mano Der 63) con ``y`` isotrópica ya aplicada por el cliente; nunca se espeja.
* Remuestreo a 30 frames: ``N >= 30`` con ``linspace(0, N-1, 30).round()``;
  ``N < 30`` con zero-padding al final (idéntico a ``conversor/test_local.py``).
* El modelo se carga una vez con ``compile=False``, se valida
  ``config_features.json`` y se calienta con ceros. El forward pass usa
  ``model(x, training=False)`` envuelto en ``tf.function`` (nunca ``predict()``).

Este módulo no depende de FastAPI. La inferencia síncrona se expone también como
``predecir_async``, que limita la concurrencia con un ``asyncio.Semaphore``
compartido (REST y WebSocket) y ejecuta el cómputo en un hilo aparte.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from app.ml import features_lsch

logger = logging.getLogger(__name__)

N_FRAMES = features_lsch.N_FRAMES                          # 30
N_FEATURES_RAW = features_lsch.N_FEATURES_ORIGINAL         # 1629
N_FEATURES_MODELO = features_lsch.N_FEATURES_MODELO        # 576
VERSION_FEATURES = features_lsch.VERSION_CONFIG            # 3

# Rango de los bloques de manos dentro del vector de 1629 (Mano Izq + Mano Der).
INICIO_MANOS = features_lsch.INICIO_MANO_IZQ * 3           # 1503
FIN_MANOS = N_FEATURES_RAW                                 # 1629

TOP_K_MAX = 5

T = TypeVar("T")


def cargar_etiquetas(ruta: str | Path) -> list[str]:
    """Acepta lista ``["hola", ...]`` o dict ``{"0": "hola", ...}``."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if isinstance(datos, list):
        return [str(e) for e in datos]
    if isinstance(datos, dict):
        return [str(datos[str(i)]) for i in range(len(datos))]
    raise ValueError(f"Formato de etiquetas no reconocido en {ruta}")


def formatear_etiqueta(etiqueta_raw: str) -> tuple[str, bool]:
    """``'a_que_hora_abren.I'`` -> ``('¿a que hora abren?', True)``."""
    es_pregunta = etiqueta_raw.endswith(".I")
    limpia = etiqueta_raw[:-2] if es_pregunta else etiqueta_raw
    limpia = limpia.replace("_", " ").strip()
    if es_pregunta:
        limpia = f"¿{limpia}?"
    return limpia, es_pregunta


def remuestrear_a_30(frames: np.ndarray) -> np.ndarray:
    """``(N, 1629)`` -> ``(30, 1629)`` float32 (paridad con ``test_local.remuestrear``)."""
    n = frames.shape[0]
    if n == N_FRAMES:
        return frames.astype(np.float32, copy=False)
    if n > N_FRAMES:
        idx = np.linspace(0, n - 1, N_FRAMES).round().astype(int)
        return frames[idx].astype(np.float32, copy=False)
    salida = np.zeros((N_FRAMES, N_FEATURES_RAW), dtype=np.float32)
    salida[:n] = frames
    return salida


def hay_manos(frame: np.ndarray) -> bool:
    """Un bloque de mano ausente llega como 0.0 exacto; cualquier valor != 0 = mano detectada."""
    return bool(np.any(frame[INICIO_MANOS:FIN_MANOS]))


def validar_secuencia(frames: Any) -> np.ndarray:
    """Convierte a ``(N, 1629)`` float32 y valida forma y finitud tras el cast.

    El chequeo después del cast importa: un valor finito en float64 (p. ej. 1e300)
    se vuelve ``inf`` en float32.
    """
    with np.errstate(over="ignore"):  # el desborde se detecta abajo con isfinite
        arr = np.asarray(frames, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != N_FEATURES_RAW or arr.shape[0] < 1:
        raise ValueError(f"Se esperaba una secuencia (N, {N_FEATURES_RAW}); llegó {arr.shape}")
    if not np.isfinite(arr).all():
        raise ValueError("La secuencia contiene valores no finitos (NaN/Inf)")
    return arr


def campos_history(resultado: dict[str, Any], mode: str) -> dict[str, Any]:
    """Campos compatibles con la tabla ``history`` a partir del contrato v3."""
    mejor = resultado["prediccion"]
    return {
        "predicted_label": mejor["clase_raw"],
        "spanish_text": mejor["texto"],
        "confidence": mejor["confianza"],
        "mode": mode,
    }


class LSChPredictor:
    def __init__(
        self,
        modelo_path: str | Path,
        etiquetas_path: str | Path,
        config_path: str | Path,
        umbral_confianza: float = 0.55,
        max_concurrentes: int = 2,
    ) -> None:
        modelo_path = Path(modelo_path)
        if modelo_path.suffix != ".keras":
            raise ValueError(
                f"Modelo no soportado: {modelo_path.name}. Solo se acepta el v3 "
                "'mejor_modelo_lsch.keras' (el legado .h5 está prohibido)."
            )

        # 1) Contrato de features: falla antes de aceptar tráfico si no coincide.
        features_lsch.verificar_config(config_path)

        # 2) Modelo (una sola vez, sin compilar).
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        import tensorflow as tf

        self.model = tf.keras.models.load_model(modelo_path, compile=False)
        entrada = tuple(self.model.input_shape)
        salida = tuple(self.model.output_shape)
        if entrada[1:] != (N_FRAMES, N_FEATURES_MODELO):
            raise ValueError(f"Entrada esperada (None, 30, 576); el modelo tiene {entrada}")
        self.num_clases = int(salida[-1])

        # 3) Etiquetas.
        self.etiquetas = cargar_etiquetas(etiquetas_path)
        if len(self.etiquetas) != self.num_clases:
            raise ValueError(
                f"{len(self.etiquetas)} etiquetas para {self.num_clases} salidas del modelo"
            )

        self.umbral = float(umbral_confianza)
        self.version_features = VERSION_FEATURES
        self.max_concurrentes = int(max_concurrentes)
        # Compartido por REST y WebSocket para acotar el uso de CPU.
        self._semaforo = asyncio.Semaphore(self.max_concurrentes)

        # 4) Forward pass compilado como grafo: en CPU baja de ~200 ms a ~4 ms.
        model = self.model

        @tf.function(reduce_retracing=True)
        def _forward(x):
            return model(x, training=False)

        self._forward = _forward

        # 5) Warm-up: 2 llamadas con ceros (traza + primera ejecución del grafo)
        #    y el pipeline de features con un tensor de ceros.
        ceros = np.zeros((1, N_FRAMES, N_FEATURES_MODELO), dtype=np.float32)
        self.warmup_ms: list[float] = []
        for _ in range(2):
            t0 = time.perf_counter()
            self._forward(ceros)
            self.warmup_ms.append(round((time.perf_counter() - t0) * 1000, 2))
        features_lsch.preparar_entrada_modelo(np.zeros((N_FRAMES, N_FEATURES_RAW), np.float32))

        logger.info(
            "Modelo LSCh v3 cargado: %d clases, features v%d, warm-up %s ms",
            self.num_clases,
            self.version_features,
            self.warmup_ms,
        )

    # ------------------------------------------------------------------ API
    def clases(self) -> list[dict[str, Any]]:
        salida = []
        for i, raw in enumerate(self.etiquetas):
            texto, es_pregunta = formatear_etiqueta(raw)
            salida.append(
                {"indice": i, "clase_raw": raw, "texto": texto, "es_pregunta": es_pregunta}
            )
        return salida

    def probabilidades(self, secuencia: np.ndarray) -> np.ndarray:
        """``(N, 1629)`` validada -> vector de probabilidades ``(num_clases,)``."""
        seq_30 = remuestrear_a_30(secuencia)
        entrada = features_lsch.preparar_entrada_modelo(seq_30)[np.newaxis].astype(
            np.float32, copy=False
        )
        probs = self._forward(entrada).numpy()[0].astype(np.float64)
        # Normalización defensiva si el modelo devolviera logits.
        if not (np.all(probs >= 0) and abs(float(probs.sum()) - 1.0) < 1e-2):
            e = np.exp(probs - probs.max())
            probs = e / e.sum()
        return probs

    def predecir_secuencia(
        self, frames: Any, top_k: int = 3, umbral: float | None = None
    ) -> dict[str, Any]:
        """Inferencia síncrona (CPU-bound). Llamar desde un hilo, no desde el event loop."""
        t0 = time.perf_counter()
        secuencia = validar_secuencia(frames)
        probs = self.probabilidades(secuencia)

        k = max(1, min(int(top_k), TOP_K_MAX, self.num_clases))
        top_idx = np.argsort(probs)[::-1][:k]
        candidatos = []
        for idx in top_idx:
            raw = self.etiquetas[int(idx)]
            texto, es_pregunta = formatear_etiqueta(raw)
            candidatos.append(
                {
                    "clase_raw": raw,
                    "texto": texto,
                    "es_pregunta": es_pregunta,
                    "confianza": round(float(probs[idx]), 4),
                }
            )

        mejor = candidatos[0]
        umbral_efectivo = self.umbral if umbral is None else float(umbral)
        return {
            "aceptada": mejor["confianza"] >= umbral_efectivo,
            "prediccion": mejor,
            "top_k": candidatos,
            "frames_recibidos": int(secuencia.shape[0]),
            "latencia_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    async def predecir_async(
        self, frames: Any, top_k: int = 3, umbral: float | None = None
    ) -> dict[str, Any]:
        """Inferencia no bloqueante con tope de concurrencia compartido."""
        return await self.ejecutar_limitado(self.predecir_secuencia, frames, top_k, umbral)

    async def ejecutar_limitado(self, fn: Callable[..., T], *args: Any) -> T:
        """Corre ``fn`` en un hilo, bajo el semáforo compartido de inferencias."""
        async with self._semaforo:
            return await asyncio.to_thread(fn, *args)

    def info(self) -> dict[str, Any]:
        return {
            "estado": "loaded",
            "archivo": "mejor_modelo_lsch.keras",
            "version_features": self.version_features,
            "num_clases": self.num_clases,
            "umbral_confianza": self.umbral,
            "max_inferencias_concurrentes": self.max_concurrentes,
        }
