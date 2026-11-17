"""Franja horaria de robots.txt (Visit-time): diferir el job y acotar el presupuesto a la franja."""

from datetime import UTC, datetime

from patagonia_land.crawling.robots import Robots

AMPRO = """User-agent: *
Disallow:
Crawl-delay: 60
Visit-time: 0300-1200
Request-rate: 6/60m
Request-rate: 3/60m 1200-0300
"""


def test_next_visit_start_outside_window():
    rp = Robots(AMPRO)
    now = datetime(2026, 11, 17, 16, 20, tzinfo=UTC)
    assert not rp.visit_allowed_now("bot", now)
    assert rp.next_visit_start("bot", now) == datetime(2026, 11, 18, 3, 0, tzinfo=UTC)
    early = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)
    assert rp.next_visit_start("bot", early) == datetime(2026, 11, 17, 3, 0, tzinfo=UTC)


def test_inside_window_rate_and_time_left():
    rp = Robots(AMPRO)
    now = datetime(2026, 11, 17, 4, 0, tzinfo=UTC)
    assert rp.next_visit_start("bot", now) is None
    assert rp.visit_seconds_left("bot", now) == 8 * 3600
    assert rp.min_interval("bot", now) == 600  # 6/60m dentro de la franja (no el 3/60m de la tarde)


def test_no_visit_time():
    rp = Robots("User-agent: *\nCrawl-delay: 5\n")
    assert rp.next_visit_start("bot") is None
    assert rp.visit_seconds_left("bot") is None


async def test_budget_goes_to_new_then_oldest_known_details(fetcher_factory, site_state):
    from patagonia_land.crawling.discovery import SourceConfig, discover_properties

    base, starts = "https://inmoa.test", ["https://inmoa.test/propiedades"]
    async with fetcher_factory() as f:
        full = await discover_properties(f, SourceConfig("inmoa", base, starts, max_pages_per_run=60))
    urls = sorted(full.details)
    new, old, recent = urls[:2], urls[2:4], urls[4:]
    known = {u: 1000.0 for u in old} | {u: 2_000_000_000.0 for u in recent}
    budget = full.pages_visited - len(recent)  # alcanza para listados + nuevas + las 2 más viejas
    async with fetcher_factory() as f:
        res = await discover_properties(f, SourceConfig("inmoa", base, starts, max_pages_per_run=budget,
                                                        known_details=known))
    assert set(res.details) == set(new) | set(old)
