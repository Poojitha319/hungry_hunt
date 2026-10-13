from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hunt.config import Settings
from hunt.db import Base, make_engine, session_factory
from hunt.models import Application, Assessment, Company, Delivery, Job, Profile, Run
from web.api.app import create_app

NOW = datetime(2026, 10, 7, 1, 30, tzinfo=UTC)
TOKEN = "s3cret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/hunt.db", user_id="u", review_token=TOKEN, review_base_url="https://ui")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Profile(user_id="u", resume_version="v1", resume_text="r", updated_at=NOW))
        c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data", tier="mid", status="target", notes="")
        s.add(c)
        s.flush()
        j = Job(company_id=c.id, external_id="1", title="SDE I", location_raw="Bangalore", is_india=True, url="https://apply/1",
                posted_at=NOW - timedelta(days=1), first_seen=NOW - timedelta(hours=2), last_seen=NOW, description="0-2 years of experience.", content_hash="h")
        s.add(j)
        s.flush()
        s.add(Assessment(job_id=j.id, resume_version="v1", content_hash="h", passed_rules=True, rule_fails=[], min_years=0, max_years=2,
                         years_evidence="0-2 years of experience.", fit_score=88, verdict="apply", reason="Great fit.", scored_at=NOW,
                         matched_skills=["Python"], missing_skills=["Go"]))
        s.add(Run(stage="fetch", started_at=NOW - timedelta(minutes=10), finished_at=NOW, stats={"boards_total": 5, "boards_ok": 5, "jobs_new": 1, "lever_boards": 2}))
        s.commit()
        job_id, company_id = j.id, c.id
    app = create_app(settings, sf, now=lambda: NOW)
    client = TestClient(app)
    client.job_id, client.company_id, client.sf = job_id, company_id, sf
    return client


def test_health_is_public(api):
    assert api.get("/health").json() == {"ok": True}


