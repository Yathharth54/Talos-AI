"""Custom run events for the web app's event stream (overview spec §4.4).

Nodes call `emit()` to report facts that are not in their state updates:
the Forger's code for an attempt, per-test results, the smoke call, the
Executor's resolved arguments and result, vault saves and failures.

LangGraph concept: inside a node, `get_stream_writer()` returns a function
that pushes a chunk to any `stream_mode="custom"` consumer. Under `invoke()`
or a stream without "custom" it is a no-op, and outside a graph run it
raises RuntimeError. `emit()` hides both cases, so the CLI and the unit
tests behave exactly as before.

Chunk shape seen by a consumer: `{"type": event_type, "data": {...}}`.
"""

from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def emit(event_type: str, /, **data: Any) -> None:
    """Send a custom stream event if a stream is listening; otherwise do nothing.

    `event_type` is positional-only so event data may itself contain a
    `type` key (e.g. `call.result` carries the result's type name).

    Args:
        event_type: A contract event type, e.g. "forge.code".
        **data: The event's data fields, JSON-serialisable.

    Example:
        >>> emit("forge.smoke", call="add(a=1, b=2)", result="3", passed=True)
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return  # not inside a graph run (plain function call, unit test)
    writer({"type": event_type, "data": data})
