# Talos Web App Stage 03 (Docker, Forged-Tool Sandbox, CI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forged tools stop running inside the Talos process (a time-limited subprocess per call, values crossing as tagged JSON), and the whole app starts with `docker compose up`, with the integration suite running the same way locally (`make test-int`) and in CI.

**Architecture:** A new `talos/sandbox/` package: `codec.py` (tagged JSON, both directions), `child.py` (the `python -P -m talos.sandbox.child` process that loads one tool file and calls one function), `runner.py` (`run_tool()`, process-group kill on timeout) and `tool.py` (`SandboxedTool`, a callable proxy whose signature is parsed from the source with `ast`, so the executor's existing coercion, validation and `describe_args` code keeps working unchanged). The executor and the smoke gate swap `SkillManager.load()` / in-process `exec()` for `SandboxedTool`. Then a three-stage Dockerfile (plus a `test` stage for compose), `compose.yml` / `compose.dev.yml` / `compose.test.yml`, a Makefile of aliases, and two new CI jobs (`integration`, `docker`).

**Tech Stack:** Python 3.11+ stdlib (`subprocess`, `ast`, `json`, `base64`), psycopg 3 (DB wait), Docker with BuildKit, Docker Compose v2 (verified with 5.1.4), `node:22-alpine`, `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, `python:3.12-slim-bookworm`, `postgres:16-alpine` (compose) / `postgres:16` (CI), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-30-talos-web-03-docker-sandbox-design.md` (the authority for this stage). Also read: overview `2026-09-30-talos-web-app-overview-design.md` (§1 success criteria 1, 5, 6; §6 out of scope), stage 2 `2026-09-30-talos-web-02-api-design.md` (§2 `talos-web`, §3 lifespan, §4 `/api/health` and static files, §9 fake graph), stage 4 `2026-09-30-talos-web-04-frontend-design.md` §2 (`frontend/` layout) and §9 (Playwright suite). Sibling plans: stage 1 `2026-09-30-talos-web-01-persistence.md` (done; `talos/persistence/`, `alembic/`, `TALOS_VAULT_DIR` etc.), stage 2 `2026-09-30-talos-web-02-api.md`, stage 4 part B `2026-09-30-talos-web-04b-frontend-live.md` (owns the CI `frontend` job).

**How this plan was checked:** every code block below was run in a scratch copy of the repo on 30 Sep 2026: the unit suite (343 passed, 34 skipped), ruff check and format, `docker build .`, the `make test-int` flow (unit + 27 integration tests inside compose), and `docker compose up` with a stand-in `talos-web` (healthy, sandbox cwd `/data/workspace`, a 2 s timeout killed a `sleep(60)` tool, root filesystem read-only, `/data/.env` writable).

## Global Constraints

- Branch `feat/web-03-docker-sandbox`, stacked on `feat/web-02-api`. Create it from the tip of `feat/web-02-api` before Task 1: `git checkout feat/web-02-api && git checkout -b feat/web-03-docker-sandbox`.
- `uv run pytest` stays green with no database, no Docker and no API keys. Integration tests stay behind the existing gate: `DATABASE_URL` exported in the shell **and** `-m integration` (see `tests/conftest.py`). Local Postgres for them: the `talos-pg-test` container on port 55432. Never touch or remove that container.
- Python 3.11+ (the sandbox child uses `python -P`, new in 3.11). Type hints everywhere, Google-style docstrings on public functions, `logging` not `print`, `ruff check .` and `ruff format --check .` clean (line length 100).
- Sandbox values cross the process boundary as tagged JSON only. Never `pickle`, `marshal`, `eval` or `exec` a value coming back from the child.
- Tool error strings keep today's format exactly: `f"{type(e).__name__}: {e}"`, e.g. `TypeError: shift must be an int, got str`. A timeout is `TimeoutError: tool ran longer than 30s` (the number is the limit formatted with `:g`).
- `TALOS_TOOL_TIMEOUT`: new setting, float seconds, default `30`, read at call time from `settings.TOOL_TIMEOUT`.
- Primitives (`python_exec`, `shell_exec`, `web_*`, `file_*`, `vault_list`) are unchanged. `SkillManager.load()` stays (tests and backward compatibility) but the executor must never call it.
- Container: user `talos` uid 1000; `ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 TALOS_VAULT_DIR=/data/vault TALOS_WORKSPACE_DIR=/data/workspace TALOS_DOTENV_PATH=/data/.env TALOS_WEB_HOST=0.0.0.0`; compose publishes the app on `127.0.0.1:8000` only; `db` publishes no port except through `compose.dev.yml` (`127.0.0.1:5432:5432`).
- Stage 2 names this stage depends on (spec 02): console script `talos-web`, `GET /api/health` → `{ok, db, fake_graph, version}`, `TALOS_WEB_HOST` / `TALOS_WEB_PORT`, `TALOS_FAKE_GRAPH=1`, the built frontend served from `frontend/dist` (resolved from the project root). If stage 2's plan or code names any of these differently, use stage 2's name and tell the controller.
- Commit messages: prefix `[Feat]:`, `[Fix]:`, `[Docs]:` or `[Chore]:`, then a short sentence. **No `Co-Authored-By` trailer and no Claude attribution line.**
- All commands run from the repo root unless a step says otherwise.

## Review Focus

1. **A tool that prints, writes straight to fd 1, or prints something that looks like the reply.** Expected: the reply is still parsed correctly (a per-call random sentinel line precedes it, and the parent takes the last one), the printed text lands in `ToolResult.stdout`, capped at 64 KB. Pinned in Task 2 by `test_prints_are_captured_and_do_not_corrupt_the_reply`, `test_output_written_straight_to_the_fd_is_kept_as_stdout`, `test_stdout_is_truncated`.
2. **A tool that starts its own subprocess and then hangs.** Expected: the timeout kills the whole process group, including the grandchild, and the parent returns within a few seconds instead of waiting on pipes the grandchild holds open. Pinned in Task 2 by `test_timeout_kills_processes_the_tool_started`.
3. **A file called `json.py` (or any stdlib name) in the workspace.** Expected: it doesn't shadow the stdlib in the child, whose cwd is the workspace (`-P` keeps cwd off `sys.path`). Pinned in Task 2 by `test_workspace_module_does_not_shadow_the_stdlib`.
4. **A tool that returns a dict that happens to look like a tagged value, or a self-referencing list, or an object with a hostile `__reduce__`/`__repr__`.** Expected: the dict round-trips unchanged (dicts with a `"__t"` key are always tagged), the loop falls back to its repr, the object arrives as a repr string and nothing runs in the parent. Pinned in Task 1 by `test_user_dict_with_a_tag_key_is_not_mistaken_for_a_tagged_value` and `test_broken_repr_still_encodes`, in Task 2 by `test_self_referencing_value_falls_back_to_repr` and `test_returned_objects_arrive_as_repr_strings`.
5. **`make test-int` next to real data, and a `.env` that sets container paths.** Expected: the integration suite (which wipes its database) never runs against the `db` volume that `make up` uses: `make test-int` always uses compose project `talos-test`, so its `db` has its own volume, removed afterwards. Host paths in `.env` (`TALOS_VAULT_DIR=…`) can't redirect the container: compose pins them in `environment:`, which beats `env_file:`. Pinned in Task 8 by `test_integration_tests_never_use_the_default_project` and `test_container_paths_are_pinned_over_the_env_file`.

## Rulings on ambiguities (read before starting)

- **Frontend at stage 03 (controller decision 2).** Stage 03 adds a minimal placeholder `frontend/`: `package.json` (no dependencies; `build` copies `placeholder.html` to `dist/index.html`; `dev` prints that the frontend arrives in stage 04), a matching `package-lock.json`, and `placeholder.html`. The Dockerfile's `frontend` stage (`npm ci`, then `npm run build` in `frontend/`) builds it today and needs no change in stage 04. **Stage 04 part A must overwrite `frontend/package.json` and `frontend/package-lock.json` and delete `frontend/placeholder.html`.** Stage 03 doesn't touch `.gitignore` (`frontend/dist` is already covered by the existing `dist/` rule; stage 04a Task 1 adds `frontend/node_modules/`), so any local `npm ci` check deletes `node_modules` afterwards.
- **CI `frontend` job: deferred to stage 04.** Stage 4 part B's plan (Task 11) adds the whole job (Node 22, lint, typecheck, build, Playwright visual + live against `TALOS_FAKE_GRAPH=1` and a `postgres:16` service). Stage 03 adds only `integration` and `docker`; the existing `lint` and `test` jobs are unchanged.
- **Signature without executing the tool.** The executor inspects signatures (`schema_from_signature`, `_validate_kwargs`, `describe_args`) before calling. `SandboxedTool` parses the signature with `ast` (annotations as source strings, literal defaults evaluated with `ast.literal_eval`, other defaults kept as a marker) and exposes it as `__signature__`. The executor code that uses `fn` stays as it is; only `_resolve_callable` and the error formatting change.
- **Where the sandbox error text comes from.** `SandboxedTool.__call__` raises `ToolFailed`, whose `str()` is the child's `"TypeError: …"` text. `talos.sandbox.error_text(exc)` returns that text for `ToolFailed` and `f"{type(exc).__name__}: {exc}"` for anything else, so the executor and smoke keep one `except Exception` branch.
- **Load errors move.** A tool file that doesn't parse or doesn't define the function is caught when `SandboxedTool` is built (a `ValueError`), so the executor reports `dispatch error: …` and smoke reports `load error: …`, as before. Import errors inside the tool (`import no_such_module`) now surface as runtime errors from the child (before, in smoke, they would have crashed the node).
- **The spec's `pytest -m "integration or not integration"`** doesn't work with the existing gate (`tests/conftest.py` skips integration tests whenever the expression contains `not integration`). The `tests` service runs `pytest -q && pytest -q -m integration` instead: same coverage, gate untouched.
- **`compose.test.yml` and data safety.** The spec runs the tests "against `db`". The integration suite downgrades and truncates that database, so `make test-int` runs compose with its own project name (`-p talos-test`). The `db` service is the same definition, but in its own project it gets its own `pgdata` volume, and `make test-int` removes it with `down -v` afterwards, pass or fail.
- **Tests image = `test` stage.** The spec says "the same image built with `--target deps` plus dev dependencies". That's a named `test` stage (`FROM deps`, `uv sync --extra dev`, plus `alembic/`, `tests/` and the reference demo folder that stage 2's copy test reads). It sits before `runtime`, so `docker build .` still builds `runtime` and skips `test`.
- **`uv sync --no-dev`.** This project keeps its dev tools in the `dev` *extra*, not a dependency group, so `--no-dev` changes nothing and `--extra dev` is what installs pytest and ruff in the `test` stage.
- **Editable install inside the image.** `settings.PROJECT_ROOT` is computed from `talos/config/settings.py`'s location, and `talos.persistence.migrations` finds `alembic.ini` through it. So the project is installed editable (uv's default) with the source at `/app/talos`, and the runtime stage copies both `/app/.venv` and `/app/talos` to the same paths. `PROJECT_ROOT` is then `/app`, and `alembic.ini`, `alembic/` and `frontend/dist` live there.
- **Healthcheck without curl.** `python:3.12-slim-bookworm` has no curl. The `HEALTHCHECK` does the same GET with `urllib.request` (no extra apt packages in the runtime image).
- **Waiting for the database.** `docker/entrypoint.sh` runs `python -m talos.persistence.wait` (new, unit-tested: retries `psycopg.connect` for up to `TALOS_DB_WAIT_TIMEOUT` seconds, default 60), then `alembic upgrade head`, then `exec talos-web "$@"`.
- **`.env` must exist for `make up`.** `env_file: .env` is required, so `docker compose up` stops with "env file … not found" instead of Docker creating a directory called `.env` for the bind mount. `make test-int` works without `.env` (checked). Human check writes `.env` in place (`Path.write_text`), which works on a single-file bind mount; don't change it to write-and-rename.
- **Paths pinned in compose.** Besides the spec's `DATABASE_URL` and `TALOS_CHECKPOINTER`, the app's `environment:` also sets `TALOS_VAULT_DIR`, `TALOS_WORKSPACE_DIR`, `TALOS_DOTENV_PATH`, `TALOS_WEB_HOST` and `TALOS_WEB_PORT`, because `env_file` values override the image's `ENV`.
- **CI `docker` job** also runs `docker compose … config --quiet` (after `cp .env.example .env`) so a broken compose file fails CI. It builds nothing else and pushes nothing.

