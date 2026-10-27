import json

import pytest

from hungry_hunt.core.schemas import AssessmentOut, Breakdown
from hungry_hunt.scoring import gemini

RESUME = "Jane. Backend Engineer at Acme (Nov 2025-present): Python, FastAPI, PostgreSQL, Docker in production. Courses: Kubernetes (Udemy)."
DESC = "Backend Engineer, Bengaluru, hybrid. 0-2 years of experience. Python, PostgreSQL, Kubernetes. Fintech."


def out(**kw):
    base = dict(
        fit_score=0,
        verdict="apply",
        matched_skills=["Python", "PostgreSQL"],
        missing_skills=["Kubernetes"],
        min_years=0,
        max_years=2,
        years_evidence="0-2 years of experience.",
        is_engineering=True,
        is_senior=False,
        reason="Good overlap.",
        breakdown=dict(
            skills_overlap=30,
            skills_reason="Python and PostgreSQL in production; Kubernetes only from a course",
            seniority_fit=22,
            seniority_reason="0-2 years matches 0.9 years",
            domain_fit=12,
            domain_reason="payments adjacent",
            practical_fit=10,
            practical_reason="Bengaluru hybrid; salary not stated",
        ),
    )
    return AssessmentOut(**{**base, **kw})


def test_total_is_computed_from_breakdown_not_trusted_from_the_model():
    v = gemini.validate(out(fit_score=99), DESC, RESUME, max_years_bar=2, rules_min=0)
    assert v.fit_score == 74 and v.breakdown.skills_overlap == 30


@pytest.mark.parametrize(
    "field,value",
    [("skills_overlap", 41), ("seniority_fit", 26), ("domain_fit", 21), ("practical_fit", 16), ("skills_overlap", -1)],
)
def test_breakdown_parts_are_bounded(field, value):
    with pytest.raises(ValueError):
        Breakdown(**{**out().breakdown.model_dump(), field: value})


def test_verdict_follows_the_computed_total():
    high = gemini.validate(out(verdict="skip"), DESC, RESUME, max_years_bar=2, rules_min=0)
    assert high.verdict == "apply"
    low = out()
    low.breakdown.skills_overlap, low.breakdown.domain_fit = 5, 2
    assert gemini.validate(low, DESC, RESUME, max_years_bar=2, rules_min=0).verdict == "skip"
    mid = out()
    mid.breakdown.skills_overlap = 15
    assert gemini.validate(mid, DESC, RESUME, max_years_bar=2, rules_min=0).verdict == "review"


def test_prompt_states_the_rubric_and_the_two_rules():
    captured = {}

    class Spy:
        def generate(self, model, prompt, schema):
            captured["prompt"], captured["schema"] = prompt, schema
            return json.dumps(out().model_dump())

    gemini.Gemini(api_key="k", model="m", client=Spy()).assess(
        RESUME, "summary", "Acme", "mid", "Backend Engineer", "Bengaluru", DESC
    )
    p = captured["prompt"].lower()
    assert captured["schema"] is AssessmentOut
    for s in (
        "skills overlap",
        "40",
        "seniority fit",
        "25",
        "domain fit",
        "20",
        "practical fit",
        "15",
        "course",
        "production",
        "salary",
    ):
        assert s in p, s


def test_scoring_version_is_part_of_the_assessment_key(session):
    from hungry_hunt.config import Settings
    from hungry_hunt.scoring import assess, rules
    from tests.scoring.test_assess import mk_company, mk_job, mk_profile

    prof = mk_profile(session)
    mk_job(session, mk_company(session, "c", kind="product"), "a")
    assess.run_rules(session, Settings(user_id="u"), prof, assess.datetime(2026, 10, 7, 2, 0, tzinfo=assess.UTC))
    from sqlalchemy import select

    from hungry_hunt.db.models import Assessment

    a = session.scalar(select(Assessment))
    assert f"|r{rules.RULES_VERSION}|s{assess.SCORING_VERSION}|b" in a.content_hash
