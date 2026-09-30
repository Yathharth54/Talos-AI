"""Storage for the web layer: one interface, a Postgres and an in-memory version.

`PgStore` wraps the stage 1 repo functions; every method is its own short
transaction (`session_scope`), so no DB session is ever shared with a
request or a run task that might be cancelled, and `append_event` holds
the run row lock only for one insert.

`MemoryStore` keeps the same rows as transient ORM objects in dicts. It
exists so the route, SSE and runner tests run without a database; the
contract tests in `tests/web/test_store.py` run against both.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.models import (
    ACTIVE_RUN_STATUSES,
    MESSAGE_ROLES,
    RUN_STATUSES,
    Message,
    Run,
    RunEvent,
    Session,
)
from talos.persistence.recovery import RECOVERY_ERROR, RECOVERY_SUMMARY, recover_runs
from talos.persistence.repo import TERMINAL_STATUSES, SessionSummary, summarise_session


class Store(Protocol):
    """What the web layer needs from storage. Each call is one transaction."""

    async def ping(self) -> bool: ...
    async def create_session(self) -> Session: ...
    async def get_session(self, session_id: uuid.UUID) -> Session | None: ...
    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None: ...
    async def list_sessions(self) -> list[SessionSummary]: ...
    async def list_messages(self, session_id: uuid.UUID) -> list[Message]: ...
    async def list_runs(self, session_id: uuid.UUID) -> list[Run]: ...
    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]: ...
    async def get_run(self, run_id: uuid.UUID) -> Run | None: ...
    async def active_runs(self) -> list[Run]: ...
    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run: ...
    async def append_event(
        self, run_id: uuid.UUID, type_: str, data: dict[str, Any]
    ) -> RunEvent: ...
    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]: ...
    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message: ...
    async def get_setting(self, key: str, default: Any = None) -> Any: ...
    async def set_setting(self, key: str, value: Any) -> None: ...
    async def recover(self) -> list[uuid.UUID]: ...


class PgStore:
    """`Store` on Postgres through `talos.persistence.repo`.

    Args:
        factory: The session factory from `init_db()`.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    def _tx(self):  # noqa: ANN202 - async context manager
        return session_scope(self._factory)

    async def ping(self) -> bool:
        try:
            async with self._tx() as db:
                await db.execute(text("select 1"))
        except Exception:  # noqa: BLE001 - health reports it, never raises
            return False
        return True

    async def create_session(self) -> Session:
        async with self._tx() as db:
            return await repo.create_session(db)

    async def get_session(self, session_id: uuid.UUID) -> Session | None:
        async with self._tx() as db:
            return await repo.get_session(db, session_id)

    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None:
        async with self._tx() as db:
            return await repo.rename_session(db, session_id, name)

    async def list_sessions(self) -> list[SessionSummary]:
        async with self._tx() as db:
            return await repo.list_sessions(db)

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        async with self._tx() as db:
            return await repo.list_messages(db, session_id)

    async def list_runs(self, session_id: uuid.UUID) -> list[Run]:
        async with self._tx() as db:
            return await repo.list_runs(db, session_id)

    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]:
        async with self._tx() as db:
            run = await repo.create_run(db, session_id, query)
            message = await repo.add_message(db, session_id, "user", user_html, run_id=run.id)
            if rename_to:
                await repo.rename_session(db, session_id, rename_to)
            return run, message

    async def get_run(self, run_id: uuid.UUID) -> Run | None:
        async with self._tx() as db:
            return await repo.get_run(db, run_id)

    async def active_runs(self) -> list[Run]:
        async with self._tx() as db:
            return await repo.active_runs(db)

    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
        async with self._tx() as db:
            return await repo.set_run_status(db, run_id, status, **fields)

    async def append_event(self, run_id: uuid.UUID, type_: str, data: dict[str, Any]) -> RunEvent:
        async with self._tx() as db:
            return await repo.append_event(db, run_id, type_, data)

    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
        async with self._tx() as db:
            return await repo.events_after(db, run_id, seq)

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message:
        async with self._tx() as db:
            return await repo.add_message(db, session_id, role, html, note, chips, run_id)

    async def get_setting(self, key: str, default: Any = None) -> Any:
        async with self._tx() as db:
            return await repo.get_setting(db, key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        async with self._tx() as db:
            await repo.set_setting(db, key, value)

    async def recover(self) -> list[uuid.UUID]:
        async with self._tx() as db:
            return await recover_runs(db)


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    """`Store` in process memory, with the same rules as the repo functions."""

    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        self.runs: dict[uuid.UUID, Run] = {}
        self.messages: list[Message] = []
        self.events: dict[uuid.UUID, list[RunEvent]] = {}
        self.settings: dict[str, Any] = {}

    async def ping(self) -> bool:
        return True

    async def create_session(self) -> Session:
        number = max((s.number for s in self.sessions.values()), default=0) + 1
        sid = uuid.uuid4()
        now = _now()
        row = Session(
            id=sid,
            name=f"Session {number}",
            number=number,
            thread_id=f"session-{sid}",
            created_at=now,
            updated_at=now,
        )
        row.runs = []
        self.sessions[sid] = row
        return row

    async def get_session(self, session_id: uuid.UUID) -> Session | None:
        return self.sessions.get(session_id)

    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None:
        row = self.sessions.get(session_id)
        if row is not None:
            row.name = name
            row.updated_at = _now()
        return row

    async def list_sessions(self) -> list[SessionSummary]:
        rows = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.number), reverse=True)
        return [summarise_session(s) for s in rows]

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        return [m for m in self.messages if m.session_id == session_id]

    async def list_runs(self, session_id: uuid.UUID) -> list[Run]:
        return sorted((r for r in self.runs.values() if r.session_id == session_id), key=_n)

    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]:
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"session {session_id} not found")
        n = max((r.n for r in session.runs), default=0) + 1
        run = Run(
            id=uuid.uuid4(),
            session_id=session_id,
            n=n,
            query=query,
            status="running",
            summary_gold=False,
            forged=[],
            used=[],
            failed=False,
            started_at=_now(),
        )
        self.runs[run.id] = run
        self.events[run.id] = []
        session.runs.append(run)
        session.updated_at = _now()
        message = await self.add_message(session_id, "user", user_html, run_id=run.id)
        if rename_to:
            session.name = rename_to
        return run, message

    async def get_run(self, run_id: uuid.UUID) -> Run | None:
        return self.runs.get(run_id)

    async def active_runs(self) -> list[Run]:
        return [r for r in self.runs.values() if r.status in ACTIVE_RUN_STATUSES]

    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        run = self.runs.get(run_id)
        if run is None:
            raise LookupError(f"run {run_id} not found")
        run.status = status
        for name, value in fields.items():
            setattr(run, name, list(value) if name in {"forged", "used"} else value)
        if status in TERMINAL_STATUSES and "finished_at" not in fields:
            run.finished_at = _now()
        return run

    async def append_event(self, run_id: uuid.UUID, type_: str, data: dict[str, Any]) -> RunEvent:
        if run_id not in self.runs:
            raise LookupError(f"run {run_id} not found")
        events = self.events[run_id]
        event = RunEvent(run_id=run_id, seq=len(events) + 1, type=type_, data=data, ts=_now())
        events.append(event)
        return event

    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
        return [e for e in self.events.get(run_id, []) if e.seq > seq]

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message:
        if role not in MESSAGE_ROLES:
            raise ValueError(f"unknown message role {role!r}")
        message = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            run_id=run_id,
            role=role,
            html=html,
            note=note,
            chips=[dict(c) for c in chips],
            created_at=_now(),
        )
        self.messages.append(message)
        return message

    async def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value

    async def recover(self) -> list[uuid.UUID]:
        stale = sorted(
            (r for r in self.runs.values() if r.status == "running"), key=lambda r: r.started_at
        )
        for run in stale:
            await self.set_run_status(
                run.id, "failed", error=RECOVERY_ERROR, summary=RECOVERY_SUMMARY
            )
            await self.append_event(run.id, "error", {"message": RECOVERY_ERROR})
            await self.append_event(
                run.id,
                "run.finished",
                {
                    "status": "failed",
                    "summary": RECOVERY_SUMMARY,
                    "summary_gold": False,
                    "forged": list(run.forged),
                    "used": list(run.used),
                },
            )
        return [r.id for r in stale]


def _n(run: Run) -> int:
    return run.n
