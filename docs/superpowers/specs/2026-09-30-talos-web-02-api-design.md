# Stage 2: API (FastAPI, run manager, SSE)

Date: 2026-09-30
Status: draft for review
Parent: `2026-09-30-talos-web-app-overview-design.md`
Depends on: `2026-09-30-talos-web-01-persistence-design.md`

## 1. Goal

A local HTTP API that starts graph runs, streams their events to the browser, pauses and resumes them for approvals and keys, and serves sessions, vault and settings. It must be complete enough that the frontend (stage 4) never needs anything else.

## 2. Package layout

```
talos/web/
  __init__.py
  app.py            # create_app(): FastAPI instance, lifespan, routers, static files
  deps.py           # DB session, RunManager, settings dependencies
  schemas.py        # Pydantic request/response models
  copy.py           # caption, log and chip templates (overview §4.5)
  translator.py     # EventTranslator: raw astream chunks → contract events
  runner.py         # RunManager: one background task per active run, fan-out to subscribers
  naming.py         # session name from the first query
  fake_graph.py     # TALOS_FAKE_GRAPH=1: scripted event sequences, no model calls
  routes/
    sessions.py
    runs.py
    vault.py
    settings.py
    health.py
talos/web/__main__.py  # `python -m talos.web` → uvicorn on 127.0.0.1:8000
```

Dependencies: `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `sse-starlette>=2.1`. Dev: `httpx`.

A `talos-web` console script is added next to `talos`.

## 3. App lifecycle

`lifespan`:

1. Refuse to start without `DATABASE_URL`, with a clear message.
2. Run `alembic upgrade head` programmatically. The Docker entrypoint also runs it, and running it twice is harmless.
3. `open_postgres_saver()`, then `graph = build_app(saver)`. With `TALOS_FAKE_GRAPH=1`, use the fake runner instead.
4. Recovery (stage 1 §7).
5. Load `ask_before_exec` from `app_settings` and apply it (§7).
6. On shutdown: cancel active run tasks (they become `stopped`), close the pool.

Server: uvicorn, one worker, `--host 127.0.0.1` by default (`TALOS_WEB_HOST`, `TALOS_WEB_PORT` override). One worker is required: run state and the vault files are single-process.

## 4. Endpoints

All JSON. Errors use one shape: `{"error": {"code": "run_active", "message": "A run is already going. Stop it or wait for it to finish."}}`. Prefix `/api`.

### Sessions

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/sessions` | none | `201` `Session` |
| `GET /api/sessions` | none | `[SessionSummary]`, newest first (stage 1 §6) |
| `GET /api/sessions/{id}` | none | `{session: Session, messages: [Message], runs: [RunSummary]}` |
| `PATCH /api/sessions/{id}` | `{name}` (1–80 chars) | `Session` |
| `POST /api/sessions/{id}/messages` | `{text}` (1–4000 chars, trimmed) | `202` `{run: RunSummary, message: Message}`; `409 run_active` if any run is `running` or `waiting` anywhere |

`Session = {id, name, number, created_at, updated_at}`
`Message = {id, role, html, note, chips, run_id, created_at}`
`RunSummary = {id, n, query, status, summary, summary_gold, forged, used, failed, started_at, finished_at}`

There's one active run at a time across the whole app, not just per session. The vault and `.env` are shared files, and it matches the demo, where the composer locks while a run is going.

### Runs

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/runs/{id}` | none | `RunSummary` + `pending: {kind, payload} \| null` (browser-safe payload only) |
| `GET /api/runs/{id}/events` | `Last-Event-ID` header or `?after=N` | SSE stream (§5) |
| `POST /api/runs/{id}/resume` | `{decision: "approve"\|"decline"}` for `confirm_exec`; `{decision: "save", value}` or `{decision: "skip"}` for `missing_api_key` | `202`; `409 not_waiting` if the run isn't paused; `422` if the decision doesn't fit the pending kind |
| `POST /api/runs/{id}/stop` | none | `202`; no-op if the run already finished |

Resume rules:

- `approve` resumes with `{"approved": true, "args": pending.args, "kwargs": pending.kwargs}`, taken from `runs.pending_interrupt`. The browser never sends code back.
- `decline` resumes with `{"approved": false}`. The run finishes with status `declined` and the "Executor, declined" state and copy from the demo.
- `save` resumes with the key value. `hitl_check_node` writes it to `.env` as it does today. The value is never logged, never stored in `run_events`, and never echoed back.
- `skip` resumes with `"skip"`.
- The Escape key and the Stop button are the frontend's "cancel". Cancel during a pause calls `/stop`, not `/resume`.

### Vault

| Method and path | Returns |
|---|---|
| `GET /api/vault` | `{count, web_count, failed_count, tools: [VaultEntry]}`, sorted by `last_used` (or `created_at`) descending |
| `GET /api/vault/{name}` | `VaultEntry + {source: str \| null, lines: int}`; `404` if not in the manifest |
| `DELETE /api/vault/{name}` | `204`. Calls `SkillManager.remove`; the `.py` file stays |

`VaultEntry = {name, args, ret, signature, description, keywords, uses, failures, streak, created_at, last_used, last_failure, last_failed_at, web: bool, file}`

- `args` and `ret` are split out of `signature`.
- `web` is true when the source imports `requests`, `urllib` or `httpx`. This matches "reaches the web through a free API it found itself".
- `source` is read from `talos/vault/tools/{name}.py`. It is null only if the file is missing.

### Settings

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/settings` | none | `Settings` |
| `PATCH /api/settings` | `{ask_before_exec: bool}` | `Settings` |

