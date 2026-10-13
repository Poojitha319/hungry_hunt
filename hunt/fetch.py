import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt import rules
from hunt.ats import board_url
from hunt.config import Settings
from hunt.http import BoardError
from hunt.models import Company, Job, Run
from hunt.ports import JobSource
from hunt.schemas import Coverage, Posting

SUPPORTED = ("greenhouse", "lever", "ashby", "careers", "smartrecruiters", "workday", "workable_feed", "amazon", "google")
FEEDS = {"workable_feed": "workable"}
DEAD_AFTER = 30
UNPROVEN_ATTEMPTS = 3
DESCRIPTION_TTL = timedelta(days=7)
DORMANT_AFTER = timedelta(days=30)
MAX_TEXT = 512
MAX_URL = 1024


@dataclass
class Listing:
    postings: list[Posting] = field(default_factory=list)
    ok: bool = True
    status: int | None = None
    descriptions_fetched: int = 0


@dataclass
class BoardOutcome:
    ok: bool
    status: int | None = None
    new: int = 0
    closed: int = 0
    seen: int = 0
    stored: int = 0
    descriptions_fetched: int = 0


def _hash(title: str, location: str, description: str | None) -> str:
    return hashlib.sha1(f"{title}|{location}|{description or ''}".encode()).hexdigest()


def _storable(p: Posting) -> bool:
    loc = rules.location(p.location_raw, p.country, p.remote_flag)
    return loc.is_india or (loc.is_remote and not loc.remote_restricted) or not p.location_raw.strip()


async def collect(company: Company, source: JobSource, known: set[str] = frozenset(), *, now: datetime | None = None,
                  max_posted_age_days: int | None = None) -> Listing:
    try:
        postings = await source.list_jobs(company.ats, company.slug)
    except BoardError as e:
        return Listing(ok=False, status=e.status)
    listing = Listing(postings=postings)
    for p in postings:
        too_old = bool(max_posted_age_days and now and p.posted_at and now - p.posted_at > timedelta(days=max_posted_age_days))
        wanted = _storable(p) and rules.prefilter(p) and not too_old
        if not wanted:
            p.description = None
            continue
        if p.description is None and p.external_id not in known:
            try:
                p.description = await source.description(company.ats, company.slug, p.detail_ref or p.external_id) or None
            except BoardError:
                continue
            listing.descriptions_fetched += bool(p.description)
    return listing


def apply_listing(session: Session, company: Company, postings: list[Posting], now: datetime,
                  existing: dict[str, Job] | None = None) -> tuple[int, int]:
    if existing is None:
        existing = {j.external_id: j for j in session.scalars(select(Job).where(Job.company_id == company.id))}
    new = 0
    for p in postings:
        if not _storable(p):
            continue
        loc = rules.location(p.location_raw, p.country, p.remote_flag)
        j = existing.get(p.external_id)
        if j is None:
            j = Job(company_id=company.id, external_id=p.external_id[:255], first_seen=now)
            session.add(j)
            existing[p.external_id] = j
            new += 1
        j.title, j.location_raw, j.url, j.posted_at = p.title[:MAX_TEXT], p.location_raw[:MAX_TEXT], p.url[:MAX_URL], p.posted_at
        j.is_india, j.is_remote, j.last_seen, j.closed_at = loc.is_india, loc.is_remote, now, None
        if p.description is not None and rules.prefilter(p):
            j.description, j.description_at = p.description, now
        j.content_hash = _hash(j.title, j.location_raw, j.description)
    closed = 0
    for j in existing.values():
        if j.closed_at is None and j.last_seen < now:
            j.closed_at = now
            closed += 1
    session.flush()
    return new, closed


def apply_board(session: Session, company: Company, listing: Listing, now: datetime, existing: dict[str, Job] | None = None) -> BoardOutcome:
    company.last_fetched = now
    if not listing.ok:
        company.fail_count += 1
        return BoardOutcome(ok=False, status=listing.status)
    company.last_ok, company.fail_count = now, 0
    names = [p.company_name for p in listing.postings if p.company_name]
    if names and company.name in ("", company.slug):
        company.name = names[0][:255]
    if company.kind == "unknown":
        company.kind = rules.company_kind(company.name, company.slug, [p.title for p in listing.postings])
    if company.tier == "unknown":
        company.tier = rules.tier(company.team_size, len(listing.postings))
    new, closed = apply_listing(session, company, listing.postings, now, existing)
    if any(_storable(p) and rules.prefilter(p) for p in listing.postings):
        company.last_relevant_at, company.dormant = now, False
    else:
        company.dormant = company.last_relevant_at is None or now - company.last_relevant_at > DORMANT_AFTER
    return BoardOutcome(ok=True, new=new, closed=closed, seen=len(listing.postings),
                        stored=sum(_storable(p) for p in listing.postings), descriptions_fetched=listing.descriptions_fetched)


