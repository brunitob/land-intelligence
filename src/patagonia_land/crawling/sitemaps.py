"""Descubrimiento vía sitemaps e índices de sitemap."""

from __future__ import annotations

import gzip
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from patagonia_land.crawling.fetcher import Fetcher, FetchError
from patagonia_land.crawling.urls import canonicalize, same_site

log = structlog.get_logger()

COMMON_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml")
# Sub-sitemaps que claramente no contienen propiedades.
SKIP_SITEMAP_TOKENS = ("post-sitemap", "page-sitemap", "category", "tag", "author", "attachment", "image")


def _parse(text: str) -> tuple[list[str], list[str]]:
    """Devuelve (sub_sitemaps, urls)."""
    soup = BeautifulSoup(text, "xml")
    subs = [loc.get_text(strip=True) for sm in soup.find_all("sitemap") if (loc := sm.find("loc"))]
    urls = [loc.get_text(strip=True) for u in soup.find_all("url") if (loc := u.find("loc"))]
    return subs, urls


async def discover_sitemap_urls(fetcher: Fetcher, base_url: str, max_sitemaps: int = 30,
                                max_urls: int = 5000) -> tuple[list[str], list[str]]:
    """Devuelve (sitemaps_encontrados, urls_del_sitio)."""
    queue = list(dict.fromkeys(await fetcher.sitemaps_from_robots(base_url)
                               + [urljoin(base_url, p) for p in COMMON_SITEMAPS]))
    seen: set[str] = set()
    found: list[str] = []
    urls: dict[str, None] = {}
    while queue and len(seen) < max_sitemaps and len(urls) < max_urls:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            res = await fetcher.get(sm, retries=0)
        except FetchError as exc:
            log.debug("sitemap.error", url=sm, error=str(exc))
            continue
        if res.status != 200:
            continue
        text = res.text
        if sm.endswith(".gz") and not text.lstrip().startswith("<"):
            try:
                text = gzip.decompress(res.text.encode("latin-1")).decode("utf-8", "replace")
            except OSError:
                continue
        if "<urlset" not in text and "<sitemapindex" not in text:
            continue
        found.append(sm)
        subs, page_urls = _parse(text)
        for s in subs:
            if not any(t in s.lower() for t in SKIP_SITEMAP_TOKENS):
                queue.append(s)
        for u in page_urls:
            c = canonicalize(u)
            if c and same_site(c, base_url):
                urls.setdefault(c, None)
    return found, list(urls)[:max_urls]
