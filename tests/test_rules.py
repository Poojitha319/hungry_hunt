import pytest

from hunt import rules


@pytest.mark.parametrize("raw,country,flag,india,remote,restricted", [
    ("Indianapolis, IN", "US", False, False, False, False),
    ("Indianapolis", None, False, False, False, False),
    ("Remote - India", None, False, True, True, False),
    ("Bengaluru / Hyderabad", None, False, True, False, False),
    ("Bangalore, Karnataka, India", None, False, True, False, False),
    ("Gurugram", None, False, True, False, False),
    ("Remote", None, False, False, True, False),
    ("", None, True, False, True, False),
    ("Remote (US only)", None, False, False, True, True),
    ("Remote - EMEA", None, False, False, True, True),
    ("Singapore / Remote", None, False, False, True, True),
    ("", None, False, False, False, False),
    ("Chennai", "IN", False, True, False, False),
    ("Berlin", "IN", False, True, False, False),
])
def test_location(raw, country, flag, india, remote, restricted):
    loc = rules.location(raw, country, flag)
    assert (loc.is_india, loc.is_remote, loc.remote_restricted) == (india, remote, restricted)


@pytest.mark.parametrize("title,eng,senior", [
    ("SDE-1 Backend", True, False),
    ("Software Engineer I", True, False),
    ("Associate Software Engineer", True, False),
    ("AI Platform Engineer", True, False),
    ("Software Engineer", True, False),
    ("Senior Software Engineer", True, True),
    ("Sr. Backend Engineer", True, True),
    ("SDE II", True, True),
    ("SDE III", True, True),
    ("Software Engineer 2", True, True),
    ("Staff Engineer", True, True),
    ("Headless CMS Developer", True, False),
    ("Implementation Engineer", False, False),
    ("Support Engineer", False, False),
    ("Technical Support Engineer", False, False),
    ("Forward Deployed Engineer", False, False),
    ("Forward Deployment Engineer", False, False),
    ("Freelance Full-Stack Developer - Python", False, False),
    ("Contract Software Engineer (6 months)", False, False),
    ("Smart Contract Engineer", True, False),
    ("Solutions Engineer", False, False),
    ("Software Engineer Intern", False, False),
    ("Engineering Manager", False, True),
    ("Lead Generation Specialist", False, True),
    ("Product Manager", False, True),
])
def test_title_kind(title, eng, senior):
    assert rules.title_kind(title) == (eng, senior)


@pytest.mark.parametrize("text,mn,mx,evidence_part", [
    ("Requirements: 4+ years of experience building backend systems.", 4, None, "4+ years"),
    ("0-2 years of experience with Python.", 0, 2, "0-2 years"),
    ("2+ years experience in a product company.", 2, None, "2+ years"),
    ("Freshers are welcome to apply.", 0, None, "Freshers"),
    ("We want 1 to 3 years of experience.", 1, 3, "1 to 3 years"),
    ("A minimum of 3 years experience is required.", 3, None, "minimum of 3 years"),
    ("five+ years of backend experience.", 5, None, "five+ years"),
    ("5+ years overall experience; 2+ years with Python.", 5, None, "5+ years overall"),
    ("We have been around for 8 years. Python 3 experience.", None, None, None),
    ("24/7 on-call rotation. Founded 2 years ago.", None, None, None),
    ("Entry-level role for recent graduates.", 0, None, "Entry-level"),
])
def test_years_bar(text, mn, mx, evidence_part):
    y = rules.years_bar(text)
    assert (y.min, y.max) == (mn, mx)
    if evidence_part is None:
        assert y.evidence is None
    else:
        assert evidence_part.lower() in y.evidence.lower()


@pytest.mark.parametrize("name,slug,titles,kind", [
    ("Razorpay Software Private Limited", "razorpaysoftwareprivatelimited", ["SDE I", "SDE II"], "product"),
    ("XYZ Infotech", "xyzinfotech", ["Java Developer"], "service"),
    ("TalentHub", "talenthub", ["Recruiter"], "service"),
    ("Acme Solutions", "acme", ["Backend Engineer"] * 19 + ["Implementation Consultant"], "product"),
    ("Acme Solutions", "acme", ["Backend Engineer"] * 12 + ["Implementation Consultant"] * 8, "service"),
    ("Hevo Data", "hevodata", ["SDE I", "Solutions Engineer"], "product"),
])
def test_company_kind(name, slug, titles, kind):
    assert rules.company_kind(name, slug, titles) == kind


@pytest.mark.parametrize("team,jobs,tier", [
    (30, 100, "early_funded"), (300, 5, "mid"), (900, 5, "big_product"),
    (None, 10, "early_funded"), (None, 52, "mid"), (None, 889, "big_product"),
])
def test_tier(team, jobs, tier):
    assert rules.tier(team, jobs) == tier


def test_prefilter_passes_blank_location_engineering_role():
    from hunt.schemas import Posting
    p = Posting(external_id="1", title="Software Engineer", location_raw="", url="u")
    assert rules.prefilter(p) is True


def test_prefilter_rejects_restricted_remote_and_senior():
    from hunt.schemas import Posting
    assert rules.prefilter(Posting(external_id="1", title="Software Engineer", location_raw="Remote - US only", url="u")) is False
    assert rules.prefilter(Posting(external_id="2", title="Senior Engineer", location_raw="Bangalore", url="u")) is False
    assert rules.prefilter(Posting(external_id="3", title="Support Engineer", location_raw="Bangalore", url="u")) is False
