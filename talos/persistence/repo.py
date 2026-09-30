"""Repository functions: plain async reads and writes, no business logic.

Every function takes an `AsyncSession` first and never commits. Callers own
the transaction (`session_scope()` or `get_db()` in `talos.persistence.db`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from talos.persistence.models import (
    ACTIVE_RUN_STATUSES,
    MESSAGE_ROLES,
    RUN_STATUSES,
    AppSetting,
    Message,
    Run,
    RunEvent,
    Session,
)

# Any fixed number works; it only has to be the same for every caller.
_SESSION_NUMBER_LOCK = 7_140_001

TERMINAL_STATUSES = frozenset({"done", "failed", "stopped", "declined"})

# Run columns `set_run_status` may write besides `status`.
_RUN_FIELDS = frozenset(
    {
        "translator_state",
        "pending_interrupt",
        "summary",
        "summary_gold",
        "forged",
        "used",
        "failed",
        "error",
        "finished_at",
    }
)

RunMarkKind = Literal["forged", "reused", "failed"]


@dataclass(frozen=True)
class RunMark:
    """One of the first three runs shown on a Sessions page card."""

    n: int
    query: str
    mark: RunMarkKind | None


@dataclass(frozen=True)
class SessionSummary:
    """What the Sessions page needs for one session (spec 01 §6)."""

    id: uuid.UUID
    name: str
    created_at: datetime
    run_count: int
    forged: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    runs: list[RunMark] = field(default_factory=list)


# ---- sessions -------------------------------------------------------------


async def create_session(db: AsyncSession) -> Session:
    """Create `Session {n}` with the next number and its own LangGraph thread."""
    # Serialise numbering across concurrent callers for this transaction.
    await db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _SESSION_NUMBER_LOCK})
    number = (await db.scalar(select(func.coalesce(func.max(Session.number), 0)))) + 1
    session_id = uuid.uuid4()
    row = Session(
        id=session_id,
        name=f"Session {number}",
        number=number,
        thread_id=f"session-{session_id}",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    """The session, or None."""
    return await db.get(Session, session_id)


async def rename_session(db: AsyncSession, session_id: uuid.UUID, name: str) -> Session | None:
    """Set a session's name. Returns None if it doesn't exist."""
    row = await db.get(Session, session_id)
    if row is None:
        return None
    row.name = name
    row.updated_at = func.now()
    await db.flush()
    await db.refresh(row)
    return row


async def list_sessions(db: AsyncSession) -> list[SessionSummary]:
    """Every session, newest first, with its Sessions-page summary."""
    rows = (
        await db.scalars(
            select(Session)
            .options(selectinload(Session.runs))
            .order_by(Session.created_at.desc(), Session.number.desc())
        )
    ).all()
    return [summarise_session(s) for s in rows]


def summarise_session(s: Session) -> SessionSummary:
    """Build a SessionSummary from a session with its runs loaded."""
    runs = sorted(s.runs, key=lambda r: r.n)
    forged = _distinct(name for r in runs for name in r.forged)
    used = [name for name in _distinct(n for r in runs for n in r.used) if name not in forged]
    return SessionSummary(
        id=s.id,
        name=s.name,
        created_at=s.created_at,
        run_count=len(runs),
        forged=forged,
        used=used,
        runs=[RunMark(n=r.n, query=r.query, mark=run_mark(r)) for r in runs[:3]],
    )


def run_mark(run: Run) -> RunMarkKind | None:
    """The mark a run gets on a Sessions card.

    A failure wins (the demo shows the red mark even if a tool was reused),
    then a forge, then a reuse.
    """
    if run.failed or run.status == "failed":
        return "failed"
    if run.forged:
        return "forged"
    if run.used:
        return "reused"
    return None


def _distinct(names: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)


# ---- runs -----------------------------------------------------------------


async def create_run(db: AsyncSession, session_id: uuid.UUID, query: str) -> Run:
    """Start a run with the session's next `n` and bump the session's `updated_at`.

    Raises:
        LookupError: The session doesn't exist.
    """
    locked = await db.scalar(select(Session.id).where(Session.id == session_id).with_for_update())
    if locked is None:
        raise LookupError(f"session {session_id} not found")
    n = (
        await db.scalar(
            select(func.coalesce(func.max(Run.n), 0)).where(Run.session_id == session_id)
        )
    ) + 1
    run = Run(session_id=session_id, n=n, query=query, status="running")
    db.add(run)
    await db.execute(update(Session).where(Session.id == session_id).values(updated_at=func.now()))
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: uuid.UUID) -> Run | None:
    """The run, or None."""
    return await db.get(Run, run_id)


async def list_runs(db: AsyncSession, session_id: uuid.UUID) -> list[Run]:
    """A session's runs in order (n ascending)."""
    return list(
        (await db.scalars(select(Run).where(Run.session_id == session_id).order_by(Run.n))).all()
    )


