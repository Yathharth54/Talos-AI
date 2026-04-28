"""human_input primitive — pause the graph and ask the user a question.

LangGraph concept (the new one to learn here):
- `interrupt(payload)` is a special call that *pauses graph execution mid-node*.
  When the runtime hits it, control returns to whoever called `app.invoke()`
  / `app.stream()` with a special "interrupt" event carrying `payload`.
- The caller (REPL) shows the prompt to the user, collects their response,
  then resumes the graph by invoking again with `Command(resume=user_value)`.
- Inside the node, `interrupt()` *returns* `user_value` — so from the node's
  point of view it looks like a normal blocking function call.
- For interrupt+resume to work, the graph must be compiled with a
  `checkpointer` (an in-memory or persistent store of state per `thread_id`).
  We'll add that in Phase 9 when we wire the real HITL flow.

PydanticAI analogue: nothing exact. Closest is `agent.run_stream()` with
deferred tool execution where the host app fulfils a tool call manually.

Phase 2 scope: just the wrapper. We test it raises a `GraphInterrupt`
when called outside a checkpointed context — that proves the import path
and contract are correct without needing the full HITL machinery yet.
"""

from __future__ import annotations

from langgraph.types import interrupt


def human_input(message: str, **context: object) -> str:
    """Ask the user something and return their answer.

    Args:
        message: prompt shown to the user.
        **context: any extra fields (e.g. signup_url, instructions) the
            REPL may want to render alongside the prompt.

    Returns:
        The user's response (whatever the REPL passes via `Command(resume=...)`).

    Behaviour:
        Calling this from inside a graph node pauses the graph. Calling it
        outside a graph context raises `GraphInterrupt` immediately — that's
        the runtime telling you "I have nothing to pause; you called this
        in the wrong place."
    """
    payload = {"message": message, **context}
    answer = interrupt(payload)
    return str(answer)
