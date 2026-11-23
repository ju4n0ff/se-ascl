"""Motor y sesión asíncrona de PostgreSQL (asyncpg)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings

settings = get_settings()


def opciones_motor(cfg: Settings) -> dict[str, Any]:
    """Local: sin SSL ni ajustes de pooler. Supabase/PgBouncer: ``Settings.db_connect_args``."""
    return {
        # echo=False: el eco de SQLAlchemy vuelca parámetros (emails, hashes) a los logs.
        "echo": False,
        # El pooler cierra conexiones inactivas: verificar antes de usar y reciclar.
        "pool_pre_ping": True,
        "pool_recycle": cfg.db_pool_recycle_s,
        "pool_size": cfg.db_pool_size,
        "max_overflow": cfg.db_max_overflow,
        "connect_args": cfg.db_connect_args,
    }


engine = create_async_engine(settings.database_url, **opciones_motor(settings))
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def ping() -> None:
    """Consulta trivial para el healthcheck; lanza si PostgreSQL no responde."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
