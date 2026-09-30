"""copy.py strings are the demo's strings, word for word (overview §4.5)."""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from talos.persistence.recovery import RECOVERY_SUMMARY
from talos.web import copy

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/specs/reference/workbench-demo/index.html"
)


def reference_text() -> str:
    """The demo source with JS string escapes undone (\\" → ", \\' → ')."""
    return REFERENCE.read_text(encoding="utf-8").replace('\\"', '"').replace("\\'", "'")


def literal_parts(template: str) -> list[str]:
    """The text between `{field}`s, e.g. "Writing {tool}" → ["Writing "]."""
    return [text for text, *_ in string.Formatter().parse(template) if text]


def copy_templates() -> dict[str, str]:
    """Every public copy string, flattened: constants, (label, text) pairs, dict values."""
    out: dict[str, str] = {}
    for name in dir(copy):
        if not name.isupper() or name == "NEW_COPY":
            continue
        value = getattr(copy, name)
        if isinstance(value, str):
            out[name] = value
        elif isinstance(value, tuple):
            for i, part in enumerate(value):
                out[f"{name}[{i}]"] = part
        elif isinstance(value, dict):
            for key, part in value.items():
                out[f"{name}[{key}]"] = part
    return out


def test_the_reference_file_is_present():
    assert REFERENCE.is_file(), REFERENCE


def test_there_is_copy_to_check():
    assert len(copy_templates()) > 100


@pytest.mark.parametrize("name", sorted(copy_templates()))
def test_every_copy_string_appears_verbatim_in_the_reference(name):
    text = reference_text()
    for part in literal_parts(copy_templates()[name]):
        assert part in text, f"{name}: {part!r} is not in the reference demo"


def test_recovery_summary_matches_the_copy():
    assert RECOVERY_SUMMARY == copy.SUMMARY_FAILED


def test_join_words_matches_the_demo_style():
    assert copy.join_words([]) == ""
    assert copy.join_words(["caesar"]) == "caesar"
    assert copy.join_words(["caesar", "cipher"]) == "caesar and cipher"
    assert copy.join_words(["caesar", "cipher", "encrypt"]) == "caesar, cipher and encrypt"
