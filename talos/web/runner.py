"""RunManager: one background task per active run, fan-out to SSE subscribers.

A run is driven by a `Driver`: `GraphDriver` for the real graph (through
`EventTranslator`), `FakeDriver` (fake_graph.py) for TALOS_FAKE_GRAPH=1.
The manager owns everything drivers share:

- the one-active-run lock (the vault and .env are shared files),
- persisting each event (`store.append_event` allocates `seq`) and only
  then publishing it to subscribers,
- pausing: the interrupt value goes to `runs.pending_interrupt`, the run
  becomes `waiting`, and no task is held while it waits,
- resuming, stopping, and the exception path.

Driver state (strip, attempts, tools) is a JSON dict saved as
`runs.translator_state` at every pause and at the end.
"""

from __future__ import annotations

import asyncio
import html
import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from talos.agents.executor import PRIMITIVES
from talos.persistence.models import Message, Run
from talos.persistence.repo import TERMINAL_STATUSES
from talos.vault.manager import SkillManager
from talos.web import copy
from talos.web.board import Board
from talos.web.naming import session_name
from talos.web.schemas import pending_payload
from talos.web.store import Store
from talos.web.translator import STREAM_MODES, EventTranslator

log = logging.getLogger(__name__)


# ---- errors the routes turn into HTTP codes -------------------------------------


class RunError(Exception):
    """Base for run errors that map to an API error code."""

    code = "run_error"
    status = 400
    extra: dict[str, str] = {}


class RunActive(RunError):
    """Another run is going. `extra` names it so the browser can open it."""

    code, status = "run_active", 409

    def __init__(self, active: Run | None = None) -> None:
        super().__init__("A run is already going. Stop it or wait for it to finish.")
        if active is not None:
            self.extra = {"run_id": str(active.id), "session_id": str(active.session_id)}


class NotWaiting(RunError):
    code, status = "not_waiting", 409

    def __init__(self) -> None:
        super().__init__("This run isn't waiting for an answer.")


class BadDecision(RunError):
    code, status = "bad_decision", 422


class NotFound(RunError):
    code, status = "not_found", 404


# ---- driver protocol --------------------------------------------------------------


@dataclass(frozen=True)
class Resume:
    """The user's answer to a pause.

    `value` is what the graph resumes with. For a saved key it is the key
    itself: it goes to the graph and nowhere else (no events, no logs).
    """

    kind: str
    decision: str
    value: Any


@dataclass(frozen=True)
class Pause:
    """A driver paused: `value` is the full interrupt value (server side only)."""

    kind: str
    value: dict[str, Any]


Emitted = tuple[str, dict[str, Any]]


class Driver(Protocol):
    """Produces a run's contract events. Mutates `state` in place."""

    def initial_state(self) -> dict[str, Any]: ...

    def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]: ...


def signature_text(fn: Callable[..., Any]) -> str:
    """`python_exec(code: str, timeout: int | None = None) -> dict` for a primitive."""
    sig = inspect.signature(fn)
    params = []
    for p in sig.parameters.values():
        ann = p.annotation
        ann_text = ann if isinstance(ann, str) else getattr(ann, "__name__", "")
        text = f"{p.name}: {ann_text}" if ann is not inspect.Parameter.empty else p.name
        if p.default is not inspect.Parameter.empty:
            text += f" = {p.default!r}"
        params.append(text)
    ret = sig.return_annotation
    ret_text = ret if isinstance(ret, str) else getattr(ret, "__name__", "")
    out = f"{fn.__name__}({', '.join(params)})"
    return f"{out} -> {ret_text}" if ret is not inspect.Signature.empty else out


def graph_signatures(needs: str, hint: str | None) -> str | None:
    """Signature lookup for the strip header: primitives and vault tools."""
    if not hint:
        return None
    if needs == "primitive" and hint in PRIMITIVES:
        return signature_text(PRIMITIVES[hint])
    if needs == "vault":
        entry = SkillManager().get(hint)
        return entry.get("signature") if entry else None
    return None


class GraphDriver:
    """Drives the compiled Talos graph and translates its stream.

    Args:
        graph: `build_app(saver)` with the Postgres checkpointer. Only the
            async API (`astream`) is used; AsyncPostgresSaver has no sync path.
    """

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def initial_state(self) -> dict[str, Any]:
        return EventTranslator.initial_state()

    async def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]:
        tr = EventTranslator(state, signatures=graph_signatures)
        if resume is None:
            graph_input: Any = {"messages": [HumanMessage(content=query)]}
        else:
            for event in tr.resumed(resume.kind, resume.decision):
                yield event
            graph_input = Command(resume=resume.value)
        config = {"configurable": {"thread_id": thread_id}}
        async for chunk in self.graph.astream(
            graph_input, config, stream_mode=STREAM_MODES, subgraphs=True
        ):
            for event in tr.feed(chunk):
                yield event
        if tr.pause is not None:
            yield Pause(kind=tr.pause[0], value=tr.pause[1])
            return
        for event in tr.finish():
            yield event


