"""Despliegue cloud: Supabase (URL, SSL, pooler, RLS), Render (proxy, blueprint) y Vercel (CORS/WS).

Nada aquí se conecta a Supabase: las URL remotas solo se analizan. Las pruebas con base
usan ``signia_test`` local y revierten cualquier DDL.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from conftest import TEST_DATABASE_URL, es_servidor_local
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.datastructures import Headers
from starlette.websockets import WebSocketDisconnect

from app.core import network, security
from app.core.config import Settings
from app.core.db_url import nombre_sentencia
from app.core.network import obtener_ip_cliente
from app.core.rate_limit import rate_limiter
from app.db.session import opciones_motor
from app.main import opciones_cors
from app.routes.ws import conexiones_ws, origen_permitido

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAIZ = BACKEND_DIR.parent
SECRET_FUERTE = "Pr0d-" + "x9Y8w7V6u5T4s3R2q1P0-" * 3
CLAVE = "Cl4ve%40Fict1cia"  # contraseña ficticia codificada ("@" -> %40)

LOCAL = "postgresql+asyncpg://user:password@localhost:5432/signia"
POOLER_TX = f"postgresql://postgres.abcref:{CLAVE}@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
POOLER_SESION = POOLER_TX.replace(":6543", ":5432")
DIRECTA = f"postgresql://postgres:{CLAVE}@db.abcref.supabase.co:5432/postgres"


def _settings(**kwargs) -> Settings:
    """Settings sin ``.env``; SSL y pooler en automático salvo que el test los fije."""
    base = {"secret_key": SECRET_FUERTE, "debug": False, "db_ssl": None, "db_use_pgbouncer": None}
    return Settings(_env_file=None, **{**base, **kwargs})


# ======================================================== DATABASE_URL y connect_args
class TestDatabaseUrl:
    @pytest.mark.parametrize(
        "esquema",
        ["postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg2", "postgresql+psycopg"],
    )
    def test_normaliza_el_driver(self, esquema):
        cfg = _settings(
            database_url=f"{esquema}://u:{CLAVE}@localhost:5432/signia",
            database_url_sync=f"{esquema}://u:{CLAVE}@localhost:5432/signia",
        )
        url = make_url(cfg.database_url)
        assert url.drivername == "postgresql+asyncpg"
        assert url.password == "Cl4ve@Fict1cia"  # no se pierde ni se recodifica mal
        assert make_url(cfg.database_url_sync).drivername == "postgresql+psycopg2"

    @pytest.mark.parametrize(
        "query",
        ["sslmode=require", "ssl=require", "ssl=true", "pgbouncer=true&sslmode=require&connection_limit=1"],
    )
    def test_limpia_parametros_que_asyncpg_rechaza(self, query):
        cfg = _settings(database_url=f"{LOCAL}?{query}")
        assert not make_url(cfg.database_url).query
        assert cfg.db_connect_args["ssl"] == "require"

    def test_conserva_los_demas_parametros(self):
        cfg = _settings(database_url=f"{LOCAL}?sslmode=require&command_timeout=5")
        assert dict(make_url(cfg.database_url).query) == {"command_timeout": "5"}

    def test_local_queda_sin_ssl_ni_ajustes_de_pooler(self):
        cfg = _settings(database_url=LOCAL)
        assert cfg.database_url == LOCAL
        assert cfg.db_connect_args == {}

    def test_url_de_tests_sin_cambios(self, settings):
        assert settings.database_url == TEST_DATABASE_URL
        assert settings.db_connect_args == {}

    @pytest.mark.parametrize(
        ("url", "ssl_on", "pooler"),
        [
            (LOCAL, False, False),
            (POOLER_TX, True, True),
            (POOLER_SESION, True, True),
            (DIRECTA, True, False),
            (POOLER_TX.upper().replace("POSTGRESQL://", "postgresql://"), True, True),
            ("postgresql://u:p@localhost:6543/db", False, True),
            ("postgresql://u:p@localhost/db?pgbouncer=true", False, True),
            ("postgresql://u:p@db.supabase.com.evil.example/db", False, False),
            ("postgresql://u:p@notsupabase.co/db", False, False),
        ],
    )
    def test_autodeteccion(self, url, ssl_on, pooler):
        cfg = _settings(database_url=url)
        assert (cfg.usar_ssl, cfg.usar_pgbouncer) == (ssl_on, pooler)

    def test_connect_args_de_supabase_pooler(self):
        args = _settings(database_url=POOLER_TX).db_connect_args
        assert args["ssl"] == "require"
        assert args["statement_cache_size"] == 0
        assert args["prepared_statement_cache_size"] == 0
        assert args["prepared_statement_name_func"] is nombre_sentencia

    def test_variables_explicitas_ganan(self):
        cfg = _settings(database_url=POOLER_TX, db_ssl=False, db_use_pgbouncer=False)
        assert cfg.db_connect_args == {}
        cfg = _settings(database_url=LOCAL, db_ssl=True, db_use_pgbouncer=True)
        assert cfg.db_connect_args["ssl"] == "require"
        assert cfg.db_connect_args["statement_cache_size"] == 0

    def test_variables_vacias_son_automaticas(self):
        cfg = _settings(database_url=DIRECTA, db_ssl="", db_use_pgbouncer=" ", db_ssl_root_cert="")
        assert cfg.db_ssl is None and cfg.db_use_pgbouncer is None and cfg.db_ssl_root_cert is None
        assert cfg.usar_ssl is True

    def test_ssl_desactivado_hacia_supabase_avisa(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            _settings(database_url=POOLER_TX, db_ssl=False)
        assert any("Supabase" in r.getMessage() for r in caplog.records)
        assert "Cl4ve" not in caplog.text

    @pytest.mark.parametrize("modo", ["verify-full", "verify-ca"])
    def test_verify_no_se_degrada_a_require(self, modo):
        ctx = _settings(database_url=f"{DIRECTA}?sslmode={modo}").db_connect_args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode is ssl.CERT_REQUIRED and ctx.check_hostname

    def test_ca_propia_verifica_certificado_y_hostname(self, monkeypatch, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_text("ficticio")
        pedidos: list[str] = []
        real = ssl.create_default_context

        def falso(cafile=None):
            pedidos.append(cafile)
            return real()

        monkeypatch.setattr(ssl, "create_default_context", falso)
        ctx = _settings(database_url=POOLER_TX, db_ssl_root_cert=ca).db_connect_args["ssl"]
        assert pedidos == [str(ca)]
        assert ctx.verify_mode is ssl.CERT_REQUIRED and ctx.check_hostname

    def test_ca_inexistente_aborta(self, tmp_path):
        with pytest.raises(ValidationError, match="DB_SSL_ROOT_CERT"):
            _settings(db_ssl_root_cert=tmp_path / "no-existe.crt")

    @pytest.mark.parametrize(
        "url",
        [
            f"mysql://u:{CLAVE}@h/db",
            f"postgresql://u:{CLAVE}@h:puerto/db",
            f"{CLAVE}",
            f"postgresql://u:{CLAVE}@h/db?sslmode=inventado",
            f"postgresql://u:{CLAVE}@h/db?sslmode=verify-full&sslrootcert=/tmp/x",
        ],
    )
    def test_url_invalida_no_filtra_la_clave(self, url):
        with pytest.raises(ValidationError) as exc:
            _settings(database_url=url)
        assert "Cl4ve" not in str(exc.value)

    def test_errores_de_settings_no_vuelcan_secretos(self):
        with pytest.raises(ValidationError) as exc:
            _settings(database_url=POOLER_TX, allowed_origins="*")
        assert "Cl4ve" not in str(exc.value) and SECRET_FUERTE not in str(exc.value)

    def test_url_sync_conserva_sslmode(self):
        cfg = _settings(database_url_sync=f"{DIRECTA}?sslmode=verify-full&pgbouncer=true")
        assert dict(make_url(cfg.database_url_sync).query) == {"sslmode": "verify-full"}
        assert dict(make_url(_settings(database_url_sync=DIRECTA).database_url_sync).query) == {
            "sslmode": "require"
        }

    def test_opciones_del_motor(self):
        op = opciones_motor(_settings(database_url=POOLER_TX, db_pool_size=3, db_max_overflow=0))
        assert op["echo"] is False and op["pool_pre_ping"] is True
        assert (op["pool_recycle"], op["pool_size"], op["max_overflow"]) == (300, 3, 0)
        # El dialecto debe aceptar los argumentos (si no, falla al crear el motor).
        motor = create_async_engine(_settings(database_url=POOLER_TX).database_url, **op)
        assert motor.url.host.endswith(".pooler.supabase.com")

    @pytest.mark.parametrize(
        "campo", [{"db_pool_size": 0}, {"db_max_overflow": -1}, {"trust_proxy_hops": 6},
                  {"trust_proxy_hops": -1}, {"max_concurrent_hashes": 0}],
    )
    def test_rangos(self, campo):
        with pytest.raises(ValidationError):
            _settings(**campo)


class TestModoPooler:
    """Los ``connect_args`` de PgBouncer funcionan con el asyncpg instalado (base local)."""

    @staticmethod
    async def _sentencias(connect_args: dict) -> list[str]:
        motor = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, connect_args=connect_args)
        try:
            async with motor.connect() as conn:
                for i in range(3):
                    fila = await conn.execute(text("SELECT CAST(:v AS INTEGER)"), {"v": i})
                    assert fila.scalar_one() == i
                filas = await conn.execute(text("SELECT name FROM pg_prepared_statements"))
                return [f[0] for f in filas]
        finally:
            await motor.dispose()

    async def test_nombres_unicos_entre_conexiones(self):
        args = _settings(database_url=LOCAL, db_use_pgbouncer=True).db_connect_args
        a, b = await self._sentencias(args), await self._sentencias(args)
        assert a and b and not set(a) & set(b)
        assert all(re.fullmatch(r"__asyncpg_[0-9a-f]{32}__", n) for n in a + b)

    async def test_sin_name_func_los_nombres_son_secuenciales(self):
        """Con los cachés en 0 no basta: el contador reinicia por proceso y puede chocar."""
        args = {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
        nombres = await self._sentencias(args)
        assert nombres and all(re.fullmatch(r"__asyncpg_stmt_[0-9a-f]+__", n) for n in nombres)


# ================================================================ guarda de los tests
class TestGuardaBaseLocal:
    @pytest.mark.parametrize(
        "url",
        [
            POOLER_TX,
            DIRECTA,
            "postgresql+asyncpg://u:p@127.0.0.1:6543/signia_test",
            "postgresql+asyncpg://u:p@8.8.8.8:5432/signia_test",
            "postgresql+asyncpg://u:p@db.ejemplo.com:5432/signia_test",
            "postgresql+asyncpg://u:p@127.0.0.1/signia_test?host=db.abcref.supabase.co",
        ],
    )
    def test_rechaza_remotos(self, url):
        assert es_servidor_local(make_url(url)) is False

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "172.20.1.5", "[::1]"])
    def test_acepta_locales(self, host):
        assert es_servidor_local(make_url(f"postgresql+asyncpg://u:p@{host}:5432/signia_test"))

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "url",
        [POOLER_TX.replace("/postgres", "/signia_test"), "postgresql://u:p@127.0.0.1/signia"],
    )
    def test_conftest_aborta(self, url):
        r = subprocess.run(
            [sys.executable, "-c", "import conftest"],
            cwd=BACKEND_DIR / "tests",
            env={**os.environ, "TEST_DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        )
        assert r.returncode != 0
        assert "TEST_DATABASE_URL debe apuntar" in r.stderr


# ==================================================================== IP tras el proxy
class _Conexion:
    def __init__(self, *xff: str, host: str | None = "10.0.0.7") -> None:
        self.client = type("C", (), {"host": host})() if host else None
        self.headers = Headers(raw=[(b"x-forwarded-for", v.encode()) for v in xff])


@pytest.fixture
def saltos(settings, monkeypatch):
    monkeypatch.setattr(network, "_aviso_emitido", False)
    return lambda n: monkeypatch.setattr(settings, "trust_proxy_hops", n)


class TestIpCliente:
    @pytest.mark.parametrize("xff", [(), ("1.2.3.4",), ("1.2.3.4, 203.0.113.9",), ("basura",)])
    def test_cero_saltos_ignora_xff(self, saltos, xff):
        saltos(0)
        assert obtener_ip_cliente(_Conexion(*xff)) == "10.0.0.7"

    def test_sin_cliente(self, saltos):
        saltos(0)
        assert obtener_ip_cliente(_Conexion("1.2.3.4", host=None)) == "desconocida"

    @pytest.mark.parametrize(
        ("n", "xff", "esperada"),
        [
            (1, "203.0.113.9", "203.0.113.9"),
            (1, "1.1.1.1, 203.0.113.9", "203.0.113.9"),  # 1.1.1.1 lo escribió el atacante
            (1, "basura, <script>, 203.0.113.9", "203.0.113.9"),
            (1, "  203.0.113.9  ", "203.0.113.9"),
            (2, "203.0.113.9, 172.71.1.1", "203.0.113.9"),
            (2, "6.6.6.6, 203.0.113.9, 172.71.1.1", "203.0.113.9"),
            (3, "6.6.6.6, 203.0.113.9, 172.71.1.1, 10.1.2.3", "203.0.113.9"),
            (1, "2001:DB8::0001", "2001:db8::1"),
            (1, "::ffff:203.0.113.9", "203.0.113.9"),
        ],
    )
    def test_cuenta_desde_la_derecha(self, saltos, n, xff, esperada):
        saltos(n)
        assert obtener_ip_cliente(_Conexion(xff)) == esperada

    def test_cabeceras_repetidas_se_concatenan(self, saltos):
        saltos(1)
        assert obtener_ip_cliente(_Conexion("1.1.1.1", "203.0.113.9")) == "203.0.113.9"

    @pytest.mark.parametrize(
        ("n", "xff"),
        [
            (1, ()),
            (1, ("",)),
            (1, ("1.1.1.1, no-es-ip",)),
            (1, ("1.1.1.1, 999.1.1.1",)),
            (1, ("203.0.113.9:4433",)),
            (1, ("1.1.1.1,",)),
            (2, ("203.0.113.9",)),  # menos entradas que saltos: no se confía en ninguna
            (2, ("203.0.113.9, basura",)),
        ],
    )
    def test_ausente_o_malformado_usa_la_conexion(self, saltos, n, xff):
        saltos(n)
        assert obtener_ip_cliente(_Conexion(*xff)) == "10.0.0.7"

    def test_avisa_una_vez_si_resuelve_a_ip_interna(self, saltos, caplog):
        saltos(1)
        with caplog.at_level(logging.WARNING, logger="app.core.network"):
            for _ in range(3):
                obtener_ip_cliente(_Conexion("200.1.2.3, 172.71.1.1, 10.1.2.3"))
        avisos = [r.getMessage() for r in caplog.records if "TRUST_PROXY_HOPS" in r.getMessage()]
        assert len(avisos) == 1 and "3 entradas" in avisos[0]
        assert "200.1.2.3" not in caplog.text and "10.1.2.3" not in caplog.text  # sin IPs en el log

    def test_rate_limit_no_se_evade_con_xff(self, client, settings, saltos):
        """``client`` llega como 'testclient': con 0 saltos rotar XFF no sirve de nada."""
        saltos(0)
        self._agotar_login(client, settings, lambda i: f"1.2.3.{i}")

    def test_rate_limit_con_un_salto_resiste_spoofing(self, client, settings, saltos):
        saltos(1)
        self._agotar_login(client, settings, lambda i: f"1.2.3.{i}, 203.0.113.9")
        # Otro cliente real (último salto distinto) conserva su cupo.
        r = client.post(
            "/api/auth/login",
            json={"username": "nadie", "password": "x"},
            headers={"X-Forwarded-For": "203.0.113.9, 203.0.113.10"},
        )
        assert r.status_code == 401

    @staticmethod
    def _agotar_login(client, settings, xff):
        rate_limiter.reset()
        codigos = [
            client.post(
                "/api/auth/login",
                json={"username": "nadie", "password": "x"},
                headers={"X-Forwarded-For": xff(i)},
            ).status_code
            for i in range(settings.rate_limit_login_per_min + 1)
        ]
        assert codigos == [401] * settings.rate_limit_login_per_min + [429]

    def test_tope_ws_usa_la_ip_real(self, client, settings, saltos, monkeypatch):
        saltos(1)
        monkeypatch.setattr(settings, "ws_max_connections_per_ip", 1)

        def conectar(xff):
            return client.websocket_connect(
                "/ws/recognize",
                headers={"origin": "http://localhost:4200", "x-forwarded-for": xff},
            )

        with conectar("1.1.1.1, 203.0.113.9") as ws:
            ws.receive_json()
            assert conexiones_ws.activas("203.0.113.9") == 1
            with pytest.raises(WebSocketDisconnect) as exc, conectar("2.2.2.2, 203.0.113.9"):
                pass
            assert exc.value.code == 1008
            with conectar("1.1.1.1, 203.0.113.10") as otra:
                assert otra.receive_json()["type"] == "estado"


# ============================================================== CORS / Origin (Vercel)
VERCEL = "https://senacl.vercel.app"
PROPIO = "https://www.senacl.cl"
REGEX_OK = r"^https://senacl-[a-z0-9-]+-equipo\.vercel\.app$"


class TestOrigenes:
    def test_lista_con_espacios_y_barra_final(self):
        cfg = _settings(allowed_origins=f" {VERCEL}/ , {PROPIO.upper()} ,, ")
        assert cfg.origins == [VERCEL, PROPIO]

    @pytest.mark.parametrize(
        "origen",
        [
            "*", "https://*.vercel.app", "http://senacl.vercel.app", "http://192.168.1.10:4200",
            "http://localhost.evil.example", "http://localhost@evil.example", "ftp://x",
            "https://", "https://senacl.vercel.app/ruta", "https://senacl.vercel.app?x=1",
            "https://u:p@senacl.vercel.app", "https://a b.cl", "https://a.cl:puerto", "null",
        ],
    )
    def test_invalidos_en_produccion(self, origen):
        with pytest.raises(ValidationError):
            _settings(allowed_origins=f"{VERCEL},{origen}")

    @pytest.mark.parametrize("origen", ["http://localhost:4200", "http://127.0.0.1:4200", "http://[::1]:4200"])
    def test_http_solo_loopback_en_produccion(self, origen):
        """Política: con DEBUG=false se exige https://, salvo loopback (la propia máquina)."""
        assert _settings(allowed_origins=origen).origins == [origen]

    def test_http_de_red_local_solo_en_debug(self):
        assert _settings(allowed_origins="http://192.168.1.10:4200", debug=True).origins

    @pytest.mark.parametrize(
        "patron",
        [
            REGEX_OK,
            r"https://senacl-[a-z0-9]{9}-equipo\.vercel\.app",
            r"^https://[a-z0-9-]+\.preview\.senacl\.cl$",
            r"^https://[a-z0-9-]+\.senacl\.cl$",
            r"^https://senacl\.vercel\.app$",
            "",
        ],
    )
    def test_regex_cerrado_aceptado(self, patron):
        assert _settings(allowed_origin_regex=patron).allowed_origin_regex == patron

    @pytest.mark.parametrize(
        "patron",
        [
            ".*", ".+", "^.*$", r"^https?://.*", "https://.*", r"https://.*\.vercel\.app",
            r"^https://[a-z0-9-]+\.vercel\.app$",  # cualquier cuenta de Vercel
            r"^https://senacl-[a-z0-9-]+\.vercel\.app$",  # cualquiera puede crear "senacl-x"
            r"^https://[a-z0-9-]+-equipo\.vercel\.app$",
            r"^https://-[a-z0-9-]+-\.vercel\.app$",
            r"^https://[a-z0-9-]+\.cl$", r"^https://[a-z0-9-]+\.com\.ar$", r"^https://[a-z]+$",
            r"^https://senacl\.[a-z]+$", r"^https://senacl-[a-z0-9-]+-equipo.vercel.app$",
            r"^http://senacl-[a-z0-9-]+-equipo\.vercel\.app$",
            r"^https://(a|.*)\.senacl\.cl$", r"^https://a\.senacl\.cl|.*$", r"^https://[^/]+\.senacl\.cl$",
            r"^https://\S+\.senacl\.cl$", r"^https://([a-z]+)+\.senacl\.cl$", r"^https://a*\.senacl\.cl$",
            r"^https://[a-z]{9,1}\.senacl\.cl$", r"^https://\.senacl\.cl$",
            r"^https://[a-z]+[a-z]+[a-z]+\.senacl\.cl$", r"^https://" + "a" * 200 + r"\.senacl\.cl$",
            "https://[a-z", r"(?i)https://senacl\.cl", "https://senacl",
        ],
    )
    def test_regex_abierto_rechazado(self, patron):
        with pytest.raises(ValidationError, match="ALLOWED_ORIGIN_REGEX"):
            _settings(allowed_origin_regex=patron)

    ACEPTADOS = [VERCEL, PROPIO, "https://senacl-git-dev-equipo.vercel.app"]
    RECHAZADOS = [
        "https://evil.vercel.app", "https://senacl.vercel.app.evil.example", "http://senacl.vercel.app",
        "https://senacl-x-equipo.vercel.app.evil.example", "https://senacl-x-equipoXvercel.app",
        "https://a.senacl-x-equipo.vercel.app", "https://senacl-x-equipo.vercel.app:8443", "null", "",
        "https://senacl-x-equipo.vercel.app\n",
    ]

    @pytest.fixture
    def cfg(self):
        return _settings(allowed_origins=f"{VERCEL}, {PROPIO}", allowed_origin_regex=REGEX_OK)

    @pytest.fixture
    def cors(self, cfg):
        app = FastAPI()
        app.add_middleware(CORSMiddleware, **opciones_cors(cfg))
        return TestClient(app)

    @pytest.mark.parametrize("origen", ACEPTADOS)
    def test_preflight_aceptado(self, cors, origen):
        r = cors.options(
            "/api/recognize",
            headers={"Origin": origen, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization,content-type"},
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origen
        assert "access-control-allow-credentials" not in r.headers

    @pytest.mark.parametrize("origen", [o for o in RECHAZADOS if "\n" not in o])
    def test_preflight_rechazado(self, cors, origen):
        r = cors.options(
            "/api/recognize", headers={"Origin": origen, "Access-Control-Request-Method": "POST"}
        )
        assert "access-control-allow-origin" not in r.headers

    @pytest.mark.parametrize("origen", ACEPTADOS + RECHAZADOS)
    def test_cors_y_ws_aplican_la_misma_politica(self, cfg, monkeypatch, origen):
        monkeypatch.setattr("app.routes.ws.get_settings", lambda: cfg)
        assert origen_permitido(origen) is (origen in self.ACEPTADOS)

    def test_sin_regex_no_acepta_previews(self, settings):
        assert settings.allowed_origin_regex == ""
        assert not settings.origen_en_lista_blanca("https://senacl-git-dev-equipo.vercel.app")
        assert opciones_cors(settings)["allow_origin_regex"] is None

    @pytest.mark.parametrize(
        ("origen", "ok"), [(VERCEL, True), (PROPIO, True), ("https://evil.vercel.app", False)]
    )
    def test_handshake_ws_con_origenes_vercel(self, client, settings, monkeypatch, origen, ok):
        monkeypatch.setattr(settings, "allowed_origins", f"{VERCEL},{PROPIO}")
        monkeypatch.setattr(settings, "debug", False)
        if ok:
            with client.websocket_connect("/ws/recognize", headers={"origin": origen}) as ws:
                assert ws.receive_json()["type"] == "estado"
        else:
            with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(
                "/ws/recognize", headers={"origin": origen}
            ):
                pass
            assert exc.value.code == 1008


# ======================================================================= Supabase RLS
RLS_SQL = (BACKEND_DIR / "db" / "supabase_rls.sql").read_text(encoding="utf-8")


class TestSupabaseRls:
    def test_contenido(self):
        codigo = re.sub(r"--[^\n]*", "", RLS_SQL)
        for tabla in ("users", "history"):
            assert f"ALTER TABLE public.{tabla} ENABLE ROW LEVEL SECURITY;" in codigo
        assert "'anon', 'authenticated'" in codigo and "REVOKE ALL" in codigo
        for prohibido in (r"\bGRANT\b", r"CREATE\s+POLICY", r"DISABLE\s+ROW", r"\bDROP\b", r"\bTRUNCATE\b"):
            assert not re.search(prohibido, codigo, re.IGNORECASE), prohibido

    def test_schema_local_no_depende_de_supabase(self):
        esquema = (BACKEND_DIR / "db" / "schema.sql").read_text(encoding="utf-8").lower()
        assert "row level security" not in esquema and "authenticated" not in esquema

    @staticmethod
    def _rls(cur) -> list[bool]:
        cur.execute(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid IN ('public.users'::regclass, 'public.history'::regclass)"
        )
        return [f[0] for f in cur.fetchall()]

    @pytest.mark.parametrize("con_roles", [False, True], ids=["postgres-estandar", "con-roles-supabase"])
    def test_ejecucion_idempotente_y_revertida(self, db_sync, con_roles):
        """Se ejecuta dos veces dentro de una transacción que siempre se revierte."""
        conn = db_sync.raw_connection()
        try:
            cur = conn.cursor()
            antes = self._rls(cur)
            if con_roles:
                for rol in ("anon", "authenticated"):
                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (rol,))
                    if cur.fetchone() is None:
                        cur.execute(f"CREATE ROLE {rol} NOLOGIN")
                cur.execute("GRANT ALL ON public.users, public.history TO anon, authenticated")
                cur.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated")
            for _ in range(2):
                cur.execute(RLS_SQL)
            assert self._rls(cur) == [True, True]
            cur.execute("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
            assert cur.fetchone()[0] == 0
            if con_roles:
                cur.execute(
                    "SELECT bool_or(has_table_privilege(r, t, p)) "
                    "FROM unnest(ARRAY['anon', 'authenticated']) r, "
                    "unnest(ARRAY['public.users', 'public.history']) t, "
                    "unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) p"
                )
                assert cur.fetchone()[0] is False
                cur.execute("SELECT has_sequence_privilege('anon', 'public.users_id_seq', 'USAGE')")
                assert cur.fetchone()[0] is False
            # El dueño (rol con el que se conecta el backend) sigue operando.
            cur.execute(
                "INSERT INTO users (username, email, password_hash) "
                "VALUES ('rls_test', 'rls@example.com', 'x') RETURNING id"
            )
            assert cur.fetchone()[0]
            conn.rollback()
            assert self._rls(cur) == antes
        finally:
            conn.rollback()
            conn.close()


# ==================================================================== Render / Argon2id
class TestRender:
    @pytest.fixture(scope="class")
    def servicio(self) -> dict:
        blueprint = yaml.safe_load((RAIZ / "render.yaml").read_text(encoding="utf-8"))
        return blueprint["services"][0]

    @pytest.fixture(scope="class")
    def env(self, servicio) -> dict:
        return {e["key"]: e for e in servicio["envVars"]}

    def test_servicio(self, servicio):
        assert servicio["runtime"] == "python" and servicio["rootDir"] == "backend"
        assert servicio["healthCheckPath"] == "/api/health"

    @pytest.mark.parametrize(
        "parte",
        ["app.main:app", "--host 0.0.0.0", "--port $PORT", "--ws-max-size 49152", "--no-proxy-headers"],
    )
    def test_arranque(self, servicio, parte):
        assert parte in servicio["startCommand"]

    @pytest.mark.parametrize("clave", ["DATABASE_URL", "SECRET_KEY", "ALLOWED_ORIGINS"])
    def test_secretos_sin_valor(self, env, clave):
        assert env[clave] == {"key": clave, "sync": False}

    def test_sin_credenciales_en_archivos_versionados(self):
        patron = re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s:]+:([^\s@]+)@\S*supabase|eyJhbGciOi")
        for ruta in (RAIZ / "render.yaml", RAIZ / ".env.example", BACKEND_DIR / ".env.example",
                     BACKEND_DIR / "README.md", BACKEND_DIR / "SECURITY.md"):
            for m in patron.finditer(ruta.read_text(encoding="utf-8")):
                assert re.fullmatch(r"\[?[A-Z_-]+\]?|<[^>]+>", m.group(1) or ""), ruta.name

    def test_valores(self, env):
        esperado = {
            "DEBUG": "false", "ALGORITHM": "HS256", "TRUST_PROXY_HOPS": "1", "DB_SSL": "true",
            "DB_USE_PGBOUNCER": "true", "WEB_CONCURRENCY": "1", "FORWARDED_ALLOW_IPS": "127.0.0.1",
            "TF_CPP_MIN_LOG_LEVEL": "2", "OMP_NUM_THREADS": "1", "TF_NUM_INTRAOP_THREADS": "1",
            "TF_NUM_INTEROP_THREADS": "1", "MAX_CONCURRENT_INFERENCES": "1", "MAX_CONCURRENT_HASHES": "1",
        }
        assert {k: env[k]["value"] for k in esperado} == esperado
        assert env["PYTHON_VERSION"]["value"].startswith("3.11.")

    def test_el_blueprint_produce_settings_validos(self, env):
        campos = {k.lower(): e["value"] for k, e in env.items() if "value" in e}
        cfg = _settings(**{**{k: v for k, v in campos.items() if k in Settings.model_fields},
                           "database_url": POOLER_TX, "allowed_origins": VERCEL})
        assert cfg.debug is False and cfg.trust_proxy_hops == 1
        assert cfg.usar_ssl and cfg.usar_pgbouncer and cfg.max_concurrent_hashes == 1

    def test_tensorflow_cpu_solo_en_linux_x86_64(self):
        lineas = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
        tf = [x for x in lineas if x.startswith("tensorflow")]
        assert [x.split(";")[0] for x in tf] == ["tensorflow==2.16.2", "tensorflow-cpu==2.16.2"]
        assert 'sys_platform == "linux" and platform_machine == "x86_64"' in tf[1]
        assert {"keras==3.15.1", "numpy==1.26.4"} <= set(lineas)

    def test_gitignore_protege_env_y_publica_el_modelo(self):
        # El Blueprint clona el repo tal cual: el modelo debe ser un archivo real, no un puntero LFS.
        assert (BACKEND_DIR / "models" / "mejor_modelo_lsch.keras").stat().st_size > 10_000_000
        assert ".env" in (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()

    async def test_hashes_concurrentes_acotados(self, settings, monkeypatch):
        activos, pico, candado = 0, 0, threading.Lock()

        def lento(_password: str) -> str:
            nonlocal activos, pico
            with candado:
                activos += 1
                pico = max(pico, activos)
            time.sleep(0.02)
            with candado:
                activos -= 1
            return "hash"

        monkeypatch.setattr(security, "hash_password", lento)
        await asyncio.gather(*(security.hash_password_async("x") for _ in range(10)))
        assert 1 <= pico <= settings.max_concurrent_hashes

    def test_argon2id_sin_bajar_parametros(self):
        assert "$argon2id$v=19$m=65536,t=3,p=4$" in security.hash_password("Prueba1234")


# ================================================================ app real tras el proxy
@pytest.mark.slow
def test_uvicorn_de_render_no_confia_en_xff(env_prod, tmp_path):
    """Con los flags del Blueprint y ``FORWARDED_ALLOW_IPS=*`` la app ve la IP TCP, no la falsa."""
    modulo = tmp_path / "eco_ip.py"
    modulo.write_text(
        "async def app(scope, receive, send):\n"
        "    if scope['type'] != 'http':\n"
        "        return\n"
        "    cuerpo = scope['client'][0].encode()\n"
        "    await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
        "    await send({'type': 'http.response.body', 'body': cuerpo})\n",
        encoding="utf-8",
    )
    blueprint = yaml.safe_load((RAIZ / "render.yaml").read_text(encoding="utf-8"))
    flags = [f for f in blueprint["services"][0]["startCommand"].split() if f.startswith("--no-")]
    assert _ip_vista(tmp_path, env_prod, flags) == "127.0.0.1"
    # Contraprueba: sin el flag, uvicorn entrega la IP escrita por el cliente.
    assert _ip_vista(tmp_path, env_prod, []) == "6.6.6.6"


@pytest.fixture
def env_prod() -> dict:
    return {**os.environ, "FORWARDED_ALLOW_IPS": "*"}


def _ip_vista(directorio: Path, env: dict, flags: list[str]) -> str:
    import socket

    import httpx

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "eco_ip:app", "--host", "127.0.0.1", "--port", str(puerto),
         "--lifespan", "off", "--log-level", "warning", *flags],
        cwd=directorio, env=env,
    )
    try:
        for _ in range(100):
            try:
                return httpx.get(
                    f"http://127.0.0.1:{puerto}/",
                    headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.9"},
                    trust_env=False,
                ).text
            except httpx.TransportError:
                time.sleep(0.1)
        raise AssertionError("uvicorn no arrancó")
    finally:
        proceso.terminate()
        proceso.wait(timeout=10)
