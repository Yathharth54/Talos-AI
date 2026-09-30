# Stage 1: persistence (Postgres, Alembic, checkpointer)

Date: 2026-09-30
Status: draft for review
Parent: `2026-09-30-talos-web-app-overview-design.md`

## 1. Goal

Give the web app durable storage for sessions, messages, runs and run events, and let paused graph runs survive restarts. The vault stays on disk. The CLI keeps its in-memory behaviour unless it's told otherwise.

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Database | PostgreSQL 16 | `langgraph-checkpoint-postgres` targets it; JSONB for event payloads |
| Driver | `psycopg` 3 (async, with `psycopg_pool`) | one driver for both SQLAlchemy and the LangGraph saver |
| ORM | SQLAlchemy 2.0, async engine, `postgresql+psycopg://` URL | typed models, works with Alembic |
| Migrations | Alembic, async `env.py` | the owner asked for it |
| Graph checkpoints | `AsyncPostgresSaver` from `langgraph-checkpoint-postgres` | interrupts must survive between HTTP requests and restarts |
| Checkpoint tables | created by `await saver.setup()` at app start, not by Alembic | LangGraph owns and migrates its own schema; Alembic must ignore those tables |
| Vault | unchanged: `manifest.json` + `tools/*.py` | promise on the landing page; tools are meant to be read |
| `.env` writes | unchanged: `hitl._persist_env_var` | keys stay in the file the user already manages |

New dependencies: `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary,pool]>=3.2`, `langgraph-checkpoint-postgres>=2.0`. Dev: `pytest-asyncio` (already present).

## 3. Configuration

Added to `talos/config/settings.py`, all read from the environment:

| Var | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | empty | `postgresql+psycopg://talos:talos@localhost:5432/talos`. Empty means no database |
| `TALOS_CHECKPOINTER` | `memory` | `memory` or `postgres`. The web app forces `postgres` and refuses to start without `DATABASE_URL` |
| `TALOS_VAULT_DIR` | `<repo>/talos/vault` | lets Docker mount the vault elsewhere |
| `TALOS_WORKSPACE_DIR` | `<repo>/workspace` | same, for `file_read`/`file_write` |
| `TALOS_DOTENV_PATH` | `<repo>/.env` | where HITL writes keys |

`VAULT_DIR`, `VAULT_TOOLS_DIR`, `VAULT_MANIFEST_PATH`, `WORKSPACE_DIR` and `hitl.DOTENV_PATH` are derived from these. `.env.example` gains `DATABASE_URL` and `TALOS_CHECKPOINTER`, and the README config table is updated.

## 4. Checkpointer wiring

`talos/graph.py` today compiles one module-level `app` with `MemorySaver`. Change to:

```python
def build_app(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the graph. None → the default in-memory saver (CLI, tests)."""

app = build_app()  # unchanged behaviour for `talos.main` and every existing test
```

- `make_checkpointer()` keeps `JsonPlusSerializer(pickle_fallback=True)` for big ints and sets. The Postgres saver is created with the same serializer: `AsyncPostgresSaver(conn, serde=JsonPlusSerializer(pickle_fallback=True))`.
- The web app builds its own compiled graph at startup: `build_app(await open_postgres_saver())`.
- `talos/persistence/checkpoint.py` provides `open_postgres_saver()`. It opens an `AsyncConnectionPool` with `autocommit=True` and `prepare_threshold=0`, as the saver requires, and calls `setup()` once.
- One LangGraph `thread_id` per session: `sessions.thread_id` (see below). This keeps the planner's conversation history per session, which is how the REPL already works.

## 5. Schema (Alembic revision `0001_initial`)

Naming convention on the metadata: `pk_%(table_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `ix_%(column_0_label)s`, `uq_%(table_name)s_%(column_0_name)s`, `ck_%(table_name)s_%(constraint_name)s`.

### `sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` pk | `gen_random_uuid()` |
| `name` | `text` not null | `Session {n}` until the first run names it (stage 2 §6) |
| `number` | `integer` not null, unique | 1, 2, 3… for the default name |
| `thread_id` | `text` not null, unique | `session-{id}` |
| `created_at` | `timestamptz` not null default `now()` | |
| `updated_at` | `timestamptz` not null default `now()` | bumped on every run |

### `messages`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` pk | |
| `session_id` | `uuid` fk → `sessions.id` on delete cascade, indexed | |
| `run_id` | `uuid` fk → `runs.id` on delete set null, nullable | the run this message started or answered |
| `role` | `text` check in (`user`, `assistant`) | |
| `html` | `text` not null | user text is stored escaped; assistant html is `answer.done.html` (only the tags the overview §4.3 allows) |
| `note` | `text` nullable | `answer.done.note` |
| `chips` | `jsonb` not null default `[]` | `answer.done.chips` |
| `created_at` | `timestamptz` not null default `now()` | |

