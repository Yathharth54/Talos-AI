"""SandboxedTool: a callable stand-in for a forged tool that never runs its
code in this process.

The executor and the smoke gate inspect a tool's signature (argument names,
type hints, defaults) to coerce and validate arguments before calling it.
`SandboxedTool` reads that signature from the source with `ast`, without
executing anything, and each call goes through `run_tool` in a subprocess.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

from talos.sandbox.runner import ToolResult, run_tool


class ToolFailed(Exception):
    """A sandboxed call raised, timed out or crashed.

    `str(exc)` is the tool's error text (`"TypeError: …"`), which callers
    record as-is instead of wrapping it in `ToolFailed: …`.
    """

    def __init__(self, result: ToolResult) -> None:
        super().__init__(result.error or "SandboxError: tool failed")
        self.result = result


def error_text(exc: BaseException) -> str:
    """The error string recorded for a failed tool call.

    `ToolFailed` already carries the tool's own `"TypeError: …"` text; any
    other exception is formatted the same way.
    """
    if isinstance(exc, ToolFailed):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


class _Unevaluated:
    """Default value that isn't a literal (e.g. `x=len`). Only its presence
    matters to callers; the child evaluates the real default."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _annotation(node: ast.expr | None) -> Any:
    return inspect.Parameter.empty if node is None else ast.unparse(node)


def _default(node: ast.expr | None) -> Any:
    if node is None:
        return inspect.Parameter.empty
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return _Unevaluated(ast.unparse(node))


def _signature_of_def(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> inspect.Signature:
    a = fn.args
    P = inspect.Parameter
    params: list[inspect.Parameter] = []
    positional = [*a.posonlyargs, *a.args]
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for i, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        kind = P.POSITIONAL_ONLY if i < len(a.posonlyargs) else P.POSITIONAL_OR_KEYWORD
        params.append(
            P(arg.arg, kind, default=_default(default), annotation=_annotation(arg.annotation))
        )
    if a.vararg:
        params.append(
            P(a.vararg.arg, P.VAR_POSITIONAL, annotation=_annotation(a.vararg.annotation))
        )
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        params.append(
            P(
                arg.arg,
                P.KEYWORD_ONLY,
                default=_default(default),
                annotation=_annotation(arg.annotation),
            )
        )
    if a.kwarg:
        params.append(P(a.kwarg.arg, P.VAR_KEYWORD, annotation=_annotation(a.kwarg.annotation)))
    return inspect.Signature(params, return_annotation=_annotation(fn.returns))


_OPEN_SIGNATURE = inspect.Signature(
    [
        inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL),
        inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
    ]
)


def signature_from_source(source: str, function: str) -> inspect.Signature:
    """Read `function`'s signature from Python source without running it.

    Args:
        source: The tool file's text.
        function: The top-level function name.

    Returns:
        The signature, with annotations as source strings (`"int"`,
        `"list[str]"`). A name bound some other way at top level (e.g.
        `f = make_f()`) gets an open `(*args, **kwargs)` signature.

    Raises:
        ValueError: If the source doesn't parse or doesn't define `function`.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"SyntaxError: {e}") from e
    found: inspect.Signature | None = None
    for node in tree.body:  # the last top-level binding wins, as at runtime
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            found = _signature_of_def(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == function for t in targets):
                found = _OPEN_SIGNATURE
    if found is None:
        raise ValueError(f"source defines no function {function!r}")
    return found


class SandboxedTool:
    """Callable proxy for a tool file; every call runs in a subprocess.

    `inspect.signature(tool)` returns the signature parsed from the source,
    and `tool.__name__` is the function name, so code written for plain
    functions (coercion, validation, `describe_args`) keeps working.
    """

    def __init__(self, source_path: Path, function: str, timeout: float | None = None) -> None:
        """Parse the tool's signature.

        Args:
            source_path: The tool's .py file.
            function: The function to call in it.
            timeout: Per-call limit; None means `settings.TOOL_TIMEOUT`.

        Raises:
            ValueError: If the file can't be read, doesn't parse, or doesn't
                define `function`.
        """
        self.source_path = Path(source_path)
        self.function = function
        self.timeout = timeout
        try:
            source = self.source_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"cannot read tool file {self.source_path}: {e}") from e
        self.__signature__ = signature_from_source(source, function)
        self.__name__ = function

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the tool in the sandbox.

        Returns:
            The tool's decoded return value.

        Raises:
            ToolFailed: If the tool raised, timed out or crashed.
        """
        result = run_tool(self.source_path, self.function, list(args), kwargs, self.timeout)
        if not result.ok:
            raise ToolFailed(result)
        return result.value

    def __repr__(self) -> str:
        return f"<SandboxedTool {self.function} from {self.source_path.name}>"
