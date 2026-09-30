"""The fake graph replays the demo's flows as contract events (spec 02 §9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.config import settings
from talos.vault.manager import SkillManager
from talos.web import fake_graph
from talos.web.fake_graph import FakeDriver, make_fake_vault, parse_caesar, run_python
from talos.web.runner import Pause, Resume
from talos.web.translator import EventTranslator
from tests.web import chunks
from tests.web.test_copy import reference_text
from tests.web.test_translator import types


@pytest.fixture
def driver(tmp_path: Path) -> FakeDriver:
    return FakeDriver(SkillManager(vault_dir=tmp_path / "vault"))


@pytest.fixture(autouse=True)
def ask_before_exec():
    settings.set_auto_approve_override(False)
    yield
    settings.set_auto_approve_override(None)


async def drive(driver: FakeDriver, query: str, state=None, resume: Resume | None = None):
    state = state if state is not None else driver.initial_state()
    items = [item async for item in driver.run(state, query=query, thread_id="t", resume=resume)]
    pause = items[-1] if items and isinstance(items[-1], Pause) else None
    events = [item for item in items if not isinstance(item, Pause)]
    return state, events, pause


def data(events, type_):
    return [d for t, d in events if t == type_]


def translated(*names, resume=None):
    tr = EventTranslator()
    out = []
    for i, name in enumerate(names):
        if i:
            out += tr.resumed(*resume)
        for chunk in chunks.load(name):
            out += tr.feed(chunk)
    return out + ([] if tr.pause else tr.finish())


CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
DECRYPT_Q = 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"
WEATHER_Q = "Use the OpenWeatherMap API to get the current temperature in Mumbai."


async def test_caesar_forge_then_reuse(driver):
    _, events, pause = await drive(driver, CAESAR_Q)
    assert pause is None
    code = data(events, "forge.code")
    assert [(c["attempt"], c["changed"], c["tests"]) for c in code] == [(1, None, 5), (2, 48, 5)]
    assert code[0]["lines"][47] == "    effective_shift = shift"
    assert code[1]["note"] == fake_graph.CAESAR_RETRY_NOTE
    first_tests = data(events, "forge.tests")[0]["results"]
    assert [r["passed"] for r in first_tests] == [True, False, True, True, True]
    assert first_tests[1]["why"] == "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'"
    assert data(events, "forge.smoke") == [
        {"call": fake_graph.CAESAR_SMOKE_CALL, "result": "'AHSVZ HNLUA'", "passed": True}
    ]
    assert data(events, "vault.saved")[0]["sub"] == fake_graph.CAESAR_SAVED_SUB
    assert driver.vault.get("caesar_cipher") is not None
    assert data(events, "answer.done")[0] == {
        "html": (
            '"TALOS AGENT" encrypted with a shift of 7 is <span class="mono">AHSVZ HNLUA</span>.'
        ),
        "note": 'The same tool decrypts too. Ask with "decrypt" and the same shift.',
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

    _, events, _ = await drive(driver, DECRYPT_Q)
    assert data(events, "strip.set")[0]["variant"] == "vault"
    assert data(events, "answer.done")[0]["html"] == (
        'It decrypts to <span class="mono">TALOS AGENT</span>.'
    )
    assert events[-1][1]["summary"] == "0 tools forged"
    assert driver.vault.get("caesar_cipher")["usage_count"] == 2


async def test_word_shift_fails_then_prunes(driver):
    await drive(driver, CAESAR_Q)
    word_q = 'Decrypt "AHSVZ HNLUA" with a shift of three'
    _, events, _ = await drive(driver, word_q)
    args = data(events, "call.args")[0]["args"]
    assert args[1] == ["shift", '"three"', True]
    assert data(events, "call.error")[0] == {
        "error": "TypeError: shift must be an int, got str",
        "when": "run",
    }
    assert data(events, "vault.failure")[0]["streak"] == 1
    assert data(events, "answer.done")[0]["note"] == 'Ask again with "shift 3" and it should work.'
    assert events[-1][1]["summary"] == "Failed, 1 failure in a row"

    _, events, _ = await drive(driver, word_q)
    assert data(events, "vault.failure")[0]["pruned"] is True
    assert {"label": "vault", "text": "removed after 2 failures in a row", "tone": "plain"} in (
        data(events, "log.line")
    )
    assert events[-1][1]["summary"] == "Failed, removed from the vault"
    assert driver.vault.get("caesar_cipher") is None


async def test_python_pauses_for_approval_then_runs(driver):
    state, events, pause = await drive(driver, PYTHON_Q)
    assert pause.kind == "confirm_exec"
    assert pause.value["kwargs"] == {"code": "print(sum(range(1, 101)))"}
    assert data(events, "node.started")[-1] == {
        "step": "executor",
        "label": "Executor, waiting for you",
    }
    approve = Resume("confirm_exec", "approve", {"approved": True})
    _, events, pause = await drive(driver, PYTHON_Q, state, approve)
    assert pause is None
    assert data(events, "call.result")[0] == {"repr": "5050", "type": "stdout", "small": True}
    assert data(events, "answer.done")[0]["html"] == (
        'The code prints <span class="mono">5050</span>.'
    )
    assert events[-1][1]["summary"] == "Built-in, approved"


async def test_python_decline(driver):
    state, _, _ = await drive(driver, PYTHON_Q)
    _, events, _ = await drive(driver, PYTHON_Q, state, Resume("confirm_exec", "decline", None))
    assert events[-1][1]["status"] == "declined"
    assert events[-1][1]["summary"] == "Declined, nothing ran"
    assert data(events, "answer.done")[0]["html"] == (
        "I didn't run the code, so I don't have its output."
    )


async def test_python_without_asking_when_the_setting_is_off(driver):
    settings.set_auto_approve_override(True)
    _, events, pause = await drive(driver, PYTHON_Q)
    assert pause is None
    assert {
        "html": 'Ran without asking, because "Ask before running code" is off in Settings.'
    } in (data(events, "caption"))


async def test_weather_key_save_then_reuse(driver):
    state, events, pause = await drive(driver, WEATHER_Q)
    assert pause.kind == "missing_api_key"
    assert pause.value["env_var"] == "OPENWEATHERMAP_API_KEY"
    save = Resume("missing_api_key", "save", None)  # the fake never sees the value
    _, events, _ = await drive(driver, WEATHER_Q, state, save)
    assert data(events, "call.result")[0]["repr"] == "Not called in this demo"
    assert events[-1][1]["summary"] == "1 tool forged, key saved"
    assert driver.saved_keys == {"OPENWEATHERMAP_API_KEY"}

    _, events, pause = await drive(driver, "What's the temperature in Pune?")
    assert pause is None and data(events, "strip.set")[0]["variant"] == "vault"
    assert data(events, "answer.done")[0]["note"] == (
        "In Talos, you'd get the current temperature in Pune here."
    )


async def test_weather_key_skip_fails_without_the_key(driver):
    state, _, _ = await drive(driver, WEATHER_Q)
    _, events, _ = await drive(driver, WEATHER_Q, state, Resume("missing_api_key", "skip", "skip"))
    assert data(events, "node.finished")[0] == {
        "step": "human",
        "status": "done",
        "label": "Human check, skipped",
    }
    assert events[-1][1]["summary"] == "1 tool forged, failed without a key"


async def test_chat_and_unknown(driver):
    _, events, _ = await drive(driver, "What can you do?")
    assert events[-1][1]["summary"] == "Answered directly"
    _, events, _ = await drive(driver, "Sort these numbers please")
    assert events[-1][1]["summary"] == "Not in this demo"


@pytest.mark.parametrize(
    ("query", "names", "resume", "fake_resume"),
    [
        (CAESAR_Q, ("forge_retry",), None, None),
        ("What can you do?", ("chat",), None, None),
        (
            PYTHON_Q,
            ("exec_pause", "exec_approve"),
            ("confirm_exec", "approve"),
            Resume("confirm_exec", "approve", None),
        ),
        (
            WEATHER_Q,
            ("key_pause", "key_skip"),
            ("missing_api_key", "skip"),
            Resume("missing_api_key", "skip", "skip"),
        ),
    ],
)
async def test_fake_events_come_in_the_same_order_as_the_real_graphs(
    driver, query, names, resume, fake_resume
):
    state, events, pause = await drive(driver, query)
    if fake_resume is not None:
        _, more, _ = await drive(driver, query, state, fake_resume)
        events += more
    assert types(events) == types(translated(*names, resume=resume))


async def test_reuse_order_matches_the_real_vault_run(driver):
    await drive(driver, CAESAR_Q)
    _, events, _ = await drive(driver, DECRYPT_Q)
    assert types(events) == types(translated("vault"))


def test_demo_values_appear_in_the_reference():
    text = reference_text()
    for value in (
        *fake_graph.CAESAR_TESTS,
        *fake_graph.WEATHER_TESTS,
        fake_graph.CAESAR_FAIL_WHY,
        fake_graph.CAESAR_RETRY_NOTE,
        fake_graph.CAESAR_SMOKE_CALL,
        fake_graph.CAESAR_SAVED_SUB,
        fake_graph.CAESAR_TYPE_ERROR,
        fake_graph.WEATHER_NO_KEY,
        fake_graph.PYTHON_DEFAULT,
    ):
        assert value in text, value


def test_parse_caesar_matches_the_demo():
    assert parse_caesar(CAESAR_Q) == {
        "text": "TALOS AGENT",
        "shift": 7,
        "word": None,
        "mode": "encrypt",
    }
    assert parse_caesar(DECRYPT_Q)["mode"] == "decrypt"
    assert parse_caesar("encrypt it with shift of three")["word"] == "three"
    assert parse_caesar("decrypt it")["text"] == "AHSVZ HNLUA"


@pytest.mark.parametrize(
    ("code", "out"),
    [
        ("print(sum(range(1, 101)))", "5050"),
        ("print('hi')", "hi"),
        ("print(2 + 3 * 4)", "14"),
        ("print(7 / 2)", "3.5"),
        ("print(8 / 2)", "4"),
        ("print(9 ** 9 ** 9)", None),
        ("print(((9**64)**64)**3)", None),
        ("print(((((9**64)**64)**64)**64)**64)", None),
        ("print(1 / 0)", None),
        ("import os", None),
    ],
)
def test_run_python_only_runs_simple_prints(code, out):
    assert run_python(code) == out


def test_fake_vault_is_a_copy_without_the_demo_tools(tmp_path: Path):
    source = SkillManager(vault_dir=tmp_path / "src")
    for name in ("caesar_cipher", "slugify"):
        source.register({"name": name, "function": name}, f"def {name}():\n    pass\n")
    vault, root = make_fake_vault(tmp_path / "src")
    assert [e["name"] for e in vault.all()] == ["slugify"]
    assert (root / "tools" / "caesar_cipher.py").exists()  # files stay, like remove()
    vault.remove("slugify")
    assert source.get("slugify") is not None  # the real vault is untouched
