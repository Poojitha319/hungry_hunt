"""Amazon jobs search JSON."""

import contextlib
from datetime import UTC, datetime

from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import Limits, get_json
from hungry_hunt.core.schemas import Posting

BOARD = "https://www.amazon.jobs/en/search?country={slug}"
SEARCH = "https://www.amazon.jobs/en/search.json"
PAGE, CAP = 100, 3000


def parse(jobs: list[dict]) -> list[Posting]:
    out = []
    for j in jobs:
        posted = None
        with contextlib.suppress(ValueError):
            posted = datetime.strptime(j.get("posted_date") or "", "%B %d, %Y").replace(tzinfo=UTC)
        text = " ".join(j.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
        out.append(
            Posting(
                external_id=str(j.get("id_icims") or j.get("id")),
                title=j.get("title") or "",
                location_raw=j.get("normalized_location") or j.get("location") or "",
                country=(j.get("country_code") or "")[:2] or None,
                url="https://www.amazon.jobs" + (j.get("job_path") or ""),
                posted_at=posted,
                description=html_to_text(text) or None,
            )
        )
    return [p for p in out if p.title]


async def board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, offset, hits = [], 0, None
    while hits is None or offset < min(hits, CAP):
        data = await get_json(
            client,
            SEARCH,
            params={"base_query": "", "country": slug, "result_limit": PAGE, "offset": offset, "sort": "recent"},
            limits=limits,
        )
        page = parse(data.get("jobs") or [])
        hits = int(data.get("hits") or 0)
        if not page:
            break
        postings += page
        offset += PAGE
    return postings
