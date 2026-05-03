"""Researcher — the Forger's web-research utility.

This is the FIRST place we use a LangChain prebuilt: `create_react_agent`.

LangGraph concept: prebuilt ReAct agent.
- LangChain ships `from langgraph.prebuilt import create_react_agent`.
- Give it a model + a list of tools + a system prompt; you get back a
  compiled graph that does the classic ReAct loop:
      model thinks → calls a tool → observes result → repeats → answers.
- This is the SAME shape as PydanticAI's `Agent(model, tools=[...])` + `.run()`.
- We use it here because "research a topic by searching and reading the web"
  is a textbook ReAct task: the LLM should freely decide what to search for,
  what URL to follow, when it has enough context. We don't want to pre-script that.

Why we DIDN'T use create_react_agent for Forger / Planner / Executor:
- Forger has structural rules (max 3 retries, validate via tester) that we
  don't want the LLM to override. Hand-rolled graph wins there.
- Planner has structural rules (must emit ordered sub-tasks). Same.
- Researcher has NO structural rules — it just needs to "find out about X".
  ReAct fits perfectly.

PydanticAI parallel: `Agent(model, tools=[search_tool, read_tool])`.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from talos.config import settings
from talos.primitives.web_read import web_read as _web_read
from talos.primitives.web_search import web_search as _web_search


# Wrap primitives as LangChain Tool objects so the ReAct agent can pick them.
# `@tool` introspects the function signature + docstring to build the JSON
# schema the LLM sees. This is the FIRST time we wrap things as Tools —
# everywhere else they're called directly.

@tool
def search_web(query: str) -> list[dict]:
    """Search the web for a free-text query. Returns up to 5 results, each
    with title, url, and a short content snippet. Use this to find what
    APIs / sites exist for a topic before reading specific URLs."""
    return _web_search(query, max_results=5)


@tool
def read_url(url: str) -> str:
    """Fetch any public URL and return its content as clean markdown. Use
    after search_web finds promising URLs. Good for reading API docs or
    structured pages. Returns at most a few thousand characters."""
    text = _web_read(url)
    if len(text) > 4000:
        text = text[:4000] + "\n...(truncated)"
    return text


_RESEARCHER_PROMPT = """\
You are Talos AI's Researcher. You help by gathering concrete, actionable
information from the web — usually about APIs, data formats, or how to
solve a specific programming problem.

Your output is fed into another agent that will write Python code. So:
1. Prefer FREE, no-auth APIs when they exist (open-meteo, wikipedia, ip-api,
   exchangerate-api). Note explicitly when a service requires a key.
2. When you find an API, capture: base URL, key endpoint(s), exactly which
   query parameters matter, and an example response shape.
3. Be terse. Bullet points beat prose.
4. Don't over-search: 2-4 tool calls is plenty for most tasks.
5. If you can't find a good answer in 4-5 tool calls, stop and say so —
   don't loop.
"""


def _make_react_agent() -> Any:
    """Build the ReAct agent. Module-level factory so tests can patch it."""
    return create_react_agent(
        model=f"openai:{settings.OPENAI_MODEL}",
        tools=[search_web, read_url],
        prompt=_RESEARCHER_PROMPT,
    )


def research(query: str, max_iterations: int = 8) -> str:
    """Run the researcher on a query and return the assistant's final answer.

    Args:
        query: free-text research question.
        max_iterations: cap on the ReAct loop's recursion (each
            tool-call + observe pair is roughly 2 iterations).

    Returns:
        The final assistant message content as a string.
    """
    if not settings.OPENAI_API_KEY:
        return "(researcher unavailable: no OPENAI_API_KEY set)"

    agent = _make_react_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"recursion_limit": max_iterations},
    )
    # ReAct agents return state with .messages. Last AIMessage = the answer.
    msgs = result.get("messages", [])
    for msg in reversed(msgs):
        if msg.__class__.__name__ == "AIMessage":
            content = getattr(msg, "content", "")
            if content:
                return str(content)
    return ""


# ---- heuristic: should the Forger research before writing? ----------------

# Keywords that suggest external knowledge would help. Cheap regex scan; no
# LLM call. If any matches, we research; otherwise skip and save the cost.
_RESEARCH_TRIGGERS = re.compile(
    r"\b(api|endpoint|http|https|url|scrape|scraping|fetch|"
    r"weather|stock|crypto|currency|exchange|geolocate|geocode|"
    r"wikipedia|github|reddit|youtube|twitter|news|"
    r"openai|anthropic|gemini|"
    r"download|upload|webhook|rss|atom)\b",
    re.IGNORECASE,
)


def should_research(task_description: str) -> bool:
    """Return True if the task likely benefits from web research."""
    return bool(_RESEARCH_TRIGGERS.search(task_description or ""))
