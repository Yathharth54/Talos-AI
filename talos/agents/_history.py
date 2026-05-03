"""Shared helper for formatting recent conversation history into prompts.

This is what makes Talos behave statefully across turns. PydanticAI hides
this behind `message_history`; LangChain leaves it to the caller. We
manually format the last N messages into a compact string and inject it
into the Planner / ArgResolver / Orchestrator user messages so they have
context for things like "this" / "that" / "do that again."
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def format_recent_history(messages: list[BaseMessage], max_turns: int = 6) -> str:
    """Render the last `max_turns` Human/AI messages as compact dialogue.

    The MOST RECENT HumanMessage is excluded — callers handle that one
    explicitly as "the current query." We're rendering the *prior* context.

    Returns "" if there's no prior turn to show.
    """
    if not messages:
        return ""

    # Trim to the most recent N+1 (we'll drop the latest HumanMessage below).
    relevant = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    if not relevant:
        return ""

    # Drop the LAST HumanMessage if it's the trailing one — that's the current query.
    if isinstance(relevant[-1], HumanMessage):
        relevant = relevant[:-1]

    if not relevant:
        return ""

    tail = relevant[-max_turns:]
    lines: list[str] = []
    for m in tail:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        content = str(getattr(m, "content", "") or "").strip()
        if not content:
            continue
        # Compact long messages — preserves structure without blowing the prompt.
        if len(content) > 800:
            content = content[:800] + "...(truncated)"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
