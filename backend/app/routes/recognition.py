from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.entities import HistoryEntry
from app.schemas.schemas import RecognitionRequest, RecognitionResponse
from app.services.inference import get_model_status, predict

router = APIRouter(prefix="/api", tags=["recognition"])


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize(
    payload: RecognitionRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.mode not in ("static", "dynamic", "lsch_v3"):
        raise HTTPException(status_code=422, detail="mode debe ser 'static', 'dynamic' o 'lsch_v3'")

    if payload.mode == "lsch_v3":
        if not payload.frames:
            raise HTTPException(status_code=422, detail="Se requieren frames para mode='lsch_v3'")
    elif not payload.hands:
        raise HTTPException(status_code=422, detail="Se requiere al menos una mano")

    result = predict(
        payload.mode,
        payload.hands,
        payload.face,
        frames=payload.frames,
        top_k=payload.top_k,
    )

    if result.get("error") and result.get("predicted_label") in {"INVALID", "UNKNOWN", "ERROR"}:
        # Keep response shape for clients, but surface obvious input/model issues as 4xx/503 when appropriate.
        if result["predicted_label"] == "INVALID":
            raise HTTPException(status_code=422, detail=result["error"])
        if result["predicted_label"] == "UNKNOWN" and "no cargado" in str(result.get("note", "")).lower():
            raise HTTPException(status_code=503, detail=result.get("note", "Modelo no disponible"))

    # Save to history only when DB is usable and session provided
    if payload.session_id is not None:
        try:
            entry = HistoryEntry(
                user_id=payload.session_id,
                predicted_label=result["predicted_label"],
                spanish_text=result.get("spanish_text", ""),
                confidence=float(result.get("confidence", 0.0)),
                mode=payload.mode,
            )
            db.add(entry)
            await db.flush()
        except SQLAlchemyError:
            # Recognition should still work without DB/history persistence.
            pass

    return RecognitionResponse(
        predicted_label=result["predicted_label"],
        spanish_text=result.get("spanish_text", ""),
        confidence=float(result.get("confidence", 0.0)),
        mode=result.get("mode", payload.mode),
        timestamp=datetime.utcnow(),
        accepted=result.get("accepted"),
        top_k=result.get("top_k"),
        frames_received=result.get("frames_received"),
        latency_ms=result.get("latency_ms"),
    )


@router.get("/health")
async def health():
    return {"status": "ok", "service": "signia-backend", "models": get_model_status()}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "signia-backend"}
