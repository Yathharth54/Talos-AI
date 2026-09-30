"""A scripted Driver for RunManager tests: the query picks the behaviour."""

from __future__ import annotations

import asyncio
from typing import Any

from talos.web.board import Board, new_state
from talos.web.runner import Pause, Resume

CONFIRM = {
    "type": "confirm_exec",
    "tool": "python_exec",
    "preview": "print(1)",
    "args": [],
    "kwargs": {"code": "print(1)"},
    "message": "Talos wants to run python_exec. Allow it? [y/N]",
}
KEY = {
    "type": "missing_api_key",
    "env_var": "OPENWEATHERMAP_API_KEY",
    "tool_name": "get_current_temperature",
    "message": "needs a key",
}


class ScriptDriver:
    """Queries: "pause" (confirm_exec), "key" (missing_api_key), "block" (never
    ends until cancelled), "boom" (raises), anything else finishes at once."""

    def __init__(self) -> None:
        self.resumes: list[Resume] = []
        self.started = asyncio.Event()

    def initial_state(self) -> dict[str, Any]:
        return new_state()

    async def run(self, state, *, query, thread_id, resume):
        b = Board(state)
        if resume is None:
            b.strip("primitive", index=1, total=1, label="Sub-task 1 of 1", sig=None)
            b.start("planner")
            for event in b.drain():
                yield event
            self.started.set()
            if query == "pause":
                yield Pause("confirm_exec", dict(CONFIRM))
                return
            if query == "key":
                yield Pause("missing_api_key", dict(KEY))
                return
            if query == "block":
                await asyncio.Event().wait()
            if query == "boom":
                raise RuntimeError("kaboom")
        else:
            self.resumes.append(resume)
        b.finish("planner", "done")
        b.add_used("caesar_cipher")
        b.emit("answer.done", html="ok", note=None, chips=[])
        b.finished("done", "Built-in")
        for event in b.drain():
            yield event
