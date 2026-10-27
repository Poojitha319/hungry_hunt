"""Company careers pages: JSON-LD JobPosting blocks, linked job pages, sitemap fallback."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

from hungry_hunt.adapters.html import html_posting, html_to_text
from hungry_hunt.core.http import BoardError, Limits, get_text
from hungry_hunt.core.schemas import Posting
from hungry_hunt.discovery.sitemaps import JOB_PAGE, NOISE, sitemap_job_urls

BOARD = "{slug}"
MAX_LDJSON = 1_000_000
HREF = re.compile(r"""href\s*=\s*["']([^"'#?]+)""", re.IGNORECASE)
JOB_PATH = re.compile(r"job|career|position|opening|vacanc|role|opportunit", re.IGNORECASE)
MAX_JOB_LINKS = 40
COUNTRY_CODES = {"india": "IN", "in": "IN", "ind": "IN", "united states": "US", "usa": "US", "us": "US"}


def _job_postings(node, depth: int = 0):
    if depth > 8:
        return
    if isinstance(node, list):
        for item in node[:500]:
            yield from _job_postings(item, depth + 1)
    elif isinstance(node, dict):
        if node.get("@type") == "JobPosting":
            yield node
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in node:
                yield from _job_postings(node[key], depth + 1)


def _ldjson_blocks(page: str) -> list[str]:
    blocks, lower, pos = [], page.lower(), 0
    while True:
        tag = lower.find("application/ld+json", pos)
        if tag < 0:
            break
        start = lower.find(">", tag)
        end = lower.find("</script>", start) if start >= 0 else -1
        if start < 0 or end < 0:
            break
        if end - start <= MAX_LDJSON:
            blocks.append(page[start + 1 : end])
        pos = end
    return blocks


def jsonld_postings(page: str) -> list[dict]:
    found = []
    for block in _ldjson_blocks(page):
        try:
            found += list(_job_postings(json.loads(block.strip())))
        except (ValueError, RecursionError):
            continue
    return found


def _address(loc) -> tuple[str, str | None]:
    if isinstance(loc, list):
        parts = [_address(x) for x in loc]
        return " / ".join(p[0] for p in parts if p[0]), next((p[1] for p in parts if p[1]), None)
    if not isinstance(loc, dict):
        return "", None
    addr = loc.get("address")
    a = addr if isinstance(addr, dict) else loc
    bits = [v for k in ("addressLocality", "addressRegion", "addressCountry") if isinstance(v := a.get(k), str) and v]
    country = a.get("addressCountry") or ""
    code = COUNTRY_CODES.get(country.lower()) if isinstance(country, str) else None
    return ", ".join(bits), code


def parse(page: str, base: str) -> list[Posting]:
    out = []
    for j in jsonld_postings(page):
        ident = j.get("identifier")
        external = (
            (ident.get("value") if isinstance(ident, dict) else ident)
            or j.get("url")
            or f"{j.get('title')}|{j.get('datePosted')}"
        )
        location_raw, country = _address(j.get("jobLocation"))
        remote = j.get("jobLocationType") == "TELECOMMUTE" or "remote" in location_raw.lower()
        posted = None
        if j.get("datePosted"):
            try:
                posted = datetime.fromisoformat(str(j["datePosted"]))
                posted = posted if posted.tzinfo else posted.replace(tzinfo=UTC)
            except ValueError:
                posted = None
        url = str(j.get("url") or "")
        if urlsplit(url).scheme not in ("http", "https"):
            url = base
        out.append(
            Posting(
                external_id=str(external)[:255],
                title=str(j.get("title") or "").strip(),
                location_raw=location_raw,
                country=country,
                remote_flag=remote,
                url=url,
                posted_at=posted,
                description=html_to_text(str(j.get("description") or "")),
            )
        )
    return [p for p in out if p.title]


def job_links(page: str, base: str) -> list[str]:
    host = urlsplit(base).netloc.lower()
    seen, out = set(), []
    for href in HREF.findall(page):
        url = urljoin(base, href.strip())
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.netloc.lower() != host or url.rstrip("/") == base.rstrip("/"):
            continue
        if not JOB_PATH.search(parts.path) or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out[:MAX_JOB_LINKS]


async def board(client, url: str, limits: Limits | None) -> list[Posting]:
    page = await get_text(client, url, limits=limits)
    postings = parse(page, url)
    if postings:
        return postings
    seen = set()
    links = job_links(page, url)
    if not links:
        root = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
        links = (await sitemap_job_urls(client, root))[:MAX_JOB_LINKS]
    for link in links:
        try:
            sub = await get_text(client, link, limits=limits)
        except BoardError:
            continue
        found = parse(sub, link)
        if (
            not found
            and JOB_PAGE.search(urlsplit(link).path)
            and not NOISE.search(urlsplit(link).path)
            and (p := html_posting(sub, link))
        ):
            found = [p]
        for p in found:
            if p.external_id not in seen:
                seen.add(p.external_id)
                postings.append(p)
    return postings
