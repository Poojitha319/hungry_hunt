"""Pure drop rules: location, title, seniority, posting age; every decision is a tagged reason."""

import re
from datetime import datetime, timedelta

from hungry_hunt.core.schemas import Location, Posting, RuleResult, Years

RULES_VERSION = 7

INDIA = re.compile(
    r"\b(india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|gurgaon|gurugram|noida|delhi|new delhi|"
    r"kolkata|ahmedabad|kochi|jaipur|coimbatore|thiruvananthapuram|trivandrum|indore|chandigarh|mohali|"
    r"bhubaneswar|visakhapatnam|vizag)\b",
    re.IGNORECASE,
)
REMOTE = re.compile(r"\b(remote|anywhere|worldwide|distributed|work from home|wfh)\b", re.IGNORECASE)
RESTRICTED = re.compile(
    r"\b(us|usa|u\.s\.|united states|canada|north america|americas|latam|emea|europe|eu|uk|"
    r"united kingdom|germany|france|australia|apac(?!.*india)|singapore|pst|est|pacific|"
    r"eastern time|cet)\b",
    re.IGNORECASE,
)
NOT_A_PLACE = {
    "anywhere",
    "worldwide",
    "global",
    "globally",
    "hybrid",
    "only",
    "office",
    "based",
    "and",
    "the",
    "within",
    "from",
    "local",
    "flexible",
    "location",
    "locations",
    "multiple",
    "various",
    "any",
    "home",
    "work",
    "fully",
}
WORD = re.compile(r"[a-z]{3,}", re.IGNORECASE)

ROLE_NOUN = r"(?:software\s+)?(?:engineer|architect|specialist|analyst|developer|lead|manager|associate|executive|representative)"
NOT_ENG = re.compile(
    r"\b(?:support|solutions?|implementation|field|sales|customer\s+success|customer|pre-?sales|forward[- ]deploy(?:ed|ment)|network|"
    r"qa|test|testing|quality|quality\s+assurance|automation\s+test|sdet|servicenow|sap|mainframe|hardware|embedded|firmware|"
    r"mechanical|electrical|civil)\s+" + ROLE_NOUN + r"\b"
    r"|\baccount\s+(?:executive|manager|director)\b|\bbusiness\s+development\b|\bmarketing\b|\brecruit|\bconsultant\b|"
    r"\bintern(?:ship)?\b|\bbusiness\s+intel\w*\b|\btelecom\b|\bdata\s+operations\b|\bquality\s+services\b|\bfreelanc\w*\b|\b(?<!smart )contract(?:or|ual)?\b|\bqa\b|\bsdet\b|\btester\b|\banalyst\b|\bmanager\b|\bnight\s+shift\b|\btechnical\s+writer\b|"
    r"\bdesigner\b|\bproduct\s+owner\b|\bin\s+test\b|\bsoc\b|\bit\s+operations\b|\bsystems?\s+engineer\b|"
    r"\bsecurity\s+engineer\b|\bhelp\s*desk\b|\bcustomer\s+(?:experience|success|support|engineer)\b|"
    r"\btechnical\s+account\b|\bdeveloper\s+(?:advocate|relations|evangelist)\b|\bsolutions?\s+consultant\b",
    re.IGNORECASE,
)
ENG = re.compile(
    r"engineer|developer|\bsde\b|software|backend|back-end|full[ -]?stack|platform|devops|\bsre\b|"
    r"machine learning|\bml\b|\bai\b|data scien|programmer|member of technical staff|\bmts\b",
    re.IGNORECASE,
)
JUNIOR = re.compile(
    r"\b(sde|engineer|developer)\s*[- ]?\s*(1|i)\b|\bassociate\b|\bjunior\b|\bjr\.?\b|\bgraduate\b|"
    r"\bentry[- ]level\b|\bfresher\b|\bnew grad\b",
    re.IGNORECASE,
)
HARD_SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\bstaff\b|\bprincipal\b|\blead\b|\bmanager\b|\bdirector\b|\bhead\b|"
    r"\barchitect\b|\bvp\b",
    re.IGNORECASE,
)
SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\bstaff\b|\bprincipal\b|\blead\b|\bmanager\b|\bdirector\b|\bhead\b|"
    r"\barchitect\b|\bvp\b|\b(sde|engineer|developer)\s*[- ]?\s*(ii|iii|iv|v|2|3|4|5)\b|\b(ii|iii|iv)\b|\bl[4-9]\b|"
    r"\be[4-9]\b",
    re.IGNORECASE,
)

