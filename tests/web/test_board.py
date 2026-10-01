"""Board: UI state plus the contract events that change it."""

from __future__ import annotations

import json

from talos.web.board import STRIPS, Board, new_state


def test_strip_resets_steps_and_starts_skip_as_skip():
    b = Board()
    b.strip("vault", index=1, total=1, label="Sub-task 1 of 1, found in the vault", sig=None)
    assert [k for k in b.state["steps"]] == [k for k, _ in STRIPS["vault"]]
    assert b.state["steps"]["skip"]["state"] == "skip"
    assert b.state["steps"]["vault"] == {"state": "pending", "label": "Vault tool"}
    assert b.drain() == [
        (
            "strip.set",
            {
                "variant": "vault",
                "subtask": {"index": 1, "total": 1, "label": "Sub-task 1 of 1, found in the vault"},
                "sig": None,
            },
        )
    ]
    assert b.drain() == []


def test_node_events_carry_labels_only_when_given():
    b = Board()
    b.strip("primitive", index=1, total=1, label="x", sig=None)
    b.drain()
    b.start("executor", "Executor, waiting for you")
    b.finish("executor", "done", "Executor")
    b.start("answer")
    assert b.drain() == [
        ("node.started", {"step": "executor", "label": "Executor, waiting for you"}),
        ("node.finished", {"step": "executor", "status": "done", "label": "Executor"}),
        ("node.started", {"step": "answer"}),
    ]


def test_log_lines_format_fields_and_caret():
    b = Board()
    b.log(("test", "{passed} of {total} passed, retrying"), "g", passed=4, total=5)
    b.log(("test", "running"), "g", caret=True)
    b.sub("test_decrypt_reverses_encrypt")
    assert b.drain() == [
        ("log.line", {"label": "test", "text": "4 of 5 passed, retrying", "tone": "g"}),
        ("log.line", {"label": "test", "text": "running", "tone": "g", "caret": True}),
        ("log.line", {"label": "", "text": "test_decrypt_reverses_encrypt", "tone": "sub"}),
    ]


def test_stop_marks_active_steps_and_says_so():
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.start("forger")
    b.start("executor", "Executor, waiting for you")
    b.drain()
    b.stop()
    assert b.drain() == [
        ("node.finished", {"step": "forger", "status": "stopped", "label": "Forger, stopped"}),
        ("node.finished", {"step": "executor", "status": "stopped", "label": "Executor, stopped"}),
        ("log.line", {"label": "stop", "text": "stopped by you", "tone": "w"}),
        ("log.status", {"text": "Stopped", "gold": False, "tone": ""}),
        ("caption", {"html": "You stopped this run. Nothing was saved to the vault."}),
    ]


def test_stop_between_two_steps_marks_the_step_being_handed_the_run():
    """Between `node.finished` and `node.started` no step is active: Stop marks the flow target."""
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.start("forger")
    b.finish("forger", "forge")
    b.flow("forger", "tester")
    b.drain()
    b.stop()
    assert b.drain()[0] == (
        "node.finished",
        {"step": "tester", "status": "stopped", "label": "Tester, stopped"},
    )
    assert b.state["steps"]["forger"]["state"] == "forge"
    assert b.state["steps"]["tester"]["state"] == "stopped"


def test_stop_right_after_a_step_finished_and_before_the_hand_over_marks_nothing():
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.start("forger")
    b.finish("forger", "forge")  # no link.flow yet: nothing is being handed the run
    b.drain()
    b.stop()
    assert [t for t, _ in b.drain()] == ["log.line", "log.status", "caption"]


def test_stop_during_a_retry_hand_over_marks_the_tester_that_ran_before():
    """CI run 36821538409: attempt 2's Forger handed over to the Tester that ran attempt 1."""
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.flow("forger", "tester")
    b.start("tester")
    b.finish("tester", "forge")
    b.start("forger")
    b.finish("forger", "forge")
    b.flow("forger", "tester")
    b.drain()
    b.stop()
    assert b.drain()[0] == (
        "node.finished",
        {"step": "tester", "status": "stopped", "label": "Tester, stopped"},
    )


def test_stop_never_marks_a_flow_target_that_already_took_the_run():
    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.flow("forger", "tester")
    b.start("tester")
    b.finish("tester", "forge")  # the target started (which ends the hand-over) and finished
    b.drain()
    b.stop()
    assert [t for t, _ in b.drain()] == ["log.line", "log.status", "caption"]

    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.flow("tester", "human")
    b.finish("human", "skip")  # finished without starting: the hand-over is over too
    b.drain()
    b.stop()
    assert [t for t, _ in b.drain()] == ["log.line", "log.status", "caption"]

    b = Board()
    b.strip("forge", index=1, total=1, label="x", sig=None)
    b.flow("planner", "forger")
    b.start("forger")
    b.drain()
    b.stop()
    stopped = [d["step"] for t, d in b.drain() if t == "node.finished"]
    assert stopped == ["forger"]  # the active step only, once


def test_a_new_strip_forgets_the_hand_over():
    b = Board()
    b.strip("forge", index=1, total=2, label="x", sig=None)
    b.flow("executor", "answer")
    b.strip("chat", index=2, total=2, label="y", sig=None)
    b.drain()
    b.stop()
    assert [t for t, _ in b.drain()] == ["log.line", "log.status", "caption"]


def test_stop_reads_a_saved_state_without_the_hand_over_key():
    """A `translator_state` saved before `next` existed still stops its active step."""
    state = new_state()
    del state["next"]
    state["steps"] = {"planner": {"state": "active", "label": "Planner"}}
    b = Board(state)
    b.stop()
    assert b.drain()[0][1]["step"] == "planner"


def test_finished_reports_tools_and_state_stays_json():
    state = new_state()
    b = Board(state)
    b.add_forged("caesar_cipher")
    b.add_forged("caesar_cipher")
    b.add_used("caesar_cipher")
    b.mark_failed()
    b.finished("done", "Failed, 1 failure in a row")
    assert b.drain()[-1] == (
        "run.finished",
        {
            "status": "done",
            "summary": "Failed, 1 failure in a row",
            "summary_gold": False,
            "forged": ["caesar_cipher"],
            "used": ["caesar_cipher"],
        },
    )
    assert state["failed"] is True
    assert json.loads(json.dumps(state)) == state
