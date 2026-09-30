"""Behaviour every `Store` must have. Run against MemoryStore (unit) and
PgStore (integration), so the in-memory store the route tests use can't
drift from Postgres."""

from __future__ import annotations

import uuid

import pytest

from talos.persistence.recovery import RECOVERY_ERROR


async def sessions_are_numbered_and_named(store):
    first = await store.create_session()
    second = await store.create_session()
    assert (first.number, second.number) == (1, 2)
    assert (first.name, second.name) == ("Session 1", "Session 2")
    assert first.thread_id == f"session-{first.id}"
    assert (await store.get_session(first.id)).id == first.id
    assert await store.get_session(uuid.uuid4()) is None


async def begin_run_numbers_runs_adds_the_user_message_and_renames(store):
    s = await store.create_session()
    run1, msg = await store.begin_run(s.id, "encrypt it", "encrypt it", "Caesar cipher")
    run2, _ = await store.begin_run(s.id, "again", "again", None)
    assert (run1.n, run2.n, run1.status) == (1, 2, "running")
    assert (msg.role, msg.html, msg.run_id) == ("user", "encrypt it", run1.id)
    assert (await store.get_session(s.id)).name == "Caesar cipher"
    assert [r.n for r in await store.list_runs(s.id)] == [1, 2]
    assert [m.html for m in await store.list_messages(s.id)] == ["encrypt it", "again"]
    with pytest.raises(LookupError):
        await store.begin_run(uuid.uuid4(), "q", "q", None)


async def events_get_gap_free_seq_and_an_envelope(store):
    s = await store.create_session()
    run, _ = await store.begin_run(s.id, "q", "q", None)
    for i in range(5):
        event = await store.append_event(run.id, "log.line", {"i": i})
        assert event.seq == i + 1
    after = await store.events_after(run.id, 3)
    assert [e.seq for e in after] == [4, 5]
    env = after[0].envelope()
    assert set(env) == {"run_id", "seq", "ts", "type", "data"}
    assert env["run_id"] == str(run.id) and env["data"] == {"i": 3}
    assert env["ts"].endswith("Z")
    with pytest.raises(LookupError):
        await store.append_event(uuid.uuid4(), "x", {})


async def run_status_rules(store):
    s = await store.create_session()
    run, _ = await store.begin_run(s.id, "q", "q", None)
    state = {"steps": {"planner": {"state": "done", "label": "Planner"}}}
    waiting = await store.set_run_status(
        run.id, "waiting", translator_state=state, pending_interrupt={"type": "confirm_exec"}
    )
    assert waiting.finished_at is None
    assert [r.id for r in await store.active_runs()] == [run.id]
    again = await store.get_run(run.id)
    assert again.translator_state == state
    assert again.pending_interrupt == {"type": "confirm_exec"}
    done = await store.set_run_status(
        run.id, "done", pending_interrupt=None, summary="0 tools forged", used=["t"]
    )
    assert done.finished_at is not None and done.pending_interrupt is None
    assert done.used == ["t"]
    assert await store.active_runs() == []
    with pytest.raises(ValueError):
        await store.set_run_status(run.id, "exploded")
    with pytest.raises(LookupError):
        await store.set_run_status(uuid.uuid4(), "done")


async def sessions_list_newest_first_with_marks(store):
    old = await store.create_session()
    new = await store.create_session()
    run, _ = await store.begin_run(old.id, "caesar", "caesar", None)
    await store.set_run_status(run.id, "done", forged=["caesar_cipher"], used=["caesar_cipher"])
    listed = await store.list_sessions()
    assert [x.id for x in listed] == [new.id, old.id]
    assert listed[1].run_count == 1
    assert listed[1].forged == ["caesar_cipher"] and listed[1].used == []
    assert listed[1].runs[0].mark == "forged"


async def settings_round_trip(store):
    assert await store.get_setting("ask_before_exec") is None
    assert await store.get_setting("ask_before_exec", True) is True
    await store.set_setting("ask_before_exec", False)
    await store.set_setting("ask_before_exec", False)
    assert await store.get_setting("ask_before_exec") is False


async def recover_fails_running_runs_only(store):
    s = await store.create_session()
    running, _ = await store.begin_run(s.id, "a", "a", None)
    waiting, _ = await store.begin_run(s.id, "b", "b", None)
    await store.set_run_status(waiting.id, "waiting", pending_interrupt={"type": "x"})
    assert await store.recover() == [running.id]
    failed = await store.get_run(running.id)
    assert (failed.status, failed.error, failed.summary) == ("failed", RECOVERY_ERROR, "Failed")
    assert [e.type for e in await store.events_after(running.id)] == ["error", "run.finished"]
    assert (await store.get_run(waiting.id)).status == "waiting"


CONTRACT = [
    sessions_are_numbered_and_named,
    begin_run_numbers_runs_adds_the_user_message_and_renames,
    events_get_gap_free_seq_and_an_envelope,
    run_status_rules,
    sessions_list_newest_first_with_marks,
    settings_round_trip,
    recover_fails_running_runs_only,
]
