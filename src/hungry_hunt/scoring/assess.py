"""Assessment stage: rules for every job, Gemini scoring for the survivors, keyed for re-evaluation."""

import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hungry_hunt.config import Settings
from hungry_hunt.core.ports import Assessor
from hungry_hunt.db.models import Assessment, Company, Job, Profile, Run
from hungry_hunt.scoring import rules
from hungry_hunt.scoring.gemini import QuotaExhausted, validate

COMMIT_EVERY = 10
SCORING_VERSION = 2


class NoProfile(Exception):
    pass


@dataclass
class ScoreStats:
    rules_evaluated: int = 0
    calls: int = 0
    scored: int = 0
    invalid: int = 0
    errors: int = 0
    quota_hit: bool = False


def _summary(profile: Profile) -> str:
    roles = f"; preferred roles: {', '.join(profile.target_titles)}" if profile.target_titles else ""
    return (
        f"{profile.years_experience} years of professional experience; skills: {', '.join(profile.skills)}; "
        f"looking for roles whose experience bar is at most {profile.max_years_bar} years{roles}"
    )


def _key(job: Job, profile: Profile) -> str:
    return f"{job.content_hash}|r{rules.RULES_VERSION}|s{SCORING_VERSION}|b{profile.max_years_bar}"


def _ceil(v: float | None) -> int | None:
    return None if v is None else math.ceil(v)


def run_rules(session: Session, settings: Settings, profile: Profile, now: datetime) -> int:
    rows = session.execute(
        select(Job, Company, Assessment)
        .join(Company, Job.company_id == Company.id)
        .outerjoin(Assessment, (Assessment.job_id == Job.id) & (Assessment.resume_version == profile.resume_version))
        .where(Job.closed_at.is_(None), Company.user_id == settings.user_id)
    ).all()
    n = 0
    for job, company, a in rows:
        if a is not None and a.content_hash == _key(job, profile):
            continue
        r = rules.evaluate(
            job.title,
            job.is_india,
            job.is_remote,
            job.location_raw,
            job.description,
            company.status,
            company.kind,
            profile.max_years_bar,
            profile.excluded_titles or [],
            posted_at=job.posted_at,
            first_seen=job.first_seen,
            now=now,
            max_posted_age_days=settings.max_posted_age_days,
        )
        keep_score = (
            a is not None
            and a.verdict is not None
            and r.passed
            and a.content_hash.split("|")[0] == job.content_hash
            and f"|s{SCORING_VERSION}" in a.content_hash
            and (a.min_years is None or a.min_years <= profile.max_years_bar)
        )
        if a is None:
            a = Assessment(job_id=job.id, resume_version=profile.resume_version)
            session.add(a)
        a.content_hash, a.passed_rules, a.rule_fails = _key(job, profile), r.passed, r.fails
        a.min_years, a.max_years, a.years_evidence = _ceil(r.years.min), _ceil(r.years.max), r.years.evidence
        a.is_engineering, a.is_senior = r.is_engineering, r.is_senior
        if not keep_score:
            a.fit_score = a.verdict = a.reason = a.scored_at = None
            a.matched_skills, a.missing_skills = [], []
        n += 1
    session.flush()
    return n


def score(
    session: Session,
    settings: Settings,
    profile: Profile,
    llm: Assessor,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> ScoreStats:
    stats = ScoreStats()
    rows = session.execute(
        select(Assessment, Job, Company)
        .join(Job, Assessment.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(
            Assessment.resume_version == profile.resume_version,
            Assessment.passed_rules.is_(True),
            Assessment.verdict.is_(None),
            Job.closed_at.is_(None),
            Job.description.isnot(None),
        )
        .order_by(Job.first_seen.desc())
        .limit(settings.assess_max_calls)
    ).all()
    summary = _summary(profile)
    last_call = None
    for a, job, company in rows:
        retried = False
        while True:
            if last_call is not None:
                sleep(max(0.0, settings.assess_interval_s - (time.monotonic() - last_call)))
            last_call = time.monotonic()
            stats.calls += 1
            try:
                out = llm.assess(
                    profile.resume_text,
                    summary,
                    company.name,
                    company.tier,
                    job.title,
                    job.location_raw,
                    job.description or "",
                )
            except QuotaExhausted:
                if retried:
                    stats.quota_hit = True
                    session.commit()
                    return stats
                retried = True
                sleep(60)
                continue
            except (ValidationError, ValueError):
                stats.invalid += 1
                break
            except Exception:
                stats.errors += 1
                break
            out = validate(
                out, job.description or "", profile.resume_text, profile.max_years_bar, rules_min=a.min_years
            )
            a.fit_score, a.verdict, a.reason, a.scored_at = out.fit_score, out.verdict, out.reason, now
            a.breakdown = out.breakdown.model_dump() if out.breakdown else None
            a.matched_skills, a.missing_skills = out.matched_skills, out.missing_skills
            if a.min_years is None and out.years_evidence is not None:
                a.min_years, a.max_years, a.years_evidence = out.min_years, out.max_years, out.years_evidence
                if out.min_years is not None and out.min_years > profile.max_years_bar:
                    a.verdict, a.rule_fails = "skip", [*a.rule_fails, "years>bar(llm)"]
            stats.scored += 1
            if stats.scored % COMMIT_EVERY == 0:
                session.commit()
            break
    session.commit()
    return stats


def run(
    sf, settings: Settings, llm: Assessor, now: datetime | None = None, sleep: Callable[[float], None] = time.sleep
) -> ScoreStats:
    now = now or datetime.now(UTC)
    with sf() as session:
        profile = session.get(Profile, settings.user_id)
        if profile is None:
            raise NoProfile(f"no profile for {settings.user_id}; run `hunt profile` locally first")
        evaluated = run_rules(session, settings, profile, now)
        session.commit()
        stats = score(session, settings, profile, llm, now, sleep)
        stats.rules_evaluated = evaluated
        session.add(Run(stage="assess", started_at=now, finished_at=datetime.now(UTC), stats=asdict(stats)))
        session.commit()
    return stats
