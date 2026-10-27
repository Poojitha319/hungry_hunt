"""Protocols the pipeline depends on, so adapters, the LLM and the mailer can be swapped in tests."""

from typing import Protocol

from hungry_hunt.core.schemas import AssessmentOut, OutreachOut, Posting, ProfileOut


class JobSource(Protocol):
    async def list_jobs(self, ats: str, slug: str) -> list[Posting]: ...
    async def description(self, ats: str, slug: str, external_id: str) -> str: ...


class Assessor(Protocol):
    def assess(
        self,
        resume_text: str,
        profile_summary: str,
        company: str,
        tier: str,
        title: str,
        location: str,
        description: str,
    ) -> AssessmentOut: ...
    def extract_profile(self, resume_text: str) -> ProfileOut: ...
    def draft_outreach(self, resume_text: str, company: str, title: str, description: str, url: str) -> OutreachOut: ...


class Mailer(Protocol):
    def send(self, subject: str, html: str) -> None: ...
