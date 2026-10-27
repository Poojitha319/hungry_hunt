"""Copies every table from one database URL to another (used for SQLite to Neon migration)."""

import logging
import sys

from sqlalchemy import String, func, select, text

from hungry_hunt.db import (
    Base,
    make_engine,
    models,  # noqa: F401  registers tables on Base.metadata
)

CHUNK = 1000


class TargetNotEmpty(Exception):
    pass


def copy(src, dst, replace: bool = False) -> dict[str, int]:
    tables = Base.metadata.sorted_tables
    with dst.begin() as conn:
        populated = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
        if populated and not replace:
            raise TargetNotEmpty(f"target already has rows in: {', '.join(populated)} (use --replace)")
        for t in reversed(tables):
            conn.execute(t.delete())
    counts = {}
    with src.connect() as sconn, dst.begin() as dconn:
        for t in tables:
            limits = {c.name: c.type.length for c in t.c if isinstance(c.type, String) and c.type.length}
            rows = [
                {k: (v[: limits[k]] if k in limits and isinstance(v, str) else v) for k, v in r._mapping.items()}
                for r in sconn.execute(select(t))
            ]
            for start in range(0, len(rows), CHUNK):
                dconn.execute(t.insert(), rows[start : start + CHUNK])
            counts[t.name] = len(rows)
            if dconn.dialect.name == "postgresql" and "id" in t.c and rows:
                dconn.execute(
                    text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), (SELECT MAX(id) FROM {t.name}))")  # noqa: S608  table names come from metadata
                )
    return counts


if __name__ == "__main__":
    from hungry_hunt.log import configure_logging

    configure_logging()
    if len(sys.argv) < 3:
        sys.exit("usage: python -m hungry_hunt.db.copydb SRC_URL DST_URL [--replace]")
    result = copy(make_engine(sys.argv[1]), make_engine(sys.argv[2]), replace="--replace" in sys.argv)
    logging.getLogger(__name__).info(" ".join(f"{k}={v}" for k, v in result.items()))
