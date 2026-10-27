from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from hungry_hunt.config import Settings
from hungry_hunt.db.models import Application, Company, Job, TrackedMail
from hungry_hunt.tracking import track

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=UTC)


ATS_AUTH = "mx.google.com; dkim=pass header.i=@hire.lever.co; spf=pass; arc=pass (i=1 spf=pass dkim=pass)"
GMAIL_AUTH = (
    "mx.google.com; dkim=pass header.i=@gmail.com header.s=20230601; spf=pass smtp.mailfrom=candidate.apps@gmail.com"
)


def mail(
    subject,
    sender="Hevo Data <no-reply@hire.lever.co>",
    snippet="",
    mid="<m1@x>",
    forwarded="candidate.apps@gmail.com candidate@gmail.com",
    date=NOW,
    auth=ATS_AUTH,
):
    if auth is ATS_AUTH:
        domain = sender.rsplit("@", 1)[-1].rstrip(">").lower()
        auth = f"mx.google.com; dkim=pass header.i=@{domain}; spf=pass; arc=pass"
    return track.Mail(
        message_id=mid,
        sender=sender,
        subject=subject,
        date=date,
        snippet=snippet,
        forwarded_for=forwarded,
        auth_results=auth,
    )


@pytest.mark.parametrize(
    "subject,sender,snippet,status,company",
    [
        ("Thank you for applying to Hevo Data", "Hevo Data <no-reply@hire.lever.co>", "", "applied", "Hevo Data"),
        (
            "Your application to Rubrik",
            "Rubrik <no-reply@us.greenhouse-mail.io>",
            "We received your application for Software Engineer - SaaS O365.",
            "applied",
            "Rubrik",
        ),
        ("Application received: Groww", "careers@groww.in", "Thanks for applying!", "applied", "Groww"),
        (
            "Hevo Data Hiring Challenge - Invitation",
            "DoSelect <no-reply@doselect.com>",
            "You have been invited to take the test",
            "test",
            "Hevo Data",
        ),
        ("Online Assessment for SDE I at Rubrik", "HackerRank <noreply@hackerrank.com>", "", "test", "Rubrik"),
        (
            "Interview with Groww - Software Development Engineer I",
            "Groww <scheduling@ashbyhq.com>",
            "Please pick a slot",
            "interview",
            "Groww",
        ),
        ("Invitation: Phone screen with Atlan", "Atlan <no-reply@calendly.com>", "", "interview", "Atlan"),
        (
            "Update on your application to Coinbase",
            "Coinbase <no-reply@hire.lever.co>",
            "Unfortunately we will not be moving forward at this time.",
            "rejected",
            "Coinbase",
        ),
        (
            "Your application to Elastic",
            "Elastic <no-reply@greenhouse.io>",
            "After careful consideration we have decided to pursue other candidates.",
            "rejected",
            "Elastic",
        ),
        ("Weekly newsletter", "news@somecompany.com", "Top stories", None, None),
    ],
)
def test_classify(subject, sender, snippet, status, company):
    event = track.classify(mail(subject, sender, snippet))
    assert (event.status, event.company_hint) == (status, company)


def test_classify_extracts_title_hint():
    e = track.classify(
        mail(
            "Your application to Rubrik",
            snippet="Thank you for applying to the Software Engineer - SaaS O365 position at Rubrik.",
        )
    )
    assert e.title_hint and "Software Engineer - SaaS O365" in e.title_hint


def seed(session):
    hevo = Company(user_id="u", ats="lever", slug="hevodata", name="Hevo Data")
    rubrik = Company(user_id="u", ats="greenhouse", slug="rubrik", name="Rubrik")
    session.add_all([hevo, rubrik])
    session.flush()
    j1 = Job(company_id=hevo.id, external_id="1", title="SDE I", url="u1", first_seen=NOW, last_seen=NOW)
    j2 = Job(
        company_id=hevo.id,
        external_id="2",
        title="Associate Software Development Engineer (SDE)",
        url="u2",
        first_seen=NOW,
        last_seen=NOW,
    )
    j3 = Job(
        company_id=rubrik.id,
        external_id="3",
        title="Software Engineer - SaaS O365",
        url="u3",
        first_seen=NOW,
        last_seen=NOW,
    )
    session.add_all([j1, j2, j3])
    session.flush()
    return hevo, rubrik, j1, j2, j3


