"""EventTranslator on recorded chunks from the real graph (spec 02 §11)."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.types import Interrupt

from talos.web.translator import STREAM_MODES, EventTranslator, error_type
from tests.web import chunks

CAESAR_SIG = "caesar_cipher(text: str, shift: int, mode: str) -> str"


def lookup(needs: str, hint: str | None) -> str | None:
    return {
        "caesar_cipher": CAESAR_SIG,
        "python_exec": "python_exec(code: str, timeout: int | None = None) -> dict",
    }.get(hint or "")


def run(*names: str, resume: tuple[str, str] | None = None):
    """Translate fixtures in order; between them, the user answers `resume`."""
    tr = EventTranslator(signatures=lookup, max_attempts=3, timeout_s=10, prune_after=2)
    events = []
    for i, name in enumerate(names):
        if i:
            assert tr.pause is not None
            events += tr.resumed(*resume)
        for chunk in chunks.load(name):
            events += tr.feed(chunk)
            json.dumps(tr.state)  # always storable as runs.translator_state
    if tr.pause is None:
        events += tr.finish()
    return tr, events


def types(events) -> list[str]:
    """Event types, with runs of answer.delta collapsed to one."""
    out: list[str] = []
    for type_, _ in events:
        if not (type_ == "answer.delta" and out and out[-1] == "answer.delta"):
            out.append(type_)
    return out


def first(events, type_: str, **match):
    return next(d for t, d in events if t == type_ and all(d.get(k) == v for k, v in match.items()))


def test_stream_modes_are_the_four_the_translator_reads():
    assert STREAM_MODES == ["updates", "custom", "messages", "tasks"]


def test_forge_with_retry_produces_the_demo_sequence():
    tr, events = run("forge_retry")
    assert types(events) == [
        "node.started", "caption", "talos.status",  # planner
        "plan.ready", "strip.set", "node.finished", "log.line", "caption",
        "log.status", "log.line", "link.flow",  # Forging, vault no match, planner→forger
        "node.started", "talos.status", "caption", "log.line", "forge.code",  # attempt 1
        "node.finished", "link.flow", "node.started", "caption", "log.line",  # tester
        "log.pop", "forge.tests", "log.line", "log.line", "forge.attempt", "talos.status",
        "node.finished", "node.started", "caption", "log.line", "forge.code",  # attempt 2
        "node.finished", "link.flow", "node.started", "caption", "log.line",
        "log.pop", "forge.tests", "log.line",
        "caption", "forge.smoke", "log.line", "forge.attempt",  # smoke settles attempt 2
        "node.finished", "link.flow",  # tester → human
        "node.finished", "caption", "link.flow",  # human skipped
        "node.started", "caption",  # learn
        "node.finished", "log.line", "vault.saved", "link.flow",
        "node.started", "talos.status", "caption", "call.args", "call.result",
        "node.finished", "log.line",  # executor done
        "link.flow", "node.started", "log.status", "caption",  # into Answer
        "answer.delta", "node.finished", "answer.done", "run.finished",
    ]  # fmt: skip
    assert first(events, "strip.set")["subtask"]["label"] == "Sub-task 1 of 1, needs a new tool"
    assert first(
        events,
        "caption",
        html=("1 sub-task. Nothing in the vault matches, so it needs a new tool."),
    )
    code1, code2 = [d for t, d in events if t == "forge.code"]
    assert (code1["attempt"], code1["changed"], code1["note"]) == (1, None, None)
    assert (code1["tests"], code2["tests"]) == (5, 5)  # def test_ count in that attempt
    assert (code2["attempt"], code2["changed"]) == (2, 48)
    assert code2["note"] == "Line 48 is new in attempt 2."
    assert first(events, "log.line", text="4 of 5 passed, retrying")["tone"] == "g"
    assert first(events, "log.line", tone="sub")["text"] == "test_decrypt_reverses_encrypt"
    assert first(events, "forge.attempt", attempt=1) == {
        "attempt": 1,
        "ok": False,
        "detail": "test_decrypt_reverses_encrypt\nAssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'",
    }
    assert first(events, "forge.attempt", attempt=2)["ok"] is True
    assert first(
        events,
        "caption",
        html=(
            '<span class="gold">Attempt 2 of 3.</span> Running 5 tests in a subprocess,'
            " 10-second limit."
        ),
    )
    saved = first(events, "vault.saved")
    assert saved["tool"]["name"] == "caesar_cipher"
    assert saved["tool"]["args"] == "text: str, shift: int, mode: str"
    assert saved["tool"]["ret"] == "str"
    assert saved["tool"]["web"] is False
    assert first(events, "call.args")["caption"] == "Filled in by the Executor"
    assert first(events, "answer.done") == {
        "html": "&quot;TALOS AGENT&quot; encrypted with a shift of 7 is AHSVZ HNLUA.",
        "note": None,
        "chips": [{"kind": "forged", "text": "Forged caesar_cipher"}],
    }
    assert events[-1] == (
        "run.finished",
        {
            "status": "done",
            "summary": "1 tool forged, 2 attempts",
            "summary_gold": True,
            "forged": ["caesar_cipher"],
            "used": ["caesar_cipher"],
        },
    )
    assert tr.state["failed"] is False


def test_vault_run_marks_vault_and_skip_then_reuses():
    _, events = run("vault")
    strip = first(events, "strip.set")
    assert strip["variant"] == "vault"
    assert strip["sig"] == {
        "name": "caesar_cipher",
        "args": "text: str, shift: int, mode: str",
        "ret": "str",
    }
    assert first(
        events,
        "caption",
        html=(
            'The Planner matched <span class="mono">caesar_cipher</span> on the keywords caesar,'
            " cipher and decrypt. Nothing will be written or tested this time."
        ),
    )
    flows = [(d["from"], d["to"]) for t, d in events if t == "link.flow"]
    assert flows == [
        ("planner", "vault"),
        ("vault", "skip"),
        ("skip", "executor"),
        ("executor", "answer"),
    ]
    assert first(events, "log.status", text="0 tools forged")["tone"] == "warm"
    assert first(events, "caption", html="Done from the vault. The forge sub-graph never ran.")
    assert first(events, "answer.done")["chips"] == [
        {"kind": "reused", "text": "Reused caesar_cipher from the vault"}
    ]
    assert events[-1][1]["summary"] == "0 tools forged"
    assert events[-1][1]["used"] == ["caesar_cipher"]


def test_chat_run_goes_planner_to_answer():
    _, events = run("chat")
    assert types(events) == [
        "node.started", "caption", "talos.status",
        "plan.ready", "strip.set", "node.finished", "log.line", "caption", "log.status",
        "link.flow", "node.started", "answer.delta", "node.finished",
        "answer.done", "run.finished",
    ]  # fmt: skip
    assert first(events, "strip.set") == {
        "variant": "chat",
        "subtask": {"index": 0, "total": 0, "label": "Conversational"},
        "sig": None,
    }
    assert first(events, "link.flow") == {"from": "planner", "to": "answer"}
    assert "".join(d["text"] for t, d in events if t == "answer.delta") == (
        "I plan, then forge tools."
    )
    assert events[-1][1]["summary"] == "Answered directly"


def test_a_run_that_ends_in_an_interrupt_has_no_answer_and_a_pause():
    tr, events = run("exec_pause")
    assert tr.pause is not None
    kind, value = tr.pause
    assert kind == "confirm_exec"
    assert value["kwargs"] == {"code": "print(sum(range(1, 101)))"}
    assert types(events)[-5:] == [
        "node.started", "caption", "log.line", "log.status", "talos.status",
    ]  # fmt: skip
    assert first(events, "node.started", step="executor", label="Executor, waiting for you")
    assert first(events, "log.line", text="paused for approval")["caret"] is True
    assert not any(t in ("answer.done", "run.finished", "call.args") for t, _ in events)


def test_approved_exec_continues_on_the_same_translator():
    tr, events = run("exec_pause", "exec_approve", resume=("confirm_exec", "approve"))
    _, paused = run("exec_pause")
    after = events[len(paused) :]
    assert [t for t, _ in after][:3] == ["log.pop", "log.line", "call.args"]
    assert first(events, "log.line", text="running")["caret"] is True
    assert first(events, "call.args")["caption"] == "Written by the Executor"
    # planner, executor, executor (waiting for you), answer
    assert types(events).count("node.started") == 4
    assert events[-1][1]["status"] == "done"
    assert events[-1][1]["summary"] == "Built-in, approved"


def test_declined_exec_finishes_declined():
    tr = EventTranslator()
    for chunk in chunks.load("exec_pause"):
        tr.feed(chunk)
    events = tr.resumed("confirm_exec", "decline")
    events += tr.feed(((), "tasks", {"name": "executor", "input": None}))
    events += tr.feed(((), "custom", {"type": "call.error", "data": {
        "error": "declined by user", "when": "declined"}}))  # fmt: skip
    events += tr.feed(((), "tasks", {"name": "orchestrator_out", "input": None}))
    events += tr.finish()
    assert first(events, "node.finished", step="executor")["label"] == "Executor, declined"
    assert first(events, "log.line", text="declined by you")["tone"] == "w"
    assert first(events, "log.status", text="Not run")
    assert first(events, "caption", html="Nothing ran. The sub-task is recorded as declined.")
    assert events[-1][1]["status"] == "declined"
    assert events[-1][1]["summary"] == "Declined, nothing ran"


def test_missing_key_pause_then_skip_runs_and_fails_without_the_key():
    tr, events = run("key_pause", "key_skip", resume=("missing_api_key", "skip"))
    assert first(
        events,
        "caption",
        html=(
            'Human check paused the graph. <span class="mono">get_current_temperature</span>'
            ' needs <span class="mono">OPENWEATHERMAP_API_KEY</span>.'
        ),
    )
    assert first(events, "node.finished", step="human")["label"] == "Human check, skipped"
    assert first(events, "log.line", text="failed, RuntimeError")
    assert first(events, "log.status", text="1 step failed")["tone"] == "alert"
    assert first(events, "log.line", text="1 failure in a row")
    assert first(events, "vault.saved")["tool"]["web"] is True
    assert first(events, "answer.done")["chips"] == [
        {"kind": "failed", "text": "get_current_temperature raised a RuntimeError"}
    ]
    assert events[-1][1]["summary"] == "Failed, 1 failure in a row"
    assert tr.state["failed"] is True


def test_missing_key_saved_says_so():
    tr = EventTranslator()
    for chunk in chunks.load("key_pause"):
        tr.feed(chunk)
    events = tr.resumed("missing_api_key", "save")
    assert [t for t, _ in events] == [
        "log.pop", "log.line", "node.finished", "caption", "log.status", "link.flow",
    ]  # fmt: skip
    assert events[3][1]["html"] == (
        'Saved <span class="mono">OPENWEATHERMAP_API_KEY</span> to .env. Talos won\'t ask again.'
    )


def test_subgraph_custom_chunks_keep_their_namespace_and_shape():
    """Pins the LangGraph chunk shape the translator relies on."""
    custom = [c for c in chunks.load("forge_retry") if c[1] == "custom"]
    inner = [c for c in custom if c[0]]
    assert inner, "forge events must come from inside the forge sub-graph"
    for ns, mode, data in inner:
        assert len(ns) == 1 and ns[0].startswith("forge_subgraph:")
        assert set(data) == {"type", "data"}
    assert {c[2]["type"] for c in inner} == {"forge.code", "forge.tests", "forge.smoke"}
    outer = {c[2]["type"] for c in custom if not c[0]}
    assert outer == {"vault.saved", "call.args", "call.result"}


@pytest.mark.parametrize("name", chunks.SCENARIOS)
async def test_recorded_fixtures_match_a_live_capture(name):
    live = [(tuple(ns), mode, data) for ns, mode, data in await chunks.capture(name)]
    assert chunks.shape(live) == chunks.shape(chunks.load(name))


def test_forge_code_carries_the_forged_signature_when_the_plan_names_no_tool():
    # The Planner can't name a tool it hasn't forged yet (tool_hint is null), so
    # strip.set has no signature. The Forger's signature fills the bench title.
    _, events = run("forge_retry")
    assert first(events, "strip.set")["sig"] is None
    sig = {"name": "caesar_cipher", "args": "text: str, shift: int, mode: str", "ret": "str"}
    assert [d["sig"] for t, d in events if t == "forge.code"] == [sig, sig]


def test_forger_failure_and_smoke_without_a_call_are_tolerated():
    tr = EventTranslator()
    tr.feed(((), "updates", {"planner": {"plan": {"sub_tasks": [
        {"id": 1, "action": "x", "needs": "forge"}]}}}))  # fmt: skip
    ns = ("forge_subgraph:abc",)
    tr.feed((ns, "tasks", {"name": "forge", "input": None}))
    code = {"tool": "", "attempt": 1, "file": "tool.py", "lines": [], "changed": 1, "note": None}
    assert tr.feed((ns, "custom", {"type": "forge.code", "data": code})) == []
    events = tr.feed((ns, "updates", {"forge": {"forged_tool": {"name": "", "code": ""}}}))
    assert first(events, "forge.code")["tool"] == ""
    assert first(events, "forge.code")["tests"] == 0
    assert first(events, "forge.code")["sig"] is None
    tr.feed((ns, "tasks", {"name": "test", "input": None}))
    tests = {"tool": "", "attempt": 1, "results": []}
    tr.feed((ns, "custom", {"type": "forge.tests", "data": tests}))
    events = tr.feed((ns, "updates", {"test": {"test_result": {
        "passed": False, "results": [], "n_total": 0, "timed_out": False,
        "error": "Forger produced no code or no test_code."}}}))  # fmt: skip
    assert first(events, "forge.attempt")["detail"] == "Forger produced no code or no test_code."
    assert first(events, "log.line", text="0 of 0 passed, retrying")
    events = tr.feed((ns, "custom", {"type": "forge.smoke", "data": {
        "call": None, "result": None, "passed": False}}))  # fmt: skip
    assert first(events, "forge.smoke")["call"] is None


def test_timed_out_tests_explain_themselves():
    tr = EventTranslator()
    tr.state["attempt"] = 3
    events = tr.feed((("forge_subgraph:x",), "updates", {"test": {"test_result": {
        "passed": False, "results": [], "n_total": 0, "timed_out": True,
        "error": "Subprocess timed out (likely infinite loop)."}}}))  # fmt: skip
    detail = first(events, "forge.attempt")["detail"]
    assert detail == "Subprocess timed out (likely infinite loop)."
    assert first(events, "log.line", text="0 of 0 passed")


def test_answer_without_streamed_tokens_still_arrives():
    tr = EventTranslator()
    meta = {"langgraph_node": "orchestrator_out"}
    assert tr.feed(((), "messages", (AIMessage(content="Hello there."), meta))) == [
        ("answer.delta", {"text": "Hello there."})
    ]
    assert tr.feed(
        ((), "updates", {"orchestrator_out": {"messages": [AIMessage(content="Hello there.")]}})
    ) == [  # fmt: skip
        ("node.finished", {"step": "answer", "status": "answer"})
    ]


def test_tokens_from_other_nodes_are_ignored():
    tr = EventTranslator()
    chunk = AIMessageChunk(content="{json plan}")
    assert tr.feed(((), "messages", (chunk, {"langgraph_node": "planner"}))) == []


def test_interrupt_objects_and_error_types():
    tr = EventTranslator()
    value = {"type": "missing_api_key", "env_var": "X_API_KEY", "tool_name": "t"}
    tr.feed(((), "updates", {"__interrupt__": (Interrupt(value=value, id="1"),)}))
    assert tr.pause[0] == "missing_api_key"
    assert error_type("TypeError: shift must be an int, got str") == "TypeError"
    assert error_type("requests.exceptions.HTTPError: 404") == "HTTPError"
    assert error_type("dispatch error: Unknown primitive") == "error"


def test_answer_html_is_escaped():
    tr = EventTranslator()
    meta = {"langgraph_node": "orchestrator_out"}
    tr.feed(((), "messages", (AIMessageChunk(content="<script>x</script> & <b>"), meta)))
    done = dict(tr.finish())["answer.done"]
    assert done["html"] == "&lt;script&gt;x&lt;/script&gt; &amp; &lt;b&gt;"


def test_multi_subtask_plan_resets_the_strip_per_subtask():
    tr = EventTranslator(max_attempts=3)
    plan = {
        "sub_tasks": [
            {"id": 1, "action": "read", "needs": "primitive", "tool_hint": "web_read"},
            {
                "id": 2,
                "action": "slug",
                "needs": "vault",
                "tool_hint": "slugify",
                "depends_on": [1],
            },
        ],
        "verdict": "feasible",
    }
    events = tr.feed(((), "updates", {"planner": {"plan": plan}}))
    first = next(d for t, d in events if t == "strip.set")
    assert first["variant"] == "primitive"
    assert first["subtask"] == {
        "index": 1,
        "total": 2,
        "label": "Sub-task 1 of 2, built-in primitive",
    }
    assert ("log.line", {"label": "plan", "text": "2 sub-tasks", "tone": "plain"}) in events

    events = tr.feed(((), "updates", {"advance": {"current_sub_task": plan["sub_tasks"][1]}}))
    assert events[0] == ("subtask.started", {"index": 2, "total": 2})
    assert events[1][0] == "strip.set"
    assert events[1][1]["variant"] == "vault"
    assert events[1][1]["subtask"]["label"] == "Sub-task 2 of 2, found in the vault"
    assert events[2] == ("node.finished", {"step": "planner", "status": "done"})
    assert ("log.line", {"label": "vault", "text": "slugify", "tone": "plain"}) in events


def test_approval_does_not_pop_log_lines_of_later_subtasks():
    tr = EventTranslator()
    plan = {
        "sub_tasks": [
            {"id": 1, "action": "run", "needs": "primitive", "tool_hint": "python_exec"},
            {"id": 2, "action": "slug", "needs": "vault", "tool_hint": "slugify"},
        ]
    }
    tr.feed(((), "updates", {"planner": {"plan": plan}}))
    tr.feed(((), "tasks", {"name": "executor", "input": None}))
    value = {"type": "confirm_exec", "tool": "python_exec", "kwargs": {"code": "1"}}
    tr.feed(((), "updates", {"__interrupt__": (Interrupt(value=value, id="1"),)}))
    tr.resumed("confirm_exec", "approve")
    events = tr.feed(((), "custom", {"type": "call.result", "data": {"result": "1"}}))
    assert "log.pop" in [t for t, _ in events]
    tr.feed(((), "updates", {"advance": {}}))
    tr.feed(((), "tasks", {"name": "executor", "input": None}))
    events = tr.feed(((), "custom", {"type": "call.result", "data": {"result": "x"}}))
    assert "log.pop" not in [t for t, _ in events]
    events = tr.finish()
    assert events[-1][1]["status"] == "done"


def test_key_captions_escape_model_derived_names():
    tr = EventTranslator()
    value = {"type": "missing_api_key", "env_var": "<b>X</b>", "tool_name": "<i>t</i>"}
    events = tr.feed(((), "updates", {"__interrupt__": (Interrupt(value=value, id="1"),)}))
    html_ = "".join(d["html"] for t, d in events if t == "caption")
    assert "<b>X</b>" not in html_ and "&lt;b&gt;X&lt;/b&gt;" in html_
    assert "<i>t</i>" not in html_
    events = tr.resumed("missing_api_key", "save")
    html_ = "".join(d["html"] for t, d in events if t == "caption")
    assert "<b>X</b>" not in html_ and "&lt;b&gt;X&lt;/b&gt;" in html_


def test_no_changed_line_note_for_an_empty_file():
    tr = EventTranslator()
    tr.state["attempt"] = 2
    code = {"tool": "", "attempt": 2, "file": "t.py", "lines": [], "changed": 1, "note": None}
    ns = ("forge_subgraph:a",)
    tr.feed((ns, "custom", {"type": "forge.code", "data": code}))
    events = tr.feed((ns, "updates", {"forge": {"forged_tool": {"name": "", "code": ""}}}))
    assert first(events, "forge.code")["note"] is None


def test_failed_first_attempt_does_not_replay_the_intro_on_retry():
    tr = EventTranslator()
    tr.feed(((), "updates", {"planner": {"plan": {"sub_tasks": [
        {"id": 1, "action": "x", "needs": "forge"}]}}}))  # fmt: skip
    ns = ("forge_subgraph:a",)
    tr.feed((ns, "tasks", {"name": "forge", "input": None}))
    assert tr.state["intro_pending"] is True
    tr.feed((ns, "tasks", {"name": "forge", "input": None}))
    assert tr.state["intro_pending"] is False
    code = {
        "tool": "f",
        "attempt": 2,
        "file": "t.py",
        "lines": ["x"],
        "changed": None,
        "note": None,
    }
    events = tr.feed((ns, "custom", {"type": "forge.code", "data": code}))
    tests = "def test_a():\n    pass\n\ndef test_b():\n    pass\n"
    forged = {"name": "f", "test_code": tests}
    events += tr.feed((ns, "updates", {"forge": {"forged_tool": forged}}))
    assert first(events, "forge.code")["tests"] == 2
    assert not any(
        "Attempt" in d.get("html", "") and "first" in d.get("html", "") for t, d in events
    )
    assert [t for t, _ in events] == ["forge.code"]


def test_smoke_failure_detail_uses_the_error():
    tr = EventTranslator()
    tr.state["pending_attempt"] = "5 of 5 passed"
    tr.state["attempt"] = 1
    data = {"call": "f(1)", "result": None, "passed": False, "error": "load error: SyntaxError"}
    events = tr.feed((("forge_subgraph:a",), "custom", {"type": "forge.smoke", "data": data}))
    assert first(events, "forge.attempt")["detail"] == "Smoke test failed: load error: SyntaxError"


@pytest.mark.parametrize("name", ["vault", "forge_retry", "exec_approve"])
def test_real_results_are_never_small(name):
    """`small` is the reference's placeholder style: a real result never has it."""
    names = ("exec_pause", "exec_approve") if name == "exec_approve" else (name,)
    _, events = run(*names, resume=("confirm_exec", "approve"))
    results = [d for t, d in events if t == "call.result"]
    assert results and all(d["small"] is False for d in results)
