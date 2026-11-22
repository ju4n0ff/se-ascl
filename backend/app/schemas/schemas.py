from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

N_FEATURES_RAW = 1629
MIN_FRAMES_REST = 12
MAX_FRAMES_REST = 600


# Auth (se endurece en la Fase 3)
class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Reconocimiento v3
# allow_inf_nan=False rechaza NaN/Infinity durante el parseo (pydantic-core, en Rust).
FloatFinito = Annotated[float, Field(allow_inf_nan=False)]
Frame1629 = Annotated[
    list[FloatFinito], Field(min_length=N_FEATURES_RAW, max_length=N_FEATURES_RAW)
]


class RecognitionRequest(BaseModel):
    """Secuencia ``(N, 1629)`` con ``y`` isotrópica (``y * alto / ancho``), sin espejar."""

    model_config = ConfigDict(extra="forbid")

    frames: list[Frame1629] = Field(min_length=MIN_FRAMES_REST, max_length=MAX_FRAMES_REST)
    mode: Literal["dynamic", "static"] = "dynamic"
    top_k: int = Field(default=3, ge=1, le=5)
    # Solo tiene efecto con JWT válido y aceptada=True (Fase 3).
    save_history: bool = False


class Candidato(BaseModel):
    clase_raw: str
    texto: str
    es_pregunta: bool
    confianza: float


class RecognitionResponse(BaseModel):
    # Contrato v3
    aceptada: bool
    prediccion: Candidato
    top_k: list[Candidato]
    frames_recibidos: int
    latencia_ms: float
    # Compatibilidad con la tabla history
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: Literal["dynamic", "static"]
    timestamp: datetime


class ClaseInfo(BaseModel):
    indice: int
    clase_raw: str
    texto: str
    es_pregunta: bool


class ClasesResponse(BaseModel):
    total: int
    clases: list[ClaseInfo]


# History
class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: str
    created_at: datetime
