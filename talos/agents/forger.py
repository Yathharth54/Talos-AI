"""Forger agent — calls an LLM with structured output to produce a forged tool.

LangChain concept: structured output.
- `ChatOpenAI` is LangChain's OpenAI client. You build it once with model
  name + key, then call `.invoke(messages)` to get a response.
- `.with_structured_output(SchemaClass)` returns a NEW client where invoke()
  yields a typed Python object instead of a raw text message. Under the
  hood LangChain wires up OpenAI's tool-calling or JSON mode, validates
  the response against the schema, and gives you a parsed instance.
- The schema can be a Pydantic model OR a TypedDict. Pydantic is more
  expressive (Field descriptions teach the LLM what each field means).

PydanticAI analogue: `Agent(..., result_type=ForgedTool)`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from talos.agents.researcher import research, should_research
from talos.config import settings
from talos.prompts.forger import FORGER_SYSTEM_PROMPT, build_retry_context
from talos.state import TalosState


class ForgedTool(BaseModel):
    """The Forger's structured output schema.

    Field descriptions reach the LLM (LangChain serialises them into the
    JSON Schema it sends to OpenAI), so they double as inline guidance.
    """

    name: str = Field(description="snake_case identifier, also the Python function name")
    description: str = Field(description="one-sentence summary of what the tool does")
    keywords: list[str] = Field(description="3-8 lowercase tokens for keyword search")
    signature: str = Field(description="human-readable function signature")
    code: str = Field(description="full source of the .py file")
    test_code: str = Field(description="full source of the pytest-style test functions")
    needs_env_vars: list[str] = Field(
        default_factory=list,
        description=(
            "Names of environment variables this tool reads via os.environ. "
            "List each one (e.g. 'OPENWEATHER_API_KEY'). The system uses "
            "this to ask the user for missing keys before running the tool."
        ),
    )


def _make_llm() -> Any:
    """Build a structured-output ChatOpenAI client.

    Factored out so tests can monkeypatch it with a fake.
    """
    base = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.2,  # low but not zero — code gen tolerates a bit of variation
    )
    return base.with_structured_output(ForgedTool)


def forger_node(state: TalosState) -> dict:
    """LangGraph node: forge a tool for the current sub-task.

    Reads from state:
        current_sub_task: the sub-task spec (must have `action` or similar)
        forged_tool:      previous attempt (if retrying)
        test_result:      previous failure (if retrying)
        retry_count:      attempt number, 0-indexed

    Writes to state:
        forged_tool: the new ForgedTool as a dict
        retry_count: incremented (0 on first attempt → 1 after this call)
    """
    sub_task = state.get("current_sub_task") or {}
    task_description = (
        sub_task.get("action")
        or sub_task.get("description")
        or "No task description provided"
    )

    messages: list[Any] = [SystemMessage(content=FORGER_SYSTEM_PROMPT)]

    retry_count = state.get("retry_count", 0)
    previous = state.get("forged_tool")
    previous_test = state.get("test_result") or {}

    # On the FIRST attempt only, optionally call the Researcher to gather
    # concrete API/site context. We don't research on retries — by then we
    # already have research from the first attempt and can rely on the
    # error trace to fix the bug.
    research_block = ""
    if retry_count == 0 and should_research(task_description):
        research_block = research(task_description) or ""

    contract_block = _format_contract(sub_task)

    previous_smoke = state.get("smoke_result") or {}

    if retry_count > 0 and previous:
        error_summary = _summarise_failure(previous_test, previous_smoke)
        retry_msg = build_retry_context(
            previous_code=previous.get("code", ""),
            previous_test_code=previous.get("test_code", ""),
            error_summary=error_summary,
            attempt=retry_count,
        )
        body = f"Task: {task_description}"
        if contract_block:
            body += f"\n\n{contract_block}"
        body += f"\n\n{retry_msg}"
        messages.append(HumanMessage(content=body))
    else:
        body = f"Task: {task_description}"
        if contract_block:
            body += f"\n\n{contract_block}"
        if research_block:
            body += f"\n\n--- Research notes from the Researcher ---\n{research_block}"
        messages.append(HumanMessage(content=body))

    llm = _make_llm()
    forged: ForgedTool = llm.invoke(messages)  # type: ignore[assignment]

    return {
        "forged_tool": forged.model_dump(),
        "retry_count": retry_count + 1,
    }


def _format_contract(sub_task: dict) -> str:
    """Render the Planner's typed contract (if present) as a block the Forger
    must match. Empty string if no schema was emitted (primitive/vault path
    or older planner output)."""
    schema = sub_task.get("input_schema") or {}
    out = sub_task.get("output_schema") or ""
    if not schema and not out:
        return ""
    params = ", ".join(f"{k}: {v}" for k, v in schema.items())
    sig = f"({params}) -> {out or 'Any'}"
    return (
        "--- TYPED CONTRACT (must match exactly) ---\n"
        f"Required signature: your_function{sig}\n"
        "Rules:\n"
        "  - Function parameters must use these EXACT names and types — no extras, no renames.\n"
        "  - Function return type must match output_schema.\n"
        "  - Do NOT add api_key/token/url/etc. as parameters; read env vars internally.\n"
        "  - Tests you write must call the function with these param names as kwargs."
    )


def _summarise_failure(test_result: dict, smoke_result: dict | None = None) -> str:
    """Compact Tester + smoke results into something the LLM can act on.

    A smoke failure means the unit tests passed (against mocks) but invoking
    the function with the real planner-provided arguments raised. The Forger
    needs to know which class of failure to fix.
    """
    smoke_result = smoke_result or {}
    if smoke_result and not smoke_result.get("passed") and not smoke_result.get("skipped"):
        # Unit tests passed; runtime call failed. Surface this prominently.
        return (
            "RUNTIME SMOKE FAILURE — unit tests passed against mocks, but "
            "calling the function with the real planner-provided arguments "
            "raised:\n"
            f"  {smoke_result.get('error', 'unknown error')}\n\n"
            "Fix the function so it handles the real input shape. Common "
            "causes: missing/extra fields in API response, wrong field name, "
            "type mismatch, KeyError on a dict path that didn't exist."
        )
    if not test_result:
        return "Unknown failure."
    if test_result.get("timed_out"):
        return "Tests timed out — likely an infinite loop. Make the function terminate."
    parts: list[str] = []
    if test_result.get("error"):
        parts.append(f"Parsed error: {test_result['error']}")
    if test_result.get("stderr"):
        parts.append(f"stderr:\n{test_result['stderr']}")
    if test_result.get("stdout"):
        parts.append(f"stdout:\n{test_result['stdout']}")
    return "\n\n".join(parts) if parts else "Tests failed without output."
