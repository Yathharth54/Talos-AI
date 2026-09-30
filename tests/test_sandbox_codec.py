"""Tagged-JSON codec for the forged-tool sandbox (spec 03 §2.2)."""

from __future__ import annotations

import json

import pytest

from talos.sandbox.codec import decode, encode


def _round_trip(value):
    return decode(json.loads(json.dumps(encode(value))))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -7,
        2**53,
        -(2**53),
        1.5,
        "héllo",
        "",
        [1, "a", None],
        {"a": 1, "b": [1, 2]},
    ],
)
def test_json_native_values_pass_through_untagged(value):
    assert encode(value) == value
    assert _round_trip(value) == value


@pytest.mark.parametrize(
    ("value", "tag"),
    [
        ((1, "a"), "tuple"),
        ({1, 2, 3}, "set"),
        (frozenset({"x"}), "set"),
        (b"\x00\xffbytes", "bytes"),
        (2**53 + 1, "int"),
        (-(2**64), "int"),
        ({1: "one", 2: "two"}, "dict"),
        ({(1, 2): "pair"}, "dict"),
    ],
)
def test_tagged_types_round_trip(value, tag):
    encoded = encode(value)
    assert encoded["__t"] == tag
    out = _round_trip(value)
    assert out == (set(value) if isinstance(value, frozenset) else value)
    assert type(out) is (set if isinstance(value, frozenset) else type(value))


def test_big_int_travels_as_a_string():
    assert encode(10**30) == {"__t": "int", "v": str(10**30)}


def test_bytearray_decodes_to_bytes():
    assert _round_trip(bytearray(b"ab")) == b"ab"


def test_nested_structures_round_trip():
    value = {"rows": [(1, {2, 3}), {"k": b"v", "big": 2**70}], "map": {1: [(None,)]}}
    assert _round_trip(value) == value


def test_user_dict_with_a_tag_key_is_not_mistaken_for_a_tagged_value():
    value = {"__t": "tuple", "v": [1, 2]}
    assert _round_trip(value) == value


def test_unknown_objects_become_their_repr():
    class Thing:
        def __repr__(self) -> str:
            return "<Thing 1>"

    assert encode(Thing()) == {"__t": "repr", "v": "<Thing 1>"}
    assert _round_trip(Thing()) == "<Thing 1>"


def test_broken_repr_still_encodes():
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("no")

    assert encode(Broken()) == {"__t": "repr", "v": "<unrepresentable Broken>"}


def test_unknown_tag_is_rejected():
    with pytest.raises(ValueError, match="unknown tag"):
        decode({"__t": "pickle", "v": "gASV"})


def test_malformed_tagged_value_is_rejected():
    with pytest.raises(ValueError, match="malformed"):
        decode({"__t": "bytes", "v": "not base64!!"})
