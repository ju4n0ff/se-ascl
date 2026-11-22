"""Paridad numérica del modelo LSCh v3 entre la API y una referencia independiente.

La referencia usa ``conversor/features_lsch.py`` (cargado desde la carpeta de solo
lectura, sin escribir bytecode allí), el remuestreo descrito en CLAUDE.md y el
modelo Keras en modo eager (``model(x, training=False)``), sin pasar por
``LSChPredictor`` ni por ``tf.function``.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

from app.ml import predictor as predictor_mod
from app.ml.predictor import (
    N_FEATURES_MODELO,
    N_FEATURES_RAW,
    N_FRAMES,
    formatear_etiqueta,
    remuestrear_a_30,
)
from utils import generar_frames

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
CONVERSOR = REPO_DIR / "conversor"
TOLERANCIA = 1e-4  # 4.º decimal

pytestmark = pytest.mark.skipif(
    not (CONVERSOR / "features_lsch.py").exists(), reason="conversor/ no disponible"
)


# ------------------------------------------------------------------ referencia
@pytest.fixture(scope="module")
def fx_conversor():
    """Importa ``conversor/features_lsch.py`` sin generar ``__pycache__`` en conversor/."""
    previo = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "features_lsch_conversor", CONVERSOR / "features_lsch.py"
        )
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        sys.dont_write_bytecode = previo
    return modulo


def remuestreo_referencia(frames: np.ndarray) -> np.ndarray:
    """CLAUDE.md: N >= 30 -> linspace(0, N-1, 30).round(); N < 30 -> zero-padding al final."""
    n = frames.shape[0]
    if n >= N_FRAMES:
        return frames[np.linspace(0, n - 1, N_FRAMES).round().astype(int)]
    salida = np.zeros((N_FRAMES, frames.shape[1]), dtype=np.float32)
    salida[:n] = frames
    return salida


def probabilidades_referencia(predictor, fx_conversor, frames: np.ndarray) -> np.ndarray:
    entrada = fx_conversor.preparar_entrada_modelo(remuestreo_referencia(frames))
    salida = predictor.model(entrada[np.newaxis].astype(np.float32), training=False)
    return np.asarray(salida)[0].astype(np.float64)


def _assert_paridad(cuerpo: dict, probs_ref: np.ndarray, etiquetas: list[str], n: int) -> None:
    orden = np.argsort(probs_ref)[::-1]
    assert cuerpo["frames_recibidos"] == n
    assert cuerpo["prediccion"]["clase_raw"] == etiquetas[orden[0]]
    assert abs(cuerpo["prediccion"]["confianza"] - probs_ref[orden[0]]) < TOLERANCIA
    assert abs(cuerpo["confidence"] - probs_ref[orden[0]]) < TOLERANCIA
    for candidato, idx in zip(cuerpo["top_k"], orden, strict=False):
        assert candidato["clase_raw"] == etiquetas[idx]
        assert abs(candidato["confianza"] - probs_ref[idx]) < TOLERANCIA


# ----------------------------------------------------------- artefactos 1:1
def test_features_lsch_identico_a_conversor():
    backend = (BACKEND_DIR / "app" / "ml" / "features_lsch.py").read_bytes()
    original = (CONVERSOR / "features_lsch.py").read_bytes()
    assert hashlib.sha256(backend).hexdigest() == hashlib.sha256(original).hexdigest()
    assert backend == original


@pytest.mark.parametrize(
    "artefacto", ["mejor_modelo_lsch.keras", "etiquetas_lsch.json", "config_features.json"]
)
def test_artefactos_identicos_a_conversor(artefacto):
    backend = BACKEND_DIR / "models" / artefacto
    original = CONVERSOR / "modelos" / artefacto
    if not original.exists():
        pytest.skip(f"{original} no existe")
    assert backend.read_bytes() == original.read_bytes()


def test_config_features_valida(fx_conversor):
    # Mismo contrato con ambas copias del módulo.
    fx_conversor.verificar_config(BACKEND_DIR / "models" / "config_features.json")
    predictor_mod.features_lsch.verificar_config(BACKEND_DIR / "models" / "config_features.json")


# ------------------------------------------------------------ contrato modelo
def test_modelo_cargado_con_contrato_v3(predictor):
    assert tuple(predictor.model.input_shape) == (None, N_FRAMES, N_FEATURES_MODELO)
    assert tuple(predictor.model.output_shape) == (None, 89)
    assert len(predictor.etiquetas) == predictor.num_clases == 89
    assert len(predictor.warmup_ms) == 2  # 2 warm-ups con ceros
    assert predictor.info()["estado"] == "loaded"


def test_inferencia_sin_predict_y_fuera_del_event_loop():
    codigo = inspect.getsource(predictor_mod)
    assert ".predict(" not in codigo
    assert "training=False" in codigo
    assert "compile=False" in codigo
    assert "asyncio.to_thread" in codigo


# -------------------------------------------------------------- remuestreo
@pytest.mark.parametrize("n", [1, 12, 15, 29, 30, 31, 45, 90, 600])
def test_remuestreo_coincide_con_referencia(n):
    frames = generar_frames(n, seed=n)
    salida = remuestrear_a_30(frames)
    assert salida.shape == (N_FRAMES, N_FEATURES_RAW)
    assert salida.dtype == np.float32
    np.testing.assert_array_equal(salida, remuestreo_referencia(frames))


def test_remuestreo_padding_al_final_con_ceros_exactos():
    salida = remuestrear_a_30(generar_frames(15))
    assert np.all(salida[15:] == 0.0)
    assert np.all(salida[:15] != 0.0)


# ---------------------------------------------------------------- paridad API
@pytest.mark.parametrize("n", [15, 30, 45])
def test_paridad_rest_json(client, predictor, fx_conversor, n):
    frames = generar_frames(n, seed=100 + n)
    r = client.post("/api/recognize", json={"frames": frames.tolist(), "top_k": 5})
    assert r.status_code == 200, r.text
    _assert_paridad(r.json(), probabilidades_referencia(predictor, fx_conversor, frames),
                    predictor.etiquetas, n)


@pytest.mark.parametrize("n", [15, 30, 45])
def test_paridad_rest_binario(client, predictor, fx_conversor, n):
    frames = generar_frames(n, seed=100 + n)
    r = client.post(
        "/api/recognize?top_k=5",
        content=frames.astype("<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200, r.text
    _assert_paridad(r.json(), probabilidades_referencia(predictor, fx_conversor, frames),
                    predictor.etiquetas, n)


@pytest.mark.parametrize("n", [15, 30, 45])
def test_json_y_binario_dan_el_mismo_resultado(client, n):
    frames = generar_frames(n, seed=7 * n)
    json_r = client.post("/api/recognize", json={"frames": frames.tolist(), "top_k": 5}).json()
    bin_r = client.post(
        "/api/recognize?top_k=5",
        content=frames.astype("<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    ).json()
    assert json_r["top_k"] == bin_r["top_k"]
    assert json_r["aceptada"] == bin_r["aceptada"]


def test_predictor_directo_coincide_con_referencia(predictor, fx_conversor):
    frames = generar_frames(45, seed=3)
    np.testing.assert_allclose(
        predictor.probabilidades(frames),
        probabilidades_referencia(predictor, fx_conversor, frames),
        atol=TOLERANCIA,
    )


def test_probabilidades_suman_uno(predictor):
    probs = predictor.probabilidades(generar_frames(30, seed=11))
    assert probs.shape == (89,)
    assert abs(probs.sum() - 1.0) < 1e-3
    assert np.all(probs >= 0)


def test_respuesta_contrato_v3_y_compat_history(client):
    r = client.post("/api/recognize", json={"frames": generar_frames(30).tolist()})
    cuerpo = r.json()
    assert r.status_code == 200
    assert set(cuerpo) >= {
        "aceptada", "prediccion", "top_k", "frames_recibidos", "latencia_ms",
        "predicted_label", "spanish_text", "confidence", "mode", "timestamp",
        "guardado_en_historial",
    }
    assert len(cuerpo["top_k"]) == 3
    assert cuerpo["mode"] == "dynamic"
    assert cuerpo["predicted_label"] == cuerpo["prediccion"]["clase_raw"]
    assert cuerpo["spanish_text"] == cuerpo["prediccion"]["texto"]
    assert cuerpo["guardado_en_historial"] is False
    assert cuerpo["latencia_ms"] >= 0


# ----------------------------------------------------------------- formateo .I
@pytest.mark.parametrize(
    ("raw", "texto", "es_pregunta"),
    [
        ("donde_salida.I", "¿donde salida?", True),
        ("a_que_hora_abren.I", "¿a que hora abren?", True),
        ("como.I", "¿como?", True),
        ("buenos_dias", "buenos dias", False),
        ("RUT", "RUT", False),
    ],
)
def test_formateo_preguntas(raw, texto, es_pregunta):
    assert formatear_etiqueta(raw) == (texto, es_pregunta)


def test_api_clases_formatea_preguntas(client):
    r = client.get("/api/clases")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 89 == len(cuerpo["clases"])
    por_raw = {c["clase_raw"]: c for c in cuerpo["clases"]}
    assert por_raw["donde_salida.I"]["texto"] == "¿donde salida?"
    assert por_raw["donde_salida.I"]["es_pregunta"] is True
    assert por_raw["buenos_dias"]["es_pregunta"] is False
    preguntas = [c for c in cuerpo["clases"] if c["clase_raw"].endswith(".I")]
    assert preguntas and all(c["texto"].startswith("¿") and c["texto"].endswith("?") for c in preguntas)


# ------------------------------------------------------------ concurrencia
async def test_semaforo_limita_inferencias_concurrentes():
    """``ejecutar_limitado`` (usado por REST y WS) nunca corre más de N tareas a la vez."""
    import threading
    import time

    falso = object.__new__(predictor_mod.LSChPredictor)
    falso._semaforo = asyncio.Semaphore(2)
    activos, maximo, lock = 0, 0, threading.Lock()

    def trabajo():
        nonlocal activos, maximo
        with lock:
            activos += 1
            maximo = max(maximo, activos)
        time.sleep(0.05)
        with lock:
            activos -= 1

    await asyncio.gather(*(falso.ejecutar_limitado(trabajo) for _ in range(8)))
    assert maximo == 2


def test_rest_y_ws_comparten_el_mismo_predictor(client, predictor):
    assert client.app.state.predictor is predictor
    assert isinstance(predictor._semaforo, asyncio.Semaphore)
    assert predictor.max_concurrentes == 2
