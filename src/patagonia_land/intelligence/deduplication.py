"""Deduplicación entre inmobiliarias: mismo inmueble físico publicado en varias fuentes.

Solo se vinculan automáticamente coincidencias muy fuertes; los casos ambiguos van a revisión manual.
Las fichas originales, sus fuentes e historiales se conservan siempre.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

AUTO_MERGE_SCORE = 0.9
REVIEW_SCORE = 0.6


@dataclass
class ListingFeatures:
    id: int
    source_id: str
    locality: str | None
    latitude: float | None
    longitude: float | None
    geo_precision: str | None
    area_m2: float | None
    price_usd: float | None
    title: str | None
    description: str | None
    photos: list[str] = field(default_factory=list)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _photo_keys(urls: list[str]) -> set[str]:
    # Nombre de archivo sin sufijos de tamaño (-1024x768) ni extensión.
    out = set()
    for u in urls:
        name = urlsplit(u).path.rsplit("/", 1)[-1].lower()
        name = re.sub(r"(-\d+x\d+)?\.(jpe?g|png|webp)$", "", name)
        if len(name) > 6:
            out.add(name)
    return out


def _text_sim(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower()[:1500], b.lower()[:1500]).ratio()


def score_pair(a: ListingFeatures, b: ListingFeatures) -> tuple[float, dict[str, Any]]:
    if a.source_id == b.source_id:
        return 0.0, {"reason": "misma fuente"}
    reasons: dict[str, Any] = {}
    score = 0.0
    weight = 0.0

    if a.area_m2 and b.area_m2:
        diff = abs(a.area_m2 - b.area_m2) / max(a.area_m2, b.area_m2)
        s = 1.0 if diff < 0.01 else 0.7 if diff < 0.05 else 0.0
        reasons["area_diff_pct"] = round(diff * 100, 2)
        score += 0.3 * s
        weight += 0.3
        if diff > 0.2:
            return 0.0, {"reason": "superficie muy distinta", **reasons}

    exact = a.geo_precision == "exact" and b.geo_precision == "exact"
    if exact and a.latitude and b.latitude:
        dist = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        reasons["distance_m"] = round(dist)
        s = 1.0 if dist < 150 else 0.6 if dist < 600 else 0.0
        score += 0.3 * s
        weight += 0.3
    elif a.locality and b.locality:
        same = a.locality == b.locality
        reasons["same_locality"] = same
        score += 0.1 * (1.0 if same else 0.0)
        weight += 0.1
        if not same:
            return 0.0, {"reason": "localidades distintas", **reasons}

    pa, pb = _photo_keys(a.photos), _photo_keys(b.photos)
    if pa and pb:
        overlap = len(pa & pb) / min(len(pa), len(pb))
        reasons["photo_overlap"] = round(overlap, 2)
        score += 0.2 * min(1.0, overlap * 2)
        weight += 0.2

    tsim = max(_text_sim(a.description, b.description), _text_sim(a.title, b.title))
    reasons["text_similarity"] = round(tsim, 2)
    score += 0.15 * tsim
    weight += 0.15

    if a.price_usd and b.price_usd:
        pdiff = abs(float(a.price_usd) - float(b.price_usd)) / max(float(a.price_usd), float(b.price_usd))
        reasons["price_diff_pct"] = round(pdiff * 100, 2)
        score += 0.05 * (1.0 if pdiff < 0.15 else 0.0)  # inmobiliarias distintas pueden publicar precios distintos
        weight += 0.05

    final = round(score / weight, 3) if weight >= 0.45 else round(score, 3)
    return final, reasons


def decide(score: float) -> str:
    if score >= AUTO_MERGE_SCORE:
        return "auto_merged"
    if score >= REVIEW_SCORE:
        return "pending"
    return "distinct"
