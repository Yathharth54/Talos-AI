"""PgStore obeys the same Store contract as MemoryStore."""

from __future__ import annotations

import pytest

from talos.web.store import PgStore
from tests.web.store_contract import CONTRACT

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("case", CONTRACT, ids=lambda f: f.__name__)
async def test_pg_store(case, factory):
    await case(PgStore(factory))
