"""Canonicalización de URLs y control de parámetros (evita loops y URLs infinitas)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid",
    "ref", "share", "s_id", "_ga", "mc_cid", "mc_eid", "replytocom",
}
# Parámetros que sí cambian la página (paginación / identidad de ficha).
MEANINGFUL_PARAMS = {"page", "pagina", "pag", "p", "paged", "pg", "offset", "start", "id", "propiedad", "prop",
                     "ficha", "codigo", "cod", "property_id", "tipo", "type", "operacion", "categoria", "category"}
MAX_QUERY_PARAMS = 4

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".mp4", ".mp3", ".css", ".js",
    ".ico", ".woff", ".woff2", ".ttf", ".xml.gz", ".doc", ".docx", ".xls", ".xlsx", ".avif",
)


def canonicalize(url: str, base: str | None = None) -> str | None:
    """Devuelve URL canónica o None si no es navegable (mailto, js, ancla, archivo binario)."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("mailto:", "tel:", "javascript:", "whatsapp:", "#", "data:")):
        return None
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    path = parts.path or "/"
    if path.lower().endswith(SKIP_EXTENSIONS):
        return None
    # Normaliza "//" y barra final (excepto raíz).
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in TRACKING_PARAMS]
    query.sort()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def same_site(url: str, base_url: str) -> bool:
    a = urlsplit(url).netloc.lower().removeprefix("www.")
    b = urlsplit(base_url).netloc.lower().removeprefix("www.")
    return a == b


def is_crawlable_query(url: str) -> bool:
    """Rechaza combinaciones de filtros/búsqueda que generan espacios infinitos."""
    params = parse_qsl(urlsplit(url).query)
    if len(params) > MAX_QUERY_PARAMS:
        return False
    for k, _ in params:
        kl = k.lower()
        if kl in ("orderby", "order", "sort", "orden", "view", "vista", "lang", "currency", "moneda"):
            return False
    return True


PATH_PAGE_RE = re.compile(r"/(page|pagina|pag)/(\d+)/?$", re.IGNORECASE)


def page_param(url: str) -> int | None:
    """Número de página por query (?page=2) o por path (/page/2)."""
    parts = urlsplit(url)
    for k, v in parse_qsl(parts.query):
        if k.lower() in ("page", "pagina", "pag", "p", "paged", "pg") and v.isdigit():
            return int(v)
    m = PATH_PAGE_RE.search(parts.path)
    return int(m.group(2)) if m else None
