from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.models.database import get_db
from app.models.entities import HistoryEntry
from app.schemas.schemas import RecognitionRequest, RecognitionResponse, HistoryCreate, HistoryResponse
from app.services.inference import predict

router = APIRouter(prefix="/api", tags=["recognition"])


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize(
    payload: RecognitionRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.mode not in ("static", "dynamic"):
        raise HTTPException(status_code=422, detail="mode debe ser 'static' o 'dynamic'")

    if not payload.hands:
        raise HTTPException(status_code=422, detail="Se requiere al menos una mano")

    result = predict(payload.mode, payload.hands, payload.face)

    # Save to history if session provided
    if payload.session_id is not None:
        entry = HistoryEntry(
            user_id=payload.session_id,
            predicted_label=result["predicted_label"],
            spanish_text=result["spanish_text"],
            confidence=result["confidence"],
            mode=payload.mode,
        )
        db.add(entry)
        await db.flush()

    return RecognitionResponse(
        predicted_label=result["predicted_label"],
        spanish_text=result["spanish_text"],
        confidence=result["confidence"],
        mode=payload.mode,
        timestamp=datetime.utcnow(),
    )


@router.get("/health")
async def health():
    return {"status": "ok", "service": "signia-backend"}
