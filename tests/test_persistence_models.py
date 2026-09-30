"""Models and database helpers that need no database (spec 01 §8, unit)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from talos.persistence import db as db_mod
from talos.persistence.models import (
    LANGGRAPH_TABLES,
    Base,
    RunEvent,
    format_ts,
    include_object,
)

TABLES = {"sessions", "messages", "runs", "run_events", "app_settings"}


def test_metadata_has_exactly_the_five_tables():
    assert set(Base.metadata.tables) == TABLES


def test_naming_convention_is_applied():
    runs = Base.metadata.tables["runs"]
    names = {c.name for c in runs.constraints} | {i.name for i in runs.indexes}
    assert {"pk_runs", "fk_runs_session_id_sessions", "ck_runs_status"} <= names
    assert {"ix_runs_active", "ix_runs_session_id", "uq_runs_session_id_n"} <= names


def test_include_object_ignores_langgraph_tables():
    for name in LANGGRAPH_TABLES:
        assert include_object(None, name, "table", True, None) is False
    assert include_object(None, "runs", "table", False, None) is True


def test_include_object_ignores_indexes_on_langgraph_tables():
    class _Table:
        name = "checkpoints"

    class _Index:
        table = _Table()

    assert include_object(_Index(), "checkpoints_thread_id_idx", "index", True, None) is False


def test_format_ts_is_utc_with_milliseconds():
    ts = datetime(2026, 9, 30, 16, 23, 55, 120999, tzinfo=timezone(timedelta(hours=2)))
    assert format_ts(ts) == "2026-09-30T14:23:55.120Z"


def test_event_envelope_shape():
    run_id = uuid.uuid4()
    event = RunEvent(
        run_id=run_id,
        seq=12,
        type="node.started",
        data={"step": "planner"},
        ts=datetime(2026, 9, 30, 14, 23, 55, 120000, tzinfo=UTC),
    )
    assert event.envelope() == {
        "run_id": str(run_id),
        "seq": 12,
        "ts": "2026-09-30T14:23:55.120Z",
        "type": "node.started",
        "data": {"step": "planner"},
    }


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
        "postgres://u:p@h:5432/d",
    ],
)
def test_urls_normalise_for_sqlalchemy_and_psycopg(url):
    assert db_mod.sqlalchemy_url(url) == "postgresql+psycopg://u:p@h:5432/d"
    assert db_mod.libpq_url(url) == "postgresql://u:p@h:5432/d"


@pytest.mark.parametrize("url", ["", "sqlite:///x.db", "mysql://u@h/d"])
def test_non_postgres_urls_are_rejected(url):
    with pytest.raises(ValueError, match="Postgres"):
        db_mod.sqlalchemy_url(url)


def test_make_engine_without_url_explains(monkeypatch):
    monkeypatch.setattr(db_mod.settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db_mod.make_engine()


def test_session_factory_requires_init(monkeypatch):
    monkeypatch.setattr(db_mod, "_factory", None)
    with pytest.raises(RuntimeError, match="init_db"):
        db_mod.session_factory()


async def test_init_db_is_idempotent_and_dispose_resets(monkeypatch):
    monkeypatch.setattr(db_mod, "_factory", None)
    monkeypatch.setattr(db_mod, "_engine", None)
    url = "postgresql+psycopg://u:p@localhost:1/d"  # never connected to
    first = db_mod.init_db(url)
    assert db_mod.init_db(url) is first
    assert db_mod.session_factory() is first
    await db_mod.dispose_db()
    with pytest.raises(RuntimeError):
        db_mod.session_factory()
