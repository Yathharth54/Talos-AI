# Talos Web App Stage 02 (API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local FastAPI app (`talos-web`) that starts graph runs, streams their contract events over SSE, pauses and resumes them for approvals and API keys, serves sessions, vault and settings, and has a fake-graph mode (`TALOS_FAKE_GRAPH=1`) that replays the demo's scripted runs with no model calls.

**Architecture:** A new `talos/web/` package. `EventTranslator` (pure) turns LangGraph `astream` chunks into the overview §4 contract events; a shared `Board` builds those events and keeps the run's UI state, so the fake graph emits exactly what the translator emits for the same run. `RunManager` owns the one-active-run lock, persists each event (stage 1's `append_event` allocates `seq`) before publishing it to SSE subscribers, and drives either `GraphDriver` (real graph on the Postgres checkpointer) or `FakeDriver`. Routes talk to a small `Store` interface with a Postgres implementation (stage 1 repo functions) and an in-memory one, so every route, SSE and runner test runs without a database; the same store contract tests also run on Postgres.

**Tech Stack:** Python 3.11+, FastAPI (0.142 at plan time), Starlette, uvicorn[standard], sse-starlette 3.x, httpx (tests, `ASGITransport`), LangGraph 1.1.x (`astream` with `subgraphs=True`), SQLAlchemy 2.0 async + psycopg 3 (stage 1), pytest + pytest-asyncio (auto mode), ruff.

**Spec:** `docs/superpowers/specs/2026-09-30-talos-web-02-api-design.md` (the authority for this stage). The event contract is normative in `docs/superpowers/specs/2026-09-30-talos-web-app-overview-design.md` §4 (copy rules §4.5). What the frontend needs: `docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md` §5, §6, §8. Stage 1 code this builds on is on `feat/web-01-persistence` (plan: `docs/superpowers/plans/2026-09-30-talos-web-01-persistence.md`). The demo whose strings and flows are copied: `docs/superpowers/specs/reference/workbench-demo/index.html`.

## Global Constraints

