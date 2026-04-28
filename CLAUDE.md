# CLAUDE.md — Talos AI

## Project identity

- **Name**: Talos AI
- **One-liner**: A LangGraph-based self-evolving agent that forges, tests, and accumulates reusable tools at runtime.
- **Philosophy**: Inspired by GenericAgent's skill crystallization, but built graph-native on LangGraph. Every phase of the self-evolving loop is a visible, debuggable node — not buried in imperative code. Tools are atomic, composable Python functions — not monolithic execution paths.
- **Stage**: POC — prove the core forge→test→learn loop works, then layer features on top.

---

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Orchestration | LangGraph | State graph with conditional edges — the forge-test-retry loop IS a graph |
| LLM abstraction | LangChain | Model-agnostic, swap providers without rewriting nodes |
| LLM providers | OpenAI (gpt-4o) + Anthropic (claude-sonnet-4-20250514) | Support both, user configures via .env |
| Web search | Tavily | Native LangChain integration, free tier 1k searches/month |
| Web reading | Jina Reader (r.jina.ai) | Free, returns clean markdown, no API key needed for basic use |
| Tracing | LangSmith | First-class LangGraph integration, shows state at each node |
| Skill storage | JSON manifest + .py files on disk | No database for POC |
| Code execution | subprocess with timeout | No Docker for POC |
| Interface | Interactive REPL (CLI) | Chat-style, supports follow-ups and interrupts |

---

## Agent architecture

Talos has **5 LLM agents + 1 non-LLM utility**. Each agent is a separate LLM call with its own system prompt.

### Orchestrator (the boss)
- **What it does**: Owns the main LangGraph StateGraph. Receives user queries, delegates to specialists, collects results, formulates final response.
- **Does NOT**: Do any actual work. It routes.
- **Owns**: Conversation state, message history, the top-level graph.
- **Handles**: Interactive layer — if a sub-agent needs user input (API key, clarification), the Orchestrator pauses and asks.
- **Implementation**: The top-level `StateGraph` in `talos/graph.py`. Each specialist agent is a node in this graph.

### Planner (the strategist)
- **What it does**: Takes a raw user query and returns a structured task plan — what needs to happen, in what order, what each step requires.
- **Has access to**: Skill Manager (to check what tools exist), Researcher (to understand the domain before planning).
- **Output format**:
```python
{
  "sub_tasks": [
    {"id": 1, "action": "scrape website", "needs": "primitive:web_read", "input": "url from query"},
    {"id": 2, "action": "parse HTML data", "needs": "vault_or_forge", "input": "output of task 1", "depends_on": [1]},
    {"id": 3, "action": "save to file", "needs": "primitive:file_write", "input": "output of task 2", "depends_on": [2]}
  ]
}
```
- **Key behavior**: For each sub-task, the Planner explicitly states whether it needs a primitive, an existing vault tool, or a new forged tool. It checks the vault BEFORE declaring a forge is needed.

### Researcher (shared intelligence service)
- **What it does**: Uses `web_search` (Tavily) and `web_read` (Jina) to gather context. Any agent can call it.
- **Called by**:
  - Planner — to understand a domain before decomposing a task
  - Forger — to understand an API's endpoints/params/response format before writing integration code
- **NOT a standalone agent in the graph** — it's a utility function that other nodes invoke internally.
- **Key behavior**: Returns structured context, not raw HTML. Summarizes relevant information so the calling agent gets what it needs without processing noise.

### Forger (the builder)
- **What it does**: Given a task description + context from Researcher + knowledge of available integrations, writes a Python function.
- **System prompt focus**: Code generation — type hints, docstrings, error handling, clean function signatures, `requests` for HTTP calls.
- **Contains the Tester internally** — the forge→test→retry loop is a sub-graph:
  1. Forger writes tool code + test code
  2. Tester runs tests via `python_exec`
  3. If fail → error context fed back to Forger → retry (max 3)
  4. If pass → tool moves to Executor + Skill Manager registers it
