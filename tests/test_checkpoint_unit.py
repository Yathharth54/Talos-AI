"""The Postgres saver factory without a database."""

from __future__ import annotations

import pytest

from talos.persistence import checkpoint


async def test_open_postgres_saver_without_url_explains(monkeypatch):
    monkeypatch.setattr(checkpoint.settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await checkpoint.open_postgres_saver()
