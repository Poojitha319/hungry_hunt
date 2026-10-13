import smtplib
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt import digest as digest_stage
from hunt.config import Settings
from hunt.models import Delivery, Run
from hunt.ports import Mailer
from hunt.schemas import Digest

RETRY_BACKOFF = (10, 30)


class GmailMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, subject: str, html: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.settings.smtp_user, self.settings.digest_to, subject
        msg.set_content("This digest is HTML; open it in an HTML-capable mail client.")
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
            smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(msg)


def _jobs(d: Digest) -> list[int]:
    return [j.job_id for group in (d.new, d.carried) for jobs in group.values() for j in jobs] + [j.job_id for j in d.unscored]


def send(session: Session, d: Digest, subject: str, html: str, settings: Settings, mailer: Mailer, now: datetime, *,
         force: bool = False, sleep: Callable[[float], None] = time.sleep) -> bool:
    already = session.scalar(select(Delivery).where(Delivery.user_id == settings.user_id, Delivery.digest_id == d.digest_id,
                                                    Delivery.confirmed_at.isnot(None)))
    if already and not force:
        return True
    rows = [Delivery(job_id=jid, user_id=settings.user_id, channel="email", digest_id=d.digest_id, sent_at=now) for jid in _jobs(d)]
    session.add_all(rows)
    session.commit()
    error = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        try:
            mailer.send(subject, html)
            error = None
            break
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            if attempt < len(RETRY_BACKOFF):
                sleep(RETRY_BACKOFF[attempt])
    for r in rows:
        if error is None:
            r.confirmed_at = now
        else:
            r.error = error
    session.commit()
    return error is None


def run(sf, settings: Settings, mailer: Mailer, now: datetime | None = None, *, force: bool = False,
        sleep: Callable[[float], None] = time.sleep) -> bool:
    now = now or datetime.now(UTC)
    with sf() as session:
        d = digest_stage.build(session, settings, now)
        subject, html = digest_stage.render(d, settings)
        ok = send(session, d, subject, html, settings, mailer, now, force=force, sleep=sleep)
        session.add(Run(stage="send", started_at=now, finished_at=datetime.now(UTC),
                        stats={"sent": ok, "jobs": len(_jobs(d)), "digest_id": d.digest_id, "subject": subject}))
        session.commit()
    return ok
