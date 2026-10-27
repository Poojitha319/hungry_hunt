"""Liveness check that also proves the database answers."""

from fastapi import APIRouter
from sqlalchemy import select

from hungry_hunt.api.deps import Db

router = APIRouter()


@router.get("/health")
def health(s: Db):
    s.execute(select(1))
    return {"ok": True}
