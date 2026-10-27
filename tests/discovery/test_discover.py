import pytest
from sqlalchemy import select

from hungry_hunt.db.models import Company
from hungry_hunt.discovery import discover, seeds


@pytest.mark.parametrize(
    "text,ats,slug",
    [
        ("lever:hevodata", "lever", "hevodata"),
        ("greenhouse:acme", "greenhouse", "acme"),
        ("https://jobs.lever.co/cred", "lever", "cred"),
        ("https://jobs.lever.co/cred/abc-123", "lever", "cred"),
        ("https://boards.greenhouse.io/acme", "greenhouse", "acme"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
        ("https://job-boards.eu.greenhouse.io/growwreferrals", "greenhouse", "growwreferrals"),
        ("https://jobs.ashbyhq.com/sarvam", "ashby", "sarvam"),
        ("https://jobs.ashbyhq.com/Sarvam/xyz", "ashby", "sarvam"),
    ],
)
def test_parse_board(text, ats, slug):
    b = discover.parse_board(text)
    assert (b.ats, b.slug) == (ats, slug)


def test_parse_board_rejects_unknown():
    with pytest.raises(ValueError):
        discover.parse_board("https://www.linkedin.com/jobs/123")


def test_upsert_inserts_and_is_idempotent(session):
    boards = [
        discover.Board(ats="lever", slug="hevodata", name="Hevo Data", status="target"),
        discover.Board(
            ats="unsupported",
            slug="cashfree",
            name="Cashfree",
            board_url="https://careers.cashfree.com",
            notes="Kula ATS",
        ),
    ]
    assert discover.upsert_companies(session, "u", boards) == 2
    assert discover.upsert_companies(session, "u", boards) == 0
    rows = session.scalars(select(Company).where(Company.user_id == "u")).all()
    assert len(rows) == 2
    cf = next(r for r in rows if r.slug == "cashfree")
    assert (cf.ats, cf.board_url, cf.notes, cf.status) == (
        "unsupported",
        "https://careers.cashfree.com",
        "Kula ATS",
        "watch",
    )


def test_upsert_never_overwrites_human_status_or_notes(session):
    b = discover.Board(ats="lever", slug="porter", name="Porter", status="watch")
    discover.upsert_companies(session, "u", [b])
    row = session.scalar(select(Company).where(Company.slug == "porter"))
    row.status, row.notes = "avoid", "layoffs 2026 (set by me)"
    session.flush()
    discover.upsert_companies(
        session,
        "u",
        [discover.Board(ats="lever", slug="porter", name="Porter Inc", status="target", notes="seed note")],
    )
    row = session.scalar(select(Company).where(Company.slug == "porter"))
    assert (row.status, row.notes) == ("avoid", "layoffs 2026 (set by me)")


def test_seeds_cover_referral_list_and_verified_boards():
    by_slug = {(b.ats, b.slug): b for b in seeds.SEEDS}
    assert by_slug[("lever", "hevodata")].status == "target"
    assert by_slug[("lever", "porter")].status == "avoid"
    assert by_slug[("unsupported", "cashfree")].board_url
    assert by_slug[("workday", "postman.wd108.myworkdayjobs.com/postman/careers")].status == "target"
    assert sum(b.ats in ("greenhouse", "lever", "ashby") for b in seeds.SEEDS) >= 30
    assert len(by_slug) == len(seeds.SEEDS)


@pytest.mark.parametrize(
    "text",
    [
        "workable:acme",
        "https://apply.workable.com/acme/",
        "https://apply.workable.com/acme/j/512B42B5B8/",
        "https://acme.workable.com/",
    ],
)
def test_parse_board_recognises_workable(text):
    assert discover.parse_board(text) == discover.Board(ats="workable", slug="acme")


def test_boards_from_text_finds_workable_and_no_longer_treats_it_as_unsupported():
    page = '<a href="https://apply.workable.com/acme/">Jobs</a>'
    assert discover.boards_from_text(page) == [discover.Board(ats="workable", slug="acme")]
    assert discover.UNSUPPORTED.search(page) is None


@pytest.mark.parametrize(
    "text,board",
    [
        ("amazon:IND", discover.Board(ats="amazon", slug="IND")),
        ("google:India", discover.Board(ats="google", slug="India")),
        ("https://www.amazon.jobs/en/search?country=IND", discover.Board(ats="amazon", slug="IND")),
        (
            "https://www.google.com/about/careers/applications/jobs/results/?location=India",
            discover.Board(ats="google", slug="India"),
        ),
    ],
)
def test_parse_board_recognises_big_tech_search_pages(text, board):
    assert discover.parse_board(text) == board


@pytest.mark.parametrize(
    "text,board",
    [
        (
            "https://api.smartrecruiters.com/v1/companies/SWIGGY/postings",
            discover.Board(ats="smartrecruiters", slug="swiggy"),
        ),
        (
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
            discover.Board(ats="greenhouse", slug="acme"),
        ),
        ("https://api.lever.co/v0/postings/acme?mode=json", discover.Board(ats="lever", slug="acme")),
        ("https://api.ashbyhq.com/posting-api/job-board/acme", discover.Board(ats="ashby", slug="acme")),
    ],
)
def test_parse_board_recognises_ats_api_urls(text, board):
    assert discover.parse_board(text) == board
