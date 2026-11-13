"""Clasificación textual de agua. Distingue costa, acceso, vista y cercanía.

El texto de la ficha solo puede producir `waterfront_claimed` como máximo: `waterfront_confirmed`
requiere geometrías catastrales fiables o evidencia documental (no se produce acá).
"""

from __future__ import annotations

import re

from patagonia_land.extraction.schemas import WaterClass, WaterInfo
from patagonia_land.intelligence.normalization import parse_number, strip_accents

BODY = r"(lago|laguna|rio|arroyo|mallin|vertiente|costa|ribera|playa|embalse|chorrillo|canadon con agua)"
WATER_TYPE = {"lago": "lake", "laguna": "lake", "rio": "river", "arroyo": "stream", "chorrillo": "stream",
              "vertiente": "spring", "embalse": "reservoir", "mallin": "wetland"}

NEGATION = re.compile(r"\b(sin|no tiene|no posee|no cuenta con|carece de)\b[^.,;]{0,25}$")

PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    # (clase, patrón, confianza)
    ("claimed", re.compile(r"\b(con\s+)?costa\s+(propia\s+)?(de|al|sobre\s+el|sobre\s+la|del)\s+(lago|laguna|rio|arroyo)"), 0.92),
    ("claimed", re.compile(r"\b(costa|ribera|frente)\s+(propia|privada)\b"), 0.9),
    ("claimed", re.compile(r"\bfrente\s+(al|a la)\s+(lago|laguna|rio)\b"), 0.75),
    ("claimed", re.compile(r"\b(arroyo|rio|vertiente|chorrillo)\s+(que\s+)?(atraviesa|cruza|recorre)\b"), 0.85),
    ("claimed", re.compile(r"\b(atravesad[oa]|recorrid[oa])\s+por\s+(un|el)\s+(arroyo|rio|chorrillo)\b"), 0.85),
    ("claimed", re.compile(r"\b(vertiente|arroyo)\s+propi[oa]\b"), 0.85),
    ("claimed", re.compile(r"\b(\d[\d.,]*)\s*(m|mts|metros)\s+de\s+costa\b"), 0.93),
    ("claimed", re.compile(r"\bcosta\s+de\s+(\d[\d.,]*)\s*(m|mts|metros)\b"), 0.93),
    ("access", re.compile(r"\b(acceso|bajada|salida)\s+(directo\s+|directa\s+|propio\s+|propia\s+)?(al|a la|hacia el|hacia la)\s+(lago|laguna|rio|arroyo|playa|costa)"), 0.8),
    ("access", re.compile(r"\bacceso\s+(comun|compartido)\s+al\s+(lago|rio)"), 0.75),
    ("view", re.compile(r"\bvistas?\s+(panoramicas?\s+|abiertas?\s+|privilegiadas?\s+|directas?\s+)?(al|a la|del|de la|sobre el|sobre la)\s+(lago|laguna|rio)"), 0.85),
    ("nearby", re.compile(r"\ba\s+(\d[\d.,]*)\s*(m|mts|metros|km|kms|cuadras)\s+(del|de la|de)\s+(lago|laguna|rio|arroyo|playa|costa)"), 0.8),
    ("nearby", re.compile(r"\b(cerca|cercano|proximo|proximidad|a pasos|a metros)\s+(del|de la|al|a la)\s+(lago|laguna|rio|arroyo|playa)"), 0.7),
    ("possible", re.compile(r"\b(lindero|linda|limita|colinda)\s+(con\s+)?(el|la)?\s*(lago|laguna|rio|arroyo)\b"), 0.65),
    ("possible", re.compile(r"\b(mallin|vertientes?|arroyo)\b"), 0.4),
]

NAME_RE = re.compile(r"\b(lago|laguna|rio|arroyo)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?)")
RANK = {"claimed": 5, "access": 4, "possible": 3, "nearby": 2, "view": 1}


def classify_water_text(*texts: str | None) -> WaterInfo:
    raw = " . ".join(t for t in texts if t)
    if not raw.strip():
        return WaterInfo()
    norm = strip_accents(raw.lower())
    hits: list[tuple[str, float, re.Match[str]]] = []
    for kind, pattern, conf in PATTERNS:
        for m in pattern.finditer(norm):
            if NEGATION.search(norm[max(0, m.start() - 40): m.start()]):
                continue
            hits.append((kind, conf, m))
    if not hits:
        return WaterInfo(water_class=WaterClass.UNKNOWN, confidence=0.3)

    claimed = any(k == "claimed" for k, _, _ in hits)
    access = any(k == "access" for k, _, _ in hits)
    view = any(k == "view" for k, _, _ in hits)
    best_kind, best_conf, best_m = max(hits, key=lambda h: (RANK[h[0]], h[1]))

    if claimed:
        wclass = WaterClass.WATERFRONT_CLAIMED
    elif access or best_kind == "possible" and best_conf >= 0.6:
        wclass = WaterClass.WATERFRONT_POSSIBLE
    elif best_kind == "nearby" or best_kind == "possible":
        wclass = WaterClass.WATER_NEARBY
    elif view:
        wclass = WaterClass.WATER_VIEW_ONLY
    else:
        wclass = WaterClass.UNKNOWN

    body = re.search(BODY, best_m.group(0))
    water_type = WATER_TYPE.get(body.group(1)) if body else None
    distance = None
    for kind, _, m in hits:
        if kind == "nearby":
            num = re.search(r"(\d[\d.,]*)\s*(m|mts|metros|km|kms|cuadras)", m.group(0))
            if num:
                v = parse_number(num.group(1))
                unit = num.group(2)
                if v is not None:
                    distance = v * 1000 if unit.startswith("km") else v * 100 if unit == "cuadras" else v
            break

    # Nombre del cuerpo de agua desde el texto original (con mayúsculas).
    name = None
    nm = NAME_RE.search(strip_accents(raw).replace("Rio ", "rio ").replace("Lago ", "lago "))
    if nm:
        name = f"{nm.group(1).capitalize()} {nm.group(2)}"

    start = max(0, best_m.start() - 40)
    evidence = raw[start: best_m.end() + 40].strip() if len(raw) == len(norm) else best_m.group(0)
    return WaterInfo(
        water_class=wclass,
        waterfront_claimed=True if claimed else None,
        water_access=True if access else None,
        water_view=True if view else None,
        water_type=water_type,
        water_name=name,
        distance_m_mentioned=distance,
        evidence=evidence[:240],
        confidence=round(best_conf, 2),
    )