## File map

| File | Task | Responsibility |
|---|---|---|
| `talos/sandbox/__init__.py` | 1 | Package docstring; lazy re-exports `run_tool`, `ToolResult`, `SandboxedTool`, `ToolFailed`, `error_text` |
| `talos/sandbox/codec.py` | 1 | `encode()` / `decode()` / `safe_repr()`: tagged JSON, stdlib only |
| `talos/sandbox/child.py` | 2 | The subprocess: read request, load tool, call, write sentinel + reply |
| `talos/sandbox/runner.py` | 2 | `run_tool()`, `ToolResult`, `STDOUT_LIMIT` |
| `talos/config/settings.py` | 2 | `TOOL_TIMEOUT` |
| `talos/sandbox/tool.py` | 3 | `SandboxedTool`, `ToolFailed`, `error_text()`, `signature_from_source()` |
| `talos/vault/manager.py` | 4 | `SkillManager.locate()`; `load()` docstring |
| `talos/agents/executor.py` | 4 | Vault/forge dispatch through `SandboxedTool` |
| `talos/agents/smoke.py` | 5 | Smoke through `SandboxedTool` on a temp file |
| `talos/persistence/wait.py` | 6 | `wait_for_db()` + `python -m talos.persistence.wait` |
| `frontend/package.json`, `frontend/package-lock.json`, `frontend/placeholder.html` | 7 | Placeholder frontend until stage 04 |
| `Dockerfile`, `.dockerignore`, `docker/entrypoint.sh` | 7 | The image |
| `compose.yml`, `compose.dev.yml`, `compose.test.yml`, `Makefile` | 8 | The stack and developer commands |
| `.github/workflows/ci.yml` | 9 | `integration` and `docker` jobs |
| `README.md`, `PROGRESS.md`, `.env.example` | 10 | Docs |
| `tests/test_sandbox_codec.py` | 1 | Codec |
| `tests/test_sandbox_runner.py`, `tests/fixtures/sandbox/caesar_cipher.py` | 2 | `run_tool` |
| `tests/test_sandbox_tool.py` | 3 | `SandboxedTool` |
| `tests/test_executor.py`, `tests/test_vault_manager.py` | 4 | Appended sandbox tests; existing tests untouched |
| `tests/test_smoke.py` | 5 | Appended sandbox tests; existing tests untouched |
| `tests/test_wait_for_db.py` | 6 | DB wait |
| `tests/test_docker_files.py` | 8 | Safety settings in the compose/Docker files |

---

### Task 1: Tagged-JSON codec

**Files:**
- Create: `talos/sandbox/__init__.py`
- Create: `talos/sandbox/codec.py`
- Test: `tests/test_sandbox_codec.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `talos.sandbox.codec.TAG: str = "__t"`
  - `talos.sandbox.codec.encode(value: Any) -> Any` (JSON-safe data)
  - `talos.sandbox.codec.decode(data: Any) -> Any` (raises `ValueError` on unknown or malformed tags)
  - `talos.sandbox.codec.safe_repr(value: Any) -> str` (never raises)
  - `talos.sandbox` package whose `__getattr__` lazily exposes `run_tool`, `ToolResult` (Task 2) and `SandboxedTool`, `ToolFailed`, `error_text` (Task 3). The laziness matters: the child imports `talos.sandbox.codec`, and must not load `talos.config.settings` on every tool call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sandbox_codec.py`:

```python
"""Tagged-JSON codec for the forged-tool sandbox (spec 03 §2.2)."""

from __future__ import annotations

import json

import pytest

from talos.sandbox.codec import decode, encode


def _round_trip(value):
    return decode(json.loads(json.dumps(encode(value))))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -7,
        2**53,
        -(2**53),
        1.5,
        "héllo",
        "",
        [1, "a", None],
        {"a": 1, "b": [1, 2]},
    ],
)
def test_json_native_values_pass_through_untagged(value):
    assert encode(value) == value
    assert _round_trip(value) == value


@pytest.mark.parametrize(
    ("value", "tag"),
    [
        ((1, "a"), "tuple"),
        ({1, 2, 3}, "set"),
        (frozenset({"x"}), "set"),
        (b"\x00\xffbytes", "bytes"),
        (2**53 + 1, "int"),
        (-(2**64), "int"),
        ({1: "one", 2: "two"}, "dict"),
        ({(1, 2): "pair"}, "dict"),
    ],
)
def test_tagged_types_round_trip(value, tag):
    encoded = encode(value)
    assert encoded["__t"] == tag
    out = _round_trip(value)
    assert out == (set(value) if isinstance(value, frozenset) else value)
    assert type(out) is (set if isinstance(value, frozenset) else type(value))


def test_big_int_travels_as_a_string():
    assert encode(10**30) == {"__t": "int", "v": str(10**30)}


def test_bytearray_decodes_to_bytes():
    assert _round_trip(bytearray(b"ab")) == b"ab"


def test_nested_structures_round_trip():
    value = {"rows": [(1, {2, 3}), {"k": b"v", "big": 2**70}], "map": {1: [(None,)]}}
    assert _round_trip(value) == value


def test_user_dict_with_a_tag_key_is_not_mistaken_for_a_tagged_value():
    value = {"__t": "tuple", "v": [1, 2]}
    assert _round_trip(value) == value


def test_unknown_objects_become_their_repr():
    class Thing:
        def __repr__(self) -> str:
            return "<Thing 1>"

    assert encode(Thing()) == {"__t": "repr", "v": "<Thing 1>"}
    assert _round_trip(Thing()) == "<Thing 1>"


def test_broken_repr_still_encodes():
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("no")

    assert encode(Broken()) == {"__t": "repr", "v": "<unrepresentable Broken>"}


def test_unknown_tag_is_rejected():
    with pytest.raises(ValueError, match="unknown tag"):
        decode({"__t": "pickle", "v": "gASV"})


def test_malformed_tagged_value_is_rejected():
    with pytest.raises(ValueError, match="malformed"):
        decode({"__t": "bytes", "v": "not base64!!"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sandbox_codec.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'talos.sandbox'`.

- [ ] **Step 3: Create the package**

Create `talos/sandbox/__init__.py`:

```python
"""Forged-tool sandbox: run vault tools in a time-limited subprocess.

Public API (spec 03 §2): `run_tool`, `ToolResult`, `SandboxedTool`,
`ToolFailed`, `error_text`. They are imported lazily so the sandbox child, which imports
`talos.sandbox.codec`, doesn't pay for loading settings.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SandboxedTool", "ToolFailed", "ToolResult", "error_text", "run_tool"]


def __getattr__(name: str) -> Any:
    if name in {"ToolResult", "run_tool"}:
        from talos.sandbox import runner

        return getattr(runner, name)
    if name in {"SandboxedTool", "ToolFailed", "error_text"}:
        from talos.sandbox import tool

        return getattr(tool, name)
    raise AttributeError(f"module 'talos.sandbox' has no attribute {name!r}")
```

Create `talos/sandbox/codec.py`:

```python
"""Tagged-JSON codec for values crossing the sandbox boundary (spec 03 §2.2).

Both directions use it: the parent encodes a tool's arguments, the child
encodes the return value. Nothing is ever unpickled, so the worst a tool can
send back is data. Anything the codec does not know becomes its repr string.

This module must stay stdlib-only: the sandbox child imports it before it
runs untrusted code, and it should start fast.
"""

from __future__ import annotations

import base64
from typing import Any

TAG = "__t"

# Largest int a JSON reader that uses doubles can hold exactly (2**53).
_SAFE_INT = 2**53


def safe_repr(value: Any) -> str:
    """repr() that never raises: a tool's __repr__ may be broken on purpose."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 — any failure falls back to the type name
        return f"<unrepresentable {type(value).__name__}>"


def encode(value: Any) -> Any:
    """Turn a Python value into JSON-safe data.

    Args:
        value: Any Python value.

    Returns:
        JSON-native data. Tuples, sets, frozensets, bytes, ints beyond 2**53
        and dicts with non-str keys (or a "__t" key) use tagged forms; any
        other object becomes `{"__t": "repr", "v": repr(value)}`.
    """
    if value is None or isinstance(value, (bool, str, float)):
        return value
    if isinstance(value, int):
        if -_SAFE_INT <= value <= _SAFE_INT:
            return value
        return {TAG: "int", "v": str(value)}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, tuple):
        return {TAG: "tuple", "v": [encode(v) for v in value]}
    if isinstance(value, (set, frozenset)):
        return {TAG: "set", "v": [encode(v) for v in value]}
    if isinstance(value, (bytes, bytearray)):
        return {TAG: "bytes", "v": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value) and TAG not in value:
            return {k: encode(v) for k, v in value.items()}
        return {TAG: "dict", "v": [[encode(k), encode(v)] for k, v in value.items()]}
    return {TAG: "repr", "v": safe_repr(value)}


def _hashable(value: Any) -> Any:
    """Make a decoded value usable as a set member or dict key."""
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return safe_repr(value)
    return value


def decode(data: Any) -> Any:
    """Inverse of `encode`.

    Args:
        data: Parsed JSON produced by `encode`.

    Returns:
        The Python value. A `repr` tag decodes to its string.

    Raises:
        ValueError: On an unknown tag or a malformed tagged form.
    """
    if isinstance(data, list):
        return [decode(v) for v in data]
    if not isinstance(data, dict):
        return data
    if TAG not in data:
        return {k: decode(v) for k, v in data.items()}
    tag, payload = data.get(TAG), data.get("v")
    try:
        if tag == "int":
            return int(payload)
        if tag == "tuple":
            return tuple(decode(v) for v in payload)
        if tag == "set":
            return {_hashable(decode(v)) for v in payload}
        if tag == "bytes":
            return base64.b64decode(payload.encode("ascii"), validate=True)
        if tag == "dict":
            return {_hashable(decode(k)): decode(v) for k, v in payload}
        if tag == "repr":
            return str(payload)
    except (TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"malformed {tag!r} value: {e}") from e
    raise ValueError(f"unknown tag {tag!r}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sandbox_codec.py -q`
Expected: 28 passed.

Run: `uv run ruff check talos/sandbox tests/test_sandbox_codec.py && uv run ruff format --check talos/sandbox tests/test_sandbox_codec.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add talos/sandbox/__init__.py talos/sandbox/codec.py tests/test_sandbox_codec.py
git commit -m "[Feat]: Add the tagged-JSON codec for the forged-tool sandbox"
```

---

### Task 2: `run_tool` and the sandbox child

**Files:**
- Create: `talos/sandbox/child.py`
- Create: `talos/sandbox/runner.py`
- Create: `tests/fixtures/sandbox/caesar_cipher.py` (a copy of the real vault tool)
- Modify: `talos/config/settings.py` (add `TOOL_TIMEOUT` after `LLM_TIMEOUT`)
- Test: `tests/test_sandbox_runner.py`

