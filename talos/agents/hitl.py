"""HITL (human-in-the-loop) — pause the graph and ask for missing API keys.

Concept (LangGraph):
- `interrupt(payload)` pauses the graph mid-node. The runtime returns
  control to the caller (REPL or test) with the payload visible.
- The caller resumes by re-invoking with `Command(resume=user_value)`.
- Inside the node, `interrupt()` returns whatever the caller resumed with.
- For interrupt+resume to work, the graph must be compiled with a
  `checkpointer`. Our main `app` is — see talos/graph.py.

Design choice for env-var detection:
- The Forger declares `needs_env_vars` in its structured output.
- The `hitl_check_node` runs after the forge sub-graph reports success
  (test passed). It iterates the declared vars; for each missing one, it
  calls `interrupt()` with a payload describing what's needed.
- On resume, the user-supplied value is written to `.env` so it persists
  across sessions, and into `os.environ` so the just-forged tool can use
  it immediately.
"""

from __future__ import annotations

import os
from pathlib import Path

from langgraph.types import interrupt

from talos.config import settings
from talos.state import TalosState

DOTENV_PATH: Path = settings.PROJECT_ROOT / ".env"


def _persist_env_var(name: str, value: str) -> None:
    """Write/update a key in the .env file AND in os.environ.

    Why not python-dotenv's `set_key`: it works fine, but reading + rewriting
    by hand keeps formatting predictable (we control whitespace and ordering)
    and makes the function trivially testable with a tmp .env path.
    """
    os.environ[name] = value
    if not DOTENV_PATH.exists():
        DOTENV_PATH.write_text(f"{name}={value}\n", encoding="utf-8")
        return
    lines = DOTENV_PATH.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith(f"{name}="):
            out.append(f"{name}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{name}={value}")
    DOTENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def hitl_check_node(state: TalosState) -> dict:
    """Pause the graph for any missing env vars the forged tool needs.

    No-op if the forged_tool declared no `needs_env_vars` or all are set.
    Otherwise, calls `interrupt()` once per missing var; the user supplies
    values via `Command(resume=...)` from the REPL.
    """
    forged = state.get("forged_tool") or {}
    needed: list[str] = forged.get("needs_env_vars") or []
    missing = [n for n in needed if not os.environ.get(n)]
    if not missing:
        return {}

    integrations = dict(state.get("available_integrations") or {})
    for var in missing:
        # Each interrupt pauses the graph until resumed; once resumed, the
        # call returns the user's value and execution continues.
        value = interrupt({
            "type": "missing_api_key",
            "env_var": var,
            "tool_name": forged.get("name"),
            "message": (
                f"The forged tool '{forged.get('name')}' needs the env var "
                f"{var}. Please paste its value (or 'skip' to abort)."
            ),
        })
        if not value or str(value).strip().lower() == "skip":
            # User declined → don't write; the next executor call will fail
            # cleanly because the env var is still unset.
            continue
        _persist_env_var(var, str(value).strip())
        integrations[var] = var

    return {"available_integrations": integrations}
