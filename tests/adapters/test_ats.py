import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from hungry_hunt import adapters as ats
from hungry_hunt.core import http

FIX = Path(__file__).parent.parent / "fixtures"


def fixture(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(http, "BACKOFF", (0, 0))


@respx.mock
async def test_lever_postings_normalize(client):
    respx.get("https://api.lever.co/v0/postings/hevodata", params={"mode": "json"}).respond(
        json=fixture("lever_hevodata.json")
    )
    postings = await ats.list_jobs(client, "lever", "hevodata")
    sde = next(p for p in postings if p.title == "SDE I")
    assert sde.location_raw == "Bangalore, India"
    assert sde.country == "IN"
    assert sde.remote_flag is False
    assert sde.url.startswith("https://jobs.lever.co/hevodata/")
    assert sde.posted_at.tzinfo is not None and sde.posted_at < datetime.now(UTC)
    assert sde.description and "<" not in sde.description
    assert len(postings) == 3


@respx.mock
async def test_lever_remote_flag_and_lists_appended(client):
    data = fixture("lever_hevodata.json")
    data[0]["workplaceType"] = "remote"
    data[0]["lists"] = [{"text": "Requirements", "content": "<li>2+ years of experience</li>"}]
    respx.get("https://api.lever.co/v0/postings/hevodata", params={"mode": "json"}).respond(json=data)
    p = (await ats.list_jobs(client, "lever", "hevodata"))[0]
    assert p.remote_flag is True
    assert "2+ years of experience" in p.description


@respx.mock
async def test_greenhouse_list_has_no_description_and_company_name(client):
    respx.get("https://boards-api.greenhouse.io/v1/boards/observeai/jobs").respond(
        json=fixture("greenhouse_observeai_list.json")
    )
    postings = await ats.list_jobs(client, "greenhouse", "observeai")
    assert len(postings) == 3
    assert postings[0].description is None
    assert postings[0].company_name == "Observe.AI"
    assert postings[0].location_raw == "Hyderabad, Telangana, India"
    assert postings[0].posted_at is not None


@respx.mock
async def test_greenhouse_null_location_becomes_empty(client):
    data = fixture("greenhouse_observeai_list.json")
    data["jobs"][0]["location"] = None
    respx.get("https://boards-api.greenhouse.io/v1/boards/observeai/jobs").respond(json=data)
    postings = await ats.list_jobs(client, "greenhouse", "observeai")
    assert postings[0].location_raw == ""


@respx.mock
async def test_greenhouse_description_is_unescaped_plain_text(client):
    job = fixture("greenhouse_job_content.json")
    respx.get(f"https://boards-api.greenhouse.io/v1/boards/observeai/jobs/{job['id']}").respond(json=job)
    text = await ats.greenhouse_description(client, "observeai", str(job["id"]))
    assert "&lt;" not in text and "<" not in text
    assert len(text) > 50


@respx.mock
async def test_greenhouse_falls_back_to_eu_host_on_404(client):
    respx.get("https://boards-api.greenhouse.io/v1/boards/growwreferrals/jobs").respond(404)
    respx.get("https://boards-api.eu.greenhouse.io/v1/boards/growwreferrals/jobs").respond(
        json=fixture("greenhouse_observeai_list.json")
    )
    assert len(await ats.list_jobs(client, "greenhouse", "growwreferrals")) == 3


@respx.mock
async def test_ashby_remote_flag_and_secondary_locations(client):
    data = fixture("ashby_atlan.json")
    data["jobs"][0]["secondaryLocations"] = [{"location": "Bengaluru"}, {"location": "Remote - India"}]
    respx.get("https://api.ashbyhq.com/posting-api/job-board/atlan").respond(json=data)
    p = (await ats.list_jobs(client, "ashby", "atlan"))[0]
    assert p.remote_flag is True
    assert p.location_raw == "India / Bengaluru / Remote - India"
    assert p.description
    assert p.posted_at is not None


@respx.mock
async def test_get_json_raises_board_error_after_retries_on_500(client):
    route = respx.get("https://api.lever.co/v0/postings/dead").respond(500)
    with pytest.raises(http.BoardError) as e:
        await http.get_json(client, "https://api.lever.co/v0/postings/dead")
    assert e.value.status == 500
    assert route.call_count == 3


@respx.mock
async def test_get_json_404_raises_without_retry(client):
    route = respx.get("https://api.lever.co/v0/postings/nope").respond(404)
    with pytest.raises(http.BoardError) as e:
        await http.get_json(client, "https://api.lever.co/v0/postings/nope")
    assert e.value.status == 404
    assert route.call_count == 1


def test_html_to_text_strips_tags_and_entities():
    assert ats.html_to_text("&lt;p&gt;Hello &amp; <b>world</b>&lt;/p&gt;\n\n\n x") == "Hello & world x"


@respx.mock
async def test_smartrecruiters_adapter_lists_and_enriches(client):
    respx.get("https://api.smartrecruiters.com/v1/companies/acme/postings", params__contains={"offset": "0"}).respond(
        json=fixture("smartrecruiters_list.json")
    )
    respx.get("https://api.smartrecruiters.com/v1/companies/acme/postings/743999900000001").respond(
        json=fixture("smartrecruiters_detail.json")
    )
    postings = await ats.list_jobs(client, "smartrecruiters", "acme")
    assert len(postings) == 2
    p = postings[0]
    assert (p.external_id, p.title, p.location_raw, p.country, p.remote_flag) == (
        "743999900000001",
        "Software Engineer I - Backend",
        "Bengaluru, KA, in",
        "IN",
        False,
    )
    assert p.posted_at.year == 2026 and p.description is None and p.url.startswith("https://jobs.smartrecruiters.com/")
    assert postings[1].remote_flag is True and postings[1].country == "US"
    text = await ats.AtsSource(client).description("smartrecruiters", "acme", "743999900000001")
    assert "0-2 years of experience" in text and "Python" in text and "<" not in text


@respx.mock
async def test_smartrecruiters_adapter_paginates(client):
    page1 = fixture("smartrecruiters_list.json")
    page1["totalFound"] = 101
    page1["content"] = [dict(page1["content"][0], id=str(i)) for i in range(100)]
    page2 = fixture("smartrecruiters_list.json")
    page2["totalFound"] = 101
    page2["offset"] = 100
    page2["content"] = [dict(page2["content"][1], id="x")]
    respx.get("https://api.smartrecruiters.com/v1/companies/big/postings", params__contains={"offset": "0"}).respond(
        json=page1
    )
    respx.get("https://api.smartrecruiters.com/v1/companies/big/postings", params__contains={"offset": "100"}).respond(
        json=page2
    )
    assert len(await ats.list_jobs(client, "smartrecruiters", "big")) == 101


@respx.mock
async def test_workday_adapter_lists_pages_and_reads_detail(client):
    body = fixture("workday_list.json")
    respx.post("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json=body
            if json.loads(req.content)["offset"] == 0
            else {
                "total": 41,
                "jobPostings": [
                    dict(body["jobPostings"][0], externalPath=f"/job/x/Y_JR{json.loads(req.content)['offset']}")
                ],
            },
        )
    )
    respx.get(
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/job/IN-KA-Bangalore/Software-Engineer-I---Backend_JR1001"
    ).respond(json=fixture("workday_detail.json"))
    postings = await ats.list_jobs(client, "workday", "acme.wd5.myworkdayjobs.com/acme/External")
    assert len(postings) == 4 and postings[0].external_id == "JR1001"
    p = postings[0]
    assert (p.title, p.location_raw, p.description) == ("Software Engineer I - Backend", "IN, KA, Bangalore", None)
    assert (
        p.url
        == "https://acme.wd5.myworkdayjobs.com/en-US/External/job/IN-KA-Bangalore/Software-Engineer-I---Backend_JR1001"
    )
    assert p.posted_at is not None and (datetime.now(UTC) - p.posted_at).days <= 2
    assert postings[1].posted_at is not None and (datetime.now(UTC) - postings[1].posted_at).days >= 30
    text = await ats.AtsSource(client).description(
        "workday",
        "acme.wd5.myworkdayjobs.com/acme/External",
        "/job/IN-KA-Bangalore/Software-Engineer-I---Backend_JR1001",
    )
    assert "0-2 years of experience" in text and "<" not in text


