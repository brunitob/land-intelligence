from __future__ import annotations

import pytest

from patagonia_land.adapters.generic import extract_listing
from patagonia_land.crawling.page import Page
from patagonia_land.extraction.schemas import GeoPrecision, WaterClass
from patagonia_land.intelligence.normalization import (
    detect_property_type,
    parse_area,
    parse_number,
    parse_price,
)
from patagonia_land.intelligence.water_classifier import classify_water_text
from tests.fixtures.sites import A_ITEMS, B_ITEMS, C_ITEMS, a_detail, b_detail, c_detail


# ------------------------------------------------------------------ normalización
@pytest.mark.parametrize("raw,expected", [
    ("1.200.000", 1_200_000), ("380.000", 380_000), ("1,5", 1.5), ("1.234,56", 1234.56),
    ("380,000", 380_000), ("2.5", 2.5), ("4,5", 4.5), ("12", 12)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("text,amount,currency", [
    ("USD 85.000", 85_000, "USD"), ("U$S 420.000", 420_000, "USD"), ("u$s 1.200.000", 1_200_000, "USD"),
    ("$ 45.000.000", 45_000_000, "ARS"), ("380.000 dólares", 380_000, "USD"), ("USD 1,2 millones", 1_200_000, "USD")])
def test_parse_price(text, amount, currency):
    r = parse_price(text)
    assert r and r.amount == amount and r.currency == currency


def test_price_on_request_is_not_invented():
    r = parse_price("Consultar")
    assert r and r.amount is None and r.on_request


@pytest.mark.parametrize("text,m2,unit", [
    ("1.200 m²", 1200, "m2"), ("4,5 ha", 45_000, "ha"), ("120 hectáreas", 1_200_000, "ha"),
    ("2 has", 20_000, "ha"), ("2.500 m2", 2500, "m2"), ("850 hectáreas", 8_500_000, "ha")])
def test_parse_area_converts_ha(text, m2, unit):
    r = parse_area(text)
    assert r and r.m2 == m2 and r.unit == unit


def test_property_type_title_wins():
    assert detect_property_type("Chacra en Colonia Suiza", "terreno")[0].value == "chacra"
    assert detect_property_type("Fracción de 12 ha en Lago Lolog")[0].value == "terreno"


# ------------------------------------------------------------------ agua
@pytest.mark.parametrize("text,cls", [
    ("Lote con costa propia sobre el lago Moreno", WaterClass.WATERFRONT_CLAIMED),
    ("Campo atravesado por un arroyo", WaterClass.WATERFRONT_CLAIMED),
    ("120 metros de costa sobre el lago Lolog", WaterClass.WATERFRONT_CLAIMED),
    ("Lote con acceso al lago Lácar por bajada común", WaterClass.WATERFRONT_POSSIBLE),
    ("Terreno a 300 metros del lago Gutiérrez", WaterClass.WATER_NEARBY),
    ("Lote con vista al lago Nahuel Huapi", WaterClass.WATER_VIEW_ONLY),
    ("Casa sin costa, a 10 cuadras del lago", WaterClass.WATER_NEARBY),
    ("Departamento céntrico con cochera", WaterClass.UNKNOWN),
])
def test_water_classes(text, cls):
    assert classify_water_text(text).water_class == cls


def test_water_view_is_not_waterfront():
    w = classify_water_text("Hermosa vista al lago")
    assert w.waterfront_claimed is None and w.water_class == WaterClass.WATER_VIEW_ONLY


def test_nearby_distance_parsed():
    w = classify_water_text("Terreno a 300 metros del lago Gutiérrez")
    assert w.distance_m_mentioned == 300 and w.water_type == "lake"


# ------------------------------------------------------------------ fichas completas
async def test_site_a_jsonld_extraction():
    it = A_ITEMS[1]
    page = Page(f"https://inmoa.test/propiedad/{it.id}-colonia-suiza", a_detail(it), "https://inmoa.test")
    e = await extract_listing("inmoa", page, use_llm=False)
    assert e.title == it.title
    assert e.price == 420_000 and e.currency == "USD"
    assert e.area_m2 == 45_000 and e.area_original_unit == "ha"
    assert e.location.locality == "Colonia Suiza"
    assert e.location.precision == GeoPrecision.EXACT
    assert e.external_listing_id == "A-102"
    assert e.property_type.value == "chacra"
    assert e.water.water_class == WaterClass.WATERFRONT_CLAIMED
    assert e.provenance["price"].method == "json_ld"
    assert len(e.photos) >= 3
    assert e.canonical_url == "https://inmoa.test/propiedad/102-colonia-suiza"


async def test_site_b_table_and_map_extraction():
    it = B_ITEMS[0]
    page = Page("https://inmob.test/ficha.php?id=1", b_detail(it), "https://inmob.test")
    e = await extract_listing("inmob", page, use_llm=False)
    assert e.price == 95_000 and e.currency == "USD"
    assert e.area_m2 == 20_000
    assert e.location.locality == "Trevelin" and e.location.province == "Chubut"
    assert (e.location.latitude, e.location.longitude) == (-43.0901, -71.4702)
    assert e.location.precision == GeoPrecision.EXACT
    assert e.external_listing_id == "B0001"
    assert e.water.water_class == WaterClass.WATER_NEARBY
    assert any("b1_1.jpg" in p for p in e.photos)


async def test_site_b_no_coords_uses_locality_centroid_with_uncertainty():
    it = B_ITEMS[1]
    page = Page("https://inmob.test/ficha.php?id=2", b_detail(it), "https://inmob.test")
    e = await extract_listing("inmob", page, use_llm=False)
    assert e.location.precision == GeoPrecision.LOCALITY
    assert e.provenance["latitude"].method == "gazetteer" and e.provenance["latitude"].confidence <= 0.3
    assert e.area_m2 == 8_500_000 and e.price == 1_200_000


async def test_site_c_price_on_request_is_null():
    it = C_ITEMS[0]
    page = Page("https://inmoc.test/inmueble/11/x", c_detail(it), "https://inmoc.test")
    e = await extract_listing("inmoc", page, use_llm=False)
    assert e.price is None and e.currency is None and e.price_on_request
    assert e.area_m2 == 1850
    assert e.location.locality == "San Martín de los Andes"
    assert e.water.water_class == WaterClass.WATERFRONT_POSSIBLE
    assert not any("logo" in p for p in e.photos)


async def test_site_c_ars_price_and_waterfront():
    e = await extract_listing("inmoc", Page("https://inmoc.test/inmueble/12/x", c_detail(C_ITEMS[1]),
                                            "https://inmoc.test"), use_llm=False)
    assert e.price == 45_000_000 and e.currency == "ARS"
    e = await extract_listing("inmoc", Page("https://inmoc.test/inmueble/13/x", c_detail(C_ITEMS[2]),
                                            "https://inmoc.test"), use_llm=False)
    assert e.area_m2 == 120_000 and e.water.water_class == WaterClass.WATERFRONT_CLAIMED
    assert e.location.locality == "Lago Lolog"


async def test_missing_fields_stay_null():
    html = "<html><head><title>Lote</title></head><body><h1>Lote en Esquel</h1><p>Hermoso lote, consulte.</p></body></html>"
    e = await extract_listing("x", Page("https://x.test/lote/99", html, "https://x.test"), use_llm=False)
    assert e.price is None and e.area_m2 is None and e.location.latitude is not None  # centroide
    assert e.location.precision == GeoPrecision.LOCALITY
    assert e.confidence < 0.7


async def test_implausible_coordinates_discarded():
    html = ('<html><body><h1>Lote en Esquel USD 50.000</h1><div data-lat="-34.6" data-lng="-58.4"></div>'
            '<p>Superficie: 1000 m2</p></body></html>')
    e = await extract_listing("x", Page("https://x.test/lote/1", html, "https://x.test"), use_llm=False)
    assert e.location.precision == GeoPrecision.LOCALITY
    assert any("fuera de la zona" in w for w in e.warnings)


# ------------------------------------------------------------------ regresiones vistas en sitios reales
REAL_PATTERN = """<html><head><title>De la montaña</title><meta name="description" content="Inmobiliaria en Esquel, Chubut">
</head><body><header><a href="https://www.google.com/maps/place/Oficina/@-42.9157974,-71.3202441,17z">Oficina</a></header>
<h1 class="title">Listado de propiedades</h1>
<div class="header-property-detail"><div class="content-top"><h3 class="title">Terreno en Venta</h3><h3>U$D 40.000</h3></div></div>
<h5>Descripción</h5><div class="descripcion"><p>¡Hermoso terreno en esquina! Loteo con servicios aprobados. Red de gas instalada.
645m2. A 50 metros del río, vistas que te van a enamorar. Ubicado a minutos de la plaza.</p></div>
<ul><li><div class="content"><span class="label">ID:</span><span>92</span></div></li>
<li><div class="content"><span class="label">Tipo:</span><span>Terreno</span></div></li>
<li><div class="content"><span class="label">Operación:</span><span>Venta</span></div></li>
<li><div class="content"><span class="label">Superficie:</span><span>645 m²</span></div></li></ul>
<li><span class="label fw-6">Dirección</span><div class="text">Trevelin</div></li>
<iframe src="https://www.google.com/maps?q=Trevelin&t=m&z=14&output=embed"></iframe>
<footer><a href="https://www.google.com/maps/place/Oficina/@-42.9157974,-71.3202441,17z/data=!3d-42.9157974!4d-71.3202441">Mapa</a></footer>
</body></html>"""


async def test_real_site_patterns_generic_h1_office_map_and_label_spans():
    e = await extract_listing("x", Page("https://x.test/propiedad.php?id=92", REAL_PATTERN, "https://x.test"),
                              use_llm=False)
    assert e.title == "Terreno en Venta"
    assert e.property_type.value == "terreno" and e.operation == "venta"
    assert e.price == 40_000 and e.currency == "USD" and e.area_m2 == 645
    assert e.location.locality == "Trevelin"
    assert e.location.precision == GeoPrecision.LOCALITY  # nunca la oficina como coordenada exacta
    assert e.water.water_class == WaterClass.WATER_NEARBY and e.water.distance_m_mentioned == 50
    assert "Inmobiliaria en Esquel" not in (e.description or "")


async def test_rental_detected_from_label_and_monthly_price():
    html = REAL_PATTERN.replace("<span>Venta</span>", "<span>Alquiler Permanente</span>")
    e = await extract_listing("x", Page("https://x.test/propiedad.php?id=1", html, "https://x.test"), use_llm=False)
    assert e.operation == "alquiler"


async def test_shared_coordinates_are_demoted():
    from patagonia_land.extraction.validation import demote_shared_coordinates

    html = A_ITEMS[0]
    items = []
    for it in A_ITEMS[:4]:
        same = type(it)(**{**it.__dict__, "lat": -42.9157, "lon": -71.3202})
        items.append(await extract_listing("a", Page(f"https://inmoa.test/propiedad/{it.id}-x", a_detail(same),
                                                     "https://inmoa.test"), use_llm=False))
    assert demote_shared_coordinates(items) == 4
    assert all(e.location.precision in (GeoPrecision.LOCALITY, GeoPrecision.UNKNOWN) for e in items)
    del html


def test_locality_prefers_source_region():
    from patagonia_land.geo.localities import find_locality

    assert find_locality("Los Coihues Ruta 40, Esquel", region="esquel")[0].name == "Esquel"
    assert find_locality("Villa Los Coihues", region="bariloche")[0].name == "Villa Los Coihues"
    # nombre completo de otra región sí se acepta
    assert find_locality("Lote en Villa La Angostura", region="esquel")[0].name == "Villa La Angostura"
