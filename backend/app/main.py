from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routes import auth, recognition, history, ws
from app.services.inference import load_models

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load ML models
    load_models()
    yield
    # Shutdown: nothing to clean up


app = FastAPI(
    title="SignIA API",
    description="Traductor de Lengua de Señas Chilena — Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(auth.router)
app.include_router(recognition.router)
app.include_router(history.router)

# WebSocket route
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
