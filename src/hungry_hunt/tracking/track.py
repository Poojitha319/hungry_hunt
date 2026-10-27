"""Reads forwarded hiring mail over IMAP, classifies events and links them to jobs."""

import email
import imaplib
import logging
import quopri
import re
import ssl
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hungry_hunt.config import Settings
from hungry_hunt.db.models import Application, Company, Job, Run, TrackedMail

log = logging.getLogger(__name__)

REJECTED = re.compile(
    r"unfortunately|not (?:be )?moving forward|other candidates|regret to|not selected|"
    r"decided (?:not )?to (?:pursue|proceed)|no longer under consideration",
    re.IGNORECASE,
)
TEST_SENDER = re.compile(r"hackerrank|doselect|codility|hackerearth|codesignal|testgorilla|mettl|imocha", re.IGNORECASE)
TEST = re.compile(
    r"assessment|coding (?:challenge|test|round)|online test|hiring challenge|take-?home|test invite|invited to take",
    re.IGNORECASE,
)
INTERVIEW = re.compile(
    r"interview|phone screen|schedule (?:a )?(?:call|conversation|time)|pick a slot|calendly|technical round|"
    r"invitation:",
    re.IGNORECASE,
)
APPLIED = re.compile(
    r"thank(?:s| you) for applying|application (?:received|has been received|submitted)|received your application|"
    r"your application to",
    re.IGNORECASE,
)
GENERIC_SENDER = re.compile(
    r"hackerrank|doselect|codility|hackerearth|calendly|greenhouse|lever|ashby|workday|no-?reply|careers|jobs|"
    r"recruiting|talent|notifications?",
    re.IGNORECASE,
)
COMPANY_PATTERNS = [
    re.compile(r"applying to (?:the .+? (?:position|role) at )?(.+?)(?: for\b| -|!|\.|$)", re.IGNORECASE),
    re.compile(r"application (?:to|at|with) (.+?)(?: for\b| -|!|\.|$)", re.IGNORECASE),
    re.compile(r"application received:\s*(.+?)(?: -|!|\.|$)", re.IGNORECASE),
    re.compile(r"^(.+?)\s*[-–:]\s*application received", re.IGNORECASE),
    re.compile(r"^(.+?)\s+hiring challenge", re.IGNORECASE),
    re.compile(r"(?:assessment|challenge|test|interview|screen)\b.*?\b(?:with|at)\s+(.+?)(?: -|!|\.|$)", re.IGNORECASE),
]
TITLE_PATTERNS = [
    re.compile(r"for the (.+?) (?:position|role)", re.IGNORECASE),
    re.compile(r"\bthe (.+?) position\b", re.IGNORECASE),
    re.compile(r"\b(?:position|role):\s*(.+?)(?:\.|$)", re.IGNORECASE),
]
ORDER = {"applied": 1, "test": 2, "callback": 2, "interview": 3, "rejected": 4}
STATUSES = ("applied", "test", "interview", "rejected")


@dataclass
class Mail:
    message_id: str
    sender: str
    subject: str
    date: datetime
    snippet: str
    forwarded_for: str | None
    auth_results: str | None = None


@dataclass
class Event:
    status: str | None
    company_hint: str | None
    title_hint: str | None


@dataclass
class TrackStats:
    seen: int = 0
    classified: int = 0
    linked_jobs: int = 0
    unmatched: int = 0


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _company_hint(m: Mail) -> str | None:
    for pattern in COMPANY_PATTERNS:
        if (hit := pattern.search(m.subject)) and hit.group(1).strip():
            return hit.group(1).strip()
    name, addr = parseaddr(m.sender)
    if name and not GENERIC_SENDER.search(name):
        return name.strip()
    domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
    if domain and not GENERIC_SENDER.search(domain) and not TEST_SENDER.search(domain):
        return domain.split(".")[0].title()
    return None


FWD_PREFIX = re.compile(r"^\s*(?:fwd?|fw)\s*:\s*", re.IGNORECASE)


