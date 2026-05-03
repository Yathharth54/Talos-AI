# Talos AI

A LangGraph-based self-evolving agent that forges, tests, and accumulates reusable Python tools at runtime.

## What it does

You ask Talos to do something. It:

1. **Plans** — decomposes your query into ordered sub-tasks. Each sub-task is labelled with how it should run: a built-in primitive, an existing tool from its vault, or a tool that needs to be forged.
2. **Forges** — writes Python code for any sub-task that needs a new tool. Researches free APIs first when the task involves the web. Asks for an API key if one is needed.
3. **Tests** — runs the forged code through auto-generated tests in a sandboxed subprocess. Up to 3 retries with the error trace fed back to the LLM.
4. **Executes** — runs the chosen tool with arguments resolved from your query and prior sub-task outputs.
5. **Learns** — registers successful tools in a vault on disk. Next time you ask something similar, Talos uses the existing tool instead of forging again.

Everything is a visible LangGraph node. Every step shows up as a discrete event in LangSmith traces.

## Quick start

```bash
git clone <repo>
cd Talos-AI
uv venv
uv sync --extra dev
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY
uv run python -m talos.main
```

Then type queries at the prompt:

```
> Reverse the string 'hello' and tell me the result.
> Use a free weather API to get the current temperature in Mumbai.
> Read https://example.com and save the body to /tmp/out.txt
```

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

### Components

| Component | Type | Purpose |
|---|---|---|
| **Orchestrator (in/out)** | LangGraph nodes | Per-turn state reset; final response synthesis (1 LLM call) |
| **Planner** | LangGraph node | Vault-aware decomposition (1 LLM call, structured output) |
| **Researcher** | `create_react_agent` | Web search + URL read in a ReAct loop, called by Forger before writing API code |
| **Forger** | LangGraph node | Code + test generation (1 LLM call per attempt, structured output) |
| **Tester** | LangGraph node | Subprocess execution + structured pass/fail (no LLM) |
| **HITL check** | LangGraph node | Pauses graph for missing API keys via `interrupt()` |
| **Learn** | LangGraph node | Registers forged tool in vault (no LLM) |
| **Executor** | LangGraph node | Dispatches primitive/vault/forge; ArgResolver inside (1 LLM call) |
| **Skill Manager** | Plain Python | Manifest + .py files on disk; search/register/load |

### Primitives (always available)

- `web_search` (Tavily)
- `web_read` (Jina Reader)
- `file_read` / `file_write`
- `python_exec` / `shell_exec` (subprocess + 10s timeout)
- `human_input` (LangGraph `interrupt()`)

## Project layout

```
Talos-AI/
├── talos/
│   ├── main.py              # REPL
│   ├── graph.py             # Main StateGraph wiring
│   ├── state.py             # TalosState TypedDict
│   ├── agents/              # Each "agent" is a graph node + prompt
│   │   ├── planner.py
│   │   ├── forger.py
│   │   ├── tester.py
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
│       └── logging.py
├── tests/                   # 80+ tests, ~6s end-to-end
├── examples/demo_queries.py
├── CLAUDE.md                # Architecture spec
└── PROGRESS.md              # Build log per phase
```

## Configuration

All via `.env` (see `.env.example`):

| Var | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes | Talos uses OpenAI for all LLM-using nodes |
| `OPENAI_MODEL` | no | Defaults to `gpt-4o` |
| `TAVILY_API_KEY` | yes (for web_search) | Free tier covers POC use |
| `JINA_API_KEY` | no | Optional; raises Jina Reader rate limits |
| `LANGSMITH_API_KEY` | no | Enables full tracing of every node |
| `LANGSMITH_TRACING` | no | Set `true` to enable; tests force-disable it |
| `TALOS_SUBPROCESS_TIMEOUT` | no | Default 10 (seconds) |
| `TALOS_FORGE_MAX_RETRIES` | no | Default 3 |
| `TALOS_LOG_LEVEL` | no | Default WARNING |

## Tests

```bash
uv run pytest                   # ~6s, all mocked
RUN_LIVE=1 uv run pytest        # also exercises real OpenAI/Tavily/Jina
```

Tests are organised by component. Mock LLMs at the factory seam (`_make_llm`, `_make_resolver_llm`, etc.) for cheap deterministic runs. Live tests are gated by `RUN_LIVE=1`.

## Known limits (POC)

- Subprocess sandboxing only — not Docker/E2B isolation.
- Keyword vault search — no semantic search yet (deferred until vault grows).
- OpenAI only for now (Anthropic would slot into the LangChain `ChatModel` seam).
- OAuth-style API auth is out of scope; only env-var-keyed APIs supported via HITL.
- In-memory checkpointer (`MemorySaver`); state lost on process exit. Vault persists.

See `CLAUDE.md` for the full design and `PROGRESS.md` for the per-phase build log.