**Interfaces:**
- Consumes: `encode`, `decode`, `safe_repr` from Task 1; `settings.WORKSPACE_DIR` (stage 1).
- Produces:
  - `talos.sandbox.runner.ToolResult` dataclass: `ok: bool`, `value: Any = None`, `error: str | None = None`, `timed_out: bool = False`, `stdout: str = ""`
  - `talos.sandbox.runner.run_tool(source_path: Path, function: str, args: list, kwargs: dict, timeout: float | None = None) -> ToolResult` (never raises for tool failures, timeouts or crashes)
  - `talos.sandbox.runner.STDOUT_LIMIT = 65536`
  - `talos.config.settings.TOOL_TIMEOUT: float` (env `TALOS_TOOL_TIMEOUT`, default 30)
  - Child protocol: stdin `{"source_path", "function", "args", "kwargs", "sentinel"}`; stdout `"\n" + sentinel + "\n" + json.dumps({"ok", "value", "error", "stdout"}) + "\n"`.

Design notes for the implementer:
- The child runs as `[sys.executable, "-P", "-m", "talos.sandbox.child"]` with `cwd=settings.WORKSPACE_DIR` (created if missing), the parent's environment plus the package root prepended to `PYTHONPATH`, and `start_new_session=True` so the timeout can `killpg` the whole group.
- The sentinel is random per call (`secrets.token_hex(16)`), and the parent splits on the **last** occurrence.
- In the child, `sys.stdout` is redirected into a buffer while the tool loads and runs, and `sys.stdin` is an empty `StringIO`, so `input()` raises `EOFError` instead of hanging until the timeout.

- [ ] **Step 1: Copy the real vault's `caesar_cipher` as a fixture**

The real vault (`talos/vault/tools/`) is gitignored, so the spec's `caesar_cipher` test needs its own copy. Create `tests/fixtures/sandbox/caesar_cipher.py` with exactly this content (it is the file from the owner's vault on 30 Sep 2026):

```python
"""Caesar cipher tool: shift-based encryption/decryption of text."""

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
        raise ValueError(f"mode must be 'encrypt' or 'decrypt', got {mode!r}")

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

    return "".join(result_chars)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_sandbox_runner.py`:

```python
"""run_tool: forged tools run in a time-limited subprocess (spec 03 §2.1, §2.4)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from talos.config import settings
from talos.sandbox import ToolResult, run_tool
from talos.sandbox.runner import STDOUT_LIMIT

FIXTURES = Path(__file__).parent / "fixtures" / "sandbox"


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setattr(settings, "WORKSPACE_DIR", ws)
    return ws


def _tool(tmp_path: Path, source: str, name: str = "tool.py") -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_returns_the_value(tmp_path):
    path = _tool(tmp_path, "def add(a: int, b: int) -> int:\n    return a + b\n")
    assert run_tool(path, "add", [2], {"b": 3}) == ToolResult(ok=True, value=5)


def test_tagged_values_cross_both_ways(tmp_path):
    path = _tool(tmp_path, "def echo(x):\n    return (x, {1: b'raw'}, 2**60)\n")
    result = run_tool(path, "echo", [{"k": (1, 2)}], {})
    assert result.value == ({"k": (1, 2)}, {1: b"raw"}, 2**60)


def test_raised_error_uses_the_executor_format(tmp_path):
    path = _tool(tmp_path, "def boom():\n    raise ValueError('kaboom')\n")
    result = run_tool(path, "boom", [], {})
    assert result.ok is False
    assert result.error == "ValueError: kaboom"
    assert result.timed_out is False


def test_real_vault_caesar_cipher_word_shift_error_is_unchanged():
    result = run_tool(
        FIXTURES / "caesar_cipher.py",
        "caesar_cipher",
        [],
        {"text": "TALOS AGENT", "shift": "seven", "mode": "encrypt"},
    )
    assert result.error == "TypeError: shift must be an int, got str"


def test_real_vault_caesar_cipher_works():
    result = run_tool(
        FIXTURES / "caesar_cipher.py",
        "caesar_cipher",
        [],
        {"text": "TALOS AGENT", "shift": 7, "mode": "encrypt"},
    )
    assert result.value == "AHSVZ HNLUA"


def test_sleeping_tool_is_killed_at_the_timeout(tmp_path):
    path = _tool(tmp_path, "import time\ndef slow():\n    time.sleep(60)\n")
    started = time.monotonic()
    result = run_tool(path, "slow", [], {}, timeout=1)
    assert time.monotonic() - started < 10
    assert result.ok is False
    assert result.timed_out is True
    assert result.error == "TimeoutError: tool ran longer than 1s"


def test_timeout_kills_processes_the_tool_started(tmp_path):
    marker = tmp_path / "grandchild.pid"
    path = _tool(
        tmp_path,
        "import subprocess, sys, time\n"
        "def spawn(marker):\n"
        "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "    open(marker, 'w').write(str(p.pid))\n"
        "    time.sleep(60)\n",
    )
    result = run_tool(path, "spawn", [str(marker)], {}, timeout=2)
    assert result.timed_out is True
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild process survived the timeout")


def test_default_timeout_comes_from_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TOOL_TIMEOUT", 1.0)
    path = _tool(tmp_path, "import time\ndef slow():\n    time.sleep(60)\n")
    result = run_tool(path, "slow", [], {})
    assert result.error == "TimeoutError: tool ran longer than 1s"


def test_prints_are_captured_and_do_not_corrupt_the_reply(tmp_path):
    path = _tool(
        tmp_path,
        "import sys\n"
        "def chatty():\n"
        "    print('hello')\n"
        "    print('{\"ok\": false}')\n"
        "    sys.stdout.write('no newline')\n"
        "    return 'done'\n",
    )
    result = run_tool(path, "chatty", [], {})
    assert result.ok is True
    assert result.value == "done"
    assert result.stdout == 'hello\n{"ok": false}\nno newline'


def test_output_written_straight_to_the_fd_is_kept_as_stdout(tmp_path):
    path = _tool(
        tmp_path, "import os\ndef raw():\n    os.write(1, b'raw bytes\\n')\n    return 1\n"
    )
    result = run_tool(path, "raw", [], {})
    assert result.value == 1
    assert "raw bytes" in result.stdout


def test_stdout_is_truncated(tmp_path):
    path = _tool(tmp_path, "def loud():\n    print('x' * 200_000)\n")
    result = run_tool(path, "loud", [], {})
    assert result.ok is True
    assert len(result.stdout) <= STDOUT_LIMIT + 20


def test_returned_objects_arrive_as_repr_strings(tmp_path):
    path = _tool(
        tmp_path,
        "import os\n"
        "class Evil:\n"
        "    def __reduce__(self):\n"
        "        return (os.system, ('touch pwned',))\n"
        "    def __repr__(self):\n"
        "        return '<Evil>'\n"
        "def make():\n"
        "    return Evil()\n",
    )
    result = run_tool(path, "make", [], {})
    assert result.ok is True
    assert result.value == "<Evil>"
    assert not (Path.cwd() / "pwned").exists()


def test_self_referencing_value_falls_back_to_repr(tmp_path):
    path = _tool(tmp_path, "def loop():\n    x = []\n    x.append(x)\n    return x\n")
    assert run_tool(path, "loop", [], {}).value == "[[...]]"


def test_input_gets_eof_instead_of_hanging(tmp_path):
    path = _tool(tmp_path, "def ask():\n    return input('name? ')\n")
    result = run_tool(path, "ask", [], {}, timeout=5)
    assert result.timed_out is False
    assert result.error == "EOFError: EOF when reading a line"


def test_hard_exit_is_reported_as_a_crash(tmp_path):
    path = _tool(tmp_path, "import os\ndef die():\n    os._exit(3)\n")
    result = run_tool(path, "die", [], {})
    assert result.ok is False
    assert result.error.startswith("SandboxError: tool process exited with code 3")


def test_sys_exit_is_a_tool_error(tmp_path):
    path = _tool(tmp_path, "import sys\ndef leave():\n    sys.exit('bye')\n")
    assert run_tool(path, "leave", [], {}).error == "SystemExit: bye"


def test_missing_function_is_an_error(tmp_path):
    path = _tool(tmp_path, "def other():\n    return 1\n")
    assert (
        run_tool(path, "absent", [], {}).error
        == "AttributeError: tool.py defines no function 'absent'"
    )


def test_syntax_error_is_an_error(tmp_path):
    path = _tool(tmp_path, "def broken(:\n")
    assert run_tool(path, "broken", [], {}).error.startswith("SyntaxError:")


def test_cwd_is_the_workspace(tmp_path, workspace):
    path = _tool(tmp_path, "def write():\n    open('out.txt', 'w').write('hi')\n    return 'ok'\n")
    assert run_tool(path, "write", [], {}).ok is True
    assert (workspace / "out.txt").read_text() == "hi"


def test_workspace_module_does_not_shadow_the_stdlib(tmp_path, workspace):
    workspace.mkdir(parents=True)
    (workspace / "json.py").write_text("raise RuntimeError('shadowed')\n")
    path = _tool(tmp_path, "import json\ndef dump():\n    return json.dumps([1])\n")
    assert run_tool(path, "dump", [], {}).value == "[1]"


def test_tool_sees_the_parent_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TALOS_SANDBOX_TEST_KEY", "secret-123")
    path = _tool(
        tmp_path, "import os\ndef key():\n    return os.environ['TALOS_SANDBOX_TEST_KEY']\n"
    )
    assert run_tool(path, "key", [], {}).value == "secret-123"


def test_state_does_not_leak_between_calls(tmp_path):
    path = _tool(
        tmp_path,
        "COUNTER = []\ndef bump():\n    COUNTER.append(1)\n    return len(COUNTER)\n",
    )
    assert run_tool(path, "bump", [], {}).value == 1
    assert run_tool(path, "bump", [], {}).value == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sandbox_runner.py -q`
Expected: collection error, `AttributeError: module 'talos.sandbox' has no attribute 'ToolResult'` (or `ModuleNotFoundError` for `talos.sandbox.runner`).

- [ ] **Step 4: Add the setting**

In `talos/config/settings.py`, directly after the line `LLM_TIMEOUT = float(os.environ.get("TALOS_LLM_TIMEOUT", "120"))`, add:

```python
# Wall-clock limit (seconds) for one sandboxed forged-tool call.
TOOL_TIMEOUT = float(os.environ.get("TALOS_TOOL_TIMEOUT", "30"))
```

- [ ] **Step 5: Write the child**

Create `talos/sandbox/child.py`:

