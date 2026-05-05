"""Planner agent — decomposes a user query into an ordered list of sub-tasks.

LangChain pattern reused from the Forger: structured output via Pydantic
schema. Same `_make_llm()` factory seam so tests can swap the LLM.

Vault-awareness:
- Before calling the LLM, we read the manifest and inject its contents into
  the user message. This lets the Planner pick `needs="vault"` for sub-tasks
  whose work matches an existing forged tool.
- We do NOT pre-filter by keywords here — the LLM picks. Reason: the Planner
  hasn't decomposed yet, so it doesn't know what keywords to search for.
  When vault grows past ~50 tools we'll switch to a two-pass approach.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from talos.agents._history import format_recent_history
from talos.config import settings
from talos.prompts.planner import (
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_message,
    format_vault_summary,
)
from talos.state import TalosState
from talos.vault.manager import SkillManager


class SubTask(BaseModel):
    id: int = Field(description="1-indexed position in the plan")
    action: str = Field(description="natural-language description of the work")
    needs: Literal["primitive", "vault", "forge"] = Field(
        description="how this sub-task should execute"
    )
    tool_hint: str | None = Field(
        default=None,
        description="primitive name if needs=primitive; vault skill name if needs=vault; null otherwise",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="3-8 lowercase tokens; used for vault search and Forger guidance",
    )
    input_description: str = Field(
        default="",
        description="how this sub-task gets its input (literal value vs output of an upstream sub-task)",
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="upstream sub-task IDs whose output feeds this one",
    )

    # --- Typed contract (required for needs='forge'; ignored otherwise) ---
    # When present these define the FUNCTION SIGNATURE the Forger must match,
    # AND the deterministic kwargs the Executor will pass at invoke time.
    # No more freeform LLM arg-resolution for forged tools.
    input_schema: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Forge only: maps parameter NAME to a Python type string "
            "(e.g. 'str', 'int', 'float', 'list', 'dict', 'list[dict]'). "
            "The Forger MUST produce a function with exactly these params and types. "
            "Empty for primitive/vault sub-tasks."
        ),
    )
    output_schema: str = Field(
        default="",
        description=(
            "Forge only: the function's return type as a Python type string "
            "(e.g. 'dict', 'float', 'list[dict]'). Empty for primitive/vault."
        ),
    )
    param_bindings: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Forge only: maps each parameter NAME to its concrete value. "
            "Each value is either a literal (str/int/float/bool/list/dict) "
            "OR the string '__SUBTASK_OUTPUT_<N>__' to receive the full output "
            "of upstream sub-task N (optionally with [idx]/[\"key\"] accessors, "
            "e.g. '__SUBTASK_OUTPUT_1__[\"price\"]'). Every key in input_schema "
            "MUST appear in param_bindings."
        ),
    )


class Plan(BaseModel):
    sub_tasks: list[SubTask] = Field(description="ordered list of sub-tasks; may be empty")
    verdict: Literal["feasible", "infeasible"] = Field(
        default="feasible",
        description=(
            "'infeasible' if the query fundamentally cannot be answered with the "
            "available primitives + reasonable forging. 'feasible' otherwise. "
            "When 'infeasible', sub_tasks should be empty."
        ),
    )
    verdict_category: Literal[
        "physics-impossible", "missing-resource", "out-of-scope",
        "underspecified", "",
    ] = Field(
        default="",
        description=(
            "When verdict='infeasible', categorise:\n"
            "  - physics-impossible: predicting the future, solving the halting problem, etc.\n"
            "  - missing-resource: relies on a tool/library/API that doesn't exist.\n"
            "  - out-of-scope: outside Talos's capability boundaries.\n"
            "  - underspecified: needs clarification before any plan is possible.\n"
            "Empty when verdict='feasible'."
        ),
    )
    verdict_reason: str = Field(
        default="",
        description=(
            "When verdict='infeasible', a short user-facing explanation of why. "
            "This is what we tell the user. Empty when verdict='feasible'."
        ),
    )


def _make_llm() -> Any:
    """Structured-output ChatOpenAI client for Plan. Test seam."""
    base = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.1,  # decomposition wants determinism more than the Forger does
    )
    return base.with_structured_output(Plan)


def _get_skill_manager() -> SkillManager:
    """SkillManager factory; test seam in case we want to inject a fake."""
    return SkillManager()


def planner_node(state: TalosState) -> dict:
    """Read the latest user message, produce a plan, write it to state.

    Reads:  messages (last HumanMessage)
    Writes: plan, current_sub_task (= sub_tasks[0] or None), sub_task_results=[]
    """
    query = _last_user_text(state)

    mgr = _get_skill_manager()
    vault_summary = format_vault_summary(mgr.all())
    history = format_recent_history(state.get("messages") or [])

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=build_planner_user_message(query, vault_summary, history)),
    ]
    plan: Plan = _make_llm().invoke(messages)  # type: ignore[assignment]

    # No vault-name validation here: a plan may legitimately reference a tool
    # that an *earlier* sub-task in the same plan will forge. The Executor
    # records a clean failure if a vault hint really doesn't resolve at run
    # time, so we trust the Planner's labels and let truth surface at execute.

    sub_tasks_dump = [st.model_dump() for st in plan.sub_tasks]
    return {
        "plan": {
            "sub_tasks": sub_tasks_dump,
            "verdict": plan.verdict,
            "verdict_category": plan.verdict_category,
            "verdict_reason": plan.verdict_reason,
        },
        "current_sub_task": sub_tasks_dump[0] if sub_tasks_dump else None,
        "sub_task_results": [],
    }


def _last_user_text(state: TalosState) -> str:
    """Pull the most recent HumanMessage content out of state.messages."""
    for msg in reversed(state.get("messages", []) or []):
        if msg.__class__.__name__ == "HumanMessage":
            return str(getattr(msg, "content", "") or "")
    return ""
