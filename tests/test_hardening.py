from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from hunt import assess, ats, discover, fetch, gemini, http, rules
from hunt.config import Settings
from hunt.db import Base, make_engine, session_factory
from hunt.models import Application, Assessment, Company, Job, Profile, Run
from hunt.schemas import AssessmentOut
from tests.test_assess import FakeLLM, mk_company, mk_job, mk_profile, out, rows
from tests.test_fetch import FakeSource, p

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


# --- C2: one transient Gemini error must not discard the day's assessments ---

def test_score_counts_unexpected_llm_errors_and_continues(session):
    prof = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    mk_job(session, c, "a", title="SDE a", age_h=1)
    mk_job(session, c, "b", title="SDE b", age_h=2)
    assess.run_rules(session, Settings(user_id="u"), prof, NOW)
    llm = FakeLLM({"SDE a": RuntimeError("503 model overloaded")})
    stats = assess.score(session, Settings(user_id="u"), prof, llm, NOW, sleep=lambda s: None)
    assert (stats.calls, stats.scored, stats.errors) == (2, 1, 1)
    assert rows(session)["a"].verdict is None and rows(session)["b"].verdict == "apply"


def test_run_persists_rules_rows_even_if_scoring_crashes_hard():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        mk_profile(s)
        mk_job(s, mk_company(s, "c", kind="product"), "a", title="SDE a")
        s.commit()

    class Exploding:
        def assess(self, *a, **k):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        assess.run(sf, Settings(user_id="u"), Exploding(), now=NOW, sleep=lambda s: None)
    with sf() as s:
        assert s.scalar(select(Assessment)).passed_rules is True


def test_score_commits_partial_progress(session):
    prof = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    for i in range(12):
        mk_job(session, c, f"j{i}", title=f"Backend Developer #{i}", age_h=i)
    assess.run_rules(session, Settings(user_id="u"), prof, NOW)
    commits = []
    session.commit = lambda: commits.append(1)  # type: ignore[method-assign]
    assess.score(session, Settings(user_id="u"), prof, FakeLLM(), NOW, sleep=lambda s: None)
    assert len(commits) >= 2


# --- I8: Gemini's years reading never overrides a bar the rules already read ---

def test_validate_does_not_skip_when_rules_already_found_an_in_bar_requirement():
    v = gemini.validate(out(min_years=4, years_evidence="We need 2+ years of experience with Python and Go."),
                        "We need 2+ years of experience with Python and Go.", "Python FastAPI", max_years_bar=2, rules_min=0)
    assert v.verdict == "apply"


def test_validate_skips_only_when_rules_found_nothing():
    v = gemini.validate(out(min_years=4, years_evidence="We need 2+ years of experience with Python and Go."),
                        "We need 2+ years of experience with Python and Go.", "Python FastAPI", max_years_bar=2, rules_min=None)
    assert v.verdict == "skip"


def test_validate_truncates_long_reason_and_uses_word_boundaries_for_skills():
    raw = {**out().model_dump(), "reason": "x" * 400, "matched_skills": ["Go", "C", "Python"]}
    v = gemini.validate(AssessmentOut.model_validate(raw), "desc", "Good Python code", max_years_bar=2, rules_min=None)
    assert len(v.reason) == 200 and v.matched_skills == ["Python"]


# --- I6 / I7: rules false negatives ---

@pytest.mark.parametrize("text,mn,mx,ok", [
    ("Requires 1.5+ years of experience with Python.", 1.5, None, True),
    ("2.5 - 4 years of experience.", 2.5, 4, False),
    ("Our team brings 10+ years of experience in fintech. 0-2 years of experience required.", 0, 2, True),
    ("3 years of experience in backend development.", 3, None, False),
    ("At least 1 year of relevant experience.", 1, None, True),
])
def test_years_bar_decimals_blurbs_and_plain_phrasing(text, mn, mx, ok):
    y = rules.years_bar(text)
    assert (y.min, y.max) == (mn, mx)
    assert (y.min is None or y.min <= 2) is ok


