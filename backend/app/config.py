from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/signia"
    database_url_sync: str = "postgresql+psycopg2://user:password@localhost:5432/signia"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    static_model_path: str = "models/static_svm.joblib"
    dynamic_model_path: str = "models/dynamic_lstm.h5"
    labels_path: str = "models/labels.json"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
