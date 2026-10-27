"""Pydantic models passed between stages: postings, assessments, digest rows, outreach drafts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Posting(BaseModel):
    external_id: str
    title: str
    location_raw: str = ""
    country: str | None = None
    remote_flag: bool = False
    url: str
    posted_at: datetime | None = None
    description: str | None = None
    company_name: str | None = None
    detail_ref: str | None = None
    company_ref: str | None = None
    company_url: str | None = None


class Location(BaseModel):
    is_india: bool
    is_remote: bool
    remote_restricted: bool


class Years(BaseModel):
    min: float | None = None
    max: float | None = None
    evidence: str | None = None


class RuleResult(BaseModel):
    passed: bool
    fails: list[str]
    years: Years
    is_engineering: bool
    is_senior: bool


class Breakdown(BaseModel):
    skills_overlap: int = Field(ge=0, le=40)
    skills_reason: str = ""
    seniority_fit: int = Field(ge=0, le=25)
    seniority_reason: str = ""
    domain_fit: int = Field(ge=0, le=20)
    domain_reason: str = ""
    practical_fit: int = Field(ge=0, le=15)
    practical_reason: str = ""

    @property
    def total(self) -> int:
        return self.skills_overlap + self.seniority_fit + self.domain_fit + self.practical_fit


class AssessmentOut(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    breakdown: Breakdown | None = None
    verdict: Literal["apply", "review", "skip"]
    matched_skills: list[str] = Field(max_length=12)
    missing_skills: list[str] = Field(max_length=8)
    min_years: int | None = None
    max_years: int | None = None
    years_evidence: str | None = None
    is_engineering: bool
    is_senior: bool
    reason: str


class ProfileOut(BaseModel):
    skills: list[str]
    years_experience: float
    summary: str


class DigestJob(BaseModel):
    job_id: int
    company: str
    tier: str
    title: str
    location_raw: str
    posted_age_days: int | None
    score: int | None
    verdict: str | None
    reason: str | None
    years_evidence: str | None
    url: str
    review_url: str
    is_new: bool
    company_velocity: int = 0
    recently_funded: bool = False
    breakdown: dict | None = None


class Coverage(BaseModel):
    boards_total: int = 0
    boards_ok: int = 0
    boards_failed: int = 0
    boards_skipped: int = 0
    jobs_seen: int = 0
    jobs_stored: int = 0
    jobs_new: int = 0
    jobs_closed: int = 0
    descriptions_fetched: int = 0
    rules_passed: int = 0
    gemini_calls: int = 0
    unscored: int = 0
    quota_hit: bool = False
    blind_spots: list[str] = []
    stale_targets: list[str] = []
    lever_boards: int = 0
    service_auto: int = 0
    stale_hidden: int = 0
    funded_unwatched: list[str] = []
    stats_available: bool = True
    errors: list[str] = []


class Digest(BaseModel):
    digest_id: str
    date_ist: date
    new: dict[str, list[DigestJob]]
    carried: dict[str, list[DigestJob]]
    unscored: list[DigestJob]
    coverage: Coverage
    truncated: int = 0
    pipeline: dict[str, dict[str, int]] = {}


class OutreachOut(BaseModel):
    subject: str
    note: str
    referral_ask: str
    who_to_contact: str


class OutreachResult(OutreachOut):
    flags: list[str] = []
    created_at: datetime | None = None
