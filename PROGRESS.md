# Talos AI — Build Progress

> Living document. Updated after every work session. Read this first when opening a new chat to know exactly where we are.

**Stack confirmed**: OpenAI only (gpt-4o) for now • Tavily • Jina Reader • LangSmith • LangGraph • LangChain • `uv` venv • pytest per-module tests

**Keys status**: Tavily, Jina, LangSmith provided (free dev keys). OpenAI key pending — user will provide before Phase 4.

**Scope**: Backend only. CLI/REPL is the sole interface. No frontend, no web UI, no HTTP server in any phase below — deferred to a future phase not yet planned.

---

## Phase status legend
- [ ] Not started
- [~] In progress
- [x] Done
- [!] Blocked

---

## Phase 0 — Project setup & secrets ✅
- [x] `uv` venv created at `.venv/` (Python 3.12.12)
- [x] `pyproject.toml` with deps: langgraph, langchain, langchain-openai, langchain-community, langsmith, tavily-python, python-dotenv, requests + dev: pytest, pytest-asyncio, ruff
- [x] `.gitignore` (venv, .env, __pycache__, .pytest_cache, vault state)
- [x] `.env` populated with Tavily, Jina, LangSmith keys (OpenAI placeholder empty)
- [x] `.env.example` mirror without values
- [x] Folder skeleton per CLAUDE.md
- [x] `talos/config/settings.py` loads .env, exposes constants + `key_status()` helper
- [x] Smoke test passes: model=gpt-4o, 3/4 keys present (OpenAI pending), pytest collects 0 tests cleanly

**Test gate**: ✅ smoke script confirms keys load; `pytest` runs cleanly.

**Notes**:
- Resolved python version mismatch: CLAUDE.md says 3.11+, system has 3.13 but uv picked 3.12.12 for the venv. Fine, all >=3.11.
- Created minimal `README.md` (hatchling required it for the build). Will expand in Phase 10.
- `talos/vault/manifest.json` and `talos/vault/tools/*.py` are gitignored — vault is per-user runtime state.
- OpenAI key intentionally blank; will be filled before Phase 4 (Forger).

---

## Phase 1 — State + graph skeleton ✅
- [x] `talos/state.py` — `TalosState` TypedDict with `add_messages` reducer + `visited` debug field
- [x] `talos/graph.py` — 8 stub nodes wired (orchestrate, plan, search_vault, forge, test, execute, learn, respond) + 4 routers
- [x] `talos/main.py` — REPL that invokes the graph and prints traversal/state
- [x] `tests/test_graph_flow.py` — 5 tests: compiles, runs, traversal order, message reducer, partial-state merge

**Test gate**: ✅ 5/5 pass.

**Notes**:
- Phase 1 stub routing path: `orchestrate → plan → search_vault → forge → test → execute → learn → respond`. Real Phase 6 wiring will route `learn → plan` (sub-task loop); kept it `learn → respond` for now to avoid infinite stub loops.
- `visited: list[str]` is a Phase-1-only debug field on TalosState. Removed once real nodes land.
- `add_messages` reducer demonstrated and tested — node returns `{"messages": [m]}` appends rather than replaces (default reducer is "replace").
- `app = build_graph().compile()` exposed at module level for both `main.py` and tests; tests can also rebuild fresh via `build_graph()`.

---

## Phase 2 — Primitives ✅
- [x] `primitives/web_search.py` (Tavily, raw SDK — not LangChain Tool wrapper)
- [x] `primitives/web_read.py` (Jina r.jina.ai with optional Bearer auth)
- [x] `primitives/file_ops.py` (file_read + file_write, UTF-8, auto-mkdir on write)
- [x] `primitives/python_exec.py` (subprocess, configurable timeout, structured result dict)
- [x] `primitives/shell_exec.py` (same shape as python_exec, shell=True for pipes)
- [x] `primitives/human_input.py` (LangGraph `interrupt()` wrapper)
- [x] `tests/test_primitives.py` — 12 tests including live Tavily/Jina, timeout-fires assertions, and a checkpointer-backed interrupt test

**Test gate**: ✅ 12/12 pass (~4s).

