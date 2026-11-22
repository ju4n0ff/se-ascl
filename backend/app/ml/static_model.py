"""Modelo estático opcional (SVM de deletreo, ``static_svm.joblib``).

Si el archivo no existe o no carga, el servidor sigue operando en modo
``dynamic`` y ``/api/health`` informa ``no_disponible``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.predictor import FIN_MANOS, INICIO_MANOS

logger = logging.getLogger(__name__)


class StaticModel:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.clf: Any = None
        if not self.path.exists():
            logger.warning("Modelo estático no encontrado (%s); modo 'static' deshabilitado", self.path.name)
            return
        try:
            import joblib

            # Artefacto local del propio proyecto (nunca subido por usuarios).
            self.clf = joblib.load(self.path)
            logger.info("Modelo estático cargado: %s", self.path.name)
        except Exception:
            logger.exception("No se pudo cargar el modelo estático; modo 'static' deshabilitado")
            self.clf = None

    @property
    def disponible(self) -> bool:
        return self.clf is not None

    @property
    def estado(self) -> str:
        return "loaded" if self.disponible else "no_disponible"

    def predecir(self, frame: np.ndarray) -> tuple[str, float]:
        """Clasifica una postura con los 126 floats de manos (izq + der) de un frame."""
        if self.clf is None:
            raise RuntimeError("Modelo estático no disponible")
        x = np.asarray(frame[INICIO_MANOS:FIN_MANOS], dtype=np.float32).reshape(1, -1)
        etiqueta = str(self.clf.predict(x)[0])
        if hasattr(self.clf, "predict_proba"):
            confianza = float(np.max(self.clf.predict_proba(x)))
        else:
            confianza = 0.0
        return etiqueta, confianza
