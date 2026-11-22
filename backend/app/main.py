from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, history, recognition, ws
from app.services.inference import load_models

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load ML models (best effort; app should still boot for health/debug)
    try:
        load_models()
    except Exception:
        # load_models already logs; keep API up so /api/health reports status.
        pass
    yield


app = FastAPI(
    title="SignIA API",
    description="Traductor de Lengua de Señas Chilena — Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(recognition.router)
app.include_router(history.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
