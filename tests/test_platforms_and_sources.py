"""Regresiones de la ronda de fuentes descubiertas vía InterPatagonia: Tokko, precios, localidad vs coordenadas,
directorio de agencias y resolución de dominios. HTML sintético que imita los patrones reales."""

from __future__ import annotations

import pytest

from patagonia_land.adapters.generic import extract_listing
from patagonia_land.crawling.classifier import PageType, classify_page
from patagonia_land.crawling.page import Page
from patagonia_land.crawling.platforms import detect_platform, platform_hints
from patagonia_land.extraction.schemas import GeoPrecision
from patagonia_land.intelligence.normalization import parse_price
from patagonia_land.source_discovery.interpatagonia import parse_directory
from patagonia_land.source_discovery.resolve import candidate_domains, phone_keys

TOKKO_HEAD = '<link href="https://static.tokkobroker.com/tfw/css/estilo.css" rel="stylesheet">'


def tokko_list(ids: list[int]) -> str:
    cards = "".join(f"""
    <a href="/p/{i}-Terreno-en-Venta-en-Melipal" prop-id="{i}"><div class="propiedad">
      <div class="prop_img"><img src="https://static.tokkobroker.com/pictures/{i}.jpg"></div>
      <div class="prop_data"><div class="prop_dir">Terreno en Melipal, Bariloche</div>
      <div class="prop_address prop_operation">VENTA USD{100 + i}.000</div>
      <div class="prop_datos"><div class="prop_dato">Terreno: 1200.0 m²</div></div></div>
    </div></a>""" for i in ids)
    return f"<html><head>{TOKKO_HEAD}</head><body><h1>Terrenos</h1><div id='propiedades'>{cards}</div></body></html>"


TOKKO_DETAIL = f"""<html><head>{TOKKO_HEAD}<title>Terreno en Venta en Melipal</title></head><body>
<h1>Terreno en Venta en Melipal - Melipal</h1>
<div class="prop_address">VENTA USD1 </div>
<div class="ficha_detalle_item"><b>Tipo de Propiedad</b><br/>Terreno</div>
<div class="ficha_detalle_item"><b>Ubicación</b><br/>Melipal</div>
<div class="ficha_detalle_item"><b>Terreno</b><br/>159 Ha</div>
<div id="prop-desc">&lt;p&gt;Hermoso campo con vista al lago. Escritura inmediata, acceso por ruta asfaltada y todos
los servicios disponibles en el frente del lote.&lt;/p&gt;&lt;p&gt;Desde U$ 7000 ha.&lt;/p&gt;</div>
<section id="ficha_mapa"><script>
  var map = L.map(document.getElementById("openstreetmap_box")).setView([-41.1270444, -71.3558147], 15);
  var circle = L.circle([-41.1270444, -71.3558147], 400, {{color: 'red'}}).addTo(map);
</script></section>
<footer>Oficina: Mitre 100, Bariloche. Tel 294 442-0000</footer></body></html>"""


def test_card_wrapped_in_anchor_is_detected():
    page = Page("https://inmo.test/Terrenos", tokko_list([1, 2, 3, 4]), "https://inmo.test/")
    g = page.property_card_group
    assert g and len(g.links) == 4 and all("/p/" in u for u in g.links)
    assert classify_page(page).page_type in (PageType.PROPERTY_LIST, PageType.CATEGORY)


def test_tokko_platform_hints():
    assert detect_platform(tokko_list([1])) == "tokko"
    h = platform_hints("tokko", "https://inmo.test")
    assert h["entry_urls"] == ["https://inmo.test/Venta"]
    assert h["pagination"]["parameter"] == "p" and h["detail_pattern_strict"]
    assert detect_platform("<html>wordpress</html>") is None


