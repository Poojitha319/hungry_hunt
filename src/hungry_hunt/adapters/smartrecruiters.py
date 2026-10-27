"""SmartRecruiters public postings API."""

import httpx

from hungry_hunt.adapters.common import iso
from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import Limits, get_json
from hungry_hunt.core.schemas import Posting

BOARD = "https://jobs.smartrecruiters.com/{slug}"
API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE = 100


def parse(content: list[dict], slug: str) -> list[Posting]:
    out = []
    for j in content:
        loc = j.get("location") or {}
        bits = [v for k in ("city", "region", "country") if (v := loc.get(k))]
        country = loc.get("country")
        out.append(
            Posting(
                external_id=str(j["id"]),
                title=j.get("name", ""),
                location_raw=", ".join(bits),
                country=country.upper() if isinstance(country, str) and len(country) == 2 else None,
                remote_flag=bool(loc.get("remote")),
                url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                posted_at=iso(j.get("releasedDate")),
            )
        )
    return out


async def board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, offset = [], 0
    while True:
        data = await get_json(client, API.format(slug=slug), params={"limit": PAGE, "offset": offset}, limits=limits)
        postings += parse(data.get("content", []), slug)
        offset += PAGE
        if offset >= int(data.get("totalFound", 0)) or not data.get("content"):
            return postings


async def description(client: httpx.AsyncClient, slug: str, external_id: str, limits: Limits | None = None) -> str:
    job = await get_json(client, API.format(slug=slug) + f"/{external_id}", limits=limits)
    sections = (job.get("jobAd") or {}).get("sections") or {}
    return html_to_text(
        " ".join(
            (sections.get(k) or {}).get("text", "")
            for k in ("jobDescription", "qualifications", "additionalInformation")
        )
    )
