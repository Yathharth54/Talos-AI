"""The fake graph's tool sources are the demo's, byte for byte."""

from __future__ import annotations

import re

from talos.web.demo_sources import (
    CAESAR,
    CAESAR_BAD_LINE,
    CAESAR_BAD_SOURCE,
    CAESAR_SOURCE,
    WEATHER,
    WEATHER_SOURCE,
)
from tests.web.test_copy import REFERENCE


def script(block_id: str) -> str:
    text = REFERENCE.read_text(encoding="utf-8")
    pattern = rf'<script type="text/plain" id="{block_id}">(.*?)</script>'
    return re.search(pattern, text, re.S).group(1)


def test_sources_match_the_reference_blocks():
    assert CAESAR_SOURCE == script("src-caesar")
    assert WEATHER_SOURCE == script("src-weather")


def test_the_bad_attempt_differs_only_on_line_48():
    good, bad = CAESAR_SOURCE.split("\n"), CAESAR_BAD_SOURCE.split("\n")
    assert len(good) == len(bad) == 63
    diff = [i + 1 for i, (a, b) in enumerate(zip(good, bad, strict=True)) if a != b]
    assert diff == [CAESAR_BAD_LINE] == [48]
    assert bad[47] == "    effective_shift = shift"


def test_the_caesar_source_really_works():
    namespace: dict = {}
    exec(CAESAR_SOURCE, namespace)
    assert namespace["caesar_cipher"](text="TALOS AGENT", shift=7, mode="encrypt") == "AHSVZ HNLUA"


def test_metadata_matches_the_demo_constants():
    text = REFERENCE.read_text(encoding="utf-8")
    for meta in (CAESAR, WEATHER):
        assert f'name: "{meta["name"]}", args: "{meta["args"]}", ret: "{meta["ret"]}"' in text
    assert WEATHER["env"] == "OPENWEATHERMAP_API_KEY"
