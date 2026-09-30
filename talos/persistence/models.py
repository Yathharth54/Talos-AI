"""SQLAlchemy models for the web app's history (spec 01 §5).

Postgres holds history only: sessions, messages, runs, run events and app
settings. Forged tools stay on disk in the vault. LangGraph's checkpoint
tables live in the same database but are created by `saver.setup()`, not
by these models or by Alembic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

# Tables owned by LangGraph's AsyncPostgresSaver.setup(). Alembic ignores them.
LANGGRAPH_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)

RUN_STATUSES = ("running", "waiting", "done", "failed", "stopped", "declined")
ACTIVE_RUN_STATUSES = ("running", "waiting")
MESSAGE_ROLES = ("user", "assistant")


class Base(DeclarativeBase):
    """Declarative base carrying the constraint naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> Any:
    return text("now()")


class Session(Base):
    """A chat session. One LangGraph thread per session."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="session", order_by="Run.n", passive_deletes=True
    )


class Run(Base):
    """One graph run: a user message and everything it caused."""

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("session_id", "n", name="uq_runs_session_id_n"),
        CheckConstraint(
            "status in ('running', 'waiting', 'done', 'failed', 'stopped', 'declined')",
            name="status",
        ),
        Index(
            "ix_runs_active",
            "status",
            postgresql_where=text("status in ('running', 'waiting')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    translator_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pending_interrupt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_gold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    forged: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    used: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[Session] = relationship(back_populates="runs")


class Message(Base):
    """A chat bubble. User text is stored escaped; assistant html is `answer.done.html`."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint("role in ('user', 'assistant')", name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    chips: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # clock_timestamp(), not now(): two messages written in one transaction
    # must still sort in the order they were added.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class RunEvent(Base):
    """One contract event (overview §4.1). `seq` is 1, 2, 3… per run, no gaps."""

    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )

    def envelope(self) -> dict[str, Any]:
        """The wire shape from overview §4.1: `{run_id, seq, ts, type, data}`."""
        return {
            "run_id": str(self.run_id),
            "seq": self.seq,
            "ts": format_ts(self.ts),
            "type": self.type,
            "data": self.data,
        }


class AppSetting(Base):
    """A key/value app setting. v1 has one key: `ask_before_exec`."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )


def format_ts(ts: datetime) -> str:
    """ISO 8601 UTC with milliseconds, e.g. `2026-09-30T14:23:55.120Z`."""
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic filter: never touch LangGraph's checkpoint tables."""
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    table = getattr(obj, "table", None)
    return not (table is not None and table.name in LANGGRAPH_TABLES)
