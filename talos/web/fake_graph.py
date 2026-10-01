"""TALOS_FAKE_GRAPH=1: the demo's scripted runs as contract events, no model calls.

`FakeDriver` replaces `GraphDriver`. It routes with the demo's `classify()`
and replays its flows (`flowCaesar`, `executeCaesar`, `flowPython`,
`flowWeather`, `flowChat`, `flowUnknown`, with `planner`, `forgeTool`,
`humanCheck` and `learn`), emitting the same events, in the same order, as
`EventTranslator` does for the equivalent real run. Values are the demo's:
the Caesar retry on line 48, its five tests, the word-number shift failure,
`print(sum(range(1, 101)))`, the OpenWeatherMap key.

- Pauses are real: the run waits, and `/resume` continues it (also after
  an app restart, because the flow's position lives in the saved state).
- It really updates a vault: a temporary copy of the vault folder
  (`make_fake_vault`), so the Vault page shows forged tools and failures.
- A saved API key is only remembered as "set" in memory. Its value never
  reaches this module, and nothing is written to `.env`.

Vault list questions fall through to the "not in this demo" flow.
"""

from __future__ import annotations

import ast
import asyncio
import copy as _copy
import html
import json
import operator
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD, SkillManager
from talos.web import copy
from talos.web.board import Board, new_state
from talos.web.demo_sources import (
    CAESAR,
    CAESAR_BAD_LINE,
    CAESAR_BAD_SOURCE,
    CAESAR_SOURCE,
    WEATHER,
    WEATHER_SOURCE,
)
from talos.web.naming import classify, weather_city
from talos.web.runner import Emitted, Pause, Resume
from talos.web.schemas import vault_entry

# Scripted values from the demo (docs/superpowers/specs/reference/workbench-demo).
CAESAR_TESTS = [
    "test_encrypt_shifts_forward",
    "test_decrypt_reverses_encrypt",
    "test_preserves_case_and_spaces",
    "test_wraps_past_z",
    "test_rejects_unknown_mode",
]
CAESAR_FAIL_WHY = "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'"
CAESAR_RETRY_NOTE = "Line 48 is new in attempt 2. Decrypt now shifts backwards instead of forwards."
CAESAR_SMOKE_CALL = 'caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")'
CAESAR_SAVED_SUB = (
    "Next time a request needs a Caesar cipher, Talos skips forging and goes straight to Execute."
)
CAESAR_TYPE_ERROR = "TypeError: shift must be an int, got str"
WEATHER_TESTS = [
    "test_reads_temperature_from_response",
    "test_raises_when_key_missing",
    "test_raises_on_unknown_city",
]
WEATHER_NO_KEY = "RuntimeError: OPENWEATHERMAP_API_KEY is not set"
PYTHON_DEFAULT = "print(sum(range(1, 101)))"
PYTHON_SIG = {"name": "python_exec", "args": "code: str, timeout: int | None = None", "ret": "dict"}
NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
}  # fmt: skip
DEMO_TOOLS = (CAESAR["name"], WEATHER["name"])


def make_fake_vault(source: Path | None = None) -> tuple[SkillManager, Path]:
    """Copy the vault into a temp folder, minus the two tools the demo forges live.

    Args:
        source: Vault folder to copy (default `settings.VAULT_DIR`).

    Returns:
        A SkillManager on the copy, and the temp folder (delete it on shutdown).
    """
    source = source or settings.VAULT_DIR
    root = Path(tempfile.mkdtemp(prefix="talos_fake_vault_"))
    if source.is_dir():
        shutil.copytree(source, root, dirs_exist_ok=True)
    vault = SkillManager(vault_dir=root)
    for name in DEMO_TOOLS:
        vault.remove(name)
    return vault, root


# ---- the demo's helpers, ported ---------------------------------------------------


def caesar(text: str, shift: int, mode: str) -> str:
    """The demo's `caesar()`: rotate ASCII letters, keep everything else."""
    k = (-shift if mode == "decrypt" else shift) % 26
    out = []
    for c in text:
        if "A" <= c <= "Z":
            out.append(chr((ord(c) - 65 + k) % 26 + 65))
        elif "a" <= c <= "z":
            out.append(chr((ord(c) - 97 + k) % 26 + 97))
        else:
            out.append(c)
    return "".join(out)


def py_str(value: str) -> str:
    """The demo's `pyStr`: a Python-style single-quoted repr."""
    return "'" + value.replace("'", "\\'") + "'"


