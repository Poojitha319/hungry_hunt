"""Today's digest as the review app sees it."""

from fastapi import APIRouter, Depends, Query

from hungry_hunt.api.deps import Ctx, Db, require_token
from hungry_hunt.core.schemas import Digest
from hungry_hunt.delivery import digest

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/api/digest", response_model=Digest)
def get_digest(ctx: Ctx, s: Db, days: int | None = Query(None, ge=1, le=90)):
    return digest.build(s, ctx.settings, ctx.now(), days=days, cap=None)
