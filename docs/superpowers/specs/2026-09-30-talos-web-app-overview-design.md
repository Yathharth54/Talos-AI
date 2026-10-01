# Talos web app: overview and event contract

Date: 2026-09-30
Status: draft for review
Owner: Yathharth Karanjikar

This is the umbrella spec for turning Talos from a command-line REPL into a local web app. It fixes the scope, the build order, and the one interface every piece shares: the run event stream. Each stage has its own spec:

| Stage | Spec | Delivers |
|---|---|---|
| 1 | `2026-09-30-talos-web-01-persistence-design.md` | Postgres, Alembic, `AsyncPostgresSaver`, session/run/event tables |
| 2 | `2026-09-30-talos-web-02-api-design.md` | FastAPI app, run manager, SSE event stream, REST endpoints |
| 3 | `2026-09-30-talos-web-03-docker-sandbox-design.md` | Docker image, compose stack, forged-tool sandbox, integration tests, CI |
| 4 | `2026-09-30-talos-web-04-frontend-design.md` | The Workbench demo, ported as the real frontend with no visual change |

## 1. Intent

What the owner said:

- Talos is a personal, fun project. The web app is for the owner's own use; UX polish matters to the owner, but there are no other users to design for.
- The approved Workbench demo (https://claude.ai/artifact/6EtEykFd7rGvb77U7nwz54) must be kept exactly as it is: layout, copy, colours, motion, interactions. The real app is that demo with real data behind it.
- Build order: database and migrations, then APIs, then Docker and local tests, then the frontend.

Assumptions (correct these if wrong):

- Single user, running on their own machine. No accounts, no login, no multi-tenant anything.
- The server binds to `127.0.0.1` only. Exposing it on a network is out of scope.
- The CLI REPL (`uv run talos`) keeps working unchanged next to the web app.
- The vault stays as `.py` files plus `manifest.json` on disk. The landing page promises "no database, nothing hidden" for tools, and that stays true: Postgres holds history, not tools.

Success looks like:

1. `docker compose up` starts Postgres and the app. Opening `http://127.0.0.1:8000` shows the Workbench with the demo's exact layout, styling and motion. Only the data differs, as listed in the stage 4 spec §8, and demo mode (`/?demo`) is pixel-identical to the published demo.
2. Asking the Caesar cipher question runs the real graph. The UI animates through the same steps as the demo, driven by real events, and the forged tool shows up in the Vault page.
3. The approval dialog and the API-key dialog pause and resume the real graph, including after an app restart while the run is paused.
4. Sessions and runs survive restarts, and the Sessions page and "View this run" replay them.
5. Forged tools no longer run inside the server process. They run in a subprocess with a time limit.
6. The unit suite still passes with no keys and no Docker. Integration tests pass against Postgres in compose and in CI.

## 2. Current state (what exists on `main`)

- `talos/graph.py` compiles one `StateGraph` with a `MemorySaver` checkpointer (`make_checkpointer()`). Nodes: `orchestrator_in`, `planner`, `_dispatch`, `forge_subgraph` (compiled sub-graph of `forge`, `test`, `smoke`), `hitl_check`, `learn`, `executor`, `advance`, `orchestrator_out`.
- Two interrupt types exist: `missing_api_key` (from `hitl_check_node`) and `confirm_exec` (from `executor._confirm_exec`). Approval resumes with `{"approved": true, "args": ..., "kwargs": ...}` echoing the payload, so a re-resolved call can't run different code.
- Vault tools are loaded with `exec()` into the server process (`talos/vault/manager.py` `load()`), and `smoke.py` execs forged code in-process too. There is no timeout on either.
- The Tester runs tests in a subprocess and parses `TALOS_TEST PASS|FAIL <name>` markers.
- No HTTP layer, no database, no Docker. CI runs ruff and the mocked pytest suite on 3.11 and 3.12.

## 3. Architecture

```
Browser (frontend/, React 18 + TSX, Vite)
   │  REST (JSON)                 SSE (run events)
   ▼                               ▲
FastAPI app (talos/web/)  ──►  RunManager ──► graph.astream(...)  ──► talos graph (unchanged nodes)
   │                               │                │
   │                               │                └─ emit() custom events from nodes
   │                               ▼
   │                         EventTranslator ──► run_events table + live subscribers
   ▼
Postgres: sessions, messages, runs, run_events, app_settings (Alembic)
          + LangGraph checkpoint tables (AsyncPostgresSaver.setup())
Disk:     talos/vault/manifest.json, talos/vault/tools/*.py, workspace/, .env
Sandbox:  python -m talos.sandbox.child  (one subprocess per tool call, time-limited)
```

Principles:

- The graph's nodes and routing stay as they are. The web layer observes the graph through `astream` and through a small `emit()` helper; it never reaches into node internals.
- Events are the only thing the frontend knows about a run. Live runs, replays of old runs, and the scripted demo mode all produce the same events.
- The backend sends complete facts ("attempt 2's code is X", "these 5 tests passed"). All reveal pacing (code typing in, tests ticking, words fading in) happens in the frontend, with the demo's timings.

## 4. The run event contract

This section is normative for stages 2 and 4.

### 4.1 Envelope

Every event, live or replayed, is one JSON object:

```json
{ "run_id": "3f2a…", "seq": 12, "ts": "2026-09-30T14:23:55.120Z", "type": "node.started", "data": { … } }
```

- `seq` starts at 1 per run and increases by 1 with no gaps. It is the SSE `id:` field.
- `ts` is server time, ISO 8601 UTC with milliseconds.
- Events are persisted before they are published, so a replay from `seq` N is always complete.

### 4.2 UI step keys

The frontend's graph strip uses these keys, not LangGraph node names:

| Key | Label | Calls a model (gold pip) |
|---|---|---|
| `planner` | Planner | yes |
| `forger` | Forger | yes |
| `tester` | Tester | no |
| `human` | Human check | no |
| `learn` | Learn | no |
| `executor` | Executor | yes |
| `answer` | Answer | no |
| `vault` | Vault tool | no |
| `primitive` | Primitive | no |
| `skip` | Forge sub-graph skipped | no |

Strip variants, in order:

- `forge`: planner, forger, tester, human, learn, executor, answer
- `vault`: planner, vault, skip, executor, answer (`skip` starts in state `skip`)
- `primitive`: planner, primitive, executor, answer
- `chat`: planner, answer

Graph node to UI step mapping, done by `EventTranslator`:

| LangGraph node | UI step | Notes |
|---|---|---|
| `orchestrator_in` | none | resets per-turn state |
| `planner` | `planner` | on finish, emit `plan.ready`, then `strip.set` for sub-task 1 |
| `_dispatch` | none | its routing decision picks the strip variant for the current sub-task |
| `forge_subgraph` › `forge` | `forger` | one `node.started` per attempt |
| `forge_subgraph` › `test` | `tester` | |
| `forge_subgraph` › `smoke` | `tester` | reported as `forge.smoke`, the step stays `tester` |
| `hitl_check` | `human` | finish status `skipped` when no key was needed |
| `learn` | `learn` | emits `vault.saved` |
| `executor` | `executor` | also marks `vault` or `primitive` done first for those variants |
| `advance` | none | emits `subtask.started` when there is a next sub-task |
| `orchestrator_out` | `answer` | streams `answer.delta` |

### 4.3 Event types

| Type | Data | Emitted when |
|---|---|---|
| `run.started` | `{session_id, query, n}` (`n` = run number in the session) | run task begins |
| `log.cmd` | `{text}` | first event after `run.started`: the query line (`talos › …`) |
| `plan.ready` | `{subtasks: [{id, action, needs: "primitive"\|"vault"\|"forge", tool_hint, depends_on}], verdict}` | planner finished |
| `strip.set` | `{variant, subtask: {index, total, label}, sig: {name, args, ret} \| null}` | a sub-task begins, before its first `node.started` |
| `subtask.started` | `{index, total}` | `advance` moves to the next sub-task |
| `node.started` | `{step, label?}` | step becomes active. `label` overrides the step label, e.g. `"Executor, waiting for you"` |
| `node.finished` | `{step, status: "done"\|"forge"\|"skip"\|"fail"\|"answer"\|"stopped", label?}` | step ends. `forge` = gold done state for forger/tester. `stopped` = the step was active when the user pressed Stop |
| `link.flow` | `{from, to}` | a gold packet should travel between two steps |
| `caption` | `{html}` | narration under the strip (server builds it from the fixed caption table in §4.5) |
| `log.line` | `{label, text, tone: "plain"\|"g"\|"w"\|"sub", caret?: bool}` | one run-log line. `g` gold, `w` bone |
| `log.pop` | `{}` | remove the last log line (replaces a transient "running" line) |
| `log.status` | `{text, gold: bool, tone: ""\|"warm"\|"alert"}` | run-log caption and frame tone |
| `talos.status` | `{text}` | the "working on it" status next to the orbit spinner |
| `forge.code` | `{tool, attempt, file, lines: [str], changed: int \| null, note: str \| null, tests?: int, sig?: {name, args, ret} \| null}` | forger produced code for an attempt. `changed` = the first line that differs from the previous attempt. `tests` = how many tests that attempt wrote (the `def test_` count in its `test_code`); the translator sends the event once the forge node's update carries it. `sig` = the forged tool's signature (from `forged_tool.signature`), which the bench heading shows, because a forge sub-task's `strip.set.sig` is null when the plan names no tool |
| `forge.tests` | `{tool, attempt, results: [{name, passed, why: str \| null}]}` | tester finished an attempt |
| `forge.attempt` | `{attempt, ok, detail}` | an attempt is decided |
| `forge.smoke` | `{call, result \| null, passed}` | smoke gate ran |
| `vault.saved` | `{tool: VaultEntry, sub}` | learn registered a tool. `sub` = the banner's second line |
| `vault.failure` | `{tool, streak, pruned, error}` | a vault/forged tool raised during execute |
| `call.args` | `{tool, args: [[name, repr, suspicious: bool]], caption}` | executor resolved arguments |
| `call.result` | `{repr, type, small: bool}` | tool returned |
| `call.error` | `{error, when}` | tool raised or was declined |
| `interrupt` | `{kind: "confirm_exec"\|"missing_api_key", payload}` | the graph paused. Run status becomes `waiting` |
| `interrupt.resolved` | `{kind, decision}` | the user answered |
| `answer.delta` | `{text}` | streamed answer tokens from `orchestrator_out` |
| `answer.done` | `{html, note \| null, chips: [{kind: "forged"\|"reused"\|"failed", text}]}` | final answer. `html` and `note` may contain only `<span class="mono">` and in-app `<a href="#vault">` / `#settings` links; everything else is escaped |
| `run.finished` | `{status: "done"\|"failed"\|"stopped"\|"declined", summary, summary_gold: bool, forged: [str], used: [str]}` | always the last event |
| `error` | `{message}` | unexpected failure. Always followed by `run.finished` with `failed` |

`interrupt.payload` shapes:

- `confirm_exec`: `{tool: "python_exec"\|"shell_exec", preview: str}`. The server keeps `args`/`kwargs` itself (see stage 2), so the browser never sends code back.
- `missing_api_key`: `{env_var, tool_name, service}`. `service` is derived from the env var name, e.g. `OPENWEATHERMAP_API_KEY` → `OpenWeatherMap`, falling back to the env var itself.

### 4.4 Where events come from

- Node boundaries come from `stream_mode="updates"` with `subgraphs=True`. That covers `forge`/`test`/`smoke` inside `forge_subgraph`.
- Facts that aren't in state updates come from a new helper, `talos/events.py`:

  ```python
  def emit(event_type: str, **data) -> None:
      """Send a custom stream event if a stream is listening; otherwise do nothing."""
  ```

  It wraps `langgraph.config.get_stream_writer()` and swallows the error raised outside a streaming context, so the CLI and the unit tests are unaffected. Nodes call it in these places only:
  - `forger_node`: `forge.code` (computing `changed` against the previous attempt's code)
  - `tester_node`: `forge.tests`. The runner output parser must also return per-test names and pass/fail; it already reads `TALOS_TEST PASS|FAIL <name>` lines.
  - `smoke_node`: `forge.smoke`
  - `executor_node`: `call.args` after resolution, then `call.result` or `call.error`
  - `SkillManager.record_failure`, via the executor: `vault.failure`
  - `learn_node`: `vault.saved`
- Answer tokens come from `stream_mode="messages"`, filtered to the `orchestrator_out` node.
- Everything else is derived by `EventTranslator` from those three sources: `strip.set`, `link.flow`, `caption`, `log.*`, `talos.status`, `answer.done`, `run.finished`.

### 4.5 Captions, log lines and chips

The copy is fixed and must match the demo word for word. `EventTranslator` owns one table of templates, `talos/web/copy.py`, taken from the reference demo (`docs/superpowers/specs/reference/workbench-demo/index.html`). A test asserts that every template string appears verbatim in the reference file. Examples:

| Moment | Caption | Log line |
|---|---|---|
| planning | `The Planner is splitting your request into sub-tasks and checking the vault.` | |
| plan needs forge | `1 sub-task. Nothing in the vault matches, so it needs a new tool.` | `plan` `1 sub-task, needs a new tool` |
| vault miss | | `vault` `no match` |
| forger attempt 1 | `The Forger is writing <span class="mono">{tool}</span> and its tests in one structured call.` | `forge` `{tool}()` (g) |
| forger retry | `<span class="gold">Attempt {n} of 3.</span> The failing test and its traceback went back to the Forger.` | `forge` `attempt {n}` (g) |
| tester | `<span class="gold">Attempt {n} of 3.</span> Running {k} tests in a subprocess, 10-second limit.` | `test` `running` (g, caret), then popped |
| tests failed | | `test` `{p} of {k} passed, retrying` (g) + sub line with the failing test name |
| tests passed | | `test` `{k} of {k} passed` (g) |
| smoke | `Smoke test: the tool runs once on a real input before it can be saved.` | `smoke` `{result}` |
| human skipped | `No API key needed, so Human check passed straight through.` | |
| learn | `Learn is writing the .py file and its manifest entry.` | `learn` `saved to the vault` |
| executor | `The Executor is reading your message and filling in the arguments.` | `execute` `done` (w) |

Multi-sub-task plans are allowed by the contract: the label reads `Sub-task {i} of {n}, …`, and the strip is reset with `strip.set` for each sub-task. The demo only shows single-sub-task runs, so any multi-sub-task copy not in the reference file must be added to `copy.py` and the frontend spec together.

Numbers in the copy come from settings, not literals: `3` is `TALOS_FORGE_MAX_RETRIES`, `10-second` is `TALOS_SUBPROCESS_TIMEOUT`, and `2` failures in a row is `_AUTO_PRUNE_THRESHOLD`.

### 4.6 Honest animation

The frontend animates facts that arrive whole:

- The Forger returns a whole file in one structured call. The code "typing in" is the frontend revealing `forge.code.lines` at the demo's pace.
- Test results arrive together when the subprocess ends. The frontend ticks them one by one at the demo's pace.
- Answer words stream for real from `answer.delta`. The frontend still fades each word in the way the demo does.

The frontend holds each active step for at least the demo's dwell time (stage 4 spec, §6), so a fast backend never looks jumpier than the demo.

## 5. Build order and dependencies

1. Persistence: nothing depends on the web layer yet. It includes the `emit()` helper and the tester's per-test results, both testable without HTTP.
2. API: needs stage 1. Ships with a fake-graph mode (`TALOS_FAKE_GRAPH=1`) that replays scripted event sequences, so the frontend can be built and tested without a model key.
3. Docker and sandbox: needs stages 1 and 2. The sandbox change is in the core package and also benefits the CLI.
4. Frontend: needs the stage 2 contract, and it can start against the fake graph as soon as stage 2's fake mode works.

Each stage ends with its own passing tests and its own PR.

## 6. Out of scope

- Authentication, multiple users, remote hosting, HTTPS.
- Moving tools into the database, or semantic vault search.
- Container-per-tool isolation or E2B. Stage 3 gives a subprocess with a time limit, inside the app container.
- Streaming the Forger's code token by token.
- Mobile-first redesign. The demo's responsive behaviour is kept as is, and that's all.
