# Talos Web App Stage 01 (Persistence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web app durable Postgres storage (sessions, messages, runs, run events, settings) and a Postgres LangGraph checkpointer, plus the core-graph changes (`emit()` events, per-test results, `changed`, `SkillManager.remove`, path settings, `build_app`) that stage 2 builds on. The CLI's behaviour doesn't change.

**Architecture:** A new `talos/persistence/` package: SQLAlchemy 2.0 async models, an engine/session module, plain async repo functions, Alembic migrations (async `env.py`, revision `0001_initial`), an `AsyncPostgresSaver` factory and a startup recovery function. Graph nodes gain cheap `emit()` calls that do nothing unless a `stream_mode="custom"` consumer is listening. `talos/graph.py` gets `build_app(checkpointer)`, and the module-level `app` stays on `MemorySaver`.

**Tech Stack:** Python 3.11+, LangGraph 1.1.x, `langgraph-checkpoint-postgres` 3.x, SQLAlchemy 2.0 (`[asyncio]`), Alembic 1.x, psycopg 3 (`[binary,pool]`), pytest + pytest-asyncio 1.x, Postgres 16, ruff.

**Spec:** `docs/superpowers/specs/2026-09-30-talos-web-01-persistence-design.md` (the authority for this stage). The event contract is in `docs/superpowers/specs/2026-09-30-talos-web-app-overview-design.md` §4 (normative, especially §4.3 and §4.4). Stage 2 (`2026-09-30-talos-web-02-api-design.md`) consumes the repo functions, `SessionSummary`, `translator_state`, `pending_interrupt`, `recover_runs()`, `open_postgres_saver()` and `upgrade_head()`.

## Global Constraints

