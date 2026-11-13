"""Detección del esquema de paginación y generación de la página siguiente."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from patagonia_land.crawling.page import Page

PAGE_PARAMS = ("page", "pagina", "pag", "p", "paged", "pg")
PATH_PAGE_RE = re.compile(r"/(page|pagina|pag)/(\d+)/?$", re.IGNORECASE)


def detect_pagination(page: Page) -> dict[str, Any]:
    """Infere el tipo de paginación de una página de listado."""
    for link in page.links + page.next_links:
        q = dict(parse_qsl(urlsplit(link).query))
        for p in PAGE_PARAMS:
            if p in q and q[p].isdigit():
                return {"type": "query_parameter", "parameter": p}
        m = PATH_PAGE_RE.search(urlsplit(link).path)
        if m:
            return {"type": "path_segment", "segment": m.group(1)}
    if page.next_links:
        return {"type": "next_link"}
    if page.has_load_more:
        return {"type": "load_more"}
    return {"type": "none"}


def current_page_number(url: str, pagination: dict[str, Any]) -> int:
    if pagination.get("type") == "query_parameter":
        v = dict(parse_qsl(urlsplit(url).query)).get(pagination["parameter"])
        return int(v) if v and v.isdigit() else 1
    if pagination.get("type") == "path_segment":
        m = PATH_PAGE_RE.search(urlsplit(url).path)
        return int(m.group(2)) if m else 1
    return 1


def build_page_url(url: str, pagination: dict[str, Any], number: int) -> str | None:
    parts = urlsplit(url)
    if pagination.get("type") == "query_parameter":
        q = dict(parse_qsl(parts.query))
        q[pagination["parameter"]] = str(number)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(q.items())), ""))
    if pagination.get("type") == "path_segment":
        seg = pagination.get("segment", "page")
        base = PATH_PAGE_RE.sub("", parts.path).rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, f"{base}/{seg}/{number}", parts.query, ""))
    return None
