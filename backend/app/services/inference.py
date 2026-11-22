"""
Inference service — loads trained models and runs prediction.

Modes:
- "static"  : legacy SVM classifier (single-frame hand landmarks, deletreo)
- "dynamic" : legacy LSTM classifier (simple hand sequences)
- "lsch_v3" : production LSCh v3 Keras model (Holistic 1629 -> features_lsch -> 576 -> 89)

Models are loaded once at startup. Missing models degrade gracefully.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Loaded at startup
_static_model = None
_dynamic_model = None
_labels: list[str] = []

_lsch_model = None
_lsch_labels: list[str] = []
_lsch_features = None
_lsch_load_error: str | None = None


def _format_lsch_label(raw: str) -> tuple[str, bool]:
    es_pregunta = raw.endswith(".I")
    limpia = raw[:-2] if es_pregunta else raw
    limpia = limpia.replace("_", " ").strip()
    if es_pregunta:
        limpia = f"¿{limpia}?"
    return limpia, es_pregunta


def load_models():
    """Load trained models from disk. Called once at app startup."""
    global _static_model, _dynamic_model, _labels, _lsch_model, _lsch_labels, _lsch_features, _lsch_load_error

    static_path = Path(settings.static_model_path)
    dynamic_path = Path(settings.dynamic_model_path)
    labels_path = Path(settings.labels_path)

    if labels_path.exists():
        with open(labels_path, encoding="utf-8") as f:
            _labels = json.load(f)
        logger.info("Loaded %s legacy labels", len(_labels))
    else:
        logger.warning("Labels file not found: %s", labels_path)

    if static_path.exists():
        try:
            import joblib

            _static_model = joblib.load(static_path)
            logger.info("Loaded static model: %s", static_path)
        except Exception as e:
            logger.warning("Failed to load static model %s: %s", static_path, e)
    else:
        logger.warning("Static model not found: %s", static_path)

    if dynamic_path.exists():
        try:
            from tensorflow import keras

            _dynamic_model = keras.models.load_model(str(dynamic_path))
            logger.info("Loaded dynamic model: %s", dynamic_path)
        except ImportError:
            logger.warning("TensorFlow not installed, skipping dynamic model")
        except Exception as e:
            logger.error("Failed to load dynamic model: %s", e)
    else:
        logger.warning("Dynamic model not found: %s", dynamic_path)

    _load_lsch_v3()


def _load_lsch_v3():
    global _lsch_model, _lsch_labels, _lsch_features, _lsch_load_error

    model_path = Path(settings.lsch_model_path)
    labels_path = Path(settings.lsch_labels_path)
    config_path = Path(settings.lsch_config_path)
    features_dir = Path(settings.lsch_features_module)

    if not model_path.exists():
        _lsch_load_error = f"LSCh model not found: {model_path}"
        logger.warning(_lsch_load_error)
        return

    try:
        if str(features_dir) not in sys.path:
            sys.path.insert(0, str(features_dir))
        import features_lsch  # type: ignore

        if config_path.exists():
            features_lsch.verificar_config(str(config_path))
        else:
            logger.warning("LSCh config not found: %s (skipping config verification)", config_path)

        _lsch_features = features_lsch

        with open(labels_path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            _lsch_labels = [str(x) for x in raw]
        else:
            _lsch_labels = [str(raw[str(i)]) for i in range(len(raw))]

        import tensorflow as tf

        _lsch_model = tf.keras.models.load_model(str(model_path), compile=False)
        dummy = np.zeros((1, 30, 576), dtype=np.float32)
        _ = _lsch_model(dummy, training=False)
        _lsch_load_error = None
        logger.info("Loaded LSCh v3 model: %s (%s classes)", model_path, len(_lsch_labels))
    except Exception as e:
        _lsch_load_error = str(e)
        _lsch_model = None
        logger.exception("Failed to load LSCh v3 model: %s", e)


def get_model_status() -> dict:
    return {
        "static_loaded": _static_model is not None,
        "dynamic_loaded": _dynamic_model is not None,
        "lsch_v3_loaded": _lsch_model is not None,
        "lsch_v3_labels": len(_lsch_labels),
        "lsch_v3_error": _lsch_load_error,
    }


def _hands_to_features(hands: list) -> np.ndarray:
    """
    Flatten hand landmarks to feature vector.
    21 points × 3 coords × 2 hands = 126 features (padded to 126 if 1 hand).
    """
    features = []
    for hand in hands[:2]:  # max 2 hands
        for point in hand.get("landmarks", hand if isinstance(hand, list) else []):
            if isinstance(point, dict):
                features.extend([point.get("x", 0), point.get("y", 0), point.get("z", 0)])
            else:
                features.extend([point[0], point[1], point[2] if len(point) > 2 else 0])

    # Pad to 126 if only 1 hand
    while len(features) < 126:
        features.extend([0.0, 0.0, 0.0])

    return np.array(features[:126], dtype=np.float32)


def predict(
    mode: str,
    hands: Optional[list] = None,
    face: Optional[list] = None,
    frames: Optional[list[list[float]]] = None,
    top_k: int = 3,
) -> dict:
    """
    Run inference on the given landmarks.

    Returns dict with predicted_label, spanish_text, confidence, mode (+ optional lsch_v3 fields).
    """
    hands = hands or []

    if mode == "lsch_v3":
        return _predict_lsch_v3(frames or [], top_k=top_k)

    features = _hands_to_features(hands)
    if mode == "static":
        return _predict_static(features)
    return _predict_dynamic(features)


def _resample_to_30(frames: np.ndarray) -> np.ndarray:
    n = frames.shape[0]
    if n == 30:
        return frames.astype(np.float32, copy=False)
    if n > 30:
        idx = np.linspace(0, n - 1, 30).round().astype(int)
        return frames[idx].astype(np.float32, copy=False)
    out = np.zeros((30, 1629), dtype=np.float32)
    out[:n] = frames.astype(np.float32, copy=False)
    return out


def _predict_lsch_v3(frames: list[list[float]], top_k: int = 3) -> dict:
    if _lsch_model is None or _lsch_features is None:
        return {
            "predicted_label": "UNKNOWN",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "lsch_v3",
            "accepted": False,
            "note": _lsch_load_error or "Modelo LSCh v3 no cargado",
        }

    if not frames:
        return {
            "predicted_label": "UNKNOWN",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "lsch_v3",
            "accepted": False,
            "error": "Se requieren frames para modo lsch_v3",
        }

    try:
        seq = np.asarray(frames, dtype=np.float32)
        if seq.ndim != 2 or seq.shape[1] != 1629:
            return {
                "predicted_label": "INVALID",
                "spanish_text": "",
                "confidence": 0.0,
                "mode": "lsch_v3",
                "accepted": False,
                "error": f"frames debe tener forma (N,1629), recibido {list(seq.shape)}",
            }

        t0 = time.perf_counter()
        seq30 = _resample_to_30(seq)
        x = _lsch_features.preparar_entrada_modelo(seq30)
        x = np.asarray(x, dtype=np.float32)[np.newaxis, ...]

        probs = _lsch_model(x, training=False).numpy()[0].astype(np.float64)
        if not np.isclose(np.sum(probs), 1.0, atol=1e-2):
            exp = np.exp(probs - np.max(probs))
            probs = exp / exp.sum()

        k = max(1, min(int(top_k or 3), len(probs)))
        top_idx = np.argsort(probs)[::-1][:k]
        candidates = []
        for idx in top_idx:
            raw = _lsch_labels[int(idx)] if int(idx) < len(_lsch_labels) else f"class_{int(idx)}"
            text, is_question = _format_lsch_label(raw)
            candidates.append(
                {
                    "clase_raw": raw,
                    "texto": text,
                    "es_pregunta": is_question,
                    "confianza": round(float(probs[int(idx)]), 4),
                }
            )

        best = candidates[0]
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        accepted = float(best["confianza"]) >= float(settings.lsch_confidence_threshold)

        return {
            "predicted_label": best["clase_raw"],
            "spanish_text": best["texto"] if accepted else "",
            "confidence": float(best["confianza"]),
            "mode": "lsch_v3",
            "accepted": accepted,
            "top_k": candidates,
            "frames_received": int(seq.shape[0]),
            "latency_ms": latency_ms,
        }
    except Exception as e:
        logger.exception("LSCh v3 prediction error: %s", e)
        return {
            "predicted_label": "ERROR",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "lsch_v3",
            "accepted": False,
            "error": "Error en inferencia LSCh v3",
        }


def _predict_static(features: np.ndarray) -> dict:
    """SVM inference for static signs (deletreo)."""
    if _static_model is None:
        return {
            "predicted_label": "UNKNOWN",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "static",
            "note": "Modelo SVM no cargado",
        }

    try:
        prediction = _static_model.predict(features.reshape(1, -1))[0]
        if hasattr(_static_model, "predict_proba"):
            proba = _static_model.predict_proba(features.reshape(1, -1))
            confidence = float(np.max(proba))
        else:
            confidence = 0.8

        label = str(prediction)
        return {
            "predicted_label": label,
            "spanish_text": label,
            "confidence": confidence,
            "mode": "static",
        }
    except Exception as e:
        logger.error(f"SVM prediction error: {e}")
        return {
            "predicted_label": "ERROR",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "static",
        }


def _predict_dynamic(features: np.ndarray) -> dict:
    """LSTM inference for dynamic signs (conversacion)."""
    if _dynamic_model is None:
        return {
            "predicted_label": "UNKNOWN",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "dynamic",
            "note": "Modelo LSTM no cargado",
        }

    try:
        # LSTM expects (batch, timesteps, features)
        # For single frame, expand to (1, 1, 126)
        seq = features.reshape(1, 1, -1)
        prediction = _dynamic_model.predict(seq, verbose=0)
        class_idx = int(np.argmax(prediction))
        confidence = float(np.max(prediction))

        label = _labels[class_idx] if class_idx < len(_labels) else f"class_{class_idx}"

        # Map gloss to Spanish
        spanish = _gloss_to_spanish(label)

        return {
            "predicted_label": label,
            "spanish_text": spanish,
            "confidence": confidence,
            "mode": "dynamic",
        }
    except Exception as e:
        logger.error(f"LSTM prediction error: {e}")
        return {
            "predicted_label": "ERROR",
            "spanish_text": "",
            "confidence": 0.0,
            "mode": "dynamic",
        }


_GLOSS_MAP = {
    "HOLA": "¡Hola!",
    "GRACIAS": "Gracias",
    "POR_FAVOR": "Por favor",
    "SI": "Sí",
    "NO": "No",
    "AYUDA": "Ayuda",
    "AGUA": "Agua",
    "COMIDA": "Comida",
    "FAMILIA": "Familia",
    "AMIGO": "Amigo",
    "CASA": "Casa",
    "TRABAJO": "Trabajo",
    "ESCUELA": "Escuela",
    "BIEN": "Bien",
    "MAL": "Mal",
    "YO": "Yo",
    "TU": "Tú",
}


def _gloss_to_spanish(gloss: str) -> str:
    return _GLOSS_MAP.get(gloss, gloss)
