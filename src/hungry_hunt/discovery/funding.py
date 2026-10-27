"""Funding news feeds that mark recently funded companies for a rank boost."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree as ET
from sqlalchemy import select
from sqlalchemy.orm import Session

from hungry_hunt.config import Settings
from hungry_hunt.db.models import Company, FundingSignal

FEEDS = {
    "inc42": "https://inc42.com/feed/",
    "yourstory": "https://yourstory.com/feed",
    "techcrunch": "https://techcrunch.com/category/venture/feed/",
}
VERB = re.compile(r"\b(raises?|raised|bags|secures|lands|nets|closes|picks up|snags)\b", re.IGNORECASE)
NOT_A_COMPANY = re.compile(
    r"\bfunds?\b|\bventures\b|\bcapital\b|\bpartners\b|\bcatalyst\b|\baccelerator\b|\bvc\b|"
    r"\bthis week\b|\broundup\b|\bstartups\s+raised\b|\breport\b|^from\b|^\[",
    re.IGNORECASE,
)
GENERIC = re.compile(
    r"^(?:at \d+,?\s*)?(?:a |an |the |this )?(?:founder|startup|company|firm|unicorn|team|duo|trio)s?$", re.IGNORECASE
)
DESCRIPTOR = re.compile(
    r"\b(?:d2c|b2b|b2c|saas|ai|fintech|edtech|healthtech|agritech|proptech|insurtech|deeptech|lifestyle|brand|startup|"
    r"company|firm|platform|indian|india|bengaluru|bangalore|mumbai|delhi|hyderabad|pune|chennai|based|backed|unicorn|"
    r"ev|gaming|logistics|quick|commerce|consumer|tech|digital|lending|neobank|payments)\b|[\w-]+-based",
    re.IGNORECASE,
)
FOR_X = re.compile(r"\bfor ([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*)*)")
RECENT = timedelta(days=180)
LISTED = timedelta(days=60)


@dataclass
class FeedItem:
    title: str
    link: str
    published: datetime
    source: str


@dataclass
class FundingStats:
    items: int = 0
    funding_events: int = 0
    matched: int = 0
    unmatched: int = 0


def parse_feed(xml: bytes, source: str) -> list[FeedItem]:
    items = []
    for node in ET.fromstring(xml).iter("item"):
        title, link = (node.findtext("title") or "").strip(), (node.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = datetime.now(UTC)
        if title and link:
            items.append(
                FeedItem(
                    title=re.sub(r"\s+", " ", title), link=link, published=published.astimezone(UTC), source=source
                )
            )
    return items


def extract_company(title: str) -> str | None:
    m = VERB.search(title)
    if not m or NOT_A_COMPANY.search(title):
        return None
    subject = title[: m.start()].strip(" ,:-–")
    if GENERIC.match(subject):
        hit = FOR_X.search(title[m.end() :])
        return hit.group(1).strip() if hit else None
    cleaned = DESCRIPTOR.sub(" ", subject)
    tokens = [t for t in re.split(r"\s+", cleaned) if t and t[0].isalnum()]
    return " ".join(tokens).strip(" ,") or None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match(companies: Sequence[Company], name: str) -> Company | None:
    n = _norm(name)
    exact = [c for c in companies if _norm(c.name) == n]
    if exact:
        return exact[0]
    loose = [
        c for c in companies if len(n) >= 4 and len(_norm(c.name)) >= 4 and (n in _norm(c.name) or _norm(c.name) in n)
    ]
    return loose[0] if len(loose) == 1 else None


def ingest(session: Session, settings: Settings, items: list[FeedItem], now: datetime) -> FundingStats:
    stats = FundingStats(items=len(items))
    seen = set(session.scalars(select(FundingSignal.link).where(FundingSignal.user_id == settings.user_id)))
    companies = session.scalars(select(Company).where(Company.user_id == settings.user_id)).all()
    for item in items:
        if item.link in seen:
            continue
        name = extract_company(item.title)
        if not name:
            continue
        stats.funding_events += 1
        company = _match(companies, name)
        if company:
            stats.matched += 1
            if company.funded_at is None or item.published > company.funded_at:
                company.funded_at, company.funding_note = item.published, item.title
        else:
            stats.unmatched += 1
        session.add(
            FundingSignal(
                user_id=settings.user_id,
                name=name[:255],
                title=item.title[:512],
                link=item.link[:1024],
                source=item.source,
                published=item.published,
                seen_at=now,
                company_id=company.id if company else None,
            )
        )
        seen.add(item.link)
    session.flush()
    return stats


def unwatched(session: Session, user_id: str, now: datetime, limit: int = 10) -> list[str]:
    rows = session.scalars(
        select(FundingSignal)
        .where(
            FundingSignal.user_id == user_id,
            FundingSignal.company_id.is_(None),
            FundingSignal.published >= now - LISTED,
        )
        .order_by(FundingSignal.published.desc())
        .limit(limit)
    )
    return [r.name for r in rows]


def recently_funded(company: Company, now: datetime) -> bool:
    return bool(company.funded_at and now - company.funded_at <= RECENT)


async def fetch_feeds(client: httpx.AsyncClient) -> list[FeedItem]:
    items = []
    for source, url in FEEDS.items():
        try:
            r = await client.get(url, timeout=30, headers={"User-Agent": "hungry-hunt/0.1"})
            if r.status_code == 200:
                items += parse_feed(r.content, source)
        except (httpx.HTTPError, ET.ParseError):
            continue
    return items
