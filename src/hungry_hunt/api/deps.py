"""FastAPI dependencies: app context, DB session, bearer-token auth, ownership checks."""

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from hungry_hunt.config import Settings
from hungry_hunt.db.models import Company, Job


@dataclass
class Context:
    settings: Settings
    sf: Any
    now: Callable[[], datetime]
    llm: Any = None

    def get_llm(self):
        if self.llm is not None:
            return self.llm
        from hungry_hunt.scoring.gemini import Gemini

        return Gemini(self.settings.gemini_api_key, self.settings.gemini_model)


def get_ctx(request: Request) -> Context:
    return request.app.state.ctx


def get_session(ctx: Annotated[Context, Depends(get_ctx)]):
    with ctx.sf() as s:
        yield s


def require_token(request: Request, ctx: Annotated[Context, Depends(get_ctx)]) -> None:
    header = request.headers.get("authorization", "")
    supplied = (
        header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else request.query_params.get("t", "")
    )
    if not ctx.settings.review_token or not hmac.compare_digest(supplied.encode(), ctx.settings.review_token.encode()):
        raise HTTPException(401, "invalid or missing token")


def owned_job(s: Session, ctx: Context, job_id: int) -> tuple[Job, Company]:
    row = s.execute(
        select(Job, Company)
        .join(Company, Job.company_id == Company.id)
        .where(Job.id == job_id, Company.user_id == ctx.settings.user_id)
    ).first()
    if row is None:
        raise HTTPException(404, "job not found")
    return row


Ctx = Annotated[Context, Depends(get_ctx)]
Db = Annotated[Session, Depends(get_session)]
