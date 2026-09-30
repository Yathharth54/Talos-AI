"""wait_for_db: the Docker entrypoint's database wait (spec 03 §3)."""

from __future__ import annotations

import psycopg
import pytest

from talos.persistence import wait as wait_mod
from talos.persistence.wait import wait_for_db

URL = "postgresql+psycopg://talos:talos@db:5432/talos"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Conn:
    def close(self) -> None:
        pass


def test_returns_once_the_database_answers():
    clock = _Clock()
    calls: list[tuple] = []

    def connect(conninfo, **kwargs):
        calls.append((conninfo, kwargs))
        if len(calls) < 3:
            raise psycopg.OperationalError("connection refused")
        return _Conn()

    wait_for_db(URL, timeout=10, connect=connect, sleep=clock.sleep, clock=clock)
    assert len(calls) == 3
    assert calls[0] == ("postgresql://talos:talos@db:5432/talos", {"connect_timeout": 3})


def test_gives_up_after_the_timeout():
    clock = _Clock()

    def connect(conninfo, **kwargs):
        raise psycopg.OperationalError("connection refused")

    with pytest.raises(TimeoutError, match="not reachable after 5s"):
        wait_for_db(URL, timeout=5, interval=1, connect=connect, sleep=clock.sleep, clock=clock)
    assert clock.now == 5


def test_rejects_a_non_postgres_url():
    with pytest.raises(ValueError, match="Postgres URL"):
        wait_for_db("mysql://x", connect=lambda *a, **k: _Conn())


def test_main_fails_without_database_url(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", "")
    assert wait_mod.main() == 1


def test_main_returns_zero_when_ready(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", URL)
    monkeypatch.setattr(wait_mod, "wait_for_db", lambda url, timeout: None)
    assert wait_mod.main() == 0


def test_main_reports_a_timeout(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", URL)
    monkeypatch.setenv("TALOS_DB_WAIT_TIMEOUT", "2")

    def boom(url, timeout):
        assert timeout == 2.0
        raise TimeoutError("database not reachable after 2s")

    monkeypatch.setattr(wait_mod, "wait_for_db", boom)
    assert wait_mod.main() == 1
