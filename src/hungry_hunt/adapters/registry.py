"""Maps an ATS name to its adapter: board URL, job listing and description fetch."""

import httpx

from hungry_hunt.adapters import amazon, ashby, careers, google, greenhouse, lever, smartrecruiters, workable, workday
from hungry_hunt.adapters.common import get_with_fallback
from hungry_hunt.core.http import Limits
from hungry_hunt.core.schemas import Posting

SUPPORTED = (
    "greenhouse",
    "lever",
    "ashby",
    "careers",
    "smartrecruiters",
    "workday",
    "workable_feed",
    "amazon",
    "google",
)
BOARD_URL = {
    "greenhouse": greenhouse.BOARD,
    "lever": lever.BOARD,
    "ashby": ashby.BOARD,
    "careers": careers.BOARD,
    "smartrecruiters": smartrecruiters.BOARD,
    "workable": workable.BOARD,
    "workable_feed": workable.FEED_BOARD,
    "amazon": amazon.BOARD,
    "google": google.BOARD,
}
JSON_BOARDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
PAGED_BOARDS = {
    "workday": workday.board,
    "careers": careers.board,
    "smartrecruiters": smartrecruiters.board,
    "workable_feed": workable.board,
    "amazon": amazon.board,
    "google": google.board,
}
DESCRIPTIONS = {
    "greenhouse": greenhouse.description,
    "smartrecruiters": smartrecruiters.description,
    "workday": workday.description,
}


def board_url(ats: str, slug: str) -> str | None:
    if ats == "workday":
        return workday.board_url(slug)
    return BOARD_URL.get(ats, "").format(slug=slug) or None


async def list_jobs(client: httpx.AsyncClient, ats: str, slug: str, limits: Limits | None = None) -> list[Posting]:
    if ats in PAGED_BOARDS:
        return await PAGED_BOARDS[ats](client, slug, limits)
    mod = JSON_BOARDS[ats]
    data = await get_with_fallback(client, ats, mod.HOSTS, slug, params=mod.PARAMS, limits=limits)
    return mod.parse(data)


class AtsSource:
    def __init__(self, client: httpx.AsyncClient, limits: Limits | None = None):
        self.client, self.limits = client, limits

    async def list_jobs(self, ats: str, slug: str) -> list[Posting]:
        return await list_jobs(self.client, ats, slug, self.limits)

    async def description(self, ats: str, slug: str, external_id: str) -> str:
        fetch = DESCRIPTIONS.get(ats)
        return await fetch(self.client, slug, external_id, self.limits) if fetch else ""
