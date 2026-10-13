from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from hunt import fetch
from hunt.config import Settings
from hunt.db import Base, make_engine, session_factory
from hunt.http import BoardError
from hunt.models import Company, Job, Run
from hunt.schemas import Posting

NOW = datetime(2026, 10, 7, 1, 30, tzinfo=UTC)


def p(eid, title="Software Engineer", loc="Bangalore, India", desc="0-2 years of experience", **kw):
    return Posting(external_id=eid, title=title, location_raw=loc, url=f"https://x/{eid}", description=desc, **kw)


class FakeSource:
    def __init__(self, listings: dict, fail: set = (), descriptions: dict | None = None):
        self.listings, self.fail, self.descriptions = listings, set(fail), descriptions or {}
        self.description_calls = []

    async def list_jobs(self, ats, slug):
        if slug in self.fail:
            raise BoardError("boom", status=500)
        return [q.model_copy() for q in self.listings[slug]]

    async def description(self, ats, slug, external_id):
        self.description_calls.append(external_id)
        return self.descriptions.get(external_id, "")


def jobs(session, company):
    return {j.external_id: j for j in session.scalars(select(Job).where(Job.company_id == company.id))}


def test_apply_listing_stores_india_and_remote_only(session, company):
    new, closed = fetch.apply_listing(session, company, [p("in"), p("us", loc="Austin, TX"), p("rm", loc="Remote"),
                                                          p("rx", loc="Remote - US only"), p("bl", loc="")], NOW)
    assert (new, closed) == (3, 0)
    js = jobs(session, company)
    assert set(js) == {"in", "rm", "bl"}
    assert js["in"].is_india and not js["in"].is_remote and js["rm"].is_remote
    assert js["in"].first_seen == js["in"].last_seen == NOW


def test_apply_listing_stores_description_only_when_prefilter_passes(session, company):
    fetch.apply_listing(session, company, [p("jr"), p("sr", title="Senior Engineer"), p("sup", title="Support Engineer")], NOW)
    js = jobs(session, company)
    assert js["jr"].description == "0-2 years of experience" and js["jr"].content_hash
    assert js["sr"].description is None and js["sup"].description is None


def test_apply_listing_closes_missing_and_revives_returning(session, company):
    fetch.apply_listing(session, company, [p("a"), p("b")], NOW)
    later = NOW + timedelta(days=1)
    assert fetch.apply_listing(session, company, [p("a")], later) == (0, 1)
    js = jobs(session, company)
    assert js["b"].closed_at == later and js["a"].closed_at is None and js["a"].last_seen == later
    assert fetch.apply_listing(session, company, [p("a"), p("b")], later + timedelta(days=1)) == (0, 0)
    assert jobs(session, company)["b"].closed_at is None


def test_apply_listing_updates_content_hash_when_description_changes(session, company):
    fetch.apply_listing(session, company, [p("a")], NOW)
    h1 = jobs(session, company)["a"].content_hash
    fetch.apply_listing(session, company, [p("a", desc="4+ years of experience")], NOW)
    assert jobs(session, company)["a"].content_hash != h1


async def test_fetch_board_failure_counts_and_never_closes(session, company):
    fetch.apply_listing(session, company, [p("a")], NOW - timedelta(days=1))
    company.last_ok = NOW - timedelta(days=1)
    out = await fetch.fetch_board(session, company, FakeSource({}, fail={"hevodata"}), NOW)
    assert out.ok is False and out.status == 500
    assert company.fail_count == 1 and company.last_fetched == NOW and company.last_ok == NOW - timedelta(days=1)
    assert jobs(session, company)["a"].closed_at is None


async def test_fetch_board_success_updates_company(session):
    c = Company(user_id="u", ats="greenhouse", slug="observeai", name="observeai", fail_count=3)
    session.add(c)
    session.flush()
    src = FakeSource({"observeai": [p("1", company_name="Observe.AI", desc=None), p("2", title="Sr Engineer", company_name="Observe.AI", desc=None)]},
                     descriptions={"1": "We need 1-2 years of experience"})
    out = await fetch.fetch_board(session, c, src, NOW)
    assert out.ok and out.new == 2 and out.seen == 2 and out.stored == 2
    assert (c.name, c.fail_count, c.last_ok, c.kind, c.tier) == ("Observe.AI", 0, NOW, "product", "early_funded")
    assert src.description_calls == ["1"]
    js = jobs(session, c)
    assert js["1"].description == "We need 1-2 years of experience" and js["2"].description is None
    assert out.descriptions_fetched == 1


