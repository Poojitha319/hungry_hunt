import os
from datetime import UTC, datetime

import pytest

from hunt.db import Base, make_engine, session_factory
from hunt.models import Company, Job


@pytest.fixture
def session():
    url = os.environ.get("HUNT_TEST_DATABASE_URL", "sqlite://")
    engine = make_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def company(session):
    c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data")
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def job(session, company):
    now = datetime.now(UTC)
    j = Job(company_id=company.id, external_id="x1", title="SDE I", url="https://jobs.lever.co/hevodata/x1",
            first_seen=now, last_seen=now)
    session.add(j)
    session.flush()
    return j


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    from hunt import http
    monkeypatch.setattr(http, "resolve", lambda host: {"93.184.216.34"})
