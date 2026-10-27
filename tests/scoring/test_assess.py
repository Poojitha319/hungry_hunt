from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from hungry_hunt.config import Settings
from hungry_hunt.core.schemas import AssessmentOut
from hungry_hunt.db import Base, make_engine, session_factory
from hungry_hunt.db.models import Assessment, Company, Job, Profile, Run
from hungry_hunt.scoring import assess
from hungry_hunt.scoring.gemini import QuotaExhausted

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)
GOOD = "Join our backend team. We need 0-2 years of experience with Python. Bangalore office."


def mk_company(session, slug, **kw):
    c = Company(user_id="u", ats="lever", slug=slug, name=slug, **kw)
    session.add(c)
    session.flush()
    return c


def mk_job(
    session,
    company,
    eid,
    title="Software Engineer",
    desc=GOOD,
    loc="Bangalore, India",
    india=True,
    remote=False,
    age_h=1,
):
    j = Job(
        company_id=company.id,
        external_id=eid,
        title=title,
        location_raw=loc,
        is_india=india,
        is_remote=remote,
        url=f"https://x/{eid}",
        first_seen=NOW - timedelta(hours=age_h),
        last_seen=NOW,
        description=desc,
        content_hash=f"h-{eid}-{len(desc or '')}",
    )
    session.add(j)
    session.flush()
    return j


def mk_profile(session, version="v1"):
    p = Profile(
        user_id="u",
        resume_version=version,
        resume_text="Asha. Python, FastAPI, PostgreSQL, Docker. 0.9 years.",
        skills=["Python", "FastAPI"],
        years_experience=0.9,
        max_years_bar=2,
        excluded_titles=["Android"],
        updated_at=NOW,
    )
    session.add(p)
    session.flush()
    return p


def rows(session):
    return {session.get(Job, a.job_id).external_id: a for a in session.scalars(select(Assessment))}


def test_run_rules_tags_every_failure_reason(session):
    p = mk_profile(session)
    good = mk_company(session, "good", kind="product")
    mk_job(session, good, "ok")
    mk_job(session, good, "senior", title="Senior Software Engineer")
    mk_job(session, good, "years", desc="You have 4+ years of experience shipping services.")
    mk_job(session, good, "blank_noindia", loc="", india=False, desc="We need 1 year of experience. Office in Berlin.")
    mk_job(session, good, "blank_india", loc="", india=False, desc="1-2 years of experience. Based in Bengaluru.")
    mk_job(session, good, "excluded", title="Android Software Engineer")
    mk_job(session, mk_company(session, "svc", kind="service"), "svc1")
    mk_job(session, mk_company(session, "bad", status="avoid", kind="product"), "avoid1")
    assert assess.run_rules(session, Settings(user_id="u"), p, NOW) == 8
    a = rows(session)
    assert a["ok"].passed_rules and a["ok"].rule_fails == [] and (a["ok"].min_years, a["ok"].max_years) == (0, 2)
    assert a["ok"].years_evidence.startswith("We need 0-2 years")
    assert a["senior"].rule_fails == ["senior"] and a["senior"].is_senior
    assert a["years"].rule_fails == ["years>bar"] and a["years"].min_years == 4
    assert a["blank_noindia"].rule_fails == ["location"]
    assert a["blank_india"].passed_rules
    assert a["excluded"].rule_fails == ["excluded_title"]
    assert a["svc1"].rule_fails == ["service_company"]
    assert a["avoid1"].rule_fails == ["avoid_company"]
    assert all(x.verdict is None and x.resume_version == "v1" for x in a.values())


