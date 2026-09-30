"""Repo helpers that need no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from talos.persistence.models import Run, Session
from talos.persistence.repo import run_mark, set_run_status, summarise_session


def _run(n: int, **kw) -> Run:
    base = {"status": "done", "forged": [], "used": [], "failed": False}
    base.update(kw)
    return Run(n=n, query=f"q{n}", **base)


@pytest.mark.parametrize(
    ("kw", "mark"),
    [
        ({"forged": ["caesar_cipher"]}, "forged"),
        ({"used": ["caesar_cipher"]}, "reused"),
        ({"used": ["caesar_cipher"], "failed": True}, "failed"),
        ({"status": "failed"}, "failed"),
        ({}, None),
        ({"status": "declined"}, None),
    ],
)
def test_run_mark(kw, mark):
    assert run_mark(_run(1, **kw)) == mark


def test_summarise_session_distinct_tools_and_first_three_runs():
    s = Session(id=uuid.uuid4(), name="Caesar cipher", number=1, thread_id="session-x")
    s.created_at = datetime(2026, 9, 30, tzinfo=UTC)
    s.runs = [
        _run(4, used=["weather"]),
        _run(1, forged=["caesar_cipher"]),
        _run(2, used=["caesar_cipher"]),
        _run(3, used=["caesar_cipher"], failed=True),
    ]

    summary = summarise_session(s)

    assert summary.run_count == 4
    assert summary.forged == ["caesar_cipher"]
    assert summary.used == ["weather"]  # caesar_cipher was forged here, so not "used"
    assert [(r.n, r.mark) for r in summary.runs] == [(1, "forged"), (2, "reused"), (3, "failed")]


async def test_set_run_status_rejects_unknown_status_and_fields():
    with pytest.raises(ValueError, match="status"):
        await set_run_status(None, uuid.uuid4(), "paused")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query"):
        await set_run_status(None, uuid.uuid4(), "done", query="x")  # type: ignore[arg-type]
