"""Grounded outreach drafts for one job."""

from fastapi import APIRouter, Depends, HTTPException

from hungry_hunt.api.deps import Ctx, Db, require_token
from hungry_hunt.core.schemas import OutreachResult
from hungry_hunt.delivery import outreach

router = APIRouter(dependencies=[Depends(require_token)])


@router.post("/api/jobs/{job_id}/outreach", response_model=OutreachResult)
def draft_outreach(job_id: int, ctx: Ctx, s: Db, regenerate: bool = False):
    try:
        return outreach.draft(s, ctx.settings, ctx.get_llm(), job_id, ctx.now(), regenerate=regenerate)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/jobs/{job_id}/outreach", response_model=OutreachResult)
def get_outreach(job_id: int, ctx: Ctx, s: Db):
    result = outreach.load(s, ctx.settings, job_id)
    if result is None:
        raise HTTPException(404, "no draft yet")
    return result
