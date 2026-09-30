"""Forged-tool sandbox: run vault tools in a time-limited subprocess.

Public API (spec 03 §2): `run_tool`, `ToolResult`, `SandboxedTool`,
`ToolFailed`, `error_text`. They are imported lazily so the sandbox child, which imports
`talos.sandbox.codec`, doesn't pay for loading settings.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SandboxedTool", "ToolFailed", "ToolResult", "error_text", "run_tool"]


def __getattr__(name: str) -> Any:
    if name in {"ToolResult", "run_tool"}:
        from talos.sandbox import runner

        return getattr(runner, name)
    if name in {"SandboxedTool", "ToolFailed", "error_text"}:
        from talos.sandbox import tool

        return getattr(tool, name)
    raise AttributeError(f"module 'talos.sandbox' has no attribute {name!r}")
