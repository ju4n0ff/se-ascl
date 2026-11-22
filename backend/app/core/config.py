"""Configuración centralizada (pydantic-settings v2).

Las rutas relativas de artefactos se resuelven contra el directorio ``backend/``,
de modo que el servidor y los tests funcionan igual sin importar el directorio
de trabajo desde el que se lancen.

Seguridad por defecto: ``DEBUG`` es ``false`` si no se indica, y con ``DEBUG=false``
el arranque falla si ``SECRET_KEY`` es débil o el valor de ejemplo.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

ALGORITMOS_JWT_PERMITIDOS = ["HS256"]
MIN_LARGO_SECRET_KEY = 32
SECRETOS_INSEGUROS = {
    "change-me-in-production",
    "changeme",
    "secret",
    "secret-key",
    "dev",
    "test",
}


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

    # JWT: algoritmo cerrado a HS256 (nunca "none" ni asimétricos mezclados).
    secret_key: str = "change-me-in-production"
    algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)

    # Artefactos ML (v3 oficial)
    static_model_path: Path = Path("models/static_svm.joblib")
    dynamic_model_path: Path = Path("models/mejor_modelo_lsch.keras")
    labels_path: Path = Path("models/etiquetas_lsch.json")
    features_config_path: Path = Path("models/config_features.json")

    # Inferencia
    umbral_confianza: float = Field(default=0.55, ge=0.0, le=1.0)
    max_concurrent_inferences: int = Field(default=2, ge=1, le=16)

    # CORS / Origin del WebSocket: lista separada por comas, sin comodines.
    allowed_origins: str = "http://localhost:4200"

    # Límites anti-DoS
    max_body_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    rate_limit_login_per_min: int = Field(default=5, ge=1)
    rate_limit_register_per_min: int = Field(default=3, ge=1)
    rate_limit_recognize_per_min: int = Field(default=30, ge=1)
    ws_max_message_bytes: int = Field(default=48 * 1024, ge=8 * 1024)
    ws_max_connections_per_ip: int = Field(default=5, ge=1)
    ws_max_messages_per_sec: int = Field(default=35, ge=1)
    ws_idle_timeout_s: float = Field(default=60.0, gt=0)

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    @field_validator(
        "static_model_path",
        "dynamic_model_path",
        "labels_path",
        "features_config_path",
    )
    @classmethod
    def _resolver_ruta(cls, valor: Path) -> Path:
        return valor if valor.is_absolute() else (BACKEND_DIR / valor).resolve()

    @field_validator("allowed_origins")
    @classmethod
    def _validar_origenes(cls, valor: str) -> str:
        origenes = [o.strip().rstrip("/") for o in valor.split(",") if o.strip()]
        for origen in origenes:
            if "*" in origen:
                raise ValueError("ALLOWED_ORIGINS no admite comodines '*'")
            if not origen.startswith(("http://", "https://")):
                raise ValueError(f"Origen inválido en ALLOWED_ORIGINS: {origen!r}")
        return ",".join(origenes)

    @model_validator(mode="after")
    def _validar_secret_key(self) -> Settings:
        debil = (
            self.secret_key.strip().lower() in SECRETOS_INSEGUROS
            or len(self.secret_key) < MIN_LARGO_SECRET_KEY
            or len(set(self.secret_key)) < 10
        )
        if debil and not self.debug:
            raise ValueError(
                "SECRET_KEY débil o por defecto con DEBUG=false. Genera una con: "
                "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if debil:
            logger.warning("SECRET_KEY débil: aceptada solo porque DEBUG=true")
        return self

    @property
    def origins(self) -> list[str]:
        return [o for o in self.allowed_origins.split(",") if o]


@lru_cache
def get_settings() -> Settings:
    return Settings()
