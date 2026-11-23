from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import registrar_manejadores
from app.core.logging_config import configurar_logging
from app.core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.db.session import engine
from app.ml.predictor import LSChPredictor
from app.ml.static_model import StaticModel
from app.routes import auth, history, meta, recognition, users, ws

settings = get_settings()
configurar_logging(settings.debug)
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


# Superficie mínima en producción: sin Swagger, ReDoc ni openapi.json.
_docs = {} if settings.debug else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    title="SignIA API",
    description="Traductor de Lengua de Señas Chilena — Backend (modelo LSCh v3)",
    version="2.0.0",
    lifespan=lifespan,
    **_docs,
)
registrar_manejadores(app)

# Orden: el último agregado es el más externo.
#   SecurityHeaders (request_id + cabeceras) -> CORS -> límite de body -> app
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,  # JWT en header Authorization, sin cookies
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware, debug=settings.debug)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(recognition.router)
app.include_router(history.router)
app.include_router(meta.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        ws_max_size=settings.ws_max_message_bytes,
        server_header=False,
    )
