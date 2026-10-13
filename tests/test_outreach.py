import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from hunt import outreach
from hunt.config import Settings
from hunt.db import Base, make_engine, session_factory
from hunt.models import Assessment, Company, Job, Outreach, Profile
from hunt.schemas import OutreachOut

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
RESUME = "Sai Poojitha. Backend Engineer at Quantum Gandiva AI (Nov 2025-present). Python, FastAPI, PostgreSQL, Redis Streams, Docker, AWS. Built a multi-agent AI platform."


def out(**kw):
    base = dict(note="Hi — I applied for the SDE I role at Hevo Data today. I build FastAPI services with PostgreSQL and Redis Streams at Quantum Gandiva AI and would love 5 minutes of your advice on the backend team.",
                referral_ask="Would you be open to referring me for the SDE I role? I've applied already and can share my resume.",
                who_to_contact="A backend engineer or engineering manager at Hevo Data; the recruiter named on the posting if any.",
                subject="SDE I application — quick question")
    return OutreachOut(**{**base, **kw})


class FakeLLM:
    def __init__(self, result=None):
        self.result, self.calls = result or out(), []

    def draft_outreach(self, resume_text, company, title, description, url):
        self.calls.append((company, title))
        return self.result


def seed(session):
    session.add(Profile(user_id="u", resume_version="v1", resume_text=RESUME, updated_at=NOW))
    c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data")
    session.add(c)
    session.flush()
    j = Job(company_id=c.id, external_id="1", title="SDE I", url="https://jobs.lever.co/hevodata/1", first_seen=NOW, last_seen=NOW,
            description="SDE I at Hevo Data. 0-1 years. Python, Java, REST APIs, data pipelines.")
    session.add(j)
    session.flush()
    session.add(Assessment(job_id=j.id, resume_version="v1", content_hash="h", passed_rules=True, fit_score=90, verdict="apply", matched_skills=["Python"]))
    session.flush()
    return j


def test_draft_grounds_in_resume_and_posting_and_caches(session):
    j = seed(session)
    llm = FakeLLM()
    first = outreach.draft(session, Settings(user_id="u"), llm, j.id, NOW)
    assert first.note.startswith("Hi") and "Hevo Data" in first.note
    assert llm.calls == [("Hevo Data", "SDE I")]
    second = outreach.draft(session, Settings(user_id="u"), llm, j.id, NOW)
    assert second.note == first.note and len(llm.calls) == 1
    row = session.scalar(select(Outreach).where(Outreach.job_id == j.id))
    assert row.resume_version == "v1" and json.loads(row.payload)["subject"] == "SDE I application — quick question"


def test_draft_rejects_claims_not_in_resume():
    bad = out(note="I have 5 years of Kubernetes experience and led a team of 10 at Google; I applied to Hevo Data.")
    v = outreach.validate(bad, RESUME, "Hevo Data")
    assert v.flags and any("Kubernetes" in f or "Google" in f or "5 years" in f for f in v.flags)


def test_draft_prompt_forbids_fabrication_and_names_the_company():
    captured = {}

    class Spy:
        def generate(self, model, prompt, schema):
            captured["prompt"] = prompt
            return json.dumps(out().model_dump())

    from hunt.gemini import Gemini
    g = Gemini(api_key="k", model="m", client=Spy())
    r = g.draft_outreach(RESUME, "Hevo Data", "SDE I", "desc", "https://jobs.lever.co/hevodata/1")
    assert r.note and "only" in captured["prompt"].lower() and "Hevo Data" in captured["prompt"] and "never" in captured["prompt"].lower()


def test_api_returns_draft_and_regenerates_on_demand(tmp_path):
    from web.api.app import create_app
    settings = Settings(database_url=f"sqlite:///{tmp_path}/h.db", user_id="u", review_token="t")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        j = seed(s)
        s.commit()
        job_id = j.id
    llm = FakeLLM()
    client = TestClient(create_app(settings, sf, now=lambda: NOW, llm=llm))
    r = client.post(f"/api/jobs/{job_id}/outreach", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200 and r.json()["note"].startswith("Hi") and r.json()["flags"] == []
    r2 = client.post(f"/api/jobs/{job_id}/outreach", headers={"Authorization": "Bearer t"})
    assert len(llm.calls) == 1 and r2.json()["note"] == r.json()["note"]
    r3 = client.post(f"/api/jobs/{job_id}/outreach?regenerate=true", headers={"Authorization": "Bearer t"})
    assert len(llm.calls) == 2 and r3.status_code == 200
    assert client.get(f"/api/jobs/{job_id}/outreach", headers={"Authorization": "Bearer t"}).json()["note"] == r3.json()["note"]
    assert client.get("/api/jobs/999/outreach", headers={"Authorization": "Bearer t"}).status_code == 404


def test_validate_ignores_sentence_initial_words_but_flags_real_names():
    v = outreach.validate(out(note="Given my experience with Python at Quantum Gandiva AI, I applied to Hevo Data. Thanks for reading. Previously I led the Kubernetes migration at Google."), RESUME, "Hevo Data", "SDE I")
    assert not any("'Given'" in f or "'Thanks'" in f or "'Previously'" in f for f in v.flags)
    assert any("Kubernetes" in f for f in v.flags) and any("Google" in f for f in v.flags)
