from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


# Repo root: .../se-ascl (two levels up from backend/app/config.py)
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/signia"
    database_url_sync: str = "postgresql+psycopg2://user:password@localhost:5432/signia"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Legacy/simple model paths (optional fallback)
    static_model_path: str = "models/static_svm.joblib"
    dynamic_model_path: str = "models/dynamic_lstm.h5"
    labels_path: str = "models/labels.json"

    # LSCh v3 production model (conversor/)
    lsch_model_path: str = str(REPO_ROOT / "conversor" / "modelos" / "mejor_modelo_lsch.keras")
    lsch_labels_path: str = str(REPO_ROOT / "conversor" / "modelos" / "etiquetas_lsch.json")
    lsch_config_path: str = str(REPO_ROOT / "conversor" / "modelos" / "config_features.json")
    lsch_features_module: str = str(REPO_ROOT / "conversor")
    lsch_confidence_threshold: float = 0.55

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
