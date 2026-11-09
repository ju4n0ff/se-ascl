from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.database import get_db
from app.models.entities import HistoryEntry
from app.schemas.schemas import HistoryResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{user_id}", response_model=list[HistoryResponse])
async def get_history(
    user_id: int,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HistoryEntry)
        .where(HistoryEntry.user_id == user_id)
        .order_by(HistoryEntry.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(HistoryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    await db.delete(entry)
    await db.flush()
