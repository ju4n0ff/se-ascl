from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import registrar_manejadores
from app.db.session import engine
from app.ml.predictor import LSChPredictor
from app.ml.static_model import StaticModel
from app.routes import auth, history, meta, recognition, ws

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Carga única: verifica config_features.json, carga el .keras (compile=False)
    # y hace 2 warm-ups. Si falla, el servidor no arranca (fail-fast).
    app.state.predictor = LSChPredictor(
        modelo_path=settings.dynamic_model_path,
        etiquetas_path=settings.labels_path,
        config_path=settings.features_config_path,
        umbral_confianza=settings.umbral_confianza,
        max_concurrentes=settings.max_concurrent_inferences,
    )
    # Opcional: si no existe, el modo 'static' queda deshabilitado.
    app.state.modelo_estatico = StaticModel(settings.static_model_path)
    yield
    await engine.dispose()


app = FastAPI(
    title="SignIA API",
    description="Traductor de Lengua de Señas Chilena — Backend (modelo LSCh v3)",
    version="0.3.0",
    lifespan=lifespan,
)
registrar_manejadores(app)

# CORS por lista blanca configurable: Fase 3.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(recognition.router)
app.include_router(history.router)
app.include_router(meta.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
