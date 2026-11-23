"""Configuración centralizada (pydantic-settings v2).

Las rutas relativas de artefactos se resuelven contra el directorio ``backend/``,
de modo que el servidor y los tests funcionan igual sin importar el directorio
de trabajo desde el que se lancen.

Seguridad por defecto: ``DEBUG`` es ``false`` si no se indica, y con ``DEBUG=false``
el arranque falla si ``SECRET_KEY`` es débil o el valor de ejemplo, o si
``ALLOWED_ORIGINS`` trae un ``http://`` que no sea loopback.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import db_url
from app.core.origins import validar_origen, validar_regex_origen

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
        # Los errores de validación no deben volcar DATABASE_URL ni SECRET_KEY a los logs.
        hide_input_in_errors=True,
    )

    # Base de datos
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/signia"
    database_url_sync: str = "postgresql+psycopg2://user:password@localhost:5432/signia"
    # None = automático: SSL si el host es de Supabase o la URL pide sslmode=require;
    # PgBouncer si el host es *.pooler.supabase.com o el puerto es 6543.
    db_ssl: bool | None = None
    db_ssl_root_cert: Path | None = None  # CA para verificar el certificado (verify-full)
    db_use_pgbouncer: bool | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_recycle_s: int = Field(default=300, ge=30)

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
    # Cada hash Argon2id usa 64 MiB: acota el pico de RAM sin bajar los parámetros.
    max_concurrent_hashes: int = Field(default=2, ge=1, le=16)

    # CORS / Origin del WebSocket: lista separada por comas, sin comodines.
    allowed_origins: str = "http://localhost:4200"
    # Opcional (previews de Vercel): patrón cerrado, ver core/origins.py. Vacío = desactivado.
    allowed_origin_regex: str = ""

    # Proxies inversos confiables delante de la app. 0 = se ignora X-Forwarded-For.
    trust_proxy_hops: int = Field(default=0, ge=0, le=5)

    # Límites anti-DoS
    max_body_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    rate_limit_login_per_min: int = Field(default=5, ge=1)
    rate_limit_register_per_min: int = Field(default=3, ge=1)
    rate_limit_profile_per_min: int = Field(default=5, ge=1)
    rate_limit_recognize_per_min: int = Field(default=30, ge=1)
    ws_max_message_bytes: int = Field(default=48 * 1024, ge=8 * 1024)
    ws_max_connections_per_ip: int = Field(default=5, ge=1)
    ws_max_messages_per_sec: int = Field(default=35, ge=1)
    ws_idle_timeout_s: float = Field(default=60.0, gt=0)

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    _datos_db: db_url.DatosConexion = PrivateAttr()

    @field_validator("db_ssl", "db_ssl_root_cert", "db_use_pgbouncer", mode="before")
    @classmethod
    def _vacio_es_automatico(cls, valor: Any) -> Any:
        return None if isinstance(valor, str) and not valor.strip() else valor

    @field_validator(
        "static_model_path",
        "dynamic_model_path",
        "labels_path",
        "features_config_path",
    )
    @classmethod
    def _resolver_ruta(cls, valor: Path) -> Path:
        return valor if valor.is_absolute() else (BACKEND_DIR / valor).resolve()

    @field_validator("db_ssl_root_cert")
    @classmethod
    def _resolver_ca(cls, valor: Path | None) -> Path | None:
        if valor is None:
            return None
        ruta = valor if valor.is_absolute() else (BACKEND_DIR / valor).resolve()
        if not ruta.is_file():
            raise ValueError("DB_SSL_ROOT_CERT no apunta a un archivo existente")
        return ruta

    @field_validator("database_url_sync")
    @classmethod
    def _normalizar_url_sync(cls, valor: str) -> str:
        return db_url.normalizar_url_sync(valor)

    @field_validator("allowed_origin_regex")
    @classmethod
    def _validar_regex(cls, valor: str) -> str:
        return validar_regex_origen(valor)

    @model_validator(mode="after")
    def _normalizar_database_url(self) -> Settings:
        self._datos_db = db_url.analizar_url(self.database_url)
        self.database_url = db_url.texto(self._datos_db.url)
        if self._datos_db.es_supabase and not self.usar_ssl:
            logger.warning("SSL desactivado hacia Supabase: la conexión puede viajar sin cifrar")
        return self

    @model_validator(mode="after")
    def _validar_origenes(self) -> Settings:
        # Posterior a los campos: la política de http:// depende de DEBUG.
        crudos = [o for o in self.allowed_origins.split(",") if o.strip()]
        self.allowed_origins = ",".join(validar_origen(o, self.debug) for o in crudos)
        return self

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

    def origen_en_lista_blanca(self, origen: str) -> bool:
        """Misma política que ``CORSMiddleware``: lista exacta o regex con ``fullmatch``."""
        if origen in self.origins:
            return True
        patron = self.allowed_origin_regex
        return bool(patron and re.fullmatch(patron, origen))

    @property
    def usar_ssl(self) -> bool:
        return db_url.ssl_efectivo(self._datos_db, self.db_ssl)

    @property
    def usar_pgbouncer(self) -> bool:
        if self.db_use_pgbouncer is not None:
            return self.db_use_pgbouncer
        return self._datos_db.usa_pooler

    @property
    def db_connect_args(self) -> dict[str, Any]:
        return db_url.construir_connect_args(
            usar_ssl=self.usar_ssl,
            usar_pgbouncer=self.usar_pgbouncer,
            sslmode=self._datos_db.sslmode,
            ca=self.db_ssl_root_cert,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
