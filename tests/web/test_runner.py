"""RunManager with a scripted driver and the in-memory store (spec 02 §11)."""

from __future__ import annotations

import asyncio
import copy
import uuid

import pytest

from talos.web.runner import BadDecision, NotFound, NotWaiting, RunActive, RunManager
from talos.web.store import MemoryStore
from tests.web.stubs import ScriptDriver


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def driver() -> ScriptDriver:
    return ScriptDriver()


@pytest.fixture
def manager(store, driver) -> RunManager:
    return RunManager(store, driver)


async def events(store: MemoryStore, run_id) -> list[tuple[int, str]]:
    return [(e.seq, e.type) for e in await store.events_after(run_id)]


async def test_a_run_streams_to_the_end_and_is_recorded(manager, store):
    session = await store.create_session()
    started = await manager.start(session.id, "Encrypt with a Caesar cipher")
    await manager.join(started.run.id)

    types = [t for _, t in await events(store, started.run.id)]
    assert types[:2] == ["run.started", "log.cmd"]
    assert types[-2:] == ["answer.done", "run.finished"]
    first = (await store.events_after(started.run.id))[0]
    assert first.data == {"session_id": str(session.id), "query": started.run.query, "n": 1}
    run = await store.get_run(started.run.id)
    assert (run.status, run.summary, run.used) == ("done", "Built-in", ["caesar_cipher"])
    assert run.translator_state["steps"]["planner"]["state"] == "done"
    roles = [(m.role, m.html) for m in await store.list_messages(session.id)]
    assert roles == [("user", "Encrypt with a Caesar cipher"), ("assistant", "ok")]
    assert (await store.get_session(session.id)).name == "Caesar cipher"


async def test_only_the_first_run_names_the_session(manager, store):
    session = await store.create_session()
    for text in ("What can you do?", "Encrypt with a Caesar cipher"):
        await manager.join((await manager.start(session.id, text)).run.id)
    assert (await store.get_session(session.id)).name == "Getting to know Talos"


async def test_user_text_is_stored_escaped(manager, store):
    session = await store.create_session()
    started = await manager.start(session.id, "<b>hi</b>")
    assert started.message.html == "&lt;b&gt;hi&lt;/b&gt;"
    await manager.join(started.run.id)


async def test_one_active_run_across_the_whole_app(manager, store):
    a = await store.create_session()
    b = await store.create_session()
    paused = await manager.start(a.id, "pause")
    await manager.join(paused.run.id)
    assert (await store.get_run(paused.run.id)).status == "waiting"
    with pytest.raises(RunActive):
        await manager.start(b.id, "hello")


async def test_concurrent_starts_let_exactly_one_through(manager, store):
    session = await store.create_session()
    results = await asyncio.gather(
        *(manager.start(session.id, "block") for _ in range(5)), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1
    assert all(isinstance(r, RunActive) for r in results if isinstance(r, Exception))
    await manager.stop(ok[0].run.id)


async def test_unknown_session_is_not_found(manager):
    with pytest.raises(NotFound):
        await manager.start(uuid.uuid4(), "hi")


async def test_pause_then_resume_keeps_seq_gap_free(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    paused = await store.get_run(run_id)
    assert paused.status == "waiting"
    assert paused.pending_interrupt["kwargs"] == {"code": "print(1)"}
    last = (await store.events_after(run_id))[-1]
    assert (last.type, last.data) == (
        "interrupt",
        {"kind": "confirm_exec", "payload": {"tool": "python_exec", "preview": "print(1)"}},
    )

    await manager.resume(run_id, "approve")
    await manager.join(run_id)

    seqs = [s for s, _ in await events(store, run_id)]
    assert seqs == list(range(1, len(seqs) + 1))
    types = [t for _, t in await events(store, run_id)]
    assert types[types.index("interrupt") + 1] == "interrupt.resolved"
    assert types[-1] == "run.finished"
    resolved = next(e for e in await store.events_after(run_id) if e.type == "interrupt.resolved")
    assert resolved.data == {"kind": "confirm_exec", "decision": "approve"}
    assert driver.resumes[0].value == {
        "approved": True,
        "args": [],
        "kwargs": {"code": "print(1)"},
    }
    done = await store.get_run(run_id)
    assert (done.status, done.pending_interrupt) == ("done", None)


async def test_decline_and_key_decisions_map_to_resume_values(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "decline")
    await manager.join(run_id)

    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "save", "  sk-secret  ")
    await manager.join(run_id)

    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "skip")
    await manager.join(run_id)
    assert [r.value for r in driver.resumes] == [{"approved": False}, "sk-secret", "skip"]


