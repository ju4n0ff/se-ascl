"""Máquina de estados del WebSocket (modo auto, ruido, modo manual) y unitarios del
segmentador. Paridad de la predicción por WS con la inferencia directa."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.segmenter import (
    FRAMES_FIN,
    FRAMES_INICIO,
    MAX_FRAMES_AUTO,
    MAX_FRAMES_MANUAL,
    MIN_FRAMES_SENA,
    SesionReconocimiento,
)
from utils import ORIGEN_OK, contar_historial, generar_frames

TOLERANCIA = 1e-4


@pytest.fixture
def ws(client):
    with client.websocket_connect("/ws/recognize", headers={"origin": ORIGEN_OK}) as conexion:
        inicial = conexion.receive_json()
        assert inicial == {"type": "estado", "estado": "ESPERANDO", "modo": "auto",
                           "frames_acumulados": 0}
        yield conexion


def enviar(ws, frames: np.ndarray) -> None:
    for frame in frames:
        ws.send_bytes(frame.astype("<f4").tobytes())


def recibir(ws, n: int) -> list[dict]:
    return [ws.receive_json() for _ in range(n)]


def assert_sin_mensajes_pendientes(ws) -> None:
    """Un ``reset`` responde con un estado: si llega primero, no había nada en cola."""
    ws.send_json({"type": "reset"})
    siguiente = ws.receive_json()
    assert siguiente["type"] == "estado" and siguiente["frames_acumulados"] == 0, siguiente


def assert_paridad(prediccion: dict, predictor, frames: np.ndarray, top_k: int = 3) -> None:
    directo = predictor.predecir_secuencia(frames, top_k)
    assert prediccion["prediccion"]["clase_raw"] == directo["prediccion"]["clase_raw"]
    for a, b in zip(prediccion["top_k"], directo["top_k"], strict=True):
        assert a["clase_raw"] == b["clase_raw"]
        assert abs(a["confianza"] - b["confianza"]) < TOLERANCIA


# ================================================================== modo auto
class TestModoAuto:
    def test_flujo_completo_inicio_sena_fin(self, ws, predictor):
        manos = generar_frames(18, seed=1)
        sin_manos = generar_frames(FRAMES_FIN, seed=2, manos=False)

        enviar(ws, manos[:2])            # racha 1-2: sin mensajes
        enviar(ws, manos[2:3])           # 3.er frame con manos -> GRABANDO
        inicio = ws.receive_json()
        assert inicio == {"type": "estado", "estado": "GRABANDO", "modo": "auto",
                          "frames_acumulados": FRAMES_INICIO}

        enviar(ws, manos[3:])            # 15 frames de seña
        progreso = recibir(ws, 15)
        assert [m["frames_acumulados"] for m in progreso] == list(range(4, 19))
        assert all(m["estado"] == "GRABANDO" for m in progreso)

        enviar(ws, sin_manos)            # 10 frames sin manos -> fin
        cola = recibir(ws, FRAMES_FIN - 1)
        assert all(m["type"] == "estado" for m in cola)
        prediccion, final = recibir(ws, 2)

        assert prediccion["type"] == "prediccion"
        assert prediccion["origen"] == "auto"
        assert prediccion["aviso"] is None
        assert prediccion["frames_recibidos"] == 18  # se recorta la cola sin manos
        assert len(prediccion["top_k"]) == 3
        assert prediccion["latencia_ms"] > 0
        assert prediccion["guardado_en_historial"] is False
        assert {"predicted_label", "spanish_text", "confidence", "mode"} <= set(prediccion)
        assert final == {"type": "estado", "estado": "ESPERANDO", "modo": "auto",
                         "frames_acumulados": 0}
        assert_paridad(prediccion, predictor, manos)

    def test_ruido_descartado(self, ws):
        enviar(ws, generar_frames(FRAMES_INICIO, seed=3))
        assert ws.receive_json()["estado"] == "GRABANDO"
        enviar(ws, generar_frames(FRAMES_FIN, seed=4, manos=False))
        recibir(ws, FRAMES_FIN - 1)
        descartado, final = recibir(ws, 2)
        assert descartado == {"type": "descartado", "motivo": "ruido", "frames": FRAMES_INICIO,
                              "min_frames": MIN_FRAMES_SENA}
        assert final["estado"] == "ESPERANDO"
        assert_sin_mensajes_pendientes(ws)

    def test_sin_manos_en_espera_no_emite(self, ws):
        enviar(ws, generar_frames(20, seed=5, manos=False))
        assert_sin_mensajes_pendientes(ws)

    def test_racha_de_inicio_se_reinicia(self, ws):
        manos = generar_frames(5, seed=6)
        sin = generar_frames(1, seed=7, manos=False)
        enviar(ws, np.vstack([manos[:2], sin, manos[2:4]]))  # 2 + corte + 2: no inicia
        enviar(ws, manos[4:5])                               # 3 consecutivos -> inicia
        m = ws.receive_json()
        assert m["estado"] == "GRABANDO" and m["frames_acumulados"] == FRAMES_INICIO

    def test_tope_max_frames_auto(self, ws, predictor):
        frames = generar_frames(MAX_FRAMES_AUTO, seed=8)
        enviar(ws, frames)
        mensajes = recibir(ws, MAX_FRAMES_AUTO - FRAMES_INICIO + 2)
        prediccion = mensajes[-2]
        assert prediccion["type"] == "prediccion"
        assert prediccion["frames_recibidos"] == MAX_FRAMES_AUTO
        assert mensajes[-1]["estado"] == "ESPERANDO"
        assert_paridad(prediccion, predictor, frames)

    def test_frame_json_equivale_a_binario(self, ws):
        frames = generar_frames(FRAMES_INICIO, seed=10)
        for f in frames:
            ws.send_json({"type": "frame", "data": f.tolist()})
        assert ws.receive_json()["estado"] == "GRABANDO"

    def test_config_top_k_y_umbral(self, ws):
        ws.send_json({"type": "config", "top_k": 5, "umbral": 0.0})
        assert ws.receive_json()["type"] == "estado"
        enviar(ws, generar_frames(14, seed=11))
        recibir(ws, 14 - FRAMES_INICIO + 1)
        enviar(ws, generar_frames(FRAMES_FIN, seed=12, manos=False))
        recibir(ws, FRAMES_FIN - 1)
        prediccion, _ = recibir(ws, 2)
        assert len(prediccion["top_k"]) == 5
        assert prediccion["aceptada"] is True  # umbral 0.0


# ================================================================ modo manual
class TestModoManual:
    def test_manual_start_stop(self, ws, predictor):
        ws.send_json({"type": "manual_start"})
        assert ws.receive_json() == {"type": "estado", "estado": "GRABANDO", "modo": "manual",
                                     "frames_acumulados": 0}
        # En manual se graba todo, haya manos o no.
        frames = np.vstack([generar_frames(10, seed=13), generar_frames(10, seed=14, manos=False)])
        enviar(ws, frames)
        assert [m["frames_acumulados"] for m in recibir(ws, 20)] == list(range(1, 21))

        ws.send_json({"type": "manual_stop"})
        prediccion, final = recibir(ws, 2)
        assert prediccion["type"] == "prediccion"
        assert prediccion["origen"] == "manual"
        assert prediccion["aviso"] is None
        assert prediccion["frames_recibidos"] == 20
        assert final == {"type": "estado", "estado": "ESPERANDO", "modo": "manual",
                         "frames_acumulados": 0}
        assert_paridad(prediccion, predictor, frames)

    def test_secuencia_manual_corta_se_predice_con_aviso(self, ws):
        ws.send_json({"type": "manual_start"})
        ws.receive_json()
        enviar(ws, generar_frames(5, seed=15))
        recibir(ws, 5)
        ws.send_json({"type": "manual_stop"})
        prediccion, _ = recibir(ws, 2)
        assert prediccion["aviso"] == "secuencia_corta"
        assert prediccion["frames_recibidos"] == 5

    def test_stop_sin_start_solo_estado(self, ws):
        ws.send_json({"type": "manual_stop"})
        assert ws.receive_json()["type"] == "estado"
        assert_sin_mensajes_pendientes(ws)

    def test_frames_en_manual_sin_grabar_se_ignoran(self, ws):
        ws.send_json({"type": "config", "modo": "manual"})
        assert ws.receive_json()["modo"] == "manual"
        enviar(ws, generar_frames(5, seed=16))
        assert_sin_mensajes_pendientes(ws)

    def test_reset_descarta_la_grabacion(self, ws):
        ws.send_json({"type": "manual_start"})
        ws.receive_json()
        enviar(ws, generar_frames(4, seed=17))
        recibir(ws, 4)
        ws.send_json({"type": "reset"})
        assert ws.receive_json() == {"type": "estado", "estado": "ESPERANDO", "modo": "manual",
                                     "frames_acumulados": 0}
        ws.send_json({"type": "manual_stop"})  # no hay nada que predecir
        assert ws.receive_json()["type"] == "estado"
        assert_sin_mensajes_pendientes(ws)

    def test_volver_a_auto(self, ws):
        ws.send_json({"type": "manual_start"})
        ws.receive_json()
        ws.send_json({"type": "config", "modo": "auto"})
        assert ws.receive_json() == {"type": "estado", "estado": "ESPERANDO", "modo": "auto",
                                     "frames_acumulados": 0}


# ============================================================ aislamiento / BD
def test_sesiones_aisladas_entre_conexiones(client, ws):
    enviar(ws, generar_frames(FRAMES_INICIO, seed=18))
    assert ws.receive_json()["estado"] == "GRABANDO"
    with client.websocket_connect("/ws/recognize", headers={"origin": ORIGEN_OK}) as otra:
        assert otra.receive_json()["estado"] == "ESPERANDO"


def test_ws_persiste_solo_autenticado_con_flag(client, usuario, db_sync):
    def flujo(conexion):
        enviar(conexion, generar_frames(15, seed=19))
        recibir(conexion, 15 - FRAMES_INICIO + 1)
        enviar(conexion, generar_frames(FRAMES_FIN, seed=20, manos=False))
        recibir(conexion, FRAMES_FIN - 1)
        prediccion, _ = recibir(conexion, 2)
        return prediccion

    with client.websocket_connect("/ws/recognize", headers={"origin": ORIGEN_OK}) as anonimo:
        anonimo.receive_json()
        anonimo.send_json({"type": "config", "umbral": 0.0, "save_history": True})
        anonimo.receive_json()
        assert flujo(anonimo)["guardado_en_historial"] is False
    assert contar_historial(db_sync) == 0

    with client.websocket_connect("/ws/recognize", headers={"origin": ORIGEN_OK}) as autenticado:
        autenticado.receive_json()
        autenticado.send_json({"type": "auth", "token": usuario["token"]})
        assert autenticado.receive_json() == {"type": "auth", "ok": True}
        autenticado.send_json({"type": "config", "umbral": 0.0, "save_history": True})
        autenticado.receive_json()
        assert flujo(autenticado)["guardado_en_historial"] is True
    assert contar_historial(db_sync, usuario["id"]) == 1


# ================================================== unitarios del segmentador
def test_unitario_tope_manual():
    sesion = SesionReconocimiento(umbral=0.55)
    sesion.manual_start()
    frame = generar_frames(1, seed=21)[0]
    eventos = []
    for _ in range(MAX_FRAMES_MANUAL):
        eventos = sesion.procesar_frame(frame)
    assert eventos[0].tipo == "secuencia"
    assert eventos[0].aviso == "tope_manual"
    assert eventos[0].n_frames == MAX_FRAMES_MANUAL
    assert sesion.estado == "ESPERANDO"


def test_unitario_fin_exacto_y_umbral_ruido():
    sesion = SesionReconocimiento(umbral=0.55)
    manos = generar_frames(MIN_FRAMES_SENA, seed=22)
    sin = generar_frames(FRAMES_FIN, seed=23, manos=False)
    eventos = [e for f in np.vstack([manos, sin]) for e in sesion.procesar_frame(f)]
    secuencias = [e for e in eventos if e.tipo == "secuencia"]
    assert len(secuencias) == 1
    assert secuencias[0].n_frames == MIN_FRAMES_SENA  # justo en el mínimo: no es ruido
    np.testing.assert_array_equal(np.stack(secuencias[0].frames), manos)