def test_apply_events_links_company_and_job_and_dedupes(session):
    _hevo, _rubrik, j1, _j2, j3 = seed(session)
    mails = [
        mail("Thank you for applying to Hevo Data", snippet="for the SDE I position", mid="<a>"),
        mail(
            "Your application to Rubrik", "Rubrik <no-reply@greenhouse.io>", "Software Engineer - SaaS O365", mid="<b>"
        ),
    ]
    stats = track.apply_events(session, Settings(user_id="u"), mails, NOW)
    assert (stats.seen, stats.classified, stats.linked_jobs) == (2, 2, 2)
    apps = {a.job_id: a for a in session.scalars(select(Application))}
    assert apps[j1.id].status == "applied" and apps[j1.id].applied_at == NOW and apps[j1.id].channel == "email"
    assert apps[j3.id].status == "applied"
    assert track.apply_events(session, Settings(user_id="u"), mails, NOW).seen == 0
    assert session.scalar(select(TrackedMail).where(TrackedMail.message_id == "<a>")).status == "applied"


def test_apply_events_progresses_status_but_never_downgrades(session):
    _hevo, _rubrik, j1, _j2, _j3 = seed(session)
    s = Settings(user_id="u")
    track.apply_events(session, s, [mail("Thank you for applying to Hevo Data", snippet="SDE I", mid="<1>")], NOW)
    track.apply_events(
        session,
        s,
        [
            mail(
                "Hevo Data Hiring Challenge",
                "DoSelect <no-reply@doselect.com>",
                "SDE I test invite",
                mid="<2>",
                date=NOW + timedelta(days=1),
            )
        ],
        NOW,
    )
    assert session.scalar(select(Application).where(Application.job_id == j1.id)).status == "test"
    track.apply_events(
        session,
        s,
        [mail("Thank you for applying to Hevo Data", snippet="SDE I", mid="<3>", date=NOW + timedelta(days=2))],
        NOW,
    )
    assert session.scalar(select(Application).where(Application.job_id == j1.id)).status == "test"
    track.apply_events(
        session,
        s,
        [
            mail(
                "Update on your application to Hevo Data",
                snippet="unfortunately we will not be moving forward",
                mid="<4>",
                date=NOW + timedelta(days=3),
            )
        ],
        NOW,
    )
    assert session.scalar(select(Application).where(Application.job_id == j1.id)).status == "rejected"


def test_apply_events_keeps_unmatched_events_for_pipeline_counts(session):
    seed(session)
    stats = track.apply_events(
        session,
        Settings(user_id="u"),
        [mail("Thank you for applying to Juspay", "Juspay <careers@juspay.in>", mid="<j>")],
        NOW,
    )
    assert (stats.classified, stats.linked_jobs) == (1, 0)
    row = session.scalar(select(TrackedMail).where(TrackedMail.message_id == "<j>"))
    assert (row.company_hint, row.status, row.job_id) == ("Juspay", "applied", None)


def test_apply_events_ignores_mail_not_forwarded_from_the_application_mailbox(session):
    seed(session)
    stats = track.apply_events(
        session, Settings(user_id="u"), [mail("Thank you for applying to Hevo Data", forwarded=None, mid="<nf>")], NOW
    )
    assert stats.seen == 1 and stats.classified == 0
    assert session.scalar(select(TrackedMail)) is None


def test_pipeline_counts(session):
    seed(session)
    s = Settings(user_id="u")
    track.apply_events(
        session,
        s,
        [
            mail("Thank you for applying to Hevo Data", snippet="SDE I", mid="<1>"),
            mail("Your application to Rubrik", "Rubrik <x@greenhouse.io>", "Software Engineer - SaaS O365", mid="<2>"),
            mail("Online Assessment for SDE I at Rubrik", "HackerRank <noreply@hackerrank.com>", mid="<3>"),
            mail(
                "Update on your application to Coinbase",
                "Coinbase <no-reply@hire.lever.co>",
                "unfortunately",
                mid="<4>",
                date=NOW - timedelta(days=20),
            ),
        ],
        NOW,
    )
    counts = track.pipeline_counts(session, "u", NOW)
    assert counts["week"] == {"applied": 2, "test": 1, "interview": 0, "rejected": 0}
    assert counts["total"] == {"applied": 2, "test": 1, "interview": 0, "rejected": 1}