### `runs`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` pk | |
| `session_id` | `uuid` fk → `sessions.id` on delete cascade, indexed | |
| `n` | `integer` not null | run number within the session; unique with `session_id` |
| `query` | `text` not null | |
| `status` | `text` check in (`running`, `waiting`, `done`, `failed`, `stopped`, `declined`) | |
| `translator_state` | `jsonb` nullable | `EventTranslator` state, so a resumed run continues its strip, attempts and `seq` (stage 2 §6) |
| `pending_interrupt` | `jsonb` nullable | the full interrupt value from LangGraph, including `args`/`kwargs` for `confirm_exec`. Never sent to the browser |
| `summary` | `text` nullable | `run.finished.summary` |
| `summary_gold` | `boolean` not null default false | |
| `forged` | `text[]` not null default `{}` | tool names learned in this run |
| `used` | `text[]` not null default `{}` | vault tools executed in this run |
| `failed` | `boolean` not null default false | any tool error |
| `error` | `text` nullable | unexpected error text |
| `started_at` | `timestamptz` not null default `now()` | |
| `finished_at` | `timestamptz` nullable | |

Index: `(session_id, n)` unique. Partial index `ix_runs_active` on `status` where `status in ('running','waiting')`.

### `run_events`

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity pk | |
| `run_id` | `uuid` fk → `runs.id` on delete cascade | |
| `seq` | `integer` not null | unique with `run_id` |
| `type` | `text` not null | contract event type |
| `data` | `jsonb` not null | contract event data |
| `ts` | `timestamptz` not null default `now()` | |

Index: `(run_id, seq)` unique. That's the only access path (replay after a given seq).

### `app_settings`

| Column | Type | Notes |
|---|---|---|
| `key` | `text` pk | |
| `value` | `jsonb` not null | |
| `updated_at` | `timestamptz` not null default `now()` | |

The only key in v1 is `ask_before_exec` (`true`/`false`). It is read at app start and applied through the override in stage 2 §7.

## 6. Repository layer

`talos/persistence/` (new package):

- `db.py`: `make_engine(url)`, `session_factory`, and `get_db()` (a FastAPI dependency in stage 2).
- `models.py`: the five SQLAlchemy models.
- `repo.py`: plain async functions, no business logic:
  - `create_session() -> Session`, `list_sessions() -> list[SessionSummary]`, `get_session(id)`, `rename_session(id, name)`
  - `create_run(session_id, query) -> Run` (allocates `n`), `set_run_status(id, status, **fields)`, `get_run(id)`, `list_runs(session_id)`
  - `append_event(run_id, type, data) -> Event` (allocates `seq` inside the same transaction with `SELECT max(seq) … FOR UPDATE` on the run row)
  - `events_after(run_id, seq) -> list[Event]`
  - `add_message(session_id, role, html, note=None, chips=(), run_id=None)`, `list_messages(session_id)`
  - `get_setting(key, default)`, `set_setting(key, value)`
- `SessionSummary` carries what the Sessions page needs: `id, name, created_at, run_count, forged (distinct), used (distinct, minus forged), runs: [{n, query, mark: "forged"|"reused"|"failed"|null}]` for the first 3 runs.

## 7. Recovery on start

When the web app starts, it marks runs left `running` as `failed` with `error = "The app stopped while this run was going."` and appends `run.finished`. That process is gone and can't resume.

Runs left `waiting` stay `waiting`. Their checkpoint is in Postgres, so a later resume works. That is success criterion 3 in the overview.

## 8. Tests

- Unit (no Postgres, run in the default suite): the models import, Alembic `env.py` finds all tables, `copy.py` strings are checked against the reference file (overview §4.5), and `emit()` is a no-op outside a stream.
- Integration (`@pytest.mark.integration`, needs `DATABASE_URL`, skipped otherwise):
  - `alembic upgrade head` then `downgrade base` round-trips on an empty database.
  - The repo functions work, including `seq` allocation under 20 concurrent `append_event` calls (no gaps, no duplicates).
  - Interrupt survival: run a small fixture graph that calls `interrupt()` with an `AsyncPostgresSaver`, dispose the saver and pool, open a new one, resume with `Command(resume=…)`, and assert the graph finishes with the resumed value.
  - The existing HITL graph test is repeated with the Postgres saver.
- `pyproject.toml` registers the `integration` marker. `uv run pytest` stays green with no database.

## 9. Also in this stage (core changes the web app needs)

1. `talos/events.py` with `emit()` (overview §4.4) and its calls in forger, tester, smoke, executor and learn. Every call is keyword-only and cheap; there is no behaviour change without a stream.
2. `tester._parse_runner_output` also returns `results: [{name, passed, why}]`. `why` is the last line of the failing test's traceback.
3. `forger_node` computes `changed`: the first 1-based line where attempt N's code differs from attempt N-1's (`difflib`), or `null` on attempt 1.
4. `SkillManager.remove(name) -> bool` as a public method (prune already does this internally). The `.py` file stays on disk.
5. Path settings from §3.

## 10. Acceptance

- `uv run pytest` (no database) passes, with the same count plus the new unit tests.
- With Postgres running: `uv run alembic upgrade head` works and `uv run pytest -m integration` passes.
- The CLI still runs with `MemorySaver` and needs no database.
