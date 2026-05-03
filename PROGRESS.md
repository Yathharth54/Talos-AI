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

## Phase 5 — Planner ✅
- [x] `prompts/planner.py` — system prompt + `build_planner_user_message()` + `format_vault_summary()`
- [x] `agents/planner.py` — `Plan` / `SubTask` Pydantic models + `planner_node`
- [x] Vault contents injected into the user message every call (full-dump approach for POC; switch to keyword pre-filter once vault > ~50 tools)
- [x] Vault hallucination guard: if LLM picks `needs="vault"` with an unknown name, downgrade to `forge`
- [x] `tests/test_planner.py` — 6 mocked tests (well-formed plan, empty plan, vault hint pickup, hallucination downgrade, prompt injection, empty-vault handling) + 1 live gated test

**Test gate**: ✅ 6/6 mocked + live test pass; full suite 48 passed, 2 skipped.

**Notes**:
- **3-state `needs` instead of CLAUDE.md's `vault_or_forge`**: I split it into explicit `primitive | vault | forge`. Reason: the Planner already knows whether a primitive applies (it has the primitives list in the system prompt), so we shouldn't defer that decision to a `search_vault` node. The Phase 1 stub graph router will need updating in Phase 7 to read these three labels.
- **Hallucination guard**: LLMs occasionally invent vault tool names that don't exist. `planner_node` post-validates against `SkillManager.all()` and downgrades unknown `vault` hints to `forge`. The Forger then handles them.
- **Test seams**: both `_make_llm()` (LLM factory) and `_get_skill_manager()` (vault factory) are module-level functions, monkeypatched in tests. Same pattern as Forger.
- **Live test passed first try** — no prompt bug this time. (~3.5s, ~$0.005.)

---

## Phase 6 — Executor + Learn ✅
- [x] `prompts/arg_resolver.py` — small system prompt for the in-Executor arg resolution call
- [x] `agents/executor.py` — `executor_node` dispatches primitive / vault / forge; `_resolve_args()` LLM call resolves natural-language input descriptions into concrete `args/kwargs`; usage counter bumped on success
- [x] `agents/learner.py` — `learn_node` validates forged_tool and registers it via SkillManager when tests passed; no-op otherwise
- [x] `tests/test_executor.py` — 9 mocked + 1 live (passes): primitive/vault/forge dispatch, runtime error capture, missing tool, usage counter, prior-results-in-prompt, live arg resolution
- [x] `tests/test_learner.py` — 6 tests covering register-on-pass, no-op cases, idempotent overwrite

**Test gate**: ✅ 15/15 mocked + 1/1 live; full suite 63 passed, 3 skipped.

**Notes**:
- **Argument resolution architecture**: chose to put a small LLM call inside the Executor (`_resolve_args`) rather than asking the Planner to emit literal args. Reason: keeps the Planner prompt focused on decomposition + labelling; arg resolution can vary per call and benefits from the most-recent upstream results being in the prompt. (PydanticAI analogue: a tool call inside an agent.)
- **`method="function_calling"` gotcha**: OpenAI's strict "structured outputs" mode (default in `langchain-openai >= 0.3`) rejects open-ended types like `dict[str, Any]`. Our `ResolvedArgs.kwargs` is genuinely arbitrary, so we explicitly opt into the older `function_calling` method. Caught by the live test — would not have surfaced in mocks. Forger/Planner schemas have no `Any` and work fine in strict mode.
- **Learn node placement**: kept as a top-level node (per CLAUDE.md spec) rather than inside the forge sub-graph. Reason: separation — sub-graph generates valid code; main graph owns vault writes. Phase 7 will wire `forge → test (passed) → learn → execute`.
- **Vault dispatch == Forge dispatch (post-Learn)**: a freshly forged tool is registered by Learn, so the Executor loads it via `SkillManager.load(forged_tool['name'])` — same code path as a vault tool. The only difference between `needs="vault"` and `needs="forge"` is which name we look up.
- **Errors as data**: tool runtime errors are caught and recorded as `{ok: False, error: "TypeName: msg"}` in `sub_task_results`. The graph keeps moving; the Orchestrator (Phase 7) decides whether to abort or carry on.

---

