from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from hungry_hunt.cli import main
from hungry_hunt.config import Settings
from hungry_hunt.core.http import BoardError
from hungry_hunt.core.schemas import AssessmentOut, Posting, ProfileOut
from hungry_hunt.db import Base, make_engine, session_factory
from hungry_hunt.db.models import Company, Delivery, Job, Profile, Run
from hungry_hunt.discovery import seeds

NOW = datetime(2026, 10, 7, 1, 30, tzinfo=UTC)
TEX = Path(__file__).parent.parent / "fixtures" / "resume_sample.tex"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/hunt.db",
        user_id="u",
        smtp_user="a@b",
        smtp_password="p",
        digest_to="a@b",
        review_token="t",
        resume_tex=str(TEX),
        assess_interval_s=0,
    )
    Base.metadata.create_all(make_engine(settings.database_url))
    return settings


def sf(settings):
    return session_factory(make_engine(settings.database_url))


class FakeSource:
    def __init__(self, fail=False):
        self.fail = fail

    async def list_jobs(self, ats, slug):
        if self.fail:
            raise BoardError("down", status=500)
        return [
            Posting(
                external_id=f"{slug}-1",
                title="SDE I",
                location_raw="Bangalore, India",
                url=f"https://apply/{slug}",
                description="0-2 years of experience with Python.",
            )
        ]

    async def description(self, ats, slug, external_id):
        return ""


class FakeLLM:
    def extract_profile(self, text):
        return ProfileOut(skills=["Python"], years_experience=0.9, summary="s")

    def assess(self, *a, **k):
        return AssessmentOut(
            fit_score=85,
            verdict="apply",
            matched_skills=["Python"],
            missing_skills=[],
            min_years=None,
            max_years=None,
            years_evidence=None,
            is_engineering=True,
            is_senior=False,
            reason="fits",
        )


class FakeMailer:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def send(self, subject, html):
        self.calls.append(subject)
        if self.fail:
            raise OSError("smtp")


def test_discover_seeds_is_idempotent(env):
    assert main(["discover", "--seeds"], settings=env) == 0
    assert main(["discover", "--seeds"], settings=env) == 0
    with sf(env)() as s:
        assert s.scalar(select(func.count()).select_from(Company)) == len(seeds.SEEDS)


def test_discover_add_board(env):
    assert (
        main(
            ["discover", "add", "https://jobs.lever.co/cred", "--status", "target", "--notes", "fintech"], settings=env
        )
        == 0
    )
    with sf(env)() as s:
        c = s.scalar(select(Company).where(Company.slug == "cred"))
        assert (c.ats, c.status, c.notes) == ("lever", "target", "fintech")


def test_discover_slugs_file_loads_prototype_harvest(env, tmp_path):
    f = tmp_path / "slugs.json"
    f.write_text('{"greenhouse": ["acme"], "lever": ["hevodata"], "ashby": []}')
    assert main(["discover", "--slugs", str(f)], settings=env) == 0
    with sf(env)() as s:
        assert {(c.ats, c.slug) for c in s.scalars(select(Company))} == {("greenhouse", "acme"), ("lever", "hevodata")}


def test_profile_extracts_from_tex(env):
    assert main(["profile"], settings=env, llm=FakeLLM()) == 0
    with sf(env)() as s:
        p = s.get(Profile, "u")
        assert p.skills == ["Python"] and "Jane Doe" in p.resume_text


def test_fetch_only_filters_boards(env):
    main(["discover", "--seeds"], settings=env)
    assert main(["fetch", "--only", "lever:hevodata"], settings=env, source=FakeSource(), now=NOW) == 0
    with sf(env)() as s:
        assert [j.external_id for j in s.scalars(select(Job))] == ["hevodata-1"]


def test_assess_without_profile_fails_loudly(env, caplog):
    assert main(["assess"], settings=env, llm=FakeLLM()) == 1
    assert any("profile" in r.getMessage().lower() for r in caplog.records if r.levelname == "ERROR")


def test_digest_preview_writes_html_without_deliveries(env, tmp_path):
    main(["profile"], settings=env, llm=FakeLLM())
    out = tmp_path / "digest.html"
    assert main(["digest", "--preview", str(out)], settings=env, now=NOW) == 0
    assert "Hungry Hunt" in out.read_text()
    with sf(env)() as s:
        assert s.scalar(select(func.count()).select_from(Delivery)) == 0


def test_run_end_to_end_sends_and_exits_zero(env):
    main(["discover", "add", "lever:hevodata"], settings=env)
    main(["profile"], settings=env, llm=FakeLLM())
    mailer = FakeMailer()
    assert (
        main(["run"], settings=env, source=FakeSource(), llm=FakeLLM(), mailer=mailer, mailbox=FakeMailbox(), now=NOW)
        == 0
    )
    assert len(mailer.calls) == 1 and "1 new" in mailer.calls[0]
    with sf(env)() as s:
        (d,) = s.scalars(select(Delivery)).all()
        assert d.confirmed_at is not None
        assert {r.stage for r in s.scalars(select(Run))} >= {"fetch", "assess", "send", "prune"}


def test_prune_subcommand_records_run(env):
    assert main(["prune"], settings=env, now=NOW) == 0
    with sf(env)() as s:
        assert s.scalar(select(Run).where(Run.stage == "prune")).stats["jobs_deleted"] == 0


def test_run_exit_2_when_send_fails(env):
    main(["profile"], settings=env, llm=FakeLLM())
    assert (
        main(
            ["run"],
            settings=env,
            source=FakeSource(),
            llm=FakeLLM(),
            mailer=FakeMailer(fail=True),
            mailbox=FakeMailbox(),
            now=NOW,
            sleep=lambda s: None,
        )
        == 2
    )


