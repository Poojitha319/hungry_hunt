import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt import funding, http, rules
from hunt.ats import board_url, html_posting, job_links, jsonld_postings
from hunt.config import Settings
from hunt.models import Company, Run
from hunt.sitemaps import sitemap_job_urls

URL_PATTERNS = [
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)", re.IGNORECASE)),
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([\w-]+)", re.IGNORECASE)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/[^\"'\s]*?[?&]for=([\w-]+)", re.IGNORECASE)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([\w-]+)", re.IGNORECASE)),
    ("greenhouse", re.compile(r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([\w-]+)", re.IGNORECASE)),
    ("lever", re.compile(r"api(?:\.eu)?\.lever\.co/v0/postings/([\w.-]+)", re.IGNORECASE)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([\w.%-]+)", re.IGNORECASE)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.IGNORECASE)),
    ("workable", re.compile(r"https?://([\w-]+)\.workable\.com", re.IGNORECASE)),
]
WORKDAY_URL = re.compile(r"https?://([\w-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.IGNORECASE)
IGNORE = {"", "embed", "v1", "api", "apply", "www", "app", "help", "resources", "jobs", "careers", "favicon.ico", "robots.txt", "sitemap.xml", "static", "assets", "js", "css", "img", "images"}
UNSUPPORTED = re.compile(r"https?://[^\s\"'<>]*?(kula\.ai|darwinbox|keka\.com|trakstar|zohorecruit|"
                         r"jobvite\.com|freshteam\.com|bamboohr\.com|icims\.com|successfactors|taleo\.net)[^\s\"'<>]*", re.IGNORECASE)
WAYBACK = "https://web.archive.org/cdx/search/cdx"
WAYBACK_HOSTS = ("jobs.lever.co", "jobs.eu.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.ashbyhq.com")
WAYBACK_BACKOFF = (15, 45, 90)
CRAWLS = ["CC-MAIN-2026-39", "CC-MAIN-2026-34", "CC-MAIN-2026-30", "CC-MAIN-2025-51", "CC-MAIN-2025-38"]
CC_PATTERNS = [("greenhouse", "boards.greenhouse.io/*"), ("greenhouse", "job-boards.greenhouse.io/*"), ("lever", "jobs.lever.co/*"),
               ("lever", "jobs.eu.lever.co/*"), ("ashby", "jobs.ashbyhq.com/*")]
GITHUB_LISTS = ["https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
                "https://raw.githubusercontent.com/remoteintech/remote-jobs/main/README.md",
                "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md"]
YC_URL = "https://yc-oss.github.io/api/companies/all.json"
PROBE_PATHS = ("/careers", "/jobs", "/")
PROBE_LIMIT = 200


class Board(BaseModel):
    ats: str
    slug: str
    name: str | None = None
    status: str = "watch"
    notes: str = ""
    board_url: str | None = None


@dataclass
class DiscoverStats:
    new_companies: int = 0
    per_source: dict = field(default_factory=dict)
    probed: int = 0
    enriched: int = 0
    errors: list = field(default_factory=list)


def parse_board(text: str) -> Board:
    text = text.strip()
    if m := re.fullmatch(r"(greenhouse|lever|ashby|smartrecruiters|workable|amazon|google):([\w.-]+)", text, re.IGNORECASE):
        ats = m.group(1).lower()
        return Board(ats=ats, slug=m.group(2) if ats in ("amazon", "google") else m.group(2).lower())
    if m := re.search(r"amazon\.jobs/\S*[?&]country=([A-Z]{3})", text):
        return Board(ats="amazon", slug=m.group(1))
    if m := re.search(r"google\.com/about/careers/\S*[?&]location=([\w-]+)", text, re.IGNORECASE):
        return Board(ats="google", slug=m.group(1))
    if m := re.fullmatch(r"careers:(https?://\S+)", text, re.IGNORECASE):
        return Board(ats="careers", slug=m.group(1), board_url=m.group(1))
    if m := re.fullmatch(r"workday:([\w-]+\.wd\d+\.myworkdayjobs\.com/[\w-]+/[\w-]+)", text, re.IGNORECASE):
        return Board(ats="workday", slug=m.group(1))
    if m := WORKDAY_URL.search(text):
        host, site = m.group(1).lower(), m.group(2)
        if site.lower() not in ("job", "jobs", "wday"):
            return Board(ats="workday", slug=f"{host}/{host.split('.')[0]}/{site}")
    for ats, pattern in URL_PATTERNS:
        if (m := pattern.search(text)) and m.group(1).lower() not in IGNORE:
            return Board(ats=ats, slug=m.group(1).lower())
    raise ValueError(f"not a Greenhouse/Lever/Ashby board: {text}")


def boards_from_text(text: str) -> list[Board]:
    seen, out = set(), []
    for host, site in WORKDAY_URL.findall(text):
        host = host.lower()
        slug = f"{host}/{host.split('.')[0]}/{site}"
        if site.lower() not in ("job", "jobs", "wday") and ("workday", slug) not in seen:
            seen.add(("workday", slug))
            out.append(Board(ats="workday", slug=slug))
    for ats, pattern in URL_PATTERNS:
        for m in pattern.finditer(text):
            slug = m.group(1).lower()
            if slug not in IGNORE and (ats, slug) not in seen:
                seen.add((ats, slug))
                out.append(Board(ats=ats, slug=slug))
    return out


def upsert_companies(session: Session, user_id: str, boards: Iterable[Board]) -> int:
    existing = set(session.execute(select(Company.ats, Company.slug).where(Company.user_id == user_id)).all())
    now = datetime.now(UTC)
    inserted = 0
    for b in boards:
        if (b.ats, b.slug) in existing:
            continue
        url = b.board_url or board_url(b.ats, b.slug)
        session.add(Company(user_id=user_id, ats=b.ats, slug=b.slug[:255], name=(b.name or b.slug)[:255], status=b.status, notes=b.notes,
                            board_url=url[:512] if url else None, first_seen=now))
        existing.add((b.ats, b.slug))
        inserted += 1
    session.flush()
    return inserted


async def _wayback_get(client, params):
    for attempt in range(len(WAYBACK_BACKOFF) + 1):
        try:
            r = await client.get(WAYBACK, params=params, timeout=120)
            if r.status_code == 200:
                return r.text
        except httpx.HTTPError:
            pass
        if attempt < len(WAYBACK_BACKOFF):
            await asyncio.sleep(WAYBACK_BACKOFF[attempt])
    return None


async def wayback_slugs(client: httpx.AsyncClient, host: str) -> set[str]:
    base = {"url": f"{host}/*", "output": "json", "fl": "original", "collapse": "urlkey", "filter": "statuscode:200", "from": "2023"}
    pages_text = await _wayback_get(client, {"url": base["url"], "showNumPages": "true"})
    if pages_text is None or not pages_text.strip().isdigit():
        return set()
    pattern = next(p for ats, p in URL_PATTERNS if ats == next(a for a in ("lever", "greenhouse", "ashby") if a in host))
    found = set()
    for page in range(int(pages_text.strip())):
        text = await _wayback_get(client, {**base, "page": str(page)})
        if text is None:
            break
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            rows = [[line] for line in text.splitlines()]
        for row in rows[1:] if rows and rows[0] == ["original"] else rows:
            if (m := pattern.search(row[0])) and m.group(1).lower() not in IGNORE:
                found.add(m.group(1).lower())
    return found


async def commoncrawl_slugs(client: httpx.AsyncClient, crawls: list[str], patterns=None) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for crawl in crawls:
        for ats, glob in patterns or CC_PATTERNS:
            index = f"https://index.commoncrawl.org/{crawl}-index"
            try:
                info = await client.get(index, params={"url": glob, "showNumPages": "true"}, timeout=120)
                pages = info.json()["pages"] if info.status_code == 200 else 0
            except (httpx.HTTPError, ValueError, KeyError):
                continue
            regex = next(p for a, p in URL_PATTERNS if a == ats)
            for page in range(pages):
                try:
                    r = await client.get(index, params={"url": glob, "output": "json", "fl": "url", "page": page}, timeout=120)
                except httpx.HTTPError:
                    continue
                for line in r.text.splitlines():
                    try:
                        url = json.loads(line)["url"]
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
                    if (m := regex.search(url)) and m.group(1).lower() not in IGNORE:
                        found.setdefault(ats, set()).add(m.group(1).lower())
    return found


def _safe_root(website: str) -> str | None:
    u = urlsplit(website if "://" in website else f"https://{website}")
    return f"{u.scheme}://{u.netloc}" if http.safe_url(f"{u.scheme}://{u.netloc}") else None


MAX_REDIRECTS = 3


async def _safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    for _ in range(MAX_REDIRECTS + 1):
        if _safe_root(url) is None:
            return None
        try:
            r = await client.get(url, timeout=10, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        return r
    return None


async def careers_probe(client: httpx.AsyncClient, website: str) -> Board | None:
    root = _safe_root(website)
    if root is None:
        return None
    for path in PROBE_PATHS:
        r = await _safe_get(client, root + path)
        if r is None or r.status_code != 200:
            continue
        if boards := boards_from_text(r.text):
            return boards[0]
        if jsonld_postings(r.text):
            return Board(ats="careers", slug=str(r.url), board_url=str(r.url), notes="careers page (JobPosting structured data)")
        candidates = job_links(r.text, str(r.url))[:5] or (await sitemap_job_urls(client, root))[:5]
        for link in candidates:
            sub = await _safe_get(client, link)
            if sub is not None and sub.status_code == 200 and (jsonld_postings(sub.text) or html_posting(sub.text, link)):
                return Board(ats="careers", slug=str(r.url), board_url=str(r.url), notes="careers page (JobPosting data on job pages)")
        if m := UNSUPPORTED.search(r.text):
            vendor = m.group(1).split(".")[0]
            return Board(ats="unsupported", slug=urlsplit(root).netloc.removeprefix("www.").split(".")[0], board_url=m.group(0),
                         notes=f"{vendor} ATS (not readable yet)")
    return None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def yc_india_candidates(yc: list[dict]) -> list[dict]:
    return [c for c in yc if c.get("status") == "Active"
            and ("India" in (c.get("regions") or []) or "india" in (c.get("all_locations") or "").lower())]


def enrich_from_yc(session: Session, user_id: str, yc: list[dict]) -> int:
    by_name = {_norm(c["name"]): c for c in yc if c.get("name")}
    n = 0
    for company in session.scalars(select(Company).where(Company.user_id == user_id)):
        c = by_name.get(_norm(company.name))
        if not c:
            continue
        company.yc_batch, company.team_size = c.get("batch"), c.get("team_size")
        if company.team_size:
            company.tier = rules.tier(company.team_size, 0)
        n += 1
    session.flush()
    return n


def _upgrade(session: Session, user_id: str, c: Company, b: Board) -> int:
    slug = c.slug if b.ats == "unsupported" else b.slug[:255]
    twin = session.scalar(select(Company).where(Company.user_id == user_id, Company.ats == b.ats, Company.slug == slug, Company.id != c.id))
    if twin is not None:
        session.delete(c)
        return 0
    if b.ats == "unsupported":
        c.ats, c.board_url, c.notes = "unsupported", b.board_url, c.notes or b.notes
        return 0
    c.ats, c.slug, c.board_url, c.notes = b.ats, b.slug[:255], b.board_url or board_url(b.ats, b.slug), b.notes
    c.fail_count, c.dormant = 0, False
    return 1


async def discover(sf, settings: Settings, sources: list[str], client: httpx.AsyncClient, now: datetime | None = None) -> DiscoverStats:
    now = now or datetime.now(UTC)
    stats = DiscoverStats()

    def add(source: str, boards: list[Board]):
        with sf() as session:
            n = upsert_companies(session, settings.user_id, boards)
            session.commit()
        stats.per_source[source] = n
        stats.new_companies += n

    for source in sources:
        try:
            if source == "wayback":
                for host in WAYBACK_HOSTS:
                    ats = next(a for a in ("lever", "greenhouse", "ashby") if a in host)
                    add(f"wayback:{host}", [Board(ats=ats, slug=s) for s in await wayback_slugs(client, host)])
            elif source == "cc":
                found = await commoncrawl_slugs(client, CRAWLS)
                add(source, [Board(ats=a, slug=s) for a, slugs in found.items() for s in slugs])
            elif source == "github":
                boards = []
                for url in GITHUB_LISTS:
                    r = await client.get(url, timeout=30)
                    if r.status_code == 200:
                        boards += boards_from_text(r.text)
                add(source, boards)
            elif source == "yc":
                yc = (await client.get(YC_URL, timeout=60)).json()
                with sf() as session:
                    stats.enriched = enrich_from_yc(session, settings.user_id, yc)
                    known = {_norm(c.name) for c in session.scalars(select(Company).where(Company.user_id == settings.user_id))}
                    session.commit()
                boards = []
                for c in [c for c in yc_india_candidates(yc) if _norm(c["name"]) not in known][:PROBE_LIMIT]:
                    stats.probed += 1
                    if (b := await careers_probe(client, c["website"])) if c.get("website") else None:
                        boards.append(b.model_copy(update={"name": c["name"]}))
                add(source, boards)
            elif source in ("careers", "sniff"):
                with sf() as session:
                    query = select(Company).where(Company.user_id == settings.user_id, Company.ats.in_(["unknown", "unsupported"]), Company.status != "avoid")
                    if source == "sniff":
                        query = query.where(Company.status.in_(["target", "watch"]), Company.board_url.isnot(None))
                    targets = [(c.id, c.board_url or c.name) for c in session.scalars(query)]
                upgraded = 0
                for cid, url in targets[:PROBE_LIMIT]:
                    if not url.startswith("http"):
                        continue
                    stats.probed += 1
                    try:
                        if source == "sniff":
                            from hunt import sniff as sniffer
                            b = await sniffer.sniff(url, capture=sniffer.capture)
                        else:
                            b = await careers_probe(client, url)
                        if b:
                            with sf() as session:
                                upgraded += _upgrade(session, settings.user_id, session.get(Company, cid), b)
                                session.commit()
                    except Exception as e:
                        stats.errors.append(f"{source} {url}: {type(e).__name__}: {str(e)[:120]}")
                stats.per_source[source] = upgraded
                stats.new_companies += upgraded
            elif source == "funding":
                items = await funding.fetch_feeds(client)
                with sf() as session:
                    fs = funding.ingest(session, settings, items, now)
                    session.commit()
                stats.per_source[source] = fs.funding_events
            else:
                stats.errors.append(f"unknown source {source}")
        except Exception as e:
            stats.errors.append(f"{source}: {type(e).__name__}: {e}")
    with sf() as session:
        session.add(Run(stage="discover", started_at=now, finished_at=datetime.now(UTC), stats=asdict(stats)))
        session.commit()
    return stats
