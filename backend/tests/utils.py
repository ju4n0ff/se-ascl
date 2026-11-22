"""Utilidades compartidas por los tests (datos deterministas, auth y SQL de apoyo)."""
from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ml.predictor import INICIO_MANOS, N_FEATURES_RAW

ORIGEN_OK = "http://localhost:4200"
PASSWORD_OK = "Prueba1234"


def generar_frames(n: int, seed: int = 0, manos: bool = True) -> np.ndarray:
    """Secuencia determinista ``(n, 1629)`` float32; sin manos -> bloque de manos en 0.0."""
    rng = np.random.default_rng(seed)
    frames = rng.uniform(0.2, 0.8, size=(n, N_FEATURES_RAW)).astype(np.float32)
    if not manos:
        frames[:, INICIO_MANOS:] = 0.0
    return frames


def registrar(client: TestClient, username: str, password: str = PASSWORD_OK) -> dict:
    r = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    return r.json()


def token_de(client: TestClient, username: str, password: str = PASSWORD_OK) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def insertar_historial(db_sync, user_id: int, label: str = "hola") -> int:
    with db_sync.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO history (user_id, predicted_label, spanish_text, confidence, mode) "
                "VALUES (:u, :l, :t, 0.9, 'dynamic') RETURNING id"
            ),
            {"u": user_id, "l": label, "t": label},
        ).scalar_one()


def contar_historial(db_sync, user_id: int | None = None) -> int:
    with db_sync.connect() as conn:
        if user_id is None:
            return conn.execute(text("SELECT count(*) FROM history")).scalar_one()
        return conn.execute(
            text("SELECT count(*) FROM history WHERE user_id = :u"), {"u": user_id}
        ).scalar_one()


def existe_historial(db_sync, entry_id: int) -> bool:
    with db_sync.connect() as conn:
        return conn.execute(
            text("SELECT 1 FROM history WHERE id = :i"), {"i": entry_id}
        ).first() is not None
