"""Dependencias compartidas de las rutas."""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.ml.predictor import LSChPredictor
from app.ml.static_model import StaticModel


def get_predictor(request: Request) -> LSChPredictor:
    predictor = getattr(request.app.state, "predictor", None)
    if predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo no disponible")
    return predictor


def get_static_model(request: Request) -> StaticModel | None:
    return getattr(request.app.state, "modelo_estatico", None)