@pytest.mark.parametrize("title", [
    "Software Engineer, Customer Platform", "Backend Engineer - Field Operations", "SDE 1 - Accounts Payable",
    "Software Engineer (Sales Platform)", "Software Engineer - Quality of Service", "Backend Engineer (Payments Support)",
    "Software Engineer - Analytics",
])
def test_engineering_titles_with_domain_words_are_engineering(title):
    assert rules.title_kind(title)[0] is True


@pytest.mark.parametrize("title", [
    "Support Engineer", "Technical Support Engineer", "Solutions Engineer", "Implementation Engineer", "Forward Deployed Engineer",
    "Sales Engineer", "QA Engineer", "Test Engineer", "Customer Success Engineer", "Field Engineer", "Account Executive",
    "Quality Engineer", "Software Engineer Intern", "Engineering Manager",
])
def test_non_engineering_roles_still_excluded(title):
    assert rules.title_kind(title)[0] is False


def test_run_rules_re_evaluates_when_rules_version_changes(session, monkeypatch):
    prof = mk_profile(session)
    mk_job(session, mk_company(session, "c", kind="product"), "a")
    assert assess.run_rules(session, Settings(user_id="u"), prof, NOW) == 1
    assert assess.run_rules(session, Settings(user_id="u"), prof, NOW) == 0
    monkeypatch.setattr(rules, "RULES_VERSION", rules.RULES_VERSION + 1)
    assert assess.run_rules(session, Settings(user_id="u"), prof, NOW) == 1


# --- C3 / I9: fetch robustness ---

def test_collect_drops_descriptions_that_can_never_be_used():
    import asyncio
    src = FakeSource({"x": [p("us", loc="Austin, TX", desc="long" * 100), p("sr", title="Senior Engineer", desc="long" * 100), p("ok")]})
    listing = asyncio.run(fetch.collect(Company(user_id="u", ats="lever", slug="x", name="x"), src))
    by = {q.external_id: q for q in listing.postings}
    assert by["us"].description is None and by["sr"].description is None and by["ok"].description


async def test_fetch_all_isolates_one_bad_board_with_a_savepoint(monkeypatch):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add_all([Company(user_id="u", ats="lever", slug="good", name="Good"), Company(user_id="u", ats="lever", slug="bad", name="Bad")])
        s.commit()
    real = fetch.apply_listing

    def exploding(session, company, postings, now, existing=None):
        if company.slug == "bad":
            raise RuntimeError("value too long for type character varying(512)")
        return real(session, company, postings, now, existing)

    monkeypatch.setattr(fetch, "apply_listing", exploding)
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), FakeSource({"good": [p("g1")], "bad": [p("b1")]}), now=NOW)
    assert (stats.boards_ok, stats.boards_failed, stats.jobs_new) == (1, 1, 1)
    with sf() as s:
        assert [j.external_id for j in s.scalars(select(Job))] == ["g1"]
        assert s.scalar(select(Run).where(Run.stage == "fetch")) is not None


def test_apply_listing_truncates_oversized_fields(session, company):
    fetch.apply_listing(session, company, [p("long", loc="Bengaluru / " * 80, title="T" * 1000)], NOW)
    j = session.scalar(select(Job))
    assert len(j.location_raw) <= 512 and len(j.title) <= 512 and j.is_india


# --- I4 / Neon URL ---

def test_settings_ignore_empty_env_values(monkeypatch):
    monkeypatch.setenv("USER_ID", "")
    monkeypatch.setenv("GEMINI_MODEL", "")
    s = Settings(_env_file=None)
    assert s.user_id == "poojitha" and s.gemini_model == "gemini-3.5-flash-lite"


def test_make_engine_normalizes_plain_postgres_urls():
    e = make_engine("postgresql://u:p@host-pooler.neon.tech/db?sslmode=require")
    assert e.dialect.driver == "psycopg"


# --- I5: blind spots and the careers probe ---