TRUSTED_DOMAINS = (
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "ashbyhq.com",
    "hackerrank.com",
    "doselect.com",
    "codility.com",
    "hackerearth.com",
    "codesignal.com",
    "calendly.com",
    "myworkdayjobs.com",
    "workday.com",
    "smartrecruiters.com",
    "testgorilla.com",
    "mettl.com",
    "imocha.io",
)
DKIM_PASS_DOMAIN = re.compile(r"dkim=pass[^;]*?header\.(?:i=@|d=)([a-z0-9.-]+)", re.IGNORECASE)
DMARC_PASS = re.compile(r"\bdmarc=pass\b", re.IGNORECASE)
ARC_PASS = re.compile(r"\barc=pass\b", re.IGNORECASE)


AUTHSERV = re.compile(r"^mx\.google\.com\s*(?:;|$)", re.IGNORECASE)


def _gmail_results(auth: str | None) -> str | None:
    top = (auth or "").strip()
    return top if AUTHSERV.match(top) else None


def _aligned(top: str, domain: str) -> bool:
    if DMARC_PASS.search(top):
        return True
    return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in DKIM_PASS_DOMAIN.findall(top))


def _is_trusted(m: Mail, settings: Settings) -> bool:
    top = _gmail_results(m.auth_results)
    if top is None:
        return False
    addresses = [a for _, a in getaddresses([m.sender]) if a]
    if len(addresses) != 1:
        return False
    addr = addresses[0].lower()
    domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
    aligned = bool(domain) and _aligned(top, domain)
    if settings.digest_to and addr == settings.digest_to.lower():
        return aligned and domain == "gmail.com"
    if not m.forwarded_for or not aligned:
        return False
    if any(domain == d or domain.endswith("." + d) for d in TRUSTED_DOMAINS):
        return True
    return bool(ARC_PASS.search(top))


def classify(m: Mail) -> Event:
    m = Mail(**{**m.__dict__, "subject": FWD_PREFIX.sub("", m.subject)})
    text = f"{m.subject}\n{m.snippet}"
    if REJECTED.search(text):
        status = "rejected"
    elif TEST_SENDER.search(m.sender) or TEST.search(text):
        status = "test"
    elif INTERVIEW.search(text):
        status = "interview"
    elif APPLIED.search(text):
        status = "applied"
    else:
        return Event(None, None, None)
    title = next((h.group(1).strip() for p in TITLE_PATTERNS if (h := p.search(text))), None)
    return Event(status, _company_hint(m), title)


def _match_company(companies: Sequence[Company], hint: str | None) -> Company | None:
    if not hint:
        return None
    h = _norm(hint)
    if len(h) < 3:
        return None
    exact = [c for c in companies if _norm(c.name) == h]
    if exact:
        return exact[0]
    loose = [c for c in companies if len(_norm(c.name)) >= 4 and (_norm(c.name) in h or h in _norm(c.name))]
    return loose[0] if len(loose) == 1 else None


def _match_job(session: Session, company: Company, user_id: str, text: str, title_hint: str | None) -> Job | None:
    jobs = session.scalars(select(Job).where(Job.company_id == company.id).order_by(Job.first_seen.desc())).all()
    haystack = _norm(text)
    for j in jobs:
        if len(_norm(j.title)) >= 4 and _norm(j.title) in haystack:
            return j
    if title_hint:
        want = set(re.findall(r"[a-z0-9]+", title_hint.lower()))
        scored = [(len(want & set(re.findall(r"[a-z0-9]+", j.title.lower()))) / max(len(want), 1), j) for j in jobs]
        best = max(scored, key=lambda x: x[0], default=(0, None))
        if best[0] >= 0.6:
            return best[1]
    latest = session.scalar(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .where(Job.company_id == company.id, Application.user_id == user_id)
        .order_by(Application.updated_at.desc())
    )
    return session.get(Job, latest.job_id) if latest else None


