"""Hashing Argon2id, JWT estricto y dependencias de usuario autenticado."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ALGORITMOS_JWT_PERMITIDOS, get_settings
from app.db.models import User
from app.db.session import get_db

TOKEN_TYPE_ACCESS = "access"
CLAIMS_REQUERIDOS = ["sub", "exp", "iat", "jti", "type"]

# Argon2id (variante por defecto de argon2-cffi) con los parámetros recomendados por pwdlib.
_hasher = PasswordHash((Argon2Hasher(),))
# Hash de referencia para igualar el tiempo de respuesta cuando el usuario no existe.
_HASH_DUMMY = _hasher.hash(uuid.uuid4().hex)

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Pega el access_token obtenido en POST /api/auth/login",
)


# ----------------------------------------------------------------- contraseñas
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(plain, hashed)
    except Exception:
        # Hash con formato desconocido (p. ej. bcrypt legado o placeholder): nunca autentica.
        return False


def verify_dummy(plain: str) -> None:
    """Gasta el mismo tiempo que una verificación real (mitiga enumeración por timing)."""
    _hasher.verify(plain, _HASH_DUMMY)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain: str, hashed: str | None) -> bool:
    if hashed is None:
        await asyncio.to_thread(verify_dummy, plain)
        return False
    return await asyncio.to_thread(verify_password, plain, hashed)


# ------------------------------------------------------------------------- JWT
def create_access_token(user_id: int) -> str:
    settings = get_settings()
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": uuid.uuid4().hex,
        "type": TOKEN_TYPE_ACCESS,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> int:
    """Devuelve el ``user_id`` o lanza ``ValueError`` si el token no es válido."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=ALGORITMOS_JWT_PERMITIDOS,
            options={"require": CLAIMS_REQUERIDOS},
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Token inválido") from exc
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise ValueError("Tipo de token inválido")
    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Claim sub inválido") from exc


def _no_autorizado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def usuario_desde_token(token: str, db: AsyncSession) -> User | None:
    try:
        user_id = decode_access_token(token)
    except ValueError:
        return None
    return await db.get(User, user_id)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if cred is None or cred.scheme.lower() != "bearer":
        raise _no_autorizado()
    user = await usuario_desde_token(cred.credentials, db)
    if user is None:
        raise _no_autorizado()
    return user


async def get_current_user_optional(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Sin header -> anónimo. Con un token presente pero inválido -> 401 explícito."""
    if cred is None:
        return None
    return await get_current_user(cred, db)
