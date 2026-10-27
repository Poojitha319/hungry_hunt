"""Entry point for the `hunt` console script and `python -m hungry_hunt`."""

import time
from datetime import UTC, datetime

from hungry_hunt.cli.commands import COMMANDS
from hungry_hunt.cli.parser import build_parser
from hungry_hunt.config import Settings
from hungry_hunt.db import make_engine, session_factory
from hungry_hunt.log import configure_logging
from hungry_hunt.pipeline.run import Pipeline

__all__ = ["build_parser", "main"]


def main(
    argv=None, *, settings=None, source=None, llm=None, mailer=None, mailbox=None, now=None, sleep=time.sleep
) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)
    pipeline = Pipeline(
        session_factory(make_engine(settings.database_url)),
        settings,
        now or datetime.now(UTC),
        source=source,
        llm=llm,
        mailer=mailer,
        mailbox=mailbox,
        sleep=sleep,
    )
    return COMMANDS[args.cmd](args, pipeline)
