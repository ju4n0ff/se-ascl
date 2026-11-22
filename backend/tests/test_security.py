"""Seguridad y abuso: auth/JWT, anti-BOLA/IDOR, validación numérica, anti-DoS,
cabeceras, CORS, handler 500 y WebSocket (anti-CSWSH, 1009, 1001, límites)."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import rate_limit as rate_limit_mod
from app.core.middleware import BodySizeLimitMiddleware
from app.core.rate_limit import RateLimiter
from app.routes.ws import conexiones_ws
from utils import (
    ORIGEN_OK,
    auth,
    existe_historial,
    generar_frames,
    insertar_historial,
    registrar,
)

URL_WS = "/ws/recognize"
TEST_SECRET_KEY = os.environ["SECRET_KEY"]  # fijada por conftest, nunca la de .env
INT4_MAX = 2_147_483_647


def ws_ok(client: TestClient, origen: str | None = ORIGEN_OK):
    headers = {"origin": origen} if origen else {}
    return client.websocket_connect(URL_WS, headers=headers)


def _b64(datos: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(datos).encode()).rstrip(b"=").decode()


def _claims(user_id: int, **cambios) -> dict:
    ahora = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=5),
        "jti": "abc123",
        "type": "access",
    }
    claims.update(cambios)
    return {k: v for k, v in claims.items() if v is not None}


# ========================================================================= AUTH
class TestRegistro:
    @pytest.mark.parametrize(
        "password",
        ["1234", "corta1A", "sinmayuscula1", "SINMINUSCULA1", "SinDigitosAqui", "x" * 129 + "A1"],
    )
    def test_password_debil_rechazada(self, client, password):
        r = client.post(
            "/api/auth/register",
            json={"username": "debil_user", "email": "d@example.com", "password": password},
        )
        assert r.status_code == 422
        assert password not in r.text  # el 422 no refleja el input

    def test_password_fuerte_aceptada_sin_filtrar_hash(self, client):
        r = client.post(
            "/api/auth/register",
            json={"username": "fuerte_user", "email": "Fuerte@Example.COM", "password": "Fuerte1234"},
        )
        assert r.status_code == 201
        cuerpo = r.json()
        assert set(cuerpo) == {"id", "username", "email"}
        assert cuerpo["email"] == "fuerte@example.com"

    @pytest.mark.parametrize(
        "cambio",
        [
            {"username": "<script>"},
            {"username": "ab"},
            {"username": "a b c"},
            {"email": "no-es-email"},
            {"is_admin": True},  # mass assignment
        ],
    )
    def test_datos_invalidos_o_campos_extra(self, client, cambio):
        payload = {"username": "valido_user", "email": "v@example.com", "password": "Valido1234"}
        payload.update(cambio)
        assert client.post("/api/auth/register", json=payload).status_code == 422

    def test_duplicados_devuelven_el_mismo_409(self, client):
        registrar(client, "dup_user")
        por_username = client.post(
            "/api/auth/register",
            json={"username": "dup_user", "email": "otro@example.com", "password": "Valido1234"},
        )
        por_email = client.post(
            "/api/auth/register",
            json={"username": "otro_user", "email": "dup_user@example.com", "password": "Valido1234"},
        )
        assert por_username.status_code == por_email.status_code == 409
        assert por_username.json() == por_email.json()


class TestLogin:
    def test_login_invalido_generico(self, client):
        registrar(client, "login_user")
        mala = client.post("/api/auth/login", json={"username": "login_user", "password": "Mala12345"})
        inexistente = client.post(
            "/api/auth/login", json={"username": "no_existe", "password": "Mala12345"}
        )
        assert mala.status_code == inexistente.status_code == 401
        assert mala.json() == inexistente.json() == {"detail": "Credenciales inválidas"}
        assert mala.headers["www-authenticate"] == "Bearer"

    def test_login_campos_extra_rechazados(self, client):
        r = client.post(
            "/api/auth/login", json={"username": "x", "password": "y", "role": "admin"}
        )
        assert r.status_code == 422

    def test_token_trae_claims_obligatorios(self, client, usuario):
        payload = jwt.decode(usuario["token"], TEST_SECRET_KEY, algorithms=["HS256"])
        assert {"sub", "exp", "iat", "jti", "type"} <= set(payload)
        assert payload["type"] == "access"
        assert payload["sub"] == str(usuario["id"])


class TestJWT:
    @pytest.mark.parametrize("ruta", ["/api/history/me", "/api/history/1"])
    def test_rutas_protegidas_sin_token(self, client, ruta):
        r = client.get(ruta)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"

    def test_delete_sin_token(self, client):
        assert client.delete("/api/history/1").status_code == 401

    @pytest.mark.parametrize(
        "caso",
        ["alg_none", "otra_clave", "tipo_refresh", "sin_jti", "expirado", "hs512", "basura",
         "usuario_inexistente", "sub_no_numerico"],
    )
    def test_tokens_manipulados(self, client, usuario, caso):
        uid = usuario["id"]
        if caso == "alg_none":
            token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_claims(uid, iat=0, exp=4102444800))}."
        elif caso == "otra_clave":
            token = jwt.encode(_claims(uid), "otra-clave-" * 4, algorithm="HS256")
        elif caso == "tipo_refresh":
            token = jwt.encode(_claims(uid, type="refresh"), TEST_SECRET_KEY, algorithm="HS256")
        elif caso == "sin_jti":
            token = jwt.encode(_claims(uid, jti=None), TEST_SECRET_KEY, algorithm="HS256")
        elif caso == "expirado":
            pasado = datetime.now(UTC) - timedelta(hours=2)
            token = jwt.encode(
                _claims(uid, iat=pasado, exp=pasado + timedelta(minutes=1)),
                TEST_SECRET_KEY, algorithm="HS256",
            )
        elif caso == "hs512":
            token = jwt.encode(_claims(uid), TEST_SECRET_KEY, algorithm="HS512")
        elif caso == "basura":
            token = "no.es.un-jwt"
        elif caso == "usuario_inexistente":
            token = jwt.encode(_claims(999_999), TEST_SECRET_KEY, algorithm="HS256")
        else:
            token = jwt.encode(_claims(uid, sub="admin"), TEST_SECRET_KEY, algorithm="HS256")
        assert client.get("/api/history/me", headers=auth(token)).status_code == 401

    def test_token_invalido_en_recognize_es_401(self, client):
        r = client.post(
            "/api/recognize",
            json={"frames": generar_frames(12).tolist(), "save_history": True},
            headers=auth("token-invalido"),
        )
        assert r.status_code == 401


# =================================================================== BOLA / IDOR
class TestBOLA:
    def test_get_historial_ajeno_403(self, client, dos_usuarios):
        a, b = dos_usuarios
        r = client.get(f"/api/history/{b['id']}", headers=auth(a["token"]))
        assert r.status_code == 403

    def test_get_historial_propio_200(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        insertar_historial(db_sync, a["id"], "hola")
        insertar_historial(db_sync, b["id"], "gracias")
        propio = client.get(f"/api/history/{a['id']}", headers=auth(a["token"])).json()
        me = client.get("/api/history/me", headers=auth(a["token"])).json()
        assert [e["predicted_label"] for e in propio] == ["hola"]
        assert propio == me
        assert all(e["user_id"] == a["id"] for e in me)

    def test_delete_entrada_ajena_404_y_sigue_existiendo(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        entrada_b = insertar_historial(db_sync, b["id"])
        r = client.delete(f"/api/history/{entrada_b}", headers=auth(a["token"]))
        assert r.status_code == 404
        assert existe_historial(db_sync, entrada_b)

    def test_delete_inexistente_y_ajena_son_indistinguibles(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        entrada_b = insertar_historial(db_sync, b["id"])
        ajena = client.delete(f"/api/history/{entrada_b}", headers=auth(a["token"]))
        inexistente = client.delete("/api/history/987654", headers=auth(a["token"]))
        assert ajena.status_code == inexistente.status_code == 404
        assert ajena.json() == inexistente.json()

    def test_delete_entrada_propia_204(self, client, usuario, db_sync):
        entrada = insertar_historial(db_sync, usuario["id"])
        r = client.delete(f"/api/history/{entrada}", headers=auth(usuario["token"]))
        assert r.status_code == 204
        assert not existe_historial(db_sync, entrada)

    @pytest.mark.parametrize("valor", [0, -1, INT4_MAX + 1, "abc"])
    def test_ids_fuera_de_rango_422(self, client, usuario, valor):
        h = auth(usuario["token"])
        assert client.get(f"/api/history/{valor}", headers=h).status_code == 422
        assert client.delete(f"/api/history/{valor}", headers=h).status_code == 422


# ======================================================== validación numérica
def _cuerpo_json_crudo(frames_txt: list[str]) -> bytes:
    return ('{"frames": [' + ",".join(frames_txt) + "]}").encode()


def _frame_txt(valores: list[str]) -> str:
    return "[" + ",".join(valores) + "]"


class TestValidacionNumerica:
    @pytest.mark.parametrize("token_invalido", ["NaN", "Infinity", "-Infinity"])
    def test_no_finitos_json_422_sin_eco(self, client, token_invalido):
        base = ["0.5"] * 1629
        malo = base.copy()
        malo[1600] = token_invalido
        cuerpo = _cuerpo_json_crudo([_frame_txt(base)] * 11 + [_frame_txt(malo)])
        r = client.post(
            "/api/recognize", content=cuerpo, headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 422
        assert "input" not in r.json()["detail"][0]
        assert len(r.content) < 4000  # no devuelve los 1629 floats
        assert r.json()["request_id"]

    @pytest.mark.parametrize(
        ("n_frames", "largo"), [(12, 1628), (12, 1630), (5, 1629), (0, 1629)]
    )
    def test_forma_invalida_422(self, client, n_frames, largo):
        frames = np.full((n_frames, largo), 0.5).tolist()
        assert client.post("/api/recognize", json={"frames": frames}).status_code == 422

    def test_601_frames_json_422(self, client):
        # Enteros (0) para que 601 frames quepan bajo los 5 MB y se pruebe el 422, no el 413.
        cuerpo = _cuerpo_json_crudo([_frame_txt(["0"] * 1629)] * 601)
        assert len(cuerpo) < 5 * 1024 * 1024
        r = client.post(
            "/api/recognize", content=cuerpo, headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 422

    def test_strings_no_se_convierten_a_float(self, client):
        frames = [["0.1"] * 1629] * 12
        assert client.post("/api/recognize", json={"frames": frames}).status_code == 422

    def test_desborde_float32_422(self, client):
        frames = generar_frames(12).astype(np.float64)
        frames[3, 10] = 1e300  # finito en float64, inf en float32
        r = client.post("/api/recognize", json={"frames": frames.tolist()})
        assert r.status_code == 422

    @pytest.mark.parametrize("campo", [{"top_k": 0}, {"top_k": 6}, {"mode": "otro"}, {"extra": 1}])
    def test_parametros_invalidos_422(self, client, campo):
        payload = {"frames": generar_frames(12).tolist(), **campo}
        assert client.post("/api/recognize", json=payload).status_code == 422

    def test_binario_con_nan_422(self, client):
        frames = generar_frames(12)
        frames[0, 0] = np.nan
        r = client.post(
            "/api/recognize", content=frames.tobytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("n_bytes", [0, 6515, 6516 * 12 + 1, 6516 * 5, 6516 * 601])
    def test_binario_mal_formado_422(self, client, n_bytes):
        r = client.post(
            "/api/recognize", content=b"\x00" * n_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 422

    def test_content_type_no_soportado_415(self, client):
        r = client.post("/api/recognize", content=b"hola", headers={"Content-Type": "text/plain"})
        assert r.status_code == 415

    def test_modo_estatico_sin_modelo_503(self, client):
        payload = {"frames": generar_frames(12).tolist(), "mode": "static"}
        assert client.post("/api/recognize", json=payload).status_code == 503


# ==================================================================== anti-DoS
class TestLimites:
    def test_413_por_content_length(self, client, settings):
        r = client.post(
            "/api/recognize",
            content=b"0" * (settings.max_body_bytes + 1),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
        assert r.headers["x-request-id"]

    def test_413_chunked_sin_content_length(self, client, settings):
        bloque = b"0" * (1024 * 1024)

        def cuerpo():
            for _ in range(settings.max_body_bytes // len(bloque) + 1):
                yield bloque

        r = client.post(
            "/api/recognize", content=cuerpo(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 413

    def test_content_length_invalido_400(self, client):
        # httpx recalcula Content-Length; se prueba el middleware directamente.
        app = BodySizeLimitMiddleware(FastAPI(), max_bytes=1024)
        enviados = _ejecutar_asgi(app, [b"x"], headers=[(b"content-length", b"-5")])
        assert enviados[0]["status"] == 400

    async def test_middleware_cuenta_bytes_en_streaming(self):
        """Chunked real (varios mensajes ``http.request``): corta al superar el tope."""
        mini = FastAPI()

        @mini.post("/eco")
        async def eco(request: Request) -> dict:
            return {"n": len(await request.body())}

        app = BodySizeLimitMiddleware(mini, max_bytes=5000)
        trozos = [b"a" * 2000] * 4  # 8000 bytes en 4 mensajes, sin Content-Length
        enviados, pendientes = await _ejecutar_asgi_async(app, trozos, headers=[])
        assert enviados[0]["status"] == 413
        assert pendientes == 0  # drenó el resto del cuerpo sin bufferizarlo

        enviados, _ = await _ejecutar_asgi_async(app, [b"a" * 2000] * 2, headers=[])
        assert enviados[0]["status"] == 200

    def test_429_login(self, client, settings):
        codigos = [
            client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code
            for _ in range(settings.rate_limit_login_per_min + 1)
        ]
        assert codigos[:-1] == [401] * settings.rate_limit_login_per_min
        assert codigos[-1] == 429

    def test_429_trae_retry_after(self, client, settings):
        for _ in range(settings.rate_limit_login_per_min):
            client.post("/api/auth/login", json={"username": "x", "password": "y"})
        r = client.post("/api/auth/login", json={"username": "x", "password": "y"})
        assert r.status_code == 429
        assert 1 <= int(r.headers["retry-after"]) <= 60

    def test_429_registro(self, client, settings):
        codigos = [
            client.post("/api/auth/register", json={}).status_code
            for _ in range(settings.rate_limit_register_per_min + 1)
        ]
        assert codigos[-1] == 429

    def test_429_recognize(self, client, settings):
        codigos = [
            client.post("/api/recognize", json={}).status_code
            for _ in range(settings.rate_limit_recognize_per_min + 1)
        ]
        assert codigos[:-1] == [422] * settings.rate_limit_recognize_per_min
        assert codigos[-1] == 429


class TestRateLimiterUnitario:
    def test_ventana_y_reset(self):
        rl = RateLimiter()
        assert [rl.hit("k", 2)[0] for _ in range(3)] == [True, True, False]
        rl.reset()
        assert rl.hit("k", 2)[0] is True

    def test_expira_por_ventana(self, monkeypatch):
        # Reloj simulado: en Windows time.monotonic avanza en pasos de ~15.6 ms.
        reloj = [1000.0]
        monkeypatch.setattr(rate_limit_mod, "time", SimpleNamespace(monotonic=lambda: reloj[0]))
        rl = RateLimiter()
        assert rl.hit("k", 1, ventana=60)[0]
        reloj[0] += 30
        permitido, reintento = rl.hit("k", 1, ventana=60)
        assert not permitido and reintento == 30
        reloj[0] += 30
        assert rl.hit("k", 1, ventana=60)[0]

    def test_purga_entradas_expiradas(self, monkeypatch):
        reloj = [1000.0]
        monkeypatch.setattr(rate_limit_mod, "time", SimpleNamespace(monotonic=lambda: reloj[0]))
        rl = RateLimiter(intervalo_purga_s=60)
        for i in range(50):
            rl.hit(f"ip-{i}", 5)
        assert len(rl) == 50
        reloj[0] += 61
        rl.hit("nueva", 5)
        assert len(rl) == 1

    def test_purga_y_tope_de_claves(self):
        rl = RateLimiter(max_claves=100)
        for i in range(500):
            rl.hit(f"ip-{i}", 5)
        assert len(rl) <= 101


def _mensajes_cuerpo(trozos: list[bytes]):
    cola = [
        {"type": "http.request", "body": t, "more_body": i < len(trozos) - 1}
        for i, t in enumerate(trozos)
    ]
    return cola


async def _ejecutar_asgi_async(app, trozos, headers):
    cola = _mensajes_cuerpo(trozos)
    enviados: list[dict] = []

    async def receive():
        return cola.pop(0) if cola else {"type": "http.disconnect"}

    async def send(mensaje):
        enviados.append(mensaje)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/eco", "raw_path": b"/eco", "query_string": b"",
        "headers": headers, "client": ("127.0.0.1", 1), "server": ("test", 80),
    }
    await app(scope, receive, send)
    return [m for m in enviados if m["type"] == "http.response.start"], len(cola)


def _ejecutar_asgi(app, trozos, headers):
    import asyncio

    enviados, _ = asyncio.run(_ejecutar_asgi_async(app, trozos, headers))
    return enviados


# ============================================================ cabeceras / CORS
class TestCabeceras:
    CABECERAS = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "permissions-policy": "camera=(self), microphone=(), geolocation=()",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    }

    @pytest.mark.parametrize("ruta", ["/api/health", "/api/clases", "/api/history/me", "/no-existe"])
    def test_cabeceras_de_seguridad(self, client, ruta):
        r = client.get(ruta)
        for clave, valor in self.CABECERAS.items():
            assert r.headers.get(clave) == valor, clave
        assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])
        assert "strict-transport-security" not in r.headers  # solo con DEBUG=false

    def test_no_store_en_auth_e_historial(self, client):
        for r in (
            client.post("/api/auth/login", json={"username": "x", "password": "y"}),
            client.get("/api/history/me"),
        ):
            assert r.headers["cache-control"] == "no-store"

    def test_cors_origen_permitido_sin_credenciales(self, client):
        r = client.options(
            "/api/recognize",
            headers={"Origin": ORIGEN_OK, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization,content-type"},
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == ORIGEN_OK
        assert "access-control-allow-credentials" not in r.headers

    def test_cors_origen_malicioso(self, client):
        r = client.options(
            "/api/recognize",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in r.headers
        r = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers


# ================================================================= handler 500
class TestHandler500:
    def test_500_devuelve_request_id_sin_traceback(self, app, predictor, monkeypatch, caplog):
        secreto = "SELECT password_hash FROM users -- C:\\ruta\\interna\\secreta.py"

        def falla_controlada():
            raise RuntimeError(secreto)

        monkeypatch.setattr(predictor, "clases", falla_controlada)
        cliente = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.ERROR, logger="app.core.exceptions"):
            r = cliente.get("/api/clases")

        assert r.status_code == 500
        cuerpo = r.json()
        assert set(cuerpo) == {"detail", "request_id"}
        assert cuerpo["detail"] == "Error interno del servidor"
        assert re.fullmatch(r"[0-9a-f]{32}", cuerpo["request_id"])
        assert r.headers["x-request-id"] == cuerpo["request_id"]
        for fuga in ("Traceback", "RuntimeError", "password_hash", "secreta.py", 'File "'):
            assert fuga not in r.text
        assert r.headers["x-content-type-options"] == "nosniff"
        # El detalle queda solo en el log del servidor, correlacionado por request_id.
        registro = [rec for rec in caplog.records if cuerpo["request_id"] in rec.getMessage()]
        assert registro and registro[0].exc_info is not None


# =================================================================== WebSocket
class TestWebSocketSeguridad:
    def test_origin_malicioso_rechazado_1008(self, client):
        with pytest.raises(WebSocketDisconnect) as exc, ws_ok(client, "https://evil.example"):
            pass
        assert exc.value.code == 1008

    def test_origin_permitido_acepta(self, client):
        with ws_ok(client) as ws:
            assert ws.receive_json()["type"] == "estado"

    def test_sin_origin_solo_en_debug(self, client, settings, monkeypatch):
        with ws_ok(client, origen=None) as ws:  # DEBUG=true en tests
            assert ws.receive_json()["type"] == "estado"
        monkeypatch.setattr(settings, "debug", False)
        with pytest.raises(WebSocketDisconnect) as exc, ws_ok(client, origen=None):
            pass
        assert exc.value.code == 1008

    def test_mensaje_gigante_1009(self, client, settings):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_text("x" * (settings.ws_max_message_bytes + 1))
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 1009

    def test_binario_gigante_1009(self, client, settings):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x00" * (settings.ws_max_message_bytes + 1))
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 1009

    def test_frame_json_sin_redondear_cabe_en_48kb(self, client):
        frame = [0.12345678901234567] * 1629  # ~32 KB en JSON
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_json({"type": "manual_start"})
            ws.receive_json()
            ws.send_json({"type": "frame", "data": frame})
            assert ws.receive_json()["frames_acumulados"] == 1

    def test_inactividad_1001(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "ws_idle_timeout_s", 0.3)
        with ws_ok(client) as ws:
            ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 1001

    @pytest.mark.parametrize(
        "mensaje",
        [
            {"type": "frame", "data": [0.5] * 1628},
            {"type": "frame", "data": [0.5] * 1628 + ["0.5"]},
            {"type": "frame", "data": [0.5] * 1628 + [1e300]},
            {"type": "frame", "data": "no-es-lista"},
            {"type": "config", "umbral": 2.0},
            {"type": "desconocido"},
        ],
    )
    def test_mensajes_invalidos_error_controlado(self, client, mensaje):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_json(mensaje)
            respuesta = ws.receive_json()
            assert respuesta["type"] == "error"
            assert respuesta["codigo"] == "mensaje_invalido"
            ws.send_json({"type": "reset"})  # la conexión sigue viva
            assert ws.receive_json()["type"] == "estado"

    @pytest.mark.parametrize("crudo", ["{no json", "[1, 2, 3]", "NaN"])
    def test_texto_no_objeto(self, client, crudo):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_text(crudo)
            assert ws.receive_json()["codigo"] == "mensaje_invalido"

    @pytest.mark.parametrize("valor", [np.nan, np.inf])
    def test_binario_no_finito(self, client, valor):
        frame = generar_frames(1)[0]
        frame[5] = valor
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_bytes(frame.astype("<f4").tobytes())
            assert ws.receive_json()["codigo"] == "mensaje_invalido"
            ws.send_bytes(b"\x00" * 100)  # tamaño incorrecto
            assert ws.receive_json()["codigo"] == "mensaje_invalido"

    def test_tope_de_conexiones_por_ip(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "ws_max_connections_per_ip", 2)
        with ws_ok(client) as ws1, ws_ok(client) as ws2:
            ws1.receive_json()
            ws2.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc, ws_ok(client):
                pass
            assert exc.value.code == 1008
        # Al cerrar se liberan los cupos.
        with ws_ok(client) as ws3:
            assert ws3.receive_json()["type"] == "estado"
        assert conexiones_ws.activas("testclient") == 0

    def test_rate_limit_de_mensajes(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "ws_max_messages_per_sec", 5)
        with ws_ok(client) as ws:
            ws.receive_json()
            for _ in range(10):
                ws.send_json({"type": "reset"})
            respuestas = [ws.receive_json() for _ in range(6)]
        assert [m["type"] for m in respuestas[:5]] == ["estado"] * 5
        assert respuestas[5] == {
            "type": "error", "codigo": "rate_limit", "detalle": "Máximo 5 mensajes/s"
        }

    @pytest.mark.parametrize("token", ["token-invalido", "", "x" * 5000, 123])
    def test_auth_ws_invalida(self, client, token):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_json({"type": "auth", "token": token})
            assert ws.receive_json() == {
                "type": "error", "codigo": "auth_invalida", "detalle": "Token inválido"
            }

    def test_auth_ws_valida(self, client, usuario):
        with ws_ok(client) as ws:
            ws.receive_json()
            ws.send_json({"type": "auth", "token": usuario["token"]})
            assert ws.receive_json() == {"type": "auth", "ok": True}
