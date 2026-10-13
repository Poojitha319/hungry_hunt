from pathlib import Path

from sqlalchemy import select

from hunt import profile
from hunt.models import Profile
from hunt.schemas import ProfileOut

TEX = Path(__file__).parent / "fixtures" / "resume_sample.tex"


class FakeAssessor:
    def __init__(self):
        self.calls = 0

    def extract_profile(self, resume_text):
        self.calls += 1
        return ProfileOut(skills=["Python", "FastAPI"], years_experience=0.9, summary="Backend engineer")


def test_latex_to_text_keeps_content_drops_markup():
    text = profile.latex_to_text(TEX.read_text())
    assert "Jane Doe" in text and "FastAPI, SQLAlchemy, Alembic, Redis Streams" in text
    assert "Built a FastAPI service handling 2,000 requests/day with 99.9% uptime" in text
    assert "jane@example.com" in text and "github.com/jane" in text
    for junk in ("\\documentclass", "\\textbf", "\\resumeItem", "a comment that must not appear", "\\begin", "{", "}"):
        assert junk not in text


def test_latex_to_text_handles_raisebox_icons_and_control_spaces():
    text = profile.latex_to_text(r"\begin{document}\raisebox{-0.1\height}{\faGithub}\ \href{https://github.com/j}{j} \\ next\end{document}")
    assert "\\" not in text and "height" not in text and "-0.1" not in text
    assert text.startswith("j")


def test_ensure_profile_extracts_once_and_skips_when_unchanged(session):
    llm = FakeAssessor()
    p1 = profile.ensure_profile(session, "u", llm, TEX)
    p2 = profile.ensure_profile(session, "u", llm, TEX)
    assert llm.calls == 1
    assert p1.resume_version == p2.resume_version and len(p1.resume_version) == 8
    assert p1.skills == ["Python", "FastAPI"] and p1.years_experience == 0.9
    assert session.scalar(select(Profile).where(Profile.user_id == "u")).resume_text.startswith("Jane Doe")


def test_ensure_profile_re_extracts_when_resume_changes(session, tmp_path):
    llm = FakeAssessor()
    tex = tmp_path / "r.tex"
    tex.write_text(TEX.read_text())
    v1 = profile.ensure_profile(session, "u", llm, tex).resume_version
    tex.write_text(TEX.read_text().replace("Redis Streams", "Kafka"))
    v2 = profile.ensure_profile(session, "u", llm, tex).resume_version
    assert v1 != v2 and llm.calls == 2
