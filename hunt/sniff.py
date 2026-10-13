import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from hunt.discover import UNSUPPORTED, Board, boards_from_text
from hunt.fetch import SUPPORTED

FOLLOW = re.compile(r"job|opening|position|vacanc|explore|open[- ]roles", re.IGNORECASE)
MAX_FOLLOW, MAX_BODY, SETTLE_MS = 3, 2_000_000, 4000
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class BrowserUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


async def capture(url: str, *, follow: bool = True, timeout_s: int = 45) -> list[str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise BrowserUnavailable("playwright is not installed (pip install 'hungry-hunt[sniff]' && playwright install chromium)") from e
    texts: list[str] = []

    async def on_response(r):
        if r.request.resource_type not in ("xhr", "fetch", "document"):
            return
        texts.append(f"{r.request.method} {r.url}")
        try:
            body = await r.text()
        except Exception:
            return
        if len(body) <= MAX_BODY:
            texts.append(body)

    async def visit(page, target):
        try:
            await page.goto(target, wait_until="load", timeout=timeout_s * 1000)
        except Exception:
            pass
        await page.wait_for_timeout(SETTLE_MS)
        for frame in page.frames:
            try:
                texts.append(f"frame {frame.url}")
                texts.append(await frame.content())
            except Exception:
                continue

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(user_agent=UA)
        page.on("response", on_response)
        await visit(page, url)
        if follow:
            host = urlsplit(page.url).netloc
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => [e.href, e.textContent || ''])")
            seen, targets = {page.url}, []
            for href, text in hrefs:
                if href in seen or urlsplit(href).netloc != host or not (FOLLOW.search(href) or FOLLOW.search(text)):
                    continue
                seen.add(href)
                targets.append(href)
            for target in targets[:MAX_FOLLOW]:
                await visit(page, target)
        await browser.close()
    return texts


async def sniff(url: str, capture: Callable[[str], Awaitable[list[str]]] = capture) -> Board | None:
    text = "\n".join(await capture(url))
    boards = boards_from_text(text)
    if supported := [b for b in boards if b.ats in SUPPORTED]:
        return supported[0]
    if m := UNSUPPORTED.search(text):
        vendor = m.group(1).split(".")[0]
        return Board(ats="unsupported", slug=urlsplit(url).netloc.removeprefix("www.").split(".")[0], board_url=m.group(0), notes=f"{vendor} ATS (not readable yet)")
    return None
