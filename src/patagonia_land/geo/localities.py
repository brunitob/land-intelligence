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
    zone: str = ""  # agrupación para filtrar (vacía = la propia localidad)


# Zonas: agrupan localidades y parajes para filtrar ("Villa La Angostura" incluye Puerto Manzano, etc.).
BRC_ZONE, VLA, TRAFUL, COMARCA, LINEA_SUR = ("Bariloche", "Villa La Angostura", "Traful", "Comarca Andina",
                                             "Línea Sur")
SMA, MELIQUINA, SIETE_LAGOS, JUNIN, ALUMINE = ("San Martín de los Andes", "Meliquina", "Siete Lagos",
                                               "Junín de los Andes", "Aluminé")
ESQ, TREVELIN, ALERCES, CHOLILA, CORCOVADO, MESETA_CH = ("Esquel", "Trevelin", "Los Alerces", "Cholila",
                                                         "Corcovado", "Meseta (Chubut)")

LOCALITIES: list[Locality] = [
    # --- Bariloche (BRC)
    Locality("San Carlos de Bariloche", "Río Negro", "bariloche", -41.1335, -71.3103, ("bariloche",), BRC_ZONE),
    Locality("Dina Huapi", "Río Negro", "bariloche", -41.0710, -71.1583, (), BRC_ZONE),
    Locality("Villa Llao Llao", "Río Negro", "bariloche", -41.0530, -71.5330, ("llao llao", "llao-llao"), BRC_ZONE),
    Locality("Colonia Suiza", "Río Negro", "bariloche", -41.0960, -71.5040, (), BRC_ZONE),
    Locality("Villa Los Coihues", "Río Negro", "bariloche", -41.1650, -71.4170, ("los coihues",), BRC_ZONE),
    Locality("Lago Gutiérrez", "Río Negro", "bariloche", -41.1850, -71.3900, ("villa lago gutierrez",), BRC_ZONE),
    Locality("Villa Mascardi", "Río Negro", "bariloche", -41.3470, -71.5070, ("mascardi",), BRC_ZONE),
    Locality("Villa Catedral", "Río Negro", "bariloche", -41.1680, -71.4380, ("cerro catedral",), BRC_ZONE),
    Locality("Lago Moreno", "Río Negro", "bariloche", -41.0900, -71.4700, (), BRC_ZONE),  # sin alias "moreno": calle
    Locality("Ñirihuau", "Río Negro", "bariloche", -41.0880, -71.1400, ("nirihuau",), BRC_ZONE),
    Locality("Villa Llanquín", "Río Negro", "bariloche", -40.9050, -71.0250, ("llanquin",), BRC_ZONE),
    Locality("Pilcaniyeu", "Río Negro", "bariloche", -41.1240, -70.7260, (), LINEA_SUR),
    Locality("Comallo", "Río Negro", "bariloche", -41.0300, -70.2670, (), LINEA_SUR),
    Locality("Villa La Angostura", "Neuquén", "bariloche", -40.7640, -71.6450, ("la angostura",), VLA),
    Locality("Puerto Manzano", "Neuquén", "bariloche", -40.7800, -71.5800, (), VLA),
    Locality("Correntoso", "Neuquén", "bariloche", -40.7400, -71.6400, ("lago correntoso",), VLA),
    Locality("Lago Espejo", "Neuquén", "bariloche", -40.6550, -71.7200, (), VLA),
    Locality("Villa Traful", "Neuquén", "bariloche", -40.6550, -71.4050, ("traful",), TRAFUL),
    Locality("Confluencia Traful", "Neuquén", "bariloche", -40.7270, -71.0960, ("confluencia",), TRAFUL),
    Locality("Cuyín Manzano", "Neuquén", "bariloche", -40.7700, -71.1700, ("cuyin manzano",), TRAFUL),
    Locality("El Bolsón", "Río Negro", "bariloche", -41.9640, -71.5350, ("bolson",), COMARCA),
    Locality("Mallín Ahogado", "Río Negro", "bariloche", -41.8800, -71.5100, ("mallin ahogado",), COMARCA),
    # --- Chapelco (CPC)
    Locality("San Martín de los Andes", "Neuquén", "chapelco", -40.1572, -71.3533,
             ("san martin de los andes", "smandes", "sma", "s m andes", "s m de los andes", "san martin de los a"),
             SMA),
    Locality("Lago Lolog", "Neuquén", "chapelco", -40.0400, -71.3900, ("lolog",), SMA),
    Locality("Quila Quina", "Neuquén", "chapelco", -40.1700, -71.4300, (), SMA),
    # Base del centro de esquí (con camino). Sin alias "chapelco" suelto: también nombra al aeropuerto y al golf.
    Locality("Cerro Chapelco", "Neuquén", "chapelco", -40.2560, -71.2030, ("chapelco ski",), SMA),
    Locality("Lago Meliquina", "Neuquén", "chapelco", -40.3830, -71.2670, ("meliquina", "villa meliquina"),
             MELIQUINA),
    Locality("Lago Hermoso", "Neuquén", "chapelco", -40.3700, -71.5200, (), SIETE_LAGOS),
    Locality("Lago Falkner", "Neuquén", "chapelco", -40.4330, -71.5370, ("falkner",), SIETE_LAGOS),
    Locality("Junín de los Andes", "Neuquén", "chapelco", -39.9510, -71.0690, ("junin de los andes",), JUNIN),
    Locality("Huechulafquen", "Neuquén", "chapelco", -39.7700, -71.3600, ("lago huechulafquen",), JUNIN),
    Locality("Las Coloradas", "Neuquén", "chapelco", -39.5560, -70.5940, (), JUNIN),
    Locality("Piedra del Águila", "Neuquén", "chapelco", -40.0480, -70.0740, ("piedra del aguila",)),
    Locality("Aluminé", "Neuquén", "chapelco", -39.2370, -70.9200, ("alumine",), ALUMINE),
    # --- Esquel (EQS)
    Locality("Esquel", "Chubut", "esquel", -42.9110, -71.3190, (), ESQ),
    Locality("Nahuel Pan", "Chubut", "esquel", -42.9700, -71.1700, (), ESQ),
    Locality("Trevelin", "Chubut", "esquel", -43.0850, -71.4640, (), TREVELIN),
    Locality("Aldea Escolar", "Chubut", "esquel", -43.1200, -71.5500, (), TREVELIN),
    Locality("Los Cipreses", "Chubut", "esquel", -43.1900, -71.6500, (), TREVELIN),
    Locality("Lago Rosario", "Chubut", "esquel", -43.2500, -71.3500, (), TREVELIN),
    Locality("Villa Futalaufquen", "Chubut", "esquel", -42.8230, -71.6490, ("futalaufquen",), ALERCES),
    Locality("Lago Rivadavia", "Chubut", "esquel", -42.5900, -71.6600, (), ALERCES),
    Locality("Cholila", "Chubut", "esquel", -42.5110, -71.4500, (), CHOLILA),
    Locality("Epuyén", "Chubut", "esquel", -42.2300, -71.3700, ("epuyen",), COMARCA),
    Locality("El Hoyo", "Chubut", "esquel", -42.0700, -71.5200, (), COMARCA),
    Locality("Lago Puelo", "Chubut", "esquel", -42.0700, -71.6000, ("puelo",), COMARCA),
    Locality("El Maitén", "Chubut", "esquel", -42.0510, -71.1670, ("el maiten",), COMARCA),
    Locality("Corcovado", "Chubut", "esquel", -43.5370, -71.4650, (), CORCOVADO),
    Locality("Carrenleufú", "Chubut", "esquel", -43.5860, -71.7000, ("carrenleufu",), CORCOVADO),
    Locality("Gualjaina", "Chubut", "esquel", -42.7250, -70.5400, (), MESETA_CH),
    Locality("Tecka", "Chubut", "esquel", -43.4940, -70.8140, (), MESETA_CH),
]


def zones() -> dict[str, list[str]]:
    """Zona → localidades, en el orden del gazetteer."""
    out: dict[str, list[str]] = {}
    for loc in LOCALITIES:
        out.setdefault(loc.zone or loc.name, []).append(loc.name)
    return out

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
