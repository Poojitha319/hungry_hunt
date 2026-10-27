"""Request and response bodies of the review API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["applied", "callback", "test", "interview", "rejected", "skipped"]


class StatusIn(BaseModel):
    status: Status
    notes: str | None = None


class ApplicationOut(BaseModel):
    job_id: int
    status: str
    applied_at: datetime | None
    notes: str
    updated_at: datetime


class JobOut(BaseModel):
    id: int
    title: str
    location_raw: str
    url: str
    posted_at: datetime | None
    first_seen: datetime
    closed_at: datetime | None
    description: str | None


class CompanyOut(BaseModel):
    id: int
    name: str
    ats: str
    slug: str
    board_url: str | None
    kind: str
    tier: str
    status: str
    notes: str
    last_ok: datetime | None
    fail_count: int


class CompanyIn(BaseModel):
    status: Literal["target", "watch", "avoid"] | None = None
    notes: str | None = None


class CompanyAdd(CompanyIn):
    text: str = Field(min_length=1, max_length=1024)


class AssessmentOut(BaseModel):
    passed_rules: bool
    rule_fails: list[str]
    min_years: int | None
    max_years: int | None
    years_evidence: str | None
    fit_score: int | None
    matched_skills: list[str]
    missing_skills: list[str]
    verdict: str | None
    reason: str | None


class JobDetail(BaseModel):
    job: JobOut
    company: CompanyOut
    assessment: AssessmentOut | None
    application: ApplicationOut | None


class RunOut(BaseModel):
    id: int
    stage: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict
