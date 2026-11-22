"""Seed idempotente de desarrollo: ``python -m app.db.seed`` (desde ``backend/``).

Crea ``test_user`` / ``Test1234!`` (Argon2id) y un historial de ejemplo si no
existen. Se niega a correr con ``DEBUG=false`` para no dejar una cuenta con
contraseña conocida en producción.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import HistoryEntry, User
from app.db.session import async_session, engine

USERNAME = "test_user"
EMAIL = "test@signia.cl"
PASSWORD_DEV = "Test1234!"  # nosec B105 - credencial ficticia solo para DEBUG=true
HISTORIAL = [
    ("hola", "hola", 0.94),
    ("gracias", "gracias", 0.87),
    ("buenos_dias", "buenos dias", 0.81),
    ("donde_salida.I", "¿donde salida?", 0.78),
]


async def sembrar() -> tuple[bool, int]:
    """Devuelve ``(usuario_creado, entradas_creadas)``."""
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.username == USERNAME))).scalar_one_or_none()
        creado = user is None
        if creado:
            user = User(username=USERNAME, email=EMAIL, password_hash=hash_password(PASSWORD_DEV))
            db.add(user)
            await db.flush()

        existentes = await db.scalar(
            select(func.count()).select_from(HistoryEntry).where(HistoryEntry.user_id == user.id)
        )
        nuevas = 0
        if not existentes:
            for label, texto, conf in HISTORIAL:
                db.add(HistoryEntry(user_id=user.id, predicted_label=label,
                                    spanish_text=texto, confidence=conf, mode="dynamic"))
                nuevas += 1
        await db.commit()
    await engine.dispose()
    return creado, nuevas


def main() -> int:
    if not get_settings().debug:
        print("Seed rechazado: solo se permite con DEBUG=true.", file=sys.stderr)
        return 1
    creado, nuevas = asyncio.run(sembrar())
    print(f"Usuario {USERNAME}: {'creado' if creado else 'ya existía'}; historial: {nuevas} entradas nuevas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
