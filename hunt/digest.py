from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hunt import funding, track
from hunt.config import Settings
from hunt.fetch import SUPPORTED
from hunt.models import Application, Assessment, Company, Delivery, Job, Profile, Run
from hunt.rules import INDIA, JUNIOR
from hunt.schemas import Coverage, Digest, DigestJob

IST = timezone(timedelta(hours=5, minutes=30))
SECTIONS = ("India", "Remote", "Stretch")
STRETCH_CAP = 20
FAST_HIRING = 3
STALE_AFTER = timedelta(days=3)
ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html", "j2"]))


def select_undelivered(session: Session, user_id: str, resume_version: str,
                       keep_delivered_since: datetime | None = None) -> list[tuple[Job, Company, Assessment]]:
    confirmed = select(Delivery.job_id).where(Delivery.user_id == user_id, Delivery.confirmed_at.isnot(None))
    if keep_delivered_since is not None:
        confirmed = confirmed.where(Delivery.confirmed_at < keep_delivered_since)
    acted = select(Application.job_id).where(Application.user_id == user_id)
    return session.execute(
        select(Job, Company, Assessment)
        .join(Company, Job.company_id == Company.id)
        .join(Assessment, (Assessment.job_id == Job.id) & (Assessment.resume_version == resume_version))
        .where(Job.closed_at.is_(None), Company.user_id == user_id, Company.status != "avoid", Assessment.passed_rules.is_(True),
               or_(Assessment.verdict.in_(["apply", "review"]), Assessment.verdict.is_(None)),
               Job.id.not_in(confirmed), Job.id.not_in(acted))).all()


def velocity(session: Session, user_id: str, now: datetime, days: int = 14) -> dict[int, int]:
    rows = session.execute(select(Job.company_id, func.count()).join(Company, Job.company_id == Company.id)
                           .where(Company.user_id == user_id, Job.closed_at.is_(None), Job.description.isnot(None),
                                  Job.first_seen >= now - timedelta(days=days)).group_by(Job.company_id))
    return {cid: n for cid, n in rows}


def _section(job: Job) -> str:
    if job.is_india or not job.is_remote:
        return "India"
    return "Remote" if INDIA.search(job.description or "") else "Stretch"


def _digest_job(job: Job, company: Company, a: Assessment, settings: Settings, now: datetime) -> DigestJob:
    return DigestJob(job_id=job.id, company=company.name, tier=company.tier, title=job.title, location_raw=job.location_raw,
                     posted_age_days=(now - job.posted_at).days if job.posted_at else None, score=a.fit_score, verdict=a.verdict,
                     reason=a.reason, years_evidence=a.years_evidence, url=job.url, breakdown=a.breakdown,
                     review_url=f"{settings.review_base_url.rstrip('/')}/job/{job.id}?t={settings.review_token}",
                     is_new=job.first_seen >= now - timedelta(hours=24))


def _coverage(session: Session, settings: Settings, now: datetime, unscored: int) -> Coverage:
    day_start = datetime.combine(now.astimezone(IST).date(), datetime.min.time(), tzinfo=IST).astimezone(UTC)
    runs = session.scalars(select(Run).where(Run.started_at >= day_start).order_by(Run.started_at)).all()
    fetch = next((r.stats for r in reversed(runs) if r.stage == "fetch"), None)
    assess = next((r.stats for r in reversed(runs) if r.stage == "assess"), {})
    cov = Coverage.model_validate({k: v for k, v in (fetch or {}).items() if k in Coverage.model_fields})
    cov.stats_available = fetch is not None
    cov.gemini_calls, cov.quota_hit, cov.unscored = assess.get("calls", 0), bool(assess.get("quota_hit")), unscored
    companies = session.scalars(select(Company).where(Company.user_id == settings.user_id)).all()
    watched = [c for c in companies if c.status in ("target", "watch")]
    cov.blind_spots = sorted(f"{c.name} ({c.notes or 'hiring system unknown'})" for c in watched if c.ats in ("unsupported", "unknown"))
    cov.stale_targets = sorted(c.name for c in watched if c.ats in SUPPORTED and c.kind != "service"
                               and (c.last_ok is None or c.last_ok < now - STALE_AFTER))
    cov.service_auto = sum(c.kind == "service" for c in companies)
    cov.funded_unwatched = funding.unwatched(session, settings.user_id, now)
    profile = session.get(Profile, settings.user_id)
    if profile:
        stale = session.execute(select(Assessment.rule_fails).join(Job, Assessment.job_id == Job.id)
                                .where(Assessment.resume_version == profile.resume_version, Job.closed_at.is_(None),
                                       Assessment.passed_rules.is_(False))).scalars()
        cov.stale_hidden = sum("stale_posting" in (fails or []) for fails in stale)
    return cov


