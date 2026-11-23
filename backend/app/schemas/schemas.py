from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

N_FEATURES_RAW = 1629
MIN_FRAMES_REST = 12
MAX_FRAMES_REST = 600

PATRON_USERNAME = r"^[a-zA-Z0-9_.-]{3,50}$"
PASSWORD_MIN = 8
PASSWORD_MAX = 128  # tope también para no gastar CPU hasheando strings enormes
TEXTO_MAX = 500


def _politica_password(valor: str) -> str:
    if not re.search(r"[a-z]", valor):
        raise ValueError("La contraseña requiere al menos una minúscula")
    if not re.search(r"[A-Z]", valor):
        raise ValueError("La contraseña requiere al menos una mayúscula")
    if not re.search(r"\d", valor):
        raise ValueError("La contraseña requiere al menos un dígito")
    return valor


def _sin_caracteres_de_control(valor: str) -> str:
    # PostgreSQL no admite NUL en texto: sin este filtro la consulta terminaría en 500.
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", valor):
        raise ValueError("El texto contiene caracteres de control no permitidos")
    return valor


# Compartidos por registro y actualización: una sola política para ambos.
EmailNormalizado = Annotated[EmailStr, Field(max_length=100), AfterValidator(str.lower)]
PasswordFuerte = Annotated[
    str, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX), AfterValidator(_politica_password)
]
TextoHistorial = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXTO_MAX),
    AfterValidator(_sin_caracteres_de_control),
]


# Auth
class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    username: str = Field(pattern=PATRON_USERNAME)
    email: EmailNormalizado
    password: PasswordFuerte


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Sin PATRON_USERNAME: un nombre que no lo cumple recibe el mismo 401 genérico.
    username: Annotated[
        str, Field(min_length=1, max_length=50), AfterValidator(_sin_caracteres_de_control)
    ]
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str


class UserUpdate(BaseModel):
    """Cambio de email y/o contraseña; siempre exige la contraseña actual."""

    model_config = ConfigDict(extra="forbid")

    email: EmailNormalizado | None = None
    new_password: PasswordFuerte | None = None
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)

    @model_validator(mode="after")
    def _al_menos_un_cambio(self) -> UserUpdate:
        if self.email is None and self.new_password is None:
            raise ValueError("Debe indicar email y/o new_password")
        return self


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Reconocimiento v3
# allow_inf_nan=False rechaza NaN/Infinity durante el parseo (pydantic-core, en Rust);
# strict=True impide que strings como "0.1" se conviertan a float.
FloatFinito = Annotated[float, Field(allow_inf_nan=False, strict=True)]
Frame1629 = Annotated[
    list[FloatFinito], Field(min_length=N_FEATURES_RAW, max_length=N_FEATURES_RAW)
]


class RecognitionRequest(BaseModel):
    """Secuencia ``(N, 1629)`` con ``y`` isotrópica (``y * alto / ancho``), sin espejar."""

    model_config = ConfigDict(extra="forbid")

    frames: list[Frame1629] = Field(min_length=MIN_FRAMES_REST, max_length=MAX_FRAMES_REST)
    mode: Literal["dynamic", "static"] = "dynamic"
    top_k: int = Field(default=3, ge=1, le=5)
    # Solo persiste con JWT válido y aceptada=True.
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
    guardado_en_historial: bool = False


class ClaseInfo(BaseModel):
    indice: int
    clase_raw: str
    texto: str
    es_pregunta: bool


class ClasesResponse(BaseModel):
    total: int
    clases: list[ClaseInfo]


# History
class HistoryUpdate(BaseModel):
    """Solo el texto es editable: lo que predijo el modelo queda inmutable."""

    model_config = ConfigDict(extra="forbid")

    spanish_text: TextoHistorial


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    predicted_label: str
    spanish_text: str
    confidence: float
    mode: str
    created_at: datetime
