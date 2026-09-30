"""Caesar cipher tool: shift-based encryption/decryption of text."""

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
        raise ValueError(f"mode must be 'encrypt' or 'decrypt', got {mode!r}")

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

    return "".join(result_chars)
