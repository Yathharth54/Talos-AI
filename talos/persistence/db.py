"""Async engine and session handling for the web app's database.

One engine per process. `init_db()` creates it at app start, `get_db()`
hands out sessions (a FastAPI dependency in stage 2), and `session_scope()`
does the same for code outside a request, like the run manager.

Transactions: repo functions never commit. `session_scope()` / `get_db()`
commit when the block exits cleanly and roll back on an exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from talos.config import settings

_SQLALCHEMY_SCHEME = "postgresql+psycopg"
_ACCEPTED_SCHEMES = ("postgresql+psycopg://", "postgresql://", "postgres://")

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def sqlalchemy_url(url: str) -> str:
    """Normalise a Postgres URL to the `postgresql+psycopg://` form SQLAlchemy needs.

    Raises:
        ValueError: The URL is empty or not a Postgres URL.
    """
    url = (url or "").strip()
    for scheme in _ACCEPTED_SCHEMES:
        if url.startswith(scheme):
            return f"{_SQLALCHEMY_SCHEME}://{url[len(scheme) :]}"
    raise ValueError(
        "DATABASE_URL must be a Postgres URL like "
        "postgresql+psycopg://talos:talos@localhost:5432/talos"
    )


def libpq_url(url: str) -> str:
    """The same URL in the plain `postgresql://` form psycopg itself accepts."""
    return "postgresql://" + sqlalchemy_url(url)[len(_SQLALCHEMY_SCHEME) + 3 :]


def make_engine(url: str | None = None) -> AsyncEngine:
    """Create an async engine for `url` (default: `settings.DATABASE_URL`).

    Raises:
        RuntimeError: No URL was given and DATABASE_URL is empty.
    """
    url = url if url is not None else settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set. The web app needs a Postgres database.")
    return create_async_engine(sqlalchemy_url(url), pool_pre_ping=True)


def init_db(url: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Create the process-wide engine and session factory. Idempotent per process.

    Only the first call uses `url`; later calls ignore it and return the
    existing factory.

    `expire_on_commit=False` keeps loaded objects readable after the
    session that loaded them has committed and closed.
    """
    global _engine, _factory
    if _factory is None:
        _engine = make_engine(url)
        _factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _factory


def session_factory() -> async_sessionmaker[AsyncSession]:
    """The factory created by `init_db()`.

    Raises:
        RuntimeError: `init_db()` has not been called.
    """
    if _factory is None:
        raise RuntimeError("Database not initialised: call talos.persistence.db.init_db() first.")
    return _factory


async def dispose_db() -> None:
    """Close the engine's connections and forget it (app shutdown, tests)."""
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """One transaction: commit on clean exit, roll back on an exception.

    Args:
        factory: Session factory to use; defaults to the one from `init_db()`.
    """
    async with (factory or session_factory())() as db:
        try:
            yield db
        except BaseException:
            await db.rollback()
            raise
        await db.commit()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session whose transaction commits after the request."""
    async with session_scope() as db:
        yield db
