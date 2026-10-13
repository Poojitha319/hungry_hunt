import html
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from hunt.http import BoardError, Limits, get_json, get_text, post_json
from hunt.schemas import Posting
from hunt.sitemaps import JOB_PAGE, NOISE, sitemap_job_urls

BOARD_URL = {"greenhouse": "https://job-boards.greenhouse.io/{slug}", "lever": "https://jobs.lever.co/{slug}",
             "ashby": "https://jobs.ashbyhq.com/{slug}", "careers": "{slug}", "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}",
             "workable": "https://jobs.workable.com/company/{slug}", "workable_feed": "https://jobs.workable.com/search?location={slug}", "amazon": "https://www.amazon.jobs/en/search?country={slug}",
             "google": "https://www.google.com/about/careers/applications/jobs/results/?location={slug}"}
WD_PAGE, WD_CAP = 20, 400
WD_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)
SR_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
WORKABLE_FEED = "https://jobs.workable.com/api/v1/jobs"
WORKABLE_FEED_PAGES = 400
AMAZON_SEARCH = "https://www.amazon.jobs/en/search.json"
AMAZON_PAGE, AMAZON_CAP = 100, 3000
GOOGLE_RESULTS = "https://www.google.com/about/careers/applications/jobs/results/"
GOOGLE_PAGE, GOOGLE_PAGES = 20, 30
WORKDAY_HOST = re.compile(r"[\w-]+\.wd\d+\.myworkdayjobs\.com", re.IGNORECASE)
SR_PAGE = 100
MAX_LDJSON = 1_000_000
HREF = re.compile(r"""href\s*=\s*["']([^"'#?]+)""", re.IGNORECASE)
JOB_PATH = re.compile(r"job|career|position|opening|vacanc|role|opportunit", re.IGNORECASE)
MAX_JOB_LINKS = 40
COUNTRY_CODES = {"india": "IN", "in": "IN", "ind": "IN", "united states": "US", "usa": "US", "us": "US"}
API = {"greenhouse": ["https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs"],
       "lever": ["https://api.lever.co/v0/postings/{slug}", "https://api.eu.lever.co/v0/postings/{slug}"],
       "ashby": ["https://api.ashbyhq.com/posting-api/job-board/{slug}"]}
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def html_to_text(s: str) -> str:
    return SPACE.sub(" ", TAG.sub(" ", html.unescape(html.unescape(s or "")))).strip()


CHROME_TAG = re.compile(r"<(/?)(script|style|noscript|svg|nav|header|footer)\b[^>]*>", re.IGNORECASE)
H1_OPEN = re.compile(r"<h1\b[^>]*>", re.IGNORECASE)
HIRING_CUES = re.compile(r"responsibilit|requirements|qualifications|what you.ll do|apply now|job description", re.IGNORECASE)
ROLE = re.compile(r"engineer|developer|\bsde\b|manager|specialist|\blead\b|analyst|designer|intern|associate|architect|scientist|consultant|executive|\bhead\b|director|officer|representative|recruiter|writer|marketer|accountant|counsel|programmer|administrator|\bmts\b", re.IGNORECASE)
MAX_PAGE = 400_000


def strip_chrome(page: str) -> str:
    out, depth, pos = [], 0, 0
    for m in CHROME_TAG.finditer(page):
        if depth == 0:
            out.append(page[pos:m.start()])
        depth = max(0, depth - 1) if m.group(1) else depth + 1
        pos = m.end()
    if depth == 0:
        out.append(page[pos:])
    return " ".join(out)


def html_posting(page: str, url: str) -> Posting | None:
    body = strip_chrome(page[:MAX_PAGE])
    m = H1_OPEN.search(body)
    title = html_to_text(body[m.end():m.end() + 500].split("</h1")[0]) if m else ""
    text = html_to_text(body)
    if not title or len(title) > 120 or not ROLE.search(title) or not HIRING_CUES.search(text):
        return None
    return Posting(external_id=urlsplit(url).path[:255], title=title, url=url, description=text)


def _iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


async def _get_with_fallback(client, ats, slug, params=None, limits=None):
    hosts = API[ats]
    for i, url in enumerate(hosts):
        try:
            return await get_json(client, url.format(slug=slug), params=params, limits=limits)
        except BoardError as e:
            if e.status != 404 or i == len(hosts) - 1:
                raise
    raise BoardError(f"{ats}:{slug} not found", status=404)


