"""Flujo funcional de auth + historial y reglas de persistencia de predicciones."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from utils import (
    auth,
    contar_historial,
    generar_frames,
    insertar_historial,
    registrar,
    token_de,
)

# Columnas permitidas en history: ningún landmark ni frame (cero persistencia biométrica).
COLUMNAS_HISTORY = {"id", "user_id", "predicted_label", "spanish_text", "confidence", "mode", "created_at"}


@pytest.fixture
def umbral(predictor, monkeypatch):
    """Permite fijar el umbral del predictor para forzar ``aceptada`` True/False."""

    def _fijar(valor: float) -> None:
        monkeypatch.setattr(predictor, "umbral", valor)

    return _fijar


def _reconocer(client, token=None, **extra):
    payload = {"frames": generar_frames(30, seed=5).tolist(), **extra}
    return client.post("/api/recognize", json=payload, headers=auth(token) if token else {})


def test_health_reporta_bd_y_modelo(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["database"] == "ok"
    assert cuerpo["modelo"]["estado"] == "loaded"
    assert cuerpo["modelo"]["num_clases"] == 89
    assert cuerpo["modelo_estatico"] == "no_disponible"


def test_registro_login_y_mi_historial(client):
    usuario = registrar(client, "flujo_user")
    token = token_de(client, "flujo_user")
    r = client.get("/api/history/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == []
    assert usuario["username"] == "flujo_user"


def test_password_se_guarda_con_argon2id(client, db_sync):
    registrar(client, "hash_user")
    with db_sync.connect() as conn:
        h = conn.execute(
            text("SELECT password_hash FROM users WHERE username = 'hash_user'")
        ).scalar_one()
    assert h.startswith("$argon2id$")
    assert "Prueba1234" not in h


def test_historial_orden_y_limite(client, usuario, db_sync):
    for label in ("uno", "dos", "tres"):
        insertar_historial(db_sync, usuario["id"], label)
    h = auth(usuario["token"])
    todos = client.get("/api/history/me", headers=h).json()
    assert [e["predicted_label"] for e in todos] == ["tres", "dos", "uno"]
    assert len(client.get("/api/history/me?limit=2", headers=h).json()) == 2
    assert client.get("/api/history/me?limit=0", headers=h).status_code == 422
    assert client.get("/api/history/me?limit=201", headers=h).status_code == 422


def test_tabla_history_sin_columnas_biometricas(db_sync):
    with db_sync.connect() as conn:
        columnas = set(
            conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'history'")
            ).scalars()
        )
    assert columnas == COLUMNAS_HISTORY


# ------------------------------------------------- persistencia en /recognize
def test_anonimo_nunca_persiste(client, umbral, db_sync):
    umbral(0.0)
    r = _reconocer(client, save_history=True)
    assert r.status_code == 200
    assert r.json()["guardado_en_historial"] is False
    assert contar_historial(db_sync) == 0


def test_con_token_sin_flag_no_persiste(client, usuario, umbral, db_sync):
    umbral(0.0)
    r = _reconocer(client, usuario["token"], save_history=False)
    assert r.json()["guardado_en_historial"] is False
    assert contar_historial(db_sync) == 0


def test_con_token_flag_y_aceptada_persiste(client, usuario, umbral, db_sync):
    umbral(0.0)
    r = _reconocer(client, usuario["token"], save_history=True)
    cuerpo = r.json()
    assert cuerpo["aceptada"] is True
    assert cuerpo["guardado_en_historial"] is True
    assert contar_historial(db_sync, usuario["id"]) == 1

    entrada = client.get("/api/history/me", headers=auth(usuario["token"])).json()[0]
    assert entrada["predicted_label"] == cuerpo["predicted_label"]
    assert entrada["spanish_text"] == cuerpo["spanish_text"]
    assert abs(entrada["confidence"] - cuerpo["confidence"]) < 1e-6
    assert entrada["mode"] == "dynamic"


def test_no_aceptada_no_persiste(client, usuario, umbral, db_sync):
    umbral(1.01)  # ninguna confianza alcanza el umbral
    r = _reconocer(client, usuario["token"], save_history=True)
    assert r.json()["aceptada"] is False
    assert r.json()["guardado_en_historial"] is False
    assert contar_historial(db_sync) == 0


def test_binario_persiste_con_query_params(client, usuario, umbral, db_sync):
    umbral(0.0)
    r = client.post(
        "/api/recognize?save_history=true&top_k=2",
        content=generar_frames(20, seed=9).tobytes(),
        headers={"Content-Type": "application/octet-stream", **auth(usuario["token"])},
    )
    assert r.status_code == 200
    assert len(r.json()["top_k"]) == 2
    assert r.json()["guardado_en_historial"] is True
    assert contar_historial(db_sync, usuario["id"]) == 1


def test_persistencia_solo_en_el_usuario_del_token(client, dos_usuarios, umbral, db_sync):
    a, b = dos_usuarios
    umbral(0.0)
    _reconocer(client, a["token"], save_history=True)
    assert contar_historial(db_sync, a["id"]) == 1
    assert contar_historial(db_sync, b["id"]) == 0
