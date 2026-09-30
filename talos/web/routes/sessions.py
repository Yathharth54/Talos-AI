"""Sessions and sending a message (spec 02 §4 Sessions)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from talos.web.deps import get_manager, get_store, not_found
from talos.web.runner import RunManager
from talos.web.schemas import (
    MessageIn,
    MessageOut,
    RenameIn,
    RunSummaryOut,
    SessionDetailOut,
    SessionOut,
    SessionSummaryOut,
    StartRunOut,
)
from talos.web.store import Store

router = APIRouter()


@router.post("/sessions", status_code=201, response_model=SessionOut)
async def create_session(store: Store = Depends(get_store)) -> SessionOut:
    """A new session, or the newest empty one (empty sessions are reused, not piled up)."""
    for summary in await store.list_sessions():
        if summary.run_count == 0:
            existing = await store.get_session(summary.id)
            if existing is not None:
                return SessionOut.model_validate(existing)
    return SessionOut.model_validate(await store.create_session())


@router.get("/sessions", response_model=list[SessionSummaryOut])
async def list_sessions(store: Store = Depends(get_store)) -> list[SessionSummaryOut]:
    """Sessions with at least one run, newest first."""
    return [SessionSummaryOut.model_validate(s) for s in await store.list_sessions() if s.run_count]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session(session_id: uuid.UUID, store: Store = Depends(get_store)) -> SessionDetailOut:
    """One session with its messages and runs.

    Raises:
        ApiError: 404 `not_found` when there is no such session.
    """
    session = await store.get_session(session_id)
    if session is None:
        raise not_found("Session")
    return SessionDetailOut(
        session=SessionOut.model_validate(session),
        messages=[MessageOut.model_validate(m) for m in await store.list_messages(session_id)],
        runs=[RunSummaryOut.model_validate(r) for r in await store.list_runs(session_id)],
    )


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID, body: RenameIn, store: Store = Depends(get_store)
) -> SessionOut:
    """Rename a session.

    Raises:
        ApiError: 404 `not_found` when there is no such session.
    """
    session = await store.rename_session(session_id, body.name)
    if session is None:
        raise not_found("Session")
    return SessionOut.model_validate(session)


@router.post("/sessions/{session_id}/messages", status_code=202, response_model=StartRunOut)
async def send_message(
    session_id: uuid.UUID, body: MessageIn, manager: RunManager = Depends(get_manager)
) -> StartRunOut:
    """Start a run. 409 `run_active` while any run is running or waiting."""
    started = await manager.start(session_id, body.text)
    return StartRunOut(
        run=RunSummaryOut.model_validate(started.run),
        message=MessageOut.model_validate(started.message),
    )
