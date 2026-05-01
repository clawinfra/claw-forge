"""SQLAlchemy models for agent state persistence."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

_logger = logging.getLogger(__name__)


class SafeJSON(TypeDecorator[Any]):
    """JSON column that survives truncated / corrupt payloads.

    On read, if ``json.loads`` raises ``JSONDecodeError`` the column
    returns *fallback* (default ``None``) instead of crashing the
    entire request.  Writes are passed through unchanged.

    Overrides ``result_processor`` rather than ``process_result_value``
    because SQLAlchemy's base ``JSON`` type deserializes in its own
    result processor — if that throws, the TypeDecorator wrapper never
    gets called.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, *args: Any, fallback: Any = None, **kwargs: Any) -> None:
        self._fallback = fallback
        super().__init__(*args, **kwargs)

    def result_processor(self, dialect: Any, coltype: Any) -> Any:  # noqa: ANN401
        base_processor = self.impl_instance.result_processor(dialect, coltype)
        fallback = self._fallback

        def _safe_processor(value: Any) -> Any:  # noqa: ANN401
            if value is None:
                return value
            if base_processor is not None:
                try:
                    return base_processor(value)
                except (json.JSONDecodeError, ValueError):
                    _logger.warning(
                        "Corrupt JSON in DB column (returning fallback): "
                        "%.80s…",
                        value,
                    )
                    return fallback
            # No base processor — try manual parse for string values
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    _logger.warning(
                        "Corrupt JSON in DB column (returning fallback): "
                        "%.80s…",
                        value,
                    )
                    return fallback
            return value

        return _safe_processor


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
    )
    project_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    manifest_json: Mapped[dict[str, Any] | None] = mapped_column(
        SafeJSON(fallback=None), nullable=True,
    )

    tasks = relationship("Task", back_populates="session", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False)
    plugin_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    depends_on: Mapped[list[str]] = mapped_column(
        SafeJSON(fallback=[]), default=list,
    )
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    steps: Mapped[list[str]] = mapped_column(
        SafeJSON(fallback=[]), default=list, nullable=False,
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        SafeJSON(fallback=None), nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    active_subagents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parent_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bugfix_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    touches_files: Mapped[list[str]] = mapped_column(
        SafeJSON(fallback=[]), default=list, nullable=False,
    )
    merged_to_main: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session = relationship("Session", back_populates="tasks")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(SafeJSON(fallback=None), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class FileClaim(Base):
    """A live claim by a running task on a single file path.

    The ``UNIQUE(session_id, file_path)`` constraint provides atomic
    claim semantics: an INSERT inside a transaction either succeeds for
    all rows or rolls back, so two tasks racing for the same file see a
    deterministic winner.
    """

    __tablename__ = "file_claims"
    __table_args__ = (
        UniqueConstraint("session_id", "file_path", name="uq_file_claim_session_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC),
    )