def test_imap_mailbox_reads_readonly_and_parses_forwarded_headers(monkeypatch):
    raw = (
        b"From: Hevo Data <no-reply@hire.lever.co>\r\nSubject: Thank you for applying to Hevo Data\r\n"
        b"Date: Wed, 08 Oct 2026 07:30:00 +0530\r\nMessage-ID: <abc@lever>\r\n"
        b"Authentication-Results: mx.google.com; dkim=pass header.i=@hire.lever.co; arc=pass\r\n"
        b"X-Forwarded-For: candidate.apps@gmail.com candidate@gmail.com\r\n\r\n"
    )
    body = b"Hi Asha,\r\nThank you for applying to the SDE I position at Hevo Data.\r\n"
    events = []

    class FakeIMAP:
        def __init__(self, host, port, ssl_context=None):
            events.append(("connect", host, port, ssl_context is not None))

        def login(self, user, password):
            events.append(("login", user, password))

        def select(self, mailbox, readonly=False):
            events.append(("select", mailbox, readonly))
            return "OK", [b"3"]

        def search(self, charset, criteria):
            events.append(("search", criteria))
            return "OK", [b"1 2"]

        def fetch(self, ids, parts):
            events.append(("fetch", ids, parts))
            return "OK", [(b"1 (BODY[HEADER.FIELDS (...)] {0}", raw), b")", (b"1 (BODY[TEXT] {0}", body), b")"]

        def logout(self):
            events.append(("logout",))

    monkeypatch.setattr(track.imaplib, "IMAP4_SSL", FakeIMAP)
    settings = Settings(smtp_user="candidate@gmail.com", smtp_password="app-pass")
    mails = track.ImapMailbox(settings).fetch_recent(NOW - timedelta(days=14))
    assert events[0] == ("connect", "imap.gmail.com", 993, True)
    assert events[1] == ("login", "candidate@gmail.com", "app-pass")
    assert events[2] == ("select", "INBOX", True)
    assert "SINCE" in events[3][1] and "24-Sep-2026" in events[3][1]
    assert all("PEEK" in e[2] for e in events if e[0] == "fetch")
    assert len(mails) == 1
    m = mails[0]
    assert (m.message_id, m.subject, m.sender) == (
        "<abc@lever>",
        "Thank you for applying to Hevo Data",
        "Hevo Data <no-reply@hire.lever.co>",
    )
    assert m.forwarded_for and "candidate.apps" in m.forwarded_for
    assert m.auth_results and "dkim=pass" in m.auth_results
    assert any("AUTHENTICATION-RESULTS" in e[2].upper() for e in events if e[0] == "fetch")
    assert "SDE I position" in m.snippet and m.date.tzinfo is not None
    assert events[-1] == ("logout",)


def test_manual_forward_from_application_mailbox_counts_and_fwd_prefix_is_ignored(session):
    _hevo, _rubrik, _j1, _j2, _j3 = seed(session)
    s = Settings(user_id="u", digest_to="candidate.apps@gmail.com")
    m = mail(
        "Fwd: Thank you for applying to Hevo Data",
        sender="Asha Rao <candidate.apps@gmail.com>",
        snippet="---------- Forwarded message --------- From: Hevo Data <no-reply@hire.lever.co> ... for the SDE I position",
        forwarded=None,
        mid="<fwd>",
        auth=GMAIL_AUTH,
    )
    stats = track.apply_events(session, s, [m], NOW)
    assert (stats.classified, stats.linked_jobs) == (1, 1)
    assert track.classify(m).company_hint == "Hevo Data"