# ---- the manager ---------------------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    run: Run
    message: Message


def user_html(text: str) -> str:
    """User text is stored escaped (it's rendered as HTML later)."""
    return html.escape(text)


class RunManager:
    """Starts, resumes and stops runs; publishes their events.

    Args:
        store: Where sessions, runs and events live.
        driver: Produces the events (real graph or fake).
    """

    def __init__(self, store: Store, driver: Driver) -> None:
        self.store = store
        self.driver = driver
        self._lock = asyncio.Lock()
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._states: dict[uuid.UUID, dict[str, Any]] = {}
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = {}

    # ---- lifecycle -----------------------------------------------------------------

    async def join(self, run_id: uuid.UUID) -> None:
        """Wait until the run's current task (if any) ends: finished or paused."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        """App shutdown: stop running runs. A run that just paused keeps waiting."""
        for run_id, task in list(self._tasks.items()):
            run = await self.store.get_run(run_id)
            if run is not None and run.status == "waiting":
                await asyncio.gather(task, return_exceptions=True)  # finishing its pause
            else:
                await self.stop(run_id)

    # ---- start / resume / stop ------------------------------------------------------

    async def start(self, session_id: uuid.UUID, text: str) -> StartResult:
        """Start a run for `text` in a session.

        Raises:
            NotFound: No such session.
            RunActive: Some run anywhere is `running` or `waiting`.
        """
        async with self._lock:
            session = await self.store.get_session(session_id)
            if session is None:
                raise NotFound("Session not found.")
            active = await self.store.active_runs()
            if active:
                raise RunActive(active[0])
            first = not await self.store.list_runs(session_id)
            run, message = await self.store.begin_run(
                session_id, text, user_html(text), session_name(text) if first else None
            )
            state = self.driver.initial_state()
            self._states[run.id] = state
            await self._publish(
                run.id, "run.started", session_id=str(session_id), query=text, n=run.n
            )
            await self._publish(run.id, "log.cmd", text=text)
            self._spawn(run, session.thread_id, state, None)
        return StartResult(run=run, message=message)

    async def resume(self, run_id: uuid.UUID, decision: str, value: str | None = None) -> None:
        """Answer a paused run and continue it in a new task.

        Raises:
            NotFound: No such run.
            NotWaiting: The run isn't paused.
            BadDecision: The decision doesn't fit the pending interrupt.
        """
        async with self._lock:
            run = await self.store.get_run(run_id)
            if run is None:
                raise NotFound("Run not found.")
            if run.status != "waiting" or not run.pending_interrupt:
                raise NotWaiting()
            pending = dict(run.pending_interrupt)
            resume = _resume_for(pending, decision, value)
            await self.join(run_id)  # the pausing task may still be publishing `interrupt`
            session = await self.store.get_session(run.session_id)
            state = dict(run.translator_state or self.driver.initial_state())
            self._states[run_id] = state
            await self.store.set_run_status(run_id, "running", pending_interrupt=None)
            await self._publish(run_id, "interrupt.resolved", kind=resume.kind, decision=decision)
            self._spawn(run, session.thread_id, state, resume)

    async def stop(self, run_id: uuid.UUID) -> None:
        """Stop a run: cancel its task, or finish it if it is paused. No-op when finished.

        Raises:
            NotFound: No such run.
        """
        async with self._lock:
            run = await self.store.get_run(run_id)
            if run is None:
                raise NotFound("Run not found.")
            if run.status in TERMINAL_STATUSES:
                return
            task = self._tasks.pop(run_id, None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            state = self._states.pop(run_id, None) or dict(run.translator_state or {})
            board = Board(state)
            board.stop()
            await self.store.set_run_status(
                run_id,
                "stopped",
                pending_interrupt=None,
                translator_state=board.state,
                summary=copy.SUMMARY_STOPPED,
                summary_gold=False,
                forged=board.state["forged"],
                used=board.state["used"],
                failed=bool(board.state["failed"]),
            )
            board.finished("stopped", copy.SUMMARY_STOPPED)
            for type_, data in board.drain():
                await self._publish(run_id, type_, **data)
            await self.store.add_message(
                run.session_id, "assistant", "", note=copy.STOP_NOTE, run_id=run_id
            )

    # ---- events -------------------------------------------------------------------------

    async def subscribe(self, run_id: uuid.UUID, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Envelopes with `seq > after`: the stored backlog, then live ones.

        Ends after `run.finished`, or right after the backlog when the run
        already finished. The queue is registered before the backlog is
        read, and duplicates are dropped by `seq`, so nothing is missed.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            last = after
            for event in await self.store.events_after(run_id, after):
                envelope = event.envelope()
                last = envelope["seq"]
                yield envelope
                if envelope["type"] == "run.finished":
                    return
            run = await self.store.get_run(run_id)
            if run is None or run.status in TERMINAL_STATUSES:
                return
            while True:
                envelope = await queue.get()
                if envelope["seq"] <= last:
                    continue
                last = envelope["seq"]
                yield envelope
                if envelope["type"] == "run.finished":
                    return
        finally:
            subs = self._subscribers.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(run_id, None)

    async def _publish(self, run_id: uuid.UUID, type_: str, **data: Any) -> None:
        """Persist (allocating `seq`), then hand the envelope to every subscriber."""
        event = await self.store.append_event(run_id, type_, data)
        envelope = event.envelope()
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(envelope)

    # ---- the run task -----------------------------------------------------------------------

    def _spawn(
        self, run: Run, thread_id: str, state: dict[str, Any], resume: Resume | None
    ) -> None:
        task = asyncio.create_task(
            self._drive(run.id, run.session_id, run.query, thread_id, state, resume),
            name=f"talos-run-{run.id}",
        )
        self._tasks[run.id] = task

    async def _drive(
        self,
        run_id: uuid.UUID,
        session_id: uuid.UUID,
        query: str,
        thread_id: str,
        state: dict[str, Any],
        resume: Resume | None,
    ) -> None:
        try:
            async for item in self.driver.run(
                state, query=query, thread_id=thread_id, resume=resume
            ):
                if isinstance(item, Pause):
                    await self.store.set_run_status(
                        run_id,
                        "waiting",
                        pending_interrupt=item.value,
                        translator_state=state,
                    )
                    await self._publish(
                        run_id, "interrupt", kind=item.kind, payload=pending_payload(item.value)
                    )
                    return
                type_, data = item
                if type_ == "answer.done":
                    await self.store.add_message(
                        session_id,
                        "assistant",
                        data.get("html") or "",
                        note=data.get("note"),
                        chips=data.get("chips") or [],
                        run_id=run_id,
                    )
                elif type_ == "run.finished":
                    await self.store.set_run_status(
                        run_id,
                        data["status"],
                        translator_state=state,
                        pending_interrupt=None,
                        summary=data["summary"],
                        summary_gold=bool(data.get("summary_gold")),
                        forged=data.get("forged") or [],
                        used=data.get("used") or [],
                        failed=bool(state.get("failed")),
                    )
                await self._publish(run_id, type_, **data)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any driver failure ends the run cleanly
            log.exception("run %s failed", run_id)
            message = f"{type(e).__name__}: {e}"
            forged, used = list(state.get("forged") or []), list(state.get("used") or [])
            await self.store.set_run_status(
                run_id,
                "failed",
                translator_state=state,
                pending_interrupt=None,
                error=message,
                summary=copy.SUMMARY_FAILED,
                summary_gold=False,
                forged=forged,
                used=used,
                failed=True,
            )
            await self._publish(run_id, "error", message=message)
            await self._publish(
                run_id,
                "run.finished",
                status="failed",
                summary=copy.SUMMARY_FAILED,
                summary_gold=False,
                forged=forged,
                used=used,
            )
        finally:
            if self._tasks.get(run_id) is asyncio.current_task():
                self._tasks.pop(run_id, None)
                self._states.pop(run_id, None)


def _resume_for(pending: dict[str, Any], decision: str, value: str | None) -> Resume:
    """Map a browser decision onto the graph's resume value (spec 02 §4 Resume rules)."""
    kind = str(pending.get("type"))
    if kind == "confirm_exec":
        if decision == "approve":
            return Resume(
                kind,
                decision,
                {
                    "approved": True,
                    "args": list(pending.get("args") or []),
                    "kwargs": dict(pending.get("kwargs") or {}),
                },
            )
        if decision == "decline":
            return Resume(kind, decision, {"approved": False})
        raise BadDecision("An approval takes approve or decline.")
    if kind == "missing_api_key":
        if decision == "save":
            key = (value or "").strip()
            if not key:
                raise BadDecision("Paste the key first, or choose Skip.")
            return Resume(kind, decision, key)
        if decision == "skip":
            return Resume(kind, decision, "skip")
        raise BadDecision("A key request takes save or skip.")
    raise BadDecision(f"Unknown pause kind {kind!r}.")
