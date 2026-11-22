"""Persistencia de predicciones en ``history``.

Solo se guardan la etiqueta, el texto, la confianza y el modo: nunca frames ni
landmarks (cero persistencia biométrica).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HistoryEntry
from app.ml.predictor import campos_history

MAX_LARGO_ETIQUETA = 50  # VARCHAR(50) en schema.sql


def debe_guardarse(user_id: int | None, save_history: bool, resultado: dict[str, Any]) -> bool:
    return user_id is not None and save_history and bool(resultado.get("aceptada"))


async def guardar_prediccion(
    db: AsyncSession, user_id: int, resultado: dict[str, Any], mode: str
) -> None:
    campos = campos_history(resultado, mode)
    db.add(
        HistoryEntry(
            user_id=user_id,
            predicted_label=campos["predicted_label"][:MAX_LARGO_ETIQUETA],
            spanish_text=campos["spanish_text"],
            confidence=min(max(float(campos["confidence"]), 0.0), 1.0),
            mode=mode,
        )
    )
    await db.flush()
