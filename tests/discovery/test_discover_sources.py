from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from hungry_hunt.core import http
from hungry_hunt.db.models import Company
from hungry_hunt.discovery import discover

FIX = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(http, "BACKOFF", (0, 0))
    monkeypatch.setattr(discover, "WAYBACK_BACKOFF", (0, 0, 0))


@respx.mock
async def test_wayback_slugs_extracts_unique_lowercase_slugs_and_skips_junk(client):
    respx.get(
        "https://web.archive.org/cdx/search/cdx", params__contains={"url": "jobs.lever.co/*", "showNumPages": "true"}
    ).respond(text="1\n")
    respx.get(
        "https://web.archive.org/cdx/search/cdx", params__contains={"url": "jobs.lever.co/*", "page": "0"}
    ).respond(json=__import__("json").loads((FIX / "wayback_cdx.json").read_text()))
    slugs = await discover.wayback_slugs(client, "jobs.lever.co")
    assert slugs == {"hevodata", "cred", "meesho", "zeta"}


@respx.mock
async def test_wayback_retries_on_503_then_gives_up_quietly(client):
    route = respx.get("https://web.archive.org/cdx/search/cdx").respond(503)
    assert await discover.wayback_slugs(client, "jobs.lever.co") == set()
    assert route.call_count == 4


@respx.mock
async def test_commoncrawl_tolerates_truncated_lines(client):
    respx.get("https://index.commoncrawl.org/CC-MAIN-2026-39-index", params__contains={"showNumPages": "true"}).respond(
        json={"pages": 1}
    )
    respx.get("https://index.commoncrawl.org/CC-MAIN-2026-39-index", params__contains={"page": "0"}).respond(
        text=(FIX / "cc_cdx_truncated.txt").read_text()
    )
    found = await discover.commoncrawl_slugs(
        client, ["CC-MAIN-2026-39"], patterns=[("greenhouse", "boards.greenhouse.io/*")]
    )
    assert found["greenhouse"] == {"razorpaysoftwareprivatelimited", "observeai", "druva"}


def test_boards_from_text_finds_ats_links_and_ignores_others():
    boards = discover.boards_from_text((FIX / "github_newgrad_readme.md").read_text())
    assert {(b.ats, b.slug) for b in boards} == {("greenhouse", "rubrik"), ("ashby", "atlan"), ("lever", "hevodata")}


@respx.mock
async def test_careers_probe_finds_lever_board_on_company_site(client):
    respx.get("https://hevodata.com/careers").respond(text=(FIX / "careers_page.html").read_text())
    b = await discover.careers_probe(client, "https://hevodata.com")
    assert (b.ats, b.slug) == ("lever", "hevodata")


@respx.mock
async def test_careers_probe_detects_unsupported_ats(client):
    respx.get("https://postman.com/careers").respond(404)
    respx.get("https://postman.com/jobs").respond(text=(FIX / "careers_page_workday.html").read_text())
    b = await discover.careers_probe(client, "https://postman.com")
    assert (b.ats, b.slug) == ("workday", "postman.wd1.myworkdayjobs.com/postman/Postman")


@respx.mock
async def test_careers_probe_still_reports_truly_unsupported_vendors(client):
    respx.get("https://rapido.example/careers").respond(
        text='<a href="https://rapido.darwinbox.in/ms/candidate/careers">Jobs</a>'
    )
    respx.get(url__regex=r"https://rapido\.example/(robots\.txt|sitemap\.xml)").respond(404)
    b = await discover.careers_probe(client, "https://rapido.example")
    assert b.ats == "unsupported" and "darwinbox" in b.notes.lower()


@respx.mock
async def test_careers_probe_returns_none_when_nothing_found(client):
    for path in ("/careers", "/jobs", "/"):
        respx.get(f"https://plain.example{path}").respond(text="<html>hi</html>")
    respx.get(url__regex=r"https://plain\.example/(robots\.txt|sitemap\.xml)").respond(404)
    assert await discover.careers_probe(client, "https://plain.example") is None


def test_enrich_from_yc_matches_exact_normalized_name_only(session):
    import json

    yc = json.loads((FIX / "yc_sample.json").read_text())
    discover.upsert_companies(
        session,
        "u",
        [
            discover.Board(ats="lever", slug="hevodata", name="Hevo Data"),
            discover.Board(ats="greenhouse", slug="razorpaysoftwareprivatelimited", name="Razorpay"),
            discover.Board(ats="ashby", slug="atlan", name="atlan"),
            discover.Board(ats="greenhouse", slug="stripe", name="Stripe Payments India"),
        ],
    )
    assert discover.enrich_from_yc(session, "u", yc) == 3
    rows = {c.slug: c for c in session.scalars(select(Company))}
    assert (rows["hevodata"].yc_batch, rows["hevodata"].team_size, rows["hevodata"].tier) == ("Winter 2017", 180, "mid")
    assert (rows["razorpaysoftwareprivatelimited"].team_size, rows["razorpaysoftwareprivatelimited"].tier) == (
        3000,
        "big_product",
    )
    assert rows["atlan"].team_size == 400
    assert rows["stripe"].team_size is None


