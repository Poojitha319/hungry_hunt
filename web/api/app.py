import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select

from hunt import digest, discover, outreach
from hunt.config import Settings
from hunt.db import make_engine, session_factory
from hunt.models import Application, Assessment, Company, Job, Profile, Run
from hunt.schemas import Digest, OutreachResult

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


def create_app(settings: Settings | None = None, sf=None, now: Callable[[], datetime] = lambda: datetime.now(UTC), llm=None) -> FastAPI:
    settings = settings or Settings()
    sf = sf or session_factory(make_engine(settings.database_url))
    app = FastAPI(title="Hungry Hunt API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=[settings.review_base_url.rstrip("/")], allow_methods=["*"], allow_headers=["*"])

    def session():
        with sf() as s:
            yield s

    def require_token(request: Request):
        header = request.headers.get("authorization", "")
        supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else request.query_params.get("t", "")
        if not settings.review_token or not hmac.compare_digest(supplied.encode(), settings.review_token.encode()):
            raise HTTPException(401, "invalid or missing token")

    def application_out(a: Application) -> ApplicationOut:
        return ApplicationOut(job_id=a.job_id, status=a.status, applied_at=a.applied_at, notes=a.notes, updated_at=a.updated_at)

    def owned_job(s, job_id: int) -> tuple[Job, Company]:
        row = s.execute(select(Job, Company).join(Company, Job.company_id == Company.id)
                        .where(Job.id == job_id, Company.user_id == settings.user_id)).first()
        if row is None:
            raise HTTPException(404, "job not found")
        return row

    @app.get("/health")
    def health(s=Depends(session)):
        s.execute(select(1))
        return {"ok": True}

    @app.get("/api/digest", response_model=Digest, dependencies=[Depends(require_token)])
    def get_digest(days: int | None = Query(None, ge=1, le=90), s=Depends(session)):
        return digest.build(s, settings, now(), days=days, cap=None)

    @app.get("/api/jobs/{job_id}", response_model=JobDetail, dependencies=[Depends(require_token)])
    def get_job(job_id: int, s=Depends(session)):
        job, company = owned_job(s, job_id)
        profile = s.get(Profile, settings.user_id)
        a = s.scalar(select(Assessment).where(Assessment.job_id == job_id, Assessment.resume_version == profile.resume_version)) if profile else None
        app_row = s.scalar(select(Application).where(Application.job_id == job_id, Application.user_id == settings.user_id))
        return JobDetail(job=JobOut.model_validate(job, from_attributes=True), company=CompanyOut.model_validate(company, from_attributes=True),
                         assessment=AssessmentOut.model_validate(a, from_attributes=True) if a else None,
                         application=application_out(app_row) if app_row else None)

    @app.post("/api/jobs/{job_id}/status", response_model=ApplicationOut, dependencies=[Depends(require_token)])
    def set_status(job_id: int, body: StatusIn, s=Depends(session)):
        owned_job(s, job_id)
        t = now()
        row = s.scalar(select(Application).where(Application.job_id == job_id, Application.user_id == settings.user_id))
        if row is None:
            row = Application(job_id=job_id, user_id=settings.user_id, status=body.status, updated_at=t)
            s.add(row)
        row.status, row.updated_at = body.status, t
        if body.notes is not None:
            row.notes = body.notes
        if body.status == "applied" and row.applied_at is None:
            row.applied_at = t
        s.commit()
        return application_out(row)

    def get_llm():
        if llm is not None:
            return llm
        from hunt.gemini import Gemini
        return Gemini(settings.gemini_api_key, settings.gemini_model)

    @app.post("/api/jobs/{job_id}/outreach", response_model=OutreachResult, dependencies=[Depends(require_token)])
    def draft_outreach(job_id: int, regenerate: bool = False, s=Depends(session)):
        try:
            return outreach.draft(s, settings, get_llm(), job_id, now(), regenerate=regenerate)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/jobs/{job_id}/outreach", response_model=OutreachResult, dependencies=[Depends(require_token)])
    def get_outreach(job_id: int, s=Depends(session)):
        result = outreach.load(s, settings, job_id)
        if result is None:
            raise HTTPException(404, "no draft yet")
        return result

    @app.get("/api/companies", response_model=list[CompanyOut], dependencies=[Depends(require_token)])
    def list_companies(status: Literal["target", "watch", "avoid"] | None = None, kind: str | None = None, tier: str | None = None,
                       q: str | None = Query(None, max_length=100), limit: int = Query(500, ge=1, le=5000), s=Depends(session)):
        query = select(Company).where(Company.user_id == settings.user_id).order_by(Company.name).limit(limit)
        if status:
            query = query.where(Company.status == status)
        if kind:
            query = query.where(Company.kind.in_(kind.split(",")))
        if tier:
            query = query.where(Company.tier.in_(tier.split(",")))
        if q:
            query = query.where(Company.name.ilike(f"%{q}%"))
        return [CompanyOut.model_validate(c, from_attributes=True) for c in s.scalars(query)]

    @app.post("/api/companies", response_model=CompanyOut, dependencies=[Depends(require_token)])
    def add_company(body: CompanyAdd, response: Response, s=Depends(session)):
        try:
            board = discover.parse_board(body.text)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        existing = s.scalar(select(Company).where(Company.user_id == settings.user_id, Company.ats == board.ats, Company.slug == board.slug[:255]))
        if existing is None:
            board = board.model_copy(update={"status": body.status or "watch", "notes": body.notes or ""})
            discover.upsert_companies(s, settings.user_id, [board])
            s.commit()
            response.status_code = 201
            existing = s.scalar(select(Company).where(Company.user_id == settings.user_id, Company.ats == board.ats, Company.slug == board.slug[:255]))
        return CompanyOut.model_validate(existing, from_attributes=True)

    @app.post("/api/companies/{company_id}", response_model=CompanyOut, dependencies=[Depends(require_token)])
    def update_company(company_id: int, body: CompanyIn, s=Depends(session)):
        c = s.get(Company, company_id)
        if c is None or c.user_id != settings.user_id:
            raise HTTPException(404, "company not found")
        if body.status:
            c.status = body.status
        if body.notes is not None:
            c.notes = body.notes
        s.commit()
        return CompanyOut.model_validate(c, from_attributes=True)

    @app.get("/api/coverage", response_model=list[RunOut], dependencies=[Depends(require_token)])
    def coverage(days: int = Query(7, ge=1, le=180), s=Depends(session)):
        rows = s.scalars(select(Run).where(Run.started_at >= now() - timedelta(days=days)).order_by(Run.started_at.desc()))
        return [RunOut.model_validate(r, from_attributes=True) for r in rows]

    return app


app = create_app()
