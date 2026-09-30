"""MemoryStore obeys the Store contract (the Postgres run is in tests/integration)."""

from __future__ import annotations

import pytest

from talos.web.store import MemoryStore
from tests.web.store_contract import CONTRACT


@pytest.mark.parametrize("case", CONTRACT, ids=lambda f: f.__name__)
async def test_memory_store(case):
    await case(MemoryStore())
