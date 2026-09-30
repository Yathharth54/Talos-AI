"""LangGraph's Postgres checkpointer for the web app (spec 01 §4).

Paused runs (approval and API-key interrupts) live in LangGraph checkpoints.
With `AsyncPostgresSaver` they survive an app restart, so a later resume
works. The saver creates and migrates its own tables in `setup()`.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from talos.config import settings
from talos.persistence.db import libpq_url


async def open_postgres_saver(
    database_url: str | None = None, *, max_size: int = 10
) -> AsyncPostgresSaver:
    """Open a connection pool, wrap it in a saver, and run `setup()` once.

    The pool uses the connection settings the saver requires: autocommit,
    no prepared statements (`prepare_threshold=0`) and dict rows. The
    serializer matches `talos.graph.make_checkpointer()`: pickle fallback
    for values msgpack can't hold (2**100, sets).

    Args:
        database_url: Postgres URL; defaults to `settings.DATABASE_URL`.
        max_size: Most connections the pool opens.

    Returns:
        A ready saver. Close it with `close_postgres_saver()`.

    Raises:
        RuntimeError: No URL was given and DATABASE_URL is empty.
    """
    url = database_url if database_url is not None else settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set. The Postgres checkpointer needs it.")
    pool = AsyncConnectionPool(
        libpq_url(url),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open(wait=True)
    try:
        saver = AsyncPostgresSaver(pool, serde=JsonPlusSerializer(pickle_fallback=True))
        await saver.setup()
    except BaseException:
        await pool.close()
        raise
    return saver


async def close_postgres_saver(saver: AsyncPostgresSaver) -> None:
    """Close the pool behind a saver from `open_postgres_saver()`."""
    conn = saver.conn
    if isinstance(conn, AsyncConnectionPool):
        await conn.close()
