from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from hungry_hunt import adapters as ats
from hungry_hunt.config import Settings
from hungry_hunt.db import Base, make_engine, session_factory
from hungry_hunt.db.models import Company, Job
from hungry_hunt.discovery import discover
from hungry_hunt.pipeline import fetch

FIX = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def client():
    return httpx.AsyncClient()


@respx.mock
async def test_careers_adapter_reads_jsonld_job_postings(client):
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_jsonld.html").read_text())
    postings = await ats.list_jobs(client, "careers", "https://juspay.io/careers")
    by = {p.external_id: p for p in postings}
    assert set(by) == {"JP-1021", "https://juspay.io/careers/sre", "https://juspay.io/careers/ase"}
    p = by["JP-1021"]
    assert (p.title, p.location_raw, p.country, p.url) == (
        "Software Engineer - Backend",
        "Bengaluru, KA, IN",
        "IN",
        "https://juspay.io/careers/jp-1021",
    )
    assert (
        p.posted_at.year == 2026
        and p.posted_at.month == 10
        and "0-2 years of experience" in p.description
        and "<p>" not in p.description
    )
    assert by["https://juspay.io/careers/sre"].remote_flag is True
    assert (
        by["https://juspay.io/careers/ase"].location_raw == "Hyderabad, India"
        and by["https://juspay.io/careers/ase"].country == "IN"
    )


@respx.mock
async def test_careers_adapter_returns_empty_when_no_structured_data(client):
    respx.get("https://plain.example/jobs").respond(text="<html><body>We are hiring!</body></html>")
    respx.get(url__regex=r"https://plain\.example/(robots\.txt|sitemap\.xml)").respond(404)
    assert await ats.list_jobs(client, "careers", "https://plain.example/jobs") == []


@respx.mock
async def test_careers_probe_prefers_ats_boards_but_falls_back_to_jsonld_pages(client):
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_jsonld.html").read_text())
    b = await discover.careers_probe(client, "https://juspay.io")
    assert (b.ats, b.slug) == ("careers", "https://juspay.io/careers")


@respx.mock
async def test_fetch_all_includes_careers_boards():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(
            Company(
                user_id="u",
                ats="careers",
                slug="https://juspay.io/careers",
                name="Juspay",
                board_url="https://juspay.io/careers",
            )
        )
        s.commit()
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_jsonld.html").read_text())
    async with httpx.AsyncClient() as client:
        stats = await fetch.fetch_all(sf, Settings(user_id="u"), ats.AtsSource(client))
    assert (stats.boards_ok, stats.jobs_new) == (1, 3)
    with sf() as s:
        titles = {j.title for j in s.scalars(select(Job))}
        assert "Associate Software Engineer" in titles


def test_parse_board_accepts_careers_urls():
    b = discover.parse_board("careers:https://juspay.io/careers")
    assert (b.ats, b.slug) == ("careers", "https://juspay.io/careers")


@respx.mock
async def test_careers_adapter_follows_job_links_one_level_when_index_has_no_structured_data(client):
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_index.html").read_text())
    job = respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_job.html").read_text())
    respx.get("https://juspay.io/careers/ase").respond(text="<html>no data</html>")
    postings = await ats.list_jobs(client, "careers", "https://juspay.io/careers")
    assert [p.external_id for p in postings] == ["JP-1021"] and job.call_count == 1
    urls = [str(c.request.url) for c in respx.calls]
    assert not any(x in u for u in urls for x in ("/about", "linkedin", "/blog/"))


def test_job_links_are_same_host_job_like_and_deduplicated():
    links = ats.job_links((FIX / "careers_index.html").read_text(), "https://juspay.io/careers")
    assert links == ["https://juspay.io/careers/jp-1021", "https://juspay.io/careers/ase"]


@respx.mock
async def test_careers_probe_accepts_pages_whose_job_links_carry_structured_data(client):
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_index.html").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_job.html").read_text())
    respx.get("https://juspay.io/careers/ase").respond(text="<html>no data</html>")
    b = await discover.careers_probe(client, "https://juspay.io")
    assert (b.ats, b.slug) == ("careers", "https://juspay.io/careers")


