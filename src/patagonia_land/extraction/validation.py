"""Construye y valida el ExtractedListing a partir del Draft. Valores implausibles → null + warning."""

from __future__ import annotations

from urllib.parse import urlsplit

from patagonia_land.crawling.page import Page
from patagonia_land.extraction.draft import Draft
from patagonia_land.extraction.schemas import (
    LAND_TYPES,
    ExtractedListing,
    Features,
    GeoPrecision,
    Location,
    PropertyType,
    Provenance,
    WaterClass,
    WaterInfo,
)
from patagonia_land.geo.localities import (
    distance_km,
    find_locality,
    find_province,
    in_bbox,
    nearest_locality,
)
from patagonia_land.intelligence.water_classifier import classify_water_text

SERVICE_WORDS = {"luz": "electricidad", "electricidad": "electricidad", "energia electrica": "electricidad",
                 "gas natural": "gas", "gas": "gas", "agua de red": "agua", "agua corriente": "agua",
                 "agua potable": "agua", "cloacas": "cloacas", "internet": "internet", "fibra optica": "internet"}

KEY_FIELDS = ("title", "price", "area_m2", "property_type", "location", "description")


def _services(text: str) -> list[str]:
    from patagonia_land.intelligence.normalization import strip_accents

    t = strip_accents(text.lower())
    found = []
    for k, v in SERVICE_WORDS.items():
        if k in t and v not in found:
            found.append(v)
    return found


def build_listing(source_id: str, page: Page, d: Draft, region: str | None = None) -> ExtractedListing:
    warnings = list(d.warnings)

    # --- Precio
    price = d.get("price")
    currency = d.get("currency")
    if price is not None:
        price = float(price)
        if currency not in ("USD", "ARS"):
            warnings.append(f"moneda no reconocida '{currency}': se deja null")
            currency = None
        if price <= 0 or (currency == "USD" and not 500 <= price <= 100_000_000):
            warnings.append(f"precio implausible {price} {currency}: descartado")
            price, currency = None, None
            d.provenance.pop("price", None)

    # --- Superficie
    area = d.get("area_m2")
    if area is not None:
        area = float(area)
        if not 20 <= area <= 500_000_000:  # 50.000 ha como techo
            warnings.append(f"superficie implausible {area} m²: descartada")
            area = None
            d.provenance.pop("area_m2", None)

    # --- Ubicación: coordenadas publicadas > gazetteer de localidad (aproximado)
    lat, lon = d.get("latitude"), d.get("longitude")
    precision = GeoPrecision(d.get("geo_precision") or "unknown") if lat is not None else GeoPrecision.UNKNOWN
    if lat is not None and not in_bbox(lat, lon):
        warnings.append(f"coordenadas fuera de la zona ({lat},{lon}): descartadas")
        lat = lon = None
        precision = GeoPrecision.UNKNOWN
        d.provenance.pop("latitude", None)
        d.provenance.pop("longitude", None)
    title = d.get("title") or page.title
    loc_text = d.get("location_text")
    # Último recurso: el slug de la URL ("/p/123-Casa-en-Venta-en-San-Carlos-de-Bariloche").
    slug = urlsplit(page.url).path.rstrip("/").rsplit("/", 1)[-1]
    loc, loc_ev = find_locality(d.get("locality"), loc_text, d.get("locality_hint"), title, d.get("description"),
                                slug, region=region)
    if loc and lat is not None and not d.has("locality"):
        # La localidad sale del texto ("a 10 min de Dina Huapi", "calle Moreno"): si contradice las coordenadas
        # publicadas por la ficha, mandan las coordenadas.
        km = distance_km(lat, lon, loc)
        if km > 10:
            near = nearest_locality(lat, lon, max_km=12, region=region)
            warnings.append(f"localidad del texto ({loc.name}) a {km:.0f} km de las coordenadas: "
                            + (f"se usa {near[0].name}" if near else "se descarta"))
            loc, loc_ev = None, None
    locality = loc.name if loc else d.get("locality")
    province = find_province(d.get("province"), loc_text) or (loc.province if loc else d.get("province"))
    if loc and not d.has("locality"):
        d.offer("locality", loc.name, "gazetteer", loc_ev, 0.7)
    if not loc and not d.has("locality") and lat is not None:
        # Barrio/paraje fuera del gazetteer (p.ej. "Melipal") pero con coordenadas publicadas: localidad más cercana.
        near = nearest_locality(lat, lon, max_km=12, region=region)
        if near:
            near_loc, km = near
            locality = near_loc.name
            province = province or near_loc.province
            d.offer("locality", near_loc.name, "gazetteer_nearest",
                    f"coordenadas a {km:.1f} km del centro de {near_loc.name}", 0.5)
    if lat is None and loc:
        # Centroide de localidad: SOLO para mapa/filtros con incertidumbre; nunca como ubicación exacta.
        lat, lon, precision = loc.lat, loc.lon, GeoPrecision.LOCALITY
        d.offer("latitude", lat, "gazetteer", f"centroide de {loc.name}", 0.3, override=True)
        d.offer("longitude", lon, "gazetteer", f"centroide de {loc.name}", 0.3, override=True)

    # --- Agua: texto de la ficha (+ pista del LLM si los regex no encontraron nada)
    water = classify_water_text(title, d.get("description"))
    llm_w = d.get("llm_water")
    if water.water_class == WaterClass.UNKNOWN and llm_w:
        mapping = {"costa_propia": WaterClass.WATERFRONT_CLAIMED, "acceso": WaterClass.WATERFRONT_POSSIBLE,
                   "vista": WaterClass.WATER_VIEW_ONLY, "cercania": WaterClass.WATER_NEARBY}
        water = WaterInfo(water_class=mapping[llm_w["relation"]], water_name=llm_w.get("name"),
                          waterfront_claimed=True if llm_w["relation"] == "costa_propia" else None,
                          evidence=d.provenance["llm_water"].evidence, confidence=0.6)
    if water.water_class != WaterClass.UNKNOWN:
        d.provenance.setdefault("water", Provenance(method="llm" if llm_w and water.confidence == 0.6 else "regex",
                                                    evidence=water.evidence, confidence=water.confidence))

    # --- Tipo
    ptype = d.get("property_type")
    try:
        ptype = PropertyType(ptype) if ptype else None
    except ValueError:
        ptype = PropertyType.OTRO

    desc = d.get("description")
    full_text = " ".join(x for x in (title, desc) if x)
    services = _services(full_text)
    feats = Features(
        services=services,
        electricity=True if "electricidad" in services else None,
        gas=True if "gas" in services else None,
        water_supply=True if "agua" in services else None,
    )

    generic_title = any(w.startswith("título genérico") for w in warnings)
    present = sum(1 for f in KEY_FIELDS if (f == "location" and locality) or d.has(f))
    field_conf = [p.confidence for k, p in d.provenance.items() if k in ("price", "area_m2", "title", "property_type")]
    confidence = round((present / len(KEY_FIELDS)) * 0.5 + (sum(field_conf) / len(field_conf) if field_conf else 0) * 0.5, 2)
    if generic_title:
        confidence = round(confidence * 0.8, 2)
    if d.get("operation") == "alquiler":
        warnings.append("operación: alquiler")
    if ptype and ptype not in LAND_TYPES:
        warnings.append(f"tipo '{ptype.value}' no es terreno/lote/chacra/campo (se guarda igual)")

    return ExtractedListing(
        source_id=source_id,
        url=page.url,
        canonical_url=page.canonical_url,
        external_listing_id=str(d.get("external_listing_id"))[:120] if d.get("external_listing_id") else None,
        title=title,
        status_text=d.get("status_text"),
        property_type=ptype,
        operation=d.get("operation"),
        price=price,
        currency=currency,
        price_raw=d.get("price_raw"),
        price_on_request=bool(d.get("price_on_request")) and price is None,
        published_at=d.get("published_at"),
        updated_at=d.get("updated_at"),
        area_m2=area,
        area_raw=d.get("area_raw"),
        area_original_unit=d.get("area_original_unit"),
        built_area_m2=d.get("built_area_m2"),
        location=Location(province=province, locality=locality, address=d.get("address") or loc_text,
                          latitude=lat, longitude=lon, precision=precision),
        features=feats,
        water=water,
        description=desc,
        photos=d.get("photos") or [],
        documents=d.get("documents") or [],
        provenance=d.provenance,
        warnings=warnings,
        confidence=confidence,
        extraction_methods=d.methods,
    )


