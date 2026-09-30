"""The two tools the Workbench demo forges, verbatim from the reference demo.

The fake graph (TALOS_FAKE_GRAPH=1) "forges" these, and the translator
tests use them as the Forger's output. `tests/web/test_demo_sources.py`
checks they match the `<script type="text/plain">` blocks in
`docs/superpowers/specs/reference/workbench-demo/index.html`.
"""

from __future__ import annotations

CAESAR_SOURCE = '''"""Caesar cipher tool: shift-based encryption/decryption of text."""

import string


def caesar_cipher(text: str, shift: int, mode: str) -> str:
    """Encrypt or decrypt text with a Caesar cipher using the given shift.

    Each ASCII letter is rotated by ``shift`` positions within the alphabet
    (A-Z / a-z), preserving letter case. Non-alphabetic characters (spaces,
    digits, punctuation) are passed through unchanged. In ``"encrypt"`` mode
    letters move forward by ``shift``; in ``"decrypt"`` mode they move
    backward by the same amount. Shifts larger than 26 or negative are
    normalised modulo 26.

    Args:
        text: The input string to transform. Must be a ``str``.
        shift: The integer number of alphabet positions to rotate. May be
            negative or greater than 25; it is normalised modulo 26.
        mode: Either ``"encrypt"`` or ``"decrypt"`` (case-insensitive,
            surrounding whitespace ignored).

    Returns:
        The transformed string with the same length as ``text``.

    Raises:
        TypeError: If ``text`` or ``mode`` is not a ``str``, or ``shift`` is
            not an ``int`` (booleans are rejected).
        ValueError: If ``mode`` is not ``"encrypt"`` or ``"decrypt"``.

    Example:
        >>> caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")
        'AHSVZ HNLUA'
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}")
    if isinstance(shift, bool) or not isinstance(shift, int):
        raise TypeError(f"shift must be an int, got {type(shift).__name__}")
    if not isinstance(mode, str):
        raise TypeError(f"mode must be a str, got {type(mode).__name__}")

    normalized_mode = mode.strip().lower()
    if normalized_mode not in ("encrypt", "decrypt"):
        raise ValueError(
            f"mode must be 'encrypt' or 'decrypt', got {mode!r}"
        )

    effective_shift = shift if normalized_mode == "encrypt" else -shift
    effective_shift %= 26

    result_chars = []
    for char in text:
        if char in string.ascii_uppercase:
            base = ord("A")
        elif char in string.ascii_lowercase:
            base = ord("a")
        else:
            result_chars.append(char)
            continue
        rotated = (ord(char) - base + effective_shift) % 26 + base
        result_chars.append(chr(rotated))

    return "".join(result_chars)'''

WEATHER_SOURCE = '''"""Current temperature for a city from OpenWeatherMap."""

import os

import requests


def get_current_temperature(city: str) -> float:
    """Return the current temperature in Celsius for ``city``.

    Reads the API key from the OPENWEATHERMAP_API_KEY environment variable.

    Args:
        city: City name, for example "Mumbai".

    Returns:
        The current temperature in degrees Celsius.

    Raises:
        RuntimeError: If the API key is not set.
        ValueError: If the city is empty or not found.
    """
    key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not key:
        raise RuntimeError("OPENWEATHERMAP_API_KEY is not set")
    if not city.strip():
        raise ValueError("city must not be empty")
    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": city, "appid": key, "units": "metric"},
        timeout=10,
    )
    if resp.status_code == 404:
        raise ValueError(f"city not found: {city!r}")
    resp.raise_for_status()
    return float(resp.json()["main"]["temp"])'''

CAESAR = {
    "name": "caesar_cipher",
    "args": "text: str, shift: int, mode: str",
    "ret": "str",
    "description": (
        "Encrypts or decrypts a text string using a Caesar cipher with a given shift,"
        " preserving case and non-alphabetic characters."
    ),
    "keywords": ["caesar", "cipher", "encrypt", "decrypt", "shift", "text", "cryptography"],
}

WEATHER = {
    "name": "get_current_temperature",
    "args": "city: str",
    "ret": "float",
    "description": "Returns the current temperature in Celsius for a city from OpenWeatherMap.",
    "keywords": ["weather", "temperature", "openweathermap", "city", "celsius", "mumbai"],
    "env": "OPENWEATHERMAP_API_KEY",
}

# Attempt 1 of the Caesar forge: line 48 forgets to negate the shift for decrypt.
CAESAR_BAD_LINE = 48
CAESAR_BAD_SOURCE = "\n".join(
    "    effective_shift = shift" if i == CAESAR_BAD_LINE else line
    for i, line in enumerate(CAESAR_SOURCE.split("\n"), start=1)
)
