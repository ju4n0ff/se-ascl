"""Repositorios de ``users`` e ``history``: único punto de la API con consultas a esas tablas.

Las rutas y los servicios reciben una ``AsyncSession`` de ``get_db()`` (que hace el
commit o rollback por solicitud) y delegan aquí todo ``SELECT``/``INSERT``/``UPDATE``/
``DELETE``. Los repositorios no conocen HTTP: devuelven entidades, ``None`` o ``bool``,
o lanzan ``RegistroDuplicadoError``.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HistoryEntry, User


class RegistroDuplicadoError(Exception):
    """Se violó una restricción ``UNIQUE`` (``username`` o ``email``)."""


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def por_id(self, user_id: int) -> User | None:
        return await self._db.get(User, user_id)

    async def por_username(self, username: str) -> User | None:
        resultado = await self._db.execute(select(User).where(User.username == username))
        return resultado.scalar_one_or_none()

    async def por_email(self, email: str) -> User | None:
        resultado = await self._db.execute(select(User).where(User.email == email))
        return resultado.scalar_one_or_none()

    async def existe_username_o_email(self, username: str, email: str) -> bool:
        resultado = await self._db.execute(
            select(User.id).where(or_(User.username == username, User.email == email)).limit(1)
        )
        return resultado.first() is not None

    async def crear(self, username: str, email: str, password_hash: str) -> User:
        user = User(username=username, email=email, password_hash=password_hash)
        self._db.add(user)
        try:
            await self._db.flush()
        except IntegrityError as exc:  # carrera entre dos registros simultáneos
            await self._db.rollback()
            raise RegistroDuplicadoError from exc
        await self._db.refresh(user)
        return user

    async def actualizar(
        self, user_id: int, *, email: str | None = None, password_hash: str | None = None
    ) -> User | None:
        """Actualiza solo los campos indicados; ``None`` si el usuario ya no existe."""
        cambios: dict[str, str] = {}
        if email is not None:
            cambios["email"] = email
        if password_hash is not None:
            cambios["password_hash"] = password_hash
        if not cambios:
            return await self.por_id(user_id)
        try:
            resultado = await self._db.execute(
                update(User).where(User.id == user_id).values(**cambios).returning(User)
            )
        except IntegrityError as exc:  # carrera: otro usuario tomó el email
            await self._db.rollback()
            raise RegistroDuplicadoError from exc
        return resultado.scalar_one_or_none()

    async def borrar(self, user_id: int) -> bool:
        # DELETE directo: ON DELETE CASCADE de PostgreSQL elimina también su historial.
        resultado = await self._db.execute(
            delete(User).where(User.id == user_id).returning(User.id)
        )
        return resultado.first() is not None


class HistoryRepository:
    """Toda lectura o modificación va acotada al dueño (``user_id``): anti-BOLA."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def listar_por_usuario(self, user_id: int, limit: int) -> Sequence[HistoryEntry]:
        resultado = await self._db.execute(
            select(HistoryEntry)
            .where(HistoryEntry.user_id == user_id)
            .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
            .limit(limit)
        )
        return resultado.scalars().all()

    async def crear(
        self, *, user_id: int, predicted_label: str, spanish_text: str, confidence: float, mode: str
    ) -> HistoryEntry:
        entrada = HistoryEntry(
            user_id=user_id,
            predicted_label=predicted_label,
            spanish_text=spanish_text,
            confidence=confidence,
            mode=mode,
        )
        self._db.add(entrada)
        await self._db.flush()
        return entrada

    async def actualizar_texto(
        self, entry_id: int, user_id: int, spanish_text: str
    ) -> HistoryEntry | None:
        """``UPDATE`` atómico por dueño; ``None`` si no existe o es ajena (indistinguibles)."""
        resultado = await self._db.execute(
            update(HistoryEntry)
            .where(HistoryEntry.id == entry_id, HistoryEntry.user_id == user_id)
            .values(spanish_text=spanish_text)
            .returning(HistoryEntry)
        )
        return resultado.scalar_one_or_none()

    async def borrar(self, entry_id: int, user_id: int) -> bool:
        """``DELETE`` atómico por dueño; ``False`` si no existe o es ajena (indistinguibles)."""
        resultado = await self._db.execute(
            delete(HistoryEntry)
            .where(HistoryEntry.id == entry_id, HistoryEntry.user_id == user_id)
            .returning(HistoryEntry.id)
        )
        return resultado.first() is not None
