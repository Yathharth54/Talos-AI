"""Alembic environment: async engine, Talos models, LangGraph tables ignored.

Runs with `asyncio.run()`, so call it from a thread when an event loop is
already running (the web app does `await asyncio.to_thread(upgrade_head)`).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from talos.config import settings
from talos.persistence.db import sqlalchemy_url
from talos.persistence.models import Base, include_object

config = context.config

# Only the `alembic` CLI configures logging. Programmatic callers set
# configure_logger=False so their own logging setup survives.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set; Alembic needs a Postgres URL.")
    return sqlalchemy_url(url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations against the database."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