async def test_fetch_all_filters_and_records_run():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add_all([Company(user_id="u", ats="lever", slug="hevodata", name="Hevo", status="target"),
                   Company(user_id="u", ats="lever", slug="porter", name="Porter", status="avoid"),
                   Company(user_id="u", ats="lever", slug="dead", name="Dead", fail_count=30),
                   Company(user_id="u", ats="unsupported", slug="cashfree", name="Cashfree"),
                   Company(user_id="u", ats="lever", slug="broken", name="Broken")])
        s.commit()
    src = FakeSource({"hevodata": [p("h1"), p("h2", title="SDE I")], "porter": [p("p1")], "dead": [p("d1")]}, fail={"broken"})
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW)
    assert (stats.boards_total, stats.boards_ok, stats.boards_failed, stats.boards_skipped) == (2, 1, 1, 1)
    assert (stats.jobs_seen, stats.jobs_new, stats.lever_boards) == (2, 2, 2)
    assert stats.stale_targets == []
    with sf() as s:
        assert s.scalar(select(Run).where(Run.stage == "fetch")).stats["jobs_new"] == 2
        assert {j.external_id for j in s.scalars(select(Job))} == {"h1", "h2"}
    stats2 = await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW + timedelta(hours=1))
    assert stats2.jobs_new == 0


async def test_fetch_all_target_board_404_is_a_stale_target():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Company(user_id="u", ats="lever", slug="gone", name="Gone", status="target"))
        s.commit()

    class NotFound(FakeSource):
        async def list_jobs(self, ats, slug):
            raise BoardError("404", status=404)

    stats = await fetch.fetch_all(sf, Settings(user_id="u"), NotFound({}), now=NOW)
    assert stats.stale_targets == ["Gone"]


def _feed_posting(eid, ref, name, **kw):
    return p(eid, company_ref=ref, company_name=name, company_url=f"https://jobs.workable.com/company/{ref}", **kw)


async def test_feed_board_groups_postings_per_company_and_closes_members_that_vanish():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Company(user_id="u", ats="workable_feed", slug="India", name="Workable India", status="watch"))
        s.commit()
    src = FakeSource({"India": [_feed_posting("a1", "apna", "Apna"), _feed_posting("a2", "apna", "Apna", title="Senior Assistant"), _feed_posting("z1", "zeta", "Zeta")]})
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW)
    assert (stats.boards_ok, stats.boards_total, stats.jobs_new) == (1, 1, 3)
    with sf() as s:
        members = {c.slug: c for c in s.scalars(select(Company).where(Company.ats == "workable"))}
        assert set(members) == {"apna", "zeta"} and members["apna"].name == "Apna" and members["apna"].last_ok == NOW
        assert members["apna"].board_url == "https://jobs.workable.com/company/apna" and members["apna"].status == "watch"
        assert s.scalar(select(Job).where(Job.external_id == "z1")).company_id == members["zeta"].id
    src = FakeSource({"India": [_feed_posting("a1", "apna", "Apna")]})
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW + timedelta(hours=1))
    assert stats.jobs_closed == 2
    with sf() as s:
        assert s.scalar(select(Job).where(Job.external_id == "z1")).closed_at is not None
        assert s.scalar(select(Job).where(Job.external_id == "a2")).closed_at is not None
        assert s.scalar(select(Job).where(Job.external_id == "a1")).closed_at is None
        assert s.scalar(select(Company).where(Company.slug == "zeta")).last_ok == NOW + timedelta(hours=1)
    src = FakeSource({}, fail={"India"})
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), src, now=NOW + timedelta(hours=2))
    assert stats.boards_failed == 1 and stats.jobs_closed == 0
    with sf() as s:
        assert s.scalar(select(Job).where(Job.external_id == "a1")).closed_at is None
        assert s.scalar(select(Company).where(Company.ats == "workable_feed")).fail_count == 1


async def test_member_boards_of_a_feed_are_never_fetched_directly():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Company(user_id="u", ats="workable", slug="apna", name="Apna", status="target"))
        s.commit()
    stats = await fetch.fetch_all(sf, Settings(user_id="u"), FakeSource({}), now=NOW)
    assert stats.boards_total == 0
