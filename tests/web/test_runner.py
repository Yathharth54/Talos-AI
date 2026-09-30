"""RunManager with a scripted driver and the in-memory store (spec 02 §11)."""

from __future__ import annotations

import asyncio
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
    key = paused
    await manager.stop(key)
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
    await asyncio.sleep(0.01)
    assert seen == list(range(3, backlog + 1))  # backlog after seq 2, then waits
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
