"""Historial del usuario autenticado (anti-BOLA/IDOR)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import HistoryEntry, User
from app.db.session import get_db
from app.schemas.schemas import HistoryResponse

router = APIRouter(prefix="/api/history", tags=["history"])

INT32_MAX = 2_147_483_647  # SERIAL de PostgreSQL; evita DataError (500) con IDs enormes
# Annotated: FastAPI crea un FieldInfo por parámetro (una instancia Path() compartida
# entre rutas heredaría el alias de la primera y rompería las demás).
UserIdPath = Annotated[int, Path(ge=1, le=INT32_MAX)]
EntryIdPath = Annotated[int, Path(ge=1, le=INT32_MAX)]
Limite = Annotated[int, Query(ge=1, le=200)]


async def _historial(db: AsyncSession, user_id: int, limit: int) -> Sequence[HistoryEntry]:
    resultado = await db.execute(
        select(HistoryEntry)
        .where(HistoryEntry.user_id == user_id)
        .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
        .limit(limit)
    )
    return resultado.scalars().all()


# Debe declararse antes de /{user_id} para que "me" no se interprete como ID.
@router.get("/me", response_model=list[HistoryResponse])
async def get_my_history(
    limit: Limite = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Sequence[HistoryEntry]:
    return await _historial(db, current_user.id, limit)


@router.get("/{user_id}", response_model=list[HistoryResponse])
async def get_history(
    user_id: UserIdPath,
    limit: Limite = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Sequence[HistoryEntry]:
    if user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a este historial")
    return await _historial(db, current_user.id, limit)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: EntryIdPath,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Filtra por dueño en la misma consulta: una entrada ajena es indistinguible de una inexistente.
    resultado = await db.execute(
        delete(HistoryEntry)
        .where(HistoryEntry.id == entry_id, HistoryEntry.user_id == current_user.id)
        .returning(HistoryEntry.id)
    )
    if resultado.first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entrada no encontrada")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
