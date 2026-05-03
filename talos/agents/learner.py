"""Learn — register a successfully-forged tool into the vault.

No LLM. Pure plumbing. Reads the forged_tool from state, writes to disk
via SkillManager.

When this runs (set up by the main graph in Phase 7):
- After the forge sub-graph completes successfully (test_result.passed)
- Before the next sub-task is processed

If forge_tool is absent or test_result didn't pass, this node is a no-op.
That keeps it safe to put on the main graph's success path without
guarding every edge.
"""

from __future__ import annotations

from talos.agents.forger import ForgedTool
from talos.state import TalosState
from talos.vault.manager import SkillManager


def _get_skill_manager() -> SkillManager:
    return SkillManager()


def learn_node(state: TalosState) -> dict:
    forged = state.get("forged_tool")
    test = state.get("test_result") or {}
    if not forged or not test.get("passed"):
        return {}

    # Coerce to ForgedTool so we get validation; then back to dict for storage.
    try:
        validated = ForgedTool(**forged).model_dump()
    except Exception as e:  # noqa: BLE001 — bad shape shouldn't crash the graph
        return {"execution_result": f"learn skipped: invalid forged_tool ({e})"}

    entry = {
        "name": validated["name"],
        "description": validated["description"],
        "keywords": validated["keywords"],
        "function": validated["name"],
        "signature": validated["signature"],
    }
    mgr = _get_skill_manager()
    mgr.register(entry, validated["code"])
    return {}