def apply_events(session: Session, settings: Settings, mails: list[Mail], now: datetime) -> TrackStats:
    stats = TrackStats()
    seen_ids = set(session.scalars(select(TrackedMail.message_id).where(TrackedMail.user_id == settings.user_id)))
    companies = session.scalars(select(Company).where(Company.user_id == settings.user_id)).all()
    for m in sorted(mails, key=lambda x: x.date):
        if m.message_id in seen_ids:
            continue
        stats.seen += 1
        if settings.track_require_forwarded and not _is_trusted(m, settings):
            continue
        event = classify(m)
        if event.status is None:
            continue
        stats.classified += 1
        company = _match_company(companies, event.company_hint)
        job = (
            _match_job(session, company, settings.user_id, f"{m.subject} {m.snippet}", event.title_hint)
            if company
            else None
        )
        if job is None:
            stats.unmatched += 1
        else:
            stats.linked_jobs += 1
            app = session.scalar(
                select(Application).where(Application.job_id == job.id, Application.user_id == settings.user_id)
            )
            if app is None:
                app = Application(
                    job_id=job.id,
                    user_id=settings.user_id,
                    status=event.status,
                    applied_at=m.date,
                    channel="email",
                    updated_at=m.date,
                )
                session.add(app)
            elif ORDER[event.status] >= ORDER.get(app.status, 0):
                app.status, app.updated_at = event.status, m.date
                app.applied_at = app.applied_at or m.date
        session.add(
            TrackedMail(
                user_id=settings.user_id,
                message_id=m.message_id,
                sender=m.sender[:255],
                subject=m.subject[:512],
                received_at=m.date,
                status=event.status,
                company_hint=(event.company_hint or "")[:255] or None,
                title_hint=(event.title_hint or "")[:255] or None,
                company_id=company.id if company else None,
                job_id=job.id if job else None,
            )
        )
        seen_ids.add(m.message_id)
    session.flush()
    return stats


def pipeline_counts(session: Session, user_id: str, now: datetime) -> dict:
    rows = session.scalars(select(TrackedMail).where(TrackedMail.user_id == user_id)).all()
    week = now - timedelta(days=7)
    return {
        "week": {s: sum(r.status == s and r.received_at >= week for r in rows) for s in STATUSES},
        "total": {s: sum(r.status == s for r in rows) for s in STATUSES},
    }


def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


class ImapMailbox:
    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_recent(self, since: datetime) -> list[Mail]:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context())
        try:
            imap.login(self.settings.smtp_user, self.settings.smtp_password)
            imap.select("INBOX", readonly=True)
            _, data = imap.search(None, f"(SINCE {since:%d-%b-%Y})")
            ids = data[0].split() if data and data[0] else []
            if not ids:
                return []
            _, parts = imap.fetch(
                b",".join(ids).decode(),
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID X-FORWARDED-FOR AUTHENTICATION-RESULTS)] BODY.PEEK[TEXT]<0.2000>)",
            )
        finally:
            try:
                imap.logout()
            except Exception:
                log.debug("imap logout failed", exc_info=True)
        headers: dict[bytes, bytes] = {}
        texts: dict[bytes, bytes] = {}
        for item in parts:
            if not isinstance(item, tuple):
                continue
            meta, payload = item[0], item[1]
            seq = meta.split()[0]
            (headers if b"HEADER" in meta else texts)[seq] = payload
        mails = []
        for seq, raw in headers.items():
            msg = email.message_from_bytes(raw)
            try:
                date = parsedate_to_datetime(msg.get("Date", ""))
            except (TypeError, ValueError):
                date = datetime.now(UTC)
            body = texts.get(seq, b"")
            try:
                body = quopri.decodestring(body)
            except Exception:
                log.debug("quoted-printable decode failed for %s", seq, exc_info=True)
            snippet = re.sub(r"\s+", " ", body.decode("utf-8", "ignore"))[:600].strip()
            mails.append(
                Mail(
                    message_id=(msg.get("Message-ID") or f"<seq-{seq.decode()}-{date.timestamp()}>").strip(),
                    sender=_decode(msg.get("From")),
                    subject=_decode(msg.get("Subject")),
                    date=date if date.tzinfo else date.replace(tzinfo=UTC),
                    snippet=snippet,
                    forwarded_for=msg.get("X-Forwarded-For"),
                    auth_results=next(iter(msg.get_all("Authentication-Results") or []), None),
                )
            )
        return mails


def run(sf, settings: Settings, mailbox, now: datetime | None = None) -> TrackStats:
    now = now or datetime.now(UTC)
    mails = mailbox.fetch_recent(now - timedelta(days=settings.track_days))
    with sf() as session:
        stats = apply_events(session, settings, mails, now)
        session.add(Run(stage="track", started_at=now, finished_at=datetime.now(UTC), stats=asdict(stats)))
        session.commit()
    return stats
