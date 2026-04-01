"""
core/og_fetcher.py — OG 圖片非同步擷取模組
使用 aiohttp 並行擷取新聞來源的 Open Graph 圖片。
"""

import asyncio
import logging
import re

import aiohttp

log = logging.getLogger("research-bot.og")

OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0)"}


def extract_first_url(sources: str) -> str | None:
    """從來源文字中擷取第一個 URL。"""
    match = re.search(r'https?://[^\s\)\]>]+', sources)
    return match.group(0).rstrip(",.;") if match else None


async def _fetch_one(session: aiohttp.ClientSession, url: str) -> tuple[str, str | None]:
    """擷取單一 URL 的 OG 圖片。"""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return url, None
            html = await resp.text(errors="replace")
            html = html[:80000]
            for pattern in OG_PATTERNS:
                match = pattern.search(html)
                if match:
                    img_url = match.group(1)
                    if img_url.startswith("http"):
                        return url, img_url
    except Exception:
        pass
    return url, None


async def fetch_og_images(items: list[dict]) -> dict[str, str]:
    """
    並行擷取所有新聞項目的 OG 圖片。

    Args:
        items: 新聞項目列表，每項需有 'sources' 欄位

    Returns:
        {source_url: og_image_url}
    """
    urls = set()
    for item in items:
        url = extract_first_url(item.get("sources", ""))
        if url:
            urls.add(url)

    if not urls:
        return {}

    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one(session, url) for url in urls]
        done = await asyncio.gather(*tasks, return_exceptions=True)
        for result in done:
            if isinstance(result, tuple):
                url, img = result
                if img:
                    results[url] = img

    log.info(f"OG 圖片擷取: {len(results)}/{len(urls)}")
    return results
