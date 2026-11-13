"""Pipeline de extracción de una ficha individual siguiendo la jerarquía de la especificación."""

from __future__ import annotations

from typing import Any

import patagonia_land.adapters.tokko  # noqa: F401  (registra el adaptador)
from patagonia_land.adapters.base import adapter_for
from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft
from patagonia_land.extraction.html_extractor import extract_html, extract_with_selectors
from patagonia_land.extraction.llm_extractor import extract_llm
from patagonia_land.extraction.schemas import ExtractedListing
from patagonia_land.extraction.structured_data import extract_structured
from patagonia_land.extraction.validation import build_listing


async def extract_listing(source_id: str, page: Page, profile: dict[str, Any] | None = None,
                          manual_overrides: dict[str, Any] | None = None,
                          use_llm: bool = True, region: str | None = None) -> ExtractedListing:
    profile = profile or {}
    manual_overrides = manual_overrides or {}
    d = Draft()

    # 1. Overrides manuales (selectores validados por una persona)
    if manual_overrides.get("selectors"):
        extract_with_selectors(page, d, manual_overrides["selectors"])
    # 2. Adaptador específico del sitio
    adapter = adapter_for(page.url, profile)
    if adapter:
        adapter.extract(page, d, profile)
    # 3. Selectores del perfil (solo si fueron validados con fichas de muestra)
    sel = profile.get("selectors") or {}
    if profile.get("selectors_validated") and any(k in sel for k in ("title", "price", "description")):
        extract_with_selectors(page, d, sel)
    # 4. Datos estructurados
    if profile.get("extraction", {}).get("use_json_ld", True):
        extract_structured(page, d)
    # 5. HTML genérico
    extract_html(page, d)
    # 6. LLM para faltantes/ambiguos
    if use_llm and profile.get("extraction", {}).get("use_llm_fallback", True):
        await extract_llm(d.get("description") or page.main_text, page.title, d)
    return build_listing(source_id, page, d, region=region)
