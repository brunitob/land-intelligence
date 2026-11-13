"""Clasificador de páginas: URL + contenido + DOM + datos estructurados (+ fallback semántico LLM).

Una ruta `/propiedad/123` es una señal, no una prueba: se combinan señales con puntajes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from patagonia_land.crawling.page import (
    AREA_RE,
    DETAIL_URL_TOKENS,
    LAND_WORDS_RE,
    LIST_URL_TOKENS,
    OTHER_URL_TOKENS,
    PRICE_RE,
    Page,
    path_has_id,
    url_token_score,
)
from patagonia_land.crawling.urls import page_param


class PageType(StrEnum):
    PROPERTY_DETAIL = "PROPERTY_DETAIL"
    PROPERTY_LIST = "PROPERTY_LIST"
    PAGINATION = "PAGINATION"
    CATEGORY = "CATEGORY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@dataclass
class Classification:
    page_type: PageType
    confidence: float
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


# Páginas de error servidas con HTTP 200 ("soft 404"): nunca son fichas.
SOFT_404_RE = re.compile(
    r"\b(propiedad|p[aá]gina|inmueble|aviso|publicaci[oó]n|recurso)\s+no\s+(encontrad[ao]|existe|disponible)"
    r"|\b(page|property)\s+not\s+found\b|^\s*(error\s*)?404\b|\bno\s+se\s+encontr[oó]\s+la\s+(propiedad|p[aá]gina)",
    re.IGNORECASE,
)
# Segmentos de taxonomía (WordPress y similares): agrupan fichas, no son fichas aunque tengan slug.
TAXONOMY_SEGMENTS = {"property_location", "property_city", "property_area", "property_category",
                     "property_action_category", "property_type", "property-type", "property_status",
                     "property-status", "property-city", "property-location", "category", "categoria", "tag",
                     "etiqueta", "tipo-propiedad", "ubicacion-propiedad", "author"}


def is_soft_404(page: Page) -> bool:
    title = page.soup.title.get_text(" ", strip=True) if page.soup.title else ""
    return bool(SOFT_404_RE.search(page.title) or SOFT_404_RE.search(title))


def is_taxonomy_url(url: str) -> bool:
    segs = [s.lower() for s in urlsplit(url).path.split("/") if s]
    return any(s in TAXONOMY_SEGMENTS for s in segs[:-1])


def classify_url_only(url: str, profile: dict[str, Any] | None = None) -> Classification:
    """Pre-clasificación sin descargar (para priorizar la cola)."""
    profile = profile or {}
    u = url.lower()
    for pat in profile.get("listing_patterns", []):
        if pat and pat.lower() in u and path_has_id(url):
            return Classification(PageType.PROPERTY_DETAIL, 0.6, [f"patrón de perfil {pat}"])
    if url_token_score(u, OTHER_URL_TOKENS):
        return Classification(PageType.OTHER, 0.5, ["token URL de página no-propiedad"])
    if page_param(url):
        return Classification(PageType.PAGINATION, 0.5, ["parámetro de página"])
    if is_taxonomy_url(url):
        return Classification(PageType.CATEGORY, 0.4, ["URL de taxonomía"])
    if url_token_score(u, DETAIL_URL_TOKENS) and path_has_id(url):
        return Classification(PageType.PROPERTY_DETAIL, 0.45, ["token URL + id/slug"])
    if url_token_score(u, LIST_URL_TOKENS):
        return Classification(PageType.PROPERTY_LIST, 0.35, ["token URL de listado"])
    return Classification(PageType.UNKNOWN, 0.0)


def classify_page(page: Page, profile: dict[str, Any] | None = None) -> Classification:
    profile = profile or {}
    detail = 0.0
    listing = 0.0
    other = 0.0
    reasons: list[str] = []
    url = page.url.lower()

    if is_soft_404(page):
        return Classification(PageType.OTHER, 0.9, ["página de error servida con HTTP 200 (soft 404)"])

    # --- Datos estructurados
    if page.jsonld_listing_nodes:
        has_offer = any("offers" in n or "price" in n for n in page.jsonld_listing_nodes)
        if len(page.jsonld_listing_nodes) == 1 or has_offer and len(page.jsonld_listing_nodes) <= 2:
            detail += 3
            reasons.append("JSON-LD de inmueble/oferta único")
        elif len(page.jsonld_listing_nodes) >= 3:
            listing += 2
            reasons.append(f"{len(page.jsonld_listing_nodes)} nodos JSON-LD (listado)")
    if any(n.get("@type") in ("ItemList", "SearchResultsPage") for n in page.jsonld):
        listing += 2
        reasons.append("JSON-LD ItemList")
    og_type = page.meta.get("og:type", "")
    if og_type in ("product", "realestate", "place", "og:product"):
        detail += 1
        reasons.append(f"og:type={og_type}")

    # --- URL
    for pat in profile.get("listing_patterns", []):
        if pat and pat.lower() in url:
            detail += 1.5
            reasons.append(f"coincide patrón de perfil {pat}")
            break
    if url_token_score(url, DETAIL_URL_TOKENS) and path_has_id(page.url):
        detail += 1
        reasons.append("URL con token de ficha e id/slug")
    if url_token_score(url, LIST_URL_TOKENS) and not path_has_id(page.url):
        listing += 0.75
    if page_param(page.url):
        listing += 2
        reasons.append("URL paginada")
    if url_token_score(url, OTHER_URL_TOKENS):
        other += 2
        reasons.append("URL de sección institucional")

    # --- Contenido / DOM
    group = page.property_card_group
    # Pocas tarjetas en una ficha con datos estructurados o mucho texto = "propiedades similares", no listado.
    if group and len(group.links) <= 3 and (page.jsonld_listing_nodes or len(page.main_text) > 2500):
        reasons.append("tarjetas pocas: probablemente 'similares'")
        group = None
    if group:
        listing += 2 + min(len(group.links), 20) / 10
        reasons.append(f"{len(group.links)} tarjetas repetidas con precio/superficie ({group.selector})")
    title_has_price = bool(PRICE_RE.search(page.title))
    text = page.main_text
    prices = page.price_mentions
    areas = len(AREA_RE.findall(text))
    if 1 <= prices <= 4 and not group:
        detail += 1.5
        reasons.append(f"{prices} menciones de precio (ficha)")
    elif prices > 4 and group:
        listing += 1
    if areas >= 1 and not group:
        detail += 1
        reasons.append("superficie mencionada")
    if len(text) > 600 and not group:
        detail += 0.5
    if LAND_WORDS_RE.search(page.title):
        detail += 0.5 if not group else 0
    if title_has_price:
        detail += 0.5
    if page.image_count >= 6 and not group:
        detail += 0.5
        reasons.append("galería de fotos")
    if page.next_links or page.has_load_more:
        listing += 1
        reasons.append("controles de paginación/carga")
    if not prices and not areas and not group:
        other += 1

    scores = {"detail": detail, "list": listing, "other": other}
    best = max(scores, key=lambda k: scores[k])
    top = scores[best]
    second = sorted(scores.values())[-2]
    if top < 1.5:
        return Classification(PageType.UNKNOWN, 0.2, reasons, scores)
    confidence = round(min(0.99, 0.5 + (top - second) / (top + 2)), 2)
    if best == "detail" and is_taxonomy_url(page.url):
        # Archivo de taxonomía con una sola tarjeta: se recorre como categoría, no se guarda como ficha.
        return Classification(PageType.CATEGORY, 0.5, reasons + ["URL de taxonomía"], scores)
    if best == "detail":
        pt = PageType.PROPERTY_DETAIL
    elif best == "list":
        pt = PageType.PAGINATION if page_param(page.url) else PageType.PROPERTY_LIST
        if re.search(r"categor|tipo|/(terrenos|lotes|campos|chacras)$", url) and pt == PageType.PROPERTY_LIST:
            pt = PageType.CATEGORY
    else:
        pt = PageType.OTHER
    return Classification(pt, confidence, reasons, scores)
