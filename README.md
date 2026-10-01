<p align="center">
  <img src="assets/talos-banner.jpg" alt="Talos: forge, test, execute, learn" width="100%">
</p>

# Talos AI

[![CI](https://github.com/Yathharth54/Talos-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Yathharth54/Talos-AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

A LangGraph-based self-evolving agent that forges, tests, and accumulates reusable Python tools at runtime.

**Website:** [talos-ai-umber.vercel.app](https://talos-ai-umber.vercel.app)

## What it does

You ask Talos to do something. It:

1. **Plans**: decomposes your query into ordered sub-tasks. Each sub-task is labelled with how it should run: a built-in primitive, an existing tool from its vault, or a tool that needs to be forged.
2. **Forges**: writes Python code for any sub-task that needs a new tool. Researches free APIs first when the task involves the web. Asks for an API key if one is needed.
3. **Tests**: runs the forged code through auto-generated tests in a subprocess, then smoke-tests it once against the real upstream inputs. Up to 3 retries with the error trace fed back to the LLM.
4. **Executes**: runs the chosen tool with arguments resolved from your query and prior sub-task outputs.
5. **Learns**: registers successful tools in a vault on disk. Next time you ask something similar, Talos uses the existing tool instead of forging again.

Everything is a visible LangGraph node. Every step shows up as a discrete event in LangSmith traces.

## Safety: read this first

Talos runs code written by an LLM on your machine.

- **`python_exec` and `shell_exec` ask before running.** The REPL shows you the exact code or command and waits for `y`. Anything else declines. Set `TALOS_AUTO_APPROVE_EXEC=true` to skip the prompt (the unattended benchmark runners do this).
- **Forged tools run in a subprocess with a time limit.** Every call to a vault tool (and the smoke test before a tool is saved) runs in its own Python process, killed after `TALOS_TOOL_TIMEOUT` seconds (default 30). Values come back as plain data, never as objects. The subprocess still has your user's permissions, your environment (API keys) and the network: it's a time limit and a crash boundary, not a jail.
- **The CLI and forged tools run without container isolation.** `uv run talos` and every forged-tool subprocess it starts run directly on your machine as your user. Run the CLI in a VM, container, or throwaway account if you plan to point it at anything you care about. The compose stack runs the server in a locked-down container (see [Web app](#web-app)).
- **The web app has no login.** `talos-web` binds to `127.0.0.1` and anyone who can reach its port can run code through it. Keep it on localhost. Inside a container it has to bind `TALOS_WEB_HOST=0.0.0.0` to be reachable at all; then publish the port on the host's loopback only (`-p 127.0.0.1:8000:8000`), never as `-p 8000:8000`. Outside a container, don't set `0.0.0.0` on a shared network.
- **The web app only answers local requests.** It rejects any `Host` header other than `127.0.0.1`, `localhost` and `[::1]` (plus `TALOS_WEB_ALLOWED_HOSTS`) with `400`, so a web page can't reach it through DNS rebinding, and it rejects `POST`/`PATCH`/`DELETE` requests whose `Origin` is another site with `403`, so a page you visit can't start runs or save keys.

## Quick start

```bash
git clone https://github.com/Yathharth54/Talos-AI.git
cd Talos-AI
uv sync --extra dev
cp .env.example .env
# Edit .env: at minimum set OPENROUTER_API_KEY (and TAVILY_API_KEY for web search)
uv run talos
```

Then type queries at the prompt:

```
> Reverse the string 'hello' and tell me the result.
> Use a free weather API to get the current temperature in Mumbai.
> Read https://example.com and save the body to /tmp/out.txt
```

Relative file paths are written under `workspace/` (gitignored). Forged tools land in `talos/vault/` (also gitignored), so your vault is yours.

## Web app

Talos also runs as a local web app: Postgres keeps sessions and run history, the vault stays as files on disk, and the CLI keeps working next to it.

```bash
cp .env.example .env    # then set OPENROUTER_API_KEY (and TAVILY_API_KEY for web search)
make up                 # docker compose up --build: Postgres + the app
```

Open http://127.0.0.1:8000. `docker compose ps` should show `db` and `app` as healthy. `make down` stops both; your history stays in the `pgdata` volume. The HTTP API is documented under [Web app (API)](#web-app-api) below.

- **No login.** There are no accounts and no authentication. Compose publishes the app on `127.0.0.1` only; don't expose it on a network.
- **Same vault as the CLI.** `talos/vault/` and `workspace/` are mounted into the container, so tools forged in the browser show up in `uv run talos` and the other way round.
- **Keys.** `.env` is mounted read-write, so keys saved from the browser's API-key dialog persist, just like the CLI's Human check.
- **Container limits.** The app runs as a non-root user on a read-only filesystem, with no Linux capabilities, 2 GB of memory and 256 processes. It keeps network access, because web tools need it. Forged tools run in a subprocess inside the container with a `TALOS_TOOL_TIMEOUT` limit (see [Safety](#safety-read-this-first)).
- **Bind-mount ownership.** The container runs as uid 1000. On Linux, `talos/vault/`, `workspace/` and `.env` must be writable by that uid: `sudo chown -R 1000:1000 talos/vault workspace .env`, or run as your own uid if it is 1000. Docker Desktop on macOS maps ownership for you.
- **Plain `docker run`.** Compose starts the app with `init: true`, so an init process reaps the forged-tool subprocesses. If you run the image without compose, pass `--init` as well (for example `docker run --init -p 127.0.0.1:8000:8000 …`).

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

### Frontend

The UI lives in `frontend/` (React, TypeScript, Vite). It has two modes.

- **Live.** `http://127.0.0.1:8000` talks to the API and streams real runs over SSE.
- **Demo.** `/?demo` (or a build with `VITE_DEMO=1`) is the scripted demo. It needs no backend and shows the Demo controls.

Develop it with the fake graph, so no model key is needed:

```bash
make db     # Postgres (or the talos-pg-test container)
make fake   # TALOS_FAKE_GRAPH=1 uv run talos-web
make fe     # cd frontend && npm run dev; Vite proxies /api to 127.0.0.1:8000
```

Checks, from `frontend/`:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Playwright needs `npx playwright install chromium` once.

```bash
npm run e2e:visual   # /?demo against the reference file, 1440x900 and 390x844
npm run e2e:live     # the live app against an isolated fake-graph server
```

Both scripts build `dist/` first. `e2e:visual` deletes any old baselines and renders them again from the reference in the same run. They are never committed.

`e2e:live` starts its own fake-graph server on port 8765. It uses the `talos_e2e` database on `E2E_DATABASE_URL` (default `postgresql+psycopg://talos:talos@localhost:55432/talos_e2e`), and a throwaway vault, workspace and `.env` in `frontend/.e2e-tmp/`. **Warning:** the harness drops and recreates that database. It refuses any name that does not end in `_e2e`, and any host other than localhost. The harness sets every `TALOS_*` variable itself, so nothing in your shell changes how the server behaves. It paces the fake graph by 25 ms per event (`TALOS_FAKE_EVENT_DELAY_MS`), so the Stop and reload specs act on a run that is still going on the server.

## Architecture

```
                          User query
                              │
                              ▼
                       Orchestrator (in)        ← state hygiene per turn
                              │
                              ▼
                          Planner               ← decomposes into sub-tasks
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
          (per sub-task)              (no sub-tasks)
                  │                       │
        ┌─────────┼─────────┐             │
   primitive    vault    forge            │
        │         │       │               │
        │         │       ▼               │
        │         │  Forger ↔ Tester      │   ← max 3 retries; sub-graph
        │         │       │               │
        │         │       ▼               │
        │         │  HITL check           │   ← interrupts for missing API keys
        │         │       │               │
        │         │       ▼               │
        │         │     Learn             │   ← registers tool in vault
        │         │       │               │
        └─────────┴───────┘               │
                  │                       │
                  ▼                       │
              Executor                    │   ← runs primitive/vault/forged
                  │                       │
                  ▼                       │
            More sub-tasks? ──────────────┤
                  │                       │
                  ▼                       ▼
                       Orchestrator (out)
                              │
                              ▼
                          Final response
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the Mermaid diagrams, including the forge sub-graph.

### Components

| Component | Type | Purpose |
|---|---|---|
| **Orchestrator (in/out)** | LangGraph nodes | Per-turn state reset; final response synthesis (1 LLM call) |
| **Planner** | LangGraph node | Vault-aware decomposition (1 LLM call, structured output) |
| **Researcher** | `create_agent` (ReAct) | Web search + URL read in a loop, called by the Forger before writing API code |
| **Forger** | LangGraph node | Code + test generation (1 LLM call per attempt, structured output) |
| **Tester** | LangGraph node | Subprocess test run + smoke test on real inputs (no LLM) |
| **HITL check** | LangGraph node | Pauses the graph for missing API keys via `interrupt()` |
| **Learn** | LangGraph node | Registers the forged tool in the vault (no LLM) |
| **Executor** | LangGraph node | Dispatches primitive/vault/forge; ArgResolver inside (1 LLM call); asks before exec |
| **Skill Manager** | Plain Python | Manifest + .py files on disk; search/register/load |

### Primitives (always available)

- `web_search` (Tavily)
- `web_read` (Jina Reader)
- `file_read` / `file_write`
- `python_exec` / `shell_exec` (subprocess + 10s timeout, asks for approval first)
- `vault_list` (lets Talos describe the tools it has learned)
- `human_input` (LangGraph `interrupt()`)

## Project layout

```
Talos-AI/
├── talos/
│   ├── main.py              # REPL (`uv run talos`)
│   ├── graph.py             # Main StateGraph wiring
│   ├── state.py             # TalosState TypedDict
│   ├── agents/              # Each "agent" is a graph node + prompt
│   │   ├── planner.py
│   │   ├── forger.py
│   │   ├── forge_subgraph.py
│   │   ├── tester.py
│   │   ├── smoke.py         # Real-input smoke gate before registering
│   │   ├── researcher.py    # The only ReAct agent
│   │   ├── executor.py
│   │   ├── learner.py
│   │   ├── orchestrator.py
│   │   └── hitl.py
│   ├── primitives/          # Built-in tools
│   ├── persistence/         # Postgres models, repo, migrations (web app only)
│   ├── web/                 # Web app API (`uv run talos-web`): FastAPI, runs, SSE
│   ├── prompts/             # System prompts
│   ├── vault/               # Forged tools live here (gitignored)
│   │   ├── manager.py
│   │   ├── manifest.json
│   │   └── tools/*.py
│   └── config/
│       ├── settings.py
│       ├── llm.py           # OpenRouter chat model factory
│       └── logging.py
├── tests/                   # 160+ mocked tests, ~5s, no keys needed
├── benchmarks/              # 62-query end-to-end suite
├── examples/                # Demo queries, trace viewers, benchmark runner
├── site/                    # Static landing page (deployed on Vercel)
├── ARCHITECTURE.md          # Graph diagrams
├── CLAUDE.md                # Original design spec
└── PROGRESS.md              # Build log per phase
```

## Results

Measured on the end-to-end suite in `benchmarks/talos_test_suite/` (62 queries, `deepseek/deepseek-v4.1-flash` via OpenRouter, September 2026), before and after the latest round of fixes:

| | Before | After |
|---|---|---|
| Suite score | 45/62 | **56/62** |
| Search/reading questions | 0/5 | **5/5** |
| Queries that crashed | 3 | **1** |
| Median time per query | 13.9s | 17.1s |

Run it yourself with `uv run python -m benchmarks.talos_test_suite.run_suite` (live API calls; costs a little).

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

## Configuration

All via `.env` (see `.env.example`):

| Var | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | All LLM-using nodes call OpenRouter |
| `TALOS_MODEL` | no | OpenRouter model slug; defaults to `deepseek/deepseek-v4.1-flash` |
| `TAVILY_API_KEY` | yes (for web_search) | Free tier covers POC use |
| `JINA_API_KEY` | no | Optional; raises Jina Reader rate limits |
| `LANGSMITH_API_KEY` | no | Enables full tracing of every node |
| `LANGSMITH_TRACING` | no | Set `true` to enable; tests force-disable it |
| `TALOS_AUTO_APPROVE_EXEC` | no | Default `false`. `true` runs `python_exec`/`shell_exec` without asking |
| `TALOS_SUBPROCESS_TIMEOUT` | no | Default 10 (seconds) |
| `TALOS_FORGE_MAX_RETRIES` | no | Default 3 |
| `TALOS_LLM_TIMEOUT` | no | Per-request LLM timeout, default 120 (seconds) |
| `TALOS_TOOL_TIMEOUT` | no | Per-call limit for forged tools in the sandbox, default 30 (seconds) |
| `TALOS_LOG_LEVEL` | no | Default WARNING |
| `DATABASE_URL` | web app only | Postgres URL, e.g. `postgresql+psycopg://talos:talos@localhost:5432/talos`. Empty means no database; the CLI never needs one |
| `TALOS_CHECKPOINTER` | no | `memory` (default) or `postgres`. The web app always uses Postgres; the CLI stays in memory and logs a warning if this is `postgres` |
| `TALOS_VAULT_DIR` | no | Vault folder (`manifest.json` + `tools/`). Default `talos/vault` |
| `TALOS_WORKSPACE_DIR` | no | Where relative `file_read`/`file_write` paths land. Default `workspace/` |
| `TALOS_DOTENV_PATH` | no | The `.env` Talos loads and where Human check saves keys. Default `.env` in the repo. Must be set in the shell environment: it is read before `.env` is loaded |
| `TALOS_WEB_HOST` | no | Web app bind address. Default `127.0.0.1`. There is no login: keep it local. In a container use `0.0.0.0` and publish as `127.0.0.1:8000:8000` |
| `TALOS_WEB_PORT` | no | Web app port. Default `8000` |
| `TALOS_WEB_ALLOWED_HOSTS` | no | Comma-separated extra `Host` names the web app answers, besides `127.0.0.1`, `localhost` and `[::1]`. Default empty. Writes from those hosts' pages are allowed too |
| `TALOS_FAKE_GRAPH` | no | `1` runs the web app with the demo's scripted runs: no model calls, no keys, a temporary vault copy |
| `TALOS_FAKE_EVENT_DELAY_MS` | no | E2E only. With `TALOS_FAKE_GRAPH=1`, wait this many ms before each scripted event, so a run is still going on the server while the page stops or reloads it. Default `0` (no pacing) |
| `TALOS_WEB_DEV` | no | `1` allows CORS from Vite's dev server at `http://127.0.0.1:5173` |

## Tests

```bash
uv run pytest                   # ~5s, all mocked, no API keys needed
RUN_LIVE=1 uv run pytest        # also exercises real OpenRouter/Tavily/Jina
uv run ruff check . && uv run ruff format --check .
```

Tests are organised by component. LLMs are mocked at the factory seam (`_make_llm`, `_make_resolver_llm`, etc.) for cheap deterministic runs. Live tests are gated by `RUN_LIVE=1`. CI runs lint and the mocked suite on Python 3.11 and 3.12.

Postgres integration tests (the web app's storage) are marked `integration`. They run only when `DATABASE_URL` is exported in your shell and you pass `-m integration`; a value in `.env` is ignored, so a plain `uv run pytest` never touches a database. The schema is managed by Alembic; apply it to a database with `uv run alembic upgrade head`.

**Warning:** the integration suite downgrades, recreates and truncates the tables at `DATABASE_URL`. It must point at a disposable database (for example the `talos-pg-test` container below), never a real one.

```bash
docker run -d --name talos-pg-test -e POSTGRES_USER=talos -e POSTGRES_PASSWORD=talos \
  -e POSTGRES_DB=talos -p 55432:5432 postgres:16-alpine
DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos uv run pytest -m integration
```

`make test-int` runs the unit and integration suites inside Docker against a throwaway Postgres (compose project `talos-test`, removed afterwards). CI runs lint, the unit suite on 3.11 and 3.12, the integration suite against a `postgres:16` service, and `docker build .`.

The web app's route, SSE and runner tests run in the default suite against an in-memory store and the fake graph; the same store contract, a full fake-graph run, and a restart mid-pause run against Postgres under `-m integration`. The translator's chunk fixtures are recorded from the real graph with mocked LLMs; regenerate them after a LangGraph upgrade with `uv run python -m tests.web.chunks`.

## Known limits (POC)

- Forged tools run in a subprocess with a time limit, not a jail: same user, same environment, network on (see [Safety](#safety-read-this-first)). No container-per-tool or E2B isolation.
- Keyword vault search; no semantic search yet (deferred until the vault grows).
- Single provider (OpenRouter): one model for every node, set via `TALOS_MODEL`.
- OAuth-style API auth is out of scope; only env-var-keyed APIs are supported via HITL.
- The CLI uses an in-memory checkpointer (`MemorySaver`); its conversation state is lost on exit. The vault persists.
- Stopping a web run ends it right away (the run is marked `stopped` and its stream closes), but a graph node already running in a worker thread (an LLM call, a tool, a test subprocess) can't be interrupted: its thread runs to completion in the background. Its result is discarded, but its side effects (a file written, a tool saved to the vault) can still happen.

## Acknowledgements

The skill-crystallization idea (an agent that turns solved tasks into reusable tools) is inspired by [GenericAgent](https://github.com/lsdefine/GenericAgent). Talos rebuilds that loop graph-native on [LangGraph](https://github.com/langchain-ai/langgraph) so every phase is a visible, debuggable node.

## License

[MIT](LICENSE) © 2026 Yathharth Karanjikar
