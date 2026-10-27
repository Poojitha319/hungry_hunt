from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from hungry_hunt.db.models import Application, Assessment, Company, Delivery, Job, Run
from hungry_hunt.pipeline import prune

NOW = datetime(2026, 10, 7, 1, 30, tzinfo=UTC)


def mk_job(session, company, eid, closed_days=None, desc="d"):
    j = Job(
        company_id=company.id,
        external_id=eid,
        title="SDE",
        url="u",
        first_seen=NOW - timedelta(days=200),
        last_seen=NOW,
        closed_at=NOW - timedelta(days=closed_days) if closed_days is not None else None,
        description=desc,
    )
    session.add(j)
    session.flush()
    session.add(Assessment(job_id=j.id, resume_version="v1", content_hash="h", passed_rules=True))
    session.add(Delivery(job_id=j.id, user_id="u", digest_id="x", sent_at=NOW))
    session.flush()
    return j


def test_prune_deletes_old_closed_jobs_without_applications_and_cascades(session, company):
    old = mk_job(session, company, "old", closed_days=91)
    applied = mk_job(session, company, "applied", closed_days=200)
    session.add(Application(job_id=applied.id, user_id="u", status="applied", updated_at=NOW))
    recent = mk_job(session, company, "recent", closed_days=30)
    open_ = mk_job(session, company, "open")
    session.flush()
    stats = prune.prune(session, NOW)
    ids = {j.external_id for j in session.scalars(select(Job))}
    assert ids == {"applied", "recent", "open"} and stats.jobs_deleted == 1
    assert session.scalar(select(Assessment).where(Assessment.job_id == old.id)) is None
    assert session.scalar(select(Delivery).where(Delivery.job_id == old.id)) is None
    assert session.get(Job, recent.id).description is None and session.get(Job, applied.id).description is None
    assert session.get(Job, open_.id).description == "d" and stats.descriptions_cleared == 2


def test_prune_keeps_recently_closed_descriptions_and_trims_old_runs(session, company):
    mk_job(session, company, "fresh", closed_days=3)
    session.add_all(
        [
            Run(stage="fetch", started_at=NOW - timedelta(days=181), stats={}),
            Run(stage="fetch", started_at=NOW - timedelta(days=10), stats={}),
        ]
    )
    session.flush()
    stats = prune.prune(session, NOW)
    assert session.scalar(select(Job).where(Job.external_id == "fresh")).description == "d"
    assert (
        session.scalar(select(Run).where(Run.started_at < NOW - timedelta(days=180))) is None
        and stats.runs_deleted == 1
    )


def test_company_not_a_prune_target(session, company):
    prune.prune(session, NOW)
    assert session.get(Company, company.id) is not None
