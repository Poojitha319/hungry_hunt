import asyncio
import ipaddress
import socket
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

BACKOFF = (2, 8)
USER_AGENT = "hungry-hunt/0.1 (personal job search; +https://github.com/Poojitha319/hungry_hunt)"


def resolve(host: str) -> set[str]:
    return {info[4][0] for info in socket.getaddrinfo(host, None)}


def safe_url(url: str) -> bool:
    u = urlsplit(url)
    host = (u.hostname or "").rstrip(".").lower()
    if u.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        addresses = {host} if ipaddress.ip_address(host) else set()
    except ValueError:
        try:
            addresses = resolve(host)
        except (socket.gaierror, UnicodeError):
            return False
    try:
        return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
    except ValueError:
        return False


class BoardError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Limits:
    def __init__(self, total: int, per_host: int):
        self.total = asyncio.Semaphore(total)
        self.per_host = defaultdict(lambda: asyncio.Semaphore(per_host))


def make_client(timeout: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


async def get_json(client: httpx.AsyncClient, url: str, *, params: dict | None = None, retries: int = 2,
                   limits: Limits | None = None) -> Any:
    host = urlsplit(url).netloc
    for attempt in range(retries + 1):
        try:
            if limits:
                async with limits.total, limits.per_host[host]:
                    r = await client.get(url, params=params)
            else:
                r = await client.get(url, params=params)
        except httpx.HTTPError as e:
            if attempt == retries:
                raise BoardError(f"{url}: {e}") from e
            await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError as e:
                raise BoardError(f"{url}: invalid JSON", status=200) from e
        if r.status_code < 500 or attempt == retries:
            raise BoardError(f"{url}: HTTP {r.status_code}", status=r.status_code)
        await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])


MAX_REDIRECTS = 3


async def post_json(client: httpx.AsyncClient, url: str, body: dict, *, retries: int = 2, limits: Limits | None = None) -> Any:
    if not safe_url(url):
        raise BoardError(f"{url}: unsafe destination")
    host = urlsplit(url).netloc
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    for attempt in range(retries + 1):
        try:
            if limits:
                async with limits.total, limits.per_host[host]:
                    r = await client.post(url, json=body, headers=headers)
            else:
                r = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            if attempt == retries:
                raise BoardError(f"{url}: {e}") from e
            await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError as e:
                raise BoardError(f"{url}: invalid JSON", status=200) from e
        if r.status_code < 500 or attempt == retries:
            raise BoardError(f"{url}: HTTP {r.status_code}", status=r.status_code)
        await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])


async def get_text(client: httpx.AsyncClient, url: str, *, retries: int = 1, limits: Limits | None = None) -> str:
    for _ in range(MAX_REDIRECTS + 1):
        if not safe_url(url):
            raise BoardError(f"{url}: refused (not a public http(s) address)")
        host = urlsplit(url).netloc
        r = None
        for attempt in range(retries + 1):
            try:
                if limits:
                    async with limits.total, limits.per_host[host]:
                        r = await client.get(url, follow_redirects=False)
                else:
                    r = await client.get(url, follow_redirects=False)
                break
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise BoardError(f"{url}: {e}") from e
                await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        if r.status_code == 200:
            return r.text
        raise BoardError(f"{url}: HTTP {r.status_code}", status=r.status_code)
    raise BoardError(f"{url}: too many redirects")
