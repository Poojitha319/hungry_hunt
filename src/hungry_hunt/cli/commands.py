"""One function per `hunt` subcommand; each returns the process exit code."""

import asyncio
import json
import logging
from argparse import Namespace
from pathlib import Path

from hungry_hunt.core.http import make_client
from hungry_hunt.delivery import digest
from hungry_hunt.discovery import discover
from hungry_hunt.discovery.seeds import SEEDS
from hungry_hunt.pipeline.run import Pipeline, run_daily
from hungry_hunt.scoring import assess, profile

log = logging.getLogger(__name__)


def cmd_profile(args: Namespace, p: Pipeline) -> int:
    with p.sf() as session:
        prof = profile.ensure_profile(session, p.settings.user_id, p.get_llm(), Path(p.settings.resume_tex))
        prof.max_years_bar = p.settings.max_years_bar
        if args.targets is not None:
            prof.target_titles = [t.strip() for t in args.targets.split(",") if t.strip()]
        if args.exclude is not None:
            prof.excluded_titles = [t.strip() for t in args.exclude.split(",") if t.strip()]
        session.commit()
        log.info(
            f"profile {prof.resume_version}: {len(prof.skills)} skills, {prof.years_experience} years, preferred roles: {', '.join(prof.target_titles or []) or '-'}"
        )
    return 0


def cmd_discover(args: Namespace, p: Pipeline) -> int:
    boards = list(SEEDS) if args.seeds else []
    if args.slugs:
        data = json.loads(Path(args.slugs).read_text())
        boards += [discover.Board(ats=ats, slug=slug) for ats, slugs in data.items() for slug in slugs]
    if args.discover_cmd == "add":
        b = discover.parse_board(args.board)
        boards.append(b.model_copy(update={"status": args.status, "notes": args.notes}))
    with p.sf() as session:
        n = discover.upsert_companies(session, p.settings.user_id, boards)
        session.commit()
    log.info(f"discover: {n} new companies from seeds/slugs/add")
    if args.sources:

        async def run_discover():
            async with make_client() as client:
                return await discover.discover(p.sf, p.settings, args.sources.split(","), client, now=p.now)

        st = asyncio.run(run_discover())
        log.info(
            f"discover: {st.new_companies} new companies {st.per_source}, probed {st.probed}, enriched {st.enriched}"
            + (f", errors: {st.errors}" if st.errors else "")
        )
    return 0


def cmd_fetch(args: Namespace, p: Pipeline) -> int:
    cov = asyncio.run(
        p.fetch(only=args.only.split(",") if args.only else None, limit=args.limit, include_dead=args.include_dead)
    )
    log.info(f"fetch: {cov.boards_ok}/{cov.boards_total} boards ok, {cov.jobs_new} new jobs, {cov.jobs_closed} closed")
    return 0


def cmd_assess(args: Namespace, p: Pipeline) -> int:
    try:
        st = p.assess(args.max_calls)
    except assess.NoProfile as e:
        log.error("assess: %s", e)
        return 1
    log.info(f"assess: {st.rules_evaluated} rules evaluated, {st.scored} scored, quota_hit={st.quota_hit}")
    return 0


def cmd_digest(args: Namespace, p: Pipeline) -> int:
    with p.sf() as session:
        d = digest.build(session, p.settings, p.now)
        subject, html = digest.render(d, p.settings)
    if args.preview:
        Path(args.preview).write_text(html)
        log.info(f"digest: wrote {args.preview}")
    log.info(subject)
    return 0


def cmd_send(args: Namespace, p: Pipeline) -> int:
    return 0 if p.send(force=args.force) else 2


def cmd_track(args: Namespace, p: Pipeline) -> int:
    p.track()
    return 0


def cmd_prune(args: Namespace, p: Pipeline) -> int:
    st = p.prune()
    log.info(
        f"prune: {st.jobs_deleted} jobs deleted, {st.descriptions_cleared} descriptions cleared, {st.runs_deleted} runs deleted"
    )
    return 0


def cmd_run(args: Namespace, p: Pipeline) -> int:
    return run_daily(p).exit_code


COMMANDS = {
    "profile": cmd_profile,
    "discover": cmd_discover,
    "fetch": cmd_fetch,
    "assess": cmd_assess,
    "digest": cmd_digest,
    "send": cmd_send,
    "track": cmd_track,
    "prune": cmd_prune,
    "run": cmd_run,
}
