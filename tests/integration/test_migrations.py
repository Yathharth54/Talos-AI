"""Alembic round-trip and model/migration agreement (spec 01 §8)."""

from __future__ import annotations

import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
from talos.persistence.db import make_engine
from talos.persistence.migrations import downgrade_base, upgrade_head
from talos.persistence.models import LANGGRAPH_TABLES, Base, include_object

pytestmark = pytest.mark.integration

APP_TABLES = {"sessions", "messages", "runs", "run_events", "app_settings"}


async def _tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    finally:
        await engine.dispose()


async def _diff(url: str) -> list:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:

            def _compare(sync_conn):
                ctx = MigrationContext.configure(
                    sync_conn, opts={"include_object": include_object, "compare_type": True}
                )
                return compare_metadata(ctx, Base.metadata)

            return await conn.run_sync(_compare)
    finally:
        await engine.dispose()


def test_upgrade_then_downgrade_round_trips(migrated_url):
    downgrade_base(migrated_url)
    assert asyncio.run(_tables(migrated_url)) & APP_TABLES == set()

    upgrade_head(migrated_url)
    assert APP_TABLES <= asyncio.run(_tables(migrated_url))

    upgrade_head(migrated_url)  # already at head: harmless


def test_models_match_the_migration(migrated_url):
    assert asyncio.run(_diff(migrated_url)) == []


async def test_downgrade_leaves_langgraph_tables_alone(migrated_url):
    saver = await open_postgres_saver(migrated_url)
    await close_postgres_saver(saver)

    await asyncio.to_thread(downgrade_base, migrated_url)
    try:
        assert LANGGRAPH_TABLES <= await _tables(migrated_url)
    finally:
        await asyncio.to_thread(upgrade_head, migrated_url)