@pytest.mark.parametrize(
    "sender,forwarded,auth,accepted",
    [
        ("Hevo Data <no-reply@hire.lever.co>", "sai poo", ATS_AUTH, True),
        ("Hevo Data <no-reply@hire.lever.co>", "sai poo", None, False),
        ("Hevo Data <no-reply@hire.lever.co>", "sai poo", "mx.google.com; dkim=fail; spf=fail", False),
        ("Hevo Data <attacker@evil.example>", "sai poo", "mx.google.com; dkim=pass header.i=@evil.example", False),
        ("careers@groww.in", "sai poo", "mx.google.com; dkim=pass header.i=@groww.in; arc=pass", True),
        ("careers@groww.in", "sai poo", "mx.google.com; dkim=pass header.i=@groww.in", False),
        ("Asha Rao <candidate.apps@gmail.com>", None, GMAIL_AUTH, True),
        (
            "Asha Rao <candidate.apps@gmail.com>",
            None,
            "mx.google.com; dkim=pass header.i=@evil.example",
            False,
        ),
        ("Asha Rao <candidate.apps@gmail.com>", None, None, False),
    ],
)
def test_only_authenticated_mail_from_trusted_senders_is_tracked(session, sender, forwarded, auth, accepted):
    seed(session)
    s = Settings(user_id="u", digest_to="candidate.apps@gmail.com")
    stats = track.apply_events(
        session,
        s,
        [mail("Thank you for applying to Hevo Data", sender=sender, forwarded=forwarded, auth=auth, mid="<t>")],
        NOW,
    )
    assert (stats.classified == 1) is accepted


@pytest.mark.parametrize(
    "sender,forwarded,auth,accepted",
    [
        # attacker-supplied Authentication-Results header (wrong authserv-id) is ignored
        (
            "Hevo Data <no-reply@hire.lever.co>",
            "sai poo",
            "evil.example; dkim=pass header.i=@hire.lever.co; arc=pass",
            False,
        ),
        # Gmail-stamped, but the DKIM pass is for a different domain than From
        (
            "Hevo Data <no-reply@hire.lever.co>",
            "sai poo",
            "mx.google.com; dkim=pass header.i=@evil.example; arc=pass",
            False,
        ),
        # dmarc=pass counts as alignment
        (
            "Hevo Data <no-reply@hire.lever.co>",
            "sai poo",
            "mx.google.com; dmarc=pass header.from=hire.lever.co; arc=pass",
            True,
        ),
        # organisational-domain DKIM (lever.co) aligns with a subdomain From (hire.lever.co)
        ("Hevo Data <no-reply@hire.lever.co>", "sai poo", "mx.google.com; dkim=pass header.d=lever.co", True),
        # two headers: attacker's first, Gmail's second — only Gmail's counts
        (
            "Hevo Data <no-reply@hire.lever.co>",
            "sai poo",
            "evil.example; dkim=pass header.i=@hire.lever.co mx.google.com; dkim=fail; spf=fail",
            False,
        ),
    ],
)
def test_only_gmail_stamped_aligned_authentication_counts(session, sender, forwarded, auth, accepted):
    seed(session)
    s = Settings(user_id="u", digest_to="candidate.apps@gmail.com")
    stats = track.apply_events(
        session,
        s,
        [mail("Thank you for applying to Hevo Data", sender=sender, forwarded=forwarded, auth=auth, mid="<g>")],
        NOW,
    )
    assert (stats.classified == 1) is accepted


@pytest.mark.parametrize(
    "sender,auth,accepted",
    [
        (
            "Hevo Data <no-reply@hire.lever.co>",
            "mx.google.com.evil.example; dkim=pass header.i=@hire.lever.co; arc=pass",
            False,
        ),
        ("Hevo Data <no-reply@hire.lever.co>", "MX.GOOGLE.COM; dkim=pass header.i=@hire.lever.co", True),
        ("no-reply@hire.lever.co, attacker@evil.example", "mx.google.com; dkim=pass header.i=@hire.lever.co", False),
        ('"no-reply@hire.lever.co" <attacker@evil.example>', "mx.google.com; dkim=pass header.i=@hire.lever.co", False),
    ],
)
def test_authserv_id_must_be_exact_and_from_must_be_a_single_address(session, sender, auth, accepted):
    seed(session)
    s = Settings(user_id="u", digest_to="candidate.apps@gmail.com")
    stats = track.apply_events(
        session, s, [mail("Thank you for applying to Hevo Data", sender=sender, auth=auth, mid="<pd>")], NOW
    )
    assert (stats.classified == 1) is accepted
