"""CRUD de los recursos ``history`` y ``users/me``: éxito, errores, anti-BOLA y supresión."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.rate_limit import rate_limiter
from app.db import session as db_session
from app.db.repositories import HistoryRepository, RegistroDuplicadoError, UserRepository
from utils import (
    PASSWORD_OK,
    auth,
    contar_historial,
    existe_historial,
    insertar_historial,
    registrar,
    token_de,
)

PASSWORD_NUEVA = "Cambiada5678"
PASSWORD_MALA = "Incorrecta99"


def _fila_historial(db_sync, entry_id: int) -> dict:
    with db_sync.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM history WHERE id = :i"), {"i": entry_id}).mappings().one()
        )


def _fila_usuario(db_sync, user_id: int) -> dict | None:
    with db_sync.connect() as conn:
        fila = conn.execute(text("SELECT * FROM users WHERE id = :i"), {"i": user_id}).mappings().first()
    return dict(fila) if fila else None


def _patch_me(client, token: str, **cuerpo):
    cuerpo.setdefault("current_password", PASSWORD_OK)
    return client.patch("/api/users/me", json=cuerpo, headers=auth(token))


# ================================================= PATCH /api/history/{entry_id}
class TestHistorialUpdate:
    def test_dueno_200_y_persiste(self, client, usuario, db_sync):
        entrada = insertar_historial(db_sync, usuario["id"], "hola")
        antes = _fila_historial(db_sync, entrada)
        h = auth(usuario["token"])
        r = client.patch(f"/api/history/{entrada}", json={"spanish_text": "  hola, ¿cómo estás? "}, headers=h)
        assert r.status_code == 200
        assert r.json()["spanish_text"] == "hola, ¿cómo estás?"
        assert r.json() == client.get("/api/history/me", headers=h).json()[0]
        # Solo cambia el texto: lo que predijo el modelo es inmutable.
        assert _fila_historial(db_sync, entrada) == {**antes, "spanish_text": "hola, ¿cómo estás?"}

    def test_ajena_e_inexistente_404_indistinguibles(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        entrada_b = insertar_historial(db_sync, b["id"], "gracias")
        cuerpo = {"spanish_text": "secuestrado"}
        ajena = client.patch(f"/api/history/{entrada_b}", json=cuerpo, headers=auth(a["token"]))
        inexistente = client.patch("/api/history/987654", json=cuerpo, headers=auth(a["token"]))
        assert ajena.status_code == inexistente.status_code == 404
        assert ajena.json() == inexistente.json()
        assert _fila_historial(db_sync, entrada_b)["spanish_text"] == "gracias"

    def test_solo_modifica_la_entrada_indicada(self, client, usuario, db_sync):
        una, otra = (insertar_historial(db_sync, usuario["id"], x) for x in ("uno", "dos"))
        client.patch(f"/api/history/{una}", json={"spanish_text": "nuevo"}, headers=auth(usuario["token"]))
        assert _fila_historial(db_sync, una)["spanish_text"] == "nuevo"
        assert _fila_historial(db_sync, otra)["spanish_text"] == "dos"

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {},
            {"spanish_text": ""},
            {"spanish_text": "   \t\n "},
            {"spanish_text": "x" * 501},
            {"spanish_text": None},
            {"spanish_text": 123},
            {"spanish_text": "nul\x00"},
            {"spanish_text": "\x1c"},
            {"spanish_text": "ok", "predicted_label": "otra"},
            {"spanish_text": "ok", "confidence": 1.0},
            {"spanish_text": "ok", "mode": "static"},
            {"spanish_text": "ok", "user_id": 1},
        ],
    )
    def test_cuerpo_invalido_422(self, client, usuario, db_sync, cuerpo):
        entrada = insertar_historial(db_sync, usuario["id"], "hola")
        antes = _fila_historial(db_sync, entrada)
        r = client.patch(f"/api/history/{entrada}", json=cuerpo, headers=auth(usuario["token"]))
        assert r.status_code == 422
        assert _fila_historial(db_sync, entrada) == antes

    def test_500_caracteres_tras_strip_es_valido(self, client, usuario, db_sync):
        entrada = insertar_historial(db_sync, usuario["id"])
        r = client.patch(
            f"/api/history/{entrada}",
            json={"spanish_text": " " + "ñ" * 500 + " "},
            headers=auth(usuario["token"]),
        )
        assert r.status_code == 200
        assert r.json()["spanish_text"] == "ñ" * 500

    @pytest.mark.parametrize("valor", [0, -1, 2_147_483_648, "abc"])
    def test_id_fuera_de_int4_422(self, client, usuario, valor):
        r = client.patch(
            f"/api/history/{valor}", json={"spanish_text": "x"}, headers=auth(usuario["token"])
        )
        assert r.status_code == 422

    def test_sin_token_401(self, client, usuario, db_sync):
        entrada = insertar_historial(db_sync, usuario["id"], "hola")
        r = client.patch(f"/api/history/{entrada}", json={"spanish_text": "x"})
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
        assert _fila_historial(db_sync, entrada)["spanish_text"] == "hola"


# ============================================================ /api/users/me
class TestPerfil:
    @pytest.mark.parametrize("metodo", ["GET", "PATCH", "DELETE"])
    @pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer no.es.jwt"}])
    def test_sin_token_o_invalido_401(self, client, metodo, headers):
        r = client.request(metodo, "/api/users/me", headers=headers)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"

    def test_get_me_sin_password_hash(self, client, dos_usuarios):
        a, _ = dos_usuarios
        r = client.get("/api/users/me", headers=auth(a["token"]))
        assert r.status_code == 200
        assert r.json() == {"id": a["id"], "username": "usuario_a", "email": "usuario_a@example.com"}


class TestPerfilUpdate:
    def test_cambia_email_en_minusculas(self, client, usuario, db_sync):
        hash_antes = _fila_usuario(db_sync, usuario["id"])["password_hash"]
        r = _patch_me(client, usuario["token"], email="Nuevo@Example.COM")
        assert r.status_code == 200
        assert r.json() == {"id": usuario["id"], "username": "ana_test", "email": "nuevo@example.com"}
        assert client.get("/api/users/me", headers=auth(usuario["token"])).json() == r.json()
        assert _fila_usuario(db_sync, usuario["id"])["password_hash"] == hash_antes

    def test_mismo_email_propio_200(self, client, usuario):
        assert _patch_me(client, usuario["token"], email="ana_test@example.com").status_code == 200

    def test_cambia_password_y_la_anterior_deja_de_servir(self, client, usuario, db_sync):
        r = _patch_me(client, usuario["token"], new_password=PASSWORD_NUEVA)
        assert r.status_code == 200
        assert set(r.json()) == {"id", "username", "email"}
        fila = _fila_usuario(db_sync, usuario["id"])
        assert fila["password_hash"].startswith("$argon2id$")
        assert fila["email"] == "ana_test@example.com"
        vieja = client.post("/api/auth/login", json={"username": "ana_test", "password": PASSWORD_OK})
        assert vieja.status_code == 401
        assert token_de(client, "ana_test", PASSWORD_NUEVA)

    def test_cambia_email_y_password_juntos(self, client, usuario):
        r = _patch_me(client, usuario["token"], email="ambos@example.com", new_password=PASSWORD_NUEVA)
        assert r.status_code == 200
        assert r.json()["email"] == "ambos@example.com"
        assert token_de(client, "ana_test", PASSWORD_NUEVA)

    def test_no_afecta_a_otros_usuarios(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        antes = _fila_usuario(db_sync, b["id"])
        _patch_me(client, a["token"], email="nuevo@example.com", new_password=PASSWORD_NUEVA)
        assert _fila_usuario(db_sync, b["id"]) == antes

    def test_current_password_incorrecta_401_sin_cambios(self, client, dos_usuarios, db_sync):
        a, _ = dos_usuarios
        antes = _fila_usuario(db_sync, a["id"])
        libre = _patch_me(client, a["token"], email="libre@example.com", current_password=PASSWORD_MALA)
        # Con la contraseña mala un email ocupado responde igual: no se puede sondear.
        ocupado = _patch_me(
            client, a["token"], email="usuario_b@example.com", current_password=PASSWORD_MALA
        )
        assert libre.status_code == ocupado.status_code == 401
        assert libre.json() == ocupado.json() == {"detail": "Credenciales inválidas"}
        assert _fila_usuario(db_sync, a["id"]) == antes

    @pytest.mark.parametrize("email", ["usuario_b@example.com", "USUARIO_B@Example.com"])
    def test_email_duplicado_409_generico(self, client, dos_usuarios, db_sync, email):
        a, _ = dos_usuarios
        antes = _fila_usuario(db_sync, a["id"])
        # Todo o nada: la contraseña tampoco cambia si el email choca.
        r = _patch_me(client, a["token"], email=email, new_password=PASSWORD_NUEVA)
        assert r.status_code == 409
        assert "email" not in r.text.lower()
        assert _fila_usuario(db_sync, a["id"]) == antes

    @pytest.mark.parametrize(
        "password",
        ["1234", "corta1A", "sinmayuscula1", "SINMINUSCULA1", "SinDigitosAqui", "x" * 129 + "A1"],
    )
    def test_password_debil_422_sin_eco(self, client, usuario, password):
        r = _patch_me(client, usuario["token"], new_password=password)
        assert r.status_code == 422
        assert password not in r.text
        assert PASSWORD_OK not in r.text

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"current_password": PASSWORD_OK},
            {"current_password": PASSWORD_OK, "email": None, "new_password": None},
            {"email": "n@example.com"},
            {"email": "n@example.com", "current_password": ""},
            {"email": "no-es-email", "current_password": PASSWORD_OK},
            {"email": "a" * 95 + "@example.com", "current_password": PASSWORD_OK},
            {"email": "n@example.com", "current_password": PASSWORD_OK, "username": "otro"},
            {"email": "n@example.com", "current_password": PASSWORD_OK, "id": 1},
            {"email": "n@example.com", "current_password": PASSWORD_OK, "password_hash": "x"},
            {"email": "n@example.com", "current_password": PASSWORD_OK, "is_admin": True},
        ],
    )
    def test_cuerpo_invalido_o_campos_extra_422(self, client, usuario, db_sync, cuerpo):
        antes = _fila_usuario(db_sync, usuario["id"])
        r = client.patch("/api/users/me", json=cuerpo, headers=auth(usuario["token"]))
        assert r.status_code == 422
        assert _fila_usuario(db_sync, usuario["id"]) == antes

    def test_429_frena_fuerza_bruta_de_current_password(self, client, usuario, settings):
        limite = settings.rate_limit_profile_per_min
        respuestas = [
            _patch_me(client, usuario["token"], email="x@example.com", current_password=PASSWORD_MALA)
            for _ in range(limite + 1)
        ]
        assert [r.status_code for r in respuestas] == [401] * limite + [429]
        assert 1 <= int(respuestas[-1].headers["retry-after"]) <= 60


class TestPerfilDelete:
    def test_204_cascada_y_token_anterior_401(self, client, dos_usuarios, db_sync):
        a, b = dos_usuarios
        for label in ("uno", "dos"):
            insertar_historial(db_sync, a["id"], label)
        entrada_b = insertar_historial(db_sync, b["id"], "ajena")

        r = client.delete("/api/users/me", headers=auth(a["token"]))
        assert r.status_code == 204
        assert r.content == b""

        assert _fila_usuario(db_sync, a["id"]) is None
        assert contar_historial(db_sync, a["id"]) == 0  # ON DELETE CASCADE
        assert _fila_usuario(db_sync, b["id"]) is not None
        assert existe_historial(db_sync, entrada_b)

        # El JWT sigue firmado y vigente, pero su usuario ya no existe.
        for metodo, ruta in (
            ("GET", "/api/users/me"),
            ("DELETE", "/api/users/me"),
            ("GET", "/api/history/me"),
        ):
            assert client.request(metodo, ruta, headers=auth(a["token"])).status_code == 401
        login = client.post("/api/auth/login", json={"username": "usuario_a", "password": PASSWORD_OK})
        assert login.status_code == 401

    def test_reregistro_no_hereda_el_token_anterior(self, client, usuario):
        client.delete("/api/users/me", headers=auth(usuario["token"]))
        nuevo = registrar(client, "ana_test")
        assert nuevo["id"] != usuario["id"]
        assert client.get("/api/users/me", headers=auth(usuario["token"])).status_code == 401


# =================================================== repositorios (carreras)
@pytest.fixture
async def sesion(dos_usuarios):
    async with db_session.async_session() as db:
        yield db


class TestRepositorios:
    async def test_busquedas(self, sesion, dos_usuarios):
        a, _ = dos_usuarios
        repo = UserRepository(sesion)
        por_id = await repo.por_id(a["id"])
        assert por_id is await repo.por_username("usuario_a")
        assert por_id is await repo.por_email("usuario_a@example.com")
        assert await repo.por_id(999_999) is None
        assert await repo.por_username("nadie") is None
        assert await repo.por_email("nadie@example.com") is None
        assert await repo.existe_username_o_email("usuario_a", "nadie@example.com")
        assert await repo.existe_username_o_email("nadie", "usuario_a@example.com")
        assert not await repo.existe_username_o_email("nadie", "nadie@example.com")

    async def test_unique_se_traduce_a_error_de_dominio(self, sesion, dos_usuarios):
        a, _ = dos_usuarios
        repo = UserRepository(sesion)
        with pytest.raises(RegistroDuplicadoError):
            await repo.crear("usuario_a", "libre@example.com", "hash")
        with pytest.raises(RegistroDuplicadoError):
            await repo.actualizar(a["id"], email="usuario_b@example.com")
        # La sesión queda utilizable tras el rollback.
        assert (await repo.por_id(a["id"])).email == "usuario_a@example.com"

    async def test_usuario_inexistente(self, sesion):
        repo = UserRepository(sesion)
        assert await repo.actualizar(999_999, email="x@example.com") is None
        assert await repo.borrar(999_999) is False

    async def test_historial_acotado_al_dueno(self, sesion, dos_usuarios, db_sync):
        a, b = dos_usuarios
        entrada_b = insertar_historial(db_sync, b["id"], "gracias")
        repo = HistoryRepository(sesion)
        assert await repo.listar_por_usuario(a["id"], 50) == []
        assert await repo.actualizar_texto(entrada_b, a["id"], "x") is None
        assert await repo.borrar(entrada_b, a["id"]) is False
        assert await repo.borrar(entrada_b, b["id"]) is True


def test_registro_carrera_409(client, usuario, monkeypatch):
    """Si la consulta previa no ve el duplicado, el UNIQUE responde el mismo 409 genérico."""

    async def _no_existe(self, username, email):
        return False

    monkeypatch.setattr(UserRepository, "existe_username_o_email", _no_existe)
    rate_limiter.reset()
    r = client.post(
        "/api/auth/register",
        json={"username": "ana_test", "email": "otra@example.com", "password": PASSWORD_OK},
    )
    assert r.status_code == 409
    assert r.json() == {"detail": "No se pudo completar el registro con esos datos"}
