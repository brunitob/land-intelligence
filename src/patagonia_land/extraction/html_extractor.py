"""Extractor HTML genérico: título, precio, superficie, tablas de características, fotos, mapa."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft
from patagonia_land.intelligence.normalization import (
    AreaResult,
    detect_property_type,
    parse_area,
    parse_price,
)

LABEL_PRICE = re.compile(r"\b(precio|valor|price)\b", re.IGNORECASE)
LABEL_AREA = re.compile(r"\b(superficie|sup\.?|terreno|lote|medidas|area|área|hect[aá]reas|tamaño)\b"
                        r"|^(m2|m²|mts2?)\s+totales?$", re.IGNORECASE)
LABEL_BUILT = re.compile(r"\b(cubiert[ao]s?|construid[ao]s?|edificad[ao]s?)\b", re.IGNORECASE)
LABEL_UNIT = re.compile(r"(m2|m²|mts2?|ha|has|hect[aá]reas)\b|m²", re.IGNORECASE)
NUMERIC_VALUE = re.compile(r"[\d][\d.,]*\s*(m2|m²|mts2?|ha|has)?", re.IGNORECASE)
LABEL_LOCATION = re.compile(r"\b(ubicaci[oó]n|localidad|zona|barrio|direcci[oó]n|ciudad)\b", re.IGNORECASE)
LABEL_ID = re.compile(r"\b(c[oó]digo|ref(erencia)?|id|cod\.?)\b", re.IGNORECASE)
LABEL_TYPE = re.compile(r"^(tipo( de (propiedad|inmueble))?|categor[ií]a)$", re.IGNORECASE)
LABEL_OPERATION = re.compile(r"^(operaci[oó]n|tipo de operaci[oó]n)$", re.IGNORECASE)
LABEL_AVAILABLE = re.compile(r"^(disponible|estado|disponibilidad)$", re.IGNORECASE)
KNOWN_LABEL = re.compile(r"^(precio|valor|superficie( total| del terreno)?|direcci[oó]n|ubicaci[oó]n|localidad|zona|"
                         r"barrio|tipo|operaci[oó]n|disponible|estado|c[oó]digo|ref(erencia)?|id)$", re.IGNORECASE)
CHROME_CLASSES = {"footer", "site-footer", "main-footer", "header", "site-header", "main-header", "navbar", "nav",
                  "topbar", "top-bar", "sidebar", "widget", "site-info", "contact-info", "copyright"}
GENERIC_TITLE = re.compile(r"^(listado de propiedades|propiedades?|detalle( de la propiedad)?|ficha|inmuebles?|"
                           r"resultados?|en venta|venta|home|inicio)$", re.IGNORECASE)
STATUS_RE = re.compile(r"\b(vendid[oa]|reservad[oa]|señad[oa]|no disponible)\b", re.IGNORECASE)
COORD_RE = re.compile(r"(-4[0-5]\.\d{3,})\s*,\s*(-7[0-3]\.\d{3,})")
SKIP_IMG = re.compile(r"(logo|icon|avatar|whatsapp|banner|sprite|placeholder|loader|flag|marker|pixel)", re.IGNORECASE)


def _label_value_pairs(page: Page) -> list[tuple[str, str]]:
    """Pares etiqueta→valor de tablas, listas de definición y 'Etiqueta: valor' en <li>/<p>."""
    soup = page.soup
    pairs: list[tuple[str, str]] = []
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                pairs.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) == 2:
            pairs.append((cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True)))
    for el in soup.find_all(["li", "p", "div", "span"]):
        if not isinstance(el, Tag) or len(el.find_all(True)) > 4:
            continue
        txt = el.get_text(" ", strip=True)
        if 3 < len(txt) < 120 and ":" in txt:
            k, v = txt.split(":", 1)
            if 1 < len(k) < 40 and v.strip():
                pairs.append((k.strip(), v.strip()))
    # <button>M² Totales <span class="number">2683</span></button>: etiqueta suelta + número en el último hijo.
    for el in soup.find_all(["button", "li", "div"]):
        if not 1 <= len(el.find_all(True)) <= 4:
            continue
        last = el.find_all(["span", "strong", "b"], recursive=False)
        if not last:
            continue
        v = last[-1].get_text(" ", strip=True)
        txt = el.get_text(" ", strip=True)
        if v and NUMERIC_VALUE.fullmatch(v) and txt.endswith(v):
            k = txt[: -len(v)].strip()
            if 1 < len(k) < 30 and ":" not in k:
                pairs.append((k, v))
    # <span class="label">Dirección</span><div>Trevelin</div> (etiqueta conocida sin dos puntos)
    for el in soup.find_all(["span", "strong", "b", "label", "dt", "th", "div"]):
        if len(el.find_all(True)) > 1:
            continue
        k = el.get_text(" ", strip=True).rstrip(":").strip()
        if not KNOWN_LABEL.match(k):
            continue
        sib = el.find_next_sibling()
        if sib is not None and len(sib.find_all(True)) <= 3:
            v = sib.get_text(" ", strip=True)
            if v and len(v) < 150:
                pairs.append((k, v))
    return pairs


def _area_from_pair(k: str, v: str) -> AreaResult | None:
    """Superficie de un par etiqueta→valor; la unidad puede estar en la etiqueta ("M² Totales" → "2683")."""
    ar = parse_area(v)
    if ar is None and (u := LABEL_UNIT.search(k)) and NUMERIC_VALUE.fullmatch(v.strip()):
        ar = parse_area(f"{v.strip()} {u.group(0)}")
    return ar


def _is_chrome(el: Tag) -> bool:
    """Elemento dentro de header/footer/nav/aside: datos de la inmobiliaria, no del inmueble."""
    for parent in el.parents:
        if parent.name in ("header", "footer", "nav", "aside"):
            return True
        classes = {c.lower() for c in parent.get("class", [])} if hasattr(parent, "get") else set()
        ident = (parent.get("id") or "").lower() if hasattr(parent, "get") else ""
        if classes & CHROME_CLASSES or ident in CHROME_CLASSES:
            return True
    return False


def _title(page: Page) -> tuple[str | None, str]:
    """h1 salvo que sea genérico ('Listado de propiedades'); si no, el primer encabezado específico."""
    soup = page.soup
    h1 = soup.find("h1")
    h1t = h1.get_text(" ", strip=True) if h1 else ""
    if h1t and not GENERIC_TITLE.match(h1t):
        return h1t, "h1"
    for h in soup.find_all(["h2", "h3", "h4"]):
        if _is_chrome(h):
            continue
        t = h.get_text(" ", strip=True)
        if 4 < len(t) < 160 and not GENERIC_TITLE.match(t) and not parse_price(t) \
                and not re.match(r"^(descripci[oó]n|caracter[ií]sticas|ubicaci[oó]n|contact|similares|mapa)", t, re.I):
            return t, h.name
    return (h1t or None), "h1"


ESCAPED_HTML_RE = re.compile(r"</?(?:p|div|br|span|strong|b|i|em|ul|li)\b[^>]*>", re.IGNORECASE)


def _clean_text(t: str) -> str:
    """Algunos sistemas (p.ej. Tokko) publican la descripción con el HTML escapado: se le quitan las etiquetas."""
    if ESCAPED_HTML_RE.search(t):
        t = BeautifulSoup(t, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()


def _description(page: Page) -> str | None:
    soup = page.soup
    for sel in ('[itemprop="description"]', ".description", ".descripcion", "#descripcion", "#description",
                ".property-description", ".prop-description", ".entry-content", "article .content"):
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 80:
            return _clean_text(el.get_text(" ", strip=True))
    # Bloque de texto más largo dentro del contenido principal.
    best = ""
    for p in soup.find_all(["p", "div"]):
        if len(p.find_all(["div", "p", "ul", "table"])) > 0:
            continue
        t = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(t) > len(best):
            best = t
    return _clean_text(best) if len(best) > 80 else None


def _photos(page: Page) -> list[str]:
    out: list[str] = []
    for img in page.soup.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src")
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[-1].strip().split(" ")[0]
        if not src or src.startswith("data:") or SKIP_IMG.search(src):
            continue
        w = img.get("width")
        if w and str(w).isdigit() and int(w) < 120:
            continue
        out.append(urljoin(page.url, src))
    for a in page.soup.find_all("a", href=True):
        if re.search(r"\.(jpe?g|png|webp)(\?|$)", a["href"], re.IGNORECASE) and not SKIP_IMG.search(a["href"]):
            out.append(urljoin(page.url, a["href"]))
    return list(dict.fromkeys(out))[:60]


def _documents(page: Page) -> list[str]:
    return list(dict.fromkeys(
        urljoin(page.url, a["href"]) for a in page.soup.find_all("a", href=True)
        if re.search(r"\.(pdf|dwg|kmz|kml)(\?|$)", a["href"], re.IGNORECASE)
    ))[:20]


def _coordinates(page: Page) -> tuple[float, float, str] | None:
    """Coordenadas de iframes de Google Maps, links de mapas o atributos data-lat/data-lng."""
    soup = page.soup
    for el in soup.find_all(attrs={"data-lat": True}):
        if _is_chrome(el):
            continue
        lng = el.get("data-lng") or el.get("data-lon") or el.get("data-long")
        try:
            return float(el["data-lat"]), float(lng), f"data-lat={el['data-lat']}"
        except (TypeError, ValueError):
            continue
    for el in soup.find_all(["iframe", "a"]):
        src = el.get("src") or el.get("href") or ""
        if "google" not in src and "openstreetmap" not in src and "maps" not in src:
            continue
        # Links a /maps/place/<Negocio> o en header/footer son la oficina de la inmobiliaria, no el inmueble.
        if _is_chrome(el) or "/maps/place/" in src or "/maps/dir/" in src:
            continue
        q = parse_qs(urlsplit(src).query)
        for key in ("q", "ll", "center", "query", "daddr", "mlat"):
            if key in q:
                m = COORD_RE.search(q[key][0].replace("%2C", ","))
                if m:
                    return float(m.group(1)), float(m.group(2)), src[:200]
        m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", src) or re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", src)
        if m:
            return float(m.group(1)), float(m.group(2)), src[:200]
    return None


def _map_query_text(page: Page) -> str | None:
    """Texto de búsqueda de un mapa embebido (maps?q=Trevelin): sirve como referencia de ubicación."""
    for el in page.soup.find_all("iframe"):
        src = el.get("src") or ""
        if "maps" not in src or _is_chrome(el):
            continue
        q = parse_qs(urlsplit(src).query).get("q")
        if q and not COORD_RE.search(q[0]):
            return q[0][:150]
    return None


def extract_html(page: Page, d: Draft) -> None:
    m = "html"
    title, title_src = _title(page)
    if title and GENERIC_TITLE.match(title):
        d.warnings.append(f"título genérico '{title}'")
        d.offer("title", title, m, confidence=0.2)
    else:
        d.offer("title", title, m, f"<{title_src}> {title}", 0.8 if title_src == "h1" else 0.65)
    pairs = _label_value_pairs(page)
    for k, v in pairs:
        kk = k.strip().rstrip(":")
        if LABEL_TYPE.match(kk):
            ptype, ev = detect_property_type(v)
            if ptype:
                d.offer("property_type", ptype.value, m, f"{k}: {v}", 0.9)
            continue
        if LABEL_OPERATION.match(kk):
            op = "alquiler" if re.search(r"alquil", v, re.I) else "venta" if re.search(r"vent", v, re.I) else None
            d.offer("operation", op, m, f"{k}: {v}", 0.9)
            continue
        if LABEL_AVAILABLE.match(kk) and re.match(r"^(no|vendid|reservad|señad)", v.strip(), re.I):
            d.offer("status_text", "no disponible", m, f"{k}: {v}", 0.85)
            continue
        if LABEL_PRICE.search(k) and not d.has("price"):
            pr = parse_price(v)
            if pr and pr.amount:
                d.offer("price", pr.amount, m, f"{k}: {v}", 0.85)
                d.offer("currency", pr.currency, m, f"{k}: {v}", 0.8)
                d.offer("price_raw", pr.raw, m)
            elif pr and pr.on_request:
                d.offer("price_on_request", True, m, f"{k}: {v}", 0.8)
        elif LABEL_BUILT.search(k):
            ar = _area_from_pair(k, v)
            if ar:
                d.offer("built_area_m2", ar.m2, m, f"{k}: {v}", 0.8)
        elif LABEL_AREA.search(k) and not d.has("area_m2"):
            ar = _area_from_pair(k, v)
            if ar:
                d.offer("area_m2", ar.m2, m, f"{k}: {v}", 0.85)
                d.offer("area_original_unit", ar.unit, m)
                d.offer("area_raw", ar.raw, m)
        elif LABEL_LOCATION.search(k) and len(v) < 120:
            d.offer("location_text", v, m, f"{k}: {v}", 0.75)
        elif LABEL_ID.search(k) and len(v) < 40 and re.search(r"\d", v):
            d.offer("external_listing_id", v, m, f"{k}: {v}", 0.7)

    # Precio en título / zona destacada / texto principal (regex), con menor confianza.
    if not d.has("price"):
        for el in page.soup.select('[class*="price"], [class*="precio"], [itemprop="price"]'):
            pr = parse_price(el.get_text(" ", strip=True) or el.get("content", ""))
            if pr and pr.amount:
                d.offer("price", pr.amount, "html", el.get_text(" ", strip=True)[:120], 0.8)
                d.offer("currency", pr.currency, "html", confidence=0.75)
                d.offer("price_raw", pr.raw, "html")
                break
    if not d.has("price"):
        for text, conf in ((page.title, 0.7), (page.main_text, 0.55)):
            pr = parse_price(text)
            if pr and pr.amount:
                d.offer("price", pr.amount, "regex", pr.raw, conf)
                d.offer("currency", pr.currency, "regex", pr.raw, conf)
                d.offer("price_raw", pr.raw, "regex")
                break
            if pr and pr.on_request:
                d.offer("price_on_request", True, "regex", pr.raw, 0.6)
    if not d.has("area_m2"):
        for text, conf in ((page.title, 0.75), (d.get("description"), 0.6), (page.main_text, 0.5)):
            ar = parse_area(text)
            if ar:
                d.offer("area_m2", ar.m2, "regex", ar.raw, conf)
                d.offer("area_original_unit", ar.unit, "regex")
                d.offer("area_raw", ar.raw, "regex")
                break

    d.offer("description", _description(page), m, confidence=0.7)
    # Metadatos de página como último recurso (suelen ser genéricos del sitio).
    meta = page.meta
    og_title = meta.get("og:title")
    if og_title and not GENERIC_TITLE.match(og_title.strip()):
        d.offer("title", og_title, "meta", confidence=0.5)
    d.offer("description", meta.get("og:description") or meta.get("description"), "meta", confidence=0.4)
    d.offer("photos", _photos(page), m, confidence=0.7)
    d.offer("documents", _documents(page), m, confidence=0.7)

    d.offer("location_text", _map_query_text(page), "html", confidence=0.6)
    coords = _coordinates(page)
    if coords:
        d.offer("latitude", coords[0], "html", coords[2], 0.75)
        d.offer("longitude", coords[1], "html", coords[2], 0.75)
        d.offer("geo_precision", "exact", "html", coords[2], 0.6)

    st = STATUS_RE.search(d.get("title") or "") or STATUS_RE.search(page.main_text[:600])
    if st:
        d.offer("status_text", st.group(1).lower(), "regex", st.group(0), 0.6)

    ptype, ev = detect_property_type(d.get("title"), d.get("description"))
    if ptype:
        d.offer("property_type", ptype.value, "regex", ev, 0.75)
    if d.get("price_raw") and re.search(r"/\s*mes|mensual|por mes", page.main_text[:3000], re.I):
        d.offer("operation", "alquiler", "regex", "precio por mes", 0.7)
    op = re.search(r"\b(venta|vende|alquiler|alquila)\b", ((d.get("title") or "") + " " + page.main_text[:500]).lower())
    if op:
        d.offer("operation", "alquiler" if op.group(1).startswith("alquil") else "venta", "regex", op.group(0), 0.6)


def extract_with_selectors(page: Page, d: Draft, selectors: dict[str, str]) -> None:
    """Adaptador por selectores del SiteProfile (overrides manuales o perfiles validados)."""
    soup = page.soup
    m = "selector"

    def text(key: str) -> str | None:
        sel = selectors.get(key)
        el = soup.select_one(sel) if sel else None
        return el.get_text(" ", strip=True) if el else None

    d.offer("title", text("title"), m, confidence=0.95)
    if (t := text("price")):
        pr = parse_price(t)
        if pr and pr.amount:
            d.offer("price", pr.amount, m, t, 0.95)
            d.offer("currency", pr.currency, m, t, 0.9)
            d.offer("price_raw", pr.raw, m)
        elif pr and pr.on_request:
            d.offer("price_on_request", True, m, t, 0.9)
    if (t := text("area")):
        ar = parse_area(t)
        if ar:
            d.offer("area_m2", ar.m2, m, t, 0.95)
            d.offer("area_original_unit", ar.unit, m)
    d.offer("description", text("description"), m, confidence=0.95)
    d.offer("location_text", text("location"), m, confidence=0.9)
    if selectors.get("photos"):
        imgs = [urljoin(page.url, i.get("data-src") or i.get("src") or i.get("href", ""))
                for i in soup.select(selectors["photos"])]
        d.offer("photos", [i for i in imgs if i], m, confidence=0.95)
