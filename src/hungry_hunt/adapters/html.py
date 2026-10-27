"""HTML to text helpers and the plain-HTML job page reader."""

import html
import re
from urllib.parse import urlsplit

from hungry_hunt.core.schemas import Posting

TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
CHROME_TAG = re.compile(r"<(/?)(script|style|noscript|svg|nav|header|footer)\b[^>]*>", re.IGNORECASE)
H1_OPEN = re.compile(r"<h1\b[^>]*>", re.IGNORECASE)
HIRING_CUES = re.compile(
    r"responsibilit|requirements|qualifications|what you.ll do|apply now|job description", re.IGNORECASE
)
ROLE = re.compile(
    r"engineer|developer|\bsde\b|manager|specialist|\blead\b|analyst|designer|intern|associate|architect|scientist|consultant|executive|\bhead\b|director|officer|representative|recruiter|writer|marketer|accountant|counsel|programmer|administrator|\bmts\b",
    re.IGNORECASE,
)
MAX_PAGE = 400_000


def html_to_text(s: str) -> str:
    return SPACE.sub(" ", TAG.sub(" ", html.unescape(html.unescape(s or "")))).strip()


def strip_chrome(page: str) -> str:
    out, depth, pos = [], 0, 0
    for m in CHROME_TAG.finditer(page):
        if depth == 0:
            out.append(page[pos : m.start()])
        depth = max(0, depth - 1) if m.group(1) else depth + 1
        pos = m.end()
    if depth == 0:
        out.append(page[pos:])
    return " ".join(out)


def html_posting(page: str, url: str) -> Posting | None:
    body = strip_chrome(page[:MAX_PAGE])
    m = H1_OPEN.search(body)
    title = html_to_text(body[m.end() : m.end() + 500].split("</h1")[0]) if m else ""
    text = html_to_text(body)
    if not title or len(title) > 120 or not ROLE.search(title) or not HIRING_CUES.search(text):
        return None
    return Posting(external_id=urlsplit(url).path[:255], title=title, url=url, description=text)
