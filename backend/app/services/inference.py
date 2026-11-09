"""
Inference service — loads trained models and runs prediction.

Mode "static"  → SVM classifier (single-frame hand landmarks, deletreo)
Mode "dynamic" → LSTM classifier (sequence of frames, conversacion)

Models are loaded once at startup. If no trained model exists,
returns a placeholder response with confidence 0.
"""
import json
import logging
import os
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


def load_models():
    """Load trained models from disk. Called once at app startup."""
    global _static_model, _dynamic_model, _labels

    static_path = Path(settings.static_model_path)
    dynamic_path = Path(settings.dynamic_model_path)
    labels_path = Path(settings.labels_path)

    if labels_path.exists():
        with open(labels_path) as f:
            _labels = json.load(f)
        logger.info(f"Loaded {len(_labels)} labels")
    else:
        logger.warning(f"Labels file not found: {labels_path}")

    if static_path.exists():
        import joblib
        _static_model = joblib.load(static_path)
        logger.info(f"Loaded static model: {static_path}")
    else:
        logger.warning(f"Static model not found: {static_path}")

    if dynamic_path.exists():
        try:
            from tensorflow import keras
            _dynamic_model = keras.models.load_model(str(dynamic_path))
            logger.info(f"Loaded dynamic model: {dynamic_path}")
        except ImportError:
            logger.warning("TensorFlow not installed, skipping dynamic model")
        except Exception as e:
            logger.error(f"Failed to load dynamic model: {e}")
    else:
        logger.warning(f"Dynamic model not found: {dynamic_path}")


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


def predict(mode: str, hands: list, face: Optional[list] = None) -> dict:
    """
    Run inference on the given landmarks.

    Returns:
        dict with predicted_label, spanish_text, confidence, mode
    """
    features = _hands_to_features(hands)

    if mode == "static":
        return _predict_static(features)
    else:
        return _predict_dynamic(features)


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
