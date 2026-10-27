"""Pipeline run history for the coverage page."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from hungry_hunt.api.deps import Ctx, Db, require_token
from hungry_hunt.api.schemas import RunOut
from hungry_hunt.db.models import Run

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/api/coverage", response_model=list[RunOut])
def coverage(ctx: Ctx, s: Db, days: int = Query(7, ge=1, le=180)):
    rows = s.scalars(
        select(Run).where(Run.started_at >= ctx.now() - timedelta(days=days)).order_by(Run.started_at.desc())
    )
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]