def apply_feed(session: Session, feed: Company, listing: Listing, now: datetime) -> BoardOutcome:
    feed.last_fetched = now
    if not listing.ok:
        feed.fail_count += 1
        return BoardOutcome(ok=False, status=listing.status)
    feed.last_ok, feed.fail_count = now, 0
    member_ats, groups = FEEDS[feed.ats], {}
    for p in listing.postings:
        groups.setdefault(p.company_ref, []).append(p)
    members = {c.slug: c for c in session.scalars(select(Company).where(Company.user_id == feed.user_id, Company.ats == member_ats))}
    out = BoardOutcome(ok=True)
    for ref, postings in groups.items():
        company = members.get(ref)
        if company is None:
            company = Company(user_id=feed.user_id, ats=member_ats, slug=ref[:255], name=(postings[0].company_name or ref)[:255], status="watch",
                              board_url=(postings[0].company_url or board_url(member_ats, ref))[:MAX_URL], first_seen=now)
            session.add(company)
            session.flush()
            members[ref] = company
        if company.status == "avoid":
            continue
        one = apply_board(session, company, Listing(postings=postings), now)
        out.new, out.closed, out.seen, out.stored = out.new + one.new, out.closed + one.closed, out.seen + one.seen, out.stored + one.stored
    for company in members.values():
        if company.slug not in groups and company.last_ok is not None:
            out.closed += apply_board(session, company, Listing(), now).closed
    return out


async def fetch_board(session: Session, company: Company, source: JobSource, now: datetime) -> BoardOutcome:
    return apply_board(session, company, await collect(company, source), now)


def _selectable(session: Session, settings: Settings, only: list[str] | None, include_dead: bool, now: datetime):
    rows = session.scalars(select(Company).where(Company.user_id == settings.user_id, Company.status != "avoid",
                                                 Company.ats.in_(SUPPORTED))).all()
    if only:
        wanted = {tuple(o.split(":", 1)) for o in only}
        rows = [c for c in rows if (c.ats, c.slug) in wanted]
    live = include_dead or now.weekday() == 6
    def daily(c):
        if c.dormant or c.fail_count >= DEAD_AFTER:
            return False
        return c.last_ok is not None or c.fail_count < UNPROVEN_ATTEMPTS

    chosen = [c for c in rows if live or c.status == "target" or daily(c)]
    return chosen, len(rows) - len(chosen)


def _existing_jobs(session: Session, companies: list[Company]) -> dict[int, dict[str, Job]]:
    by_company: dict[int, dict[str, Job]] = {c.id: {} for c in companies}
    ids = list(by_company)
    for start in range(0, len(ids), 500):
        for j in session.scalars(select(Job).where(Job.company_id.in_(ids[start:start + 500]))):
            by_company[j.company_id][j.external_id] = j
    return by_company


async def fetch_all(sf, settings: Settings, source: JobSource, *, only: list[str] | None = None, limit: int | None = None,
                    include_dead: bool = False, now: datetime | None = None) -> Coverage:
    now = now or datetime.now(UTC)
    cov = Coverage()
    with sf() as session:
        companies, cov.boards_skipped = _selectable(session, settings, only, include_dead, now)
        companies = companies[:limit] if limit else companies
        session.commit()
        cov.boards_total = len(companies)
        cov.lever_boards = sum(c.ats == "lever" for c in companies)
        existing = _existing_jobs(session, companies)
        fresh_after = now - DESCRIPTION_TTL
        known = {cid: {eid for eid, j in jobs.items() if j.description and j.description_at and j.description_at > fresh_after}
                 for cid, jobs in existing.items()}
        sem = asyncio.Semaphore(settings.fetch_concurrency)

        async def one(c):
            async with sem:
                return await collect(c, source, known.get(c.id, set()), now=now, max_posted_age_days=settings.max_posted_age_days)

        listings = await asyncio.gather(*(one(c) for c in companies))
        for company, listing in zip(companies, listings, strict=True):
            try:
                with session.begin_nested():
                    out = (apply_feed if company.ats in FEEDS else lambda s_, c_, l_, n_: apply_board(s_, c_, l_, n_, existing.get(c_.id)))(session, company, listing, now)
            except Exception as e:
                cov.boards_failed += 1
                cov.errors.append(f"{company.ats}:{company.slug}: {type(e).__name__}: {str(e)[:120]}")
                continue
            if out.ok:
                cov.boards_ok += 1
                cov.jobs_seen += out.seen
                cov.jobs_stored += out.stored
                cov.jobs_new += out.new
                cov.jobs_closed += out.closed
                cov.descriptions_fetched += out.descriptions_fetched
            else:
                cov.boards_failed += 1
                if out.status == 404 and company.status == "target":
                    cov.stale_targets.append(company.name)
        session.add(Run(stage="fetch", started_at=now, finished_at=datetime.now(UTC), stats=cov.model_dump()))
        session.commit()
    return cov