@pytest.mark.parametrize(
    "text,days",
    [
        ("Posted Today", 0),
        ("Posted Yesterday", 1),
        ("Posted 3 Days Ago", 3),
        ("Posted 30+ Days Ago", 30),
        ("garbage", None),
    ],
)
def test_workday_posted_on_to_age(text, days):
    assert ats.workday_posted_days(text) == days


def test_parse_board_accepts_workday_urls_and_slugs():
    for text in [
        "workday:acme.wd5.myworkdayjobs.com/acme/External",
        "https://acme.wd5.myworkdayjobs.com/en-US/External/job/x",
        "https://acme.wd5.myworkdayjobs.com/External",
    ]:
        from hungry_hunt.discovery import discover

        b = discover.parse_board(text)
        assert (b.ats, b.slug) == ("workday", "acme.wd5.myworkdayjobs.com/acme/External"), text


@respx.mock
async def test_workable_feed_pages_by_token_and_tags_postings_with_their_company(client):
    respx.get(
        "https://jobs.workable.com/api/v1/jobs", params__contains={"location": "India", "pageToken": "tok2"}
    ).respond(json=fixture("workable_feed_2.json"))
    respx.get("https://jobs.workable.com/api/v1/jobs", params__contains={"location": "India"}).respond(
        json=fixture("workable_feed.json")
    )
    postings = await ats.list_jobs(client, "workable_feed", "India")
    assert len(postings) == 4 and len({p.company_ref for p in postings}) == 2
    p = postings[0]
    assert (p.title[:24], p.company_name, p.location_raw, p.country) == (
        "Senior Software Engineer",
        "Apna",
        "Bengaluru, Karnataka, India",
        "IN",
    )
    assert p.company_ref == "b7c615d2-3982-4e8d-8e33-bb53f501c869" and p.company_url.startswith(
        "https://jobs.workable.com/company/"
    )
    assert p.url.startswith("https://jobs.workable.com/view/") and p.posted_at.date().isoformat() == "2026-10-13"
    assert p.description and "<p>" not in p.description


