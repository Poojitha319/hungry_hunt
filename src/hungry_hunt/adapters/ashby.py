"""Ashby job board API."""

from hungry_hunt.adapters.common import iso
from hungry_hunt.adapters.html import html_to_text
from hungry_hunt.core.schemas import Posting

BOARD = "https://jobs.ashbyhq.com/{slug}"
HOSTS = ["https://api.ashbyhq.com/posting-api/job-board/{slug}"]
PARAMS = None


def parse(data) -> list[Posting]:
    out = []
    for j in data.get("jobs", []):
        locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
        out.append(
            Posting(
                external_id=j["id"],
                title=j["title"],
                location_raw=" / ".join(filter(None, locs)),
                remote_flag=bool(j.get("isRemote")),
                url=j["jobUrl"],
                posted_at=iso(j.get("publishedAt")),
                description=html_to_text(j.get("descriptionPlain") or ""),
            )
        )
    return out
