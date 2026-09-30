# Stage 3: Docker, forged-tool sandbox, local and CI tests

Date: 2026-09-30
Status: draft for review
Parent: `2026-09-30-talos-web-app-overview-design.md`
Depends on: stages 1 and 2

## 1. Goal

- One command starts the whole app locally: `docker compose up`.
- Forged tools stop running inside the server process. Today `SkillManager.load()` and `smoke.py` `exec()` model-written code in-process with no timeout, and in a web app that's the biggest risk.
- Integration tests run the same way locally and in CI.

## 2. Forged-tool sandbox

### 2.1 Interface

New package `talos/sandbox/`:

```python
def run_tool(source_path: Path, function: str, args: list, kwargs: dict,
             timeout: float | None = None) -> ToolResult: ...

@dataclass
class ToolResult:
    ok: bool
    value: Any = None          # decoded return value when ok
    error: str | None = None   # "TypeError: shift must be an int, got str"
    timed_out: bool = False
    stdout: str = ""           # captured prints, truncated to 64 KB
```

- `run_tool` starts `sys.executable -m talos.sandbox.child` and sends one JSON request on stdin: `{source_path, function, args, kwargs}`. It reads one JSON response from the child's stdout, after a sentinel line.
- `timeout` defaults to `TALOS_TOOL_TIMEOUT` (new setting, default 30 s). A timeout kills the process group and returns `timed_out=True`, `error="TimeoutError: tool ran longer than 30s"`.
- The child's working directory is the workspace directory, so relative-path I/O lands where `file_write` would put it. The environment is the parent's, so tools can read their API keys.
- Nothing is unpickled from the child. Values cross the boundary as tagged JSON (§2.2), so a malicious tool can only return data, never objects.

### 2.2 Value encoding

`talos/sandbox/codec.py`, used in both directions:

- JSON-native values pass through: `None`, bool, int (any size, as a string when it's beyond 2⁵³), float, str, list, dict with str keys.
- Tagged forms: `{"__t": "tuple", "v": [...]}`, `{"__t": "set", "v": [...]}`, `{"__t": "bytes", "v": "<base64>"}`, `{"__t": "int", "v": "123…"}`, `{"__t": "dict", "v": [[k, v], ...]}` for dicts with non-str keys.
- Anything else is `{"__t": "repr", "v": repr(obj)}` and decodes to that string. The executor already copes with str-typed outputs via `coerce_to_schema`.

### 2.3 Who uses it

- `executor_node`: for `needs` `vault` or `forge`, call `run_tool` with the entry's file. It no longer calls `mgr.load()`. `record_usage` and `record_failure` get the same success and failure signals as today; a timeout counts as a failure.
- `smoke.py`: runs the forged code through `run_tool`. For code that isn't registered yet, it writes to a temporary file first.
- `SkillManager.load()` stays for backward compatibility and tests, with a docstring saying the executor no longer uses it.
- Primitives (`python_exec`, `shell_exec`, `web_*`, `file_*`, `vault_list`) are unchanged. The two exec primitives already run in subprocesses and already ask first.

### 2.4 Tests

- Codec round-trips every tagged type, big ints, and nested structures.
- A tool that sleeps past the timeout is killed and returns `timed_out`.
- A tool that raises returns its error text in the same format as today (`TypeError: …`).
- A tool's `print()` output is captured and doesn't corrupt the response.
- A tool that tries to return an object can't make the parent execute anything; the parent gets a repr string.
- The existing executor and smoke tests pass unchanged. The vault-tool tests exercise the subprocess path.
- The `caesar_cipher` failure from the real vault (`shift="seven"`) produces the same error string through the sandbox.

## 3. Docker image

`Dockerfile` at the repo root, three stages:

1. `frontend`: `node:22-alpine`. `npm ci` and `npm run build` in `frontend/`, producing `/frontend/dist`.
2. `deps`: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`. `uv sync --frozen --no-dev` into `/app/.venv`.
3. `runtime`: `python:3.12-slim-bookworm`.
   - Copy the venv, `talos/`, `alembic/`, `alembic.ini`, and `frontend/dist`.
   - Create user `talos` (uid 1000) and run as that user.
   - `ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 TALOS_VAULT_DIR=/data/vault TALOS_WORKSPACE_DIR=/data/workspace TALOS_DOTENV_PATH=/data/.env TALOS_WEB_HOST=0.0.0.0`. Inside the container it has to listen on all interfaces; compose publishes it on localhost only.
   - `ENTRYPOINT ["/app/docker/entrypoint.sh"]`: waits for the database, runs `alembic upgrade head`, then `exec talos-web`.
   - `HEALTHCHECK` curls `/api/health`.

`.dockerignore` excludes `.venv`, `.git`, `workspace/`, `talos/vault/tools/*.py`, `talos/vault/manifest.json`, `.env`, `talos logos/`, `site/`, `node_modules`, and caches.

## 4. Compose

`compose.yml`:

```yaml
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

- The vault is bind-mounted from the repo, so the CLI and the web app share the same tools.
- `.env` is mounted read-write so Human check can save keys.
- `db` publishes no port. The `compose.dev.yml` override adds `127.0.0.1:5432:5432` for running tests and the app outside Docker.
- Network access stays on: web tools need the internet.

`compose.test.yml` adds a `tests` service: the same image built with `--target deps` plus dev dependencies. It runs `pytest -m "integration or not integration"` against `db`, with `TALOS_FAKE_GRAPH=1` for the API end-to-end tests.

## 5. Developer commands

A `Makefile` (short, no logic beyond aliases):

| Target | Runs |
|---|---|
| `make up` | `docker compose up --build` |
| `make down` | `docker compose down` |
| `make db` | `docker compose -f compose.yml -f compose.dev.yml up -d db` |
| `make migrate` | `uv run alembic upgrade head` |
| `make web` | `uv run talos-web` (needs `make db`) |
| `make fake` | `TALOS_FAKE_GRAPH=1 uv run talos-web` |
| `make test` | `uv run pytest` (unit, no Docker) |
| `make test-int` | `docker compose -f compose.yml -f compose.test.yml run --rm tests` |
| `make fe` | `cd frontend && npm run dev` |

README gets a "Web app" section: `make up`, open `http://127.0.0.1:8000`, the safety notes, and the fact that there's no login.

## 6. CI

`.github/workflows/ci.yml` gains:

- `integration`: `ubuntu-latest` with a `postgres:16` service container, `DATABASE_URL` pointed at it. Runs `uv run alembic upgrade head` then `uv run pytest -m integration`.
- `frontend`: Node 22. `npm ci`, `npm run lint`, `npm run typecheck`, `npm run build`, and the Playwright suite (stage 4 §9) against `TALOS_FAKE_GRAPH=1` with a Postgres service.
- `docker`: `docker build .`, to prove the image builds. Nothing is pushed.

The existing `lint` and `test` jobs are unchanged.

## 7. Acceptance

- `make up` on a clean checkout with a filled `.env` serves the app at `http://127.0.0.1:8000`. `docker compose ps` shows both services healthy.
- A forged tool with `time.sleep(60)` is killed after 30 s. The run records a failure, and the server keeps serving.
- The web app and `uv run talos` see the same vault.
- `make test`, `make test-int` and all CI jobs are green.
