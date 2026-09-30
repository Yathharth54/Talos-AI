"""The integration gate: a plain `uv run pytest` never touches a database."""

from __future__ import annotations

import pytest

from tests.conftest import integration_skip_reason

URL = "postgresql+psycopg://talos:talos@localhost:55432/talos"


@pytest.mark.parametrize(
    ("url", "markexpr", "runs"),
    [
        ("", "", False),
        ("", "integration", False),
        (URL, "", False),
        (URL, "not integration", False),
        (URL, "not  integration", False),
        (URL, "integration", True),
        (URL, "integration and not slow", True),
    ],
)
def test_integration_skip_reason(url, markexpr, runs):
    assert (integration_skip_reason(url, markexpr) is None) is runs