def test_requires_token(api):
    assert api.get("/api/digest").status_code == 401
    assert api.get("/api/digest", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_token_accepted_as_bearer_or_query(api):
    assert api.get("/api/digest", headers=AUTH).status_code == 200
    assert api.get(f"/api/digest?t={TOKEN}").status_code == 200


def test_digest_payload_matches_schema(api):
    d = api.get("/api/digest", headers=AUTH).json()
    assert d["digest_id"] == "u:2026-10-07T07"
    (job,) = d["new"]["India"]
    assert (job["title"], job["company"], job["score"], job["verdict"]) == ("SDE I", "Hevo Data", 88, "apply")
    assert job["review_url"].startswith("https://ui/job/")
    assert d["coverage"]["boards_total"] == 5 and d["coverage"]["stats_available"] is True


def test_job_detail(api):
    r = api.get(f"/api/jobs/{api.job_id}", headers=AUTH).json()
    assert r["job"]["title"] == "SDE I" and r["job"]["description"].startswith("0-2 years")
    assert r["company"]["name"] == "Hevo Data" and r["assessment"]["matched_skills"] == ["Python"]
    assert r["application"] is None
    assert api.get("/api/jobs/999", headers=AUTH).status_code == 404


def test_status_upsert_sets_applied_at_once(api):
    r = api.post(f"/api/jobs/{api.job_id}/status", json={"status": "applied", "notes": "via careers page"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "applied" and r.json()["applied_at"] is not None
    first_applied = r.json()["applied_at"]
    r2 = api.post(f"/api/jobs/{api.job_id}/status", json={"status": "callback"}, headers=AUTH)
    assert r2.json()["status"] == "callback" and r2.json()["applied_at"] == first_applied and r2.json()["notes"] == "via careers page"
    with api.sf() as s:
        assert s.scalar(select(Application).where(Application.job_id == api.job_id)).status == "callback"
    assert api.post(f"/api/jobs/{api.job_id}/status", json={"status": "bogus"}, headers=AUTH).status_code == 422


def test_other_users_jobs_are_not_visible_or_writable(api):
    with api.sf() as s:
        other = Company(user_id="someone-else", ats="lever", slug="x", name="X")
        s.add(other)
        s.flush()
        j = Job(company_id=other.id, external_id="9", title="SDE", url="u", first_seen=NOW, last_seen=NOW)
        s.add(j)
        s.commit()
        foreign_id, foreign_company = j.id, other.id
    assert api.get(f"/api/jobs/{foreign_id}", headers=AUTH).status_code == 404
    assert api.post(f"/api/jobs/{foreign_id}/status", json={"status": "applied"}, headers=AUTH).status_code == 404
    assert api.post(f"/api/companies/{foreign_company}", json={"status": "avoid"}, headers=AUTH).status_code == 404
    with api.sf() as s:
        assert s.scalar(select(Application).where(Application.job_id == foreign_id)) is None


def test_skipped_job_leaves_the_digest(api):
    api.post(f"/api/jobs/{api.job_id}/status", json={"status": "skipped"}, headers=AUTH)
    d = api.get("/api/digest", headers=AUTH).json()
    assert d["new"]["India"] == []


def test_companies_list_and_update(api):
    rows = api.get("/api/companies?status=target", headers=AUTH).json()
    assert [c["name"] for c in rows] == ["Hevo Data"]
    r = api.post(f"/api/companies/{api.company_id}", json={"status": "avoid", "notes": "layoffs"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "avoid"
    assert api.get("/api/companies?status=target", headers=AUTH).json() == []
    assert api.get("/api/digest", headers=AUTH).json()["new"]["India"] == []


def test_coverage_history(api):
    rows = api.get("/api/coverage?days=7", headers=AUTH).json()
    assert rows[0]["stage"] == "fetch" and rows[0]["stats"]["boards_ok"] == 5


def test_delivered_jobs_still_visible_in_digest_history(api):
    with api.sf() as s:
        s.add(Delivery(job_id=api.job_id, user_id="u", digest_id="u:2026-10-07", sent_at=NOW, confirmed_at=NOW))
        s.commit()
    d = api.get("/api/digest?days=7", headers=AUTH).json()
    assert len(d["new"]["India"]) == 1


def test_add_company_from_slug_or_url_and_reject_junk(api):
    r = api.post("/api/companies", json={"text": "lever:acme", "status": "target", "notes": "referral"}, headers=AUTH)
    assert r.status_code == 201 and (r.json()["ats"], r.json()["slug"], r.json()["status"], r.json()["notes"]) == ("lever", "acme", "target", "referral")
    r2 = api.post("/api/companies", json={"text": "https://jobs.lever.co/acme/123"}, headers=AUTH)
    assert r2.status_code == 200 and r2.json()["id"] == r.json()["id"]
    assert api.post("/api/companies", json={"text": "https://example.com/about"}, headers=AUTH).status_code == 422
    assert api.post("/api/companies", json={"text": "careers:https://acme.example/jobs"}, headers=AUTH).status_code == 201
    with api.sf() as s:
        assert {c.slug for c in s.scalars(select(Company).where(Company.user_id == "u"))} >= {"acme", "https://acme.example/jobs"}


def test_companies_list_filters_and_search(api):
    with api.sf() as s:
        s.add_all([Company(user_id="u", ats="greenhouse", slug="infotech", name="XYZ Infotech", kind="service", tier="mid", status="watch"),
                   Company(user_id="u", ats="ashby", slug="zeta", name="Zeta", kind="product", tier="early_funded", status="watch"),
                   Company(user_id="u", ats="ashby", slug="bigco", name="BigCo", kind="product", tier="big_product", status="watch")])
        s.commit()
    names = lambda r: [c["name"] for c in r.json()]
    assert names(api.get("/api/companies?kind=product&tier=early_funded,mid", headers=AUTH)) == ["Zeta"]
    assert names(api.get("/api/companies?tier=mid", headers=AUTH)) == ["Hevo Data", "XYZ Infotech"]
    assert names(api.get("/api/companies?q=info", headers=AUTH)) == ["XYZ Infotech"]
    assert names(api.get("/api/companies?limit=2", headers=AUTH)) == ["BigCo", "Hevo Data"]