async def test_tokko_detail_circle_is_approximate_and_price_per_ha_is_not_total():
    page = Page("https://inmo.test/p/1-Terreno-en-Venta-en-Melipal", TOKKO_DETAIL, "https://inmo.test/")
    lst = await extract_listing("t", page, {"platform": "tokko"}, use_llm=False, region="bariloche")
    assert lst.location.precision == GeoPrecision.APPROXIMATE
    assert lst.location.latitude == pytest.approx(-41.1270444)
    assert "400 m" in lst.provenance["latitude"].evidence
    # "Melipal" no está en el gazetteer: localidad más cercana a las coordenadas, marcada como inferida.
    assert lst.location.locality == "San Carlos de Bariloche"
    assert lst.provenance["locality"].method == "gazetteer_nearest"
    # "USD1" es relleno y "U$ 7000 ha" es precio por hectárea: no hay precio total, y nunca ARS.
    assert lst.price is None and lst.currency != "ARS"
    assert lst.area_m2 == 1_590_000
    assert "<p>" not in (lst.description or "")


@pytest.mark.parametrize("text,amount,currency", [
    ("VENTA USD1 , Desde U$ 7000 ha.", None, None),
    ("USD 50 el m2, total USD 80.000", 80_000, "USD"),
    ("Precio U$S 3.000 x m2", None, None),
    ("U$ 95.000", 95_000, "USD"),
    ("$ 45.000.000", 45_000_000, "ARS"),
])
def test_price_dollar_sign_per_unit_and_placeholders(text, amount, currency):
    r = parse_price(text)
    assert (r.amount if r else None) == amount
    assert (r.currency if r else None) == currency


async def test_text_locality_contradicting_coordinates_is_overridden():
    html = """<html><body><h1>Terreno en Venta en Centro</h1><p>Precio: USD 120.000</p>
    <p>Lote de 350 m2 con accesos directos a la ruta de circunvalación, RN 40 Norte de acceso al aeropuerto y
    Dina Huapi, y zona noroeste de la ciudad. Ideal vivienda.</p>
    <iframe src="https://maps.google.com/maps?q=-41.1306,-71.3050&output=embed"></iframe></body></html>"""
    page = Page("https://inmo.test/propiedad/9", html, "https://inmo.test/")
    lst = await extract_listing("t", page, {}, use_llm=False, region="bariloche")
    assert lst.location.locality == "San Carlos de Bariloche"
    assert any("Dina Huapi" in w for w in lst.warnings)


def test_street_moreno_is_not_lago_moreno():
    from patagonia_land.geo.localities import find_locality

    loc, _ = find_locality("Moreno 450, Centro", region="bariloche")
    assert loc is None or loc.name != "Lago Moreno"


DIRECTORY = """<html><body>
<article class="tarj tarj-simple"><div class="tarj-cuerpo"><span class="tarj-rubro-txt">Inmobiliarias</span>
<h3>Lagos del Sur Propiedades</h3><p class="dir">Mitre 100</p><p class="tels">294-4420000  294-4630000</p>
<a class="btn btn-wa" href="https://wa.me/5492944111111?text=hola">WhatsApp</a></div></article>
<article class="tarj"><div class="tarj-cuerpo"><span class="tarj-rubro-txt">Escribanías</span><h3>Escribanía X</h3>
</div></article></body></html>"""


def test_interpatagonia_directory_parsing():
    rows = parse_directory(DIRECTORY, "bariloche")
    assert len(rows) == 1
    a = rows[0]
    assert (a.name, a.region, a.address, a.whatsapp) == ("Lagos del Sur Propiedades", "bariloche", "Mitre 100",
                                                       "5492944111111")
    assert phone_keys(a.phones, a.whatsapp) == {"4420000", "4630000", "4111111"}


def test_candidate_domains_from_name():
    c = candidate_domains("Andrea Pena Real Estate", "bariloche")
    assert "andreapenarealestate.com.ar" in c and "andreapena.com.ar" in c
    c = candidate_domains("BRC Homes Rental (alquileres)", "bariloche")
    assert all("alquileres" not in d for d in c)
