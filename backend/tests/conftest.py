"""Fixtures compartidas de la suite.

Aislamiento de datos (obligatorio):
* La base se toma de ``TEST_DATABASE_URL`` (por defecto ``signia_test`` en WSL) y se
  inyecta como ``DATABASE_URL`` **antes** de importar la app; las variables de
  entorno tienen prioridad sobre ``backend/.env``, que nunca se lee aquí.
* Si el nombre de la base no termina en ``_test``, o el servidor no es local, la sesión
  se aborta: la suite trunca tablas y nunca debe correr contra Supabase.
* Antes de cada test se truncan ``history`` y ``users`` y se reinician el rate
  limiter y el registro de conexiones WebSocket.
"""
from __future__ import annotations

import ipaddress
import os

from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/signia_test",
)
_url = make_url(TEST_DATABASE_URL)
if not (_url.database or "").endswith("_test"):
    raise RuntimeError(
        f"TEST_DATABASE_URL debe apuntar a una base que termine en '_test' (llegó {_url.database!r})"
    )


def es_servidor_local(url) -> bool:
    """localhost o IP privada/loopback (WSL). ``?host=`` también define el destino en asyncpg."""
    if "host" in url.query or url.port == 6543:
        return False
    if url.host == "localhost":
        return True
    try:
        return ipaddress.ip_address(url.host or "").is_private
    except ValueError:
        return False


if not es_servidor_local(_url):
    raise RuntimeError("TEST_DATABASE_URL debe apuntar a un PostgreSQL local (nunca a Supabase)")

TEST_SECRET_KEY = "pytest-" + "k3y-S1gn1A-" * 6  # >= 32 caracteres y variada; solo para tests

# Configuración determinista: no depende de lo que tenga backend/.env.
ENV_TESTS = {
    "DATABASE_URL": TEST_DATABASE_URL,
    "DATABASE_URL_SYNC": _url.set(drivername="postgresql+psycopg2").render_as_string(
        hide_password=False
    ),
    "DB_SSL": "false",
    "DB_SSL_ROOT_CERT": "",
    "DB_USE_PGBOUNCER": "false",
    "DB_POOL_SIZE": "5",
    "DB_MAX_OVERFLOW": "5",
    "DB_POOL_RECYCLE_S": "300",
    "SECRET_KEY": TEST_SECRET_KEY,
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
    "DEBUG": "true",
    "ALLOWED_ORIGINS": "http://localhost:4200",
    "ALLOWED_ORIGIN_REGEX": "",
    "TRUST_PROXY_HOPS": "0",
    "DYNAMIC_MODEL_PATH": "models/mejor_modelo_lsch.keras",
    "LABELS_PATH": "models/etiquetas_lsch.json",
    "FEATURES_CONFIG_PATH": "models/config_features.json",
    "STATIC_MODEL_PATH": "models/static_svm.joblib",
    "UMBRAL_CONFIANZA": "0.55",
    "MAX_CONCURRENT_INFERENCES": "2",
    "MAX_CONCURRENT_HASHES": "2",
    "MAX_BODY_BYTES": str(5 * 1024 * 1024),
    "RATE_LIMIT_LOGIN_PER_MIN": "5",
    "RATE_LIMIT_REGISTER_PER_MIN": "3",
    "RATE_LIMIT_PROFILE_PER_MIN": "5",
    "RATE_LIMIT_RECOGNIZE_PER_MIN": "30",
    "WS_MAX_MESSAGE_BYTES": str(48 * 1024),
    "WS_MAX_CONNECTIONS_PER_IP": "5",
    # Alto para que los flujos de la máquina de estados no choquen con el límite;
    # test_security lo baja con monkeypatch para probarlo.
    "WS_MAX_MESSAGES_PER_SEC": "10000",
    "WS_IDLE_TIMEOUT_S": "60",
    "TF_CPP_MIN_LOG_LEVEL": "2",
}
os.environ.update(ENV_TESTS)

# --- A partir de aquí ya es seguro importar la app -------------------------------
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import rate_limiter  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.routes.ws import conexiones_ws  # noqa: E402
from utils import registrar, token_de  # noqa: E402

# Segunda guarda: la app efectivamente quedó apuntando a la base de pruebas.
assert make_url(get_settings().database_url).database == _url.database
assert make_url(str(db_session.engine.url)).database == _url.database

# NullPool: cada TestClient corre la app en su propio event loop y una conexión
# asyncpg no puede reutilizarse entre loops distintos.
db_session.engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
db_session.async_session = async_sessionmaker(
    db_session.engine, class_=AsyncSession, expire_on_commit=False
)

_engine_sync = create_engine(ENV_TESTS["DATABASE_URL_SYNC"], poolclass=NullPool)


def truncar() -> None:
    with _engine_sync.begin() as conn:
        conn.execute(text("TRUNCATE history, users RESTART IDENTITY CASCADE"))


# ----------------------------------------------------------------- fixtures base
@pytest.fixture(scope="session")
def db_sync():
    """Motor síncrono (psycopg2) para preparar y verificar datos desde los tests."""
    try:
        with _engine_sync.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - entorno sin PostgreSQL
        pytest.exit(f"No se pudo conectar a {_url.database} en {_url.host}:{_url.port}: {exc}", 2)
    yield _engine_sync
    truncar()  # deja la base limpia al terminar la sesión


@pytest.fixture(autouse=True)
def _aislamiento(db_sync) -> Iterator[None]:
    truncar()
    rate_limiter.reset()
    conexiones_ws.reset()
    yield
    rate_limiter.reset()
    conexiones_ws.reset()


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="session")
def client(app) -> Iterator[TestClient]:
    """Cliente con lifespan real: el modelo .keras se carga una sola vez por sesión."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def predictor(client):
    return client.app.state.predictor


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def usuario(client) -> dict:
    """Usuario registrado con token. El rate limiter se reinicia para no consumir cupo."""
    datos = registrar(client, "ana_test")
    datos["token"] = token_de(client, "ana_test")
    rate_limiter.reset()
    return datos


@pytest.fixture
def dos_usuarios(client) -> tuple[dict, dict]:
    a = registrar(client, "usuario_a")
    b = registrar(client, "usuario_b")
    a["token"] = token_de(client, "usuario_a")
    b["token"] = token_de(client, "usuario_b")
    rate_limiter.reset()
    return a, b
