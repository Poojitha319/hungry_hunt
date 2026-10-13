from datetime import UTC, datetime, timedelta

from hunt import digest
from hunt.config import Settings
from hunt.models import Application, Assessment, Company, Delivery, Job, Profile, Run

NOW = datetime(2026, 10, 7, 1, 30, tzinfo=UTC)
SETTINGS = Settings(user_id="u", review_base_url="https://hunt.pages.dev", review_token="tok", digest_max_jobs=120)


def mk_company(session, slug, **kw):
    c = Company(user_id="u", ats=kw.pop("ats", "lever"), slug=slug, name=kw.pop("name", slug.title()), **kw)
    session.add(c)
    session.flush()
    return c


def mk_job(session, company, eid, *, title="Software Engineer", india=True, remote=False, loc="Bangalore", desc="2 years of experience. Bengaluru.",
           age_h=1, closed=False, score=70, verdict="apply", passed=True, posted_days=1):
    j = Job(company_id=company.id, external_id=eid, title=title, location_raw=loc, is_india=india, is_remote=remote, url=f"https://apply/{eid}",
            posted_at=NOW - timedelta(days=posted_days), first_seen=NOW - timedelta(hours=age_h), last_seen=NOW,
            closed_at=NOW if closed else None, description=desc, content_hash="h")
    session.add(j)
    session.flush()
    session.add(Assessment(job_id=j.id, resume_version="v1", content_hash="h", passed_rules=passed, rule_fails=[] if passed else ["senior"],
                           min_years=0, max_years=2, years_evidence="2 years of experience", fit_score=score, verdict=verdict,
                           reason="Good fit." if verdict else None, scored_at=NOW if verdict else None))
    session.flush()
    return j


def mk_profile(session):
    session.add(Profile(user_id="u", resume_version="v1", resume_text="r", updated_at=NOW))
    session.flush()


def test_select_undelivered_applies_every_exclusion(session):
    mk_profile(session)
    c = mk_company(session, "good")
    mk_job(session, c, "keep")
    mk_job(session, c, "unscored", score=None, verdict=None)
    rolled = mk_job(session, c, "rolled")
    session.add(Delivery(job_id=rolled.id, user_id="u", digest_id="u:2026-10-06", sent_at=NOW - timedelta(days=1), confirmed_at=None, error="smtp"))
    delivered = mk_job(session, c, "delivered")
    session.add(Delivery(job_id=delivered.id, user_id="u", digest_id="u:2026-10-06", sent_at=NOW - timedelta(days=1), confirmed_at=NOW - timedelta(days=1)))
    skipped = mk_job(session, c, "skipped")
    session.add(Application(job_id=skipped.id, user_id="u", status="skipped", updated_at=NOW))
    mk_job(session, c, "closed", closed=True)
    mk_job(session, c, "skipverdict", verdict="skip", score=20)
    mk_job(session, c, "failed", passed=False, verdict=None, score=None)
    mk_job(session, mk_company(session, "bad", status="avoid"), "avoided")
    session.flush()
    ids = {j.external_id for j, _, _ in digest.select_undelivered(session, "u", "v1")}
    assert ids == {"keep", "unscored", "rolled"}


def test_build_groups_sections_orders_and_links(session):
    mk_profile(session)
    c = mk_company(session, "hevodata", name="Hevo Data", tier="mid")
    mk_job(session, c, "new_lo", title="SDE I", score=60, verdict="review", age_h=2)
    mk_job(session, c, "new_hi", title="Associate SDE", score=90, age_h=3)
    mk_job(session, c, "old", title="Backend Engineer", age_h=30)
    mk_job(session, c, "remote_in", title="Platform Engineer", india=False, remote=True, loc="Remote", desc="Remote within India. 1-2 years of experience.")
    mk_job(session, c, "stretch", title="Infra Engineer", india=False, remote=True, loc="Remote", desc="Anywhere. 1-2 years of experience.")
    mk_job(session, c, "unscored", title="SDE unscored", score=None, verdict=None)
    d = digest.build(session, SETTINGS, NOW)
    assert d.digest_id == "u:2026-10-07T07" and str(d.date_ist) == "2026-10-07"
    assert [j.title for j in d.new["India"]] == ["Associate SDE", "SDE I"]
    assert [j.title for j in d.new["Remote"]] == ["Platform Engineer"]
    assert [j.title for j in d.new["Stretch"]] == ["Infra Engineer"]
    assert [j.title for j in d.carried["India"]] == ["Backend Engineer"]
    assert [j.title for j in d.unscored] == ["SDE unscored"]
    hi = d.new["India"][0]
    assert hi.url == "https://apply/new_hi" and hi.review_url.startswith("https://hunt.pages.dev/job/") and hi.review_url.endswith("?t=tok")
    assert (hi.company, hi.tier, hi.score, hi.verdict, hi.is_new, hi.posted_age_days) == ("Hevo Data", "mid", 90, "apply", True, 1)
    assert hi.years_evidence == "2 years of experience"
    assert d.truncated == 0


