from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hunt.db import Base, TZDateTime


class Company(Base):
    __tablename__ = "company"
    __table_args__ = (UniqueConstraint("user_id", "ats", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    ats: Mapped[str] = mapped_column(String(32))
    slug: Mapped[str] = mapped_column(String(255))
    board_url: Mapped[str | None] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16), default="unknown")
    tier: Mapped[str] = mapped_column(String(16), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="watch")
    notes: Mapped[str] = mapped_column(Text, default="")
    yc_batch: Mapped[str | None] = mapped_column(String(32))
    team_size: Mapped[int | None] = mapped_column(Integer)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    dormant: Mapped[bool] = mapped_column(Boolean, default=False)
    funded_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    funding_note: Mapped[str | None] = mapped_column(Text)
    last_relevant_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    first_seen: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_fetched: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_ok: Mapped[datetime | None] = mapped_column(TZDateTime)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (UniqueConstraint("company_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    location_raw: Mapped[str] = mapped_column(String(512), default="")
    is_india: Mapped[bool] = mapped_column(Boolean, default=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1024))
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    first_seen: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(TZDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    description_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    content_hash: Mapped[str] = mapped_column(String(40), default="")


class Assessment(Base):
    __tablename__ = "assessment"
    __table_args__ = (UniqueConstraint("job_id", "resume_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    resume_version: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    passed_rules: Mapped[bool] = mapped_column(Boolean)
    rule_fails: Mapped[list] = mapped_column(JSON, default=list)
    min_years: Mapped[int | None] = mapped_column(Integer)
    max_years: Mapped[int | None] = mapped_column(Integer)
    years_evidence: Mapped[str | None] = mapped_column(Text)
    is_engineering: Mapped[bool] = mapped_column(Boolean, default=False)
    is_senior: Mapped[bool] = mapped_column(Boolean, default=False)
    fit_score: Mapped[int | None] = mapped_column(Integer)
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    verdict: Mapped[str | None] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(Text)
    breakdown: Mapped[dict | None] = mapped_column(JSON)
    scored_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Delivery(Base):
    __tablename__ = "delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="email")
    digest_id: Mapped[str] = mapped_column(String(64), index=True)
    sent_at: Mapped[datetime] = mapped_column(TZDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    error: Mapped[str | None] = mapped_column(Text)


class Application(Base):
    __tablename__ = "application"
    __table_args__ = (UniqueConstraint("job_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    applied_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    channel: Mapped[str | None] = mapped_column(String(32))
    resume_version: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)


class Profile(Base):
    __tablename__ = "profile"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resume_version: Mapped[str] = mapped_column(String(16))
    resume_text: Mapped[str] = mapped_column(Text)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    target_titles: Mapped[list] = mapped_column(JSON, default=list)
    excluded_titles: Mapped[list] = mapped_column(JSON, default=list)
    cities: Mapped[list] = mapped_column(JSON, default=list)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    max_years_bar: Mapped[int] = mapped_column(Integer, default=2)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)


class Run(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class TrackedMail(Base):
    __tablename__ = "tracked_mail"
    __table_args__ = (UniqueConstraint("user_id", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(255))
    sender: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(512))
    received_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    status: Mapped[str] = mapped_column(String(16))
    company_hint: Mapped[str | None] = mapped_column(String(255))
    title_hint: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))


class FundingSignal(Base):
    __tablename__ = "funding_signal"
    __table_args__ = (UniqueConstraint("user_id", "link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    link: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(32))
    published: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    seen_at: Mapped[datetime] = mapped_column(TZDateTime)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"))


class Outreach(Base):
    __tablename__ = "outreach"
    __table_args__ = (UniqueConstraint("job_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    resume_version: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