```python
"""Sandbox child: runs one forged-tool call and reports back (spec 03 §2.1).

Started by `talos.sandbox.runner.run_tool` as
`python -P -m talos.sandbox.child`. Protocol:

1. Read one JSON request from stdin:
   `{"source_path", "function", "args", "kwargs", "sentinel"}`, with args
   and kwargs in the tagged form from `talos.sandbox.codec`.
2. Load the tool file into a fresh namespace and call the function, with
   `sys.stdout` redirected into a buffer so the tool's prints can't corrupt
   the reply, and stdin emptied so `input()` gets EOF instead of hanging.
3. Write the sentinel line, then one JSON reply line to the real stdout:
   `{"ok", "value", "error", "stdout"}`.

This module must only import the stdlib and `talos.sandbox.codec`.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

from talos.sandbox.codec import decode, encode, safe_repr


def _error_text(exc: BaseException) -> str:
    """Same format the executor has always used: `TypeError: message`."""
    return f"{type(exc).__name__}: {exc}"


def _load_function(source_path: str, function: str) -> Any:
    """exec the tool file in a fresh namespace and return `function`."""
    path = Path(source_path)
    source = path.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {"__name__": f"talos.vault.tools.{path.stem}"}
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 — this is the sandbox
    fn = namespace.get(function)
    if fn is None:
        raise AttributeError(f"{path.name} defines no function {function!r}")
    if not callable(fn):
        raise TypeError(f"{function!r} in {path.name} is not callable")
    return fn


def _encode_value(value: Any) -> Any:
    """Encode the return value; fall back to its repr if encoding fails
    (e.g. a self-referencing list hits the recursion limit)."""
    try:
        encoded = encode(value)
        json.dumps(encoded)
        return encoded
    except Exception:  # noqa: BLE001 — never lose the reply over a weird value
        return encode(safe_repr(value))


def run_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one request and build the reply dict (no I/O on real stdout).

    Args:
        request: The decoded stdin request.

    Returns:
        `{"ok", "value", "error", "stdout"}` with `value` in tagged form.
    """
    captured = io.StringIO()
    reply: dict[str, Any] = {"ok": False, "value": None, "error": None, "stdout": ""}
    real_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(captured):
            fn = _load_function(request["source_path"], request["function"])
            args = decode(request.get("args") or [])
            kwargs = decode(request.get("kwargs") or {})
            value = fn(*args, **kwargs)
        reply["ok"] = True
        reply["value"] = _encode_value(value)
    except BaseException as e:  # noqa: BLE001 — SystemExit/KeyboardInterrupt are tool errors too
        reply["error"] = _error_text(e)
    finally:
        sys.stdin = real_stdin
    reply["stdout"] = captured.getvalue()
    return reply


def main() -> int:
    """Entry point for `python -m talos.sandbox.child`."""
    out = sys.stdout
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as e:
        out.write(f"\nbad request: {e}\n")
        return 2
    reply = run_request(request)
    out.write("\n" + str(request.get("sentinel", "")) + "\n")
    out.write(json.dumps(reply) + "\n")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write the runner**

Create `talos/sandbox/runner.py`:

```python
"""run_tool: call one forged-tool function in a time-limited subprocess.

Spec 03 §2.1. The parent never unpickles anything: arguments and the
return value cross the boundary as tagged JSON (`talos.sandbox.codec`).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from talos.config import settings
from talos.sandbox.codec import decode, encode

logger = logging.getLogger(__name__)

# Captured tool output kept in ToolResult.stdout (characters).
STDOUT_LIMIT = 64 * 1024

# The directory that holds the `talos` package, so the child can import
# talos.sandbox.child even when its cwd is the workspace.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

# How long to wait for a killed child's pipes to close.
_REAP_TIMEOUT = 5.0


@dataclass
class ToolResult:
    """Outcome of one sandboxed tool call.

    Attributes:
        ok: True when the function returned normally.
        value: The decoded return value when ok.
        error: `"TypeError: shift must be an int, got str"` style text.
        timed_out: True when the call was killed for running too long.
        stdout: The tool's printed output, truncated to 64 KB.
    """

    ok: bool
    value: Any = None
    error: str | None = None
    timed_out: bool = False
    stdout: str = ""


def _truncate(text: str) -> str:
    if len(text) <= STDOUT_LIMIT:
        return text
    return text[:STDOUT_LIMIT] + "\n…(truncated)"


def _child_env() -> dict[str, str]:
    """The parent's environment (tools need their API keys), plus a
    PYTHONPATH entry so the child can import the talos package."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_PACKAGE_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill the child and everything it started (it leads its own session)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _parse_reply(stdout: str, sentinel: str) -> tuple[str, dict[str, Any] | None]:
    """Split raw child stdout into (stray output, reply dict or None)."""
    marker = "\n" + sentinel + "\n"
    head, found, tail = stdout.rpartition(marker)
    if not found:
        return stdout, None
    try:
        reply = json.loads(tail.strip().splitlines()[0])
    except (ValueError, IndexError):
        return head, None
    return head, reply if isinstance(reply, dict) else None


def _crash_error(returncode: int | None, stderr: str) -> str:
    last = next((ln for ln in reversed(stderr.strip().splitlines()) if ln.strip()), "")
    detail = f": {last}" if last else ""
    return f"SandboxError: tool process exited with code {returncode} and no result{detail}"