def test_blind_spots_include_unknown_ats_and_probe_marks_unsupported(session):
    from hunt import digest
    session.add(Profile(user_id="u", resume_version="v1", resume_text="r", updated_at=NOW))
    discover.upsert_companies(session, "u", [discover.Board(ats="unknown", slug="zerodha", name="Zerodha", board_url="https://zerodha.com/careers"),
                                             discover.Board(ats="unsupported", slug="cashfree", name="Cashfree", notes="Kula ATS", board_url="x")])
    cov = digest.build(session, Settings(user_id="u"), NOW).coverage
    assert cov.blind_spots == ["Cashfree (Kula ATS)", "Zerodha (hiring system unknown)"]


@respx.mock
async def test_careers_source_sets_unsupported_and_keeps_human_notes():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        discover.upsert_companies(s, "u", [discover.Board(ats="unknown", slug="postman", name="Postman", board_url="https://postman.com", notes="my note")])
        s.commit()
    respx.get(url__regex=r"https://postman\.com/.*").respond(text='<a href="https://postman.darwinbox.in/ms/candidate/careers">jobs</a>')
    async with httpx.AsyncClient() as client:
        await discover.discover(sf, Settings(user_id="u"), ["careers"], client)
    with sf() as s:
        c = s.scalar(select(Company).where(Company.slug == "postman"))
        assert c.ats == "unsupported" and c.notes == "my note" and "darwinbox" in c.board_url


@pytest.mark.parametrize("url", ["http://localhost/careers", "https://127.0.0.1/", "https://10.0.0.5/jobs", "https://169.254.169.254/latest",
                                 "ftp://example.com", "file:///etc/passwd", "https://[::1]/"])
async def test_careers_probe_refuses_private_or_non_http_targets(url):
    async with httpx.AsyncClient() as client:
        assert await discover.careers_probe(client, url) is None


# --- I10: digest / API behaviour ---

