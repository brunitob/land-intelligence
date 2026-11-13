"""Regresiones de la auditoría de los primeros crawls de fuentes descubiertas: 429, soft 404, taxonomías,
<header> sin cerrar y localidad desde slug/abreviatura."""

from __future__ import annotations

import httpx
import pytest

from patagonia_land.adapters.generic import extract_listing
from patagonia_land.crawling.classifier import PageType, classify_page, classify_url_only, is_taxonomy_url
from patagonia_land.crawling.fetcher import Fetcher, RateLimited
from patagonia_land.crawling.page import Page
from patagonia_land.geo.localities import find_locality
from tests.conftest import test_settings as make_settings


async def test_persistent_429_slows_host_and_stops(monkeypatch):
    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr("patagonia_land.crawling.fetcher.asyncio.sleep", no_sleep)
    hits = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(429, headers={"retry-after": "0"})

    async with Fetcher(settings=make_settings(), allow_private=True, transport=httpx.MockTransport(handler)) as f:
        with pytest.raises(RateLimited):
            await f.get("https://inmo.test/propiedades", retries=2)
        assert f.crawl_delay("https://inmo.test/x") >= 5  # el host queda frenado para el resto de la corrida
    assert hits.count("/propiedades") == 3


def test_soft_404_is_never_a_detail():
    html = """<html><head><title>Los Cerros Propiedades</title></head><body><h1>Propiedad no encontrada</h1>
    <p>La propiedad que busca no existe. Vea otras: Terreno USD 50.000, 1200 m2</p></body></html>"""
    page = Page("https://inmo.test/propiedades/7966143", html, "https://inmo.test/")
    assert classify_page(page).page_type == PageType.OTHER


def test_taxonomy_urls_are_categories():
    assert is_taxonomy_url("https://inmo.test/archivos/property_location/chapelco-golf")
    assert is_taxonomy_url("https://inmo.test/tipo-propiedad/lote/")
    assert not is_taxonomy_url("https://inmo.test/propiedad/lote-en-dina-huapi")
    assert not is_taxonomy_url("https://inmo.test/categoria")  # el último segmento no cuenta
    assert classify_url_only("https://inmo.test/archivos/property_location/kaleuche").page_type == PageType.CATEGORY
    html = """<html><body><h1>Property Location: Kaleuche</h1><div class="item"><a href="/p/1">Lote</a>
    <p>USD 80.000 · 1200 m2</p></div><p>""" + "texto " * 150 + "</p></body></html>"
    page = Page("https://inmo.test/archivos/property_location/kaleuche", html, "https://inmo.test/")
    assert classify_page(page).page_type != PageType.PROPERTY_DETAIL


async def test_unclosed_header_keeps_content():
    # Tema "Pixel Inmobiliario": un <header> sin cerrar envuelve toda la ficha.
    html = """<html><body><header><nav><a href="/">Inicio</a><a href="/venta">Venta</a></nav>
    <h1>Lote en Arelauquen</h1><div>En Venta USD80.000 Lote. Código: 116371</div>
    <div>Arelauquen Ruta 82 Lago Gutierrez, San Carlos De Bariloche, Rio Negro</div>
    <button type="button"><p><i class="fa"></i></p> M² Totales <span class="number">2683</span></button>
    <button type="button"><p><i class="fa"></i></p> M² Cubiertos <span class="number">264</span></button><p>""" + "Hermoso lote con vista. " * 30 + """</p>
    <footer>Rolando 287, Bariloche</footer></body></html>"""
    page = Page("https://inmo.test/ad/lote-en-arelauquen", html, "https://inmo.test/")
    assert "USD80.000" in page.main_text
    lst = await extract_listing("t", page, {}, use_llm=False, region="bariloche")
    assert (lst.price, lst.currency, lst.area_m2) == (80_000, "USD", 2683)


async def test_locality_from_url_slug_as_last_resort():
    html = "<html><body><h1>Casa B° 150 viviendas</h1><p>Precio: USD 95.000</p></body></html>"
    page = Page("https://inmo.test/p/6934831-Casa-en-Venta-en-San-Carlos-de-Bariloche", html, "https://inmo.test/")
    lst = await extract_listing("t", page, {}, use_llm=False, region="bariloche")
    assert lst.location.locality == "San Carlos de Bariloche"


def test_locality_abbreviations_and_new_entries():
    assert find_locality("Excelente casa en el centro de S.M.Andes", region="chapelco")[0].name == \
        "San Martín de los Andes"
    assert find_locality("Chacra en Mallín Ahogado", region="bariloche")[0].name == "Mallín Ahogado"
    loc, _ = find_locality("Moreno 450, Centro", region="bariloche")
    assert loc is None
