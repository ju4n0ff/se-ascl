"""Configuración centralizada (pydantic-settings v2).

Las rutas relativas de artefactos se resuelven contra el directorio ``backend/``,
de modo que el servidor y los tests funcionan igual sin importar el directorio
de trabajo desde el que se lancen.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    # Base de datos
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/signia"
    database_url_sync: str = "postgresql+psycopg2://user:password@localhost:5432/signia"

    # JWT (se endurece en la Fase 3)
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Artefactos ML (v3 oficial)
    static_model_path: Path = Path("models/static_svm.joblib")
    dynamic_model_path: Path = Path("models/mejor_modelo_lsch.keras")
    labels_path: Path = Path("models/etiquetas_lsch.json")
    features_config_path: Path = Path("models/config_features.json")

    # Inferencia
    umbral_confianza: float = Field(default=0.55, ge=0.0, le=1.0)
    max_concurrent_inferences: int = Field(default=2, ge=1, le=16)

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True

    @field_validator(
        "static_model_path",
        "dynamic_model_path",
        "labels_path",
        "features_config_path",
    )
    @classmethod
    def _resolver_ruta(cls, valor: Path) -> Path:
        return valor if valor.is_absolute() else (BACKEND_DIR / valor).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