async def test_resume_errors(manager, store):
    session = await store.create_session()
    with pytest.raises(NotFound):
        await manager.resume(uuid.uuid4(), "approve")
    done = (await manager.start(session.id, "hi")).run.id
    await manager.join(done)
    with pytest.raises(NotWaiting):
        await manager.resume(done, "approve")

    paused = (await manager.start(session.id, "pause")).run.id
    await manager.join(paused)
    with pytest.raises(BadDecision):
        await manager.resume(paused, "save", "x")
    await manager.stop(paused)
    key = (await manager.start(session.id, "key")).run.id
    await manager.join(key)
    with pytest.raises(BadDecision):
        await manager.resume(key, "approve")
    with pytest.raises(BadDecision):
        await manager.resume(key, "save", "   ")
    assert (await store.get_run(key)).status == "waiting"


async def test_stop_during_a_run(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "block")).run.id
    await driver.started.wait()
    await manager.stop(run_id)

    run = await store.get_run(run_id)
    assert (run.status, run.summary) == ("stopped", "Stopped")
    tail = [(e.type, e.data) for e in await store.events_after(run_id)][-5:]
    assert tail == [
        ("node.finished", {"step": "planner", "status": "stopped", "label": "Planner, stopped"}),
        ("log.line", {"label": "stop", "text": "stopped by you", "tone": "w"}),
        ("log.status", {"text": "Stopped", "gold": False, "tone": ""}),
        ("caption", {"html": "You stopped this run. Nothing was saved to the vault."}),
        (
            "run.finished",
            {"status": "stopped", "summary": "Stopped", "summary_gold": False,
             "forged": [], "used": []},
        ),
    ]  # fmt: skip
    notes = [m.note for m in await store.list_messages(session.id) if m.role == "assistant"]
    assert notes == ["Stopped. Ask again whenever you're ready."]
    # the lock is free again
    await manager.join((await manager.start(session.id, "hi")).run.id)


async def test_stop_during_a_pause_uses_the_saved_state(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    fresh = RunManager(store, ScriptDriver())  # e.g. after an app restart
    await fresh.stop(run_id)
    run = await store.get_run(run_id)
    assert (run.status, run.pending_interrupt) == ("stopped", None)
    types = [t for _, t in await events(store, run_id)]
    assert types[-5:] == ["node.finished", "log.line", "log.status", "caption", "run.finished"]
    await fresh.stop(run_id)  # already finished: no-op
    assert len(await events(store, run_id)) == len(types)


async def test_an_exception_fails_the_run(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "boom")).run.id
    await manager.join(run_id)
    tail = [(e.type, e.data) for e in await store.events_after(run_id)][-2:]
    assert tail == [
        ("error", {"message": "RuntimeError: kaboom"}),
        (
            "run.finished",
            {"status": "failed", "summary": "Failed", "summary_gold": False,
             "forged": [], "used": []},
        ),
    ]  # fmt: skip
    run = await store.get_run(run_id)
    assert (run.status, run.error, run.failed) == ("failed", "RuntimeError: kaboom", True)


async def test_subscribe_replays_then_goes_live_then_closes(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    backlog = len(await events(store, run_id))

    seen: list[int] = []

    async def consume() -> None:
        async for envelope in manager.subscribe(run_id, after=2):
            seen.append(envelope["seq"])

    consumer = asyncio.create_task(consume())
    for _ in range(500):
        if len(seen) == backlog - 2:
            break
        await asyncio.sleep(0.001)
    assert seen == list(range(3, backlog + 1))  # backlog after seq 2, then waits
    assert not consumer.done()
    await manager.resume(run_id, "approve")
    await asyncio.wait_for(consumer, 2)
    total = len(await events(store, run_id))
    assert seen == list(range(3, total + 1))  # live events, closed after run.finished


async def test_subscribe_to_a_finished_run_returns_the_backlog_and_closes(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "hi")).run.id
    await manager.join(run_id)
    got = [e["seq"] async for e in manager.subscribe(run_id, after=0)]
    assert got == [s for s, _ in await events(store, run_id)]
    assert [e["seq"] async for e in manager.subscribe(run_id, after=len(got))] == []


async def test_shutdown_stops_running_runs(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "block")).run.id
    await driver.started.wait()
    await manager.shutdown()
    assert (await store.get_run(run_id)).status == "stopped"


class SlowStore(MemoryStore):
    """Appends take a moment, like a real database round trip."""

    async def append_event(self, run_id, type_, data):
        await asyncio.sleep(0.01)
        return await super().append_event(run_id, type_, data)


async def until_waiting(store, run_id) -> None:
    for _ in range(500):
        if (await store.get_run(run_id)).status == "waiting":
            return
        await asyncio.sleep(0.001)
    raise AssertionError("never paused")


async def test_resume_right_after_the_pause_keeps_interrupt_first():
    store = SlowStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await until_waiting(store, run_id)  # status is waiting; `interrupt` may still be in flight
    await manager.resume(run_id, "approve")
    await manager.join(run_id)
    types = [t for _, t in await events(store, run_id)]
    assert types.index("interrupt") < types.index("interrupt.resolved")