def test_run_rules_idempotent_and_rescored_on_content_change(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    j = mk_job(session, c, "a")
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    a = rows(session)["a"]
    a.verdict, a.fit_score = "apply", 80
    session.flush()
    assert assess.run_rules(session, Settings(user_id="u"), p, NOW) == 0
    assert rows(session)["a"].verdict == "apply"
    j.description, j.content_hash = "Requires 5+ years of experience.", "changed"
    session.flush()
    assert assess.run_rules(session, Settings(user_id="u"), p, NOW) == 1
    a = rows(session)["a"]
    assert (
        a.verdict is None
        and a.fit_score is None
        and a.rule_fails == ["years>bar"]
        and a.content_hash.startswith("changed|r")
    )
    assert session.scalar(select(Assessment).where(Assessment.job_id == j.id)) is a


def out(**kw):
    base = dict(
        fit_score=75,
        verdict="apply",
        matched_skills=["Python", "Kubernetes"],
        missing_skills=["Go"],
        min_years=None,
        max_years=None,
        years_evidence=None,
        is_engineering=True,
        is_senior=False,
        reason="Good overlap.",
    )
    return AssessmentOut(**{**base, **kw})


class FakeLLM:
    def __init__(self, results=None, errors=()):
        self.results, self.errors, self.calls = results or {}, list(errors), []

    def assess(self, resume_text, profile_summary, company, tier, title, location, description):
        self.calls.append(title)
        if self.errors:
            raise self.errors.pop(0)
        r = self.results.get(title, out())
        if isinstance(r, Exception):
            raise r
        return r


def test_score_only_passed_described_unscored_newest_first_capped(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    for i, age in enumerate([5, 1, 3]):
        mk_job(session, c, f"j{i}", title=f"SDE {i}", age_h=age)
    mk_job(session, c, "nodesc", title="SDE nodesc", desc=None)
    mk_job(session, c, "senior", title="Senior SDE")
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    rows(session)["j2"].verdict = "review"
    session.flush()
    llm = FakeLLM()
    sleeps = []
    stats = assess.score(
        session, Settings(user_id="u", assess_max_calls=5, assess_interval_s=6.2), p, llm, NOW, sleep=sleeps.append
    )
    assert llm.calls == ["SDE 1", "SDE 0"]
    assert stats.calls == 2 and stats.scored == 2 and stats.quota_hit is False
    a = rows(session)["j1"]
    assert (a.fit_score, a.verdict, a.matched_skills, a.scored_at) == (75, "apply", ["Python"], NOW)
    assert len(sleeps) == 1 and 6.0 < sleeps[0] <= 6.2


def test_score_respects_cap(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    for i in range(4):
        mk_job(session, c, f"j{i}", title=f"SDE {i}")
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    stats = assess.score(session, Settings(user_id="u", assess_max_calls=2), p, FakeLLM(), NOW, sleep=lambda s: None)
    assert stats.calls == 2 and sum(a.verdict is None for a in rows(session).values()) == 2


def test_score_llm_years_apply_bar_only_with_verified_evidence(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    amb = "Experienced engineers wanted. Must have shipped 3+ production services."
    mk_job(session, c, "amb", title="SDE amb", desc=amb)
    mk_job(session, c, "amb2", title="SDE amb2", desc=amb)
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    llm = FakeLLM(
        {
            "SDE amb": out(min_years=5, years_evidence="Must have shipped 3+ production services."),
            "SDE amb2": out(min_years=5, years_evidence="made up sentence"),
        }
    )
    assess.score(session, Settings(user_id="u"), p, llm, NOW, sleep=lambda s: None)
    a = rows(session)
    assert (a["amb"].verdict, a["amb"].min_years, a["amb"].rule_fails) == ("skip", 5, ["years>bar(llm)"])
    assert (a["amb2"].verdict, a["amb2"].min_years, a["amb2"].years_evidence) == ("apply", None, None)


def test_score_stops_on_quota_after_one_retry(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    for i in range(3):
        mk_job(session, c, f"j{i}", title=f"SDE {i}", age_h=i)
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    llm = FakeLLM(errors=[QuotaExhausted("429"), QuotaExhausted("429")])
    sleeps = []
    stats = assess.score(session, Settings(user_id="u"), p, llm, NOW, sleep=sleeps.append)
    assert stats.quota_hit is True and stats.scored == 0 and llm.calls == ["SDE 0", "SDE 0"]
    assert 60 in sleeps
    assert all(a.verdict is None for a in rows(session).values())


def test_score_skips_invalid_output_and_continues(session):
    p = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    mk_job(session, c, "a", title="SDE a", age_h=1)
    mk_job(session, c, "b", title="SDE b", age_h=2)
    assess.run_rules(session, Settings(user_id="u"), p, NOW)
    llm = FakeLLM({"SDE a": ValueError("bad json")})
    stats = assess.score(session, Settings(user_id="u"), p, llm, NOW, sleep=lambda s: None)
    assert (stats.calls, stats.scored, stats.invalid) == (2, 1, 1)
    assert rows(session)["a"].verdict is None and rows(session)["b"].verdict == "apply"


def test_run_records_run_row_and_requires_profile():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with pytest.raises(assess.NoProfile):
        assess.run(sf, Settings(user_id="u"), FakeLLM(), now=NOW)
    with sf() as s:
        mk_profile(s)
        mk_job(s, mk_company(s, "c", kind="product"), "a", title="SDE a")
        s.commit()
    stats = assess.run(sf, Settings(user_id="u"), FakeLLM(), now=NOW, sleep=lambda s: None)
    assert stats.scored == 1
    with sf() as s:
        r = s.scalar(select(Run).where(Run.stage == "assess"))
        assert r.stats["scored"] == 1 and r.stats["rules_evaluated"] == 1


def test_summary_tells_the_model_the_preferred_roles(session):
    p = mk_profile(session)
    assert "preferred roles" not in assess._summary(p)
    p.target_titles = ["AI engineer", "backend"]
    assert "preferred roles: AI engineer, backend" in assess._summary(p)


def test_lowering_the_years_bar_re_evaluates_and_hides_two_plus_roles(session):
    p = mk_profile(session)
    c = mk_company(session, "hevodata")
    j = mk_job(session, c, "two", title="Software Engineer", desc="2+ years of experience with Python.")
    settings = Settings(user_id="u")
    assess.run_rules(session, settings, p, NOW)
    a = session.scalar(select(Assessment).where(Assessment.job_id == j.id))
    assert a.passed_rules is True and a.content_hash.endswith("|b2")
    a.fit_score, a.verdict, a.scored_at = 80, "apply", NOW
    p.max_years_bar = 1
    assert assess.run_rules(session, settings, p, NOW) == 1
    assert a.passed_rules is False and "years>bar" in a.rule_fails and a.content_hash.endswith("|b1")
    p.max_years_bar = 2
    assess.run_rules(session, settings, p, NOW)
    assert a.passed_rules is True and a.verdict is None


def test_lowering_the_bar_rescores_jobs_whose_years_came_from_the_model(session):
    p = mk_profile(session)
    c = mk_company(session, "hevodata")
    j = mk_job(session, c, "vague", title="Software Engineer", desc="Join our platform team. Python required.")
    settings = Settings(user_id="u")
    assess.run_rules(session, settings, p, NOW)
    a = session.scalar(select(Assessment).where(Assessment.job_id == j.id))
    assert a.min_years is None
    a.min_years, a.fit_score, a.verdict, a.scored_at = 2, 70, "review", NOW
    p.max_years_bar = 1
    assess.run_rules(session, settings, p, NOW)
    assert a.passed_rules is True and a.verdict is None and a.fit_score is None
