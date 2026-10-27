"""Grounded outreach drafts for one job, validated against the profile and posting."""

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hungry_hunt.config import Settings
from hungry_hunt.core.schemas import OutreachOut, OutreachResult
from hungry_hunt.db.models import Company, Job, Outreach, Profile

YEARS = re.compile(r"\b(\d{1,2})\+?\s*years?\b", re.IGNORECASE)
PROPER = re.compile(r"\b[A-Z][A-Za-z+#.]{2,}\b")
COMMON = {
    "Hi",
    "Hello",
    "Dear",
    "Thanks",
    "Thank",
    "Would",
    "Could",
    "The",
    "This",
    "That",
    "Your",
    "Our",
    "My",
    "For",
    "With",
    "And",
    "But",
    "Also",
    "Please",
    "Best",
    "Regards",
    "Sai",
    "Poojitha",
    "Team",
    "Role",
    "Engineer",
    "Software",
    "Backend",
    "Application",
    "Associate",
    "Senior",
    "Junior",
    "India",
    "Bangalore",
    "Bengaluru",
    "Hyderabad",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "LinkedIn",
    "GitHub",
}


def validate(out: OutreachOut, resume_text: str, company: str, title: str = "") -> OutreachResult:
    text = f"{out.note} {out.referral_ask}"
    resume = resume_text.lower()
    allowed = {w.lower() for w in re.findall(r"[A-Za-z+#.]+", f"{company} {title}")} | {w.lower() for w in COMMON}
    flags = []
    for m in YEARS.finditer(text):
        if m.group(0).lower() not in resume:
            flags.append(f"claim not in resume: '{m.group(0)}'")
    sentence_starts = {m.group(1) for m in re.finditer(r"(?:^|[.!?]\s+|\n\s*)([A-Z][A-Za-z+#.]{2,})", text)}
    for word in dict.fromkeys(PROPER.findall(text)):
        w = word.lower().strip(".")
        if word in sentence_starts and w not in resume and text.count(word) == 1:
            continue
        if w not in resume and w not in allowed and not any(w in a or a in w for a in allowed if len(a) > 3):
            flags.append(f"name not in resume or posting: '{word}'")
    return OutreachResult(**out.model_dump(), flags=flags)


def draft(
    session: Session, settings: Settings, llm, job_id: int, now: datetime, regenerate: bool = False
) -> OutreachResult:
    row = session.execute(
        select(Job, Company)
        .join(Company, Job.company_id == Company.id)
        .where(Job.id == job_id, Company.user_id == settings.user_id)
    ).first()
    if row is None:
        raise LookupError("job not found")
    job, company = row
    profile = session.get(Profile, settings.user_id)
    if profile is None:
        raise LookupError("no profile")
    existing = session.scalar(select(Outreach).where(Outreach.job_id == job_id, Outreach.user_id == settings.user_id))
    if existing and existing.resume_version == profile.resume_version and not regenerate:
        return validate(
            OutreachOut(**json.loads(existing.payload)), profile.resume_text, company.name, job.title
        ).model_copy(update={"created_at": existing.created_at})
    out = llm.draft_outreach(profile.resume_text, company.name, job.title, job.description or "", job.url)
    if existing is None:
        existing = Outreach(job_id=job_id, user_id=settings.user_id)
        session.add(existing)
    existing.resume_version, existing.payload, existing.created_at = (
        profile.resume_version,
        json.dumps(out.model_dump()),
        now,
    )
    session.commit()
    return validate(out, profile.resume_text, company.name, job.title).model_copy(update={"created_at": now})


def load(session: Session, settings: Settings, job_id: int) -> OutreachResult | None:
    row = session.execute(
        select(Outreach, Company, Profile, Job)
        .join(Job, Outreach.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .join(Profile, Profile.user_id == Outreach.user_id)
        .where(Outreach.job_id == job_id, Outreach.user_id == settings.user_id, Company.user_id == settings.user_id)
    ).first()
    if row is None:
        return None
    existing, company, profile, job = row
    return validate(
        OutreachOut(**json.loads(existing.payload)), profile.resume_text, company.name, job.title
    ).model_copy(update={"created_at": existing.created_at})