## Phase 7.5 — Statefulness + python_exec policy fix ✅
Triggered by a real REPL session that hallucinated a Mumbai temperature. LangSmith trace revealed two stacked bugs:
- The Planner used `python_exec` as a "transform prior result" step. The arg-resolved code didn't `print()`, so stdout was empty, but `ok=True` because returncode was 0. Orchestrator then fabricated values from raw search snippets.
- The Planner / ArgResolver / Orchestrator only saw the latest user message — no conversation context, so "is THIS the highest temp?" was decomposed in isolation.

**Fixes**:
- [x] `talos/agents/_history.py` — `format_recent_history()` helper renders last N Human/AI messages
- [x] Planner / ArgResolver / Orchestrator prompts all receive a "Recent conversation" block built from `state.messages`
- [x] Planner system prompt updated: `python_exec` is for running known code only, NEVER as transformation glue. For data extraction/transformation between sub-tasks, label `needs="forge"` so we get a real tested function with structured output.
- [x] `talos/graph.py` — `app` now compiled with `MemorySaver()` checkpointer; main.py uses `thread_id` per session, no more manual history-passing
- [x] `tests/test_planner.py` — 2 new tests for history injection
- [x] `tests/test_orchestrator.py` — 1 new test verifying multi-turn checkpointer integration (turn 2's planner sees turn 1's messages)

**Test gate**: ✅ 68 passed, 4 skipped.

**Notes**:
- **Statefulness model** (PydanticAI parallel): PydanticAI does `agent.run(prompt, message_history=[...])` and threads history through automatically. We now do the equivalent via LangGraph checkpointer + `thread_id`. State for a given thread (messages, vault, anything else in TalosState) is restored before each invoke.
- **Why `MemorySaver` and not `SqliteSaver` yet**: in-process is fine for the REPL POC. Phase 9 (HITL) may still want `SqliteSaver` so the graph can resume across crashes when waiting on user input — flagged for that phase.
- **Why we don't reset `messages` in `orchestrator_in_node`**: the per-turn reset clears workflow state (plan, sub_task_results) but not messages — those accumulate via the `add_messages` reducer across turns.
- **The fabricated-temperature bug WAS NOT just bad luck** — it's a class of bug we had to fix structurally. The new Planner prompt forbids the misuse pattern; the Orchestrator prompt now explicitly says "do not fabricate values" if results don't contain them.

## Phase 7 — Orchestrator + multi-step ✅
- [x] `prompts/orchestrator.py` — final-response synthesis prompt
- [x] `agents/orchestrator.py` — `orchestrator_in_node` (state hygiene), `orchestrator_out_node` (LLM-synthesised response), 4 routers (planner, dispatch, advance, forge-test), `advance_node`
- [x] `talos/graph.py` — full production wiring; replaces all Phase 1 stubs. Includes a synthetic `_dispatch` no-op node to host the dispatch router.
- [x] `talos/state.py` — dropped Phase 1 `visited` debug field
- [x] `talos/main.py` — REPL now displays the final AIMessage
- [x] `tests/conftest.py` — disables LangSmith tracing during tests (was spamming quota)
- [x] `tests/test_graph_flow.py` — rewritten for production graph
- [x] `tests/test_orchestrator.py` — 6 mocked end-to-end tests + 1 live test (passes ~9.5s)

**Test gate**: ✅ 8/8 mocked + 1/1 live; full suite 65 passed, 4 skipped.

**Notes**:
- **Three real bugs caught by the first test run** (and fixed):
  1. **Test-helper bug**: `_patch_resolver` was creating a new `_FakeStructured` per `_make_resolver_llm()` call, so each sub-task got the FIRST canned response. Fixed: helpers now share one fake across all factory invocations.
  2. **Forge-fail infinite loop**: when forge exhausted retries, my router went `forge_subgraph → advance → _dispatch → executor (no current_sub_task) → advance → ...` forever. LangSmith trace overflowed at 25k events. Fixed: forge-failure routes to executor (which records a clean failure record so `len(results)` grows), then advance terminates correctly.
  3. **Hallucination guard broke forge→vault chains**: Planner ran ONCE at plan time when vault was empty, then downgraded sub-task 2's `needs="vault"` to `forge` even though sub-task 1 was about to forge it. Removed the guard entirely; the Executor records a clean failure if a vault hint really doesn't resolve at run time. Deleted the now-obsolete Phase 5 test.