def test_digest_excludes_any_job_with_an_application(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    c = dc(session, "c")
    j = dj(session, c, "applied")
    dj(session, c, "fresh")
    session.add(Application(job_id=j.id, user_id="u", status="applied", updated_at=NOW))
    session.flush()
    d = digest.build(session, Settings(user_id="u"), NOW)
    assert [x.title for x in d.new["India"]] and all(x.job_id != j.id for x in d.new["India"])


def test_digest_build_can_be_uncapped_and_budgets_unscored_separately(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    c = dc(session, "c")
    for i in range(6):
        dj(session, c, f"s{i}", score=50 + i)
    for i in range(3):
        dj(session, c, f"u{i}", score=None, verdict=None)
    capped = digest.build(session, Settings(user_id="u", digest_max_jobs=4), NOW)
    assert sum(len(v) for v in capped.new.values()) == 4 and len(capped.unscored) == 3 and capped.truncated == 2
    full = digest.build(session, Settings(user_id="u", digest_max_jobs=4), NOW, cap=None)
    assert sum(len(v) for v in full.new.values()) == 6 and full.truncated == 0


def test_api_digest_is_uncapped(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    from web.api.app import create_app
    settings = Settings(database_url=f"sqlite:///{tmp_path}/h.db", user_id="u", review_token="t", digest_max_jobs=2)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        dp(s)
        c = dc(s, "c")
        for i in range(5):
            dj(s, c, f"s{i}", score=50 + i)
        s.commit()
    client = TestClient(create_app(settings, sf, now=lambda: NOW))
    d = client.get("/api/digest", headers={"Authorization": "Bearer t"}).json()
    assert len(d["new"]["India"]) == 5 and d["truncated"] == 0


# --- misc ---


def test_fetch_truncation_keeps_board_url_short(session):
    b = discover.Board(ats="unsupported", slug="x", name="X", board_url="https://" + "a" * 700 + ".com")
    discover.upsert_companies(session, "u", [b])
    assert len(session.scalar(select(Company)).board_url) <= 512




async def test_careers_probe_rejects_hosts_resolving_to_private_addresses(monkeypatch):
    monkeypatch.setattr(http, "resolve", lambda host: {"10.1.2.3", "93.184.216.34"})
    async with httpx.AsyncClient() as client:
        assert await discover.careers_probe(client, "https://evil.example") is None


@respx.mock
async def test_careers_probe_validates_each_redirect_hop(monkeypatch):
    respx.get("https://a.example/careers").respond(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
    respx.get("https://a.example/jobs").respond(404)
    respx.get("https://a.example/").respond(404)
    respx.get("https://b.example/careers").respond(302, headers={"Location": "https://c.example/open-roles"})
    respx.get("https://c.example/open-roles").respond(text='<a href="https://jobs.lever.co/hevodata">roles</a>')
    async with httpx.AsyncClient() as client:
        assert await discover.careers_probe(client, "https://a.example") is None
        b = await discover.careers_probe(client, "https://b.example")
    assert (b.ats, b.slug) == ("lever", "hevodata")


async def test_careers_probe_treats_unparseable_resolution_as_unsafe(monkeypatch):
    monkeypatch.setattr(http, "resolve", lambda host: {"not-an-ip"})
    async with httpx.AsyncClient() as client:
        assert await discover.careers_probe(client, "https://odd.example") is None


def test_digest_ranks_junior_titles_first_then_score_then_freshness(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    c = dc(session, "c")
    dj(session, c, "a", title="Software Engineer", score=95, posted_days=1)
    dj(session, c, "b", title="Associate Software Engineer", score=70, posted_days=5)
    dj(session, c, "c", title="SDE 1 - Backend", score=70, posted_days=2)
    dj(session, c, "d", title="Backend Developer", score=70, posted_days=1)
    d = digest.build(session, Settings(user_id="u"), NOW)
    assert [j.title for j in d.new["India"]] == ["SDE 1 - Backend", "Associate Software Engineer", "Software Engineer", "Backend Developer"]


# --- rules v3: remote postings that name a foreign place are remote *for that place* ---

@pytest.mark.parametrize("raw,flag,india,remote,restricted", [
    ("Vancouver", True, False, True, True),
    ("San Francisco ", True, False, True, True),
    ("Remote/Hybrid if local to Maryland", False, False, True, True),
    ("Remote", True, False, True, False),
    ("Remote - India", True, True, True, False),
    ("Remote (Anywhere)", False, False, True, False),
    ("Bengaluru", True, True, True, False),
])
def test_remote_flag_with_a_named_foreign_place_is_restricted(raw, flag, india, remote, restricted):
    loc = rules.location(raw, None, flag)
    assert (loc.is_india, loc.is_remote, loc.remote_restricted) == (india, remote, restricted)


def test_evaluate_fails_location_for_stored_foreign_remote_jobs():
    r = rules.evaluate("Software Engineer I", False, True, "Vancouver", "0-2 years of experience", "watch", "product", 2, [])
    assert "location" in r.fails


@pytest.mark.parametrize("title,eng,senior", [
    ("Staff Engineer I", True, True),
    ("Senior Associate Engineer", True, True),
    ("Associate Software Engineer", True, False),
    ("Software Development Engineer in Test II", False, True),
    ("SOC Engineer I", False, False),
    ("Systems Engineer I", False, False),
    ("Associate IT Operations Engineer", False, False),
    ("Associate Security Engineer", False, False),
    ("Junior DevOps Engineer", True, False),
    ("Site Reliability Engineer I", True, False),
])
def test_rules_v3_title_edge_cases(title, eng, senior):
    assert rules.title_kind(title) == (eng, senior)


def test_digest_carries_pipeline_counts_and_template_renders_them(session):
    from hunt import digest, track
    from hunt.models import Company
    from tests.test_digest import mk_profile as dp
    dp(session)
    c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data")
    session.add(c)
    session.flush()
    track.apply_events(session, Settings(user_id="u"), [track.Mail("<p1>", "Hevo Data <no-reply@hire.lever.co>", "Thank you for applying to Hevo Data", NOW, "", "x y", "mx.google.com; dkim=pass header.i=@hire.lever.co; arc=pass"),
                                                         track.Mail("<p2>", "HackerRank <noreply@hackerrank.com>", "Online Assessment at Hevo Data", NOW, "", "x y", "mx.google.com; dkim=pass header.i=@hackerrank.com; arc=pass")], NOW)
    d = digest.build(session, Settings(user_id="u"), NOW)
    assert d.pipeline["week"] == {"applied": 1, "test": 1, "interview": 0, "rejected": 0}
    _, html = digest.render(d, Settings(user_id="u"))
    assert "Your pipeline" in html and "1 applied" in html and "1 test" in html


# --- fetch speed: descriptions are fetched once per posting, not every run ---

async def test_collect_skips_description_fetch_for_known_postings():
    src = FakeSource({"x": [p("known", desc=None), p("new", desc=None)]}, descriptions={"known": "old", "new": "fresh 0-2 years of experience"})
    listing = await fetch.collect(Company(user_id="u", ats="greenhouse", slug="x", name="x"), src, known={"known"})
    assert src.description_calls == ["new"] and listing.descriptions_fetched == 1


async def test_fetch_all_passes_known_described_jobs_and_keeps_their_descriptions():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        c = Company(user_id="u", ats="greenhouse", slug="x", name="x")
        s.add(c)
        s.commit()
    src = FakeSource({"x": [p("a", desc=None)]}, descriptions={"a": "0-2 years of experience"})
    await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW)
    await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW + timedelta(days=1))
    assert src.description_calls == ["a"]
    with sf() as s:
        assert s.scalar(select(Job)).description == "0-2 years of experience"


async def test_fetch_all_refreshes_descriptions_weekly():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Company(user_id="u", ats="greenhouse", slug="x", name="x"))
        s.commit()
    src = FakeSource({"x": [p("a", desc=None)]}, descriptions={"a": "0-2 years of experience"})
    await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW)
    await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW + timedelta(days=8))
    assert src.description_calls == ["a", "a"]