@pytest.mark.parametrize("url", ["http://127.0.0.1/careers", "https://169.254.169.254/latest", "file:///etc/passwd"])
async def test_careers_adapter_refuses_private_or_non_http_boards(client, url):
    with pytest.raises(ats.BoardError):
        await ats.list_jobs(client, "careers", url)


@respx.mock
async def test_careers_adapter_skips_job_links_that_resolve_to_private_addresses(client, monkeypatch):
    from hungry_hunt.core import http

    monkeypatch.setattr(http, "resolve", lambda host: {"10.0.0.9"} if host == "juspay.io" else {"93.184.216.34"})
    respx.get("https://juspay.io/careers").respond(text=(FIX / "careers_index.html").read_text())
    with pytest.raises(ats.BoardError):
        await ats.list_jobs(client, "careers", "https://juspay.io/careers")


def test_jsonld_blocks_scan_is_linear_on_hostile_input():
    import time

    page = "<script type=application/ld+json>" + "{" * 200000  # never closed, deeply nested
    t = time.monotonic()
    assert ats.jsonld_postings(page) == []
    assert time.monotonic() - t < 1.0
    page2 = '<script type="application/ld+json">{"@type":"JobPosting","title":"X","url":"u"}</script>' * 300
    assert len(ats.jsonld_postings(page2)) == 300


