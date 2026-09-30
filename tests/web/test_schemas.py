"""Converters and request models (spec 02 §4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from talos.web.schemas import (
    MessageIn,
    RenameIn,
    ResumeIn,
    is_web_source,
    pending_payload,
    service_name,
    split_signature,
    vault_entry,
)


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        (
            "caesar_cipher(text: str, shift: int, mode: str) -> str",
            ("text: str, shift: int, mode: str", "str"),
        ),
        ("generate_uuid4() -> str", ("", "str")),
        (
            "hex_to_rgb(hex_code: str) -> tuple[int, int, int]",
            ("hex_code: str", "tuple[int, int, int]"),
        ),
        ("f(x)", ("x", "")),
        ("not a signature", ("", "")),
        ("", ("", "")),
    ],
)
def test_split_signature(signature, expected):
    assert split_signature(signature) == expected


def test_web_means_it_imports_an_http_library():
    assert is_web_source("import requests\n")
    assert is_web_source("from urllib.request import urlopen\n")
    assert is_web_source("    import httpx\n")
    assert not is_web_source("# requests are nice\nimport json\n")
    assert not is_web_source(None)


def test_vault_entry_maps_manifest_fields():
    entry = {
        "name": "slugify",
        "signature": "slugify(title: str) -> str",
        "description": "Slug it.",
        "keywords": ["slug"],
        "usage_count": 3,
        "failure_count": 1,
        "consecutive_failures": 1,
        "created_at": "2026-09-28T14:58:00+00:00",
        "last_used": None,
        "last_failure_reason": "TypeError: x",
        "last_failed_at": "2026-09-28T15:00:00+00:00",
        "file": "tools/slugify.py",
    }
    out = vault_entry(entry, "def slugify(title): ...").model_dump()
    assert out == {
        "name": "slugify",
        "args": "title: str",
        "ret": "str",
        "signature": "slugify(title: str) -> str",
        "description": "Slug it.",
        "keywords": ["slug"],
        "uses": 3,
        "failures": 1,
        "streak": 1,
        "created_at": "2026-09-28T14:58:00+00:00",
        "last_used": None,
        "last_failure": "TypeError: x",
        "last_failed_at": "2026-09-28T15:00:00+00:00",
        "web": False,
        "file": "tools/slugify.py",
    }
    assert vault_entry({"name": "x"}, None).file == "tools/x.py"


def test_service_names():
    assert service_name("OPENWEATHERMAP_API_KEY") == "OpenWeatherMap"
    assert service_name("GITHUB_TOKEN") == "GitHub"
    assert service_name("ACME_API_KEY") == "ACME_API_KEY"


def test_pending_payload_never_carries_code_args():
    confirm = {
        "type": "confirm_exec",
        "tool": "python_exec",
        "preview": "print(1)",
        "args": ["x"],
        "kwargs": {"code": "print(1)"},
        "message": "Allow it?",
    }
    assert pending_payload(confirm) == {"tool": "python_exec", "preview": "print(1)"}
    key = {"type": "missing_api_key", "env_var": "OPENWEATHERMAP_API_KEY", "tool_name": "t"}
    assert pending_payload(key) == {
        "env_var": "OPENWEATHERMAP_API_KEY",
        "tool_name": "t",
        "service": "OpenWeatherMap",
    }


def test_request_models_trim_and_bound():
    assert RenameIn(name="  Ciphers ").name == "Ciphers"
    assert MessageIn(text="  hi \n").text == "hi"
    for bad in ({"name": ""}, {"name": "x" * 81}):
        with pytest.raises(ValidationError):
            RenameIn(**bad)
    with pytest.raises(ValidationError):
        MessageIn(text="x" * 4001)
    with pytest.raises(ValidationError):
        ResumeIn(decision="maybe")
    assert "sk-123" not in repr(ResumeIn(decision="save", value="sk-123"))