def test_workable_board_urls():
    assert ats.board_url("workable_feed", "India") == "https://jobs.workable.com/search?location=India"
    assert ats.board_url("workable", "b7c6") == "https://jobs.workable.com/company/b7c6"


@respx.mock
async def test_amazon_adapter_pages_by_offset_and_keeps_descriptions_inline(client):
    respx.get("https://www.amazon.jobs/en/search.json", params__contains={"country": "IND", "offset": "0"}).respond(
        json=fixture("amazon_search.json")
    )
    respx.get("https://www.amazon.jobs/en/search.json", params__contains={"country": "IND", "offset": "100"}).respond(
        json={"hits": 2379, "jobs": []}
    )
    postings = await ats.list_jobs(client, "amazon", "IND")
    assert len(postings) == 2
    p = postings[0]
    assert (p.external_id, p.title[:13], p.location_raw, p.country) == (
        "10576634",
        "Data Engineer",
        "Bengaluru, Karnataka, IND",
        "IN",
    )
    assert p.url == "https://www.amazon.jobs/en/jobs/10576634/data-engineer-in-data-engineering-analytics"
    assert (
        p.posted_at.date().isoformat() == "2026-10-13"
        and "3+ years of data engineering experience" in p.description
        and "<br" not in p.description
    )


@respx.mock
async def test_google_adapter_reads_embedded_results_and_pages(client):
    respx.get(
        "https://www.google.com/about/careers/applications/jobs/results/",
        params__contains={"location": "India", "page": "1"},
    ).respond(text=(FIX / "google_results.html").read_text())
    respx.get(
        "https://www.google.com/about/careers/applications/jobs/results/",
        params__contains={"location": "India", "page": "2"},
    ).respond(
        text="<html>AF_initDataCallback({key: 'ds:1', hash: '2', data:[[], null, 286, 20], sideChannel: {}});</html>"
    )
    postings = await ats.list_jobs(client, "google", "India")
    assert [p.title[:24] for p in postings] == ["Senior Software Engineer", "Software Engineer, PhD, "]
    p = postings[1]
    assert (p.external_id, p.location_raw, p.country) == (
        "107018346561446598",
        "Bengaluru, Karnataka, India; Hyderabad, Telangana, India",
        "IN",
    )
    assert p.url == "https://www.google.com/about/careers/applications/jobs/results/107018346561446598"
    assert (
        p.posted_at.date().isoformat() == "2026-06-24"
        and "Minimum qualifications" in p.description
        and "<h3>" not in p.description
    )


def test_big_tech_board_urls():
    assert ats.board_url("amazon", "IND") == "https://www.amazon.jobs/en/search?country=IND"
    assert (
        ats.board_url("google", "India")
        == "https://www.google.com/about/careers/applications/jobs/results/?location=India"
    )
