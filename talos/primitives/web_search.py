"""web_search primitive — Tavily-backed search.

Concept (LangGraph/LangChain context):
- LangChain ships `TavilySearchResults` as a `Tool`-shaped wrapper meant to be
  bound into an LLM's tool-calling loop (e.g. via `bind_tools`).
- We deliberately use the raw `tavily-python` SDK here because primitives are
  *called by nodes*, not picked by an LLM. We don't want LangChain Tool
  metadata, JSON schemas, or callback overhead — just a function that returns
  a clean Python list.
- PydanticAI analogue: this is a plain helper, not an `@agent.tool`.
"""

from __future__ import annotations

from tavily import TavilyClient

from talos.config import settings


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily.

    Args:
        query: free-text search query.
        max_results: cap on results returned (Tavily default is 5).

    Returns:
        List of {title, url, content, score} dicts. Empty list on no hits.

    Raises:
        RuntimeError if TAVILY_API_KEY is missing — fail loud on misconfig.
    """
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set in environment")

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    response = client.search(query=query, max_results=max_results)
    # Tavily returns {"query": ..., "results": [...], "response_time": ...}.
    return response.get("results", [])
