"""Repository functions against a real Postgres (spec 01 §6, §8)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select, text

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.models import Message, Run, RunEvent, Session

pytestmark = pytest.mark.integration


async def _new_session(factory) -> Session:
    async with session_scope(factory) as db:
        return await repo.create_session(db)


async def _new_run(factory, session_id, query: str = "caesar") -> Run:
    async with session_scope(factory) as db:
        return await repo.create_run(db, session_id, query)


# ---- sessions -------------------------------------------------------------------


async def test_create_session_numbers_and_threads(factory):
    first = await _new_session(factory)
    second = await _new_session(factory)

    assert (first.number, first.name) == (1, "Session 1")
    assert (second.number, second.name) == (2, "Session 2")
    assert first.thread_id == f"session-{first.id}"
    assert first.created_at is not None and first.updated_at is not None


async def test_concurrent_create_session_gets_unique_numbers(factory):
    sessions = await asyncio.gather(*(_new_session(factory) for _ in range(8)))
    assert sorted(s.number for s in sessions) == list(range(1, 9))


async def test_get_and_rename_session(factory):
    s = await _new_session(factory)
    async with session_scope(factory) as db:
        renamed = await repo.rename_session(db, s.id, "Caesar cipher")
        assert renamed is not None and renamed.name == "Caesar cipher"
        assert renamed.updated_at >= s.updated_at
    async with session_scope(factory) as db:
        assert (await repo.get_session(db, s.id)).name == "Caesar cipher"
        assert await repo.get_session(db, uuid.uuid4()) is None
        assert await repo.rename_session(db, uuid.uuid4(), "x") is None


# ---- runs -------------------------------------------------------------------------


async def test_create_run_allocates_n_per_session_and_bumps_updated_at(factory):
    a = await _new_session(factory)
    b = await _new_session(factory)

    r1 = await _new_run(factory, a.id)
    r2 = await _new_run(factory, a.id)
    rb = await _new_run(factory, b.id)

    assert (r1.n, r2.n, rb.n) == (1, 2, 1)
    assert r1.status == "running"
    assert (r1.forged, r1.used, r1.failed, r1.summary_gold) == ([], [], False, False)
    async with session_scope(factory) as db:
        assert (await repo.get_session(db, a.id)).updated_at > a.updated_at
        assert [r.n for r in await repo.list_runs(db, a.id)] == [1, 2]


async def test_concurrent_create_run_has_no_duplicate_n(factory):
    s = await _new_session(factory)
    runs = await asyncio.gather(*(_new_run(factory, s.id) for _ in range(10)))
    assert sorted(r.n for r in runs) == list(range(1, 11))


async def test_create_run_for_missing_session_raises(factory):
    with pytest.raises(LookupError):
        await _new_run(factory, uuid.uuid4())


async def test_set_run_status_fields_and_finished_at(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    interrupt = {"type": "confirm_exec", "args": [], "kwargs": {"code": "print(2**100)"}}

    async with session_scope(factory) as db:
        waiting = await repo.set_run_status(
            db, run.id, "waiting", pending_interrupt=interrupt, translator_state={"seq": 7}
        )
        assert waiting.finished_at is None
    async with session_scope(factory) as db:
        done = await repo.set_run_status(
            db,
            run.id,
            "done",
            pending_interrupt=None,
            summary="1 tool forged, 2 attempts",
            summary_gold=True,
            forged=("caesar_cipher",),
            used=["caesar_cipher"],
        )
    assert done.finished_at is not None
    async with session_scope(factory) as db:
        got = await repo.get_run(db, run.id)
    assert got.status == "done"
    assert got.pending_interrupt is None
    assert got.translator_state == {"seq": 7}
    assert got.forged == ["caesar_cipher"] and got.used == ["caesar_cipher"]
    assert got.summary_gold is True


async def test_clearing_jsonb_columns_writes_sql_null(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        await repo.set_run_status(
            db, run.id, "waiting", pending_interrupt={"type": "x"}, translator_state={"seq": 1}
        )
    async with session_scope(factory) as db:
        await repo.set_run_status(
            db, run.id, "running", pending_interrupt=None, translator_state=None
        )
    async with session_scope(factory) as db:
        row = (
            await db.execute(
                text(
                    "select pending_interrupt is null, translator_state is null "
                    "from runs where id = :id"
                ),
                {"id": run.id},
            )
        ).one()
    assert tuple(row) == (True, True)


async def test_active_runs(factory):
    s = await _new_session(factory)
    running = await _new_run(factory, s.id)
    waiting = await _new_run(factory, s.id)
    done = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        await repo.set_run_status(db, waiting.id, "waiting")
        await repo.set_run_status(db, done.id, "done")
    async with session_scope(factory) as db:
        assert {r.id for r in await repo.active_runs(db)} == {running.id, waiting.id}


# ---- events -------------------------------------------------------------------------


async def test_append_event_and_events_after(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        e1 = await repo.append_event(db, run.id, "run.started", {"n": 1})
        e2 = await repo.append_event(db, run.id, "log.cmd", {"text": "talos › hi"})
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.envelope()["ts"].endswith("Z")

    async with session_scope(factory) as db:
        after = await repo.events_after(db, run.id, 1)
        everything = await repo.events_after(db, run.id)
    assert [(e.seq, e.type, e.data) for e in after] == [(2, "log.cmd", {"text": "talos › hi"})]
    assert [e.seq for e in everything] == [1, 2]


async def test_twenty_concurrent_appends_have_no_gaps_or_duplicates(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)

    async def append(i: int) -> int:
        async with session_scope(factory) as db:
            return (await repo.append_event(db, run.id, "log.line", {"i": i})).seq

    seqs = await asyncio.gather(*(append(i) for i in range(20)))

    assert sorted(seqs) == list(range(1, 21))
    async with session_scope(factory) as db:
        stored = [e.seq for e in await repo.events_after(db, run.id)]
    assert stored == list(range(1, 21))


async def test_append_event_to_missing_run_raises(factory):
    with pytest.raises(LookupError):
        async with session_scope(factory) as db:
            await repo.append_event(db, uuid.uuid4(), "run.started", {})


async def test_failed_transaction_leaves_no_event(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    with pytest.raises(RuntimeError):
        async with session_scope(factory) as db:
            await repo.append_event(db, run.id, "run.started", {})
            raise RuntimeError("boom")
    async with session_scope(factory) as db:
        assert await repo.events_after(db, run.id) == []
        assert (await repo.append_event(db, run.id, "run.started", {})).seq == 1


# ---- messages ---------------------------------------------------------------------------


async def test_messages_keep_insert_order_within_one_transaction(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    chips = [{"kind": "forged", "text": "Forged caesar_cipher"}]
    async with session_scope(factory) as db:
        await repo.add_message(db, s.id, "user", "shift &lt;abc&gt; by 3", run_id=run.id)
        await repo.add_message(db, s.id, "assistant", "Done.", note="n", chips=chips, run_id=run.id)
    async with session_scope(factory) as db:
        msgs = await repo.list_messages(db, s.id)
    assert [(m.role, m.html) for m in msgs] == [
        ("user", "shift &lt;abc&gt; by 3"),
        ("assistant", "Done."),
    ]
    assert msgs[1].chips == chips and msgs[1].note == "n" and msgs[0].chips == []


async def test_add_message_rejects_unknown_role(factory):
    s = await _new_session(factory)
    with pytest.raises(ValueError):
        async with session_scope(factory) as db:
            await repo.add_message(db, s.id, "system", "x")


# ---- settings ---------------------------------------------------------------------------


async def test_settings_default_set_and_overwrite(factory):
    async with session_scope(factory) as db:
        assert await repo.get_setting(db, "ask_before_exec", True) is True
        await repo.set_setting(db, "ask_before_exec", False)
        assert await repo.get_setting(db, "ask_before_exec", True) is False
    async with session_scope(factory) as db:
        await repo.set_setting(db, "ask_before_exec", True)
    async with session_scope(factory) as db:
        assert await repo.get_setting(db, "ask_before_exec") is True


# ---- sessions page ---------------------------------------------------------------------------


async def test_list_sessions_newest_first_with_summary(factory):
    old = await _new_session(factory)
    new = await _new_session(factory)
    r1 = await _new_run(factory, new.id, "encrypt hello")
    r2 = await _new_run(factory, new.id, "decrypt it")
    async with session_scope(factory) as db:
        await repo.set_run_status(db, r1.id, "done", forged=["caesar_cipher"])
        await repo.set_run_status(db, r2.id, "done", used=["caesar_cipher", "vault_list"])

    async with session_scope(factory) as db:
        summaries = await repo.list_sessions(db)

    assert [s.id for s in summaries] == [new.id, old.id]
    top = summaries[0]
    assert top.run_count == 2
    assert top.forged == ["caesar_cipher"]
    assert top.used == ["vault_list"]
    assert [(r.n, r.query, r.mark) for r in top.runs] == [
        (1, "encrypt hello", "forged"),
        (2, "decrypt it", "reused"),
    ]
    assert summaries[1].run_count == 0 and summaries[1].runs == []


async def test_deleting_a_session_cascades(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        await repo.append_event(db, run.id, "run.started", {})
        await repo.add_message(db, s.id, "user", "hi", run_id=run.id)
    async with session_scope(factory) as db:
        await db.execute(delete(Session).where(Session.id == s.id))
    async with session_scope(factory) as db:
        for model in (Run, RunEvent, Message):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
