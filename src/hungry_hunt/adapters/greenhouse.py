"""Greenhouse job board API."""

import httpx

from hungry_hunt.adapters.common import iso
from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import BoardError, Limits, get_json
from hungry_hunt.core.schemas import Posting

BOARD = "https://job-boards.greenhouse.io/{slug}"
HOSTS = [
    "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs",
]
PARAMS = None


def parse(data) -> list[Posting]:
    return [
        Posting(
            external_id=str(j["id"]),
            title=j["title"],
            location_raw=(j.get("location") or {}).get("name") or "",
            url=j["absolute_url"],
            posted_at=iso(j.get("first_published") or j.get("updated_at")),
            company_name=j.get("company_name"),
        )
        for j in data.get("jobs", [])
    ]


async def description(client: httpx.AsyncClient, slug: str, external_id: str, limits: Limits | None = None) -> str:
    for host in HOSTS:
        try:
            job = await get_json(client, host.format(slug=slug).rstrip("/") + f"/{external_id}", limits=limits)
            return html_to_text(job.get("content") or "")
        except BoardError as e:
            if e.status != 404:
                raise
    return ""