# --- posting-age cap: only recently posted jobs reach the digest ---

@pytest.mark.parametrize("posted_days,first_seen_days,expect_stale", [
    (3, 3, False),
    (14, 14, False),
    (15, 15, True),
    (60, 1, True),
    (None, 2, False),
    (None, 20, True),
])
def test_evaluate_flags_stale_postings(posted_days, first_seen_days, expect_stale):
    posted = NOW - timedelta(days=posted_days) if posted_days is not None else None
    r = rules.evaluate("Software Engineer", True, False, "Bangalore", "0-2 years of experience", "watch", "product", 2, [],
                       posted_at=posted, first_seen=NOW - timedelta(days=first_seen_days), now=NOW, max_posted_age_days=14)
    assert ("stale_posting" in r.fails) is expect_stale


def test_run_rules_uses_settings_posting_age_and_counts_stale(session):
    from tests.test_assess import mk_company, mk_job, mk_profile
    prof = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    fresh = mk_job(session, c, "fresh")
    old = mk_job(session, c, "old")
    fresh.posted_at, old.posted_at = NOW - timedelta(days=2), NOW - timedelta(days=40)
    session.flush()
    assess.run_rules(session, Settings(user_id="u", max_posted_age_days=14), prof, NOW)
    a = {session.get(Job, x.job_id).external_id: x for x in session.scalars(select(Assessment))}
    assert a["fresh"].passed_rules and a["old"].rule_fails == ["stale_posting"]