async def set_run_status(db: AsyncSession, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
    """Set a run's status and any of its result columns.

    A terminal status (done, failed, stopped, declined) also stamps
    `finished_at` unless the caller passed one.

    Args:
        db: The session.
        run_id: The run.
        status: One of `RUN_STATUSES`.
        **fields: Any of translator_state, pending_interrupt, summary,
            summary_gold, forged, used, failed, error, finished_at.

    Raises:
        ValueError: Unknown status or field.
        LookupError: The run doesn't exist.
    """
    if status not in RUN_STATUSES:
        raise ValueError(f"unknown run status {status!r}")
    unknown = set(fields) - _RUN_FIELDS
    if unknown:
        raise ValueError(f"set_run_status can't set {sorted(unknown)}")
    run = await db.get(Run, run_id, with_for_update=True)
    if run is None:
        raise LookupError(f"run {run_id} not found")
    run.status = status
    for name, value in fields.items():
        setattr(run, name, list(value) if name in {"forged", "used"} else value)
    if status in TERMINAL_STATUSES and "finished_at" not in fields:
        run.finished_at = func.now()
    await db.flush()
    await db.refresh(run)
    return run


async def active_runs(db: AsyncSession) -> list[Run]:
    """Runs that are `running` or `waiting`, anywhere in the app."""
    return list(
        (
            await db.scalars(
                select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES)).order_by(Run.started_at)
            )
        ).all()
    )


# ---- run events -------------------------------------------------------------


async def append_event(
    db: AsyncSession, run_id: uuid.UUID, type: str, data: dict[str, Any]
) -> RunEvent:
    """Append a contract event with the run's next `seq`.

    The run row is locked `FOR UPDATE` first, so concurrent appends to the
    same run queue up and `seq` has no gaps or duplicates. The lock is held
    until the caller's transaction ends, so keep that transaction short.

    Raises:
        LookupError: The run doesn't exist.
    """
    locked = await db.scalar(select(Run.id).where(Run.id == run_id).with_for_update())
    if locked is None:
        raise LookupError(f"run {run_id} not found")
    seq = (
        await db.scalar(
            select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run_id)
        )
    ) + 1
    event = RunEvent(run_id=run_id, seq=seq, type=type, data=data)
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def events_after(db: AsyncSession, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
    """A run's events with `seq > seq`, in order."""
    return list(
        (
            await db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > seq)
                .order_by(RunEvent.seq)
            )
        ).all()
    )


# ---- messages -----------------------------------------------------------------


async def add_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    html: str,
    note: str | None = None,
    chips: Sequence[dict[str, Any]] = (),
    run_id: uuid.UUID | None = None,
) -> Message:
    """Add a chat message. The caller escapes user text before passing it as `html`.

    Raises:
        ValueError: `role` isn't "user" or "assistant".
    """
    if role not in MESSAGE_ROLES:
        raise ValueError(f"unknown message role {role!r}")
    message = Message(
        session_id=session_id,
        run_id=run_id,
        role=role,
        html=html,
        note=note,
        chips=[dict(c) for c in chips],
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def list_messages(db: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    """A session's messages, oldest first."""
    return list(
        (
            await db.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
    )


# ---- app settings ---------------------------------------------------------------


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    """A setting's JSON value, or `default` when it was never set."""
    row = await db.get(AppSetting, key, populate_existing=True)
    return default if row is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Insert or replace a setting's JSON value."""
    stmt = pg_insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await db.execute(stmt)