**Notes**:
- **Design contract**: exec primitives (python/shell) return errors as data (`{"ok": False, ...}`) — they never raise. Network primitives (Tavily/Jina) raise on auth/network failure so misconfig fails loud at first call.
- Did NOT wrap primitives as LangChain `Tool` objects. They're called directly by nodes, not picked by an LLM tool-calling loop. Same goes for forged tools later.
- `human_input` test uses an inline tiny graph + `MemorySaver` checkpointer to prove `interrupt()` pauses correctly. Real HITL resume flow lands in Phase 9.
- Result dict shape (used by Tester in Phase 4): `{ok, returncode, stdout, stderr, timed_out}`.

---

## Phase 3 — Skill Vault ✅
- [x] `vault/manager.py` — `SkillManager` class with `search`, `register`, `load`, `record_usage`, `all`
- [x] `SkillEntry` TypedDict matching CLAUDE.md manifest schema
- [x] Atomic manifest writes (tmp + rename)
- [x] `tests/test_vault_manager.py` — 12 tests covering manifest lifecycle, search ranking, load+reload-on-overwrite, usage tracking

**Test gate**: ✅ 12/12 vault tests + full 29/29 suite green.

**Notes**:
- **Big design choice**: `load()` does NOT use `importlib.import_module`. It reads the `.py` source as text and runs `exec(compile(...), namespace)`. Reason: Python's `.pyc` bytecode cache uses second-resolution mtimes — two `register()` calls within the same second otherwise serve stale bytecode. The Forger's retry loop will absolutely hit this. `exec()` is cache-free and predictable. The reload test (`test_reload_picks_up_overwritten_code`) caught this exact bug during this phase — both `import_module` and `spec_from_file_location` failed it.
- This also means the vault dir does not need to be on `sys.path` or be a Python package — tests can use `tmp_path`. Cleaner.
- Manifest is a plain JSON list (not dict-keyed-by-name) so it stays human-readable and stable-ordered for git diffs (when un-gitignored later).
- Did NOT seed sample tools into the real vault — keeping vault empty for clean Phase 4 forging.

---

## Phase 4 — Forger + Tester (core loop) ✅
- [x] `prompts/forger.py` — system prompt + `build_retry_context()` helper
- [x] `agents/forger.py` — `ForgedTool` Pydantic schema + `forger_node` using `ChatOpenAI.with_structured_output`
- [x] `agents/tester.py` — `run_tests()` utility + `tester_node`. Custom subprocess test runner using `TALOS_TEST` markers (no pytest dep at runtime)
- [x] `agents/forge_subgraph.py` — compiled forge ↔ test ↔ retry sub-graph (`forge_app`)
- [x] `tests/test_tester.py` — 8 tests (happy path, assertion fail, syntax error, runtime error, timeout, partial failure)
- [x] `tests/test_forger.py` — 5 mocked tests (first attempt, retry context, sub-graph succeed first/second try, retry exhaustion) + 1 live test gated by `RUN_LIVE=1` (skipped by default)

**Test gate**: ✅ 13/13 mocked tests; full suite 42 passed, 1 skipped (live).

**Notes**:
- **Did not create `prompts/tester.py`** — Tester has no LLM in Phase 4. PROGRESS.md previously listed it; reserved for later if test generation moves out of the Forger.
- **Structured output**: `ChatOpenAI.with_structured_output(ForgedTool)` returns a runnable that yields a typed Pydantic instance. Field descriptions on `ForgedTool` reach the LLM as JSON schema descriptions. (PydanticAI analogue: `result_type=ForgedTool`.)
- **Sub-graph as modularity primitive**: `build_forge_subgraph()` returns its own `StateGraph` reusing `TalosState` fields. Compiled to `forge_app`. The outer graph (Phase 7) will call this as a single node — gives a clean LangSmith trace boundary.
- **Test runner design**: instead of subprocess-invoking pytest, we append a tiny `_RUNNER` script that emits `TALOS_TEST PASS/FAIL` markers and a `TALOS_TEST SUMMARY` line. Parsed by `_parse_runner_output`. Fast, dep-free, and gives us structured per-test failures without exit-code guessing.
- **pytest collection gotcha**: pytest's default `python_functions = test` matched `tester_node` as a test. Tightened to `test_*` in `pyproject.toml`. Lesson: never name non-test helpers starting with "test".
- **LLM mocking pattern**: tests monkeypatch `forger._make_llm` (the factory) with a `_FakeLLM` returning canned `ForgedTool` objects. Cheap, deterministic, no network.
- **Live test caught a real prompt bug**: original prompt said "import the function under test from the same module," but the runner *concatenates* code + test_code into one file, so the import had nothing to resolve. Updated prompt rule #5 to forbid imports of the tool itself. Live test now passes (~5s, ~$0.005). Lesson: mocked tests can't catch prompt-vs-runtime contract mismatches — always run the live gate at least once per phase.