`Settings = {model, ask_before_exec, forge_retries, test_timeout_s, llm_timeout_s, prune_after, keys: [{name, set: bool, required: bool, description}]}`

- `keys` lists `OPENROUTER_API_KEY` (required), `TAVILY_API_KEY` (required for web search), `JINA_API_KEY` and `LANGSMITH_API_KEY` (optional), plus every other `*_API_KEY` found in `.env` (described as "Saved by Human check this session.", the demo's sentence).
- Values are never returned. Only `set: true|false`.

### Health

`GET /api/health` returns `{ok: true, db: bool, fake_graph: bool, version}`.

### Static files

In production the built frontend (`frontend/dist`) is served at `/`, with `index.html` as the fallback for unknown non-`/api` paths. In development, Vite's dev server proxies `/api` to `127.0.0.1:8000`.

## 5. SSE stream

- Content type `text/event-stream`. Each event goes out as `id: {seq}`, `event: {type}`, `data: {envelope JSON}`.
- On connect, first send every persisted event with `seq > after`, then live events. If the run already finished, send the backlog and close.
- Heartbeat comment `: keep-alive` every 15 s.
- The stream stays open through pauses. `interrupt`, `interrupt.resolved` and the rest of the run all arrive on the same connection.
- It closes after `run.finished`.
- More than one subscriber per run is fine: each gets its own queue.

## 6. RunManager and EventTranslator

`RunManager` (singleton, lives on `app.state`):

```python
class RunManager:
    async def start(self, session: Session, text: str) -> Run: ...
    async def resume(self, run_id: UUID, decision: ResumeDecision) -> None: ...
    async def stop(self, run_id: UUID) -> None: ...
    def subscribe(self, run_id: UUID) -> AsyncIterator[Event]: ...
```

`start`:

1. Take the global lock; `409` if a run is active.
2. Create the run row and the user message row. If this is the session's first run, rename the session (§8).
3. Spawn an `asyncio.Task` that drives `graph.astream({"messages": [HumanMessage(text)]}, config={"configurable": {"thread_id": session.thread_id}}, stream_mode=["updates", "custom", "messages"], subgraphs=True)`.

The task:

- Feeds every chunk to `EventTranslator.feed(chunk) -> list[Event]`. Each event is appended to `run_events`, then published to subscribers.
- When the stream ends with `__interrupt__` in the final update: store the interrupt value in `runs.pending_interrupt`, emit `interrupt` with the browser-safe payload, set status `waiting`, and end the task. No task is held while waiting.
- `resume` starts a new task with `graph.astream(Command(resume=value), same config, …)`, reusing the same translator state (saved as JSON on the run row) and continuing `seq`.
- On normal end: emit `answer.done` and `run.finished`, write the assistant message row, and fill `summary`, `forged`, `used` and `failed`.
- On exception: emit `error` and `run.finished` with status `failed`, and store `error`.

`stop` cancels the task, or for a waiting run just finishes it. The run is marked `stopped`, then:

- Active steps get state `stopped`, with the label suffix ", stopped".
- Log line `stop` `stopped by you` (w).
- Caption `You stopped this run. Nothing was saved to the vault.`
- `run.finished`.

The checkpoint may still hold pending tasks. The next message on that session starts a fresh turn: `orchestrator_in` resets per-turn state, and passing new input starts the graph from `START`. A test must confirm this behaviour in the pinned LangGraph version. If it doesn't hold, `stop` clears the thread's pending writes with `graph.aupdate_state(config, None, as_node="orchestrator_out")`.

`EventTranslator` is a pure class (no I/O), so it can be unit-tested with recorded chunks:

- It holds: current sub-task index, strip variant, which steps are active or done, attempt counter, tools forged and used, and the answer text so far.
- It maps node boundaries using the overview §4.2 table, fills captions and log lines from `copy.py`, and emits `link.flow` between consecutive steps.
- It picks the strip variant from the planner output: the current sub-task's `needs` label. `forge` → `forge`, `vault` → `vault`, `primitive` → `primitive`, an empty plan → `chat`.
- It builds `answer.done.chips` and `run.finished.summary` with the demo's exact wording:
  - forged: chip `Forged {tool}`; summary `1 tool forged, {n} attempts`
  - reused: chip `Reused {tool} from the vault`; summary `0 tools forged`
  - failed: chip `{tool} raised a {ErrorType}`; summary `Failed, {k} failure in a row` or `Failed, removed from the vault`
  - primitive: summary `Built-in` or `Built-in, approved`
  - declined: summary `Declined, nothing ran`
  - chat: summary `Answered directly`
  - stopped: summary `Stopped`

## 7. Ask-before-exec override

`talos/config/settings.py` gains a process-level override:

```python
_auto_approve_override: bool | None = None

def set_auto_approve_override(value: bool | None) -> None: ...

def auto_approve_exec() -> bool:
    if _auto_approve_override is not None:
        return _auto_approve_override
    return os.environ.get("TALOS_AUTO_APPROVE_EXEC", "false").lower() in {"1", "true", "yes"}
```

`PATCH /api/settings {ask_before_exec}` stores the value and calls `set_auto_approve_override(not ask_before_exec)`. The CLI never sets the override, so its behaviour is unchanged.

## 8. Session naming

`naming.session_name(text) -> str` mirrors the demo's rules, in order:

1. Mentions caesar or cipher → `Caesar cipher`
2. Mentions python, `print(`, or "run this code" → `Running Python`
3. Mentions weather, openweather or temperature → `Weather in {City}` (from `in {Capitalised words}`), else `Weather in Mumbai`
4. "what can you do" and similar → `Getting to know Talos`
5. "how many tools", or "in your vault" → `What's in the vault`
6. Otherwise the first four words, first letter uppercased

The user can rename with `PATCH`. The frontend decodes the new name into place, as in the demo.

## 9. Fake graph mode

`TALOS_FAKE_GRAPH=1` swaps the graph for `fake_graph.FakeRunner`. It emits the same contract events for the demo's five scripted flows: Caesar forge with one retry, Caesar reuse, Caesar failure with the word-number shift, `python_exec` approval, and OpenWeatherMap key. It uses the demo's routing (`classify`) and its real computations (the cipher, `print(sum(range(…)))`).

- Interrupts pause for real and resume through `/resume`.
- It updates the real vault manifest in a temporary `TALOS_VAULT_DIR` so the Vault page shows the result.
- No model calls and no keys.

This mode is used by stage 4's end-to-end tests and for building the frontend without spending tokens.

## 10. Security

- Binds to `127.0.0.1`. There's no auth, and the README says so in the Safety section.
- CORS is disabled, except `http://127.0.0.1:5173` when `TALOS_WEB_DEV=1`.
- Request size limit 64 KB.
- API key values from `/resume` are never logged: an explicit logging filter drops them, and a test covers it.
- Responses never include `.env` values or `pending_interrupt.args` / `pending_interrupt.kwargs`.

## 11. Tests

- `translator.py`, unit, with recorded chunk fixtures (captured once from real runs, then stored as JSON): the forge-with-retry run produces the exact event sequence expected by stage 4; the vault run; the chat run; the interrupt end.
- `runner.py`, unit, with a stub graph: one-active-run lock, `seq` continuity across resume, stop during run and during pause, the exception path.
- Routes, with `httpx.AsyncClient` and `TALOS_FAKE_GRAPH=1`: every endpoint's happy path and its documented error codes.
- SSE: backlog then live, `Last-Event-ID` resume after a dropped connection, close after `run.finished`.
- Security: a key value sent to `/resume` doesn't appear in logs, in `run_events`, or in any response.
- Integration (Postgres): full fake-graph Caesar run, then a restart mid-pause (a new app instance) and a successful resume.

## 12. Acceptance

- `uv run talos-web` with `TALOS_FAKE_GRAPH=1` and a local Postgres serves every endpoint, and a scripted Caesar run streams the full event sequence over `curl -N`.
- With real keys and without fake mode, the same Caesar question produces the same event types in the same order.
- All tests in §11 pass. Unit tests need no database.
