"""Modelos SQLAlchemy alineados 1:1 con ``backend/db/schema.sql``."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    history: Mapped[list[HistoryEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class HistoryEntry(Base):
    __tablename__ = "history"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="history_confidence_check"),
        CheckConstraint("mode IN ('static', 'dynamic')", name="history_mode_check"),
        Index("idx_history_user_id", "user_id"),
        Index("idx_history_created_at", "created_at", postgresql_ops={"created_at": "DESC"}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    predicted_label: Mapped[str] = mapped_column(String(50), nullable=False)
    spanish_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # "static" | "dynamic"
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="history")
