"""Workable public jobs feed, grouped by company downstream."""

from datetime import datetime

from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import Limits, get_json
from hungry_hunt.core.schemas import Posting

BOARD = "https://jobs.workable.com/company/{slug}"
FEED_BOARD = "https://jobs.workable.com/search?location={slug}"
FEED = "https://jobs.workable.com/api/v1/jobs"
FEED_PAGES = 400


def parse(jobs: list[dict]) -> list[Posting]:
    out = []
    for j in jobs:
        company, loc = j.get("company") or {}, j.get("location") or {}
        text = " ".join(j.get(k) or "" for k in ("description", "requirementsSection", "benefitsSection"))
        out.append(
            Posting(
                external_id=str(j["id"]),
                title=j.get("title") or "",
                location_raw=", ".join(j.get("locations") or []),
                country="IN" if loc.get("countryName") == "India" else None,
                remote_flag=j.get("workplace") == "remote",
                url=j.get("url") or "",
                posted_at=datetime.fromisoformat(j["created"]) if j.get("created") else None,
                description=html_to_text(text) or None,
                company_name=company.get("title"),
                company_ref=company.get("id"),
                company_url=company.get("url"),
            )
        )
    return [p for p in out if p.title and p.company_ref]


async def board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, params = [], {"location": slug}
    for _ in range(FEED_PAGES):
        data = await get_json(client, FEED, params=params, limits=limits)
        postings += parse(data.get("jobs") or [])
        if not data.get("nextPageToken") or not data.get("jobs"):
            break
        params = {**params, "pageToken": data["nextPageToken"]}
    return postings
