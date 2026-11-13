"""Interfaz de adaptadores de sitio.

Jerarquía: manual override → site-specific adapter → structured data → generic HTML → LLM fallback.
Un adaptador específico solo hace falta si el genérico no alcanza; se registra con @register.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft


class SiteAdapter(ABC):
    #: dominios para los que aplica (sin www)
    domains: tuple[str, ...] = ()
    #: plataformas (profile["platform"]) para las que aplica, p.ej. "tokko"
    platforms: tuple[str, ...] = ()

    @abstractmethod
    def extract(self, page: Page, draft: Draft, profile: dict[str, Any]) -> None:
        """Completa el draft con lo que el sitio permite extraer de forma específica."""


_REGISTRY: list[type[SiteAdapter]] = []


def register(cls: type[SiteAdapter]) -> type[SiteAdapter]:
    _REGISTRY.append(cls)
    return cls


def adapter_for(url: str, profile: dict[str, Any] | None = None) -> SiteAdapter | None:
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc.lower().removeprefix("www.")
    for cls in _REGISTRY:
        if host in cls.domains:
            return cls()
    platform = (profile or {}).get("platform")
    for cls in _REGISTRY:
        if platform and platform in cls.platforms:
            return cls()
    return None