def test_run_exit_1_when_a_stage_raises_but_digest_still_goes_out(env, caplog):
    main(["discover", "add", "lever:hevodata"], settings=env)
    mailer = FakeMailer()
    assert (
        main(["run"], settings=env, source=FakeSource(), llm=FakeLLM(), mailer=mailer, mailbox=FakeMailbox(), now=NOW)
        == 1
    )
    assert len(mailer.calls) == 1
    assert any("profile" in r.getMessage().lower() for r in caplog.records if r.levelname == "ERROR")


class FakeMailbox:
    def __init__(self, mails=()):
        self.mails, self.calls = list(mails), []

    def fetch_recent(self, since):
        self.calls.append(since)
        return self.mails


def test_track_subcommand_records_run_and_applications(env):
    from hungry_hunt.tracking.track import Mail

    main(["discover", "add", "lever:hevodata"], settings=env)
    main(["fetch", "--only", "lever:hevodata"], settings=env, source=FakeSource(), now=NOW)
    mb = FakeMailbox(
        [
            Mail(
                "<m1>",
                "Hevo Data <no-reply@hire.lever.co>",
                "Thank you for applying to Hevo Data",
                NOW,
                "for the SDE I position",
                "candidate.apps@gmail.com candidate@gmail.com",
                "mx.google.com; dkim=pass header.i=@hire.lever.co; arc=pass",
            )
        ]
    )
    assert main(["track"], settings=env, mailbox=mb, now=NOW) == 0
    with sf(env)() as s:
        from hungry_hunt.db.models import Application

        assert s.scalar(select(Application)).status == "applied"
        assert s.scalar(select(Run).where(Run.stage == "track")).stats["linked_jobs"] == 1


def test_run_tracks_before_digest_so_applied_jobs_drop_out(env):
    from hungry_hunt.tracking.track import Mail

    main(["discover", "add", "lever:hevodata"], settings=env)
    main(["profile"], settings=env, llm=FakeLLM())
    mb = FakeMailbox(
        [
            Mail(
                "<m1>",
                "Hevo Data <no-reply@hire.lever.co>",
                "Thank you for applying to Hevo Data",
                NOW,
                "for the SDE I position",
                "candidate.apps@gmail.com candidate@gmail.com",
                "mx.google.com; dkim=pass header.i=@hire.lever.co; arc=pass",
            )
        ]
    )
    mailer = FakeMailer()
    assert main(["run"], settings=env, source=FakeSource(), llm=FakeLLM(), mailer=mailer, mailbox=mb, now=NOW) == 0
    assert "0 new" in mailer.calls[0]
    with sf(env)() as s:
        assert [r.stage for r in s.scalars(select(Run).order_by(Run.id))][:3] == ["fetch", "track", "assess"]


def test_profile_flags_set_preferred_and_excluded_titles_and_survive_reextraction(env):
    assert main(["profile", "--targets", "AI engineer, LLM ", "--exclude", "Android"], settings=env, llm=FakeLLM()) == 0
    with sf(env)() as s:
        p = s.get(Profile, "u")
        assert p.target_titles == ["AI engineer", "LLM"] and p.excluded_titles == ["Android"]
    assert main(["profile"], settings=env, llm=FakeLLM()) == 0
    with sf(env)() as s:
        p = s.get(Profile, "u")
        assert p.target_titles == ["AI engineer", "LLM"]


def test_profile_syncs_the_years_bar_from_settings(env):
    assert main(["profile"], settings=env.model_copy(update={"max_years_bar": 1}), llm=FakeLLM()) == 0
    with sf(env)() as s:
        assert s.get(Profile, "u").max_years_bar == 1


def test_run_daily_continues_after_fetch_failure(env, monkeypatch):
    from hungry_hunt.pipeline import fetch as fetch_stage
    from hungry_hunt.pipeline.run import Pipeline, run_daily
    from hungry_hunt.scoring import assess as assess_stage

    async def boom(*a, **k):
        raise RuntimeError("boom")

    called = []
    monkeypatch.setattr(fetch_stage, "fetch_all", boom)
    monkeypatch.setattr(assess_stage, "run", lambda *a, **k: called.append(1) or assess_stage.ScoreStats(scored=3))
    mailer = FakeMailer()
    summary = run_daily(
        Pipeline(sf(env), env, now=NOW, source=FakeSource(), llm=FakeLLM(), mailer=mailer, mailbox=FakeMailbox())
    )
    assert called == [1]
    assert summary.errors == ["fetch: boom"]
    assert summary.assess_scored == 3
    assert summary.sent is True
    assert summary.exit_code == 1


def test_run_logs_stage_summary(env, caplog):
    import logging

    from hungry_hunt.pipeline.run import Pipeline, run_daily

    main(["discover", "add", "lever:hevodata"], settings=env)
    main(["profile"], settings=env, llm=FakeLLM())
    with caplog.at_level(logging.INFO, logger="hungry_hunt"):
        run_daily(
            Pipeline(
                sf(env), env, now=NOW, source=FakeSource(), llm=FakeLLM(), mailer=FakeMailer(), mailbox=FakeMailbox()
            )
        )
    messages = [r.getMessage() for r in caplog.records if r.name.startswith("hungry_hunt")]
    assert any(m.startswith("fetch: ") for m in messages)
    assert any(m.startswith("assess: ") for m in messages)


def test_settings_have_logging_fields(env):
    assert env.log_level == "INFO"
    assert env.log_format == "plain"
