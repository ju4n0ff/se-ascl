"""Perfil del usuario autenticado: leer, actualizar y borrar la propia cuenta.

No hay rutas por ``id``: el usuario sale siempre del JWT, así que no existe un
identificador que manipular (anti-BOLA por diseño).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limitar
from app.core.security import get_current_user, hash_password_async, verify_password_async
from app.db.models import User
from app.db.repositories import RegistroDuplicadoError, UserRepository
from app.db.session import get_db
from app.routes.auth import MSG_CREDENCIALES
from app.schemas.schemas import UserResponse, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])

MSG_ACTUALIZACION_CONFLICTO = "No se pudo completar la actualización con esos datos"


def _credenciales_invalidas() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, MSG_CREDENCIALES, headers={"WWW-Authenticate": "Bearer"}
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    dependencies=[Depends(limitar("users_me", "rate_limit_profile_per_min"))],
)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Se reautentica antes de consultar nada: sin la contraseña actual, un token robado
    # no sirve para tomar la cuenta ni para sondear emails con el 409.
    if not await verify_password_async(payload.current_password, current_user.password_hash):
        raise _credenciales_invalidas()

    nuevo_hash = await hash_password_async(payload.new_password) if payload.new_password else None
    try:
        # El UNIQUE de la base decide el conflicto: sin ventana entre consultar y actualizar.
        user = await UserRepository(db).actualizar(
            current_user.id, email=payload.email, password_hash=nuevo_hash
        )
    except RegistroDuplicadoError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, MSG_ACTUALIZACION_CONFLICTO) from exc
    if user is None:  # la cuenta se borró entre la autenticación y el UPDATE
        raise _credenciales_invalidas()
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Derecho de supresión (Ley 21.719): borra la cuenta y, en cascada, su historial."""
    await UserRepository(db).borrar(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
