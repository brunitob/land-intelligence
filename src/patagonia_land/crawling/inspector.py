"""Site Inspector: analiza una inmobiliaria a partir de su URL y genera un SiteProfile.

Preferencia: sitemap/datos estructurados → HTTP/HTML → endpoints públicos → Playwright → LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from patagonia_land.crawling.classifier import PageType, classify_page, classify_url_only
from patagonia_land.crawling.discovery import fetch_page
from patagonia_land.crawling.fetcher import BlockedError, Fetcher, FetchError
from patagonia_land.crawling.page import Page, most_common_prefixes
from patagonia_land.crawling.pagination import detect_pagination
from patagonia_land.crawling.platforms import detect_platform, platform_hints
from patagonia_land.crawling.sitemaps import discover_sitemap_urls
from patagonia_land.crawling.urls import canonicalize

log = structlog.get_logger()


@dataclass
class InspectionReport:
    profile: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sample_detail_urls: list[str] = field(default_factory=list)


async def inspect_site(fetcher: Fetcher, source_id: str, base_url: str, start_urls: list[str] | None = None,
                       max_list_pages: int = 6, max_samples: int = 4,
                       max_inspect_interval: float = 120) -> InspectionReport:
    notes: list[str] = []
    errors: list[str] = []
    profile: dict[str, Any] = {"source_id": source_id}

    # 1. robots.txt y sitemaps
    rp = await fetcher.robots_for(base_url)
    profile["robots_txt"] = "present" if rp is not None else "absent"
    if rp is not None:
        pol = rp.policy(fetcher.settings.user_agent)
        profile["robots_policy"] = pol
        if pol.get("min_interval_seconds_now", 0) >= 60:
            notes.append(f"robots.txt exige ≥{pol['min_interval_seconds_now']:.0f}s entre pedidos")
        if pol.get("visit_time_utc"):
            notes.append(f"robots.txt limita visitas a la franja {pol['visit_time_utc']} UTC")
        if pol.get("disallows_query_urls"):
            notes.append("robots.txt prohíbe URLs con '?': fichas o APIs con parámetros no son accesibles")
        if pol.get("min_interval_seconds_now", 0) > max_inspect_interval:
            profile.update(rendering="unknown", confidence=0.0, slow_crawl_required=True)
            notes.append("inspección interactiva cancelada: el ritmo exigido no permite inspeccionar ahora; "
                         "la fuente solo puede rastrearse con un crawl lento programado")
            return InspectionReport(profile, notes, errors)
    if rp is not None and not rp.can_fetch(fetcher.settings.user_agent, base_url):
        errors.append("robots.txt no permite rastrear la home con nuestro user-agent")
    try:
        sitemaps, sm_urls = await discover_sitemap_urls(fetcher, base_url, max_urls=2000)
    except FetchError as exc:
        sitemaps, sm_urls = [], []
        errors.append(f"sitemap: {exc}")
    sm_detail_like = [u for u in sm_urls if classify_url_only(u).page_type == PageType.PROPERTY_DETAIL]
    profile["sitemaps"] = sitemaps
    profile["sitemap_url_count"] = len(sm_urls)
    notes.append(f"{len(sitemaps)} sitemaps, {len(sm_urls)} URLs, {len(sm_detail_like)} con forma de ficha")

    # 2. Home + start_urls: rendering y estructura
    pages: list[Page] = []
    to_visit = [canonicalize(u) for u in (start_urls or [])] + [canonicalize(base_url)]
    rendering = "static"
    for url in dict.fromkeys(u for u in to_visit if u):
        try:
            page, res = await fetch_page(fetcher, url, base_url, {})
        except BlockedError as exc:
            errors.append(f"bloqueado: {exc}")
            profile.update(rendering="unknown", blocked=True, confidence=0.0)
            return InspectionReport(profile, notes, errors)
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        if res.rendered:
            rendering = "javascript"
        elif page.script_heavy:
            rendering = "javascript"
            notes.append(f"{url} parece SPA; habilitar Playwright para rastrearla")
        pages.append(page)
    if not pages:
        profile.update(rendering="unknown", confidence=0.0)
        return InspectionReport(profile, notes, errors or ["no se pudo descargar ninguna página"])
    profile["rendering"] = rendering

    # 2b. Plataforma conocida: pistas que el HTML no expone (p.ej. paginación por scroll infinito)
    platform = next((pl for pl in (detect_platform(p.html) for p in pages) if pl), None)
    hints = platform_hints(platform, base_url)
    if platform:
        profile["platform"] = platform
        notes.append(f"plataforma detectada: {platform}")
    for url in hints.get("entry_urls", []):
        if url in {p.url for p in pages}:
            continue
        try:
            page, _ = await fetch_page(fetcher, url, base_url, {})
            pages.append(page)
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
    for k in ("entry_urls", "detail_pattern_strict", "follow_links"):
        if hints.get(k):
            profile[k] = hints[k]

    # 3. Buscar páginas de listado (start_urls, links de menú con tokens de listado)
    list_pages: list[Page] = []
    candidates: list[str] = []
    for p in pages:
        if classify_page(p).page_type in (PageType.PROPERTY_LIST, PageType.CATEGORY, PageType.PAGINATION):
            list_pages.append(p)
        candidates += [u for u in p.links if classify_url_only(u).page_type in
                       (PageType.PROPERTY_LIST, PageType.CATEGORY)]
    for url in dict.fromkeys(candidates):
        if len(list_pages) >= max_list_pages:
            break
        try:
            page, _ = await fetch_page(fetcher, url, base_url, profile)
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        if page.property_card_group:
            list_pages.append(page)

    card_selectors: dict[str, int] = {}
    detail_candidates: list[str] = []
    pagination: dict[str, Any] = {"type": "none"}
    for lp in list_pages:
        g = lp.property_card_group
        if g:
            card_selectors[g.selector] = card_selectors.get(g.selector, 0) + len(g.links)
            detail_candidates += g.links
        pg = detect_pagination(lp)
        if pg["type"] != "none" and pagination["type"] in ("none", "next_link", "load_more"):
            pagination = pg
    if hints.get("pagination") and pagination["type"] in ("none", "load_more"):
        pagination = hints["pagination"]
    profile["pagination"] = pagination
    if card_selectors:
        profile.setdefault("selectors", {})["property_cards"] = max(card_selectors, key=card_selectors.get)
    profile["list_pages"] = [p.url for p in list_pages]
    if pagination["type"] == "load_more":
        notes.append("Listado con 'ver más'/scroll: requiere Playwright o endpoint JSON público")

    # 4. Muestrear fichas para validar patrones y estrategia de extracción
    detail_candidates = list(dict.fromkeys(detail_candidates)) or sm_detail_like
    confirmed: list[Page] = []
    for url in detail_candidates[: max_samples * 2]:
        if len(confirmed) >= max_samples:
            break
        try:
            page, _ = await fetch_page(fetcher, url, base_url, profile)
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        if classify_page(page).page_type == PageType.PROPERTY_DETAIL:
            confirmed.append(page)
    detail_urls = [p.canonical_url for p in confirmed]
    profile["listing_patterns"] = most_common_prefixes(detail_urls + detail_candidates) \
        or hints.get("listing_patterns", [])
    with_jsonld = sum(1 for p in confirmed if p.jsonld_listing_nodes)
    profile["structured_data"] = {"json_ld_listing": with_jsonld, "samples": len(confirmed)}
    if confirmed and with_jsonld == len(confirmed):
        profile["detail_strategy"] = "json_ld_with_html_fallback"
    else:
        profile["detail_strategy"] = "html_with_llm_fallback"

    if sm_detail_like and len(sm_detail_like) >= len(detail_candidates):
        profile["discovery_strategy"] = "sitemap"
    elif pagination["type"] in ("query_parameter", "path_segment", "next_link"):
        profile["discovery_strategy"] = "pagination"
    elif pagination["type"] == "load_more":
        profile["discovery_strategy"] = "load_more"
    else:
        profile["discovery_strategy"] = "crawl"

    # 5. Confianza del perfil (no del dato): ¿pudimos confirmar fichas y su patrón?
    conf = 0.2
    conf += 0.3 if confirmed else 0
    conf += 0.2 if profile["listing_patterns"] else 0
    conf += 0.15 if pagination["type"] != "none" or sm_detail_like else 0
    conf += 0.15 if with_jsonld else 0.05 if confirmed else 0
    conf -= 0.3 if rendering == "javascript" and not fetcher.settings.enable_playwright else 0
    profile["confidence"] = round(max(0.0, min(conf, 0.99)), 2)
    profile["extraction"] = {"use_json_ld": bool(with_jsonld), "use_llm_fallback": True}
    log.info("inspect.done", source=source_id, profile=profile)
    return InspectionReport(profile, notes, errors, detail_urls)