@respx.mock
async def test_get_text_validates_every_redirect_hop(client, monkeypatch):
    from hungry_hunt.core import http

    respx.get("https://juspay.io/careers").respond(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
    with pytest.raises(http.BoardError):
        await http.get_text(client, "https://juspay.io/careers")
    respx.get("https://a.example/jobs").respond(301, headers={"Location": "https://b.example/openings"})
    respx.get("https://b.example/openings").respond(text="<html>ok</html>")
    assert await http.get_text(client, "https://a.example/jobs") == "<html>ok</html>"
    loop = respx.get("https://loop.example/x").respond(302, headers={"Location": "https://loop.example/x"})
    with pytest.raises(http.BoardError):
        await http.get_text(client, "https://loop.example/x")
    assert loop.call_count <= 4


@respx.mock
async def test_sitemap_job_urls_follows_index_and_keeps_job_like_urls(client):
    respx.get("https://juspay.io/robots.txt").respond(text="User-agent: *\nSitemap: https://juspay.io/sitemap.xml\n")
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_index.xml").read_text())
    respx.get("https://juspay.io/sitemap-pages.xml").respond(
        text='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://juspay.io/about</loc></url></urlset>'
    )
    respx.get("https://juspay.io/sitemap-jobs.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    urls = await discover.sitemap_job_urls(client, "https://juspay.io")
    assert urls == ["https://juspay.io/careers/jp-1021", "https://juspay.io/careers/ase"]


@respx.mock
async def test_sitemap_job_urls_falls_back_to_default_location_without_robots(client):
    respx.get("https://acme.example/robots.txt").respond(404)
    respx.get("https://acme.example/sitemap.xml").respond(
        text=(FIX / "sitemap_jobs.xml").read_text().replace("juspay.io", "acme.example")
    )
    assert len(await discover.sitemap_job_urls(client, "https://acme.example")) == 2


@respx.mock
async def test_careers_adapter_uses_sitemap_when_the_index_page_is_javascript(client):
    respx.get("https://juspay.io/careers").respond(text="<html><body><div id=app></div></body></html>")
    respx.get("https://juspay.io/robots.txt").respond(404)
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_job.html").read_text())
    respx.get("https://juspay.io/careers/ase").respond(text="<html>no data</html>")
    postings = await ats.list_jobs(client, "careers", "https://juspay.io/careers")
    assert [p.external_id for p in postings] == ["JP-1021"]


@respx.mock
async def test_careers_probe_accepts_sites_whose_sitemap_leads_to_structured_data(client):
    respx.get("https://juspay.io/careers").respond(text="<html><body><div id=app></div></body></html>")
    respx.get("https://juspay.io/robots.txt").respond(404)
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_job.html").read_text())
    respx.get("https://juspay.io/careers/ase").respond(text="<html>no data</html>")
    b = await discover.careers_probe(client, "https://juspay.io")
    assert (b.ats, b.slug) == ("careers", "https://juspay.io/careers")


@respx.mock
async def test_careers_adapter_reads_plain_html_job_pages_without_structured_data(client):
    respx.get("https://juspay.io/careers").respond(text="<html><div id='root'></div></html>")
    respx.get("https://juspay.io/robots.txt").respond(404)
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_plain_job.html").read_text())
    respx.get("https://juspay.io/careers/ase").respond(
        text="<html><head><title>Life at Juspay</title></head><body><h1>Life at Juspay</h1><p>We love Haskell.</p></body></html>"
    )
    (p,) = await ats.list_jobs(client, "careers", "https://juspay.io/careers")
    assert (p.title, p.external_id, p.url) == (
        "Software Development Engineer Backend",
        "/careers/jp-1021",
        "https://juspay.io/careers/jp-1021",
    )
    assert "Bengaluru" in p.description and "0-2 years" in p.description
    assert "Senior Staff" not in p.description and "Home" not in p.description


@respx.mock
async def test_careers_probe_accepts_sites_whose_job_pages_are_plain_html(client):
    respx.get("https://juspay.io/careers").respond(text="<html><div id='root'></div></html>")
    respx.get("https://juspay.io/robots.txt").respond(404)
    respx.get("https://juspay.io/sitemap.xml").respond(text=(FIX / "sitemap_jobs.xml").read_text())
    respx.get("https://juspay.io/careers/jp-1021").respond(text=(FIX / "careers_plain_job.html").read_text())
    b = await discover.careers_probe(client, "https://juspay.io")
    assert b.ats == "careers" and b.slug == "https://juspay.io/careers"


def test_html_posting_handles_huge_pages_with_unclosed_tags_quickly():
    import time

    page = "<header>" * 3000 + "<h1>SDE</h1>" + "x" * 2_000_000 + "Responsibilities"
    t = time.perf_counter()
    ats.html_posting(page, "https://x.example/careers/sde")
    assert time.perf_counter() - t < 1


@pytest.mark.parametrize("h1", ["Life at PhonePe", "Jump Aboard the Rocketship", "Careers", "Open positions"])
def test_html_posting_rejects_hub_pages_whose_heading_is_not_a_role(h1):
    page = f"<html><body><h1>{h1}</h1><h2>Responsibilities</h2><h2>Requirements</h2><a>Apply now</a></body></html>"
    assert ats.html_posting(page, "https://x.example/careers/life") is None


@pytest.mark.parametrize(
    "h1",
    [
        "Software Development Engineer Backend",
        "AEO_GEO Specialist",
        "SDE I",
        "Associate Product Manager",
        "Data Scientist",
    ],
)
def test_html_posting_accepts_role_headings(h1):
    page = f"<html><body><h1>{h1}</h1><h2>Responsibilities</h2><p>Bengaluru</p></body></html>"
    assert ats.html_posting(page, "https://x.example/careers/x").title == h1


@respx.mock
async def test_careers_adapter_plain_html_fallback_skips_index_like_links(client):
    respx.get("https://whatfix.example/").respond(text='<a href="/careers/">Careers</a>')
    respx.get("https://whatfix.example/careers/").respond(text=(FIX / "careers_plain_job.html").read_text())
    assert await ats.list_jobs(client, "careers", "https://whatfix.example/") == []


def test_html_posting_handles_many_unclosed_headings_quickly():
    import time

    page = "<h1>" * 50_000 + "x" * 300_000
    t = time.perf_counter()
    ats.html_posting(page, "https://x.example/careers/sde")
    assert time.perf_counter() - t < 1
