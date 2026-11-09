from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from app.models.database import get_db
from app.models.entities import User
from app.schemas.schemas import UserCreate, UserResponse, Token
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Usuario o email ya existe")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return Token(access_token=token)
