"""Job detail and application status."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from hungry_hunt.api.deps import Ctx, Db, owned_job, require_token
from hungry_hunt.api.schemas import ApplicationOut, AssessmentOut, CompanyOut, JobDetail, JobOut, StatusIn
from hungry_hunt.db.models import Application, Assessment, Profile

router = APIRouter(dependencies=[Depends(require_token)])


def application_out(a: Application) -> ApplicationOut:
    return ApplicationOut(
        job_id=a.job_id, status=a.status, applied_at=a.applied_at, notes=a.notes, updated_at=a.updated_at
    )


@router.get("/api/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int, ctx: Ctx, s: Db):
    job, company = owned_job(s, ctx, job_id)
    profile = s.get(Profile, ctx.settings.user_id)
    a = (
        s.scalar(
            select(Assessment).where(Assessment.job_id == job_id, Assessment.resume_version == profile.resume_version)
        )
        if profile
        else None
    )
    app_row = s.scalar(
        select(Application).where(Application.job_id == job_id, Application.user_id == ctx.settings.user_id)
    )
    return JobDetail(
        job=JobOut.model_validate(job, from_attributes=True),
        company=CompanyOut.model_validate(company, from_attributes=True),
        assessment=AssessmentOut.model_validate(a, from_attributes=True) if a else None,
        application=application_out(app_row) if app_row else None,
    )


@router.post("/api/jobs/{job_id}/status", response_model=ApplicationOut)
def set_status(job_id: int, body: StatusIn, ctx: Ctx, s: Db):
    owned_job(s, ctx, job_id)
    t = ctx.now()
    row = s.scalar(select(Application).where(Application.job_id == job_id, Application.user_id == ctx.settings.user_id))
    if row is None:
        row = Application(job_id=job_id, user_id=ctx.settings.user_id, status=body.status, updated_at=t)
        s.add(row)
    row.status, row.updated_at = body.status, t
    if body.notes is not None:
        row.notes = body.notes
    if body.status == "applied" and row.applied_at is None:
        row.applied_at = t
    s.commit()
    return application_out(row)
