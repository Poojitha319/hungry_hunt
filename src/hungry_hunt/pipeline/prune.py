"""Deletes long-closed jobs, stale descriptions and old run rows."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, Result, delete, select, update
from sqlalchemy.orm import Session

from hungry_hunt.db.models import Application, Assessment, Delivery, Job, Run

DELETE_CLOSED_AFTER = timedelta(days=90)
CLEAR_DESCRIPTION_AFTER = timedelta(days=7)
KEEP_RUNS = timedelta(days=180)


def _rowcount(result: Result) -> int:
    return cast(CursorResult, result).rowcount


@dataclass
class PruneStats:
    jobs_deleted: int = 0
    descriptions_cleared: int = 0
    runs_deleted: int = 0


def prune(session: Session, now: datetime) -> PruneStats:
    stats = PruneStats()
    with_application = select(Application.job_id)
    doomed = session.scalars(
        select(Job.id).where(Job.closed_at < now - DELETE_CLOSED_AFTER, Job.id.not_in(with_application))
    ).all()
    if doomed:
        for model in (Assessment, Delivery):
            session.execute(delete(model).where(model.job_id.in_(doomed)))
        stats.jobs_deleted = _rowcount(session.execute(delete(Job).where(Job.id.in_(doomed))))
    stats.descriptions_cleared = _rowcount(
        session.execute(
            update(Job)
            .where(Job.closed_at < now - CLEAR_DESCRIPTION_AFTER, Job.description.isnot(None))
            .values(description=None)
        )
    )
    stats.runs_deleted = _rowcount(session.execute(delete(Run).where(Run.started_at < now - KEEP_RUNS)))
    session.flush()
    session.expire_all()
    return stats
