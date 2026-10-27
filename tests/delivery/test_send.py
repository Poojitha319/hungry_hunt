from datetime import UTC, datetime

from sqlalchemy import select

from hungry_hunt.config import Settings
from hungry_hunt.core.schemas import Coverage, Digest, DigestJob
from hungry_hunt.db import Base, make_engine, session_factory
from hungry_hunt.db.models import Company, Delivery, Job, Profile, Run
from hungry_hunt.delivery import send

NOW = datetime(2026, 10, 7, 1, 45, tzinfo=UTC)
SETTINGS = Settings(user_id="u", smtp_user="me@gmail.com", smtp_password="app-pass", digest_to="me@gmail.com")


def dj(job_id, **kw):
    base = dict(
        company="Hevo",
        tier="mid",
        title="SDE I",
        location_raw="Bangalore",
        posted_age_days=1,
        score=80,
        verdict="apply",
        reason="r",
        years_evidence=None,
        url=f"https://apply/{job_id}",
        review_url="https://r",
        is_new=True,
    )
    return DigestJob(job_id=job_id, **{**base, **kw})


def mk_digest(*job_ids, unscored=()):
    return Digest(
        digest_id="u:2026-10-07",
        date_ist=NOW.date(),
        new={"India": [dj(i) for i in job_ids], "Remote": [], "Stretch": []},
        carried={"India": [], "Remote": [], "Stretch": []},
        unscored=[dj(i, score=None, verdict=None) for i in unscored],
        coverage=Coverage(),
    )


class FakeMailer:
    def __init__(self, fail_times=0):
        self.fail_times, self.calls = fail_times, []

    def send(self, subject, html):
        self.calls.append((subject, html))
        if len(self.calls) <= self.fail_times:
            raise OSError("smtp down")


def seed_jobs(session, n):
    c = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo")
    session.add(c)
    session.flush()
    jobs = [
        Job(company_id=c.id, external_id=str(i), title="SDE I", url=f"https://apply/{i}", first_seen=NOW, last_seen=NOW)
        for i in range(n)
    ]
    session.add_all(jobs)
    session.flush()
    return [j.id for j in jobs]


def deliveries(session):
    return session.scalars(select(Delivery).order_by(Delivery.job_id)).all()


def test_send_records_ledger_then_confirms_on_success(session):
    ids = seed_jobs(session, 3)
    mailer = FakeMailer()
    ok = send.send(
        session,
        mk_digest(ids[0], ids[1], unscored=[ids[2]]),
        "Subj",
        "<p>hi</p>",
        SETTINGS,
        mailer,
        NOW,
        sleep=lambda s: None,
    )
    assert ok is True and mailer.calls == [("Subj", "<p>hi</p>")]
    rows = deliveries(session)
    assert [d.job_id for d in rows] == ids
    assert all(
        d.confirmed_at == NOW
        and d.sent_at == NOW
        and d.digest_id == "u:2026-10-07"
        and d.channel == "email"
        and d.error is None
        for d in rows
    )


def test_send_retries_then_leaves_unconfirmed_with_error(session):
    ids = seed_jobs(session, 1)
    mailer, sleeps = FakeMailer(fail_times=3), []
    ok = send.send(session, mk_digest(ids[0]), "S", "H", SETTINGS, mailer, NOW, sleep=sleeps.append)
    assert ok is False and len(mailer.calls) == 3 and sleeps == [10, 30]
    (d,) = deliveries(session)
    assert d.confirmed_at is None and "smtp down" in d.error


def test_send_succeeds_on_second_attempt(session):
    ids = seed_jobs(session, 1)
    ok = send.send(session, mk_digest(ids[0]), "S", "H", SETTINGS, FakeMailer(fail_times=1), NOW, sleep=lambda s: None)
    assert ok is True and deliveries(session)[0].confirmed_at == NOW


def test_send_is_noop_when_digest_already_confirmed_unless_forced(session):
    ids = seed_jobs(session, 1)
    send.send(session, mk_digest(ids[0]), "S", "H", SETTINGS, FakeMailer(), NOW, sleep=lambda s: None)
    second = FakeMailer()
    assert send.send(session, mk_digest(ids[0]), "S", "H", SETTINGS, second, NOW, sleep=lambda s: None) is True
    assert second.calls == [] and len(deliveries(session)) == 1
    forced = FakeMailer()
    send.send(session, mk_digest(ids[0]), "S", "H", SETTINGS, forced, NOW, force=True, sleep=lambda s: None)
    assert len(forced.calls) == 1 and len(deliveries(session)) == 2


def test_gmail_mailer_uses_smtp_ssl_with_app_password(monkeypatch):
    events = []

    class FakeSMTP:
        def __init__(self, host, port, context=None):
            events.append(("connect", host, port))
            assert context is not None and context.verify_mode == send.ssl.CERT_REQUIRED and context.check_hostname

        def __enter__(self):
            return self

        def __exit__(self, *a):
            events.append(("quit",))

        def login(self, user, password):
            events.append(("login", user, password))

        def send_message(self, msg):
            events.append(("send", msg["From"], msg["To"], msg["Subject"], msg.get_content_type()))

    monkeypatch.setattr(send.smtplib, "SMTP_SSL", FakeSMTP)
    send.GmailMailer(SETTINGS).send("Subj", "<p>hi</p>")
    assert events[0] == ("connect", "smtp.gmail.com", 465)
    assert events[1] == ("login", "me@gmail.com", "app-pass")
    assert events[2][:4] == ("send", "me@gmail.com", "me@gmail.com", "Subj") and events[2][4] in (
        "multipart/alternative",
        "text/html",
    )


def test_run_builds_renders_sends_and_records_run():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = session_factory(engine)
    with sf() as s:
        s.add(Profile(user_id="u", resume_version="v1", resume_text="r", updated_at=NOW))
        s.commit()
    mailer = FakeMailer()
    assert send.run(sf, SETTINGS, mailer, now=NOW, sleep=lambda s: None) is True
    subject, html = mailer.calls[0]
    assert "0 new" in subject and "No genuine openings today" in html
    with sf() as s:
        r = s.scalar(select(Run).where(Run.stage == "send"))
        assert r.stats["sent"] is True and r.stats["jobs"] == 0 and r.stats["digest_id"] == "u:2026-10-07T07"
