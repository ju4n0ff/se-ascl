from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    history = relationship("HistoryEntry", back_populates="user", cascade="all, delete-orphan")


class HistoryEntry(Base):
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    predicted_label = Column(String(50), nullable=False)
    spanish_text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    mode = Column(String(20), nullable=False)  # "static" or "dynamic"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="history")
