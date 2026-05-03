"""Example queries that exercise different paths through the system.

Run any of these by piping into the REPL:
    echo "<query>" | uv run python -m talos.main

Or run them all programmatically with this script:
    uv run python -m examples.demo_queries

Each example below has a short note on what it tests so you know what
to look for in the LangSmith trace.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, HumanMessage

from talos.config.logging import setup_logging
from talos.graph import app

DEMOS: list[tuple[str, str]] = [
    (
        "primitives only",
        # Should produce a 2-step plan: web_read + file_write.
        # No forging — vault stays empty.
        "Read https://example.com and save the body to /tmp/talos_demo_example.txt",
    ),
    (
        "forge a pure-python tool",
        # Planner labels needs=forge for the 'reverse'. Forger writes
        # reverse_string + tests; Tester validates; Learn registers; Executor runs it.
        "Reverse the string 'self-evolving' and tell me the result.",
    ),
    (
        "research-driven forge",
        # 'API' keyword triggers the Researcher heuristic before forging.
        # The Forger gets free-API context and should pick open-meteo or similar.
        "Use a free weather API to get the current temperature in Mumbai.",
    ),
]


def main() -> None:
    setup_logging()
    for label, query in DEMOS:
        print(f"\n=== {label} ===")
        print(f"> {query}")
        config = {"configurable": {"thread_id": f"demo-{uuid.uuid4()}"}}
        final = app.invoke({"messages": [HumanMessage(content=query)]}, config=config)
        for msg in reversed(final.get("messages", [])):
            if isinstance(msg, AIMessage):
                print(f"\n{msg.content}\n")
                break


if __name__ == "__main__":
    main()
