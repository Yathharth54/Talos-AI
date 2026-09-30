"""Tagged-JSON codec for values crossing the sandbox boundary (spec 03 §2.2).

Both directions use it: the parent encodes a tool's arguments, the child
encodes the return value. Nothing is ever unpickled, so the worst a tool can
send back is data. Anything the codec does not know becomes its repr string.

This module must stay stdlib-only: the sandbox child imports it before it
runs untrusted code, and it should start fast.
"""

from __future__ import annotations

import base64
from typing import Any

TAG = "__t"

# Largest int a JSON reader that uses doubles can hold exactly (2**53).
_SAFE_INT = 2**53


def safe_repr(value: Any) -> str:
    """repr() that never raises: a tool's __repr__ may be broken on purpose."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 — any failure falls back to the type name
        return f"<unrepresentable {type(value).__name__}>"


def encode(value: Any) -> Any:
    """Turn a Python value into JSON-safe data.

    Args:
        value: Any Python value.

    Returns:
        JSON-native data. Tuples, sets, frozensets, bytes, ints beyond 2**53
        and dicts with non-str keys (or a "__t" key) use tagged forms; any
        other object becomes `{"__t": "repr", "v": repr(value)}`.
    """
    if value is None or isinstance(value, (bool, str, float)):
        return value
    if isinstance(value, int):
        if -_SAFE_INT <= value <= _SAFE_INT:
            return value
        return {TAG: "int", "v": str(value)}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, tuple):
        return {TAG: "tuple", "v": [encode(v) for v in value]}
    if isinstance(value, (set, frozenset)):
        return {TAG: "set", "v": [encode(v) for v in value]}
    if isinstance(value, (bytes, bytearray)):
        return {TAG: "bytes", "v": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value) and TAG not in value:
            return {k: encode(v) for k, v in value.items()}
        return {TAG: "dict", "v": [[encode(k), encode(v)] for k, v in value.items()]}
    return {TAG: "repr", "v": safe_repr(value)}


def _hashable(value: Any) -> Any:
    """Make a decoded value usable as a set member or dict key."""
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return safe_repr(value)
    return value


def decode(data: Any) -> Any:
    """Inverse of `encode`.

    Args:
        data: Parsed JSON produced by `encode`.

    Returns:
        The Python value. A `repr` tag decodes to its string.

    Raises:
        ValueError: On an unknown tag or a malformed tagged form.
    """
    if isinstance(data, list):
        return [decode(v) for v in data]
    if not isinstance(data, dict):
        return data
    if TAG not in data:
        return {k: decode(v) for k, v in data.items()}
    tag, payload = data.get(TAG), data.get("v")
    try:
        if tag == "int":
            return int(payload)
        if tag == "tuple":
            return tuple(decode(v) for v in payload)
        if tag == "set":
            return {_hashable(decode(v)) for v in payload}
        if tag == "bytes":
            return base64.b64decode(payload.encode("ascii"), validate=True)
        if tag == "dict":
            return {_hashable(decode(k)): decode(v) for k, v in payload}
        if tag == "repr":
            return str(payload)
    except (TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"malformed {tag!r} value: {e}") from e
    raise ValueError(f"unknown tag {tag!r}")
