"""Normalización de precio, moneda, superficie y tipo de inmueble (formatos argentinos)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from patagonia_land.extraction.schemas import PropertyType

HA_TO_M2 = 10_000


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def parse_number(raw: str) -> float | None:
    """'1.200.000' → 1200000; '1,5' → 1.5; '1.234,56' → 1234.56; '380,000' → 380000; '2.5' → 2.5."""
    s = re.sub(r"[^\d.,]", "", raw or "")
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        # El último separador es el decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", "") if len(parts) > 2 or len(parts[-1]) == 3 else s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class PriceResult:
    amount: float | None
    currency: str | None
    raw: str
    on_request: bool = False


USD_TOKENS = r"(?:U\$S|U\$D|USD|US\$|U\$|u\$s|d[oó]lares|dolares|u\.?s\.?d\.?)"
ARS_TOKENS = r"(?:ARS|AR\$|(?<![A-Za-z])\$|pesos)"  # "$" suelto, nunca el de "U$"/"US$"
PRICE_PATTERNS = [
    (re.compile(rf"{USD_TOKENS}\s*([\d][\d.,]*)\s*(millones|mil|M\b)?", re.IGNORECASE), "USD"),
    (re.compile(rf"([\d][\d.,]*)\s*(millones|mil)?\s*{USD_TOKENS}", re.IGNORECASE), "USD"),
    (re.compile(rf"{ARS_TOKENS}\s*([\d][\d.,]*)\s*(millones|mil)?", re.IGNORECASE), "ARS"),
]
# Precio unitario ("U$ 7000 ha", "USD 50 el m2", "$ 3000/m²"): no es el precio total de la propiedad.
PER_UNIT_RE = re.compile(r"^\s*(?:/|x|por|la|el|c/u|cada)?\s*(?:ha\b|has\b|hect[aá]rea|m2|m²|mts?2?\b|metro)",
                         re.IGNORECASE)
ON_REQUEST_RE = re.compile(r"consultar|a consultar|precio a convenir|consulte", re.IGNORECASE)


def parse_price(text: str | None) -> PriceResult | None:
    if not text:
        return None
    t = text.strip()
    for pattern, currency in PRICE_PATTERNS:
        for m in pattern.finditer(t):
            amount = parse_number(m.group(1))
            mult = (m.group(2) or "").lower()
            if amount is None:
                continue
            if mult == "mil":
                amount *= 1_000
            elif mult in ("millones", "m"):
                amount *= 1_000_000
            if amount < 100:  # "$ 5" o el "USD1" de relleno de algunos sistemas no es un precio
                continue
            if PER_UNIT_RE.match(t[m.end():m.end() + 20]):
                continue  # precio por ha / m²
            return PriceResult(amount, currency, m.group(0).strip())
    if ON_REQUEST_RE.search(t):
        return PriceResult(None, None, t[:80], on_request=True)
    return None


@dataclass
class AreaResult:
    m2: float
    unit: str
    raw: str


AREA_PATTERNS = [
    (re.compile(r"([\d][\d.,]*)\s*(?:ha\b|has\b|hect[aá]reas?|htas?\b)", re.IGNORECASE), "ha"),
    (re.compile(r"([\d][\d.,]*)\s*(?:m2|m²|mts2|mts\.?\s*2|mt2|metros\s+cuadrados|mts\b|m\s*2\b)", re.IGNORECASE), "m2"),
]


def parse_area(text: str | None) -> AreaResult | None:
    if not text:
        return None
    best: AreaResult | None = None
    for pattern, unit in AREA_PATTERNS:
        for m in pattern.finditer(text):
            val = parse_number(m.group(1))
            if val is None or val <= 0:
                continue
            m2 = val * HA_TO_M2 if unit == "ha" else val
            if m2 < 15:  # "2 m" de frente, etc. (hay monoambientes de ~20 m²)
                continue
            cand = AreaResult(m2, unit, m.group(0).strip())
            if best is None:
                best = cand
            break  # primera ocurrencia de cada unidad
        if best:
            return best
    return best


TYPE_KEYWORDS: list[tuple[PropertyType, tuple[str, ...]]] = [
    (PropertyType.CHACRA, ("chacra", "quinta")),
    (PropertyType.CAMPO, ("campo", "estancia", "fraccion de campo", "hectareas de campo")),
    (PropertyType.LOTE, ("lote", "lotes")),
    (PropertyType.TERRENO, ("terreno", "parcela", "fraccion")),
    (PropertyType.CABANA, ("cabana", "cabanas", "complejo")),
    (PropertyType.CASA, ("casa", "chalet", "vivienda")),
    (PropertyType.DEPARTAMENTO, ("departamento", "depto", "monoambiente", "duplex")),
    (PropertyType.LOCAL, ("local comercial", "oficina", "galpon")),
]


def detect_property_type(*texts: str | None) -> tuple[PropertyType | None, str | None]:
    """Busca primero en el título y luego en otros textos; devuelve (tipo, evidencia)."""
    for text in texts:
        if not text:
            continue
        t = strip_accents(text.lower())
        hits: list[tuple[int, PropertyType, str]] = []
        for ptype, kws in TYPE_KEYWORDS:
            for kw in kws:
                m = re.search(rf"\b{kw}\b", t)
                if m:
                    hits.append((m.start(), ptype, kw))
        if hits:
            hits.sort()
            return hits[0][1], hits[0][2]
    return None, None


def to_usd(amount: float | None, currency: str | None, ars_per_usd: float | None = None) -> float | None:
    if amount is None or currency is None:
        return None
    if currency == "USD":
        return amount
    if currency == "ARS" and ars_per_usd:
        return round(amount / ars_per_usd, 2)
    return None
