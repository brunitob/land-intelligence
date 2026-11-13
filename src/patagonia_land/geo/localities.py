"""Gazetteer de localidades/parajes del área de BRC, CPC y EQS.

Las coordenadas son centroides APROXIMADOS: una propiedad ubicada solo por localidad
recibe precision='locality' y nunca un tiempo de manejo exacto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from patagonia_land.intelligence.normalization import strip_accents


@dataclass(frozen=True)
class Locality:
    name: str
    province: str
    region: str  # bariloche | chapelco | esquel
    lat: float
    lon: float
    aliases: tuple[str, ...] = ()


LOCALITIES: list[Locality] = [
    # --- Bariloche (BRC)
    Locality("San Carlos de Bariloche", "Río Negro", "bariloche", -41.1335, -71.3103, ("bariloche",)),
    Locality("Dina Huapi", "Río Negro", "bariloche", -41.0710, -71.1583),
    Locality("Villa Llao Llao", "Río Negro", "bariloche", -41.0530, -71.5330, ("llao llao", "llao-llao")),
    Locality("Colonia Suiza", "Río Negro", "bariloche", -41.0960, -71.5040),
    Locality("Villa Los Coihues", "Río Negro", "bariloche", -41.1650, -71.4170, ("los coihues",)),
    Locality("Lago Gutiérrez", "Río Negro", "bariloche", -41.1850, -71.3900, ("villa lago gutierrez",)),
    Locality("Villa Mascardi", "Río Negro", "bariloche", -41.3470, -71.5070, ("mascardi",)),
    Locality("Villa Catedral", "Río Negro", "bariloche", -41.1680, -71.4380, ("cerro catedral",)),
    Locality("Lago Moreno", "Río Negro", "bariloche", -41.0900, -71.4700),  # sin alias "moreno": calle céntrica
    Locality("Pilcaniyeu", "Río Negro", "bariloche", -41.1240, -70.7260),
    Locality("Villa Llanquín", "Río Negro", "bariloche", -40.9050, -71.0250, ("llanquin",)),
    Locality("Villa La Angostura", "Neuquén", "bariloche", -40.7640, -71.6450, ("la angostura",)),
    Locality("El Bolsón", "Río Negro", "bariloche", -41.9640, -71.5350, ("bolson",)),
    Locality("Mallín Ahogado", "Río Negro", "bariloche", -41.8800, -71.5100, ("mallin ahogado",)),
    Locality("Ñirihuau", "Río Negro", "bariloche", -41.0880, -71.1400, ("nirihuau",)),
    Locality("Villa Traful", "Neuquén", "bariloche", -40.6550, -71.4050, ("traful",)),
    Locality("Confluencia Traful", "Neuquén", "bariloche", -40.7270, -71.0960, ("confluencia",)),
    # --- Chapelco (CPC)
    Locality("San Martín de los Andes", "Neuquén", "chapelco", -40.1572, -71.3533,
             ("san martin de los andes", "smandes", "sma", "s m andes", "s m de los andes", "san martin de los a")),
    Locality("Junín de los Andes", "Neuquén", "chapelco", -39.9510, -71.0690, ("junin de los andes",)),
    Locality("Lago Lolog", "Neuquén", "chapelco", -40.0400, -71.3900, ("lolog",)),
    Locality("Quila Quina", "Neuquén", "chapelco", -40.1700, -71.4300),
    Locality("Lago Meliquina", "Neuquén", "chapelco", -40.3500, -71.2900, ("meliquina", "villa meliquina")),
    Locality("Chapelco", "Neuquén", "chapelco", -40.1700, -71.2500, ("cerro chapelco", "loma linda")),
    Locality("Lago Hermoso", "Neuquén", "chapelco", -40.3700, -71.5200),
    Locality("Huechulafquen", "Neuquén", "chapelco", -39.7700, -71.3600, ("lago huechulafquen",)),
    Locality("Aluminé", "Neuquén", "chapelco", -39.2370, -70.9200, ("alumine",)),
    # --- Esquel (EQS)
    Locality("Esquel", "Chubut", "esquel", -42.9110, -71.3190),
    Locality("Trevelin", "Chubut", "esquel", -43.0850, -71.4640),
    Locality("Villa Futalaufquen", "Chubut", "esquel", -42.8230, -71.6490, ("futalaufquen",)),
    Locality("Aldea Escolar", "Chubut", "esquel", -43.1200, -71.5500),
    Locality("Los Cipreses", "Chubut", "esquel", -43.1900, -71.6500),
    Locality("Corcovado", "Chubut", "esquel", -43.5370, -71.4650),
    Locality("Cholila", "Chubut", "esquel", -42.5110, -71.4500),
    Locality("Epuyén", "Chubut", "esquel", -42.2300, -71.3700, ("epuyen",)),
    Locality("El Hoyo", "Chubut", "esquel", -42.0700, -71.5200),
    Locality("Lago Puelo", "Chubut", "esquel", -42.0700, -71.6000, ("puelo",)),
    Locality("Gualjaina", "Chubut", "esquel", -42.7250, -70.5400),
    Locality("Nahuel Pan", "Chubut", "esquel", -42.9700, -71.1700),
    Locality("Lago Rosario", "Chubut", "esquel", -43.2500, -71.3500),
]

PROVINCES = {"río negro": "Río Negro", "rio negro": "Río Negro", "neuquén": "Neuquén", "neuquen": "Neuquén",
             "chubut": "Chubut"}


def _norm(s: str) -> str:
    # "S.M.Andes" -> "s m andes"; guiones de slugs de URL -> espacios.
    return re.sub(r"\s+", " ", re.sub(r"[.\-_/]", " ", strip_accents(s.lower())))


_INDEX: list[tuple[re.Pattern[str], Locality, bool]] = []  # (patrón, localidad, es_nombre_completo)
for _loc in LOCALITIES:
    for _alias in (_loc.name, *_loc.aliases):
        _INDEX.append((re.compile(rf"\b{re.escape(_norm(_alias))}\b"), _loc, _alias == _loc.name))
# Alias más largos primero ("villa la angostura" antes que "angostura").
_INDEX.sort(key=lambda x: len(x[0].pattern), reverse=True)


def find_locality(*texts: str | None, region: str | None = None) -> tuple[Locality | None, str | None]:
    """Primer texto con coincidencia gana (ubicación declarada > título > descripción).

    Con `region` (la de la inmobiliaria), dentro de un mismo texto se prefiere una localidad de esa región, y
    un alias corto de OTRA región ("los coihues" existe en Bariloche y como barrio de Esquel) se ignora.
    """
    for text in texts:
        if not text:
            continue
        t = _norm(text)
        hits = []
        for pattern, loc, full in _INDEX:
            m = pattern.search(t)
            if m:
                hits.append((loc, full, m))
        if not hits:
            continue
        if region:
            same = [h for h in hits if h[0].region == region]
            other_ok = [h for h in hits if h[0].region != region and h[1]]
            hits = same or other_ok
            if not hits:
                continue
        loc, _, m = min(hits, key=lambda h: (h[2].start(), -len(h[2].group(0))))
        return loc, text[max(0, m.start() - 30): m.end() + 30]
    return None, None


def find_province(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        t = text.lower()
        for k, v in PROVINCES.items():
            if k in t:
                return v
    return None


# Bounding box amplio de la zona de interés (para descartar coordenadas absurdas).
PATAGONIA_BBOX = (-44.5, -73.0, -38.5, -69.5)  # lat_min, lon_min, lat_max, lon_max


def in_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return PATAGONIA_BBOX[0] <= lat <= PATAGONIA_BBOX[2] and PATAGONIA_BBOX[1] <= lon <= PATAGONIA_BBOX[3]


def distance_km(lat: float, lon: float, loc: Locality) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(loc.lat - lat), radians(loc.lon - lon)
    h = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(loc.lat)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


def nearest_locality(lat: float, lon: float, max_km: float = 12, region: str | None = None
                     ) -> tuple[Locality, float] | None:
    """Localidad del gazetteer más cercana a un punto (solo si está a menos de max_km)."""
    def km(a: Locality) -> float:
        return distance_km(lat, lon, a)

    pool = [loc for loc in LOCALITIES if not region or loc.region == region] or LOCALITIES
    best = min(pool, key=km)
    d = km(best)
    return (best, d) if d <= max_km else None