def parse_caesar(text: str) -> dict[str, Any]:
    """The demo's `parseCaesar`: quoted text, mode, and a numeric or word shift."""
    quoted = re.search(r"[\"“]([^\"”]+)[\"”]", text)
    before = text[: quoted.start()] if quoted else text
    verbs = list(re.finditer(r"\b(en|de)(?:crypt|code)", before, re.I))
    mode = "encrypt"
    if verbs:
        mode = "decrypt" if verbs[-1].group(1).lower() == "de" else "encrypt"
    shift, word = 7, None
    number = re.search(r"shift(?:\s+of)?\s*(?:=|:)?\s*(-?\d+)", text, re.I)
    named = re.search(r"shift(?:\s+of)?\s+([a-z]+)", text, re.I)
    if number:
        shift = int(number.group(1))
    elif named and not re.fullmatch(r"of|to|by", named.group(1), re.I):
        word = named.group(1).lower()
    default = "AHSVZ HNLUA" if mode == "decrypt" else "TALOS AGENT"
    return {
        "text": quoted.group(1) if quoted else default,
        "shift": shift,
        "word": word,
        "mode": mode,
    }


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _arith(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_arith(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _arith(node.left), _arith(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise ValueError("exponent too large")
        result = _OPS[type(node.op)](left, right)
        if isinstance(result, int) and result.bit_length() > 4096:
            raise ValueError("result too large")
        return result
    raise ValueError("not arithmetic")


def run_python(code: str) -> str | None:
    """The demo's `runPython`: only `print(...)` of a literal, sum(range) or arithmetic."""
    match = re.fullmatch(r"print\((.*)\)", code.strip(), re.S)
    if not match:
        return None
    inner = match.group(1).strip()
    summed = re.fullmatch(r"sum\(range\((-?\d+)\s*,\s*(-?\d+)\)\)", inner)
    if summed:
        return str(sum(range(int(summed.group(1)), int(summed.group(2)))))
    literal = re.fullmatch(r"([\"'])(.*)\1", inner, re.S)
    if literal:
        return literal.group(2)
    if re.fullmatch(r"[\d\s+\-*/().%]+", inner):
        try:
            value = _arith(ast.parse(inner, mode="eval").body)
            if isinstance(value, float):
                if value != value or value in (float("inf"), float("-inf")):
                    return None
                return str(int(value)) if value.is_integer() else repr(value)
            return str(value)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
            return None
    return None


def python_code(query: str) -> str:
    """The code in a query: `backticks`, else after a colon, else the demo default."""
    match = re.search(r"`([^`]+)`", query) or re.search(r":\s*(.+)$", query)
    return match.group(1).strip() if match else PYTHON_DEFAULT


def _plain(html_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", html_text))


# ---- the driver -------------------------------------------------------------------------


class _PacedBoard(Board):
    """A Board that keeps a copy of the state as it was after each event."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__(state)
        self.snapshots: list[dict[str, Any]] = []

    def emit(self, type_: str, **data: Any) -> None:
        super().emit(type_, **data)
        self.snapshots.append(_copy.deepcopy(self.state))


class FakeDriver:
    """Scripted runs (see module doc).

    Args:
        vault: The vault the fake forges into (use `make_fake_vault()`).
        event_delay_ms: E2E only (`TALOS_FAKE_EVENT_DELAY_MS`): wait this long
            before each event, and keep the board state at the last event
            sent, so Stop and a reload meet a run that is still going. The
            vault writes still happen when the flow is planned, up front.
    """

    def __init__(self, vault: SkillManager, *, event_delay_ms: int = 0) -> None:
        self.vault = vault
        self.saved_keys: set[str] = set()
        self.event_delay_s = max(0, event_delay_ms) / 1000

    def initial_state(self) -> dict[str, Any]:
        return {**new_state(), "flow": None, "phase": None, "p": {}, "attempts": 0}

    async def run(
        self, state: dict[str, Any], *, query: str, thread_id: str, resume: Resume | None
    ) -> AsyncIterator[Emitted | Pause]:
        paced = self.event_delay_s > 0
        b = _PacedBoard(state) if paced else Board(state)
        if resume is None:
            kind = classify(query)
            state["flow"] = kind if kind in ("caesar", "python", "weather", "chat") else "unknown"
            pause = getattr(self, f"_flow_{state['flow']}")(b, query)
        else:
            pause = self._resume(b, resume)
        events = b.drain()
        if not paced:
            for event in events:
                yield event
        else:
            end = _copy.deepcopy(state)
            snapshots = b.snapshots  # type: ignore[attr-defined]
            for event, snapshot in zip(events, snapshots, strict=True):
                await asyncio.sleep(self.event_delay_s)
                state.clear()
                state.update(snapshot)
                yield event
            state.clear()
            state.update(end)
        if pause is not None:
            yield pause

    def _resume(self, b: Board, resume: Resume) -> Pause | None:
        state = b.state
        b.pop()
        if state["phase"] == "approve":
            if resume.decision == "approve":
                b.log(copy.LOG_EXEC_RUNNING, "g", caret=True)
                return self._run_code(b, approved=True)
            return self._declined(b)
        # missing_api_key
        env = WEATHER["env"]
        if resume.decision == "save":
            self.saved_keys.add(env)
            b.log(copy.LOG_CHECK_SAVED)
            b.finish("human", "done")
            b.caption(copy.CAPTION_HUMAN_SAVED.format(env=env))
        else:
            b.log(copy.LOG_CHECK_SKIPPED)
            b.finish("human", "done", copy.LABEL_HUMAN_SKIPPED)
            b.caption(copy.CAPTION_HUMAN_SKIPPED)
        b.status(copy.STATUS_FORGING, gold=True)
        b.flow("human", "learn")
        self._learn(b, WEATHER, WEATHER_SOURCE, copy.SAVED_SUB_KEY)
        self._execute_weather(b)
        return None

    # ---- shared steps (the demo's planner, forgeTool, humanCheck, learn) -------------------

    def _planner(
        self,
        b: Board,
        *,
        variant: str,
        needs: str | None,
        tool_hint: str | None,
        label: str,
        sig: dict[str, str] | None,
        log_line: tuple[str, str],
        caption: str,
    ) -> None:
        b.start("planner")
        b.caption(copy.CAPTION_PLANNING)
        b.talos(copy.TALOS_PLANNING)
        subtasks = []
        if needs:
            subtasks = [
                {"id": 1, "action": label, "needs": needs, "tool_hint": tool_hint, "depends_on": []}
            ]
        b.emit("plan.ready", subtasks=subtasks, verdict="feasible")
        total = 1 if needs else 0
        b.strip(variant, index=total, total=total, label=label, sig=sig)
        b.finish("planner", "done")
        b.log(log_line)
        b.caption(caption)

    def _forge(
        self,
        b: Board,
        meta: dict[str, Any],
        attempts: list[tuple[str, int | None, str | None]],
        tests: list[str],
        fail_index: int,
        fail_why: str,
        smoke: tuple[str, str] | None,
    ) -> None:
        tool = meta["name"]
        b.status(copy.STATUS_FORGING, gold=True)
        b.log(copy.LOG_VAULT_MISS)
        b.flow("planner", "forger")
        total = len(tests)
        for a, (source, changed, note) in enumerate(attempts):
            n = a + 1
            if a == 0:
                b.start("forger")
                b.talos(copy.TALOS_WRITING.format(tool=tool))
                b.caption(copy.CAPTION_FORGER_FIRST.format(tool=tool))
                b.log(copy.LOG_FORGE_FIRST, "g", tool=tool)
            else:
                b.finish("tester", "forge")
                b.start("forger")
                b.caption(copy.CAPTION_FORGER_RETRY.format(n=n, max=settings.FORGE_MAX_RETRIES))
                b.log(copy.LOG_FORGE_RETRY, "g", n=n)
            b.emit(
                "forge.code",
                tool=tool,
                attempt=n,
                file=f"{tool}.py",
                lines=source.split("\n"),
                changed=changed,
                note=note,
                tests=total,
            )
            b.finish("forger", "forge")
            b.flow("forger", "tester")
            b.start("tester")
            b.caption(
                copy.CAPTION_TESTER.format(
                    n=n,
                    max=settings.FORGE_MAX_RETRIES,
                    k=total,
                    timeout=settings.SUBPROCESS_TIMEOUT,
                )
            )
            b.log(copy.LOG_TEST_RUNNING, "g", caret=True)
            fail = a == 0 and fail_index >= 0 and len(attempts) > 1
            results = [
                {
                    "name": name,
                    "passed": not (fail and i == fail_index),
                    "why": fail_why if fail and i == fail_index else None,
                }
                for i, name in enumerate(tests)
            ]
            b.pop()
            b.emit("forge.tests", tool=tool, attempt=n, results=results)
            if fail:
                b.log(copy.LOG_TEST_RETRYING, "g", passed=total - 1, total=total)
                b.sub(tests[fail_index])
                b.emit(
                    "forge.attempt", attempt=n, ok=False, detail=f"{tests[fail_index]}\n{fail_why}"
                )
                b.talos(copy.TALOS_RETRYING)
            else:
                b.log(copy.LOG_TEST_PASSED, "g", total=total)
        if smoke is not None:
            b.caption(copy.CAPTION_SMOKE)
            b.emit("forge.smoke", call=smoke[0], result=smoke[1], passed=True)
            b.log(copy.LOG_SMOKE, result=smoke[1])
        b.emit(
            "forge.attempt",
            attempt=len(attempts),
            ok=True,
            detail=copy.DETAIL_TESTS_PASSED.format(total=total),
        )
        b.state["attempts"] = len(attempts)
        b.finish("tester", "forge")
        b.flow("tester", "human")

    def _human(self, b: Board, meta: dict[str, Any]) -> Pause | None:
        env = meta.get("env")
        if not env:
            b.finish("human", "skip")
            b.caption(copy.CAPTION_HUMAN_SKIP)
            b.flow("human", "learn")
            return None
        if env in self.saved_keys:
            b.finish("human", "skip")
            b.caption(copy.CAPTION_HUMAN_KEY_SET.format(env=env))
            b.log(copy.LOG_CHECK_KEY_SET)
            b.flow("human", "learn")
            return None
        b.start("human")
        b.caption(copy.CAPTION_HUMAN_WAIT.format(tool=meta["name"], env=env))
        b.log(copy.LOG_CHECK_WAITING, "g", caret=True)
        b.status(copy.STATUS_WAITING, gold=True)
        b.talos(copy.TALOS_NEEDS_KEY)
        b.state["phase"] = "key"
        return Pause(
            "missing_api_key",
            {
                "type": "missing_api_key",
                "env_var": env,
                "tool_name": meta["name"],
                "message": f"The forged tool '{meta['name']}' needs the env var {env}.",
            },
        )

    def _learn(self, b: Board, meta: dict[str, Any], source: str, sub: str) -> None:
        b.start("learn")
        b.caption(copy.CAPTION_LEARN)
        saved = self.vault.register(
            {
                "name": meta["name"],
                "function": meta["name"],
                "description": meta["description"],
                "keywords": list(meta["keywords"]),
                "signature": f"{meta['name']}({meta['args']}) -> {meta['ret']}",
            },
            source + "\n",
        )
        b.finish("learn", "done")
        b.log(copy.LOG_LEARN)
        b.emit("vault.saved", tool=vault_entry(saved, source).model_dump(), sub=sub)
        b.flow("learn", "executor")
        b.add_forged(meta["name"])

    def _answer(
        self,
        b: Board,
        html_text: str,
        note: str | None,
        chips: list[dict[str, str]],
        *,
        status: str,
        summary: str,
        gold: bool = False,
    ) -> None:
        b.emit("answer.delta", text=_plain(html_text))
        b.finish("answer", "answer")
        b.emit("answer.done", html=html_text, note=note, chips=chips)
        b.finished(status, summary, gold=gold)

    def _vault_hit(self, b: Board, tool: str) -> None:
        b.flow("planner", "vault")
        b.finish("vault", "done")
        b.log(copy.LOG_VAULT_HIT, tool=tool)
        b.status(copy.STATUS_NONE_FORGED, tone="warm")
        b.talos(copy.TALOS_FOUND.format(tool=tool))
        b.flow("vault", "skip")
        b.flow("skip", "executor")

    def _vault_failure(self, b: Board, tool: str, error: str) -> dict[str, Any]:
        before = self.vault.get(tool) or {}
        pruned = self.vault.record_failure(tool, reason=error)
        streak = int(before.get("consecutive_failures", 0)) + 1
        if pruned:
            b.log(copy.LOG_VAULT_REMOVED, prune=_AUTO_PRUNE_THRESHOLD)
        else:
            b.log(copy.LOG_VAULT_STREAK, streak=streak)
        b.emit("vault.failure", tool=tool, streak=streak, pruned=pruned, error=error)
        return {"streak": streak, "pruned": pruned}

    # ---- flows -------------------------------------------------------------------------------

    def _flow_caesar(self, b: Board, query: str) -> Pause | None:
        p = parse_caesar(query)
        b.state["p"] = p
        sig = {"name": CAESAR["name"], "args": CAESAR["args"], "ret": CAESAR["ret"]}
        if self.vault.get(CAESAR["name"]) is None:
            self._planner(
                b,
                variant="forge",
                needs="forge",
                tool_hint=None,
                label=copy.LABEL_FORGE.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_FORGE,
                caption=copy.CAPTION_PLAN_FORGE,
            )
            self._forge(
                b,
                CAESAR,
                [
                    (CAESAR_BAD_SOURCE, None, None),
                    (CAESAR_SOURCE, CAESAR_BAD_LINE, CAESAR_RETRY_NOTE),
                ],
                CAESAR_TESTS,
                1,
                CAESAR_FAIL_WHY,
                (CAESAR_SMOKE_CALL, "'AHSVZ HNLUA'"),
            )
            self._human(b, CAESAR)
            self._learn(b, CAESAR, CAESAR_SOURCE, CAESAR_SAVED_SUB)
            self._execute_caesar(b, p, after_forge=True)
        else:
            self._planner(
                b,
                variant="vault",
                needs="vault",
                tool_hint=CAESAR["name"],
                label=copy.LABEL_VAULT.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_VAULT,
                caption=copy.CAPTION_PLAN_VAULT_KEYWORDS.format(
                    tool=CAESAR["name"], keywords=copy.join_words(["caesar", "cipher", p["mode"]])
                ),
            )
            self._vault_hit(b, CAESAR["name"])
            self._execute_caesar(b, p, after_forge=False)
        return None

    def _execute_caesar(self, b: Board, p: dict[str, Any], *, after_forge: bool) -> None:
        tool = CAESAR["name"]
        b.add_used(tool)
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool=tool))
        b.caption(copy.CAPTION_EXECUTOR)
        word = p["word"]
        shift_repr = json.dumps(word) if word else str(p["shift"])
        b.emit(
            "call.args",
            tool=tool,
            args=[
                ["text", json.dumps(p["text"]), False],
                ["shift", shift_repr, bool(word)],
                ["mode", json.dumps(p["mode"]), False],
            ],
            caption=copy.ARGS_CAPTION,
        )
        if word:
            b.emit("call.error", error=CAESAR_TYPE_ERROR, when="run")
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type="TypeError")
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            health = self._vault_failure(b, tool, CAESAR_TYPE_ERROR)
            b.flow("executor", "answer")
            b.start("answer")
            b.caption(copy.CAPTION_FAILED)
            digit = NUM_WORDS.get(word)
            summary = (
                copy.SUMMARY_FAILED_PRUNED
                if health["pruned"]
                else copy.SUMMARY_FAILED_STREAK.format(streak=health["streak"])
            )
            self._answer(
                b,
                copy.ANSWER_CAESAR_FAILED.format(mode=p["mode"], word=html.escape(word)),
                copy.NOTE_RETRY_DIGIT.format(digit=digit)
                if digit is not None
                else copy.NOTE_RETRY_NUMBER,
                [
                    {
                        "kind": "failed",
                        "text": copy.CHIP_FAILED.format(tool=tool, error_type="TypeError"),
                    }
                ],
                status="done",
                summary=summary,
            )
            return
        out = caesar(p["text"], p["shift"], p["mode"])
        self.vault.record_usage(tool)
        b.emit("call.result", repr=py_str(out), type="str", small=False)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE, "w")
        b.flow("executor", "answer")
        b.start("answer")
        if after_forge:
            attempts = b.state["attempts"]
            b.status(copy.STATUS_ONE_FORGED, gold=True)
            b.caption(copy.CAPTION_DONE_FORGED.format(attempts=attempts))
            summary, gold = copy.SUMMARY_FORGED.format(attempts=attempts), True
        else:
            b.caption(copy.CAPTION_DONE_VAULT)
            summary, gold = copy.SUMMARY_REUSED, False
        if p["mode"] == "encrypt":
            answer = copy.ANSWER_ENCRYPTED.format(
                text=html.escape(p["text"]), shift=p["shift"], out=html.escape(out)
            )
            note = copy.NOTE_ENCRYPT_TOO
        else:
            answer = copy.ANSWER_DECRYPTED.format(out=html.escape(out))
            note = copy.NOTE_DECRYPT_TOO
        chip = (
            {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=tool)}
            if after_forge
            else {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=tool)}
        )
        self._answer(
            b,
            answer,
            note if after_forge else None,
            [chip],
            status="done",
            summary=summary,
            gold=gold,
        )

    def _flow_python(self, b: Board, query: str) -> Pause | None:
        code = python_code(query)
        b.state["p"] = {"code": code}
        self._planner(
            b,
            variant="primitive",
            needs="primitive",
            tool_hint="python_exec",
            label=copy.LABEL_PRIMITIVE.format(i=1, n=1),
            sig=PYTHON_SIG,
            log_line=copy.LOG_PLAN_PRIMITIVE,
            caption=copy.CAPTION_PLAN_PRIMITIVE,
        )
        b.flow("planner", "primitive")
        b.finish("primitive", "done")
        b.flow("primitive", "executor")
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool="python_exec"))
        if not settings.auto_approve_exec():
            b.start("executor", copy.LABEL_EXEC_WAITING)
            b.caption(copy.CAPTION_EXEC_PAUSED.format(tool="python_exec"))
            b.log(copy.LOG_EXEC_PAUSED, "g", caret=True)
            b.status(copy.STATUS_WAITING, gold=True)
            b.talos(copy.TALOS_APPROVE)
            b.state["phase"] = "approve"
            return Pause(
                "confirm_exec",
                {
                    "type": "confirm_exec",
                    "tool": "python_exec",
                    "preview": code,
                    "args": [],
                    "kwargs": {"code": code},
                    "message": "Talos wants to run python_exec. Allow it? [y/N]",
                },
            )
        b.caption(copy.CAPTION_EXEC_AUTO)
        return self._run_code(b, approved=False)

    def _run_code(self, b: Board, *, approved: bool) -> None:
        code = b.state["p"]["code"]
        b.emit(
            "call.args",
            tool="python_exec",
            args=[["code", json.dumps(code), False]],
            caption=copy.ARGS_CAPTION_CODE,
        )
        if approved:
            b.pop()
        out = run_python(code)
        if out is None:
            b.emit("call.result", repr=copy.RESULT_PYTHON_UNSUPPORTED, type="", small=True)
        else:
            b.emit("call.result", repr=out, type="stdout", small=False)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE, "w")
        b.flow("executor", "answer")
        b.start("answer")
        b.status(copy.STATUS_NONE_FORGED)
        b.caption(copy.CAPTION_DONE_PRIMITIVE)
        answer = (
            copy.ANSWER_PYTHON_UNSUPPORTED
            if out is None
            else copy.ANSWER_PYTHON.format(out=html.escape(out))
        )
        summary = copy.SUMMARY_PRIMITIVE_APPROVED if approved else copy.SUMMARY_PRIMITIVE
        self._answer(b, answer, None, [], status="done", summary=summary)

    def _declined(self, b: Board) -> None:
        b.emit("call.error", error="declined by user", when="declined")
        b.finish("executor", "fail", copy.LABEL_EXEC_DECLINED)
        b.log(copy.LOG_EXEC_DECLINED, "w")
        b.status(copy.STATUS_NOT_RUN)
        b.flow("executor", "answer")
        b.start("answer")
        b.caption(copy.CAPTION_DECLINED)
        self._answer(
            b,
            copy.ANSWER_DECLINED,
            copy.NOTE_DECLINED,
            [],
            status="declined",
            summary=copy.SUMMARY_DECLINED,
        )

    def _flow_weather(self, b: Board, query: str) -> Pause | None:
        b.state["p"] = {"city": weather_city(query)}
        tool = WEATHER["name"]
        sig = {"name": tool, "args": WEATHER["args"], "ret": WEATHER["ret"]}
        if self.vault.get(tool) is None:
            self._planner(
                b,
                variant="forge",
                needs="forge",
                tool_hint=None,
                label=copy.LABEL_FORGE.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_FORGE,
                caption=copy.CAPTION_PLAN_FORGE_WEATHER,
            )
            self._forge(b, WEATHER, [(WEATHER_SOURCE, None, None)], WEATHER_TESTS, -1, "", None)
            pause = self._human(b, WEATHER)
            if pause is not None:
                return pause
            self._learn(b, WEATHER, WEATHER_SOURCE, copy.SAVED_SUB_KEY)
        else:
            self._planner(
                b,
                variant="vault",
                needs="vault",
                tool_hint=tool,
                label=copy.LABEL_VAULT.format(i=1, n=1),
                sig=sig,
                log_line=copy.LOG_PLAN_VAULT,
                caption=copy.CAPTION_PLAN_VAULT.format(tool=tool),
            )
            self._vault_hit(b, tool)
        self._execute_weather(b)
        return None

    def _execute_weather(self, b: Board) -> None:
        tool, env = WEATHER["name"], WEATHER["env"]
        city = b.state["p"]["city"]
        forged = tool in b.state["forged"]
        b.add_used(tool)
        b.start("executor")
        b.talos(copy.TALOS_RUNNING.format(tool=tool))
        b.caption(copy.CAPTION_EXECUTOR_SHORT)
        b.emit(
            "call.args",
            tool=tool,
            args=[["city", json.dumps(city), False]],
            caption=copy.ARGS_CAPTION,
        )
        if env not in self.saved_keys:
            b.emit("call.error", error=WEATHER_NO_KEY, when="run")
            b.finish("executor", "fail", copy.LABEL_EXEC_FAILED)
            b.log(copy.LOG_EXEC_FAILED, "w", error_type="RuntimeError")
            b.status(copy.STATUS_STEP_FAILED, tone="alert")
            b.mark_failed()
            self._vault_failure(b, tool, WEATHER_NO_KEY)
            b.flow("executor", "answer")
            b.start("answer")
            b.caption(copy.CAPTION_FAILED_NO_KEY)
            self._answer(
                b,
                copy.ANSWER_WEATHER_NO_KEY.format(tool=tool, env=env),
                copy.NOTE_WEATHER_NO_KEY,
                [
                    {
                        "kind": "failed",
                        "text": copy.CHIP_FAILED.format(tool=tool, error_type="RuntimeError"),
                    }
                ],
                status="done",
                summary=copy.SUMMARY_FORGED_NO_KEY if forged else copy.SUMMARY_NO_KEY,
                gold=forged,
            )
            return
        self.vault.record_usage(tool)
        b.emit("call.result", repr=copy.RESULT_WEATHER, type="", small=True)
        b.finish("executor", "done", "Executor")
        b.log(copy.LOG_EXEC_DONE_WEATHER, "w")
        b.flow("executor", "answer")
        b.start("answer")
        if forged:
            b.status(copy.STATUS_ONE_FORGED, gold=True)
            summary, gold = copy.SUMMARY_FORGED_KEY, True
        else:
            summary, gold = copy.SUMMARY_REUSED, False
        b.caption(copy.CAPTION_DONE_WEATHER)
        chip = (
            {"kind": "forged", "text": copy.CHIP_FORGED.format(tool=tool)}
            if forged
            else {"kind": "reused", "text": copy.CHIP_REUSED.format(tool=tool)}
        )
        self._answer(
            b,
            copy.ANSWER_WEATHER,
            copy.NOTE_WEATHER.format(city=html.escape(city)),
            [chip],
            status="done",
            summary=summary,
            gold=gold,
        )

    def _flow_chat(self, b: Board, query: str) -> Pause | None:
        self._planner(
            b,
            variant="chat",
            needs=None,
            tool_hint=None,
            label=copy.LABEL_CHAT,
            sig=None,
            log_line=copy.LOG_PLAN_CHAT,
            caption=copy.CAPTION_PLAN_CHAT,
        )
        b.status(copy.STATUS_NONE_FORGED)
        b.flow("planner", "answer")
        b.start("answer")
        self._answer(
            b,
            copy.ANSWER_CHAT.format(count=len(self.vault.all())),
            copy.NOTE_CHAT,
            [],
            status="done",
            summary=copy.SUMMARY_CHAT,
        )
        return None

    def _flow_unknown(self, b: Board, query: str) -> Pause | None:
        self._planner(
            b,
            variant="chat",
            needs=None,
            tool_hint=None,
            label=copy.LABEL_UNKNOWN,
            sig=None,
            log_line=copy.LOG_PLAN_UNKNOWN,
            caption=copy.CAPTION_PLAN_UNKNOWN,
        )
        b.status(copy.STATUS_NOTHING_RAN)
        b.flow("planner", "answer")
        b.start("answer")
        self._answer(b, copy.ANSWER_UNKNOWN, None, [], status="done", summary=copy.SUMMARY_UNKNOWN)
        return None