def test_build_caps_and_reports_truncation(session):
    mk_profile(session)
    c = mk_company(session, "c")
    for i in range(7):
        mk_job(session, c, f"j{i}", score=50 + i)
    d = digest.build(session, Settings(user_id="u", digest_max_jobs=5), NOW)
    assert sum(len(v) for v in d.new.values()) == 5 and d.truncated == 2
    assert [j.score for j in d.new["India"]] == [56, 55, 54, 53, 52]


def test_build_coverage_from_todays_runs_and_registry(session):
    mk_profile(session)
    mk_company(session, "cashfree", ats="unsupported", status="target", notes="Kula ATS", name="Cashfree")
    mk_company(session, "postman", ats="unsupported", status="target", notes="Workday", name="Postman")
    mk_company(session, "ignored", ats="unsupported", status="avoid", name="Ignored")
    mk_company(session, "stale", ats="lever", status="target", name="Stale Co", last_ok=NOW - timedelta(days=5))
    mk_company(session, "fresh", ats="lever", status="target", name="Fresh Co", last_ok=NOW - timedelta(hours=3))
    mk_company(session, "never", ats="greenhouse", status="watch", name="Never Co", last_ok=None, fail_count=2)
    mk_company(session, "svc", ats="lever", kind="service", name="Svc")
    session.add(Run(stage="fetch", started_at=NOW - timedelta(minutes=20), finished_at=NOW, stats={"boards_total": 40, "boards_ok": 38, "boards_failed": 2, "jobs_new": 7, "lever_boards": 12}))
    session.add(Run(stage="assess", started_at=NOW - timedelta(minutes=5), finished_at=NOW, stats={"calls": 9, "scored": 8, "quota_hit": True, "rules_evaluated": 30}))
    session.add(Run(stage="fetch", started_at=NOW - timedelta(days=1), finished_at=NOW - timedelta(days=1), stats={"boards_total": 1}))
    session.flush()
    cov = digest.build(session, SETTINGS, NOW).coverage
    assert (cov.boards_total, cov.boards_ok, cov.boards_failed, cov.jobs_new, cov.lever_boards) == (40, 38, 2, 7, 12)
    assert (cov.gemini_calls, cov.quota_hit, cov.stats_available) == (9, True, True)
    assert cov.blind_spots == ["Cashfree (Kula ATS)", "Postman (Workday)"]
    assert cov.stale_targets == ["Never Co", "Stale Co"]
    assert cov.service_auto == 1


def test_build_without_runs_marks_stats_unavailable(session):
    mk_profile(session)
    cov = digest.build(session, SETTINGS, NOW).coverage
    assert cov.stats_available is False


def test_render_contains_jobs_links_evidence_and_footer(session):
    mk_profile(session)
    c = mk_company(session, "hevodata", name="Hevo Data", tier="mid")
    mk_job(session, c, "a", title="SDE I")
    mk_job(session, c, "u", title="SDE unscored", score=None, verdict=None)
    mk_company(session, "cashfree", ats="unsupported", status="target", notes="Kula ATS", name="Cashfree")
    session.add(Run(stage="fetch", started_at=NOW, finished_at=NOW, stats={"boards_total": 3, "boards_ok": 3, "jobs_new": 2, "lever_boards": 1}))
    session.flush()
    d = digest.build(session, SETTINGS, NOW)
    subject, html = digest.render(d, SETTINGS)
    assert "1 new" in subject and "2026-10-07" in subject
    for s in ("Hevo Data", "SDE I", "https://apply/a", "https://hunt.pages.dev/job/", "2 years of experience", "Good fit.",
              "Unscored", "SDE unscored", "Cashfree (Kula ATS)", "Boards: 3 fetched", "Lever boards: 1"):
        assert s in html, s
    assert "<script" not in html


def test_render_empty_digest_says_zero_and_still_shows_coverage(session):
    mk_profile(session)
    d = digest.build(session, SETTINGS, NOW)
    subject, html = digest.render(d, SETTINGS)
    assert "0 new" in subject and "No genuine openings today" in html and "stats unavailable" in html


def test_preferred_roles_rank_with_junior_titles(session):
    from hunt.models import Profile
    mk_profile(session)
    session.get(Profile, SETTINGS.user_id).target_titles = ["AI engineer", "LLM"]
    c = mk_company(session, "hevodata", name="Hevo Data", tier="mid")
    mk_job(session, c, "a", title="Backend Engineer", score=80, age_h=2)
    mk_job(session, c, "b", title="AI Engineer", score=70, age_h=2)
    mk_job(session, c, "c", title="Associate SDE", score=90, age_h=2)
    d = digest.build(session, SETTINGS, NOW)
    assert [j.title for j in d.new["India"]] == ["Associate SDE", "AI Engineer", "Backend Engineer"]
