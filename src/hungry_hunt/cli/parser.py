"""Argument parser for the `hunt` command."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hunt", description="Find genuine fresher-fit openings and deliver a daily digest."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("profile", help="extract the profile from the resume (local only)")
    pr.add_argument(
        "--targets",
        help="comma-separated preferred role words, matched against titles (e.g. 'backend,AI engineer,LLM')",
    )
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
