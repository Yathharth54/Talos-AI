"""REPL entry point.

Phase 1: just proves the graph is wired. Reads a line, invokes, prints state.
The real conversational loop lands in Phase 7 with the orchestrator.

Run with: `uv run python -m talos.main`
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from talos.graph import app


def main() -> None:
    print("Talos AI — Phase 1 skeleton REPL. Type a query, or 'exit'.")
    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in {"exit", "quit"}:
            break

        # `.invoke()` runs the graph synchronously to completion and returns
        # the final merged state. PydanticAI analogue: `agent.run_sync(prompt)`.
        # `.stream()` would yield per-node updates instead — useful later for
        # showing live progress in the REPL.
        final_state = app.invoke({"messages": [HumanMessage(content=user_input)]})

        print(f"  visited:     {final_state.get('visited')}")
        print(f"  plan:        {final_state.get('plan')}")
        print(f"  exec result: {final_state.get('execution_result')}")


if __name__ == "__main__":
    main()
