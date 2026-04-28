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

## Phase 1 — State + graph skeleton
- [ ] `talos/state.py` — `TalosState` TypedDict
- [ ] `talos/graph.py` — all nodes as no-op stubs, wired with conditional edges using dummy routing
- [ ] `talos/main.py` — REPL that compiles graph and invokes
- [ ] `tests/test_graph_flow.py` — graph compiles, runs end-to-end on fake state

**Test gate**: graph compiles; mock-driven test asserts node traversal order.

**Notes**:
_(add after work)_

---

## Phase 2 — Primitives
- [ ] `primitives/web_search.py` (Tavily)
- [ ] `primitives/web_read.py` (Jina r.jina.ai)
- [ ] `primitives/file_ops.py` (file_read + file_write)
- [ ] `primitives/python_exec.py` (subprocess + 10s timeout)
- [ ] `primitives/shell_exec.py` (subprocess + 10s timeout)
- [ ] `primitives/human_input.py` (LangGraph interrupt wrapper)
- [ ] `tests/test_primitives.py` — one test per primitive, including timeout-fires assertion for python_exec

**Test gate**: all primitive tests pass; live Tavily + Jina calls succeed.

**Notes**:
_(add after work)_

---

## Phase 3 — Skill Vault
- [ ] `vault/manager.py` — `SkillManager` class with `search`, `register`, `load`
- [ ] `vault/manifest.json` seeded
- [ ] 1–2 hand-written sample tools in `vault/tools/`
- [ ] `tests/test_vault_manager.py` — search by keyword, register writes file+manifest, load returns working callable

**Test gate**: vault tests pass; manifest schema validates.

**Notes**:
_(add after work)_

---

## Phase 4 — Forger + Tester (core loop)
- [ ] `prompts/forger.py` — code generation system prompt
- [ ] `prompts/tester.py` — test generation system prompt
- [ ] `agents/forger.py` — emits {code, test_code, name, description}
- [ ] `agents/tester.py` — runs test in subprocess, structured pass/fail with stdout/stderr
- [ ] Forge→test→retry (max 3) sub-graph
- [ ] Unit tests with mocked LLM (forger returns valid Python, tester handles good+bad code)
- [ ] Live integration test gated by `RUN_LIVE=1`: "reverse a string" forges + passes
- [ ] Failure path test: 3 retries → graceful failure

**Test gate**: mock unit tests pass; live test produces a working forged tool.

**Notes**:
_(add after work)_

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
