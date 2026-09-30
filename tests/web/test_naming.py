"""Session naming and query routing mirror the demo (spec 02 §8)."""

from __future__ import annotations

import pytest

from talos.web.naming import classify, session_name, weather_city


@pytest.mark.parametrize(
    ("query", "name"),
    [
        ('Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.', "Caesar cipher"),
        ('Decrypt this message with shift 7: "AHSVZ HNLUA"', "Caesar cipher"),
        ("Run this Python code: print(sum(range(1, 101)))", "Running Python"),
        ("print(2 + 2) please", "Running Python"),
        (
            "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
            "Weather in Mumbai",
        ),
        ("What's the weather in New Delhi?", "Weather in New Delhi"),
        ("what's the weather like", "Weather in Mumbai"),
        ("What can you do?", "Getting to know Talos"),
        ("How many tools are in your vault?", "What's in the vault"),
        ("list the tools in the skill vault", "What's in the vault"),
        ("convert 5 km to miles and back", "Convert 5 km to"),
        ("  hello   there  ", "Hello there"),
    ],
)
def test_session_name(query, name):
    assert session_name(query.strip()) == name


def test_chat_wins_over_caesar_like_the_demo():
    assert classify("what can you do with a caesar cipher") == "chat"


def test_long_names_are_cut_to_80_characters():
    assert len(session_name("Supercalifragilistic" * 10)) == 80


def test_weather_city_defaults_to_mumbai():
    assert weather_city("weather please") == "Mumbai"
    assert weather_city("temperature in Pune.") == "Pune"


def test_unknown_queries_are_unknown():
    assert classify("sort these numbers") == "unknown"
