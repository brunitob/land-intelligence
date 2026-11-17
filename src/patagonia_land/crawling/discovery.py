"""Discovery Engine: encuentra TODAS las URLs de fichas individuales de una fuente.

Combina sitemaps + crawling (menús, categorías, paginación, "siguiente", páginas sintetizadas) con
límites de profundidad y páginas por ejecución. Las fichas descargadas se devuelven ya parseadas para
que la extracción no vuelva a pedirlas.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import structlog

from patagonia_land.crawling.classifier import Classification, PageType, classify_page, classify_url_only
from patagonia_land.crawling.fetcher import (
    BlockedError,
    Fetcher,
    FetchError,
    FetchResult,
    OutsideVisitTime,
    RobotsDisallowed,
)
from patagonia_land.crawling.page import Page
from patagonia_land.crawling.pagination import build_page_url, current_page_number, detect_pagination
from patagonia_land.crawling.sitemaps import discover_sitemap_urls
from patagonia_land.crawling.urls import canonicalize, is_crawlable_query, same_site

log = structlog.get_logger()

PRIORITY = {
    PageType.PROPERTY_LIST: 1, PageType.PAGINATION: 1, PageType.CATEGORY: 1,
    PageType.PROPERTY_DETAIL: 2, PageType.UNKNOWN: 3, PageType.OTHER: 9,
}


@dataclass
class SourceConfig:
    id: str
    base_url: str
    start_urls: list[str] = field(default_factory=list)
    max_pages_per_run: int = 200
    max_depth: int = 5
    max_run_seconds: int = 4 * 3600
    # Fichas ya conocidas → último chequeo (epoch s). Se visitan después de listados y fichas nuevas, las más
    # viejas primero: si el presupuesto no alcanza, cada corrida avanza sobre las que hace más que no se miran.
    known_details: dict[str, float] = field(default_factory=dict)


@dataclass
class PageRecord:
    url: str
    depth: int
    parent_url: str | None
    page_type: str = PageType.UNKNOWN
    status: str = "discovered"
    http_status: int | None = None
    content_hash: str | None = None
    error: str | None = None
    confidence: float | None = None


@dataclass
class DiscoveryResult:
    details: dict[str, Page] = field(default_factory=dict)
    detail_fetch: dict[str, FetchResult] = field(default_factory=dict)
    records: dict[str, PageRecord] = field(default_factory=dict)
    candidate_urls: int = 0
    sitemap_urls: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    window_closed: bool = False  # se cerró la franja Visit-time de robots.txt: corrida incompleta, no rota
    pages_visited: int = 0
    page_budget: int = 0
    notes: list[str] = field(default_factory=list)


ProgressCb = Callable[[dict[str, Any]], Awaitable[None] | None]


async def fetch_page(fetcher: Fetcher, url: str, base_url: str, profile: dict[str, Any]) -> tuple[Page, FetchResult]:
    """Descarga HTML (o renderiza si el perfil/heurística lo exige y Playwright está habilitado)."""
    if profile.get("rendering") == "javascript" and fetcher.settings.enable_playwright:
        res = await fetcher.render(url)
    else:
        res = await fetcher.get(url)
        page = Page(url=res.url, html=res.text, base_url=base_url)
        if res.is_html and page.script_heavy and fetcher.settings.enable_playwright:
            res = await fetcher.render(url)
        else:
            return page, res
    return Page(url=res.url, html=res.text, base_url=base_url), res


async def discover_properties(
    fetcher: Fetcher,
    source: SourceConfig,
    profile: dict[str, Any] | None = None,
    progress: ProgressCb | None = None,
    use_sitemaps: bool = True,
) -> DiscoveryResult:
    profile = profile or {}
    result = DiscoveryResult()
    counter = itertools.count()
    heap: list[tuple[float, int, str]] = []
    pagination = profile.get("pagination") or {}

    def enqueue(url: str | None, depth: int, parent: str | None, hint: Classification | None = None) -> None:
        if not url or url in result.records or not same_site(url, source.base_url):
            return
        if not is_crawlable_query(url) or depth > source.max_depth:
            return
        hint = hint or classify_url_only(url, profile)
        if hint.page_type == PageType.OTHER:
            result.records[url] = PageRecord(url, depth, parent, PageType.OTHER, "skipped")
            return
        result.records[url] = PageRecord(url, depth, parent, hint.page_type)
        result.candidate_urls += 1
        prio: float = PRIORITY[hint.page_type] * 100 + depth
        if hint.page_type == PageType.PROPERTY_DETAIL and url in source.known_details:
            prio = 1000 + source.known_details[url] / 1e10  # conocidas al final, la menos reciente primero
        heapq.heappush(heap, (prio, next(counter), url))

    starts = source.start_urls or profile.get("entry_urls") or [source.base_url]
    for u in starts + [source.base_url]:
        c = canonicalize(u)
        if c and c not in result.records:
            result.records[c] = PageRecord(c, 0, None)
            result.candidate_urls += 1
            heapq.heappush(heap, (0, next(counter), c))

    if use_sitemaps and profile.get("discovery_strategy") != "crawl_only":
        try:
            _, sm_urls = await discover_sitemap_urls(fetcher, source.base_url)
        except FetchError as exc:
            sm_urls = []
            result.errors.append({"url": source.base_url, "stage": "sitemap", "error": str(exc)})
        result.sitemap_urls = len(sm_urls)
        for u in sm_urls:
            hint = classify_url_only(u, profile)
            # Del sitemap solo encolamos lo que parece ficha o listado; el resto se ignora para no gastar presupuesto.
            if hint.page_type in (PageType.PROPERTY_DETAIL, PageType.PROPERTY_LIST, PageType.CATEGORY):
                enqueue(u, 1, "sitemap", hint)

    # Presupuesto: páginas por corrida, acotado por el ritmo que exige robots.txt (Crawl-delay/Request-rate).
    if fetcher.settings.respect_robots:
        await fetcher.robots_for(source.base_url)  # el ritmo y la franja salen de robots.txt
    interval = fetcher.crawl_delay(source.base_url)
    budget = source.max_pages_per_run
    run_seconds = source.max_run_seconds
    window_left = fetcher.visit_seconds_left(source.base_url)
    if window_left is not None:
        run_seconds = min(run_seconds, int(window_left))
    if interval > 0:
        budget = min(budget, max(1, int(run_seconds / interval)))
        if budget < source.max_pages_per_run:
            result.notes.append(f"robots.txt exige {interval:.0f}s entre pedidos: presupuesto reducido a {budget} "
                                f"páginas por corrida (máx. {run_seconds // 60} min)")
    result.page_budget = budget

    while heap and result.pages_visited < budget:
        _, _, url = heapq.heappop(heap)
        rec = result.records[url]
        try:
            page, res = await fetch_page(fetcher, url, source.base_url, profile)
        except RobotsDisallowed as exc:
            rec.status, rec.error = "skipped", str(exc)
            continue
        except OutsideVisitTime as exc:
            rec.status, rec.error = "skipped", str(exc)
            result.window_closed = True
            result.notes.append("se cerró la franja horaria de robots.txt: el resto sigue en la próxima corrida")
            break
        except BlockedError as exc:
            rec.status, rec.error = "error", str(exc)
            result.errors.append({"url": url, "stage": "fetch", "error": str(exc), "blocked": True})
            result.blocked = True
            break  # No insistir ante bloqueos.
        except FetchError as exc:
            rec.status, rec.error = "error", str(exc)
            result.errors.append({"url": url, "stage": "fetch", "error": str(exc)})
            continue
        result.pages_visited += 1
        rec.http_status = res.status
        rec.content_hash = res.content_hash
        if res.status >= 400 or not res.is_html:
            rec.status = "error" if res.status >= 400 else "skipped"
            rec.error = f"HTTP {res.status}" if res.status >= 400 else "no HTML"
            if res.status >= 400:
                result.errors.append({"url": url, "stage": "fetch", "error": rec.error})
            continue
        rec.status = "fetched"

        final = canonicalize(res.url) or url
        if final != url and not same_site(final, source.base_url):
            rec.status, rec.error = "skipped", "redirige fuera del sitio"
            continue

        cls = classify_page(page, profile)
        hinted_list = rec.page_type in (PageType.PAGINATION, PageType.PROPERTY_LIST, PageType.CATEGORY)
        if cls.page_type == PageType.PROPERTY_DETAIL and hinted_list and not page.jsonld_listing_nodes \
                and cls.confidence < 0.8:
            # Última página de un listado con 1-2 tarjetas: confiar en cómo llegamos a ella.
            cls = Classification(rec.page_type, 0.5, cls.reasons + ["pista de navegación: listado"], cls.scores)
        if cls.page_type == PageType.PROPERTY_DETAIL and profile.get("detail_pattern_strict") and not any(
                pat in urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else "")
                for pat in profile.get("listing_patterns") or []):
            # Plataforma conocida: una "ficha" fuera del patrón es una categoría con 1-2 tarjetas.
            cls = Classification(PageType.CATEGORY, 0.6, cls.reasons + ["fuera del patrón de fichas"], cls.scores)
        rec.page_type, rec.confidence = cls.page_type, cls.confidence

        if cls.page_type == PageType.PROPERTY_DETAIL:
            key = page.canonical_url
            if key not in result.details:
                result.details[key] = page
                result.detail_fetch[key] = res
            # Las fichas pueden enlazar "propiedades similares": se encolan como candidatas de bajo costo.
            for link in page.links:
                hint = classify_url_only(link, profile)
                if hint.page_type == PageType.PROPERTY_DETAIL:
                    enqueue(link, rec.depth + 1, url, hint)
        else:
            group = page.property_card_group
            new_details = 0
            if group:
                for link in group.links:
                    if link not in result.records:
                        new_details += 1
                    enqueue(link, rec.depth + 1, url, Classification(PageType.PROPERTY_DETAIL, 0.6, ["tarjeta"]))
            for link in page.next_links:
                # La paginación no consume profundidad: listados largos deben recorrerse completos.
                enqueue(link, rec.depth, url, Classification(PageType.PAGINATION, 0.7, ["next"]))
            if cls.page_type in (PageType.PROPERTY_LIST, PageType.PAGINATION, PageType.CATEGORY):
                pag = pagination if pagination.get("type") not in (None, "none") else detect_pagination(page)
                if new_details and pag.get("type") in ("query_parameter", "path_segment"):
                    nxt = build_page_url(url, pag, current_page_number(url, pag) + 1)
                    enqueue(canonicalize(nxt), rec.depth, url, Classification(PageType.PAGINATION, 0.5, ["sintética"]))
            if profile.get("follow_links") != "cards_and_pagination":
                for link in page.links:
                    enqueue(link, rec.depth + 1, url)

        if progress and result.pages_visited % 5 == 0:
            maybe = progress({"pages_visited": result.pages_visited, "details": len(result.details),
                              "queue": len(heap)})
            if maybe is not None:
                await maybe

    log.info("discovery.done", source=source.id, visited=result.pages_visited, details=len(result.details),
             candidates=result.candidate_urls, errors=len(result.errors))
    return result
