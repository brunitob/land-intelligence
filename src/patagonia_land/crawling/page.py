"""Parseo de una página HTML una sola vez y señales reutilizables (links, JSON-LD, tarjetas repetidas)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from bs4 import BeautifulSoup, Tag

from patagonia_land.crawling.urls import canonicalize, same_site

PRICE_RE = re.compile(
    r"(?:(?:U\$?S|USD|US\$|u\$s|D[oó]lares|\$|ARS|AR\$)\s*[\d][\d.,]{2,}|[\d][\d.,]{3,}\s*(?:USD|U\$S|d[oó]lares))",
    re.IGNORECASE,
)
AREA_RE = re.compile(r"\d[\d.,]*\s*(?:m2|m²|mts2?|metros\s+cuadrados|ha\b|has\b|hect[aá]reas?)", re.IGNORECASE)
LAND_WORDS_RE = re.compile(r"\b(terrenos?|lotes?|chacras?|campos?|fracci[oó]n|parcela|estancia|hect[aá]reas?)\b",
                           re.IGNORECASE)

DETAIL_URL_TOKENS = ("propiedad", "propiedades/", "inmueble", "ficha", "detalle", "property", "listing",
                     "terreno", "lote", "chacra", "campo", "venta/", "/p/", "aviso")
LIST_URL_TOKENS = ("propiedades", "listado", "resultados", "buscar", "busqueda", "search", "catalogo",
                   "venta", "terrenos", "lotes", "campos", "chacras", "inmuebles", "categoria", "category", "tipo")
OTHER_URL_TOKENS = ("contacto", "contact", "nosotros", "about", "quienes", "blog", "noticias", "news",
                    "login", "registro", "carrito", "cart", "politica", "privacidad", "terminos", "tasaciones",
                    "servicios", "faq", "wp-admin", "wp-login", "feed", "tag/", "author/", "alquiler")
LISTING_JSONLD_TYPES = {"realestatelisting", "product", "offer", "residence", "singlefamilyresidence",
                        "place", "landform", "house", "apartment", "accommodation", "realestateagent__no"}


def _flatten_jsonld(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(data, list):
        for d in data:
            out.extend(_flatten_jsonld(d))
    elif isinstance(data, dict):
        if "@graph" in data:
            out.extend(_flatten_jsonld(data["@graph"]))
        out.append(data)
    return out


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type", [])
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


@dataclass
class CardGroup:
    selector: str
    count: int
    links: list[str]
    with_price: int


@dataclass
class Page:
    url: str
    html: str
    base_url: str
    _soup: BeautifulSoup | None = field(default=None, repr=False)

    @property
    def soup(self) -> BeautifulSoup:
        if self._soup is None:
            self._soup = BeautifulSoup(self.html, "lxml")
        return self._soup

    @cached_property
    def title(self) -> str:
        h1 = self.soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(" ", strip=True)
        return self.soup.title.get_text(strip=True) if self.soup.title else ""

    @cached_property
    def main_text(self) -> str:
        soup = BeautifulSoup(self.html, "lxml")
        for t in soup(["script", "style", "noscript", "svg"]):
            t.decompose()
        total = len((soup.body or soup).get_text(" ", strip=True))
        for t in soup(["header", "footer", "nav", "form"]):
            # Un <header> sin cerrar puede envolver toda la página: no se descarta un bloque con la mayor parte
            # del texto.
            if t.decomposed or len(t.get_text(" ", strip=True)) > 0.5 * total:
                continue
            t.decompose()
        body = soup.body or soup
        body_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
        # <main>/<article> si concentra el contenido; algunos temas dejan uno vacío o solo con el título.
        for cand in (soup.find("main"), soup.find("article")):
            if cand is not None:
                t = re.sub(r"\s+", " ", cand.get_text(" ", strip=True))
                if len(t) >= 400 or len(t) >= 0.5 * len(body_text):
                    return t
        return body_text

    @cached_property
    def jsonld(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for script in self.soup.find_all("script", type=lambda v: v and "ld+json" in v):
            raw = script.string or script.get_text() or ""
            try:
                nodes.extend(_flatten_jsonld(json.loads(raw.strip())))
            except (json.JSONDecodeError, ValueError):
                continue
        return nodes

    @cached_property
    def jsonld_listing_nodes(self) -> list[dict[str, Any]]:
        return [n for n in self.jsonld if _types(n) & LISTING_JSONLD_TYPES]

    @cached_property
    def meta(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for m in self.soup.find_all("meta"):
            key = m.get("property") or m.get("name") or m.get("itemprop")
            if key and m.get("content"):
                out.setdefault(key.lower(), m["content"].strip())
        link = self.soup.find("link", rel="canonical")
        if link and link.get("href"):
            out["canonical"] = link["href"]
        return out

    @cached_property
    def canonical_url(self) -> str:
        c = canonicalize(self.meta.get("canonical", ""), self.url)
        return c if c and same_site(c, self.base_url) else (canonicalize(self.url) or self.url)

    @cached_property
    def links(self) -> list[str]:
        seen: dict[str, None] = {}
        for a in self.soup.find_all("a", href=True):
            c = canonicalize(a["href"], self.url)
            if c and same_site(c, self.base_url):
                seen.setdefault(c, None)
        return list(seen)

    @cached_property
    def next_links(self) -> list[str]:
        out = []
        for el in self.soup.select('a[rel~="next"], link[rel~="next"]'):
            c = canonicalize(el.get("href", ""), self.url)
            if c:
                out.append(c)
        for a in self.soup.find_all("a", href=True):
            txt = a.get_text(" ", strip=True).lower()
            cls = " ".join(a.get("class", [])).lower()
            if txt in ("siguiente", "next", "›", "»", ">", "siguiente »", "siguientes") or "next" in cls:
                c = canonicalize(a["href"], self.url)
                if c:
                    out.append(c)
        return list(dict.fromkeys(out))

    @cached_property
    def has_load_more(self) -> bool:
        for el in self.soup.find_all(["button", "a"]):
            t = el.get_text(" ", strip=True).lower()
            if t in ("ver más", "ver mas", "cargar más", "cargar mas", "load more", "mostrar más", "más propiedades"):
                return True
        return False

    @cached_property
    def price_mentions(self) -> int:
        return len(PRICE_RE.findall(self.main_text))

    @cached_property
    def image_count(self) -> int:
        return len(self.soup.find_all("img"))

    @cached_property
    def card_groups(self) -> list[CardGroup]:
        """Detecta grupos de elementos hermanos repetidos con link (tarjetas de propiedades)."""
        groups: dict[str, list[Tag]] = defaultdict(list)
        for el in self.soup.find_all(["div", "article", "li", "section", "a"]):
            classes = [c for c in el.get("class", []) if not re.search(r"\d", c)]
            if not classes or el.parent is None:
                continue
            key = f"{el.name}." + ".".join(sorted(classes)[:3])
            groups[key].append(el)
        out: list[CardGroup] = []
        for selector, els in groups.items():
            if len(els) < 2:
                continue
            links: list[str] = []
            with_price = 0
            for el in els:
                # link dentro de la tarjeta, o la tarjeta envuelta en un <a> (p.ej. Tokko: <a><div.propiedad>)
                a = (el if el.name == "a" and el.get("href") else el.find("a", href=True)
                     or el.find_parent("a", href=True))
                if not a:
                    continue
                c = canonicalize(a["href"], self.url)
                if c and same_site(c, self.base_url):
                    links.append(c)
                if PRICE_RE.search(el.get_text(" ", strip=True)) or AREA_RE.search(el.get_text(" ", strip=True)):
                    with_price += 1
            uniq = list(dict.fromkeys(links))
            if len(uniq) >= 3 or (len(uniq) == 2 and with_price >= 2):
                out.append(CardGroup(selector=selector, count=len(els), links=uniq, with_price=with_price))
        out.sort(key=lambda g: (g.with_price, len(g.links)), reverse=True)
        return out

    @cached_property
    def property_card_group(self) -> CardGroup | None:
        for g in self.card_groups:
            if g.with_price >= max(2, int(0.5 * len(g.links))):
                return g
        return None

    @cached_property
    def script_heavy(self) -> bool:
        """Heurística: HTML mínimo + bundle JS (SPA) => requiere renderizado."""
        text_len = len(self.main_text)
        scripts = len(self.soup.find_all("script"))
        markers = ('id="root"', 'id="app"', "id=\"__next\"", "ng-app", "data-reactroot", "__NUXT__")
        return text_len < 400 and (scripts >= 3 or any(m in self.html for m in markers))


def url_token_score(url: str, tokens: tuple[str, ...]) -> int:
    u = url.lower()
    return sum(1 for t in tokens if t in u)


ID_PARAMS = ("id", "propiedad", "prop", "ficha", "codigo", "cod", "property_id", "pid", "p_id")


def path_has_id(url: str) -> bool:
    from urllib.parse import parse_qsl, urlsplit

    from patagonia_land.crawling.urls import page_param

    if page_param(url):
        return False
    parts = urlsplit(url)
    segs = [s for s in parts.path.split("/") if s]
    last = segs[-1] if segs else ""
    if any(k.lower() in ID_PARAMS and v.strip() for k, v in parse_qsl(parts.query)):
        return True
    if any(re.fullmatch(r"\d+", s) for s in segs[1:]):
        return True
    return bool(re.search(r"\d{2,}", last)) or (last.count("-") >= 3)


def most_common_prefixes(urls: list[str], top: int = 5) -> list[str]:
    from urllib.parse import parse_qsl, urlsplit

    c: Counter[str] = Counter()
    for u in urls:
        parts = urlsplit(u)
        segs = [s for s in parts.path.split("/") if s]
        if len(segs) >= 2:
            c["/" + segs[0] + "/"] += 1
        elif len(segs) == 1:
            ids = [k for k, _ in parse_qsl(parts.query) if k.lower() in ID_PARAMS]
            if ids:
                c[f"/{segs[0]}?{ids[0]}="] += 1
    return [p for p, n in c.most_common(top) if n >= 2]
