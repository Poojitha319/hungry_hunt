"""Gemini client with the scoring rubric, strict JSON validation and quota detection."""

import re

from pydantic import BaseModel

from hungry_hunt.core.schemas import AssessmentOut, OutreachOut, ProfileOut

MAX_DESCRIPTION = 12000
QUOTA = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|quota", re.IGNORECASE)
WS = re.compile(r"\s+")

ASSESS_RULES = """You are screening one job posting for one specific candidate. Score it out of 100 in four weighted parts and fill
`breakdown` with each part and a one-line reason. Only production evidence counts.
- skills overlap (0-40): skills the posting asks for that the resume shows used in real work. A tool the resume lists only from a
  course, certificate or tutorial counts ZERO. A tool with no evidence counts zero.
- seniority fit (0-25): how well the candidate's actual years and level match what the posting asks. If the posting does not
  state seniority or years, score LOW (at most 10) rather than guessing.
- domain fit (0-20): overlap between the posting's domain (fintech, data infra, AI, ...) and what the resume shows.
- practical fit (0-15): location, remote policy and salary against the candidate's situation. If salary is not stated, score at
  most 8 here rather than assuming.
Facts about the candidate come ONLY from the resume text below; never assume skills or experience it does not state.
- matched_skills: only skills that appear literally in the resume AND are asked for by the posting.
- missing_skills: skills the posting asks for that the resume does not mention.
- years_evidence: the exact sentence from the posting that states the experience requirement, copied verbatim, or null if none.
- min_years / max_years: the numbers from that sentence, or null.
- Never infer seniority from the title alone; read the posting.
- fit_score: the sum of the four parts. verdict: apply if the sum is 70 or more and the role is winnable at the candidate's years;
  review for 45-69 or unclear eligibility; skip otherwise.
- reason: one sentence naming the decisive factor."""

PROFILE_RULES = """Extract the candidate's profile from the resume text. skills: the distinct technical skills literally named
(languages, frameworks, databases, cloud, tools). years_experience: total full-time professional experience in years as a
decimal (internships count half). summary: one sentence."""


OUTREACH_RULES = """Write a short outreach for a job application the candidate has ALREADY submitted. The reader is an engineer or
recruiter at the company. Use ONLY facts stated in the resume text; never invent experience, numbers, employers, tools or names.
- subject: at most 8 words, plain.
- note: 70-120 words, first person, specific to this posting (name the company and role), one concrete thing from the resume that
  matches the posting, one clear ask (5 minutes of advice or a pointer to the hiring manager). No flattery, no buzzwords.
- referral_ask: 2-3 sentences asking politely for a referral, mentioning the application is already in.
- who_to_contact: one sentence on who at this company to send it to (role, not a name) and where to find them."""


class QuotaExhausted(Exception):
    pass


class GenaiClient:
    def __init__(self, api_key: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)

    def generate(self, model: str, prompt: str, schema: type[BaseModel]) -> str:
        from google.genai import types

        r = self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema, temperature=0
            ),
        )
        return r.text or ""


class Gemini:
    def __init__(self, api_key: str, model: str, client=None):
        self.model = model
        self.client = client or GenaiClient(api_key)

    def _call(self, prompt: str, schema: type[BaseModel]):
        try:
            text = self.client.generate(self.model, prompt, schema)
        except Exception as e:
            if QUOTA.search(str(e)):
                raise QuotaExhausted(str(e)) from e
            raise
        return schema.model_validate_json(text)

    def assess(
        self,
        resume_text: str,
        profile_summary: str,
        company: str,
        tier: str,
        title: str,
        location: str,
        description: str,
    ) -> AssessmentOut:
        prompt = (
            f"{ASSESS_RULES}\n\n## Candidate\n{profile_summary}\n\n## Resume\n{resume_text}\n\n"
            f"## Posting\nCompany: {company} ({tier})\nTitle: {title}\nLocation: {location}\n\n{description[:MAX_DESCRIPTION]}"
        )
        return self._call(prompt, AssessmentOut)

    def draft_outreach(self, resume_text: str, company: str, title: str, description: str, url: str) -> OutreachOut:
        prompt = (
            f"{OUTREACH_RULES}\n\n## Resume\n{resume_text}\n\n## Posting\nCompany: {company}\nTitle: {title}\nURL: {url}\n\n"
            f"{description[:MAX_DESCRIPTION]}"
        )
        return self._call(prompt, OutreachOut)

    def extract_profile(self, resume_text: str) -> ProfileOut:
        return self._call(f"{PROFILE_RULES}\n\n## Resume\n{resume_text}", ProfileOut)


def validate(
    out: AssessmentOut, description: str, resume_text: str, max_years_bar: int, rules_min: float | None = None
) -> AssessmentOut:
    if out.years_evidence is not None and WS.sub(" ", out.years_evidence).strip() not in WS.sub(" ", description):
        out.years_evidence, out.min_years, out.max_years = None, None, None
    out.matched_skills = [
        s
        for s in out.matched_skills
        if re.search(r"(?<![\w+#.])" + re.escape(s) + r"(?![\w+#])", resume_text, re.IGNORECASE)
    ]
    out.reason = out.reason[:200]
    if out.breakdown is not None:
        out.fit_score = out.breakdown.total
        out.verdict = "apply" if out.fit_score >= 70 else "review" if out.fit_score >= 45 else "skip"
    if rules_min is None and out.min_years is not None and out.min_years > max_years_bar:
        out.verdict = "skip"
    return out