def _greenhouse(data) -> list[Posting]:
    return [Posting(external_id=str(j["id"]), title=j["title"], location_raw=(j.get("location") or {}).get("name") or "",
                    url=j["absolute_url"], posted_at=_iso(j.get("first_published") or j.get("updated_at")),
                    company_name=j.get("company_name")) for j in data.get("jobs", [])]


def _lever(data) -> list[Posting]:
    out = []
    for j in data:
        c = j.get("categories") or {}
        lists = " ".join(f"{li.get('text', '')} {html_to_text(li.get('content', ''))}" for li in j.get("lists") or [])
        out.append(Posting(external_id=j["id"], title=j["text"],
                           location_raw=" / ".join(filter(None, c.get("allLocations") or [c.get("location")])),
                           country=j.get("country"), remote_flag=j.get("workplaceType") == "remote", url=j["hostedUrl"],
                           posted_at=datetime.fromtimestamp(j["createdAt"] / 1000, tz=UTC) if j.get("createdAt") else None,
                           description=html_to_text(f"{j.get('descriptionPlain') or ''} {lists}")))
    return out


def _ashby(data) -> list[Posting]:
    out = []
    for j in data.get("jobs", []):
        locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
        out.append(Posting(external_id=j["id"], title=j["title"], location_raw=" / ".join(filter(None, locs)),
                           remote_flag=bool(j.get("isRemote")), url=j["jobUrl"], posted_at=_iso(j.get("publishedAt")),
                           description=html_to_text(j.get("descriptionPlain") or "")))
    return out


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
            blocks.append(page[start + 1:end])
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
    a = loc.get("address") if isinstance(loc.get("address"), dict) else loc
    bits = [a.get(k) for k in ("addressLocality", "addressRegion", "addressCountry") if isinstance(a.get(k), str) and a.get(k)]
    country = (a.get("addressCountry") or "")
    code = COUNTRY_CODES.get(country.lower()) if isinstance(country, str) else None
    return ", ".join(bits), code


def _careers(page: str, base: str) -> list[Posting]:
    out = []
    for j in jsonld_postings(page):
        ident = j.get("identifier")
        external = (ident.get("value") if isinstance(ident, dict) else ident) or j.get("url") or f"{j.get('title')}|{j.get('datePosted')}"
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
        out.append(Posting(external_id=str(external)[:255], title=str(j.get("title") or "").strip(), location_raw=location_raw, country=country,
                           remote_flag=remote, url=url, posted_at=posted, description=html_to_text(str(j.get("description") or ""))))
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


async def _careers_board(client, url: str, limits: Limits | None) -> list[Posting]:
    page = await get_text(client, url, limits=limits)
    postings = _careers(page, url)
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
        found = _careers(sub, link)
        if not found and JOB_PAGE.search(urlsplit(link).path) and not NOISE.search(urlsplit(link).path) and (p := html_posting(sub, link)):
            found = [p]
        for p in found:
            if p.external_id not in seen:
                seen.add(p.external_id)
                postings.append(p)
    return postings


PARSERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}
PARAMS = {"greenhouse": None, "lever": {"mode": "json"}, "ashby": None}


def _smartrecruiters(content: list[dict], slug: str) -> list[Posting]:
    out = []
    for j in content:
        loc = j.get("location") or {}
        bits = [loc.get(k) for k in ("city", "region", "country") if loc.get(k)]
        country = loc.get("country")
        out.append(Posting(external_id=str(j["id"]), title=j.get("name", ""), location_raw=", ".join(bits),
                           country=country.upper() if isinstance(country, str) and len(country) == 2 else None,
                           remote_flag=bool(loc.get("remote")), url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                           posted_at=_iso(j.get("releasedDate"))))
    return out


async def _smartrecruiters_board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, offset = [], 0
    while True:
        data = await get_json(client, SR_API.format(slug=slug), params={"limit": SR_PAGE, "offset": offset}, limits=limits)
        postings += _smartrecruiters(data.get("content", []), slug)
        offset += SR_PAGE
        if offset >= int(data.get("totalFound", 0)) or not data.get("content"):
            return postings


