"""Runs: status, the SSE event stream, resume and stop (spec 02 §4 Runs, §5)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from talos.web.deps import get_manager, get_store, not_found
from talos.web.runner import RunManager
from talos.web.schemas import PendingOut, ResumeIn, RunOut, RunSummaryOut, pending_payload
from talos.web.security import remember_secret
from talos.web.store import Store

router = APIRouter()

HEARTBEAT_S = 15


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, store: Store = Depends(get_store)) -> RunOut:
    """The run summary, plus the browser-safe pending interrupt when paused."""
    run = await store.get_run(run_id)
    if run is None:
        raise not_found("Run")
    pending = None
    if run.status == "waiting" and run.pending_interrupt:
        # Built by hand from the stored interrupt: only browser-safe fields (never args/kwargs).
        pending = PendingOut(
            kind=str(run.pending_interrupt.get("type")),
            payload=pending_payload(run.pending_interrupt),
        )
    summary = RunSummaryOut.model_validate(run)
    return RunOut(**summary.model_dump(), pending=pending)


def _after(last_event_id: str | None, after: int | None) -> int:
    for value in (last_event_id, after):
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: uuid.UUID,
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None),
    manager: RunManager = Depends(get_manager),
    store: Store = Depends(get_store),
) -> EventSourceResponse:
    """SSE: backlog after `Last-Event-ID` (or `?after=N`), then live events.

    Each event is `id: {seq}`, `event: {type}`, `data: {envelope}`. The
    stream stays open through pauses and closes after `run.finished`.
    """
    if await store.get_run(run_id) is None:
        raise not_found("Run")

    async def stream() -> AsyncIterator[ServerSentEvent]:
        events = manager.subscribe(run_id, _after(last_event_id, after))
        try:
            async for envelope in events:
                yield ServerSentEvent(
                    id=str(envelope["seq"]),
                    event=envelope["type"],
                    data=json.dumps(envelope, separators=(",", ":")),
                )
        finally:
            await events.aclose()  # a client disconnect must release the subscriber queue

    return EventSourceResponse(
        stream(),
        ping=HEARTBEAT_S,
        ping_message_factory=lambda: ServerSentEvent(comment="keep-alive"),
        sep="\n",
    )


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(
    run_id: uuid.UUID, body: ResumeIn, manager: RunManager = Depends(get_manager)
) -> dict[str, bool]:
    """Answer a pause. 409 `not_waiting`; 422 if the decision doesn't fit."""
    if body.decision == "save":
        remember_secret(body.value)
    await manager.resume(run_id, body.decision, body.value)
    return {"ok": True}


@router.post("/runs/{run_id}/stop", status_code=202)
async def stop_run(
    run_id: uuid.UUID, manager: RunManager = Depends(get_manager)
) -> dict[str, bool]:
    """Stop a run (also during a pause). No-op if it already finished."""
    await manager.stop(run_id)
    return {"ok": True}
