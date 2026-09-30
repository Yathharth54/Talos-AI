"""Log redaction for API key values (spec 02 §10)."""

from __future__ import annotations

import logging

from talos.web import security
from talos.web.runner import RunManager
from talos.web.schemas import ResumeIn
from talos.web.store import MemoryStore
from tests.web.stubs import ScriptDriver

KEY = "owm-" + "5b1d0c9e8a7f6e54"


def test_remembered_secrets_are_redacted_from_every_log_record(caplog):
    security.install_log_redaction()
    security.remember_secret(f"  {KEY}  ")
    caplog.set_level(logging.INFO)
    logging.getLogger("talos.anything").info("got key %s from the dialog", KEY)
    logging.getLogger("uvicorn.error").warning(f"body was {KEY}")
    assert KEY not in caplog.text
    assert caplog.text.count("[redacted]") == 2


def test_redaction_is_installed_once_and_ignores_short_values():
    security.install_log_redaction()
    factory = logging.getLogRecordFactory()
    security.install_log_redaction()
    assert logging.getLogRecordFactory() is factory
    security.remember_secret("abc")
    assert security.redact("abc") == "abc"


def test_resume_value_is_hidden_from_repr():
    assert KEY not in repr(ResumeIn(decision="save", value=KEY))


async def test_run_manager_itself_never_logs_the_value(caplog):
    caplog.set_level(logging.DEBUG)
    store = MemoryStore()
    manager = RunManager(store, ScriptDriver())
    session = await store.create_session()
    run_id = (await manager.start(session.id, "key")).run.id
    await manager.join(run_id)
    await manager.resume(run_id, "save", "zz-" + KEY)
    await manager.join(run_id)
    assert "zz-" + KEY not in caplog.text
    assert "zz-" + KEY not in str([e.data for e in await store.events_after(run_id)])