def demote_shared_coordinates(listings: list[ExtractedListing], min_repeats: int = 3) -> int:
    """Coordenadas idénticas en varias fichas de una fuente = ubicación de la oficina/mapa genérico.

    Se descartan y se usa la localidad (precisión 'locality'). Devuelve cuántas fichas se corrigieron.
    """
    from collections import Counter

    published = (GeoPrecision.EXACT, GeoPrecision.APPROXIMATE)
    keys = Counter((round(e.location.latitude, 5), round(e.location.longitude, 5)) for e in listings
                   if e.location.precision in published and e.location.latitude is not None)
    shared = {k for k, n in keys.items() if n >= min_repeats}
    fixed = 0
    for e in listings:
        if e.location.precision not in published or e.location.latitude is None:
            continue
        if (round(e.location.latitude, 5), round(e.location.longitude, 5)) not in shared:
            continue
        loc, _ = find_locality(e.location.address, e.location.locality, e.title, e.description)
        e.warnings.append(f"coordenadas compartidas por {keys[(round(e.location.latitude, 5), round(e.location.longitude, 5))]} "
                          "fichas (probable oficina): descartadas")
        if loc:
            e.location.latitude, e.location.longitude = loc.lat, loc.lon
            e.location.precision = GeoPrecision.LOCALITY
            e.provenance["latitude"] = Provenance(method="gazetteer", evidence=f"centroide de {loc.name}", confidence=0.3)
            e.provenance["longitude"] = e.provenance["latitude"]
        else:
            e.location.latitude = e.location.longitude = None
            e.location.precision = GeoPrecision.UNKNOWN
            e.provenance.pop("latitude", None)
            e.provenance.pop("longitude", None)
        fixed += 1
    return fixed
