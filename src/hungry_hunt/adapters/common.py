"""Helpers shared by the hiring-system adapters."""

from datetime import datetime

from hungry_hunt.core.http import BoardError, get_json


def iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


async def get_with_fallback(client, ats, hosts, slug, params=None, limits=None):
    for i, url in enumerate(hosts):
        try:
            return await get_json(client, url.format(slug=slug), params=params, limits=limits)
        except BoardError as e:
            if e.status != 404 or i == len(hosts) - 1:
                raise
    raise BoardError(f"{ats}:{slug} not found", status=404)
