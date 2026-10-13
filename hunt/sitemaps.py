import re
from urllib.parse import urljoin, urlsplit

import httpx
from defusedxml import ElementTree as ET

from hunt.http import BoardError, get_text

JOB_PAGE = re.compile(r"/(?:careers?|jobs?|openings?|positions?|vacancies|opportunities|join-us|work-with-us)/(?!(?:page|category|tag|search)\b)[^/]+", re.IGNORECASE)
NOISE = re.compile(r"/(?:blog|articles?|news|press|stories|resources|insights)/", re.IGNORECASE)
MAX_SITEMAPS, MAX_URLS = 10, 200


def _locs(xml: str) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except (ET.ParseError, ValueError):
        return [], []
    tag = root.tag.lower()
    locs = [(el.text or "").strip() for el in root.iter() if el.tag.lower().endswith("loc") and el.text]
    return (locs, []) if tag.endswith("sitemapindex") else ([], locs)


async def _sitemap_locations(client: httpx.AsyncClient, root: str) -> list[str]:
    try:
        robots = await get_text(client, urljoin(root, "/robots.txt"))
        found = [m.group(1).strip() for m in re.finditer(r"^sitemap:\s*(\S+)", robots, re.IGNORECASE | re.MULTILINE)]
        if found:
            return found
    except BoardError:
        pass
    return [urljoin(root, "/sitemap.xml")]


async def sitemap_job_urls(client: httpx.AsyncClient, root: str) -> list[str]:
    host = urlsplit(root).netloc.lower()
    queue, seen_maps, urls, seen_urls = await _sitemap_locations(client, root), set(), [], set()
    while queue and len(seen_maps) < MAX_SITEMAPS and len(urls) < MAX_URLS:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            text = await get_text(client, sm)
        except BoardError:
            continue
        children, locs = _locs(text)
        queue += [c for c in children if urlsplit(c).netloc.lower() == host]
        for u in locs:
            parts = urlsplit(u)
            if parts.netloc.lower() != host or u in seen_urls or not JOB_PAGE.search(parts.path) or NOISE.search(parts.path):
                continue
            seen_urls.add(u)
            urls.append(u)
            if len(urls) >= MAX_URLS:
                break
    return urls
