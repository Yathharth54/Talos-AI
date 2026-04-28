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

    if retry_count > 0 and previous:
        # Retry: include previous attempt + error trace in the user message.
        error_summary = _summarise_failure(previous_test)
        retry_msg = build_retry_context(
            previous_code=previous.get("code", ""),
            previous_test_code=previous.get("test_code", ""),
            error_summary=error_summary,
            attempt=retry_count,
        )
        messages.append(HumanMessage(content=f"Task: {task_description}\n\n{retry_msg}"))
    else:
        messages.append(HumanMessage(content=f"Task: {task_description}"))

    llm = _make_llm()
    forged: ForgedTool = llm.invoke(messages)  # type: ignore[assignment]

    return {
        "forged_tool": forged.model_dump(),
        "retry_count": retry_count + 1,
    }


def _summarise_failure(test_result: dict) -> str:
    """Compact a Tester result into something the LLM can act on."""
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