def run_tool(
    source_path: Path,
    function: str,
    args: list[Any],
    kwargs: dict[str, Any],
    timeout: float | None = None,
) -> ToolResult:
    """Run `function` from the file at `source_path` in a subprocess.

    Args:
        source_path: The tool's .py file.
        function: Name of the function to call in that file.
        args: Positional arguments.
        kwargs: Keyword arguments.
        timeout: Seconds before the child is killed; defaults to
            `settings.TOOL_TIMEOUT` (TALOS_TOOL_TIMEOUT, 30 s).

    Returns:
        A ToolResult. It never raises for tool failures, timeouts or crashes.
    """
    limit = settings.TOOL_TIMEOUT if timeout is None else timeout
    sentinel = f"__TALOS_SANDBOX_REPLY_{secrets.token_hex(16)}__"
    request = json.dumps(
        {
            "source_path": str(Path(source_path).resolve()),
            "function": function,
            "args": encode(list(args)),
            "kwargs": encode(dict(kwargs)),
            "sentinel": sentinel,
        }
    )
    workdir = Path(settings.WORKSPACE_DIR)
    workdir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, "-P", "-m", "talos.sandbox.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workdir,
        env=_child_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(request, timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            stdout, _ = proc.communicate(timeout=_REAP_TIMEOUT)
        except subprocess.TimeoutExpired:
            stdout = ""
        logger.warning("sandboxed tool %s timed out after %ss", function, limit)
        return ToolResult(
            ok=False,
            error=f"TimeoutError: tool ran longer than {limit:g}s",
            timed_out=True,
            stdout=_truncate(stdout or ""),
        )

    stray, reply = _parse_reply(stdout, sentinel)
    if reply is None:
        return ToolResult(
            ok=False, error=_crash_error(proc.returncode, stderr), stdout=_truncate(stray)
        )
    printed = stray.rstrip("\n") + str(reply.get("stdout") or "")
    if not reply.get("ok"):
        return ToolResult(ok=False, error=str(reply.get("error")), stdout=_truncate(printed))
    try:
        value = decode(reply.get("value"))
    except (ValueError, RecursionError) as e:
        return ToolResult(
            ok=False, error=f"SandboxError: bad result: {e}", stdout=_truncate(printed)
        )
    return ToolResult(ok=True, value=value, stdout=_truncate(printed))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sandbox_runner.py -q`
Expected: 22 passed, in about 5 s (three of them wait on 1–2 s timeouts).

Run: `uv run pytest -q`
Expected: the whole unit suite passes (nothing else uses the sandbox yet).

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add talos/sandbox/child.py talos/sandbox/runner.py talos/config/settings.py tests/test_sandbox_runner.py tests/fixtures/sandbox/caesar_cipher.py
git commit -m "[Feat]: Run forged tools in a time-limited subprocess with run_tool"
```

---

### Task 3: `SandboxedTool`, `ToolFailed` and `error_text`

**Files:**
- Create: `talos/sandbox/tool.py`
- Test: `tests/test_sandbox_tool.py`

**Interfaces:**
- Consumes: `run_tool`, `ToolResult` (Task 2); `talos.agents.executor._validate_kwargs` and `schema_from_signature` (existing, used by the tests only).
- Produces:
  - `talos.sandbox.tool.signature_from_source(source: str, function: str) -> inspect.Signature` (raises `ValueError` on a syntax error or a missing function; a top-level `f = …` binding gets an open `(*args, **kwargs)` signature)
  - `talos.sandbox.tool.SandboxedTool(source_path: Path, function: str, timeout: float | None = None)`: callable; attributes `source_path`, `function`, `timeout`, `__name__`, `__signature__`; the constructor raises `ValueError` if the file can't be read or parsed or lacks the function; `__call__(*args, **kwargs)` returns the decoded value or raises `ToolFailed`
  - `talos.sandbox.tool.ToolFailed(Exception)` with `.result: ToolResult`; `str(exc)` is the tool's error text
  - `talos.sandbox.tool.error_text(exc: BaseException) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sandbox_tool.py`:

```python
"""SandboxedTool: signature from source, calls through the sandbox."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from talos.agents.executor import _validate_kwargs, schema_from_signature
from talos.config import settings
from talos.sandbox import SandboxedTool, ToolFailed
from talos.sandbox.tool import signature_from_source


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WORKSPACE_DIR", tmp_path / "workspace")


def test_signature_matches_the_real_function():
    source = (
        "def f(a, /, b: int, c: 'list[str]' = None, *rest: int, d: float = 1.5, "
        "e=len, **extra) -> dict:\n    return {}\n"
    )
    sig = signature_from_source(source, "f")
    namespace: dict = {}
    exec(source, namespace)
    real = inspect.signature(namespace["f"])
    assert list(sig.parameters) == list(real.parameters)
    assert [p.kind for p in sig.parameters.values()] == [p.kind for p in real.parameters.values()]
    assert sig.parameters["b"].annotation == "int"
    assert sig.parameters["c"].default is None
    assert sig.parameters["d"].default == 1.5
    assert repr(sig.parameters["e"].default) == "len"
    assert sig.return_annotation == "dict"


def test_signature_does_not_run_the_source(tmp_path):
    marker = tmp_path / "ran"
    source = f"open({str(marker)!r}, 'w')\ndef f(x):\n    return x\n"
    signature_from_source(source, "f")
    assert not marker.exists()


def test_last_definition_wins():
    source = "def f(a):\n    pass\ndef f(a, b):\n    pass\n"
    assert list(signature_from_source(source, "f").parameters) == ["a", "b"]


def test_assigned_callable_gets_an_open_signature():
    sig = signature_from_source("f = print\n", "f")
    assert [p.kind for p in sig.parameters.values()] == [
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ]


def test_missing_function_raises_value_error():
    with pytest.raises(ValueError, match="defines no function 'g'"):
        signature_from_source("def f():\n    pass\n", "g")


def test_syntax_error_raises_value_error():
    with pytest.raises(ValueError, match="SyntaxError"):
        signature_from_source("def f(:\n", "f")


def test_proxy_works_with_executor_introspection(tmp_path):
    path = tmp_path / "add.py"
    path.write_text("def add(a: int, b: int = 2) -> int:\n    return a + b\n")
    tool = SandboxedTool(path, "add")
    assert tool.__name__ == "add"
    assert schema_from_signature(tool) == {"a": "int", "b": "int"}
    with pytest.raises(TypeError, match="missing required args"):
        _validate_kwargs(tool, {"b": 1})
    assert tool(1) == 3


def test_failed_call_raises_tool_failed_with_the_error_text(tmp_path):
    path = tmp_path / "boom.py"
    path.write_text("def boom():\n    raise ValueError('kaboom')\n")
    with pytest.raises(ToolFailed) as info:
        SandboxedTool(path, "boom")()
    assert str(info.value) == "ValueError: kaboom"
    assert info.value.result.timed_out is False


def test_timeout_is_passed_through(tmp_path):
    path = tmp_path / "slow.py"
    path.write_text("import time\ndef slow():\n    time.sleep(30)\n")
    with pytest.raises(ToolFailed) as info:
        SandboxedTool(path, "slow", timeout=1)()
    assert info.value.result.timed_out is True


def test_unreadable_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read tool file"):
        SandboxedTool(tmp_path / "missing.py", "f")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sandbox_tool.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'talos.sandbox.tool'`.

- [ ] **Step 3: Write the implementation**

Create `talos/sandbox/tool.py`:

```python
"""SandboxedTool: a callable stand-in for a forged tool that never runs its
code in this process.

The executor and the smoke gate inspect a tool's signature (argument names,
type hints, defaults) to coerce and validate arguments before calling it.
`SandboxedTool` reads that signature from the source with `ast`, without
executing anything, and each call goes through `run_tool` in a subprocess.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

from talos.sandbox.runner import ToolResult, run_tool


class ToolFailed(Exception):
    """A sandboxed call raised, timed out or crashed.

    `str(exc)` is the tool's error text (`"TypeError: …"`), which callers
    record as-is instead of wrapping it in `ToolFailed: …`.
    """

    def __init__(self, result: ToolResult) -> None:
        super().__init__(result.error or "SandboxError: tool failed")
        self.result = result


def error_text(exc: BaseException) -> str:
    """The error string recorded for a failed tool call.

    `ToolFailed` already carries the tool's own `"TypeError: …"` text; any
    other exception is formatted the same way.
    """
    if isinstance(exc, ToolFailed):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


class _Unevaluated:
    """Default value that isn't a literal (e.g. `x=len`). Only its presence
    matters to callers; the child evaluates the real default."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _annotation(node: ast.expr | None) -> Any:
    return inspect.Parameter.empty if node is None else ast.unparse(node)


def _default(node: ast.expr | None) -> Any:
    if node is None:
        return inspect.Parameter.empty
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return _Unevaluated(ast.unparse(node))


def _signature_of_def(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> inspect.Signature:
    a = fn.args
    P = inspect.Parameter
    params: list[inspect.Parameter] = []
    positional = [*a.posonlyargs, *a.args]
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for i, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        kind = P.POSITIONAL_ONLY if i < len(a.posonlyargs) else P.POSITIONAL_OR_KEYWORD
        params.append(
            P(arg.arg, kind, default=_default(default), annotation=_annotation(arg.annotation))
        )
    if a.vararg:
        params.append(
            P(a.vararg.arg, P.VAR_POSITIONAL, annotation=_annotation(a.vararg.annotation))
        )
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        params.append(
            P(
                arg.arg,
                P.KEYWORD_ONLY,
                default=_default(default),
                annotation=_annotation(arg.annotation),
            )
        )
    if a.kwarg:
        params.append(P(a.kwarg.arg, P.VAR_KEYWORD, annotation=_annotation(a.kwarg.annotation)))
    return inspect.Signature(params, return_annotation=_annotation(fn.returns))


_OPEN_SIGNATURE = inspect.Signature(
    [
        inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL),
        inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
    ]
)


def signature_from_source(source: str, function: str) -> inspect.Signature:
    """Read `function`'s signature from Python source without running it.

    Args:
        source: The tool file's text.
        function: The top-level function name.

    Returns:
        The signature, with annotations as source strings (`"int"`,
        `"list[str]"`). A name bound some other way at top level (e.g.
        `f = make_f()`) gets an open `(*args, **kwargs)` signature.

    Raises:
        ValueError: If the source doesn't parse or doesn't define `function`.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"SyntaxError: {e}") from e
    found: inspect.Signature | None = None
    for node in tree.body:  # the last top-level binding wins, as at runtime
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            found = _signature_of_def(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == function for t in targets):
                found = _OPEN_SIGNATURE
    if found is None:
        raise ValueError(f"source defines no function {function!r}")
    return found


class SandboxedTool:
    """Callable proxy for a tool file; every call runs in a subprocess.

    `inspect.signature(tool)` returns the signature parsed from the source,
    and `tool.__name__` is the function name, so code written for plain
    functions (coercion, validation, `describe_args`) keeps working.
    """

    def __init__(self, source_path: Path, function: str, timeout: float | None = None) -> None:
        """Parse the tool's signature.

        Args:
            source_path: The tool's .py file.
            function: The function to call in it.
            timeout: Per-call limit; None means `settings.TOOL_TIMEOUT`.

        Raises:
            ValueError: If the file can't be read, doesn't parse, or doesn't
                define `function`.
        """
        self.source_path = Path(source_path)
        self.function = function
        self.timeout = timeout
        try:
            source = self.source_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"cannot read tool file {self.source_path}: {e}") from e
        self.__signature__ = signature_from_source(source, function)
        self.__name__ = function

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the tool in the sandbox.

        Returns:
            The tool's decoded return value.

        Raises:
            ToolFailed: If the tool raised, timed out or crashed.
        """
        result = run_tool(self.source_path, self.function, list(args), kwargs, self.timeout)
        if not result.ok:
            raise ToolFailed(result)
        return result.value

    def __repr__(self) -> str:
        return f"<SandboxedTool {self.function} from {self.source_path.name}>"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sandbox_tool.py -q`
Expected: 10 passed.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add talos/sandbox/tool.py tests/test_sandbox_tool.py
git commit -m "[Feat]: Add SandboxedTool, a callable proxy that reads the signature without running the tool"
```

---

### Task 4: Executor runs vault and forged tools through the sandbox

**Files:**
- Modify: `talos/vault/manager.py` (add `locate()` before `load()`; extend `load()`'s docstring)
- Modify: `talos/agents/executor.py` (module docstring, import, `_sandboxed()`, `_resolve_callable()`, the tool-call `except`)
- Test: `tests/test_vault_manager.py` (append), `tests/test_executor.py` (append). Existing tests in both files stay exactly as they are and must keep passing.

**Interfaces:**
- Consumes: `SandboxedTool`, `error_text` (Task 3); `settings.TOOL_TIMEOUT` (Task 2).
- Produces:
  - `SkillManager.locate(name: str) -> tuple[Path, str]`: `(tool file path, function name)` from the manifest; raises `KeyError(f"No skill named {name!r} in manifest")`.
  - `talos.agents.executor._sandboxed(mgr: SkillManager, name: str) -> SandboxedTool`
  - Behaviour: for `needs` `vault` and `forge`, `executor_node` calls a `SandboxedTool`; a timeout is recorded like any other failure (`call.error` with `when="run"`, `record_failure`, `vault.failure`). `SkillManager.load()` is never called.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_manager.py`:

```python
def test_locate_returns_file_and_function(manager):
    manager.register(
        {"name": "adder2", "description": "d", "keywords": ["add"], "function": "adder2"},
        "def adder2(a, b):\n    return a + b\n",
    )
    path, function = manager.locate("adder2")
    assert path == manager.vault_dir / "tools" / "adder2.py"
    assert path.is_file()
    assert function == "adder2"


def test_locate_unknown_tool_raises_key_error(manager):
    with pytest.raises(KeyError, match="No skill named 'nope'"):
        manager.locate("nope")
```

Append to `tests/test_executor.py` (it already imports `os`, `Path`, `pytest`, `SkillManager`, and defines `_patch_resolver`, `_state`, `_exec_events` and `_add_tool` above):

```python
# ---- sandbox (spec 03 §2.3) -------------------------------------------------


def _register(vault: SkillManager, name: str, code: str, signature: str) -> None:
    vault.register(
        {
            "name": name,
            "description": name,
            "keywords": [name],
            "function": name,
            "signature": signature,
        },
        code,
    )


def test_vault_tool_runs_in_another_process(vault, monkeypatch):
    _register(
        vault,
        "whoami",
        "import os\ndef whoami() -> int:\n    return os.getpid()\n",
        "whoami() -> int",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "whoami", "action": "pid"}
    rec = executor_node(_state(current_sub_task=sub_task))["sub_task_results"][0]
    assert rec["ok"] is True
    assert rec["output"] != os.getpid()


def test_vault_tool_timeout_is_a_recorded_failure(vault, monkeypatch):
    from talos.config import settings

    monkeypatch.setattr(settings, "TOOL_TIMEOUT", 1.0)
    _register(
        vault, "sleepy", "import time\ndef sleepy():\n    time.sleep(60)\n", "sleepy() -> None"
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "sleepy", "action": "sleep"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert events[1] == {
        "type": "call.error",
        "data": {"error": "TimeoutError: tool ran longer than 1s", "when": "run"},
    }
    assert events[2]["type"] == "vault.failure"
    entry = vault.get("sleepy")
    assert entry["consecutive_failures"] == 1
    assert entry["last_failure_reason"] == "TimeoutError: tool ran longer than 1s"


def test_real_vault_caesar_cipher_word_shift_fails_the_same_way(vault, monkeypatch):
    source = (Path(__file__).parent / "fixtures" / "sandbox" / "caesar_cipher.py").read_text()
    _register(
        vault, "caesar_cipher", source, "caesar_cipher(text: str, shift: int, mode: str) -> str"
    )
    _patch_resolver(
        monkeypatch,
        ResolvedArgs(args=[], kwargs={"text": "TALOS AGENT", "shift": "seven", "mode": "encrypt"}),
    )
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "caesar_cipher", "action": "encrypt"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert events[0]["data"]["args"][1] == ["shift", "'seven'", True]
    assert events[-1]["data"]["error"] == "TypeError: shift must be an int, got str"


def test_vault_tool_with_missing_file_is_a_dispatch_error(vault, monkeypatch):
    _register(vault, "gone", "def gone():\n    return 1\n", "gone() -> int")
    (vault.tools_dir / "gone.py").unlink()
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "gone", "action": "x"}
    rec = executor_node(_state(current_sub_task=sub_task))["sub_task_results"][0]
    assert rec["ok"] is False
    assert rec["error"].startswith("dispatch error: cannot read tool file")


def test_executor_never_calls_skill_manager_load(vault, monkeypatch):
    _add_tool(vault)
    monkeypatch.setattr(
        SkillManager, "load", lambda self, name: pytest.fail("executor must not load in-process")
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[2, 3], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}
    assert executor_node(_state(current_sub_task=sub_task))["sub_task_results"][0]["output"] == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_vault_manager.py tests/test_executor.py -q`
Expected: failures: `AttributeError: 'SkillManager' object has no attribute 'locate'`; `test_vault_tool_runs_in_another_process` (same pid); `test_vault_tool_timeout_is_a_recorded_failure` (the tool sleeps 60 s in-process, so expect this one to take a minute); `test_vault_tool_with_missing_file_is_a_dispatch_error` (`FileNotFoundError` escapes the node); `test_executor_never_calls_skill_manager_load`.

- [ ] **Step 3: Add `SkillManager.locate()`**

In `talos/vault/manager.py`, replace:

```python
    def load(self, name: str) -> Callable[..., Any]:
        """Return the callable for a registered tool.

```

with:

```python
    def locate(self, name: str) -> tuple[Path, str]:
        """Return the tool's file and the function to call in it.

        This is how the executor finds a tool to run in the sandbox
        (`talos.sandbox`); it reads nothing but the manifest.

        Args:
            name: The tool's name.

        Returns:
            `(path to the .py file, function name)`.

        Raises:
            KeyError: If the tool isn't in the manifest.
        """
        entry = self._find(name)
        if entry is None:
            raise KeyError(f"No skill named {name!r} in manifest")
        file_path = self.vault_dir / entry.get("file", f"tools/{name}.py")
        return file_path, entry.get("function") or name

    def load(self, name: str) -> Callable[..., Any]:
        """Return the callable for a registered tool.

        Not used by the executor any more: it runs vault tools in a
        subprocess through `talos.sandbox`. Kept for backward compatibility
        and tests. This runs the tool's code in the current process.

```

- [ ] **Step 4: Switch the executor**

In `talos/agents/executor.py`:

1. In the module docstring, replace

```text
- vault      → SkillManager.load(name)(...)
- forge      → after Learn registers it, vault.load(forged_tool['name'])(...)
```

with

```text
- vault      → the vault tool, run in a subprocess via talos.sandbox
- forge      → after Learn registers it, the forged tool, same sandbox

Vault and forged tools never run in this process: `SandboxedTool` reads
their signature from the source (for arg coercion and validation) and each
call goes through `run_tool`, with a TALOS_TOOL_TIMEOUT limit.
```

2. After `from talos.prompts.arg_resolver import ARG_RESOLVER_SYSTEM_PROMPT`, add:

```python
from talos.sandbox import SandboxedTool, error_text
```

3. Directly above `def _resolve_callable(`, add:

```python
def _sandboxed(mgr: SkillManager, name: str) -> SandboxedTool:
    """A subprocess-backed callable for the vault tool `name`.

    Raises KeyError if it isn't in the manifest, ValueError if its file is
    missing, doesn't parse, or doesn't define the function.
    """
    path, function = mgr.locate(name)
    return SandboxedTool(path, function)


```

4. In `_resolve_callable`, replace `return mgr.load(hint)` with `return _sandboxed(mgr, hint)` and `return mgr.load(name)` with `return _sandboxed(mgr, name)`. The `except (ValueError, KeyError)` around `_resolve_callable` in `executor_node` already turns both errors into `dispatch error: …`.

5. In `executor_node`, replace:

```python
    except Exception as e:  # noqa: BLE001 — tool execution may legitimately fail
        output = None
        ok = False
        error = f"{type(e).__name__}: {e}"
```

with:

```python
    except Exception as e:  # noqa: BLE001 — tool execution may legitimately fail
        # Sandboxed tools raise ToolFailed carrying the tool's own
        # "TypeError: …" text (or a timeout); primitives raise directly.
        output = None
        ok = False
        error = error_text(e)
```

Nothing else in the executor changes: `_signature_of`, `_coerce_call_args`, `_validate_kwargs` and `describe_args` all work on the `SandboxedTool` through `inspect.signature`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_vault_manager.py tests/test_executor.py tests/test_orchestrator.py tests/test_graph_flow.py -q`
Expected: all pass (the existing executor tests now run their vault tools in subprocesses; a few seconds slower in total).

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add talos/vault/manager.py talos/agents/executor.py tests/test_vault_manager.py tests/test_executor.py
git commit -m "[Feat]: Run vault and forged tools in the sandbox from the executor"
```

---

### Task 5: Smoke gate runs forged code through the sandbox

**Files:**
- Modify: `talos/agents/smoke.py`
- Test: `tests/test_smoke.py` (append; existing tests unchanged and must pass)

**Interfaces:**
- Consumes: `SandboxedTool`, `error_text` (Task 3); `settings.TOOL_TIMEOUT` (Task 2).
- Produces: `talos.agents.smoke._write_forged_tool(forged: dict, directory: Path) -> SandboxedTool` (raises `ValueError`); `talos.agents.smoke._smoke(fn: SandboxedTool, forged: dict, sub_task: dict, state: TalosState) -> dict`. `smoke_node`'s inputs, outputs and `forge.smoke` events are unchanged. `_load_forged_function` is removed (nothing else imports it).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py` (it already defines `_state` and `_ADD_TASK` above):

```python
# ---- sandbox (spec 03 §2.3) ----------------------------------------------------


def test_smoke_runs_the_tool_in_another_process():
    import os

    code = "import os\ndef pid():\n    return os.getpid()\n"
    out = smoke_node(_state(code, "pid", {"id": 1, "needs": "forge"}))
    assert out["smoke_result"]["passed"] is True
    assert out["smoke_result"]["output"] != os.getpid()


def test_smoke_times_out_a_hanging_tool(monkeypatch):
    from talos.config import settings

    monkeypatch.setattr(settings, "TOOL_TIMEOUT", 1.0)
    code = "import time\ndef hang():\n    time.sleep(60)\n"
    out = smoke_node(_state(code, "hang", {"id": 1, "needs": "forge"}))
    assert out["smoke_result"] == {
        "passed": False,
        "skipped": False,
        "error": "runtime: TimeoutError: tool ran longer than 1s",
    }


def test_smoke_reports_a_missing_import_as_a_runtime_failure():
    code = "import no_such_module_talos\ndef f():\n    return 1\n"
    out = smoke_node(_state(code, "f", {"id": 1, "needs": "forge"}))
    assert out["smoke_result"]["passed"] is False
    assert "ModuleNotFoundError" in out["smoke_result"]["error"]


def test_smoke_load_error_when_function_is_missing():
    out = smoke_node(_state("def other():\n    return 1\n", "wanted", _ADD_TASK))
    assert out["smoke_result"]["error"] == "load error: source defines no function 'wanted'"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -q`
Expected: `test_smoke_runs_the_tool_in_another_process` fails (same pid), `test_smoke_times_out_a_hanging_tool` fails after about 60 s (in-process sleep, no timeout), `test_smoke_reports_a_missing_import_as_a_runtime_failure` errors (`ModuleNotFoundError` escapes the node), `test_smoke_load_error_when_function_is_missing` fails on the message.

- [ ] **Step 3: Switch smoke to the sandbox**

In `talos/agents/smoke.py`:

1. Replace the imports block

```python
import inspect
from typing import Any
```

with

```python
import inspect
import tempfile
from pathlib import Path
from typing import Any
```

and after `from talos.events import emit` add:

```python
from talos.sandbox import SandboxedTool, error_text
```

2. Replace the whole `_load_forged_function` function with:

```python
def _write_forged_tool(forged: dict, directory: Path) -> SandboxedTool:
    """Write the forged source into `directory` and return a sandboxed
    callable for it. The code never runs in this process.

    Raises:
        ValueError: If the forged tool has no name or code, the code doesn't
            parse, or it doesn't define a function named `forged['name']`.
    """
    name = forged.get("name")
    code = forged.get("code", "")
    if not name or not code:
        raise ValueError("forged_tool missing name or code")
    path = directory / "forged_tool.py"
    path.write_text(code, encoding="utf-8")
    return SandboxedTool(path, name)
```

3. In `smoke_node`, replace this block (everything from the load `try` up to, but not including, `has_contract = …`):

```python
    try:
        fn = _load_forged_function(forged)
    except (SyntaxError, ValueError) as e:
        emit("forge.smoke", call=None, result=None, passed=False)
        return {
            "smoke_result": {
                "passed": False,
                "skipped": False,
                "error": f"load error: {type(e).__name__}: {e}",
            }
        }

```

with:

```python
    # Unregistered code: write it to a temporary file for the sandbox.
    with tempfile.TemporaryDirectory(prefix="talos-smoke-") as tmp:
        try:
            fn = _write_forged_tool(forged, Path(tmp))
        except ValueError as e:
            emit("forge.smoke", call=None, result=None, passed=False)
            return {
                "smoke_result": {"passed": False, "skipped": False, "error": f"load error: {e}"}
            }
        return _smoke(fn, forged, sub_task, state)


def _smoke(fn: SandboxedTool, forged: dict, sub_task: dict, state: TalosState) -> dict:
    """Build the call from the sub-task contract and run it once in the sandbox."""
```

The rest of the old `smoke_node` body (from `has_contract = bool(sub_task.get("input_schema"))` to the final `return`) now forms the body of `_smoke`, unchanged except for one line.

4. In that body, in the runtime `except Exception as e:` block, replace

```python
                "error": f"runtime: {type(e).__name__}: {e}",
```

with

```python
                "error": f"runtime: {error_text(e)}",
```

The temporary directory lives until `_smoke` returns, so the child can read the file; it is removed afterwards even when the tool fails.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py tests/test_forger.py tests/test_graph_flow.py -q`
Expected: all pass.

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green. `grep -n "exec(" talos/agents/smoke.py talos/agents/executor.py` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add talos/agents/smoke.py tests/test_smoke.py
git commit -m "[Feat]: Run the smoke gate's forged code in the sandbox"
```

---

### Task 6: Database wait for the container entrypoint

**Files:**
- Create: `talos/persistence/wait.py`
- Test: `tests/test_wait_for_db.py`

**Interfaces:**
- Consumes: `talos.persistence.db.libpq_url(url: str) -> str` (stage 1), `settings.DATABASE_URL`.
- Produces: `talos.persistence.wait.wait_for_db(url: str, timeout: float = 60.0, interval: float = 1.0, *, connect=psycopg.connect, sleep=time.sleep, clock=time.monotonic) -> None` (raises `TimeoutError`, `ValueError`); `talos.persistence.wait.main() -> int`; `python -m talos.persistence.wait` exits 0 when the database answers, 1 otherwise. Env `TALOS_DB_WAIT_TIMEOUT` (seconds, default 60). Used by `docker/entrypoint.sh` in Task 7.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wait_for_db.py`:

```python
"""wait_for_db: the Docker entrypoint's database wait (spec 03 §3)."""

from __future__ import annotations

import psycopg
import pytest

from talos.persistence import wait as wait_mod
from talos.persistence.wait import wait_for_db

URL = "postgresql+psycopg://talos:talos@db:5432/talos"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Conn:
    def close(self) -> None:
        pass


def test_returns_once_the_database_answers():
    clock = _Clock()
    calls: list[tuple] = []

    def connect(conninfo, **kwargs):
        calls.append((conninfo, kwargs))
        if len(calls) < 3:
            raise psycopg.OperationalError("connection refused")
        return _Conn()

    wait_for_db(URL, timeout=10, connect=connect, sleep=clock.sleep, clock=clock)
    assert len(calls) == 3
    assert calls[0] == ("postgresql://talos:talos@db:5432/talos", {"connect_timeout": 3})


def test_gives_up_after_the_timeout():
    clock = _Clock()

    def connect(conninfo, **kwargs):
        raise psycopg.OperationalError("connection refused")

    with pytest.raises(TimeoutError, match="not reachable after 5s"):
        wait_for_db(URL, timeout=5, interval=1, connect=connect, sleep=clock.sleep, clock=clock)
    assert clock.now == 5


def test_rejects_a_non_postgres_url():
    with pytest.raises(ValueError, match="Postgres URL"):
        wait_for_db("mysql://x", connect=lambda *a, **k: _Conn())


def test_main_fails_without_database_url(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", "")
    assert wait_mod.main() == 1


def test_main_returns_zero_when_ready(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", URL)
    monkeypatch.setattr(wait_mod, "wait_for_db", lambda url, timeout: None)
    assert wait_mod.main() == 0


def test_main_reports_a_timeout(monkeypatch):
    monkeypatch.setattr(wait_mod.settings, "DATABASE_URL", URL)
    monkeypatch.setenv("TALOS_DB_WAIT_TIMEOUT", "2")

    def boom(url, timeout):
        assert timeout == 2.0
        raise TimeoutError("database not reachable after 2s")

    monkeypatch.setattr(wait_mod, "wait_for_db", boom)
    assert wait_mod.main() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_wait_for_db.py -q`
Expected: `ModuleNotFoundError: No module named 'talos.persistence.wait'`.

- [ ] **Step 3: Write the implementation**

Create `talos/persistence/wait.py`:

```python
"""Wait until Postgres accepts connections (Docker entrypoint).

`python -m talos.persistence.wait` blocks until DATABASE_URL answers or
TALOS_DB_WAIT_TIMEOUT seconds (default 60) pass, then exits 0 or 1.
Compose already waits for the db healthcheck; this also covers a database
that is up but still restarting, and a DATABASE_URL pointing elsewhere.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import psycopg

from talos.config import settings
from talos.persistence.db import libpq_url

logger = logging.getLogger(__name__)


def wait_for_db(
    url: str,
    timeout: float = 60.0,
    interval: float = 1.0,
    *,
    connect: Callable[..., Any] = psycopg.connect,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Block until a connection to `url` succeeds.

    Args:
        url: Postgres URL in any form `libpq_url` accepts.
        timeout: Seconds to keep trying.
        interval: Seconds between attempts.
        connect: psycopg.connect, replaceable in tests.
        sleep: time.sleep, replaceable in tests.
        clock: time.monotonic, replaceable in tests.

    Raises:
        ValueError: If `url` is not a Postgres URL.
        TimeoutError: If no attempt succeeded within `timeout`.
    """
    conninfo = libpq_url(url)
    deadline = clock() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            connect(conninfo, connect_timeout=3).close()
            logger.info("database is ready after %d attempt(s)", attempt)
            return
        except psycopg.OperationalError as e:
            if clock() >= deadline:
                raise TimeoutError(f"database not reachable after {timeout:g}s: {e}") from e
            logger.info("waiting for the database (attempt %d): %s", attempt, e)
            sleep(interval)


def main() -> int:
    """CLI entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL is not set; the web app needs Postgres.")
        return 1
    timeout = float(os.environ.get("TALOS_DB_WAIT_TIMEOUT", "60"))
    try:
        wait_for_db(settings.DATABASE_URL, timeout=timeout)
    except (TimeoutError, ValueError) as e:
        logger.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_wait_for_db.py -q`
Expected: 6 passed.

Optional real check against the test container (only if `talos-pg-test` is running): `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run python -m talos.persistence.wait; echo $?` prints `INFO … database is ready after 1 attempt(s)` and `0`.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add talos/persistence/wait.py tests/test_wait_for_db.py
git commit -m "[Feat]: Add a database wait for the container entrypoint"
```

---

### Task 7: Docker image and the placeholder frontend

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/placeholder.html`
- Create: `Dockerfile`, `.dockerignore`, `docker/entrypoint.sh`

**Interfaces:**
- Consumes: `python -m talos.persistence.wait` (Task 6), `alembic.ini` + `alembic/` (stage 1), console script `talos-web` and `GET /api/health` (stage 2), `frontend/dist` served by stage 2's app.
- Produces: image stages `frontend`, `deps`, `test`, `runtime` (default). `test` is used by `compose.test.yml` (Task 8). Stage 04 replaces the placeholder frontend without touching the Dockerfile (see Rulings).

This task is configuration, so its "test" is the build and a run of the built image.

- [ ] **Step 1: Confirm stage 2's names**

Run: `grep -n "talos-web" pyproject.toml && grep -rn "api/health\|frontend.*dist" talos/web | head`
Expected: `talos-web = "talos.web…"` in `[project.scripts]`, a `/api/health` route, and the static mount reading `frontend/dist` under the project root. If any differ, stop and tell the controller before writing the Dockerfile.

- [ ] **Step 2: Add the placeholder frontend**

Create `frontend/package.json`:

```json
{
  "name": "talos-workbench",
  "version": "0.0.0",
  "private": true,
  "description": "Placeholder until stage 04 ports the Workbench. Stage 04 replaces this file.",
  "scripts": {
    "build": "rm -rf dist && mkdir -p dist && cp placeholder.html dist/index.html",
    "dev": "echo 'The Workbench frontend arrives in stage 04.' && exit 1"
  }
}
```

Create `frontend/package-lock.json` (exactly what `npm install --package-lock-only` produces for that package.json):

```json
{
  "name": "talos-workbench",
  "version": "0.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "talos-workbench",
      "version": "0.0.0"
    }
  }
}
```

Create `frontend/placeholder.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Talos Workbench</title>
  </head>
  <body>
    <p>Talos is running. The Workbench frontend arrives in stage 04; the API is at <a href="/api/health">/api/health</a>.</p>
  </body>
</html>
```

Check: `cd frontend && npm ci && npm run build && ls dist && rm -rf dist node_modules && cd ..`
Expected: `index.html`.

- [ ] **Step 3: Write the Dockerfile, entrypoint and .dockerignore**

Create `Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
# Talos web app image (spec 03 §3). Build: `docker build .` (runtime target).
# Stages: frontend (Vite build) → deps (uv venv) → test (dev extras, for
# compose.test.yml) → runtime (what `docker compose up` runs).

# ---- 1. frontend: build frontend/dist ----------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. deps: the Python venv at /app/.venv -------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS deps
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Third-party packages first, so source edits don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# The project itself, installed editable: talos/ must stay at /app/talos,
# because settings.PROJECT_ROOT (alembic.ini, alembic/) is derived from it.
COPY README.md LICENSE ./
COPY talos/ ./talos/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- 3. test: deps + dev extras + tests (compose.test.yml) ---------------------
FROM deps AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra dev
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY tests/ ./tests/
COPY docs/superpowers/specs/reference/ ./docs/superpowers/specs/reference/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["pytest", "-q"]

# ---- 4. runtime -----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin talos \
    && mkdir -p /data/vault/tools /data/workspace \
    && chown -R talos:talos /data
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY talos/ ./talos/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY --chmod=755 docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --from=frontend /frontend/dist /app/frontend/dist
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TALOS_VAULT_DIR=/data/vault \
    TALOS_WORKSPACE_DIR=/data/workspace \
    TALOS_DOTENV_PATH=/data/.env \
    TALOS_WEB_HOST=0.0.0.0 \
    TALOS_WEB_PORT=8000
USER talos
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
```

Create `docker/entrypoint.sh` and make it executable (`chmod +x docker/entrypoint.sh`; the Dockerfile also sets mode 755 on copy):

```sh
#!/bin/sh
# Container entrypoint (spec 03 §3): wait for Postgres, migrate, start the app.
set -eu

cd /app
python -m talos.persistence.wait
alembic upgrade head
exec talos-web "$@"
```

Create `.dockerignore`:

```gitignore
# Keep the build context small and free of local state and secrets.
.git
.github
.venv
venv
.env
.env.*
!.env.example
**/__pycache__
**/*.py[cod]
.pytest_cache
.ruff_cache
.mypy_cache
.coverage
htmlcov
.DS_Store
.superpowers
workspace/
talos/vault/tools/*.py
talos/vault/manifest.json
talos logos/
site/
assets/
benchmarks/
benchmarks.txt
docs/
# Stage 02's copy test reads the reference demo (test image only).
!docs/superpowers/specs/reference/
examples/
**/node_modules
frontend/dist
frontend/test-results
frontend/playwright-report
frontend/.e2e-tmp
```

- [ ] **Step 4: Build the image**

Run: `docker build -t talos-web:dev .`
Expected: success; the `frontend`, `deps` and `runtime` stages run and `test` is skipped. About 1 minute cold.

Run: `docker run --rm --entrypoint sh talos-web:dev -c 'id && which talos-web && python -c "import talos; print(talos.__file__)" && ls /app/frontend/dist'`
Expected: `uid=1000(talos) gid=1000(talos)`, `/app/.venv/bin/talos-web`, `/app/talos/__init__.py`, `index.html`.

Run: `docker build --target test -t talos-web:test . && docker run --rm talos-web:test pytest -q`
Expected: the unit suite passes inside the image (integration tests skipped: no `DATABASE_URL`).

- [ ] **Step 5: Clean up and commit**

```bash
docker image rm talos-web:dev talos-web:test
git add frontend/package.json frontend/package-lock.json frontend/placeholder.html Dockerfile .dockerignore docker/entrypoint.sh
git commit -m "[Feat]: Add the Docker image with a placeholder frontend until stage 04"
```

---

### Task 8: Compose stack and Makefile

**Files:**
- Create: `compose.yml`, `compose.dev.yml`, `compose.test.yml`, `Makefile`
- Test: `tests/test_docker_files.py`

**Interfaces:**
- Consumes: the image from Task 7 (`build: .`, and `target: test`).
- Produces: `make up | down | db | migrate | web | fake | test | test-int | fe` (spec §5). `make test-int` always uses compose project `talos-test`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docker_files.py`:

```python
"""Safety settings in the Docker and compose files (spec 03 §3–§5).

These are plain text/YAML checks, so they run in the unit suite with no
Docker. They pin the settings a later edit could silently weaken.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_app_is_published_on_localhost_only():
    app = _compose("compose.yml")["services"]["app"]
    assert app["ports"] == ["127.0.0.1:8000:8000"]


def test_db_publishes_no_port_except_in_the_dev_override():
    assert "ports" not in _compose("compose.yml")["services"]["db"]
    assert _compose("compose.dev.yml")["services"]["db"]["ports"] == ["127.0.0.1:5432:5432"]


def test_app_container_is_locked_down():
    app = _compose("compose.yml")["services"]["app"]
    assert app["read_only"] is True
    assert app["tmpfs"] == ["/tmp"]
    assert app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["mem_limit"] == "2g"
    assert app["pids_limit"] == 256


def test_container_paths_are_pinned_over_the_env_file():
    env = _compose("compose.yml")["services"]["app"]["environment"]
    assert env["TALOS_VAULT_DIR"] == "/data/vault"
    assert env["TALOS_WORKSPACE_DIR"] == "/data/workspace"
    assert env["TALOS_DOTENV_PATH"] == "/data/.env"
    assert env["TALOS_WEB_PORT"] == "8000"
    assert env["TALOS_CHECKPOINTER"] == "postgres"


def test_cli_and_web_app_share_the_vault():
    volumes = _compose("compose.yml")["services"]["app"]["volumes"]
    assert "./talos/vault:/data/vault" in volumes
    assert "./.env:/data/.env" in volumes


def test_integration_tests_never_use_the_default_project():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker compose -p talos-test -f compose.yml -f compose.test.yml" in makefile
    tests = _compose("compose.test.yml")["services"]["tests"]
    assert tests["build"] == {"context": ".", "target": "test"}
    assert tests["environment"]["TALOS_FAKE_GRAPH"] == "1"


def test_dockerignore_keeps_secrets_and_local_state_out():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (
        ".env",
        ".git",
        ".venv",
        "workspace/",
        "talos/vault/tools/*.py",
        "talos/vault/manifest.json",
        "**/node_modules",
    ):
        assert pattern in ignored


def test_image_runs_as_uid_1000_with_a_healthcheck():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd --uid 1000" in dockerfile
    assert "\nUSER talos\n" in dockerfile
    assert "/api/health" in dockerfile
    assert 'ENTRYPOINT ["/app/docker/entrypoint.sh"]' in dockerfile
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docker_files.py -q`
Expected: failures with `FileNotFoundError` for `compose.yml`, `compose.dev.yml`, `compose.test.yml` and `Makefile` (the `.dockerignore` and Dockerfile tests already pass).

- [ ] **Step 3: Write the compose files and the Makefile**

Create `compose.yml`:

```yaml
# Talos web app: `docker compose up` (or `make up`), then http://127.0.0.1:8000.
# Spec 03 §4. Needs a filled .env next to this file (cp .env.example .env).
services:
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: talos, POSTGRES_PASSWORD: talos, POSTGRES_DB: talos }
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U talos"], interval: 5s, retries: 10 }
  app:
    build: .
    depends_on: { db: { condition: service_healthy } }
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://talos:talos@db:5432/talos
      TALOS_CHECKPOINTER: postgres
      # Pinned here so a host path in .env can't point the container elsewhere.
      TALOS_VAULT_DIR: /data/vault
      TALOS_WORKSPACE_DIR: /data/workspace
      TALOS_DOTENV_PATH: /data/.env
      TALOS_WEB_HOST: 0.0.0.0
      TALOS_WEB_PORT: "8000"
    ports: ["127.0.0.1:8000:8000"]
    volumes:
      - ./talos/vault:/data/vault
      - ./workspace:/data/workspace
      - ./.env:/data/.env
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 2g
    pids_limit: 256
volumes:
  pgdata:
```

Create `compose.dev.yml`:

```yaml
# Publishes Postgres on 127.0.0.1:5432 for running the app and tests outside
# Docker: `make db` (docker compose -f compose.yml -f compose.dev.yml up -d db).
services:
  db:
    ports: ["127.0.0.1:5432:5432"]
```

Create `compose.test.yml`:

```yaml
# Test runner (spec 03 §4): `make test-int`. Always use it with its own
# project name (`-p talos-test`, as the Makefile does): the integration suite
# wipes the database, and the project name gives it its own `db` volume, so
# your real history in the default project is never touched.
services:
  tests:
    build: { context: ., target: test }
    depends_on: { db: { condition: service_healthy } }
    environment:
      DATABASE_URL: postgresql+psycopg://talos:talos@db:5432/talos
      TALOS_FAKE_GRAPH: "1"
    # Unit suite, then the integration suite (the gate needs `-m integration`).
    command: ["sh", "-c", "pytest -q && pytest -q -m integration"]
```

Create `Makefile` (recipe lines start with a **tab**):

```makefile
# Developer commands (spec 03 §5). Aliases only.
.PHONY: up down db migrate web fake test test-int fe

TEST_COMPOSE = docker compose -p talos-test -f compose.yml -f compose.test.yml

up:
	docker compose up --build

down:
	docker compose down

db:
	docker compose -f compose.yml -f compose.dev.yml up -d db

migrate:
	uv run alembic upgrade head

web:
	uv run talos-web

fake:
	TALOS_FAKE_GRAPH=1 uv run talos-web

test:
	uv run pytest

test-int:
	$(TEST_COMPOSE) run --rm --build tests || ($(TEST_COMPOSE) down -v; exit 1)
	$(TEST_COMPOSE) down -v

fe:
	cd frontend && npm run dev
```

- [ ] **Step 4: Run the tests and validate the compose files**

Run: `uv run pytest tests/test_docker_files.py -q`
Expected: 8 passed.

Run: `docker compose -f compose.yml -f compose.dev.yml -f compose.test.yml config --quiet`
Expected: no output, exit 0 (needs a `.env`; if you have none, `cp .env.example .env` first and delete it afterwards).

- [ ] **Step 5: Run the integration suite in compose**

Run: `make test-int`
Expected: the `test` image builds; the unit run ends `… passed, … skipped`; the integration run ends `27 passed, … deselected` (plus stage 2's integration tests); then `talos-test` containers, network and the `talos-test_pgdata` volume are removed. `docker volume ls | grep talos-test` prints nothing afterwards.

- [ ] **Step 6: Bring the stack up**

Use a separate compose project and port so this check can't collide with anything already running on 8000 and never touches the default project's data volume. It uses the fake graph, so no model key is needed.

```bash
test -f .env || { cp .env.example .env; echo "created .env for the check"; }
cat > /tmp/talos-check.yml <<'EOF'
services:
  app:
    ports: !override ["127.0.0.1:18000:8000"]
    environment:
      TALOS_FAKE_GRAPH: "1"
EOF
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml up -d --build
for i in $(seq 1 30); do [ "$(docker inspect -f '{{.State.Health.Status}}' talos-check-app-1)" = healthy ] && break; sleep 2; done
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml ps --format '{{.Service}} {{.Status}}'
curl -s http://127.0.0.1:18000/api/health; echo
curl -s http://127.0.0.1:18000/ | head -5
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml logs app | head -20
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml exec app \
  python -c "import pathlib; pathlib.Path('/app/x').write_text('x')"
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml exec app python -c "
from pathlib import Path
from talos.sandbox import run_tool
p = Path('/tmp/slow.py'); p.write_text('import time\ndef slow():\n    time.sleep(60)\n')
print(run_tool(p, 'slow', [], {}, timeout=2))"
docker compose -p talos-check -f compose.yml -f /tmp/talos-check.yml down -v
rm /tmp/talos-check.yml
```

Expected: `app Up … (healthy)` and `db Up … (healthy)`; `{"ok": true, "db": true, "fake_graph": true, …}`; the placeholder page's HTML; the logs show `database is ready after 1 attempt(s)` and Alembic's `Running upgrade  -> 0001_initial` before the server starts; the `/app/x` write fails with `Read-only file system`; the sandbox check prints `ToolResult(ok=False, value=None, error='TimeoutError: tool ran longer than 2s', timed_out=True, stdout='')`. If you created `.env` just for this check, delete it afterwards.

- [ ] **Step 7: Commit**

```bash
git add compose.yml compose.dev.yml compose.test.yml Makefile tests/test_docker_files.py
git commit -m "[Feat]: Add the compose stack, test runner and Makefile commands"
```

---

### Task 9: CI jobs `integration` and `docker`

**Files:**
- Modify: `.github/workflows/ci.yml` (append two jobs; `lint` and `test` unchanged)

**Interfaces:**
- Consumes: the integration gate (`DATABASE_URL` + `-m integration`), the Dockerfile and compose files.
- Produces: CI jobs `integration` and `docker`. Stage 4 part B appends `frontend` later.

- [ ] **Step 1: Append the jobs**

Append to the end of `.github/workflows/ci.yml` (two-space indentation, under `jobs:`):

```yaml
  # Postgres integration suite (spec 03 §6). The conftest gate runs these only
  # with DATABASE_URL exported and `-m integration`.
  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: talos
          POSTGRES_PASSWORD: talos
          POSTGRES_DB: talos
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U talos"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://talos:talos@localhost:5432/talos
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --extra dev
      - run: uv run alembic upgrade head
      - run: uv run pytest -q -m integration

  # Proves the image builds (spec 03 §6). Nothing is pushed.
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - run: docker build .
      - run: cp .env.example .env && docker compose -f compose.yml -f compose.dev.yml -f compose.test.yml config --quiet
```

- [ ] **Step 2: Validate**

Run: `uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs']))"`
Expected: `['docker', 'integration', 'lint', 'test']`.

Run: `git diff .github/workflows/ci.yml`
Expected: only added lines.

Run the `integration` job's commands locally against the test container: `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run alembic upgrade head && DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -q -m integration`
Expected: all integration tests pass.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "[Chore]: Run the Postgres integration suite and the Docker build in CI"
```

---

### Task 10: Docs and full verification

**Files:**
- Modify: `README.md` (new "Web app" section; Safety, Configuration, Tests and Known limits updates)
- Modify: `PROGRESS.md` (stage 03 section)
- Modify: `.env.example` (`TALOS_TOOL_TIMEOUT`)

Stage 2 may also have edited `README.md`. Make each edit against the text as it is on this branch; if a sentence quoted below was already changed by stage 2, adapt the edit to keep both stages' facts and mention it in the task report.

- [ ] **Step 1: `.env.example`**

After the line `TALOS_LLM_TIMEOUT=120`, add:

```dotenv
# Wall-clock limit (seconds) for one forged-tool call in the sandbox
TALOS_TOOL_TIMEOUT=30
```

- [ ] **Step 2: README Safety section**

Replace the bullet

```markdown
- **Forged tools are not sandboxed.** They are tested in a subprocess with a timeout, but once registered they run inside the Talos process, with your user's permissions and no timeout.
```

with

```markdown
- **Forged tools run in a subprocess with a time limit.** Every call to a vault tool (and the smoke test before a tool is saved) runs in its own Python process, killed after `TALOS_TOOL_TIMEOUT` seconds (default 30). Values come back as plain data, never as objects. The subprocess still has your user's permissions, your environment (API keys) and the network: it's a time limit and a crash boundary, not a jail.
```

- [ ] **Step 3: README "Web app" section**

Insert a new section directly before `## Architecture`:

````markdown
## Web app

Talos also runs as a local web app: Postgres keeps sessions and run history, the vault stays as files on disk, and the CLI keeps working next to it.

```bash
cp .env.example .env    # then set OPENROUTER_API_KEY (and TAVILY_API_KEY for web search)
make up                 # docker compose up --build: Postgres + the app
```

Open http://127.0.0.1:8000. `docker compose ps` should show `db` and `app` as healthy. `make down` stops both; your history stays in the `pgdata` volume.

- **No login.** There are no accounts and no authentication. Compose publishes the app on `127.0.0.1` only; don't expose it on a network.
- **Same vault as the CLI.** `talos/vault/` and `workspace/` are mounted into the container, so tools forged in the browser show up in `uv run talos` and the other way round.
- **Keys.** `.env` is mounted read-write, so keys saved from the browser's API-key dialog persist, just like the CLI's Human check.
- **Container limits.** The app runs as a non-root user on a read-only filesystem, with no Linux capabilities, 2 GB of memory and 256 processes. It keeps network access, because web tools need it. Forged tools run in a subprocess inside the container with a `TALOS_TOOL_TIMEOUT` limit (see [Safety](#safety-read-this-first)).

Developer commands (see the `Makefile`):

| Command | What it does |
|---|---|
| `make up` / `make down` | Start or stop the whole stack in Docker |
| `make db` | Only Postgres, published on `127.0.0.1:5432` (set `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:5432/talos` in your shell or `.env`) |
| `make migrate` | `uv run alembic upgrade head` against `DATABASE_URL` |
| `make web` | Run the app outside Docker (needs `make db`) |
| `make fake` | Same, with `TALOS_FAKE_GRAPH=1`: scripted runs, no model calls, no keys |
| `make test` | Unit suite, no Docker |
| `make test-int` | Unit and integration suites in Docker against a throwaway Postgres |
| `make fe` | Frontend dev server (from stage 04) |
````

- [ ] **Step 4: README Configuration, Tests and Known limits**

In the Configuration table, add after the `TALOS_LLM_TIMEOUT` row:

```markdown
| `TALOS_TOOL_TIMEOUT` | no | Per-call limit for forged tools in the sandbox, default 30 (seconds) |
```

In the Tests section, after the fenced block that starts `docker run -d --name talos-pg-test`, add:

```markdown
`make test-int` runs the unit and integration suites inside Docker against a throwaway Postgres (compose project `talos-test`, removed afterwards). CI runs lint, the unit suite on 3.11 and 3.12, the integration suite against a `postgres:16` service, and `docker build .`.
```

In Known limits, replace

```markdown
- Forged tools run in-process after registration: no sandbox, no timeout (see [Safety](#safety-read-this-first)).
- Subprocess isolation only for tests and exec primitives, not Docker/E2B.
```

with

```markdown
- Forged tools run in a subprocess with a time limit, not a jail: same user, same environment, network on (see [Safety](#safety-read-this-first)). No container-per-tool or E2B isolation.
```

- [ ] **Step 5: PROGRESS.md**

Insert before `## Session log`:

```markdown
## Web app stage 03 — Docker, sandbox, CI ✅

Spec: `docs/superpowers/specs/2026-09-30-talos-web-03-docker-sandbox-design.md`. Plan: `docs/superpowers/plans/2026-09-30-talos-web-03-docker-sandbox.md`.

- [x] `talos/sandbox/`: tagged-JSON codec, `run_tool` (subprocess per call, `TALOS_TOOL_TIMEOUT` default 30 s, process-group kill), `SandboxedTool` (signature read with `ast`, no in-process exec)
- [x] Executor runs vault and forged tools through the sandbox; a timeout is a recorded failure. `SkillManager.locate()`; `load()` kept but unused by the executor
- [x] Smoke gate runs unregistered forged code from a temp file through the sandbox
- [x] `Dockerfile` (frontend, deps, test, runtime), `docker/entrypoint.sh` (DB wait, `alembic upgrade head`, `talos-web`), `.dockerignore`
- [x] `compose.yml`, `compose.dev.yml`, `compose.test.yml`; `Makefile` aliases; `make test-int` uses its own compose project (`talos-test`)
- [x] CI: `integration` (Postgres service) and `docker` (`docker build .`) jobs
- Placeholder `frontend/` (package.json, lockfile, placeholder.html) until stage 04 replaces it. The CI `frontend` job is added by stage 04.
```

And append to the Session log:

```markdown
- **2026-09-30** — Web app stage 03 complete: forged-tool sandbox (`talos/sandbox/`), executor and smoke switched to it, Docker image, compose stack, Makefile, CI `integration` and `docker` jobs. Next: stage 04 (frontend), which replaces the placeholder `frontend/` and adds the CI `frontend` job.
```

- [ ] **Step 6: Full verification**

Run each and check the result before claiming anything:

```bash
uv run pytest -q
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -q -m integration
uv run ruff check .
uv run ruff format --check .
docker build .
make test-int
```

Expected: unit suite green with no database (the sandbox tests add about 5 s); integration green against `talos-pg-test` (skip that line only if the container isn't running, and say so); ruff clean; image builds; `make test-int` green and leaves no `talos-test` containers or volumes (`docker ps -a --filter name=talos-test` and `docker volume ls --filter name=talos-test` print nothing).

Acceptance (spec §7), if a filled `.env` and port 8000 are available: `make up`, `docker compose ps` shows both services healthy, `http://127.0.0.1:8000` serves the placeholder page and `/api/health`, then `make down`. The "forged tool with `time.sleep(60)` is killed after 30 s" criterion is covered by `test_vault_tool_timeout_is_a_recorded_failure` (with a 1 s limit) and the in-container check in Task 8 Step 6. "The web app and `uv run talos` see the same vault" holds by construction: compose bind-mounts `./talos/vault` (pinned by `test_cli_and_web_app_share_the_vault`).

- [ ] **Step 7: Commit**

```bash
git add README.md PROGRESS.md .env.example
git commit -m "[Docs]: Document the web app stack, the forged-tool sandbox and stage 03 progress"
```
