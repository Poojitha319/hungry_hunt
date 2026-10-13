from datetime import UTC, datetime

from sqlalchemy import select

from hunt import copydb
from hunt.db import Base, make_engine, session_factory
from hunt.models import Application, Assessment, Company, Delivery, Job, Profile, Run, TrackedMail

NOW = datetime(2026, 10, 10, 2, 0, tzinfo=UTC)


def fill(sf):
    with sf() as s:
        s.add(Profile(user_id="u", resume_version="v1", resume_text="r", skills=["Python"], updated_at=NOW))
        c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo", dormant=False, last_relevant_at=NOW)
        s.add(c)
        s.flush()
        j = Job(company_id=c.id, external_id="1", title="SDE I", url="u", first_seen=NOW, last_seen=NOW, description="d", description_at=NOW, content_hash="h")
        s.add(j)
        s.flush()
        s.add_all([Assessment(job_id=j.id, resume_version="v1", content_hash="h|r5", passed_rules=True, rule_fails=[], fit_score=90, verdict="apply", matched_skills=["Python"]),
                   Delivery(job_id=j.id, user_id="u", digest_id="u:2026-10-10T07", sent_at=NOW, confirmed_at=NOW),
                   Application(job_id=j.id, user_id="u", status="applied", applied_at=NOW, updated_at=NOW),
                   TrackedMail(user_id="u", message_id="<m>", sender="x", subject="s", received_at=NOW, status="applied", job_id=j.id, company_id=c.id),
                   Run(stage="fetch", started_at=NOW, finished_at=NOW, stats={"boards_ok": 1})])
        s.commit()


def test_copy_moves_every_table_preserving_ids_and_links():
    src, dst = make_engine("sqlite://"), make_engine("sqlite://")
    Base.metadata.create_all(src)
    Base.metadata.create_all(dst)
    fill(session_factory(src))
    counts = copydb.copy(src, dst)
    assert {k: v for k, v in counts.items() if v} == {"profile": 1, "company": 1, "job": 1, "assessment": 1, "delivery": 1, "application": 1, "tracked_mail": 1, "run": 1}
    with session_factory(dst)() as s:
        j = s.scalar(select(Job))
        a = s.scalar(select(Assessment))
        assert (j.id, a.job_id, a.verdict, a.matched_skills, j.description_at) == (1, 1, "apply", ["Python"], NOW)
        assert s.scalar(select(Company)).last_relevant_at == NOW
        assert s.scalar(select(TrackedMail)).job_id == 1


def test_copy_is_idempotent_and_refuses_a_non_empty_target_unless_told():
    import pytest
    src, dst = make_engine("sqlite://"), make_engine("sqlite://")
    Base.metadata.create_all(src)
    Base.metadata.create_all(dst)
    fill(session_factory(src))
    copydb.copy(src, dst)
    with pytest.raises(copydb.TargetNotEmpty):
        copydb.copy(src, dst)
    counts = copydb.copy(src, dst, replace=True)
    assert counts["job"] == 1
    with session_factory(dst)() as s:
        assert len(s.scalars(select(Job)).all()) == 1


def test_copy_registers_tables_without_importing_models_elsewhere():
    import subprocess
    import sys
    src, dst = make_engine("sqlite:////tmp/hh_copy_src.db"), make_engine("sqlite:////tmp/hh_copy_dst.db")
    for e in (src, dst):
        Base.metadata.drop_all(e)
        Base.metadata.create_all(e)
    fill(session_factory(src))
    out = subprocess.run([sys.executable, "-m", "hunt.copydb", "sqlite:////tmp/hh_copy_src.db", "sqlite:////tmp/hh_copy_dst.db", "--replace"],
                         capture_output=True, text=True, check=True).stdout
    assert "job=1" in out and "company=1" in out


def test_copy_truncates_strings_to_the_target_column_length():
    src, dst = make_engine("sqlite://"), make_engine("sqlite://")
    Base.metadata.create_all(src)
    Base.metadata.create_all(dst)
    with session_factory(src)() as s:
        s.add(Company(user_id="u", ats="lever", slug="x", name="N" * 400))
        s.commit()
    copydb.copy(src, dst)
    with session_factory(dst)() as s:
        assert len(s.scalar(select(Company)).name) == 255