def test_digest_footer_reports_stale_hidden(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    c = dc(session, "c")
    dj(session, c, "ok")
    dj(session, c, "old", passed=False, verdict=None, score=None)
    a = session.scalar(select(Assessment).join(Job).where(Job.external_id == "old"))
    a.rule_fails = ["stale_posting"]
    session.flush()
    d = digest.build(session, Settings(user_id="u"), NOW)
    assert d.coverage.stale_hidden == 1
    _, html = digest.render(d, Settings(user_id="u"))
    assert "1 hidden as stale" in html


def test_rules_version_bump_keeps_scores_for_jobs_that_still_pass(session, monkeypatch):
    from tests.test_assess import mk_company, mk_job, mk_profile
    prof = mk_profile(session)
    c = mk_company(session, "c", kind="product")
    keep = mk_job(session, c, "keep")
    drop = mk_job(session, c, "drop")
    keep.posted_at = drop.posted_at = NOW - timedelta(days=1)
    assess.run_rules(session, Settings(user_id="u"), prof, NOW)
    for a in session.scalars(select(Assessment)):
        a.fit_score, a.verdict, a.reason, a.scored_at = 80, "apply", "fits", NOW
    drop.posted_at = NOW - timedelta(days=40)
    session.flush()
    monkeypatch.setattr(rules, "RULES_VERSION", rules.RULES_VERSION + 1)
    assess.run_rules(session, Settings(user_id="u"), prof, NOW)
    a = {session.get(Job, x.job_id).external_id: x for x in session.scalars(select(Assessment))}
    assert (a["keep"].verdict, a["keep"].fit_score) == ("apply", 80)
    assert a["drop"].verdict is None and a["drop"].rule_fails == ["stale_posting"]


async def test_collect_skips_descriptions_for_postings_older_than_the_cap():
    src = FakeSource({"x": [p("old", desc=None, posted_at=NOW - timedelta(days=40)), p("new", desc=None, posted_at=NOW - timedelta(days=2)),
                            p("undated", desc=None)]}, descriptions={"old": "x", "new": "y", "undated": "z"})
    listing = await fetch.collect(Company(user_id="u", ats="greenhouse", slug="x", name="x"), src, now=NOW, max_posted_age_days=14)
    assert sorted(src.description_calls) == ["new", "undated"] and listing.descriptions_fetched == 2


@pytest.mark.parametrize("title", ["Customer Experience Engineer I/II", "Customer Engineer", "Technical Account Manager", "Developer Advocate", "Solutions Consultant"])
def test_more_customer_facing_titles_excluded(title):
    assert rules.title_kind(title)[0] is False


def test_known_consultancies_are_service():
    assert rules.company_kind("Capco", "capco", ["Python Developer-TPRM"]) == "service"
    assert rules.company_kind("Publicis Sapient", "publicissapient", ["Software Engineer"]) == "service"


# --- adaptive fetch frequency: boards go dormant after 30 days without a relevant posting ---

def mk_board(session, slug, status="watch", relevant_days=None, dormant=False):
    c = Company(user_id="u", ats="lever", slug=slug, name=slug, status=status, dormant=dormant,
                last_relevant_at=NOW - timedelta(days=relevant_days) if relevant_days is not None else None)
    session.add(c)
    session.flush()
    return c


def test_selectable_skips_dormant_boards_except_on_sunday_and_targets(session):
    mk_board(session, "active", relevant_days=3)
    mk_board(session, "sleepy", dormant=True)
    mk_board(session, "target-sleepy", status="target", dormant=True)
    chosen, skipped = fetch._selectable(session, Settings(user_id="u"), None, False, NOW)  # NOW is a Wednesday
    assert sorted(c.slug for c in chosen) == ["active", "target-sleepy"] and skipped == 1
    sunday = NOW + timedelta(days=4)
    chosen, _ = fetch._selectable(session, Settings(user_id="u"), None, False, sunday)
    assert len(chosen) == 3


def test_apply_board_updates_relevance_and_dormancy(session):
    c = mk_board(session, "x", relevant_days=45)
    listing = fetch.Listing(postings=[p("sr", title="Senior Engineer")])
    fetch.apply_board(session, c, listing, NOW)
    assert c.dormant is True and c.last_relevant_at == NOW - timedelta(days=45)
    listing = fetch.Listing(postings=[p("jr", title="Software Engineer I")])
    fetch.apply_board(session, c, listing, NOW)
    assert c.dormant is False and c.last_relevant_at == NOW


def test_board_with_no_relevant_postings_goes_dormant_immediately(session):
    c = mk_board(session, "new")
    fetch.apply_board(session, c, fetch.Listing(postings=[p("sr", title="Senior Engineer")]), NOW)
    assert c.dormant is True and c.last_relevant_at is None
    fetch.apply_board(session, c, fetch.Listing(postings=[p("jr")]), NOW)
    assert c.dormant is False and c.last_relevant_at == NOW


def test_never_successful_boards_back_off_to_weekly_after_three_failures(session):
    fresh = mk_board(session, "fresh")
    fresh.fail_count = 2
    dead = mk_board(session, "dead")
    dead.fail_count = 3
    once_ok = mk_board(session, "once-ok", relevant_days=5)
    once_ok.fail_count, once_ok.last_ok = 10, NOW - timedelta(days=12)
    session.flush()
    chosen, skipped = fetch._selectable(session, Settings(user_id="u"), None, False, NOW)
    assert sorted(c.slug for c in chosen) == ["fresh", "once-ok"] and skipped == 1
    chosen, _ = fetch._selectable(session, Settings(user_id="u"), None, False, NOW + timedelta(days=4))
    assert len(chosen) == 3


# --- hiring velocity: companies opening several junior roles recently rank higher ---

def test_velocity_counts_recent_relevant_openings_per_company(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    fast = dc(session, "fast", name="Fast Co")
    slow = dc(session, "slow", name="Slow Co")
    for i in range(3):
        dj(session, fast, f"f{i}", title=f"Software Engineer {['I', 'A', 'B'][i]}", score=70, age_h=24 * i)
    dj(session, fast, "old", title="Backend Engineer", score=70, age_h=24 * 40)
    dj(session, slow, "s0", title="Software Engineer", score=95, age_h=2)
    v = digest.velocity(session, "u", NOW, days=14)
    assert v == {fast.id: 3, slow.id: 1}


def test_digest_ranks_fast_hiring_companies_above_score_but_below_junior_titles(session):
    from hunt import digest
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    fast = dc(session, "fast", name="Fast Co")
    slow = dc(session, "slow", name="Slow Co")
    for i in range(3):
        dj(session, fast, f"f{i}", title=f"Platform Engineer {'ABC'[i]}", score=70, age_h=1 + i)
    dj(session, slow, "top", title="Software Engineer", score=95, age_h=1)
    dj(session, slow, "jr", title="Associate Software Engineer", score=60, age_h=1)
    d = digest.build(session, Settings(user_id="u"), NOW)
    titles = [j.title for j in d.new["India"]]
    assert titles[0] == "Associate Software Engineer"
    assert titles[1:4] == ["Platform Engineer A", "Platform Engineer B", "Platform Engineer C"]
    assert titles[4] == "Software Engineer"
    assert d.new["India"][1].company_velocity == 3 and d.new["India"][4].company_velocity == 2
    _, html = digest.render(d, Settings(user_id="u"))
    assert "hiring fast" in html


@pytest.mark.parametrize("text", ["workday:evil.example/acme/External", "workday:acme.wd5.myworkdayjobs.com.evil.example/acme/External", "workday:127.0.0.1/acme/External"])
def test_parse_board_rejects_workday_slugs_outside_myworkdayjobs(text):
    with pytest.raises(ValueError):
        discover.parse_board(text)


@respx.mock
async def test_workday_adapter_refuses_foreign_hosts_before_any_request():
    route = respx.post(url__regex=r"https://evil\.example/.*").respond(json={"total": 0, "jobPostings": []})
    async with httpx.AsyncClient() as client:
        with pytest.raises(http.BoardError):
            await ats.list_jobs(client, "workday", "evil.example/acme/External")
        with pytest.raises(http.BoardError):
            await ats.AtsSource(client).description("workday", "evil.example/acme/External", "/job/x")
    assert not route.called


@respx.mock
async def test_post_json_refuses_private_addresses(monkeypatch):
    monkeypatch.setattr(http, "resolve", lambda host: {"10.0.0.5"})
    route = respx.post("https://internal.example/api").respond(json={})
    async with httpx.AsyncClient() as client:
        with pytest.raises(http.BoardError):
            await http.post_json(client, "https://internal.example/api", {})
    assert not route.called