- **Phase 1 (POC)**: Pure Python only — string manipulation, math, data transformation, parsing.
- **Phase 2 (later)**: I/O tools — API calls, scraping, file processing.

### Tester (the Forger's inner critic)
- **What it does**: Takes forged code, generates test cases, runs them via subprocess with 10s timeout, reports pass/fail with stdout/stderr.
- **Lives inside the Forger's sub-graph** — not a top-level node.
- **On failure**: Returns the error trace to the Forger along with the failing test, so the Forger can fix the specific issue.

### Executor (the hands)
- **What it does**: Runs tools — primitives or forged vault tools — against real inputs. Captures and returns results.
- **For vault tools**: Uses `importlib.import_module()` to dynamically load the tool from the vault.
- **For primitives**: Calls them directly.
- **Returns**: The result of the tool execution, which the Orchestrator collects.

### Skill Manager (the librarian — NOT an LLM)
- **What it does**: Pure Python utility. Three functions:
  - `search(keywords: list[str]) -> list[SkillEntry]` — keyword match against manifest
  - `register(skill: SkillEntry) -> None` — write .py file + update manifest.json
  - `load(skill_name: str) -> Callable` — dynamic import, return the function
- **Called by**: Planner (check what exists), Forger (register new tools), Executor (load tools to run).

---

## Tool taxonomy

### Primitives (always available, hardcoded)
These are Talos's built-in senses. They exist from day one and are never forged.

| Primitive | Implementation | Purpose |
|-----------|---------------|---------|
| `web_search` | Tavily API via LangChain | Search the internet |
| `web_read` | Jina Reader (`r.jina.ai/{url}`) | Fetch + parse any URL to clean markdown |
| `file_read` | Python built-in `open()` | Read local files |
| `file_write` | Python built-in `open()` | Write local files |
| `python_exec` | `subprocess.run()` with 10s timeout | Execute Python code |
| `shell_exec` | `subprocess.run()` with 10s timeout | Execute shell commands |
| `human_input` | LangGraph `interrupt()` | Pause graph, ask user for input (API keys, confirmations) |

### Forged tools (learned at runtime, persisted)
Created by the Forger, validated by the Tester, stored in the Skill Vault.

**Stored as**: Individual `.py` files in `talos/vault/tools/` + entries in `talos/vault/manifest.json`.

**Manifest entry format**:
```json
{
  "name": "csv_top_rows",
  "description": "Parse a CSV and return top N rows sorted by a given column",
  "keywords": ["csv", "parse", "sort", "top", "rows", "data", "table"],
  "file": "tools/csv_top_rows.py",
  "function": "csv_top_rows",
  "signature": "csv_top_rows(filepath: str, column: str, n: int = 5) -> list[dict]",
  "created_at": "2026-04-28T10:30:00",
  "usage_count": 0,
  "last_used": null
}
```