- Python `>=3.11`; type hints everywhere; Google-style docstrings on public functions; `logging`, never `print` (except the existing REPL output in `talos/main.py`).
- `ruff check .` and `ruff format --check .` must pass (line length 100, rules `E, F, I, W, UP`).
- New dependencies exactly: `sqlalchemy[asyncio]>=2.0`, `alembic>=1.13`, `psycopg[binary,pool]>=3.2`, `langgraph-checkpoint-postgres>=2.0`. Add them with `uv add` so `uv.lock` updates. (`[asyncio]` pulls in `greenlet`; SQLAlchemy's async engine fails without it.)
- Database: PostgreSQL 16. URL form `postgresql+psycopg://talos:talos@localhost:5432/talos`. Empty `DATABASE_URL` means no database.
- Settings (spec §3): `DATABASE_URL` (default empty), `TALOS_CHECKPOINTER` (`memory` default, or `postgres`), `TALOS_VAULT_DIR` (default `<repo>/talos/vault`), `TALOS_WORKSPACE_DIR` (default `<repo>/workspace`), `TALOS_DOTENV_PATH` (default `<repo>/.env`).
- Checkpoint tables are created by `await saver.setup()`, never by Alembic. Alembic must ignore `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`.
- Saver serializer: `JsonPlusSerializer(pickle_fallback=True)`, same as `make_checkpointer()`. Saver pool: `autocommit=True`, `prepare_threshold=0`, `row_factory=dict_row`.
- Naming convention: `pk_%(table_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `ix_%(column_0_label)s`, `uq_%(table_name)s_%(column_0_name)s`, `ck_%(table_name)s_%(constraint_name)s`.
- `app = build_app()` stays at module level in `talos/graph.py`. The existing suite (160 passed, 7 skipped on this branch) stays green. `uv run pytest` with no database must pass.
- `emit()` calls are keyword-only data and cheap. No behaviour change without a stream.
- Commit messages: prefix `[Feat]:`, `[Fix]:`, `[Docs]:` or `[Chore]:`, then a blank line and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Spec §8 lists "`copy.py` strings are checked against the reference file" as a unit test. `copy.py` is `talos/web/copy.py`, a stage 2 file, so **that test moves to stage 2's plan**. It is not in this plan.

## Review Focus

1. **A developer's `.env` has `DATABASE_URL` (copied from `.env.example`) pointing at their real database, and they run `uv run pytest`.** Expected: nothing touches that database. Integration tests only run when `DATABASE_URL` is exported in the shell (read in `tests/conftest.py` before `talos.config.settings` loads `.env`) **and** `-m integration` is given. Pinned by `tests/test_integration_gate.py` (Task 7).
2. **A `python_exec` approval resumes, LangGraph re-runs the executor node, and the ArgResolver drifts.** Expected: the stream reports only the approved arguments, once, and nothing before approval. Pinned by `test_executor_emits_only_approved_args_after_resume` (Task 4).
3. **Event data that itself contains a `type` key (`call.result` has `type`).** Expected: `emit("call.result", type="int", ...)` works; the chunk is `{"type": "call.result", "data": {..., "type": "int"}}`. `event_type` is positional-only. Pinned by `test_emit_under_custom_stream_sends_type_and_data` (Task 2) and `test_executor_emits_result_for_a_successful_call` (Task 4).
4. **Stage 2 runs `upgrade_head()` inside the app process.** Expected: Alembic doesn't reconfigure or disable the app's loggers, and a `%` in the DB password doesn't crash ConfigParser. Pinned by `test_offline_upgrade_creates_every_table_and_no_checkpoint_table` (logger check) and `test_alembic_config_escapes_percent_in_passwords` (Task 7).
5. **A paused run whose state holds values msgpack can't encode (`2**100`, sets), then an app restart.** Expected: the resume works and the value comes back intact through the Postgres saver. Pinned by `test_interrupt_survives_a_restart` (Task 9).

Also covered: 20 concurrent `append_event` calls give `seq` 1..20 with no gaps or duplicates, and a rolled-back append leaves no gap (Task 8).

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `talos/config/settings.py` | modify | path + persistence settings from env |
| `talos/agents/hitl.py` | modify | `DOTENV_PATH` from settings |
| `talos/main.py` | modify | warn when `TALOS_CHECKPOINTER=postgres` (CLI stays in-memory) |
| `talos/events.py` | create | `emit()` |
| `talos/agents/tester.py` | modify | per-test `results`, `forge.tests` |
| `talos/agents/forger.py` | modify | `first_changed_line`, `forge.code` |
| `talos/agents/smoke.py` | modify | `forge.smoke` |
| `talos/vault/manager.py` | modify | `get()`, `remove()` |
| `talos/agents/learner.py` | modify | `vault.saved` |
| `talos/agents/executor.py` | modify | `call.args`, `call.result`, `call.error`, `vault.failure` |
| `talos/graph.py` | modify | `build_app(checkpointer)` |
| `talos/persistence/__init__.py` | create | package doc |
| `talos/persistence/models.py` | create | 5 models, naming convention, `include_object`, `format_ts` |
| `talos/persistence/db.py` | create | URL normalising, engine, session factory, `session_scope`, `get_db` |
| `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py` | create | migrations |
| `talos/persistence/migrations.py` | create | `alembic_config`, `upgrade_head`, `downgrade_base` |
| `talos/persistence/repo.py` | create | repo functions, `SessionSummary` |
| `talos/persistence/checkpoint.py` | create | `open_postgres_saver`, `close_postgres_saver` |
| `talos/persistence/recovery.py` | create | `recover_runs` |
| `tests/conftest.py` | modify | integration gate, `database_url` fixture |
| `tests/integration/*` | create | Postgres tests |
| `pyproject.toml`, `uv.lock` | modify | deps, pytest config, ruff isort |
| `README.md`, `.env.example`, `PROGRESS.md` | modify | docs (Task 10) |

---

### Task 1: Path and persistence settings

**Files:**
- Modify: `talos/config/settings.py` (the `PROJECT_ROOT`/`load_dotenv` lines at the top, and the `VAULT_DIR`…`WORKSPACE_DIR` block)
- Modify: `talos/agents/hitl.py:31`
- Modify: `talos/main.py` (imports, new `warn_if_postgres_checkpointer`, first lines of `main()`)
- Test: `tests/test_settings.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `settings.DOTENV_PATH: Path`, `settings.VAULT_DIR: Path`, `settings.VAULT_TOOLS_DIR: Path`, `settings.VAULT_MANIFEST_PATH: Path`, `settings.WORKSPACE_DIR: Path`, `settings.DATABASE_URL: str` (stripped, `""` = none), `settings.CHECKPOINTER: str` (`"memory"` or `"postgres"`, lower-cased; any other value raises `ValueError` at import), `settings.CHECKPOINTER_KINDS: frozenset[str]`. `talos.main.warn_if_postgres_checkpointer() -> bool`. `hitl.DOTENV_PATH` stays a module attribute (tests monkeypatch it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings.py`:

```python
"""Path and persistence settings are read from the environment (spec 01 §3)."""

from __future__ import annotations

import importlib
from pathlib import Path

import dotenv
import pytest

from talos.config import settings

_VARS = (
    "TALOS_VAULT_DIR",
    "TALOS_WORKSPACE_DIR",
    "TALOS_DOTENV_PATH",
    "DATABASE_URL",
    "TALOS_CHECKPOINTER",
)


@pytest.fixture
def reload_settings(monkeypatch):
    """Reload settings under a patched environment, then restore it."""

    # Keep a developer's real .env out of these tests.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _reload(**env: str):
        for name in _VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(settings)

    yield _reload
    monkeypatch.undo()
    importlib.reload(settings)


def test_path_defaults_live_under_the_repo(reload_settings):
    s = reload_settings()
    assert s.VAULT_DIR == s.PROJECT_ROOT / "talos" / "vault"
    assert s.VAULT_TOOLS_DIR == s.VAULT_DIR / "tools"
    assert s.VAULT_MANIFEST_PATH == s.VAULT_DIR / "manifest.json"
    assert s.WORKSPACE_DIR == s.PROJECT_ROOT / "workspace"
    assert s.DOTENV_PATH == s.PROJECT_ROOT / ".env"


def test_path_overrides_come_from_env(reload_settings, tmp_path: Path):
    s = reload_settings(
        TALOS_VAULT_DIR=str(tmp_path / "v"),
        TALOS_WORKSPACE_DIR=str(tmp_path / "w"),
        TALOS_DOTENV_PATH=str(tmp_path / "keys.env"),
    )
    assert s.VAULT_DIR == tmp_path / "v"
    assert s.VAULT_TOOLS_DIR == tmp_path / "v" / "tools"
    assert s.VAULT_MANIFEST_PATH == tmp_path / "v" / "manifest.json"
    assert s.WORKSPACE_DIR == tmp_path / "w"
    assert s.DOTENV_PATH == tmp_path / "keys.env"


def test_empty_path_override_falls_back_to_default(reload_settings):
    s = reload_settings(TALOS_VAULT_DIR="")
    assert s.VAULT_DIR == s.PROJECT_ROOT / "talos" / "vault"


def test_database_defaults(reload_settings):
    s = reload_settings()
    assert s.CHECKPOINTER == "memory"
    assert s.DATABASE_URL == ""


def test_checkpointer_is_normalised(reload_settings):
    s = reload_settings(TALOS_CHECKPOINTER=" Postgres ", DATABASE_URL="postgresql+psycopg://x")
    assert s.CHECKPOINTER == "postgres"
    assert s.DATABASE_URL == "postgresql+psycopg://x"


def test_unknown_checkpointer_is_rejected(reload_settings):
    with pytest.raises(ValueError, match="TALOS_CHECKPOINTER"):
        reload_settings(TALOS_CHECKPOINTER="sqlite")


def test_hitl_writes_to_the_configured_dotenv():
    from talos.agents import hitl

    assert hitl.DOTENV_PATH == settings.DOTENV_PATH


def test_cli_warns_but_stays_in_memory_when_postgres_is_asked(monkeypatch, caplog):
    from talos import main as main_mod
    from talos.graph import app, checkpointer

    monkeypatch.setattr(main_mod.settings, "CHECKPOINTER", "postgres")
    with caplog.at_level("WARNING", logger="talos.main"):
        assert main_mod.warn_if_postgres_checkpointer() is True
    assert "in-memory" in caplog.text
    assert app.checkpointer is checkpointer

    monkeypatch.setattr(main_mod.settings, "CHECKPOINTER", "memory")
    assert main_mod.warn_if_postgres_checkpointer() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'DOTENV_PATH'` / `'CHECKPOINTER'`, and `warn_if_postgres_checkpointer` missing).

- [ ] **Step 3: Implement the settings**

In `talos/config/settings.py`, replace

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
```

with

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Where HITL writes API keys, and the .env we load at startup. Read before
# load_dotenv so the file itself can't redirect where it is read from.
DOTENV_PATH = Path(os.environ.get("TALOS_DOTENV_PATH") or PROJECT_ROOT / ".env")
load_dotenv(DOTENV_PATH)
```

and replace

```python
VAULT_DIR = PROJECT_ROOT / "talos" / "vault"
VAULT_TOOLS_DIR = VAULT_DIR / "tools"
VAULT_MANIFEST_PATH = VAULT_DIR / "manifest.json"

# Where Talos writes files when the user doesn't specify an absolute path.
# All relative paths in file_read/file_write get anchored here. Gitignored.
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
```

with

```python
# Vault location. TALOS_VAULT_DIR lets Docker mount the vault elsewhere.
VAULT_DIR = Path(os.environ.get("TALOS_VAULT_DIR") or PROJECT_ROOT / "talos" / "vault")
VAULT_TOOLS_DIR = VAULT_DIR / "tools"
VAULT_MANIFEST_PATH = VAULT_DIR / "manifest.json"

# Where Talos writes files when the user doesn't specify an absolute path.
# All relative paths in file_read/file_write get anchored here. Gitignored.
WORKSPACE_DIR = Path(os.environ.get("TALOS_WORKSPACE_DIR") or PROJECT_ROOT / "workspace")

# Persistence. Empty DATABASE_URL means no database (the CLI default).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
CHECKPOINTER_KINDS = frozenset({"memory", "postgres"})
CHECKPOINTER = os.environ.get("TALOS_CHECKPOINTER", "memory").strip().lower() or "memory"
if CHECKPOINTER not in CHECKPOINTER_KINDS:
    raise ValueError(
        f"TALOS_CHECKPOINTER must be one of {sorted(CHECKPOINTER_KINDS)}, got {CHECKPOINTER!r}"
    )
```

In `talos/agents/hitl.py`, replace

```python
DOTENV_PATH: Path = settings.PROJECT_ROOT / ".env"
```

with

```python
DOTENV_PATH: Path = settings.DOTENV_PATH
```

In `talos/main.py`, replace the import block

```python
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from talos.config.logging import setup_logging
from talos.graph import app
```

with

```python
import logging
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from talos.config import settings
from talos.config.logging import setup_logging
from talos.graph import app

log = logging.getLogger(__name__)


def warn_if_postgres_checkpointer() -> bool:
    """Log a warning when TALOS_CHECKPOINTER asks the CLI for Postgres.

    The REPL is synchronous and starts a fresh thread per process, so it
    always keeps the in-memory checkpointer. Postgres is for the web app.

    Returns:
        True if a warning was logged.
    """
    if settings.CHECKPOINTER == "memory":
        return False
    log.warning(
        "TALOS_CHECKPOINTER=%s applies to the web app; the CLI keeps its in-memory checkpointer.",
        settings.CHECKPOINTER,
    )
    return True
```

and in `main()` replace

```python
def main() -> None:
    setup_logging()
```

with

```python
def main() -> None:
    setup_logging()
    warn_if_postgres_checkpointer()
```

- [ ] **Step 4: Run the tests to verify they pass, plus the full suite**

Run: `uv run pytest tests/test_settings.py -v && uv run pytest -q`
Expected: 8 passed in `test_settings.py`; full suite 168 passed, 7 skipped.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add talos/config/settings.py talos/agents/hitl.py talos/main.py tests/test_settings.py
git commit -m "$(cat <<'EOF'
[Feat]: Read vault, workspace, .env and database settings from the environment

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `emit()` helper and async test support

**Files:**
- Create: `talos/events.py`
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]`)
- Test: `tests/test_events.py` (create)

**Interfaces:**
- Consumes: `langgraph.config.get_stream_writer` (verified on langgraph 1.1.10: raises `RuntimeError("Called get_config outside of a runnable context")` outside a run; returns a no-op writer under `invoke()` or a stream without `"custom"`).
- Produces: `talos.events.emit(event_type: str, /, **data: Any) -> None`. A `stream_mode="custom"` consumer receives `{"type": event_type, "data": data}`. With `subgraphs=True` the chunk arrives as `(namespace_tuple, "custom", {...})`. Stage 2's `EventTranslator` reads this shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_events.py`:

```python
"""emit() is a no-op without a stream and a custom chunk with one."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from talos.events import emit


class _S(TypedDict, total=False):
    x: int


def _graph():
    def node(state: _S) -> dict:
        emit("call.result", repr="3", type="int", small=True)
        return {"x": 1}

    g: StateGraph = StateGraph(_S)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


def test_emit_outside_a_graph_is_a_noop():
    assert emit("forge.smoke", call=None, result=None, passed=False) is None


def test_emit_under_invoke_is_a_noop():
    assert _graph().invoke({"x": 0}) == {"x": 1}


def test_emit_under_updates_only_stream_sends_nothing():
    chunks = list(_graph().stream({"x": 0}, stream_mode="updates"))
    assert chunks == [{"n": {"x": 1}}]


def test_emit_under_custom_stream_sends_type_and_data():
    chunks = list(_graph().stream({"x": 0}, stream_mode=["custom", "updates"]))
    assert (
        "custom",
        {"type": "call.result", "data": {"repr": "3", "type": "int", "small": True}},
    ) in chunks


async def test_emit_reaches_async_stream_from_a_sync_node():
    chunks = [c async for c in _graph().astream({"x": 0}, stream_mode="custom")]
    assert chunks == [{"type": "call.result", "data": {"repr": "3", "type": "int", "small": True}}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'talos.events'`.

- [ ] **Step 3: Implement `emit()` and enable async tests**

Create `talos/events.py`:

```python
"""Custom run events for the web app's event stream (overview spec §4.4).

Nodes call `emit()` to report facts that are not in their state updates:
the Forger's code for an attempt, per-test results, the smoke call, the
Executor's resolved arguments and result, vault saves and failures.

LangGraph concept: inside a node, `get_stream_writer()` returns a function
that pushes a chunk to any `stream_mode="custom"` consumer. Under `invoke()`
or a stream without "custom" it is a no-op, and outside a graph run it
raises RuntimeError. `emit()` hides both cases, so the CLI and the unit
tests behave exactly as before.

Chunk shape seen by a consumer: `{"type": event_type, "data": {...}}`.
"""

from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def emit(event_type: str, /, **data: Any) -> None:
    """Send a custom stream event if a stream is listening; otherwise do nothing.

    `event_type` is positional-only so event data may itself contain a
    `type` key (e.g. `call.result` carries the result's type name).

    Args:
        event_type: A contract event type, e.g. "forge.code".
        **data: The event's data fields, JSON-serialisable.

    Example:
        >>> emit("forge.smoke", call="add(a=1, b=2)", result="3", passed=True)
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return  # not inside a graph run (plain function call, unit test)
    writer({"type": event_type, "data": data})
```

In `pyproject.toml`, append to the end of `[tool.pytest.ini_options]` (after the `python_functions` line):

```toml
# Async tests (persistence, event streams) run without per-test markers.
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_events.py -v && uv run pytest -q`
Expected: 5 passed; full suite 173 passed, 7 skipped.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add talos/events.py tests/test_events.py pyproject.toml
git commit -m "$(cat <<'EOF'
[Feat]: Add emit() for custom run events

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Forge-loop events (tester results, forger `changed`, smoke)

**Files:**
- Modify: `talos/agents/tester.py` (`run_tests` timeout branch, `tester_node`, `_parse_runner_output`, new `_last_line`, imports)
- Modify: `talos/agents/forger.py` (imports, end of `forger_node`, new `first_changed_line`)
- Modify: `talos/agents/smoke.py` (imports, new helpers, `smoke_node`)
- Test: `tests/test_tester.py`, `tests/test_forger.py`, `tests/test_smoke.py` (append)

**Interfaces:**
- Consumes: `talos.events.emit` (Task 2).
- Produces:
  - `run_tests(...)` and `tester_node(...)["test_result"]` gain `results: list[{"name": str, "passed": bool, "why": str | None}]` in run order (`[]` on timeout, crash before tests, or no code). `why` = last non-empty traceback line of a failing test.
  - `tester_node` emits `forge.tests {tool: str, attempt: int, results}`. `attempt` = `state["retry_count"]` (the Forger already incremented it).
  - `talos.agents.forger.first_changed_line(previous: str | None, current: str) -> int | None`.
  - `forger_node` emits `forge.code {tool, attempt, file: "{name}.py", lines: list[str], changed: int | None, note: None}`.
  - `talos.agents.smoke.short_repr(value: Any, limit: int = 200) -> str`.
  - `smoke_node` emits `forge.smoke {call: str | None, result: str | None, passed: bool}` whenever the gate didn't skip. No event when it skips.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tester.py`:

```python


# --- per-test results (spec 01 §9.2) ------------------------------------------


def test_run_tests_reports_each_test_in_order():
    code = "def add(a: int, b: int) -> int:\n    return a + b + (1 if a == 2 else 0)\n"
    test_code = (
        "def test_zero():\n    assert add(0, 0) == 0\n\n"
        "def test_two():\n    assert add(2, 3) == 5, 'add(2, 3) should be 5'\n\n"
        "def test_one():\n    assert add(1, 1) == 2\n"
    )
    r = run_tests(code, test_code)
    assert r["results"] == [
        {"name": "test_zero", "passed": True, "why": None},
        {"name": "test_two", "passed": False, "why": "AssertionError: add(2, 3) should be 5"},
        {"name": "test_one", "passed": True, "why": None},
    ]


def test_run_tests_results_empty_when_code_does_not_compile():
    r = run_tests("def broken(:\n    pass\n", "def test_x():\n    assert True\n")
    assert r["results"] == []


def test_run_tests_results_empty_on_timeout():
    code = "def loop() -> None:\n    while True:\n        pass\n"
    r = run_tests(code, "def test_loop():\n    loop()\n", timeout=2)
    assert r["results"] == []


def test_failing_test_without_message_uses_exception_name():
    code = "def f() -> int:\n    return 1\n"
    r = run_tests(code, "def test_f():\n    assert f() == 2\n")
    assert r["results"] == [{"name": "test_f", "passed": False, "why": "AssertionError"}]


def test_tester_node_emits_forge_tests():
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("test", tester_node)
    g.add_edge(START, "test")
    g.add_edge("test", END)
    forged = {
        "name": "add",
        "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "test_code": "def test_add():\n    assert add(1, 2) == 3\n",
    }
    chunks = list(
        g.compile().stream({"forged_tool": forged, "retry_count": 2}, stream_mode="custom")
    )
    assert chunks == [
        {
            "type": "forge.tests",
            "data": {
                "tool": "add",
                "attempt": 2,
                "results": [{"name": "test_add", "passed": True, "why": None}],
            },
        }
    ]


def test_tester_node_without_code_reports_no_results():
    out = tester_node({"forged_tool": {"name": "x", "code": "", "test_code": ""}})  # type: ignore[arg-type]
    assert out["test_result"]["results"] == []
    assert out["test_result"]["passed"] is False
```

Append to `tests/test_forger.py`:

```python


# ---- forge.code event and `changed` (spec 01 §9.3) --------------------------


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, "a\nb\n", None),
        ("a\nb\nc\n", "a\nb\nc\n", None),
        ("a\nb\nc\n", "a\nB\nc\n", 2),
        ("a\nb\n", "a\nb\nc\n", 3),
        ("x\n", "y\n", 1),
        ("a\nb\nc\n", "a\nb\n", 2),
        ("", "a\n", 1),
        ("a\n", "", 1),
    ],
)
def test_first_changed_line(previous, current, expected):
    from talos.agents.forger import first_changed_line

    assert first_changed_line(previous, current) == expected


def _forge_events(state: dict) -> list[dict]:
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("forge", forger_node)
    g.add_edge(START, "forge")
    g.add_edge("forge", END)
    return list(g.compile().stream(state, stream_mode="custom"))


def test_forger_emits_code_with_no_changed_on_attempt_one(monkeypatch):
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: _FakeLLM([_good_tool()]))
    events = _forge_events({"current_sub_task": {"action": "reverse a string"}})
    assert events == [
        {
            "type": "forge.code",
            "data": {
                "tool": "reverse_string",
                "attempt": 1,
                "file": "reverse_string.py",
                "lines": ["def reverse_string(s: str) -> str:", "    return s[::-1]"],
                "changed": None,
                "note": None,
            },
        }
    ]


def test_forger_emits_first_changed_line_on_retry(monkeypatch):
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: _FakeLLM([_good_tool()]))
    state = {
        "current_sub_task": {"action": "reverse a string"},
        "retry_count": 1,
        "forged_tool": _broken_tool().model_dump(),
        "test_result": {"passed": False, "error": "test_basic failed", "timed_out": False},
    }
    [event] = _forge_events(state)
    assert event["data"]["attempt"] == 2
    assert event["data"]["changed"] == 2  # `return s` → `return s[::-1]`
```

Append to `tests/test_smoke.py`:

```python


# ---- forge.smoke events (overview §4.4) --------------------------------------


def _smoke_events(state: dict) -> list[dict]:
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("smoke", smoke_node)
    g.add_edge(START, "smoke")
    g.add_edge("smoke", END)
    return list(g.compile().stream(state, stream_mode="custom"))


_ADD_TASK = {
    "id": 1,
    "needs": "forge",
    "input_schema": {"a": "int", "b": "int"},
    "output_schema": "int",
    "param_bindings": {"a": 2, "b": 3},
}


def test_smoke_emits_call_and_result_on_success():
    events = _smoke_events(_state("def add(a, b):\n    return a + b\n", "add", _ADD_TASK))
    assert events == [
        {"type": "forge.smoke", "data": {"call": "add(a=2, b=3)", "result": "5", "passed": True}}
    ]


def test_smoke_emits_failure_with_the_call():
    code = "def add(a, b):\n    raise ValueError('nope')\n"
    [event] = _smoke_events(_state(code, "add", _ADD_TASK))
    assert event["data"] == {"call": "add(a=2, b=3)", "result": None, "passed": False}


def test_smoke_emits_nothing_when_skipped():
    state = _state("def f():\n    return 1\n", "f", {}, env_vars=["SOME_KEY"])
    assert _smoke_events(state) == []


def test_smoke_emits_no_call_when_the_tool_cannot_load():
    [event] = _smoke_events(_state("def add(:\n", "add", _ADD_TASK))
    assert event["data"] == {"call": None, "result": None, "passed": False}


def test_smoke_result_repr_is_capped():
    from talos.agents.smoke import short_repr

    text = short_repr("x" * 1000)
    assert len(text) == 200
    assert text.endswith("…")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tester.py tests/test_forger.py tests/test_smoke.py -v`
Expected: FAIL (`KeyError: 'results'`, `ImportError: first_changed_line`, `ImportError: short_repr`, empty event lists).

- [ ] **Step 3: Implement the tester changes**

In `talos/agents/tester.py`, add the import after `from talos.config import settings`:

```python
from talos.events import emit
```

In `run_tests`, in the `if result["timed_out"]:` return dict, add `"results": [],` right after `"failures": [],`:

```python
    if result["timed_out"]:
        return {
            "passed": False,
            "n_passed": 0,
            "n_failed": 0,
            "n_total": 0,
            "failures": [],
            "results": [],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "timed_out": True,
            "error": "Subprocess timed out (likely infinite loop).",
        }
```

Replace the whole `tester_node` function with:

```python
def tester_node(state: TalosState) -> dict:
    """LangGraph node: run the forged_tool through tests.

    Reads:  forged_tool {name, code, test_code}, retry_count (the attempt number)
    Writes: test_result {passed, results, ...full run_tests output}
    Emits:  forge.tests {tool, attempt, results}
    """
    forged = state.get("forged_tool") or {}
    code = forged.get("code", "")
    test_code = forged.get("test_code", "")
    if not code or not test_code:
        result = {
            "passed": False,
            "n_passed": 0,
            "n_failed": 0,
            "n_total": 0,
            "failures": [],
            "results": [],
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "error": "Forger produced no code or no test_code.",
        }
    else:
        result = run_tests(code, test_code)
    emit(
        "forge.tests",
        tool=forged.get("name") or "",
        attempt=state.get("retry_count", 0),
        results=result["results"],
    )
    return {"test_result": result}
```

Replace the whole `_parse_runner_output` function with the following, and add `_last_line` right after it:

```python
def _parse_runner_output(stdout: str) -> dict:
    """Parse our TALOS_TEST markers out of subprocess stdout.

    `results` lists every test in run order as `{name, passed, why}`. `why`
    is the last non-empty line of a failing test's traceback (e.g.
    "AssertionError: expected 'cba'"), and None for a passing test.
    """
    n_passed = 0
    n_failed = 0
    n_total = 0
    failures: list[dict] = []
    results: list[dict] = []
    by_name: dict[str, dict] = {}
    in_trace_for: str | None = None
    trace_buf: list[str] = []

    for line in stdout.splitlines():
        if line.startswith("TALOS_TEST PASS "):
            n_passed += 1
            name = line[len("TALOS_TEST PASS ") :].strip()
            results.append({"name": name, "passed": True, "why": None})
        elif line.startswith("TALOS_TEST FAIL "):
            n_failed += 1
            name = line[len("TALOS_TEST FAIL ") :].strip()
            record = {"name": name, "passed": False, "why": None}
            results.append(record)
            by_name[name] = record
        elif line.startswith("TALOS_TEST TRACE_START "):
            in_trace_for = line[len("TALOS_TEST TRACE_START ") :].strip()
            trace_buf = []
        elif line.startswith("TALOS_TEST TRACE_END "):
            if in_trace_for is not None:
                failures.append({"name": in_trace_for, "trace": "\n".join(trace_buf)})
                if in_trace_for in by_name:
                    by_name[in_trace_for]["why"] = _last_line(trace_buf)
            in_trace_for = None
            trace_buf = []
        elif line.startswith("TALOS_TEST SUMMARY "):
            for tok in line.split()[2:]:
                k, _, v = tok.partition("=")
                if k == "total":
                    n_total = int(v)
        elif in_trace_for is not None:
            trace_buf.append(line)

    return {
        "passed": False,  # caller overrides based on counts + crash detection
        "n_passed": n_passed,
        "n_failed": n_failed,
        "n_total": n_total,
        "failures": failures,
        "results": results,
    }


def _last_line(lines: list[str]) -> str | None:
    """Last non-empty line of a traceback, stripped; None if there is none."""
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return None
```

- [ ] **Step 4: Implement the forger changes**

In `talos/agents/forger.py`, change the stdlib imports to

```python
import difflib
import logging
from typing import Any
```

and add after `from talos.config.llm import make_structured_model`:

```python
from talos.events import emit
```

Replace the final `return` of `forger_node`

```python
    return {
        "forged_tool": forged_dump,
        "retry_count": retry_count + 1,
    }
```

with

```python
    attempt = retry_count + 1
    new_code = forged_dump.get("code") or ""
    old_code: str | None = None
    if retry_count > 0:
        old_code = (previous or {}).get("code") or ""
    emit(
        "forge.code",
        tool=forged_dump.get("name") or "",
        attempt=attempt,
        file=f"{forged_dump.get('name') or 'tool'}.py",
        lines=new_code.splitlines(),
        changed=first_changed_line(old_code, new_code),
        note=None,
    )

    return {
        "forged_tool": forged_dump,
        "retry_count": attempt,
    }


def first_changed_line(previous: str | None, current: str) -> int | None:
    """First 1-based line of `current` that differs from `previous`.

    Args:
        previous: The previous attempt's code, or None on attempt 1.
        current: This attempt's code.

    Returns:
        The line number in `current`, or None on attempt 1 or when the code
        is unchanged. If `current` only drops lines from the end, the last
        line of `current` is returned (the first line with a changed context).

    Example:
        >>> first_changed_line("a\\nb\\nc", "a\\nB\\nc")
        2
    """
    if previous is None:
        return None
    old_lines = previous.splitlines()
    new_lines = current.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            return max(1, min(j1 + 1, len(new_lines)))
    return None
```

- [ ] **Step 5: Implement the smoke changes**

In `talos/agents/smoke.py`, replace

```python
from talos.state import TalosState
```

with

```python
from talos.events import emit
from talos.state import TalosState

# Longest `call` / `result` string sent in a forge.smoke event.
_SMOKE_REPR_LIMIT = 200


def short_repr(value: Any, limit: int = _SMOKE_REPR_LIMIT) -> str:
    """repr() capped at `limit` characters, with an ellipsis when cut."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _call_text(name: str, kwargs: dict[str, Any]) -> str:
    """Render a call like `caesar_cipher(text='abc', shift=3)` for the UI."""
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    text = f"{name}({args})"
    return text if len(text) <= _SMOKE_REPR_LIMIT else text[: _SMOKE_REPR_LIMIT - 1] + "…"
```

In `smoke_node`'s docstring, after the `Writes:` line add:

```
    Emits:  forge.smoke {call, result, passed} whenever the gate did not skip.
            `call` is None when the tool could not be loaded or its
            arguments could not be built.
```

Then make these four edits inside `smoke_node`:

1. In the `except (SyntaxError, ValueError) as e:` branch after `_load_forged_function`, add as its first line:

```python
        emit("forge.smoke", call=None, result=None, passed=False)
```

2. In the `except (ValueError, TypeError) as e:` branch after `_validate_kwargs`, add as its first line:

```python
        emit("forge.smoke", call=None, result=None, passed=False)
```

3. Replace

```python
    try:
        out = fn(**kwargs)
    except Exception as e:  # noqa: BLE001 — smoke is meant to surface anything
        return {
```

with

```python
    call = _call_text(forged.get("name") or "tool", kwargs)
    try:
        out = fn(**kwargs)
    except Exception as e:  # noqa: BLE001 — smoke is meant to surface anything
        emit("forge.smoke", call=call, result=None, passed=False)
        return {
```

4. Replace the final line

```python
    return {"smoke_result": {"passed": True, "skipped": False, "output": out}}
```

with

```python
    emit("forge.smoke", call=call, result=short_repr(out), passed=True)
    return {"smoke_result": {"passed": True, "skipped": False, "output": out}}
```

(The two early `skipped: True` returns stay as they are and emit nothing.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tester.py tests/test_forger.py tests/test_smoke.py -v && uv run pytest -q`
Expected: all pass; full suite 194 passed, 7 skipped.

- [ ] **Step 7: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add talos/agents/tester.py talos/agents/forger.py talos/agents/smoke.py tests/test_tester.py tests/test_forger.py tests/test_smoke.py
git commit -m "$(cat <<'EOF'
[Feat]: Emit forge.code, forge.tests and forge.smoke from the forge loop

The Tester now returns per-test results, and the Forger reports the
first line that changed since the previous attempt.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Vault and execution events (`SkillManager.get/remove`, learn, executor)

**Files:**
- Modify: `talos/vault/manager.py` (add `get` and `remove` before `record_usage`)
- Modify: `talos/agents/learner.py` (import, end of `learn_node`)
- Modify: `talos/agents/executor.py` (import, `executor_node`, `_record_failure`, new helpers before `_last_user_text`)
- Test: `tests/test_vault_manager.py`, `tests/test_learner.py`, `tests/test_executor.py` (append)

**Interfaces:**
- Consumes: `talos.events.emit` (Task 2).
- Produces:
  - `SkillManager.get(name: str) -> SkillEntry | None`; `SkillManager.remove(name: str) -> bool` (manifest entry removed, `.py` kept; used by stage 2's `DELETE /api/vault/{name}`).
  - `learn_node` emits `vault.saved {tool: SkillEntry (the finalised manifest entry), sub: None}`.
  - `executor_node` emits, in order: `call.args {tool, args: [[name, repr, suspicious]], caption: None}`; then `call.result {repr, type, small}` or `call.error {error, when: "run"}`; then `vault.failure {tool, streak, pruned, error}` when a manifest tool raised. Early failures emit only `call.error` with `when` in `"skipped" | "dispatch" | "arguments" | "declined"`. For `python_exec`/`shell_exec` confirmation, `call.args` is emitted only after approval, with the approved args.
  - `executor.is_suspicious(declared: str | None, value: Any) -> bool`, `executor.describe_args(fn, args, kwargs) -> list[list[Any]]`, `executor.describe_result(output) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_manager.py`:

```python


# --- get / remove (spec 01 §9.4) ------------------------------------------------


def _echo(manager: SkillManager, name: str = "echo_tool") -> None:
    manager.register(
        {
            "name": name,
            "description": "echoes input",
            "keywords": ["echo"],
            "function": name,
            "signature": f"{name}(s: str) -> str",
        },
        f"def {name}(s):\n    return s\n",
    )


def test_get_returns_entry_or_none(manager: SkillManager):
    _echo(manager)
    assert manager.get("echo_tool")["signature"] == "echo_tool(s: str) -> str"
    assert manager.get("missing") is None


def test_remove_drops_entry_and_keeps_file(manager: SkillManager, tmp_path: Path):
    _echo(manager)
    _echo(manager, "other_tool")

    assert manager.remove("echo_tool") is True

    assert [e["name"] for e in manager.all()] == ["other_tool"]
    assert (tmp_path / "tools" / "echo_tool.py").exists()
    assert manager.search(["echo"])[0]["name"] == "other_tool"
    with pytest.raises(KeyError):
        manager.load("echo_tool")


def test_remove_unknown_returns_false_and_leaves_manifest(manager: SkillManager, tmp_path: Path):
    _echo(manager)
    before = (tmp_path / "manifest.json").read_text()
    assert manager.remove("missing") is False
    assert (tmp_path / "manifest.json").read_text() == before
```

Append to `tests/test_learner.py`:

```python


def _learn_graph():
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("learn", learn_node)
    g.add_edge(START, "learn")
    g.add_edge("learn", END)
    return g.compile()


def test_learn_emits_vault_saved_with_the_manifest_entry(vault):
    state = {"forged_tool": _good_forged(), "test_result": {"passed": True}}

    [event] = list(_learn_graph().stream(state, stream_mode="custom"))

    assert event["type"] == "vault.saved"
    assert event["data"]["sub"] is None
    assert event["data"]["tool"] == vault.get("reverse_string")


def test_learn_emits_nothing_when_tests_failed(vault):
    state = {"forged_tool": _good_forged(), "test_result": {"passed": False}}
    assert list(_learn_graph().stream(state, stream_mode="custom")) == []
```

Append to `tests/test_executor.py`:

```python


# ---- call.* and vault.failure events (overview §4.4) ------------------------


def _exec_events(state: dict, config: dict | None = None, resume=None) -> list[dict]:
    """Stream the one-node executor graph and return its custom events."""
    from langgraph.types import Command

    app = _exec_graph()
    config = config or {"configurable": {"thread_id": "events"}}
    events = list(app.stream(state, config=config, stream_mode="custom"))
    if resume is not None:
        events += list(app.stream(Command(resume=resume), config=config, stream_mode="custom"))
    return events


def _add_tool(vault: SkillManager, body: str = "return a + b") -> None:
    vault.register(
        {
            "name": "add",
            "description": "add",
            "keywords": ["add"],
            "function": "add",
            "signature": "add(a: int, b: int) -> int",
        },
        f"def add(a: int, b: int) -> int:\n    {body}\n",
    )


def test_executor_emits_args_then_result(vault, monkeypatch):
    _add_tool(vault)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[2], kwargs={"b": "three"}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert events[0] == {
        "type": "call.args",
        "data": {
            "tool": "add",
            "args": [["a", "2", False], ["b", "'three'", True]],
            "caption": None,
        },
    }
    assert events[1]["type"] == "call.error"  # 2 + "three" raises TypeError
    assert events[1]["data"]["when"] == "run"
    assert events[1]["data"]["error"].startswith("TypeError")


def test_executor_emits_result_for_a_successful_call(vault, monkeypatch):
    _add_tool(vault)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[2, 3], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert [e["type"] for e in events] == ["call.args", "call.result"]
    assert events[1]["data"] == {"repr": "5", "type": "int", "small": True}


def test_executor_emits_vault_failure_with_streak_and_prune(vault, monkeypatch):
    _add_tool(vault, body="raise ValueError('kaboom')")
    _patch_resolver(monkeypatch, ResolvedArgs(args=[1, 2], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    first = _exec_events(_state(current_sub_task=sub_task), {"configurable": {"thread_id": "f1"}})
    second = _exec_events(_state(current_sub_task=sub_task), {"configurable": {"thread_id": "f2"}})

    assert first[-1] == {
        "type": "vault.failure",
        "data": {"tool": "add", "streak": 1, "pruned": False, "error": "ValueError: kaboom"},
    }
    assert second[-1]["data"]["streak"] == 2
    assert second[-1]["data"]["pruned"] is True


def test_executor_emits_call_error_when_dispatch_fails(vault, monkeypatch):
    sub_task = {"id": 1, "needs": "primitive", "tool_hint": "nope", "action": "x"}
    events = _exec_events(_state(current_sub_task=sub_task))
    assert events == [
        {
            "type": "call.error",
            "data": {"error": "dispatch error: Unknown primitive: 'nope'", "when": "dispatch"},
        }
    ]


def test_executor_emits_only_approved_args_after_resume(vault, monkeypatch):
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print('shown')"}))
    monkeypatch.setitem(exec_mod.PRIMITIVES, "python_exec", lambda code: "ok")
    config = {"configurable": {"thread_id": "approve-events"}}
    app = _exec_graph()

    paused = list(app.stream(_exec_state(), config=config, stream_mode="custom"))
    assert paused == []  # nothing emitted before approval

    from langgraph.types import Command

    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print('drifted')"}))
    resume = {"approved": True, "args": [], "kwargs": {"code": "print('shown')"}}
    events = list(app.stream(Command(resume=resume), config=config, stream_mode="custom"))

    assert events[0]["data"]["args"] == [["code", "\"print('shown')\"", False]]
    assert events[1]["type"] == "call.result"


def test_executor_emits_declined(vault, monkeypatch):
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print(1)"}))
    events = _exec_events(
        _exec_state(), {"configurable": {"thread_id": "decline-events"}}, {"approved": False}
    )
    assert events == [
        {"type": "call.error", "data": {"error": "declined by user", "when": "declined"}}
    ]


@pytest.mark.parametrize(
    ("declared", "value", "expected"),
    [
        ("int", 3, False),
        ("int", "three", True),
        ("int", True, True),
        ("float", 3, False),
        ("bool", True, False),
        ("str", 3, True),
        ("list[str]", ["a"], False),
        ("list[str]", "a", True),
        ("int | None", None, False),
        ("int | None", "x", True),
        ("dict", {}, False),
        ("Any", object(), False),
        ("MyThing", 1, False),
        (None, 1, False),
        ("", 1, False),
    ],
)
def test_is_suspicious(declared, value, expected):
    assert exec_mod.is_suspicious(declared, value) is expected


def test_describe_result_marks_long_output_as_not_small_and_caps_it():
    assert exec_mod.describe_result("x" * 100)["small"] is False
    assert exec_mod.describe_result("a\nb")["small"] is True  # repr escapes the newline
    big = exec_mod.describe_result(list(range(1000)))["repr"]
    assert big.endswith("…") and len(big) == 2000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_vault_manager.py tests/test_learner.py tests/test_executor.py -v`
Expected: FAIL (`AttributeError: 'SkillManager' object has no attribute 'get'`, `is_suspicious` missing, empty event lists).

- [ ] **Step 3: Implement `get` and `remove`**

In `talos/vault/manager.py`, insert directly above `def record_usage(self, name: str) -> None:`:

```python
    def get(self, name: str) -> SkillEntry | None:
        """Return the manifest entry for `name`, or None if it isn't there."""
        return self._find(name)

    def remove(self, name: str) -> bool:
        """Remove a tool's manifest entry. The .py file stays on disk.

        Same effect as an auto-prune: search and load can no longer find
        the tool, but its source is kept for reading.

        Args:
            name: The tool's name.

        Returns:
            True if an entry was removed, False if there was none.
        """
        manifest = self._read_manifest()
        kept = [e for e in manifest if e.get("name") != name]
        if len(kept) == len(manifest):
            return False
        self._write_manifest(kept)
        return True

```

- [ ] **Step 4: Implement the learn event**

In `talos/agents/learner.py`, add after `from talos.agents.forger import ForgedTool`:

```python
from talos.events import emit
```

and replace

```python
    mgr = _get_skill_manager()
    mgr.register(entry, validated["code"])
    return {}
```

with

```python
    mgr = _get_skill_manager()
    saved = mgr.register(entry, validated["code"])
    # `sub` (the banner's second line) is filled in by the web layer's copy.
    emit("vault.saved", tool=dict(saved), sub=None)
    return {}
```

- [ ] **Step 5: Implement the executor events**

In `talos/agents/executor.py`, add after `from talos.config.llm import make_structured_model`:

```python
from talos.events import emit
```

In `executor_node`, make these replacements:

```python
        return _record_failure(state, sub_task, f"skipped: upstream sub-task {ids} failed")
```
→
```python
        return _record_failure(
            state, sub_task, f"skipped: upstream sub-task {ids} failed", when="skipped"
        )
```

```python
        result = _record_failure(state, sub_task, f"dispatch error: {e}")
        return result
```
→
```python
        return _record_failure(state, sub_task, f"dispatch error: {e}", when="dispatch")
```

```python
            return _record_failure(state, sub_task, f"contract violation: {e}")
```
→
```python
            return _record_failure(state, sub_task, f"contract violation: {e}", when="arguments")
```

```python
            return _record_failure(state, sub_task, f"arg resolution failed: {e}")
```
→
```python
            return _record_failure(state, sub_task, f"arg resolution failed: {e}", when="arguments")
```

Then replace the block from `if _needs_confirmation(sub_task):` through the end of the vault/forge usage-tracking block:

```python
    if _needs_confirmation(sub_task):
        approved = _confirm_exec(sub_task, final_args, final_kwargs)
        if approved is None:
            return _record_failure(state, sub_task, "declined by user")
        final_args, final_kwargs = approved

    try:
        output = fn(*final_args, **final_kwargs)
        ok = True
        error: str | None = None
    except Exception as e:  # noqa: BLE001 — tool execution may legitimately fail
        output = None
        ok = False
        error = f"{type(e).__name__}: {e}"

    # Vault/forge usage tracking. Success bumps usage; failure bumps
    # consecutive_failures and may auto-prune (after N failures in a row).
    if sub_task.get("needs") in {"vault", "forge"}:
        name = sub_task.get("tool_hint") or (state.get("forged_tool") or {}).get("name")
        if name:
            if ok:
                mgr.record_usage(name)
            else:
                mgr.record_failure(name, reason=error or "unknown error")
```

with

```python
    if _needs_confirmation(sub_task):
        # call.args is emitted only after approval: on resume LangGraph re-runs
        # this node and the resolver may drift, so only the approved args are
        # reported. While paused, the interrupt payload carries the preview.
        approved = _confirm_exec(sub_task, final_args, final_kwargs)
        if approved is None:
            return _record_failure(state, sub_task, "declined by user", when="declined")
        final_args, final_kwargs = approved

    emit(
        "call.args",
        tool=_tool_name(sub_task, state, fn),
        args=describe_args(fn, final_args, final_kwargs),
        caption=None,  # filled in by the web layer's copy
    )

    try:
        output = fn(*final_args, **final_kwargs)
        ok = True
        error: str | None = None
    except Exception as e:  # noqa: BLE001 — tool execution may legitimately fail
        output = None
        ok = False
        error = f"{type(e).__name__}: {e}"

    if ok:
        emit("call.result", **describe_result(output))
    else:
        emit("call.error", error=error, when="run")

    # Vault/forge usage tracking. Success bumps usage; failure bumps
    # consecutive_failures and may auto-prune (after N failures in a row).
    if sub_task.get("needs") in {"vault", "forge"}:
        name = sub_task.get("tool_hint") or (state.get("forged_tool") or {}).get("name")
        if name:
            if ok:
                mgr.record_usage(name)
            else:
                entry = mgr.get(name)
                pruned = mgr.record_failure(name, reason=error or "unknown error")
                if entry is not None:
                    emit(
                        "vault.failure",
                        tool=name,
                        streak=int(entry.get("consecutive_failures", 0)) + 1,
                        pruned=pruned,
                        error=error,
                    )
```

Replace the `_record_failure` signature and first line

```python
def _record_failure(state: TalosState, sub_task: dict, reason: str) -> dict:
    prior = state.get("sub_task_results") or []
```

with

```python
def _record_failure(state: TalosState, sub_task: dict, reason: str, *, when: str) -> dict:
    """Append a failed result for `sub_task` and emit `call.error`.

    `when` says which stage failed: "skipped", "dispatch", "arguments",
    "declined" or "run".
    """
    emit("call.error", error=reason, when=when)
    prior = state.get("sub_task_results") or []
```

Insert directly above `def _last_user_text(state: TalosState) -> str:`:

```python
# Longest repr sent for one argument / for a result in call.* events.
_ARG_REPR_LIMIT = 200
_RESULT_REPR_LIMIT = 2000
# A result repr at most this long, on one line, is shown inline ("small").
_SMALL_RESULT = 60

# Declared type name → the Python types a value may have without looking wrong.
_EXPECTED_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "list": (list, tuple),
    "dict": (dict,),
}


def _short_repr(value: Any, limit: int) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fits(value: Any, base: str) -> bool:
    expected = _EXPECTED_TYPES[base]
    if isinstance(value, bool) and bool not in expected:
        return False  # True is an int to Python, not to a reader
    return isinstance(value, expected)


def is_suspicious(declared: str | None, value: Any) -> bool:
    """True when `value` plainly doesn't fit the declared type.

    Example: `shift` declared `int` but resolved to the string "three".
    Missing or unknown annotations (Any, custom classes) are never
    suspicious. Unions are checked part by part, so `int | None` accepts None.

    Args:
        declared: The annotation text, e.g. "int", "list[str]", "int | None".
        value: The resolved argument.

    Returns:
        True only if every part of the annotation is known and rejects the value.
    """
    if not declared or not declared.strip():
        return False
    for part in re.split(r"\s*\|\s*", declared.strip()):
        base = part.split("[", 1)[0].strip()
        if base in {"None", "NoneType"}:
            if value is None:
                return False
        elif base.lower() in _EXPECTED_TYPES:
            if _fits(value, base.lower()):
                return False
        else:
            return False
    return True


def describe_args(
    fn: Callable[..., Any], args: list[Any], kwargs: dict[str, Any]
) -> list[list[Any]]:
    """Name each call argument for the `call.args` event.

    Returns:
        `[[name, repr, suspicious], ...]` in call order. Positional args
        take their parameter names from `fn`'s signature, or `arg{i}`.
    """
    schema = schema_from_signature(fn)
    try:
        names = list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        names = []
    pairs = [(names[i] if i < len(names) else f"arg{i}", v) for i, v in enumerate(args)]
    pairs += list(kwargs.items())
    return [
        [name, _short_repr(value, _ARG_REPR_LIMIT), is_suspicious(schema.get(name), value)]
        for name, value in pairs
    ]


def describe_result(output: Any) -> dict[str, Any]:
    """Data for the `call.result` event: `{repr, type, small}`."""
    text = _short_repr(output, _RESULT_REPR_LIMIT)
    return {
        "repr": text,
        "type": type(output).__name__,
        "small": len(text) <= _SMALL_RESULT and "\n" not in text,
    }


def _tool_name(sub_task: dict, state: TalosState, fn: Callable[..., Any]) -> str:
    if sub_task.get("needs") == "forge":
        return (state.get("forged_tool") or {}).get("name") or getattr(fn, "__name__", "tool")
    return sub_task.get("tool_hint") or getattr(fn, "__name__", "tool")


```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_vault_manager.py tests/test_learner.py tests/test_executor.py -v && uv run pytest -q`
Expected: all pass; full suite 221 passed, 7 skipped.

- [ ] **Step 7: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add talos/vault/manager.py talos/agents/learner.py talos/agents/executor.py tests/test_vault_manager.py tests/test_learner.py tests/test_executor.py
git commit -m "$(cat <<'EOF'
[Feat]: Emit call, vault.saved and vault.failure events; add SkillManager.remove

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `build_app(checkpointer)`

**Files:**
- Modify: `talos/graph.py` (imports; the MemorySaver comment; the last two lines)
- Test: `tests/test_graph_flow.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `talos.graph.build_app(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph`. `None` → a fresh `make_checkpointer()` (MemorySaver with pickle fallback). Module-level `checkpointer` and `app = build_app(checkpointer)` keep working. Stage 2 calls `build_app(await open_postgres_saver())`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graph_flow.py`:

```python


def test_build_app_defaults_to_a_pickle_fallback_memory_saver():
    from langgraph.checkpoint.memory import MemorySaver

    from talos.graph import build_app

    compiled = build_app()
    assert isinstance(compiled.checkpointer, MemorySaver)
    serde = compiled.checkpointer.serde
    assert serde.loads_typed(serde.dumps_typed(2**100)) == 2**100


def test_build_app_uses_the_given_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    from talos.graph import build_app

    saver = MemorySaver()
    assert build_app(saver).checkpointer is saver


def test_module_app_keeps_the_module_checkpointer():
    from talos.graph import checkpointer

    assert app.checkpointer is checkpointer
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_graph_flow.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_app'`.

- [ ] **Step 3: Implement `build_app`**

In `talos/graph.py`, replace

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
```

with

```python
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
```

Replace the comment lines

```python
# MemorySaver is in-process only. Swap to SqliteSaver / PostgresSaver later
# for cross-process persistence (Phase 9 may want this for HITL resume).
#
```

with

```python
# MemorySaver is in-process only. The web app passes an AsyncPostgresSaver
# (talos.persistence.checkpoint.open_postgres_saver) to build_app() so
# paused runs survive restarts.
#
```

Replace the last two lines

```python
checkpointer = make_checkpointer()
app = build_graph().compile(checkpointer=checkpointer)
```

with

```python
def build_app(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the graph. None → the default in-memory saver (CLI, tests).

    Args:
        checkpointer: Any LangGraph saver, e.g. the web app's AsyncPostgresSaver.

    Returns:
        The compiled Talos graph.
    """
    return build_graph().compile(
        checkpointer=checkpointer if checkpointer is not None else make_checkpointer()
    )


checkpointer = make_checkpointer()
app = build_app(checkpointer)  # unchanged behaviour for `talos.main` and every existing test
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_graph_flow.py -v && uv run pytest -q`
Expected: 6 passed; full suite 224 passed, 7 skipped.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add talos/graph.py tests/test_graph_flow.py
git commit -m "$(cat <<'EOF'
[Feat]: Add build_app(checkpointer) so the web app can pass a Postgres saver

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Dependencies, models and the database module

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `talos/persistence/__init__.py`, `talos/persistence/models.py`, `talos/persistence/db.py`
- Test: `tests/test_persistence_models.py` (create)

**Interfaces:**
- Consumes: `settings.DATABASE_URL` (Task 1).
- Produces:
  - `talos.persistence.models`: `Base` (with `NAMING_CONVENTION`), models `Session`, `Run`, `Message`, `RunEvent`, `AppSetting`; constants `LANGGRAPH_TABLES: frozenset[str]`, `RUN_STATUSES: tuple[str, ...]`, `ACTIVE_RUN_STATUSES`, `MESSAGE_ROLES`; `RunEvent.envelope() -> dict` (overview §4.1 shape); `format_ts(ts: datetime) -> str` (`2026-09-30T14:23:55.120Z`); `include_object(obj, name, type_, reflected, compare_to) -> bool` (Alembic filter).
  - `talos.persistence.db`: `sqlalchemy_url(url: str) -> str`, `libpq_url(url: str) -> str`, `make_engine(url: str | None = None) -> AsyncEngine`, `init_db(url: str | None = None) -> async_sessionmaker[AsyncSession]`, `session_factory() -> async_sessionmaker[AsyncSession]`, `dispose_db() -> None` (async), `session_scope(factory=None)` (async context manager; commit on success, rollback on error), `get_db()` (async generator, FastAPI dependency). Sessions use `expire_on_commit=False`.

- [ ] **Step 1: Add the dependencies**

Run:

```bash
uv add 'sqlalchemy[asyncio]>=2.0' 'alembic>=1.13' 'psycopg[binary,pool]>=3.2' 'langgraph-checkpoint-postgres>=2.0'
uv sync --extra dev
```

Expected: `pyproject.toml` `dependencies` gains the four lines; `uv.lock` adds alembic, mako, psycopg, psycopg-binary, psycopg-pool, langgraph-checkpoint-postgres, greenlet (and bumps `langgraph-checkpoint` 4.0.3 → 4.2.x). Then `uv run pytest -q` is still 224 passed, 7 skipped.

Verify the saver API you're about to use:

```bash
uv run python -c "import inspect; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as S; print(inspect.signature(S.__init__))"
```

Expected: `(self, conn: '_ainternal.Conn', pipe: 'AsyncPipeline | None' = None, serde: 'SerializerProtocol | None' = None) -> 'None'`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_persistence_models.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_persistence_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'talos.persistence'`.

- [ ] **Step 4: Create the package, models and db module**

Create `talos/persistence/__init__.py`:

```python
"""Postgres persistence for the web app: models, repo, migrations, checkpointer.

The CLI never imports this package; it keeps the in-memory checkpointer.
"""
```

Create `talos/persistence/models.py`:

```python
"""SQLAlchemy models for the web app's history (spec 01 §5).

Postgres holds history only: sessions, messages, runs, run events and app
settings. Forged tools stay on disk in the vault. LangGraph's checkpoint
tables live in the same database but are created by `saver.setup()`, not
by these models or by Alembic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

# Tables owned by LangGraph's AsyncPostgresSaver.setup(). Alembic ignores them.
LANGGRAPH_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)

RUN_STATUSES = ("running", "waiting", "done", "failed", "stopped", "declined")
ACTIVE_RUN_STATUSES = ("running", "waiting")
MESSAGE_ROLES = ("user", "assistant")


class Base(DeclarativeBase):
    """Declarative base carrying the constraint naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> Any:
    return text("now()")


class Session(Base):
    """A chat session. One LangGraph thread per session."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="session", order_by="Run.n", passive_deletes=True
    )


class Run(Base):
    """One graph run: a user message and everything it caused."""

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("session_id", "n", name="uq_runs_session_id_n"),
        CheckConstraint(
            "status in ('running', 'waiting', 'done', 'failed', 'stopped', 'declined')",
            name="status",
        ),
        Index(
            "ix_runs_active",
            "status",
            postgresql_where=text("status in ('running', 'waiting')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    translator_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pending_interrupt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_gold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    forged: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    used: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[Session] = relationship(back_populates="runs")


class Message(Base):
    """A chat bubble. User text is stored escaped; assistant html is `answer.done.html`."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint("role in ('user', 'assistant')", name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    chips: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # clock_timestamp(), not now(): two messages written in one transaction
    # must still sort in the order they were added.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class RunEvent(Base):
    """One contract event (overview §4.1). `seq` is 1, 2, 3… per run, no gaps."""

    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )

    def envelope(self) -> dict[str, Any]:
        """The wire shape from overview §4.1: `{run_id, seq, ts, type, data}`."""
        return {
            "run_id": str(self.run_id),
            "seq": self.seq,
            "ts": format_ts(self.ts),
            "type": self.type,
            "data": self.data,
        }


class AppSetting(Base):
    """A key/value app setting. v1 has one key: `ask_before_exec`."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_now()
    )


def format_ts(ts: datetime) -> str:
    """ISO 8601 UTC with milliseconds, e.g. `2026-09-30T14:23:55.120Z`."""
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic filter: never touch LangGraph's checkpoint tables."""
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    table = getattr(obj, "table", None)
    return not (table is not None and table.name in LANGGRAPH_TABLES)
```

Create `talos/persistence/db.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_persistence_models.py -v && uv run pytest -q`
Expected: 15 passed; full suite 239 passed, 7 skipped.

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff format talos tests && uv run ruff check .
git add pyproject.toml uv.lock talos/persistence/__init__.py talos/persistence/models.py talos/persistence/db.py tests/test_persistence_models.py
git commit -m "$(cat <<'EOF'
[Feat]: Add Postgres dependencies, persistence models and the async DB module

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Alembic migrations and the integration-test harness

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py`, `talos/persistence/migrations.py`
- Modify: `pyproject.toml` (pytest `markers`, ruff isort), `tests/conftest.py`
- Create: `tests/integration/__init__.py` (empty), `tests/integration/conftest.py`, `tests/integration/test_migrations.py`
- Test: `tests/test_migrations_offline.py`, `tests/test_integration_gate.py` (create)

**Interfaces:**
- Consumes: `models.Base`, `models.include_object`, `models.LANGGRAPH_TABLES`, `db.sqlalchemy_url`, `db.make_engine` (Task 6).
- Produces:
  - `talos.persistence.migrations`: `ALEMBIC_INI`, `ALEMBIC_DIR`, `alembic_config(database_url: str | None = None) -> alembic.config.Config`, `upgrade_head(database_url: str | None = None) -> None`, `downgrade_base(database_url: str | None = None) -> None`. Sync; from async code call `await asyncio.to_thread(upgrade_head)` (env.py uses `asyncio.run`).
  - Alembic revision `0001_initial` (single head).
  - `tests/conftest.py`: `integration_skip_reason(explicit_url: str, markexpr: str) -> str | None`, fixture `database_url` (session scope, str).
  - `tests/integration/conftest.py`: fixtures `migrated_url` (session scope, sync: downgrade base + upgrade head once) and `factory` (async, per test: empty tables incl. checkpoint tables, yields `async_sessionmaker`).

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_integration_gate.py`:

```python
"""The integration gate: a plain `uv run pytest` never touches a database."""

from __future__ import annotations

import pytest

from tests.conftest import integration_skip_reason

URL = "postgresql+psycopg://talos:talos@localhost:55432/talos"


@pytest.mark.parametrize(
    ("url", "markexpr", "runs"),
    [
        ("", "", False),
        ("", "integration", False),
        (URL, "", False),
        (URL, "not integration", False),
        (URL, "not  integration", False),
        (URL, "integration", True),
        (URL, "integration and not slow", True),
    ],
)
def test_integration_skip_reason(url, markexpr, runs):
    assert (integration_skip_reason(url, markexpr) is None) is runs
```

Create `tests/test_migrations_offline.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_integration_gate.py tests/test_migrations_offline.py -v`
Expected: FAIL with `ImportError: cannot import name 'integration_skip_reason'` and `ModuleNotFoundError: No module named 'talos.persistence.migrations'`.

- [ ] **Step 3: Write the Alembic files**

Create `alembic.ini`:

```ini
# Alembic config for the web app's database (sessions, runs, run events).
# The URL comes from DATABASE_URL, not from this file.
# LangGraph's checkpoint tables are created by AsyncPostgresSaver.setup()
# and are ignored here (see talos.persistence.models.include_object).

[alembic]
script_location = %(here)s/alembic
prepend_sys_path = .
path_separator = os
file_template = %%(rev)s_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Create `alembic/env.py`:

```python
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
```

Create `alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `alembic/versions/0001_initial.py` (this is Alembic's autogenerate output against the Task 6 models, tidied; the integration test in Step 9 proves models and migration agree):

```python
"""Initial schema: sessions, runs, messages, run_events, app_settings.

LangGraph's checkpoint tables are not here: AsyncPostgresSaver.setup()
creates and migrates them.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-30 21:10:38.414978
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("number", name=op.f("uq_sessions_number")),
        sa.UniqueConstraint("thread_id", name=op.f("uq_sessions_thread_id")),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("translator_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pending_interrupt", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_gold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "forged", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "used", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("failed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('running', 'waiting', 'done', 'failed', 'stopped', 'declined')",
            name=op.f("ck_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_runs_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("session_id", "n", name="uq_runs_session_id_n"),
    )
    op.create_index(
        "ix_runs_active",
        "runs",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status in ('running', 'waiting')"),
    )
    op.create_index(op.f("ix_runs_session_id"), "runs", ["session_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "chips",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("role in ('user', 'assistant')", name=op.f("ck_messages_role")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_messages_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_messages_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(op.f("ix_messages_session_id"), "messages", ["session_id"], unique=False)
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_index(op.f("ix_messages_session_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_runs_session_id"), table_name="runs")
    op.drop_index(
        "ix_runs_active",
        table_name="runs",
        postgresql_where=sa.text("status in ('running', 'waiting')"),
    )
    op.drop_table("runs")
    op.drop_table("sessions")
    op.drop_table("app_settings")
```

Create `talos/persistence/migrations.py`:

```python
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
```

- [ ] **Step 4: Register the marker, fix isort for the `alembic/` folder, add the gate**

In `pyproject.toml`, append to `[tool.pytest.ini_options]` (after the asyncio lines from Task 2):

```toml
markers = [
    "integration: needs a real Postgres; run with `-m integration` and DATABASE_URL set",
]
```

and insert before `[tool.ruff.lint.per-file-ignores]`:

```toml
[tool.ruff.lint.isort]
# The repo-root alembic/ folder holds migrations, not the alembic package.
known-third-party = ["alembic"]

```

Replace `tests/conftest.py` with:

```python
"""Test-wide setup. Runs before any test imports.

Disables LangSmith tracing during tests so we don't spam the LangSmith
quota with mock-LLM traces (which are noisy and useless). Live tests
that need tracing can re-enable it explicitly.

Integration tests (`@pytest.mark.integration`) wipe and migrate a real
Postgres. They run only when BOTH hold:
- DATABASE_URL is exported in the shell (a value from .env is ignored:
  it is read here, before talos.config.settings loads .env), and
- the run selects them with `-m integration`.
So a plain `uv run pytest` can never touch a database.
"""

from __future__ import annotations

import os

import pytest

os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_TRACING_V2", None)

# Snapshot before any talos import can load .env into os.environ.
_EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def integration_skip_reason(explicit_url: str, markexpr: str) -> str | None:
    """Why integration tests must be skipped in this run, or None to run them.

    Args:
        explicit_url: DATABASE_URL as exported in the shell (not from .env).
        markexpr: The `-m` expression pytest was given ("" if none).
    """
    if not explicit_url:
        return "needs DATABASE_URL exported (a disposable Postgres); see README Tests"
    expr = markexpr.replace(" ", "")
    if "integration" not in expr or "notintegration" in expr:
        return "integration test: run with -m integration"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests unless explicitly selected with a database."""
    reason = integration_skip_reason(_EXPLICIT_DATABASE_URL, config.option.markexpr or "")
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database_url() -> str:
    """The explicitly exported DATABASE_URL (integration tests only)."""
    return _EXPLICIT_DATABASE_URL
```

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `uv run pytest tests/test_integration_gate.py tests/test_migrations_offline.py -v && uv run ruff check .`
Expected: 10 passed; `All checks passed!`

- [ ] **Step 6: Write the integration harness and migration tests**

Create `tests/integration/__init__.py` as an empty file.

Create `tests/integration/conftest.py`:

```python
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
```

Create `tests/integration/test_migrations.py`. (Task 9 swaps the last test for one that uses the real LangGraph saver; here it proves the same thing with a table Alembic doesn't own.)

```python
"""Alembic round-trip and model/migration agreement (spec 01 §8)."""

from __future__ import annotations

import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from talos.persistence.db import make_engine
from talos.persistence.migrations import downgrade_base, upgrade_head
from talos.persistence.models import Base, include_object

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


async def test_downgrade_leaves_other_tables_alone(migrated_url):
    engine = make_engine(migrated_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS not_ours (v int)"))
    try:
        await asyncio.to_thread(downgrade_base, migrated_url)
        assert "not_ours" in await _tables(migrated_url)
    finally:
        await asyncio.to_thread(upgrade_head, migrated_url)
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS not_ours"))
        await engine.dispose()
```

- [ ] **Step 7: Start the test Postgres**

Run (once; reuse the container for later tasks):

```bash
docker run -d --name talos-pg-test -e POSTGRES_USER=talos -e POSTGRES_PASSWORD=talos -e POSTGRES_DB=talos -p 55432:5432 postgres:16-alpine
until docker exec talos-pg-test pg_isready -U talos -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done; echo ready
```

If the container already exists but is stopped: `docker start talos-pg-test`.

- [ ] **Step 8: Check the migration with the real CLI**

Run:

```bash
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run alembic current
```

Expected: `Running upgrade  -> 0001_initial`, then `0001_initial (head)`.

- [ ] **Step 9: Run the integration tests, then the default suite**

Run:

```bash
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration -v
uv run pytest -q
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -q
```

Expected: 3 passed (integration); default suite 249 passed, 10 skipped; the third command gives the same counts as the second (exported URL without `-m integration` still skips them).

- [ ] **Step 10: Lint, format, commit**

```bash
uv run ruff format . && uv run ruff check .
git add alembic.ini alembic talos/persistence/migrations.py pyproject.toml tests/conftest.py tests/integration tests/test_integration_gate.py tests/test_migrations_offline.py
git commit -m "$(cat <<'EOF'
[Feat]: Add Alembic migrations (0001_initial) and the Postgres integration test harness

Integration tests run only with DATABASE_URL exported and -m integration,
so a plain `uv run pytest` never touches a database.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Repository functions

**Files:**
- Create: `talos/persistence/repo.py`
- Test: `tests/test_repo_unit.py` (create), `tests/integration/test_repo.py` (create)

**Interfaces:**
- Consumes: models (Task 6), `db.session_scope(factory)` (Task 6), fixtures `factory` (Task 7).
- Produces (every function takes `db: AsyncSession` first and never commits):
  - `create_session(db) -> Session` (`number` = max+1 under an advisory transaction lock; `name` = `f"Session {number}"`; `thread_id` = `f"session-{id}"`)
  - `get_session(db, session_id: UUID) -> Session | None`; `rename_session(db, session_id, name: str) -> Session | None` (also bumps `updated_at`)
  - `list_sessions(db) -> list[SessionSummary]` (newest first by `created_at`, then `number`)
  - `summarise_session(s: Session) -> SessionSummary` (needs `s.runs` loaded); `run_mark(run: Run) -> "forged" | "reused" | "failed" | None`
  - `create_run(db, session_id, query: str) -> Run` (`n` = max+1 with the session row locked; status `running`; bumps session `updated_at`; `LookupError` if no session)
  - `get_run(db, run_id) -> Run | None`; `list_runs(db, session_id) -> list[Run]` (by `n`); `active_runs(db) -> list[Run]` (status `running`/`waiting`)
  - `set_run_status(db, run_id, status: str, **fields) -> Run` (fields: `translator_state, pending_interrupt, summary, summary_gold, forged, used, failed, error, finished_at`; terminal status stamps `finished_at`; `ValueError` on unknown status/field; `LookupError` on missing run)
  - `append_event(db, run_id, type: str, data: dict) -> RunEvent` (`seq` = max+1 with the run row locked `FOR UPDATE`; `LookupError` on missing run)
  - `events_after(db, run_id, seq: int = 0) -> list[RunEvent]`
  - `add_message(db, session_id, role, html, note=None, chips=(), run_id=None) -> Message`; `list_messages(db, session_id) -> list[Message]`
  - `get_setting(db, key, default=None) -> Any`; `set_setting(db, key, value) -> None` (upsert)
  - Dataclasses `SessionSummary(id: UUID, name: str, created_at: datetime, run_count: int, forged: list[str], used: list[str], runs: list[RunMark])`, `RunMark(n: int, query: str, mark: RunMarkKind | None)`; constant `TERMINAL_STATUSES`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_repo_unit.py`:

```python
"""Repo helpers that need no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from talos.persistence.models import Run, Session
from talos.persistence.repo import run_mark, set_run_status, summarise_session


def _run(n: int, **kw) -> Run:
    base = {"status": "done", "forged": [], "used": [], "failed": False}
    base.update(kw)
    return Run(n=n, query=f"q{n}", **base)


@pytest.mark.parametrize(
    ("kw", "mark"),
    [
        ({"forged": ["caesar_cipher"]}, "forged"),
        ({"used": ["caesar_cipher"]}, "reused"),
        ({"used": ["caesar_cipher"], "failed": True}, "failed"),
        ({"status": "failed"}, "failed"),
        ({}, None),
        ({"status": "declined"}, None),
    ],
)
def test_run_mark(kw, mark):
    assert run_mark(_run(1, **kw)) == mark


def test_summarise_session_distinct_tools_and_first_three_runs():
    s = Session(id=uuid.uuid4(), name="Caesar cipher", number=1, thread_id="session-x")
    s.created_at = datetime(2026, 9, 30, tzinfo=UTC)
    s.runs = [
        _run(4, used=["weather"]),
        _run(1, forged=["caesar_cipher"]),
        _run(2, used=["caesar_cipher"]),
        _run(3, used=["caesar_cipher"], failed=True),
    ]

    summary = summarise_session(s)

    assert summary.run_count == 4
    assert summary.forged == ["caesar_cipher"]
    assert summary.used == ["weather"]  # caesar_cipher was forged here, so not "used"
    assert [(r.n, r.mark) for r in summary.runs] == [(1, "forged"), (2, "reused"), (3, "failed")]


async def test_set_run_status_rejects_unknown_status_and_fields():
    with pytest.raises(ValueError, match="status"):
        await set_run_status(None, uuid.uuid4(), "paused")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query"):
        await set_run_status(None, uuid.uuid4(), "done", query="x")  # type: ignore[arg-type]
```

Create `tests/integration/test_repo.py`:

```python
"""Repository functions against a real Postgres (spec 01 §6, §8)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.models import Message, Run, RunEvent, Session

pytestmark = pytest.mark.integration


async def _new_session(factory) -> Session:
    async with session_scope(factory) as db:
        return await repo.create_session(db)


async def _new_run(factory, session_id, query: str = "caesar") -> Run:
    async with session_scope(factory) as db:
        return await repo.create_run(db, session_id, query)


# ---- sessions -------------------------------------------------------------------


async def test_create_session_numbers_and_threads(factory):
    first = await _new_session(factory)
    second = await _new_session(factory)

    assert (first.number, first.name) == (1, "Session 1")
    assert (second.number, second.name) == (2, "Session 2")
    assert first.thread_id == f"session-{first.id}"
    assert first.created_at is not None and first.updated_at is not None


async def test_concurrent_create_session_gets_unique_numbers(factory):
    sessions = await asyncio.gather(*(_new_session(factory) for _ in range(8)))
    assert sorted(s.number for s in sessions) == list(range(1, 9))


async def test_get_and_rename_session(factory):
    s = await _new_session(factory)
    async with session_scope(factory) as db:
        renamed = await repo.rename_session(db, s.id, "Caesar cipher")
        assert renamed is not None and renamed.name == "Caesar cipher"
        assert renamed.updated_at >= s.updated_at
    async with session_scope(factory) as db:
        assert (await repo.get_session(db, s.id)).name == "Caesar cipher"
        assert await repo.get_session(db, uuid.uuid4()) is None
        assert await repo.rename_session(db, uuid.uuid4(), "x") is None


# ---- runs -------------------------------------------------------------------------


async def test_create_run_allocates_n_per_session_and_bumps_updated_at(factory):
    a = await _new_session(factory)
    b = await _new_session(factory)

    r1 = await _new_run(factory, a.id)
    r2 = await _new_run(factory, a.id)
    rb = await _new_run(factory, b.id)

    assert (r1.n, r2.n, rb.n) == (1, 2, 1)
    assert r1.status == "running"
    assert (r1.forged, r1.used, r1.failed, r1.summary_gold) == ([], [], False, False)
    async with session_scope(factory) as db:
        assert (await repo.get_session(db, a.id)).updated_at > a.updated_at
        assert [r.n for r in await repo.list_runs(db, a.id)] == [1, 2]


async def test_concurrent_create_run_has_no_duplicate_n(factory):
    s = await _new_session(factory)
    runs = await asyncio.gather(*(_new_run(factory, s.id) for _ in range(10)))
    assert sorted(r.n for r in runs) == list(range(1, 11))


async def test_create_run_for_missing_session_raises(factory):
    with pytest.raises(LookupError):
        await _new_run(factory, uuid.uuid4())


async def test_set_run_status_fields_and_finished_at(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    interrupt = {"type": "confirm_exec", "args": [], "kwargs": {"code": "print(2**100)"}}

    async with session_scope(factory) as db:
        waiting = await repo.set_run_status(
            db, run.id, "waiting", pending_interrupt=interrupt, translator_state={"seq": 7}
        )
        assert waiting.finished_at is None
    async with session_scope(factory) as db:
        done = await repo.set_run_status(
            db,
            run.id,
            "done",
            pending_interrupt=None,
            summary="1 tool forged, 2 attempts",
            summary_gold=True,
            forged=("caesar_cipher",),
            used=["caesar_cipher"],
        )
    assert done.finished_at is not None
    async with session_scope(factory) as db:
        got = await repo.get_run(db, run.id)
    assert got.status == "done"
    assert got.pending_interrupt is None
    assert got.translator_state == {"seq": 7}
    assert got.forged == ["caesar_cipher"] and got.used == ["caesar_cipher"]
    assert got.summary_gold is True


async def test_active_runs(factory):
    s = await _new_session(factory)
    running = await _new_run(factory, s.id)
    waiting = await _new_run(factory, s.id)
    done = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        await repo.set_run_status(db, waiting.id, "waiting")
        await repo.set_run_status(db, done.id, "done")
    async with session_scope(factory) as db:
        assert {r.id for r in await repo.active_runs(db)} == {running.id, waiting.id}


# ---- events -------------------------------------------------------------------------


async def test_append_event_and_events_after(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        e1 = await repo.append_event(db, run.id, "run.started", {"n": 1})
        e2 = await repo.append_event(db, run.id, "log.cmd", {"text": "talos › hi"})
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.envelope()["ts"].endswith("Z")

    async with session_scope(factory) as db:
        after = await repo.events_after(db, run.id, 1)
        everything = await repo.events_after(db, run.id)
    assert [(e.seq, e.type, e.data) for e in after] == [(2, "log.cmd", {"text": "talos › hi"})]
    assert [e.seq for e in everything] == [1, 2]


async def test_twenty_concurrent_appends_have_no_gaps_or_duplicates(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)

    async def append(i: int) -> int:
        async with session_scope(factory) as db:
            return (await repo.append_event(db, run.id, "log.line", {"i": i})).seq

    seqs = await asyncio.gather(*(append(i) for i in range(20)))

    assert sorted(seqs) == list(range(1, 21))
    async with session_scope(factory) as db:
        stored = [e.seq for e in await repo.events_after(db, run.id)]
    assert stored == list(range(1, 21))


async def test_append_event_to_missing_run_raises(factory):
    with pytest.raises(LookupError):
        async with session_scope(factory) as db:
            await repo.append_event(db, uuid.uuid4(), "run.started", {})


async def test_failed_transaction_leaves_no_event(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    with pytest.raises(RuntimeError):
        async with session_scope(factory) as db:
            await repo.append_event(db, run.id, "run.started", {})
            raise RuntimeError("boom")
    async with session_scope(factory) as db:
        assert await repo.events_after(db, run.id) == []
        assert (await repo.append_event(db, run.id, "run.started", {})).seq == 1


# ---- messages ---------------------------------------------------------------------------


async def test_messages_keep_insert_order_within_one_transaction(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    chips = [{"kind": "forged", "text": "Forged caesar_cipher"}]
    async with session_scope(factory) as db:
        await repo.add_message(db, s.id, "user", "shift &lt;abc&gt; by 3", run_id=run.id)
        await repo.add_message(db, s.id, "assistant", "Done.", note="n", chips=chips, run_id=run.id)
    async with session_scope(factory) as db:
        msgs = await repo.list_messages(db, s.id)
    assert [(m.role, m.html) for m in msgs] == [
        ("user", "shift &lt;abc&gt; by 3"),
        ("assistant", "Done."),
    ]
    assert msgs[1].chips == chips and msgs[1].note == "n" and msgs[0].chips == []


async def test_add_message_rejects_unknown_role(factory):
    s = await _new_session(factory)
    with pytest.raises(ValueError):
        async with session_scope(factory) as db:
            await repo.add_message(db, s.id, "system", "x")


# ---- settings ---------------------------------------------------------------------------


async def test_settings_default_set_and_overwrite(factory):
    async with session_scope(factory) as db:
        assert await repo.get_setting(db, "ask_before_exec", True) is True
        await repo.set_setting(db, "ask_before_exec", False)
        assert await repo.get_setting(db, "ask_before_exec", True) is False
    async with session_scope(factory) as db:
        await repo.set_setting(db, "ask_before_exec", True)
    async with session_scope(factory) as db:
        assert await repo.get_setting(db, "ask_before_exec") is True


# ---- sessions page ---------------------------------------------------------------------------


async def test_list_sessions_newest_first_with_summary(factory):
    old = await _new_session(factory)
    new = await _new_session(factory)
    r1 = await _new_run(factory, new.id, "encrypt hello")
    r2 = await _new_run(factory, new.id, "decrypt it")
    async with session_scope(factory) as db:
        await repo.set_run_status(db, r1.id, "done", forged=["caesar_cipher"])
        await repo.set_run_status(db, r2.id, "done", used=["caesar_cipher", "vault_list"])

    async with session_scope(factory) as db:
        summaries = await repo.list_sessions(db)

    assert [s.id for s in summaries] == [new.id, old.id]
    top = summaries[0]
    assert top.run_count == 2
    assert top.forged == ["caesar_cipher"]
    assert top.used == ["vault_list"]
    assert [(r.n, r.query, r.mark) for r in top.runs] == [
        (1, "encrypt hello", "forged"),
        (2, "decrypt it", "reused"),
    ]
    assert summaries[1].run_count == 0 and summaries[1].runs == []


async def test_deleting_a_session_cascades(factory):
    s = await _new_session(factory)
    run = await _new_run(factory, s.id)
    async with session_scope(factory) as db:
        await repo.append_event(db, run.id, "run.started", {})
        await repo.add_message(db, s.id, "user", "hi", run_id=run.id)
    async with session_scope(factory) as db:
        await db.execute(delete(Session).where(Session.id == s.id))
    async with session_scope(factory) as db:
        for model in (Run, RunEvent, Message):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_repo_unit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'talos.persistence.repo'`.

- [ ] **Step 3: Implement the repo**

Create `talos/persistence/repo.py`:

```python
"""Repository functions: plain async reads and writes, no business logic.

Every function takes an `AsyncSession` first and never commits. Callers own
the transaction (`session_scope()` or `get_db()` in `talos.persistence.db`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from talos.persistence.models import (
    ACTIVE_RUN_STATUSES,
    MESSAGE_ROLES,
    RUN_STATUSES,
    AppSetting,
    Message,
    Run,
    RunEvent,
    Session,
)

# Any fixed number works; it only has to be the same for every caller.
_SESSION_NUMBER_LOCK = 7_140_001

TERMINAL_STATUSES = frozenset({"done", "failed", "stopped", "declined"})

# Run columns `set_run_status` may write besides `status`.
_RUN_FIELDS = frozenset(
    {
        "translator_state",
        "pending_interrupt",
        "summary",
        "summary_gold",
        "forged",
        "used",
        "failed",
        "error",
        "finished_at",
    }
)

RunMarkKind = Literal["forged", "reused", "failed"]


@dataclass(frozen=True)
class RunMark:
    """One of the first three runs shown on a Sessions page card."""

    n: int
    query: str
    mark: RunMarkKind | None


@dataclass(frozen=True)
class SessionSummary:
    """What the Sessions page needs for one session (spec 01 §6)."""

    id: uuid.UUID
    name: str
    created_at: datetime
    run_count: int
    forged: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    runs: list[RunMark] = field(default_factory=list)


# ---- sessions -------------------------------------------------------------


async def create_session(db: AsyncSession) -> Session:
    """Create `Session {n}` with the next number and its own LangGraph thread."""
    # Serialise numbering across concurrent callers for this transaction.
    await db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _SESSION_NUMBER_LOCK})
    number = (await db.scalar(select(func.coalesce(func.max(Session.number), 0)))) + 1
    session_id = uuid.uuid4()
    row = Session(
        id=session_id,
        name=f"Session {number}",
        number=number,
        thread_id=f"session-{session_id}",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    """The session, or None."""
    return await db.get(Session, session_id)


async def rename_session(db: AsyncSession, session_id: uuid.UUID, name: str) -> Session | None:
    """Set a session's name. Returns None if it doesn't exist."""
    row = await db.get(Session, session_id)
    if row is None:
        return None
    row.name = name
    row.updated_at = func.now()
    await db.flush()
    await db.refresh(row)
    return row


async def list_sessions(db: AsyncSession) -> list[SessionSummary]:
    """Every session, newest first, with its Sessions-page summary."""
    rows = (
        await db.scalars(
            select(Session)
            .options(selectinload(Session.runs))
            .order_by(Session.created_at.desc(), Session.number.desc())
        )
    ).all()
    return [summarise_session(s) for s in rows]


def summarise_session(s: Session) -> SessionSummary:
    """Build a SessionSummary from a session with its runs loaded."""
    runs = sorted(s.runs, key=lambda r: r.n)
    forged = _distinct(name for r in runs for name in r.forged)
    used = [name for name in _distinct(n for r in runs for n in r.used) if name not in forged]
    return SessionSummary(
        id=s.id,
        name=s.name,
        created_at=s.created_at,
        run_count=len(runs),
        forged=forged,
        used=used,
        runs=[RunMark(n=r.n, query=r.query, mark=run_mark(r)) for r in runs[:3]],
    )


def run_mark(run: Run) -> RunMarkKind | None:
    """The mark a run gets on a Sessions card.

    A failure wins (the demo shows the red mark even if a tool was reused),
    then a forge, then a reuse.
    """
    if run.failed or run.status == "failed":
        return "failed"
    if run.forged:
        return "forged"
    if run.used:
        return "reused"
    return None


def _distinct(names: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)


# ---- runs -----------------------------------------------------------------


async def create_run(db: AsyncSession, session_id: uuid.UUID, query: str) -> Run:
    """Start a run with the session's next `n` and bump the session's `updated_at`.

    Raises:
        LookupError: The session doesn't exist.
    """
    locked = await db.scalar(select(Session.id).where(Session.id == session_id).with_for_update())
    if locked is None:
        raise LookupError(f"session {session_id} not found")
    n = (
        await db.scalar(
            select(func.coalesce(func.max(Run.n), 0)).where(Run.session_id == session_id)
        )
    ) + 1
    run = Run(session_id=session_id, n=n, query=query, status="running")
    db.add(run)
    await db.execute(update(Session).where(Session.id == session_id).values(updated_at=func.now()))
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: uuid.UUID) -> Run | None:
    """The run, or None."""
    return await db.get(Run, run_id)


async def list_runs(db: AsyncSession, session_id: uuid.UUID) -> list[Run]:
    """A session's runs in order (n ascending)."""
    return list(
        (await db.scalars(select(Run).where(Run.session_id == session_id).order_by(Run.n))).all()
    )


async def set_run_status(db: AsyncSession, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
    """Set a run's status and any of its result columns.

    A terminal status (done, failed, stopped, declined) also stamps
    `finished_at` unless the caller passed one.

    Args:
        db: The session.
        run_id: The run.
        status: One of `RUN_STATUSES`.
        **fields: Any of translator_state, pending_interrupt, summary,
            summary_gold, forged, used, failed, error, finished_at.

    Raises:
        ValueError: Unknown status or field.
        LookupError: The run doesn't exist.
    """
    if status not in RUN_STATUSES:
        raise ValueError(f"unknown run status {status!r}")
    unknown = set(fields) - _RUN_FIELDS
    if unknown:
        raise ValueError(f"set_run_status can't set {sorted(unknown)}")
    run = await db.get(Run, run_id, with_for_update=True)
    if run is None:
        raise LookupError(f"run {run_id} not found")
    run.status = status
    for name, value in fields.items():
        setattr(run, name, list(value) if name in {"forged", "used"} else value)
    if status in TERMINAL_STATUSES and "finished_at" not in fields:
        run.finished_at = func.now()
    await db.flush()
    await db.refresh(run)
    return run


async def active_runs(db: AsyncSession) -> list[Run]:
    """Runs that are `running` or `waiting`, anywhere in the app."""
    return list(
        (
            await db.scalars(
                select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES)).order_by(Run.started_at)
            )
        ).all()
    )


# ---- run events -------------------------------------------------------------


async def append_event(
    db: AsyncSession, run_id: uuid.UUID, type: str, data: dict[str, Any]
) -> RunEvent:
    """Append a contract event with the run's next `seq`.

    The run row is locked `FOR UPDATE` first, so concurrent appends to the
    same run queue up and `seq` has no gaps or duplicates. The lock is held
    until the caller's transaction ends, so keep that transaction short.

    Raises:
        LookupError: The run doesn't exist.
    """
    locked = await db.scalar(select(Run.id).where(Run.id == run_id).with_for_update())
    if locked is None:
        raise LookupError(f"run {run_id} not found")
    seq = (
        await db.scalar(
            select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run_id)
        )
    ) + 1
    event = RunEvent(run_id=run_id, seq=seq, type=type, data=data)
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def events_after(db: AsyncSession, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
    """A run's events with `seq > seq`, in order."""
    return list(
        (
            await db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > seq)
                .order_by(RunEvent.seq)
            )
        ).all()
    )


# ---- messages -----------------------------------------------------------------


async def add_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    html: str,
    note: str | None = None,
    chips: Sequence[dict[str, Any]] = (),
    run_id: uuid.UUID | None = None,
) -> Message:
    """Add a chat message. The caller escapes user text before passing it as `html`.

    Raises:
        ValueError: `role` isn't "user" or "assistant".
    """
    if role not in MESSAGE_ROLES:
        raise ValueError(f"unknown message role {role!r}")
    message = Message(
        session_id=session_id,
        run_id=run_id,
        role=role,
        html=html,
        note=note,
        chips=[dict(c) for c in chips],
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def list_messages(db: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    """A session's messages, oldest first."""
    return list(
        (
            await db.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
    )


# ---- app settings ---------------------------------------------------------------


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    """A setting's JSON value, or `default` when it was never set."""
    row = await db.get(AppSetting, key, populate_existing=True)
    return default if row is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Insert or replace a setting's JSON value."""
    stmt = pg_insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await db.execute(stmt)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_repo_unit.py -v
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration -v
uv run pytest -q
```

Expected: 8 passed (unit); 20 passed (integration: 3 migrations + 17 repo); default suite 257 passed, 27 skipped.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format . && uv run ruff check .
git add talos/persistence/repo.py tests/test_repo_unit.py tests/integration/test_repo.py
git commit -m "$(cat <<'EOF'
[Feat]: Add persistence repo functions with gap-free event seq allocation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Postgres checkpointer and startup recovery

**Files:**
- Create: `talos/persistence/checkpoint.py`, `talos/persistence/recovery.py`
- Modify: `tests/integration/test_migrations.py` (use the real saver in the last test)
- Test: `tests/test_checkpoint_unit.py` (create), `tests/integration/test_checkpoint.py`, `tests/integration/test_recovery.py` (create)

**Interfaces:**
- Consumes: `db.libpq_url` (Task 6), `repo.set_run_status`, `repo.append_event` (Task 8), `graph.build_app` (Task 5), `hitl.hitl_check_node`.
- Produces:
  - `open_postgres_saver(database_url: str | None = None, *, max_size: int = 10) -> AsyncPostgresSaver` (opens an `AsyncConnectionPool` with `autocommit=True, prepare_threshold=0, row_factory=dict_row`, serializer `JsonPlusSerializer(pickle_fallback=True)`, runs `setup()`; `RuntimeError` without a URL).
  - `close_postgres_saver(saver: AsyncPostgresSaver) -> None` (closes the pool, `saver.conn`).
  - `recover_runs(db: AsyncSession) -> list[UUID]`: every `running` run → `failed`, `error = RECOVERY_ERROR`, `summary = RECOVERY_SUMMARY`, then appends `error {message}` and `run.finished {status: "failed", summary, summary_gold: False, forged, used}`. `waiting` runs are untouched. Constants `RECOVERY_ERROR = "The app stopped while this run was going."`, `RECOVERY_SUMMARY = "Failed"`. Stage 2's lifespan calls it inside `session_scope()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_checkpoint_unit.py`:

```python
"""The Postgres saver factory without a database."""

from __future__ import annotations

import pytest

from talos.persistence import checkpoint


async def test_open_postgres_saver_without_url_explains(monkeypatch):
    monkeypatch.setattr(checkpoint.settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await checkpoint.open_postgres_saver()
```

Create `tests/integration/test_checkpoint.py`:

```python
"""Interrupts survive a saver/pool restart (spec 01 §4, §8)."""

from __future__ import annotations

from typing import TypedDict

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from talos.agents import hitl as hitl_mod
from talos.agents.hitl import hitl_check_node
from talos.graph import build_app
from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
from talos.state import TalosState

pytestmark = pytest.mark.integration


class _S(TypedDict, total=False):
    answer: str
    big: int


def _ask(state: _S) -> dict:
    value = interrupt({"type": "confirm_exec", "preview": "print(1)"})
    return {"answer": value, "big": 2**100}


def _fixture_graph(saver):
    g: StateGraph = StateGraph(_S)
    g.add_node("ask", _ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=saver)


async def test_interrupt_survives_a_restart(factory, migrated_url):
    config = {"configurable": {"thread_id": "survive-1"}}

    first = await open_postgres_saver(migrated_url)
    try:
        paused = await _fixture_graph(first).ainvoke({}, config)
        assert paused["__interrupt__"][0].value["preview"] == "print(1)"
    finally:
        await close_postgres_saver(first)

    second = await open_postgres_saver(migrated_url)
    try:
        app = _fixture_graph(second)
        final = await app.ainvoke(Command(resume="approved"), config)
        assert final == {"answer": "approved", "big": 2**100}
        # 2**100 is beyond msgpack: stored through the pickle fallback.
        assert (await app.aget_state(config)).values["big"] == 2**100
    finally:
        await close_postgres_saver(second)


async def test_hitl_interrupts_and_resumes_with_postgres(
    factory, migrated_url, monkeypatch, tmp_path
):
    """tests/test_hitl.py::test_hitl_interrupts_and_resumes, on the Postgres saver."""
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    config = {"configurable": {"thread_id": "hitl-pg"}}

    g: StateGraph = StateGraph(TalosState)
    g.add_node("hitl", hitl_check_node)
    g.add_edge(START, "hitl")
    g.add_edge("hitl", END)

    saver = await open_postgres_saver(migrated_url)
    try:
        app = g.compile(checkpointer=saver)
        initial = {
            "messages": [HumanMessage(content="forge a weather tool")],
            "forged_tool": {"name": "weather", "needs_env_vars": ["FAKE_API_KEY"]},
        }
        state = await app.ainvoke(initial, config)
        payload = state["__interrupt__"][0].value
        assert payload["env_var"] == "FAKE_API_KEY"
        assert payload["tool_name"] == "weather"

        final = await app.ainvoke(Command(resume="user-supplied-key"), config)
        assert "__interrupt__" not in final
        assert "FAKE_API_KEY" in (final.get("available_integrations") or {})
        assert (tmp_path / ".env").read_text() == "FAKE_API_KEY=user-supplied-key\n"
    finally:
        await close_postgres_saver(saver)


async def test_build_app_accepts_the_postgres_saver(factory, migrated_url):
    saver = await open_postgres_saver(migrated_url)
    try:
        assert build_app(saver).checkpointer is saver
    finally:
        await close_postgres_saver(saver)


async def test_close_postgres_saver_closes_the_pool(factory, migrated_url):
    saver = await open_postgres_saver(migrated_url)
    await close_postgres_saver(saver)
    assert saver.conn.closed
```

Create `tests/integration/test_recovery.py`:

```python
"""Startup recovery (spec 01 §7)."""

from __future__ import annotations

import pytest

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.recovery import RECOVERY_ERROR, recover_runs

pytestmark = pytest.mark.integration


async def test_running_runs_fail_and_waiting_runs_stay(factory):
    async with session_scope(factory) as db:
        s = await repo.create_session(db)
        running = await repo.create_run(db, s.id, "q1")
        waiting = await repo.create_run(db, s.id, "q2")
        done = await repo.create_run(db, s.id, "q3")
        await repo.append_event(db, running.id, "run.started", {"n": 1})
        await repo.set_run_status(db, running.id, "running", used=["caesar_cipher"])
        await repo.set_run_status(db, waiting.id, "waiting", pending_interrupt={"type": "x"})
        await repo.set_run_status(db, done.id, "done")

    async with session_scope(factory) as db:
        recovered = await recover_runs(db)

    assert recovered == [running.id]
    async with session_scope(factory) as db:
        failed = await repo.get_run(db, running.id)
        assert failed.status == "failed"
        assert failed.error == RECOVERY_ERROR
        assert failed.finished_at is not None
        events = await repo.events_after(db, running.id)
        assert [(e.seq, e.type) for e in events] == [
            (1, "run.started"),
            (2, "error"),
            (3, "run.finished"),
        ]
        assert events[1].data == {"message": RECOVERY_ERROR}
        assert events[2].data == {
            "status": "failed",
            "summary": "Failed",
            "summary_gold": False,
            "forged": [],
            "used": ["caesar_cipher"],
        }
        still = await repo.get_run(db, waiting.id)
        assert still.status == "waiting" and still.pending_interrupt == {"type": "x"}
        assert (await repo.get_run(db, done.id)).status == "done"


async def test_recovery_is_a_noop_when_nothing_is_running(factory):
    async with session_scope(factory) as db:
        assert await recover_runs(db) == []
```

In `tests/integration/test_migrations.py`, replace the last test (`test_downgrade_leaves_other_tables_alone`) with the real-saver version, and add the import `from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver` plus `LANGGRAPH_TABLES` to the models import (drop the now-unused `text` import from `sqlalchemy`):

```python
async def test_downgrade_leaves_langgraph_tables_alone(migrated_url):
    saver = await open_postgres_saver(migrated_url)
    await close_postgres_saver(saver)

    await asyncio.to_thread(downgrade_base, migrated_url)
    try:
        assert LANGGRAPH_TABLES <= await _tables(migrated_url)
    finally:
        await asyncio.to_thread(upgrade_head, migrated_url)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_checkpoint_unit.py -v`
Expected: FAIL with `ImportError: cannot import name 'checkpoint' from 'talos.persistence'`.

- [ ] **Step 3: Implement the saver factory**

Create `talos/persistence/checkpoint.py`:

```python
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
```

- [ ] **Step 4: Implement recovery**

Create `talos/persistence/recovery.py`:

```python
"""Startup recovery for runs a previous process left behind (spec 01 §7).

A run still `running` at startup belonged to a process that is gone, so it
can never finish: mark it failed and close its event stream. A run that is
`waiting` is paused at an interrupt whose checkpoint is in Postgres, so it
stays `waiting` and can still be resumed.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talos.persistence import repo
from talos.persistence.models import Run

log = logging.getLogger(__name__)

RECOVERY_ERROR = "The app stopped while this run was going."
RECOVERY_SUMMARY = "Failed"


async def recover_runs(db: AsyncSession) -> list[uuid.UUID]:
    """Fail every `running` run and append `error` + `run.finished` to each.

    Args:
        db: A session; the caller commits (e.g. `async with session_scope()`).

    Returns:
        The ids of the runs that were failed, oldest first.
    """
    stale = (
        await db.scalars(
            select(Run).where(Run.status == "running").order_by(Run.started_at).with_for_update()
        )
    ).all()
    for run in stale:
        await repo.set_run_status(db, run.id, "failed", error=RECOVERY_ERROR, summary=RECOVERY_SUMMARY)
        await repo.append_event(db, run.id, "error", {"message": RECOVERY_ERROR})
        await repo.append_event(
            db,
            run.id,
            "run.finished",
            {
                "status": "failed",
                "summary": RECOVERY_SUMMARY,
                "summary_gold": False,
                "forged": list(run.forged),
                "used": list(run.used),
            },
        )
    if stale:
        log.warning("marked %d interrupted run(s) as failed", len(stale))
    return [run.id for run in stale]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_checkpoint_unit.py -v
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration -v
uv run pytest -q
```

Expected: 1 passed (unit); 26 passed (integration); default suite 258 passed, 33 skipped.

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff format . && uv run ruff check .
git add talos/persistence/checkpoint.py talos/persistence/recovery.py tests/test_checkpoint_unit.py tests/integration/test_checkpoint.py tests/integration/test_recovery.py tests/integration/test_migrations.py
git commit -m "$(cat <<'EOF'
[Feat]: Add the Postgres checkpointer and startup recovery for interrupted runs

Paused runs survive a restart; runs left `running` are marked failed.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Docs and full verification

**Files:**
- Modify: `README.md` (Configuration table after the `TALOS_LOG_LEVEL` row; Tests section), `.env.example`, `PROGRESS.md` (new stage section before `## Session log`, and a session-log entry at the end)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only.

- [ ] **Step 1: Update the README configuration table**

In `README.md`, add these rows directly after the `| \`TALOS_LOG_LEVEL\` | no | Default WARNING |` row:

```markdown
| `DATABASE_URL` | web app only | Postgres URL, e.g. `postgresql+psycopg://talos:talos@localhost:5432/talos`. Empty means no database; the CLI never needs one |
| `TALOS_CHECKPOINTER` | no | `memory` (default) or `postgres`. The web app always uses Postgres; the CLI stays in memory and logs a warning if this is `postgres` |
| `TALOS_VAULT_DIR` | no | Vault folder (`manifest.json` + `tools/`). Default `talos/vault` |
| `TALOS_WORKSPACE_DIR` | no | Where relative `file_read`/`file_write` paths land. Default `workspace/` |
| `TALOS_DOTENV_PATH` | no | The `.env` Talos loads and where Human check saves keys. Default `.env` in the repo |
```

- [ ] **Step 2: Update the README Tests section**

Read the current `## Tests` section of `README.md` first, then append this paragraph at the end of that section (before `## Known limits (POC)`):

````markdown
Postgres integration tests (the web app's storage) are marked `integration`. They drop and recreate the tables, so point them at a throwaway database. They run only when `DATABASE_URL` is exported in your shell and you pass `-m integration`; a value in `.env` is ignored, so a plain `uv run pytest` never touches a database.

```bash
docker run -d --name talos-pg-test -e POSTGRES_USER=talos -e POSTGRES_PASSWORD=talos \
  -e POSTGRES_DB=talos -p 55432:5432 postgres:16-alpine
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration
```
````

- [ ] **Step 3: Update `.env.example`**

Append to `.env.example`:

```bash

# Web app storage (not needed for the CLI)
# DATABASE_URL=postgresql+psycopg://talos:talos@localhost:5432/talos
# memory (CLI default) or postgres (the web app always uses postgres)
TALOS_CHECKPOINTER=memory
```

(`DATABASE_URL` is commented out on purpose: an empty value keeps the CLI database-free.)

- [ ] **Step 4: Update `PROGRESS.md`**

Insert this section directly above `## Session log`:

```markdown
## Web app stage 01 — Persistence ✅

Spec: `docs/superpowers/specs/2026-09-30-talos-web-01-persistence-design.md`. Plan: `docs/superpowers/plans/2026-09-30-talos-web-01-persistence.md`.

- [x] Settings from env: `DATABASE_URL`, `TALOS_CHECKPOINTER`, `TALOS_VAULT_DIR`, `TALOS_WORKSPACE_DIR`, `TALOS_DOTENV_PATH`
- [x] `talos/events.py` `emit()`; `forge.code`, `forge.tests`, `forge.smoke`, `call.args`, `call.result`, `call.error`, `vault.saved`, `vault.failure` emitted from the nodes
- [x] Tester per-test `results`; Forger `changed`; `SkillManager.get/remove`
- [x] `build_app(checkpointer)`; module-level `app` unchanged (MemorySaver)
- [x] `talos/persistence/`: models, db, repo, migrations, checkpoint (`AsyncPostgresSaver`), recovery
- [x] Alembic `0001_initial`; LangGraph checkpoint tables ignored
- [x] Integration tests (`-m integration`, real Postgres): migrations round-trip, repo, 20 concurrent appends, interrupt survives a restart, HITL on Postgres, recovery
- Moved to stage 2: the `copy.py` vs reference-demo test (spec 01 §8), since `copy.py` is a stage 2 file.
```

Then append this entry to the end of the `## Session log` list (if Step 5 shows different counts, use the real ones):

```markdown

- **2026-09-30** — Web app stage 01 (persistence) on branch `feat/web-01-persistence`. Postgres storage for sessions, messages, runs, run events and settings (SQLAlchemy 2 async + Alembic `0001_initial`), `AsyncPostgresSaver` with the pickle-fallback serializer, startup recovery, and the core changes stage 2 needs: `emit()` events from forger/tester/smoke/executor/learn, per-test results, `changed`, `SkillManager.remove`, env-driven paths, `build_app(checkpointer)`. The CLI is unchanged and needs no database. Unit 258 passed / 33 skipped (26 of the skips are integration tests); integration 26 passed against `postgres:16-alpine`.
```

- [ ] **Step 5: Run the full verification**

Make sure the test Postgres from Task 7 is running (`docker start talos-pg-test` if needed), then run each command and read its output:

```bash
uv run pytest
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration
uv run ruff check .
uv run ruff format --check .
```

Expected: `uv run pytest` → 258 passed, 33 skipped (160 of the passes are the pre-existing suite); integration → 26 passed; `All checks passed!`; `N files already formatted`.

Also confirm the CLI still starts without a database:

```bash
printf 'exit\n' | uv run talos
```

Expected: prints `Talos AI — type a query or 'exit'.` and exits 0 (no database error).

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example PROGRESS.md
git commit -m "$(cat <<'EOF'
[Docs]: Document stage 01 persistence settings and integration tests

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Stop the test database (optional)**

```bash
docker rm -f talos-pg-test
```

---

## Decisions this plan makes where the specs are silent

These are deliberate and stage 2 relies on them:

- `emit()` chunk shape is `{"type": event_type, "data": {...}}`; `event_type` is positional-only.
- `forge.code.note` is always `null` in stage 1; `file` is `"{tool}.py"` (as in the demo). `call.args.caption` and `vault.saved.sub` are `null`; `vault.saved.tool` is the raw manifest entry (`SkillEntry`). Stage 2's `EventTranslator` fills copy and maps `SkillEntry` → `VaultEntry`.
- `forge.smoke` isn't emitted when the smoke gate skips; `call` is `null` when the tool can't load or its arguments can't be built.
- For `python_exec`/`shell_exec`, `call.args` is emitted once, after approval, with the approved args; a decline emits only `call.error {when: "declined"}`.
- `call.error.when` ∈ `skipped | dispatch | arguments | declined | run`. `suspicious` = the value doesn't fit the parameter's annotation. `call.result.small` = repr ≤ 60 chars on one line; reprs are capped at 200 (args, smoke) and 2000 (result) characters.
- `vault.failure` is emitted only for tools that were in the manifest; `streak` = previous `consecutive_failures + 1`.
- Repo functions take an `AsyncSession` first and never commit; `session_scope()`/`get_db()` own the transaction; sessions use `expire_on_commit=False`.
- The event ORM class is `RunEvent` (spec §6 calls it `Event`). `messages.created_at` defaults to `clock_timestamp()` (spec says `now()`) so two messages in one transaction keep their order.
- Recovery appends `error` then `run.finished` with summary `"Failed"`; it doesn't set `runs.failed` (that column means "a tool raised").
- Sessions-card mark precedence: `failed` > `forged` > `reused`.
- Extra helpers for stage 2: `repo.active_runs`, `SkillManager.get`, `RunEvent.envelope()`, `migrations.upgrade_head/downgrade_base`, `checkpoint.close_postgres_saver`.
- An invalid `TALOS_CHECKPOINTER` raises at import. The CLI never uses Postgres; it warns if asked.
- CI is unchanged in this stage (it runs the default suite, which skips integration tests). Running integration tests in CI is stage 3. `alembic.ini` and `alembic/` live at the repo root and aren't in the wheel, so stage 3's Docker image must copy them.