UNSCORED_CAP = 40


def build(session: Session, settings: Settings, now: datetime, days: int | None = None, cap: int | None = -1) -> Digest:
    profile = session.get(Profile, settings.user_id)
    since = now - timedelta(days=days) if days else None
    rows = select_undelivered(session, settings.user_id, profile.resume_version, since) if profile else []
    fast = velocity(session, settings.user_id, now)
    jobs = []
    for j, c, a in rows:
        d = _digest_job(j, c, a, settings, now)
        d.company_velocity, d.recently_funded = fast.get(c.id, 0), funding.recently_funded(c, now)
        jobs.append((d, _section(j)))
    wanted = [t.lower() for t in (profile.target_titles if profile else None) or []]
    preferred = lambda title: bool(JUNIOR.search(title)) or any(t in title.lower() for t in wanted)
    scored = sorted((x for x in jobs if x[0].verdict is not None),
                    key=lambda x: (0 if preferred(x[0].title) else 1, 0 if x[0].company_velocity >= FAST_HIRING or x[0].recently_funded else 1, -x[0].score,
                                   x[0].posted_age_days if x[0].posted_age_days is not None else 10**6))
    unscored = sorted((x[0] for x in jobs if x[0].verdict is None), key=lambda d: d.posted_age_days if d.posted_age_days is not None else 10**6)
    new = {s: [] for s in SECTIONS}
    carried = {s: [] for s in SECTIONS}
    budget = (settings.digest_max_jobs if cap == -1 else cap) if cap is not None else 10**9
    truncated = 0
    for group in (True, False):
        for d, section in scored:
            if d.is_new != group:
                continue
            target = new if group else carried
            if budget <= 0 or (section == "Stretch" and len(target["Stretch"]) >= STRETCH_CAP):
                truncated += 1
                continue
            target[section].append(d)
            budget -= 1
    shown_unscored = unscored[: (UNSCORED_CAP if cap is not None else len(unscored))]
    truncated += len(unscored) - len(shown_unscored)
    date_ist = now.astimezone(IST).date()
    return Digest(digest_id=f"{settings.user_id}:{now.astimezone(IST):%Y-%m-%dT%H}", date_ist=date_ist, new=new, carried=carried, unscored=shown_unscored,
                  coverage=_coverage(session, settings, now, len(unscored)), truncated=truncated,
                  pipeline=track.pipeline_counts(session, settings.user_id, now))


def render(digest: Digest, settings: Settings) -> tuple[str, str]:
    n_new = sum(len(v) for v in digest.new.values())
    n_carried = sum(len(v) for v in digest.carried.values())
    subject = f"Hungry Hunt · {n_new} new, {n_carried} carried, {len(digest.unscored)} unscored · {digest.date_ist}"
    html = ENV.get_template("digest.html.j2").render(d=digest, n_new=n_new, n_carried=n_carried, sections=SECTIONS,
                                                     review_base=settings.review_base_url.rstrip("/"), token=settings.review_token)
    return subject, html
