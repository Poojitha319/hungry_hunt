from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from hunt import funding
from hunt.config import Settings
from hunt.models import Company, FundingSignal

FIX = Path(__file__).parent / "fixtures" / "funding_feed.xml"
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)


def test_parse_feed_returns_items_with_dates():
    items = funding.parse_feed(FIX.read_bytes(), source="inc42")
    assert len(items) == 8 and items[0].title.startswith("NeoGrowth") and items[0].published.tzinfo is not None
    assert items[0].link == "https://inc42.com/buzz/neogrowth-raises" and items[0].source == "inc42"


@pytest.mark.parametrize("title,company", [
    ("NeoGrowth Raises ₹85 Cr To Expand Digital Lending Capabilities", "NeoGrowth"),
    ("D2C Lifestyle Brand DailyObjects Raises ₹332 Cr To Expand Offline Presence", "DailyObjects"),
    ("Hevo Data bags $30 Mn Series B led by Sequoia", "Hevo Data"),
    ("Vesta raises $30M to bring swarms of agents to mortgage lenders", "Vesta"),
    ("At 19, founder raises $11M for Ghost, maker of a $3,499 computer for personal AI", "Ghost"),
    ("Fintech startup Jar secures $50 Mn in Series C round", "Jar"),
    ("Indian AI Startup Funding Surges 265% YoY In Q3, Will Momentum Continue?", None),
    ("NABARD-backed NABVENTURES raises Rs 450 Cr for second fund", None),
    ("How to prepare for your Series A", None),
    ("Endeavor Catalyst raises $320M for founders elsewhere", None),
])
def test_extract_company(title, company):
    assert funding.extract_company(title) == company


def test_ingest_marks_registry_companies_and_records_unmatched(session):
    hevo = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data")
    session.add(hevo)
    session.flush()
    items = funding.parse_feed(FIX.read_bytes(), source="inc42")
    stats = funding.ingest(session, Settings(user_id="u"), items, NOW)
    assert (stats.items, stats.funding_events, stats.matched, stats.unmatched) == (8, 5, 1, 4)
    assert hevo.funded_at == datetime(2026, 10, 7, 8, 0, tzinfo=UTC) and "Series B" in hevo.funding_note
    names = sorted(s.name for s in session.scalars(select(FundingSignal).where(FundingSignal.company_id.is_(None))))
    assert names == ["DailyObjects", "Ghost", "NeoGrowth", "Vesta"]
    again = funding.ingest(session, Settings(user_id="u"), items, NOW)
    assert again.funding_events == 0 and len(session.scalars(select(FundingSignal)).all()) == 5


def test_ingest_never_moves_funded_at_backwards(session):
    hevo = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data", funded_at=NOW, funding_note="newer")
    session.add(hevo)
    session.flush()
    funding.ingest(session, Settings(user_id="u"), funding.parse_feed(FIX.read_bytes(), source="inc42"), NOW)
    assert hevo.funded_at == NOW and hevo.funding_note == "newer"


def test_recently_funded_companies_rank_with_fast_hirers_and_footer_lists_unwatched(session):
    from hunt import digest
    from tests.test_digest import NOW as DNOW
    from tests.test_digest import mk_company as dc
    from tests.test_digest import mk_job as dj
    from tests.test_digest import mk_profile as dp
    dp(session)
    funded = dc(session, "funded", name="Funded Co", funded_at=DNOW - timedelta(days=30), funding_note="raised Series A")
    plain = dc(session, "plain", name="Plain Co")
    dj(session, funded, "f", title="Software Engineer", score=70)
    dj(session, plain, "p", title="Software Engineer", score=95)
    session.add(FundingSignal(user_id="u", name="Jar", title="Jar secures $50 Mn", link="https://x/jar", source="inc42", published=DNOW, seen_at=DNOW))
    session.flush()
    d = digest.build(session, Settings(user_id="u"), DNOW)
    assert [j.company for j in d.new["India"]] == ["Funded Co", "Plain Co"]
    assert d.new["India"][0].recently_funded is True
    assert d.coverage.funded_unwatched == ["Jar"]
    _, html = digest.render(d, Settings(user_id="u"))
    assert "recently funded" in html and "Jar" in html


@pytest.mark.parametrize("title", [
    "From DailyObjects To StockGro — Indian Startups Raised About $123 Mn This Week",
    "[Weekly funding roundup Oct 3-9] Steep decline in VC inflow",
    "Indian startups raised $2 Bn in Q3: report",
])
def test_roundup_headlines_are_not_companies(title):
    assert funding.extract_company(title) is None
