"""REPL entry point. Phases 7.5 + 9: stateful + HITL for missing API keys.

Run with: `uv run python -m talos.main`
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from talos.config.logging import setup_logging
from talos.graph import app


def _drain_interrupts(final_state, config) -> dict:
    """If the run paused for HITL, prompt the user and resume — repeat
    until the graph reaches its end."""
    while "__interrupt__" in final_state:
        interrupts = final_state["__interrupt__"]
        # We always handle one interrupt at a time (the runtime serialises them).
        intr = interrupts[0]
        payload = intr.value
        msg = payload.get("message", "Need input from you:")
        print(f"\n[!] {msg}")
        if payload.get("type") == "missing_api_key":
            env_var = payload.get("env_var", "")
            tool = payload.get("tool_name", "")
            print(f"    (env var: {env_var}, for tool: {tool}; type 'skip' to abort)")
        try:
            user_value = input("    > ").strip()
        except (EOFError, KeyboardInterrupt):
            user_value = "skip"
        final_state = app.invoke(Command(resume=user_value), config=config)
    return final_state


def main() -> None:
    setup_logging()
    print("Talos AI — type a query or 'exit'.")
    thread_id = f"repl-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in {"exit", "quit"}:
            break

        final_state = app.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )
        final_state = _drain_interrupts(final_state, config)

        for msg in reversed(final_state.get("messages", [])):
            if isinstance(msg, AIMessage):
                print(f"\n{msg.content}")
                break


if __name__ == "__main__":
    main()
