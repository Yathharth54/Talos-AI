"""Single factory for every LLM client in Talos.

All nodes talk to OpenRouter through its OpenAI-compatible API, so
`ChatOpenAI` pointed at `OPENROUTER_BASE_URL` covers every model it serves.
Swap models with `TALOS_MODEL` in `.env`.
"""

from __future__ import annotations

from typing import Any

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
        default_headers={"X-Title": "Talos AI"},
    )


def make_structured_model(schema: type, temperature: float) -> Any:
    """Build a client that returns instances of `schema`.

    Uses `method="function_calling"` rather than strict json_schema: our
    schemas have open-ended types (`dict[str, Any]`, `list[Any]`) that strict
    mode rejects, and tool calling is the most portable path across the
    providers OpenRouter routes to.
    """
    return make_chat_model(temperature).with_structured_output(schema, method="function_calling")
