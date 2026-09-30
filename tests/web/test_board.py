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