**Forged tool code requirements** (enforced by Forger's system prompt):
- Single function per file
- Type hints on all parameters and return type
- Docstring with description, args, returns, example
- Error handling (try/except with meaningful messages)
- No global state, no side effects beyond the function's stated purpose
- Import dependencies at the top of the file
- Only use stdlib + `requests` for HTTP (no exotic dependencies in Phase 1)

---

## External API integration strategy

### Tier 1: Free no-auth APIs — agent handles entirely
The Forger discovers these via the Researcher (web_search + web_read) and writes integration code directly. No human involvement.

Examples: open-meteo.com (weather), ip-api.com (geolocation), exchangerate-api.com, Wikipedia API, public government data APIs.

**The Forger's prompt instructs it to always search for free alternatives first.**

### Tier 2: APIs needing keys — agent researches, human provides
1. Forger determines auth is needed (from Researcher's API docs context)
2. Forger signals the Orchestrator that a key is required
3. Orchestrator uses `human_input` primitive to pause and ask the user
4. Orchestrator provides: what key is needed, signup URL, brief instructions
5. User provides the key
6. System saves it to `.env` file
7. Forger proceeds to write the tool using `os.environ.get("KEY_NAME")`
8. Key persists for future sessions — next time, no interruption needed

### Tier 3: OAuth / complex auth — OUT OF SCOPE
Browser-based login, redirect URIs, token refresh = not in POC. Acknowledged in README.

---

## Data flow for multi-step tasks

```
User: "Find top 5 trending Python repos on GitHub and save a summary to a file"

Orchestrator receives query
  → Planner decomposes:
      Sub-task 1: Scrape GitHub trending (needs: primitive:web_read)
      Sub-task 2: Parse repo data from HTML (needs: vault_or_forge)
      Sub-task 3: Format as summary (needs: vault_or_forge)
      Sub-task 4: Write to file (needs: primitive:file_write)

Orchestrator dispatches sub-task 1:
  → Executor calls web_read("https://github.com/trending/python")
  → Returns raw text/markdown

Orchestrator dispatches sub-task 2:
  → Skill Manager: search(["github", "trending", "parse"]) → no match
  → Forger: write parse_github_trending()
    → Researcher: fetch GitHub trending page structure docs
    → Forger writes code → Tester validates → pass
    → Skill Manager registers parse_github_trending
  → Executor runs parse_github_trending(raw_text) → structured list

Orchestrator dispatches sub-task 3:
  → Skill Manager: search(["format", "summary", "markdown"]) → no match
  → Forger: write format_repo_summary()
    → Forger writes code → Tester validates → pass
    → Skill Manager registers format_repo_summary
  → Executor runs format_repo_summary(repo_list) → markdown string

Orchestrator dispatches sub-task 4:
  → Executor calls file_write("trending_summary.md", markdown_string)

Orchestrator combines results → responds to user

NEXT TIME same query:
  → Planner sees parse_github_trending + format_repo_summary in vault
  → Skips forge entirely → straight to execute
```

---

## LangGraph state definition

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

class TalosState(TypedDict):
    # Conversation
    messages: Annotated[list[BaseMessage], add_messages]

    # Planning
    plan: dict | None                    # structured task plan from Planner
    current_sub_task: dict | None        # the sub-task currently being processed
    sub_task_results: list[dict]         # collected results from completed sub-tasks

    # Skill search
    skill_matches: list[dict]            # tools found in vault for current sub-task

    # Forging
    forged_tool: dict | None             # name, code, test_code, description
    test_result: dict | None             # pass/fail, stdout, stderr
    retry_count: int                     # forge→test retries (max 3)

    # Execution
    execution_result: str | None         # output from running the tool

    # Routing flags
    needs_forge: bool                    # does current sub-task need a new tool?
    needs_human_input: bool              # does agent need to ask the user something?
    human_input_request: dict | None     # what to ask (message, context)

    # API keys discovered during session
    available_integrations: dict         # name → env_var mapping from .env
```

---

## LangGraph graph structure

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(TalosState)

# Add nodes
graph.add_node("orchestrate", orchestrate_node)
graph.add_node("plan", plan_node)
graph.add_node("search_vault", search_vault_node)
graph.add_node("forge", forge_node)
graph.add_node("test", test_node)
graph.add_node("execute", execute_node)
graph.add_node("learn", learn_node)
graph.add_node("respond", respond_node)

# Edges
graph.add_edge(START, "orchestrate")
graph.add_edge("orchestrate", "plan")
graph.add_conditional_edges("plan", route_sub_task, {
    "primitive": "execute",
    "search_vault": "search_vault",
    "done": "respond"
})
graph.add_conditional_edges("search_vault", route_after_search, {
    "execute": "execute",
    "forge": "forge"
})
graph.add_edge("forge", "test")
graph.add_conditional_edges("test", route_after_test, {
    "execute": "execute",
    "retry_forge": "forge",
    "fail": "respond"
})
graph.add_conditional_edges("execute", route_after_execute, {
    "learn": "learn",
    "next_sub_task": "plan",    # loop back for next sub-task
    "respond": "respond"
})
graph.add_edge("learn", "plan")  # after learning, continue to next sub-task
graph.add_edge("respond", END)

app = graph.compile()
```

---

## File structure

```
talos-ai/
├── CLAUDE.md                        # This file
├── README.md                        # Project README for GitHub
├── pyproject.toml                   # Python package config
├── .env.example                     # Template for API keys
├── .gitignore
│
├── talos/
│   ├── __init__.py
│   ├── main.py                      # Entry point — REPL loop
│   ├── graph.py                     # LangGraph StateGraph definition + edges
│   ├── state.py                     # TalosState TypedDict
│   │
│   ├── agents/                      # Each agent = node function + system prompt
│   │   ├── __init__.py
│   │   ├── orchestrator.py          # Conversation management, routing
│   │   ├── planner.py               # Task decomposition
│   │   ├── researcher.py            # Web search + read utility (called by others)
│   │   ├── forger.py                # Tool code generation
│   │   ├── tester.py                # Tool validation
│   │   └── executor.py              # Tool execution
│   │
│   ├── primitives/                  # Built-in tools, always available
│   │   ├── __init__.py
│   │   ├── web_search.py            # Tavily wrapper
│   │   ├── web_read.py              # Jina reader wrapper
│   │   ├── file_ops.py              # file_read + file_write
│   │   ├── python_exec.py           # subprocess Python execution
│   │   ├── shell_exec.py            # subprocess shell execution
│   │   └── human_input.py           # LangGraph interrupt wrapper
│   │
│   ├── vault/                       # Skill storage
│   │   ├── __init__.py
│   │   ├── manager.py               # SkillManager class: search, register, load
│   │   ├── manifest.json            # Index of all forged tools (auto-maintained)
│   │   └── tools/                   # Forged .py files live here
│   │       └── .gitkeep
│   │
│   ├── prompts/                     # System prompts for each agent
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   ├── planner.py
│   │   ├── forger.py
│   │   └── tester.py
│   │
│   └── config/
│       ├── __init__.py
│       └── settings.py              # Load .env, model configs, timeouts
│
├── examples/
│   └── demo_queries.py              # Example queries to test the system
│
└── tests/                           # Project tests (not forged tool tests)
    ├── test_vault_manager.py
    ├── test_primitives.py
    └── test_graph_flow.py
```

---

## Build order

Build and test incrementally. Each step should be runnable before moving to the next.

### Step 1: Skeleton
- `state.py` — TalosState TypedDict
- `graph.py` — empty nodes wired together, compiles and runs with dummy data
- `main.py` — basic REPL that invokes the graph
- Verify: `python -m talos.main` starts, accepts input, graph runs through all nodes with placeholder logic

### Step 2: Primitives
- Implement all primitives in `talos/primitives/`
- Verify: each primitive works standalone (`web_search("python langgraph")` returns results)

### Step 3: Skill Manager
- `vault/manager.py` — search, register, load
- Manually create 1-2 dummy tools in `vault/tools/` and a `manifest.json`
- Verify: search finds them, load returns a callable, register adds new entries

### Step 4: Planner agent
- `agents/planner.py` + `prompts/planner.py`
- Wire into graph — should decompose queries into sub-task plans
- Verify: given "parse this CSV and find top 5 rows", returns a structured plan

### Step 5: Forger + Tester (the core loop)
- `agents/forger.py` + `agents/tester.py` + their prompts
- Wire forge→test→retry sub-graph
- Verify: given "write a function that converts JSON to YAML", it writes code, tests pass, and the tool works

### Step 6: Executor + Learn
- `agents/executor.py` — runs tools, captures results
- `learn` node — calls Skill Manager to register forged tools
- Verify: end-to-end flow — forge a tool, test it, execute it, find it in manifest.json

### Step 7: Orchestrator + multi-step
- `agents/orchestrator.py` — conversation layer, sub-task dispatch loop
- Wire the full graph with conditional edges
- Verify: "scrape this URL and save a summary" works as a 2-step task

### Step 8: Researcher integration
- `agents/researcher.py` — Tavily + Jina
- Wire into Planner and Forger
- Verify: Forger researches an API before writing integration code

### Step 9: Human-in-the-loop for API keys
- Implement interrupt flow for Tier 2 APIs
- `.env` auto-update when user provides a key
- Verify: agent asks for API key, user provides, agent continues

### Step 10: Polish
- Error handling throughout
- LangSmith tracing setup
- README for GitHub
- Example demo queries

---

## Capability boundaries

### CAN do (POC)
- Decompose multi-step queries into sub-tasks with dependency ordering
- Use primitives for web search, web reading, file I/O, code execution
- Forge new Python tools at runtime with type hints and docstrings
- Auto-generate tests and validate forged tools in subprocess sandbox
- Retry failed forges up to 3 times with error context
- Persist forged tools to disk (manifest.json + .py files)
- Reuse previously forged tools — skip forge on repeat queries
- Interactive REPL with follow-up conversation
- Discover and use free no-auth APIs autonomously
- Ask user for API keys when needed, persist them for future use
- Track tool usage count and last-used timestamps

### CANNOT do (acknowledged limitations)
- OAuth / complex auth flows (browser login, redirect URIs, token refresh)
- Docker sandboxing (subprocess with timeout only — not fully isolated)
- Semantic/vector search in vault (keyword matching only)
- Persistent conversational memory across sessions (vault persists, chat doesn't)
- Multi-agent spawning (single agent, no dynamic sub-agents)
- GUI (CLI/REPL only)
- Self-modification (can't change its own graph structure or prompts at runtime)
- Guaranteed code safety (timeout + prompt constraints, but not bulletproof)

### Deferred to future phases
- Phase 2: I/O-capable forged tools (API wrappers, scrapers, file processors)
- Phase 3: Semantic search via sentence-transformers when vault grows past 50+ tools
- Phase 3: Docker/E2B sandboxing for proper isolation
- Phase 4: MCP server integration for complex auth
- Phase 4: Web UI
- Phase 4: Multi-model routing (cheap model for planning, expensive for forging)

---

## Key LangGraph patterns used

### State updates are merges
Each node returns a partial dict — only the fields it touches. LangGraph merges it into existing state.
```python
def plan_node(state: TalosState) -> dict:
    # Only returns plan-related fields, doesn't touch messages or execution_result
    return {"plan": structured_plan, "current_sub_task": first_task}
```

### Conditional edges for routing
```python
def route_after_search(state: TalosState) -> str:
    if state.get("skill_matches"):
        return "execute"
    return "forge"
```

### Interrupt for human-in-the-loop
```python
from langgraph.types import interrupt

def handle_api_key_request(state: TalosState) -> dict:
    response = interrupt({
        "message": "I need an OpenWeatherMap API key.",
        "signup_url": "https://openweathermap.org/api",
        "instructions": "Sign up for free, copy your API key, paste it here."
    })
    save_to_dotenv("OPENWEATHER_API_KEY", response)
    return {"available_integrations": {**state["available_integrations"], "openweathermap": "OPENWEATHER_API_KEY"}}
```

### Sub-task loop
The Planner produces a list of sub-tasks. After each execute/learn cycle, the graph loops back to the Planner, which pops the next sub-task. When all sub-tasks are done, it routes to respond.

---

## Coding conventions

- Python 3.11+
- Type hints everywhere
- Docstrings on all public functions (Google style)
- `ruff` for linting and formatting
- Each agent's system prompt lives in `talos/prompts/` as a string constant
- No classes for agents — just functions that take TalosState and return partial state dicts
- Skill Manager is the exception — it's a class because it manages file I/O state
- All LLM calls go through LangChain's ChatModel interface
- Environment variables loaded via `python-dotenv`
- No print statements — use `logging` module
