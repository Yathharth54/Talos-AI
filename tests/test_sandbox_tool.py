"""SandboxedTool: signature from source, calls through the sandbox."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from talos.agents.executor import _validate_kwargs, schema_from_signature
from talos.config import settings
from talos.sandbox import SandboxedTool, ToolFailed
from talos.sandbox.tool import signature_from_source


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WORKSPACE_DIR", tmp_path / "workspace")


def test_signature_matches_the_real_function():
    source = (
        "def f(a, /, b: int, c: 'list[str]' = None, *rest: int, d: float = 1.5, "
        "e=len, **extra) -> dict:\n    return {}\n"
    )
    sig = signature_from_source(source, "f")
    namespace: dict = {}
    exec(source, namespace)
    real = inspect.signature(namespace["f"])
    assert list(sig.parameters) == list(real.parameters)
    assert [p.kind for p in sig.parameters.values()] == [p.kind for p in real.parameters.values()]
    assert sig.parameters["b"].annotation == "int"
    assert sig.parameters["c"].default is None
    assert sig.parameters["d"].default == 1.5
    assert repr(sig.parameters["e"].default) == "len"
    assert sig.return_annotation == "dict"


def test_signature_does_not_run_the_source(tmp_path):
    marker = tmp_path / "ran"
    source = f"open({str(marker)!r}, 'w')\ndef f(x):\n    return x\n"
    signature_from_source(source, "f")
    assert not marker.exists()


def test_last_definition_wins():
    source = "def f(a):\n    pass\ndef f(a, b):\n    pass\n"
    assert list(signature_from_source(source, "f").parameters) == ["a", "b"]


def test_assigned_callable_gets_an_open_signature():
    sig = signature_from_source("f = print\n", "f")
    assert [p.kind for p in sig.parameters.values()] == [
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ]


def test_missing_function_raises_value_error():
    with pytest.raises(ValueError, match="defines no function 'g'"):
        signature_from_source("def f():\n    pass\n", "g")


def test_syntax_error_raises_value_error():
    with pytest.raises(ValueError, match="SyntaxError"):
        signature_from_source("def f(:\n", "f")


def test_proxy_works_with_executor_introspection(tmp_path):
    path = tmp_path / "add.py"
    path.write_text("def add(a: int, b: int = 2) -> int:\n    return a + b\n")
    tool = SandboxedTool(path, "add")
    assert tool.__name__ == "add"
    assert schema_from_signature(tool) == {"a": "int", "b": "int"}
    with pytest.raises(TypeError, match="missing required args"):
        _validate_kwargs(tool, {"b": 1})
    assert tool(1) == 3


def test_failed_call_raises_tool_failed_with_the_error_text(tmp_path):
    path = tmp_path / "boom.py"
    path.write_text("def boom():\n    raise ValueError('kaboom')\n")
    with pytest.raises(ToolFailed) as info:
        SandboxedTool(path, "boom")()
    assert str(info.value) == "ValueError: kaboom"
    assert info.value.result.timed_out is False


def test_timeout_is_passed_through(tmp_path):
    path = tmp_path / "slow.py"
    path.write_text("import time\ndef slow():\n    time.sleep(30)\n")
    with pytest.raises(ToolFailed) as info:
        SandboxedTool(path, "slow", timeout=1)()
    assert info.value.result.timed_out is True


def test_unreadable_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read tool file"):
        SandboxedTool(tmp_path / "missing.py", "f")
