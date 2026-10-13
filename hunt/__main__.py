import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from hunt import assess, digest, discover, fetch, profile, prune, send, track
from hunt.ats import AtsSource
from hunt.config import Settings
from hunt.db import make_engine, session_factory
from hunt.http import Limits, make_client
from hunt.models import Run
from hunt.seeds import SEEDS


def build_parser():
    p = argparse.ArgumentParser(prog="hunt", description="Find genuine fresher-fit openings and deliver a daily digest.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("profile", help="extract the profile from the resume (local only)")
    pr.add_argument("--targets", help="comma-separated preferred role words, matched against titles (e.g. 'backend,AI engineer,LLM')")
    pr.add_argument("--exclude", help="comma-separated title words to drop (e.g. 'Android,iOS')")
    d = sub.add_parser("discover", help="add companies to watch")
    d.add_argument("--seeds", action="store_true", help="apply the built-in seed registry")
    d.add_argument("--slugs", help="JSON file {ats: [slug, ...]} to add as watch boards")
    d.add_argument("--sources", help="comma-separated: wayback,cc,github,yc,careers")
    dsub = d.add_subparsers(dest="discover_cmd")
    add = dsub.add_parser("add", help="add one board: ats:slug or a board URL")
    add.add_argument("board")
    add.add_argument("--status", default="watch", choices=["target", "watch", "avoid"])
    add.add_argument("--notes", default="")
    f = sub.add_parser("fetch", help="fetch every watched board")
    f.add_argument("--only", help="comma-separated ats:slug list")
    f.add_argument("--limit", type=int)
    f.add_argument("--include-dead", action="store_true")
    a = sub.add_parser("assess", help="rules, then Gemini scoring")
    a.add_argument("--max-calls", type=int)
    g = sub.add_parser("digest", help="build today's digest")
    g.add_argument("--preview", help="write the HTML here instead of sending")
    s = sub.add_parser("send", help="send today's digest by email")
    s.add_argument("--force", action="store_true")
    sub.add_parser("prune", help="drop long-closed jobs and old run rows")
    sub.add_parser("track", help="read forwarded hiring mail and update application statuses")
    sub.add_parser("run", help="fetch → track → assess → send → prune")
    return p


def run_prune(sf, now):
    with sf() as session:
        st = prune.prune(session, now)
        session.add(Run(stage="prune", started_at=now, finished_at=datetime.now(UTC), stats=asdict(st)))
        session.commit()
    return st


def main(argv=None, *, settings=None, source=None, llm=None, mailer=None, mailbox=None, now=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or Settings()
    sf = session_factory(make_engine(settings.database_url))
    now = now or datetime.now(UTC)

    def get_llm():
        if llm is not None:
            return llm
        from hunt.gemini import Gemini
        return Gemini(settings.gemini_api_key, settings.gemini_model)

    async def run_fetch(**kw):
        async with make_client() as client:
            src = source or AtsSource(client, Limits(settings.fetch_concurrency, settings.fetch_per_host))
            return await fetch.fetch_all(sf, settings, src, now=now, **kw)

    def run_assess(max_calls=None):
        s = settings.model_copy(update={"assess_max_calls": max_calls}) if max_calls is not None else settings
        return assess.run(sf, s, get_llm(), now=now, sleep=sleep)

    def run_send(force=False):
        return send.run(sf, settings, mailer or send.GmailMailer(settings), now=now, force=force, sleep=sleep)

    def run_track():
        if mailbox is None and not (settings.smtp_user and settings.smtp_password):
            print("track: skipped (no mailbox credentials)")
            return None
        st = track.run(sf, settings, mailbox or track.ImapMailbox(settings), now=now)
        print(f"track: {st.seen} new mails, {st.classified} hiring events, {st.linked_jobs} linked to jobs, {st.unmatched} unmatched")
        return st

    if args.cmd == "profile":
        with sf() as session:
            p = profile.ensure_profile(session, settings.user_id, get_llm(), Path(settings.resume_tex))
            p.max_years_bar = settings.max_years_bar
            if args.targets is not None:
                p.target_titles = [t.strip() for t in args.targets.split(",") if t.strip()]
            if args.exclude is not None:
                p.excluded_titles = [t.strip() for t in args.exclude.split(",") if t.strip()]
            session.commit()
            print(f"profile {p.resume_version}: {len(p.skills)} skills, {p.years_experience} years, preferred roles: {', '.join(p.target_titles or []) or '-'}")
        return 0

    if args.cmd == "discover":
        boards = list(SEEDS) if args.seeds else []
        if args.slugs:
            data = json.loads(Path(args.slugs).read_text())
            boards += [discover.Board(ats=ats, slug=slug) for ats, slugs in data.items() for slug in slugs]
        if args.discover_cmd == "add":
            b = discover.parse_board(args.board)
            boards.append(b.model_copy(update={"status": args.status, "notes": args.notes}))
        with sf() as session:
            n = discover.upsert_companies(session, settings.user_id, boards)
            session.commit()
        print(f"discover: {n} new companies from seeds/slugs/add")
        if args.sources:
            async def run_discover():
                async with make_client() as client:
                    return await discover.discover(sf, settings, args.sources.split(","), client, now=now)
            st = asyncio.run(run_discover())
            print(f"discover: {st.new_companies} new companies {st.per_source}, probed {st.probed}, enriched {st.enriched}"
                  + (f", errors: {st.errors}" if st.errors else ""))
        return 0

    if args.cmd == "fetch":
        cov = asyncio.run(run_fetch(only=args.only.split(",") if args.only else None, limit=args.limit, include_dead=args.include_dead))
        print(f"fetch: {cov.boards_ok}/{cov.boards_total} boards ok, {cov.jobs_new} new jobs, {cov.jobs_closed} closed")
        return 0

    if args.cmd == "assess":
        try:
            st = run_assess(args.max_calls)
        except assess.NoProfile as e:
            print(f"assess: {e}", file=sys.stderr)
            return 1
        print(f"assess: {st.rules_evaluated} rules evaluated, {st.scored} scored, quota_hit={st.quota_hit}")
        return 0

    if args.cmd == "digest":
        with sf() as session:
            d = digest.build(session, settings, now)
            subject, html = digest.render(d, settings)
        if args.preview:
            Path(args.preview).write_text(html)
            print(f"digest: wrote {args.preview}")
        print(subject)
        return 0

    if args.cmd == "send":
        return 0 if run_send(force=args.force) else 2

    if args.cmd == "track":
        run_track()
        return 0

    if args.cmd == "prune":
        st = run_prune(sf, now)
        print(f"prune: {st.jobs_deleted} jobs deleted, {st.descriptions_cleared} descriptions cleared, {st.runs_deleted} runs deleted")
        return 0

    failed = False
    try:
        cov = asyncio.run(run_fetch())
        print(f"fetch: {cov.boards_ok}/{cov.boards_total} boards ok, {cov.jobs_new} new jobs")
    except Exception as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        failed = True
    try:
        run_track()
    except Exception as e:
        print(f"track failed: {e}", file=sys.stderr)
        failed = True
    try:
        st = run_assess()
        print(f"assess: {st.scored} scored, quota_hit={st.quota_hit}")
    except Exception as e:
        print(f"assess failed: {e}", file=sys.stderr)
        failed = True
    if not run_send():
        print("send failed after retries", file=sys.stderr)
        return 2
    try:
        run_prune(sf, now)
    except Exception as e:
        print(f"prune failed: {e}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
