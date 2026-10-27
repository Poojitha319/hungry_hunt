"""Watched companies: list, add by board URL or ats:slug, change status."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from hungry_hunt.api.deps import Ctx, Db, require_token
from hungry_hunt.api.schemas import CompanyAdd, CompanyIn, CompanyOut
from hungry_hunt.db.models import Company
from hungry_hunt.discovery import discover

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/api/companies", response_model=list[CompanyOut])
def list_companies(
    ctx: Ctx,
    s: Db,
    status: Literal["target", "watch", "avoid"] | None = None,
    kind: str | None = None,
    tier: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(500, ge=1, le=5000),
):
    query = select(Company).where(Company.user_id == ctx.settings.user_id).order_by(Company.name).limit(limit)
    if status:
        query = query.where(Company.status == status)
    if kind:
        query = query.where(Company.kind.in_(kind.split(",")))
    if tier:
        query = query.where(Company.tier.in_(tier.split(",")))
    if q:
        query = query.where(Company.name.ilike(f"%{q}%"))
    return [CompanyOut.model_validate(c, from_attributes=True) for c in s.scalars(query)]


@router.post("/api/companies", response_model=CompanyOut)
def add_company(body: CompanyAdd, response: Response, ctx: Ctx, s: Db):
    try:
        board = discover.parse_board(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    existing = s.scalar(
        select(Company).where(
            Company.user_id == ctx.settings.user_id, Company.ats == board.ats, Company.slug == board.slug[:255]
        )
    )
    if existing is None:
        board = board.model_copy(update={"status": body.status or "watch", "notes": body.notes or ""})
        discover.upsert_companies(s, ctx.settings.user_id, [board])
        s.commit()
        response.status_code = 201
        existing = s.scalar(
            select(Company).where(
                Company.user_id == ctx.settings.user_id, Company.ats == board.ats, Company.slug == board.slug[:255]
            )
        )
    return CompanyOut.model_validate(existing, from_attributes=True)


@router.post("/api/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyIn, ctx: Ctx, s: Db):
    c = s.get(Company, company_id)
    if c is None or c.user_id != ctx.settings.user_id:
        raise HTTPException(404, "company not found")
    if body.status:
        c.status = body.status
    if body.notes is not None:
        c.notes = body.notes
    s.commit()
    return CompanyOut.model_validate(c, from_attributes=True)
