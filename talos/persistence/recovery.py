"""Startup recovery for runs a previous process left behind (spec 01 §7).

A run still `running` at startup belonged to a process that is gone, so it
can never finish: mark it failed and close its event stream. A run that is
`waiting` is paused at an interrupt whose checkpoint is in Postgres, so it
stays `waiting` and can still be resumed.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talos.persistence import repo
from talos.persistence.models import Run

log = logging.getLogger(__name__)

RECOVERY_ERROR = "The app stopped while this run was going."
RECOVERY_SUMMARY = "Failed"


async def recover_runs(db: AsyncSession) -> list[uuid.UUID]:
    """Fail every `running` run and append `error` + `run.finished` to each.

    Args:
        db: A session; the caller commits (e.g. `async with session_scope()`).

    Returns:
        The ids of the runs that were failed, oldest first.
    """
    stale = (
        await db.scalars(
            select(Run).where(Run.status == "running").order_by(Run.started_at).with_for_update()
        )
    ).all()
    for run in stale:
        await repo.set_run_status(
            db, run.id, "failed", error=RECOVERY_ERROR, summary=RECOVERY_SUMMARY
        )
        await repo.append_event(db, run.id, "error", {"message": RECOVERY_ERROR})
        await repo.append_event(
            db,
            run.id,
            "run.finished",
            {
                "status": "failed",
                "summary": RECOVERY_SUMMARY,
                "summary_gold": False,
                "forged": list(run.forged),
                "used": list(run.used),
            },
        )
    if stale:
        log.warning("marked %d interrupted run(s) as failed", len(stale))
    return [run.id for run in stale]
