"""A run's UI state (strip, steps, outcome) and the contract events that change it.

Both event sources use this: `EventTranslator` (real graph) and the fake
graph's scripted flows. Every method appends contract events to
`board.events`; the caller drains them. The state is a plain JSON dict,
saved on the run row as `translator_state`, so a paused run can be resumed
by a new process and a stopped run can mark its active steps.

`seq` is never kept here: `repo.append_event` allocates it.
"""

from __future__ import annotations

import re
from typing import Any

from talos.web import copy

Event = tuple[str, dict[str, Any]]

# Strip variants (overview §4.2): step keys and their default labels.
STRIPS: dict[str, list[tuple[str, str]]] = {
    "forge": [
        ("planner", "Planner"),
        ("forger", "Forger"),
        ("tester", "Tester"),
        ("human", "Human check"),
        ("learn", "Learn"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "vault": [
        ("planner", "Planner"),
        ("vault", "Vault tool"),
        ("skip", "Forge sub-graph skipped"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "primitive": [
        ("planner", "Planner"),
        ("primitive", "Primitive"),
        ("executor", "Executor"),
        ("answer", "Answer"),
    ],
    "chat": [("planner", "Planner"), ("answer", "Answer")],
}


def new_state() -> dict[str, Any]:
    """The empty board state for a new run."""
    return {
        "variant": None,
        "steps": {},
        "forged": [],
        "used": [],
        "failed": False,
        # The target of the last `link.flow` until a step starts or the target finishes:
        # the step being handed the run. It may have run before (a retry's Tester).
        "next": None,
    }


class Board:
    """Builds contract events and keeps the UI state they imply.

    Args:
        state: A dict from `new_state()` (or a saved copy). Mutated in place.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = state if state is not None else new_state()
        for key, value in new_state().items():
            self.state.setdefault(key, value)
        self.events: list[Event] = []

    # ---- plumbing -----------------------------------------------------------

    def drain(self) -> list[Event]:
        """Return and forget the events built so far."""
        out, self.events = self.events, []
        return out

    def emit(self, type_: str, **data: Any) -> None:
        """Append one contract event."""
        self.events.append((type_, data))

    # ---- strip ----------------------------------------------------------------

    def strip(
        self,
        variant: str,
        *,
        index: int,
        total: int,
        label: str,
        sig: dict[str, str] | None,
    ) -> None:
        """Reset the strip to `variant` (`strip.set`). `skip` starts as `skip`."""
        self.state["variant"] = variant
        self.state["next"] = None
        self.state["steps"] = {
            key: {"state": "skip" if key == "skip" else "pending", "label": name}
            for key, name in STRIPS[variant]
        }
        self.emit(
            "strip.set",
            variant=variant,
            subtask={"index": index, "total": total, "label": label},
            sig=sig,
        )

    def start(self, step: str, label: str | None = None) -> None:
        """`node.started`: the step becomes active."""
        self._set(step, "active", label)
        self.state["next"] = None
        self.emit("node.started", step=step, **({"label": label} if label else {}))

    def finish(self, step: str, status: str, label: str | None = None) -> None:
        """`node.finished` with status done, forge, skip, fail, answer or stopped."""
        self._set(step, status, label)
        if self.state.get("next") == step:  # finished without starting (a skipped check)
            self.state["next"] = None
        self.emit("node.finished", step=step, status=status, **({"label": label} if label else {}))

    def flow(self, source: str, target: str) -> None:
        """`link.flow`: a gold packet travels from one step to the next."""
        self.state["next"] = target
        self.emit("link.flow", **{"from": source, "to": target})

    def _set(self, step: str, state: str, label: str | None) -> None:
        entry = self.state["steps"].setdefault(step, {"state": "pending", "label": step})
        entry["state"] = state
        if label:
            entry["label"] = label

    # ---- narration ---------------------------------------------------------------

    def caption(self, html: str) -> None:
        """`caption`: the text under the graph strip.

        Args:
            html: Caption HTML from `copy` (user text already escaped).
        """
        self.emit("caption", html=html)

    def log(
        self,
        line: tuple[str, str],
        tone: str = "plain",
        *,
        caret: bool = False,
        **fields: Any,
    ) -> None:
        """`log.line` from a `(label, text)` template in `copy`."""
        label, text = line
        data: dict[str, Any] = {"label": label, "text": text.format(**fields), "tone": tone}
        if caret:
            data["caret"] = True
        self.emit("log.line", **data)

    def sub(self, text: str) -> None:
        """An indented sub line under the previous log line (e.g. a failing test)."""
        self.emit("log.line", label="", text=text, tone="sub")

    def pop(self) -> None:
        """`log.pop`: drop the last (transient "running") log line."""
        self.emit("log.pop")

    def status(self, text: str, *, gold: bool = False, tone: str = "") -> None:
        """`log.status`: the run-log caption and frame tone."""
        self.emit("log.status", text=text, gold=gold, tone=tone)

    def talos(self, text: str) -> None:
        """`talos.status`: the "working on it" text next to the orbit."""
        self.emit("talos.status", text=text)

    # ---- outcome ------------------------------------------------------------------

    def add_forged(self, tool: str) -> None:
        """Record a tool this run forged (once each, in order).

        Args:
            tool: The tool name; empty names are ignored.
        """
        if tool and tool not in self.state["forged"]:
            self.state["forged"].append(tool)

    def add_used(self, tool: str) -> None:
        """Record a tool this run used (once each, in order).

        Args:
            tool: The tool name; empty names are ignored.
        """
        if tool and tool not in self.state["used"]:
            self.state["used"].append(tool)

    def mark_failed(self) -> None:
        """Mark the run as having a failure (stored as `runs.failed`)."""
        self.state["failed"] = True

    def stop(self) -> None:
        """What Stop does to the board (spec 02 §6): active steps → stopped, log, caption.

        Between two steps (`node.finished`, `link.flow`, then `node.started`) no step is
        active. Stop then marks the step the run was being handed to, the target of that
        `link.flow`, as stopped: in the demo that hand-over is one synchronous move, so
        its Stop finds the next step already active.
        """
        steps = self.state["steps"]
        stopping = [step for step, entry in steps.items() if entry["state"] == "active"]
        nxt = self.state.get("next")
        if not stopping and nxt in steps:
            stopping = [nxt]
        for step in stopping:
            base = re.sub(r", .*$", "", steps[step]["label"])
            self.finish(step, "stopped", base + copy.LABEL_STOPPED_SUFFIX)
        self.log(copy.LOG_STOP, "w")
        self.status(copy.STATUS_STOPPED)
        self.caption(copy.CAPTION_STOPPED)

    def finished(self, status: str, summary: str, *, gold: bool = False) -> None:
        """`run.finished`: always the last event of a run."""
        self.emit(
            "run.finished",
            status=status,
            summary=summary,
            summary_gold=gold,
            forged=list(self.state["forged"]),
            used=list(self.state["used"]),
        )
