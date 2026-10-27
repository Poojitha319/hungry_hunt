"""Lever postings API."""

from datetime import UTC, datetime

from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.schemas import Posting

BOARD = "https://jobs.lever.co/{slug}"
HOSTS = ["https://api.lever.co/v0/postings/{slug}", "https://api.eu.lever.co/v0/postings/{slug}"]
PARAMS = {"mode": "json"}


def parse(data) -> list[Posting]:
    out = []
    for j in data:
        c = j.get("categories") or {}
        lists = " ".join(f"{li.get('text', '')} {html_to_text(li.get('content', ''))}" for li in j.get("lists") or [])
        out.append(
            Posting(
                external_id=j["id"],
                title=j["text"],
                location_raw=" / ".join(filter(None, c.get("allLocations") or [c.get("location")])),
                country=j.get("country"),
                remote_flag=j.get("workplaceType") == "remote",
                url=j["hostedUrl"],
                posted_at=datetime.fromtimestamp(j["createdAt"] / 1000, tz=UTC) if j.get("createdAt") else None,
                description=html_to_text(f"{j.get('descriptionPlain') or ''} {lists}"),
            )
        )
    return out
