"""Run Alembic migrations from Python (web app start, integration tests).

`alembic/env.py` uses `asyncio.run()`, so these functions must not be
called from inside a running event loop. From async code, use
`await asyncio.to_thread(upgrade_head)`.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from talos.config import settings
from talos.persistence.db import sqlalchemy_url

ALEMBIC_INI = settings.PROJECT_ROOT / "alembic.ini"
ALEMBIC_DIR = settings.PROJECT_ROOT / "alembic"


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic config pointing at this repo's migrations and `database_url`.

    Args:
        database_url: Postgres URL; defaults to `settings.DATABASE_URL`.

    Returns:
        A Config that leaves the caller's logging setup alone.
    """
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    url = database_url if database_url is not None else settings.DATABASE_URL
    if url:
        # ConfigParser treats % as interpolation; escape it (e.g. in passwords).
        cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(url).replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_head(database_url: str | None = None) -> None:
    """`alembic upgrade head`. Safe to run when already at head."""
    command.upgrade(alembic_config(database_url), "head")


def downgrade_base(database_url: str | None = None) -> None:
    """`alembic downgrade base`: drops every table Alembic owns."""
    command.downgrade(alembic_config(database_url), "base")
