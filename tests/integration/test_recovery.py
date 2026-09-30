"""Startup recovery (spec 01 §7)."""

from __future__ import annotations

import pytest

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.recovery import RECOVERY_ERROR, recover_runs

pytestmark = pytest.mark.integration


async def test_running_runs_fail_and_waiting_runs_stay(factory):
    async with session_scope(factory) as db:
        s = await repo.create_session(db)
        running = await repo.create_run(db, s.id, "q1")
        waiting = await repo.create_run(db, s.id, "q2")
        done = await repo.create_run(db, s.id, "q3")
        await repo.append_event(db, running.id, "run.started", {"n": 1})
        await repo.set_run_status(db, running.id, "running", used=["caesar_cipher"])
        await repo.set_run_status(db, waiting.id, "waiting", pending_interrupt={"type": "x"})
        await repo.set_run_status(db, done.id, "done")

    async with session_scope(factory) as db:
        recovered = await recover_runs(db)

    assert recovered == [running.id]
    async with session_scope(factory) as db:
        failed = await repo.get_run(db, running.id)
        assert failed.status == "failed"
        assert failed.error == RECOVERY_ERROR
        assert failed.finished_at is not None
        events = await repo.events_after(db, running.id)
        assert [(e.seq, e.type) for e in events] == [
            (1, "run.started"),
            (2, "error"),
            (3, "run.finished"),
        ]
        assert events[1].data == {"message": RECOVERY_ERROR}
        assert events[2].data == {
            "status": "failed",
            "summary": "Failed",
            "summary_gold": False,
            "forged": [],
            "used": ["caesar_cipher"],
        }
        still = await repo.get_run(db, waiting.id)
        assert still.status == "waiting" and still.pending_interrupt == {"type": "x"}
        assert (await repo.get_run(db, done.id)).status == "done"


async def test_recovery_is_a_noop_when_nothing_is_running(factory):
    async with session_scope(factory) as db:
        assert await recover_runs(db) == []