def _workable_feed(jobs: list[dict]) -> list[Posting]:
    out = []
    for j in jobs:
        company, loc = j.get("company") or {}, j.get("location") or {}
        text = " ".join(j.get(k) or "" for k in ("description", "requirementsSection", "benefitsSection"))
        out.append(Posting(external_id=str(j["id"]), title=j.get("title") or "", location_raw=", ".join(j.get("locations") or []),
                           country="IN" if loc.get("countryName") == "India" else None, remote_flag=j.get("workplace") == "remote",
                           url=j.get("url") or "", posted_at=datetime.fromisoformat(j["created"]) if j.get("created") else None,
                           description=html_to_text(text) or None, company_name=company.get("title"), company_ref=company.get("id"), company_url=company.get("url")))
    return [p for p in out if p.title and p.company_ref]


async def _workable_feed_board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, params = [], {"location": slug}
    for _ in range(WORKABLE_FEED_PAGES):
        data = await get_json(client, WORKABLE_FEED, params=params, limits=limits)
        postings += _workable_feed(data.get("jobs") or [])
        if not data.get("nextPageToken") or not data.get("jobs"):
            break
        params = {**params, "pageToken": data["nextPageToken"]}
    return postings


def _amazon(jobs: list[dict]) -> list[Posting]:
    out = []
    for j in jobs:
        posted = None
        try:
            posted = datetime.strptime(j.get("posted_date") or "", "%B %d, %Y").replace(tzinfo=UTC)
        except ValueError:
            pass
        text = " ".join(j.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
        out.append(Posting(external_id=str(j.get("id_icims") or j.get("id")), title=j.get("title") or "", location_raw=j.get("normalized_location") or j.get("location") or "",
                           country=(j.get("country_code") or "")[:2] or None, url="https://www.amazon.jobs" + (j.get("job_path") or ""),
                           posted_at=posted, description=html_to_text(text) or None))
    return [p for p in out if p.title]


async def _amazon_board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings, offset, hits = [], 0, None
    while hits is None or offset < min(hits, AMAZON_CAP):
        data = await get_json(client, AMAZON_SEARCH, params={"base_query": "", "country": slug, "result_limit": AMAZON_PAGE, "offset": offset, "sort": "recent"}, limits=limits)
        page = _amazon(data.get("jobs") or [])
        hits = int(data.get("hits") or 0)
        if not page:
            break
        postings += page
        offset += AMAZON_PAGE
    return postings


def google_records(page: str) -> tuple[list, int]:
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


def _google(records: list) -> list[Posting]:
    out = []
    for r in records:
        try:
            locs = [loc[0] for loc in r[9] if loc and loc[0]]
            country = next((loc[5] for loc in r[9] if loc and len(loc) > 5 and loc[5]), None)
            text = " ".join(part[1] for part in (r[10], r[3], r[4]) if isinstance(part, list) and len(part) > 1 and part[1])
            posted = datetime.fromtimestamp(r[12][0], UTC) if isinstance(r[12], list) and r[12] else None
            out.append(Posting(external_id=str(r[0]), title=str(r[1] or ""), location_raw="; ".join(locs), country=country,
                               url=f"{GOOGLE_RESULTS}{r[0]}", posted_at=posted, description=html_to_text(text) or None))
        except (IndexError, TypeError):
            continue
    return [p for p in out if p.title]


async def _google_board(client, slug: str, limits: Limits | None) -> list[Posting]:
    postings = []
    for page in range(1, GOOGLE_PAGES + 1):
        records, total = google_records(await get_text(client, f"{GOOGLE_RESULTS}?{urlencode({'location': slug, 'page': page})}", limits=limits))
        postings += _google(records)
        if len(records) < GOOGLE_PAGE or page * GOOGLE_PAGE >= total:
            break
    return postings


async def smartrecruiters_description(client: httpx.AsyncClient, slug: str, external_id: str, limits: Limits | None = None) -> str:
    job = await get_json(client, SR_API.format(slug=slug) + f"/{external_id}", limits=limits)
    sections = (job.get("jobAd") or {}).get("sections") or {}
    return html_to_text(" ".join((sections.get(k) or {}).get("text", "") for k in ("jobDescription", "qualifications", "additionalInformation")))


def board_url(ats: str, slug: str) -> str | None:
    if ats == "workday":
        host, _tenant, site = slug.split("/", 2)
        return f"https://{host}/en-US/{site}"
    return BOARD_URL.get(ats, "").format(slug=slug) or None


def workday_posted_days(text: str) -> int | None:
    m = WD_POSTED.search(text or "")
    if not m:
        return None
    word = m.group(1).lower()
    return 0 if word == "today" else 1 if word == "yesterday" else int(m.group(2))


def _workday(postings: list[dict], host: str, site: str, now: datetime) -> list[Posting]:
    out = []
    for j in postings:
        path = j.get("externalPath") or ""
        bullets = [b for b in j.get("bulletFields") or [] if isinstance(b, str)]
        days = workday_posted_days(j.get("postedOn", ""))
        out.append(Posting(external_id=(bullets[0] if bullets else path)[:255], title=j.get("title", ""), location_raw=j.get("locationsText") or "",
                           url=f"https://{host}/en-US/{site}{path}", posted_at=now - timedelta(days=days) if days is not None else None,
                           detail_ref=path))
    return [p for p in out if p.title and p.detail_ref]


def _workday_parts(slug: str) -> tuple[str, str, str]:
    host, tenant, site = slug.split("/", 2)
    if not WORKDAY_HOST.fullmatch(host):
        raise BoardError(f"{slug}: not a myworkdayjobs.com host")
    return host, tenant, site


async def _workday_board(client, slug: str, limits: Limits | None) -> list[Posting]:
    host, tenant, site = _workday_parts(slug)
    now, postings, offset, total = datetime.now(UTC), [], 0, None
    while total is None or offset < min(total, WD_CAP):
        data = await post_json(client, f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                               {"limit": WD_PAGE, "offset": offset, "appliedFacets": {}, "searchText": ""}, limits=limits)
        page = _workday(data.get("jobPostings") or [], host, site, now)
        if total is None:
            total = int(data.get("total") or 0)
        if not page:
            break
        postings += page
        offset += WD_PAGE
    return postings


async def workday_description(client: httpx.AsyncClient, slug: str, external_path: str, limits: Limits | None = None) -> str:
    host, tenant, site = _workday_parts(slug)
    data = await get_json(client, f"https://{host}/wday/cxs/{tenant}/{site}{external_path}", limits=limits)
    return html_to_text((data.get("jobPostingInfo") or {}).get("jobDescription") or "")


async def list_jobs(client: httpx.AsyncClient, ats: str, slug: str, limits: Limits | None = None) -> list[Posting]:
    if ats == "workday":
        return await _workday_board(client, slug, limits)
    if ats == "careers":
        return await _careers_board(client, slug, limits)
    if ats == "smartrecruiters":
        return await _smartrecruiters_board(client, slug, limits)
    if ats == "workable_feed":
        return await _workable_feed_board(client, slug, limits)
    if ats == "amazon":
        return await _amazon_board(client, slug, limits)
    if ats == "google":
        return await _google_board(client, slug, limits)
    data = await _get_with_fallback(client, ats, slug, params=PARAMS[ats], limits=limits)
    return PARSERS[ats](data)


class AtsSource:
    def __init__(self, client: httpx.AsyncClient, limits: Limits | None = None):
        self.client, self.limits = client, limits

    async def list_jobs(self, ats: str, slug: str) -> list[Posting]:
        return await list_jobs(self.client, ats, slug, self.limits)

    async def description(self, ats: str, slug: str, external_id: str) -> str:
        if ats == "greenhouse":
            return await greenhouse_description(self.client, slug, external_id, self.limits)
        if ats == "smartrecruiters":
            return await smartrecruiters_description(self.client, slug, external_id, self.limits)
        if ats == "workday":
            return await workday_description(self.client, slug, external_id, self.limits)
        return ""


async def greenhouse_description(client: httpx.AsyncClient, slug: str, external_id: str, limits: Limits | None = None) -> str:
    for host in API["greenhouse"]:
        try:
            job = await get_json(client, host.format(slug=slug).rstrip("/") + f"/{external_id}", limits=limits)
            return html_to_text(job.get("content") or "")
        except BoardError as e:
            if e.status != 404:
                raise
    return ""
