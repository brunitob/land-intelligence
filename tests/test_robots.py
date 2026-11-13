from datetime import UTC, datetime

from patagonia_land.crawling.robots import Robots

UA = "PatagoniaLandBot/0.1"

BRIM_LIKE = """User-agent: *
Disallow:
Crawl-delay: 60
Visit-time: 0300-1200
Request-rate: 6/60m
Request-rate: 3/60m 1200-0300
Disallow: /admin/
Disallow: /*?
Disallow: /*trackback

User-agent: Googlebot
Allow: /*.js$
Disallow: /wp-admin/
"""


def test_wildcards_and_query_disallow():
    r = Robots(BRIM_LIKE)
    assert r.can_fetch(UA, "https://x.com/")
    assert r.can_fetch(UA, "https://x.com/propiedad/123")
    assert not r.can_fetch(UA, "https://x.com/portal/api.php?action=get_public_properties")
    assert not r.can_fetch(UA, "https://x.com/foo/trackback")
    assert not r.can_fetch(UA, "https://x.com/admin/x")
    assert r.can_fetch(UA, "https://x.com/wp-admin/")  # esa regla es del grupo Googlebot


def test_request_rate_and_visit_time():
    r = Robots(BRIM_LIKE)
    inside = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    outside = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    assert r.min_interval(UA, inside) == 600  # 6 por hora
    assert r.min_interval(UA, outside) == 1200  # 3 por hora fuera de la franja
    assert r.visit_allowed_now(UA, inside) and not r.visit_allowed_now(UA, outside)


def test_specific_group_and_allow_precedence():
    r = Robots("User-agent: *\nDisallow: /\n\nUser-agent: patagonialandbot\nDisallow: /privado\nAllow: /privado/publico$\n")
    assert r.can_fetch(UA, "https://x.com/terrenos")
    assert not r.can_fetch(UA, "https://x.com/privado/x")
    assert r.can_fetch(UA, "https://x.com/privado/publico")
    assert not r.can_fetch(UA, "https://x.com/privado/publico/2")


def test_dollar_anchor():
    r = Robots("User-agent: *\nDisallow: /*.pdf$\n")
    assert not r.can_fetch(UA, "https://x.com/a/plano.pdf")
    assert r.can_fetch(UA, "https://x.com/a/plano.pdf?v=1")
