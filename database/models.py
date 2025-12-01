# models.py
from sqlalchemy import Column, Integer, DateTime, String, Text, Boolean, Float, BigInteger, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime
from typing import List

class Base(DeclarativeBase):
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Связь с сеансами
    sessions: Mapped[List["CallSession"]] = relationship("CallSession", back_populates="user")


class CallSession(Base):
    __tablename__ = "call_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=True)  # Название сеанса
    phone_numbers: Mapped[str] = mapped_column(Text)  # Номера через запятую
    knowledge_base: Mapped[str] = mapped_column(Text)  # База знаний
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft, active, completed, cancelled
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Связи
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    call_results: Mapped[List["CallResult"]] = relationship("CallResult", back_populates="session")


class CallResult(Base):
    __tablename__ = "call_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("call_sessions.id"))
    phone_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50))  # interested, not_interested, operator_request, no_answer, etc.
    interest_details: Mapped[str] = mapped_column(Text, nullable=True)  # Какие услуги заинтересовали
    notes: Mapped[str] = mapped_column(Text, nullable=True)  # Дополнительные заметки
    call_duration: Mapped[int] = mapped_column(Integer, nullable=True)  # Длительность звонка в секундах

    # Связи
    session: Mapped["CallSession"] = relationship("CallSession", back_populates="call_results")