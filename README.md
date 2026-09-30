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
- **Forged tools are not sandboxed.** They are tested in a subprocess with a timeout, but once registered they run inside the Talos process, with your user's permissions and no timeout.
- **There is no container isolation.** Run Talos in a VM, container, or throwaway account if you plan to point it at anything you care about.

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
| `TALOS_LOG_LEVEL` | no | Default WARNING |

## Tests

```bash
uv run pytest                   # ~5s, all mocked, no API keys needed
RUN_LIVE=1 uv run pytest        # also exercises real OpenRouter/Tavily/Jina
uv run ruff check . && uv run ruff format --check .
```

Tests are organised by component. LLMs are mocked at the factory seam (`_make_llm`, `_make_resolver_llm`, etc.) for cheap deterministic runs. Live tests are gated by `RUN_LIVE=1`. CI runs lint and the mocked suite on Python 3.11 and 3.12.

## Known limits (POC)

- Forged tools run in-process after registration: no sandbox, no timeout (see [Safety](#safety-read-this-first)).
- Subprocess isolation only for tests and exec primitives, not Docker/E2B.
- Keyword vault search; no semantic search yet (deferred until the vault grows).
- Single provider (OpenRouter): one model for every node, set via `TALOS_MODEL`.
- OAuth-style API auth is out of scope; only env-var-keyed APIs are supported via HITL.
- In-memory checkpointer (`MemorySaver`); conversation state is lost on exit. The vault persists.

## Acknowledgements

The skill-crystallization idea (an agent that turns solved tasks into reusable tools) is inspired by [GenericAgent](https://github.com/lsdefine/GenericAgent). Talos rebuilds that loop graph-native on [LangGraph](https://github.com/langchain-ai/langgraph) so every phase is a visible, debuggable node.

## License

[MIT](LICENSE) © 2026 Yathharth Karanjikar