---

## Phase 5 — Planner
- [ ] `prompts/planner.py`
- [ ] `agents/planner.py` — emits structured sub-task plan with `needs: primitive | vault_or_forge`
- [ ] Planner consults `SkillManager.search` before deciding "forge"
- [ ] Mock-LLM golden tests for plan shape
- [ ] One live test asserting plan structure for a 3-step query

**Test gate**: planner produces valid plan structure on mocked + live inputs.

**Notes**:
_(add after work)_

---

## Phase 6 — Executor + Learn
- [ ] `agents/executor.py` — dispatch primitive vs vault tool, capture results
- [ ] `learn` node — register forged tool post-success via SkillManager
- [ ] End-to-end test (mocked LLMs): forge a tool → execute → manifest contains it → second call uses vault not forge

**Test gate**: vault grows on first call, is reused on second call.

**Notes**:
_(add after work)_

---

## Phase 7 — Orchestrator + multi-step
- [ ] `prompts/orchestrator.py`
- [ ] `agents/orchestrator.py` — sub-task dispatch loop, response synthesis
- [ ] Full graph wired with all conditional edges
- [ ] Live 2-step end-to-end test ("read URL → save summary")

**Test gate**: live multi-step query completes; LangSmith trace shows expected node path.

**Notes**:
_(add after work)_

---

## Phase 8 — Researcher
- [ ] `agents/researcher.py` — utility (not a node). Tavily + Jina, returns structured context.
- [ ] Wire into Planner and Forger
- [ ] Test: forger given an "API integration" task researches before writing code

**Test gate**: forger output references endpoint info from research step.

**Notes**:
_(add after work)_

---

## Phase 9 — Human-in-the-loop for API keys
- [ ] Interrupt flow in orchestrator
- [ ] `.env` auto-write helper
- [ ] Resume flow after user provides key
- [ ] Test: simulate interrupt + resume; assert `.env` updated and second run skips prompt

**Test gate**: HITL flow round-trips and persists.

**Notes**:
_(add after work)_

---

## Phase 10 — Polish
- [ ] Logging cleanup (no print statements anywhere)
- [ ] Error handling pass across all nodes
- [ ] `README.md` for GitHub
- [ ] `examples/demo_queries.py`
- [ ] LangSmith tracing verified for full session

**Test gate**: full demo session traceable in LangSmith; README runnable.

**Notes**:
_(add after work)_

---

## Session log
A short bullet per session — what we did, what's next. Append-only.

- **2026-04-28** — CLAUDE.md authored. Stack and API audit completed. Build plan agreed (10 phases). PROGRESS.md created. Next: start Phase 0.
- **2026-04-28** — Phase 0 complete. Venv (py3.12.12), all deps installed, `.env`/`.env.example`/`.gitignore`/`pyproject.toml`/`README.md` in place, `settings.py` loads cleanly, pytest collects 0 tests. Next: Phase 1 (state + graph skeleton).
- **2026-04-28** — Phase 1 complete. State + graph skeleton with 8 stub nodes and 4 routers. 5/5 tests pass. OpenAI key now in `.env`. Next: Phase 2 (primitives — Tavily, Jina, file/python/shell exec, human_input).
- **2026-04-28** — Phase 2 complete. All 6 primitives + 12/12 tests pass including live Tavily/Jina calls and an interrupt-pauses-graph test using `MemorySaver`. Next: Phase 3 (Skill Vault — SkillManager class with search/register/load).
- **2026-04-28** — Phase 3 complete. SkillManager done; 12/12 vault tests, 29/29 total. Caught and fixed a real bug: `.pyc` cache served stale code on rapid re-register. Switched `load()` from `import_module` to direct `exec()` of source. Next: Phase 4 (Forger + Tester — first real LLM agents).
- **2026-04-28** — Phase 4 complete. Forger (LLM, structured output via ChatOpenAI.with_structured_output) + Tester (custom subprocess runner) + forge sub-graph. 13 new tests; suite at 42 passed + 1 skipped. Live OpenAI test authored but not run this session. Next: Phase 5 (Planner agent — task decomposition with vault-aware needs labelling).
