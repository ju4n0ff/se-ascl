"""Salud del servicio y glosario de clases."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db import session as db_session
from app.ml.predictor import LSChPredictor
from app.routes.deps import get_predictor
from app.schemas.schemas import ClasesResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["meta"])

DB_TIMEOUT_S = 3.0


async def _db_ok() -> bool:
    try:
        await asyncio.wait_for(db_session.ping(), timeout=DB_TIMEOUT_S)
        return True
    except Exception:
        logger.exception("Healthcheck: PostgreSQL no responde")
        return False


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    predictor: LSChPredictor | None = getattr(request.app.state, "predictor", None)
    estatico = getattr(request.app.state, "modelo_estatico", None)

    db_ok = await _db_ok()
    modelo: dict[str, Any] = predictor.info() if predictor else {"estado": "no_cargado"}
    sano = db_ok and predictor is not None

    cuerpo = {
        "status": "ok" if sano else "degraded",
        "service": "signia-backend",
        "database": "ok" if db_ok else "error",
        "modelo": modelo,
        "modelo_estatico": estatico.estado if estatico else "no_disponible",
    }
    return JSONResponse(cuerpo, status_code=200 if sano else 503)


@router.get("/clases", response_model=ClasesResponse)
async def clases(predictor: LSChPredictor = Depends(get_predictor)) -> ClasesResponse:
    lista = predictor.clases()
    return ClasesResponse(total=len(lista), clases=lista)
