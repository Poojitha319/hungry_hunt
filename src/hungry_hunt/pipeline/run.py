"""The daily run: fetch, track, assess, send, prune, each stage isolated so one failure does not stop the rest."""

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from hungry_hunt.adapters import AtsSource
from hungry_hunt.config import Settings
from hungry_hunt.core.http import Limits, make_client
from hungry_hunt.core.schemas import Coverage
from hungry_hunt.db.models import Run
from hungry_hunt.delivery import send
from hungry_hunt.pipeline import fetch, prune
from hungry_hunt.scoring import assess
from hungry_hunt.tracking import track

log = logging.getLogger(__name__)


@dataclass
class Pipeline:
    sf: Any
    settings: Settings
    now: datetime
    source: Any = None
    llm: Any = None
    mailer: Any = None
    mailbox: Any = None
    sleep: Any = time.sleep

    def get_llm(self):
        if self.llm is not None:
            return self.llm
        from hungry_hunt.scoring.gemini import Gemini

        return Gemini(self.settings.gemini_api_key, self.settings.gemini_model)

    async def fetch(self, **kw) -> Coverage:
        async with make_client() as client:
            src = self.source or AtsSource(
                client, Limits(self.settings.fetch_concurrency, self.settings.fetch_per_host)
            )
            return await fetch.fetch_all(self.sf, self.settings, src, now=self.now, **kw)

    def assess(self, max_calls: int | None = None) -> assess.ScoreStats:
        s = self.settings.model_copy(update={"assess_max_calls": max_calls}) if max_calls is not None else self.settings
        return assess.run(self.sf, s, self.get_llm(), now=self.now, sleep=self.sleep)

    def send(self, force: bool = False) -> bool:
        return send.run(
            self.sf,
            self.settings,
            self.mailer or send.GmailMailer(self.settings),
            now=self.now,
            force=force,
            sleep=self.sleep,
        )

    def track(self) -> track.TrackStats | None:
        if self.mailbox is None and not (self.settings.smtp_user and self.settings.smtp_password):
            log.info("track: skipped (no mailbox credentials)")
            return None
        st = track.run(self.sf, self.settings, self.mailbox or track.ImapMailbox(self.settings), now=self.now)
        log.info(
            f"track: {st.seen} new mails, {st.classified} hiring events, {st.linked_jobs} linked to jobs, {st.unmatched} unmatched"
        )
        return st

    def prune(self) -> prune.PruneStats:
        with self.sf() as session:
            st = prune.prune(session, self.now)
            session.add(Run(stage="prune", started_at=self.now, finished_at=datetime.now(UTC), stats=asdict(st)))
            session.commit()
        return st


@dataclass
class RunSummary:
    fetch: Coverage | None = None
    assess_scored: int = 0
    sent: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 2 if not self.sent else 1 if self.errors else 0


def run_daily(p: Pipeline) -> RunSummary:
    import asyncio

    out = RunSummary()
    try:
        out.fetch = asyncio.run(p.fetch())
        log.info(f"fetch: {out.fetch.boards_ok}/{out.fetch.boards_total} boards ok, {out.fetch.jobs_new} new jobs")
    except Exception as e:
        log.error("fetch failed: %s", e)
        out.errors.append(f"fetch: {e}")
    try:
        p.track()
    except Exception as e:
        log.error("track failed: %s", e)
        out.errors.append(f"track: {e}")
    try:
        st = p.assess()
        out.assess_scored = st.scored
        log.info(f"assess: {st.scored} scored, quota_hit={st.quota_hit}")
    except Exception as e:
        log.error("assess failed: %s", e)
        out.errors.append(f"assess: {e}")
    out.sent = p.send()
    if not out.sent:
        log.error("send failed after retries")
        return out
    try:
        p.prune()
    except Exception as e:
        log.error("prune failed: %s", e)
        out.errors.append(f"prune: {e}")
    return out
