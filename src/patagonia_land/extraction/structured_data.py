"""Extracción desde JSON-LD, microdatos y metadatos (OpenGraph, geo.*)."""

from __future__ import annotations

import re
from typing import Any

from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft
from patagonia_land.intelligence.normalization import parse_area, parse_number


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _as_float(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return parse_number(v)
    return None


def _coord(v: Any) -> float | None:
    """Coordenadas decimales: float() directo (parse_number confundiría '-41.151' con miles)."""
    try:
        return float(str(v).strip().replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _images(v: Any) -> list[str]:
    out = []
    for item in v if isinstance(v, list) else [v]:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("url"):
            out.append(item["url"])
    return out


def _quantity_m2(q: Any) -> tuple[float | None, str | None]:
    q = _first(q)
    if isinstance(q, dict):
        val = _as_float(q.get("value"))
        unit = str(q.get("unitCode") or q.get("unitText") or "").upper()
        if val is None:
            return None, None
        if unit in ("HAR", "HA", "HECTARE", "HECTÁREAS", "HECTAREAS"):
            return val * 10_000, "ha"
        return val, "m2"
    if isinstance(q, (str, int, float)):
        res = parse_area(str(q)) if isinstance(q, str) else None
        return (res.m2, res.unit) if res else (_as_float(q), "m2")
    return None, None


def extract_structured(page: Page, d: Draft) -> None:
    for node in page.jsonld_listing_nodes:
        m = "json_ld"
        d.offer("title", node.get("name"), m, confidence=0.9)
        d.offer("description", node.get("description"), m, confidence=0.9)
        d.offer("external_listing_id", node.get("sku") or node.get("productID") or node.get("identifier"), m)
        offers = _first(node.get("offers"))
        if isinstance(offers, dict):
            spec = _first(offers.get("priceSpecification"))
            raw_price = offers.get("price") or (spec.get("price") if isinstance(spec, dict) else None)
            price = _as_float(raw_price)
            cur = offers.get("priceCurrency")
            if price and price > 0:
                d.offer("price", price, m, f"offers.price={offers.get('price')} {cur}", 0.95)
                d.offer("currency", str(cur).upper() if cur else None, m, confidence=0.95)
            avail = str(offers.get("availability", "")).lower()
            if "soldout" in avail or "outofstock" in avail:
                d.offer("status_text", "no disponible (JSON-LD)", m, avail, 0.8)
        for key in ("lotSize", "floorSize", "area", "size"):
            m2, unit = _quantity_m2(node.get(key))
            if m2:
                target = "built_area_m2" if key == "floorSize" and node.get("lotSize") else "area_m2"
                d.offer(target, m2, m, f"{key}={node.get(key)}", 0.9)
                if target == "area_m2":
                    d.offer("area_original_unit", unit, m)
        loc = node.get("location") if isinstance(node.get("location"), dict) else {}
        geo = node.get("geo") or loc.get("geo")
        if isinstance(geo, dict):
            lat, lon = _coord(geo.get("latitude")), _coord(geo.get("longitude"))
            if lat and lon:
                d.offer("latitude", lat, m, f"geo={lat},{lon}", 0.9)
                d.offer("longitude", lon, m, f"geo={lat},{lon}", 0.9)
                d.offer("geo_precision", "exact", m, confidence=0.7)
        addr = node.get("address") or loc.get("address")
        if isinstance(addr, dict):
            d.offer("locality", addr.get("addressLocality"), m, confidence=0.85)
            d.offer("province", addr.get("addressRegion"), m, confidence=0.85)
            d.offer("address", addr.get("streetAddress"), m, confidence=0.8)
        elif isinstance(addr, str):
            d.offer("address", addr, m, confidence=0.7)
        imgs = _images(node.get("image"))
        d.offer("photos", imgs, m, f"{len(imgs)} imágenes", 0.9)
        d.offer("published_at", node.get("datePosted") or node.get("datePublished"), m)
        d.offer("updated_at", node.get("dateModified"), m)

    meta = page.meta
    if meta.get("og:image"):
        d.offer("photos", [meta["og:image"]], "meta", confidence=0.5)
    pa = meta.get("product:price:amount") or meta.get("og:price:amount")
    if pa and (val := _as_float(pa)):
        d.offer("price", val, "meta", f"product:price:amount={pa}", 0.85)
        d.offer("currency", (meta.get("product:price:currency") or meta.get("og:price:currency") or "").upper() or None,
                "meta", confidence=0.85)
    lat = meta.get("place:location:latitude") or meta.get("og:latitude")
    lon = meta.get("place:location:longitude") or meta.get("og:longitude")
    if not (lat and lon) and meta.get("geo.position"):
        parts = re.split(r"[;,]", meta["geo.position"])
        if len(parts) == 2:
            lat, lon = parts
    if lat and lon and (flat := _coord(lat)) is not None and (flon := _coord(lon)) is not None:
        d.offer("latitude", flat, "meta", f"{lat},{lon}", 0.85)
        d.offer("longitude", flon, "meta", f"{lat},{lon}", 0.85)
        d.offer("geo_precision", "exact", "meta", confidence=0.6)