- **Sub-graph as a node**: `g.add_node("forge_subgraph", forge_app)` — LangGraph treats compiled graphs as first-class nodes. First time we use this pattern.
- **Synthetic `_dispatch` node**: LangGraph requires routers to be attached to nodes (not edges). When we want a "pure" routing decision after `planner` and after `advance`, the cleanest pattern is a no-op node that exists solely to host the conditional edge. (`g.add_node("_dispatch", lambda s: {})`.) Idiomatic.
- **Two orchestrator nodes, not one**: `orchestrator_in` (Python, state reset) and `orchestrator_out` (LLM, response synthesis). Mid-query dispatch is the `_dispatch` router — also not an LLM. Concentrating LLM work to where it's actually useful keeps the trace readable.
- **`tests/conftest.py`** sets `LANGSMITH_TRACING=false` for all tests so mock-LLM runs don't spam the LangSmith quota. Live tests can re-enable explicitly if needed.

---

## Phase 8 — Researcher ✅
- [x] `agents/researcher.py` — first place we use `create_react_agent` from `langgraph.prebuilt`. ReAct loop with `search_web` + `read_url` tools (LangChain `@tool` wrapped). `research(query)` returns a string answer.
- [x] `should_research(task)` heuristic — regex scan for API/web/scrape keywords; cheap, no LLM call
- [x] Forger calls `research()` on first attempt only (not retries — error trace is enough then), and only when `should_research` matches
- [x] `tests/test_researcher.py` — 7 mocked tests + 1 live (gated). Verifies heuristic, ReAct integration, forger×researcher wiring

**Test gate**: ✅ 7/7 mocked + suite at 75 passed, 5 skipped.

**Notes**:
- **First and only `create_react_agent` in the system**: every other "agent" in Talos is a hand-rolled node with structural constraints (retry caps, validation gates). The Researcher has no such constraints — "search and read until you have an answer" is exactly the ReAct pattern. Using the prebuilt here is idiomatic.
- **Why we wrap primitives as `@tool` only here**: `create_react_agent` consumes LangChain `Tool` objects (it needs the JSON schema to feed OpenAI tool-calling). Everywhere else, primitives are called directly by nodes — no `@tool` overhead needed.
- **Recursion limit**: passed via `config={"recursion_limit": 8}` in `agent.invoke()`. Prevents the ReAct loop from running forever on a poorly-defined task.
- **Cost note**: research adds 2-5 OpenAI calls per first-attempt forge for API-shaped tasks. Worth it — without research, the Forger guesses URLs and fails.

## Phase 9 — Human-in-the-loop for API keys ✅
- [x] `ForgedTool.needs_env_vars: list[str]` — Forger declares which env vars its code reads
- [x] Forger system prompt updated to populate `needs_env_vars` and to keep tests offline
- [x] `agents/hitl.py` — `hitl_check_node`. For each missing env var, calls `interrupt({type: "missing_api_key", env_var, ...})`. Resume value persisted to `.env` and `os.environ`.
- [x] Graph wiring: forge_subgraph success → `hitl_check` → `learn` → `executor` (was: success → learn → executor)
- [x] REPL drains interrupts via `Command(resume=...)` — supports multiple interrupts in a single graph run
- [x] `tests/test_hitl.py` — 7 tests covering env-file create/update/append, no-op cases, full interrupt+resume cycle, "skip" path

**Test gate**: ✅ 7/7 + suite at 82 passed, 5 skipped.

**Notes**:
- **Env-file persistence is hand-rolled**: `_persist_env_var` reads + rewrites the .env in place. Could use `python-dotenv.set_key`, but hand-rolling lets us control formatting and makes tests trivial (just point `DOTENV_PATH` at `tmp_path`).
- **Skip path**: user can type `skip` to abort key entry. The forge succeeded, but the tool's first execute will fail cleanly because the env var stays unset — recorded as a normal sub-task failure.
- **Multiple interrupts per run**: a forged tool that needs two keys triggers two sequential interrupts. The REPL's `_drain_interrupts` loop handles them one by one.
- **Checkpointer requirement**: `interrupt()` only works when the graph is compiled with a checkpointer. Phase 7.5 already wired `MemorySaver()`, so this came free.

