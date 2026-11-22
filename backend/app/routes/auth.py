"""Registro y login (anti-enumeración, Argon2id, rate limiting)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limitar
from app.core.security import (
    create_access_token,
    hash_password_async,
    verify_password_async,
)
from app.db.models import User
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

    existente = await db.execute(
        select(User.id).where(or_(User.username == payload.username, User.email == payload.email))
    )
    if existente.first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, MSG_REGISTRO_CONFLICTO)

    user = User(username=payload.username, email=payload.email, password_hash=password_hash)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:  # carrera entre dos registros simultáneos
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, MSG_REGISTRO_CONFLICTO) from exc
    await db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(limitar("login", "rate_limit_login_per_min"))],
)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    resultado = await db.execute(select(User).where(User.username == payload.username))
    user = resultado.scalar_one_or_none()

    # Si el usuario no existe se verifica contra un hash dummy (mismo costo Argon2id).
    valido = await verify_password_async(payload.password, user.password_hash if user else None)
    if user is None or not valido:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            MSG_CREDENCIALES,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