SENTENCE_SPLIT = re.compile(r"(?<!\d)\.(?!\d)|[;\n•]")
EXPERIENCE = re.compile(r"experience|\bexp\b|years?\s+(of|in)\b", re.IGNORECASE)
REQUIREMENT_CUE = re.compile(
    r"\b(need|require|required|must|should|looking for|at least|minimum|ideal|candidate|you|"
    r"qualifications?|requirements?)\b",
    re.IGNORECASE,
)
NUM = r"(\d{1,2}(?:\.\d)?)"
RANGE = re.compile(NUM + r"\s*(?:-|–|—|to)\s*" + NUM + r"\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
PLUS = re.compile(
    NUM
    + r"\s*(?:\+|plus|or more)\s*(?:years?|yrs?)|(?:at least|minimum(?: of)?|min\.?)\s*"
    + NUM
    + r"\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
PLAIN = re.compile(
    NUM + r"\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|professional\s+|work\s+|industry\s+|hands-on\s+)*experience",
    re.IGNORECASE,
)
FRESHER = re.compile(
    r"\bfreshers?\b|\bnew grad(uate)?s?\b|\bentry[- ]level\b|no (prior )?experience (required|necessary)|"
    r"recent graduates?|\b0\s*(?:-|–|to)\s*\d",
    re.IGNORECASE,
)
WORD_NUMBERS = {
    w: str(i)
    for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"])
}
WORD_NUMBER = re.compile(r"\b(" + "|".join(WORD_NUMBERS) + r")\b", re.IGNORECASE)

SERVICE_STRONG = re.compile(
    r"infotech|staffing|outsourc|recruit(ing|ment)?|consultancy|manpower|talent|placement|\bbpo\b|"
    r"\bkpo\b|hiring agency|\bcapco\b|publicis|sapient|\bepam\b|globallogic|\bvirtusa\b|\bmindtree\b|"
    r"\btech mahindra\b|\bhexaware\b|\bzensar\b|\bpersistent\b|\bcoforge\b|\bnagarro\b|\bthoughtworks\b",
    re.IGNORECASE,
)
SERVICE_WEAK = re.compile(
    r"solutions|services|technologies|consult|systems|infosys|\btcs\b|wipro|cognizant|accenture|"
    r"capgemini|deloitte|\bhcl\b|mphasis|ltimindtree",
    re.IGNORECASE,
)
SERVICE_TITLE = re.compile(r"consultant|client|delivery|bench|implementation|onsite|offshore", re.IGNORECASE)


def _names_a_place(raw: str) -> bool:
    leftover = RESTRICTED.sub(" ", REMOTE.sub(" ", raw))
    return any(w.lower() not in NOT_A_PLACE for w in WORD.findall(leftover))


def location(raw: str, country: str | None, remote_flag: bool) -> Location:
    is_india = bool(INDIA.search(raw)) or country == "IN"
    is_remote = remote_flag or bool(REMOTE.search(raw))
    restricted = (
        is_remote
        and not is_india
        and (bool(RESTRICTED.search(raw)) or country not in (None, "IN") or _names_a_place(raw))
    )
    return Location(is_india=is_india, is_remote=is_remote, remote_restricted=restricted)


def title_kind(title: str) -> tuple[bool, bool]:
    is_engineering = bool(ENG.search(title)) and not NOT_ENG.search(title)
    is_senior = bool(HARD_SENIOR.search(title)) or (bool(SENIOR.search(title)) and not JUNIOR.search(title))
    return is_engineering, is_senior


def _num(s: str) -> float:
    v = float(s)
    return int(v) if v.is_integer() else v


def _years_in(sentence: str) -> Years | None:
    normalized = WORD_NUMBER.sub(lambda m: WORD_NUMBERS[m.group(1).lower()], sentence)
    if EXPERIENCE.search(sentence):
        if (m := RANGE.search(normalized)) and float(m.group(1)) <= 15:
            return Years(min=_num(m.group(1)), max=_num(m.group(2)), evidence=sentence)
        if (m := PLUS.search(normalized)) and float(m.group(1) or m.group(2)) <= 15:
            return Years(min=_num(m.group(1) or m.group(2)), max=None, evidence=sentence)
        if (m := PLAIN.search(normalized)) and float(m.group(1)) <= 15:
            return Years(min=_num(m.group(1)), max=None, evidence=sentence)
    if FRESHER.search(normalized):
        return Years(min=0, max=None, evidence=sentence)
    return None


def years_in_title(title: str) -> Years:
    if (m := RANGE.search(title)) and float(m.group(1)) <= 15:
        return Years(min=_num(m.group(1)), max=_num(m.group(2)), evidence=title)
    if (m := PLUS.search(title)) and float(m.group(1) or m.group(2)) <= 15:
        return Years(min=_num(m.group(1) or m.group(2)), max=None, evidence=title)
    return Years()


def years_bar(description: str) -> Years:
    found = [
        (bool(REQUIREMENT_CUE.search(s)), y)
        for s in map(str.strip, SENTENCE_SPLIT.split(description))
        if s and (y := _years_in(s))
    ]
    if not found:
        return Years()
    return next((y for cued, y in found if cued), found[0][1])


def company_kind(name: str, slug: str, titles: list[str]) -> str:
    text = f"{name} {slug}"
    if SERVICE_STRONG.search(text):
        return "service"
    if SERVICE_WEAK.search(text) and titles:
        share = sum(bool(SERVICE_TITLE.search(t)) for t in titles) / len(titles)
        if share >= 0.25:
            return "service"
    return "product"


def tier(team_size: int | None, total_jobs: int) -> str:
    if team_size is not None:
        return "early_funded" if team_size < 50 else "mid" if team_size <= 500 else "big_product"
    return "early_funded" if total_jobs < 15 else "mid" if total_jobs <= 150 else "big_product"


def prefilter(p: Posting) -> bool:
    loc = location(p.location_raw, p.country, p.remote_flag)
    location_ok = loc.is_india or (loc.is_remote and not loc.remote_restricted) or not p.location_raw.strip()
    is_engineering, is_senior = title_kind(p.title)
    return location_ok and is_engineering and not is_senior


def evaluate(
    title: str,
    is_india: bool,
    is_remote: bool,
    location_raw: str,
    description: str | None,
    company_status: str,
    company_kind: str,
    max_years_bar: int,
    excluded_titles: list[str],
    *,
    posted_at: datetime | None = None,
    first_seen: datetime | None = None,
    now: datetime | None = None,
    max_posted_age_days: int | None = None,
) -> RuleResult:
    fails = []
    reference = posted_at or first_seen
    if max_posted_age_days and now and reference and now - reference > timedelta(days=max_posted_age_days):
        fails.append("stale_posting")
    if company_status == "avoid":
        fails.append("avoid_company")
    if company_kind == "service":
        fails.append("service_company")
    remote_ok = is_remote and not location(location_raw, None, True).remote_restricted
    if not (is_india or remote_ok or (not location_raw.strip() and INDIA.search(description or ""))):
        fails.append("location")
    is_engineering, is_senior = title_kind(title)
    if not is_engineering:
        fails.append("not_engineering")
    if is_senior:
        fails.append("senior")
    if any(x.lower() in title.lower() for x in excluded_titles):
        fails.append("excluded_title")
    years = years_in_title(title)
    if years.min is None:
        years = years_bar(description or "")
    if years.min is not None and years.min > max_years_bar:
        fails.append("years>bar")
    return RuleResult(passed=not fails, fails=fails, years=years, is_engineering=is_engineering, is_senior=is_senior)
