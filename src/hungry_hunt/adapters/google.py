"""Google careers results page (AF_initDataCallback records)."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urlencode

from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import Limits, get_text
from hungry_hunt.core.schemas import Posting

RESULTS = "https://www.google.com/about/careers/applications/jobs/results/"
BOARD = RESULTS + "?location={slug}"
PAGE, PAGES = 20, 30


def records(page: str) -> tuple[list, int]:
    m = re.search(r"key: 'ds:1'", page)
    i = page.find("data:", m.end()) + 5 if m else -1
    if i < 5:
        return [], 0
    while page[i] in " \n":
        i += 1
    try:
        data, _ = json.JSONDecoder().raw_decode(page, i)
    except json.JSONDecodeError:
        return [], 0
    return (data[0] or []), int(data[2] or 0) if len(data) > 2 and isinstance(data[2], int) else 0


def parse(recs: list) -> list[Posting]:
    out = []
    for r in recs:
        try:
            locs = [loc[0] for loc in r[9] if loc and loc[0]]
            country = next((loc[5] for loc in r[9] if loc and len(loc) > 5 and loc[5]), None)
            text = " ".join(
                part[1] for part in (r[10], r[3], r[4]) if isinstance(part, list) and len(part) > 1 and part[1]
            )
            posted = datetime.fromtimestamp(r[12][0], UTC) if isinstance(r[12], list) and r[12] else None
            out.append(
                Posting(
                    external_id=str(r[0]),
                    title=str(r[1] or ""),
                    location_raw="; ".join(locs),
                    country=country,
                    url=f"{RESULTS}{r[0]}",
                    posted_at=posted,
                    description=html_to_text(text) or None,
                )
            )
        except (IndexError, TypeError):
            continue
    return [p for p in out if p.title]


async def board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings = []
    for page in range(1, PAGES + 1):
        recs, total = records(
            await get_text(client, f"{RESULTS}?{urlencode({'location': slug, 'page': page})}", limits=limits)
        )
        postings += parse(recs)
        if len(recs) < PAGE or page * PAGE >= total:
            break
    return postings