## Phase 10 — Polish ✅
- [x] `talos/config/logging.py` — central `setup_logging()`. Quiet by default; `TALOS_LOG_LEVEL=DEBUG` for verbosity.
- [x] `main.py` calls `setup_logging()` at startup; HTTP libs (httpx/openai/urllib3/langsmith) silenced unless DEBUG
- [x] `examples/demo_queries.py` — three runnable scenarios: primitives-only, pure-python forge, research-driven forge
- [x] `README.md` — full architecture, quick start, config table, project layout, known limits

**Test gate**: ✅ Final suite 82 passed, 5 skipped (cumulative across all phases).

**Notes**:
- No `print()` in production code outside of `main.py` (REPL prompts) and `examples/demo_queries.py` (intentional).
- LangSmith tracing is wired and active when `LANGSMITH_TRACING=true`; tests force-disable it via `tests/conftest.py`.
- README is the single onramp doc; CLAUDE.md remains the design spec; PROGRESS.md remains the build log.

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
- **2026-04-28** — Phase 4 live OpenAI gate run. Caught a real prompt bug ("import the function under test" but runner concatenates) → fixed prompt rule #5. Live forge passed in ~5s. Re-ran mocked suite: still 42 green.
- **2026-04-28** — Phase 5 complete. Planner agent with vault-aware decomposition + hallucination guard. 6 mocked + 1 live test. Suite at 48 passed, 2 skipped. Note: split `needs` into explicit `primitive | vault | forge` — Phase 7 routing will need to read this. Next: Phase 6 (Executor + Learn — register forged tools and run primitives/vault tools).
- **2026-04-28** — Phase 6 complete. Executor (with embedded arg-resolver LLM call) + Learn node. 15 new mocked tests + 1 live (passes). Suite at 63 passed, 3 skipped. Live test caught a real LangChain gotcha: OpenAI strict structured outputs rejects `dict[str, Any]`; switched ArgResolver to `method="function_calling"`. Next: Phase 7 (Orchestrator + multi-step) — wire all nodes into the full graph and run end-to-end multi-step queries.
- **2026-04-28** — Phase 7 complete. Full production graph wired; orchestrator with split in/out nodes; live read-URL-write-file passes end-to-end in ~9.5s. First test run caught 3 real bugs: shared-fake-state in helpers, forge-fail infinite loop, over-eager hallucination guard. All fixed. Suite at 65 passed, 4 skipped. Next: Phase 8 (Researcher — first place we'll use `create_react_agent` from LangGraph prebuilt; web_search + web_read in a ReAct loop, called by Forger when researching APIs).
- **2026-04-29** — Phase 7.5: real REPL session hallucinated a Mumbai temperature. LangSmith trace exposed two bugs (python_exec misused as transform glue; no conversation context in prompts). Fixed: `_history.format_recent_history()` injected into Planner/ArgResolver/Orchestrator prompts; Planner prompt forbids `python_exec` as transformation glue; graph now compiles with `MemorySaver()` checkpointer; REPL uses `thread_id`. 3 new tests; suite at 68 passed, 4 skipped. Statefulness now matches PydanticAI's `message_history` model. Next: Phase 8 (Researcher).
- **2026-04-29** — Phases 8 + 9 + 10 built end-to-end without the user. Researcher (`create_react_agent` with web_search + web_read tools) wired into Forger via `should_research` heuristic. HITL for missing API keys via `interrupt()` + `_persist_env_var` writing to `.env`. Polish: central logging config, `examples/demo_queries.py`, full README. Final suite 82 passed, 5 skipped. System is now feature-complete per CLAUDE.md spec; ready for end-to-end testing and bug-hardening.
- **2026-04-29** — Hardening: user hit a truncation bug (saved file contained `...(truncated)` instead of full content). Root cause: ArgResolver's prompt truncates prior outputs to 500 chars; LLM was copying the truncated string into `file_write(content=...)`. Fix: introduced `__SUBTASK_OUTPUT_N__` placeholder pattern. Resolver emits the placeholder; executor walks resolved args/kwargs and substitutes the FULL prior output before invoking the tool. Type preservation: exact-match placeholder returns the raw object (preserves dict/list types); within-string placeholders do string substitution. 3 new tests; suite at 85 passed, 5 skipped.
- **2026-04-29** — Workspace convention: relative paths in `file_read`/`file_write` now auto-anchor to a gitignored `workspace/` directory at the repo root. Absolute paths (e.g. `/tmp/x.md`) still respected as-is — user agency intact. Planner + ArgResolver prompts updated to know the convention. Stops Talos's tendency to dump files into cwd. Two new primitive tests; suite at 98 passed, 5 skipped.

- **2026-04-29** — Two more Forger-prompt fixes after partial weather success. The first sub-task (fetch weather) now works — Forger picks open-meteo, registers cleanly, returns 28.6°C. But sub-task 2 (markdown formatting) failed because:
  1. **Forger used pytest's `monkeypatch` fixture as a test parameter**: tests crashed with `TypeError: test_X() missing 1 required positional argument: 'monkeypatch'`. Our subprocess runner calls `test_fn()` with no args. Updated test rule #4 to explicitly forbid fixtures and showed the manual swap pattern (`requests.get = fake; try: ...; finally: requests.get = original`).
  2. **Forger ignored sub-task dependency** — sub-task 2's `input_description` said "output of sub-task 1" but the Forger wrote a function that re-fetched weather (took lat/lon as args, not a `data` dict). Added rule 10a: when input_description references upstream output, the function MUST accept it as a parameter; do NOT re-fetch.
  Suite still 96 passed, 5 skipped.

- **2026-04-29** — Vault auto-prune (Option A). Real bug found: a successful but BROKEN forge (e.g. `get_mumbai_weather` requiring a paid API key) was being re-used by the planner on subsequent runs, masking subsequent prompt fixes. Added `failure_count`, `consecutive_failures`, `last_failed_at`, `last_failure_reason` to SkillEntry. New `SkillManager.record_failure(name, reason)`: increments counters; auto-removes the manifest entry after 2 consecutive failures (no successes between). `record_usage` resets the consecutive streak so flaky-but-mostly-working tools survive. Pruning removes the manifest entry only — the .py stays on disk for forensics. Executor wired to call `record_failure` on vault/forge tool exceptions. 8 new tests; suite at 96 passed, 5 skipped.

- **2026-04-29** — Hardening pass after a second weather-query failure. Trace showed:
  - Planner emitted 3 forge sub-tasks ("find API" + "fetch" + "make MD") instead of 1.
  - Forger picked WeatherAPI.com (paid, 401) instead of free open-meteo.
  - Forger took `api_key` as a function PARAMETER (no env-var pattern). Resolver passed garbage. `needs_env_vars` was empty so HITL didn't fire.
  - Forger's TESTS hit the real API and wrote `test_weather_report*.md` files into the project root.
  Fixes: Forger prompt now bans api_key-as-parameter (must use os.environ + needs_env_vars); strongly nudges toward keyless APIs (open-meteo, wttr.in, ip-api, etc.); test rules now forbid network calls AND filesystem writes; Tester subprocess now runs in a `tempfile.TemporaryDirectory` cwd so even rule-violating tests can't leak files into the project. Planner prompt rule 5 now bans "find API → fetch from it" two-forge pattern (one logical fetch = one forge). New test verifies file-leak sandbox holds. Suite 89 passed, 5 skipped.
- **2026-04-29** — Built `examples/show_trace.py` — CLI that fetches LangSmith traces via the API. Used it to diagnose a failed weather query. Two stacked bugs found:
  1. **Placeholder needed accessor syntax**: web_search returns a list of dicts; placeholder substituted the whole list into `web_read()` which expects a string URL → AttributeError. Extended placeholder syntax to support `__SUBTASK_OUTPUT_N__[idx]` and `__SUBTASK_OUTPUT_N__["key"]` chains. Walker handles list/dict/chained access; on bad accessor, returns last successful intermediate (lets the tool's own error message bubble up clearly).
  2. **Planner over-decomposed API tasks**: emitted "search → read docs → forge fetcher" for "get weather data," which is structurally fragile (sub-task 2 doesn't know which URL to read). Updated Planner prompt rule #5: for external-API/data-fetching tasks, label the fetch step `forge` directly. The Forger's built-in Researcher discovers the API itself in one step.
  3 new accessor tests; suite at 88 passed, 5 skipped.
