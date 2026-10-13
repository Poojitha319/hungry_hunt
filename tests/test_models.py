from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from hunt.models import Application, Assessment, Company, Job


def test_schema_creates_all_tables(session):
    names = set(inspect(session.get_bind()).get_table_names())
    assert {"company", "job", "assessment", "delivery", "application", "profile", "run"} <= names


def test_company_unique_per_user_ats_slug(session):
    session.add_all([Company(user_id="u", ats="lever", slug="hevodata", name="Hevo"),
                     Company(user_id="u", ats="lever", slug="hevodata", name="Hevo again")])
    with pytest.raises(IntegrityError):
        session.flush()


def test_job_unique_per_company_external_id(session, company):
    now = datetime.now(UTC)
    session.add_all([Job(company_id=company.id, external_id="1", title="SDE I", url="u", first_seen=now, last_seen=now),
                     Job(company_id=company.id, external_id="1", title="SDE I", url="u", first_seen=now, last_seen=now)])
    with pytest.raises(IntegrityError):
        session.flush()


def test_assessment_unique_per_job_resume_version(session, job):
    session.add_all([Assessment(job_id=job.id, resume_version="v1", content_hash="h", passed_rules=True),
                     Assessment(job_id=job.id, resume_version="v1", content_hash="h", passed_rules=True)])
    with pytest.raises(IntegrityError):
        session.flush()


def test_application_unique_per_job_user(session, job):
    now = datetime.now(UTC)
    session.add_all([Application(job_id=job.id, user_id="u", status="applied", updated_at=now),
                     Application(job_id=job.id, user_id="u", status="skipped", updated_at=now)])
    with pytest.raises(IntegrityError):
        session.flush()
