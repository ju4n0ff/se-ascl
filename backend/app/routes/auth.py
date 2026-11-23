"""Registro y login (anti-enumeración, Argon2id, rate limiting)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limitar
from app.core.security import (
    create_access_token,
    hash_password_async,
    verify_password_async,
)
from app.db.models import User
from app.db.repositories import RegistroDuplicadoError, UserRepository
from app.db.session import get_db
from app.schemas.schemas import Token, UserCreate, UserLogin, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

MSG_REGISTRO_CONFLICTO = "No se pudo completar el registro con esos datos"
MSG_CREDENCIALES = "Credenciales inválidas"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limitar("register", "rate_limit_register_per_min"))],
)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    # El hash se calcula siempre antes de consultar: el tiempo de respuesta no
    # revela si el usuario o el email ya existían.
    password_hash = await hash_password_async(payload.password)

    repo = UserRepository(db)
    if await repo.existe_username_o_email(payload.username, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, MSG_REGISTRO_CONFLICTO)
    try:
        return await repo.crear(payload.username, payload.email, password_hash)
    except RegistroDuplicadoError as exc:  # carrera entre dos registros simultáneos
        raise HTTPException(status.HTTP_409_CONFLICT, MSG_REGISTRO_CONFLICTO) from exc


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(limitar("login", "rate_limit_login_per_min"))],
)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    user = await UserRepository(db).por_username(payload.username)

    # Si el usuario no existe se verifica contra un hash dummy (mismo costo Argon2id).
    valido = await verify_password_async(payload.password, user.password_hash if user else None)
    if user is None or not valido:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            MSG_CREDENCIALES,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
