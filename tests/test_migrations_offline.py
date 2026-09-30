"""Alembic checks that need no database: env.py finds every table."""

from __future__ import annotations

import io
import logging

from alembic import command
from alembic.script import ScriptDirectory

from talos.persistence.migrations import alembic_config
from talos.persistence.models import LANGGRAPH_TABLES

TABLES = {"sessions", "messages", "runs", "run_events", "app_settings"}


def test_alembic_has_one_head_named_0001_initial():
    script = ScriptDirectory.from_config(alembic_config("postgresql://u:p@h/d"))
    assert script.get_heads() == ["0001_initial"]


def test_offline_upgrade_creates_every_table_and_no_checkpoint_table():
    """env.py loads the models: the offline SQL creates all five tables.

    Also: running Alembic from Python must not disable the app's loggers.
    """
    probe = logging.getLogger("talos.probe")
    cfg = alembic_config("postgresql+psycopg://u:p@h:5432/d")
    buf = io.StringIO()
    cfg.output_buffer = buf

    command.upgrade(cfg, "head", sql=True)

    sql = buf.getvalue()
    for table in TABLES:
        assert f"CREATE TABLE {table} " in sql
    for table in LANGGRAPH_TABLES:
        assert f"CREATE TABLE {table} " not in sql
    assert "gen_random_uuid()" in sql
    assert "CREATE INDEX ix_runs_active ON runs (status) WHERE status in" in sql
    assert probe.disabled is False


def test_alembic_config_escapes_percent_in_passwords():
    cfg = alembic_config("postgresql://u:p%40ss@h/d")
    assert cfg.get_main_option("sqlalchemy.url") == "postgresql+psycopg://u:p%40ss@h/d"
