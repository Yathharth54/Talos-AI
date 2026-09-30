"""Session names from the first query, and the demo's query routing.

`classify()` is the demo's `classify(q)` and `session_name()` its
`sessionName(kind, q)`, ported regex for regex. The fake graph routes with
`classify()` too.
"""

from __future__ import annotations

import re
from typing import Literal

QueryKind = Literal["chat", "caesar", "python", "weather", "vaultlist", "unknown"]

MAX_NAME = 80

_CHAT = re.compile(r"\b(what can you do|who are you|help me understand|how do you work)\b", re.I)
_CAESAR = re.compile(r"(caesar|cipher|\bencrypt|\bdecrypt)", re.I)
_PYTHON = re.compile(r"(python|print\s*\(|run this code|run the code)", re.I)
_WEATHER = re.compile(r"(openweather|weather|temperature)", re.I)
_VAULTLIST = re.compile(
    r"(how many tools|list (all )?(your|the) tools|in (your|the) (skill )?vault)", re.I
)
_CITY = re.compile(r"\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)")


def classify(query: str) -> QueryKind:
    """Route a query the way the demo does. First match wins."""
    if _CHAT.search(query):
        return "chat"
    if _CAESAR.search(query):
        return "caesar"
    if _PYTHON.search(query):
        return "python"
    if _WEATHER.search(query):
        return "weather"
    if _VAULTLIST.search(query):
        return "vaultlist"
    return "unknown"


def weather_city(query: str) -> str:
    """The city in "... in Mumbai." style queries, else Mumbai (the demo's default)."""
    match = _CITY.search(query)
    return match.group(1).strip() if match else "Mumbai"


def session_name(query: str) -> str:
    """A session's name from its first query (spec 02 §8).

    Args:
        query: The first message, already trimmed.

    Returns:
        At most 80 characters, e.g. "Caesar cipher" or "Weather in Pune".
    """
    kind = classify(query)
    if kind == "caesar":
        name = "Caesar cipher"
    elif kind == "python":
        name = "Running Python"
    elif kind == "weather":
        name = f"Weather in {weather_city(query)}"
    elif kind == "chat":
        name = "Getting to know Talos"
    elif kind == "vaultlist":
        name = "What's in the vault"
    else:
        words = " ".join(query.split()[:4])
        name = words[:1].upper() + words[1:]
    return name[:MAX_NAME] or "Session"