- Branch: `feat/web-02-api`, created from `feat/web-01-persistence` (stacked). Task 1 creates it.
- Python `>=3.11`; type hints everywhere; Google-style docstrings on public functions; `logging`, never `print`.
- `uv run ruff check .` and `uv run ruff format --check .` must pass (line length 100, rules `E, F, I, W, UP`).
- New dependencies exactly: `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `sse-starlette>=2.1`; dev: `httpx>=0.27`. Add them with `uv add` so `uv.lock` updates.
- New console script: `talos-web = "talos.web.__main__:main"`, next to `talos`.
- `uv run pytest` (no database, no keys) must pass. Postgres tests are marked `integration` and run only with `DATABASE_URL` exported **and** `-m integration` (the stage 1 gate in `tests/conftest.py`). Local disposable Postgres: the `talos-pg-test` container on port 55432 (`DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos`).
- Server: one uvicorn worker, `127.0.0.1:8000` by default (`TALOS_WEB_HOST`, `TALOS_WEB_PORT`). One worker is required: run state and the vault are per process, and startup recovery fails every `running` run.
- Error body, every error: `{"error": {"code": "...", "message": "..."}}` (a `run_active` error also carries `run_id` and `session_id`). Prefix `/api`.
- Every caption, log line, chip, summary and label comes from `talos/web/copy.py`, word for word from the reference demo. Numbers come from settings: `3` = `TALOS_FORGE_MAX_RETRIES`, `10-second` = `TALOS_SUBPROCESS_TIMEOUT`, `2` = the vault's `_AUTO_PRUNE_THRESHOLD`. Strings the demo never needed live in `copy.NEW_COPY` and are listed in the frontend spec §7 (Task 12).
- `seq` is allocated only by `repo.append_event` (via the store). Nothing else computes or stores a `seq`. `translator_state` holds strip, attempt and tool state only.
- Events are persisted before they are published. Each append is its own short transaction; no DB session is shared with a request or a cancellable run task.
- `Session.runs` and `Run.session` are default lazy relationships: async code must not touch them (lazy loads fail under asyncio). Read runs with `list_runs`; only `repo.list_sessions` (which uses `selectinload`) reads `Session.runs`.
- The Postgres checkpointer is used through the async API only (`astream`, `aget_state`); never `invoke`/`stream` on it.
- API key values from `/resume` are never logged, stored in `run_events`, or returned in any response.
- The CLI (`uv run talos`) keeps working unchanged; it never imports `talos.web` and never sets the ask-before-exec override.
- Commit messages: prefix `[Feat]:`, `[Fix]:`, `[Docs]:` or `[Chore]:`, subject only (plus an optional body). No `Co-Authored-By` trailer and no other attribution.

## Review Focus

1. **The user clicks Approve the instant the dialog appears** (the run row already says `waiting`, but the `interrupt` event is still being written). Expected: `interrupt` still comes before `interrupt.resolved`, `seq` has no gap. Pinned by `test_resume_right_after_the_pause_keeps_interrupt_first` (Task 6).
2. **A run is paused when the app restarts or shuts down.** Expected: it stays `waiting` (shutdown doesn't turn a just-paused run into `stopped`), it blocks new messages app-wide, and the `409 run_active` names its `run_id` and `session_id` so the UI can open it and answer or stop it. Pinned by `test_shutdown_leaves_a_just_paused_run_waiting` (Task 6) and `test_one_run_at_a_time_anywhere` (Task 9).
3. **The model's answer contains HTML** (`<script>`, `&`, `<b>`). Expected: `answer.done.html` is escaped text. Pinned by `test_answer_html_is_escaped` (Task 4).
4. **The Planner returns two or more sub-tasks.** Expected: each sub-task gets `strip.set` with `Sub-task i of n, …`, the second starts with `subtask.started`, and the Planner step stays done after each strip reset. Pinned by `test_multi_subtask_plan_resets_the_strip_per_subtask` (Task 4).
5. **The browser tab closes mid-stream, then reconnects.** Expected: the dead subscriber's queue is dropped, and a reconnect with `Last-Event-ID` continues with no gap and no duplicate. Pinned by `test_a_closed_subscriber_is_forgotten` (Task 6) and `test_sse_resumes_after_a_dropped_connection` (Task 9).

Also covered: one active run under 5 concurrent sends, stop during a run and during a pause, the exception path, a 64 KB body limit, no key echo in 422s, and a real-graph pause surviving an app restart on the Postgres checkpointer.

## Decisions made while planning (verified against the installed libraries)

These were checked by running this plan's code in a scratch copy (FastAPI 0.142.2, Starlette 1.7, sse-starlette 3.5.0, uvicorn 0.54, httpx 0.28.1, LangGraph 1.1.10) with Postgres 16: 566 unit tests and 37 integration tests passed, ruff clean, and the Task 12 acceptance `curl -N` streamed a 72-event Caesar run.

- **Stream modes.** `stream_mode=["updates", "custom", "messages", "tasks"]`, `subgraphs=True`. The spec lists three; `"tasks"` is added because `"updates"` only reports a node when it *finishes*, so without it the Forger step would only light up after its 30-second model call returned. A `tasks` chunk with an `input` key is a node start. Chunk shape (verified): `(namespace_tuple, mode, data)`; namespace `()` for the main graph, `("forge_subgraph:<task id>",)` inside the forge sub-graph; custom data `{"type", "data"}`; a pause is an `updates` chunk `{"__interrupt__": (Interrupt(value=..., id=...),)}`; answer tokens are `messages` chunks `(AIMessageChunk, {"langgraph_node": "orchestrator_out", ...})`, followed by the whole `AIMessage` once.
- **New input after a pause starts a fresh turn** in LangGraph 1.1.10 (`orchestrator_in` runs, the old pending task is dropped). A test pins it (Task 6), so `stop` doesn't need `aupdate_state`.
- **Route tests without Postgres.** A `Store` protocol with `PgStore` (stage 1 repo, one `session_scope` per call) and `MemoryStore` (same rows as transient ORM objects). One contract suite runs on both (Postgres under `-m integration`). Route, SSE and runner tests use `MemoryStore` + the fake graph and need no database.
- **Translator fixtures** are captured from the real compiled graph, driven with the repo's existing LLM-fake pattern (canned `Plan`/`ForgedTool`/`ResolvedArgs`, plus LangChain's `GenericFakeChatModel` so answer tokens really stream). Every node, the tester subprocess, the smoke gate and the vault are real. `uv run python -m tests.web.chunks` regenerates them, and a test fails if a live capture's chunk shapes drift from the stored JSON.
- **The fake graph emits contract events directly** through the same `Board` as the translator, and a test asserts its event-type order equals the translator's for the same flow (forge with retry, reuse, chat, approval, key skip).
- `log.cmd.text` is the raw query; the frontend prints the `talos › ` prefix (demo `logLineHtml`).
- Planner order: `node.started planner` → `plan.ready` → `strip.set` → `node.finished planner` (re-sent after every `strip.set`, because the frontend's `initStrip` resets the steps).
- Stop uses `node.finished` status `stopped` with the label suffix `, stopped` (spec 02 §6), and writes an assistant message with the demo's stop note, `Stopped. Ask again whenever you're ready.`
- A tool that raises finishes the run with status `done`, `failed = true` and summary `Failed, …` (the demo's behaviour). Only an unexpected exception gives status `failed`.
- Empty sessions (frontend spec §5): `POST /api/sessions` reuses the newest empty session, and `GET /api/sessions` lists only sessions with runs.
- Naming follows the demo's `classify()` order (chat first) and regexes, a superset of spec §8's wording.
- Fake mode: the vault is a temp copy of `TALOS_VAULT_DIR` minus `caesar_cipher` and `get_current_temperature` (so the first Caesar run forges, as in the demo). A saved key is only remembered as "set" in memory; the fake never sees its value and never writes `.env`. Vault-list questions fall through to the demo's "not in this demo" flow.
- The 64 KB limit checks `Content-Length` (browsers and curl always send it).
- Redaction wraps the logging record factory, so every logger and handler (uvicorn's, pytest's `caplog`) gets redacted records.
- `RECOVERY_SUMMARY` (stage 1) is checked equal to `copy.SUMMARY_FAILED` by a test rather than imported, so `talos.persistence` never imports `talos.web`.
- `202` responses return `{"ok": true}`.

## File map

| File | Status | Responsibility |
|---|---|---|
| `pyproject.toml`, `uv.lock` | modify | web deps, `httpx` dev dep, `talos-web` script |
| `talos/config/settings.py` | modify | `set_auto_approve_override`, `WEB_HOST`, `WEB_PORT`, `FAKE_GRAPH`, `WEB_DEV` |
| `talos/web/__init__.py` | create | package doc |
| `talos/web/copy.py` | create | every user-facing string, verbatim from the demo |
| `talos/web/naming.py` | create | `classify()`, `session_name()`, `weather_city()` |
| `talos/web/demo_sources.py` | create | the demo's `caesar_cipher` and `get_current_temperature` sources |
| `talos/web/schemas.py` | create | Pydantic models; `vault_entry`, `split_signature`, `pending_payload`, `service_name` |
| `talos/web/board.py` | create | `Board`: UI state + contract event builders, `stop()` |
| `talos/web/translator.py` | create | `EventTranslator`, `STREAM_MODES` |
| `talos/web/store.py` | create | `Store` protocol, `PgStore`, `MemoryStore` |
| `talos/web/runner.py` | create | `RunManager`, `Driver`, `GraphDriver`, `Pause`, `Resume`, run errors |
| `talos/web/fake_graph.py` | create | `FakeDriver`, `make_fake_vault`, the demo's helpers |
| `talos/web/security.py` | create | key redaction in logs |
| `talos/web/deps.py` | create | `Services`, dependencies, error shape and handlers |
| `talos/web/app.py` | create | `create_app`, lifespan, `open_services`, body limit, CORS, static files |
| `talos/web/routes/{__init__,health,sessions,runs,vault,settings}.py` | create | the endpoints |
| `talos/web/__main__.py` | create | `talos-web` / `python -m talos.web` |
| `tests/test_settings.py` | modify | override + web settings tests |
| `tests/web/*` | create | unit tests, stubs, recorded chunk fixtures |
| `tests/integration/test_web_store.py`, `tests/integration/test_web_app.py` | create | Postgres tests |
| `README.md`, `.env.example`, `PROGRESS.md`, frontend spec §7 | modify | docs (Task 12) |

---

### Task 1: Branch, web dependencies, web settings and the ask-before-exec override

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Modify: `talos/config/settings.py` (the `auto_approve_exec` function; a new block before `key_status`)
- Create: `talos/web/__init__.py`
- Test: `tests/test_settings.py` (extend `_VARS`, append tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `settings.set_auto_approve_override(value: bool | None) -> None`; `settings.auto_approve_exec() -> bool` (override wins over `TALOS_AUTO_APPROVE_EXEC`); `settings._auto_approve_override: bool | None`; `settings.WEB_HOST: str` (default `"127.0.0.1"`), `settings.WEB_PORT: int` (default `8000`), `settings.FAKE_GRAPH: bool` (`TALOS_FAKE_GRAPH` in `1/true/yes`), `settings.WEB_DEV: bool` (`TALOS_WEB_DEV`). The `talos.web` package exists.

- [ ] **Step 1: Create the branch**

```bash
git switch feat/web-01-persistence
git switch -c feat/web-02-api
```

- [ ] **Step 2: Add the dependencies**

```bash
uv add 'fastapi>=0.115' 'uvicorn[standard]>=0.30' 'sse-starlette>=2.1'
uv add --optional dev 'httpx>=0.27'
uv sync --extra dev
```

Expected: `pyproject.toml` lists the three under `dependencies` and `httpx>=0.27` under `[project.optional-dependencies] dev`; `uv.lock` changes.

- [ ] **Step 3: Write the failing tests**

In `tests/test_settings.py`, extend `_VARS` so the reload fixture clears the web variables too:

```python
_VARS = (
    "TALOS_VAULT_DIR",
    "TALOS_WORKSPACE_DIR",
    "TALOS_DOTENV_PATH",
    "DATABASE_URL",
    "TALOS_CHECKPOINTER",
    "TALOS_WEB_HOST",
    "TALOS_WEB_PORT",
    "TALOS_FAKE_GRAPH",
    "TALOS_WEB_DEV",
)
```

Append to `tests/test_settings.py`:

```python
def test_web_settings_default_to_a_local_real_server(reload_settings):
    s = reload_settings()
    assert (s.WEB_HOST, s.WEB_PORT, s.FAKE_GRAPH, s.WEB_DEV) == ("127.0.0.1", 8000, False, False)


def test_web_settings_come_from_env(reload_settings):
    s = reload_settings(
        TALOS_WEB_HOST="0.0.0.0", TALOS_WEB_PORT="9001", TALOS_FAKE_GRAPH="1", TALOS_WEB_DEV="true"
    )
    assert (s.WEB_HOST, s.WEB_PORT, s.FAKE_GRAPH, s.WEB_DEV) == ("0.0.0.0", 9001, True, True)


def test_auto_approve_override_wins_over_the_env(monkeypatch):
    monkeypatch.setenv("TALOS_AUTO_APPROVE_EXEC", "true")
    assert settings.auto_approve_exec() is True
    try:
        settings.set_auto_approve_override(False)
        assert settings.auto_approve_exec() is False
        monkeypatch.setenv("TALOS_AUTO_APPROVE_EXEC", "false")
        settings.set_auto_approve_override(True)
        assert settings.auto_approve_exec() is True
    finally:
        settings.set_auto_approve_override(None)
    assert settings.auto_approve_exec() is False  # back to the env var
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: the three new tests FAIL with `AttributeError: module 'talos.config.settings' has no attribute 'WEB_HOST'` / `'set_auto_approve_override'`.

- [ ] **Step 5: Implement the settings**

In `talos/config/settings.py`, replace the whole `auto_approve_exec` function with:

```python
# Set by the web app from its "Ask before running code" setting. None means
# "no override": fall back to TALOS_AUTO_APPROVE_EXEC. The CLI never sets it.
_auto_approve_override: bool | None = None


def set_auto_approve_override(value: bool | None) -> None:
    """Override TALOS_AUTO_APPROVE_EXEC for this process (web app only).

    Args:
        value: True to run code without asking, False to always ask,
            None to go back to the environment variable.
    """
    global _auto_approve_override
    _auto_approve_override = value


def auto_approve_exec() -> bool:
    """Whether python_exec/shell_exec run without asking the user first.

    Off by default: both run model-written code on the host. Read at call
    time (not import time) so unattended runners and tests can flip it.
    The web app's setting (`set_auto_approve_override`) wins over the env var.
    """
    if _auto_approve_override is not None:
        return _auto_approve_override
    return os.environ.get("TALOS_AUTO_APPROVE_EXEC", "false").lower() in {"1", "true", "yes"}
```

Then, directly above `def key_status()`, add:

```python
# Web app (talos-web). One uvicorn worker only: runs and the vault are
# single-process state, and startup recovery fails every `running` run.
WEB_HOST = os.environ.get("TALOS_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_PORT = int(os.environ.get("TALOS_WEB_PORT", "8000"))
FAKE_GRAPH = os.environ.get("TALOS_FAKE_GRAPH", "").strip().lower() in {"1", "true", "yes"}
WEB_DEV = os.environ.get("TALOS_WEB_DEV", "").strip().lower() in {"1", "true", "yes"}
```

Create `talos/web/__init__.py`:

```python
"""Talos web app: FastAPI API, run manager and SSE event stream (stage 2).

The CLI never imports this package.
"""
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_settings.py tests/test_executor.py -v`
Expected: PASS (the executor tests still pass: with no override, behaviour is unchanged).

- [ ] **Step 7: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock talos/config/settings.py talos/web/__init__.py tests/test_settings.py
git commit -m "[Feat]: Add web dependencies, web settings and the ask-before-exec override"
```

---

### Task 2: Copy table and session naming

**Files:**
- Create: `talos/web/copy.py`, `talos/web/naming.py`
- Test: `tests/web/__init__.py`, `tests/web/test_copy.py`, `tests/web/test_naming.py`

**Interfaces:**
- Consumes: `talos.persistence.recovery.RECOVERY_SUMMARY` (stage 1, `"Failed"`).
- Produces:
  - `talos.web.copy`: string constants `CAPTION_*`, `STATUS_*`, `TALOS_*`, `LABEL_*`, `SUMMARY_*`, `CHIP_*`, `ANSWER_*`, `NOTE_*`, `RESULT_*`, `ARGS_CAPTION*`, `DETAIL_TESTS_PASSED`, `NOTE_CHANGED_LINE`, `SAVED_SUB`, `SAVED_SUB_KEY`, `STOP_NOTE`, `KEY_SAVED_BY_HUMAN_CHECK`; log lines `LOG_*` as `(label, text)` tuples; `KEY_DESCRIPTIONS: dict[str, str]`; `NEW_COPY: dict[str, str]`; `new(key: str, **fields) -> str`; `join_words(words: list[str]) -> str`. Templates use `str.format` fields (`{tool}`, `{n}`, `{max}`, `{k}`, `{timeout}`, `{env}`, …).
  - `talos.web.naming`: `QueryKind = Literal["chat", "caesar", "python", "weather", "vaultlist", "unknown"]`; `classify(query: str) -> QueryKind`; `weather_city(query: str) -> str`; `session_name(query: str) -> str` (≤ 80 chars); `MAX_NAME = 80`.
  - `tests/web/test_copy.py`: `REFERENCE: Path`, `reference_text() -> str` (demo source with `\"`/`\'` unescaped), `literal_parts(template) -> list[str]`. Later tests import `REFERENCE` and `reference_text`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/__init__.py` (empty file).

Create `tests/web/test_copy.py`:

```python
"""copy.py strings are the demo's strings, word for word (overview §4.5)."""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from talos.persistence.recovery import RECOVERY_SUMMARY
from talos.web import copy

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/specs/reference/workbench-demo/index.html"
)


def reference_text() -> str:
    """The demo source with JS string escapes undone (\\" → ", \\' → ')."""
    return REFERENCE.read_text(encoding="utf-8").replace('\\"', '"').replace("\\'", "'")


def literal_parts(template: str) -> list[str]:
    """The text between `{field}`s, e.g. "Writing {tool}" → ["Writing "]."""
    return [text for text, *_ in string.Formatter().parse(template) if text]


def copy_templates() -> dict[str, str]:
    """Every public copy string, flattened: constants, (label, text) pairs, dict values."""
    out: dict[str, str] = {}
    for name in dir(copy):
        if not name.isupper() or name == "NEW_COPY":
            continue
        value = getattr(copy, name)
        if isinstance(value, str):
            out[name] = value
        elif isinstance(value, tuple):
            for i, part in enumerate(value):
                out[f"{name}[{i}]"] = part
        elif isinstance(value, dict):
            for key, part in value.items():
                out[f"{name}[{key}]"] = part
    return out


def test_the_reference_file_is_present():
    assert REFERENCE.is_file(), REFERENCE


def test_there_is_copy_to_check():
    assert len(copy_templates()) > 100


@pytest.mark.parametrize("name", sorted(copy_templates()))
def test_every_copy_string_appears_verbatim_in_the_reference(name):
    text = reference_text()
    for part in literal_parts(copy_templates()[name]):
        assert part in text, f"{name}: {part!r} is not in the reference demo"


def test_recovery_summary_matches_the_copy():
    assert RECOVERY_SUMMARY == copy.SUMMARY_FAILED


def test_join_words_matches_the_demo_style():
    assert copy.join_words([]) == ""
    assert copy.join_words(["caesar"]) == "caesar"
    assert copy.join_words(["caesar", "cipher"]) == "caesar and cipher"
    assert copy.join_words(["caesar", "cipher", "encrypt"]) == "caesar, cipher and encrypt"
```

Create `tests/web/test_naming.py`:

```python
"""Session naming and query routing mirror the demo (spec 02 §8)."""

from __future__ import annotations

import pytest

from talos.web.naming import classify, session_name, weather_city


@pytest.mark.parametrize(
    ("query", "name"),
    [
        ('Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.', "Caesar cipher"),
        ('Decrypt this message with shift 7: "AHSVZ HNLUA"', "Caesar cipher"),
        ("Run this Python code: print(sum(range(1, 101)))", "Running Python"),
        ("print(2 + 2) please", "Running Python"),
        (
            "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
            "Weather in Mumbai",
        ),
        ("What's the weather in New Delhi?", "Weather in New Delhi"),
        ("what's the weather like", "Weather in Mumbai"),
        ("What can you do?", "Getting to know Talos"),
        ("How many tools are in your vault?", "What's in the vault"),
        ("list the tools in the skill vault", "What's in the vault"),
        ("convert 5 km to miles and back", "Convert 5 km to"),
        ("  hello   there  ", "Hello there"),
    ],
)
def test_session_name(query, name):
    assert session_name(query.strip()) == name


def test_chat_wins_over_caesar_like_the_demo():
    assert classify("what can you do with a caesar cipher") == "chat"


def test_long_names_are_cut_to_80_characters():
    assert len(session_name("Supercalifragilistic" * 10)) == 80


def test_weather_city_defaults_to_mumbai():
    assert weather_city("weather please") == "Mumbai"
    assert weather_city("temperature in Pune.") == "Pune"


def test_unknown_queries_are_unknown():
    assert classify("sort these numbers") == "unknown"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web -v`
Expected: collection errors, `ModuleNotFoundError: No module named 'talos.web.copy'` / `'talos.web.naming'`.

- [ ] **Step 3: Implement `copy.py`**

Create `talos/web/copy.py`:

```python
"""Every user-facing string the web layer sends (overview spec §4.5).

The copy is fixed and matches the approved Workbench demo word for word
(`docs/superpowers/specs/reference/workbench-demo/index.html`). Templates
use `str.format` fields; the literal text around each field appears
verbatim in the reference file, and `tests/web/test_copy.py` checks it.

Numbers that the demo shows as literals come from settings instead:
`{max}` is `TALOS_FORGE_MAX_RETRIES`, `{timeout}` is
`TALOS_SUBPROCESS_TIMEOUT`, `{prune}` is the vault's auto-prune threshold.

`NEW_COPY` holds the few strings the demo never needed (multi-sub-task
plans, a forge that runs out of attempts). They are listed in the
frontend spec §7 and are exempt from the reference check.
"""

from __future__ import annotations

# ---- captions (under the graph strip) ---------------------------------------

CAPTION_PLANNING = "The Planner is splitting your request into sub-tasks and checking the vault."
CAPTION_PLAN_FORGE = "1 sub-task. Nothing in the vault matches, so it needs a new tool."
CAPTION_PLAN_FORGE_WEATHER = (
    "1 sub-task. Nothing in the vault fetches weather, so it needs a new tool."
)
CAPTION_PLAN_VAULT_KEYWORDS = (
    'The Planner matched <span class="mono">{tool}</span> on the keywords {keywords}.'
    " Nothing will be written or tested this time."
)
CAPTION_PLAN_VAULT = 'The Planner matched <span class="mono">{tool}</span> in the vault.'
CAPTION_PLAN_PRIMITIVE = "1 sub-task, a built-in primitive. Nothing needs forging."
CAPTION_PLAN_CHAT = (
    "The Planner returned an empty plan. There's nothing to run, so Talos answers directly."
)
CAPTION_PLAN_UNKNOWN = "This demo only replays a few scripted runs, so the Planner stops here."
CAPTION_FORGER_FIRST = (
    'The Forger is writing <span class="mono">{tool}</span> and its tests in one structured call.'
)
CAPTION_FORGER_RETRY = (
    '<span class="gold">Attempt {n} of {max}.</span>'
    " The failing test and its traceback went back to the Forger."
)
CAPTION_TESTER = (
    '<span class="gold">Attempt {n} of {max}.</span>'
    " Running {k} tests in a subprocess, {timeout}-second limit."
)
CAPTION_SMOKE = "Smoke test: the tool runs once on a real input before it can be saved."
CAPTION_HUMAN_SKIP = "No API key needed, so Human check passed straight through."
CAPTION_HUMAN_KEY_SET = (
    '<span class="mono">{env}</span> is already set, so Human check passed straight through.'
)
CAPTION_HUMAN_WAIT = (
    'Human check paused the graph. <span class="mono">{tool}</span> needs'
    ' <span class="mono">{env}</span>.'
)
CAPTION_HUMAN_SAVED = 'Saved <span class="mono">{env}</span> to .env. Talos won\'t ask again.'
CAPTION_HUMAN_SKIPPED = (
    "You skipped the key. The tool is still saved, but it will fail until the key is set."
)
CAPTION_LEARN = "Learn is writing the .py file and its manifest entry."
CAPTION_EXECUTOR = "The Executor is reading your message and filling in the arguments."
CAPTION_EXECUTOR_SHORT = "The Executor is filling in the arguments."
CAPTION_EXEC_PAUSED = (
    'The Executor paused. <span class="mono">{tool}</span> runs code on your machine,'
    " so it asks first."
)
CAPTION_EXEC_AUTO = 'Ran without asking, because "Ask before running code" is off in Settings.'
CAPTION_DECLINED = "Nothing ran. The sub-task is recorded as declined."
CAPTION_DONE_FORGED = (
    "Done in {attempts} attempts. No API key was needed, so Human check passed straight through."
)
CAPTION_DONE_VAULT = "Done from the vault. The forge sub-graph never ran."
CAPTION_DONE_PRIMITIVE = "Done. Primitives go straight to the Executor, so nothing was forged."
CAPTION_DONE_WEATHER = "Done. In Talos the Executor would call OpenWeatherMap here with your key."
CAPTION_FAILED = "The run still finished. Talos explained the failure instead of guessing a result."
CAPTION_FAILED_NO_KEY = "The tool ran without its key and raised an error."
CAPTION_STOPPED = "You stopped this run. Nothing was saved to the vault."

# ---- run log lines: (label, text) ---------------------------------------------

LOG_PLAN_FORGE = ("plan", "1 sub-task, needs a new tool")
LOG_PLAN_VAULT = ("plan", "1 sub-task, in the vault")
LOG_PLAN_PRIMITIVE = ("plan", "1 sub-task, primitive")
LOG_PLAN_CHAT = ("plan", "no sub-tasks, answering directly")
LOG_PLAN_UNKNOWN = ("plan", "not in this demo")
LOG_VAULT_MISS = ("vault", "no match")
LOG_VAULT_HIT = ("vault", "{tool}")
LOG_FORGE_FIRST = ("forge", "{tool}()")
LOG_FORGE_RETRY = ("forge", "attempt {n}")
LOG_TEST_RUNNING = ("test", "running")
LOG_TEST_RETRYING = ("test", "{passed} of {total} passed, retrying")
LOG_TEST_PASSED = ("test", "{total} of {total} passed")
LOG_SMOKE = ("smoke", "{result}")
LOG_CHECK_KEY_SET = ("check", "key already set")
LOG_CHECK_WAITING = ("check", "waiting for a key")
LOG_CHECK_SAVED = ("check", "key saved to .env")
LOG_CHECK_SKIPPED = ("check", "skipped by you")
LOG_LEARN = ("learn", "saved to the vault")
LOG_EXEC_DONE = ("execute", "done")
LOG_EXEC_DONE_WEATHER = ("execute", "done (demo stops before the API)")
LOG_EXEC_FAILED = ("execute", "failed, {error_type}")
LOG_EXEC_PAUSED = ("execute", "paused for approval")
LOG_EXEC_RUNNING = ("execute", "running")
LOG_EXEC_DECLINED = ("execute", "declined by you")
LOG_VAULT_REMOVED = ("vault", "removed after {prune} failures in a row")
LOG_VAULT_STREAK = ("vault", "{streak} failure in a row")
LOG_STOP = ("stop", "stopped by you")

# ---- run-log status line (log.status) -------------------------------------------

STATUS_FORGING = "Forging"
STATUS_NONE_FORGED = "0 tools forged"
STATUS_ONE_FORGED = "1 tool forged"
STATUS_STEP_FAILED = "1 step failed"
STATUS_WAITING = "Waiting for you"
STATUS_NOT_RUN = "Not run"
STATUS_NOTHING_RAN = "Nothing ran"
STATUS_STOPPED = "Stopped"

# ---- "working on it" status next to the orbit (talos.status) ---------------------

TALOS_PLANNING = "Planning"
TALOS_WRITING = "Writing {tool}"
TALOS_RETRYING = "The first attempt failed a test. Trying again"
TALOS_RUNNING = "Running {tool}"
TALOS_FOUND = "Found {tool} in the vault"
TALOS_APPROVE = "Waiting for you to approve the code"
TALOS_NEEDS_KEY = "The tool is written and tested. It needs an API key before it can run"

# ---- strip labels -----------------------------------------------------------------

LABEL_FORGE = "Sub-task {i} of {n}, needs a new tool"
LABEL_VAULT = "Sub-task {i} of {n}, found in the vault"
LABEL_PRIMITIVE = "Sub-task {i} of {n}, built-in primitive"
LABEL_CHAT = "Conversational"
LABEL_UNKNOWN = "Scripted demo"
LABEL_EXEC_WAITING = "Executor, waiting for you"
LABEL_EXEC_DECLINED = "Executor, declined"
LABEL_EXEC_FAILED = "Executor failed"
LABEL_HUMAN_SKIPPED = "Human check, skipped"
LABEL_STOPPED_SUFFIX = ", stopped"

# ---- forge details ------------------------------------------------------------------

NOTE_CHANGED_LINE = "Line {line} is new in attempt {n}."
DETAIL_TESTS_PASSED = "{total} of {total} tests passed"
ARGS_CAPTION = "Filled in by the Executor"
ARGS_CAPTION_CODE = "Written by the Executor"
ARGS_CAPTION_NONE = "Takes no arguments"

# ---- vault banner second line (vault.saved.sub) -----------------------------------------

SAVED_SUB = "Next time a request needs {what}, Talos skips forging and goes straight to Execute."
SAVED_SUB_KEY = "Next time you ask about the weather, Talos reuses it. It reads the key from .env."

# ---- chips and run summaries --------------------------------------------------------------

CHIP_FORGED = "Forged {tool}"
CHIP_REUSED = "Reused {tool} from the vault"
CHIP_FAILED = "{tool} raised a {error_type}"

SUMMARY_FORGED = "1 tool forged, {attempts} attempts"
SUMMARY_FORGED_KEY = "1 tool forged, key saved"
SUMMARY_FORGED_NO_KEY = "1 tool forged, failed without a key"
SUMMARY_NO_KEY = "Failed without a key"
SUMMARY_REUSED = "0 tools forged"
SUMMARY_FAILED_STREAK = "Failed, {streak} failure in a row"
SUMMARY_FAILED_PRUNED = "Failed, removed from the vault"
SUMMARY_FAILED = "Failed"
SUMMARY_PRIMITIVE = "Built-in"
SUMMARY_PRIMITIVE_APPROVED = "Built-in, approved"
SUMMARY_DECLINED = "Declined, nothing ran"
SUMMARY_CHAT = "Answered directly"
SUMMARY_UNKNOWN = "Not in this demo"
SUMMARY_STOPPED = "Stopped"

STOP_NOTE = "Stopped. Ask again whenever you're ready."

# ---- scripted answers (fake graph only; html fields must be escaped by the caller) --------

ANSWER_ENCRYPTED = '"{text}" encrypted with a shift of {shift} is <span class="mono">{out}</span>.'
ANSWER_DECRYPTED = 'It decrypts to <span class="mono">{out}</span>.'
NOTE_ENCRYPT_TOO = 'The same tool decrypts too. Ask with "decrypt" and the same shift.'
NOTE_DECRYPT_TOO = 'The same tool encrypts too. Ask with "encrypt" and the same shift.'
ANSWER_CAESAR_FAILED = (
    'I couldn\'t {mode} that. <span class="mono">caesar_cipher</span> needs the shift as a'
    ' number, and it was given the word "{word}".'
)
NOTE_RETRY_DIGIT = 'Ask again with "shift {digit}" and it should work.'
NOTE_RETRY_NUMBER = "Ask again with the shift as a number."
ANSWER_DECLINED = "I didn't run the code, so I don't have its output."
NOTE_DECLINED = "Approve it next time, or turn off the prompt in Settings."
ANSWER_PYTHON = 'The code prints <span class="mono">{out}</span>.'
ANSWER_PYTHON_UNSUPPORTED = (
    'This demo can only run simple <span class="mono">print()</span> calls,'
    " so there's no output to show."
)
RESULT_PYTHON_UNSUPPORTED = "The demo only runs simple print() calls."
ANSWER_WEATHER_NO_KEY = (
    'I couldn\'t get the temperature. <span class="mono">{tool}</span> needs'
    ' <span class="mono">{env}</span>, and it isn\'t set.'
)
NOTE_WEATHER_NO_KEY = "Ask again and paste the key when Human check asks for it."
ANSWER_WEATHER = (
    "The tool is ready and your key is saved. This demo can't reach the internet,"
    " so it stops before calling OpenWeatherMap."
)
NOTE_WEATHER = "In Talos, you'd get the current temperature in {city} here."
RESULT_WEATHER = "Not called in this demo"
ANSWER_CHAT = (
    "I split your request into steps, then use a built-in tool, reuse one from my vault,"
    " or write and test a new Python tool for whatever's missing."
    " The vault holds {count} tools right now."
)
NOTE_CHAT = "Try asking me to build a Caesar cipher."
ANSWER_UNKNOWN = (
    "This demo can't plan that one. It replays a few scripted runs over the real vault."
    " Try one of these:"
)

# ---- Settings page key descriptions ---------------------------------------------------------

KEY_DESCRIPTIONS = {
    "OPENROUTER_API_KEY": "Required. Every model call goes through OpenRouter.",
    "TAVILY_API_KEY": "Needed for web search.",
    "JINA_API_KEY": "Optional. Raises web-reading limits.",
    "LANGSMITH_API_KEY": "Optional. Traces every node in LangSmith.",
}
KEY_SAVED_BY_HUMAN_CHECK = "Saved by Human check"

# ---- strings the demo never needed (frontend spec §7) ---------------------------------------

NEW_COPY = {
    "CAPTION_PLAN_MULTI": "{n} sub-tasks. Talos works through them in order.",
    "LOG_PLAN_MULTI": "{n} sub-tasks",
    "CAPTION_FORGE_GAVE_UP": "The Forger used all {max} attempts. Nothing was saved to the vault.",
    "LOG_FORGE_GAVE_UP": "gave up after {n} attempts",
    "LOG_TEST_FAILED": "{passed} of {total} passed",
    "LOG_SMOKE_FAILED": "failed",
    "TALOS_RETRYING_N": "Attempt {n} failed a test. Trying again",
    "SUMMARY_FORGED_MANY": "{k} tools forged",
    "SUMMARY_FORGED_ONE": "1 tool forged, 1 attempt",
    "CAPTION_DONE_FORGED_ONE": (
        "Done in 1 attempt. No API key was needed, so Human check passed straight through."
    ),
    "CAPTION_DONE_FORGED_KEY": "Done in {attempts}. Your key is saved to .env.",
}


def new(key: str, **fields: object) -> str:
    """Format one of the `NEW_COPY` strings."""
    return NEW_COPY[key].format(**fields)


def join_words(words: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`: the demo's keyword list style."""
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]
```

- [ ] **Step 4: Implement `naming.py`**

Create `talos/web/naming.py`:

```python
"""Session names from the first query, and the demo's query routing.

`classify()` is the demo's `classify(q)` and `session_name()` its
`sessionName(kind, q)`, ported regex for regex. The fake graph routes with
`classify()` too.
"""

from __future__ import annotations

import re
from typing import Literal

QueryKind = Literal["chat", "caesar", "python", "weather", "vaultlist", "unknown"]

MAX_NAME = 80

_CHAT = re.compile(r"\b(what can you do|who are you|help me understand|how do you work)\b", re.I)
_CAESAR = re.compile(r"(caesar|cipher|\bencrypt|\bdecrypt)", re.I)
_PYTHON = re.compile(r"(python|print\s*\(|run this code|run the code)", re.I)
_WEATHER = re.compile(r"(openweather|weather|temperature)", re.I)
_VAULTLIST = re.compile(
    r"(how many tools|list (all )?(your|the) tools|in (your|the) (skill )?vault)", re.I
)
_CITY = re.compile(r"\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)")


def classify(query: str) -> QueryKind:
    """Route a query the way the demo does. First match wins."""
    if _CHAT.search(query):
        return "chat"
    if _CAESAR.search(query):
        return "caesar"
    if _PYTHON.search(query):
        return "python"
    if _WEATHER.search(query):
        return "weather"
    if _VAULTLIST.search(query):
        return "vaultlist"
    return "unknown"


def weather_city(query: str) -> str:
    """The city in "... in Mumbai." style queries, else Mumbai (the demo's default)."""
    match = _CITY.search(query)
    return match.group(1).strip() if match else "Mumbai"


def session_name(query: str) -> str:
    """A session's name from its first query (spec 02 §8).

    Args:
        query: The first message, already trimmed.

    Returns:
        At most 80 characters, e.g. "Caesar cipher" or "Weather in Pune".
    """
    kind = classify(query)
    if kind == "caesar":
        name = "Caesar cipher"
    elif kind == "python":
        name = "Running Python"
    elif kind == "weather":
        name = f"Weather in {weather_city(query)}"
    elif kind == "chat":
        name = "Getting to know Talos"
    elif kind == "vaultlist":
        name = "What's in the vault"
    else:
        words = " ".join(query.split()[:4])
        name = words[:1].upper() + words[1:]
    return name[:MAX_NAME] or "Session"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS (about 180 tests: one per copy string, plus naming). If a copy test fails, the string was mistyped: fix `copy.py` to match the reference file, never the other way round.

- [ ] **Step 6: Commit**

```bash
git add talos/web/copy.py talos/web/naming.py tests/web/__init__.py tests/web/test_copy.py tests/web/test_naming.py
git commit -m "[Feat]: Add the web copy table checked against the demo, and session naming"
```

---

### Task 3: Demo tool sources, API schemas and the run board

**Files:**
- Create: `talos/web/demo_sources.py`, `talos/web/schemas.py`, `talos/web/board.py`
- Test: `tests/web/test_demo_sources.py`, `tests/web/test_schemas.py`, `tests/web/test_board.py`

**Interfaces:**
- Consumes: `talos.web.copy` (Task 2); `tests.web.test_copy.REFERENCE` (Task 2).
- Produces:
  - `talos.web.demo_sources`: `CAESAR_SOURCE: str` (63 lines, no trailing newline), `WEATHER_SOURCE: str`, `CAESAR: dict` / `WEATHER: dict` (keys `name, args, ret, description, keywords`; `WEATHER["env"] = "OPENWEATHERMAP_API_KEY"`), `CAESAR_BAD_LINE = 48`, `CAESAR_BAD_SOURCE: str`.
  - `talos.web.schemas`: Pydantic models `ErrorBody, ErrorOut, SessionOut, MessageOut, RunSummaryOut, PendingOut, RunOut(RunSummaryOut + pending), RunMarkOut, SessionSummaryOut, SessionDetailOut, StartRunOut, RenameIn, MessageIn, ResumeIn, VaultEntry, VaultDetail, VaultListOut, KeyOut, SettingsOut, SettingsPatch, HealthOut` (the `*Out` row models use `from_attributes=True`); functions `split_signature(signature: str) -> tuple[str, str]`, `is_web_source(source: str | None) -> bool`, `vault_entry(entry: Mapping[str, Any], source: str | None) -> VaultEntry`, `service_name(env_var: str) -> str`, `pending_payload(value: Mapping[str, Any]) -> dict[str, Any]`.
  - `talos.web.board`: `Event = tuple[str, dict[str, Any]]`; `STRIPS: dict[str, list[tuple[str, str]]]`; `new_state() -> dict` (keys `variant, steps, forged, used, failed`); class `Board(state: dict | None = None)` with `.state`, `.events`, `drain() -> list[Event]`, `emit(type_, **data)`, `strip(variant, *, index, total, label, sig)`, `start(step, label=None)`, `finish(step, status, label=None)`, `flow(source, target)`, `caption(html)`, `log(line: tuple[str, str], tone="plain", *, caret=False, **fields)`, `sub(text)`, `pop()`, `status(text, *, gold=False, tone="")`, `talos(text)`, `add_forged(tool)`, `add_used(tool)`, `mark_failed()`, `stop()`, `finished(status, summary, *, gold=False)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_demo_sources.py`:

```python
"""The fake graph's tool sources are the demo's, byte for byte."""

from __future__ import annotations

import re

from talos.web.demo_sources import (
    CAESAR,
    CAESAR_BAD_LINE,
    CAESAR_BAD_SOURCE,
    CAESAR_SOURCE,
    WEATHER,
    WEATHER_SOURCE,
)
from tests.web.test_copy import REFERENCE


def script(block_id: str) -> str:
    text = REFERENCE.read_text(encoding="utf-8")
    pattern = rf'<script type="text/plain" id="{block_id}">(.*?)</script>'
    return re.search(pattern, text, re.S).group(1)


def test_sources_match_the_reference_blocks():
    assert CAESAR_SOURCE == script("src-caesar")
    assert WEATHER_SOURCE == script("src-weather")


def test_the_bad_attempt_differs_only_on_line_48():
    good, bad = CAESAR_SOURCE.split("\n"), CAESAR_BAD_SOURCE.split("\n")
    assert len(good) == len(bad) == 63
    diff = [i + 1 for i, (a, b) in enumerate(zip(good, bad, strict=True)) if a != b]
    assert diff == [CAESAR_BAD_LINE] == [48]
    assert bad[47] == "    effective_shift = shift"


def test_the_caesar_source_really_works():
    namespace: dict = {}
    exec(CAESAR_SOURCE, namespace)
    assert namespace["caesar_cipher"](text="TALOS AGENT", shift=7, mode="encrypt") == "AHSVZ HNLUA"


def test_metadata_matches_the_demo_constants():
    text = REFERENCE.read_text(encoding="utf-8")
    for meta in (CAESAR, WEATHER):
        assert f'name: "{meta["name"]}", args: "{meta["args"]}", ret: "{meta["ret"]}"' in text
    assert WEATHER["env"] == "OPENWEATHERMAP_API_KEY"
```

Create `tests/web/test_schemas.py`:

```python
"""Converters and request models (spec 02 §4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from talos.web.schemas import (
    MessageIn,
    RenameIn,
    ResumeIn,
    is_web_source,
    pending_payload,
    service_name,
    split_signature,
    vault_entry,
)


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        (
            "caesar_cipher(text: str, shift: int, mode: str) -> str",
            ("text: str, shift: int, mode: str", "str"),
        ),
        ("generate_uuid4() -> str", ("", "str")),
        (
            "hex_to_rgb(hex_code: str) -> tuple[int, int, int]",
            ("hex_code: str", "tuple[int, int, int]"),
        ),
        ("f(x)", ("x", "")),
        ("not a signature", ("", "")),
        ("", ("", "")),
    ],
)
def test_split_signature(signature, expected):
    assert split_signature(signature) == expected


def test_web_means_it_imports_an_http_library():
    assert is_web_source("import requests\n")
    assert is_web_source("from urllib.request import urlopen\n")
    assert is_web_source("    import httpx\n")
    assert not is_web_source("# requests are nice\nimport json\n")
    assert not is_web_source(None)


def test_vault_entry_maps_manifest_fields():
    entry = {
        "name": "slugify",
        "signature": "slugify(title: str) -> str",
        "description": "Slug it.",
        "keywords": ["slug"],
        "usage_count": 3,
        "failure_count": 1,
        "consecutive_failures": 1,
        "created_at": "2026-09-28T14:58:00+00:00",
        "last_used": None,
        "last_failure_reason": "TypeError: x",
        "last_failed_at": "2026-09-28T15:00:00+00:00",
        "file": "tools/slugify.py",
    }
    out = vault_entry(entry, "def slugify(title): ...").model_dump()
    assert out == {
        "name": "slugify",
        "args": "title: str",
        "ret": "str",
        "signature": "slugify(title: str) -> str",
        "description": "Slug it.",
        "keywords": ["slug"],
        "uses": 3,
        "failures": 1,
        "streak": 1,
        "created_at": "2026-09-28T14:58:00+00:00",
        "last_used": None,
        "last_failure": "TypeError: x",
        "last_failed_at": "2026-09-28T15:00:00+00:00",
        "web": False,
        "file": "tools/slugify.py",
    }
    assert vault_entry({"name": "x"}, None).file == "tools/x.py"


def test_service_names():
    assert service_name("OPENWEATHERMAP_API_KEY") == "OpenWeatherMap"
    assert service_name("GITHUB_TOKEN") == "GitHub"
    assert service_name("ACME_API_KEY") == "ACME_API_KEY"


def test_pending_payload_never_carries_code_args():
    confirm = {
        "type": "confirm_exec",
        "tool": "python_exec",
        "preview": "print(1)",
        "args": ["x"],
        "kwargs": {"code": "print(1)"},
        "message": "Allow it?",
    }
    assert pending_payload(confirm) == {"tool": "python_exec", "preview": "print(1)"}
    key = {"type": "missing_api_key", "env_var": "OPENWEATHERMAP_API_KEY", "tool_name": "t"}
    assert pending_payload(key) == {
        "env_var": "OPENWEATHERMAP_API_KEY",
        "tool_name": "t",
        "service": "OpenWeatherMap",
    }


def test_request_models_trim_and_bound():
    assert RenameIn(name="  Ciphers ").name == "Ciphers"
    assert MessageIn(text="  hi \n").text == "hi"
    for bad in ({"name": ""}, {"name": "x" * 81}):
        with pytest.raises(ValidationError):
            RenameIn(**bad)
    with pytest.raises(ValidationError):
        MessageIn(text="x" * 4001)
    with pytest.raises(ValidationError):
        ResumeIn(decision="maybe")
    assert "sk-123" not in repr(ResumeIn(decision="save", value="sk-123"))
```

Create `tests/web/test_board.py`:

```python
"""Board: UI state plus the contract events that change it."""

from __future__ import annotations

import json

from talos.web.board import STRIPS, Board, new_state


def test_strip_resets_steps_and_starts_skip_as_skip():
    b = Board()
    b.strip("vault", index=1, total=1, label="Sub-task 1 of 1, found in the vault", sig=None)
    assert [k for k in b.state["steps"]] == [k for k, _ in STRIPS["vault"]]
    assert b.state["steps"]["skip"]["state"] == "skip"
    assert b.state["steps"]["vault"] == {"state": "pending", "label": "Vault tool"}
    assert b.drain() == [
        (
            "strip.set",
            {
                "variant": "vault",
                "subtask": {"index": 1, "total": 1, "label": "Sub-task 1 of 1, found in the vault"},
                "sig": None,
            },
        )
    ]
    assert b.drain() == []


def test_node_events_carry_labels_only_when_given():
    b = Board()
    b.strip("primitive", index=1, total=1, label="x", sig=None)
    b.drain()
    b.start("executor", "Executor, waiting for you")
    b.finish("executor", "done", "Executor")
    b.start("answer")
    assert b.drain() == [
        ("node.started", {"step": "executor", "label": "Executor, waiting for you"}),
        ("node.finished", {"step": "executor", "status": "done", "label": "Executor"}),
        ("node.started", {"step": "answer"}),
    ]


def test_log_lines_format_fields_and_caret():
    b = Board()
    b.log(("test", "{passed} of {total} passed, retrying"), "g", passed=4, total=5)
    b.log(("test", "running"), "g", caret=True)
    b.sub("test_decrypt_reverses_encrypt")
    assert b.drain() == [
        ("log.line", {"label": "test", "text": "4 of 5 passed, retrying", "tone": "g"}),
        ("log.line", {"label": "test", "text": "running", "tone": "g", "caret": True}),
        ("log.line", {"label": "", "text": "test_decrypt_reverses_encrypt", "tone": "sub"}),
    ]


def test_stop_marks_active_steps_and_says_so():
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.start("forger")
    b.start("executor", "Executor, waiting for you")
    b.drain()
    b.stop()
    assert b.drain() == [
        ("node.finished", {"step": "forger", "status": "stopped", "label": "Forger, stopped"}),
        ("node.finished", {"step": "executor", "status": "stopped", "label": "Executor, stopped"}),
        ("log.line", {"label": "stop", "text": "stopped by you", "tone": "w"}),
        ("log.status", {"text": "Stopped", "gold": False, "tone": ""}),
        ("caption", {"html": "You stopped this run. Nothing was saved to the vault."}),
    ]


def test_finished_reports_tools_and_state_stays_json():
    state = new_state()
    b = Board(state)
    b.add_forged("caesar_cipher")
    b.add_forged("caesar_cipher")
    b.add_used("caesar_cipher")
    b.mark_failed()
    b.finished("done", "Failed, 1 failure in a row")
    assert b.drain()[-1] == (
        "run.finished",
        {
            "status": "done",
            "summary": "Failed, 1 failure in a row",
            "summary_gold": False,
            "forged": ["caesar_cipher"],
            "used": ["caesar_cipher"],
        },
    )
    assert state["failed"] is True
    assert json.loads(json.dumps(state)) == state
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_demo_sources.py tests/web/test_schemas.py tests/web/test_board.py -v`
Expected: collection errors, `ModuleNotFoundError` for `talos.web.demo_sources`, `talos.web.schemas`, `talos.web.board`.

- [ ] **Step 3: Implement `demo_sources.py`**

Create `talos/web/demo_sources.py`. The two sources are copied byte for byte from the `<script type="text/plain" id="src-caesar">` and `id="src-weather"` blocks of the reference file (the test compares them):

```python
"""The two tools the Workbench demo forges, verbatim from the reference demo.

The fake graph (TALOS_FAKE_GRAPH=1) "forges" these, and the translator
tests use them as the Forger's output. `tests/web/test_demo_sources.py`
checks they match the `<script type="text/plain">` blocks in
`docs/superpowers/specs/reference/workbench-demo/index.html`.
"""

from __future__ import annotations

CAESAR_SOURCE = '''"""Caesar cipher tool: shift-based encryption/decryption of text."""

import string


def caesar_cipher(text: str, shift: int, mode: str) -> str:
    """Encrypt or decrypt text with a Caesar cipher using the given shift.

    Each ASCII letter is rotated by ``shift`` positions within the alphabet
    (A-Z / a-z), preserving letter case. Non-alphabetic characters (spaces,
    digits, punctuation) are passed through unchanged. In ``"encrypt"`` mode
    letters move forward by ``shift``; in ``"decrypt"`` mode they move
    backward by the same amount. Shifts larger than 26 or negative are
    normalised modulo 26.

    Args:
        text: The input string to transform. Must be a ``str``.
        shift: The integer number of alphabet positions to rotate. May be
            negative or greater than 25; it is normalised modulo 26.
        mode: Either ``"encrypt"`` or ``"decrypt"`` (case-insensitive,
            surrounding whitespace ignored).

    Returns:
        The transformed string with the same length as ``text``.

    Raises:
        TypeError: If ``text`` or ``mode`` is not a ``str``, or ``shift`` is
            not an ``int`` (booleans are rejected).
        ValueError: If ``mode`` is not ``"encrypt"`` or ``"decrypt"``.

    Example:
        >>> caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")
        'AHSVZ HNLUA'
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}")
    if isinstance(shift, bool) or not isinstance(shift, int):
        raise TypeError(f"shift must be an int, got {type(shift).__name__}")
    if not isinstance(mode, str):
        raise TypeError(f"mode must be a str, got {type(mode).__name__}")

    normalized_mode = mode.strip().lower()
    if normalized_mode not in ("encrypt", "decrypt"):
        raise ValueError(
            f"mode must be 'encrypt' or 'decrypt', got {mode!r}"
        )

    effective_shift = shift if normalized_mode == "encrypt" else -shift
    effective_shift %= 26

    result_chars = []
    for char in text:
        if char in string.ascii_uppercase:
            base = ord("A")
        elif char in string.ascii_lowercase:
            base = ord("a")
        else:
            result_chars.append(char)
            continue
        rotated = (ord(char) - base + effective_shift) % 26 + base
        result_chars.append(chr(rotated))

    return "".join(result_chars)'''

WEATHER_SOURCE = '''"""Current temperature for a city from OpenWeatherMap."""

import os

import requests


def get_current_temperature(city: str) -> float:
    """Return the current temperature in Celsius for ``city``.

    Reads the API key from the OPENWEATHERMAP_API_KEY environment variable.

    Args:
        city: City name, for example "Mumbai".

    Returns:
        The current temperature in degrees Celsius.

    Raises:
        RuntimeError: If the API key is not set.
        ValueError: If the city is empty or not found.
    """
    key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not key:
        raise RuntimeError("OPENWEATHERMAP_API_KEY is not set")
    if not city.strip():
        raise ValueError("city must not be empty")
    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": city, "appid": key, "units": "metric"},
        timeout=10,
    )
    if resp.status_code == 404:
        raise ValueError(f"city not found: {city!r}")
    resp.raise_for_status()
    return float(resp.json()["main"]["temp"])'''

CAESAR = {
    "name": "caesar_cipher",
    "args": "text: str, shift: int, mode: str",
    "ret": "str",
    "description": (
        "Encrypts or decrypts a text string using a Caesar cipher with a given shift,"
        " preserving case and non-alphabetic characters."
    ),
    "keywords": ["caesar", "cipher", "encrypt", "decrypt", "shift", "text", "cryptography"],
}

WEATHER = {
    "name": "get_current_temperature",
    "args": "city: str",
    "ret": "float",
    "description": "Returns the current temperature in Celsius for a city from OpenWeatherMap.",
    "keywords": ["weather", "temperature", "openweathermap", "city", "celsius", "mumbai"],
    "env": "OPENWEATHERMAP_API_KEY",
}

# Attempt 1 of the Caesar forge: line 48 forgets to negate the shift for decrypt.
CAESAR_BAD_LINE = 48
CAESAR_BAD_SOURCE = "\n".join(
    "    effective_shift = shift" if i == CAESAR_BAD_LINE else line
    for i, line in enumerate(CAESAR_SOURCE.split("\n"), start=1)
)
```

- [ ] **Step 4: Implement `schemas.py`**

Create `talos/web/schemas.py`:

```python
"""Request and response models for the API (spec 02 §4), plus converters.

Converters here are pure: vault manifest entry → `VaultEntry`, a signature
string → name/args/ret, an interrupt value → its browser-safe payload.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---- errors ---------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody


# ---- sessions, messages, runs ---------------------------------------------------


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SessionOut(_FromRow):
    id: uuid.UUID
    name: str
    number: int
    created_at: datetime
    updated_at: datetime


class MessageOut(_FromRow):
    id: uuid.UUID
    role: str
    html: str
    note: str | None
    chips: list[dict[str, Any]]
    run_id: uuid.UUID | None
    created_at: datetime


class RunSummaryOut(_FromRow):
    id: uuid.UUID
    n: int
    query: str
    status: str
    summary: str | None
    summary_gold: bool
    forged: list[str]
    used: list[str]
    failed: bool
    started_at: datetime
    finished_at: datetime | None


class PendingOut(BaseModel):
    kind: str
    payload: dict[str, Any]


class RunOut(RunSummaryOut):
    pending: PendingOut | None = None


class RunMarkOut(_FromRow):
    n: int
    query: str
    mark: str | None


class SessionSummaryOut(_FromRow):
    id: uuid.UUID
    name: str
    created_at: datetime
    run_count: int
    forged: list[str]
    used: list[str]
    runs: list[RunMarkOut]


class SessionDetailOut(BaseModel):
    session: SessionOut
    messages: list[MessageOut]
    runs: list[RunSummaryOut]


class StartRunOut(BaseModel):
    run: RunSummaryOut
    message: MessageOut


class RenameIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 80:
            raise ValueError("name must be 1 to 80 characters")
        return value


class MessageIn(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 4000:
            raise ValueError("text must be 1 to 4000 characters")
        return value


class ResumeIn(BaseModel):
    """`/resume` body. `value` is an API key: never logged or echoed (repr=False)."""

    decision: Literal["approve", "decline", "save", "skip"]
    value: str | None = Field(default=None, max_length=4096, repr=False)


# ---- vault ----------------------------------------------------------------------


class VaultEntry(BaseModel):
    name: str
    args: str
    ret: str
    signature: str
    description: str
    keywords: list[str]
    uses: int
    failures: int
    streak: int
    created_at: str | None
    last_used: str | None
    last_failure: str | None
    last_failed_at: str | None
    web: bool
    file: str


class VaultDetail(VaultEntry):
    source: str | None
    lines: int


class VaultListOut(BaseModel):
    count: int
    web_count: int
    failed_count: int
    tools: list[VaultEntry]


# ---- settings, health -------------------------------------------------------------


class KeyOut(BaseModel):
    name: str
    set: bool
    required: bool
    description: str


class SettingsOut(BaseModel):
    model: str
    ask_before_exec: bool
    forge_retries: int
    test_timeout_s: int
    llm_timeout_s: float
    prune_after: int
    keys: list[KeyOut]


class SettingsPatch(BaseModel):
    ask_before_exec: bool


class HealthOut(BaseModel):
    ok: bool
    db: bool
    fake_graph: bool
    version: str


# ---- converters ----------------------------------------------------------------------

_SIGNATURE = re.compile(r"^\s*[\w.]*\s*\((?P<args>.*)\)\s*(?:->\s*(?P<ret>.+?))?\s*$", re.S)
_WEB_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:requests|urllib|httpx)\b", re.M)


def split_signature(signature: str) -> tuple[str, str]:
    """`"f(a: int, b: str) -> bool"` → `("a: int, b: str", "bool")`.

    Anything that doesn't look like a signature gives `("", "")`.
    """
    match = _SIGNATURE.match(signature or "")
    if match is None:
        return "", ""
    return match.group("args").strip(), (match.group("ret") or "").strip()


def is_web_source(source: str | None) -> bool:
    """True when a tool's source imports requests, urllib or httpx."""
    return bool(source) and _WEB_IMPORT.search(source) is not None


def vault_entry(entry: Mapping[str, Any], source: str | None) -> VaultEntry:
    """Turn a manifest entry (SkillEntry) into the API's VaultEntry."""
    signature = str(entry.get("signature") or "")
    args, ret = split_signature(signature)
    name = str(entry.get("name") or "")
    return VaultEntry(
        name=name,
        args=args,
        ret=ret,
        signature=signature,
        description=str(entry.get("description") or ""),
        keywords=[str(k) for k in entry.get("keywords") or []],
        uses=int(entry.get("usage_count") or 0),
        failures=int(entry.get("failure_count") or 0),
        streak=int(entry.get("consecutive_failures") or 0),
        created_at=entry.get("created_at"),
        last_used=entry.get("last_used"),
        last_failure=entry.get("last_failure_reason"),
        last_failed_at=entry.get("last_failed_at"),
        web=is_web_source(source),
        file=str(entry.get("file") or f"tools/{name}.py"),
    )


# Env var prefix → service name, for the key dialog's "This tool needs an X key".
_SERVICES = {
    "OPENWEATHERMAP": "OpenWeatherMap",
    "OPENWEATHER": "OpenWeatherMap",
    "OPENAI": "OpenAI",
    "OPENROUTER": "OpenRouter",
    "ANTHROPIC": "Anthropic",
    "TAVILY": "Tavily",
    "JINA": "Jina",
    "LANGSMITH": "LangSmith",
    "GITHUB": "GitHub",
    "NEWSAPI": "NewsAPI",
}


def service_name(env_var: str) -> str:
    """`OPENWEATHERMAP_API_KEY` → `OpenWeatherMap`; unknown names come back unchanged."""
    stem = re.sub(r"_(API_KEY|KEY|TOKEN|SECRET)$", "", env_var or "")
    return _SERVICES.get(stem, env_var)


InterruptKind = Literal["confirm_exec", "missing_api_key"]


def pending_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """The browser-safe part of an interrupt value (overview §4.3).

    `confirm_exec` keeps `tool` and `preview` only: `args`/`kwargs` stay on
    the server so the browser never sends code back.
    """
    if value.get("type") == "confirm_exec":
        return {"tool": value.get("tool"), "preview": str(value.get("preview") or "")}
    env_var = str(value.get("env_var") or "")
    return {
        "env_var": env_var,
        "tool_name": value.get("tool_name"),
        "service": service_name(env_var),
    }
```

- [ ] **Step 5: Implement `board.py`**

Create `talos/web/board.py`:

```python
"""A run's UI state (strip, steps, outcome) and the contract events that change it.

Both event sources use this: `EventTranslator` (real graph) and the fake
graph's scripted flows. Every method appends contract events to
`board.events`; the caller drains them. The state is a plain JSON dict,
saved on the run row as `translator_state`, so a paused run can be resumed
by a new process and a stopped run can mark its active steps.

`seq` is never kept here: `repo.append_event` allocates it.
"""

from __future__ import annotations

import re
from typing import Any

from talos.web import copy

Event = tuple[str, dict[str, Any]]

# Strip variants (overview §4.2): step keys and their default labels.
STRIPS: dict[str, list[tuple[str, str]]] = {
    "forge": [
        ("planner", "Planner"),
        ("forger", "Forger"),
        ("tester", "Tester"),
        ("human", "Human check"),
        ("learn", "Learn"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "vault": [
        ("planner", "Planner"),
        ("vault", "Vault tool"),
        ("skip", "Forge sub-graph skipped"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "primitive": [
        ("planner", "Planner"),
        ("primitive", "Primitive"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "chat": [("planner", "Planner"), ("answer", "Answer")],
}


def new_state() -> dict[str, Any]:
    """The empty board state for a new run."""
    return {"variant": None, "steps": {}, "forged": [], "used": [], "failed": False}


class Board:
    """Builds contract events and keeps the UI state they imply.

    Args:
        state: A dict from `new_state()` (or a saved copy). Mutated in place.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = state if state is not None else new_state()
        for key, value in new_state().items():
            self.state.setdefault(key, value)
        self.events: list[Event] = []

    # ---- plumbing -----------------------------------------------------------

    def drain(self) -> list[Event]:
        """Return and forget the events built so far."""
        out, self.events = self.events, []
        return out

    def emit(self, type_: str, **data: Any) -> None:
        """Append one contract event."""
        self.events.append((type_, data))

    # ---- strip ----------------------------------------------------------------

    def strip(
        self,
        variant: str,
        *,
        index: int,
        total: int,
        label: str,
        sig: dict[str, str] | None,
    ) -> None:
        """Reset the strip to `variant` (`strip.set`). `skip` starts as `skip`."""
        self.state["variant"] = variant
        self.state["steps"] = {
            key: {"state": "skip" if key == "skip" else "pending", "label": name}
            for key, name in STRIPS[variant]
        }
        self.emit(
            "strip.set",
            variant=variant,
            subtask={"index": index, "total": total, "label": label},
            sig=sig,
        )

    def start(self, step: str, label: str | None = None) -> None:
        """`node.started`: the step becomes active."""
        self._set(step, "active", label)
        self.emit("node.started", step=step, **({"label": label} if label else {}))

    def finish(self, step: str, status: str, label: str | None = None) -> None:
        """`node.finished` with status done, forge, skip, fail, answer or stopped."""
        self._set(step, status, label)
        self.emit("node.finished", step=step, status=status, **({"label": label} if label else {}))

    def flow(self, source: str, target: str) -> None:
        """`link.flow`: a gold packet travels from one step to the next."""
        self.emit("link.flow", **{"from": source, "to": target})

    def _set(self, step: str, state: str, label: str | None) -> None:
        entry = self.state["steps"].setdefault(step, {"state": "pending", "label": step})
        entry["state"] = state
        if label:
            entry["label"] = label

    # ---- narration ---------------------------------------------------------------

    def caption(self, html: str) -> None:
        self.emit("caption", html=html)

    def log(
        self,
        line: tuple[str, str],
        tone: str = "plain",
        *,
        caret: bool = False,
        **fields: Any,
    ) -> None:
        """`log.line` from a `(label, text)` template in `copy`."""
        label, text = line
        data: dict[str, Any] = {"label": label, "text": text.format(**fields), "tone": tone}
        if caret:
            data["caret"] = True
        self.emit("log.line", **data)

    def sub(self, text: str) -> None:
        """An indented sub line under the previous log line (e.g. a failing test)."""
        self.emit("log.line", label="", text=text, tone="sub")

    def pop(self) -> None:
        """`log.pop`: drop the last (transient "running") log line."""
        self.emit("log.pop")

    def status(self, text: str, *, gold: bool = False, tone: str = "") -> None:
        """`log.status`: the run-log caption and frame tone."""
        self.emit("log.status", text=text, gold=gold, tone=tone)

    def talos(self, text: str) -> None:
        """`talos.status`: the "working on it" text next to the orbit."""
        self.emit("talos.status", text=text)

    # ---- outcome ------------------------------------------------------------------

    def add_forged(self, tool: str) -> None:
        if tool and tool not in self.state["forged"]:
            self.state["forged"].append(tool)

    def add_used(self, tool: str) -> None:
        if tool and tool not in self.state["used"]:
            self.state["used"].append(tool)

    def mark_failed(self) -> None:
        self.state["failed"] = True

    def stop(self) -> None:
        """What Stop does to the board (spec 02 §6): active steps → stopped, log, caption."""
        for step, entry in self.state["steps"].items():
            if entry["state"] == "active":
                base = re.sub(r", .*$", "", entry["label"])
                self.finish(step, "stopped", base + copy.LABEL_STOPPED_SUFFIX)
        self.log(copy.LOG_STOP, "w")
        self.status(copy.STATUS_STOPPED)
        self.caption(copy.CAPTION_STOPPED)

    def finished(self, status: str, summary: str, *, gold: bool = False) -> None:
        """`run.finished`: always the last event of a run."""
        self.emit(
            "run.finished",
            status=status,
            summary=summary,
            summary_gold=gold,
            forged=list(self.state["forged"]),
            used=list(self.state["used"]),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add talos/web/demo_sources.py talos/web/schemas.py talos/web/board.py tests/web/test_demo_sources.py tests/web/test_schemas.py tests/web/test_board.py
git commit -m "[Feat]: Add the demo tool sources, API schemas and the run board"
```

---

### Task 4: EventTranslator and recorded chunk fixtures

**Files:**
- Create: `talos/web/translator.py`
- Create: `tests/web/chunks.py` (scenario builders, capture script, JSON round trip)
- Create (generated): `tests/web/fixtures/{forge_retry,vault,chat,exec_pause,exec_approve,key_pause,key_skip}.json`
- Test: `tests/web/test_translator.py`

**Interfaces:**
- Consumes: `Board`, `new_state`, `Event` (Task 3); `copy` (Task 2); `schemas.split_signature`, `schemas.vault_entry` (Task 3); `settings.FORGE_MAX_RETRIES`, `settings.SUBPROCESS_TIMEOUT`; `talos.vault.manager._AUTO_PRUNE_THRESHOLD`; stage 1 `emit()` chunk shapes and fields left `None` for this layer (`forge.code.note`, `call.args.caption`, `vault.saved.sub`).
- Produces:
  - `talos.web.translator`: `STREAM_MODES = ["updates", "custom", "messages", "tasks"]`; `EXEC_TOOLS`; `SignatureLookup = Callable[[str, str | None], str | None]`; `error_type(error: str | None) -> str`; `attempts_phrase(n: int) -> str`; class `EventTranslator(state: dict | None = None, *, signatures: SignatureLookup | None = None, max_attempts: int = settings.FORGE_MAX_RETRIES, timeout_s: int = settings.SUBPROCESS_TIMEOUT, prune_after: int = _AUTO_PRUNE_THRESHOLD)` with `.state: dict` (JSON-safe), `.pause: tuple[str, dict] | None`, `initial_state() -> dict` (static), `feed(chunk) -> list[Event]`, `resumed(kind: str, decision: str) -> list[Event]` (also clears `.pause`), `finish() -> list[Event]` (`answer.done`, then `run.finished`). The translator never emits `interrupt`, `interrupt.resolved`, `run.started`, `log.cmd` or `error`: the RunManager does (Task 6).
  - `tests.web.chunks`: `SCENARIOS: tuple[str, ...]`, `scenario_env(name)` (context manager yielding `{"inputs": [...], "vault": SkillManager}`), `capture(name) -> list[list]` (async), `load(name) -> list[tuple[tuple[str, ...], str, Any]]`, `shape(chunks) -> list[tuple]`, `dumps(chunks) -> str`, `main()`. Task 6 and Task 11 reuse `load` and `scenario_env`.

- [ ] **Step 1: Write the scenario builder and capture script**

Create `tests/web/chunks.py`:

```python
"""Recorded astream chunks for the translator tests.

There are no model keys in CI, so "recorded from real runs" means: the real
compiled Talos graph, driven with the same LLM fakes as
tests/test_orchestrator.py (canned Plan / ForgedTool / ResolvedArgs, and a
streaming fake chat model for the answer), streamed with the web app's
exact `astream` arguments. Every node, the tester subprocess, the smoke
gate, the vault and the checkpointer are real.

Regenerate the JSON after a LangGraph upgrade:

    uv run python -m tests.web.chunks

`test_translator.py::test_recorded_fixtures_match_a_live_capture` fails
when the stored fixtures drift from what the installed LangGraph emits.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    message_to_dict,
    messages_from_dict,
)
from langgraph.types import Command, Interrupt

from talos.agents import executor as exec_mod
from talos.agents import forger as forger_mod
from talos.agents import hitl as hitl_mod
from talos.agents import learner as learner_mod
from talos.agents import orchestrator as orch_mod
from talos.agents import planner as planner_mod
from talos.agents.executor import ResolvedArgs
from talos.agents.forger import ForgedTool
from talos.agents.planner import Plan, SubTask
from talos.graph import build_app
from talos.vault.manager import SkillManager
from talos.web.demo_sources import CAESAR, CAESAR_BAD_SOURCE, CAESAR_SOURCE, WEATHER, WEATHER_SOURCE
from talos.web.translator import STREAM_MODES

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIOS = ("forge_retry", "vault", "chat", "exec_pause", "exec_approve", "key_pause", "key_skip")

CAESAR_TESTS = """def test_encrypt_shifts_forward():
    assert caesar_cipher("TALOS AGENT", 7, "encrypt") == "AHSVZ HNLUA"


def test_decrypt_reverses_encrypt():
    result = caesar_cipher("AHSVZ HNLUA", 7, "decrypt")
    assert result == "TALOS AGENT", f"{result!r} != 'TALOS AGENT'"


def test_preserves_case_and_spaces():
    assert caesar_cipher("Hi there", 1, "encrypt") == "Ij uifsf"


def test_wraps_past_z():
    assert caesar_cipher("xyz", 3, "encrypt") == "abc"


def test_rejects_unknown_mode():
    try:
        caesar_cipher("a", 1, "rot")
    except ValueError:
        return
    raise AssertionError("no ValueError")
"""

WEATHER_TESTS = """def test_reads_temperature_from_response():
    import os

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"main": {"temp": 31.5}}

    os.environ["OPENWEATHERMAP_API_KEY"] = "test"
    requests.get = lambda *a, **k: _Resp()
    assert get_current_temperature("Mumbai") == 31.5


def test_raises_when_key_missing():
    import os

    os.environ.pop("OPENWEATHERMAP_API_KEY", None)
    try:
        get_current_temperature("Mumbai")
    except RuntimeError:
        return
    raise AssertionError("no RuntimeError")


def test_raises_on_unknown_city():
    import os

    class _Resp:
        status_code = 404

    os.environ["OPENWEATHERMAP_API_KEY"] = "test"
    requests.get = lambda *a, **k: _Resp()
    try:
        get_current_temperature("Nowhere")
    except ValueError:
        return
    raise AssertionError("no ValueError")
"""


class _Canned:
    """A structured-output model that returns canned objects in order."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def invoke(self, _messages: Any) -> Any:
        return self._items.pop(0)


def _forged(name: str, code: str, tests: str, signature: str, env: list[str] | None = None):
    return ForgedTool(
        name=name,
        description="d",
        keywords=[name],
        signature=signature,
        code=code + "\n",
        test_code=tests,
        needs_env_vars=env or [],
    )


def _caesar_signature() -> str:
    return f"{CAESAR['name']}({CAESAR['args']}) -> {CAESAR['ret']}"


@contextmanager
def scenario_env(name: str) -> Iterator[dict[str, Any]]:
    """Patch the LLM seams and the vault for one scenario.

    Yields:
        `{"inputs": [graph input, ...], "vault": SkillManager}`. Inputs after
        the first are resume Commands on the same thread.
    """
    saved: dict[tuple[Any, str], Any] = {}

    def patch(module: Any, attr: str, value: Any) -> None:
        saved[(module, attr)] = getattr(module, attr)
        setattr(module, attr, value)

    old_key = os.environ.pop(WEATHER["env"], None)
    with tempfile.TemporaryDirectory(prefix="talos_chunks_") as tmp:
        vault = SkillManager(vault_dir=Path(tmp) / "vault")
        for module in (planner_mod, exec_mod, learner_mod):
            patch(module, "_get_skill_manager", lambda: vault)
        patch(forger_mod, "should_research", lambda _task: False)
        patch(hitl_mod, "DOTENV_PATH", Path(tmp) / ".env")
        answers = {
            "forge_retry": '"TALOS AGENT" encrypted with a shift of 7 is AHSVZ HNLUA.',
            "vault": "It decrypts to TALOS AGENT.",
            "chat": "I plan, then forge tools.",
            "exec_pause": "The code prints 5050.",
            "exec_approve": "The code prints 5050.",
            "key_pause": "I couldn't get the temperature.",
            "key_skip": "I couldn't get the temperature.",
        }
        chat = GenericFakeChatModel(messages=iter([AIMessage(content=answers[name])]))
        patch(orch_mod, "_make_llm", lambda: chat)
        inputs: list[Any] = []
        query = {
            "forge_retry": 'Encrypt "TALOS AGENT" with a shift of 7.',
            "vault": 'Decrypt "AHSVZ HNLUA" with shift 7',
            "chat": "What can you do?",
            "exec_pause": "Run this Python code: print(sum(range(1, 101)))",
            "exec_approve": "Run this Python code: print(sum(range(1, 101)))",
            "key_pause": "Get the current temperature in Mumbai.",
            "key_skip": "Get the current temperature in Mumbai.",
        }[name]
        inputs.append({"messages": [HumanMessage(content=query)]})

        if name == "forge_retry":
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Encrypt text with a Caesar cipher",
                        needs="forge",
                        keywords=["caesar", "cipher", "encrypt"],
                        input_description="the quoted text, shift 7, encrypt",
                        input_schema={"text": "str", "shift": "int", "mode": "str"},
                        output_schema="str",
                        param_bindings={"text": "TALOS AGENT", "shift": 7, "mode": "encrypt"},
                    )
                ]
            )
            forger = _Canned(
                [
                    _forged("caesar_cipher", CAESAR_BAD_SOURCE, CAESAR_TESTS, _caesar_signature()),
                    _forged("caesar_cipher", CAESAR_SOURCE, CAESAR_TESTS, _caesar_signature()),
                ]
            )
            patch(forger_mod, "_make_llm", lambda: forger)
        elif name == "vault":
            vault.register(
                {
                    "name": "caesar_cipher",
                    "function": "caesar_cipher",
                    "description": CAESAR["description"],
                    "keywords": CAESAR["keywords"],
                    "signature": _caesar_signature(),
                    "created_at": "2026-09-30T10:00:00+00:00",
                },
                CAESAR_SOURCE + "\n",
            )
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Decrypt with the Caesar cipher tool",
                        needs="vault",
                        tool_hint="caesar_cipher",
                        keywords=["caesar", "cipher", "decrypt"],
                        input_description="quoted text, shift 7, decrypt",
                    )
                ]
            )
            resolver = _Canned(
                [
                    ResolvedArgs(
                        args=[], kwargs={"text": "AHSVZ HNLUA", "shift": 7, "mode": "decrypt"}
                    )
                ]
            )
            patch(exec_mod, "_make_resolver_llm", lambda: resolver)
        elif name == "chat":
            plan = Plan(sub_tasks=[])
        elif name in ("exec_pause", "exec_approve"):
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Run the Python code",
                        needs="primitive",
                        tool_hint="python_exec",
                        keywords=["python"],
                        input_description="the code after the colon",
                    )
                ]
            )
            code = "print(sum(range(1, 101)))"
            resolver = _Canned([ResolvedArgs(args=[], kwargs={"code": code})] * 2)
            patch(exec_mod, "_make_resolver_llm", lambda: resolver)
            if name == "exec_approve":
                inputs.append(
                    Command(resume={"approved": True, "args": [], "kwargs": {"code": code}})
                )
        else:  # key_pause, key_skip
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Get the current temperature for a city from OpenWeatherMap",
                        needs="forge",
                        keywords=["weather", "temperature"],
                        input_description="the city",
                        input_schema={"city": "str"},
                        output_schema="float",
                        param_bindings={"city": "Mumbai"},
                    )
                ]
            )
            forger = _Canned(
                [
                    _forged(
                        WEATHER["name"],
                        WEATHER_SOURCE,
                        WEATHER_TESTS,
                        f"{WEATHER['name']}({WEATHER['args']}) -> {WEATHER['ret']}",
                        env=[WEATHER["env"]],
                    )
                ]
            )
            patch(forger_mod, "_make_llm", lambda: forger)
            if name == "key_skip":
                inputs.append(Command(resume="skip"))

        planner = _Canned([plan])
        patch(planner_mod, "_make_llm", lambda: planner)
        try:
            yield {"inputs": inputs, "vault": vault}
        finally:
            for (module, attr), value in saved.items():
                setattr(module, attr, value)
            os.environ.pop(WEATHER["env"], None)
            if old_key is not None:
                os.environ[WEATHER["env"]] = old_key


async def capture(name: str) -> list[list[Any]]:
    """Run one scenario on the real graph and return its chunks (last input only
    for resume scenarios: `exec_approve` and `key_skip` are the post-resume half)."""
    with scenario_env(name) as env:
        app = build_app()
        config = {"configurable": {"thread_id": f"capture-{name}"}}
        chunks: list[list[Any]] = []
        for graph_input in env["inputs"]:
            chunks = []
            async for ns, mode, data in app.astream(
                graph_input, config, stream_mode=STREAM_MODES, subgraphs=True
            ):
                chunks.append([list(ns), mode, _slim(mode, data)])
        return chunks


def _slim(mode: str, data: Any) -> Any:
    """Keep what the translator reads; drop task inputs/results (whole state copies)."""
    if mode == "tasks":
        keep = {"id", "name", "error", "interrupts", "triggers"}
        out = {k: v for k, v in data.items() if k in keep}
        if "input" in data:
            out["input"] = None
        return out
    return data


# ---- JSON round trip ----------------------------------------------------------------


def _encode(obj: Any) -> Any:
    if isinstance(obj, BaseMessage):
        return {"__message__": message_to_dict(obj)}
    if isinstance(obj, Interrupt):
        return {"__lg_interrupt__": {"value": obj.value, "id": obj.id}}
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=repr)
    return repr(obj)


def _decode(obj: dict[str, Any]) -> Any:
    if "__message__" in obj:
        return messages_from_dict([obj["__message__"]])[0]
    if "__lg_interrupt__" in obj:
        return Interrupt(value=obj["__lg_interrupt__"]["value"], id=obj["__lg_interrupt__"]["id"])
    return obj


def dumps(chunks: list[list[Any]]) -> str:
    return json.dumps(chunks, default=_encode, indent=1) + "\n"


def load(name: str) -> list[tuple[tuple[str, ...], str, Any]]:
    """Load a fixture as `(namespace, mode, data)` chunks with real message objects."""
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"), object_hook=_decode)
    out = []
    for ns, mode, data in raw:
        if mode == "messages":
            data = (data[0], data[1])
        elif mode == "updates" and "__interrupt__" in data:
            data = {"__interrupt__": tuple(data["__interrupt__"])}
        out.append((tuple(ns), mode, data))
    return out


_TASK_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def shape(chunks: list[Any]) -> list[tuple[Any, ...]]:
    """What must stay stable across captures: namespace kind, mode, and the keys."""
    out = []
    for ns, mode, data in chunks:
        where = tuple(_TASK_ID.sub("*", str(part)) for part in ns)
        if mode == "tasks":
            key: Any = (data.get("name"), "input" in data)
        elif mode == "custom":
            key = (data.get("type"), tuple(sorted(data.get("data", {}))))
        elif mode == "updates":
            key = tuple(sorted(data))
        else:
            key = (type(data[0]).__name__, data[1].get("langgraph_node"))
        out.append((where, mode, key))
    return out


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for name in SCENARIOS:
        chunks = asyncio.run(capture(name))
        (FIXTURES / f"{name}.json").write_text(dumps(chunks), encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the failing translator tests**

Create `tests/web/test_translator.py`:

```python
"""EventTranslator on recorded chunks from the real graph (spec 02 §11)."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.types import Interrupt

from talos.web.translator import STREAM_MODES, EventTranslator, error_type
from tests.web import chunks

CAESAR_SIG = "caesar_cipher(text: str, shift: int, mode: str) -> str"


def lookup(needs: str, hint: str | None) -> str | None:
    return {
        "caesar_cipher": CAESAR_SIG,
        "python_exec": "python_exec(code: str, timeout: int | None = None) -> dict",
    }.get(hint or "")


def run(*names: str, resume: tuple[str, str] | None = None):
    """Translate fixtures in order; between them, the user answers `resume`."""
    tr = EventTranslator(signatures=lookup, max_attempts=3, timeout_s=10, prune_after=2)
    events = []
    for i, name in enumerate(names):
        if i:
            assert tr.pause is not None
            events += tr.resumed(*resume)
        for chunk in chunks.load(name):
            events += tr.feed(chunk)
            json.dumps(tr.state)  # always storable as runs.translator_state
    if tr.pause is None:
        events += tr.finish()
    return tr, events


def types(events) -> list[str]:
    """Event types, with runs of answer.delta collapsed to one."""
    out: list[str] = []
    for type_, _ in events:
        if not (type_ == "answer.delta" and out and out[-1] == "answer.delta"):
            out.append(type_)
    return out


def first(events, type_: str, **match):
    return next(d for t, d in events if t == type_ and all(d.get(k) == v for k, v in match.items()))


def test_stream_modes_are_the_four_the_translator_reads():
    assert STREAM_MODES == ["updates", "custom", "messages", "tasks"]


def test_forge_with_retry_produces_the_demo_sequence():
    tr, events = run("forge_retry")
    assert types(events) == [
        "node.started", "caption", "talos.status",  # planner
        "plan.ready", "strip.set", "node.finished", "log.line", "caption",
        "log.status", "log.line", "link.flow",  # Forging, vault no match, planner→forger
        "node.started", "talos.status", "caption", "log.line", "forge.code",  # attempt 1
        "node.finished", "link.flow", "node.started", "caption", "log.line",  # tester
        "log.pop", "forge.tests", "log.line", "log.line", "forge.attempt", "talos.status",
        "node.finished", "node.started", "caption", "log.line", "forge.code",  # attempt 2
        "node.finished", "link.flow", "node.started", "caption", "log.line",
        "log.pop", "forge.tests", "log.line",
        "caption", "forge.smoke", "log.line", "forge.attempt",  # smoke settles attempt 2
        "node.finished", "link.flow",  # tester → human
        "node.finished", "caption", "link.flow",  # human skipped
        "node.started", "caption",  # learn
        "node.finished", "log.line", "vault.saved", "link.flow",
        "node.started", "talos.status", "caption", "call.args", "call.result",
        "node.finished", "log.line",  # executor done
        "link.flow", "node.started", "log.status", "caption",  # into Answer
        "answer.delta", "node.finished", "answer.done", "run.finished",
    ]  # fmt: skip
    assert first(events, "strip.set")["subtask"]["label"] == "Sub-task 1 of 1, needs a new tool"
    assert first(
        events,
        "caption",
        html=("1 sub-task. Nothing in the vault matches, so it needs a new tool."),
    )
    code1, code2 = [d for t, d in events if t == "forge.code"]
    assert (code1["attempt"], code1["changed"], code1["note"]) == (1, None, None)
    assert (code2["attempt"], code2["changed"]) == (2, 48)
    assert code2["note"] == "Line 48 is new in attempt 2."
    assert first(events, "log.line", text="4 of 5 passed, retrying")["tone"] == "g"
    assert first(events, "log.line", tone="sub")["text"] == "test_decrypt_reverses_encrypt"
    assert first(events, "forge.attempt", attempt=1) == {
        "attempt": 1,
        "ok": False,
        "detail": "test_decrypt_reverses_encrypt\nAssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'",
    }
    assert first(events, "forge.attempt", attempt=2)["ok"] is True
    assert first(
        events,
        "caption",
        html=(
            '<span class="gold">Attempt 2 of 3.</span> Running 5 tests in a subprocess,'
            " 10-second limit."
        ),
    )
    saved = first(events, "vault.saved")
    assert saved["tool"]["name"] == "caesar_cipher"
    assert saved["tool"]["args"] == "text: str, shift: int, mode: str"
    assert saved["tool"]["ret"] == "str"
    assert saved["tool"]["web"] is False
    assert first(events, "call.args")["caption"] == "Filled in by the Executor"
    assert first(events, "answer.done") == {
        "html": "&quot;TALOS AGENT&quot; encrypted with a shift of 7 is AHSVZ HNLUA.",
        "note": None,
        "chips": [{"kind": "forged", "text": "Forged caesar_cipher"}],
    }
    assert events[-1] == (
        "run.finished",
        {
            "status": "done",
            "summary": "1 tool forged, 2 attempts",
            "summary_gold": True,
            "forged": ["caesar_cipher"],
            "used": ["caesar_cipher"],
        },
    )
    assert tr.state["failed"] is False


def test_vault_run_marks_vault_and_skip_then_reuses():
    _, events = run("vault")
    strip = first(events, "strip.set")
    assert strip["variant"] == "vault"
    assert strip["sig"] == {
        "name": "caesar_cipher",
        "args": "text: str, shift: int, mode: str",
        "ret": "str",
    }
    assert first(
        events,
        "caption",
        html=(
            'The Planner matched <span class="mono">caesar_cipher</span> on the keywords caesar,'
            " cipher and decrypt. Nothing will be written or tested this time."
        ),
    )
    flows = [(d["from"], d["to"]) for t, d in events if t == "link.flow"]
    assert flows == [
        ("planner", "vault"),
        ("vault", "skip"),
        ("skip", "executor"),
        ("executor", "answer"),
    ]
    assert first(events, "log.status", text="0 tools forged")["tone"] == "warm"
    assert first(events, "caption", html="Done from the vault. The forge sub-graph never ran.")
    assert first(events, "answer.done")["chips"] == [
        {"kind": "reused", "text": "Reused caesar_cipher from the vault"}
    ]
    assert events[-1][1]["summary"] == "0 tools forged"
    assert events[-1][1]["used"] == ["caesar_cipher"]


def test_chat_run_goes_planner_to_answer():
    _, events = run("chat")
    assert types(events) == [
        "node.started", "caption", "talos.status",
        "plan.ready", "strip.set", "node.finished", "log.line", "caption", "log.status",
        "link.flow", "node.started", "answer.delta", "node.finished",
        "answer.done", "run.finished",
    ]  # fmt: skip
    assert first(events, "strip.set") == {
        "variant": "chat",
        "subtask": {"index": 0, "total": 0, "label": "Conversational"},
        "sig": None,
    }
    assert first(events, "link.flow") == {"from": "planner", "to": "answer"}
    assert "".join(d["text"] for t, d in events if t == "answer.delta") == (
        "I plan, then forge tools."
    )
    assert events[-1][1]["summary"] == "Answered directly"


def test_a_run_that_ends_in_an_interrupt_has_no_answer_and_a_pause():
    tr, events = run("exec_pause")
    assert tr.pause is not None
    kind, value = tr.pause
    assert kind == "confirm_exec"
    assert value["kwargs"] == {"code": "print(sum(range(1, 101)))"}
    assert types(events)[-5:] == [
        "node.started", "caption", "log.line", "log.status", "talos.status",
    ]  # fmt: skip
    assert first(events, "node.started", step="executor", label="Executor, waiting for you")
    assert first(events, "log.line", text="paused for approval")["caret"] is True
    assert not any(t in ("answer.done", "run.finished", "call.args") for t, _ in events)


def test_approved_exec_continues_on_the_same_translator():
    tr, events = run("exec_pause", "exec_approve", resume=("confirm_exec", "approve"))
    _, paused = run("exec_pause")
    after = events[len(paused) :]
    assert [t for t, _ in after][:3] == ["log.pop", "log.line", "call.args"]
    assert first(events, "log.line", text="running")["caret"] is True
    assert first(events, "call.args")["caption"] == "Written by the Executor"
    # planner, executor, executor (waiting for you), answer
    assert types(events).count("node.started") == 4
    assert events[-1][1]["status"] == "done"
    assert events[-1][1]["summary"] == "Built-in, approved"


def test_declined_exec_finishes_declined():
    tr = EventTranslator()
    for chunk in chunks.load("exec_pause"):
        tr.feed(chunk)
    events = tr.resumed("confirm_exec", "decline")
    events += tr.feed(((), "tasks", {"name": "executor", "input": None}))
    events += tr.feed(((), "custom", {"type": "call.error", "data": {
        "error": "declined by user", "when": "declined"}}))  # fmt: skip
    events += tr.feed(((), "tasks", {"name": "orchestrator_out", "input": None}))
    events += tr.finish()
    assert first(events, "node.finished", step="executor")["label"] == "Executor, declined"
    assert first(events, "log.line", text="declined by you")["tone"] == "w"
    assert first(events, "log.status", text="Not run")
    assert first(events, "caption", html="Nothing ran. The sub-task is recorded as declined.")
    assert events[-1][1]["status"] == "declined"
    assert events[-1][1]["summary"] == "Declined, nothing ran"


def test_missing_key_pause_then_skip_runs_and_fails_without_the_key():
    tr, events = run("key_pause", "key_skip", resume=("missing_api_key", "skip"))
    assert first(
        events,
        "caption",
        html=(
            'Human check paused the graph. <span class="mono">get_current_temperature</span>'
            ' needs <span class="mono">OPENWEATHERMAP_API_KEY</span>.'
        ),
    )
    assert first(events, "node.finished", step="human")["label"] == "Human check, skipped"
    assert first(events, "log.line", text="failed, RuntimeError")
    assert first(events, "log.status", text="1 step failed")["tone"] == "alert"
    assert first(events, "log.line", text="1 failure in a row")
    assert first(events, "vault.saved")["tool"]["web"] is True
    assert first(events, "answer.done")["chips"] == [
        {"kind": "failed", "text": "get_current_temperature raised a RuntimeError"}
    ]
    assert events[-1][1]["summary"] == "Failed, 1 failure in a row"
    assert tr.state["failed"] is True


def test_missing_key_saved_says_so():
    tr = EventTranslator()
    for chunk in chunks.load("key_pause"):
        tr.feed(chunk)
    events = tr.resumed("missing_api_key", "save")
    assert [t for t, _ in events] == [
        "log.pop", "log.line", "node.finished", "caption", "log.status", "link.flow",
    ]  # fmt: skip
    assert events[3][1]["html"] == (
        'Saved <span class="mono">OPENWEATHERMAP_API_KEY</span> to .env. Talos won\'t ask again.'
    )


def test_subgraph_custom_chunks_keep_their_namespace_and_shape():
    """Pins the LangGraph chunk shape the translator relies on."""
    custom = [c for c in chunks.load("forge_retry") if c[1] == "custom"]
    inner = [c for c in custom if c[0]]
    assert inner, "forge events must come from inside the forge sub-graph"
    for ns, mode, data in inner:
        assert len(ns) == 1 and ns[0].startswith("forge_subgraph:")
        assert set(data) == {"type", "data"}
    assert {c[2]["type"] for c in inner} == {"forge.code", "forge.tests", "forge.smoke"}
    outer = {c[2]["type"] for c in custom if not c[0]}
    assert outer == {"vault.saved", "call.args", "call.result"}


@pytest.mark.parametrize("name", chunks.SCENARIOS)
async def test_recorded_fixtures_match_a_live_capture(name):
    live = [(tuple(ns), mode, data) for ns, mode, data in await chunks.capture(name)]
    assert chunks.shape(live) == chunks.shape(chunks.load(name))


def test_forger_failure_and_smoke_without_a_call_are_tolerated():
    tr = EventTranslator()
    tr.feed(((), "updates", {"planner": {"plan": {"sub_tasks": [
        {"id": 1, "action": "x", "needs": "forge"}]}}}))  # fmt: skip
    ns = ("forge_subgraph:abc",)
    tr.feed((ns, "tasks", {"name": "forge", "input": None}))
    code = {"tool": "", "attempt": 1, "file": "tool.py", "lines": [], "changed": 1, "note": None}
    events = tr.feed((ns, "custom", {"type": "forge.code", "data": code}))
    assert first(events, "forge.code")["tool"] == ""
    tr.feed((ns, "updates", {"forge": {"forged_tool": {"name": "", "code": ""}}}))
    tr.feed((ns, "tasks", {"name": "test", "input": None}))
    tests = {"tool": "", "attempt": 1, "results": []}
    tr.feed((ns, "custom", {"type": "forge.tests", "data": tests}))
    events = tr.feed((ns, "updates", {"test": {"test_result": {
        "passed": False, "results": [], "n_total": 0, "timed_out": False,
        "error": "Forger produced no code or no test_code."}}}))  # fmt: skip
    assert first(events, "forge.attempt")["detail"] == "Forger produced no code or no test_code."
    assert first(events, "log.line", text="0 of 0 passed, retrying")
    events = tr.feed((ns, "custom", {"type": "forge.smoke", "data": {
        "call": None, "result": None, "passed": False}}))  # fmt: skip
    assert first(events, "forge.smoke")["call"] is None


def test_timed_out_tests_explain_themselves():
    tr = EventTranslator()
    tr.state["attempt"] = 3
    events = tr.feed((("forge_subgraph:x",), "updates", {"test": {"test_result": {
        "passed": False, "results": [], "n_total": 0, "timed_out": True,
        "error": "Subprocess timed out (likely infinite loop)."}}}))  # fmt: skip
    detail = first(events, "forge.attempt")["detail"]
    assert detail == "Subprocess timed out (likely infinite loop)."
    assert first(events, "log.line", text="0 of 0 passed")


def test_answer_without_streamed_tokens_still_arrives():
    tr = EventTranslator()
    meta = {"langgraph_node": "orchestrator_out"}
    assert tr.feed(((), "messages", (AIMessage(content="Hello there."), meta))) == [
        ("answer.delta", {"text": "Hello there."})
    ]
    assert tr.feed(
        ((), "updates", {"orchestrator_out": {"messages": [AIMessage(content="Hello there.")]}})
    ) == [  # fmt: skip
        ("node.finished", {"step": "answer", "status": "answer"})
    ]


def test_tokens_from_other_nodes_are_ignored():
    tr = EventTranslator()
    chunk = AIMessageChunk(content="{json plan}")
    assert tr.feed(((), "messages", (chunk, {"langgraph_node": "planner"}))) == []


def test_interrupt_objects_and_error_types():
    tr = EventTranslator()
    value = {"type": "missing_api_key", "env_var": "X_API_KEY", "tool_name": "t"}
    tr.feed(((), "updates", {"__interrupt__": (Interrupt(value=value, id="1"),)}))
    assert tr.pause[0] == "missing_api_key"
    assert error_type("TypeError: shift must be an int, got str") == "TypeError"
    assert error_type("requests.exceptions.HTTPError: 404") == "HTTPError"
    assert error_type("dispatch error: Unknown primitive") == "error"


def test_answer_html_is_escaped():
    tr = EventTranslator()
    meta = {"langgraph_node": "orchestrator_out"}
    tr.feed(((), "messages", (AIMessageChunk(content="<script>x</script> & <b>"), meta)))
    done = dict(tr.finish())["answer.done"]
    assert done["html"] == "&lt;script&gt;x&lt;/script&gt; &amp; &lt;b&gt;"


def test_multi_subtask_plan_resets_the_strip_per_subtask():
    tr = EventTranslator(max_attempts=3)
    plan = {
        "sub_tasks": [
            {"id": 1, "action": "read", "needs": "primitive", "tool_hint": "web_read"},
            {
                "id": 2,
                "action": "slug",
                "needs": "vault",
                "tool_hint": "slugify",
                "depends_on": [1],
            },
        ],
        "verdict": "feasible",
    }
    events = tr.feed(((), "updates", {"planner": {"plan": plan}}))
    first = next(d for t, d in events if t == "strip.set")
    assert first["variant"] == "primitive"
    assert first["subtask"] == {
        "index": 1,
        "total": 2,
        "label": "Sub-task 1 of 2, built-in primitive",
    }
    assert ("log.line", {"label": "plan", "text": "2 sub-tasks", "tone": "plain"}) in events

    events = tr.feed(((), "updates", {"advance": {"current_sub_task": plan["sub_tasks"][1]}}))
    assert events[0] == ("subtask.started", {"index": 2, "total": 2})
    assert events[1][0] == "strip.set"
    assert events[1][1]["variant"] == "vault"
    assert events[1][1]["subtask"]["label"] == "Sub-task 2 of 2, found in the vault"
    assert events[2] == ("node.finished", {"step": "planner", "status": "done"})
    assert ("log.line", {"label": "vault", "text": "slugify", "tone": "plain"}) in events
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_translator.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'talos.web.translator'`.

- [ ] **Step 4: Implement the translator**

Create `talos/web/translator.py`:

```python
"""EventTranslator: raw LangGraph stream chunks → contract events (overview §4).

Pure: no I/O. `GraphDriver` (runner.py) feeds it every chunk of

    graph.astream(..., stream_mode=STREAM_MODES, subgraphs=True)

Each chunk is `(namespace, mode, data)`. `namespace` is `()` for the main
graph and `("forge_subgraph:<task id>",)` inside the forge sub-graph.

- "tasks": `{"id", "name", "input", "triggers"}` when a node starts (the
  finish form, with "result", is ignored). This is how a step becomes
  active before its model call returns.
- "updates": `{node: partial_state}` when a node finishes; `{"__interrupt__":
  (Interrupt, ...)}` when the graph pauses.
- "custom": `{"type": ..., "data": {...}}` from `talos.events.emit()`.
- "messages": `(message_chunk, metadata)`; only `orchestrator_out` counts.

The translator's state (strip, attempt counter, tools, answer so far) is a
JSON dict that survives a pause and an app restart. It never holds `seq`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from typing import Any

from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD
from talos.web import copy
from talos.web.board import Board, Event, new_state
from talos.web.schemas import split_signature, vault_entry

STREAM_MODES = ["updates", "custom", "messages", "tasks"]

EXEC_TOOLS = frozenset({"python_exec", "shell_exec"})
_TEST_DEF = re.compile(r"^def test_", re.M)
_ERROR_TYPE = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b")

# (needs, tool_hint) → the tool's signature text, e.g. "f(a: int) -> str".
SignatureLookup = Callable[[str, str | None], str | None]


def error_type(error: str | None) -> str:
    """`"TypeError: shift must be an int"` → `"TypeError"`; otherwise `"error"`."""
    match = _ERROR_TYPE.match(error or "")
    return match.group(1).rsplit(".", 1)[-1] if match else "error"


def attempts_phrase(n: int) -> str:
    return "1 attempt" if n == 1 else f"{n} attempts"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return ""


class EventTranslator:
    """Turns stream chunks into contract events, keeping per-run UI state.

    Args:
        state: Saved state from a previous task of the same run, or None.
        signatures: Looks up a tool's signature for the strip header.
        max_attempts: Forge attempts allowed (TALOS_FORGE_MAX_RETRIES).
        timeout_s: Tester subprocess limit (TALOS_SUBPROCESS_TIMEOUT).
        prune_after: Failures in a row before a vault tool is removed.
    """

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        *,
        signatures: SignatureLookup | None = None,
        max_attempts: int = settings.FORGE_MAX_RETRIES,
        timeout_s: int = settings.SUBPROCESS_TIMEOUT,
        prune_after: int = _AUTO_PRUNE_THRESHOLD,
    ) -> None:
        self.state = state if state is not None else self.initial_state()
        self.board = Board(self.state)
        self.signatures = signatures
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.prune_after = prune_after
        self.pause: tuple[str, dict[str, Any]] | None = None

    @staticmethod
    def initial_state() -> dict[str, Any]:
        """Fresh state for a new run."""
        return {
            **new_state(),
            "plan": [],
            "index": 0,
            "attempt": 0,
            "tests_total": 0,
            "tool": None,
            "code": [],
            "env_vars": [],
            "pending_attempt": None,
            "test_results": [],
            "intro_pending": False,
            "exec_caption_pending": False,
            "resuming_executor": False,
            "human": "none",
            "approval": "none",
            "forge_failed": False,
            "failure": None,
            "answer": "",
            "answer_streamed": False,
        }

    # ---- public API -------------------------------------------------------------

    def feed(self, chunk: tuple[Any, str, Any] | list[Any]) -> list[Event]:
        """Translate one `(namespace, mode, data)` chunk."""
        namespace, mode, data = chunk
        inner = bool(namespace)
        if mode == "tasks":
            if isinstance(data, Mapping) and "input" in data:
                self._task_started(inner, str(data.get("name")))
        elif mode == "custom":
            if isinstance(data, Mapping):
                self._custom(str(data.get("type")), dict(data.get("data") or {}))
        elif mode == "updates":
            for node, update in (data or {}).items():
                if node == "__interrupt__":
                    self._interrupted(update)
                else:
                    self._updated(inner, node, update if isinstance(update, Mapping) else {})
        elif mode == "messages":
            message, metadata = data
            self._message(message, metadata or {})
        return self.board.drain()

    def resumed(self, kind: str, decision: str) -> list[Event]:
        """Copy for the moment the user answers a pause (before the graph resumes)."""
        self.pause = None
        b = self.board
        b.pop()
        if kind == "missing_api_key":
            env = (self.state["env_vars"] or [""])[0]
            if decision == "save":
                self.state["human"] = "saved"
                b.log(copy.LOG_CHECK_SAVED)
                b.finish("human", "done")
                b.caption(copy.CAPTION_HUMAN_SAVED.format(env=env))
            else:
                self.state["human"] = "skipped"
                b.log(copy.LOG_CHECK_SKIPPED)
                b.finish("human", "done", copy.LABEL_HUMAN_SKIPPED)
                b.caption(copy.CAPTION_HUMAN_SKIPPED)
            b.status(copy.STATUS_FORGING, gold=True)
            b.flow("human", "learn")
        else:
            self.state["resuming_executor"] = True
            if decision == "approve":
                self.state["approval"] = "approved"
                b.log(copy.LOG_EXEC_RUNNING, "g", caret=True)
            else:
                self.state["approval"] = "declined"
        return b.drain()

    def finish(self) -> list[Event]:
        """`answer.done` then `run.finished`, once the stream has ended normally."""
        s, b = self.state, self.board
        failure = s["failure"]
        if failure:  # the demo shows only the failure chip, even after a forge
            text = copy.CHIP_FAILED.format(tool=failure["tool"], error_type=failure["error_type"])
            chips = [{"kind": "failed", "text": text}]
        else:
            chips = [
                {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=t)} for t in s["forged"]
            ]
            chips += [
                {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=t)}
                for t in s["used"]
                if t not in s["forged"]
            ]
        b.emit("answer.done", html=html.escape(s["answer"]), note=None, chips=chips)
        summary, gold = self._summary()
        b.finished("declined" if s["approval"] == "declined" else "done", summary, gold=gold)
        return b.drain()

    # ---- tasks (a node starts) -----------------------------------------------------

    def _task_started(self, inner: bool, name: str) -> None:
        s, b = self.state, self.board
        if inner:
            if name == "forge":
                self._settle_attempt(True)
                s["attempt"] += 1
                if s["attempt"] == 1:
                    b.start("forger")
                    if s["tool"]:
                        self._forge_intro()
                    else:
                        s["intro_pending"] = True
                else:
                    b.finish("tester", "forge")
                    b.start("forger")
                    b.caption(
                        copy.CAPTION_FORGER_RETRY.format(n=s["attempt"], max=self.max_attempts)
                    )
                    b.log(copy.LOG_FORGE_RETRY, "g", n=s["attempt"])
            elif name == "test":
                b.finish("forger", "forge")
                b.flow("forger", "tester")
                b.start("tester")
                b.caption(
                    copy.CAPTION_TESTER.format(
                        n=s["attempt"],
                        max=self.max_attempts,
                        k=s["tests_total"],
                        timeout=self.timeout_s,
                    )
                )
                b.log(copy.LOG_TEST_RUNNING, "g", caret=True)
            return
        if name == "planner":
            b.start("planner")
            b.caption(copy.CAPTION_PLANNING)
            b.talos(copy.TALOS_PLANNING)
        elif name == "learn":
            b.start("learn")
            b.caption(copy.CAPTION_LEARN)
        elif name == "executor":
            if s["resuming_executor"]:
                s["resuming_executor"] = False
                return
            sub = self._subtask()
            tool = s["tool"] or sub.get("tool_hint") or "tool"
            b.start("executor")
            b.talos(copy.TALOS_RUNNING.format(tool=tool))
            if sub.get("tool_hint") in EXEC_TOOLS:
                s["exec_caption_pending"] = True  # paused or auto-approved decides
            else:
                b.caption(copy.CAPTION_EXECUTOR)
        elif name == "orchestrator_out":
            self._before_answer()

    # ---- custom events (facts from nodes) -------------------------------------------

    def _custom(self, type_: str, data: dict[str, Any]) -> None:
        s, b = self.state, self.board
        if type_ == "forge.code":
            if data.get("tool"):
                s["tool"] = data["tool"]
            s["code"] = list(data.get("lines") or [])
            if s["intro_pending"] and s["tool"]:
                self._forge_intro()
            changed = data.get("changed")
            if int(data.get("attempt") or s["attempt"]) > 1 and changed:
                data["note"] = copy.NOTE_CHANGED_LINE.format(line=changed, n=s["attempt"])
            b.emit("forge.code", **data)
        elif type_ == "forge.tests":
            s["test_results"] = list(data.get("results") or [])
            b.pop()
            b.emit("forge.tests", **data)
        elif type_ == "forge.smoke":
            b.caption(copy.CAPTION_SMOKE)  # only sent when the gate ran (not skipped)
            b.emit("forge.smoke", **data)
            if data.get("passed"):
                b.log(copy.LOG_SMOKE, result=data.get("result") or "")
                self._settle_attempt(True)
            else:
                b.emit("log.line", label="smoke", text=copy.new("LOG_SMOKE_FAILED"), tone="w")
                self._settle_attempt(False, f"Smoke test failed: {data.get('call') or 'no call'}")
        elif type_ == "vault.saved":
            entry = data.get("tool") or {}
            tool = str(entry.get("name") or s["tool"] or "")
            b.finish("learn", "done")
            b.log(copy.LOG_LEARN)
            b.emit(
                "vault.saved",
                tool=vault_entry(entry, "\n".join(s["code"])).model_dump(),
                sub=data.get("sub") or copy.SAVED_SUB.format(what=tool),
            )
            b.flow("learn", "executor")
            b.add_forged(tool)
        elif type_ == "call.args":
            tool = str(data.get("tool") or "")
            if s["variant"] in ("vault", "forge"):
                b.add_used(tool)
            if s["exec_caption_pending"]:
                s["exec_caption_pending"] = False
                b.caption(copy.CAPTION_EXEC_AUTO)
            args = data.get("args") or []
            if tool in EXEC_TOOLS:
                caption = copy.ARGS_CAPTION_CODE
            elif not args:
                caption = copy.ARGS_CAPTION_NONE
            else:
                caption = copy.ARGS_CAPTION
            b.emit("call.args", **{**data, "caption": data.get("caption") or caption})
        elif type_ == "call.result":
            if s["approval"] == "approved":
                b.pop()
            b.emit("call.result", **data)
            b.finish("executor", "done", "Executor")
            b.log(copy.LOG_EXEC_DONE, "w")
        elif type_ == "call.error":
            b.emit("call.error", **data)
            if data.get("when") == "declined":
                b.finish("executor", "fail", copy.LABEL_EXEC_DECLINED)
                b.log(copy.LOG_EXEC_DECLINED, "w")
                b.status(copy.STATUS_NOT_RUN)
                return
            if s["approval"] == "approved":
                b.pop()
            kind = error_type(data.get("error"))
            tool = s["tool"] or self._subtask().get("tool_hint") or "tool"
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type=kind)
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            s["failure"] = {"tool": tool, "error_type": kind, "streak": None, "pruned": False}
        elif type_ == "vault.failure":
            if data.get("pruned"):
                b.log(copy.LOG_VAULT_REMOVED, prune=self.prune_after)
            else:
                b.log(copy.LOG_VAULT_STREAK, streak=data.get("streak"))
            b.emit("vault.failure", **data)
            if s["failure"] is not None:
                s["failure"]["streak"] = data.get("streak")
                s["failure"]["pruned"] = bool(data.get("pruned"))
        else:
            b.emit(type_, **data)

    # ---- updates (a node finished) ----------------------------------------------------

    def _updated(self, inner: bool, node: str, update: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        if inner:
            if node == "forge":
                forged = update.get("forged_tool") or {}
                s["tool"] = forged.get("name") or s["tool"]
                s["tests_total"] = len(_TEST_DEF.findall(forged.get("test_code") or ""))
                s["env_vars"] = list(forged.get("needs_env_vars") or [])
            elif node == "test":
                self._tests_decided(update.get("test_result") or {})
            return
        if node == "planner":
            self._planned(update.get("plan") or {})
        elif node == "forge_subgraph":
            self._forge_done(update)
        elif node == "hitl_check":
            if s["human"] in ("saved", "skipped"):
                return
            if s["env_vars"]:
                b.finish("human", "skip")
                b.caption(copy.CAPTION_HUMAN_KEY_SET.format(env=s["env_vars"][0]))
                b.log(copy.LOG_CHECK_KEY_SET)
            else:
                b.finish("human", "skip")
                b.caption(copy.CAPTION_HUMAN_SKIP)
            b.flow("human", "learn")
        elif node == "advance":
            s["index"] += 1
            b.emit("subtask.started", index=s["index"] + 1, total=len(s["plan"]))
            self._begin_subtask()
        elif node == "orchestrator_out":
            messages = update.get("messages") or []
            if messages:
                text = _content_text(getattr(messages[-1], "content", ""))
                if not s["answer_streamed"] and text:
                    b.emit("answer.delta", text=text)
                    s["answer_streamed"] = True
                s["answer"] = text or s["answer"]
            b.finish("answer", "answer")

    def _interrupted(self, interrupts: Any) -> None:
        s, b = self.state, self.board
        first = interrupts[0] if interrupts else None
        value = getattr(first, "value", first)
        if not isinstance(value, Mapping):
            return
        value = dict(value)
        kind = str(value.get("type"))
        self.pause = (kind, value)
        if kind == "missing_api_key":
            env = str(value.get("env_var") or "")
            if env and env not in s["env_vars"]:
                s["env_vars"] = [env, *s["env_vars"]]
            elif env:
                s["env_vars"] = [env, *[v for v in s["env_vars"] if v != env]]
            s["human"] = "waiting"
            b.start("human")
            b.caption(
                copy.CAPTION_HUMAN_WAIT.format(tool=value.get("tool_name") or s["tool"], env=env)
            )
            b.log(copy.LOG_CHECK_WAITING, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_NEEDS_KEY)
        elif kind == "confirm_exec":
            s["approval"] = "waiting"
            s["exec_caption_pending"] = False
            b.start("executor", copy.LABEL_EXEC_WAITING)
            b.caption(copy.CAPTION_EXEC_PAUSED.format(tool=value.get("tool") or "python_exec"))
            b.log(copy.LOG_EXEC_PAUSED, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_APPROVE)

    # ---- messages (answer tokens) -------------------------------------------------------

    def _message(self, message: Any, metadata: Mapping[str, Any]) -> None:
        if metadata.get("langgraph_node") != "orchestrator_out":
            return
        s = self.state
        text = _content_text(getattr(message, "content", ""))
        if type(message).__name__.endswith("Chunk"):
            if text:
                s["answer"] += text
                s["answer_streamed"] = True
                self.board.emit("answer.delta", text=text)
        elif not s["answer_streamed"] and text:
            s["answer"] = text
            s["answer_streamed"] = True
            self.board.emit("answer.delta", text=text)

    # ---- helpers ----------------------------------------------------------------------

    def _subtask(self) -> dict[str, Any]:
        plan = self.state["plan"]
        index = self.state["index"]
        return plan[index] if 0 <= index < len(plan) else {}

    def _planned(self, plan: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        subtasks = [dict(st) for st in plan.get("sub_tasks") or []]
        s["plan"] = [
            {
                key: st.get(key)
                for key in (
                    "id",
                    "action",
                    "needs",
                    "tool_hint",
                    "keywords",
                    "depends_on",
                    "input_schema",
                    "output_schema",
                )
            }
            for st in subtasks
        ]
        s["index"] = 0
        b.emit(
            "plan.ready",
            subtasks=[
                {
                    "id": st.get("id"),
                    "action": st.get("action"),
                    "needs": st.get("needs"),
                    "tool_hint": st.get("tool_hint"),
                    "depends_on": list(st.get("depends_on") or []),
                }
                for st in subtasks
            ],
            verdict=plan.get("verdict") or "feasible",
        )
        if not subtasks or plan.get("verdict") == "infeasible":
            b.strip("chat", index=0, total=0, label=copy.LABEL_CHAT, sig=None)
            b.finish("planner", "done")
            b.log(copy.LOG_PLAN_CHAT)
            b.caption(copy.CAPTION_PLAN_CHAT)
            b.status(copy.STATUS_NONE_FORGED)
            return
        self._begin_subtask()

    def _begin_subtask(self) -> None:
        """`strip.set` for the current sub-task, then its variant's opening copy."""
        s, b = self.state, self.board
        sub = self._subtask()
        i, n = s["index"] + 1, len(s["plan"])
        needs = sub.get("needs") if sub.get("needs") in ("forge", "vault") else "primitive"
        s.update(
            attempt=0,
            tests_total=0,
            tool=sub.get("tool_hint") if needs == "vault" else None,
            code=[],
            env_vars=[],
            pending_attempt=None,
            test_results=[],
            intro_pending=False,
            exec_caption_pending=False,
            human="none",
        )
        label = {
            "forge": copy.LABEL_FORGE,
            "vault": copy.LABEL_VAULT,
            "primitive": copy.LABEL_PRIMITIVE,
        }[needs].format(i=i, n=n)
        b.strip(needs, index=i, total=n, label=label, sig=self._sig(sub, needs))
        b.finish("planner", "done")
        first = s["index"] == 0
        tool = sub.get("tool_hint") or ""
        if first and n > 1:
            b.emit("log.line", label="plan", text=copy.new("LOG_PLAN_MULTI", n=n), tone="plain")
            b.caption(copy.new("CAPTION_PLAN_MULTI", n=n))
        if needs == "forge":
            if first and n == 1:
                b.log(copy.LOG_PLAN_FORGE)
                b.caption(copy.CAPTION_PLAN_FORGE)
            b.status(copy.STATUS_FORGING, gold=True)
            b.log(copy.LOG_VAULT_MISS)
            b.flow("planner", "forger")
        elif needs == "vault":
            if first and n == 1:
                b.log(copy.LOG_PLAN_VAULT)
                keywords = [str(k) for k in sub.get("keywords") or []][:3]
                if keywords:
                    b.caption(
                        copy.CAPTION_PLAN_VAULT_KEYWORDS.format(
                            tool=html.escape(tool), keywords=html.escape(copy.join_words(keywords))
                        )
                    )
                else:
                    b.caption(copy.CAPTION_PLAN_VAULT.format(tool=html.escape(tool)))
            b.flow("planner", "vault")
            b.finish("vault", "done")
            b.log(copy.LOG_VAULT_HIT, tool=tool)
            b.status(copy.STATUS_NONE_FORGED, tone="warm")
            b.talos(copy.TALOS_FOUND.format(tool=tool))
            b.flow("vault", "skip")
            b.flow("skip", "executor")
        else:
            if first and n == 1:
                b.log(copy.LOG_PLAN_PRIMITIVE)
                b.caption(copy.CAPTION_PLAN_PRIMITIVE)
            b.flow("planner", "primitive")
            b.finish("primitive", "done")
            b.flow("primitive", "executor")

    def _sig(self, sub: Mapping[str, Any], needs: str) -> dict[str, str] | None:
        hint = sub.get("tool_hint")
        signature = self.signatures(needs, hint) if self.signatures and hint else None
        if signature:
            args, ret = split_signature(signature)
            return {"name": str(hint), "args": args, "ret": ret}
        schema = sub.get("input_schema") or {}
        if hint and (schema or sub.get("output_schema")):
            args = ", ".join(f"{k}: {v}" for k, v in schema.items())
            return {"name": str(hint), "args": args, "ret": str(sub.get("output_schema") or "")}
        return None

    def _forge_intro(self) -> None:
        s, b = self.state, self.board
        s["intro_pending"] = False
        tool = s["tool"]
        b.talos(copy.TALOS_WRITING.format(tool=tool))
        b.caption(copy.CAPTION_FORGER_FIRST.format(tool=html.escape(tool)))
        b.log(copy.LOG_FORGE_FIRST, "g", tool=tool)

    def _tests_decided(self, result: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        results = s["test_results"] or list(result.get("results") or [])
        total = len(results) or int(result.get("n_total") or 0) or s["tests_total"]
        passed = sum(1 for r in results if r.get("passed"))
        if result.get("passed"):
            b.log(copy.LOG_TEST_PASSED, "g", total=total)
            s["pending_attempt"] = copy.DETAIL_TESTS_PASSED.format(total=total)
            return
        failing = next((r for r in results if not r.get("passed")), None)
        if failing is not None:
            detail = f"{failing.get('name')}\n{failing.get('why') or ''}".rstrip()
        elif result.get("timed_out"):
            detail = str(result.get("error") or f"Timed out after {self.timeout_s} seconds.")
        else:
            detail = str(result.get("error") or "The tests did not run.")
        retrying = s["attempt"] < self.max_attempts
        if retrying:
            b.log(copy.LOG_TEST_RETRYING, "g", passed=passed, total=total)
        else:
            b.emit(
                "log.line",
                label="test",
                text=copy.new("LOG_TEST_FAILED", passed=passed, total=total),
                tone="g",
            )
        b.sub(failing.get("name") if failing is not None else detail.splitlines()[0])
        b.emit("forge.attempt", attempt=s["attempt"], ok=False, detail=detail)
        if retrying:
            b.talos(
                copy.TALOS_RETRYING
                if s["attempt"] == 1
                else copy.new("TALOS_RETRYING_N", n=s["attempt"])
            )

    def _settle_attempt(self, ok: bool, detail: str | None = None) -> None:
        """Emit the pending `forge.attempt` for an attempt whose tests passed."""
        pending = self.state["pending_attempt"]
        if pending is None:
            return
        self.state["pending_attempt"] = None
        self.board.emit(
            "forge.attempt", attempt=self.state["attempt"], ok=ok, detail=detail or pending
        )

    def _forge_done(self, update: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        test = update.get("test_result") or {}
        smoke = update.get("smoke_result") or {"passed": True}
        ok = bool(test.get("passed")) and bool(smoke.get("passed"))
        self._settle_attempt(ok, None if ok else "Smoke test failed")
        if ok:
            b.finish("tester", "forge")
            b.flow("tester", "human")
            return
        s["forge_failed"] = True
        b.mark_failed()
        b.finish("tester", "fail")
        b.caption(copy.new("CAPTION_FORGE_GAVE_UP", max=self.max_attempts))
        b.emit(
            "log.line",
            label="forge",
            text=copy.new("LOG_FORGE_GAVE_UP", n=s["attempt"]),
            tone="w",
        )

    def _before_answer(self) -> None:
        """Final captions and the flow into Answer (orchestrator_out started)."""
        s, b = self.state, self.board
        if s["variant"] == "chat":
            b.flow("planner", "answer")
            b.start("answer")
            return
        b.flow("executor", "answer")
        b.start("answer")
        if s["approval"] == "declined":
            b.caption(copy.CAPTION_DECLINED)
        elif s["failure"] or s["forge_failed"]:
            b.caption(copy.CAPTION_FAILED)
        elif s["forged"]:
            if len(s["forged"]) > 1:
                b.status(copy.new("SUMMARY_FORGED_MANY", k=len(s["forged"])), gold=True)
            else:
                b.status(copy.STATUS_ONE_FORGED, gold=True)
            if s["human"] == "saved":
                b.caption(
                    copy.new("CAPTION_DONE_FORGED_KEY", attempts=attempts_phrase(s["attempt"]))
                )
            elif s["attempt"] == 1:
                b.caption(copy.new("CAPTION_DONE_FORGED_ONE"))
            else:
                b.caption(copy.CAPTION_DONE_FORGED.format(attempts=s["attempt"]))
        elif s["variant"] == "vault":
            b.caption(copy.CAPTION_DONE_VAULT)
        else:
            b.status(copy.STATUS_NONE_FORGED)
            b.caption(copy.CAPTION_DONE_PRIMITIVE)

    def _summary(self) -> tuple[str, bool]:
        s = self.state
        failure = s["failure"]
        if s["approval"] == "declined":
            return copy.SUMMARY_DECLINED, False
        if failure and failure.get("streak"):
            if failure.get("pruned"):
                return copy.SUMMARY_FAILED_PRUNED, False
            return copy.SUMMARY_FAILED_STREAK.format(streak=failure["streak"]), False
        if failure or s["forge_failed"]:
            return copy.SUMMARY_FAILED, False
        if s["forged"]:
            if len(s["forged"]) > 1:
                return copy.new("SUMMARY_FORGED_MANY", k=len(s["forged"])), True
            if s["human"] == "saved":
                return copy.SUMMARY_FORGED_KEY, True
            if s["attempt"] == 1:
                return copy.new("SUMMARY_FORGED_ONE"), True
            return copy.SUMMARY_FORGED.format(attempts=s["attempt"]), True
        if s["variant"] == "chat":
            return copy.SUMMARY_CHAT, False
        if s["variant"] == "vault":
            return copy.SUMMARY_REUSED, False
        if s["approval"] == "approved":
            return copy.SUMMARY_PRIMITIVE_APPROVED, False
        return copy.SUMMARY_PRIMITIVE, False
```

- [ ] **Step 5: Record the fixtures from the real graph**

Run: `uv run python -m tests.web.chunks`
Expected: seven files in `tests/web/fixtures/`: `forge_retry.json` (about 70 chunks: two forge attempts, smoke, learn, execute, streamed answer), `vault.json`, `chat.json`, `exec_pause.json` (ends with an `__interrupt__` update), `exec_approve.json` (the chunks after the resume), `key_pause.json`, `key_skip.json`. It runs the real tester subprocess; nothing touches the network or your real vault or `.env`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_translator.py -v`
Expected: PASS, including `test_recorded_fixtures_match_a_live_capture[*]`, which re-runs each scenario on the installed LangGraph and compares chunk shapes with the JSON.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/translator.py tests/web/chunks.py tests/web/fixtures tests/web/test_translator.py
git commit -m "[Feat]: Add the EventTranslator with chunk fixtures recorded from the real graph"
```

---

### Task 5: Store interface with Postgres and in-memory implementations

**Files:**
- Create: `talos/web/store.py`
- Test: `tests/web/store_contract.py`, `tests/web/test_store.py`, `tests/integration/test_web_store.py`

**Interfaces:**
- Consumes (stage 1): `talos.persistence.repo` functions (all take `db: AsyncSession` first, never commit), `repo.SessionSummary`, `repo.summarise_session`, `repo.TERMINAL_STATUSES`, `talos.persistence.db.session_scope(factory)`, `talos.persistence.recovery.recover_runs`, `RECOVERY_ERROR`, `RECOVERY_SUMMARY`, models `Session, Run, Message, RunEvent` and `RunEvent.envelope()`, constants `ACTIVE_RUN_STATUSES, MESSAGE_ROLES, RUN_STATUSES`; integration fixtures `factory`, `migrated_url` (`tests/integration/conftest.py`).
- Produces: `Store` protocol (every method async, one transaction each): `ping() -> bool`, `create_session() -> Session`, `get_session(session_id) -> Session | None`, `rename_session(session_id, name) -> Session | None`, `list_sessions() -> list[SessionSummary]`, `list_messages(session_id) -> list[Message]`, `list_runs(session_id) -> list[Run]`, `begin_run(session_id, query, user_html, rename_to: str | None) -> tuple[Run, Message]` (run + user message + optional rename, one transaction; `LookupError` if no session), `get_run(run_id) -> Run | None`, `active_runs() -> list[Run]`, `set_run_status(run_id, status, **fields) -> Run`, `append_event(run_id, type_, data) -> RunEvent`, `events_after(run_id, seq=0) -> list[RunEvent]`, `add_message(session_id, role, html, note=None, chips=(), run_id=None) -> Message`, `get_setting(key, default=None)`, `set_setting(key, value) -> None`, `recover() -> list[UUID]`. Classes `PgStore(factory: async_sessionmaker[AsyncSession])` and `MemoryStore()` (public dicts `sessions`, `runs`, `events`, `settings`, list `messages`). `tests.web.store_contract.CONTRACT: list[async callable(store)]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/store_contract.py`:

```python
"""Behaviour every `Store` must have. Run against MemoryStore (unit) and
PgStore (integration), so the in-memory store the route tests use can't
drift from Postgres."""

from __future__ import annotations

import uuid

import pytest

from talos.persistence.recovery import RECOVERY_ERROR


async def sessions_are_numbered_and_named(store):
    first = await store.create_session()
    second = await store.create_session()
    assert (first.number, second.number) == (1, 2)
    assert (first.name, second.name) == ("Session 1", "Session 2")
    assert first.thread_id == f"session-{first.id}"
    assert (await store.get_session(first.id)).id == first.id
    assert await store.get_session(uuid.uuid4()) is None


async def begin_run_numbers_runs_adds_the_user_message_and_renames(store):
    s = await store.create_session()
    run1, msg = await store.begin_run(s.id, "encrypt it", "encrypt it", "Caesar cipher")
    run2, _ = await store.begin_run(s.id, "again", "again", None)
    assert (run1.n, run2.n, run1.status) == (1, 2, "running")
    assert (msg.role, msg.html, msg.run_id) == ("user", "encrypt it", run1.id)
    assert (await store.get_session(s.id)).name == "Caesar cipher"
    assert [r.n for r in await store.list_runs(s.id)] == [1, 2]
    assert [m.html for m in await store.list_messages(s.id)] == ["encrypt it", "again"]
    with pytest.raises(LookupError):
        await store.begin_run(uuid.uuid4(), "q", "q", None)


async def events_get_gap_free_seq_and_an_envelope(store):
    s = await store.create_session()
    run, _ = await store.begin_run(s.id, "q", "q", None)
    for i in range(5):
        event = await store.append_event(run.id, "log.line", {"i": i})
        assert event.seq == i + 1
    after = await store.events_after(run.id, 3)
    assert [e.seq for e in after] == [4, 5]
    env = after[0].envelope()
    assert set(env) == {"run_id", "seq", "ts", "type", "data"}
    assert env["run_id"] == str(run.id) and env["data"] == {"i": 3}
    assert env["ts"].endswith("Z")
    with pytest.raises(LookupError):
        await store.append_event(uuid.uuid4(), "x", {})


async def run_status_rules(store):
    s = await store.create_session()
    run, _ = await store.begin_run(s.id, "q", "q", None)
    state = {"steps": {"planner": {"state": "done", "label": "Planner"}}}
    waiting = await store.set_run_status(
        run.id, "waiting", translator_state=state, pending_interrupt={"type": "confirm_exec"}
    )
    assert waiting.finished_at is None
    assert [r.id for r in await store.active_runs()] == [run.id]
    again = await store.get_run(run.id)
    assert again.translator_state == state
    assert again.pending_interrupt == {"type": "confirm_exec"}
    done = await store.set_run_status(
        run.id, "done", pending_interrupt=None, summary="0 tools forged", used=["t"]
    )
    assert done.finished_at is not None and done.pending_interrupt is None
    assert done.used == ["t"]
    assert await store.active_runs() == []
    with pytest.raises(ValueError):
        await store.set_run_status(run.id, "exploded")
    with pytest.raises(LookupError):
        await store.set_run_status(uuid.uuid4(), "done")


async def sessions_list_newest_first_with_marks(store):
    old = await store.create_session()
    new = await store.create_session()
    run, _ = await store.begin_run(old.id, "caesar", "caesar", None)
    await store.set_run_status(run.id, "done", forged=["caesar_cipher"], used=["caesar_cipher"])
    listed = await store.list_sessions()
    assert [x.id for x in listed] == [new.id, old.id]
    assert listed[1].run_count == 1
    assert listed[1].forged == ["caesar_cipher"] and listed[1].used == []
    assert listed[1].runs[0].mark == "forged"


async def settings_round_trip(store):
    assert await store.get_setting("ask_before_exec") is None
    assert await store.get_setting("ask_before_exec", True) is True
    await store.set_setting("ask_before_exec", False)
    await store.set_setting("ask_before_exec", False)
    assert await store.get_setting("ask_before_exec") is False


async def recover_fails_running_runs_only(store):
    s = await store.create_session()
    running, _ = await store.begin_run(s.id, "a", "a", None)
    waiting, _ = await store.begin_run(s.id, "b", "b", None)
    await store.set_run_status(waiting.id, "waiting", pending_interrupt={"type": "x"})
    assert await store.recover() == [running.id]
    failed = await store.get_run(running.id)
    assert (failed.status, failed.error, failed.summary) == ("failed", RECOVERY_ERROR, "Failed")
    assert [e.type for e in await store.events_after(running.id)] == ["error", "run.finished"]
    assert (await store.get_run(waiting.id)).status == "waiting"


CONTRACT = [
    sessions_are_numbered_and_named,
    begin_run_numbers_runs_adds_the_user_message_and_renames,
    events_get_gap_free_seq_and_an_envelope,
    run_status_rules,
    sessions_list_newest_first_with_marks,
    settings_round_trip,
    recover_fails_running_runs_only,
]
```

Create `tests/web/test_store.py`:

```python
"""MemoryStore obeys the Store contract (the Postgres run is in tests/integration)."""

from __future__ import annotations

import pytest

from talos.web.store import MemoryStore
from tests.web.store_contract import CONTRACT


@pytest.mark.parametrize("case", CONTRACT, ids=lambda f: f.__name__)
async def test_memory_store(case):
    await case(MemoryStore())
```

Create `tests/integration/test_web_store.py`:

```python
"""PgStore obeys the same Store contract as MemoryStore."""

from __future__ import annotations

import pytest

from talos.web.store import PgStore
from tests.web.store_contract import CONTRACT

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("case", CONTRACT, ids=lambda f: f.__name__)
async def test_pg_store(case, factory):
    await case(PgStore(factory))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_store.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'talos.web.store'`.

- [ ] **Step 3: Implement the stores**

Create `talos/web/store.py`:

```python
"""Storage for the web layer: one interface, a Postgres and an in-memory version.

`PgStore` wraps the stage 1 repo functions; every method is its own short
transaction (`session_scope`), so no DB session is ever shared with a
request or a run task that might be cancelled, and `append_event` holds
the run row lock only for one insert.

`MemoryStore` keeps the same rows as transient ORM objects in dicts. It
exists so the route, SSE and runner tests run without a database; the
contract tests in `tests/web/test_store.py` run against both.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from talos.persistence import repo
from talos.persistence.db import session_scope
from talos.persistence.models import (
    ACTIVE_RUN_STATUSES,
    MESSAGE_ROLES,
    RUN_STATUSES,
    Message,
    Run,
    RunEvent,
    Session,
)
from talos.persistence.recovery import RECOVERY_ERROR, RECOVERY_SUMMARY, recover_runs
from talos.persistence.repo import TERMINAL_STATUSES, SessionSummary, summarise_session


class Store(Protocol):
    """What the web layer needs from storage. Each call is one transaction."""

    async def ping(self) -> bool: ...
    async def create_session(self) -> Session: ...
    async def get_session(self, session_id: uuid.UUID) -> Session | None: ...
    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None: ...
    async def list_sessions(self) -> list[SessionSummary]: ...
    async def list_messages(self, session_id: uuid.UUID) -> list[Message]: ...
    async def list_runs(self, session_id: uuid.UUID) -> list[Run]: ...
    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]: ...
    async def get_run(self, run_id: uuid.UUID) -> Run | None: ...
    async def active_runs(self) -> list[Run]: ...
    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run: ...
    async def append_event(
        self, run_id: uuid.UUID, type_: str, data: dict[str, Any]
    ) -> RunEvent: ...
    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]: ...
    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message: ...
    async def get_setting(self, key: str, default: Any = None) -> Any: ...
    async def set_setting(self, key: str, value: Any) -> None: ...
    async def recover(self) -> list[uuid.UUID]: ...


class PgStore:
    """`Store` on Postgres through `talos.persistence.repo`.

    Args:
        factory: The session factory from `init_db()`.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    def _tx(self):  # noqa: ANN202 - async context manager
        return session_scope(self._factory)

    async def ping(self) -> bool:
        try:
            async with self._tx() as db:
                await db.execute(text("select 1"))
        except Exception:  # noqa: BLE001 - health reports it, never raises
            return False
        return True

    async def create_session(self) -> Session:
        async with self._tx() as db:
            return await repo.create_session(db)

    async def get_session(self, session_id: uuid.UUID) -> Session | None:
        async with self._tx() as db:
            return await repo.get_session(db, session_id)

    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None:
        async with self._tx() as db:
            return await repo.rename_session(db, session_id, name)

    async def list_sessions(self) -> list[SessionSummary]:
        async with self._tx() as db:
            return await repo.list_sessions(db)

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        async with self._tx() as db:
            return await repo.list_messages(db, session_id)

    async def list_runs(self, session_id: uuid.UUID) -> list[Run]:
        async with self._tx() as db:
            return await repo.list_runs(db, session_id)

    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]:
        async with self._tx() as db:
            run = await repo.create_run(db, session_id, query)
            message = await repo.add_message(db, session_id, "user", user_html, run_id=run.id)
            if rename_to:
                await repo.rename_session(db, session_id, rename_to)
            return run, message

    async def get_run(self, run_id: uuid.UUID) -> Run | None:
        async with self._tx() as db:
            return await repo.get_run(db, run_id)

    async def active_runs(self) -> list[Run]:
        async with self._tx() as db:
            return await repo.active_runs(db)

    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
        async with self._tx() as db:
            return await repo.set_run_status(db, run_id, status, **fields)

    async def append_event(self, run_id: uuid.UUID, type_: str, data: dict[str, Any]) -> RunEvent:
        async with self._tx() as db:
            return await repo.append_event(db, run_id, type_, data)

    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
        async with self._tx() as db:
            return await repo.events_after(db, run_id, seq)

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message:
        async with self._tx() as db:
            return await repo.add_message(db, session_id, role, html, note, chips, run_id)

    async def get_setting(self, key: str, default: Any = None) -> Any:
        async with self._tx() as db:
            return await repo.get_setting(db, key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        async with self._tx() as db:
            await repo.set_setting(db, key, value)

    async def recover(self) -> list[uuid.UUID]:
        async with self._tx() as db:
            return await recover_runs(db)


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    """`Store` in process memory, with the same rules as the repo functions."""

    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        self.runs: dict[uuid.UUID, Run] = {}
        self.messages: list[Message] = []
        self.events: dict[uuid.UUID, list[RunEvent]] = {}
        self.settings: dict[str, Any] = {}

    async def ping(self) -> bool:
        return True

    async def create_session(self) -> Session:
        number = max((s.number for s in self.sessions.values()), default=0) + 1
        sid = uuid.uuid4()
        now = _now()
        row = Session(
            id=sid,
            name=f"Session {number}",
            number=number,
            thread_id=f"session-{sid}",
            created_at=now,
            updated_at=now,
        )
        row.runs = []
        self.sessions[sid] = row
        return row

    async def get_session(self, session_id: uuid.UUID) -> Session | None:
        return self.sessions.get(session_id)

    async def rename_session(self, session_id: uuid.UUID, name: str) -> Session | None:
        row = self.sessions.get(session_id)
        if row is not None:
            row.name = name
            row.updated_at = _now()
        return row

    async def list_sessions(self) -> list[SessionSummary]:
        rows = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.number), reverse=True)
        return [summarise_session(s) for s in rows]

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        return [m for m in self.messages if m.session_id == session_id]

    async def list_runs(self, session_id: uuid.UUID) -> list[Run]:
        return sorted((r for r in self.runs.values() if r.session_id == session_id), key=_n)

    async def begin_run(
        self, session_id: uuid.UUID, query: str, user_html: str, rename_to: str | None
    ) -> tuple[Run, Message]:
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"session {session_id} not found")
        n = max((r.n for r in session.runs), default=0) + 1
        run = Run(
            id=uuid.uuid4(),
            session_id=session_id,
            n=n,
            query=query,
            status="running",
            summary_gold=False,
            forged=[],
            used=[],
            failed=False,
            started_at=_now(),
        )
        self.runs[run.id] = run
        self.events[run.id] = []
        session.runs.append(run)
        session.updated_at = _now()
        message = await self.add_message(session_id, "user", user_html, run_id=run.id)
        if rename_to:
            session.name = rename_to
        return run, message

    async def get_run(self, run_id: uuid.UUID) -> Run | None:
        return self.runs.get(run_id)

    async def active_runs(self) -> list[Run]:
        return [r for r in self.runs.values() if r.status in ACTIVE_RUN_STATUSES]

    async def set_run_status(self, run_id: uuid.UUID, status: str, **fields: Any) -> Run:
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        run = self.runs.get(run_id)
        if run is None:
            raise LookupError(f"run {run_id} not found")
        run.status = status
        for name, value in fields.items():
            setattr(run, name, list(value) if name in {"forged", "used"} else value)
        if status in TERMINAL_STATUSES and "finished_at" not in fields:
            run.finished_at = _now()
        return run

    async def append_event(self, run_id: uuid.UUID, type_: str, data: dict[str, Any]) -> RunEvent:
        if run_id not in self.runs:
            raise LookupError(f"run {run_id} not found")
        events = self.events[run_id]
        event = RunEvent(run_id=run_id, seq=len(events) + 1, type=type_, data=data, ts=_now())
        events.append(event)
        return event

    async def events_after(self, run_id: uuid.UUID, seq: int = 0) -> list[RunEvent]:
        return [e for e in self.events.get(run_id, []) if e.seq > seq]

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        html: str,
        note: str | None = None,
        chips: Sequence[dict[str, Any]] = (),
        run_id: uuid.UUID | None = None,
    ) -> Message:
        if role not in MESSAGE_ROLES:
            raise ValueError(f"unknown message role {role!r}")
        message = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            run_id=run_id,
            role=role,
            html=html,
            note=note,
            chips=[dict(c) for c in chips],
            created_at=_now(),
        )
        self.messages.append(message)
        return message

    async def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value

    async def recover(self) -> list[uuid.UUID]:
        stale = sorted(
            (r for r in self.runs.values() if r.status == "running"), key=lambda r: r.started_at
        )
        for run in stale:
            await self.set_run_status(
                run.id, "failed", error=RECOVERY_ERROR, summary=RECOVERY_SUMMARY
            )
            await self.append_event(run.id, "error", {"message": RECOVERY_ERROR})
            await self.append_event(
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
        return [r.id for r in stale]


def _n(run: Run) -> int:
    return run.n
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `uv run pytest tests/web/test_store.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Run the contract on Postgres**

Start the disposable database if it isn't running (`docker start talos-pg-test`, or create it as in the README Tests section), then:

Run: `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration tests/integration/test_web_store.py -v`
Expected: 7 PASS. `MemoryStore` and `PgStore` agree.

- [ ] **Step 6: Commit**

```bash
git add talos/web/store.py tests/web/store_contract.py tests/web/test_store.py tests/integration/test_web_store.py
git commit -m "[Feat]: Add the web store with Postgres and in-memory implementations"
```

---

### Task 6: RunManager and GraphDriver

**Files:**
- Create: `talos/web/runner.py`
- Test: `tests/web/stubs.py`, `tests/web/test_runner.py`, `tests/web/test_graph_driver.py`

**Interfaces:**
- Consumes: `Store` (Task 5), `Board` (Task 3), `EventTranslator`, `STREAM_MODES` (Task 4), `copy` and `naming.session_name` (Task 2), `schemas.pending_payload` (Task 3), `talos.agents.executor.PRIMITIVES`, `talos.vault.manager.SkillManager`, `talos.graph.build_app`; `tests.web.chunks.load` (Task 4).
- Produces:
  - Errors (each has `.code`, `.status`, `.extra: dict[str, str]`): `RunError`, `RunActive(active: Run | None)` (409 `run_active`, `extra = {"run_id", "session_id"}`), `NotWaiting` (409 `not_waiting`), `BadDecision(message)` (422 `bad_decision`), `NotFound(message)` (404 `not_found`).
  - `Resume(kind: str, decision: str, value: Any)` and `Pause(kind: str, value: dict)` (frozen dataclasses); `Emitted = tuple[str, dict]`.
  - `Driver` protocol: `initial_state() -> dict`; `run(state, *, query: str, thread_id: str, resume: Resume | None) -> AsyncIterator[Emitted | Pause]` (mutates `state` in place; yields `answer.done` and `run.finished` itself at a normal end).
  - `signature_text(fn) -> str`, `graph_signatures(needs: str, hint: str | None) -> str | None`, `GraphDriver(graph)`.
  - `StartResult(run: Run, message: Message)`, `user_html(text) -> str`.
  - `RunManager(store: Store, driver: Driver)`: `start(session_id, text) -> StartResult`; `resume(run_id, decision: str, value: str | None = None) -> None`; `stop(run_id) -> None`; `subscribe(run_id, after: int = 0) -> AsyncIterator[dict]` (envelopes); `join(run_id) -> None`; `shutdown() -> None`. The manager emits `run.started {session_id, query, n}`, `log.cmd {text}`, `interrupt {kind, payload}`, `interrupt.resolved {kind, decision}`, `error {message}` and the stop / exception `run.finished`.
  - `tests.web.stubs`: `ScriptDriver` (queries `pause`, `key`, `block`, `boom`, anything else), `CONFIRM`, `KEY`. Tasks 8 and 9 use it.

- [ ] **Step 1: Write the stub driver**

Create `tests/web/stubs.py`:

```python
"""A scripted Driver for RunManager tests: the query picks the behaviour."""

from __future__ import annotations

import asyncio
from typing import Any

from talos.web.board import Board, new_state
from talos.web.runner import Pause, Resume

CONFIRM = {
    "type": "confirm_exec",
    "tool": "python_exec",
    "preview": "print(1)",
    "args": [],
    "kwargs": {"code": "print(1)"},
    "message": "Talos wants to run python_exec. Allow it? [y/N]",
}
KEY = {
    "type": "missing_api_key",
    "env_var": "OPENWEATHERMAP_API_KEY",
    "tool_name": "get_current_temperature",
    "message": "needs a key",
}


class ScriptDriver:
    """Queries: "pause" (confirm_exec), "key" (missing_api_key), "block" (never
    ends until cancelled), "boom" (raises), anything else finishes at once."""

    def __init__(self) -> None:
        self.resumes: list[Resume] = []
        self.started = asyncio.Event()

    def initial_state(self) -> dict[str, Any]:
        return new_state()

    async def run(self, state, *, query, thread_id, resume):
        b = Board(state)
        if resume is None:
            b.strip("primitive", index=1, total=1, label="Sub-task 1 of 1", sig=None)
            b.start("planner")
            for event in b.drain():
                yield event
            self.started.set()
            if query == "pause":
                yield Pause("confirm_exec", dict(CONFIRM))
                return
            if query == "key":
                yield Pause("missing_api_key", dict(KEY))
                return
            if query == "block":
                await asyncio.Event().wait()
            if query == "boom":
                raise RuntimeError("kaboom")
        else:
            self.resumes.append(resume)
        b.finish("planner", "done")
        b.add_used("caesar_cipher")
        b.emit("answer.done", html="ok", note=None, chips=[])
        b.finished("done", "Built-in")
        for event in b.drain():
            yield event
```

- [ ] **Step 2: Write the failing tests**

Create `tests/web/test_runner.py`:

```python
"""RunManager with a scripted driver and the in-memory store (spec 02 §11)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from talos.web.runner import BadDecision, NotFound, NotWaiting, RunActive, RunManager
from talos.web.store import MemoryStore
from tests.web.stubs import ScriptDriver


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def driver() -> ScriptDriver:
    return ScriptDriver()


@pytest.fixture
def manager(store, driver) -> RunManager:
    return RunManager(store, driver)


async def events(store: MemoryStore, run_id) -> list[tuple[int, str]]:
    return [(e.seq, e.type) for e in await store.events_after(run_id)]


async def test_a_run_streams_to_the_end_and_is_recorded(manager, store):
    session = await store.create_session()
    started = await manager.start(session.id, "Encrypt with a Caesar cipher")
    await manager.join(started.run.id)

    types = [t for _, t in await events(store, started.run.id)]
    assert types[:2] == ["run.started", "log.cmd"]
    assert types[-2:] == ["answer.done", "run.finished"]
    first = (await store.events_after(started.run.id))[0]
    assert first.data == {"session_id": str(session.id), "query": started.run.query, "n": 1}
    run = await store.get_run(started.run.id)
    assert (run.status, run.summary, run.used) == ("done", "Built-in", ["caesar_cipher"])
    assert run.translator_state["steps"]["planner"]["state"] == "done"
    roles = [(m.role, m.html) for m in await store.list_messages(session.id)]
    assert roles == [("user", "Encrypt with a Caesar cipher"), ("assistant", "ok")]
    assert (await store.get_session(session.id)).name == "Caesar cipher"


async def test_only_the_first_run_names_the_session(manager, store):
    session = await store.create_session()
    for text in ("What can you do?", "Encrypt with a Caesar cipher"):
        await manager.join((await manager.start(session.id, text)).run.id)
    assert (await store.get_session(session.id)).name == "Getting to know Talos"


async def test_user_text_is_stored_escaped(manager, store):
    session = await store.create_session()
    started = await manager.start(session.id, "<b>hi</b>")
    assert started.message.html == "&lt;b&gt;hi&lt;/b&gt;"
    await manager.join(started.run.id)


async def test_one_active_run_across_the_whole_app(manager, store):
    a = await store.create_session()
    b = await store.create_session()
    paused = await manager.start(a.id, "pause")
    await manager.join(paused.run.id)
    assert (await store.get_run(paused.run.id)).status == "waiting"
    with pytest.raises(RunActive):
        await manager.start(b.id, "hello")


async def test_concurrent_starts_let_exactly_one_through(manager, store):
    session = await store.create_session()
    results = await asyncio.gather(
        *(manager.start(session.id, "block") for _ in range(5)), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1
    assert all(isinstance(r, RunActive) for r in results if isinstance(r, Exception))
    await manager.stop(ok[0].run.id)


async def test_unknown_session_is_not_found(manager):
    with pytest.raises(NotFound):
        await manager.start(uuid.uuid4(), "hi")


async def test_pause_then_resume_keeps_seq_gap_free(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    paused = await store.get_run(run_id)
    assert paused.status == "waiting"
    assert paused.pending_interrupt["kwargs"] == {"code": "print(1)"}
    last = (await store.events_after(run_id))[-1]
    assert (last.type, last.data) == (
        "interrupt",
        {"kind": "confirm_exec", "payload": {"tool": "python_exec", "preview": "print(1)"}},
    )

    await manager.resume(run_id, "approve")
    await manager.join(run_id)

    seqs = [s for s, _ in await events(store, run_id)]
    assert seqs == list(range(1, len(seqs) + 1))
    types = [t for _, t in await events(store, run_id)]
    assert types[types.index("interrupt") + 1] == "interrupt.resolved"
    assert types[-1] == "run.finished"
    resolved = next(e for e in await store.events_after(run_id) if e.type == "interrupt.resolved")
    assert resolved.data == {"kind": "confirm_exec", "decision": "approve"}
    assert driver.resumes[0].value == {
        "approved": True,
        "args": [],
        "kwargs": {"code": "print(1)"},
    }
    done = await store.get_run(run_id)
    assert (done.status, done.pending_interrupt) == ("done", None)


async def test_decline_and_key_decisions_map_to_resume_values(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "decline")
    await manager.join(run_id)

    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "save", "  sk-secret  ")
    await manager.join(run_id)

    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "skip")
    await manager.join(run_id)
    assert [r.value for r in driver.resumes] == [{"approved": False}, "sk-secret", "skip"]


async def test_resume_errors(manager, store):
    session = await store.create_session()
    with pytest.raises(NotFound):
        await manager.resume(uuid.uuid4(), "approve")
    done = (await manager.start(session.id, "hi")).run.id
    await manager.join(done)
    with pytest.raises(NotWaiting):
        await manager.resume(done, "approve")

    paused = (await manager.start(session.id, "pause")).run.id
    await manager.join(paused)
    with pytest.raises(BadDecision):
        await manager.resume(paused, "save", "x")
    key = paused
    await manager.stop(key)
    key = (await manager.start(session.id, "key")).run.id
    await manager.join(key)
    with pytest.raises(BadDecision):
        await manager.resume(key, "approve")
    with pytest.raises(BadDecision):
        await manager.resume(key, "save", "   ")
    assert (await store.get_run(key)).status == "waiting"


async def test_stop_during_a_run(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "block")).run.id
    await driver.started.wait()
    await manager.stop(run_id)

    run = await store.get_run(run_id)
    assert (run.status, run.summary) == ("stopped", "Stopped")
    tail = [(e.type, e.data) for e in await store.events_after(run_id)][-5:]
    assert tail == [
        ("node.finished", {"step": "planner", "status": "stopped", "label": "Planner, stopped"}),
        ("log.line", {"label": "stop", "text": "stopped by you", "tone": "w"}),
        ("log.status", {"text": "Stopped", "gold": False, "tone": ""}),
        ("caption", {"html": "You stopped this run. Nothing was saved to the vault."}),
        (
            "run.finished",
            {"status": "stopped", "summary": "Stopped", "summary_gold": False,
             "forged": [], "used": []},
        ),
    ]  # fmt: skip
    notes = [m.note for m in await store.list_messages(session.id) if m.role == "assistant"]
    assert notes == ["Stopped. Ask again whenever you're ready."]
    # the lock is free again
    await manager.join((await manager.start(session.id, "hi")).run.id)


async def test_stop_during_a_pause_uses_the_saved_state(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    fresh = RunManager(store, ScriptDriver())  # e.g. after an app restart
    await fresh.stop(run_id)
    run = await store.get_run(run_id)
    assert (run.status, run.pending_interrupt) == ("stopped", None)
    types = [t for _, t in await events(store, run_id)]
    assert types[-5:] == ["node.finished", "log.line", "log.status", "caption", "run.finished"]
    await fresh.stop(run_id)  # already finished: no-op
    assert len(await events(store, run_id)) == len(types)


async def test_an_exception_fails_the_run(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "boom")).run.id
    await manager.join(run_id)
    tail = [(e.type, e.data) for e in await store.events_after(run_id)][-2:]
    assert tail == [
        ("error", {"message": "RuntimeError: kaboom"}),
        (
            "run.finished",
            {"status": "failed", "summary": "Failed", "summary_gold": False,
             "forged": [], "used": []},
        ),
    ]  # fmt: skip
    run = await store.get_run(run_id)
    assert (run.status, run.error, run.failed) == ("failed", "RuntimeError: kaboom", True)


async def test_subscribe_replays_then_goes_live_then_closes(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    backlog = len(await events(store, run_id))

    seen: list[int] = []

    async def consume() -> None:
        async for envelope in manager.subscribe(run_id, after=2):
            seen.append(envelope["seq"])

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert seen == list(range(3, backlog + 1))  # backlog after seq 2, then waits
    await manager.resume(run_id, "approve")
    await asyncio.wait_for(consumer, 2)
    total = len(await events(store, run_id))
    assert seen == list(range(3, total + 1))  # live events, closed after run.finished


async def test_subscribe_to_a_finished_run_returns_the_backlog_and_closes(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "hi")).run.id
    await manager.join(run_id)
    got = [e["seq"] async for e in manager.subscribe(run_id, after=0)]
    assert got == [s for s, _ in await events(store, run_id)]
    assert [e["seq"] async for e in manager.subscribe(run_id, after=len(got))] == []


async def test_shutdown_stops_running_runs(manager, store, driver):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "block")).run.id
    await driver.started.wait()
    await manager.shutdown()
    assert (await store.get_run(run_id)).status == "stopped"


class SlowStore(MemoryStore):
    """Appends take a moment, like a real database round trip."""

    async def append_event(self, run_id, type_, data):
        await asyncio.sleep(0.01)
        return await super().append_event(run_id, type_, data)


async def until_waiting(store, run_id) -> None:
    for _ in range(500):
        if (await store.get_run(run_id)).status == "waiting":
            return
        await asyncio.sleep(0.001)
    raise AssertionError("never paused")


async def test_resume_right_after_the_pause_keeps_interrupt_first():
    store = SlowStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await until_waiting(store, run_id)  # status is waiting; `interrupt` may still be in flight
    await manager.resume(run_id, "approve")
    await manager.join(run_id)
    types = [t for _, t in await events(store, run_id)]
    assert types.index("interrupt") < types.index("interrupt.resolved")


async def test_shutdown_leaves_a_just_paused_run_waiting():
    store = SlowStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await until_waiting(store, run_id)
    await manager.shutdown()
    assert (await store.get_run(run_id)).status == "waiting"
    assert [t for _, t in await events(store, run_id)][-1] == "interrupt"


async def test_a_closed_subscriber_is_forgotten(manager, store):
    session = await store.create_session()
    run_id = (await manager.start(session.id, "pause")).run.id
    await manager.join(run_id)
    stream = manager.subscribe(run_id, after=0)
    await stream.__anext__()  # the browser read one event, then the tab closed
    assert manager._subscribers[run_id]
    await stream.aclose()
    assert run_id not in manager._subscribers
```

Create `tests/web/test_graph_driver.py`:

```python
"""GraphDriver: the astream call it makes, and LangGraph's fresh-turn behaviour."""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from talos.agents import executor as exec_mod
from talos.agents import learner as learner_mod
from talos.agents import orchestrator as orch_mod
from talos.agents import planner as planner_mod
from talos.agents.executor import PRIMITIVES, ResolvedArgs
from talos.agents.planner import Plan, SubTask
from talos.graph import build_app
from talos.vault.manager import SkillManager
from talos.web.runner import GraphDriver, Pause, Resume, graph_signatures, signature_text
from tests.web import chunks


class StubGraph:
    """Replays fixture chunks and records how astream was called."""

    def __init__(self, *names: str) -> None:
        self.batches = [chunks.load(n) for n in names]
        self.calls: list[tuple] = []

    async def astream(self, graph_input, config, *, stream_mode, subgraphs):
        self.calls.append((graph_input, config, stream_mode, subgraphs))
        for chunk in self.batches.pop(0):
            yield chunk


async def collect(driver, state, **kwargs):
    return [item async for item in driver.run(state, **kwargs)]


async def test_graph_driver_streams_with_the_contract_arguments_and_pauses():
    graph = StubGraph("exec_pause", "exec_approve")
    driver = GraphDriver(graph)
    state = driver.initial_state()
    items = await collect(driver, state, query="run it", thread_id="session-1", resume=None)

    graph_input, config, modes, subgraphs = graph.calls[0]
    assert graph_input["messages"][0].content == "run it"
    assert config == {"configurable": {"thread_id": "session-1"}}
    assert (modes, subgraphs) == (["updates", "custom", "messages", "tasks"], True)
    assert isinstance(items[-1], Pause)
    assert items[-1].kind == "confirm_exec"
    assert state["approval"] == "waiting"

    value = {"approved": True, "args": [], "kwargs": {"code": "print(sum(range(1, 101)))"}}
    resume = Resume("confirm_exec", "approve", value)
    items = await collect(driver, state, query="run it", thread_id="session-1", resume=resume)
    command = graph.calls[1][0]
    assert isinstance(command, Command) and command.resume == value
    assert items[0] == ("log.pop", {})
    assert items[-1][0] == "run.finished"


def test_primitive_signatures_read_like_the_demo():
    assert signature_text(PRIMITIVES["python_exec"]) == (
        "python_exec(code: str, timeout: int | None = None) -> dict"
    )
    assert graph_signatures("primitive", "vault_list") == "vault_list() -> list[dict]"
    assert graph_signatures("forge", None) is None


class _Canned:
    def __init__(self, items):
        self.items = list(items)

    def invoke(self, _messages):
        return self.items.pop(0)


async def test_new_input_after_a_pause_starts_a_fresh_turn(monkeypatch, tmp_path: Path):
    """Spec 02 §6: a stopped (paused) run's thread must restart from START."""
    vault = SkillManager(vault_dir=tmp_path)
    for module in (planner_mod, exec_mod, learner_mod):
        monkeypatch.setattr(module, "_get_skill_manager", lambda: vault)
    exec_plan = Plan(
        sub_tasks=[
            SubTask(
                id=1,
                action="run code",
                needs="primitive",
                tool_hint="python_exec",
                keywords=["python"],
                input_description="code",
            )
        ]
    )
    planner = _Canned([exec_plan, Plan(sub_tasks=[])])
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: planner)
    resolver = _Canned([ResolvedArgs(args=[], kwargs={"code": "print(1)"})])
    monkeypatch.setattr(exec_mod, "_make_resolver_llm", lambda: resolver)
    chat = GenericFakeChatModel(messages=iter([AIMessage(content="Hi.")]))
    monkeypatch.setattr(orch_mod, "_make_llm", lambda: chat)

    app = build_app()
    config = {"configurable": {"thread_id": "fresh"}}
    first = [c async for c in app.astream(
        {"messages": [HumanMessage("run print(1)")]}, config, stream_mode="updates"
    )]  # fmt: skip
    assert "__interrupt__" in first[-1]
    assert (await app.aget_state(config)).next == ("executor",)

    second = [c async for c in app.astream(
        {"messages": [HumanMessage("hello")]}, config, stream_mode="updates"
    )]  # fmt: skip
    assert list(second[0]) == ["orchestrator_in"]
    assert list(second[-1]) == ["orchestrator_out"]
    state = await app.aget_state(config)
    assert state.next == () and not state.interrupts
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_runner.py tests/web/test_graph_driver.py -v`
Expected: collection errors, `ModuleNotFoundError: No module named 'talos.web.runner'`.

- [ ] **Step 4: Implement the runner**

Create `talos/web/runner.py`:

```python
"""RunManager: one background task per active run, fan-out to SSE subscribers.

A run is driven by a `Driver`: `GraphDriver` for the real graph (through
`EventTranslator`), `FakeDriver` (fake_graph.py) for TALOS_FAKE_GRAPH=1.
The manager owns everything drivers share:

- the one-active-run lock (the vault and .env are shared files),
- persisting each event (`store.append_event` allocates `seq`) and only
  then publishing it to subscribers,
- pausing: the interrupt value goes to `runs.pending_interrupt`, the run
  becomes `waiting`, and no task is held while it waits,
- resuming, stopping, and the exception path.

Driver state (strip, attempts, tools) is a JSON dict saved as
`runs.translator_state` at every pause and at the end.
"""

from __future__ import annotations

import asyncio
import html
import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from talos.agents.executor import PRIMITIVES
from talos.persistence.models import Message, Run
from talos.persistence.repo import TERMINAL_STATUSES
from talos.vault.manager import SkillManager
from talos.web import copy
from talos.web.board import Board
from talos.web.naming import session_name
from talos.web.schemas import pending_payload
from talos.web.store import Store
from talos.web.translator import STREAM_MODES, EventTranslator

log = logging.getLogger(__name__)


# ---- errors the routes turn into HTTP codes -------------------------------------


class RunError(Exception):
    """Base for run errors that map to an API error code."""

    code = "run_error"
    status = 400
    extra: dict[str, str] = {}


class RunActive(RunError):
    """Another run is going. `extra` names it so the browser can open it."""

    code, status = "run_active", 409

    def __init__(self, active: Run | None = None) -> None:
        super().__init__("A run is already going. Stop it or wait for it to finish.")
        if active is not None:
            self.extra = {"run_id": str(active.id), "session_id": str(active.session_id)}


class NotWaiting(RunError):
    code, status = "not_waiting", 409

    def __init__(self) -> None:
        super().__init__("This run isn't waiting for an answer.")


class BadDecision(RunError):
    code, status = "bad_decision", 422


class NotFound(RunError):
    code, status = "not_found", 404


# ---- driver protocol --------------------------------------------------------------


@dataclass(frozen=True)
class Resume:
    """The user's answer to a pause.

    `value` is what the graph resumes with. For a saved key it is the key
    itself: it goes to the graph and nowhere else (no events, no logs).
    """

    kind: str
    decision: str
    value: Any


@dataclass(frozen=True)
class Pause:
    """A driver paused: `value` is the full interrupt value (server side only)."""

    kind: str
    value: dict[str, Any]


Emitted = tuple[str, dict[str, Any]]


class Driver(Protocol):
    """Produces a run's contract events. Mutates `state` in place."""

    def initial_state(self) -> dict[str, Any]: ...

    def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]: ...


def signature_text(fn: Callable[..., Any]) -> str:
    """`python_exec(code: str, timeout: int | None = None) -> dict` for a primitive."""
    sig = inspect.signature(fn)
    params = []
    for p in sig.parameters.values():
        ann = p.annotation
        ann_text = ann if isinstance(ann, str) else getattr(ann, "__name__", "")
        text = f"{p.name}: {ann_text}" if ann is not inspect.Parameter.empty else p.name
        if p.default is not inspect.Parameter.empty:
            text += f" = {p.default!r}"
        params.append(text)
    ret = sig.return_annotation
    ret_text = ret if isinstance(ret, str) else getattr(ret, "__name__", "")
    out = f"{fn.__name__}({', '.join(params)})"
    return f"{out} -> {ret_text}" if ret is not inspect.Signature.empty else out


def graph_signatures(needs: str, hint: str | None) -> str | None:
    """Signature lookup for the strip header: primitives and vault tools."""
    if not hint:
        return None
    if needs == "primitive" and hint in PRIMITIVES:
        return signature_text(PRIMITIVES[hint])
    if needs == "vault":
        entry = SkillManager().get(hint)
        return entry.get("signature") if entry else None
    return None


class GraphDriver:
    """Drives the compiled Talos graph and translates its stream.

    Args:
        graph: `build_app(saver)` with the Postgres checkpointer. Only the
            async API (`astream`) is used; AsyncPostgresSaver has no sync path.
    """

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def initial_state(self) -> dict[str, Any]:
        return EventTranslator.initial_state()

    async def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]:
        tr = EventTranslator(state, signatures=graph_signatures)
        if resume is None:
            graph_input: Any = {"messages": [HumanMessage(content=query)]}
        else:
            for event in tr.resumed(resume.kind, resume.decision):
                yield event
            graph_input = Command(resume=resume.value)
        config = {"configurable": {"thread_id": thread_id}}
        async for chunk in self.graph.astream(
            graph_input, config, stream_mode=STREAM_MODES, subgraphs=True
        ):
            for event in tr.feed(chunk):
                yield event
        if tr.pause is not None:
            yield Pause(kind=tr.pause[0], value=tr.pause[1])
            return
        for event in tr.finish():
            yield event


# ---- the manager ---------------------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    run: Run
    message: Message


def user_html(text: str) -> str:
    """User text is stored escaped (it's rendered as HTML later)."""
    return html.escape(text)


class RunManager:
    """Starts, resumes and stops runs; publishes their events.

    Args:
        store: Where sessions, runs and events live.
        driver: Produces the events (real graph or fake).
    """

    def __init__(self, store: Store, driver: Driver) -> None:
        self.store = store
        self.driver = driver
        self._lock = asyncio.Lock()
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._states: dict[uuid.UUID, dict[str, Any]] = {}
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = {}

    # ---- lifecycle -----------------------------------------------------------------

    async def join(self, run_id: uuid.UUID) -> None:
        """Wait until the run's current task (if any) ends: finished or paused."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        """App shutdown: stop running runs. A run that just paused keeps waiting."""
        for run_id, task in list(self._tasks.items()):
            run = await self.store.get_run(run_id)
            if run is not None and run.status == "waiting":
                await asyncio.gather(task, return_exceptions=True)  # finishing its pause
            else:
                await self.stop(run_id)

    # ---- start / resume / stop ------------------------------------------------------

    async def start(self, session_id: uuid.UUID, text: str) -> StartResult:
        """Start a run for `text` in a session.

        Raises:
            NotFound: No such session.
            RunActive: Some run anywhere is `running` or `waiting`.
        """
        async with self._lock:
            session = await self.store.get_session(session_id)
            if session is None:
                raise NotFound("Session not found.")
            active = await self.store.active_runs()
            if active:
                raise RunActive(active[0])
            first = not await self.store.list_runs(session_id)
            run, message = await self.store.begin_run(
                session_id, text, user_html(text), session_name(text) if first else None
            )
            state = self.driver.initial_state()
            self._states[run.id] = state
            await self._publish(
                run.id, "run.started", session_id=str(session_id), query=text, n=run.n
            )
            await self._publish(run.id, "log.cmd", text=text)
            self._spawn(run, session.thread_id, state, None)
        return StartResult(run=run, message=message)

    async def resume(self, run_id: uuid.UUID, decision: str, value: str | None = None) -> None:
        """Answer a paused run and continue it in a new task.

        Raises:
            NotFound: No such run.
            NotWaiting: The run isn't paused.
            BadDecision: The decision doesn't fit the pending interrupt.
        """
        async with self._lock:
            run = await self.store.get_run(run_id)
            if run is None:
                raise NotFound("Run not found.")
            if run.status != "waiting" or not run.pending_interrupt:
                raise NotWaiting()
            pending = dict(run.pending_interrupt)
            resume = _resume_for(pending, decision, value)
            await self.join(run_id)  # the pausing task may still be publishing `interrupt`
            session = await self.store.get_session(run.session_id)
            state = dict(run.translator_state or self.driver.initial_state())
            self._states[run_id] = state
            await self.store.set_run_status(run_id, "running", pending_interrupt=None)
            await self._publish(run_id, "interrupt.resolved", kind=resume.kind, decision=decision)
            self._spawn(run, session.thread_id, state, resume)

    async def stop(self, run_id: uuid.UUID) -> None:
        """Stop a run: cancel its task, or finish it if it is paused. No-op when finished.

        Raises:
            NotFound: No such run.
        """
        async with self._lock:
            run = await self.store.get_run(run_id)
            if run is None:
                raise NotFound("Run not found.")
            if run.status in TERMINAL_STATUSES:
                return
            task = self._tasks.pop(run_id, None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            state = self._states.pop(run_id, None) or dict(run.translator_state or {})
            board = Board(state)
            board.stop()
            await self.store.set_run_status(
                run_id,
                "stopped",
                pending_interrupt=None,
                translator_state=board.state,
                summary=copy.SUMMARY_STOPPED,
                summary_gold=False,
                forged=board.state["forged"],
                used=board.state["used"],
                failed=bool(board.state["failed"]),
            )
            board.finished("stopped", copy.SUMMARY_STOPPED)
            for type_, data in board.drain():
                await self._publish(run_id, type_, **data)
            await self.store.add_message(
                run.session_id, "assistant", "", note=copy.STOP_NOTE, run_id=run_id
            )

    # ---- events -------------------------------------------------------------------------

    async def subscribe(self, run_id: uuid.UUID, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Envelopes with `seq > after`: the stored backlog, then live ones.

        Ends after `run.finished`, or right after the backlog when the run
        already finished. The queue is registered before the backlog is
        read, and duplicates are dropped by `seq`, so nothing is missed.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            last = after
            for event in await self.store.events_after(run_id, after):
                envelope = event.envelope()
                last = envelope["seq"]
                yield envelope
                if envelope["type"] == "run.finished":
                    return
            run = await self.store.get_run(run_id)
            if run is None or run.status in TERMINAL_STATUSES:
                return
            while True:
                envelope = await queue.get()
                if envelope["seq"] <= last:
                    continue
                last = envelope["seq"]
                yield envelope
                if envelope["type"] == "run.finished":
                    return
        finally:
            subs = self._subscribers.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(run_id, None)

    async def _publish(self, run_id: uuid.UUID, type_: str, **data: Any) -> None:
        """Persist (allocating `seq`), then hand the envelope to every subscriber."""
        event = await self.store.append_event(run_id, type_, data)
        envelope = event.envelope()
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(envelope)

    # ---- the run task -----------------------------------------------------------------------

    def _spawn(
        self, run: Run, thread_id: str, state: dict[str, Any], resume: Resume | None
    ) -> None:
        task = asyncio.create_task(
            self._drive(run.id, run.session_id, run.query, thread_id, state, resume),
            name=f"talos-run-{run.id}",
        )
        self._tasks[run.id] = task

    async def _drive(
        self,
        run_id: uuid.UUID,
        session_id: uuid.UUID,
        query: str,
        thread_id: str,
        state: dict[str, Any],
        resume: Resume | None,
    ) -> None:
        try:
            async for item in self.driver.run(
                state, query=query, thread_id=thread_id, resume=resume
            ):
                if isinstance(item, Pause):
                    await self.store.set_run_status(
                        run_id,
                        "waiting",
                        pending_interrupt=item.value,
                        translator_state=state,
                    )
                    await self._publish(
                        run_id, "interrupt", kind=item.kind, payload=pending_payload(item.value)
                    )
                    return
                type_, data = item
                if type_ == "answer.done":
                    await self.store.add_message(
                        session_id,
                        "assistant",
                        data.get("html") or "",
                        note=data.get("note"),
                        chips=data.get("chips") or [],
                        run_id=run_id,
                    )
                elif type_ == "run.finished":
                    await self.store.set_run_status(
                        run_id,
                        data["status"],
                        translator_state=state,
                        pending_interrupt=None,
                        summary=data["summary"],
                        summary_gold=bool(data.get("summary_gold")),
                        forged=data.get("forged") or [],
                        used=data.get("used") or [],
                        failed=bool(state.get("failed")),
                    )
                await self._publish(run_id, type_, **data)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any driver failure ends the run cleanly
            log.exception("run %s failed", run_id)
            message = f"{type(e).__name__}: {e}"
            forged, used = list(state.get("forged") or []), list(state.get("used") or [])
            await self.store.set_run_status(
                run_id,
                "failed",
                translator_state=state,
                pending_interrupt=None,
                error=message,
                summary=copy.SUMMARY_FAILED,
                summary_gold=False,
                forged=forged,
                used=used,
                failed=True,
            )
            await self._publish(run_id, "error", message=message)
            await self._publish(
                run_id,
                "run.finished",
                status="failed",
                summary=copy.SUMMARY_FAILED,
                summary_gold=False,
                forged=forged,
                used=used,
            )
        finally:
            if self._tasks.get(run_id) is asyncio.current_task():
                self._tasks.pop(run_id, None)
                self._states.pop(run_id, None)


def _resume_for(pending: dict[str, Any], decision: str, value: str | None) -> Resume:
    """Map a browser decision onto the graph's resume value (spec 02 §4 Resume rules)."""
    kind = str(pending.get("type"))
    if kind == "confirm_exec":
        if decision == "approve":
            return Resume(
                kind,
                decision,
                {
                    "approved": True,
                    "args": list(pending.get("args") or []),
                    "kwargs": dict(pending.get("kwargs") or {}),
                },
            )
        if decision == "decline":
            return Resume(kind, decision, {"approved": False})
        raise BadDecision("An approval takes approve or decline.")
    if kind == "missing_api_key":
        if decision == "save":
            key = (value or "").strip()
            if not key:
                raise BadDecision("Paste the key first, or choose Skip.")
            return Resume(kind, decision, key)
        if decision == "skip":
            return Resume(kind, decision, "skip")
        raise BadDecision("A key request takes save or skip.")
    raise BadDecision(f"Unknown pause kind {kind!r}.")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_runner.py tests/web/test_graph_driver.py -v`
Expected: PASS. `test_new_input_after_a_pause_starts_a_fresh_turn` is the spec 02 §6 check on the pinned LangGraph: if it ever fails after an upgrade, make `stop` clear the thread with `await graph.aupdate_state(config, None, as_node="orchestrator_out")` before finishing the run.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/runner.py tests/web/stubs.py tests/web/test_runner.py tests/web/test_graph_driver.py
git commit -m "[Feat]: Add the RunManager and the graph driver"
```

---

### Task 7: Fake graph mode

**Files:**
- Create: `talos/web/fake_graph.py`
- Test: `tests/web/test_fake_graph.py`

**Interfaces:**
- Consumes: `Board`, `new_state` (Task 3), `copy` (Task 2), `demo_sources` (Task 3), `naming.classify`, `naming.weather_city` (Task 2), `runner.Emitted`, `Pause`, `Resume` (Task 6), `schemas.vault_entry` (Task 3), `SkillManager.register/get/remove/record_usage/record_failure/all`, `settings.auto_approve_exec()` (Task 1); in tests, `tests.web.chunks.load`, `tests.web.test_translator.types`, `tests.web.test_copy.reference_text`.
- Produces: `FakeDriver(vault: SkillManager)` implementing `Driver` (`.vault`, `.saved_keys: set[str]`); `make_fake_vault(source: Path | None = None) -> tuple[SkillManager, Path]`; helpers `caesar(text, shift, mode) -> str`, `py_str(value) -> str`, `parse_caesar(text) -> dict` (`text, shift, word, mode`), `run_python(code) -> str | None`, `python_code(query) -> str`; constants `CAESAR_TESTS`, `CAESAR_FAIL_WHY`, `CAESAR_RETRY_NOTE`, `CAESAR_SMOKE_CALL`, `CAESAR_SAVED_SUB`, `CAESAR_TYPE_ERROR`, `WEATHER_TESTS`, `WEATHER_NO_KEY`, `PYTHON_DEFAULT`, `NUM_WORDS`, `DEMO_TOOLS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_fake_graph.py`:

```python
"""The fake graph replays the demo's flows as contract events (spec 02 §9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.config import settings
from talos.vault.manager import SkillManager
from talos.web import fake_graph
from talos.web.fake_graph import FakeDriver, make_fake_vault, parse_caesar, run_python
from talos.web.runner import Pause, Resume
from talos.web.translator import EventTranslator
from tests.web import chunks
from tests.web.test_copy import reference_text
from tests.web.test_translator import types


@pytest.fixture
def driver(tmp_path: Path) -> FakeDriver:
    return FakeDriver(SkillManager(vault_dir=tmp_path / "vault"))


@pytest.fixture(autouse=True)
def ask_before_exec():
    settings.set_auto_approve_override(False)
    yield
    settings.set_auto_approve_override(None)


async def drive(driver: FakeDriver, query: str, state=None, resume: Resume | None = None):
    state = state if state is not None else driver.initial_state()
    items = [item async for item in driver.run(state, query=query, thread_id="t", resume=resume)]
    pause = items[-1] if items and isinstance(items[-1], Pause) else None
    events = [item for item in items if not isinstance(item, Pause)]
    return state, events, pause


def data(events, type_):
    return [d for t, d in events if t == type_]


def translated(*names, resume=None):
    tr = EventTranslator()
    out = []
    for i, name in enumerate(names):
        if i:
            out += tr.resumed(*resume)
        for chunk in chunks.load(name):
            out += tr.feed(chunk)
    return out + ([] if tr.pause else tr.finish())


CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
DECRYPT_Q = 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"
WEATHER_Q = "Use the OpenWeatherMap API to get the current temperature in Mumbai."


async def test_caesar_forge_then_reuse(driver):
    _, events, pause = await drive(driver, CAESAR_Q)
    assert pause is None
    code = data(events, "forge.code")
    assert [(c["attempt"], c["changed"]) for c in code] == [(1, None), (2, 48)]
    assert code[0]["lines"][47] == "    effective_shift = shift"
    assert code[1]["note"] == fake_graph.CAESAR_RETRY_NOTE
    first_tests = data(events, "forge.tests")[0]["results"]
    assert [r["passed"] for r in first_tests] == [True, False, True, True, True]
    assert first_tests[1]["why"] == "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'"
    assert data(events, "forge.smoke") == [
        {"call": fake_graph.CAESAR_SMOKE_CALL, "result": "'AHSVZ HNLUA'", "passed": True}
    ]
    assert data(events, "vault.saved")[0]["sub"] == fake_graph.CAESAR_SAVED_SUB
    assert driver.vault.get("caesar_cipher") is not None
    assert data(events, "answer.done")[0] == {
        "html": (
            '"TALOS AGENT" encrypted with a shift of 7 is <span class="mono">AHSVZ HNLUA</span>.'
        ),
        "note": 'The same tool decrypts too. Ask with "decrypt" and the same shift.',
        "chips": [{"kind": "forged", "text": "Forged caesar_cipher"}],
    }
    assert events[-1] == (
        "run.finished",
        {
            "status": "done",
            "summary": "1 tool forged, 2 attempts",
            "summary_gold": True,
            "forged": ["caesar_cipher"],
            "used": ["caesar_cipher"],
        },
    )

    _, events, _ = await drive(driver, DECRYPT_Q)
    assert data(events, "strip.set")[0]["variant"] == "vault"
    assert data(events, "answer.done")[0]["html"] == (
        'It decrypts to <span class="mono">TALOS AGENT</span>.'
    )
    assert events[-1][1]["summary"] == "0 tools forged"
    assert driver.vault.get("caesar_cipher")["usage_count"] == 2


async def test_word_shift_fails_then_prunes(driver):
    await drive(driver, CAESAR_Q)
    word_q = 'Decrypt "AHSVZ HNLUA" with a shift of three'
    _, events, _ = await drive(driver, word_q)
    args = data(events, "call.args")[0]["args"]
    assert args[1] == ["shift", '"three"', True]
    assert data(events, "call.error")[0] == {
        "error": "TypeError: shift must be an int, got str",
        "when": "run",
    }
    assert data(events, "vault.failure")[0]["streak"] == 1
    assert data(events, "answer.done")[0]["note"] == 'Ask again with "shift 3" and it should work.'
    assert events[-1][1]["summary"] == "Failed, 1 failure in a row"

    _, events, _ = await drive(driver, word_q)
    assert data(events, "vault.failure")[0]["pruned"] is True
    assert {"label": "vault", "text": "removed after 2 failures in a row", "tone": "plain"} in (
        data(events, "log.line")
    )
    assert events[-1][1]["summary"] == "Failed, removed from the vault"
    assert driver.vault.get("caesar_cipher") is None


async def test_python_pauses_for_approval_then_runs(driver):
    state, events, pause = await drive(driver, PYTHON_Q)
    assert pause.kind == "confirm_exec"
    assert pause.value["kwargs"] == {"code": "print(sum(range(1, 101)))"}
    assert data(events, "node.started")[-1] == {
        "step": "executor",
        "label": "Executor, waiting for you",
    }
    approve = Resume("confirm_exec", "approve", {"approved": True})
    _, events, pause = await drive(driver, PYTHON_Q, state, approve)
    assert pause is None
    assert data(events, "call.result")[0] == {"repr": "5050", "type": "stdout", "small": True}
    assert data(events, "answer.done")[0]["html"] == (
        'The code prints <span class="mono">5050</span>.'
    )
    assert events[-1][1]["summary"] == "Built-in, approved"


async def test_python_decline(driver):
    state, _, _ = await drive(driver, PYTHON_Q)
    _, events, _ = await drive(driver, PYTHON_Q, state, Resume("confirm_exec", "decline", None))
    assert events[-1][1]["status"] == "declined"
    assert events[-1][1]["summary"] == "Declined, nothing ran"
    assert data(events, "answer.done")[0]["html"] == (
        "I didn't run the code, so I don't have its output."
    )


async def test_python_without_asking_when_the_setting_is_off(driver):
    settings.set_auto_approve_override(True)
    _, events, pause = await drive(driver, PYTHON_Q)
    assert pause is None
    assert {
        "html": 'Ran without asking, because "Ask before running code" is off in Settings.'
    } in (data(events, "caption"))


async def test_weather_key_save_then_reuse(driver):
    state, events, pause = await drive(driver, WEATHER_Q)
    assert pause.kind == "missing_api_key"
    assert pause.value["env_var"] == "OPENWEATHERMAP_API_KEY"
    save = Resume("missing_api_key", "save", None)  # the fake never sees the value
    _, events, _ = await drive(driver, WEATHER_Q, state, save)
    assert data(events, "call.result")[0]["repr"] == "Not called in this demo"
    assert events[-1][1]["summary"] == "1 tool forged, key saved"
    assert driver.saved_keys == {"OPENWEATHERMAP_API_KEY"}

    _, events, pause = await drive(driver, "What's the temperature in Pune?")
    assert pause is None and data(events, "strip.set")[0]["variant"] == "vault"
    assert data(events, "answer.done")[0]["note"] == (
        "In Talos, you'd get the current temperature in Pune here."
    )


async def test_weather_key_skip_fails_without_the_key(driver):
    state, _, _ = await drive(driver, WEATHER_Q)
    _, events, _ = await drive(driver, WEATHER_Q, state, Resume("missing_api_key", "skip", "skip"))
    assert data(events, "node.finished")[0] == {
        "step": "human",
        "status": "done",
        "label": "Human check, skipped",
    }
    assert events[-1][1]["summary"] == "1 tool forged, failed without a key"


async def test_chat_and_unknown(driver):
    _, events, _ = await drive(driver, "What can you do?")
    assert events[-1][1]["summary"] == "Answered directly"
    _, events, _ = await drive(driver, "Sort these numbers please")
    assert events[-1][1]["summary"] == "Not in this demo"


@pytest.mark.parametrize(
    ("query", "names", "resume", "fake_resume"),
    [
        (CAESAR_Q, ("forge_retry",), None, None),
        ("What can you do?", ("chat",), None, None),
        (
            PYTHON_Q,
            ("exec_pause", "exec_approve"),
            ("confirm_exec", "approve"),
            Resume("confirm_exec", "approve", None),
        ),
        (
            WEATHER_Q,
            ("key_pause", "key_skip"),
            ("missing_api_key", "skip"),
            Resume("missing_api_key", "skip", "skip"),
        ),
    ],
)
async def test_fake_events_come_in_the_same_order_as_the_real_graphs(
    driver, query, names, resume, fake_resume
):
    state, events, pause = await drive(driver, query)
    if fake_resume is not None:
        _, more, _ = await drive(driver, query, state, fake_resume)
        events += more
    assert types(events) == types(translated(*names, resume=resume))


async def test_reuse_order_matches_the_real_vault_run(driver):
    await drive(driver, CAESAR_Q)
    _, events, _ = await drive(driver, DECRYPT_Q)
    assert types(events) == types(translated("vault"))


def test_demo_values_appear_in_the_reference():
    text = reference_text()
    for value in (
        *fake_graph.CAESAR_TESTS,
        *fake_graph.WEATHER_TESTS,
        fake_graph.CAESAR_FAIL_WHY,
        fake_graph.CAESAR_RETRY_NOTE,
        fake_graph.CAESAR_SMOKE_CALL,
        fake_graph.CAESAR_SAVED_SUB,
        fake_graph.CAESAR_TYPE_ERROR,
        fake_graph.WEATHER_NO_KEY,
        fake_graph.PYTHON_DEFAULT,
    ):
        assert value in text, value


def test_parse_caesar_matches_the_demo():
    assert parse_caesar(CAESAR_Q) == {
        "text": "TALOS AGENT",
        "shift": 7,
        "word": None,
        "mode": "encrypt",
    }
    assert parse_caesar(DECRYPT_Q)["mode"] == "decrypt"
    assert parse_caesar("encrypt it with shift of three")["word"] == "three"
    assert parse_caesar("decrypt it")["text"] == "AHSVZ HNLUA"


@pytest.mark.parametrize(
    ("code", "out"),
    [
        ("print(sum(range(1, 101)))", "5050"),
        ("print('hi')", "hi"),
        ("print(2 + 3 * 4)", "14"),
        ("print(7 / 2)", "3.5"),
        ("print(8 / 2)", "4"),
        ("print(9 ** 9 ** 9)", None),
        ("print(1 / 0)", None),
        ("import os", None),
    ],
)
def test_run_python_only_runs_simple_prints(code, out):
    assert run_python(code) == out


def test_fake_vault_is_a_copy_without_the_demo_tools(tmp_path: Path):
    source = SkillManager(vault_dir=tmp_path / "src")
    for name in ("caesar_cipher", "slugify"):
        source.register({"name": name, "function": name}, f"def {name}():\n    pass\n")
    vault, root = make_fake_vault(tmp_path / "src")
    assert [e["name"] for e in vault.all()] == ["slugify"]
    assert (root / "tools" / "caesar_cipher.py").exists()  # files stay, like remove()
    vault.remove("slugify")
    assert source.get("slugify") is not None  # the real vault is untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_fake_graph.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'talos.web.fake_graph'`.

- [ ] **Step 3: Implement the fake graph**

Create `talos/web/fake_graph.py`:

```python
"""TALOS_FAKE_GRAPH=1: the demo's scripted runs as contract events, no model calls.

`FakeDriver` replaces `GraphDriver`. It routes with the demo's `classify()`
and replays its flows (`flowCaesar`, `executeCaesar`, `flowPython`,
`flowWeather`, `flowChat`, `flowUnknown`, with `planner`, `forgeTool`,
`humanCheck` and `learn`), emitting the same events, in the same order, as
`EventTranslator` does for the equivalent real run. Values are the demo's:
the Caesar retry on line 48, its five tests, the word-number shift failure,
`print(sum(range(1, 101)))`, the OpenWeatherMap key.

- Pauses are real: the run waits, and `/resume` continues it (also after
  an app restart, because the flow's position lives in the saved state).
- It really updates a vault: a temporary copy of the vault folder
  (`make_fake_vault`), so the Vault page shows forged tools and failures.
- A saved API key is only remembered as "set" in memory. Its value never
  reaches this module, and nothing is written to `.env`.

Vault list questions fall through to the "not in this demo" flow.
"""

from __future__ import annotations

import ast
import html
import json
import operator
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD, SkillManager
from talos.web import copy
from talos.web.board import Board, new_state
from talos.web.demo_sources import (
    CAESAR,
    CAESAR_BAD_LINE,
    CAESAR_BAD_SOURCE,
    CAESAR_SOURCE,
    WEATHER,
    WEATHER_SOURCE,
)
from talos.web.naming import classify, weather_city
from talos.web.runner import Emitted, Pause, Resume
from talos.web.schemas import vault_entry

# Scripted values from the demo (docs/superpowers/specs/reference/workbench-demo).
CAESAR_TESTS = [
    "test_encrypt_shifts_forward",
    "test_decrypt_reverses_encrypt",
    "test_preserves_case_and_spaces",
    "test_wraps_past_z",
    "test_rejects_unknown_mode",
]
CAESAR_FAIL_WHY = "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'"
CAESAR_RETRY_NOTE = "Line 48 is new in attempt 2. Decrypt now shifts backwards instead of forwards."
CAESAR_SMOKE_CALL = 'caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")'
CAESAR_SAVED_SUB = (
    "Next time a request needs a Caesar cipher, Talos skips forging and goes straight to Execute."
)
CAESAR_TYPE_ERROR = "TypeError: shift must be an int, got str"
WEATHER_TESTS = [
    "test_reads_temperature_from_response",
    "test_raises_when_key_missing",
    "test_raises_on_unknown_city",
]
WEATHER_NO_KEY = "RuntimeError: OPENWEATHERMAP_API_KEY is not set"
PYTHON_DEFAULT = "print(sum(range(1, 101)))"
PYTHON_SIG = {"name": "python_exec", "args": "code: str, timeout: int | None = None", "ret": "dict"}
NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
}  # fmt: skip
DEMO_TOOLS = (CAESAR["name"], WEATHER["name"])


def make_fake_vault(source: Path | None = None) -> tuple[SkillManager, Path]:
    """Copy the vault into a temp folder, minus the two tools the demo forges live.

    Args:
        source: Vault folder to copy (default `settings.VAULT_DIR`).

    Returns:
        A SkillManager on the copy, and the temp folder (delete it on shutdown).
    """
    source = source or settings.VAULT_DIR
    root = Path(tempfile.mkdtemp(prefix="talos_fake_vault_"))
    if source.is_dir():
        shutil.copytree(source, root, dirs_exist_ok=True)
    vault = SkillManager(vault_dir=root)
    for name in DEMO_TOOLS:
        vault.remove(name)
    return vault, root


# ---- the demo's helpers, ported ---------------------------------------------------


def caesar(text: str, shift: int, mode: str) -> str:
    """The demo's `caesar()`: rotate ASCII letters, keep everything else."""
    k = (-shift if mode == "decrypt" else shift) % 26
    out = []
    for c in text:
        if "A" <= c <= "Z":
            out.append(chr((ord(c) - 65 + k) % 26 + 65))
        elif "a" <= c <= "z":
            out.append(chr((ord(c) - 97 + k) % 26 + 97))
        else:
            out.append(c)
    return "".join(out)


def py_str(value: str) -> str:
    """The demo's `pyStr`: a Python-style single-quoted repr."""
    return "'" + value.replace("'", "\\'") + "'"


def parse_caesar(text: str) -> dict[str, Any]:
    """The demo's `parseCaesar`: quoted text, mode, and a numeric or word shift."""
    quoted = re.search(r"[\"“]([^\"”]+)[\"”]", text)
    before = text[: quoted.start()] if quoted else text
    verbs = list(re.finditer(r"\b(en|de)(?:crypt|code)", before, re.I))
    mode = "encrypt"
    if verbs:
        mode = "decrypt" if verbs[-1].group(1).lower() == "de" else "encrypt"
    shift, word = 7, None
    number = re.search(r"shift(?:\s+of)?\s*(?:=|:)?\s*(-?\d+)", text, re.I)
    named = re.search(r"shift(?:\s+of)?\s+([a-z]+)", text, re.I)
    if number:
        shift = int(number.group(1))
    elif named and not re.fullmatch(r"of|to|by", named.group(1), re.I):
        word = named.group(1).lower()
    default = "AHSVZ HNLUA" if mode == "decrypt" else "TALOS AGENT"
    return {
        "text": quoted.group(1) if quoted else default,
        "shift": shift,
        "word": word,
        "mode": mode,
    }


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _arith(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_arith(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _arith(node.left), _arith(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    raise ValueError("not arithmetic")


def run_python(code: str) -> str | None:
    """The demo's `runPython`: only `print(...)` of a literal, sum(range) or arithmetic."""
    match = re.fullmatch(r"print\((.*)\)", code.strip(), re.S)
    if not match:
        return None
    inner = match.group(1).strip()
    summed = re.fullmatch(r"sum\(range\((-?\d+)\s*,\s*(-?\d+)\)\)", inner)
    if summed:
        return str(sum(range(int(summed.group(1)), int(summed.group(2)))))
    literal = re.fullmatch(r"([\"'])(.*)\1", inner, re.S)
    if literal:
        return literal.group(2)
    if re.fullmatch(r"[\d\s+\-*/().%]+", inner):
        try:
            value = _arith(ast.parse(inner, mode="eval").body)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
            return None
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return None
            return str(int(value)) if value.is_integer() else repr(value)
        return str(value)
    return None


def python_code(query: str) -> str:
    """The code in a query: `backticks`, else after a colon, else the demo default."""
    match = re.search(r"`([^`]+)`", query) or re.search(r":\s*(.+)$", query)
    return match.group(1).strip() if match else PYTHON_DEFAULT


def _plain(html_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", html_text))


# ---- the driver -------------------------------------------------------------------------


class FakeDriver:
    """Scripted runs (see module doc).

    Args:
        vault: The vault the fake forges into (use `make_fake_vault()`).
    """

    def __init__(self, vault: SkillManager) -> None:
        self.vault = vault
        self.saved_keys: set[str] = set()

    def initial_state(self) -> dict[str, Any]:
        return {**new_state(), "flow": None, "phase": None, "p": {}, "attempts": 0}

    async def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]:
        b = Board(state)
        if resume is None:
            kind = classify(query)
            state["flow"] = kind if kind in ("caesar", "python", "weather", "chat") else "unknown"
            pause = getattr(self, f"_flow_{state['flow']}")(b, query)
        else:
            pause = self._resume(b, resume)
        for event in b.drain():
            yield event
        if pause is not None:
            yield pause

    def _resume(self, b: Board, resume: Resume) -> Pause | None:
        state = b.state
        b.pop()
        if state["phase"] == "approve":
            if resume.decision == "approve":
                b.log(copy.LOG_EXEC_RUNNING, "g", caret=True)
                return self._run_code(b, approved=True)
            return self._declined(b)
        # missing_api_key
        env = WEATHER["env"]
        if resume.decision == "save":
            self.saved_keys.add(env)
            b.log(copy.LOG_CHECK_SAVED)
            b.finish("human", "done")
            b.caption(copy.CAPTION_HUMAN_SAVED.format(env=env))
        else:
            b.log(copy.LOG_CHECK_SKIPPED)
            b.finish("human", "done", copy.LABEL_HUMAN_SKIPPED)
            b.caption(copy.CAPTION_HUMAN_SKIPPED)
        b.status(copy.STATUS_FORGING, gold=True)
        b.flow("human", "learn")
        self._learn(b, WEATHER, WEATHER_SOURCE, copy.SAVED_SUB_KEY)
        self._execute_weather(b)
        return None

    # ---- shared steps (the demo's planner, forgeTool, humanCheck, learn) -------------------

    def _planner(
        self,
        b: Board,
        *,
        variant: str,
        needs: str | None,
        tool_hint: str | None,
        label: str,
        sig: dict[str, str] | None,
        log_line: tuple[str, str],
        caption: str,
    ) -> None:
        b.start("planner")
        b.caption(copy.CAPTION_PLANNING)
        b.talos(copy.TALOS_PLANNING)
        subtasks = []
        if needs:
            subtasks = [
                {"id": 1, "action": label, "needs": needs, "tool_hint": tool_hint, "depends_on": []}
            ]
        b.emit("plan.ready", subtasks=subtasks, verdict="feasible")
        total = 1 if needs else 0
        b.strip(variant, index=total, total=total, label=label, sig=sig)
        b.finish("planner", "done")
        b.log(log_line)
        b.caption(caption)

    def _forge(
        self,
        b: Board,
        meta: dict[str, Any],
        attempts: list[tuple[str, int | None, str | None]],
        tests: list[str],
        fail_index: int,
        fail_why: str,
        smoke: tuple[str, str] | None,
    ) -> None:
        tool = meta["name"]
        b.status(copy.STATUS_FORGING, gold=True)
        b.log(copy.LOG_VAULT_MISS)
        b.flow("planner", "forger")
        total = len(tests)
        for a, (source, changed, note) in enumerate(attempts):
            n = a + 1
            if a == 0:
                b.start("forger")
                b.talos(copy.TALOS_WRITING.format(tool=tool))
                b.caption(copy.CAPTION_FORGER_FIRST.format(tool=tool))
                b.log(copy.LOG_FORGE_FIRST, "g", tool=tool)
            else:
                b.finish("tester", "forge")
                b.start("forger")
                b.caption(copy.CAPTION_FORGER_RETRY.format(n=n, max=settings.FORGE_MAX_RETRIES))
                b.log(copy.LOG_FORGE_RETRY, "g", n=n)
            b.emit(
                "forge.code",
                tool=tool,
                attempt=n,
                file=f"{tool}.py",
                lines=source.split("\n"),
                changed=changed,
                note=note,
            )
            b.finish("forger", "forge")
            b.flow("forger", "tester")
            b.start("tester")
            b.caption(
                copy.CAPTION_TESTER.format(
                    n=n,
                    max=settings.FORGE_MAX_RETRIES,
                    k=total,
                    timeout=settings.SUBPROCESS_TIMEOUT,
                )
            )
            b.log(copy.LOG_TEST_RUNNING, "g", caret=True)
            fail = a == 0 and fail_index >= 0 and len(attempts) > 1
            results = [
                {
                    "name": name,
                    "passed": not (fail and i == fail_index),
                    "why": fail_why if fail and i == fail_index else None,
                }
                for i, name in enumerate(tests)
            ]
            b.pop()
            b.emit("forge.tests", tool=tool, attempt=n, results=results)
            if fail:
                b.log(copy.LOG_TEST_RETRYING, "g", passed=total - 1, total=total)
                b.sub(tests[fail_index])
                b.emit(
                    "forge.attempt", attempt=n, ok=False, detail=f"{tests[fail_index]}\n{fail_why}"
                )
                b.talos(copy.TALOS_RETRYING)
            else:
                b.log(copy.LOG_TEST_PASSED, "g", total=total)
        if smoke is not None:
            b.caption(copy.CAPTION_SMOKE)
            b.emit("forge.smoke", call=smoke[0], result=smoke[1], passed=True)
            b.log(copy.LOG_SMOKE, result=smoke[1])
        b.emit(
            "forge.attempt",
            attempt=len(attempts),
            ok=True,
            detail=copy.DETAIL_TESTS_PASSED.format(total=total),
        )
        b.state["attempts"] = len(attempts)
        b.finish("tester", "forge")
        b.flow("tester", "human")

    def _human(self, b: Board, meta: dict[str, Any]) -> Pause | None:
        env = meta.get("env")
        if not env:
            b.finish("human", "skip")
            b.caption(copy.CAPTION_HUMAN_SKIP)
            b.flow("human", "learn")
            return None
        if env in self.saved_keys:
            b.finish("human", "skip")
            b.caption(copy.CAPTION_HUMAN_KEY_SET.format(env=env))
            b.log(copy.LOG_CHECK_KEY_SET)
            b.flow("human", "learn")
            return None
        b.start("human")
        b.caption(copy.CAPTION_HUMAN_WAIT.format(tool=meta["name"], env=env))
        b.log(copy.LOG_CHECK_WAITING, "g", caret=True)
        b.status(copy.STATUS_WAITING, gold=True)
        b.talos(copy.TALOS_NEEDS_KEY)
        b.state["phase"] = "key"
        return Pause(
            "missing_api_key",
            {
                "type": "missing_api_key",
                "env_var": env,
                "tool_name": meta["name"],
                "message": f"The forged tool '{meta['name']}' needs the env var {env}.",
            },
        )

    def _learn(self, b: Board, meta: dict[str, Any], source: str, sub: str) -> None:
        b.start("learn")
        b.caption(copy.CAPTION_LEARN)
        saved = self.vault.register(
            {
                "name": meta["name"],
                "function": meta["name"],
                "description": meta["description"],
                "keywords": list(meta["keywords"]),
                "signature": f"{meta['name']}({meta['args']}) -> {meta['ret']}",
            },
            source + "\n",
        )
        b.finish("learn", "done")
        b.log(copy.LOG_LEARN)
        b.emit("vault.saved", tool=vault_entry(saved, source).model_dump(), sub=sub)
        b.flow("learn", "executor")
        b.add_forged(meta["name"])

    def _answer(
        self,
        b: Board,
        html_text: str,
        note: str | None,
        chips: list[dict[str, str]],
        *,
        status: str,
        summary: str,
        gold: bool = False,
    ) -> None:
        b.emit("answer.delta", text=_plain(html_text))
        b.finish("answer", "answer")
        b.emit("answer.done", html=html_text, note=note, chips=chips)
        b.finished(status, summary, gold=gold)

    def _vault_hit(self, b: Board, tool: str) -> None:
        b.flow("planner", "vault")
        b.finish("vault", "done")
        b.log(copy.LOG_VAULT_HIT, tool=tool)
        b.status(copy.STATUS_NONE_FORGED, tone="warm")
        b.talos(copy.TALOS_FOUND.format(tool=tool))
        b.flow("vault", "skip")
        b.flow("skip", "executor")

    def _vault_failure(self, b: Board, tool: str, error: str) -> dict[str, Any]:
        before = self.vault.get(tool) or {}
        pruned = self.vault.record_failure(tool, reason=error)
        streak = int(before.get("consecutive_failures", 0)) + 1
        if pruned:
            b.log(copy.LOG_VAULT_REMOVED, prune=_AUTO_PRUNE_THRESHOLD)
        else:
            b.log(copy.LOG_VAULT_STREAK, streak=streak)
        b.emit("vault.failure", tool=tool, streak=streak, pruned=pruned, error=error)
        return {"streak": streak, "pruned": pruned}

    # ---- flows -------------------------------------------------------------------------------

    def _flow_caesar(self, b: Board, query: str) -> Pause | None:
        p = parse_caesar(query)
        b.state["p"] = p
        sig = {"name": CAESAR["name"], "args": CAESAR["args"], "ret": CAESAR["ret"]}
        if self.vault.get(CAESAR["name"]) is None:
            self._planner(
                b,
                variant="forge",
                needs="forge",
                tool_hint=None,
                label=copy.LABEL_FORGE.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_FORGE,
                caption=copy.CAPTION_PLAN_FORGE,
            )
            self._forge(
                b,
                CAESAR,
                [
                    (CAESAR_BAD_SOURCE, None, None),
                    (CAESAR_SOURCE, CAESAR_BAD_LINE, CAESAR_RETRY_NOTE),
                ],
                CAESAR_TESTS,
                1,
                CAESAR_FAIL_WHY,
                (CAESAR_SMOKE_CALL, "'AHSVZ HNLUA'"),
            )
            self._human(b, CAESAR)
            self._learn(b, CAESAR, CAESAR_SOURCE, CAESAR_SAVED_SUB)
            self._execute_caesar(b, p, after_forge=True)
        else:
            self._planner(
                b,
                variant="vault",
                needs="vault",
                tool_hint=CAESAR["name"],
                label=copy.LABEL_VAULT.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_VAULT,
                caption=copy.CAPTION_PLAN_VAULT_KEYWORDS.format(
                    tool=CAESAR["name"], keywords=copy.join_words(["caesar", "cipher", p["mode"]])
                ),
            )
            self._vault_hit(b, CAESAR["name"])
            self._execute_caesar(b, p, after_forge=False)
        return None

    def _execute_caesar(self, b: Board, p: dict[str, Any], *, after_forge: bool) -> None:
        tool = CAESAR["name"]
        b.add_used(tool)
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool=tool))
        b.caption(copy.CAPTION_EXECUTOR)
        word = p["word"]
        shift_repr = json.dumps(word) if word else str(p["shift"])
        b.emit(
            "call.args",
            tool=tool,
            args=[
                ["text", json.dumps(p["text"]), False],
                ["shift", shift_repr, bool(word)],
                ["mode", json.dumps(p["mode"]), False],
            ],
            caption=copy.ARGS_CAPTION,
        )
        if word:
            b.emit("call.error", error=CAESAR_TYPE_ERROR, when="run")
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type="TypeError")
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            health = self._vault_failure(b, tool, CAESAR_TYPE_ERROR)
            b.flow("executor", "answer")
            b.start("answer")
            b.caption(copy.CAPTION_FAILED)
            digit = NUM_WORDS.get(word)
            summary = (
                copy.SUMMARY_FAILED_PRUNED
                if health["pruned"]
                else copy.SUMMARY_FAILED_STREAK.format(streak=health["streak"])
            )
            self._answer(
                b,
                copy.ANSWER_CAESAR_FAILED.format(mode=p["mode"], word=html.escape(word)),
                copy.NOTE_RETRY_DIGIT.format(digit=digit)
                if digit is not None
                else copy.NOTE_RETRY_NUMBER,
                [
                    {
                        "kind": "failed",
                        "text": copy.CHIP_FAILED.format(tool=tool, error_type="TypeError"),
                    }
                ],
                status="done",
                summary=summary,
            )
            return
        out = caesar(p["text"], p["shift"], p["mode"])
        self.vault.record_usage(tool)
        b.emit("call.result", repr=py_str(out), type="str", small=True)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE, "w")
        b.flow("executor", "answer")
        b.start("answer")
        if after_forge:
            attempts = b.state["attempts"]
            b.status(copy.STATUS_ONE_FORGED, gold=True)
            b.caption(copy.CAPTION_DONE_FORGED.format(attempts=attempts))
            summary, gold = copy.SUMMARY_FORGED.format(attempts=attempts), True
        else:
            b.caption(copy.CAPTION_DONE_VAULT)
            summary, gold = copy.SUMMARY_REUSED, False
        if p["mode"] == "encrypt":
            answer = copy.ANSWER_ENCRYPTED.format(
                text=html.escape(p["text"]), shift=p["shift"], out=html.escape(out)
            )
            note = copy.NOTE_ENCRYPT_TOO
        else:
            answer = copy.ANSWER_DECRYPTED.format(out=html.escape(out))
            note = copy.NOTE_DECRYPT_TOO
        chip = (
            {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=tool)}
            if after_forge
            else {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=tool)}
        )
        self._answer(
            b,
            answer,
            note if after_forge else None,
            [chip],
            status="done",
            summary=summary,
            gold=gold,
        )

    def _flow_python(self, b: Board, query: str) -> Pause | None:
        code = python_code(query)
        b.state["p"] = {"code": code}
        self._planner(
            b,
            variant="primitive",
            needs="primitive",
            tool_hint="python_exec",
            label=copy.LABEL_PRIMITIVE.format(i=1, n=1),
            sig=PYTHON_SIG,
            log_line=copy.LOG_PLAN_PRIMITIVE,
            caption=copy.CAPTION_PLAN_PRIMITIVE,
        )
        b.flow("planner", "primitive")
        b.finish("primitive", "done")
        b.flow("primitive", "executor")
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool="python_exec"))
        if not settings.auto_approve_exec():
            b.start("executor", copy.LABEL_EXEC_WAITING)
            b.caption(copy.CAPTION_EXEC_PAUSED.format(tool="python_exec"))
            b.log(copy.LOG_EXEC_PAUSED, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_APPROVE)
            b.state["phase"] = "approve"
            return Pause(
                "confirm_exec",
                {
                    "type": "confirm_exec",
                    "tool": "python_exec",
                    "preview": code,
                    "args": [],
                    "kwargs": {"code": code},
                    "message": "Talos wants to run python_exec. Allow it? [y/N]",
                },
            )
        b.caption(copy.CAPTION_EXEC_AUTO)
        return self._run_code(b, approved=False)

    def _run_code(self, b: Board, *, approved: bool) -> None:
        code = b.state["p"]["code"]
        b.emit(
            "call.args",
            tool="python_exec",
            args=[["code", json.dumps(code), False]],
            caption=copy.ARGS_CAPTION_CODE,
        )
        if approved:
            b.pop()
        out = run_python(code)
        if out is None:
            b.emit("call.result", repr=copy.RESULT_PYTHON_UNSUPPORTED, type="", small=True)
        else:
            b.emit("call.result", repr=out, type="stdout", small=True)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE, "w")
        b.flow("executor", "answer")
        b.start("answer")
        b.status(copy.STATUS_NONE_FORGED)
        b.caption(copy.CAPTION_DONE_PRIMITIVE)
        answer = (
            copy.ANSWER_PYTHON_UNSUPPORTED
            if out is None
            else copy.ANSWER_PYTHON.format(out=html.escape(out))
        )
        summary = copy.SUMMARY_PRIMITIVE_APPROVED if approved else copy.SUMMARY_PRIMITIVE
        self._answer(b, answer, None, [], status="done", summary=summary)

    def _declined(self, b: Board) -> None:
        b.emit("call.error", error="declined by user", when="declined")
        b.finish("executor", "fail", copy.LABEL_EXEC_DECLINED)
        b.log(copy.LOG_EXEC_DECLINED, "w")
        b.status(copy.STATUS_NOT_RUN)
        b.flow("executor", "answer")
        b.start("answer")
        b.caption(copy.CAPTION_DECLINED)
        self._answer(
            b,
            copy.ANSWER_DECLINED,
            copy.NOTE_DECLINED,
            [],
            status="declined",
            summary=copy.SUMMARY_DECLINED,
        )

    def _flow_weather(self, b: Board, query: str) -> Pause | None:
        b.state["p"] = {"city": weather_city(query)}
        tool = WEATHER["name"]
        sig = {"name": tool, "args": WEATHER["args"], "ret": WEATHER["ret"]}
        if self.vault.get(tool) is None:
            self._planner(
                b,
                variant="forge",
                needs="forge",
                tool_hint=None,
                label=copy.LABEL_FORGE.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_FORGE,
                caption=copy.CAPTION_PLAN_FORGE_WEATHER,
            )
            self._forge(b, WEATHER, [(WEATHER_SOURCE, None, None)], WEATHER_TESTS, -1, "", None)
            pause = self._human(b, WEATHER)
            if pause is not None:
                return pause
            self._learn(b, WEATHER, WEATHER_SOURCE, copy.SAVED_SUB_KEY)
        else:
            self._planner(
                b,
                variant="vault",
                needs="vault",
                tool_hint=tool,
                label=copy.LABEL_VAULT.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_VAULT,
                caption=copy.CAPTION_PLAN_VAULT.format(tool=tool),
            )
            self._vault_hit(b, tool)
        self._execute_weather(b)
        return None

    def _execute_weather(self, b: Board) -> None:
        tool, env = WEATHER["name"], WEATHER["env"]
        city = b.state["p"]["city"]
        forged = tool in b.state["forged"]
        b.add_used(tool)
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool=tool))
        b.caption(copy.CAPTION_EXECUTOR_SHORT)
        b.emit(
            "call.args",
            tool=tool,
            args=[["city", json.dumps(city), False]],
            caption=copy.ARGS_CAPTION,
        )
        if env not in self.saved_keys:
            b.emit("call.error", error=WEATHER_NO_KEY, when="run")
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type="RuntimeError")
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            self._vault_failure(b, tool, WEATHER_NO_KEY)
            b.flow("executor", "answer")
            b.start("answer")
            b.caption(copy.CAPTION_FAILED_NO_KEY)
            self._answer(
                b,
                copy.ANSWER_WEATHER_NO_KEY.format(tool=tool, env=env),
                copy.NOTE_WEATHER_NO_KEY,
                [
                    {
                        "kind": "failed",
                        "text": copy.CHIP_FAILED.format(tool=tool, error_type="RuntimeError"),
                    }
                ],
                status="done",
                summary=copy.SUMMARY_FORGED_NO_KEY if forged else copy.SUMMARY_NO_KEY,
                gold=forged,
            )
            return
        self.vault.record_usage(tool)
        b.emit("call.result", repr=copy.RESULT_WEATHER, type="", small=True)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE_WEATHER, "w")
        b.flow("executor", "answer")
        b.start("answer")
        if forged:
            b.status(copy.STATUS_ONE_FORGED, gold=True)
            summary, gold = copy.SUMMARY_FORGED_KEY, True
        else:
            summary, gold = copy.SUMMARY_REUSED, False
        b.caption(copy.CAPTION_DONE_WEATHER)
        chip = (
            {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=tool)}
            if forged
            else {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=tool)}
        )
        self._answer(
            b,
            copy.ANSWER_WEATHER,
            copy.NOTE_WEATHER.format(city=html.escape(city)),
            [chip],
            status="done",
            summary=summary,
            gold=gold,
        )

    def _flow_chat(self, b: Board, query: str) -> Pause | None:
        self._planner(
            b,
            variant="chat",
            needs=None,
            tool_hint=None,
            label=copy.LABEL_CHAT,
            sig=None,
            log_line=copy.LOG_PLAN_CHAT,
            caption=copy.CAPTION_PLAN_CHAT,
        )
        b.status(copy.STATUS_NONE_FORGED)
        b.flow("planner", "answer")
        b.start("answer")
        self._answer(
            b,
            copy.ANSWER_CHAT.format(count=len(self.vault.all())),
            copy.NOTE_CHAT,
            [],
            status="done",
            summary=copy.SUMMARY_CHAT,
        )
        return None

    def _flow_unknown(self, b: Board, query: str) -> Pause | None:
        self._planner(
            b,
            variant="chat",
            needs=None,
            tool_hint=None,
            label=copy.LABEL_UNKNOWN,
            sig=None,
            log_line=copy.LOG_PLAN_UNKNOWN,
            caption=copy.CAPTION_PLAN_UNKNOWN,
        )
        b.status(copy.STATUS_NOTHING_RAN)
        b.flow("planner", "answer")
        b.start("answer")
        self._answer(b, copy.ANSWER_UNKNOWN, None, [], status="done", summary=copy.SUMMARY_UNKNOWN)
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_fake_graph.py -v`
Expected: PASS, including `test_fake_events_come_in_the_same_order_as_the_real_graphs[*]`: the fake and the translator agree event for event.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/fake_graph.py tests/web/test_fake_graph.py
git commit -m "[Feat]: Add fake graph mode replaying the demo's scripted runs"
```

---

### Task 8: App skeleton: lifespan, errors, limits, CORS, static files, health, log redaction

**Files:**
- Create: `talos/web/security.py`, `talos/web/deps.py`, `talos/web/app.py`, `talos/web/routes/__init__.py`, `talos/web/routes/health.py`
- Test: `tests/web/conftest.py`, `tests/web/test_app.py`, `tests/web/test_security.py`

**Interfaces:**
- Consumes: `RunManager`, `RunError`, `Driver`, `GraphDriver` (Task 6), `Store`, `PgStore`, `MemoryStore` (Task 5), `FakeDriver`, `make_fake_vault` (Task 7), `schemas.HealthOut`, `schemas.ResumeIn` (Task 3), `settings.*` (Task 1), stage 1 `init_db`, `dispose_db`, `upgrade_head`, `open_postgres_saver`, `close_postgres_saver`, `build_app`.
- Produces:
  - `talos.web.security`: `REDACTED = "[redacted]"`, `remember_secret(value: str | None) -> None`, `redact(text: str) -> str`, `install_log_redaction() -> None`.
  - `talos.web.deps`: `ASK_BEFORE_EXEC = "ask_before_exec"`; `Services(store, driver, vault, fake_graph=False, aclose=None)`; `ApiError(status, code, message)`; `not_found(what) -> ApiError`; `error_response(status, code, message, **extra) -> JSONResponse`; `install_error_handlers(app)`; dependencies `get_services`, `get_store`, `get_vault`, `get_manager`.
  - `talos.web.app`: `MAX_BODY`, `DEV_ORIGIN`, `STATIC_DIR`, `ServicesFactory`, `BodySizeLimit`, `open_services() -> Services` (production), `create_app(services: ServicesFactory | None = None, *, static_dir: Path | None = STATIC_DIR, dev: bool | None = None) -> FastAPI`. The app keeps `app.state.services` and `app.state.manager`. Routers are included from one tuple in `create_app`; Tasks 9 and 10 add theirs there.
  - `talos.web.routes.health.router` (`GET /api/health`), `app_version() -> str`.
  - `tests/web/conftest.py`: fixtures `dotenv`, `services`, `app`, `client`; helpers `make_app(services, **kwargs)`, `open_client(app)` (async generator), `parse_sse(text) -> list[dict]`, `wait_for_status(client, run_id, *statuses) -> dict`.

- [ ] **Step 1: Write the test fixtures**

Create `tests/web/conftest.py`:

```python
"""App fixtures: the real FastAPI app on MemoryStore + FakeDriver, no database.

httpx's ASGITransport doesn't run the lifespan, so `client` enters it
explicitly. It also buffers each response until the app finishes it, so an
SSE request returns once its stream closes (after `run.finished`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from talos.agents import hitl
from talos.vault.manager import SkillManager
from talos.web.app import create_app
from talos.web.deps import Services
from talos.web.fake_graph import FakeDriver
from talos.web.store import MemoryStore


@pytest.fixture
def dotenv(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setattr(hitl, "DOTENV_PATH", path)
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    return path


@pytest.fixture
def services(tmp_path: Path, dotenv: Path) -> Services:
    vault = SkillManager(vault_dir=tmp_path / "vault")
    return Services(store=MemoryStore(), driver=FakeDriver(vault), vault=vault, fake_graph=True)


def make_app(services: Services, **kwargs: Any) -> FastAPI:
    async def factory() -> Services:
        return services

    return create_app(factory, **{"static_dir": None, "dev": False, **kwargs})


@pytest.fixture
def app(services: Services) -> FastAPI:
    return make_app(services)


async def open_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in open_client(app):
        yield c


def parse_sse(text: str) -> list[dict[str, Any]]:
    """`[{id, event, data}]` from an SSE body; comment lines are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, Any] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if fields:
            fields["data"] = json.loads(fields["data"])
            events.append(fields)
    return events


async def wait_for_status(client: httpx.AsyncClient, run_id: str, *statuses: str) -> dict:
    """Poll GET /api/runs/{id} until its status is one of `statuses` (fake runs are instant)."""
    import asyncio

    for _ in range(200):
        body = (await client.get(f"/api/runs/{run_id}")).json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} never reached {statuses}: {body['status']}")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/web/test_app.py`:

```python
"""App-level behaviour: lifespan, errors, limits, CORS, static files, entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.config import settings
from talos.web.app import open_services
from tests.web.conftest import make_app, open_client


async def test_startup_applies_the_stored_setting_and_recovers(services):
    await services.store.set_setting("ask_before_exec", False)
    session = await services.store.create_session()
    orphan, _ = await services.store.begin_run(session.id, "q", "q", None)
    app = make_app(services)
    async for _client in open_client(app):
        assert settings.auto_approve_exec() is True
        assert (await services.store.get_run(orphan.id)).status == "failed"
    assert settings._auto_approve_override is None  # shutdown resets the override


async def test_open_services_refuses_without_a_database(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        await open_services()


async def test_oversized_bodies_get_413(client):
    response = await client.post("/api/anything", json={"text": "x" * (65 * 1024)})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


async def test_unknown_api_paths_use_the_error_shape(client):
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cors_only_in_dev_mode(services):
    origin = {"Origin": "http://127.0.0.1:5173"}
    async for client in open_client(make_app(services, dev=False)):
        response = await client.get("/api/health", headers=origin)
        assert "access-control-allow-origin" not in response.headers
    async for client in open_client(make_app(services, dev=True)):
        response = await client.get("/api/health", headers=origin)
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        other = await client.get("/api/health", headers={"Origin": "http://evil.test"})
        assert "access-control-allow-origin" not in other.headers


async def test_frontend_is_served_with_an_index_fallback(services, tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Talos</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    async for client in open_client(make_app(services, static_dir=dist)):
        assert "Talos" in (await client.get("/")).text
        assert (await client.get("/assets/app.js")).text == "console.log(1)"
        assert "Talos" in (await client.get("/sessions/whatever")).text
        assert "no" != (await client.get("/../secret.txt")).text
        api = await client.get("/api/nope")
        assert api.status_code == 404 and api.json()["error"]["code"] == "not_found"
```

Create `tests/web/test_security.py`:

```python
"""Log redaction for API key values (spec 02 §10)."""

from __future__ import annotations

import logging

from talos.web import security
from talos.web.runner import RunManager
from talos.web.schemas import ResumeIn
from talos.web.store import MemoryStore
from tests.web.stubs import ScriptDriver

KEY = "owm-" + "5b1d0c9e8a7f6e54"


def test_remembered_secrets_are_redacted_from_every_log_record(caplog):
    security.install_log_redaction()
    security.remember_secret(f"  {KEY}  ")
    caplog.set_level(logging.INFO)
    logging.getLogger("talos.anything").info("got key %s from the dialog", KEY)
    logging.getLogger("uvicorn.error").warning(f"body was {KEY}")
    assert KEY not in caplog.text
    assert caplog.text.count("[redacted]") == 2


def test_redaction_is_installed_once_and_ignores_short_values():
    security.install_log_redaction()
    factory = logging.getLogRecordFactory()
    security.install_log_redaction()
    assert logging.getLogRecordFactory() is factory
    security.remember_secret("abc")
    assert security.redact("abc") == "abc"


def test_resume_value_is_hidden_from_repr():
    assert KEY not in repr(ResumeIn(decision="save", value=KEY))


async def test_run_manager_itself_never_logs_the_value(caplog):
    caplog.set_level(logging.DEBUG)
    store = MemoryStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "save", "zz-" + KEY)
    await manager.join(run_id)
    assert "zz-" + KEY not in caplog.text
    assert "zz-" + KEY not in str([e.data for e in await store.events_after(run_id)])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_app.py tests/web/test_security.py -v`
Expected: collection errors, `ModuleNotFoundError: No module named 'talos.web.app'` / `'talos.web.security'`.

- [ ] **Step 4: Implement log redaction**

Create `talos/web/security.py`:

```python
"""Keep API key values out of logs (spec 02 §10).

A key pasted into the key dialog reaches the server once, in the `/resume`
body. The route calls `remember_secret(value)` before anything else, and
`install_log_redaction()` wraps the logging record factory so every log
record, from any logger or handler (uvicorn's included), has remembered
values replaced by `[redacted]` before it is formatted or stored.
"""

from __future__ import annotations

import logging
from typing import Any

REDACTED = "[redacted]"
_MIN_SECRET = 4
_secrets: set[str] = set()
_installed = False


def remember_secret(value: str | None) -> None:
    """Redact `value` from every log record from now on (process lifetime)."""
    if value and len(value.strip()) >= _MIN_SECRET:
        _secrets.add(value.strip())
        if value != value.strip():
            _secrets.add(value)


def redact(text: str) -> str:
    """`text` with every remembered secret replaced by `[redacted]`."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def install_log_redaction() -> None:
    """Wrap the log record factory once so remembered secrets never reach a handler."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if _secrets:
            try:
                message = record.getMessage()
            except Exception:  # noqa: BLE001 - a bad format string is not our problem
                return record
            cleaned = redact(message)
            if cleaned != message:
                record.msg, record.args = cleaned, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
```

- [ ] **Step 5: Implement the dependencies and error shape**

Create `talos/web/deps.py`:

```python
"""FastAPI dependencies, the services bundle, and the one error shape.

Every error response is `{"error": {"code": ..., "message": ...}}`
(spec 02 §4). Validation errors never echo the request body back, so a
pasted key can't come back in a 422.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from talos.vault.manager import SkillManager
from talos.web.runner import Driver, RunError, RunManager
from talos.web.store import Store

# The app_settings key for "Ask before running code".
ASK_BEFORE_EXEC = "ask_before_exec"


@dataclass
class Services:
    """Everything the app needs, built once at startup."""

    store: Store
    driver: Driver
    vault: SkillManager
    fake_graph: bool = False
    aclose: Callable[[], Awaitable[None]] | None = None


class ApiError(Exception):
    """An error a route raises on purpose: HTTP status, code and message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def error_response(status: int, code: str, message: str, **extra: str) -> JSONResponse:
    """`{"error": {"code", "message", ...extra}}` with the given status."""
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "too_large"}


def install_error_handlers(app: FastAPI) -> None:
    """Map every error to the one JSON shape."""

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RunError)
    async def _run(_: Request, exc: RunError) -> JSONResponse:
        return error_response(exc.status, exc.code, str(exc), **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = str(first.get("msg") or "Invalid request.").removeprefix("Value error, ")
        return error_response(422, "invalid_request", f"{where}: {message}" if where else message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_store(request: Request) -> Store:
    return request.app.state.services.store


def get_vault(request: Request) -> SkillManager:
    return request.app.state.services.vault


def get_manager(request: Request) -> RunManager:
    return request.app.state.manager
```

- [ ] **Step 6: Implement the health route**

Create `talos/web/routes/__init__.py`:

```python
"""API routers, all mounted under /api."""
```

Create `talos/web/routes/health.py`:

```python
"""GET /api/health."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends

from talos.web.deps import Services, get_services
from talos.web.schemas import HealthOut

router = APIRouter()


def app_version() -> str:
    try:
        return version("talos-ai")
    except PackageNotFoundError:
        return "0.0.0"


@router.get("/health", response_model=HealthOut)
async def health(services: Services = Depends(get_services)) -> HealthOut:
    """Liveness plus whether the database answers and which graph is running."""
    return HealthOut(
        ok=True,
        db=await services.store.ping(),
        fake_graph=services.fake_graph,
        version=app_version(),
    )
```

- [ ] **Step 7: Implement the app**

Create `talos/web/app.py` (only the health router for now; Tasks 9 and 10 add theirs to the tuple in `create_app`):

```python
"""create_app(): the FastAPI instance, its lifespan, routers and static files.

Startup (spec 02 §3), in `open_services()` and the lifespan:

1. Refuse to start without DATABASE_URL.
2. `alembic upgrade head` (in a thread: Alembic runs its own event loop).
3. The Postgres checkpointer and `build_app(saver)`, or the fake graph
   with a temporary vault copy when TALOS_FAKE_GRAPH=1.
4. Recovery: runs left `running` by a dead process become `failed`.
5. The stored "Ask before running code" setting is applied.
6. Shutdown stops active runs, then closes the pool and the engine.

Run with one uvicorn worker only: run state and the vault are per process.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from talos.config import settings
from talos.web.deps import (
    ASK_BEFORE_EXEC,
    ApiError,
    Services,
    error_response,
    install_error_handlers,
)
from talos.web.routes import health
from talos.web.runner import RunManager
from talos.web.security import install_log_redaction

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024
DEV_ORIGIN = "http://127.0.0.1:5173"
STATIC_DIR = settings.PROJECT_ROOT / "frontend" / "dist"

ServicesFactory = Callable[[], Awaitable[Services]]


class BodySizeLimit:
    """Reject request bodies over `max_bytes` (by Content-Length) with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_bytes:
                response = error_response(413, "too_large", "Request body is over 64 KB.")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def open_services() -> Services:
    """Production services from the environment (see the module doc)."""
    from talos.graph import build_app
    from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
    from talos.persistence.db import dispose_db, init_db
    from talos.persistence.migrations import upgrade_head
    from talos.vault.manager import SkillManager
    from talos.web.fake_graph import FakeDriver, make_fake_vault
    from talos.web.runner import GraphDriver
    from talos.web.store import PgStore

    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. The web app needs Postgres, for example "
            "DATABASE_URL=postgresql+psycopg://talos:talos@localhost:5432/talos "
            "(see README, Web app)."
        )
    await asyncio.to_thread(upgrade_head)
    store = PgStore(init_db())
    if settings.FAKE_GRAPH:
        fake_vault, fake_root = make_fake_vault()
        log.warning("TALOS_FAKE_GRAPH=1: scripted runs, vault copy at %s", fake_root)

        async def close_fake() -> None:
            await dispose_db()
            shutil.rmtree(fake_root, ignore_errors=True)

        return Services(
            store=store,
            driver=FakeDriver(fake_vault),
            vault=fake_vault,
            fake_graph=True,
            aclose=close_fake,
        )
    saver = await open_postgres_saver()

    async def close_real() -> None:
        await close_postgres_saver(saver)
        await dispose_db()

    return Services(
        store=store,
        driver=GraphDriver(build_app(saver)),
        vault=SkillManager(),
        aclose=close_real,
    )


def create_app(
    services: ServicesFactory | None = None,
    *,
    static_dir: Path | None = STATIC_DIR,
    dev: bool | None = None,
) -> FastAPI:
    """Build the app.

    Args:
        services: Builds the services at startup; default `open_services`
            (Postgres). Tests pass a factory with MemoryStore and FakeDriver.
        static_dir: The built frontend; served at / when it exists.
        dev: Allow CORS from Vite's dev server (default TALOS_WEB_DEV).
    """
    factory = services or open_services

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        install_log_redaction()
        built = await factory()
        manager = RunManager(built.store, built.driver)
        recovered = await built.store.recover()
        if recovered:
            log.warning("marked %d interrupted run(s) as failed", len(recovered))
        ask = await built.store.get_setting(ASK_BEFORE_EXEC)
        if ask is not None:
            settings.set_auto_approve_override(not bool(ask))
        app.state.services = built
        app.state.manager = manager
        try:
            yield
        finally:
            await manager.shutdown()
            settings.set_auto_approve_override(None)
            if built.aclose is not None:
                await built.aclose()

    app = FastAPI(
        title="Talos", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    install_error_handlers(app)
    for router in (health.router,):
        app.include_router(router, prefix="/api")
    if settings.WEB_DEV if dev is None else dev:
        app.add_middleware(
            CORSMiddleware, allow_origins=[DEV_ORIGIN], allow_methods=["*"], allow_headers=["*"]
        )
    app.add_middleware(BodySizeLimit)
    if static_dir is not None:
        _serve_frontend(app, static_dir)
    return app


def _serve_frontend(app: FastAPI, root: Path) -> None:
    """Files from the built frontend; index.html for any other non-/api path."""
    root = root.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "No such API endpoint.")
        index = root / "index.html"
        if not index.is_file():
            raise ApiError(404, "not_found", "The frontend isn't built (frontend/dist).")
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        return FileResponse(index)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS.

- [ ] **Step 9: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/security.py talos/web/deps.py talos/web/app.py talos/web/routes tests/web/conftest.py tests/web/test_app.py tests/web/test_security.py
git commit -m "[Feat]: Add the FastAPI app with lifespan, error shape, limits, health and key redaction"
```

---

### Task 9: Sessions, runs and the SSE event stream

**Files:**
- Create: `talos/web/routes/sessions.py`, `talos/web/routes/runs.py`
- Modify: `talos/web/app.py` (the routes import and the router tuple in `create_app`)
- Test: `tests/web/test_routes_sessions_runs.py`, `tests/web/test_key_leaks.py`

**Interfaces:**
- Consumes: `RunManager.start/resume/stop/subscribe` (Task 6), `Store` (Task 5), schemas (Task 3), `deps.get_manager`, `get_store`, `not_found` (Task 8), `security.remember_secret` (Task 8), `sse_starlette.sse.EventSourceResponse`, `ServerSentEvent`; test helpers from `tests/web/conftest.py` and `tests/web/stubs.py`.
- Produces: `talos.web.routes.sessions.router`: `POST /api/sessions` (201 `SessionOut`, reuses the newest empty session), `GET /api/sessions` (`[SessionSummaryOut]`, sessions with runs only, newest first), `GET /api/sessions/{id}` (`SessionDetailOut`), `PATCH /api/sessions/{id}` (`RenameIn` → `SessionOut`), `POST /api/sessions/{id}/messages` (`MessageIn` → 202 `StartRunOut`; 409 `run_active`). `talos.web.routes.runs.router`: `GET /api/runs/{id}` (`RunOut` with browser-safe `pending`), `GET /api/runs/{id}/events` (SSE: `id: {seq}`, `event: {type}`, `data: {envelope}`, `: keep-alive` every `HEARTBEAT_S = 15` s; `Last-Event-ID` header or `?after=N`), `POST /api/runs/{id}/resume` (`ResumeIn` → 202 `{"ok": true}`; 409 `not_waiting`; 422 `bad_decision` / `invalid_request`), `POST /api/runs/{id}/stop` (202 `{"ok": true}`, no-op when finished).

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_routes_sessions_runs.py`:

```python
"""Sessions, runs and the SSE stream over HTTP, with the fake graph (spec 02 §4, §5, §11)."""

from __future__ import annotations

import asyncio
import uuid

from tests.web.conftest import parse_sse, wait_for_status

CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"


async def new_session(client) -> str:
    response = await client.post("/api/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def send(client, session_id: str, text: str) -> dict:
    response = await client.post(f"/api/sessions/{session_id}/messages", json={"text": text})
    assert response.status_code == 202, response.text
    return response.json()


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["db"] is True and body["fake_graph"] is True
    assert isinstance(body["version"], str)


async def test_create_reuses_the_empty_session_and_lists_only_used_ones(client):
    first = await new_session(client)
    assert await new_session(client) == first  # an empty session is reused
    assert (await client.get("/api/sessions")).json() == []

    run = (await send(client, first, CAESAR_Q))["run"]
    await wait_for_status(client, run["id"], "done")
    listed = (await client.get("/api/sessions")).json()
    assert [s["id"] for s in listed] == [first]
    assert listed[0]["name"] == "Caesar cipher"
    assert listed[0]["run_count"] == 1
    assert listed[0]["forged"] == ["caesar_cipher"]
    assert listed[0]["runs"] == [{"n": 1, "query": CAESAR_Q, "mark": "forged"}]
    assert await new_session(client) != first


async def test_session_detail_rename_and_errors(client):
    sid = await new_session(client)
    run = (await send(client, sid, CAESAR_Q))["run"]
    await wait_for_status(client, run["id"], "done")

    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["session"]["name"] == "Caesar cipher"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["chips"] == [{"kind": "forged", "text": "Forged caesar_cipher"}]
    assert detail["runs"][0]["summary"] == "1 tool forged, 2 attempts"
    assert detail["runs"][0]["summary_gold"] is True

    renamed = await client.patch(f"/api/sessions/{sid}", json={"name": "  Ciphers  "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ciphers"
    for bad in ("", "   ", "x" * 81):
        response = await client.patch(f"/api/sessions/{sid}", json={"name": bad})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    missing = str(uuid.uuid4())
    for response in (
        await client.get(f"/api/sessions/{missing}"),
        await client.patch(f"/api/sessions/{missing}", json={"name": "x"}),
        await client.post(f"/api/sessions/{missing}/messages", json={"text": "hi"}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert (await client.get("/api/sessions/not-a-uuid")).status_code == 422


async def test_message_text_is_trimmed_and_bounded(client):
    sid = await new_session(client)
    for bad in ("", "    ", "x" * 4001):
        response = await client.post(f"/api/sessions/{sid}/messages", json={"text": bad})
        assert response.status_code == 422
    body = await send(client, sid, "   What can you do?  ")
    assert body["message"]["html"] == "What can you do?"
    assert body["run"]["query"] == "What can you do?"
    assert body["run"]["status"] == "running"


async def test_one_run_at_a_time_anywhere(client):
    a = await new_session(client)
    run = (await send(client, a, PYTHON_Q))["run"]
    await wait_for_status(client, run["id"], "waiting")
    b_session = await client.post("/api/sessions")
    b = b_session.json()["id"]
    response = await client.post(f"/api/sessions/{b}/messages", json={"text": "hi"})
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "run_active",
            "message": "A run is already going. Stop it or wait for it to finish.",
            "run_id": run["id"],
            "session_id": a,
        }
    }


async def test_pending_approval_is_browser_safe_and_resume_approve_finishes(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    paused = await wait_for_status(client, run_id, "waiting")
    assert paused["pending"] == {
        "kind": "confirm_exec",
        "payload": {"tool": "python_exec", "preview": "print(sum(range(1, 101)))"},
    }
    response = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    assert response.status_code == 202
    done = await wait_for_status(client, run_id, "done")
    assert done["pending"] is None
    assert done["summary"] == "Built-in, approved"


async def test_resume_errors(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")

    wrong = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "save", "value": "k"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "bad_decision"
    unknown = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "maybe"})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "invalid_request"

    await client.post(f"/api/runs/{run_id}/resume", json={"decision": "decline"})
    declined = await wait_for_status(client, run_id, "declined")
    assert declined["summary"] == "Declined, nothing ran"
    again = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_waiting"

    missing = str(uuid.uuid4())
    for response in (
        await client.get(f"/api/runs/{missing}"),
        await client.get(f"/api/runs/{missing}/events"),
        await client.post(f"/api/runs/{missing}/resume", json={"decision": "approve"}),
        await client.post(f"/api/runs/{missing}/stop"),
    ):
        assert response.status_code == 404


async def test_stop_during_a_pause_then_stop_again_is_a_noop(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")
    assert (await client.post(f"/api/runs/{run_id}/stop")).status_code == 202
    stopped = await wait_for_status(client, run_id, "stopped")
    assert stopped["summary"] == "Stopped"
    assert (await client.post(f"/api/runs/{run_id}/stop")).status_code == 202
    events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
    assert events[-1]["event"] == "run.finished"
    assert events[-1]["data"]["data"]["status"] == "stopped"
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["messages"][-1]["note"] == "Stopped. Ask again whenever you're ready."


async def test_sse_sends_the_whole_run_then_closes(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, CAESAR_Q))["run"]["id"]
    await wait_for_status(client, run_id, "done")
    response = await client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
    assert [e["event"] for e in events[:2]] == ["run.started", "log.cmd"]
    assert events[-1]["event"] == "run.finished"
    envelope = events[0]["data"]
    assert set(envelope) == {"run_id", "seq", "ts", "type", "data"}
    assert envelope["run_id"] == run_id and envelope["type"] == "run.started"
    assert envelope["data"] == {"session_id": sid, "query": CAESAR_Q, "n": 1}
    assert all(e["event"] == e["data"]["type"] for e in events)


async def test_sse_resumes_after_a_dropped_connection(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, CAESAR_Q))["run"]["id"]
    await wait_for_status(client, run_id, "done")
    total = len(parse_sse((await client.get(f"/api/runs/{run_id}/events")).text))
    resumed = parse_sse(
        (await client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "10"})).text
    )
    assert [int(e["id"]) for e in resumed] == list(range(11, total + 1))
    after = parse_sse((await client.get(f"/api/runs/{run_id}/events?after=20")).text)
    assert int(after[0]["id"]) == 21


async def test_sse_backlog_then_live_through_a_pause(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")

    stream = asyncio.create_task(client.get(f"/api/runs/{run_id}/events"))
    await asyncio.sleep(0.05)
    assert not stream.done()  # open while the run waits
    await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    events = parse_sse((await asyncio.wait_for(stream, 5)).text)

    kinds = [e["event"] for e in events]
    assert kinds.index("interrupt") < kinds.index("interrupt.resolved")
    assert kinds[-1] == "run.finished"
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))


def test_heartbeat_is_a_keep_alive_comment():
    from sse_starlette.sse import ServerSentEvent

    from talos.web.routes.runs import HEARTBEAT_S

    assert HEARTBEAT_S == 15
    assert ServerSentEvent(comment="keep-alive", sep="\n").encode() == b": keep-alive\n\n"
```

Create `tests/web/test_key_leaks.py`:

```python
"""A key sent to /resume never shows up in logs, run_events or responses (spec 02 §10, §11)."""

from __future__ import annotations

import json
import logging

import pytest

from tests.web.conftest import make_app, open_client, parse_sse, wait_for_status
from tests.web.stubs import ScriptDriver

KEY = "owm-" + "7f3c9a1b2d4e6f80"


class LeakyDriver(ScriptDriver):
    """A driver that logs its resume value, as careless graph code might."""

    async def run(self, state, *, query, thread_id, resume):
        if resume is not None:
            logging.getLogger("talos.agents.hitl").warning("resumed with %s", resume.value)
        async for item in super().run(state, query=query, thread_id=thread_id, resume=resume):
            yield item


@pytest.fixture
def leaky_services(services):
    services.driver = LeakyDriver()
    return services


async def test_a_saved_key_never_leaks(leaky_services, caplog):
    caplog.set_level(logging.DEBUG)
    app = make_app(leaky_services)
    async for client in open_client(app):
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": "key"})
        run_id = sent.json()["run"]["id"]
        await wait_for_status(client, run_id, "waiting")

        wrong = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "approve", "value": KEY}
        )
        too_long = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "save", "value": KEY * 400}
        )
        ok = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "save", "value": KEY}
        )
        assert (wrong.status_code, too_long.status_code, ok.status_code) == (422, 422, 202)
        await wait_for_status(client, run_id, "done")

        bodies = [wrong.text, too_long.text, ok.text]
        bodies.append((await client.get(f"/api/runs/{run_id}")).text)
        bodies.append((await client.get(f"/api/sessions/{sid}")).text)
        stream = (await client.get(f"/api/runs/{run_id}/events")).text
        bodies.append(stream)
        for body in bodies:
            assert KEY not in body

        resolved = next(e for e in parse_sse(stream) if e["event"] == "interrupt.resolved")
        assert resolved["data"]["data"] == {"kind": "missing_api_key", "decision": "save"}

    stored = leaky_services.store.events[next(iter(leaky_services.store.runs))]
    assert KEY not in json.dumps([e.data for e in stored])
    assert KEY not in caplog.text
    assert "resumed with [redacted]" in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_sessions_runs.py tests/web/test_key_leaks.py -v`
Expected: FAIL, most with 404 `not_found` (the routes don't exist yet); `test_heartbeat_is_a_keep_alive_comment` fails with `ModuleNotFoundError: No module named 'talos.web.routes.runs'`.

- [ ] **Step 3: Implement the sessions routes**

Create `talos/web/routes/sessions.py`:

```python
"""Sessions and sending a message (spec 02 §4 Sessions)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from talos.web.deps import get_manager, get_store, not_found
from talos.web.runner import RunManager
from talos.web.schemas import (
    MessageIn,
    MessageOut,
    RenameIn,
    RunSummaryOut,
    SessionDetailOut,
    SessionOut,
    SessionSummaryOut,
    StartRunOut,
)
from talos.web.store import Store

router = APIRouter()


@router.post("/sessions", status_code=201, response_model=SessionOut)
async def create_session(store: Store = Depends(get_store)) -> SessionOut:
    """A new session, or the newest empty one (empty sessions are reused, not piled up)."""
    for summary in await store.list_sessions():
        if summary.run_count == 0:
            existing = await store.get_session(summary.id)
            if existing is not None:
                return SessionOut.model_validate(existing)
    return SessionOut.model_validate(await store.create_session())


@router.get("/sessions", response_model=list[SessionSummaryOut])
async def list_sessions(store: Store = Depends(get_store)) -> list[SessionSummaryOut]:
    """Sessions with at least one run, newest first."""
    return [SessionSummaryOut.model_validate(s) for s in await store.list_sessions() if s.run_count]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session(session_id: uuid.UUID, store: Store = Depends(get_store)) -> SessionDetailOut:
    session = await store.get_session(session_id)
    if session is None:
        raise not_found("Session")
    return SessionDetailOut(
        session=SessionOut.model_validate(session),
        messages=[MessageOut.model_validate(m) for m in await store.list_messages(session_id)],
        runs=[RunSummaryOut.model_validate(r) for r in await store.list_runs(session_id)],
    )


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID, body: RenameIn, store: Store = Depends(get_store)
) -> SessionOut:
    session = await store.rename_session(session_id, body.name)
    if session is None:
        raise not_found("Session")
    return SessionOut.model_validate(session)


@router.post("/sessions/{session_id}/messages", status_code=202, response_model=StartRunOut)
async def send_message(
    session_id: uuid.UUID, body: MessageIn, manager: RunManager = Depends(get_manager)
) -> StartRunOut:
    """Start a run. 409 `run_active` while any run is running or waiting."""
    started = await manager.start(session_id, body.text)
    return StartRunOut(
        run=RunSummaryOut.model_validate(started.run),
        message=MessageOut.model_validate(started.message),
    )
```

- [ ] **Step 4: Implement the runs routes and the SSE stream**

Create `talos/web/routes/runs.py`:

```python
"""Runs: status, the SSE event stream, resume and stop (spec 02 §4 Runs, §5)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from talos.web.deps import get_manager, get_store, not_found
from talos.web.runner import RunManager
from talos.web.schemas import PendingOut, ResumeIn, RunOut, pending_payload
from talos.web.security import remember_secret
from talos.web.store import Store

router = APIRouter()

HEARTBEAT_S = 15


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, store: Store = Depends(get_store)) -> RunOut:
    """The run summary, plus the browser-safe pending interrupt when paused."""
    run = await store.get_run(run_id)
    if run is None:
        raise not_found("Run")
    out = RunOut.model_validate(run)
    if run.status == "waiting" and run.pending_interrupt:
        out.pending = PendingOut(
            kind=str(run.pending_interrupt.get("type")),
            payload=pending_payload(run.pending_interrupt),
        )
    return out


def _after(last_event_id: str | None, after: int | None) -> int:
    for value in (last_event_id, after):
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: uuid.UUID,
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None),
    manager: RunManager = Depends(get_manager),
    store: Store = Depends(get_store),
) -> EventSourceResponse:
    """SSE: backlog after `Last-Event-ID` (or `?after=N`), then live events.

    Each event is `id: {seq}`, `event: {type}`, `data: {envelope}`. The
    stream stays open through pauses and closes after `run.finished`.
    """
    if await store.get_run(run_id) is None:
        raise not_found("Run")

    async def stream() -> AsyncIterator[ServerSentEvent]:
        async for envelope in manager.subscribe(run_id, _after(last_event_id, after)):
            yield ServerSentEvent(
                id=str(envelope["seq"]),
                event=envelope["type"],
                data=json.dumps(envelope, separators=(",", ":")),
            )

    return EventSourceResponse(
        stream(),
        ping=HEARTBEAT_S,
        ping_message_factory=lambda: ServerSentEvent(comment="keep-alive"),
        sep="\n",
    )


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(
    run_id: uuid.UUID, body: ResumeIn, manager: RunManager = Depends(get_manager)
) -> dict[str, bool]:
    """Answer a pause. 409 `not_waiting`; 422 if the decision doesn't fit."""
    if body.decision == "save":
        remember_secret(body.value)
    await manager.resume(run_id, body.decision, body.value)
    return {"ok": True}


@router.post("/runs/{run_id}/stop", status_code=202)
async def stop_run(
    run_id: uuid.UUID, manager: RunManager = Depends(get_manager)
) -> dict[str, bool]:
    """Stop a run (also during a pause). No-op if it already finished."""
    await manager.stop(run_id)
    return {"ok": True}
```

- [ ] **Step 5: Mount the routers**

In `talos/web/app.py`, change the routes import to:

```python
from talos.web.routes import health, runs, sessions
```

and the router loop in `create_app` to:

```python
    for router in (health.router, sessions.router, runs.router):
        app.include_router(router, prefix="/api")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS. The SSE tests read whole responses: httpx's `ASGITransport` buffers a response until the app ends it, and each stream ends after `run.finished`.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/routes/sessions.py talos/web/routes/runs.py talos/web/app.py tests/web/test_routes_sessions_runs.py tests/web/test_key_leaks.py
git commit -m "[Feat]: Add session and run endpoints with the SSE event stream"
```

---

### Task 10: Vault and settings endpoints

**Files:**
- Create: `talos/web/routes/vault.py`, `talos/web/routes/settings.py`
- Modify: `talos/web/app.py` (the routes import and the router tuple)
- Test: `tests/web/test_routes_vault_settings.py`

**Interfaces:**
- Consumes: `SkillManager.all/get/remove/vault_dir` (stage 1 `remove` keeps the `.py`), `schemas.vault_entry`, `VaultDetail`, `VaultListOut`, `KeyOut`, `SettingsOut`, `SettingsPatch` (Task 3), `deps.ASK_BEFORE_EXEC`, `get_store`, `get_vault`, `not_found` (Task 8), `copy.KEY_DESCRIPTIONS`, `copy.KEY_SAVED_BY_HUMAN_CHECK` (Task 2), `settings.set_auto_approve_override`, `settings.auto_approve_exec` (Task 1), `talos.agents.hitl.DOTENV_PATH`.
- Produces: `talos.web.routes.vault.router`: `GET /api/vault` (`VaultListOut`, sorted by `last_used` or `created_at` descending; `failed_count` = tools with failures), `GET /api/vault/{name}` (`VaultDetail`: entry + `source`, `lines`), `DELETE /api/vault/{name}` (204, 404 if absent). `talos.web.routes.settings.router`: `GET /api/settings`, `PATCH /api/settings` (`SettingsPatch` → `SettingsOut`; stores `ask_before_exec` and calls `set_auto_approve_override(not ask_before_exec)`); `KNOWN_KEYS`, `current_settings() -> SettingsOut`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_routes_vault_settings.py`:

```python
"""Vault and Settings endpoints (spec 02 §4 Vault, Settings; §7)."""

from __future__ import annotations

from talos.config import settings
from tests.web.conftest import wait_for_status

WEB_TOOL = "import requests\n\n\ndef fetch_x() -> str:\n    return requests.get('https://x').text\n"


def seed(vault) -> None:
    vault.register(
        {
            "name": "slugify",
            "function": "slugify",
            "signature": "slugify(title: str) -> str",
            "description": "Slug it.",
            "keywords": ["slug"],
            "created_at": "2026-09-28T14:58:00+00:00",
            "last_used": "2026-09-28T15:30:00+00:00",
            "usage_count": 3,
        },
        "def slugify(title: str) -> str:\n    return title.lower()\n",
    )
    vault.register(
        {
            "name": "fetch_x",
            "function": "fetch_x",
            "signature": "fetch_x() -> str",
            "created_at": "2026-09-28T15:00:00+00:00",
        },
        WEB_TOOL,
    )
    vault.record_failure("fetch_x", reason="HTTPError: 500")


async def test_vault_list_counts_and_order(client, services):
    seed(services.vault)
    body = (await client.get("/api/vault")).json()
    assert (body["count"], body["web_count"], body["failed_count"]) == (2, 1, 1)
    assert [t["name"] for t in body["tools"]] == ["slugify", "fetch_x"]  # last used first
    slug = body["tools"][0]
    assert (slug["args"], slug["ret"], slug["uses"], slug["web"]) == ("title: str", "str", 3, False)
    fetch = body["tools"][1]
    assert (fetch["args"], fetch["failures"], fetch["streak"], fetch["web"]) == ("", 1, 1, True)
    assert fetch["last_failure"] == "HTTPError: 500"


async def test_vault_detail_has_the_source_and_404s(client, services):
    seed(services.vault)
    detail = (await client.get("/api/vault/slugify")).json()
    assert detail["source"].startswith("def slugify")
    assert detail["lines"] == 3
    assert detail["file"] == "tools/slugify.py"
    response = await client.get("/api/vault/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


async def test_vault_delete_keeps_the_file(client, services):
    seed(services.vault)
    response = await client.delete("/api/vault/slugify")
    assert response.status_code == 204
    assert services.vault.get("slugify") is None
    assert (services.vault.tools_dir / "slugify.py").exists()
    assert (await client.get("/api/vault/slugify")).status_code == 404
    assert (await client.delete("/api/vault/slugify")).status_code == 404


async def test_fake_forge_shows_up_in_the_vault(client):
    sid = (await client.post("/api/sessions")).json()["id"]
    text = 'Encrypt "TALOS AGENT" with a Caesar cipher, shift of 7.'
    run = (await client.post(f"/api/sessions/{sid}/messages", json={"text": text})).json()["run"]
    await wait_for_status(client, run["id"], "done")
    detail = (await client.get("/api/vault/caesar_cipher")).json()
    assert detail["args"] == "text: str, shift: int, mode: str"
    assert detail["lines"] == 64  # the demo's 63 lines plus the trailing newline
    assert detail["uses"] == 1


async def test_settings_shape_and_key_rows(client, dotenv, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    dotenv.write_text("OPENWEATHERMAP_API_KEY=owm-secret\nOTHER=1\n", encoding="utf-8")
    body = (await client.get("/api/settings")).json()
    assert body["model"] == settings.TALOS_MODEL
    assert body["ask_before_exec"] is True
    assert (body["forge_retries"], body["test_timeout_s"]) == (
        settings.FORGE_MAX_RETRIES,
        settings.SUBPROCESS_TIMEOUT,
    )
    assert body["llm_timeout_s"] == settings.LLM_TIMEOUT
    assert body["prune_after"] == 2
    keys = {k["name"]: k for k in body["keys"]}
    assert list(keys)[:4] == [
        "OPENROUTER_API_KEY",
        "TAVILY_API_KEY",
        "JINA_API_KEY",
        "LANGSMITH_API_KEY",
    ]
    assert keys["OPENROUTER_API_KEY"] == {
        "name": "OPENROUTER_API_KEY",
        "set": True,
        "required": True,
        "description": "Required. Every model call goes through OpenRouter.",
    }
    assert keys["TAVILY_API_KEY"]["set"] is False
    assert keys["OPENWEATHERMAP_API_KEY"] == {
        "name": "OPENWEATHERMAP_API_KEY",
        "set": True,
        "required": False,
        "description": "Saved by Human check",
    }
    assert "OTHER" not in keys
    text = (await client.get("/api/settings")).text
    assert "sk-or-secret" not in text and "owm-secret" not in text


async def test_patch_ask_before_exec_applies_and_persists(client, services):
    body = (await client.patch("/api/settings", json={"ask_before_exec": False})).json()
    assert body["ask_before_exec"] is False
    assert settings.auto_approve_exec() is True
    assert await services.store.get_setting("ask_before_exec") is False

    sid = (await client.post("/api/sessions")).json()["id"]
    text = "Run this Python code: print(2 + 2)"
    run = (await client.post(f"/api/sessions/{sid}/messages", json={"text": text})).json()["run"]
    done = await wait_for_status(client, run["id"], "done")  # no approval pause
    assert done["summary"] == "Built-in"

    assert (
        await client.patch("/api/settings", json={"ask_before_exec": "nope"})
    ).status_code == 422
    await client.patch("/api/settings", json={"ask_before_exec": True})
    assert settings.auto_approve_exec() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_vault_settings.py -v`
Expected: FAIL with 404 `not_found` responses (`KeyError: 'count'` and similar).

- [ ] **Step 3: Implement the vault routes**

Create `talos/web/routes/vault.py`:

```python
"""The vault: list, detail with source, remove (spec 02 §4 Vault)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from talos.vault.manager import SkillManager
from talos.web.deps import get_vault, not_found
from talos.web.schemas import VaultDetail, VaultListOut, vault_entry

router = APIRouter()


def _source(vault: SkillManager, entry: dict[str, Any]) -> str | None:
    path = vault.vault_dir / str(entry.get("file") or f"tools/{entry.get('name')}.py")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@router.get("/vault", response_model=VaultListOut)
async def list_vault(vault: SkillManager = Depends(get_vault)) -> VaultListOut:
    """Every tool, most recently used (or created) first."""
    tools = [vault_entry(e, _source(vault, e)) for e in vault.all()]
    tools.sort(key=lambda t: t.last_used or t.created_at or "", reverse=True)
    return VaultListOut(
        count=len(tools),
        web_count=sum(t.web for t in tools),
        failed_count=sum(t.failures > 0 for t in tools),
        tools=tools,
    )


@router.get("/vault/{name}", response_model=VaultDetail)
async def get_tool(name: str, vault: SkillManager = Depends(get_vault)) -> VaultDetail:
    entry = vault.get(name)
    if entry is None:
        raise not_found("Tool")
    source = _source(vault, entry)
    base = vault_entry(entry, source).model_dump()
    return VaultDetail(**base, source=source, lines=len(source.split("\n")) if source else 0)


@router.delete("/vault/{name}", status_code=204)
async def remove_tool(name: str, vault: SkillManager = Depends(get_vault)) -> Response:
    """Take a tool out of the manifest. Its .py file stays on disk."""
    if not vault.remove(name):
        raise not_found("Tool")
    return Response(status_code=204)
```

- [ ] **Step 4: Implement the settings routes**

Create `talos/web/routes/settings.py`:

```python
"""Settings: the ask-before-exec switch and which keys are set (spec 02 §4, §7)."""

from __future__ import annotations

import os

from dotenv import dotenv_values
from fastapi import APIRouter, Depends

from talos.agents import hitl
from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD
from talos.web import copy
from talos.web.deps import ASK_BEFORE_EXEC, get_store
from talos.web.schemas import KeyOut, SettingsOut, SettingsPatch
from talos.web.store import Store

router = APIRouter()

KNOWN_KEYS = (
    ("OPENROUTER_API_KEY", True),
    ("TAVILY_API_KEY", True),
    ("JINA_API_KEY", False),
    ("LANGSMITH_API_KEY", False),
)


def _keys() -> list[KeyOut]:
    """Known keys, then every other *_API_KEY in .env. Never the values."""
    try:
        saved = dotenv_values(hitl.DOTENV_PATH) if hitl.DOTENV_PATH.exists() else {}
    except OSError:
        saved = {}
    known = {name for name, _ in KNOWN_KEYS}
    keys = [
        KeyOut(
            name=name,
            set=bool(os.environ.get(name) or saved.get(name)),
            required=required,
            description=copy.KEY_DESCRIPTIONS[name],
        )
        for name, required in KNOWN_KEYS
    ]
    for name in sorted(n for n in saved if n.endswith("_API_KEY") and n not in known):
        keys.append(
            KeyOut(
                name=name,
                set=bool(saved.get(name) or os.environ.get(name)),
                required=False,
                description=copy.KEY_SAVED_BY_HUMAN_CHECK,
            )
        )
    return keys


def current_settings() -> SettingsOut:
    return SettingsOut(
        model=settings.TALOS_MODEL,
        ask_before_exec=not settings.auto_approve_exec(),
        forge_retries=settings.FORGE_MAX_RETRIES,
        test_timeout_s=settings.SUBPROCESS_TIMEOUT,
        llm_timeout_s=settings.LLM_TIMEOUT,
        prune_after=_AUTO_PRUNE_THRESHOLD,
        keys=_keys(),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    return current_settings()


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsPatch, store: Store = Depends(get_store)) -> SettingsOut:
    """Store the switch and apply it to this process at once."""
    await store.set_setting(ASK_BEFORE_EXEC, body.ask_before_exec)
    settings.set_auto_approve_override(not body.ask_before_exec)
    return current_settings()
```

- [ ] **Step 5: Mount the routers**

In `talos/web/app.py`, change the routes import to:

```python
from talos.web.routes import health, runs, sessions, vault
from talos.web.routes import settings as settings_routes
```

and the router loop in `create_app` to:

```python
    for router in (
        health.router,
        sessions.router,
        runs.router,
        vault.router,
        settings_routes.router,
    ):
        app.include_router(router, prefix="/api")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add talos/web/routes/vault.py talos/web/routes/settings.py talos/web/app.py tests/web/test_routes_vault_settings.py
git commit -m "[Feat]: Add vault and settings endpoints"
```

---

### Task 11: talos-web entry point and Postgres integration tests

**Files:**
- Create: `talos/web/__main__.py`
- Modify: `pyproject.toml` (`[project.scripts]`), `uv.lock` (via `uv sync`)
- Test: `tests/web/test_main.py`, `tests/integration/test_web_app.py`

**Interfaces:**
- Consumes: `create_app` (Task 8), `settings.WEB_HOST`, `settings.WEB_PORT` (Task 1), `talos.config.logging.setup_logging`; for the integration tests `PgStore` (Task 5), `FakeDriver` (Task 7), `GraphDriver` (Task 6), `open_postgres_saver`, `close_postgres_saver`, `build_app` (stage 1), `tests.web.chunks.scenario_env` (Task 4), `tests/web/conftest.py` helpers (Task 8), fixtures `factory`, `migrated_url`.
- Produces: `talos.web.__main__.main() -> None` (uvicorn, `factory=True`, one worker); console script `talos-web`; `python -m talos.web`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_main.py`:

```python
"""The talos-web entry point."""

from __future__ import annotations

import tomllib

from talos.config import settings
from talos.web import __main__ as web_main


def test_talos_web_runs_one_local_worker(monkeypatch):
    calls = {}
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: calls.update(args=a, kw=k))
    web_main.main()
    assert calls["args"] == ("talos.web.app:create_app",)
    assert calls["kw"]["factory"] is True
    assert calls["kw"]["workers"] == 1
    assert (calls["kw"]["host"], calls["kw"]["port"]) == (settings.WEB_HOST, settings.WEB_PORT)


def test_talos_web_script_is_declared():
    with open(settings.PROJECT_ROOT / "pyproject.toml", "rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]
    assert scripts["talos-web"] == "talos.web.__main__:main"
```

Create `tests/integration/test_web_app.py`:

```python
"""The web app on Postgres (spec 02 §11 Integration): a full fake-graph Caesar run,
and a restart mid-pause followed by a successful resume, with the fake graph
and with the real graph on the Postgres checkpointer."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.graph import build_app
from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
from talos.vault.manager import SkillManager
from talos.web.deps import Services
from talos.web.fake_graph import FakeDriver
from talos.web.runner import GraphDriver
from talos.web.store import PgStore
from tests.web import chunks
from tests.web.conftest import make_app, open_client, parse_sse, wait_for_status

pytestmark = pytest.mark.integration

CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"


@pytest.fixture
def fake_services(factory, tmp_path: Path, monkeypatch):
    from talos.agents import hitl

    monkeypatch.setattr(hitl, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)

    def build() -> Services:
        vault = SkillManager(vault_dir=tmp_path / "vault")
        return Services(
            store=PgStore(factory), driver=FakeDriver(vault), vault=vault, fake_graph=True
        )

    return build


async def test_full_fake_caesar_run_on_postgres(fake_services):
    services = fake_services()
    async for client in open_client(make_app(services)):
        assert (await client.get("/api/health")).json()["db"] is True
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": CAESAR_Q})
        run_id = sent.json()["run"]["id"]
        done = await wait_for_status(client, run_id, "done")
        assert done["summary"] == "1 tool forged, 2 attempts"
        events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
        assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["event"] == "run.finished"
        detail = (await client.get(f"/api/sessions/{sid}")).json()
        assert detail["session"]["name"] == "Caesar cipher"
        assert detail["messages"][1]["chips"] == [
            {"kind": "forged", "text": "Forged caesar_cipher"}
        ]
        listed = (await client.get("/api/sessions")).json()
        assert listed[0]["runs"][0]["mark"] == "forged"


async def test_fake_restart_mid_pause_then_resume(fake_services):
    first = fake_services()
    async for client in open_client(make_app(first)):
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": PYTHON_Q})
        run_id = sent.json()["run"]["id"]
        await wait_for_status(client, run_id, "waiting")

    second = fake_services()  # a new process: new store object, new driver, same database
    async for client in open_client(make_app(second)):
        paused = await wait_for_status(client, run_id, "waiting")
        assert paused["pending"]["kind"] == "confirm_exec"
        resumed = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
        assert resumed.status_code == 202
        done = await wait_for_status(client, run_id, "done")
        assert done["summary"] == "Built-in, approved"
        events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
        assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))


async def test_real_graph_restart_mid_pause_then_resume(factory, migrated_url, tmp_path: Path):
    """The real graph on AsyncPostgresSaver: pause, new app instance, approve."""
    with chunks.scenario_env("exec_pause") as env:

        async def services_with_new_saver() -> Services:
            saver = await open_postgres_saver(migrated_url)
            return Services(
                store=PgStore(factory),
                driver=GraphDriver(build_app(saver)),
                vault=env["vault"],
                aclose=lambda: close_postgres_saver(saver),
            )

        first = await services_with_new_saver()
        async for client in open_client(make_app(first)):
            sid = (await client.post("/api/sessions")).json()["id"]
            sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": PYTHON_Q})
            run_id = sent.json()["run"]["id"]
            await wait_for_status(client, run_id, "waiting")

        second = await services_with_new_saver()
        async for client in open_client(make_app(second)):
            await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
            done = await wait_for_status(client, run_id, "done", "failed")
            assert done["status"] == "done", done
            assert done["summary"] == "Built-in, approved"
            events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
            result = next(e for e in events if e["event"] == "call.result")
            assert "5050" in result["data"]["data"]["repr"]
```

- [ ] **Step 2: Run the unit test to verify it fails**

Run: `uv run pytest tests/web/test_main.py -v`
Expected: collection error, `ImportError: cannot import name '__main__' from 'talos.web'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Implement the entry point**

Create `talos/web/__main__.py`:

```python
"""`talos-web` / `python -m talos.web`: serve the API with uvicorn.

One worker, always: run state and the vault are per process, and startup
recovery fails every `running` run, which would break a second worker's
live runs. Binds to 127.0.0.1 by default; there is no auth.
"""

from __future__ import annotations

import uvicorn

from talos.config import settings
from talos.config.logging import setup_logging


def main() -> None:
    """Run the app on TALOS_WEB_HOST:TALOS_WEB_PORT (default 127.0.0.1:8000)."""
    setup_logging()
    uvicorn.run(
        "talos.web.app:create_app",
        factory=True,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        workers=1,
    )


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, under `[project.scripts]`, add the line after `talos = "talos.main:main"`:

```toml
talos-web = "talos.web.__main__:main"
```

Run: `uv sync --extra dev`
Expected: `.venv/bin/talos-web` exists.

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `uv run pytest tests/web/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Run the integration tests**

Run: `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration tests/integration/test_web_app.py tests/integration/test_web_store.py -v`
Expected: PASS: a full fake-graph Caesar run on Postgres, a fake restart mid-pause then a resume, and the real graph paused on `AsyncPostgresSaver`, resumed by a second app instance, ending with `call.result` `5050`.

- [ ] **Step 6: Commit**

```bash
git add talos/web/__main__.py pyproject.toml uv.lock tests/web/test_main.py tests/integration/test_web_app.py
git commit -m "[Feat]: Add the talos-web entry point and Postgres tests for the web app"
```

---

### Task 12: Docs, full verification and the acceptance check

**Files:**
- Modify: `README.md` (Safety, a new "Web app (API)" section, Configuration table, Project layout)
- Modify: `.env.example`
- Modify: `PROGRESS.md` (a stage 02 section before `## Session log`)
- Modify: `docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md` (§7, one bullet)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only.

- [ ] **Step 1: README: Safety**

In `README.md`, in `## Safety: read this first`, add this bullet after the "There is no container isolation" bullet:

```markdown
- **The web app has no login.** `talos-web` binds to `127.0.0.1` and anyone who can reach its port can run code through it. Keep it on localhost; don't set `TALOS_WEB_HOST=0.0.0.0` on a shared network.
```

- [ ] **Step 2: README: the Web app (API) section**

In `README.md`, insert this section directly before `## Configuration`:

````markdown
## Web app (API)

`talos-web` serves a local HTTP API with the same graph behind it: it starts runs, streams their events to the browser over Server-Sent Events, pauses for approvals and API keys, and serves sessions, the vault and settings. The frontend (stage 4) will be served from the same port.

It needs Postgres (history and paused runs live there; tools stay on disk in the vault):

```bash
docker run -d --name talos-pg -e POSTGRES_USER=talos -e POSTGRES_PASSWORD=talos \
  -e POSTGRES_DB=talos -p 5432:5432 postgres:16-alpine
export DATABASE_URL=postgresql+psycopg://talos:talos@localhost:5432/talos
uv run talos-web                       # http://127.0.0.1:8000, migrations run at startup
TALOS_FAKE_GRAPH=1 uv run talos-web    # the demo's scripted runs: no model calls, no keys
```

| Method and path | What it does |
|---|---|
| `POST /api/sessions` | New session (an empty one is reused) |
| `GET /api/sessions` | Sessions with runs, newest first |
| `GET /api/sessions/{id}` / `PATCH` `{name}` | A session with its messages and runs / rename it |
| `POST /api/sessions/{id}/messages` `{text}` | Start a run. `409 run_active` while any run is running or waiting |
| `GET /api/runs/{id}` | Run summary, plus the pending approval or key request |
| `GET /api/runs/{id}/events` | SSE event stream; resume with `Last-Event-ID` or `?after=N` |
| `POST /api/runs/{id}/resume` | `{decision: "approve" \| "decline"}` or `{decision: "save", value}` / `{decision: "skip"}` |
| `POST /api/runs/{id}/stop` | Stop a run, also while it waits |
| `GET /api/vault`, `GET` / `DELETE /api/vault/{name}` | Tools, one tool with its source, remove from the manifest |
| `GET` / `PATCH /api/settings` | Model and limits, which keys are set, the "Ask before running code" switch |
| `GET /api/health` | `{ok, db, fake_graph, version}` |

Try a run from the terminal:

```bash
B=http://127.0.0.1:8000/api
SID=$(curl -s -X POST $B/sessions | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
RID=$(curl -s -X POST -H 'content-type: application/json' \
  -d '{"text":"Encrypt \"TALOS AGENT\" with a Caesar cipher, shift of 7."}' \
  $B/sessions/$SID/messages | python3 -c 'import sys,json;print(json.load(sys.stdin)["run"]["id"])')
curl -N $B/runs/$RID/events
```

Notes:

- Run one worker only (the default). Runs and the vault are per process, and at startup every run still marked `running` is failed, since the process that owned it is gone. Runs that were waiting for you stay waiting and can be resumed after a restart.
- Every event is stored before it is sent, so a dropped connection resumes from `Last-Event-ID` with nothing missing.
- Fake mode works on a temporary copy of the vault, so the demo runs never touch your real tools, and a key you "save" is only remembered in memory.
- API key values sent to `/resume` are never logged, stored in the event history, or returned by any endpoint.
````

- [ ] **Step 3: README: Configuration and layout**

In the Configuration table, add these rows after the `TALOS_DOTENV_PATH` row:

```markdown
| `TALOS_WEB_HOST` | no | Web app bind address. Default `127.0.0.1`. There is no login: keep it local |
| `TALOS_WEB_PORT` | no | Web app port. Default `8000` |
| `TALOS_FAKE_GRAPH` | no | `1` runs the web app with the demo's scripted runs: no model calls, no keys, a temporary vault copy |
| `TALOS_WEB_DEV` | no | `1` allows CORS from Vite's dev server at `http://127.0.0.1:5173` |
```

In `## Project layout`, add these two lines directly after the `│   ├── primitives/          # Built-in tools` line:

```
│   ├── persistence/         # Postgres models, repo, migrations (web app only)
│   ├── web/                 # Web app API (`uv run talos-web`): FastAPI, runs, SSE
```

In `## Tests`, after the `docker run -d --name talos-pg-test …` code block, add:

```markdown
The web app's route, SSE and runner tests run in the default suite against an in-memory store and the fake graph; the same store contract, a full fake-graph run, and a restart mid-pause run against Postgres under `-m integration`. The translator's chunk fixtures are recorded from the real graph with mocked LLMs; regenerate them after a LangGraph upgrade with `uv run python -m tests.web.chunks`.
```

- [ ] **Step 4: .env.example**

Append to `.env.example`:

```bash

# Web app (talos-web). No login: keep the host on 127.0.0.1.
# TALOS_WEB_HOST=127.0.0.1
# TALOS_WEB_PORT=8000
# 1 = the demo's scripted runs: no model calls or keys (for frontend work)
# TALOS_FAKE_GRAPH=0
# 1 = allow CORS from Vite's dev server (http://127.0.0.1:5173)
# TALOS_WEB_DEV=0
```

- [ ] **Step 5: PROGRESS.md**

In `PROGRESS.md`, insert directly before `## Session log`:

```markdown
## Web app stage 02 — API ✅

Spec: `docs/superpowers/specs/2026-09-30-talos-web-02-api-design.md`. Plan: `docs/superpowers/plans/2026-09-30-talos-web-02-api.md`.

- [x] `talos/web/`: FastAPI app (`create_app`, lifespan: migrations, Postgres checkpointer, recovery, stored settings), `talos-web` entry point, one worker on 127.0.0.1:8000
- [x] `copy.py`: every caption, log line, chip and summary, checked word for word against the reference demo (the test moved here from stage 01)
- [x] `EventTranslator`: `astream` chunks (`updates`, `custom`, `messages`, `tasks`, `subgraphs=True`) → contract events; fixtures recorded from the real graph with mocked LLMs, plus a live drift check
- [x] `RunManager`: one active run app-wide, persist-then-publish, pause/resume/stop, exception path; SSE with backlog, `Last-Event-ID`, keep-alive, close after `run.finished`
- [x] Endpoints: sessions, messages, runs, resume, stop, events, vault, settings, health; one error shape; 64 KB body limit; CORS only with `TALOS_WEB_DEV=1`
- [x] `TALOS_FAKE_GRAPH=1`: the demo's Caesar forge/reuse/failure, `python_exec` approval and OpenWeatherMap key flows as the same events as the real graph, on a temporary vault copy
- [x] API key values never logged (record-factory redaction), stored in events, or returned
- [x] Tests: unit suite needs no database (in-memory store contract-tested against Postgres); integration: full fake Caesar run, restart mid-pause and resume (fake and real graph)
```

- [ ] **Step 6: Frontend spec §7**

In `docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md` §7, add this bullet at the end of the list:

```markdown
- A few server strings have no counterpart in the reference file because the demo never needed them. They live in `talos/web/copy.py` `NEW_COPY` and render like any other server string: `{n} sub-tasks. Talos works through them in order.` (caption) and `{n} sub-tasks` (plan log line) for multi-sub-task plans; `The Forger used all {max} attempts. Nothing was saved to the vault.` and `gave up after {n} attempts` when a forge runs out of attempts; `{passed} of {total} passed` on the last failed attempt; `failed` for a failed smoke test; `Attempt {n} failed a test. Trying again` after attempt 2+; `{k} tools forged`; `1 tool forged, 1 attempt`; `Done in 1 attempt. No API key was needed, so Human check passed straight through.`; `Done in {attempts}. Your key is saved to .env.`
```

- [ ] **Step 7: Full verification**

Run each and read the output:

```bash
uv run pytest -q
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration -q
uv run ruff check .
uv run ruff format --check .
```

Expected: the default suite passes with the integration tests skipped and no database touched; the integration run passes; both ruff commands are clean.

- [ ] **Step 8: Acceptance: a scripted Caesar run over curl**

Use a fresh database so no paused run from the integration suite blocks the new one (`409 run_active`):

```bash
docker exec talos-pg-test dropdb -U talos --if-exists talos_accept
docker exec talos-pg-test createdb -U talos talos_accept
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos_accept \
  TALOS_FAKE_GRAPH=1 TALOS_WEB_PORT=8765 uv run talos-web > /tmp/talos-web.log 2>&1 &
SERVER=$!
sleep 5
B=http://127.0.0.1:8765/api
curl -s $B/health
SID=$(curl -s -X POST $B/sessions | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
RID=$(curl -s -X POST -H 'content-type: application/json' \
  -d '{"text":"Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt \"TALOS AGENT\" with a shift of 7."}' \
  $B/sessions/$SID/messages | python3 -c 'import sys,json;print(json.load(sys.stdin)["run"]["id"])')
curl -sN --max-time 10 $B/runs/$RID/events | tee /tmp/talos-stream.txt | tail -4
grep -c '^id:' /tmp/talos-stream.txt
curl -s $B/vault/caesar_cipher | head -c 120; echo
kill $SERVER
docker exec talos-pg-test dropdb -U talos talos_accept
```

Expected: health `{"ok":true,"db":true,"fake_graph":true,...}`; the stream starts with `id: 1` / `event: run.started`, ends with `event: run.finished` and `"summary":"1 tool forged, 2 attempts"`, then closes by itself (about 72 events); `caesar_cipher` is in the (temporary) vault. The log shows migrations, the fake-graph warning and a clean shutdown.

- [ ] **Step 9: Commit**

```bash
git add README.md .env.example PROGRESS.md docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md
git commit -m "[Docs]: Document the web app API, its settings and the stage 02 progress"
```
