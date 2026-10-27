import json

import pytest

from hungry_hunt.core.schemas import AssessmentOut
from hungry_hunt.scoring import gemini

RESUME = "Jane Doe. Skills: Python, FastAPI, PostgreSQL, Docker. Backend Engineer at Acme AI."
DESC = "About the role.\nWe need 2+ years of experience with Python and Go.\nYou will own services."


def out(**kw):
    base = dict(
        fit_score=80,
        verdict="apply",
        matched_skills=["Python", "FastAPI"],
        missing_skills=["Go"],
        min_years=2,
        max_years=None,
        years_evidence="We need 2+ years of experience with Python and Go.",
        is_engineering=True,
        is_senior=False,
        reason="Strong Python/FastAPI overlap; 2+ years bar is within reach.",
    )
    return AssessmentOut(**{**base, **kw})


def test_validate_keeps_verified_evidence_and_skills():
    v = gemini.validate(out(), DESC, RESUME, max_years_bar=2)
    assert v.years_evidence == "We need 2+ years of experience with Python and Go." and v.min_years == 2
    assert v.matched_skills == ["Python", "FastAPI"] and v.verdict == "apply"


def test_validate_nulls_unverifiable_evidence_and_years():
    v = gemini.validate(out(years_evidence="Requires 2 years", min_years=2), DESC, RESUME, max_years_bar=2)
    assert v.years_evidence is None and v.min_years is None and v.max_years is None


def test_validate_accepts_whitespace_normalized_evidence():
    v = gemini.validate(
        out(years_evidence="We need 2+ years  of experience with Python   and Go."), DESC, RESUME, max_years_bar=2
    )
    assert v.years_evidence is not None


def test_validate_drops_skills_not_in_resume_case_insensitive():
    v = gemini.validate(out(matched_skills=["python", "Kubernetes", "FastAPI"]), DESC, RESUME, max_years_bar=2)
    assert v.matched_skills == ["python", "FastAPI"]


class StubClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate(self, model, prompt, schema):
        self.calls.append((model, prompt, schema))
        if self.error:
            raise self.error
        return self.text


def test_assess_parses_structured_output_and_grounds_prompt():
    stub = StubClient(text=json.dumps(out().model_dump()))
    g = gemini.Gemini(api_key="k", model="m", client=stub)
    result = g.assess(RESUME, "0.9 yrs; SDE-1 backend; Bangalore", "Hevo", "mid", "SDE I", "Bangalore", DESC)
    assert result.fit_score == 80
    model, prompt, schema = stub.calls[0]
    assert model == "m" and schema is AssessmentOut
    assert RESUME in prompt and DESC in prompt and "Hevo" in prompt
    assert "only" in prompt.lower() and "exact sentence" in prompt.lower()


def test_assess_truncates_long_descriptions():
    stub = StubClient(text=json.dumps(out().model_dump()))
    gemini.Gemini(api_key="k", model="m", client=stub).assess(RESUME, "s", "C", "mid", "T", "L", "x" * 20000)
    assert len(stub.calls[0][1]) < 16000


@pytest.mark.parametrize("message", ["429 RESOURCE_EXHAUSTED: quota", "Error 429 Too Many Requests"])
def test_assess_maps_quota_errors(message):
    g = gemini.Gemini(api_key="k", model="m", client=StubClient(error=RuntimeError(message)))
    with pytest.raises(gemini.QuotaExhausted):
        g.assess(RESUME, "s", "C", "mid", "T", "L", DESC)


def test_assess_other_errors_propagate():
    g = gemini.Gemini(api_key="k", model="m", client=StubClient(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        g.assess(RESUME, "s", "C", "mid", "T", "L", DESC)


def test_extract_profile_parses():
    stub = StubClient(text=json.dumps({"skills": ["Python"], "years_experience": 0.9, "summary": "Backend"}))
    p = gemini.Gemini(api_key="k", model="m", client=stub).extract_profile(RESUME)
    assert p.skills == ["Python"] and p.years_experience == 0.9
