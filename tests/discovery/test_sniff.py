import httpx
import pytest
from sqlalchemy import select

from hungry_hunt.config import Settings
from hungry_hunt.db import Base, make_engine, session_factory
from hungry_hunt.db.models import Company
from hungry_hunt.discovery import discover, sniff


async def test_sniff_recognises_ats_api_calls_made_by_the_app():
    async def capture(url):
        return [
            "<html><div id=root></div></html>",
            "GET https://api.smartrecruiters.com/v1/companies/SWIGGY/postings?limit=100",
            '{"content": []}',
        ]

    assert await sniff.sniff("https://careers.swiggy.in/", capture=capture) == discover.Board(
        ats="smartrecruiters", slug="swiggy"
    )


async def test_sniff_reports_unsupported_vendors_and_nothing_quietly():
    async def darwin(url):
        return ['<iframe src="https://rapido.darwinbox.in/ms/candidate/careers">']

    b = await sniff.sniff("https://rapido.example/careers", capture=darwin)
    assert b.ats == "unsupported" and "darwinbox" in b.notes.lower()

    async def plain(url):
        return ["<html>hi</html>"]

    assert await sniff.sniff("https://plain.example", capture=plain) is None


async def test_sniff_source_upgrades_rows_in_place(monkeypatch):
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
                    slug="phonepe",
                    name="PhonePe",
                    status="target",
                    board_url="https://www.phonepe.com/careers/",
                    notes="custom",
                )
            ],
        )
        s.commit()

    async def capture(url):
        return ['{"applyUrl": "https://jobs.smartrecruiters.com/PHONEPELIMITED/1000-x"}']

    monkeypatch.setattr(sniff, "capture", capture)
    async with httpx.AsyncClient() as client:
        stats = await discover.discover(sf, Settings(user_id="u"), ["sniff"], client)
    assert stats.per_source["sniff"] == 1
    with sf() as s:
        (c,) = s.scalars(select(Company)).all()
        assert (c.ats, c.slug, c.status, c.name) == ("smartrecruiters", "phonepelimited", "target", "PhonePe")


async def test_sniff_source_reports_missing_browser_instead_of_crashing(monkeypatch):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        discover.upsert_companies(
            s,
            "u",
            [discover.Board(ats="unknown", slug="zerodha", name="Zerodha", board_url="https://zerodha.com/careers")],
        )
        s.commit()

    async def capture(url):
        raise sniff.BrowserUnavailable("playwright is not installed")

    monkeypatch.setattr(sniff, "capture", capture)
    async with httpx.AsyncClient() as client:
        stats = await discover.discover(sf, Settings(user_id="u"), ["sniff"], client)
    assert any("playwright" in e for e in stats.errors)


@pytest.mark.skipif(not sniff.available(), reason="playwright not installed")
async def test_capture_sees_frames_links_and_xhr_bodies():
    html = '<html><body><a href="https://jobs.lever.co/acme">Jobs</a><script>fetch("data:application/json,{\\"ok\\":1}")</script></body></html>'
    texts = await sniff.capture("data:text/html," + html, follow=False)
    joined = "\n".join(texts)
    assert "jobs.lever.co/acme" in joined
