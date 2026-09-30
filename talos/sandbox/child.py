"""Sandbox child: runs one forged-tool call and reports back (spec 03 §2.1).

Started by `talos.sandbox.runner.run_tool` as
`python -P -m talos.sandbox.child`. Protocol:

1. Read one JSON request from stdin:
   `{"source_path", "function", "args", "kwargs", "sentinel"}`, with args
   and kwargs in the tagged form from `talos.sandbox.codec`.
2. Load the tool file into a fresh namespace and call the function, with
   `sys.stdout` redirected into a buffer so the tool's prints can't corrupt
   the reply, and stdin emptied so `input()` gets EOF instead of hanging.
3. Write the sentinel line, then one JSON reply line to the real stdout:
   `{"ok", "value", "error", "stdout"}`.

This module must only import the stdlib and `talos.sandbox.codec`.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

from talos.sandbox.codec import decode, encode, safe_repr


def _error_text(exc: BaseException) -> str:
    """Same format the executor has always used: `TypeError: message`."""
    return f"{type(exc).__name__}: {exc}"


def _load_function(source_path: str, function: str) -> Any:
    """exec the tool file in a fresh namespace and return `function`."""
    path = Path(source_path)
    source = path.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {"__name__": f"talos.vault.tools.{path.stem}"}
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 — this is the sandbox
    fn = namespace.get(function)
    if fn is None:
        raise AttributeError(f"{path.name} defines no function {function!r}")
    if not callable(fn):
        raise TypeError(f"{function!r} in {path.name} is not callable")
    return fn


def _encode_value(value: Any) -> Any:
    """Encode the return value; fall back to its repr if encoding fails
    (e.g. a self-referencing list hits the recursion limit)."""
    try:
        encoded = encode(value)
        json.dumps(encoded)
        return encoded
    except Exception:  # noqa: BLE001 — never lose the reply over a weird value
        return encode(safe_repr(value))


def run_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one request and build the reply dict (no I/O on real stdout).

    Args:
        request: The decoded stdin request.

    Returns:
        `{"ok", "value", "error", "stdout"}` with `value` in tagged form.
    """
    captured = io.StringIO()
    reply: dict[str, Any] = {"ok": False, "value": None, "error": None, "stdout": ""}
    real_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(captured):
            fn = _load_function(request["source_path"], request["function"])
            args = decode(request.get("args") or [])
            kwargs = decode(request.get("kwargs") or {})
            value = fn(*args, **kwargs)
        reply["ok"] = True
        reply["value"] = _encode_value(value)
    except BaseException as e:  # noqa: BLE001 — SystemExit/KeyboardInterrupt are tool errors too
        reply["error"] = _error_text(e)
    finally:
        sys.stdin = real_stdin
    reply["stdout"] = captured.getvalue()
    return reply


def main() -> int:
    """Entry point for `python -m talos.sandbox.child`."""
    out = sys.stdout
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as e:
        out.write(f"\nbad request: {e}\n")
        return 2
    reply = run_request(request)
    out.write("\n" + str(request.get("sentinel", "")) + "\n")
    out.write(json.dumps(reply) + "\n")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
