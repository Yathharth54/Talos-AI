"""Fixtures for Postgres integration tests.

Isolation: the schema is rebuilt once per test session (downgrade base,
upgrade head), and every test starts from empty tables, including
LangGraph's checkpoint tables when they exist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from talos.persistence.db import make_engine
from talos.persistence.migrations import downgrade_base, upgrade_head

_APP_TABLES = "sessions, runs, messages, run_events, app_settings"
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    """DATABASE_URL with a freshly built schema (sync: Alembic runs its own loop)."""
    downgrade_base(database_url)
    upgrade_head(database_url)
    return database_url


@pytest.fixture
async def factory(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on empty tables."""
    engine = make_engine(migrated_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_APP_TABLES} RESTART IDENTITY CASCADE"))
        for table in _CHECKPOINT_TABLES:
            exists = await conn.scalar(text("select to_regclass(:t)"), {"t": table})
            if exists is not None:
                await conn.execute(text(f"TRUNCATE {table}"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
