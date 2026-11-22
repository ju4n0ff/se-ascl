"""Configuración segura y comportamiento con ``DEBUG=false``.

La app de producción se levanta en un subproceso con su propio entorno: ``Settings``
se lee al importar ``app.main`` (docs, HSTS), así que no puede alternarse dentro del
mismo proceso de pytest. Los subprocesos usan la misma base ``*_test``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import Settings
from app.core.security import verify_password

BACKEND_DIR = Path(__file__).resolve().parents[1]
SECRET_FUERTE = "Pr0d-" + "x9Y8w7V6u5T4s3R2q1P0-" * 3


def _ejecutar(
    codigo: str | None = None, modulo: str | None = None, **env_extra: str
) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **env_extra}
    args = [sys.executable, "-m", modulo] if modulo else [sys.executable, "-c", codigo]
    return subprocess.run(
        args, cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=180, check=False,
    )


# ------------------------------------------------------------- Settings
def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    "secreto", ["change-me-in-production", "corta", "a" * 64, "secret", "0123456789" * 2]
)
def test_secret_debil_rechazado_en_produccion(secreto):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key=secreto, debug=False)


def test_secret_debil_tolerado_solo_en_debug():
    assert _settings(secret_key="change-me-in-production", debug=True).debug is True


def test_secret_fuerte_aceptado():
    assert _settings(secret_key=SECRET_FUERTE, debug=False).debug is False


@pytest.mark.parametrize("origenes", ["*", "http://localhost:4200,*", "localhost:4200", "ftp://x"])
def test_allowed_origins_invalidos(origenes):
    with pytest.raises(ValidationError):
        _settings(secret_key=SECRET_FUERTE, allowed_origins=origenes)


@pytest.mark.parametrize("algoritmo", ["none", "HS512", "RS256"])
def test_algoritmo_jwt_cerrado(algoritmo):
    with pytest.raises(ValidationError):
        _settings(secret_key=SECRET_FUERTE, algorithm=algoritmo)


def test_debug_false_por_defecto():
    assert Settings.model_fields["debug"].default is False


# ----------------------------------------------------- app con DEBUG=false
SCRIPT_PROD = textwrap.dedent(
    """
    import json
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import app

    c = TestClient(app)  # sin lifespan: no hace falta cargar el modelo
    res = {p: c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")}
    h = c.get("/api/health").headers
    res["hsts"] = h.get("strict-transport-security")
    res["nosniff"] = h.get("x-content-type-options")

    def ws_code(headers):
        try:
            with c.websocket_connect("/ws/recognize", headers=headers) as ws:
                ws.receive_json()
                return "aceptado"
        except WebSocketDisconnect as exc:
            return exc.code

    res["ws_sin_origin"] = ws_code({})
    res["ws_origin_malo"] = ws_code({"origin": "https://evil.example"})
    print(json.dumps(res))
    """
)


@pytest.mark.slow
def test_app_en_produccion():
    r = _ejecutar(SCRIPT_PROD, DEBUG="false", SECRET_KEY=SECRET_FUERTE)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["/docs"] == res["/redoc"] == res["/openapi.json"] == 404
    assert res["hsts"] == "max-age=31536000; includeSubDomains"
    assert res["nosniff"] == "nosniff"
    assert res["ws_sin_origin"] == 1008  # sin Origin solo se admite en DEBUG
    assert res["ws_origin_malo"] == 1008


@pytest.mark.slow
def test_arranque_aborta_con_secret_debil_en_produccion():
    r = _ejecutar("import app.main", DEBUG="false", SECRET_KEY="change-me-in-production")
    assert r.returncode != 0
    assert "SECRET_KEY" in r.stderr


def test_docs_disponibles_en_debug(client):
    assert client.get("/openapi.json").status_code == 200
    esquema = client.get("/openapi.json").json()
    cuerpo = esquema["paths"]["/api/recognize"]["post"]["requestBody"]["content"]
    assert {"application/json", "application/octet-stream"} <= set(cuerpo)
    assert "HTTPBearer" in esquema["components"]["securitySchemes"]


# ------------------------------------------------------------------- seed
@pytest.mark.slow
def test_seed_idempotente_y_bloqueado_en_produccion(client, db_sync):
    primero = _ejecutar(modulo="app.db.seed", DEBUG="true")
    assert primero.returncode == 0, primero.stderr[-2000:]
    assert "creado" in primero.stdout and "4 entradas nuevas" in primero.stdout

    segundo = _ejecutar(modulo="app.db.seed", DEBUG="true")
    assert segundo.returncode == 0
    assert "ya existía" in segundo.stdout and "0 entradas nuevas" in segundo.stdout

    with db_sync.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM history")).scalar_one() == 4

    # El usuario sembrado inicia sesión con su hash Argon2id real.
    r = client.post("/api/auth/login", json={"username": "test_user", "password": "Test1234!"})
    assert r.status_code == 200

    bloqueado = _ejecutar(modulo="app.db.seed", DEBUG="false", SECRET_KEY=SECRET_FUERTE)
    assert bloqueado.returncode == 1
    assert "DEBUG=true" in bloqueado.stderr


def test_seed_sql_trae_hash_argon2id_valido():
    sql = (BACKEND_DIR / "db" / "seed.sql").read_text(encoding="utf-8")
    hashes = re.findall(r"\$argon2id\$[^']+", sql)
    assert hashes, "seed.sql debe traer un hash Argon2id"
    assert all(verify_password("Test1234!", h) for h in hashes)
    assert "$2b$" not in sql  # sin hashes bcrypt legados
