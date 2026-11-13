from __future__ import annotations

import pytest

from patagonia_land.crawling.classifier import PageType, classify_page
from patagonia_land.crawling.discovery import SourceConfig, discover_properties
from patagonia_land.crawling.fetcher import SSRFError, assert_public_url
from patagonia_land.crawling.inspector import inspect_site
from patagonia_land.crawling.page import Page
from patagonia_land.crawling.urls import canonicalize
from tests.fixtures.sites import A_ITEMS, B_ITEMS, C_ITEMS, a_detail, a_list

SITES = [
    ("inmoa", "https://inmoa.test", ["https://inmoa.test/propiedades"], len(A_ITEMS)),
    ("inmob", "https://inmob.test", [], len(B_ITEMS)),
    ("inmoc", "https://inmoc.test", ["https://inmoc.test/venta"], len(C_ITEMS)),
]


@pytest.mark.parametrize("sid,base,starts,expected", SITES)
async def test_discovers_all_details_across_pagination(fetcher_factory, site_state, sid, base, starts, expected):
    async with fetcher_factory() as f:
        res = await discover_properties(f, SourceConfig(sid, base, starts, max_pages_per_run=60))
    assert len(res.details) == expected, sorted(res.details)
    assert not res.blocked
    # Nunca se piden páginas institucionales como fichas
    assert all("contacto" not in u for u in res.details)


async def test_robots_disallow_is_respected(fetcher_factory, site_state):
    async with fetcher_factory() as f:
        assert not await f.allowed("https://inmoc.test/admin/x")
        assert await f.allowed("https://inmoc.test/venta")


@pytest.mark.parametrize("sid,base,starts,expected", SITES)
async def test_inspector_builds_profile(fetcher_factory, sid, base, starts, expected):
    async with fetcher_factory() as f:
        rep = await inspect_site(f, sid, base, starts)
    p = rep.profile
    assert p["rendering"] == "static"
    assert p["pagination"]["type"] != "none"
    assert p["listing_patterns"], p
    assert p["confidence"] >= 0.6
    assert rep.sample_detail_urls


def test_inspector_detects_pagination_kinds():
    # el tipo de paginación difiere por sitio
    from patagonia_land.crawling.pagination import detect_pagination

    pa = detect_pagination(Page("https://inmoa.test/propiedades", a_list(1), "https://inmoa.test"))
    assert pa == {"type": "query_parameter", "parameter": "page"}


def test_classifier_detail_vs_list():
    detail = Page("https://inmoa.test/propiedad/101-dina-huapi", a_detail(A_ITEMS[0]), "https://inmoa.test")
    lst = Page("https://inmoa.test/propiedades", a_list(1), "https://inmoa.test")
    assert classify_page(detail).page_type == PageType.PROPERTY_DETAIL
    assert classify_page(lst).page_type in (PageType.PROPERTY_LIST, PageType.CATEGORY)


def test_canonicalize_strips_tracking_and_fragments():
    assert canonicalize("https://X.com/a/?utm_source=f&page=2#top") == "https://x.com/a?page=2"
    assert canonicalize("mailto:a@b.c") is None
    assert canonicalize("/foto.jpg", "https://x.com") is None


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1/", "http://169.254.169.254/latest",
                                 "http://10.0.0.1/", "file:///etc/passwd"])
def test_ssrf_blocked(url):
    with pytest.raises(SSRFError):
        assert_public_url(url)
