from pydantic import BaseModel
from datetime import datetime
from typing import Optional


# Auth
class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Landmarks / Recognition
class LandmarkPoint(BaseModel):
    x: float
    y: float
    z: float


class HandLandmarks(BaseModel):
    landmarks: list[LandmarkPoint]  # 21 points
    handedness: str  # "Left" or "Right"


class FaceLandmarks(BaseModel):
    landmarks: list[LandmarkPoint]  # 468 points (MediaPipe Face)


class RecognitionRequest(BaseModel):
    mode: str  # "static" (deletreo) or "dynamic" (conversacion)
    hands: list[HandLandmarks]  # 1-2 hands
    face: Optional[FaceLandmarks] = None
    session_id: Optional[int] = None


class RecognitionResponse(BaseModel):
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: str
    timestamp: datetime


# History
class HistoryCreate(BaseModel):
    user_id: int
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: str


class HistoryResponse(BaseModel):
    id: int
    user_id: int
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: str
    created_at: datetime

    class Config:
        from_attributes = True
