"""SQLAlchemy models for agent state persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_path = Column(String(1024), nullable=False)
    status: Column[Any] = Column(
        Enum("pending", "running", "paused", "completed", "failed", name="session_status"),
        default="pending",
    )
    project_paused = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    manifest_json = Column(JSON, nullable=True)

    tasks = relationship("Task", back_populates="session", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    plugin_name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    status: Column[Any] = Column(
        Enum(
            "pending",
            "queued",
            "running",
            "completed",
            "failed",
            "blocked",
            "needs_human",
            name="task_status",
        ),
        default="pending",
    )
    priority = Column(Integer, default=0)
    depends_on = Column(JSON, default=list)  # list of task IDs
    result_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    human_question = Column(Text, nullable=True)
    human_answer = Column(Text, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    session = relationship("Session", back_populates="tasks")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    task_id = Column(String(36), nullable=True)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