@respx.mock
async def test_discover_orchestrates_sources_in_isolation_and_records_run():
    from hungry_hunt.config import Settings
    from hungry_hunt.db import Base, make_engine, session_factory
    from hungry_hunt.db.models import Run

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    respx.get(discover.GITHUB_LISTS[0]).respond(text=(FIX / "github_newgrad_readme.md").read_text())
    respx.get(discover.GITHUB_LISTS[1]).respond(500)
    respx.get(discover.GITHUB_LISTS[2]).respond(text="nothing here")
    respx.get(discover.YC_URL).respond(json=__import__("json").loads((FIX / "yc_sample.json").read_text()))
    respx.get(url__regex=r"https://(razorpay|atlan)\.com/.*").respond(text="<html>no ats</html>")
    respx.get(url__regex=r"https://hevodata\.com/.*").respond(text=(FIX / "careers_page.html").read_text())
    async with httpx.AsyncClient() as client:
        stats = await discover.discover(sf, Settings(user_id="u"), ["github", "yc", "bogus"], client)
    assert stats.per_source["github"] == 3
    assert stats.per_source["yc"] == 0 and stats.probed == 1 and stats.enriched == 2
    assert stats.errors == ["unknown source bogus"]
    with sf() as s:
        slugs = {(c.ats, c.slug): c for c in s.scalars(select(Company))}
        assert {("greenhouse", "rubrik"), ("ashby", "atlan"), ("lever", "hevodata")} <= set(slugs)
        assert slugs[("lever", "hevodata")].team_size == 180
        assert s.scalar(select(Run).where(Run.stage == "discover")).stats["new_companies"] == 3


def test_yc_india_candidates_filters_active_with_india_presence():
    import json

    yc = json.loads((FIX / "yc_sample.json").read_text())
    assert [c["name"] for c in discover.yc_india_candidates(yc)] == ["Razorpay", "Hevo Data", "Atlan"]


@respx.mock
async def test_careers_source_upgrades_placeholder_row_in_place_when_a_board_is_found():
    from hungry_hunt.config import Settings
    from hungry_hunt.db import Base, make_engine, session_factory

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        discover.upsert_companies(
            s,
            "u",
            [
                discover.Board(
                    ats="unsupported",
                    slug="juspay",
                    name="Juspay",
                    status="target",
                    board_url="https://juspay.io/careers",
                    notes="custom careers page",
                )
            ],
        )
        s.commit()
    respx.get("https://juspay.io/careers").respond(text="<html><div id='root'></div></html>")
    respx.get("https://juspay.io/robots.txt").respond(404)
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_plain_job.html").read_text())
    async with httpx.AsyncClient() as client:
        await discover.discover(sf, Settings(user_id="u"), ["careers"], client)
    with sf() as s:
        (c,) = s.scalars(select(Company).where(Company.name == "Juspay")).all()
        assert (c.ats, c.slug, c.status, c.board_url) == (
            "careers",
            "https://juspay.io/careers",
            "target",
            "https://juspay.io/careers",
        )


@respx.mock
async def test_wayback_slugs_asks_for_page_count_without_output_filters_and_tolerates_dash(client):
    count = respx.get(
        "https://web.archive.org/cdx/search/cdx", params__contains={"url": "jobs.lever.co/*", "showNumPages": "true"}
    ).respond(text="-")
    assert await discover.wayback_slugs(client, "jobs.lever.co") == set()
    sent = count.calls[0].request.url.params
    assert "output" not in sent and "collapse" not in sent and "fl" not in sent


@respx.mock
async def test_careers_source_merges_unknown_row_into_existing_unsupported_twin_and_survives_one_failure():
    from hungry_hunt.config import Settings
    from hungry_hunt.db import Base, make_engine, session_factory

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        discover.upsert_companies(
            s,
            "u",
            [
                discover.Board(
                    ats="unsupported",
                    slug="rapido",
                    name="Rapido",
                    board_url="https://rapido.darwinbox.in/x",
                    notes="darwinbox ATS",
                ),
                discover.Board(ats="unknown", slug="rapido", name="Rapido", board_url="https://rapido.example"),
                discover.Board(ats="unknown", slug="acme", name="Acme", board_url="https://acme.example"),
            ],
        )
        s.commit()
    respx.get(url__regex=r"https://rapido\.example/.*").respond(
        text='<a href="https://rapido.darwinbox.in/ms/candidate/careers">Jobs</a>'
    )
    respx.get(url__regex=r"https://acme\.example/.*").side_effect = RuntimeError("boom")
    respx.get(url__regex=r"https://rapido\.darwinbox\.in/.*").respond(404)
    async with httpx.AsyncClient() as client:
        stats = await discover.discover(sf, Settings(user_id="u"), ["careers"], client)
    assert (
        stats.probed == 3 and list(stats.errors) == [e for e in stats.errors if "acme" in e] and len(stats.errors) == 1
    )
    with sf() as s:
        rows = s.scalars(select(Company).where(Company.name == "Rapido")).all()
        assert len(rows) == 1 and rows[0].ats == "unsupported"
