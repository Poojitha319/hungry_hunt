"""Workday CXS jobs API; slug form is host/tenant/site."""

import re
from datetime import UTC, datetime, timedelta

import httpx

from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.http import BoardError, Limits, get_json, post_json
from hungry_hunt.core.schemas import Posting

PAGE, CAP = 20, 400
POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)
HOST = re.compile(r"[\w-]+\.wd\d+\.myworkdayjobs\.com", re.IGNORECASE)


def board_url(slug: str) -> str:
    host, _tenant, site = slug.split("/", 2)
    return f"https://{host}/en-US/{site}"


def posted_days(text: str) -> int | None:
    m = POSTED.search(text or "")
    if not m:
        return None
    word = m.group(1).lower()
    return 0 if word == "today" else 1 if word == "yesterday" else int(m.group(2))


def parse(postings: list[dict], host: str, site: str, now: datetime) -> list[Posting]:
    out = []
    for j in postings:
        path = j.get("externalPath") or ""
        bullets = [b for b in j.get("bulletFields") or [] if isinstance(b, str)]
        days = posted_days(j.get("postedOn", ""))
        out.append(
            Posting(
                external_id=(bullets[0] if bullets else path)[:255],
                title=j.get("title", ""),
                location_raw=j.get("locationsText") or "",
                url=f"https://{host}/en-US/{site}{path}",
                posted_at=now - timedelta(days=days) if days is not None else None,
                detail_ref=path,
            )
        )
    return [p for p in out if p.title and p.detail_ref]


def parts(slug: str) -> tuple[str, str, str]:
    host, tenant, site = slug.split("/", 2)
    if not HOST.fullmatch(host):
        raise BoardError(f"{slug}: not a myworkdayjobs.com host")
    return host, tenant, site


async def board(client, slug: str, limits: Limits | None) -> list[Posting]:
    host, tenant, site = parts(slug)
    now, postings, offset, total = datetime.now(UTC), [], 0, None
    while total is None or offset < min(total, CAP):
        data = await post_json(
            client,
            f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
            {"limit": PAGE, "offset": offset, "appliedFacets": {}, "searchText": ""},
            limits=limits,
        )
        page = parse(data.get("jobPostings") or [], host, site, now)
        if total is None:
            total = int(data.get("total") or 0)
        if not page:
            break
        postings += page
        offset += PAGE
    return postings


async def description(client: httpx.AsyncClient, slug: str, external_path: str, limits: Limits | None = None) -> str:
    host, tenant, site = parts(slug)
    data = await get_json(client, f"https://{host}/wday/cxs/{tenant}/{site}{external_path}", limits=limits)
    return html_to_text((data.get("jobPostingInfo") or {}).get("jobDescription") or "")