async def test_shutdown_leaves_a_just_paused_run_waiting():
    store = SlowStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await until_waiting(store, run_id)
    await manager.shutdown()
    assert (await store.get_run(run_id)).status == "waiting"
    assert [t for _, t in await events(store, run_id)][-1] == "interrupt"


async def test_a_closed_subscriber_is_forgotten(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    stream = manager.subscribe(run_id, after=0)
    await stream.__anext__()  # the browser read one event, then the tab closed
    assert manager._subscribers[run_id]
    await stream.aclose()
    assert run_id not in manager._subscribers


class FinishInvariantStore(MemoryStore):
    """Records a violation if a run is marked terminal before `run.finished` is stored."""

    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []

    async def set_run_status(self, run_id, status, **fields):
        if status in ("done", "stopped", "failed"):
            events = await self.events_after(run_id)
            if not events or events[-1].type != "run.finished":
                self.violations.append(status)
        return await super().set_run_status(run_id, status, **fields)


async def test_run_finished_is_stored_before_the_run_turns_terminal():
    store = FinishInvariantStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    await manager.join((await manager.start(session.id, "hi")).run.id)
    await manager.join((await manager.start(session.id, "boom")).run.id)
    blocked = (await manager.start(session.id, "block")).run.id
    await manager.stop(blocked)
    paused = (await manager.start(session.id, "pause")).run.id
    await manager.join(paused)
    await manager.stop(paused)
    assert store.violations == []


class SlowGetStore(MemoryStore):
    """The first get_run returns the old row, then takes a moment."""

    delay = False

    async def get_run(self, run_id):
        run = await super().get_run(run_id)
        if self.delay and run is not None:
            run = copy.copy(run)  # a stale snapshot, like a row read from a real database
            self.delay = False
            await asyncio.sleep(0.05)
        return run


async def test_stop_does_not_clobber_a_run_that_just_finished():
    store = SlowGetStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "hi")).run.id
    store.delay = True
    await manager.stop(run_id)
    await manager.join(run_id)
    run = await store.get_run(run_id)
    assert run.status == "done"
    types = [t for _, t in await events(store, run_id)]
    assert types.count("run.finished") == 1
    notes = [m.note for m in await store.list_messages(session.id) if m.role == "assistant"]
    assert notes == [None]


class FailingInterruptStore(MemoryStore):
    async def append_event(self, run_id, type_, data):
        if type_ == "interrupt":
            await asyncio.sleep(0.02)
            raise RuntimeError("db hiccup")
        return await super().append_event(run_id, type_, data)


async def test_resume_does_not_revive_a_run_whose_pause_failed():
    store = FailingInterruptStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await until_waiting(store, run_id)
    with pytest.raises(NotWaiting):
        await manager.resume(run_id, "approve")
    assert (await store.get_run(run_id)).status == "failed"


async def test_shutdown_survives_a_failing_stop(manager, store, driver, monkeypatch):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "block")).run.id
    await driver.started.wait()

    async def broken(_run_id):
        raise RuntimeError("nope")

    monkeypatch.setattr(manager, "stop", broken)
    await manager.shutdown()  # must not raise
    monkeypatch.undo()
    await manager.stop(run_id)


class RaceStore(MemoryStore):
    """Injects `run.finished` and a terminal status between a subscriber's reads."""

    armed = False

    async def get_run(self, run_id):
        if self.armed:
            self.armed = False
            await self.append_event(run_id, "run.finished", {"status": "done"})
            await self.set_run_status(run_id, "done", pending_interrupt=None)
        return await super().get_run(run_id)


async def test_subscribe_delivers_run_finished_that_lands_after_the_backlog_read():
    store = RaceStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    store.armed = True
    got = [e["type"] async for e in manager.subscribe(run_id, after=0)]
    assert got[-2:] == ["interrupt", "run.finished"]


class FlakyStatusStore(MemoryStore):
    """set_run_status fails once for `fail_on`, after run.finished was stored."""

    fail_on = ""

    async def set_run_status(self, run_id, status, **fields):
        if status == self.fail_on:
            self.fail_on = ""
            raise RuntimeError("db hiccup")
        return await super().set_run_status(run_id, status, **fields)


async def test_a_failed_status_write_does_not_publish_a_second_run_finished():
    store = FlakyStatusStore()
    store.fail_on = "done"
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "hi")).run.id
    await manager.join(run_id)
    types = [t for _, t in await events(store, run_id)]
    assert types.count("run.finished") == 1
    assert "error" not in types
    assert (await store.get_run(run_id)).status == "failed"


async def test_a_retried_stop_does_not_publish_a_second_run_finished():
    store = FlakyStatusStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    store.fail_on = "stopped"
    with pytest.raises(RuntimeError):
        await manager.stop(run_id)
    await manager.stop(run_id)
    types = [t for _, t in await events(store, run_id)]
    assert types.count("run.finished") == 1
    assert (await store.get_run(run_id)).status == "stopped"
