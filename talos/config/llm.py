"""Single factory for every LLM client in Talos.

All nodes talk to OpenRouter through its OpenAI-compatible API, so
`ChatOpenAI` pointed at `OPENROUTER_BASE_URL` covers every model it serves.
Swap models with `TALOS_MODEL` in `.env`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from talos.config import settings


def make_chat_model(temperature: float) -> ChatOpenAI:
    """Build a chat client for the configured OpenRouter model.

    Args:
        temperature: sampling temperature for this node.

    Returns:
        A LangChain ChatOpenAI client routed through OpenRouter.
    """
    return ChatOpenAI(
        model=settings.TALOS_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        temperature=temperature,
        timeout=settings.LLM_TIMEOUT,
        max_retries=2,
        default_headers={"X-Title": "Talos AI"},
    )


class StructuredOutputError(RuntimeError):
    """The model failed to return a valid instance of the requested schema."""


class _RetryingStructured:
    """Invoke a structured-output runnable; retry once if it yields nothing.

    Models that don't reliably call tools sometimes answer in prose instead;
    LangChain's function_calling parser then returns None (or raises on bad
    tool args). One retry with an explicit nudge fixes most of those; after
    that we raise a clear error for the caller to record.
    """

    def __init__(self, runnable: Any, schema_name: str) -> None:
        self._runnable = runnable
        self._schema_name = schema_name

    def invoke(self, messages: list[Any]) -> Any:
        try:
            result = self._runnable.invoke(messages)
            first_error = None
        except Exception as e:  # noqa: BLE001 — parse errors are retryable
            result, first_error = None, e
        if result is not None:
            return result

        nudge = HumanMessage(content=(
            f"You must respond by calling the `{self._schema_name}` tool with "
            "valid arguments. Do not reply in plain text."
        ))
        try:
            result = self._runnable.invoke([*messages, nudge])
        except Exception as e:  # noqa: BLE001
            raise StructuredOutputError(
                f"model returned no valid {self._schema_name}: {type(e).__name__}: {e}"
            ) from e
        if result is None:
            detail = f" (first attempt: {first_error})" if first_error else ""
            raise StructuredOutputError(f"model returned no valid {self._schema_name}{detail}")
        return result


def make_structured_model(schema: type, temperature: float) -> Any:
    """Build a client that returns instances of `schema`.

    Uses `method="function_calling"` rather than strict json_schema: our
    schemas have open-ended types (`dict[str, Any]`, `list[Any]`) that strict
    mode rejects, and tool calling is the most portable path across the
    providers OpenRouter routes to.

    Raises StructuredOutputError from `.invoke()` if two attempts fail.
    """
    runnable = make_chat_model(temperature).with_structured_output(
        schema, method="function_calling"
    )
    return _RetryingStructured(runnable, schema.__name__)
