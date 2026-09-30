"""copy.py strings are the demo's strings, word for word (overview §4.5)."""

from __future__ import annotations

import re
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


# A fieldless string must be a whole JS string literal or a whole HTML text node.
_QUOTES = ('"', "'", "`")


def appears_whole(literal: str, text: str) -> bool:
    """`literal` is a whole quoted literal ("x", 'x', `x`) or a whole text node (>x<)."""
    if any(f"{q}{literal}{q}" in text for q in _QUOTES):
        return True
    return re.search(r">\s*" + re.escape(literal) + r"\s*<", text) is not None


def template_pattern(template: str) -> re.Pattern[str]:
    """Literal parts in order; each `{field}` matches `${...}` or any concrete text."""
    pattern = ""
    for text, field, *_ in string.Formatter().parse(template):
        pattern += re.escape(text)
        if field is not None:
            pattern += r"(?:\$\{[^}]*\}|[^\n]*?)"
    return re.compile(pattern)


def has_fields(template: str) -> bool:
    return any(field is not None for _, field, *_ in string.Formatter().parse(template))


@pytest.mark.parametrize("name", sorted(copy_templates()))
def test_every_copy_string_appears_verbatim_in_the_reference(name):
    template, text = copy_templates()[name], reference_text()
    if not template:
        return
    if has_fields(template):
        assert template_pattern(template).search(text), (
            f"{name}: {template!r} does not match the reference demo"
        )
    else:
        literal = "".join(literal_parts(template))
        assert appears_whole(literal, text), (
            f"{name}: {literal!r} is not a whole string or text node in the reference demo"
        )


def test_appears_whole_rejects_fragments():
    assert appears_whole("Saved", '<b>"Saved"</b>')
    assert appears_whole("Saved", "<b> Saved </b>")
    assert not appears_whole("Saved by", '"Saved by Human check this session."')


def test_template_fields_match_interpolations_or_text():
    pattern = template_pattern("Writing {tool} now")
    assert pattern.search("`Writing ${S.tool} now`")
    assert pattern.search('"Writing caesar_cipher now"')
    assert not pattern.search('"Writing\nnow"')


def test_key_saved_by_human_check_is_the_demo_sentence():
    assert copy.KEY_SAVED_BY_HUMAN_CHECK == "Saved by Human check this session."


def test_recovery_summary_matches_the_copy():
    assert RECOVERY_SUMMARY == copy.SUMMARY_FAILED


def test_join_words_matches_the_demo_style():
    assert copy.join_words([]) == ""
    assert copy.join_words(["caesar"]) == "caesar"
    assert copy.join_words(["caesar", "cipher"]) == "caesar and cipher"
    assert copy.join_words(["caesar", "cipher", "encrypt"]) == "caesar, cipher and encrypt"
