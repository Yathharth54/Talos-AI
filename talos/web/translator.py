"""EventTranslator: raw LangGraph stream chunks → contract events (overview §4).

Pure: no I/O. `GraphDriver` (runner.py) feeds it every chunk of

    graph.astream(..., stream_mode=STREAM_MODES, subgraphs=True)

Each chunk is `(namespace, mode, data)`. `namespace` is `()` for the main
graph and `("forge_subgraph:<task id>",)` inside the forge sub-graph.

- "tasks": `{"id", "name", "input", "triggers"}` when a node starts (the
  finish form, with "result", is ignored). This is how a step becomes
  active before its model call returns.
- "updates": `{node: partial_state}` when a node finishes; `{"__interrupt__":
  (Interrupt, ...)}` when the graph pauses.
- "custom": `{"type": ..., "data": {...}}` from `talos.events.emit()`.
- "messages": `(message_chunk, metadata)`; only `orchestrator_out` counts.

The translator's state (strip, attempt counter, tools, answer so far) is a
JSON dict that survives a pause and an app restart. It never holds `seq`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from typing import Any

from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD
from talos.web import copy
from talos.web.board import Board, Event, new_state
from talos.web.schemas import split_signature, vault_entry

STREAM_MODES = ["updates", "custom", "messages", "tasks"]

EXEC_TOOLS = frozenset({"python_exec", "shell_exec"})
_TEST_DEF = re.compile(r"^def test_", re.M)
_ERROR_TYPE = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b")

# (needs, tool_hint) → the tool's signature text, e.g. "f(a: int) -> str".
SignatureLookup = Callable[[str, str | None], str | None]


def error_type(error: str | None) -> str:
    """`"TypeError: shift must be an int"` → `"TypeError"`; otherwise `"error"`."""
    match = _ERROR_TYPE.match(error or "")
    return match.group(1).rsplit(".", 1)[-1] if match else "error"


def attempts_phrase(n: int) -> str:
    """`1 attempt` or `N attempts`.

    Args:
        n: The number of forge attempts.

    Returns:
        The phrase used in summaries and captions.
    """
    return "1 attempt" if n == 1 else f"{n} attempts"


def _forged_sig(forged: Mapping[str, Any]) -> dict[str, str] | None:
    """The bench signature for a forged tool, or None when the Forger gave none."""
    name, signature = forged.get("name"), forged.get("signature")
    if not name or not signature:
        return None
    args, ret = split_signature(str(signature))
    return {"name": str(name), "args": args, "ret": ret}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return ""


class EventTranslator:
    """Turns stream chunks into contract events, keeping per-run UI state.

    Args:
        state: Saved state from a previous task of the same run, or None.
        signatures: Looks up a tool's signature for the strip header.
        max_attempts: Forge attempts allowed (TALOS_FORGE_MAX_RETRIES).
        timeout_s: Tester subprocess limit (TALOS_SUBPROCESS_TIMEOUT).
        prune_after: Failures in a row before a vault tool is removed.
    """

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        *,
        signatures: SignatureLookup | None = None,
        max_attempts: int = settings.FORGE_MAX_RETRIES,
        timeout_s: int = settings.SUBPROCESS_TIMEOUT,
        prune_after: int = _AUTO_PRUNE_THRESHOLD,
    ) -> None:
        self.state = state if state is not None else self.initial_state()
        self.board = Board(self.state)
        self.signatures = signatures
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.prune_after = prune_after
        self.pause: tuple[str, dict[str, Any]] | None = None

    @staticmethod
    def initial_state() -> dict[str, Any]:
        """Fresh state for a new run."""
        return {
            **new_state(),
            "plan": [],
            "index": 0,
            "attempt": 0,
            "tests_total": 0,
            "tool": None,
            "code": [],
            "pending_code": None,
            "env_vars": [],
            "pending_attempt": None,
            "test_results": [],
            "intro_pending": False,
            "exec_caption_pending": False,
            "resuming_executor": False,
            "human": "none",
            "approval": "none",
            "exec_running_line": False,
            "forge_failed": False,
            "failure": None,
            "answer": "",
            "answer_streamed": False,
        }

    # ---- public API -------------------------------------------------------------

    def feed(self, chunk: tuple[Any, str, Any] | list[Any]) -> list[Event]:
        """Translate one `(namespace, mode, data)` chunk."""
        namespace, mode, data = chunk
        inner = bool(namespace)
        if mode == "tasks":
            if isinstance(data, Mapping) and "input" in data:
                self._task_started(inner, str(data.get("name")))
        elif mode == "custom":
            if isinstance(data, Mapping):
                self._custom(str(data.get("type")), dict(data.get("data") or {}))
        elif mode == "updates":
            for node, update in (data or {}).items():
                if node == "__interrupt__":
                    self._interrupted(update)
                else:
                    self._updated(inner, node, update if isinstance(update, Mapping) else {})
        elif mode == "messages":
            message, metadata = data
            self._message(message, metadata or {})
        return self.board.drain()

    def resumed(self, kind: str, decision: str) -> list[Event]:
        """Copy for the moment the user answers a pause (before the graph resumes)."""
        self.pause = None
        b = self.board
        b.pop()
        if kind == "missing_api_key":
            env = (self.state["env_vars"] or [""])[0]
            if decision == "save":
                self.state["human"] = "saved"
                b.log(copy.LOG_CHECK_SAVED)
                b.finish("human", "done")
                b.caption(copy.CAPTION_HUMAN_SAVED.format(env=html.escape(env)))
            else:
                self.state["human"] = "skipped"
                b.log(copy.LOG_CHECK_SKIPPED)
                b.finish("human", "done", copy.LABEL_HUMAN_SKIPPED)
                b.caption(copy.CAPTION_HUMAN_SKIPPED)
            b.status(copy.STATUS_FORGING, gold=True)
            b.flow("human", "learn")
        else:
            self.state["resuming_executor"] = True
            if decision == "approve":
                self.state["approval"] = "approved"
                self.state["exec_running_line"] = True
                b.log(copy.LOG_EXEC_RUNNING, "g", caret=True)
            else:
                self.state["approval"] = "declined"
        return b.drain()

    def finish(self) -> list[Event]:
        """`answer.done` then `run.finished`, once the stream has ended normally."""
        s, b = self.state, self.board
        failure = s["failure"]
        if failure:  # the demo shows only the failure chip, even after a forge
            text = copy.CHIP_FAILED.format(tool=failure["tool"], error_type=failure["error_type"])
            chips = [{"kind": "failed", "text": text}]
        else:
            chips = [
                {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=t)} for t in s["forged"]
            ]
            chips += [
                {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=t)}
                for t in s["used"]
                if t not in s["forged"]
            ]
        b.emit("answer.done", html=html.escape(s["answer"]), note=None, chips=chips)
        summary, gold = self._summary()
        b.finished("declined" if s["approval"] == "declined" else "done", summary, gold=gold)
        return b.drain()

    # ---- tasks (a node starts) -----------------------------------------------------

    def _task_started(self, inner: bool, name: str) -> None:
        s, b = self.state, self.board
        if inner:
            if name == "forge":
                self._settle_attempt(True)
                s["attempt"] += 1
                if s["attempt"] == 1:
                    b.start("forger")
                    if s["tool"]:
                        self._forge_intro()
                    else:
                        s["intro_pending"] = True
                else:
                    s["intro_pending"] = False
                    b.finish("tester", "forge")
                    b.start("forger")
                    b.caption(
                        copy.CAPTION_FORGER_RETRY.format(n=s["attempt"], max=self.max_attempts)
                    )
                    b.log(copy.LOG_FORGE_RETRY, "g", n=s["attempt"])
            elif name == "test":
                b.finish("forger", "forge")
                b.flow("forger", "tester")
                b.start("tester")
                b.caption(
                    copy.CAPTION_TESTER.format(
                        n=s["attempt"],
                        max=self.max_attempts,
                        k=s["tests_total"],
                        timeout=self.timeout_s,
                    )
                )
                b.log(copy.LOG_TEST_RUNNING, "g", caret=True)
            return
        if name == "planner":
            b.start("planner")
            b.caption(copy.CAPTION_PLANNING)
            b.talos(copy.TALOS_PLANNING)
        elif name == "learn":
            b.start("learn")
            b.caption(copy.CAPTION_LEARN)
        elif name == "executor":
            if s["resuming_executor"]:
                s["resuming_executor"] = False
                return
            sub = self._subtask()
            tool = s["tool"] or sub.get("tool_hint") or "tool"
            b.start("executor")
            b.talos(copy.TALOS_RUNNING.format(tool=tool))
            if sub.get("tool_hint") in EXEC_TOOLS:
                s["exec_caption_pending"] = True  # paused or auto-approved decides
            else:
                b.caption(copy.CAPTION_EXECUTOR)
        elif name == "orchestrator_out":
            self._before_answer()

    # ---- custom events (facts from nodes) -------------------------------------------

    def _custom(self, type_: str, data: dict[str, Any]) -> None:
        s, b = self.state, self.board
        if type_ == "forge.code":
            # Held until the forge node's update, which carries test_code: the
            # event says how many tests this attempt has. Nothing comes between.
            s["pending_code"] = data
        elif type_ == "forge.tests":
            s["test_results"] = list(data.get("results") or [])
            b.pop()
            b.emit("forge.tests", **data)
        elif type_ == "forge.smoke":
            b.caption(copy.CAPTION_SMOKE)  # only sent when the gate ran (not skipped)
            b.emit("forge.smoke", **data)
            if data.get("passed"):
                b.log(copy.LOG_SMOKE, result=data.get("result") or "")
                self._settle_attempt(True)
            else:
                b.emit("log.line", label="smoke", text=copy.new("LOG_SMOKE_FAILED"), tone="w")
                self._settle_attempt(
                    False,
                    f"Smoke test failed: {data.get('error') or data.get('call') or 'no call'}",
                )
        elif type_ == "vault.saved":
            entry = data.get("tool") or {}
            tool = str(entry.get("name") or s["tool"] or "")
            b.finish("learn", "done")
            b.log(copy.LOG_LEARN)
            b.emit(
                "vault.saved",
                tool=vault_entry(entry, "\n".join(s["code"])).model_dump(),
                sub=data.get("sub") or copy.SAVED_SUB.format(what=tool),
            )
            b.flow("learn", "executor")
            b.add_forged(tool)
        elif type_ == "call.args":
            tool = str(data.get("tool") or "")
            if s["variant"] in ("vault", "forge"):
                b.add_used(tool)
            if s["exec_caption_pending"]:
                s["exec_caption_pending"] = False
                b.caption(copy.CAPTION_EXEC_AUTO)
            args = data.get("args") or []
            if tool in EXEC_TOOLS:
                caption = copy.ARGS_CAPTION_CODE
            elif not args:
                caption = copy.ARGS_CAPTION_NONE
            else:
                caption = copy.ARGS_CAPTION
            b.emit("call.args", **{**data, "caption": data.get("caption") or caption})
        elif type_ == "call.result":
            if s.get("exec_running_line"):
                s["exec_running_line"] = False
                b.pop()
            b.emit("call.result", **data)
            b.finish("executor", "done", "Executor")
            b.log(copy.LOG_EXEC_DONE, "w")
        elif type_ == "call.error":
            b.emit("call.error", **data)
            if data.get("when") == "declined":
                b.finish("executor", "fail", copy.LABEL_EXEC_DECLINED)
                b.log(copy.LOG_EXEC_DECLINED, "w")
                b.status(copy.STATUS_NOT_RUN)
                return
            if s.get("exec_running_line"):
                s["exec_running_line"] = False
                b.pop()
            kind = error_type(data.get("error"))
            tool = s["tool"] or self._subtask().get("tool_hint") or "tool"
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type=kind)
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            s["failure"] = {"tool": tool, "error_type": kind, "streak": None, "pruned": False}
        elif type_ == "vault.failure":
            if data.get("pruned"):
                b.log(copy.LOG_VAULT_REMOVED, prune=self.prune_after)
            else:
                b.log(copy.LOG_VAULT_STREAK, streak=data.get("streak"))
            b.emit("vault.failure", **data)
            if s["failure"] is not None:
                s["failure"]["streak"] = data.get("streak")
                s["failure"]["pruned"] = bool(data.get("pruned"))
        else:
            b.emit(type_, **data)

    def _forge_code(self, data: dict[str, Any]) -> None:
        """`forge.code` for one attempt, with the changed-line note from attempt 2 on."""
        s, b = self.state, self.board
        if data.get("tool"):
            s["tool"] = data["tool"]
        s["code"] = list(data.get("lines") or [])
        if s["intro_pending"] and s["tool"]:
            self._forge_intro()
        changed = data.get("changed")
        if int(data.get("attempt") or s["attempt"]) > 1 and changed and changed <= len(s["code"]):
            data["note"] = copy.NOTE_CHANGED_LINE.format(line=changed, n=s["attempt"])
        b.emit("forge.code", **data)

    # ---- updates (a node finished) ----------------------------------------------------

    def _updated(self, inner: bool, node: str, update: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        if inner:
            if node == "forge":
                forged = update.get("forged_tool") or {}
                s["tool"] = forged.get("name") or s["tool"]
                s["tests_total"] = len(_TEST_DEF.findall(forged.get("test_code") or ""))
                s["env_vars"] = list(forged.get("needs_env_vars") or [])
                pending = s.get("pending_code")
                if pending is not None:
                    s["pending_code"] = None
                    sig = _forged_sig(forged)
                    self._forge_code({**pending, "tests": s["tests_total"], "sig": sig})
            elif node == "test":
                self._tests_decided(update.get("test_result") or {})
            return
        if node == "planner":
            self._planned(update.get("plan") or {})
        elif node == "forge_subgraph":
            self._forge_done(update)
        elif node == "hitl_check":
            if s["human"] in ("saved", "skipped"):
                return
            if s["env_vars"]:
                b.finish("human", "skip")
                b.caption(copy.CAPTION_HUMAN_KEY_SET.format(env=html.escape(s["env_vars"][0])))
                b.log(copy.LOG_CHECK_KEY_SET)
            else:
                b.finish("human", "skip")
                b.caption(copy.CAPTION_HUMAN_SKIP)
            b.flow("human", "learn")
        elif node == "advance":
            s["index"] += 1
            b.emit("subtask.started", index=s["index"] + 1, total=len(s["plan"]))
            self._begin_subtask()
        elif node == "orchestrator_out":
            messages = update.get("messages") or []
            if messages:
                text = _content_text(getattr(messages[-1], "content", ""))
                if not s["answer_streamed"] and text:
                    b.emit("answer.delta", text=text)
                    s["answer_streamed"] = True
                s["answer"] = text or s["answer"]
            b.finish("answer", "answer")

    def _interrupted(self, interrupts: Any) -> None:
        s, b = self.state, self.board
        first = interrupts[0] if interrupts else None
        value = getattr(first, "value", first)
        if not isinstance(value, Mapping):
            return
        value = dict(value)
        kind = str(value.get("type"))
        self.pause = (kind, value)
        if kind == "missing_api_key":
            env = str(value.get("env_var") or "")
            if env:
                s["env_vars"] = [env, *[v for v in s["env_vars"] if v != env]]
            s["human"] = "waiting"
            b.start("human")
            b.caption(
                copy.CAPTION_HUMAN_WAIT.format(
                    tool=html.escape(str(value.get("tool_name") or s["tool"] or "")),
                    env=html.escape(env),
                )
            )
            b.log(copy.LOG_CHECK_WAITING, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_NEEDS_KEY)
        elif kind == "confirm_exec":
            s["approval"] = "waiting"
            s["exec_caption_pending"] = False
            b.start("executor", copy.LABEL_EXEC_WAITING)
            b.caption(copy.CAPTION_EXEC_PAUSED.format(tool=value.get("tool") or "python_exec"))
            b.log(copy.LOG_EXEC_PAUSED, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_APPROVE)

    # ---- messages (answer tokens) -------------------------------------------------------

    def _message(self, message: Any, metadata: Mapping[str, Any]) -> None:
        if metadata.get("langgraph_node") != "orchestrator_out":
            return
        s = self.state
        text = _content_text(getattr(message, "content", ""))
        if type(message).__name__.endswith("Chunk"):
            if text:
                s["answer"] += text
                s["answer_streamed"] = True
                self.board.emit("answer.delta", text=text)
        elif not s["answer_streamed"] and text:
            s["answer"] = text
            s["answer_streamed"] = True
            self.board.emit("answer.delta", text=text)

    # ---- helpers ----------------------------------------------------------------------

    def _subtask(self) -> dict[str, Any]:
        plan = self.state["plan"]
        index = self.state["index"]
        return plan[index] if 0 <= index < len(plan) else {}

    def _planned(self, plan: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        subtasks = [dict(st) for st in plan.get("sub_tasks") or []]
        s["plan"] = [
            {
                key: st.get(key)
                for key in (
                    "id",
                    "action",
                    "needs",
                    "tool_hint",
                    "keywords",
                    "depends_on",
                    "input_schema",
                    "output_schema",
                )
            }
            for st in subtasks
        ]
        s["index"] = 0
        b.emit(
            "plan.ready",
            subtasks=[
                {
                    "id": st.get("id"),
                    "action": st.get("action"),
                    "needs": st.get("needs"),
                    "tool_hint": st.get("tool_hint"),
                    "depends_on": list(st.get("depends_on") or []),
                }
                for st in subtasks
            ],
            verdict=plan.get("verdict") or "feasible",
        )
        if not subtasks or plan.get("verdict") == "infeasible":
            b.strip("chat", index=0, total=0, label=copy.LABEL_CHAT, sig=None)
            b.finish("planner", "done")
            b.log(copy.LOG_PLAN_CHAT)
            b.caption(copy.CAPTION_PLAN_CHAT)
            b.status(copy.STATUS_NONE_FORGED)
            return
        self._begin_subtask()

    def _begin_subtask(self) -> None:
        """`strip.set` for the current sub-task, then its variant's opening copy."""
        s, b = self.state, self.board
        sub = self._subtask()
        i, n = s["index"] + 1, len(s["plan"])
        needs = sub.get("needs") if sub.get("needs") in ("forge", "vault") else "primitive"
        s.update(
            attempt=0,
            tests_total=0,
            tool=sub.get("tool_hint") if needs == "vault" else None,
            code=[],
            pending_code=None,
            env_vars=[],
            pending_attempt=None,
            test_results=[],
            intro_pending=False,
            exec_caption_pending=False,
            human="none",
        )
        label = {
            "forge": copy.LABEL_FORGE,
            "vault": copy.LABEL_VAULT,
            "primitive": copy.LABEL_PRIMITIVE,
        }[needs].format(i=i, n=n)
        b.strip(needs, index=i, total=n, label=label, sig=self._sig(sub, needs))
        b.finish("planner", "done")
        first = s["index"] == 0
        tool = sub.get("tool_hint") or ""
        if first and n > 1:
            b.emit("log.line", label="plan", text=copy.new("LOG_PLAN_MULTI", n=n), tone="plain")
            b.caption(copy.new("CAPTION_PLAN_MULTI", n=n))
        if needs == "forge":
            if first and n == 1:
                b.log(copy.LOG_PLAN_FORGE)
                b.caption(copy.CAPTION_PLAN_FORGE)
            b.status(copy.STATUS_FORGING, gold=True)
            b.log(copy.LOG_VAULT_MISS)
            b.flow("planner", "forger")
        elif needs == "vault":
            if first and n == 1:
                b.log(copy.LOG_PLAN_VAULT)
                keywords = [str(k) for k in sub.get("keywords") or []][:3]
                if keywords:
                    b.caption(
                        copy.CAPTION_PLAN_VAULT_KEYWORDS.format(
                            tool=html.escape(tool), keywords=html.escape(copy.join_words(keywords))
                        )
                    )
                else:
                    b.caption(copy.CAPTION_PLAN_VAULT.format(tool=html.escape(tool)))
            b.flow("planner", "vault")
            b.finish("vault", "done")
            b.log(copy.LOG_VAULT_HIT, tool=tool)
            b.status(copy.STATUS_NONE_FORGED, tone="warm")
            b.talos(copy.TALOS_FOUND.format(tool=tool))
            b.flow("vault", "skip")
            b.flow("skip", "executor")
        else:
            if first and n == 1:
                b.log(copy.LOG_PLAN_PRIMITIVE)
                b.caption(copy.CAPTION_PLAN_PRIMITIVE)
            b.flow("planner", "primitive")
            b.finish("primitive", "done")
            b.flow("primitive", "executor")

    def _sig(self, sub: Mapping[str, Any], needs: str) -> dict[str, str] | None:
        hint = sub.get("tool_hint")
        signature = self.signatures(needs, hint) if self.signatures and hint else None
        if signature:
            args, ret = split_signature(signature)
            return {"name": str(hint), "args": args, "ret": ret}
        schema = sub.get("input_schema") or {}
        if hint and (schema or sub.get("output_schema")):
            args = ", ".join(f"{k}: {v}" for k, v in schema.items())
            return {"name": str(hint), "args": args, "ret": str(sub.get("output_schema") or "")}
        return None

    def _forge_intro(self) -> None:
        s, b = self.state, self.board
        s["intro_pending"] = False
        tool = s["tool"]
        b.talos(copy.TALOS_WRITING.format(tool=tool))
        b.caption(copy.CAPTION_FORGER_FIRST.format(tool=html.escape(tool)))
        b.log(copy.LOG_FORGE_FIRST, "g", tool=tool)

    def _tests_decided(self, result: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        results = s["test_results"] or list(result.get("results") or [])
        total = len(results) or int(result.get("n_total") or 0) or s["tests_total"]
        passed = sum(1 for r in results if r.get("passed"))
        if result.get("passed"):
            b.log(copy.LOG_TEST_PASSED, "g", total=total)
            s["pending_attempt"] = copy.DETAIL_TESTS_PASSED.format(total=total)
            return
        failing = next((r for r in results if not r.get("passed")), None)
        if failing is not None:
            detail = f"{failing.get('name')}\n{failing.get('why') or ''}".rstrip()
        elif result.get("timed_out"):
            detail = str(result.get("error") or f"Timed out after {self.timeout_s} seconds.")
        else:
            detail = str(result.get("error") or "The tests did not run.")
        retrying = s["attempt"] < self.max_attempts
        if retrying:
            b.log(copy.LOG_TEST_RETRYING, "g", passed=passed, total=total)
        else:
            b.emit(
                "log.line",
                label="test",
                text=copy.new("LOG_TEST_FAILED", passed=passed, total=total),
                tone="g",
            )
        b.sub(failing.get("name") if failing is not None else detail.splitlines()[0])
        b.emit("forge.attempt", attempt=s["attempt"], ok=False, detail=detail)
        if retrying:
            b.talos(
                copy.TALOS_RETRYING
                if s["attempt"] == 1
                else copy.new("TALOS_RETRYING_N", n=s["attempt"])
            )

    def _settle_attempt(self, ok: bool, detail: str | None = None) -> None:
        """Emit the pending `forge.attempt` for an attempt whose tests passed."""
        pending = self.state["pending_attempt"]
        if pending is None:
            return
        self.state["pending_attempt"] = None
        self.board.emit(
            "forge.attempt", attempt=self.state["attempt"], ok=ok, detail=detail or pending
        )

    def _forge_done(self, update: Mapping[str, Any]) -> None:
        s, b = self.state, self.board
        test = update.get("test_result") or {}
        smoke = update.get("smoke_result") or {"passed": True}
        ok = bool(test.get("passed")) and bool(smoke.get("passed"))
        detail = None
        if not ok:
            detail = "Smoke test failed"
            if smoke.get("error") and test.get("passed"):
                detail = f"Smoke test failed: {smoke['error']}"
        self._settle_attempt(ok, detail)
        if ok:
            b.finish("tester", "forge")
            b.flow("tester", "human")
            return
        s["forge_failed"] = True
        b.mark_failed()
        b.finish("tester", "fail")
        b.caption(copy.new("CAPTION_FORGE_GAVE_UP", max=self.max_attempts))
        b.emit(
            "log.line",
            label="forge",
            text=copy.new("LOG_FORGE_GAVE_UP", n=s["attempt"]),
            tone="w",
        )

    def _before_answer(self) -> None:
        """Final captions and the flow into Answer (orchestrator_out started)."""
        s, b = self.state, self.board
        if s["variant"] == "chat":
            b.flow("planner", "answer")
            b.start("answer")
            return
        b.flow("executor", "answer")
        b.start("answer")
        if s["approval"] == "declined":
            b.caption(copy.CAPTION_DECLINED)
        elif s["failure"] or s["forge_failed"]:
            b.caption(copy.CAPTION_FAILED)
        elif s["forged"]:
            if len(s["forged"]) > 1:
                b.status(copy.new("SUMMARY_FORGED_MANY", k=len(s["forged"])), gold=True)
            else:
                b.status(copy.STATUS_ONE_FORGED, gold=True)
            if s["human"] == "saved":
                b.caption(
                    copy.new("CAPTION_DONE_FORGED_KEY", attempts=attempts_phrase(s["attempt"]))
                )
            elif s["attempt"] == 1:
                b.caption(copy.new("CAPTION_DONE_FORGED_ONE"))
            else:
                b.caption(copy.CAPTION_DONE_FORGED.format(attempts=s["attempt"]))
        elif s["variant"] == "vault":
            b.caption(copy.CAPTION_DONE_VAULT)
        else:
            b.status(copy.STATUS_NONE_FORGED)
            b.caption(copy.CAPTION_DONE_PRIMITIVE)

    def _summary(self) -> tuple[str, bool]:
        s = self.state
        failure = s["failure"]
        if s["approval"] == "declined":
            return copy.SUMMARY_DECLINED, False
        if failure and failure.get("streak"):
            if failure.get("pruned"):
                return copy.SUMMARY_FAILED_PRUNED, False
            return copy.SUMMARY_FAILED_STREAK.format(streak=failure["streak"]), False
        if failure or s["forge_failed"]:
            return copy.SUMMARY_FAILED, False
        if s["forged"]:
            if len(s["forged"]) > 1:
                return copy.new("SUMMARY_FORGED_MANY", k=len(s["forged"])), True
            if s["human"] == "saved":
                return copy.SUMMARY_FORGED_KEY, True
            if s["attempt"] == 1:
                return copy.new("SUMMARY_FORGED_ONE"), True
            return copy.SUMMARY_FORGED.format(attempts=s["attempt"]), True
        if s["variant"] == "chat":
            return copy.SUMMARY_CHAT, False
        if s["variant"] == "vault":
            return copy.SUMMARY_REUSED, False
        if s["approval"] == "approved":
            return copy.SUMMARY_PRIMITIVE_APPROVED, False
        return copy.SUMMARY_PRIMITIVE, False
